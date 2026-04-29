"""
prostanet.voice.llm_providers.ollama_provider — Ollama local LLM wrapper.

Soporta Qwen 2.5 14B (recomendado), Llama 3.1 70B, Phi-4, etc.
Tool_use compatible con Ollama 0.4+ (qwen2.5, llama3.1+, mistral-small).

Setup:
    brew install ollama
    ollama serve  # background
    ollama pull qwen2.5:14b  # ~9GB

Env vars:
    OLLAMA_BASE_URL=http://localhost:11434  (default)
    OLLAMA_MODEL=qwen2.5:14b  (default)
    OLLAMA_TIMEOUT=60  (default seconds)

Faubot LXXX #voice-1.5 — Implementación gratis local con tool_use estructurado.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

from .factory import LLMProvider, LLMResponse, ToolCall


class OllamaProvider:
    """LLM provider que usa Ollama local (gratis, privacy-first)."""

    name = "ollama"

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
    ) -> None:
        self.base_url = base_url or os.environ.get(
            "OLLAMA_BASE_URL", "http://localhost:11434"
        )
        self.model = model or os.environ.get("OLLAMA_MODEL", "qwen2.5:14b")
        self.timeout = timeout or int(os.environ.get("OLLAMA_TIMEOUT", "60"))
        self._client = None  # lazy init

    def _get_client(self):
        """Lazy import + init de ollama client (no falla si no instalado)."""
        if self._client is None:
            try:
                import ollama
            except ImportError as exc:
                raise ImportError(
                    "Paquete 'ollama' no instalado. Instalar con: pip install ollama"
                ) from exc
            self._client = ollama.Client(host=self.base_url, timeout=self.timeout)
        return self._client

    def is_available(self) -> bool:
        """Verifica si Ollama está corriendo + modelo disponible."""
        try:
            client = self._get_client()
            models = client.list()
            available_names = [m.get("name", "") for m in models.get("models", [])]
            return any(self.model in name for name in available_names)
        except Exception:
            return False

    def chat(
        self,
        system_prompt: str,
        user_message: str,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        """
        Envía mensaje al Ollama y retorna respuesta normalizada.

        Tool_use compatible con qwen2.5, llama3.1+, mistral-small.
        Para modelos sin tool_use nativo, usa structured prompt (degradación graceful).
        """
        client = self._get_client()
        start = time.time()

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        chat_kwargs = {
            "model": self.model,
            "messages": messages,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if tools:
            chat_kwargs["tools"] = tools

        try:
            response = client.chat(**chat_kwargs)
        except Exception as exc:
            return LLMResponse(
                text=f"[Ollama error: {exc}]",
                provider=self.name,
                model=self.model,
                latency_ms=int((time.time() - start) * 1000),
            )

        latency_ms = int((time.time() - start) * 1000)
        message = response.get("message", {})
        text = message.get("content", "")

        # Parse tool_calls (formato Ollama)
        tool_calls: list[ToolCall] = []
        for tc in message.get("tool_calls", []) or []:
            func = tc.get("function", {})
            name = func.get("name", "")
            args = func.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"raw_text": args}

            tool_calls.append(
                ToolCall(
                    name=name,
                    arguments=args,
                    confidence=float(args.get("confidence", 1.0)),
                    raw_text_evidence=str(args.get("evidence", "")),
                )
            )

        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            raw_response=response,
            provider=self.name,
            model=self.model,
            latency_ms=latency_ms,
        )

    def extract_clinical_fields(
        self,
        transcript: str,
        field_specs: list[dict[str, Any]],
    ) -> LLMResponse:
        """
        Extrae fields clínicos del transcript usando tool_use estructurado.

        Construye un tool 'set_field' generic que el LLM debe invocar N veces,
        una por cada field detectado en el transcript.
        """
        # Build tool schemas — uno generic + uno para arrays longitudinales
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "set_field",
                    "description": (
                        "Establece el valor de UN campo clínico extraído del transcript. "
                        "Llamar UNA VEZ por cada campo detectado. "
                        "field_name debe ser exactamente uno de la lista de campos disponibles."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "field_name": {
                                "type": "string",
                                "description": "Nombre exacto del campo (ej: 'gleason_primary', 'ecog_current')",
                            },
                            "value": {
                                "description": "Valor extraído (string, number, boolean, o ISO date YYYY-MM-DD)",
                            },
                            "confidence": {
                                "type": "number",
                                "description": "Confianza 0.0-1.0 (1.0 = certeza absoluta)",
                                "minimum": 0.0,
                                "maximum": 1.0,
                            },
                            "evidence": {
                                "type": "string",
                                "description": "Frase EXACTA del transcript que justifica este valor (verbatim)",
                            },
                        },
                        "required": ["field_name", "value", "confidence", "evidence"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "append_psa_history",
                    "description": (
                        "Agrega una medición PSA al historial longitudinal del paciente. "
                        "Llamar UNA VEZ por cada PSA mencionado en el transcript."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "date": {
                                "type": "string",
                                "description": "Fecha del PSA en formato ISO YYYY-MM-DD",
                            },
                            "value": {
                                "type": "number",
                                "description": "Valor PSA en ng/mL",
                            },
                            "unit": {
                                "type": "string",
                                "description": "Unidad (default: 'ng/mL')",
                                "default": "ng/mL",
                            },
                            "confidence": {
                                "type": "number",
                                "minimum": 0.0,
                                "maximum": 1.0,
                            },
                            "evidence": {
                                "type": "string",
                                "description": "Frase EXACTA del transcript",
                            },
                        },
                        "required": ["date", "value", "confidence", "evidence"],
                    },
                },
            },
        ]

        # Build system prompt con lista de fields disponibles (resumen breve)
        field_list_text = "\n".join(
            f"- {fs.get('name')}: {fs.get('label', '')} ({fs.get('field_type', 'text')})"
            for fs in field_specs[:100]  # cap a 100 fields para no saturar context
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
8. T-stage en mayúsculas: "T2c" no "t2c".

Lista de campos disponibles (subset top 100):
{field_list_text}

Si un dato del transcript NO corresponde a ningún campo de la lista, NO lo extraigas (no inventes campos)."""

        user_message = f"Transcript del médico:\n\n{transcript}\n\nExtrae todos los datos clínicos mencionados."

        return self.chat(
            system_prompt=system_prompt,
            user_message=user_message,
            tools=tools,
            temperature=0.0,
            max_tokens=2048,
        )
