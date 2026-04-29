from __future__ import annotations

from typing import Any


def build_patient_schedule_context(
    patient_record: dict[str, Any],
    *,
    latest_assessment: dict[str, Any] | None = None,
    reconciliation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from prostanet.domains.patient_tracking.followup_agenda import build_agenda_board
    from prostanet.domains.patient_tracking.guideline_schedule_engine import (
        build_guideline_followup_plan,
    )
    from prostanet.domains.patient_tracking.laboratory_intelligence.service import (
        build_laboratory_intelligence_profile,
    )
    from prostanet.domains.patient_tracking.longitudinal_intelligence import (
        resolve_followup_runtime_context,
    )
    from prostanet.domains.patient_tracking.master_followup_plan import (
        build_master_followup_plan,
    )
    from prostanet.domains.patient_tracking.reconciled_state import build_reconciled_state

    patient_record = dict(patient_record or {})
    latest_assessment = dict(latest_assessment or patient_record.get("latest_assessment") or {})
    reconciliation = dict(
        reconciliation or build_reconciled_state(patient_record, latest_assessment)
    )
    prior_history = dict(patient_record.get("prior_history") or {})
    latest_signal_snapshot = dict(patient_record.get("latest_signal_snapshot") or {})

    state = (
        reconciliation.get("reconciled_state")
        or latest_assessment.get("state")
        or prior_history.get("current_state")
        or "diagnostic_workup"
    )
    management_track = (
        reconciliation.get("reconciled_management_track") or "diagnostic_surveillance"
    )
    followup_runtime = resolve_followup_runtime_context(
        patient_record,
        state=state,
        management_track=management_track,
        latest_assessment=latest_assessment,
        signals=latest_signal_snapshot,
    )
    effective_followup_state = str(followup_runtime.get("state") or state)
    effective_followup_track = str(followup_runtime.get("management_track") or management_track)
    agenda_board = build_agenda_board(
        patient_record,
        effective_followup_state,
        effective_followup_track,
        latest_assessment,
    )
    master_followup_plan = build_master_followup_plan(
        patient_record,
        state=effective_followup_state,
        management_track=effective_followup_track,
        agenda_board=agenda_board,
        signals=latest_signal_snapshot,
        copilot_alerts=patient_record.get("alerts") or [],
        next_best_action=latest_signal_snapshot.get("next_best_action") or {},
    )
    guideline_followup_plan = build_guideline_followup_plan(
        patient=patient_record,
        state=effective_followup_state,
        management_track=effective_followup_track,
        agenda_board=agenda_board,
        master_followup_plan=master_followup_plan,
        signals=latest_signal_snapshot,
        care_intent_contract=latest_signal_snapshot.get("care_intent_contract") or {},
    )

    return {
        "followup_runtime_context": dict(followup_runtime),
        "schedule_state": effective_followup_state,
        "schedule_management_track": effective_followup_track,
        "schedule_override_reason": str(followup_runtime.get("override_reason") or ""),
        "effective_state": str(
            patient_record.get("effective_state")
            or latest_signal_snapshot.get("effective_state_final")
            or latest_signal_snapshot.get("effective_state")
            or effective_followup_state
        ),
        "effective_recommendation_family": str(
            patient_record.get("effective_recommendation_family")
            or latest_signal_snapshot.get("effective_recommendation_family")
            or ((latest_signal_snapshot.get("therapeutic_readiness_bundle") or {}).get("candidate_family"))
            or ""
        ),
        "clinical_kernel_snapshot": dict(
            patient_record.get("clinical_kernel_snapshot")
            or latest_signal_snapshot.get("clinical_kernel_snapshot")
            or {}
        ),
        "surface_consistency_status": str(
            patient_record.get("surface_consistency_status")
            or latest_signal_snapshot.get("surface_consistency_status")
            or "consistent"
        ),
        "surface_consistency_flags": list(
            patient_record.get("surface_consistency_flags")
            or latest_signal_snapshot.get("surface_consistency_flags")
            or []
        ),
        "advanced_followup_bundle": dict(
            patient_record.get("advanced_followup_bundle")
            or latest_signal_snapshot.get("advanced_followup_bundle")
            or {}
        ),
        "decision_evidence_currentness_bundle": dict(
            patient_record.get("decision_evidence_currentness_bundle")
            or latest_signal_snapshot.get("decision_evidence_currentness_bundle")
            or {}
        ),
        "selected_decision_evidence_status": str(
            ((patient_record.get("decision_evidence_currentness_bundle") or latest_signal_snapshot.get("decision_evidence_currentness_bundle") or {}).get("selected_decision_evidence_status") or "")
        ),
        "selected_decision_release_status": str(
            ((patient_record.get("decision_evidence_currentness_bundle") or latest_signal_snapshot.get("decision_evidence_currentness_bundle") or {}).get("selected_decision_release_status") or "")
        ),
        "staging_adjudication_bundle": dict(
            patient_record.get("staging_adjudication_bundle")
            or latest_signal_snapshot.get("staging_adjudication_bundle")
            or {}
        ),
        "supportive_care_toxicity_readiness_bundle": dict(
            patient_record.get("supportive_care_toxicity_readiness_bundle")
            or latest_signal_snapshot.get("supportive_care_toxicity_readiness_bundle")
            or {}
        ),
        "supportive_readiness_status": str(
            (
                (
                    patient_record.get("supportive_care_toxicity_readiness_bundle")
                    or latest_signal_snapshot.get("supportive_care_toxicity_readiness_bundle")
                    or {}
                ).get("supportive_readiness_status")
                or ""
            )
        ),
        "guideline_followup_plan": guideline_followup_plan,
        "care_intent_contract": latest_signal_snapshot.get("care_intent_contract") or {},
        "transition_resolution": latest_signal_snapshot.get("transition_resolution") or {},
        "laboratory_intelligence_profile": build_laboratory_intelligence_profile(
            patient_record,
            state=effective_followup_state,
            management_track=effective_followup_track,
            latest_assessment=latest_assessment,
        ),
    }
