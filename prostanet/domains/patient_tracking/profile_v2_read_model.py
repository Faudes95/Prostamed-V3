from __future__ import annotations

from typing import Any


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value or {}) if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value or []) if isinstance(value, list) else []


def _state_from(patient: dict[str, Any], assessment: dict[str, Any], signals: dict[str, Any]) -> str:
    return str(
        signals.get("effective_state_final")
        or signals.get("effective_state")
        or signals.get("reconciled_state")
        or signals.get("state")
        or assessment.get("state")
        or _as_dict(patient.get("prior_history")).get("current_state")
        or ""
    )


def _track_from(patient: dict[str, Any], signals: dict[str, Any]) -> str:
    return str(
        signals.get("effective_management_track_final")
        or signals.get("effective_management_track")
        or signals.get("reconciled_management_track")
        or signals.get("management_track")
        or _as_dict(patient.get("prior_history")).get("management_track")
        or ""
    )


def _lazy_trajectory(patient: dict[str, Any]) -> dict[str, Any]:
    identity = _as_dict(patient.get("identity"))
    nss = str(identity.get("nss") or patient.get("nss") or "")
    psa_rows = _as_list(patient.get("biomarker_longitudinal")) or _as_list(patient.get("biomarkers"))
    treatments = _as_list(patient.get("treatments"))
    dates: list[str] = []
    for row in psa_rows:
        if isinstance(row, dict):
            date = str(row.get("sample_date") or row.get("date") or "")[:10]
            if date:
                dates.append(date)
    for row in treatments:
        if isinstance(row, dict):
            for key in ("start_date", "end_date"):
                date = str(row.get(key) or "")[:10]
                if date:
                    dates.append(date)
    return {
        "available": True,
        "lazy": True,
        "endpoint": f"/api/trajectory/{nss}" if nss else "",
        "summary": {
            "n_visits": len(psa_rows),
            "n_treatment_lines": len(treatments),
            "earliest_date": min(dates) if dates else "",
            "latest_date": max(dates) if dates else "",
        },
        "series": {"psa": [], "ecog": [], "alp": [], "ldh": []},
        "treatment_lanes": [],
        "event_markers": [],
        "cohort_overlay": {},
        "kinetics": {
            "psa_doubling_time_months": None,
            "psa_velocity_ng_per_year": None,
            "psa_nadir": None,
            "alp_trend_pct_3m": None,
            "ecog_decline_detected": False,
        },
        "alerts": [],
        "engine_version": "epic47_lazy_v2_read_model",
        "reason": "lazy_loaded_via_api",
    }


def build_patient_profile_v2_read_model(
    *,
    patient: dict[str, Any],
    latest_assessment_raw: dict[str, Any] | None,
    latest_assessment: dict[str, Any] | None,
    state_timeline: list[dict[str, Any]],
    care_overlays: list[dict[str, Any]],
    longitudinal_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Lightweight V2 profile read-model.

    The official V2 profile is an expediente reader. It should not recompute
    the longitudinal engine on every page open; event writes and explicit
    `?refresh=1` keep that heavier path.
    """
    patient = dict(patient or {})
    assessment_raw = _as_dict(latest_assessment_raw)
    assessment = _as_dict(latest_assessment)
    bundle = _as_dict(longitudinal_bundle)
    raw_signals = _as_dict(bundle.get("signals")) or _as_dict(patient.get("latest_signal_snapshot"))
    if isinstance(raw_signals.get("signals"), dict):
        nested = _as_dict(raw_signals.get("signals"))
        nested.update(raw_signals)
        raw_signals = nested
        raw_signals.pop("signals", None)

    state = _state_from(patient, assessment_raw or assessment, raw_signals)
    management_track = _track_from(patient, raw_signals)
    display_result = _as_dict(assessment.get("display_result")) or _as_dict(assessment_raw.get("result_snapshot"))
    decision = _as_dict(raw_signals.get("next_best_action")) or _as_dict(bundle.get("next_best_action"))

    try:
        from prostanet.domains.patient_tracking.psa_line_monitor import build_psa_by_treatment_line

        psa_observability = build_psa_by_treatment_line(patient)
    except Exception:
        psa_observability = {
            "has_data": False,
            "points": [],
            "treatment_bands": [],
            "line_segments": [],
            "line_events": [],
            "metrics": {},
            "source": "missing",
        }

    try:
        from prostanet.domains.patient_tracking.psa_forecast import (
            build_combined_patient_timeline,
            build_psa_cohort_reference_overlay,
            build_psa_forecast_per_line,
        )

        psa_forecast_per_line = build_psa_forecast_per_line(patient)
        psa_cohort_reference = build_psa_cohort_reference_overlay(patient)
        psa_combined_timeline = build_combined_patient_timeline(patient)
    except Exception:
        psa_forecast_per_line = {}
        psa_cohort_reference = {}
        psa_combined_timeline = {
            "has_data": False,
            "axis_dates": [],
            "psa_series": [],
            "treatment_lanes": [],
            "clinical_event_markers": [],
            "summary": {},
        }

    clinical_compass = {
        "current_stage_label": state or "Sin clasificar",
        "effective_state_label": state or "Sin clasificar",
        "recommended_direction": decision.get("title") or display_result.get("recommendation") or "Sin decisión clínica activa",
        "why_this_now": decision.get("rationale") or display_result.get("clinical_summary") or "",
        "recommendation_family": decision.get("recommendation_family") or "",
        "source": "profile_v2_read_model",
    }

    default_panel = {
        "available": False,
        "deferred": True,
        "source": "profile_v2_read_model",
        "reason": "Panel pesado diferido; use ?refresh=1 para recálculo completo.",
    }
    readiness = _as_dict(bundle.get("clinical_readiness_tower")) or _as_dict(raw_signals.get("clinical_readiness_tower")) or default_panel
    tumor_board = _as_dict(bundle.get("tumor_board_os")) or _as_dict(raw_signals.get("tumor_board_os")) or default_panel
    care_pathway = _as_dict(bundle.get("care_pathway_os")) or _as_dict(raw_signals.get("care_pathway_os")) or default_panel
    clinical_memory = _as_dict(bundle.get("clinical_memory_os")) or _as_dict(raw_signals.get("clinical_memory_os")) or default_panel

    return {
        "profile_read_mode": "v2_cached",
        "diagnostic_state": state in {"diagnostic_workup", "post_negative_biopsy_followup"},
        "management_track": management_track,
        "reconciled_state": state,
        "clinical_compass": clinical_compass,
        "state_timeline": _as_list(state_timeline),
        "care_overlays": _as_list(care_overlays),
        "stage_specific_panels": [],
        "algorithm_panels": [],
        "pivotal_panel": {"eligible_matches": [], "partial_matches": [], "ineligible_matches": [], "hidden_ineligible_count": 0, "eligible_count": 0, "partial_count": 0, "ineligible_count": 0, "last_evaluated_at": "", "has_results": False},
        "pivotal_contraindication_gates_panel": {"has_gates": False, "total": 0, "hard_block_count": 0, "by_class": {}, "gates": [], "summary_text": "Sin contraindicaciones pivote activas en snapshot V2."},
        "pivotal_contraindication_gates": [],
        "biomarker_workup": {},
        "evidence_applicability": {},
        "advanced_panel_context": {},
        "therapy_catalog_options": [],
        "treatment_course_summary": patient.get("treatment_course_summary") or {},
        "missing_inputs_by_panel": {},
        "missing_input_actions": _as_list(raw_signals.get("critical_missing"))[:8],
        "clinical_journey_events": _as_list(patient.get("patient_events"))[:24],
        "psa_observability": psa_observability,
        "psa_forecast": _as_dict(bundle.get("psa_forecast")),
        "psa_forecast_per_line": psa_forecast_per_line,
        "psa_cohort_reference": psa_cohort_reference,
        "psa_combined_timeline": psa_combined_timeline,
        "clinical_signals": raw_signals,
        "next_best_action": decision,
        "patient_alerts": _as_list(patient.get("alerts")),
        "agenda_board": {"items": _as_list(patient.get("agenda_items"))},
        "active_agenda_items": _as_list(patient.get("agenda_items")),
        "archived_agenda_items": [],
        "next_due_items": _as_list(patient.get("agenda_items"))[:4],
        "overdue_items": [],
        "recommendation_audit": _as_list(patient.get("recommendation_audit"))[:8],
        "outcome_events": _as_list(patient.get("outcome_events")),
        "current_response_state": _as_dict(_as_dict(patient.get("latest_adjudication_snapshot")).get("current_response_state")),
        "current_course_status": _as_dict(patient.get("latest_adjudication_snapshot")).get("current_course_status", ""),
        "trial_comparable_endpoints": _as_list(_as_dict(patient.get("latest_trial_benchmark_snapshot")).get("trial_endpoints")),
        "current_trial_comparable_profile": _as_dict(_as_dict(patient.get("latest_trial_benchmark_snapshot")).get("current_trial_profile")),
        "patient_kpis": {},
        "cohort_completeness": {},
        "research_readiness": {},
        "endpoint_readiness": {},
        "consent_summary": _as_dict(patient.get("consent_summary")),
        "consent_evidence": _as_dict(patient.get("consent_evidence")),
        "clinical_readiness_tower": readiness,
        "tumor_board_os": tumor_board,
        "care_pathway_os": care_pathway,
        "clinical_memory_os": clinical_memory,
        "therapeutic_readiness_bundle": _as_dict(bundle.get("therapeutic_readiness_bundle")),
        "supportive_care_toxicity_readiness_bundle": _as_dict(bundle.get("supportive_care_toxicity_readiness_bundle")),
        "crpc_copilot_bundle": _as_dict(bundle.get("crpc_copilot_bundle")),
        "post_rp_salvage_bundle": _as_dict(bundle.get("post_rp_salvage_bundle")),
        "mhspc_copilot_bundle": _as_dict(bundle.get("mhspc_copilot_bundle")),
        "diagnostic_biopsy_bundle": _as_dict(bundle.get("diagnostic_biopsy_bundle")),
        "localized_surveillance_bundle": _as_dict(bundle.get("localized_surveillance_bundle")),
        "post_rt_salvage_bundle": _as_dict(bundle.get("post_rt_salvage_bundle")),
        "data_integrity": {"available": False, "deferred": True},
        "ml_predictions": {"available": False, "deferred": True},
        "trajectory": _lazy_trajectory(patient),
        "decision_narrative": {"available": False, "deferred": True},
        "outcome_linkage": {"available": False, "deferred": True},
        "clinical_validation_snapshot": {"available": False, "status": "deferred", "findings_count": 0},
    }
