"""
prostanet.voice.tts_providers — Factory pattern para TTS providers.

Soporta 3 providers según `VOICE_TTS_PROVIDER`:
- 'edge' (default gratis): Microsoft Edge TTS — voces español alta calidad
- 'piper' (gratis): Piper TTS local — latencia mínima
- 'elevenlabs' (paga premium): ElevenLabs Antoni/Sarah — calidad clínica máxima

Ejemplo:
    from prostanet.voice.tts_providers import get_tts_provider
    tts = get_tts_provider()  # auto-select por env VOICE_TTS_PROVIDER
    audio_bytes = tts.synthesize("Análisis completado.")
"""
from __future__ import annotations

from .factory import get_tts_provider, TTSProvider, TTSResult

__all__ = ["get_tts_provider", "TTSProvider", "TTSResult"]
