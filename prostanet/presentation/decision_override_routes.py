"""decision_override_routes — EPIC 48.B (FAUBOT CXXXVI) + Sprint 6 hardening (CXLIV).

Override workflow: captura cuando el urólogo decide algo distinto a la
recomendación primaria del engine. Foundation para:
  - Continuous learning loop (engine refinement basado en patterns reales)
  - SaMD regulatory compliance (21 CFR Part 820 §820.30 user feedback)
  - Latin recalibration coefficients (publication target)
  - Real-world evidence layer

Tabla: clinical_override_event (auto-creada en first insert)

Endpoints:
  POST /api/decision-override         — captura override event (auth clinician)
  GET  /api/decision-override/<nss>   — historial override del paciente (auth clinician)
  GET  /api/decision-override/stats   — stats poblacionales (auth admin)

Sprint 6 hardening:
  - C3: @require_clinician en POST; clinician_id viene del session (no payload)
  - C6: no leak str(exc) al cliente; solo logger.exception
  - C9: HMAC-SHA256 signature (no SHA-256 truncado sin firma)
  - HIGH: atomic transaction (INSERT override + INSERT audit en una sola BEGIN/COMMIT)
  - HIGH: try/finally para conn.close()
  - HIGH: schema bootstrap movido a register helper (no per-request CREATE)
  - HIGH: paginación con ?limit + ?offset
  - HIGH: stats con SQL aggregation (no N-pass JSON parse en Python)
  - HIGH: algorithm_version snapshot en response
  - MED: validación decided_at format + narrative_confidence rango [0,1]
  - MED: sanitización free_text (max length)
  - MED: stats requiere @require_admin (IP institucional)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

from flask import Blueprint, jsonify, request

from prostanet.shared.api_auth import (
    require_clinician, require_admin, current_api_user_id, current_api_user_role,
)

logger = logging.getLogger(__name__)

decision_override_bp = Blueprint("decision_override", __name__)


# ─────────────────────────────────────────────────────────────────────
# Constantes (Sprint 6 LOW cleanup)
# ─────────────────────────────────────────────────────────────────────

MAX_FREE_TEXT_LENGTH = 4000  # Caracteres — previene PHI dump masiva y XSS
DEFAULT_HISTORY_LIMIT = 50
MAX_HISTORY_LIMIT = 500
ACTION_TRUNCATION = 80  # Antes 50 — más generoso pero acotado
SOURCE_TRUNCATION = 50  # Antes 30
HMAC_SIGNATURE_LENGTH = 32  # bytes (truncado a 64 hex chars del HMAC-SHA256)


# Sprint 6 C9: HMAC key. En producción debe venir de env var PROSTANET_AUDIT_HMAC_KEY.
# Fallback: per-process random key (peor: signature inconsistente across restarts).
def _get_hmac_key() -> bytes:
    key = os.environ.get("PROSTANET_AUDIT_HMAC_KEY", "")
    if key:
        return key.encode("utf-8")
    # Fallback dev: warning explícito
    logger.warning(
        "PROSTANET_AUDIT_HMAC_KEY not set; using DEV fallback (signatures "
        "NOT verifiable across restarts). Set explicit key in production."
    )
    return b"prostanet-dev-fallback-key-CXLIV-do-not-use-in-prod"


# ─────────────────────────────────────────────────────────────────────
# Allowed override reasons (canonical taxonomy)
# ─────────────────────────────────────────────────────────────────────


ALLOWED_OVERRIDE_REASONS = {
    "patient_preference",
    "patient_refusal",
    "access_barrier_local",
    "insurance_coverage",
    "prior_toxicity_intolerance",
    "comorbidity_contraindication",
    "clinical_judgment_other",
    "newer_evidence_post_engine",
    "patient_age_frailty",
    "drug_drug_interaction",
    "logistics_visit_burden",
    "second_opinion_consensus",
    "other_specify",
}


# ─────────────────────────────────────────────────────────────────────
# Schema bootstrap (idempotent, llamado desde register_blueprint)
# ─────────────────────────────────────────────────────────────────────


def _ensure_override_table(conn) -> None:
    """Crea la tabla si no existe. Idempotente."""
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS clinical_override_event (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            decided_at TEXT NOT NULL,
            recommended_action TEXT,
            recommended_label TEXT,
            recommendation_source TEXT,
            narrative_confidence REAL,
            override_action TEXT NOT NULL,
            override_label TEXT NOT NULL,
            override_reasons_json TEXT NOT NULL,
            free_text TEXT,
            clinician_id TEXT,
            actor_user_id INTEGER,
            actor_role TEXT,
            faubot_release TEXT,
            narrative_version TEXT,
            audit_signature TEXT,
            audit_signature_algo TEXT DEFAULT 'hmac_sha256',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_override_patient_id "
        "ON clinical_override_event (patient_id, decided_at DESC)"
    )
    # Sprint 6 H: normalized reasons table para SQL aggregation
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS clinical_override_event_reason (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            override_event_id INTEGER NOT NULL,
            reason_code TEXT NOT NULL,
            FOREIGN KEY (override_event_id) REFERENCES clinical_override_event(id)
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_override_reason_code "
        "ON clinical_override_event_reason (reason_code)"
    )
    conn.commit()


def initialize_override_schema(db_path: str | None = None) -> None:
    """Sprint 6 HIGH: schema bootstrap one-shot al arrancar la app.

    Llamar desde bootstrap.py register_blueprint:
        from prostanet.presentation.decision_override_routes import initialize_override_schema
        initialize_override_schema()
    """
    if db_path is None:
        from tracking_db import DB_PATH
        db_path = DB_PATH
    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=5.0)
        _ensure_override_table(conn)
    except Exception as exc:
        logger.warning("Override schema init failed: %s: %s",
                       type(exc).__name__, exc)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _faubot_release_snapshot() -> str:
    try:
        from prostanet.shared.algorithm_version import FAUBOT_RELEASE
        return str(FAUBOT_RELEASE)
    except Exception:
        return "unknown"


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def _resolve_patient_id_from_nss(nss: str) -> int | None:
    try:
        import tracking_db
        core = tracking_db.load_patient_record_core(nss)
        if not core:
            return None
        identity = core.get("identity") if isinstance(core, dict) else None
        if identity and isinstance(identity, dict):
            return int(identity.get("id") or 0) or None
    except Exception as exc:
        logger.warning("NSS resolution failed: %s: %s",
                       type(exc).__name__, exc)
    return None


def _validate_iso8601(value: str) -> str | None:
    """Sprint 6 MED: validate decided_at ISO-8601 + razonablemente pasado.

    Returns valid ISO string or None.
    Rechaza timestamps >24h en el futuro (acepta pequeña deriva de reloj cliente).
    """
    if not value:
        return None
    try:
        # Acepta con o sin Z; con o sin microseconds
        cleaned = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(cleaned)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        # Si está más de 24h en el futuro, rechazar (clock skew razonable)
        if (parsed - now).total_seconds() > 24 * 3600:
            logger.warning("decided_at rejected: too far in future: %s", value)
            return None
        return parsed.isoformat()
    except (ValueError, TypeError):
        return None


def _clamp_confidence(value: Any) -> float:
    """Sprint 6 MED: clamp narrative_confidence al rango [0, 1]."""
    try:
        v = float(value or 0.0)
    except (ValueError, TypeError):
        return 0.0
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


def _sanitize_free_text(value: Any) -> str:
    """Sprint 6 MED: trunca free_text + strip control chars + max length."""
    text = str(value or "")[:MAX_FREE_TEXT_LENGTH]
    # Strip control chars excepto \n y \t
    return "".join(
        c for c in text
        if c.isprintable() or c in ("\n", "\t")
    )


def _validate_override_payload(payload: dict[str, Any]) -> tuple[bool, str]:
    if not isinstance(payload, dict):
        return False, "payload must be JSON object"
    nss = payload.get("nss") or payload.get("patient_nss")
    if not nss:
        return False, "missing field: nss"
    override_label = payload.get("override_label") or payload.get("prescribed_label")
    if not override_label or not str(override_label).strip():
        return False, "missing or empty field: override_label"
    reasons = payload.get("override_reasons") or payload.get("reasons")
    if not isinstance(reasons, list) or not reasons:
        return False, "override_reasons must be non-empty list"
    invalid = [r for r in reasons if r not in ALLOWED_OVERRIDE_REASONS]
    if invalid:
        # Sprint 6 H: NO exponer taxonomía completa en error (low-priority leak)
        return False, f"invalid override_reasons (see docs for allowed set): count={len(invalid)}"
    if "other_specify" in reasons and not str(payload.get("free_text") or "").strip():
        return False, "reason 'other_specify' requires free_text"
    return True, ""


def _compute_audit_signature(payload: dict[str, Any]) -> str:
    """Sprint 6 C9: HMAC-SHA256 (NO plain SHA-256 truncated).

    Sin HMAC, atacante con DB access podía recalcular signature y modificar
    fields para enmascarar tampering. Con HMAC, signature requiere conocer
    el secret backend → tampering detectable en audit.
    """
    canonical = json.dumps(
        {
            k: payload.get(k)
            for k in (
                "patient_id", "recommended_label", "override_label",
                "override_reasons", "decided_at",
            )
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    sig = hmac.new(
        key=_get_hmac_key(),
        msg=canonical.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    # Devolver primeros 64 hex chars (256 bits del HMAC para storage compacto)
    return sig[:64]


def _audit_override_event_in_txn(
    cur,
    patient_id: int,
    override_action: str,
    recommendation_source: str,
    actor_user_id: int | None,
) -> None:
    """Sprint 6 HIGH: ATOMIC — usa el MISMO cursor del INSERT principal.

    Antes: _audit_override_event abría su propia tx después del COMMIT del
    insert → si audit fallaba, override quedaba sin trail. Ahora ambos
    operan en la misma transaction; rollback atómico si cualquier falla.
    """
    action = (
        f"override_recorded:{override_action[:ACTION_TRUNCATION]}"
        f":{recommendation_source[:SOURCE_TRUNCATION]}"
    )
    if actor_user_id:
        action = f"{action}:user_{actor_user_id}"
    cur.execute(
        """
        INSERT INTO clinical_view_audit
            (patient_id, section_key, action, importance, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            patient_id,
            "decision_override",
            action,
            "high",
            datetime.now(timezone.utc).isoformat(),
        ),
    )


# ─────────────────────────────────────────────────────────────────────
# REST endpoints
# ─────────────────────────────────────────────────────────────────────


@decision_override_bp.route("/api/decision-override", methods=["POST"])
@require_clinician
def record_override():
    """Captura un override event.

    Sprint 6 C3: clinician_id se captura del SESSION (no del payload). Esto
    cierra el bug que permitía a cualquier requester insertar override events
    con clinician_id arbitrario contaminando el dataset.

    Sprint 6 HIGH: atomic transaction (INSERT override + INSERT audit + INSERT
    reasons en una sola BEGIN/COMMIT).

    Body JSON: ver docstring original. clinician_id en payload se IGNORA;
    el actor real viene de la sesión autenticada.
    """
    faubot = _faubot_release_snapshot()
    actor_user_id = current_api_user_id()
    actor_role = current_api_user_role()

    try:
        payload = request.get_json(silent=True) or {}
        valid, error = _validate_override_payload(payload)
        if not valid:
            return jsonify({
                "success": False,
                "error": "validation_failed",
                "message": error,
                "faubot_release": faubot,
            }), 400

        nss = str(payload.get("nss") or payload.get("patient_nss"))
        patient_id = _resolve_patient_id_from_nss(nss)
        if not patient_id:
            return jsonify({
                "success": False,
                "error": "patient_not_found",
                "message": f"NSS '{nss}' no registrado",
                "faubot_release": faubot,
            }), 404

        # Sprint 6 MED: validate decided_at
        decided_at_raw = payload.get("decided_at")
        decided_at = (
            _validate_iso8601(decided_at_raw) if decided_at_raw
            else datetime.now(timezone.utc).isoformat()
        )
        if decided_at is None:
            return jsonify({
                "success": False,
                "error": "invalid_decided_at",
                "message": "decided_at debe ser ISO-8601 y no estar >24h en el futuro",
                "faubot_release": faubot,
            }), 400

        # Sprint 6 MED: clamp confidence
        narrative_confidence = _clamp_confidence(payload.get("narrative_confidence"))
        # Sprint 6 MED: sanitize free_text
        free_text = _sanitize_free_text(payload.get("free_text"))

        payload["patient_id"] = patient_id
        payload["decided_at"] = decided_at
        signature = _compute_audit_signature(payload)

        reasons_list = payload.get("override_reasons", [])

        from tracking_db import DB_PATH
        conn = None
        try:
            # Sprint 6 HIGH: timeout + WAL hint
            conn = sqlite3.connect(DB_PATH, timeout=5.0, isolation_level=None)
            cur = conn.cursor()
            # Sprint 6 HIGH: explicit atomic transaction
            cur.execute("BEGIN")

            cur.execute(
                """
                INSERT INTO clinical_override_event
                    (patient_id, decided_at, recommended_action, recommended_label,
                     recommendation_source, narrative_confidence,
                     override_action, override_label, override_reasons_json,
                     free_text, clinician_id, actor_user_id, actor_role,
                     faubot_release, narrative_version, audit_signature,
                     audit_signature_algo)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    patient_id,
                    decided_at,
                    str(payload.get("recommended_action") or ""),
                    str(payload.get("recommended_label") or ""),
                    str(payload.get("recommendation_source") or "unknown"),
                    narrative_confidence,
                    str(payload.get("override_action") or ""),
                    str(payload.get("override_label") or ""),
                    json.dumps(reasons_list, ensure_ascii=False),
                    free_text,
                    # Sprint 6 C3: clinician_id from session, NOT from payload
                    str(actor_user_id) if actor_user_id else "",
                    actor_user_id,
                    actor_role or "unknown",
                    faubot,
                    str(payload.get("narrative_version") or "epic48_v1.0"),
                    signature,
                    "hmac_sha256",
                ),
            )
            override_id = cur.lastrowid

            # Sprint 6 HIGH: insertar reasons normalizados para SQL aggregation
            for reason in reasons_list:
                cur.execute(
                    "INSERT INTO clinical_override_event_reason "
                    "(override_event_id, reason_code) VALUES (?, ?)",
                    (override_id, str(reason)),
                )

            # Sprint 6 HIGH: audit en MISMA transaction
            _audit_override_event_in_txn(
                cur, patient_id,
                str(payload.get("override_action") or payload.get("override_label", "")),
                str(payload.get("recommendation_source") or "unknown"),
                actor_user_id,
            )

            cur.execute("COMMIT")
        except Exception:
            # Sprint 6 HIGH: rollback atómico
            if conn is not None:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
            raise
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

        return jsonify({
            "success": True,
            "override_id": override_id,
            "patient_id": patient_id,
            "nss": nss,
            "audit_signature": signature,
            "audit_signature_algo": "hmac_sha256",
            "decided_at": decided_at,
            "faubot_release": faubot,
            "actor_role": actor_role,
            "message": "Override capturado para audit trail + engine learning loop.",
        }), 201
    except Exception as exc:
        # Sprint 6 C6: NO leak str(exc) al cliente
        logger.exception("Override capture failed for nss=%s", payload.get("nss") if isinstance(payload, dict) else "?")
        return jsonify({
            "success": False,
            "error": "internal_error",
            "message": "Error temporal al registrar override. Intente de nuevo.",
            "faubot_release": faubot,
        }), 500


@decision_override_bp.route("/api/decision-override/<nss>", methods=["GET"])
@require_clinician
def get_override_history(nss: str):
    """Retorna historial de overrides para un paciente.

    Sprint 6 HIGH: pagination con ?limit + ?offset.
    """
    faubot = _faubot_release_snapshot()
    try:
        patient_id = _resolve_patient_id_from_nss(nss)
        if not patient_id:
            return jsonify({
                "success": False,
                "error": "patient_not_found",
                "message": f"NSS '{nss}' no registrado",
                "faubot_release": faubot,
            }), 404

        # Sprint 6 HIGH: pagination
        try:
            limit = int(request.args.get("limit", DEFAULT_HISTORY_LIMIT))
            limit = max(1, min(limit, MAX_HISTORY_LIMIT))
            offset = max(0, int(request.args.get("offset", 0)))
        except (ValueError, TypeError):
            limit = DEFAULT_HISTORY_LIMIT
            offset = 0

        from tracking_db import DB_PATH
        conn = None
        try:
            conn = sqlite3.connect(DB_PATH, timeout=5.0)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM clinical_override_event WHERE patient_id=?",
                        (patient_id,))
            total = cur.fetchone()[0]
            cur.execute(
                """
                SELECT id, decided_at, recommended_label, recommendation_source,
                       override_label, override_reasons_json, free_text,
                       narrative_confidence, clinician_id, actor_user_id,
                       actor_role, faubot_release, audit_signature,
                       audit_signature_algo
                  FROM clinical_override_event
                 WHERE patient_id = ?
                 ORDER BY decided_at DESC
                 LIMIT ? OFFSET ?
                """,
                (patient_id, limit, offset),
            )
            rows = [dict(r) for r in cur.fetchall()]
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

        for r in rows:
            try:
                r["override_reasons"] = json.loads(r.pop("override_reasons_json", "[]"))
            except Exception:
                r["override_reasons"] = []

        return jsonify({
            "success": True,
            "patient_id": patient_id,
            "nss": nss,
            "overrides_count": len(rows),
            "total_count": total,
            "limit": limit,
            "offset": offset,
            "overrides": rows,
            "faubot_release": faubot,
        })
    except Exception:
        logger.exception("Override history failed for nss=%s", nss)
        return jsonify({
            "success": False,
            "error": "internal_error",
            "message": "Error temporal al consultar historial.",
            "faubot_release": faubot,
        }), 500


@decision_override_bp.route("/api/decision-override/stats", methods=["GET"])
@require_admin
def get_override_stats():
    """Stats poblacionales — auth admin (Sprint 6 MED: IP institucional)."""
    faubot = _faubot_release_snapshot()
    try:
        from tracking_db import DB_PATH
        conn = None
        try:
            conn = sqlite3.connect(DB_PATH, timeout=5.0)
            cur = conn.cursor()

            cur.execute("SELECT COUNT(*) FROM clinical_override_event")
            total = cur.fetchone()[0]

            cur.execute(
                """
                SELECT recommendation_source, COUNT(*) AS n
                  FROM clinical_override_event
                 GROUP BY recommendation_source
                 ORDER BY n DESC
                """
            )
            by_source = [{"source": r[0], "count": r[1]} for r in cur.fetchall()]

            # Sprint 6 HIGH: SQL aggregation contra normalized table
            # (antes era N-pass JSON parse en Python, lento a +10k overrides)
            cur.execute(
                """
                SELECT reason_code, COUNT(*) AS n
                  FROM clinical_override_event_reason
                 GROUP BY reason_code
                 ORDER BY n DESC
                """
            )
            by_reason = [{"reason": r[0], "count": r[1]} for r in cur.fetchall()]
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

        return jsonify({
            "success": True,
            "total_overrides": total,
            "by_recommendation_source": by_source,
            "by_reason": by_reason,
            "allowed_reasons": sorted(ALLOWED_OVERRIDE_REASONS),
            "faubot_release": faubot,
        })
    except Exception:
        logger.exception("Override stats failed")
        return jsonify({
            "success": False,
            "error": "internal_error",
            "message": "Error temporal al consultar stats.",
            "faubot_release": faubot,
        }), 500


__all__ = [
    "decision_override_bp",
    "ALLOWED_OVERRIDE_REASONS",
    "initialize_override_schema",
]
