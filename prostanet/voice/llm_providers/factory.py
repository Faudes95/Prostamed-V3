"""
prostanet.voice.llm_providers.factory — Factory pattern para LLM providers.

Permite intercambiar Ollama (local/gratis) ↔ Claude (cloud/paga) sin tocar
código de aplicación. Configurable via env VOICE_LLM_MODE.

Faubot LXXX #voice-1.5 — abstracción provider para soportar 3 modos:
- local: Ollama puro, $0/consulta
- hybrid: Ollama + Claude solo SOAP, ~$0.01/consulta (recomendado)
- cloud: Claude completo, ~$0.07/consulta
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolCall:
    """Representación normalizada de una tool_call del LLM."""
    name: str
    arguments: dict[str, Any]
    confidence: float = 1.0
    raw_text_evidence: str = ""


@dataclass(frozen=True)
class LLMResponse:
    """Respuesta normalizada del LLM (cualquier provider)."""
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw_response: dict[str, Any] | None = None
    provider: str = ""
    model: str = ""
    latency_ms: int = 0


class LLMProvider(Protocol):
    """Interface común para providers LLM (Ollama / Claude)."""

    name: str
    model: str

    def chat(
        self,
        system_prompt: str,
        user_message: str,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        """Envía mensaje al LLM y retorna respuesta normalizada."""
        ...

    def extract_clinical_fields(
        self,
        transcript: str,
        field_specs: list[dict[str, Any]],
    ) -> LLMResponse:
        """
        Extrae fields clínicos estructurados del transcript usando tool_use.

        Args:
            transcript: Texto transcrito del médico (español).
            field_specs: Lista de FieldSpec (de pivotal_gate_supporting_fields)
                         para construir el tool schema.

        Returns:
            LLMResponse con tool_calls = [ToolCall(name="set_field", args={...}), ...]
        """
        ...

    def is_available(self) -> bool:
        """Retorna True si el provider está configurado y reachable."""
        ...


# ─────────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────────

_PROVIDER_CACHE: dict[str, LLMProvider] = {}


def get_llm_provider(
    mode: str | None = None,
    purpose: str = "extraction",
) -> LLMProvider:
    """
    Retorna el LLM provider apropiado según mode + purpose.

    Args:
        mode: 'cloud' | 'local' | 'hybrid' | None (auto desde env VOICE_LLM_MODE)
        purpose: 'extraction' | 'soap' | 'qa'
            - extraction: gates extracción de fields (puede ser local en hybrid)
            - soap: generación SOAP final (cloud en hybrid para máxima calidad)
            - qa: Q&A poblacional (puede ser local en hybrid)

    Returns:
        LLMProvider instance (cached).

    Raises:
        ValueError: si mode inválido o provider no disponible.
    """
    mode = mode or os.environ.get("VOICE_LLM_MODE", "hybrid").lower()

    if mode not in ("cloud", "local", "hybrid"):
        raise ValueError(
            f"VOICE_LLM_MODE inválido: '{mode}'. Use 'cloud', 'local', o 'hybrid'."
        )

    # Determinar provider concreto según mode + purpose
    if mode == "cloud":
        provider_key = "anthropic"
    elif mode == "local":
        provider_key = "ollama"
    else:  # hybrid
        # En hybrid: SOAP usa cloud (Claude) para máxima calidad,
        # extracción y Q&A usan local (Ollama) para minimizar costo.
        provider_key = "anthropic" if purpose == "soap" else "ollama"

    if provider_key in _PROVIDER_CACHE:
        return _PROVIDER_CACHE[provider_key]

    # Lazy import del provider concreto (evita ImportError si no instalado)
    if provider_key == "ollama":
        from .ollama_provider import OllamaProvider
        provider = OllamaProvider()
    elif provider_key == "anthropic":
        from .anthropic_provider import AnthropicProvider
        provider = AnthropicProvider()
    else:
        raise ValueError(f"Provider key inválido: {provider_key}")

    _PROVIDER_CACHE[provider_key] = provider
    return provider


def clear_provider_cache() -> None:
    """Limpia cache de providers (útil para tests + cambio de config)."""
    _PROVIDER_CACHE.clear()
