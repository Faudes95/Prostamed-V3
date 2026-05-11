"""
prostanet.voice.tts_providers.elevenlabs_provider — ElevenLabs Premium TTS.

Voces español de calidad clínica máxima:
- Antoni (ErXwobaYiN019PkySvjV) — masculino profesional autoritativo
- Sarah  (EXAVITQu4vr4xnSDxMaL) — femenino neutra cálida
- Bella  (bIHbv24MWmeRgasZH58o) — femenino joven energética

Setup:
    pip install elevenlabs
    export ELEVENLABS_API_KEY=sk_...

Costo: ~$0.30/1000 chars = ~$0.05/consulta de 1500 chars resumen.

Faubot LXXX #voice-1.4 — TTS premium para modo CLOUD máxima calidad.
"""
from __future__ import annotations

import os
import time
from typing import Iterator

from .factory import TTSResult


class ElevenLabsProvider:
    """TTS provider usando ElevenLabs (paga, máxima calidad clínica)."""

    name = "elevenlabs"

    # Voces ElevenLabs preconfiguradas para uso clínico ProstaMed
    VOICES = {
        "antoni": {
            "id": "ErXwobaYiN019PkySvjV",
            "description": "Masculino profesional autoritativo (Cortana default)",
        },
        "sarah": {
            "id": "EXAVITQu4vr4xnSDxMaL",
            "description": "Femenino neutra cálida",
        },
        "bella": {
            "id": "bIHbv24MWmeRgasZH58o",
            "description": "Femenino joven energética",
        },
    }

    def __init__(
        self,
        api_key: str | None = None,
        voice_id: str | None = None,
        model: str | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("ELEVENLABS_API_KEY", "")
        # Default Antoni (masculino profesional)
        self.voice = voice_id or os.environ.get(
            "ELEVENLABS_VOICE_ID", "ErXwobaYiN019PkySvjV"
        )
        self.model = model or os.environ.get(
            "ELEVENLABS_MODEL", "eleven_multilingual_v2"
        )
        self._client = None

    def _get_client(self):
        """Lazy import + init."""
        if self._client is None:
            try:
                from elevenlabs.client import ElevenLabs
            except ImportError as exc:
                raise ImportError(
                    "Paquete 'elevenlabs' no instalado. "
                    "Instalar con: pip install elevenlabs"
                ) from exc
            if not self.api_key:
                raise ValueError(
                    "ELEVENLABS_API_KEY no configurada. "
                    "Necesaria para modo TTS 'elevenlabs' (paga)."
                )
            self._client = ElevenLabs(api_key=self.api_key)
        return self._client

    def is_available(self) -> bool:
        """Verifica si API key configurada (sin gastar créditos)."""
        return bool(self.api_key) and (
            self.api_key.startswith("sk_") or len(self.api_key) > 20
        )

    def synthesize(self, text: str, voice: str | None = None) -> TTSResult:
        """Sintetiza batch."""
        client = self._get_client()
        voice = voice or self.voice
        start = time.time()

        try:
            audio_iter = client.text_to_speech.convert(
                voice_id=voice,
                output_format="mp3_44100_128",
                text=text,
                model_id=self.model,
            )
            audio_bytes = b"".join(audio_iter)
        except Exception as exc:
            return TTSResult(
                audio_bytes=b"",
                voice=voice,
                provider=self.name,
                latency_ms=int((time.time() - start) * 1000),
            )

        latency_ms = int((time.time() - start) * 1000)

        return TTSResult(
            audio_bytes=audio_bytes,
            audio_format="mp3",
            sample_rate=44100,
            voice=voice,
            provider=self.name,
            latency_ms=latency_ms,
        )

    def synthesize_streaming(
        self, text: str, voice: str | None = None
    ) -> Iterator[bytes]:
        """Sintetiza streaming (latencia <600ms primer audio)."""
        client = self._get_client()
        voice = voice or self.voice

        try:
            audio_stream = client.text_to_speech.stream(
                voice_id=voice,
                output_format="mp3_44100_128",
                text=text,
                model_id=self.model,
            )
            yield from audio_stream
        except Exception:
            return

    def list_voices(self, language: str = "es") -> list[dict[str, str]]:
        """Retorna voces ElevenLabs preconfiguradas."""
        return [
            {"id": data["id"], "name": name, "description": data["description"]}
            for name, data in self.VOICES.items()
        ]
