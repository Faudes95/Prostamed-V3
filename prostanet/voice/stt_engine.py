"""Local speech-to-text adapter for Voice Clinical OS.

The production path uses faster-whisper when installed. Tests and text-only
fallbacks can pass a transcript directly without calling any cloud service.
"""
from __future__ import annotations

import os
import json
import shutil
import subprocess
import sys
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

    def diagnose(self) -> dict[str, Any]:
        """EPIC 24a — Structured diagnostic of STT engine state.

        Returns a dict consumed by `/api/voice/stt/health` so the UI can
        show specific guidance (sidecar missing vs disabled vs in-process)
        instead of the generic "audio cifrado · STT local pendiente"
        microcopy that hides the real blocker from the clinician.
        """
        disable_flag = os.environ.get("VOICE_STT_DISABLE", "").lower() in {"1", "true", "yes", "on"}
        diag: dict[str, Any] = {
            "stt_available": False,
            "mode": "unavailable",
            "in_process_faster_whisper": False,
            "sidecar_python": None,
            "sidecar_faster_whisper_version": None,
            "model_size": self.model_size,
            "device": self.device,
            "compute_type": os.environ.get("VOICE_STT_COMPUTE_TYPE", "int8"),
            "blockers": [],
            "stt_disable_env": disable_flag,
        }
        if disable_flag:
            diag["blockers"].append("VOICE_STT_DISABLE=1 — STT desactivado por admin")
            return diag
        # Try in-process import first
        try:
            import faster_whisper as _fw  # type: ignore[import-not-found]
            diag["stt_available"] = True
            diag["mode"] = "in_process"
            diag["in_process_faster_whisper"] = True
            diag["in_process_faster_whisper_version"] = getattr(_fw, "__version__", "?")
            return diag
        except Exception:
            diag["blockers"].append(
                "faster_whisper no instalable en este Python "
                f"({sys.version_info.major}.{sys.version_info.minor}) — "
                "intentando sidecar..."
            )
        # Try sidecar
        sidecar = self._sidecar_python()
        if sidecar:
            diag["stt_available"] = True
            diag["mode"] = "sidecar"
            diag["sidecar_python"] = sidecar
            diag["sidecar_faster_whisper_version"] = self._sidecar_whisper_version(sidecar)
            return diag
        diag["blockers"].append(
            "sidecar venv no encontrado en .venv-voice311/. "
            "Crea con: python3.11 -m venv .venv-voice311 && "
            ".venv-voice311/bin/pip install faster-whisper==1.0.3"
        )
        return diag

    def _sidecar_whisper_version(self, python_bin: str) -> str | None:
        try:
            completed = subprocess.run(
                [python_bin, "-c", "import faster_whisper; print(faster_whisper.__version__)"],
                check=False, capture_output=True, text=True, timeout=5,
            )
            if completed.returncode == 0:
                return completed.stdout.strip() or None
        except Exception:
            return None
        return None

    def _sidecar_python(self) -> str | None:
        """EPIC 24c — Worktree-aware sidecar path resolution.

        Pre-EPIC 24 only checked cwd + parents[2], which silently failed when
        Flask ran from a git worktree (the venv lives in the main repo, not
        the worktree). Now searches:
          1. VOICE_STT_SIDECAR_PYTHON env (explicit override)
          2. cwd / .venv-voice311 (current directory)
          3. git rev-parse --show-toplevel / .venv-voice311 (resolves through worktrees)
          4. Path(__file__).parents up the tree (defensive)
          5. ~/.venv-voice311 (home dir fallback)
          6. python3.11 / python3.12 on PATH (last resort — must have faster_whisper)
        """
        configured = os.environ.get("VOICE_STT_SIDECAR_PYTHON", "").strip()
        candidates: list[str] = [configured]

        # cwd-relative
        candidates.append(str(Path.cwd() / ".venv-voice311" / "bin" / "python"))

        # git root-relative (handles worktrees)
        try:
            completed = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                check=False, capture_output=True, text=True, timeout=3,
                cwd=str(Path(__file__).resolve().parent),
            )
            if completed.returncode == 0:
                git_root = completed.stdout.strip()
                if git_root:
                    candidates.append(str(Path(git_root) / ".venv-voice311" / "bin" / "python"))
        except Exception:
            pass

        # Upward search from __file__ — handles any directory layout
        here = Path(__file__).resolve()
        for parent in (here.parent, *here.parents):
            cand = parent / ".venv-voice311" / "bin" / "python"
            candidates.append(str(cand))
            # Also handle when worktree path contains the main repo elsewhere
            for sib in ("ProstaNet_Model_Fase6", "ProstaMed"):
                if sib in str(parent):
                    # Already handled by going up
                    break

        # Home fallback + PATH
        candidates.append(str(Path.home() / ".venv-voice311" / "bin" / "python"))
        candidates.append(shutil.which("python3.11") or "")
        candidates.append(shutil.which("python3.12") or "")

        seen: set[str] = set()
        for candidate in candidates:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
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
                # EPIC 30.4 (GodiBot G65 CRIT) — wire clinical_vocabulary_boost
                # initial_prompt al Whisper. Pre-EPIC30 el módulo existía pero
                # NUNCA se llamaba: Whisper confundía "darolutamida"→"doralutamida",
                # "apalutamida"→"abalumida", "PSMA"→"P MA", "Lutecio-177"→"lucio 177".
                # Downstream intent_extractor regex requiere ortografía exacta,
                # producía silent drops de señales clínicas.
                try:
                    from prostanet.voice.clinical_vocabulary_boost import get_stt_initial_prompt
                    initial_prompt = get_stt_initial_prompt(language=language)
                except Exception:
                    initial_prompt = None
                transcribe_kwargs: dict[str, Any] = {
                    "language": language,
                    "vad_filter": True,
                }
                if initial_prompt:
                    transcribe_kwargs["initial_prompt"] = initial_prompt
                segments, _info = model.transcribe(str(tmp_path), **transcribe_kwargs)
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
