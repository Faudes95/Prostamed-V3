from __future__ import annotations

from typing import Any

import tracking_db

from prostanet.domains.patient_tracking.survival_analysis import build_survival_curve_payload
from prostanet.domains.research_intelligence.dynamic_cohorting import get_dynamic_cohort_payload
from prostanet.domains.research_intelligence.research_repository import persist_json_run


def _records_for_cohort(cohort_id: int | None = None) -> tuple[list[dict[str, Any]], str]:
    if cohort_id is not None:
        cohort = get_dynamic_cohort_payload(int(cohort_id))
        if not cohort:
            raise ValueError("Cohorte no encontrada.")
        records = [tracking_db.get_patient_full_record(patient_id) for patient_id in cohort.get("patient_ids", [])]
        return [record for record in records if record], cohort.get("title") or f"Cohorte {cohort_id}"
    conn = tracking_db._connect()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM patient_identity ORDER BY id ASC")
    patient_ids = [int(row["id"]) for row in cursor.fetchall()]
    conn.close()
    records = [tracking_db.get_patient_full_record(patient_id) for patient_id in patient_ids]
    return [record for record in records if record], "Institucional"


def build_survival_registry_payload(
    *,
    endpoint: str = "OS",
    cohort_id: int | None = None,
    stratify_by: str = "reconciled_state",
) -> dict[str, Any]:
    records, cohort_label = _records_for_cohort(cohort_id)
    payload = build_survival_curve_payload(records, endpoint_type=endpoint)
    response = {
        "endpoint": endpoint,
        "cohort_key": str(cohort_id or "institutional"),
        "cohort_label": cohort_label,
        "curve": payload,
        "cohort_size": len(records),
        "stratify_by": stratify_by,
    }
    persist_json_run("research_survival_snapshots", response, run_key=f"{endpoint}:{cohort_id or 'institutional'}:{stratify_by}")
    return response
