"""Verbal consent contract for Voice Clinical OS."""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any


VOICE_CONSENT_VERSION = "voice-consent-v1"
VOICE_CONSENT_TITLE = "Consentimiento verbal para captura clínica por voz"
VOICE_CONSENT_TEXT = """
Autorizo que ProstaMed grabe temporalmente esta conversación clínica para
transcribirla de forma local, extraer datos estructurados y presentarlos al
médico para revisión antes de escribirlos en mi expediente. Entiendo que el
audio crudo se eliminará después de la revisión clínica o al vencer la política
institucional de retención temporal, conservando únicamente el transcript
firmado, los datos aceptados y la auditoría correspondiente.
""".strip()


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def normalize_spoken_consent(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def is_affirmative_verbal_consent(text: str) -> bool:
    normalized = normalize_spoken_consent(text)
    if len(normalized) < 8:
        return False
    affirmative_markers = (
        "autorizo",
        "acepto",
        "doy mi consentimiento",
        "si autorizo",
        "sí autorizo",
        "estoy de acuerdo",
    )
    return any(marker in normalized for marker in affirmative_markers)


def build_voice_consent_hash(*, patient_ref: str, session_key: str, spoken_text: str, signed_at: str) -> str:
    raw = "|".join(
        [
            VOICE_CONSENT_VERSION,
            str(patient_ref or ""),
            str(session_key or ""),
            normalize_spoken_consent(spoken_text),
            str(signed_at or ""),
            VOICE_CONSENT_TEXT,
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_consent_metadata(*, patient_ref: str, session_key: str, spoken_text: str, signed_at: str) -> dict[str, Any]:
    return {
        "evidence_type": "voice",
        "voice_consent_version": VOICE_CONSENT_VERSION,
        "patient_ref": str(patient_ref or ""),
        "session_key": str(session_key or ""),
        "signed_at": signed_at,
        "spoken_text_hash": hashlib.sha256(normalize_spoken_consent(spoken_text).encode("utf-8")).hexdigest(),
        "retention_policy": "raw_audio_deleted_after_review",
        "human_in_the_loop_required": True,
    }

