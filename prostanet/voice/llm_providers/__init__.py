"""
prostanet.voice.llm_providers — Factory pattern para LLM providers.

Soporta 3 providers según `VOICE_LLM_MODE`:
- 'local' / 'hybrid': Ollama local (Qwen 2.5 14B por defecto) — gratis
- 'cloud' / 'hybrid' (SOAP): Anthropic Claude Sonnet — paga ~$0.02/llamada

Ejemplo:
    from prostanet.voice.llm_providers import get_llm_provider
    provider = get_llm_provider()  # auto-select por env VOICE_LLM_MODE
    response = provider.extract_fields(transcript, available_fields)
"""
from __future__ import annotations

from .factory import get_llm_provider, LLMProvider, LLMResponse, ToolCall

__all__ = ["get_llm_provider", "LLMProvider", "LLMResponse", "ToolCall"]
