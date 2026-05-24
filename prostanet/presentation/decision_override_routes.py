"""decision_override_routes — EPIC 48.B (FAUBOT CXXXVI).

Override workflow: captura cuando el urólogo decide algo distinto a la
recomendación primaria del engine. Foundation para:
  - Continuous learning loop (engine refinement basado en patterns reales)
  - SaMD regulatory compliance (21 CFR Part 820 §820.30 user feedback)
  - Latin recalibration coefficients (publication target)
  - Real-world evidence layer

Tabla: clinical_override_event (auto-creada en first insert)
  patient_id, recommended_action, recommended_label, override_action,
  override_label, override_reasons (JSON array), free_text, decided_at,
  clinician_id (opcional), narrative_confidence, recommendation_source

Endpoints:
  POST /api/decision-override         — captura override event
  GET  /api/decision-override/<nss>   — historial override del paciente
  GET  /api/decision-override/stats   — stats poblacionales (dashboard)
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

decision_override_bp = Blueprint("decision_override", __name__)


# ─────────────────────────────────────────────────────────────────────
# Allowed override reasons (canonical taxonomy)
# ─────────────────────────────────────────────────────────────────────
# Esta taxonomía es publicable: cada reason es un código estable que se
# puede agregar en analytics. NO permitir reasons libres (free_text es
# separado, para contexto auditable adicional).

ALLOWED_OVERRIDE_REASONS = {
    "patient_preference",
    "patient_refusal",
    "access_barrier_local",       # ej. Lu-PSMA no disponible
    "insurance_coverage",          # ej. ARSI no cubierto
    "prior_toxicity_intolerance",
    "comorbidity_contraindication",
    "clinical_judgment_other",
    "newer_evidence_post_engine",  # urólogo aware de trial reciente
    "patient_age_frailty",
    "drug_drug_interaction",
    "logistics_visit_burden",      # ej. paciente no puede viajar para infusion
    "second_opinion_consensus",    # tumor board override
    "other_specify",               # requiere free_text
}


# ─────────────────────────────────────────────────────────────────────
# Schema bootstrap (idempotent)
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
            faubot_release TEXT,
            narrative_version TEXT,
            audit_signature TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_override_patient_id "
        "ON clinical_override_event (patient_id, decided_at DESC)"
    )
    conn.commit()


def _audit_override_event(
    conn,
    patient_id: int,
    override_action: str,
    recommendation_source: str,
) -> None:
    """Audit log en clinical_view_audit para regulatory traceability."""
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO clinical_view_audit
                (patient_id, section_key, action, importance, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                patient_id,
                "decision_override",
                f"override_recorded:{override_action[:50]}:{recommendation_source[:30]}",
                "high",  # override es señal HIGH para review
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
    except Exception as exc:
        logger.debug("Override audit log failed: %s", exc)


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
        logger.debug("NSS resolution failed: %s", exc)
    return None


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
        return False, f"invalid override_reasons: {invalid}. Valid: {sorted(ALLOWED_OVERRIDE_REASONS)}"
    # other_specify requiere free_text
    if "other_specify" in reasons and not str(payload.get("free_text") or "").strip():
        return False, "reason 'other_specify' requires free_text"
    return True, ""


def _compute_audit_signature(payload: dict[str, Any]) -> str:
    """Hash SHA-256 truncado del payload para integridad audit trail."""
    import hashlib
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
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


# ─────────────────────────────────────────────────────────────────────
# REST endpoints
# ─────────────────────────────────────────────────────────────────────


@decision_override_bp.route("/api/decision-override", methods=["POST"])
def record_override():
    """Captura un override event. Body JSON:
    {
      "nss": "...",
      "recommended_action": "...",   (optional)
      "recommended_label": "...",     (optional)
      "recommendation_source": "decision_fusion" | "clinical_compass" | etc.
      "narrative_confidence": 0.0-1.0,
      "override_action": "...",       (optional canonical action id)
      "override_label": "...",         (REQUIRED, qué prescribió de verdad)
      "override_reasons": ["patient_preference", "access_barrier_local"],
      "free_text": "...",              (optional, REQUIRED si "other_specify")
      "clinician_id": "..."            (optional)
    }
    """
    try:
        payload = request.get_json(silent=True) or {}
        valid, error = _validate_override_payload(payload)
        if not valid:
            return jsonify({"success": False, "error": error}), 400

        nss = str(payload.get("nss") or payload.get("patient_nss"))
        patient_id = _resolve_patient_id_from_nss(nss)
        if not patient_id:
            return jsonify({
                "success": False,
                "error": f"Paciente con NSS '{nss}' no encontrado",
            }), 404

        from tracking_db import DB_PATH
        try:
            from prostanet.shared.algorithm_version import FAUBOT_RELEASE
        except Exception:
            FAUBOT_RELEASE = "unknown"

        decided_at = payload.get("decided_at") or datetime.now(timezone.utc).isoformat()
        payload["patient_id"] = patient_id
        payload["decided_at"] = decided_at
        signature = _compute_audit_signature(payload)

        conn = sqlite3.connect(DB_PATH)
        _ensure_override_table(conn)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO clinical_override_event
                (patient_id, decided_at, recommended_action, recommended_label,
                 recommendation_source, narrative_confidence,
                 override_action, override_label, override_reasons_json,
                 free_text, clinician_id, faubot_release, narrative_version,
                 audit_signature)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                patient_id,
                decided_at,
                str(payload.get("recommended_action") or ""),
                str(payload.get("recommended_label") or ""),
                str(payload.get("recommendation_source") or "unknown"),
                float(payload.get("narrative_confidence") or 0.0),
                str(payload.get("override_action") or ""),
                str(payload.get("override_label")),
                json.dumps(payload.get("override_reasons", []), ensure_ascii=False),
                str(payload.get("free_text") or ""),
                str(payload.get("clinician_id") or ""),
                FAUBOT_RELEASE,
                str(payload.get("narrative_version") or "epic48_v1.0"),
                signature,
            ),
        )
        override_id = cur.lastrowid
        conn.commit()

        _audit_override_event(
            conn, patient_id,
            str(payload.get("override_action") or payload.get("override_label", "")),
            str(payload.get("recommendation_source") or "unknown"),
        )
        conn.close()

        return jsonify({
            "success": True,
            "override_id": override_id,
            "patient_id": patient_id,
            "nss": nss,
            "audit_signature": signature,
            "decided_at": decided_at,
            "message": "Override capturado para audit trail + engine learning loop.",
        }), 201
    except Exception as exc:
        logger.exception("Override capture failed")
        return jsonify({"success": False, "error": str(exc)}), 500


@decision_override_bp.route("/api/decision-override/<nss>", methods=["GET"])
def get_override_history(nss: str):
    """Retorna historial de overrides para un paciente, ordenado por decided_at desc."""
    try:
        patient_id = _resolve_patient_id_from_nss(nss)
        if not patient_id:
            return jsonify({
                "success": False,
                "error": f"Paciente con NSS '{nss}' no encontrado",
            }), 404

        from tracking_db import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        _ensure_override_table(conn)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, decided_at, recommended_label, recommendation_source,
                   override_label, override_reasons_json, free_text,
                   narrative_confidence, clinician_id, faubot_release,
                   audit_signature
              FROM clinical_override_event
             WHERE patient_id = ?
             ORDER BY decided_at DESC
             LIMIT 50
            """,
            (patient_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()

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
            "overrides": rows,
        })
    except Exception as exc:
        logger.exception("Override history failed")
        return jsonify({"success": False, "error": str(exc)}), 500


@decision_override_bp.route("/api/decision-override/stats", methods=["GET"])
def get_override_stats():
    """Stats poblacionales: distribución de override reasons + tasa por
    recommendation_source. Foundation para Latin recalibration analytics."""
    try:
        from tracking_db import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        _ensure_override_table(conn)
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

        # Aggregate reasons (JSON parsing per row)
        cur.execute("SELECT override_reasons_json FROM clinical_override_event")
        reason_counter: dict[str, int] = {}
        for row in cur.fetchall():
            try:
                reasons = json.loads(row[0] or "[]")
                for r in reasons:
                    reason_counter[r] = reason_counter.get(r, 0) + 1
            except Exception:
                continue

        by_reason = sorted(
            [{"reason": r, "count": c} for r, c in reason_counter.items()],
            key=lambda x: x["count"], reverse=True,
        )

        conn.close()

        return jsonify({
            "success": True,
            "total_overrides": total,
            "by_recommendation_source": by_source,
            "by_reason": by_reason,
            "allowed_reasons": sorted(ALLOWED_OVERRIDE_REASONS),
        })
    except Exception as exc:
        logger.exception("Override stats failed")
        return jsonify({"success": False, "error": str(exc)}), 500


__all__ = ["decision_override_bp", "ALLOWED_OVERRIDE_REASONS"]
