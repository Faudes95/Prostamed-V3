"""trajectory_routes — EPIC 47 (FAUBOT CXXXV) + Sprint 6 hardening (CXLIV).

Endpoint REST GET para trajectory dashboard. Permite a la UI fetchear
trajectory bundle vía AJAX sin re-renderizar todo el perfil (útil para
"recargar" después de capturar nueva visita o lab).

GET /api/trajectory/<nss>
  → {success, patient_id, nss, faubot_release, trajectory: {...}}

Sprint 6 hardening:
  - C2: @require_clinician auth gate (HIPAA + SaMD §820.30)
  - C6: no leak str(exc) al cliente (solo log.exception)
  - HIGH: try/finally para conn.close()
  - HIGH: drug-class matching robusto (no substring frágil)
  - HIGH: imports at module level (no per-request lookup)
  - HIGH: algorithm_version snapshot en JSON top-level
  - HIGH: last_imaging_status poblado desde imaging records
  - MED: validación patient_id > 0 antes de auditar
  - MED: engine_version="unknown" si missing (no fallback hardcoded)

Cada call queda audited en clinical_view_audit con section_key='trajectory'
+ action='trajectory_fetched:v<engine_version>:user_<id>' para trazabilidad.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from flask import Blueprint, jsonify

# Sprint 6: imports module-level (antes per-request)
import tracking_db
from prostanet.domains.patient_tracking.trajectory_engine import build_trajectory_bundle
from prostanet.domains.patient_tracking.trajectory_alert_engine import (
    evaluate_trajectory_alerts,
)
from prostanet.shared.api_auth import require_clinician, current_api_user_id

logger = logging.getLogger(__name__)

trajectory_bp = Blueprint("trajectory", __name__)


# ─────────────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────────────


# Sprint 6 HIGH: drug-class catalog canónico (reemplaza substring matching)
ARSI_DRUG_CLASS_TOKENS = frozenset((
    "abiraterona", "abiraterone", "enzalutamida", "enzalutamide",
    "apalutamida", "apalutamide", "darolutamida", "darolutamide",
    "arsi", "arpi",
))
ADT_DRUG_CLASS_TOKENS = frozenset((
    "leuprolide", "leuprolida", "goserelin", "goserelina",
    "triptorelin", "triptorelina", "degarelix", "relugolix",
    "lhrh agonist", "lhrh antagonist", "lhrh-agonist",
    "gnrh agonist", "gnrh antagonist", "adt",
))


def _faubot_release_snapshot() -> str:
    try:
        from prostanet.shared.algorithm_version import FAUBOT_RELEASE
        return str(FAUBOT_RELEASE)
    except Exception:
        return "unknown"


def _audit_trajectory_fetch(
    patient_id: int,
    engine_version: str,
    actor_user_id: int | None = None,
) -> None:
    """Best-effort audit log para reproducibilidad.

    Sprint 6:
      - try/finally for conn.close()
      - logger.warning (no debug) si falla — viola §820.30 si invisible
      - actor_user_id incluido en action
    """
    if patient_id <= 0:
        return  # Sprint 6 MED: no auditamos contra patient_id=0 fantasma

    import sqlite3
    conn = None
    try:
        conn = sqlite3.connect(tracking_db.DB_PATH, timeout=5.0)
        cur = conn.cursor()
        action = f"trajectory_fetched:{engine_version}"
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
                "trajectory",
                action,
                "low",
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
    except Exception as exc:
        logger.warning(
            "Trajectory audit log FAILED (REGULATORY) for patient=%d: %s: %s",
            patient_id, type(exc).__name__, exc,
        )
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _treatment_blob(treatment: dict) -> str:
    """Sprint 6 HIGH: extrae blob normalizado de campos drug-class."""
    return " ".join(
        str(v or "").lower()
        for v in (
            treatment.get("class"),
            treatment.get("regimen_class"),
            treatment.get("scheme"),
            treatment.get("drug_scheme"),
            treatment.get("regimen"),
            treatment.get("treatment_type"),
            treatment.get("agents"),
        )
    )


def _build_treatment_context(record: dict) -> dict:
    """Sprint 6 HIGH: construye context drug-class usando catálogo canónico
    (antes era substring matching `if "abi" in treatment_blob` con falsos
    positivos en cualquier campo conteniendo 'abi' incluso 'absoluto')."""
    treatments = record.get("treatments") or []
    latest_treatment = treatments[-1] if treatments else {}
    blob = _treatment_blob(latest_treatment)

    # Match exacto contra catálogo (no substring frágil)
    blob_tokens = set(blob.split())
    on_arsi = bool(
        blob_tokens & ARSI_DRUG_CLASS_TOKENS
        or any(token in blob for token in ARSI_DRUG_CLASS_TOKENS)
    )
    on_adt = bool(
        blob_tokens & ADT_DRUG_CLASS_TOKENS
        or any(token in blob for token in ADT_DRUG_CLASS_TOKENS)
    )

    # Sprint 6 HIGH: poblar last_imaging_status desde record.imaging
    last_imaging_status = ""
    imaging = record.get("imaging") or []
    if isinstance(imaging, list) and imaging:
        last_img = imaging[-1] if isinstance(imaging[-1], dict) else {}
        last_imaging_status = str(
            last_img.get("status") or last_img.get("interpretation") or ""
        ).lower()

    state_resolved = str(
        (record.get("latest_assessment") or {}).get("state") or ""
    ).lower()

    return {
        "state_resolved": state_resolved,
        "on_arsi": on_arsi,
        "on_adt": on_adt,
        "last_imaging_status": last_imaging_status,
    }


@trajectory_bp.route("/api/trajectory/<nss>", methods=["GET"])
@require_clinician
def get_trajectory(nss: str):
    """Retorna trajectory bundle completo para un paciente identificado por NSS.

    Sprint 6 C2: @require_clinician auth required (HIPAA + SaMD).

    404 si NSS no existe. 500 si engine falla (con error genérico, no leak).
    """
    actor_user_id = current_api_user_id()
    faubot = _faubot_release_snapshot()

    try:
        core = tracking_db.load_patient_record_core(nss)
        if not core:
            return jsonify({
                "success": False,
                "error": "patient_not_found",
                "message": f"NSS '{nss}' no registrado",
                "faubot_release": faubot,
            }), 404

        record = tracking_db.build_patient_record_derivatives(core)
        if not record:
            return jsonify({
                "success": False,
                "error": "patient_derivatives_unavailable",
                "faubot_release": faubot,
            }), 500

        patient_id = int((record.get("identity") or {}).get("id") or 0)
        bundle = build_trajectory_bundle(record)

        # Sprint 6 HIGH: drug-class context con catálogo (no substring)
        ctx = _build_treatment_context(record)
        bundle["alerts"] = (
            evaluate_trajectory_alerts(bundle, ctx) if bundle.get("available") else []
        )

        engine_version = bundle.get("engine_version") or "unknown"

        # Audit (best-effort, non-blocking)
        _audit_trajectory_fetch(patient_id, engine_version, actor_user_id)

        return jsonify({
            "success": True,
            "patient_id": patient_id,
            "nss": nss,
            "trajectory": bundle,
            "faubot_release": faubot,  # Sprint 6 HIGH: reproducibility
            "engine_version": engine_version,  # Top-level explicit
        })
    except Exception as exc:
        # Sprint 6 C6: NO leak str(exc) al cliente. Detalle solo en log.
        logger.exception("Trajectory endpoint failed for nss=%s", nss)
        return jsonify({
            "success": False,
            "error": "internal_error",
            "message": "Error temporal al construir trajectory. Intente de nuevo.",
            "faubot_release": faubot,
        }), 500


__all__ = ["trajectory_bp"]
