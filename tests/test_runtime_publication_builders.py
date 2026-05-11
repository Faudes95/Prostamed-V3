# IEC 62304 §5.5 (Unit verification)
from prostanet.domains.patient_tracking.runtime_publication_builder import (
    build_runtime_publication_payload,
)
from prostanet.domains.patient_tracking.runtime_signal_snapshot_builder import (
    build_runtime_signal_snapshot,
)


def test_runtime_signal_snapshot_builder_projects_m1_crpc_keys():
    bundle = {
        "signals": {
            "effective_state": "m1_crpc",
            "reconciled_state": "m1_crpc",
            "metastatic_stage_resolved": "M1b",
            "metastatic_stage_label": "M1b",
            "metastatic_detection_basis": "psma_only",
            "nmcrpc_eligible": False,
            "next_best_action": {
                "title": "Maintain sequential mCRPC routing",
                "rationale": "The case is already metastatic.",
                "recommendation_family": "observation_family",
            },
        },
        "next_best_action": {
            "title": "Maintain sequential mCRPC routing",
            "rationale": "The case is already metastatic.",
            "recommendation_family": "observation_family",
        },
        "decision_governance_bundle": {"status": "ready"},
        "decision_evidence_currentness_bundle": {
            "selected_decision_evidence_status": "aging",
            "selected_decision_release_status": "aging_review_needed",
            "refresh_actions": ["Actualizar PSA y mpMRI"],
        },
        "guideline_followup_plan": {"schedule_evidence_basis": ["EAU"]},
        "recommendation_block_status": "provisional",
        "recommendation_block_reason": "Pending confirmation",
        "window_worklist_bundle": {},
    }
    active_copilot_bundle = {
        "status": "published",
        "effective_state": "m1_crpc",
        "effective_management_track": "systemic_control",
        "guideline_basis": ["AUA"],
        "final_presented_recommendation": {
            "recommended_action": "Escalate to mCRPC sequence",
            "rationale": "The patient has documented M1 disease under ADT.",
            "recommendation_family": "mcrpc_sequence",
            "source": "rule_based_primary",
        },
    }

    projection = build_runtime_signal_snapshot(
        patient_record={"identity": {"id": 101}},
        bundle=bundle,
        latest_snapshot={},
        decision_input_requirements={"blocking_inputs": [], "hard_blocking_inputs": []},
        outcome_bundle={"outcome_events_summary": {"event_count": 1}},
        prognostic_bundle={"prognostic_modifiers": ["visceral risk"]},
        psa_forecast_bundle={"reliability": {"status": "ok"}},
        live_benchmark_bundle={"reliability": {"status": "ok"}},
        vertical_bundles={
            "active_copilot_bundle": active_copilot_bundle,
            "crpc_copilot_bundle": active_copilot_bundle,
            "post_rp_salvage_bundle": {},
            "mhspc_copilot_bundle": {},
            "diagnostic_biopsy_bundle": {},
            "localized_surveillance_bundle": {},
            "post_rt_salvage_bundle": {},
            "current_state": "m1_crpc",
            "current_track": "systemic_control",
        },
        kernel_bundles={
            "clinical_fact_bundle": {
                "facts": [{"fact_key": "metastatic_stage_resolved", "value": "M1b"}],
                "freshness_summary": {"overall_status": "current"},
            },
            "fact_conflict_summary": {"open_conflicts": 0},
            "contradiction_resolution_bundle": {"block_status": "note", "critical_unresolved_count": 0},
            "state_reclassification_bundle": {"visible": True, "target_state": "m1_crpc"},
        },
        qa_passed=True,
        sequence_summary={"status": "sequenced"},
        ui_contradiction_flags=[],
    )

    signals = projection["signals"]
    assert signals["effective_state_final"] == "m1_crpc"
    assert signals["metastatic_stage_resolved"] == "M1b"
    assert signals["crpc_copilot_bundle"]["status"] == "published"
    assert signals["decision_governance_bundle"] == {"status": "ready"}
    assert signals["clinical_fact_bundle"]["facts"][0]["fact_key"] == "metastatic_stage_resolved"
    assert signals["next_best_action"]["recommendation_family"] == "mcrpc_sequence"


def test_runtime_publication_payload_preserves_public_contract_keys():
    bundle = {
        "care_intent_contract": {
            "headline": "Control sistémico secuencial",
            "narrative": "Mantener ruta mCRPC",
            "recommendation_family": "mcrpc_sequence",
        },
        "decision_governance_bundle": {"status": "ready"},
        "decision_evidence_currentness_bundle": {
            "selected_decision_evidence_status": "aging",
            "selected_decision_release_status": "aging_review_needed",
            "refresh_actions": ["Actualizar PSA y mpMRI"],
        },
        "systemic_regimen_scope": "mcrpc_sequence",
        "systemic_regimen_scope_contract": {"scope": "mcrpc_sequence"},
        "therapeutic_readiness_bundle": {
            "readiness_status": "conditional_pending_closure",
            "release_blockers": ["Falta trazabilidad molecular."],
            "required_to_release": ["hrr_status"],
            "next_best_action_if_not_ready": {"title": "Completar HRR"},
            "competing_intent": {"status": "aligned"},
        },
        "guideline_followup_plan": {"schedule_evidence_basis": ["EAU"]},
        "window_worklist_bundle": {"top_active_window": {"window_key": "progression_verification_closure_window"}},
        "next_best_action": {
            "title": "Legacy title",
            "rationale": "Legacy rationale",
            "recommendation_family": "observation_family",
        },
    }
    signals = {
        "effective_state_final": "m1_crpc",
        "metastatic_stage_resolved": "M1c",
        "metastatic_stage_label": "M1c",
        "metastatic_detection_basis": "both",
        "next_best_action": {
            "title": "Legacy title",
            "rationale": "Legacy rationale",
            "recommendation_family": "observation_family",
        },
        "ui_contradiction_flags": [],
    }

    projection = build_runtime_publication_payload(
        patient_record={"identity": {"id": 202}, "latest_assessment": {"result_snapshot": {"preferred_frontline_regimen": {"family_code": "mcrpc_sequence"}}}},
        bundle=bundle,
        signals=signals,
        orchestration={
            "alert_summary": {"open": 0},
            "encounters": [],
            "master_followup_plan": {"plan_key": "m1-crpc"},
            "master_followup_summary": {"headline": "Plan activo"},
            "schedule_anchor_strength": "strong",
            "copilot_alerts": [],
        },
        decision_input_requirements={"blocking_inputs": [], "decision_domains_blocked": []},
        outcome_bundle={"outcome_events": [], "outcome_events_summary": {}},
        prognostic_bundle={"prognostic_modifiers": [], "recommended_actions": []},
        psa_forecast_bundle={"reliability": {"status": "ok"}},
        live_benchmark_bundle={"reliability": {"status": "ok"}},
        vertical_bundles={
            "published_recommendation": {"recommendation_family": "mcrpc_sequence"},
            "crpc_copilot_bundle": {"status": "published"},
            "post_rp_salvage_bundle": {},
            "mhspc_copilot_bundle": {},
            "diagnostic_biopsy_bundle": {},
            "localized_surveillance_bundle": {},
            "post_rt_salvage_bundle": {},
        },
        kernel_bundles={
            "clinical_fact_bundle": {"facts": [{"fact_key": "psa", "value": 12.4}], "freshness_summary": {"overall_status": "current"}},
            "fact_conflict_summary": {"open_conflicts": 0},
            "contradiction_resolution_bundle": {"block_status": "note"},
            "state_reclassification_bundle": {"visible": False},
        },
        qa_passed=True,
        sequence_summary={"status": "sequenced"},
        clinical_ledger_bundle={"items": [{"title": "M1 confirmed"}]},
        copilot_alerts=[],
        transition_proposals=[],
        recommendation_audit=[],
    )

    public_payload = projection["public_payload"]
    assert public_payload["systemic_regimen_scope"] == "mcrpc_sequence"
    assert public_payload["next_best_action"]["recommendation_family"] == "mcrpc_sequence"
    assert public_payload["decision_governance_bundle"] == {"status": "ready"}
    assert public_payload["decision_evidence_currentness_bundle"]["selected_decision_release_status"] == "aging_review_needed"
    assert public_payload["selected_decision_evidence_status"] == "aging"
    assert public_payload["decision_refresh_actions"] == ["Actualizar PSA y mpMRI"]
    assert public_payload["clinical_fact_bundle"]["facts"][0]["fact_key"] == "psa"
    assert public_payload["therapeutic_readiness_bundle"]["readiness_status"] == "conditional_pending_closure"
    assert public_payload["readiness_status"] == "conditional_pending_closure"
    assert public_payload["required_to_release"] == ["hrr_status"]
    assert public_payload["next_best_action_if_not_ready"]["title"] == "Completar HRR"
    assert projection["runtime_context_bundle"]["signals"]["effective_state_final"] == "m1_crpc"
    assert projection["signals_to_persist"]["next_best_action"] == public_payload["next_best_action"]
