from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from prostanet.domains.patient_tracking.cohort_analytics import (
    ADVANCED_STATES,
    DIAGNOSTIC_STATES,
    POSTLOCAL_STATES,
    compute_patient_cohort_completeness,
    compute_patient_endpoint_readiness,
    compute_patient_research_readiness,
)
from prostanet.domains.patient_tracking.survival_endpoints import SurvivalEndpointService

try:
    from lifelines import CoxPHFitter
except Exception:  # pragma: no cover - graceful fallback when dependency is missing
    CoxPHFitter = None


def _reconciled_state(record: dict[str, Any]) -> str:
    return str(
        record.get("reconciled_state")
        or (record.get("latest_assessment") or {}).get("state")
        or (record.get("prior_history") or {}).get("current_state")
        or "diagnostic_workup"
    )


def _safe_date(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def _age_at_diagnosis(record: dict[str, Any]) -> float | None:
    identity = record.get("identity") or {}
    dob = _safe_date(identity.get("dob"))
    dx = _safe_date(identity.get("diagnosis_date"))
    if not dob or not dx:
        return None
    return round((dx - dob).days / 365.25, 1)


def _latest(items: list[dict[str, Any]], *keys: str) -> dict[str, Any]:
    if not items:
        return {}
    for key in keys:
        dated = [item for item in items if item.get(key)]
        if dated:
            return sorted(dated, key=lambda item: str(item.get(key)), reverse=True)[0]
    return items[-1]


def _build_covariates(record: dict[str, Any], state: str) -> dict[str, Any]:
    latest_biopsy = _latest(record.get("biopsies") or [], "biopsy_date")
    baseline = record.get("baseline") or {}
    followups = record.get("follow_ups") or []
    latest_followup = _latest(followups, "visit_date")
    latest_treatment = _latest(record.get("treatments") or [], "start_date")
    bone_profile = record.get("skeletal_event_profile") or {}
    upgrade_panel = ((record.get("risk_tools_panel") or {}).get("upgrade_panel") if isinstance(record.get("risk_tools_panel"), dict) else {}) or {}

    isup = latest_biopsy.get("isup_grade") or baseline.get("isup_grade") or record.get("surgery", {}).get("pathological_isup")
    metastatic_profile = baseline.get("metastatic_profile") or latest_followup.get("metastatic_profile") or {}
    bone_count = metastatic_profile.get("bone_total_count") or baseline.get("metastasis_count") or latest_followup.get("metastasis_count") or bone_profile.get("bone_metastasis_count")

    return {
        "age_at_diagnosis": _age_at_diagnosis(record),
        "high_grade_biology": 1 if isup and int(isup) >= 4 else 0,
        "advanced_state": 1 if state in ADVANCED_STATES else 0,
        "postlocal_state": 1 if state in POSTLOCAL_STATES else 0,
        "bone_metastatic_burden": 1 if bone_count and float(bone_count) > 0 else 0,
        "has_systemic_therapy": 1 if latest_treatment else 0,
        "pathologic_upgrade": 1 if ((upgrade_panel.get("pathologic_upgrade") or {}).get("active")) else 0,
    }


def build_survival_tidy_dataset(
    records: list[dict[str, Any]],
    endpoint_type: str,
    *,
    state_filter: str | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        state = _reconciled_state(record)
        if state_filter and state != state_filter:
            continue
        status = SurvivalEndpointService.compute_endpoints(record, state)
        endpoint = next((item for item in status.endpoints if item.endpoint_type == endpoint_type), None)
        if endpoint is None or endpoint.duration_months is None:
            continue
        row = {
            "patient_id": (record.get("identity") or {}).get("id"),
            "patient_uid": f"PT-{(record.get('identity') or {}).get('id', '')}",
            "nss_hash_hint": str((record.get("identity") or {}).get("nss", ""))[-4:],
            "state": state,
            "endpoint_type": endpoint_type,
            "duration_months": endpoint.duration_months,
            "event_observed": 0 if endpoint.censored else 1,
            "start_date": endpoint.start_date,
            "end_date": endpoint.end_date,
            "end_event": endpoint.end_event,
        }
        row.update(_build_covariates(record, state))
        rows.append(row)
    return rows


def build_survival_curve_payload(
    records: list[dict[str, Any]],
    endpoint_type: str,
    *,
    state_filter: str | None = None,
) -> dict[str, Any]:
    tidy_rows = build_survival_tidy_dataset(records, endpoint_type, state_filter=state_filter)
    km = SurvivalEndpointService.generate_kaplan_meier_points(tidy_rows, endpoint_type)
    return {
        "endpoint_type": endpoint_type,
        "state_filter": state_filter or "",
        "n_patients": len(tidy_rows),
        "n_events": sum(int(row.get("event_observed") or 0) for row in tidy_rows),
        "curve": km,
        "dataset": tidy_rows,
    }


def build_cox_analysis_payload(
    records: list[dict[str, Any]],
    endpoint_type: str,
    *,
    state_filter: str | None = None,
) -> dict[str, Any]:
    tidy_rows = build_survival_tidy_dataset(records, endpoint_type, state_filter=state_filter)
    if len(tidy_rows) < 5 or sum(int(row.get("event_observed") or 0) for row in tidy_rows) < 2:
        return {
            "endpoint_type": endpoint_type,
            "state_filter": state_filter or "",
            "status": "insufficient_data",
            "dataset_rows": len(tidy_rows),
            "events": sum(int(row.get("event_observed") or 0) for row in tidy_rows),
            "cox_model": {},
            "dataset": tidy_rows,
        }
    if CoxPHFitter is None:
        return {
            "endpoint_type": endpoint_type,
            "state_filter": state_filter or "",
            "status": "lifelines_unavailable",
            "dataset_rows": len(tidy_rows),
            "events": sum(int(row.get("event_observed") or 0) for row in tidy_rows),
            "cox_model": {},
            "dataset": tidy_rows,
        }
    df = pd.DataFrame(tidy_rows)
    covariates = [
        "age_at_diagnosis",
        "high_grade_biology",
        "advanced_state",
        "postlocal_state",
        "bone_metastatic_burden",
        "has_systemic_therapy",
        "pathologic_upgrade",
    ]
    usable_covariates = []
    for covariate in covariates:
        if covariate not in df.columns:
            continue
        series = pd.to_numeric(df[covariate], errors="coerce")
        if series.notna().sum() < 3:
            continue
        if series.nunique(dropna=True) <= 1:
            continue
        df[covariate] = series.fillna(series.median())
        usable_covariates.append(covariate)
    if not usable_covariates:
        return {
            "endpoint_type": endpoint_type,
            "state_filter": state_filter or "",
            "status": "no_usable_covariates",
            "dataset_rows": len(tidy_rows),
            "events": sum(int(row.get("event_observed") or 0) for row in tidy_rows),
            "cox_model": {},
            "dataset": tidy_rows,
        }
    fitter = CoxPHFitter()
    fitter.fit(
        df[["duration_months", "event_observed", *usable_covariates]],
        duration_col="duration_months",
        event_col="event_observed",
    )
    summary = fitter.summary.reset_index().rename(columns={"index": "covariate"}).to_dict(orient="records")
    return {
        "endpoint_type": endpoint_type,
        "state_filter": state_filter or "",
        "status": "ok",
        "dataset_rows": len(tidy_rows),
        "events": sum(int(row.get("event_observed") or 0) for row in tidy_rows),
        "covariates": usable_covariates,
        "cox_model": {
            "concordance_index": getattr(fitter, "concordance_index_", None),
            "summary": summary,
        },
        "dataset": tidy_rows,
    }


def build_domain_completeness_payload(records: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    domains = {
        "survival_status_complete": 0,
        "survival_anchor_events": 0,
        "structured_biopsy_sessions": 0,
        "active_surveillance_operational": 0,
        "skeletal_events_structured": 0,
        "bone_health_structured": 0,
        "radiotherapy_courses_detailed": 0,
    }
    for record in records:
        state = _reconciled_state(record)
        completeness = compute_patient_cohort_completeness(record, state)
        readiness = compute_patient_research_readiness(record, state)
        endpoints = compute_patient_endpoint_readiness(record, state)
        survival_ok = bool((record.get("survival_status_detail") or {}).get("vital_status") and (record.get("survival_status_detail") or {}).get("last_contact_date"))
        anchor_ok = bool(record.get("survival_anchor_events"))
        biopsy_ok = bool(record.get("structured_biopsy_sessions"))
        as_ok = bool((record.get("active_surveillance_protocol") or {}).get("schedule"))
        sre_ok = bool(record.get("skeletal_events"))
        bone_ok = bool(record.get("bone_health_snapshots") or record.get("bone_modifying_agent_courses"))
        rt_ok = bool(record.get("radiotherapy_courses_detailed"))
        domains["survival_status_complete"] += int(survival_ok)
        domains["survival_anchor_events"] += int(anchor_ok)
        domains["structured_biopsy_sessions"] += int(biopsy_ok)
        domains["active_surveillance_operational"] += int(as_ok)
        domains["skeletal_events_structured"] += int(sre_ok)
        domains["bone_health_structured"] += int(bone_ok)
        domains["radiotherapy_courses_detailed"] += int(rt_ok)
        rows.append(
            {
                "patient_id": (record.get("identity") or {}).get("id"),
                "state": state,
                "survival_status_complete": survival_ok,
                "survival_anchor_events": anchor_ok,
                "structured_biopsy_sessions": biopsy_ok,
                "active_surveillance_operational": as_ok,
                "skeletal_events_structured": sre_ok,
                "bone_health_structured": bone_ok,
                "radiotherapy_courses_detailed": rt_ok,
                "cohort_completeness_pct": completeness.get("overall_pct"),
                "research_readiness_pct": readiness.get("score"),
                "endpoint_readiness_pct": endpoints.get("overall_pct"),
            }
        )
    return {
        "total_patients": len(records),
        "domain_counts": domains,
        "rows": rows,
    }
