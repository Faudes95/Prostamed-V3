"""
prostanet.voice.llm_providers.anthropic_provider — Claude Sonnet wrapper.

Para modos 'cloud' (todo Claude) o 'hybrid' (solo SOAP final con Claude).

Env vars:
    ANTHROPIC_API_KEY=sk-ant-...
    ANTHROPIC_MODEL=claude-sonnet-4-20250514  (default)
    ANTHROPIC_MAX_RETRIES=3  (default)

Faubot LXXX #voice-1.5 — Claude para máxima calidad SOAP/extracción premium.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

from .factory import LLMProvider, LLMResponse, ToolCall


class AnthropicProvider:
    """LLM provider que usa Anthropic Claude (cloud, paga, máxima calidad)."""

    name = "anthropic"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        max_retries: int | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = model or os.environ.get(
            "ANTHROPIC_MODEL", "claude-sonnet-4-20250514"
        )
        self.max_retries = max_retries or int(
            os.environ.get("ANTHROPIC_MAX_RETRIES", "3")
        )
        self._client = None

    def _get_client(self):
        """Lazy import + init de anthropic client."""
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:
                raise ImportError(
                    "Paquete 'anthropic' no instalado. Instalar con: pip install anthropic"
                ) from exc
            if not self.api_key:
                raise ValueError(
                    "ANTHROPIC_API_KEY no configurada en env. "
                    "Necesaria para modo 'cloud' o 'hybrid' (SOAP)."
                )
            self._client = anthropic.Anthropic(
                api_key=self.api_key, max_retries=self.max_retries
            )
        return self._client

    def is_available(self) -> bool:
        """Verifica si API key configurada (no hace API call para no gastar)."""
        return bool(self.api_key) and self.api_key.startswith("sk-ant-")

    def chat(
        self,
        system_prompt: str,
        user_message: str,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        """Envía mensaje a Claude con tool_use opcional + prompt caching."""
        client = self._get_client()
        start = time.time()

        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},  # prompt caching
                }
            ],
            "messages": [{"role": "user", "content": user_message}],
        }
        if tools:
            kwargs["tools"] = tools

        try:
            response = client.messages.create(**kwargs)
        except Exception as exc:
            return LLMResponse(
                text=f"[Anthropic error: {exc}]",
                provider=self.name,
                model=self.model,
                latency_ms=int((time.time() - start) * 1000),
            )

        latency_ms = int((time.time() - start) * 1000)

        # Parse content blocks
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in response.content:
            if hasattr(block, "text"):
                text_parts.append(block.text)
            elif hasattr(block, "name") and hasattr(block, "input"):
                # tool_use block
                args = block.input if isinstance(block.input, dict) else {}
                tool_calls.append(
                    ToolCall(
                        name=block.name,
                        arguments=args,
                        confidence=float(args.get("confidence", 1.0)),
                        raw_text_evidence=str(args.get("evidence", "")),
                    )
                )

        return LLMResponse(
            text="\n".join(text_parts),
            tool_calls=tool_calls,
            raw_response=response.model_dump() if hasattr(response, "model_dump") else None,
            provider=self.name,
            model=self.model,
            latency_ms=latency_ms,
        )

    def extract_clinical_fields(
        self,
        transcript: str,
        field_specs: list[dict[str, Any]],
    ) -> LLMResponse:
        """Extracción de fields con tool_use (idéntico a OllamaProvider para portability)."""
        # Mismo schema que ollama_provider para que sean intercambiables
        tools = [
            {
                "name": "set_field",
                "description": (
                    "Establece el valor de UN campo clínico extraído del transcript. "
                    "Llamar UNA VEZ por cada campo detectado."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "field_name": {"type": "string"},
                        "value": {"type": ["string", "number", "boolean", "null"]},
                        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                        "evidence": {"type": "string"},
                    },
                    "required": ["field_name", "value", "confidence", "evidence"],
                },
            },
            {
                "name": "append_psa_history",
                "description": "Agrega medición PSA al historial longitudinal.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "date": {"type": "string", "description": "ISO YYYY-MM-DD"},
                        "value": {"type": "number"},
                        "unit": {"type": "string", "default": "ng/mL"},
                        "confidence": {"type": "number"},
                        "evidence": {"type": "string"},
                    },
                    "required": ["date", "value", "confidence", "evidence"],
                },
            },
        ]

        field_list_text = "\n".join(
            f"- {fs.get('name')}: {fs.get('label', '')} ({fs.get('field_type', 'text')})"
            for fs in field_specs[:200]  # Claude maneja más context
        )

        system_prompt = f"""Eres un asistente clínico experto en oncourología que extrae datos estructurados de transcripciones médicas en español.

REGLAS ESTRICTAS:
1. SOLO extrae información EXPLÍCITAMENTE mencionada en el transcript. NUNCA inventes valores.
2. Para cada dato detectado, llama set_field UNA VEZ con field_name + value + confidence + evidence.
3. Para mediciones PSA con fecha, llama append_psa_history (NO uses set_field para esto).
4. confidence = 1.0 solo si el valor está explícito sin ambigüedad. 0.5-0.9 si requiere interpretación.
5. evidence DEBE ser una frase verbatim del transcript (copy-paste exacto).
6. Fechas en español: convierte a ISO YYYY-MM-DD asumiendo año 2026 si no se especifica.
7. Gleason "8 (4+4)" → 3 calls: gleason_primary=4, gleason_secondary=4, gleason_score=8.
8. T-stage en mayúsculas con minúscula final: "T2c" no "t2c".

Lista de campos disponibles ({len(field_specs)} total, mostrando top 200):
{field_list_text}

Si un dato del transcript NO corresponde a ningún campo de la lista, NO lo extraigas."""

        user_message = f"Transcript del médico:\n\n{transcript}\n\nExtrae todos los datos clínicos mencionados."

        return self.chat(
            system_prompt=system_prompt,
            user_message=user_message,
            tools=tools,
            temperature=0.0,
            max_tokens=4096,
        )
