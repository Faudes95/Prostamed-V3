from __future__ import annotations

from typing import Any


def build_patient_governance_context(
    patient_record: dict[str, Any],
    *,
    latest_assessment: dict[str, Any] | None = None,
    reconciliation: dict[str, Any] | None = None,
    longitudinal_truth_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from prostanet.domains.patient_tracking.decision_input_requirements_engine import (
        build_decision_input_requirements,
        detect_ui_contradiction_flags,
    )
    from prostanet.domains.patient_tracking.followup_reconciliation_service import (
        build_decision_recalculation_trace,
    )

    patient_record = dict(patient_record or {})
    latest_assessment = dict(latest_assessment or patient_record.get("latest_assessment") or {})
    reconciliation = dict(reconciliation or {})
    prior_history = dict(patient_record.get("prior_history") or {})

    state = (
        reconciliation.get("reconciled_state")
        or latest_assessment.get("state")
        or prior_history.get("current_state")
        or "diagnostic_workup"
    )
    management_track = (
        reconciliation.get("reconciled_management_track") or "diagnostic_surveillance"
    )
    effective_followup_state = str(patient_record.get("schedule_state") or state)
    effective_followup_track = str(
        patient_record.get("schedule_management_track") or management_track
    )
    guideline_followup_plan = dict(patient_record.get("guideline_followup_plan") or {})
    latest_signal_snapshot = dict(patient_record.get("latest_signal_snapshot") or {})

    decision_recalculation_trace = build_decision_recalculation_trace(
        patient=patient_record,
        state=state,
        management_track=management_track,
        latest_assessment=latest_assessment,
        longitudinal_truth_snapshot=longitudinal_truth_snapshot or {},
        next_best_action=latest_signal_snapshot.get("next_best_action") or {},
        reconciliation=reconciliation,
        transition_resolution=patient_record.get("transition_resolution") or {},
        care_intent_contract=patient_record.get("care_intent_contract") or {},
    )
    decision_input_requirements = build_decision_input_requirements(
        patient_record,
        effective_state=effective_followup_state,
        effective_management_track=effective_followup_track,
        latest_assessment=latest_assessment,
        next_best_action=latest_signal_snapshot.get("next_best_action") or {},
    )
    ui_contradiction_flags = detect_ui_contradiction_flags(
        patient_record,
        effective_state=effective_followup_state,
        effective_management_track=effective_followup_track,
        decision_trace=decision_recalculation_trace,
        schedule_bundle={
            "schedule_state": effective_followup_state,
            "schedule_management_track": effective_followup_track,
            "schedule_override_reason": patient_record.get("schedule_override_reason") or "",
            "schedule_primary_intent": guideline_followup_plan.get("schedule_primary_intent", ""),
            "action_schedule_consistency": guideline_followup_plan.get("action_schedule_consistency"),
        },
        transition_resolution=patient_record.get("transition_resolution") or {},
        care_intent_contract=patient_record.get("care_intent_contract") or {},
    )
    return {
        "decision_recalculation_trace": decision_recalculation_trace,
        "decision_input_requirements": decision_input_requirements,
        "ui_contradiction_flags": ui_contradiction_flags,
    }
