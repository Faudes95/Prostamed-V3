"""HTTP/WebSocket surface for ProstaMed Voice Clinical OS."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from prostanet.shared.security_helpers import require_clinical_session
from prostanet.voice.consent import is_affirmative_verbal_consent
from prostanet.voice.encryption import get_voice_crypto


# EPIC 31.D (GodiBot G78 MOD) — datetime UTC unification helper. Pre-EPIC31
# `datetime.now()` (naive local) vs SQLite CURRENT_TIMESTAMP (UTC) → ordering
# inconsistente, PSADT cruzando medianoche local con errores de 1 día.
def _utc_now_iso() -> str:
    """Returns UTC-aware ISO timestamp with seconds precision."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


voice_bp = Blueprint("voice_clinical_os", __name__)

# EPIC 32.A (GodiBot G64 CRIT) — SQLite-backed intake voice sessions store
# para multi-worker safety. Pre-EPIC32 `_INTAKE_VOICE_SESSIONS` era un dict
# en-memoria per-process; bajo `gunicorn --workers ≥2` worker A guardaba
# sesión, worker B no la encontraba (404) → workflow rota silenciosamente.
#
# Implementación: store con dual backend. Si VOICE_SESSIONS_BACKEND=memory
# o sqlite no disponible → in-memory dict (backward compat tests). Default
# (production) → SQLite con tabla intake_voice_sessions auto-creada.
_INTAKE_VOICE_SESSIONS: dict[str, dict[str, Any]] = {}  # legacy in-memory fallback


def _voice_sessions_db_path() -> Path:
    """SQLite DB path para intake voice sessions. Co-located con tracking.db."""
    return Path.cwd() / ".prostanet_private" / "intake_voice_sessions.db"


def _voice_sessions_use_sqlite() -> bool:
    backend = os.environ.get("VOICE_SESSIONS_BACKEND", "sqlite").lower()
    return backend == "sqlite"


def _voice_sessions_ensure_schema() -> None:
    """Crea tabla intake_voice_sessions si no existe (idempotent)."""
    if not _voice_sessions_use_sqlite():
        return
    import sqlite3 as _sq
    db_path = _voice_sessions_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = _sq.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS intake_voice_sessions (
                session_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                expires_at TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _voice_sessions_get(session_id: str) -> dict[str, Any] | None:
    """Lookup session. Prefer SQLite, fallback memory."""
    if _voice_sessions_use_sqlite():
        try:
            import sqlite3 as _sq
            _voice_sessions_ensure_schema()
            conn = _sq.connect(_voice_sessions_db_path())
            conn.row_factory = _sq.Row
            try:
                row = conn.execute(
                    "SELECT payload_json FROM intake_voice_sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
            finally:
                conn.close()
            if row:
                return json.loads(row["payload_json"])
        except Exception:
            pass  # Fallback to memory
    return _INTAKE_VOICE_SESSIONS.get(session_id)


def _voice_sessions_put(session_id: str, session: dict[str, Any]) -> None:
    """Persist session. Write to BOTH SQLite + memory (memory is fast read cache)."""
    _INTAKE_VOICE_SESSIONS[session_id] = session  # always keep in-process cache
    if _voice_sessions_use_sqlite():
        try:
            import sqlite3 as _sq
            _voice_sessions_ensure_schema()
            now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
            # Strip bytes for JSON serialization (audio_buffer_bytes is private)
            serializable = {k: v for k, v in session.items() if not isinstance(v, bytes)}
            payload_json = json.dumps(serializable, ensure_ascii=False, default=str)
            conn = _sq.connect(_voice_sessions_db_path())
            try:
                conn.execute(
                    """
                    INSERT INTO intake_voice_sessions
                        (session_id, payload_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                        payload_json = excluded.payload_json,
                        updated_at = excluded.updated_at
                    """,
                    (session_id, payload_json, now_iso, now_iso),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception:
            pass  # Memory cache still valid, just no cross-worker visibility


def _voice_sessions_delete(session_id: str) -> None:
    _INTAKE_VOICE_SESSIONS.pop(session_id, None)
    if _voice_sessions_use_sqlite():
        try:
            import sqlite3 as _sq
            _voice_sessions_ensure_schema()
            conn = _sq.connect(_voice_sessions_db_path())
            try:
                conn.execute(
                    "DELETE FROM intake_voice_sessions WHERE session_id = ?",
                    (session_id,),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception:
            pass


def _json_body() -> dict[str, Any]:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _error(message: str, status: int = 400):
    return jsonify({"success": False, "error": message}), status


def _voice_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _read_audio_request():
    audio_bytes = b""
    mime_type = ""
    file_name = ""
    transcribe = True
    upload = request.files.get("audio")
    if upload is not None:
        audio_bytes = upload.read() or b""
        mime_type = getattr(upload, "mimetype", "") or request.form.get("mime_type", "")
        file_name = getattr(upload, "filename", "") or "voice.webm"
        transcribe = str(request.form.get("transcribe", "true")).lower() not in {"0", "false", "no"}
    else:
        body = _json_body()
        raw = str(body.get("audio_base64") or "")
        if raw.startswith("data:"):
            header, raw = raw.split(",", 1)
            mime_type = header.split(";", 1)[0].replace("data:", "")
        mime_type = mime_type or str(body.get("mime_type") or "audio/webm")
        file_name = str(body.get("file_name") or "voice.webm")
        transcribe = bool(body.get("transcribe", True))
        try:
            audio_bytes = base64.b64decode(raw)
        except Exception:
            raise ValueError("invalid_audio_base64")
    return audio_bytes, mime_type or "audio/webm", file_name or "voice.webm", transcribe


def _intake_audio_path(session_id: str, audio_sha: str) -> Path:
    root = Path.cwd() / ".prostanet_private" / "voice_audio" / "intake"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{session_id}-{audio_sha[:16]}.json"


def _voice_audio_status(
    *,
    audio_sha: str,
    transcription_status: str,
    detail: str = "",
    local_stt_available: bool | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "stored": True,
        "encrypted": True,
        "sha256": audio_sha,
        "transcription_status": transcription_status,
    }
    if detail:
        payload["stt_status_detail"] = detail
    if local_stt_available is not None:
        payload["local_stt_available"] = local_stt_available
    return payload


def _stt_error_detail(exc: Exception, *, final_chunk: bool) -> tuple[str, str]:
    message = str(exc).lower()
    exc_name = type(exc).__name__
    if "timeout" in message or exc_name == "TimeoutExpired":
        return "stt_error", "sidecar_timeout"
    if "unavailable" in message or "no está instalado" in message:
        return "requires_local_stt", "model_unavailable"
    if "stt_transcription_failed" in message or "invalid data" in message or "decode" in message:
        return ("stt_error", "decode_failed") if final_chunk else ("partial_audio_buffering", "decode_pending")
    if "sidecar" in message:
        return "stt_error", "decode_failed"
    return "stt_error", "decode_failed"


def _append_intake_audio_buffer(session: dict[str, Any], audio_bytes: bytes) -> bytes:
    max_bytes = int(os.environ.get("VOICE_STT_MAX_BUFFER_BYTES", str(32 * 1024 * 1024)))
    existing = session.get("_audio_buffer_bytes")
    if not isinstance(existing, bytes):
        existing = b""
    buffer_bytes = existing + audio_bytes
    if len(buffer_bytes) > max_bytes:
        session["_audio_buffer_overflow"] = True
        buffer_bytes = audio_bytes
    session["_audio_buffer_bytes"] = buffer_bytes
    session["audio_buffer_bytes"] = len(buffer_bytes)
    return buffer_bytes


def _transcript_delta(session: dict[str, Any], transcript_text: str) -> str:
    full_text = " ".join(str(transcript_text or "").split())
    previous = " ".join(str(session.get("_last_stt_transcript_full") or "").split())
    if not full_text or full_text == previous:
        return ""
    session["_last_stt_transcript_full"] = full_text
    if previous and full_text.startswith(previous):
        return full_text[len(previous) :].strip(" .,\n\t")
    existing = " ".join(str(session.get("transcript_text") or "").split())
    if full_text and full_text in existing:
        return ""
    return full_text


def _append_transcript_delta(session: dict[str, Any], delta: str) -> bool:
    delta = " ".join(str(delta or "").split())
    if not delta:
        return False
    existing = str(session.get("transcript_text") or "").strip()
    if delta in " ".join(existing.split()):
        return False
    session["transcript_text"] = "\n".join(text for text in [existing, delta] if text).strip()
    return True


def _serialize_intake_session(session: dict[str, Any]) -> dict[str, Any]:
    return {
        "session": {
            "session_id": session.get("session_id"),
            "status": session.get("status", "created"),
            "consent_status": session.get("consent_status", "missing"),
            "ui_surface": session.get("ui_surface", "clinical_hub_classifier"),
            "created_at": session.get("created_at"),
            "audio_sha256": session.get("audio_sha256", ""),
        },
        "transcript": {
            "text": session.get("transcript_text", ""),
            "sha256": hashlib.sha256(str(session.get("transcript_text") or "").encode("utf-8")).hexdigest()
            if session.get("transcript_text")
            else "",
        },
        "candidates": session.get("candidates") or [],
        "audit_note": "Temporary intake voice session; no patient chart write is performed from clinical hub.",
    }


def _intake_fields_from_candidates(candidates: list[dict[str, Any]], accepted_keys: set[str]) -> dict[str, Any]:
    resolved = _resolve_intake_candidate_fields(candidates, accepted_keys=accepted_keys, min_confidence=0.0)
    return resolved["fields"]


def _resolve_intake_candidate_fields(
    candidates: list[dict[str, Any]],
    *,
    accepted_keys: set[str] | None = None,
    min_confidence: float = 0.72,
) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    candidate_keys: list[str] = []
    conflicts: list[dict[str, Any]] = []
    selected: dict[str, dict[str, Any]] = {}
    accepted_keys = accepted_keys or set()
    for candidate in candidates or []:
        key = str(candidate.get("candidate_key") or "")
        if accepted_keys and key not in accepted_keys:
            continue
        if not accepted_keys and float(candidate.get("confidence") or 0) < min_confidence:
            continue
        field_name = str(candidate.get("field_name") or "")
        if not field_name:
            continue
        existing = selected.get(field_name)
        if not existing:
            selected[field_name] = candidate
            continue
        if str(existing.get("value")) == str(candidate.get("value")):
            if float(candidate.get("confidence") or 0) > float(existing.get("confidence") or 0):
                selected[field_name] = candidate
            continue
        kept = existing
        rejected = candidate
        if float(candidate.get("confidence") or 0) > float(existing.get("confidence") or 0):
            kept = candidate
            rejected = existing
            selected[field_name] = candidate
        conflicts.append(
            {
                "field_name": field_name,
                "kept_value": kept.get("value"),
                "rejected_value": rejected.get("value"),
                "kept_candidate_key": kept.get("candidate_key"),
                "rejected_candidate_key": rejected.get("candidate_key"),
            }
        )
    for field_name, candidate in selected.items():
        fields[field_name] = candidate.get("value")
        if candidate.get("candidate_key"):
            candidate_keys.append(str(candidate.get("candidate_key")))
    return {"fields": fields, "conflicts": conflicts, "candidate_keys": candidate_keys}


def _review_intake_session(session_id: str, transcript_text: str = "", *, append: bool = True) -> tuple[bool, dict[str, Any] | str]:
    from prostanet.voice.intent_extractor import extract_intake_classifier_candidates

    session = _voice_sessions_get(session_id)
    if not session:
        return False, "intake_voice_session_not_found"
    if session.get("consent_status") != "signed":
        return False, "voice_consent_required"
    transcript_text = str(transcript_text or "").strip()
    if transcript_text:
        if append:
            session["transcript_text"] = "\n".join(
                text for text in [session.get("transcript_text", ""), transcript_text] if text
            ).strip()
        else:
            session["transcript_text"] = transcript_text
    transcript = str(session.get("transcript_text") or "").strip()
    if not transcript:
        return False, "transcript_required"
    session["transcript_envelope"] = get_voice_crypto().encrypt_text(transcript, aad=f"intake-voice:{session_id}:transcript")
    session["candidates"] = extract_intake_classifier_candidates(transcript, session_key=session_id)
    session["status"] = "review_pending"
    resolved = _resolve_intake_candidate_fields(session["candidates"])
    session["last_resolved_fields"] = resolved["fields"]
    _voice_sessions_put(session_id, session)
    return True, {
        **_serialize_intake_session(session),
        "fields": resolved["fields"],
        "conflicts": resolved["conflicts"],
        "candidate_keys": resolved["candidate_keys"],
        "transcript_delta": transcript_text,
        "transcript_full": transcript,
    }


def _legacy_intake_fields_from_candidates(candidates: list[dict[str, Any]], accepted_keys: set[str]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for candidate in candidates:
        key = str(candidate.get("candidate_key") or "")
        if accepted_keys and key not in accepted_keys:
            continue
        field_name = str(candidate.get("field_name") or "")
        if not field_name:
            continue
        fields[field_name] = candidate.get("value")
    return fields


def _sidecar_module_available(python_bin: str | None, module_name: str) -> bool:
    if not python_bin:
        return False
    try:
        completed = subprocess.run(
            [python_bin, "-c", f"import {module_name}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return completed.returncode == 0
    except Exception:
        return False


@voice_bp.route("/api/stt/health", methods=["GET"])
@voice_bp.route("/api/voice/stt/health", methods=["GET"])
@require_clinical_session(scope="phi:read", redirect_to_login=False)
def voice_stt_health():
    # Fast-by-default guardrail: summary avoids sidecar subprocess probes unless
    # explicitly requested with deep=1 or scope=full.
    from prostanet.voice.stt_health import build_stt_health

    scope = str(request.args.get("scope") or "summary").strip().lower()
    deep = str(request.args.get("deep") or "").strip().lower() in {"1", "true", "yes", "full"}
    payload = build_stt_health(scope=scope, deep=deep)
    return jsonify(
        {
            **payload,
            # Legacy keys preservados para backward compat.
            "local_stt_available": payload.get("stt_available", False),
            "sidecar_available": payload.get("mode") in {"sidecar", "sidecar_unverified"},
            "checks": {
                "faster_whisper": "faster_whisper" not in (payload.get("missing_dependencies") or []),
                "pyav": None if payload.get("scope") == "summary" else None,
                "ctranslate2": None if payload.get("scope") == "summary" else None,
            },
            "diagnostic": payload.get("stt_health", {}).get("diagnostic", payload.get("stt_health", {}).get("summary", {})),
        }
    )


@voice_bp.route("/api/patients/<patient_ref>/voice/encounters", methods=["POST"])
@require_clinical_session(scope="phi:write", redirect_to_login=False)
def create_voice_encounter(patient_ref: str):
    import tracking_db

    ok, result = tracking_db.create_voice_encounter_session(patient_ref, _json_body())
    if not ok:
        return _error(str(result), 404 if result == "patient_not_found" else 400)
    return jsonify({"success": True, **result})


@voice_bp.route("/api/patients/<patient_ref>/voice/encounters/<session_key>", methods=["GET"])
@require_clinical_session(scope="phi:read", redirect_to_login=False)
def get_voice_encounter(patient_ref: str, session_key: str):
    import tracking_db

    bundle = tracking_db.get_voice_encounter_session(patient_ref, session_key)
    if not bundle:
        return _error("voice_session_not_found", 404)
    return jsonify({"success": True, **bundle})


@voice_bp.route("/api/patients/<patient_ref>/voice/encounters/<session_key>/consent", methods=["POST"])
@require_clinical_session(scope="phi:write", redirect_to_login=False)
def consent_voice_encounter(patient_ref: str, session_key: str):
    import tracking_db

    ok, result = tracking_db.record_voice_consent(patient_ref, session_key, _json_body())
    if not ok:
        status = 404 if result in {"patient_not_found", "voice_session_not_found"} else 400
        return _error(str(result), status)
    return jsonify({"success": True, **result})


@voice_bp.route("/api/patients/<patient_ref>/voice/encounters/<session_key>/review", methods=["POST"])
@require_clinical_session(scope="phi:write", redirect_to_login=False)
def review_voice_encounter(patient_ref: str, session_key: str):
    import tracking_db

    ok, result = tracking_db.review_voice_encounter(patient_ref, session_key, _json_body())
    if not ok:
        status = 404 if result in {"patient_not_found", "voice_session_not_found"} else 400
        return _error(str(result), status)
    return jsonify({"success": True, **result})


@voice_bp.route("/api/patients/<patient_ref>/voice/encounters/<session_key>/audio", methods=["POST"])
@require_clinical_session(scope="phi:write", redirect_to_login=False)
def upload_voice_audio(patient_ref: str, session_key: str):
    import tracking_db

    try:
        audio_bytes, mime_type, file_name, transcribe = _read_audio_request()
    except ValueError as exc:
        return _error(str(exc), 400)

    ok, result = tracking_db.store_voice_audio_chunk(
        patient_ref,
        session_key,
        audio_bytes,
        mime_type=mime_type,
        file_name=file_name,
        transcribe=transcribe,
    )
    if not ok:
        status = 404 if result in {"patient_not_found", "voice_session_not_found"} else 400
        return _error(str(result), status)
    return jsonify({"success": True, **result})


@voice_bp.route("/api/patients/<patient_ref>/voice/encounters/<session_key>/commit", methods=["POST"])
@require_clinical_session(scope="phi:write", redirect_to_login=False)
def commit_voice_encounter(patient_ref: str, session_key: str):
    import tracking_db

    ok, result = tracking_db.commit_voice_encounter(patient_ref, session_key, _json_body())
    if not ok:
        status = 404 if result in {"patient_not_found", "voice_session_not_found"} else 400
        return _error(str(result), status)
    return jsonify({"success": True, **result})


@voice_bp.route("/api/patients/<patient_ref>/voice/encounters/<session_key>/discard", methods=["POST"])
@require_clinical_session(scope="phi:write", redirect_to_login=False)
def discard_voice_encounter(patient_ref: str, session_key: str):
    import tracking_db

    ok, result = tracking_db.discard_voice_encounter(patient_ref, session_key, _json_body())
    if not ok:
        status = 404 if result in {"patient_not_found", "voice_session_not_found"} else 400
        return _error(str(result), status)
    return jsonify({"success": True, **result})


@voice_bp.route("/api/clinical-hub/voice/encounters", methods=["POST"])
@require_clinical_session(scope="phi:write", redirect_to_login=False)
def create_intake_voice_encounter():
    data = _json_body()
    session_id = str(data.get("session_id") or f"intake-voice-{uuid.uuid4().hex[:18]}")
    session = {
        "session_id": session_id,
        "status": "created",
        "consent_status": "missing",
        "ui_surface": data.get("ui_surface") or "clinical_hub_classifier",
        "created_at": _utc_now_iso(),
        "transcript_text": "",
        "candidates": [],
    }
    _voice_sessions_put(session_id, session)
    return jsonify({"success": True, **_serialize_intake_session(session)})


@voice_bp.route("/api/clinical-hub/voice/encounters/<session_id>/consent", methods=["POST"])
@require_clinical_session(scope="phi:write", redirect_to_login=False)
def consent_intake_voice_encounter(session_id: str):
    session = _voice_sessions_get(session_id)
    if not session:
        return _error("intake_voice_session_not_found", 404)
    spoken_text = str(_json_body().get("spoken_text") or "").strip()
    if not is_affirmative_verbal_consent(spoken_text):
        return _error("verbal_consent_not_affirmative", 400)
    session["consent_status"] = "signed"
    session["status"] = "consented"
    session["consent_hash"] = hashlib.sha256(f"{session_id}|{spoken_text}".encode("utf-8")).hexdigest()
    session["consented_at"] = _utc_now_iso()
    _voice_sessions_put(session_id, session)
    return jsonify({"success": True, **_serialize_intake_session(session)})


@voice_bp.route("/api/clinical-hub/voice/encounters/<session_id>/review", methods=["POST"])
@require_clinical_session(scope="phi:write", redirect_to_login=False)
def review_intake_voice_encounter(session_id: str):
    body = _json_body()
    ok, result = _review_intake_session(
        session_id,
        str(body.get("transcript_text") or ""),
        append=bool(body.get("append", True)),
    )
    if not ok:
        status = 404 if result == "intake_voice_session_not_found" else 400
        return _error(str(result), status)
    return jsonify({"success": True, **result})


@voice_bp.route("/api/clinical-hub/voice/encounters/<session_id>/audio", methods=["POST"])
@require_clinical_session(scope="phi:write", redirect_to_login=False)
def upload_intake_voice_audio(session_id: str):
    from prostanet.voice.stt_engine import LocalSTTEngine

    session = _voice_sessions_get(session_id)
    if not session:
        return _error("intake_voice_session_not_found", 404)
    if session.get("consent_status") != "signed":
        return _error("voice_consent_required", 400)
    try:
        audio_bytes, mime_type, file_name, transcribe = _read_audio_request()
    except ValueError as exc:
        return _error(str(exc), 400)
    if not audio_bytes:
        return _error("audio_required", 400)
    chunk_index = request.form.get("chunk_index") or request.values.get("chunk_index") or _json_body().get("chunk_index", "")
    final_chunk = str(request.form.get("final") or request.values.get("final") or _json_body().get("final", "false")).lower() in {"1", "true", "yes"}
    auto_apply = str(request.form.get("auto_apply") or request.values.get("auto_apply") or _json_body().get("auto_apply", "false")).lower() in {"1", "true", "yes"}

    audio_sha = hashlib.sha256(audio_bytes).hexdigest()
    envelope = get_voice_crypto().encrypt_bytes(audio_bytes, aad=f"intake-voice-audio:{session_id}:{audio_sha}")
    encrypted_path = _intake_audio_path(session_id, audio_sha)
    encrypted_path.write_text(
        _voice_json(
            {
                "envelope": envelope,
                "mime_type": mime_type,
                "file_name": file_name,
                "session_id": session_id,
                "created_at": _utc_now_iso(),
                "retention_policy": "delete_audio_after_review",
                "local_first": True,
                "chunk_index": chunk_index,
                "final": final_chunk,
            }
        ),
        encoding="utf-8",
    )
    try:
        encrypted_path.chmod(0o600)
    except OSError:
        pass
    session.update(
        {
            "status": "audio_received",
            "audio_sha256": audio_sha,
            "encrypted_audio_path": str(encrypted_path),
            "mime_type": mime_type,
            "file_name": file_name,
            "last_chunk_index": chunk_index,
            "audio_chunks_received": int(session.get("audio_chunks_received") or 0) + 1,
        }
    )
    if final_chunk:
        # A final MediaRecorder blob is the only authoritative object for STT.
        # Appending earlier WebM fragments can create an invalid container.
        session["_audio_buffer_bytes"] = audio_bytes
        session["audio_buffer_bytes"] = len(audio_bytes)
        buffer_bytes = audio_bytes
    else:
        buffer_bytes = _append_intake_audio_buffer(session, audio_bytes)
    if not transcribe:
        resolved = _resolve_intake_candidate_fields(session.get("candidates") or []) if auto_apply else {"fields": {}, "conflicts": [], "candidate_keys": []}
        return jsonify(
            {
                "success": True,
                **_serialize_intake_session(session),
                "audio": _voice_audio_status(audio_sha=audio_sha, transcription_status="not_requested"),
                "fields": resolved["fields"],
                "conflicts": resolved["conflicts"],
                "candidate_keys": resolved["candidate_keys"],
                "transcript_delta": "",
                "transcript_full": session.get("transcript_text") or "",
                "chunk_index": chunk_index,
                "final": final_chunk,
            }
        )

    stt = LocalSTTEngine()
    if not stt.is_available():
        return jsonify(
            {
                "success": True,
                **_serialize_intake_session(session),
                "audio": _voice_audio_status(
                    audio_sha=audio_sha,
                    transcription_status="requires_local_stt",
                    detail="model_unavailable",
                    local_stt_available=False,
                ),
                "fields": {},
                "conflicts": [],
                "candidate_keys": [],
                "transcript_delta": "",
                "transcript_full": session.get("transcript_text") or "",
                "chunk_index": chunk_index,
                "final": final_chunk,
            }
        )
    try:
        segments = stt.transcribe_bytes(buffer_bytes, suffix=Path(file_name).suffix or ".webm", language="es")
        transcript_text = " ".join(segment.text for segment in segments if segment.text).strip()
    except Exception as exc:
        status, detail = _stt_error_detail(exc, final_chunk=final_chunk)
        session["stt_last_status"] = status
        session["stt_last_detail"] = detail
        try:
            current_app.logger.warning(
                "voice_intake_stt_status | session=%s status=%s detail=%s exc=%s final=%s chunk=%s",
                session_id,
                status,
                detail,
                type(exc).__name__,
                final_chunk,
                chunk_index,
            )
        except Exception:
            pass
        return jsonify(
            {
                "success": True,
                **_serialize_intake_session(session),
                "audio": _voice_audio_status(
                    audio_sha=audio_sha,
                    transcription_status=status,
                    detail=detail,
                    local_stt_available=True,
                ),
                "fields": {},
                "conflicts": [],
                "candidate_keys": [],
                "transcript_delta": "",
                "transcript_full": session.get("transcript_text") or "",
                "chunk_index": chunk_index,
                "final": final_chunk,
            }
        )
    if not transcript_text:
        return jsonify(
            {
                "success": True,
                **_serialize_intake_session(session),
                "audio": _voice_audio_status(
                    audio_sha=audio_sha,
                    transcription_status="empty_transcript",
                    detail="empty_transcript",
                    local_stt_available=True,
                ),
                "fields": {},
                "conflicts": [],
                "candidate_keys": [],
                "transcript_delta": "",
                "transcript_full": session.get("transcript_text") or "",
                "chunk_index": chunk_index,
                "final": final_chunk,
            }
        )
    transcript_delta = _transcript_delta(session, transcript_text)
    if not _append_transcript_delta(session, transcript_delta):
        return jsonify(
            {
                "success": True,
                **_serialize_intake_session(session),
                "audio": _voice_audio_status(
                    audio_sha=audio_sha,
                    transcription_status="transcribed",
                    detail="no_new_transcript_delta",
                    local_stt_available=True,
                ),
                "fields": {},
                "conflicts": [],
                "candidate_keys": [],
                "transcript_delta": "",
                "transcript_full": session.get("transcript_text") or "",
                "chunk_index": chunk_index,
                "final": final_chunk,
                "auto_apply": auto_apply,
            }
        )
    ok, review_result = _review_intake_session(session_id, "", append=True)
    if not ok:
        return _error(str(review_result), 400)
    return jsonify(
        {
            "success": True,
            **review_result,
            "audio": _voice_audio_status(
                audio_sha=audio_sha,
                transcription_status="transcribed",
                local_stt_available=True,
            ),
            "transcript_delta": transcript_delta,
            "transcript_full": session.get("transcript_text") or "",
            "chunk_index": chunk_index,
            "final": final_chunk,
            "auto_apply": auto_apply,
        }
    )


@voice_bp.route("/api/clinical-hub/voice/encounters/<session_id>/apply", methods=["POST"])
@require_clinical_session(scope="phi:write", redirect_to_login=False)
def apply_intake_voice_encounter(session_id: str):
    session = _voice_sessions_get(session_id)
    if not session:
        return _error("intake_voice_session_not_found", 404)
    if session.get("consent_status") != "signed":
        return _error("voice_consent_required", 400)
    accepted_keys = {str(key) for key in (_json_body().get("accepted_candidate_keys") or []) if str(key).strip()}
    resolved = _resolve_intake_candidate_fields(session.get("candidates") or [], accepted_keys=accepted_keys, min_confidence=0.0)
    fields = resolved["fields"]
    if not fields:
        return _error("accepted_candidates_required", 400)
    session["status"] = "applied_to_classifier"
    session["applied_fields"] = fields
    session["applied_at"] = _utc_now_iso()
    _voice_sessions_put(session_id, session)
    return jsonify(
        {
            "success": True,
            **_serialize_intake_session(session),
            "fields": fields,
            "conflicts": resolved["conflicts"],
            "provenance": {
                "source": "clinical_hub_voice_intake",
                "session_id": session_id,
                "transcript_sha256": hashlib.sha256(str(session.get("transcript_text") or "").encode("utf-8")).hexdigest(),
                "candidate_keys": sorted(accepted_keys or set(resolved["candidate_keys"])),
            },
        }
    )


@voice_bp.route("/api/clinical-hub/voice/encounters/<session_id>/discard", methods=["POST"])
@require_clinical_session(scope="phi:write", redirect_to_login=False)
def discard_intake_voice_encounter(session_id: str):
    session = _voice_sessions_get(session_id)
    if not session:
        return _error("intake_voice_session_not_found", 404)
    session["status"] = "discarded"
    session["discarded_at"] = _utc_now_iso()
    _voice_sessions_put(session_id, session)
    return jsonify({"success": True, **_serialize_intake_session(session)})


@voice_bp.route("/api/patients/<patient_ref>/voice/encounters/<session_key>/ws-status", methods=["GET"])
def voice_ws_unavailable(patient_ref: str, session_key: str):
    return jsonify({
        "success": False,
        "error": "websocket_transport_unavailable",
        "install": "flask-sock==0.7.0",
    }), 501


def register_voice_websocket(app) -> None:
    """Register the streaming WebSocket when Flask-Sock is installed."""

    try:
        from flask_sock import Sock
    except Exception:
        app.logger.warning("Voice WebSocket disabled: flask-sock no instalado.")
        return

    sock = Sock(app)

    @sock.route("/ws/patients/<patient_ref>/voice/encounters/<session_key>")
    def voice_stream(ws, patient_ref: str, session_key: str):  # pragma: no cover - exercised in browser/e2e
        import tracking_db
        from prostanet.voice.stt_engine import LocalSTTEngine

        stt = LocalSTTEngine()
        ws.send(json.dumps({"type": "ready", "local_stt_available": stt.is_available()}))
        while True:
            message = ws.receive()
            if message is None:
                break
            if isinstance(message, bytes):
                if not stt.is_available():
                    ws.send(json.dumps({"type": "error", "error": "local_stt_unavailable"}))
                    continue
                try:
                    segments = stt.transcribe_bytes(message)
                    transcript_text = " ".join(seg.text for seg in segments if seg.text)
                    if transcript_text:
                        ok, result = tracking_db.review_voice_encounter(
                            patient_ref,
                            session_key,
                            {"transcript_text": transcript_text},
                        )
                        ws.send(json.dumps({"type": "partial", "success": ok, "bundle": result if ok else {}, "error": "" if ok else result}))
                except Exception as exc:
                    ws.send(json.dumps({"type": "error", "error": type(exc).__name__}))
                continue
            try:
                payload = json.loads(message)
            except Exception:
                payload = {"type": "transcript", "transcript_text": str(message or "")}
            if payload.get("type") == "transcript":
                ok, result = tracking_db.review_voice_encounter(patient_ref, session_key, payload)
                ws.send(json.dumps({"type": "review", "success": ok, "bundle": result if ok else {}, "error": "" if ok else result}))
            elif payload.get("type") == "ping":
                ws.send(json.dumps({"type": "pong"}))
            else:
                ws.send(json.dumps({"type": "ignored"}))


def register_voice_os(app) -> None:
    app.register_blueprint(voice_bp)
    register_voice_websocket(app)
