from __future__ import annotations

from copy import deepcopy
from typing import Any


def _text(value: Any) -> str:
    return str(value or "").strip()


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    if value in (None, "", {}):
        return []
    return [value]


def _first_nonempty(*values: Any) -> str:
    for value in values:
        text = _text(value)
        if text:
            return text
    return ""


def _is_post_rp_salvage_runtime(bundle: dict[str, Any], signals: dict[str, Any]) -> bool:
    state = _first_nonempty(
        signals.get("effective_state_final"),
        signals.get("effective_state"),
        bundle.get("effective_state"),
        signals.get("reconciled_state"),
    )
    track = _first_nonempty(
        signals.get("effective_management_track_final"),
        signals.get("effective_management_track"),
        bundle.get("effective_management_track"),
        signals.get("reconciled_management_track"),
    )
    return state == "recurrence_bcr" and track == "salvage"


def _visible_transition_proposals(
    proposals: list[dict[str, Any]] | None,
    *,
    bundle: dict[str, Any],
    signals: dict[str, Any],
) -> list[dict[str, Any]]:
    items = [dict(item) for item in list(proposals or []) if isinstance(item, dict)]
    transition = _as_dict(bundle.get("transition_resolution") or signals.get("transition_resolution"))
    if str(transition.get("policy") or "").strip() != "auto_applied":
        return items
    target_state = _text(transition.get("target_state"))
    target_track = _text(transition.get("target_management_track"))
    proposal_key = _text(transition.get("proposal_key"))
    visible: list[dict[str, Any]] = []
    for item in items:
        item_key = _text(item.get("proposal_key"))
        item_target_state = _text(item.get("target_state"))
        item_target_track = _text(item.get("target_management_track"))
        item_from_state = _text(item.get("from_state"))
        item_from_track = _text(item.get("from_management_track"))
        if item_key and item_key == proposal_key:
            continue
        if target_state and item_target_state == target_state and (
            not target_track or not item_target_track or item_target_track == target_track
        ):
            continue
        if target_state and item_from_state == target_state and (
            not target_track or not item_from_track or item_from_track == target_track
        ):
            continue
        visible.append(item)
    return visible


def _merge_next_best_action(
    *,
    bundle: dict[str, Any],
    signals: dict[str, Any],
    vertical_bundles: dict[str, Any],
) -> dict[str, Any]:
    current = _as_dict(signals.get("next_best_action") or bundle.get("next_best_action"))
    published = _as_dict(vertical_bundles.get("published_recommendation"))
    care_intent = _as_dict(bundle.get("care_intent_contract"))
    readiness = _as_dict(bundle.get("therapeutic_readiness_bundle"))
    family = _first_nonempty(
        published.get("recommendation_family"),
        care_intent.get("recommendation_family"),
        readiness.get("candidate_family"),
        current.get("recommendation_family"),
    )
    title = _first_nonempty(
        published.get("recommended_action"),
        published.get("title"),
        care_intent.get("headline"),
        current.get("title"),
        readiness.get("candidate_regimen_label"),
    )
    rationale = _first_nonempty(
        published.get("rationale"),
        care_intent.get("narrative"),
        current.get("rationale"),
        readiness.get("readiness_summary"),
    )
    merged = {**current}
    if title:
        merged["title"] = title
    if rationale:
        merged["rationale"] = rationale
    if family:
        merged["recommendation_family"] = family
    blocking_bundle = _as_dict(bundle.get("decision_blocking_bundle"))
    blocking_fields = _as_list(blocking_bundle.get("hard_blocking_inputs")) + _as_list(
        blocking_bundle.get("decision_blocking_inputs")
    )
    if (
        _text(bundle.get("recommendation_block_status")) == "hard_stop"
        and "testosterone" in blocking_fields
        and "testosterona" not in _text(merged.get("title")).lower()
        and "crpc" not in _text(merged.get("title")).lower()
    ):
        merged["title"] = "Confirmar testosterona en rango de castración y cerrar verificación CRPC"
        merged["recommendation_family"] = _first_nonempty(
            merged.get("recommendation_family"),
            "Confirmar testosterona y completar reestadificación convencional",
        )
    if _is_post_rp_salvage_runtime(bundle, signals):
        merged_title = _text(merged.get("title")).lower()
        if (
            not merged_title
            or "salvage" not in merged_title
            or merged_title.startswith("confirmar transición")
        ):
            merged["title"] = "Activar salvage y reestadificación dirigida"
            merged["recommendation_family"] = "salvage"
            merged.setdefault(
                "rationale",
                _first_nonempty(
                    care_intent.get("narrative"),
                    current.get("rationale"),
                    "El estado efectivo es recurrencia bioquímica post-prostatectomía con carril de salvage activo.",
                ),
            )
    evidence_basis = _as_list(
        published.get("evidence_basis")
        or current.get("evidence_basis")
        or (vertical_bundles.get("active_copilot_bundle") or {}).get("guideline_basis")
    )
    if evidence_basis:
        merged["evidence_basis"] = evidence_basis
    merged.setdefault("source", _first_nonempty(published.get("source"), current.get("source"), "runtime_publication"))
    return merged


def build_runtime_context_bundle(
    *,
    bundle: dict[str, Any] | None = None,
    signals: dict[str, Any] | None = None,
    vertical_bundles: dict[str, Any] | None = None,
    patient_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    runtime_bundle = deepcopy(_as_dict(bundle))
    signal_view = deepcopy(_as_dict(signals))
    vertical_view = deepcopy(_as_dict(vertical_bundles))
    patient_record = _as_dict(patient_record)

    runtime_bundle["signals"] = signal_view
    runtime_bundle["patient_id"] = (
        (patient_record.get("identity") or {}).get("id")
        or patient_record.get("id")
        or runtime_bundle.get("patient_id")
    )
    runtime_bundle["effective_state"] = _first_nonempty(
        signal_view.get("effective_state_final"),
        signal_view.get("effective_state"),
        runtime_bundle.get("effective_state"),
        runtime_bundle.get("state"),
    )
    runtime_bundle["effective_management_track"] = _first_nonempty(
        signal_view.get("effective_management_track_final"),
        signal_view.get("effective_management_track"),
        runtime_bundle.get("effective_management_track"),
        runtime_bundle.get("management_track"),
    )
    runtime_bundle["next_best_action"] = _merge_next_best_action(
        bundle=runtime_bundle,
        signals=signal_view,
        vertical_bundles=vertical_view,
    )
    for key, value in vertical_view.items():
        if key.endswith("_bundle") or key in {"active_copilot_bundle", "published_recommendation"}:
            runtime_bundle[key] = deepcopy(value)
    return runtime_bundle


def prepare_runtime_publication_state(
    *,
    patient_record: dict[str, Any] | None = None,
    bundle: dict[str, Any] | None = None,
    signals: dict[str, Any] | None = None,
    decision_input_requirements: dict[str, Any] | None = None,
    vertical_bundles: dict[str, Any] | None = None,
) -> dict[str, Any]:
    runtime_context_bundle = build_runtime_context_bundle(
        bundle=bundle,
        signals=signals,
        vertical_bundles=vertical_bundles,
        patient_record=patient_record,
    )
    signal_view = deepcopy(_as_dict(signals))
    signal_view["next_best_action"] = deepcopy(runtime_context_bundle.get("next_best_action") or {})
    signal_view["decision_input_requirements"] = deepcopy(_as_dict(decision_input_requirements))
    signal_view.setdefault(
        "effective_state_final",
        _first_nonempty(runtime_context_bundle.get("effective_state"), signal_view.get("effective_state")),
    )
    signal_view.setdefault(
        "effective_management_track_final",
        _first_nonempty(
            runtime_context_bundle.get("effective_management_track"),
            signal_view.get("effective_management_track"),
        ),
    )
    runtime_context_bundle["signals"] = signal_view
    return {
        "signals": signal_view,
        "runtime_context_bundle": runtime_context_bundle,
    }


def build_runtime_publication_payload(
    *,
    patient_record: dict[str, Any] | None = None,
    bundle: dict[str, Any] | None = None,
    signals: dict[str, Any] | None = None,
    orchestration: dict[str, Any] | None = None,
    decision_input_requirements: dict[str, Any] | None = None,
    outcome_bundle: dict[str, Any] | None = None,
    prognostic_bundle: dict[str, Any] | None = None,
    psa_forecast_bundle: dict[str, Any] | None = None,
    live_benchmark_bundle: dict[str, Any] | None = None,
    vertical_bundles: dict[str, Any] | None = None,
    kernel_bundles: dict[str, Any] | None = None,
    qa_passed: bool | None = None,
    sequence_summary: dict[str, Any] | None = None,
    clinical_ledger_bundle: dict[str, Any] | None = None,
    copilot_alerts: list[dict[str, Any]] | None = None,
    transition_proposals: list[dict[str, Any]] | None = None,
    recommendation_audit: dict[str, Any] | list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    runtime_context_bundle = build_runtime_context_bundle(
        bundle=bundle,
        signals=signals,
        vertical_bundles=vertical_bundles,
        patient_record=patient_record,
    )
    signal_view = deepcopy(_as_dict(signals))
    signal_view["next_best_action"] = deepcopy(runtime_context_bundle.get("next_best_action") or {})
    runtime_context_bundle["signals"] = signal_view

    runtime_bundle = _as_dict(bundle)
    orchestration = _as_dict(orchestration)
    decision_input_requirements = _as_dict(decision_input_requirements)
    outcome_bundle = _as_dict(outcome_bundle)
    prognostic_bundle = _as_dict(prognostic_bundle)
    psa_forecast_bundle = _as_dict(psa_forecast_bundle)
    live_benchmark_bundle = _as_dict(live_benchmark_bundle)
    vertical_bundles = _as_dict(vertical_bundles)
    kernel_bundles = _as_dict(kernel_bundles)
    therapeutic_readiness = _as_dict(runtime_bundle.get("therapeutic_readiness_bundle"))
    clinical_readiness_tower = _as_dict(runtime_bundle.get("clinical_readiness_tower"))
    tumor_board_os = _as_dict(runtime_bundle.get("tumor_board_os"))
    care_pathway_os = _as_dict(runtime_bundle.get("care_pathway_os"))
    clinical_memory_os = _as_dict(runtime_bundle.get("clinical_memory_os"))
    decision_evidence = _as_dict(runtime_bundle.get("decision_evidence_currentness_bundle"))

    public_payload: dict[str, Any] = {
        **runtime_context_bundle,
        "signals": signal_view,
        "effective_state": _first_nonempty(
            signal_view.get("effective_state_final"),
            runtime_context_bundle.get("effective_state"),
        ),
        "effective_management_track": _first_nonempty(
            signal_view.get("effective_management_track_final"),
            runtime_context_bundle.get("effective_management_track"),
        ),
        "next_best_action": deepcopy(signal_view.get("next_best_action") or {}),
        "systemic_regimen_scope": _first_nonempty(
            runtime_bundle.get("systemic_regimen_scope"),
            (_as_dict(runtime_bundle.get("systemic_regimen_scope_contract"))).get("scope"),
        ),
        "systemic_regimen_scope_contract": deepcopy(_as_dict(runtime_bundle.get("systemic_regimen_scope_contract"))),
        "care_intent_contract": deepcopy(_as_dict(runtime_bundle.get("care_intent_contract"))),
        "decision_governance_bundle": deepcopy(_as_dict(runtime_bundle.get("decision_governance_bundle"))),
        "decision_evidence_currentness_bundle": deepcopy(decision_evidence),
        "selected_decision_evidence_status": _first_nonempty(
            decision_evidence.get("selected_decision_evidence_status"),
            signal_view.get("selected_decision_evidence_status"),
        ),
        "selected_decision_release_status": _first_nonempty(
            decision_evidence.get("selected_decision_release_status"),
            signal_view.get("selected_decision_release_status"),
        ),
        "decision_refresh_actions": _as_list(decision_evidence.get("refresh_actions")),
        "decision_input_requirements": deepcopy(decision_input_requirements),
        "therapeutic_readiness_bundle": deepcopy(therapeutic_readiness),
        "clinical_readiness_tower": deepcopy(clinical_readiness_tower),
        "tumor_board_os": deepcopy(tumor_board_os),
        "care_pathway_os": deepcopy(care_pathway_os),
        "clinical_memory_os": deepcopy(clinical_memory_os),
        "readiness_status": therapeutic_readiness.get("readiness_status", ""),
        "required_to_release": _as_list(therapeutic_readiness.get("required_to_release")),
        "display_required_to_release": _as_list(therapeutic_readiness.get("display_required_to_release")),
        "release_blockers": _as_list(therapeutic_readiness.get("release_blockers")),
        "next_best_action_if_not_ready": deepcopy(_as_dict(therapeutic_readiness.get("next_best_action_if_not_ready"))),
        "competing_intent": deepcopy(_as_dict(therapeutic_readiness.get("competing_intent"))),
        "master_followup_plan": deepcopy(_as_dict(orchestration.get("master_followup_plan"))),
        "master_followup_summary": deepcopy(_as_dict(orchestration.get("master_followup_summary"))),
        "alert_summary": deepcopy(_as_dict(orchestration.get("alert_summary"))),
        "encounters": _as_list(orchestration.get("encounters")),
        "schedule_anchor_strength": _text(orchestration.get("schedule_anchor_strength")),
        "copilot_alerts": _as_list(copilot_alerts or orchestration.get("copilot_alerts")),
        "transition_proposals": _visible_transition_proposals(
            transition_proposals,
            bundle=runtime_context_bundle,
            signals=signal_view,
        ),
        "outcome_bundle": deepcopy(outcome_bundle),
        "outcome_events": _as_list(outcome_bundle.get("outcome_events")),
        "outcome_events_summary": deepcopy(_as_dict(outcome_bundle.get("outcome_events_summary"))),
        "pending_adjudications": _as_list(outcome_bundle.get("pending_adjudications")),
        "current_response_state": deepcopy(_as_dict(outcome_bundle.get("current_response_state"))),
        "current_course_status": _text(outcome_bundle.get("current_course_status")),
        "last_adjudicated_event": deepcopy(_as_dict(outcome_bundle.get("last_adjudicated_event"))),
        "trial_comparable_endpoints": _as_list(outcome_bundle.get("trial_comparable_endpoints")),
        "current_trial_comparable_profile": deepcopy(
            _as_dict(outcome_bundle.get("current_trial_comparable_profile"))
        ),
        "benchmark_reliability": deepcopy(_as_dict(outcome_bundle.get("benchmark_reliability"))),
        "prognostic_bundle": deepcopy(prognostic_bundle),
        "prognostic_modifiers": _as_list(prognostic_bundle.get("prognostic_modifiers")),
        "psa_forecast": deepcopy(psa_forecast_bundle),
        "forecast_reliability": deepcopy(_as_dict(psa_forecast_bundle.get("forecast_reliability"))),
        "live_benchmark": deepcopy(live_benchmark_bundle),
        "clinical_fact_bundle": deepcopy(_as_dict(kernel_bundles.get("clinical_fact_bundle"))),
        "fact_conflict_summary": deepcopy(_as_dict(kernel_bundles.get("fact_conflict_summary"))),
        "contradiction_resolution_bundle": deepcopy(_as_dict(kernel_bundles.get("contradiction_resolution_bundle"))),
        "state_reclassification_bundle": deepcopy(_as_dict(kernel_bundles.get("state_reclassification_bundle"))),
        "qa_passed": qa_passed,
        "sequence_summary": deepcopy(sequence_summary),
        "clinical_ledger_bundle": deepcopy(_as_dict(clinical_ledger_bundle)),
        "recommendation_audit": deepcopy(recommendation_audit or []),
    }
    for key in (
        "crpc_copilot_bundle",
        "post_rp_salvage_bundle",
        "mhspc_copilot_bundle",
        "diagnostic_biopsy_bundle",
        "localized_surveillance_bundle",
        "post_rt_salvage_bundle",
        "active_copilot_bundle",
    ):
        if key in vertical_bundles:
            public_payload[key] = deepcopy(vertical_bundles.get(key) or {})

    signals_to_persist = {
        "signals": signal_view,
        "next_best_action": deepcopy(public_payload.get("next_best_action") or {}),
        "clinical_readiness_tower": deepcopy(clinical_readiness_tower),
        "tumor_board_os": deepcopy(tumor_board_os),
        "care_pathway_os": deepcopy(care_pathway_os),
        "clinical_memory_os": deepcopy(clinical_memory_os),
    }
    return {
        "signals": signal_view,
        "runtime_context_bundle": runtime_context_bundle,
        "public_payload": public_payload,
        "signals_to_persist": signals_to_persist,
    }


__all__ = [
    "build_runtime_context_bundle",
    "prepare_runtime_publication_state",
    "build_runtime_publication_payload",
]
