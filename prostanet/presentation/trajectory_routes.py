"""trajectory_routes — EPIC 47 (FAUBOT CXXXV).

Endpoint REST GET para trajectory dashboard. Permite a la UI fetcheаr
trajectory bundle vía AJAX sin re-renderizar todo el perfil (útil para
"recargar" después de capturar nueva visita o lab).

GET /api/trajectory/<nss>
  → {success, patient_id, nss, trajectory: {available, series, kinetics, alerts, ...}}

Cada call queda audited en clinical_view_audit con section_key='trajectory'
+ action='trajectory_fetched:v<engine_version>' para trazabilidad.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from flask import Blueprint, jsonify

logger = logging.getLogger(__name__)

trajectory_bp = Blueprint("trajectory", __name__)


def _audit_trajectory_fetch(patient_id: int, engine_version: str) -> None:
    """Best-effort audit log para reproducibilidad."""
    try:
        import sqlite3
        from tracking_db import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO clinical_view_audit
                (patient_id, section_key, action, importance, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                patient_id,
                "trajectory",
                f"trajectory_fetched:{engine_version}",
                "low",
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.debug("Trajectory fetch audit log failed: %s", exc)


@trajectory_bp.route("/api/trajectory/<nss>", methods=["GET"])
def get_trajectory(nss: str):
    """Retorna trajectory bundle completo para un paciente identificado por NSS.

    404 si NSS no existe. 500 si engine falla catastróficamente (no debería
    ocurrir — engine ya es fail-safe).
    """
    try:
        import tracking_db
        from prostanet.domains.patient_tracking.trajectory_engine import (
            build_trajectory_bundle,
        )
        from prostanet.domains.patient_tracking.trajectory_alert_engine import (
            evaluate_trajectory_alerts,
        )

        core = tracking_db.load_patient_record_core(nss)
        if not core:
            return jsonify({
                "success": False,
                "error": f"Paciente con NSS '{nss}' no encontrado",
            }), 404

        record = tracking_db.build_patient_record_derivatives(core)
        if not record:
            return jsonify({
                "success": False,
                "error": "Patient derivatives no disponibles",
            }), 500

        patient_id = int((record.get("identity") or {}).get("id") or 0)
        bundle = build_trajectory_bundle(record)

        # Patient context (simplificado para REST — view model tiene más rico)
        latest_treatment = (record.get("treatments") or [{}])[-1] if record.get("treatments") else {}
        treatment_blob = " ".join(
            str(v or "").lower()
            for v in (
                latest_treatment.get("class"),
                latest_treatment.get("regimen_class"),
                latest_treatment.get("scheme"),
                latest_treatment.get("drug_scheme"),
            )
        )
        ctx = {
            "state_resolved": str((record.get("latest_assessment") or {}).get("state") or "").lower(),
            "on_arsi": any(a in treatment_blob for a in ("abi", "enza", "apa", "daro", "arsi", "arpi")),
            "on_adt": any(a in treatment_blob for a in ("adt", "lhrh", "agonist", "antagonist")),
            "last_imaging_status": "",
        }
        bundle["alerts"] = evaluate_trajectory_alerts(bundle, ctx) if bundle.get("available") else []

        # Audit (best-effort, non-blocking)
        _audit_trajectory_fetch(patient_id, bundle.get("engine_version", "epic47_v1.0"))

        return jsonify({
            "success": True,
            "patient_id": patient_id,
            "nss": nss,
            "trajectory": bundle,
        })
    except Exception as exc:
        logger.exception("Trajectory endpoint failed for nss=%s", nss)
        return jsonify({"success": False, "error": str(exc)}), 500


__all__ = ["trajectory_bp"]
