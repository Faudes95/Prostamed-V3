"""data_integrity_routes.py — EPIC 45 FAUBOT CXXX + Sprint 6 hardening (CXLIV)

Endpoints expuestos:

  GET  /api/data-integrity/audit                     — Audit poblacional (admin only)
  GET  /api/data-integrity/<nss>                     — Snapshot de un paciente (clinician)
  POST /api/data-integrity/<nss>/resolve             — Aplica auto-resolución (clinician + confirm token)
  POST /api/data-integrity/audit/apply               — Audit + apply poblacional (admin + confirm token)

Patrón paralelo a godibot_routes.py — usa el mismo connection pattern a
prostanet_tracking.db y devuelve JSON tipado con error responses
estructurados `{"success": bool, ...}`.

Reusa `prostanet.regulatory.clinical.factspec_alias_audit` como capa de
dominio. Esta capa es solo HTTP framing + validación + auth scope.

Sprint 6 hardening:
  - C4: @require_admin en /audit/apply (antes solo magic string `confirm=ALL_PATIENTS`)
  - C5: @require_clinician en /<nss>/resolve (antes solo magic string `confirm=auto`)
  - C2/C6: GET /audit y GET /<nss> requieren auth + no leak str(exc)
  - HIGH: AUDIT TRAIL en todos los endpoints (antes era el ÚNICO archivo sin audit)
  - HIGH: DB_PATH desde tracking_db (consistencia con resto del proyecto)
  - HIGH: algorithm_version snapshot en responses
  - HIGH: explicit atomic transaction en /resolve loop (antes seq sin rollback)
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any

from flask import Blueprint, jsonify, request

# Sprint 6 HIGH: imports module-level + consistencia DB_PATH
import tracking_db
from prostanet.shared.api_auth import (
    require_clinician, require_admin, current_api_user_id, current_api_user_role,
)

logger = logging.getLogger(__name__)

data_integrity_bp = Blueprint("data_integrity", __name__)


# ──────────────────────────────────────────────────────────────────────
# Storage helpers (paralelos a godibot_routes pattern)
# Sprint 6 HIGH: DB_PATH desde tracking_db (no calc path local)
# ──────────────────────────────────────────────────────────────────────


def _get_conn() -> sqlite3.Connection:
    """SQLite connection con row_factory + timeout (Sprint 6 MED)."""
    conn = sqlite3.connect(str(tracking_db.DB_PATH), timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def _nss_to_patient_id(conn: sqlite3.Connection, nss: str) -> int | None:
    """Resuelve NSS al patient_id (int) de patient_identity."""
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM patient_identity WHERE nss = ? LIMIT 1",
        (str(nss).strip(),),
    )
    row = cur.fetchone()
    return int(row["id"]) if row else None


def _faubot_release_snapshot() -> str:
    try:
        from prostanet.shared.algorithm_version import FAUBOT_RELEASE
        return str(FAUBOT_RELEASE)
    except Exception:
        return "unknown"


# Sprint 6 HIGH: AUDIT TRAIL — antes este archivo era el único sin logging.
# §820.30 exige trazabilidad de operaciones de mutación clínica.
def _audit_data_integrity_operation(
    operation: str,
    patient_id: int | None,
    actor_user_id: int | None,
    actor_role: str | None,
    scope: str = "single",
    extra: str = "",
) -> None:
    """Registra en clinical_view_audit cada llamada a data_integrity.

    Args:
        operation: audit|resolve|audit_apply|snapshot
        patient_id: target patient (None for population-wide ops)
        actor_user_id, actor_role: viene del session via api_auth
        scope: 'single' | 'population' | 'unknown'
        extra: detail string (alias_group filter, count of resolutions, etc.)
    """
    conn = None
    try:
        conn = sqlite3.connect(str(tracking_db.DB_PATH), timeout=5.0)
        cur = conn.cursor()
        action_parts = [f"data_integrity:{operation}:{scope}"]
        if actor_user_id:
            action_parts.append(f"user_{actor_user_id}")
        if actor_role:
            action_parts.append(f"role_{actor_role}")
        if extra:
            action_parts.append(extra[:80])
        action = ":".join(action_parts)
        # Para operaciones poblacionales usamos patient_id=0 como sentinel
        cur.execute(
            """
            INSERT INTO clinical_view_audit
                (patient_id, section_key, action, importance, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                patient_id if patient_id else 0,
                "data_integrity",
                action,
                "high" if operation in ("resolve", "audit_apply") else "medium",
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
    except Exception as exc:
        logger.warning(
            "Data integrity audit log FAILED (REGULATORY) op=%s patient=%s: %s: %s",
            operation, patient_id, type(exc).__name__, exc,
        )
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


# ──────────────────────────────────────────────────────────────────────
# GET /api/data-integrity/audit — population dry-run (Sprint 6: admin only)
# ──────────────────────────────────────────────────────────────────────


@data_integrity_bp.route("/api/data-integrity/audit", methods=["GET"])
@require_admin
def get_population_audit() -> Any:
    """Corre auditor sobre TODOS los pacientes en dry-run.

    Sprint 6 C2: @require_admin — operación poblacional revela patrones
    sistémicos que son IP institucional.

    Query params:
      ?include_resolutions=1 → incluye también las propuestas detalladas
    """
    faubot = _faubot_release_snapshot()
    actor_user_id = current_api_user_id()
    actor_role = current_api_user_role()

    from prostanet.regulatory.clinical.factspec_alias_audit import (
        audit_all_patients,
        resolve_all_patients,
    )

    # Sprint 6 LOW: case-insensitive boolean param
    include_resolutions = (
        request.args.get("include_resolutions", "").strip().lower()
        in ("1", "true", "yes", "on")
    )

    # Audit BEFORE execution (regulatorio)
    _audit_data_integrity_operation(
        "audit", None, actor_user_id, actor_role, scope="population",
        extra=f"include_resolutions={include_resolutions}",
    )

    conn = _get_conn()
    try:
        if include_resolutions:
            result = resolve_all_patients(conn, dry_run=True)
            return jsonify({
                "success": True,
                "endpoint": "/api/data-integrity/audit",
                "mode": "population_dry_run_with_resolutions",
                "faubot_release": faubot,
                **result,
            })
        summary = audit_all_patients(conn)
        return jsonify({
            "success": True,
            "endpoint": "/api/data-integrity/audit",
            "mode": "population_dry_run",
            "faubot_release": faubot,
            **summary,
        })
    except Exception:
        # Sprint 6 C6: NO leak exc al cliente
        logger.exception("get_population_audit failed")
        return jsonify({
            "success": False,
            "error": "audit_failed",
            "message": "Error temporal al ejecutar audit poblacional.",
            "faubot_release": faubot,
        }), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ──────────────────────────────────────────────────────────────────────
# GET /api/data-integrity/<nss> — snapshot de un paciente
# ──────────────────────────────────────────────────────────────────────


@data_integrity_bp.route("/api/data-integrity/<nss>", methods=["GET"])
@require_clinician
def get_patient_data_integrity(nss: str) -> Any:
    """Snapshot de integridad de datos para un paciente.

    Sprint 6 C2: @require_clinician (read PHI).
    """
    faubot = _faubot_release_snapshot()
    actor_user_id = current_api_user_id()
    actor_role = current_api_user_role()

    from prostanet.regulatory.clinical.factspec_alias_audit import (
        audit_patient,
        list_recent_resolutions_for_patient,
    )

    conn = _get_conn()
    try:
        patient_id = _nss_to_patient_id(conn, nss)
        if patient_id is None:
            return jsonify({
                "success": False,
                "error": "patient_not_found",
                "message": f"NSS '{nss}' no registrado",
                "faubot_release": faubot,
            }), 404

        _audit_data_integrity_operation(
            "snapshot", patient_id, actor_user_id, actor_role, scope="single",
        )

        contradictions = audit_patient(conn, patient_id)
        resolutions_history = list_recent_resolutions_for_patient(
            conn, patient_id, limit=20,
        )
        # Sprint 6 MED: severity enum cerrada
        severity_summary = {"high": 0, "medium": 0, "low": 0, "critical": 0}
        for c in contradictions:
            sev = c.severity if c.severity in severity_summary else "low"
            severity_summary[sev] = severity_summary.get(sev, 0) + 1

        return jsonify({
            "success": True,
            "nss": nss,
            "patient_id": patient_id,
            "contradictions_detected": [c.to_dict() for c in contradictions],
            "contradictions_count": len(contradictions),
            "severity_summary": severity_summary,
            "needs_clinician_review": any(c.severity == "high" for c in contradictions),
            "resolutions_history": resolutions_history,
            "resolutions_count": len(resolutions_history),
            "last_resolution_at": (
                resolutions_history[0]["resolved_at"]
                if resolutions_history else None
            ),
            "faubot_release": faubot,
        })
    except Exception:
        logger.exception("get_patient_data_integrity failed for nss=%s", nss)
        return jsonify({
            "success": False,
            "error": "snapshot_failed",
            "message": "Error temporal al construir snapshot.",
            "faubot_release": faubot,
        }), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ──────────────────────────────────────────────────────────────────────
# POST /api/data-integrity/<nss>/resolve — aplica auto-resolución
# ──────────────────────────────────────────────────────────────────────


@data_integrity_bp.route("/api/data-integrity/<nss>/resolve", methods=["POST"])
@require_clinician
def post_resolve_patient(nss: str) -> Any:
    """Aplica auto-resolución de TODAS las contradicciones del paciente.

    Sprint 6 C5: @require_clinician (mutación clínica per-paciente).

    Body JSON (opcional):
      {
        "confirm": "auto",  # safety token (defense in depth)
        "alias_group_canonical": "metastatic_stage_resolved" (optional)
      }

    Sprint 6 H: ATOMIC — todas las resoluciones en una transaction.
    Si una falla, rollback de TODAS (no estado mixto).
    """
    faubot = _faubot_release_snapshot()
    actor_user_id = current_api_user_id()
    actor_role = current_api_user_role()

    from prostanet.regulatory.clinical.factspec_alias_audit import (
        audit_patient,
        propose_resolution,
        apply_resolution,
    )

    body = request.get_json(silent=True) or {}
    # Sprint 6 MED: confirm token solo en body (no query) — POST debería tener body
    confirm = (body.get("confirm") or "").strip()
    if confirm != "auto":
        return jsonify({
            "success": False,
            "error": "confirm_token_required",
            "message": "POST con body JSON {\"confirm\": \"auto\"} requerido.",
            "faubot_release": faubot,
        }), 400

    filter_group = (body.get("alias_group_canonical") or "").strip() or None

    conn = _get_conn()
    try:
        patient_id = _nss_to_patient_id(conn, nss)
        if patient_id is None:
            return jsonify({
                "success": False,
                "error": "patient_not_found",
                "message": f"NSS '{nss}' no registrado",
                "faubot_release": faubot,
            }), 404

        contradictions = audit_patient(conn, patient_id)
        if filter_group:
            contradictions = [
                c for c in contradictions
                if c.alias_group_canonical == filter_group
            ]

        # Sprint 6 H: explicit transaction — apply ATOMIC sequence
        resolutions_applied = []
        try:
            conn.execute("BEGIN")
            for c in contradictions:
                resolution = propose_resolution(c)
                apply_resolution(conn, resolution)
                resolutions_applied.append(resolution.to_dict())
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise

        # Audit AFTER successful commit
        _audit_data_integrity_operation(
            "resolve", patient_id, actor_user_id, actor_role, scope="single",
            extra=f"applied={len(resolutions_applied)}_filter={filter_group or 'none'}",
        )

        return jsonify({
            "success": True,
            "nss": nss,
            "patient_id": patient_id,
            "alias_group_filter": filter_group,
            "resolutions_applied": resolutions_applied,
            "applied_count": len(resolutions_applied),
            "faubot_release": faubot,
        })
    except Exception:
        logger.exception("post_resolve_patient failed for nss=%s", nss)
        return jsonify({
            "success": False,
            "error": "resolve_failed",
            "message": "Error temporal al aplicar resoluciones.",
            "faubot_release": faubot,
        }), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ──────────────────────────────────────────────────────────────────────
# POST /api/data-integrity/audit/apply — population-wide apply (admin)
# ──────────────────────────────────────────────────────────────────────


@data_integrity_bp.route("/api/data-integrity/audit/apply", methods=["POST"])
@require_admin
def post_population_apply() -> Any:
    """Aplica auto-resolución sobre TODA la población.

    Sprint 6 C4 CATASTROPHIC FIX:
      Antes: "auth" era string mágico discoverable `confirm=ALL_PATIENTS`
      Ahora: @require_admin verificado contra DB role + token de defensa en profundidad

    Requiere TANTO admin auth COMO confirm token (belt + suspenders para
    operación irreversible que muta facts clínicos de toda la población).
    """
    faubot = _faubot_release_snapshot()
    actor_user_id = current_api_user_id()
    actor_role = current_api_user_role()

    from prostanet.regulatory.clinical.factspec_alias_audit import resolve_all_patients

    body = request.get_json(silent=True) or {}
    confirm = (body.get("confirm") or "").strip()
    if confirm != "ALL_PATIENTS":
        return jsonify({
            "success": False,
            "error": "confirm_token_required",
            "message": "POST con body JSON {\"confirm\": \"ALL_PATIENTS\"} requerido (defense in depth).",
            "faubot_release": faubot,
        }), 400

    # Audit BEFORE — operation poblacional irreversible
    _audit_data_integrity_operation(
        "audit_apply", None, actor_user_id, actor_role, scope="population",
        extra="population_wide_mutation",
    )

    conn = _get_conn()
    try:
        result = resolve_all_patients(conn, dry_run=False)
        return jsonify({
            "success": True,
            "endpoint": "/api/data-integrity/audit/apply",
            "mode": "population_apply",
            "faubot_release": faubot,
            "actor_user_id": actor_user_id,
            "actor_role": actor_role,
            **result,
        })
    except Exception:
        logger.exception("post_population_apply failed")
        return jsonify({
            "success": False,
            "error": "population_apply_failed",
            "message": "Error temporal al aplicar resoluciones poblacionales.",
            "faubot_release": faubot,
        }), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass


__all__ = ["data_integrity_bp"]
