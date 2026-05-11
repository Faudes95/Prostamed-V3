"""
prostanet.voice.tts_providers.factory — Factory para TTS providers.

Faubot LXXX #voice-1.4 — abstracción para 3 providers:
- edge: Edge TTS (gratis, voces español MX/ES alta calidad)
- piper: Piper local (gratis, latencia mínima, voces medium quality)
- elevenlabs: ElevenLabs (paga, voz Antoni profesional)
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import AsyncIterator, Iterator, Protocol


@dataclass(frozen=True)
class TTSResult:
    """Resultado normalizado del TTS."""
    audio_bytes: bytes
    audio_format: str = "mp3"  # 'mp3' | 'wav' | 'opus'
    sample_rate: int = 24000
    voice: str = ""
    provider: str = ""
    latency_ms: int = 0


class TTSProvider(Protocol):
    """Interface común para TTS providers."""

    name: str
    voice: str

    def synthesize(self, text: str, voice: str | None = None) -> TTSResult:
        """Sintetiza texto a audio (batch). Retorna audio bytes completos."""
        ...

    def synthesize_streaming(
        self, text: str, voice: str | None = None
    ) -> Iterator[bytes]:
        """Sintetiza streaming (yields chunks de audio para latencia mínima)."""
        ...

    def is_available(self) -> bool:
        """Retorna True si provider configurado y reachable."""
        ...

    def list_voices(self, language: str = "es") -> list[dict[str, str]]:
        """Retorna voces disponibles para el idioma."""
        ...


# ─────────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────────

_PROVIDER_CACHE: dict[str, TTSProvider] = {}


def get_tts_provider(provider_name: str | None = None) -> TTSProvider:
    """
    Retorna TTS provider según env VOICE_TTS_PROVIDER (default: 'edge').

    Args:
        provider_name: 'edge' | 'piper' | 'elevenlabs' | None (auto desde env)

    Returns:
        TTSProvider instance (cached).
    """
    provider_name = (
        provider_name or os.environ.get("VOICE_TTS_PROVIDER", "edge").lower()
    )

    if provider_name not in ("edge", "piper", "elevenlabs"):
        raise ValueError(
            f"VOICE_TTS_PROVIDER inválido: '{provider_name}'. "
            "Use 'edge' (gratis), 'piper' (gratis local), o 'elevenlabs' (paga)."
        )

    if provider_name in _PROVIDER_CACHE:
        return _PROVIDER_CACHE[provider_name]

    if provider_name == "edge":
        from .edge_tts_provider import EdgeTTSProvider
        provider = EdgeTTSProvider()
    elif provider_name == "elevenlabs":
        from .elevenlabs_provider import ElevenLabsProvider
        provider = ElevenLabsProvider()
    elif provider_name == "piper":
        from .piper_provider import PiperProvider
        provider = PiperProvider()
    else:
        raise ValueError(f"Provider inválido: {provider_name}")

    _PROVIDER_CACHE[provider_name] = provider
    return provider


def clear_tts_provider_cache() -> None:
    """Limpia cache (tests + cambio config)."""
    _PROVIDER_CACHE.clear()
