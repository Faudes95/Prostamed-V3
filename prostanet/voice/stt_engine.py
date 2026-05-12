"""Local speech-to-text adapter for Voice Clinical OS.

The production path uses faster-whisper when installed. Tests and text-only
fallbacks can pass a transcript directly without calling any cloud service.
"""
from __future__ import annotations

import os
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TranscriptSegment:
    index: int
    text: str
    start_ms: int = 0
    end_ms: int = 0
    confidence: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "text": self.text,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "confidence": self.confidence,
        }


class LocalSTTEngine:
    name = "faster-whisper-local"

    def __init__(self, model_size: str | None = None, device: str | None = None):
        self.model_size = model_size or os.environ.get("VOICE_STT_MODEL", "small")
        self.device = device or os.environ.get("VOICE_STT_DEVICE", "cpu")
        self._model = None

    def is_available(self) -> bool:
        if os.environ.get("VOICE_STT_DISABLE", "").lower() in {"1", "true", "yes", "on"}:
            return False
        try:
            import faster_whisper  # noqa: F401
            return True
        except Exception:
            return self._sidecar_python() is not None

    def _sidecar_python(self) -> str | None:
        configured = os.environ.get("VOICE_STT_SIDECAR_PYTHON", "").strip()
        candidates = [
            configured,
            str(Path.cwd() / ".venv-voice311" / "bin" / "python"),
            str(Path(__file__).resolve().parents[2] / ".venv-voice311" / "bin" / "python"),
            shutil.which("python3.11") or "",
            shutil.which("python3.12") or "",
        ]
        for candidate in candidates:
            if not candidate:
                continue
            path = Path(candidate)
            if path.exists() and os.access(path, os.X_OK) and self._sidecar_has_whisper(str(path)):
                return str(path)
        return None

    def _sidecar_has_whisper(self, python_bin: str) -> bool:
        try:
            completed = subprocess.run(
                [python_bin, "-c", "import faster_whisper"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            return completed.returncode == 0
        except Exception:
            return False

    def _load_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=os.environ.get("VOICE_STT_COMPUTE_TYPE", "int8"),
            )
        return self._model

    def transcribe_bytes(
        self,
        audio_bytes: bytes,
        *,
        suffix: str = ".webm",
        language: str = "es",
    ) -> list[TranscriptSegment]:
        if not audio_bytes:
            return []
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = Path(tmp.name)
        try:
            try:
                import faster_whisper  # noqa: F401

                model = self._load_model()
                segments, _info = model.transcribe(str(tmp_path), language=language, vad_filter=True)
                out = []
                for idx, seg in enumerate(segments):
                    out.append(
                        TranscriptSegment(
                            index=idx,
                            text=str(getattr(seg, "text", "") or "").strip(),
                            start_ms=int(float(getattr(seg, "start", 0.0) or 0.0) * 1000),
                            end_ms=int(float(getattr(seg, "end", 0.0) or 0.0) * 1000),
                            confidence=0.0,
                        )
                    )
                return [item for item in out if item.text]
            except Exception:
                sidecar = self._sidecar_python()
                if not sidecar:
                    raise RuntimeError("faster-whisper no está instalado para STT local.")
                return self._transcribe_with_sidecar(sidecar, tmp_path, language=language)
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _transcribe_with_sidecar(self, python_bin: str, audio_path: Path, *, language: str = "es") -> list[TranscriptSegment]:
        sidecar_path = Path(__file__).with_name("stt_sidecar.py")
        env = {
            key: value
            for key, value in os.environ.items()
            if key.startswith("VOICE_STT_") or key in {"PATH", "HOME", "TMPDIR", "PYTHONPATH"}
        }
        completed = subprocess.run(
            [
                python_bin,
                str(sidecar_path),
                "--audio",
                str(audio_path),
                "--model",
                self.model_size,
                "--device",
                self.device,
                "--compute-type",
                os.environ.get("VOICE_STT_COMPUTE_TYPE", "int8"),
                "--language",
                language,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=int(os.environ.get("VOICE_STT_TIMEOUT_SECONDS", "120")),
            env=env,
        )
        try:
            payload = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise RuntimeError("voice_stt_sidecar_invalid_json") from exc
        if completed.returncode != 0 or not payload.get("success"):
            error = str(payload.get("error") or "voice_stt_sidecar_failed")
            detail = str(payload.get("detail") or "").strip()
            raise RuntimeError(f"{error}:{detail}" if detail else error)
        out = []
        for idx, item in enumerate(payload.get("segments") or []):
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            out.append(
                TranscriptSegment(
                    index=int(item.get("index", idx)),
                    text=text,
                    start_ms=int(item.get("start_ms") or 0),
                    end_ms=int(item.get("end_ms") or 0),
                    confidence=float(item.get("confidence") or 0.0),
                )
            )
        return out


def transcript_from_text(text: str) -> list[TranscriptSegment]:
    text = str(text or "").strip()
    if not text:
        return []
    return [TranscriptSegment(index=0, text=text, start_ms=0, end_ms=max(len(text) * 40, 800), confidence=1.0)]
