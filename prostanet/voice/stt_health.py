"""Fast STT health summaries for voice clinical guardrails."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any


def _sidecar_candidate_exists() -> bool:
    configured = os.environ.get("VOICE_STT_SIDECAR_PYTHON", "").strip()
    candidates = [
        configured,
        str(Path.cwd() / ".venv-voice311" / "bin" / "python"),
        str(Path.home() / ".venv-voice311" / "bin" / "python"),
    ]
    return any(candidate and Path(candidate).exists() for candidate in candidates)


def _recommended_action(status: str, mode: str, missing: list[str]) -> str:
    if status == "ok":
        return "STT local disponible para flujos de voz clinica."
    if mode == "disabled":
        return "Eliminar VOICE_STT_DISABLE del entorno y reiniciar Flask si se desea habilitar STT."
    if "faster_whisper" in missing:
        return (
            "Instalar faster-whisper en el entorno actual o preparar .venv-voice311 "
            "y validar con /api/stt/health?deep=1."
        )
    return "Validar dependencias locales con /api/stt/health?deep=1 antes de expandir voz clinica."


def _normalize_status(diag: dict[str, Any]) -> str:
    if diag.get("stt_available"):
        return "ok"
    if diag.get("stt_disable_env"):
        return "unavailable"
    return "unavailable" if diag.get("mode") == "unavailable" else "degraded"


def build_stt_health(*, scope: str = "summary", deep: bool = False) -> dict[str, Any]:
    """Build a fast-by-default STT health contract.

    Summary mode avoids subprocess sidecar checks. Deep/full mode preserves the
    historical LocalSTTEngine.diagnose() contract for explicit admin audits.
    """
    scope = "full" if str(scope or "").lower() == "full" else "summary"
    if deep or scope == "full":
        from prostanet.voice.stt_engine import LocalSTTEngine

        stt = LocalSTTEngine()
        diag = stt.diagnose()
        status = _normalize_status(diag)
        missing = []
        if not diag.get("in_process_faster_whisper") and diag.get("mode") != "sidecar":
            missing.append("faster_whisper")
        if not diag.get("sidecar_python") and diag.get("mode") != "in_process":
            missing.append("voice_stt_sidecar")
        next_steps = list(diag.get("next_steps") or [])
        if not next_steps:
            next_steps = [_recommended_action(status, str(diag.get("mode") or ""), missing)]
        return {
            **diag,
            "success": True,
            "scope": "full",
            "status": status,
            "missing_dependencies": missing,
            "recommended_action": next_steps[0],
            "next_steps": next_steps,
            "stt_health": {
                "summary": {
                    "status": status,
                    "mode": diag.get("mode"),
                    "missing_dependencies": missing,
                    "recommended_action": next_steps[0],
                },
                "diagnostic": diag,
            },
            "epic": "24a",
        }

    disabled = os.environ.get("VOICE_STT_DISABLE", "").lower() in {"1", "true", "yes", "on"}
    in_process = importlib.util.find_spec("faster_whisper") is not None
    sidecar_present = _sidecar_candidate_exists()
    if disabled:
        status = "unavailable"
        mode = "disabled"
        missing = ["stt_enabled"]
        blockers = ["VOICE_STT_DISABLE=1 - STT desactivado por admin"]
    elif in_process:
        status = "ok"
        mode = "in_process"
        missing = []
        blockers = []
    elif sidecar_present:
        status = "degraded"
        mode = "sidecar_unverified"
        missing = ["faster_whisper"]
        blockers = ["faster_whisper no instalado en proceso; sidecar presente no verificado en summary"]
    else:
        status = "unavailable"
        mode = "unavailable"
        missing = ["faster_whisper", "voice_stt_sidecar"]
        blockers = ["faster_whisper no instalado y sidecar .venv-voice311 no encontrado"]
    action = _recommended_action(status, mode, missing)
    summary = {
        "status": status,
        "mode": mode,
        "stt_available": status == "ok",
        "missing_dependencies": missing,
        "recommended_action": action,
    }
    return {
        "success": True,
        "scope": "summary",
        "status": status,
        "mode": mode,
        "stt_available": status == "ok",
        "blockers": blockers,
        "missing_dependencies": missing,
        "recommended_action": action,
        "next_steps": [action] if status != "ok" else [],
        "local_first": True,
        "epic": "24a",
        "stt_health": {"summary": summary},
    }
