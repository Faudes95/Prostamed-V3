"""EPIC 38 — STT smoke end-to-end tests.

Verifica que el endpoint POST /api/voice/quick-capture/<field> en multipart
mode acepta uploads de audio reales (WAV stdlib-generated), invoca el STT
engine (mockeado para determinismo), y devuelve extracción correcta.

Estrategia (honest scope):
- Mockear `LocalSTTEngine.transcribe_bytes` para retornar TranscriptSegment
  predecibles → permite testear el wiring HTTP+endpoint+extractor sin requerir
  faster-whisper, Whisper-model download, ni GPU.
- Subir audio fixtures reales (`silence_1s_16khz.wav`, `tone_440hz_1s.wav`)
  para verificar parsing multipart, suffix detection, y manejo size limits.
- Documentar manual smoke recipe en docstring para validation real con audio
  dictado (requires faster-whisper instalado).

Tests:
- 4 fields × multipart audio → mocked STT returns transcripts → assertions
  sobre la extracción.
- Edge cases: empty audio, oversize audio (>25MB simulated), invalid suffix,
  STT engine failure (raises exception → 503).
"""
from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ─────────────────── Fixtures ───────────────────

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "audio"
SILENCE_WAV = FIXTURES_DIR / "silence_1s_16khz.wav"
TONE_WAV = FIXTURES_DIR / "tone_440hz_1s.wav"


@pytest.fixture(scope="module")
def client():
    """Flask test client con create_app() invoked."""
    from app import app, create_app
    create_app()
    return app.test_client()


@pytest.fixture
def mock_stt_transcript(monkeypatch):
    """Factory para mockear LocalSTTEngine.transcribe_bytes con transcript
    arbitrario.

    Usage:
        def test_x(client, mock_stt_transcript):
            mock_stt_transcript("ECOG 2 paciente estable")
            resp = client.post(...)
    """
    def _factory(transcript_text: str):
        from prostanet.voice import stt_engine as _stt
        # TranscriptSegment dataclass (minimal stand-in)
        class _Seg:
            def __init__(self, text):
                self.index = 0
                self.text = text
                self.start_ms = 0
                self.end_ms = 1000
                self.confidence = 0.95

        def _fake_transcribe_bytes(self, audio_bytes, *, suffix=".webm", language="es"):
            if not audio_bytes:
                return []
            return [_Seg(transcript_text)]

        monkeypatch.setattr(_stt.LocalSTTEngine, "transcribe_bytes", _fake_transcribe_bytes)
    return _factory


# ─────────────────── Fixture sanity ───────────────────

class TestFixtures:
    def test_silence_fixture_exists(self):
        assert SILENCE_WAV.exists()
        assert SILENCE_WAV.stat().st_size > 30_000  # ~32KB for 1s 16kHz mono 16-bit
        assert SILENCE_WAV.stat().st_size < 50_000

    def test_tone_fixture_exists(self):
        assert TONE_WAV.exists()
        assert TONE_WAV.stat().st_size > 30_000

    def test_silence_is_valid_wav(self):
        import wave
        with wave.open(str(SILENCE_WAV), "rb") as w:
            assert w.getnchannels() == 1
            assert w.getsampwidth() == 2
            assert w.getframerate() == 16000


# ─────────────────── Multipart audio + mock STT ───────────────────

class TestMultipartAudioPipeline:
    """Verify multipart audio path: HTTP upload → STT → extractor → response."""

    def test_ecog_multipart_with_silence_audio_and_mocked_transcript(
        self, client, mock_stt_transcript
    ):
        mock_stt_transcript("paciente con ECOG 2")
        with open(SILENCE_WAV, "rb") as f:
            r = client.post(
                "/api/voice/quick-capture/ecog",
                data={"audio": (f, "silence.wav"), "patient_ref": "TEST"},
                content_type="multipart/form-data",
            )
        assert r.status_code == 200
        b = r.get_json()
        assert b["success"] is True
        assert b["transcript_source"] == "stt_whisper"
        assert b["transcript"] == "paciente con ECOG 2"
        assert b["extraction"]["value"] == 2

    def test_castration_multipart_pipeline(self, client, mock_stt_transcript):
        mock_stt_transcript("castración confirmada, testosterona 22 ng/dL")
        with open(SILENCE_WAV, "rb") as f:
            r = client.post(
                "/api/voice/quick-capture/castration",
                data={"audio": (f, "castration.wav")},
                content_type="multipart/form-data",
            )
        assert r.status_code == 200
        b = r.get_json()
        ext = b["extraction"]
        assert ext["status"] == "confirmed_castrate"
        assert ext["testosterone_value"] == 22.0

    def test_hrr_multipart_pipeline(self, client, mock_stt_transcript):
        mock_stt_transcript("HRR positivo BRCA2 patogénica")
        with open(SILENCE_WAV, "rb") as f:
            r = client.post(
                "/api/voice/quick-capture/hrr",
                data={"audio": (f, "hrr.wav")},
                content_type="multipart/form-data",
            )
        b = r.get_json()
        assert b["extraction"]["status"] == "positive"
        assert b["extraction"]["gene"] == "BRCA2"

    def test_psma_multipart_with_full_dictation(self, client, mock_stt_transcript):
        mock_stt_transcript(
            "PSMA-PET positivo metastásico 8 lesiones SUVmax 22.5"
        )
        with open(TONE_WAV, "rb") as f:
            r = client.post(
                "/api/voice/quick-capture/psma_pet",
                data={"audio": (f, "psma.wav")},
                content_type="multipart/form-data",
            )
        ext = r.get_json()["extraction"]
        assert ext["status"] == "positive_metastatic"
        assert ext["lesion_count"] == 8
        assert ext["suv_max_value"] == 22.5


class TestSuffixDetection:
    """Verify endpoint correctly identifies audio suffix from filename."""

    @pytest.mark.parametrize("filename,expected_suffix", [
        ("recording.webm", ".webm"),
        ("dictation.wav", ".wav"),
        ("voice.mp3", ".mp3"),
        ("audio.ogg", ".ogg"),
        ("session.m4a", ".m4a"),
        ("opus_audio.opus", ".opus"),
        ("no_extension", ".webm"),  # default
    ])
    def test_suffix_detection(self, client, mock_stt_transcript, filename, expected_suffix, monkeypatch):
        """Verify that endpoint passes the right suffix to STT engine."""
        captured_suffix = {"value": None}
        from prostanet.voice import stt_engine as _stt

        class _Seg:
            def __init__(self, text):
                self.index, self.text, self.start_ms, self.end_ms, self.confidence = 0, text, 0, 1000, 0.9

        def _fake(self, audio_bytes, *, suffix=".webm", language="es"):
            captured_suffix["value"] = suffix
            return [_Seg("ECOG 1")]
        monkeypatch.setattr(_stt.LocalSTTEngine, "transcribe_bytes", _fake)

        with open(SILENCE_WAV, "rb") as f:
            client.post(
                "/api/voice/quick-capture/ecog",
                data={"audio": (f, filename)},
                content_type="multipart/form-data",
            )
        assert captured_suffix["value"] == expected_suffix


# ─────────────────── Error paths ───────────────────

class TestEndpointErrorPaths:
    def test_empty_audio_returns_400(self, client):
        r = client.post(
            "/api/voice/quick-capture/ecog",
            data={"audio": (io.BytesIO(b""), "empty.wav")},
            content_type="multipart/form-data",
        )
        assert r.status_code == 400
        assert r.get_json()["error"] == "audio_empty"

    def test_oversize_audio_returns_413(self, client):
        big = io.BytesIO(b"\x00" * (26 * 1024 * 1024))  # 26MB
        r = client.post(
            "/api/voice/quick-capture/ecog",
            data={"audio": (big, "big.wav")},
            content_type="multipart/form-data",
        )
        # Flask may also enforce its own size limit returning 413 or 400
        assert r.status_code in (400, 413)

    def test_stt_failure_returns_503(self, client, monkeypatch):
        from prostanet.voice import stt_engine as _stt

        def _raise(self, audio_bytes, *, suffix=".webm", language="es"):
            raise RuntimeError("faster-whisper no instalado en Python 3.14")
        monkeypatch.setattr(_stt.LocalSTTEngine, "transcribe_bytes", _raise)

        with open(SILENCE_WAV, "rb") as f:
            r = client.post(
                "/api/voice/quick-capture/ecog",
                data={"audio": (f, "test.wav")},
                content_type="multipart/form-data",
            )
        assert r.status_code == 503
        b = r.get_json()
        assert b["error"] == "stt_failed"
        assert "faster-whisper" in b["message"]
        assert "hint" in b

    def test_invalid_field_with_audio_returns_400(self, client):
        with open(SILENCE_WAV, "rb") as f:
            r = client.post(
                "/api/voice/quick-capture/unknown_field",
                data={"audio": (f, "x.wav")},
                content_type="multipart/form-data",
            )
        assert r.status_code == 400
        assert r.get_json()["error"] == "invalid_field"


# ─────────────────── Patient_ref echo via form data ───────────────────

class TestPatientRefEchoMultipart:
    def test_patient_ref_from_form_data(self, client, mock_stt_transcript):
        mock_stt_transcript("ECOG 1")
        with open(SILENCE_WAV, "rb") as f:
            r = client.post(
                "/api/voice/quick-capture/ecog",
                data={"audio": (f, "x.wav"), "patient_ref": "VAL-687-049"},
                content_type="multipart/form-data",
            )
        assert r.get_json()["patient_ref"] == "VAL-687-049"


# ─────────────────── Manual smoke recipe (DOC, not test) ───────────────────

class TestManualSTTRecipe:
    """Documenta cómo correr smoke STT real con faster-whisper instalado.

    NO ES UN TEST AUTOMATIZADO — solo documentación ejecutable que skip
    cuando faster-whisper no está disponible.

    Manual recipe:
        1. pip install faster-whisper (Python 3.10-3.12 only)
        2. Generar audio dictando "ECOG dos" via Quicktime/voice memo,
           guardar como ~/Desktop/ecog_test.wav
        3. curl -X POST http://127.0.0.1:8080/api/voice/quick-capture/ecog \\
             -F audio=@~/Desktop/ecog_test.wav \\
             -F patient_ref=VAL-687-049
        4. Verify response:
           {success: true, transcript: "ECOG dos", extraction: {value: 2, ...}}

    O usar el sidecar (Python 3.10-3.12 in subprocess):
        VOICE_STT_SIDECAR_PYTHON=/path/to/py312 python3 -m prostanet.voice.stt_sidecar \\
          --audio /path/ecog_test.wav --model small --device cpu --compute-type int8
    """

    def test_real_stt_available_check(self):
        """Skip si faster-whisper no instalado — informativo solamente."""
        import importlib.util
        spec = importlib.util.find_spec("faster_whisper")
        if not spec:
            pytest.skip(
                "faster-whisper NOT installed. Manual STT smoke requires: "
                "pip install faster-whisper (Python 3.10-3.12 only)"
            )
        # Si está, verificar que LocalSTTEngine puede inicializar
        from prostanet.voice.stt_engine import LocalSTTEngine
        engine = LocalSTTEngine()
        assert engine is not None
