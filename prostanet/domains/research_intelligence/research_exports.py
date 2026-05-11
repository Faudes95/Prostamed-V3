from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from typing import Any

from prostanet.domains.dashboard.dashboard_analytics_service import build_analysis_dataset_payload
from prostanet.domains.research_intelligence.dynamic_cohorting import get_dynamic_cohort_payload


SCHEMA_VERSION = "research_intelligence_v1"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _rows_for_scope(cohort_id: int | None = None) -> tuple[list[dict[str, Any]], str]:
    payload = build_analysis_dataset_payload()
    rows = payload.get("analysis_rows", [])
    if cohort_id is None:
        return rows, "institutional"
    cohort = get_dynamic_cohort_payload(int(cohort_id))
    if not cohort:
        raise ValueError("Cohorte no encontrada.")
    wanted_ids = set(cohort.get("patient_ids", []))
    scoped = [row for row in rows if row.get("patient_id") in wanted_ids]
    return scoped, cohort.get("title") or f"cohort_{cohort_id}"


def build_csv_export_payload(*, cohort_id: int | None = None) -> dict[str, Any]:
    rows, scope_label = _rows_for_scope(cohort_id)
    if not rows:
        return {"export_type": "csv", "record_count": 0, "csv": "", "manifest": _build_manifest("csv", 0, scope_label)}
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=sorted(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return {
        "export_type": "csv",
        "record_count": len(rows),
        "scope_label": scope_label,
        "csv": output.getvalue(),
        "manifest": _build_manifest("csv", len(rows), scope_label),
        "data_dictionary": [{"field": key, "label": key.replace("_", " ").title()} for key in sorted(rows[0].keys())],
    }


def build_redcap_export_payload(*, cohort_id: int | None = None) -> dict[str, Any]:
    rows, scope_label = _rows_for_scope(cohort_id)
    instruments = [
        {"instrument_name": "patient_registry", "form_label": "Registro longitudinal de próstata"},
        {"instrument_name": "survival_outcomes", "form_label": "Outcomes de supervivencia"},
        {"instrument_name": "operational_outcomes", "form_label": "Outcomes operativos"},
    ]
    return {
        "export_type": "redcap",
        "scope_label": scope_label,
        "record_count": len(rows),
        "records": rows,
        "instruments": instruments,
        "manifest": _build_manifest("redcap", len(rows), scope_label),
    }


def build_cdisc_mapping_payload(*, cohort_id: int | None = None) -> dict[str, Any]:
    rows, scope_label = _rows_for_scope(cohort_id)
    mappings = [
        {"source_field": "patient_id", "target_domain": "DM", "target_variable": "USUBJID"},
        {"source_field": "reconciled_state", "target_domain": "DS", "target_variable": "DSTERM"},
        {"source_field": "baseline_psa", "target_domain": "LB", "target_variable": "LBSTRESN"},
        {"source_field": "survival_os_months", "target_domain": "RS", "target_variable": "RSTESTCD"},
    ]
    return {
        "export_type": "cdisc",
        "scope_label": scope_label,
        "record_count": len(rows),
        "mappings": mappings,
        "status": "derived_mapping",
        "manifest": _build_manifest("cdisc", len(rows), scope_label),
    }


def _build_manifest(export_type: str, record_count: int, scope_label: str) -> dict[str, Any]:
    return {
        "export_type": export_type,
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "record_count": int(record_count),
        "scope_label": scope_label,
        "provenance": {
            "source": "analysis_dataset_payload",
            "generated_by": "research_exports",
        },
    }
