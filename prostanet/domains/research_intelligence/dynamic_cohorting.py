from __future__ import annotations

from typing import Any

import tracking_db

from prostanet.domains.dashboard.dashboard_analytics_service import build_analysis_dataset_payload
from prostanet.domains.research_intelligence.cohort_repository import (
    get_dynamic_cohort,
    list_dynamic_cohorts,
    replace_dynamic_cohort_memberships,
    save_dynamic_cohort,
)


SMART_COHORTS = [
    {
        "title": "mHSPC sincronico de alto volumen",
        "description": "Cohorte inteligente de enfermedad metastásica sensible a la castración de alto volumen sincrónica.",
        "filters": [{"field": "reconciled_state", "op": "eq", "value": "mcspc_high_volume_sync"}],
    },
    {
        "title": "mCRPC con biomarcadores accionables",
        "description": "Pacientes mCRPC con evidencia molecular documentada.",
        "filters": [
            {"field": "reconciled_state", "op": "eq", "value": "m1_crpc"},
            {"field": "molecular_report_available", "op": "truthy", "value": True},
        ],
    },
    {
        "title": "Vigilancia activa protocolizada",
        "description": "Pacientes con protocolo de vigilancia activa operativo.",
        "filters": [{"field": "as_protocol_active", "op": "truthy", "value": True}],
    },
]


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    normalized["molecular_report_available"] = bool(row.get("molecular_report_available"))
    normalized["as_protocol_active"] = bool(row.get("as_protocol_active"))
    return normalized


def _passes_filter(row: dict[str, Any], filt: dict[str, Any]) -> bool:
    field = str(filt.get("field") or "").strip()
    op = str(filt.get("op") or "eq").strip().lower()
    value = filt.get("value")
    current = row.get(field)
    if op == "eq":
        return current == value
    if op == "neq":
        return current != value
    if op == "in":
        return current in set(value or [])
    if op == "contains":
        return str(value or "").lower() in str(current or "").lower()
    if op == "gte":
        return float(current or 0) >= float(value or 0)
    if op == "lte":
        return float(current or 0) <= float(value or 0)
    if op == "truthy":
        return bool(current) is bool(value)
    return False


def evaluate_dynamic_cohort(filters: list[dict[str, Any]]) -> dict[str, Any]:
    payload = build_analysis_dataset_payload()
    rows = [_normalize_row(row) for row in payload.get("analysis_rows", [])]
    matches = [
        row for row in rows
        if all(_passes_filter(row, filt) for filt in filters or [])
    ]
    patient_ids = [int(row["patient_id"]) for row in matches if row.get("patient_id")]
    return {
        "filters": filters or [],
        "size": len(matches),
        "patient_ids": patient_ids,
        "preview": matches[:10],
    }


def seed_smart_cohorts() -> list[dict[str, Any]]:
    existing_titles = {item["title"] for item in list_dynamic_cohorts()}
    seeded = []
    for definition in SMART_COHORTS:
        if definition["title"] in existing_titles:
            continue
        evaluation = evaluate_dynamic_cohort(definition["filters"])
        seeded.append(
            save_dynamic_cohort(
                title=definition["title"],
                description=definition["description"],
                filters=definition["filters"],
                system_defined=True,
                patient_ids=evaluation["patient_ids"],
            )
        )
    return seeded


def create_dynamic_cohort(
    *,
    title: str,
    filters: list[dict[str, Any]],
    description: str = "",
) -> dict[str, Any]:
    evaluation = evaluate_dynamic_cohort(filters)
    return save_dynamic_cohort(
        title=title,
        description=description,
        filters=filters,
        system_defined=False,
        patient_ids=evaluation["patient_ids"],
    )


def refresh_dynamic_cohort(cohort_id: int) -> dict[str, Any]:
    cohort = get_dynamic_cohort(cohort_id)
    if not cohort:
        raise ValueError("Cohorte no encontrada.")
    evaluation = evaluate_dynamic_cohort(cohort.get("filters") or [])
    return replace_dynamic_cohort_memberships(cohort_id, evaluation["patient_ids"])


def list_dynamic_cohort_payload() -> list[dict[str, Any]]:
    seed_smart_cohorts()
    return list_dynamic_cohorts()


def get_dynamic_cohort_payload(cohort_id: int) -> dict[str, Any] | None:
    cohort = refresh_dynamic_cohort(cohort_id)
    if not cohort:
        return None
    records = [tracking_db.get_patient_full_record(patient_id) for patient_id in cohort.get("patient_ids", [])]
    cohort["patients_preview"] = [
        {
            "patient_id": record["identity"]["id"],
            "nss": record["identity"]["nss"],
            "full_name": record["identity"]["full_name"],
            "state": record.get("reconciled_state") or record.get("prior_history", {}).get("current_state"),
        }
        for record in records[:10]
        if record
    ]
    return cohort
