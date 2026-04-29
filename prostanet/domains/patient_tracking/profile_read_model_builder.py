from __future__ import annotations

from typing import Any


PROFILE_READ_MODEL_VERSION = "2026.4"

_STATE_BUCKETS = {
    "diagnostic_workup": "diagnostic",
    "post_negative_biopsy_followup": "diagnostic",
    "localized_initial": "localized",
    "post_prostatectomy": "postlocal",
    "recurrence_bcr": "postlocal",
    "post_radiotherapy_followup": "postlocal",
    "post_radiotherapy_or_local_salvage": "postlocal",
    "adt_progression_verification": "systemic_advanced",
    "m0_crpc": "systemic_advanced",
    "m1_crpc": "systemic_advanced",
    "mcspc_oligo_metachronous": "systemic_advanced",
    "mcspc_low_volume_sync_oligo": "systemic_advanced",
    "mcspc_high_volume_sync": "systemic_advanced",
    "mcspc_high_volume_metachronous": "systemic_advanced",
    "mcspc_high_volume": "systemic_advanced",
    "survivorship_and_toxicity_followup": "survivorship",
}
_LEGACY_SCENARIO_BUCKETS = {
    "mhspc": "systemic_advanced",
    "mcrpc": "systemic_advanced",
    "nmcrpc": "systemic_advanced",
}


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _first_nonempty(*values: Any) -> str:
    for value in values:
        text = _normalize_text(value)
        if text:
            return text
    return ""


def _dedupe(values: list[Any]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _normalize_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _state_bucket(state: Any) -> str:
    return _STATE_BUCKETS.get(_normalize_text(state), "")


def _legacy_recommendation_bucket(recommendations: dict[str, Any] | None) -> str:
    scenario = _normalize_text((recommendations or {}).get("scenario")).lower()
    return _LEGACY_SCENARIO_BUCKETS.get(scenario, "")


def build_surface_consistency_projection(
    patient: dict[str, Any],
    longitudinal_bundle: dict[str, Any] | None,
    *,
    latest_assessment: dict[str, Any] | None = None,
    recommendations: dict[str, Any] | None = None,
    therapeutic_readiness_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    patient = dict(patient or {})
    longitudinal_bundle = dict(longitudinal_bundle or {})
    latest_assessment = dict(latest_assessment or patient.get("latest_assessment") or {})
    merged_signals = dict(patient.get("latest_signal_snapshot") or {})
    merged_signals.update(dict(longitudinal_bundle.get("signals") or {}))
    therapeutic_readiness_bundle = dict(
        therapeutic_readiness_bundle
        or longitudinal_bundle.get("therapeutic_readiness_bundle")
        or patient.get("therapeutic_readiness_bundle")
        or merged_signals.get("therapeutic_readiness_bundle")
        or {}
    )

    effective_state = _first_nonempty(
        merged_signals.get("effective_state_final"),
        merged_signals.get("effective_state"),
        merged_signals.get("reconciled_state"),
        latest_assessment.get("state"),
        (patient.get("prior_history") or {}).get("current_state"),
    )
    effective_recommendation_family = _first_nonempty(
        therapeutic_readiness_bundle.get("candidate_family"),
        (merged_signals.get("next_best_action") or {}).get("recommendation_family"),
        (patient.get("next_best_action") or {}).get("recommendation_family"),
    )
    inherited_flags = [
        _normalize_text(item.get("message") or item.get("reason") or item)
        if isinstance(item, dict)
        else _normalize_text(item)
        for item in list(
            merged_signals.get("surface_consistency_flags")
            or merged_signals.get("ui_contradiction_flags")
            or []
        )
    ]
    flags = _dedupe(inherited_flags)

    state_bucket = _state_bucket(effective_state)
    legacy_bucket = _legacy_recommendation_bucket(recommendations)
    legacy_scenario = _normalize_text((recommendations or {}).get("scenario"))
    if legacy_bucket and state_bucket and legacy_bucket != state_bucket:
        flags.append(
            f"El panel legacy ({legacy_scenario}) no coincide con el estado clínico efectivo actual ({effective_state})."
        )

    if _normalize_text(merged_signals.get("state_conflict_reason")):
        flags.append(_normalize_text(merged_signals.get("state_conflict_reason")))

    if (
        _normalize_text(therapeutic_readiness_bundle.get("candidate_family"))
        and state_bucket == "postlocal"
        and _normalize_text(therapeutic_readiness_bundle.get("candidate_family")) in {"parp_family", "psma_rlt_family"}
    ):
        flags.append(
            "La familia terapéutica visible parece sistémica avanzada para un estado efectivo postlocal; revisar convergencia de superficies."
        )

    status = "requires_review" if flags else "consistent"
    legacy_panel_show = bool(
        recommendations
        and not latest_assessment
        and legacy_bucket
        and legacy_bucket == state_bucket
        and not flags
    )
    legacy_reason = (
        "Visible solo como comparador legacy mientras no exista evaluación modular persistida."
        if legacy_panel_show
        else "Oculto porque la fuente primaria visible ya es el estado reconciliado y el read-model oficial."
    )
    clinical_kernel_snapshot = dict(longitudinal_bundle.get("clinical_kernel_snapshot") or {})
    clinical_kernel_snapshot.update(
        {
            "effective_state": effective_state,
            "effective_recommendation_family": effective_recommendation_family,
            "surface_consistency_status": status,
            "surface_consistency_flags": flags,
            "profile_read_model_version": PROFILE_READ_MODEL_VERSION,
        }
    )
    return {
        "profile_read_model_version": PROFILE_READ_MODEL_VERSION,
        "clinical_kernel_snapshot": clinical_kernel_snapshot,
        "effective_state": effective_state,
        "effective_recommendation_family": effective_recommendation_family,
        "surface_consistency_status": status,
        "surface_consistency_flags": flags,
        "legacy_recommendation_panel": {
            "show": legacy_panel_show,
            "reason": legacy_reason,
            "scenario": legacy_scenario,
            "mode": "legacy_comparator" if legacy_panel_show else "hidden",
        },
    }


def build_profile_support_projection(patient, longitudinal_bundle):
    patient = dict(patient or {})
    longitudinal_bundle = dict(longitudinal_bundle or {})
    latest_signal_snapshot = dict(patient.get("latest_signal_snapshot") or {})
    return {
        "clinical_fact_bundle": longitudinal_bundle.get("clinical_fact_bundle")
        or patient.get("clinical_fact_bundle")
        or {},
        "fact_freshness_summary": longitudinal_bundle.get("fact_freshness_summary")
        or patient.get("fact_freshness_summary")
        or {},
        "fact_conflict_summary": longitudinal_bundle.get("fact_conflict_summary")
        or patient.get("fact_conflict_summary")
        or {},
        "contradiction_resolution_bundle": longitudinal_bundle.get("contradiction_resolution_bundle")
        or patient.get("contradiction_resolution_bundle")
        or {},
        "state_reclassification_bundle": longitudinal_bundle.get("state_reclassification_bundle")
        or patient.get("state_reclassification_bundle")
        or {},
        "clinical_ledger_bundle": longitudinal_bundle.get("clinical_ledger_bundle")
        or patient.get("clinical_ledger_bundle")
        or {},
        "clinical_kernel_snapshot": longitudinal_bundle.get("clinical_kernel_snapshot")
        or patient.get("clinical_kernel_snapshot")
        or latest_signal_snapshot.get("clinical_kernel_snapshot")
        or {},
        "effective_state": longitudinal_bundle.get("effective_state")
        or patient.get("effective_state")
        or latest_signal_snapshot.get("effective_state_final")
        or latest_signal_snapshot.get("effective_state")
        or latest_signal_snapshot.get("reconciled_state")
        or "",
        "effective_recommendation_family": longitudinal_bundle.get("effective_recommendation_family")
        or patient.get("effective_recommendation_family")
        or latest_signal_snapshot.get("effective_recommendation_family")
        or "",
        "surface_consistency_status": longitudinal_bundle.get("surface_consistency_status")
        or patient.get("surface_consistency_status")
        or latest_signal_snapshot.get("surface_consistency_status")
        or "consistent",
        "surface_consistency_flags": longitudinal_bundle.get("surface_consistency_flags")
        or patient.get("surface_consistency_flags")
        or latest_signal_snapshot.get("surface_consistency_flags")
        or [],
        "advanced_followup_bundle": longitudinal_bundle.get("advanced_followup_bundle")
        or patient.get("advanced_followup_bundle")
        or latest_signal_snapshot.get("advanced_followup_bundle")
        or {},
        "staging_adjudication_bundle": longitudinal_bundle.get("staging_adjudication_bundle")
        or patient.get("staging_adjudication_bundle")
        or latest_signal_snapshot.get("staging_adjudication_bundle")
        or {},
        "decision_evidence_currentness_bundle": longitudinal_bundle.get("decision_evidence_currentness_bundle")
        or patient.get("decision_evidence_currentness_bundle")
        or latest_signal_snapshot.get("decision_evidence_currentness_bundle")
        or {},
    }
