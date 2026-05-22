"""data_integrity_routes.py — EPIC 45 FAUBOT CXXX REST endpoints

Endpoints expuestos:

  GET  /api/data-integrity/audit                     — Audit poblacional (dry-run)
  GET  /api/data-integrity/<nss>                     — Snapshot de un paciente
  POST /api/data-integrity/<nss>/resolve             — Aplica auto-resolución (requiere confirm=auto)
  POST /api/data-integrity/audit/apply               — Audit + apply poblacional (requiere admin token)

Patrón paralelo a godibot_routes.py — usa el mismo connection pattern a
prostanet_tracking.db y devuelve JSON tipado con error responses
estructurados `{"success": bool, ...}`.

Reusa `prostanet.regulatory.clinical.factspec_alias_audit` como capa de
dominio. Esta capa es solo HTTP framing + validación + auth scope.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

data_integrity_bp = Blueprint("data_integrity", __name__)


# ──────────────────────────────────────────────────────────────────────
# Storage helpers (paralelos a godibot_routes pattern)
# ──────────────────────────────────────────────────────────────────────

DB_PATH = Path(__file__).parent.parent.parent / "prostanet_tracking.db"


def _get_conn() -> sqlite3.Connection:
    """SQLite connection con row_factory para column access by name."""
    conn = sqlite3.connect(str(DB_PATH))
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


# ──────────────────────────────────────────────────────────────────────
# GET /api/data-integrity/audit — population dry-run
# ──────────────────────────────────────────────────────────────────────


@data_integrity_bp.route("/api/data-integrity/audit", methods=["GET"])
def get_population_audit() -> Any:
    """Corre auditor sobre TODOS los pacientes en dry-run.

    Returns summary {patients_checked, patients_with_contradictions,
    total_contradictions, by_severity, by_alias_group, patient_summaries[]}.

    Query params:
      ?include_resolutions=1 → incluye también las propuestas detalladas
        (puede ser grande — solo usar en dashboards admin).
    """
    from prostanet.regulatory.clinical.factspec_alias_audit import (
        audit_all_patients,
        resolve_all_patients,
    )

    include_resolutions = request.args.get("include_resolutions", "").strip() in ("1", "true", "yes")
    conn = _get_conn()
    try:
        if include_resolutions:
            result = resolve_all_patients(conn, dry_run=True)
            return jsonify({
                "success": True,
                "endpoint": "/api/data-integrity/audit",
                "mode": "population_dry_run_with_resolutions",
                **result,
            })
        summary = audit_all_patients(conn)
        return jsonify({
            "success": True,
            "endpoint": "/api/data-integrity/audit",
            "mode": "population_dry_run",
            **summary,
        })
    except Exception as exc:
        logger.exception("get_population_audit failed: %s", exc)
        return jsonify({
            "success": False,
            "error": f"audit failed: {exc}",
        }), 500
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────
# GET /api/data-integrity/<nss> — snapshot de un paciente
# ──────────────────────────────────────────────────────────────────────


@data_integrity_bp.route("/api/data-integrity/<nss>", methods=["GET"])
def get_patient_data_integrity(nss: str) -> Any:
    """Snapshot de integridad de datos para un paciente.

    Returns:
      200 → {success, nss, patient_id, contradictions_detected[],
             severity_summary, needs_clinician_review, resolutions_history[],
             last_resolution_at}
      404 → si el NSS no resuelve a un paciente
    """
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
                "error": f"NSS '{nss}' no encontrado en patient_identity",
            }), 404

        contradictions = audit_patient(conn, patient_id)
        resolutions_history = list_recent_resolutions_for_patient(
            conn, patient_id, limit=20,
        )
        severity_summary = {"high": 0, "medium": 0}
        for c in contradictions:
            severity_summary[c.severity] = severity_summary.get(c.severity, 0) + 1

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
            "last_resolution_at": resolutions_history[0]["resolved_at"] if resolutions_history else None,
        })
    except Exception as exc:
        logger.exception("get_patient_data_integrity failed for nss=%s: %s", nss, exc)
        return jsonify({
            "success": False,
            "error": f"snapshot failed: {exc}",
        }), 500
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────
# POST /api/data-integrity/<nss>/resolve — aplica auto-resolución
# ──────────────────────────────────────────────────────────────────────


@data_integrity_bp.route("/api/data-integrity/<nss>/resolve", methods=["POST"])
def post_resolve_patient(nss: str) -> Any:
    """Aplica auto-resolución de TODAS las contradicciones del paciente.

    Body JSON (opcional):
      {
        "confirm": "auto" (required),  # confirmation token
        "alias_group_canonical": "metastatic_stage_resolved" (optional),
                                  # si está, solo resuelve ese grupo
      }

    Query params (fallback si no hay body JSON):
      ?confirm=auto

    Returns:
      200 → {success, nss, patient_id, resolutions_applied[], applied_count}
      400 → confirm token missing
      404 → NSS no encontrado
    """
    from prostanet.regulatory.clinical.factspec_alias_audit import (
        audit_patient,
        propose_resolution,
        apply_resolution,
    )

    body = request.get_json(silent=True) or {}
    confirm = (body.get("confirm") or request.args.get("confirm") or "").strip()
    if confirm != "auto":
        return jsonify({
            "success": False,
            "error": "confirm=auto token required to apply auto-resolution",
            "hint": "POST con body JSON {\"confirm\": \"auto\"} o query ?confirm=auto",
        }), 400

    filter_group = (body.get("alias_group_canonical") or "").strip() or None

    conn = _get_conn()
    try:
        patient_id = _nss_to_patient_id(conn, nss)
        if patient_id is None:
            return jsonify({
                "success": False,
                "error": f"NSS '{nss}' no encontrado",
            }), 404

        contradictions = audit_patient(conn, patient_id)
        if filter_group:
            contradictions = [
                c for c in contradictions
                if c.alias_group_canonical == filter_group
            ]
        resolutions_applied = []
        for c in contradictions:
            resolution = propose_resolution(c)
            apply_resolution(conn, resolution)
            resolutions_applied.append(resolution.to_dict())

        return jsonify({
            "success": True,
            "nss": nss,
            "patient_id": patient_id,
            "alias_group_filter": filter_group,
            "resolutions_applied": resolutions_applied,
            "applied_count": len(resolutions_applied),
            "next_action": f"/patient/{nss}?v=2 (re-render perfil con facts limpios)",
        })
    except Exception as exc:
        logger.exception("post_resolve_patient failed for nss=%s: %s", nss, exc)
        return jsonify({
            "success": False,
            "error": f"resolve failed: {exc}",
        }), 500
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────
# POST /api/data-integrity/audit/apply — population-wide apply (admin)
# ──────────────────────────────────────────────────────────────────────


@data_integrity_bp.route("/api/data-integrity/audit/apply", methods=["POST"])
def post_population_apply() -> Any:
    """Aplica auto-resolución sobre TODA la población.

    Requiere body JSON con `{"confirm": "ALL_PATIENTS"}` como safety token.
    Sin este token retorna 400 incluso si auth es correcto — guard contra
    aplicar accidentalmente a producción.

    Returns:
      200 → {success, audit_summary, applied_count, resolutions[]}
      400 → confirm token missing/wrong
    """
    from prostanet.regulatory.clinical.factspec_alias_audit import resolve_all_patients

    body = request.get_json(silent=True) or {}
    confirm = (body.get("confirm") or "").strip()
    if confirm != "ALL_PATIENTS":
        return jsonify({
            "success": False,
            "error": "confirm=ALL_PATIENTS token required for population-wide apply",
            "hint": "POST con body JSON {\"confirm\": \"ALL_PATIENTS\"} para confirmar.",
        }), 400

    conn = _get_conn()
    try:
        result = resolve_all_patients(conn, dry_run=False)
        return jsonify({
            "success": True,
            "endpoint": "/api/data-integrity/audit/apply",
            "mode": "population_apply",
            **result,
        })
    except Exception as exc:
        logger.exception("post_population_apply failed: %s", exc)
        return jsonify({
            "success": False,
            "error": f"population apply failed: {exc}",
        }), 500
    finally:
        conn.close()
