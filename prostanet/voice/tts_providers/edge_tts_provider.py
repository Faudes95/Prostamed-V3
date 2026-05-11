"""
prostanet.voice.tts_providers.edge_tts_provider — Microsoft Edge TTS (gratis).

Voces español de alta calidad:
- es-MX-JorgeNeural    (masculino profesional, default — equivalente Antoni)
- es-MX-DaliaNeural    (femenino cálido — equivalente Sarah)
- es-MX-CecilioNeural  (masculino joven)
- es-MX-NuriaNeural    (femenino joven)
- es-ES-AlvaroNeural   (castellano masculino)
- es-ES-ElviraNeural   (castellano femenino)

Setup:
    pip install edge-tts  # ~5MB, sin API key requerida

Env vars:
    EDGE_TTS_VOICE=es-MX-JorgeNeural  (default)
    EDGE_TTS_RATE=+0%   (default — '-50%' lento, '+50%' rápido)
    EDGE_TTS_PITCH=+0Hz (default — '-50Hz' grave, '+50Hz' agudo)

Faubot LXXX #voice-1.4 — TTS gratis con calidad profesional para modo HYBRID.
"""
from __future__ import annotations

import asyncio
import io
import os
import time
from typing import Iterator

from .factory import TTSResult


class EdgeTTSProvider:
    """TTS provider usando Microsoft Edge (gratis, no API key, voces neuronales)."""

    name = "edge"

    # Voces español de alta calidad para uso clínico
    DEFAULT_VOICES = {
        "es-MX-JorgeNeural": "Masculino profesional México",
        "es-MX-DaliaNeural": "Femenino cálido México",
        "es-MX-CecilioNeural": "Masculino joven México",
        "es-ES-AlvaroNeural": "Masculino castellano",
        "es-ES-ElviraNeural": "Femenino castellano",
    }

    def __init__(
        self,
        voice: str | None = None,
        rate: str | None = None,
        pitch: str | None = None,
    ) -> None:
        self.voice = voice or os.environ.get("EDGE_TTS_VOICE", "es-MX-JorgeNeural")
        self.rate = rate or os.environ.get("EDGE_TTS_RATE", "+0%")
        self.pitch = pitch or os.environ.get("EDGE_TTS_PITCH", "+0Hz")

    def is_available(self) -> bool:
        """Verifica si edge-tts está instalado (no necesita API key)."""
        try:
            import edge_tts  # noqa: F401
            return True
        except ImportError:
            return False

    def synthesize(self, text: str, voice: str | None = None) -> TTSResult:
        """Sintetiza batch (espera todo el audio antes de retornar)."""
        try:
            import edge_tts
        except ImportError as exc:
            raise ImportError(
                "Paquete 'edge-tts' no instalado. Instalar con: pip install edge-tts"
            ) from exc

        voice = voice or self.voice
        start = time.time()

        async def _generate() -> bytes:
            communicate = edge_tts.Communicate(
                text=text,
                voice=voice,
                rate=self.rate,
                pitch=self.pitch,
            )
            buffer = io.BytesIO()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    buffer.write(chunk["data"])
            return buffer.getvalue()

        try:
            audio_bytes = asyncio.run(_generate())
        except RuntimeError:
            # Si ya hay event loop corriendo (e.g., Jupyter), usar nest_asyncio
            loop = asyncio.new_event_loop()
            audio_bytes = loop.run_until_complete(_generate())
            loop.close()

        latency_ms = int((time.time() - start) * 1000)

        return TTSResult(
            audio_bytes=audio_bytes,
            audio_format="mp3",
            sample_rate=24000,
            voice=voice,
            provider=self.name,
            latency_ms=latency_ms,
        )

    def synthesize_streaming(
        self, text: str, voice: str | None = None
    ) -> Iterator[bytes]:
        """
        Sintetiza streaming yield-ing chunks de audio.

        Útil para latencia mínima en UI (primer audio ~300-500ms).
        """
        try:
            import edge_tts
        except ImportError as exc:
            raise ImportError(
                "Paquete 'edge-tts' no instalado. Instalar con: pip install edge-tts"
            ) from exc

        voice = voice or self.voice

        async def _stream():
            communicate = edge_tts.Communicate(
                text=text, voice=voice, rate=self.rate, pitch=self.pitch
            )
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    yield chunk["data"]

        # Convert async generator to sync iterator
        loop = asyncio.new_event_loop()
        try:
            agen = _stream()
            while True:
                try:
                    chunk = loop.run_until_complete(agen.__anext__())
                    yield chunk
                except StopAsyncIteration:
                    break
        finally:
            loop.close()

    def list_voices(self, language: str = "es") -> list[dict[str, str]]:
        """Retorna voces disponibles para idioma (default español)."""
        return [
            {"id": vid, "description": desc}
            for vid, desc in self.DEFAULT_VOICES.items()
            if vid.startswith(language)
        ]
