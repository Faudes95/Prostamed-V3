from __future__ import annotations

from typing import Any


def _bundle_can_override_recommendation(bundle: dict[str, Any] | None) -> bool:
    status = str((bundle or {}).get("status") or "").strip().lower()
    return status not in {"", "shadow", "shadow-blocked", "unavailable", "not_applicable", "advisory_candidate"}


def _build_default_runtime_signal_view(bundle: dict[str, Any] | None) -> dict[str, Any]:
    bundle = dict(bundle or {})
    signals = dict(bundle.get("signals") or {})
    published_state = (
        signals.get("effective_state_final")
        or signals.get("effective_state")
        or signals.get("reconciled_state")
        or signals.get("state")
        or ""
    )
    published_track = (
        signals.get("reconciled_management_track")
        or signals.get("management_track")
        or ""
    )
    return {
        "state": published_state,
        "management_track": published_track,
        "clinical_kernel_snapshot": dict(bundle.get("clinical_kernel_snapshot") or {}),
        "effective_state": published_state,
        "effective_recommendation_family": str(
            (bundle.get("therapeutic_readiness_bundle") or {}).get("candidate_family")
            or (bundle.get("next_best_action") or {}).get("recommendation_family")
            or ""
        ),
        "surface_consistency_status": str(bundle.get("surface_consistency_status") or "consistent"),
        "surface_consistency_flags": list(bundle.get("surface_consistency_flags") or []),
        "ready_to_restage": bool(signals.get("ready_to_restage")),
        "signals": list(signals.get("signals") or []),
        "critical_missing": list(signals.get("critical_missing") or []),
        "awaiting_review": list(signals.get("awaiting_review") or []),
        "active_safety": list(signals.get("active_safety") or []),
        "next_best_action": dict(bundle.get("next_best_action") or {}),
        "decision_governance_bundle": dict(bundle.get("decision_governance_bundle") or {}),
        "diagnostic_certainty_bundle": dict(bundle.get("diagnostic_certainty_bundle") or {}),
        "staging_certainty_bundle": dict(bundle.get("staging_certainty_bundle") or {}),
        "minimum_decisive_dataset_bundle": dict(bundle.get("minimum_decisive_dataset_bundle") or {}),
        "decision_evidence_currentness_bundle": dict(bundle.get("decision_evidence_currentness_bundle") or {}),
        "selected_decision_evidence_status": str((bundle.get("decision_evidence_currentness_bundle") or {}).get("selected_decision_evidence_status") or ""),
        "selected_decision_release_status": str((bundle.get("decision_evidence_currentness_bundle") or {}).get("selected_decision_release_status") or ""),
        "therapeutic_window_bundle": dict(bundle.get("therapeutic_window_bundle") or {}),
        "window_worklist_bundle": dict(bundle.get("window_worklist_bundle") or {}),
        "therapeutic_readiness_bundle": dict(bundle.get("therapeutic_readiness_bundle") or {}),
        "clinical_readiness_tower": dict(bundle.get("clinical_readiness_tower") or {}),
        "tumor_board_os": dict(bundle.get("tumor_board_os") or {}),
        "care_pathway_os": dict(bundle.get("care_pathway_os") or {}),
        "clinical_memory_os": dict(bundle.get("clinical_memory_os") or {}),
        "advanced_followup_bundle": dict(bundle.get("advanced_followup_bundle") or {}),
        "staging_adjudication_bundle": dict(bundle.get("staging_adjudication_bundle") or {}),
        "supportive_care_toxicity_readiness_bundle": dict(bundle.get("supportive_care_toxicity_readiness_bundle") or {}),
        "supportive_readiness_status": str((bundle.get("supportive_care_toxicity_readiness_bundle") or {}).get("supportive_readiness_status") or ""),
        "supportive_priority": str((bundle.get("supportive_care_toxicity_readiness_bundle") or {}).get("supportive_priority") or ""),
        "pro_decision_bundle": dict(bundle.get("pro_decision_bundle") or {}),
        "shared_decision_bundle": dict(bundle.get("shared_decision_bundle") or {}),
        "palliative_transition_bundle": dict(bundle.get("palliative_transition_bundle") or {}),
        "palliative_monitoring_package": dict(bundle.get("palliative_monitoring_package") or {}),
        "survivorship_transition_bundle": dict(bundle.get("survivorship_transition_bundle") or {}),
        "survivorship_monitoring_package": dict(bundle.get("survivorship_monitoring_package") or {}),
        "score_interpretation_catalog_snapshot": dict(bundle.get("score_interpretation_catalog_snapshot") or {}),
        "precision_workflow_bundle": dict(bundle.get("precision_workflow_bundle") or {}),
        "registry_core_bundle": dict(bundle.get("registry_core_bundle") or {}),
        "endpoint_adjudication_bundle": dict(bundle.get("endpoint_adjudication_bundle") or {}),
        "data_certainty_bundle": dict(bundle.get("data_certainty_bundle") or {}),
        "mcode_projection": dict(signals.get("mcode_projection") or {}),
        "evidence_basis": list(signals.get("evidence_basis") or []),
    }


def build_runtime_signal_snapshot(
    *,
    patient_record: dict[str, Any],
    bundle: dict[str, Any],
    latest_snapshot: dict[str, Any] | None,
    decision_input_requirements: dict[str, Any],
    outcome_bundle: dict[str, Any],
    prognostic_bundle: dict[str, Any],
    psa_forecast_bundle: dict[str, Any],
    live_benchmark_bundle: dict[str, Any],
    vertical_bundles: dict[str, Any],
    kernel_bundles: dict[str, Any],
    qa_passed: bool | None,
    sequence_summary: dict[str, Any] | str | None,
    ui_contradiction_flags: list[dict[str, Any]] | list[str] | None,
) -> dict[str, Any]:
    patient_record = dict(patient_record or {})
    runtime_bundle = dict(bundle or {})
    latest_snapshot = dict(latest_snapshot or {})
    if not latest_snapshot:
        latest_snapshot = _build_default_runtime_signal_view(runtime_bundle)

    fresh_next_best_action = dict(runtime_bundle.get("next_best_action") or {})
    if fresh_next_best_action:
        latest_snapshot["next_best_action"] = fresh_next_best_action

    clinical_fact_bundle = dict(kernel_bundles.get("clinical_fact_bundle") or {})
    fact_conflict_summary = dict(kernel_bundles.get("fact_conflict_summary") or {})
    contradiction_resolution_bundle = dict(kernel_bundles.get("contradiction_resolution_bundle") or {})
    state_reclassification_bundle = dict(kernel_bundles.get("state_reclassification_bundle") or {})

    if contradiction_resolution_bundle.get("block_status") == "hard_stop":
        runtime_bundle["recommendation_block_status"] = "hard_stop"
        runtime_bundle["recommendation_block_reason"] = (
            (contradiction_resolution_bundle.get("contradictions") or [{}])[0].get("title")
            or "Existe una contradicción clínica crítica no resuelta."
        )
        governance_view = dict(runtime_bundle.get("decision_governance_bundle") or {})
        governance_view["recommendation_block_status"] = "hard_stop"
        governance_view["recommendation_block_reason"] = runtime_bundle["recommendation_block_reason"]
        governance_view["critical_contradictions_open_count"] = int(
            contradiction_resolution_bundle.get("critical_unresolved_count") or 0
        )
        runtime_bundle["decision_governance_bundle"] = governance_view

    active_copilot_bundle = dict(vertical_bundles.get("active_copilot_bundle") or {})
    crpc_copilot_bundle = dict(vertical_bundles.get("crpc_copilot_bundle") or {})
    post_rp_salvage_bundle = dict(vertical_bundles.get("post_rp_salvage_bundle") or {})
    mhspc_copilot_bundle = dict(vertical_bundles.get("mhspc_copilot_bundle") or {})
    diagnostic_biopsy_bundle = dict(vertical_bundles.get("diagnostic_biopsy_bundle") or {})
    localized_surveillance_bundle = dict(vertical_bundles.get("localized_surveillance_bundle") or {})
    post_rt_salvage_bundle = dict(vertical_bundles.get("post_rt_salvage_bundle") or {})

    current_state = str(vertical_bundles.get("current_state") or "")
    current_track = str(vertical_bundles.get("current_track") or "")
    runtime_signals = dict(runtime_bundle.get("signals") or {})
    published_state = str(active_copilot_bundle.get("effective_state") or current_state)
    published_track = str(active_copilot_bundle.get("effective_management_track") or current_track)
    latest_testosterone_value = patient_record.get("latest_testosterone_value")
    latest_testosterone_date = str(patient_record.get("latest_testosterone_date") or "")
    castrate_status_resolved = str(
        runtime_signals.get("castrate_testosterone_status")
        or patient_record.get("castrate_status_resolved")
        or ""
    ).strip()
    if not castrate_status_resolved and latest_testosterone_value is not None:
        try:
            castrate_status_resolved = "confirmed_castrate" if float(latest_testosterone_value) <= 50 else "not_castrate"
        except (TypeError, ValueError):
            castrate_status_resolved = ""
    current_adt_context = str(
        runtime_signals.get("current_adt_context")
        or patient_record.get("current_adt_context")
        or ""
    ).strip()
    published_recommendation = {}
    top_active_window = dict((runtime_bundle.get("window_worklist_bundle") or {}).get("top_active_window") or {})
    preserve_runtime_recommendation = bool(
        str(runtime_bundle.get("recommendation_block_status") or "").lower() == "hard_stop"
        or (
            top_active_window
            and str(top_active_window.get("opportunity_loss_risk") or "").lower() != "none"
        )
    )
    if _bundle_can_override_recommendation(active_copilot_bundle):
        published_recommendation = dict(
            active_copilot_bundle.get("final_presented_recommendation")
            or active_copilot_bundle.get("rule_based_recommendation")
            or {}
        )
    if published_recommendation and not preserve_runtime_recommendation:
        latest_snapshot["next_best_action"] = {
            "title": str(published_recommendation.get("recommended_action") or ""),
            "rationale": str(published_recommendation.get("rationale") or ""),
            "recommendation_family": str(published_recommendation.get("recommendation_family") or ""),
            "evidence_basis": list(active_copilot_bundle.get("guideline_basis") or []),
            "source": str(published_recommendation.get("source") or "rule_based_primary"),
        }
    elif published_recommendation:
        latest_snapshot.setdefault("next_best_action", {})
        latest_snapshot["next_best_action"].setdefault(
            "evidence_basis",
            list(active_copilot_bundle.get("guideline_basis") or []),
        )
        latest_snapshot["next_best_action"].setdefault(
            "source",
            str(published_recommendation.get("source") or "governance_primary"),
        )

    latest_snapshot.update(
        {
            "explicit_state": runtime_bundle.get("signals", {}).get("explicit_state"),
            "effective_state_final": published_state,
            "effective_management_track_final": published_track,
            "effective_state": published_state,
            "effective_recommendation_family": runtime_bundle.get("effective_recommendation_family")
            or (runtime_bundle.get("therapeutic_readiness_bundle") or {}).get("candidate_family")
            or (latest_snapshot.get("next_best_action") or {}).get("recommendation_family")
            or "",
            "effective_management_track": published_track,
            "reconciled_state": runtime_bundle.get("signals", {}).get("reconciled_state"),
            "reconciled_management_track": runtime_bundle.get("signals", {}).get("reconciled_management_track"),
            "state_conflict_flag": runtime_bundle.get("signals", {}).get("state_conflict_flag"),
            "state_conflict_reason": runtime_bundle.get("signals", {}).get("state_conflict_reason"),
            "supporting_evidence": runtime_bundle.get("signals", {}).get("supporting_evidence", {}),
            "clinical_kernel_snapshot": runtime_bundle.get("clinical_kernel_snapshot", {}),
            "surface_consistency_status": runtime_bundle.get("surface_consistency_status", "consistent"),
            "surface_consistency_flags": runtime_bundle.get("surface_consistency_flags", []),
            "metastatic_state_bundle": runtime_bundle.get("metastatic_state_bundle", {}),
            "metastatic_stage_resolved": runtime_bundle.get("signals", {}).get("metastatic_stage_resolved", "M0"),
            "metastatic_stage_label": runtime_bundle.get("signals", {}).get("metastatic_stage_label", "M0"),
            "m_substage_resolved": runtime_bundle.get("signals", {}).get("m_substage_resolved", "M0"),
            "metastatic_detection_basis": runtime_bundle.get("signals", {}).get("metastatic_detection_basis", "unknown"),
            "current_adt_context": current_adt_context,
            "castrate_testosterone_status": castrate_status_resolved,
            "castrate_status_resolved": castrate_status_resolved,
            "latest_testosterone_value": latest_testosterone_value,
            "latest_testosterone_date": latest_testosterone_date,
            "nmcrpc_eligible": runtime_bundle.get("signals", {}).get("nmcrpc_eligible", False),
            "nmcrpc_ineligibility_reason": runtime_bundle.get("signals", {}).get("nmcrpc_ineligibility_reason", ""),
            "state_reclassification_required": runtime_bundle.get("signals", {}).get("state_reclassification_required", False),
            "state_reclassification_reason": runtime_bundle.get("signals", {}).get("state_reclassification_reason", ""),
            "restaging_update_required": runtime_bundle.get("signals", {}).get("restaging_update_required", False),
            "restaging_currentness_status": runtime_bundle.get("signals", {}).get("restaging_currentness_status", "unknown"),
            "restaging_update_reason": runtime_bundle.get("signals", {}).get("restaging_update_reason", ""),
            "progression_verification_required": runtime_bundle.get("signals", {}).get("progression_verification_required", False),
            "progression_verification_required_fields": runtime_bundle.get("signals", {}).get("progression_verification_required_fields", []),
            "progression_verification_missing_fields": runtime_bundle.get("signals", {}).get("progression_verification_missing_fields", []),
            "progression_verification_target_state_if_confirmed": runtime_bundle.get("signals", {}).get("progression_verification_target_state_if_confirmed", ""),
            "progression_verification_target_state_if_not_castrate": runtime_bundle.get("signals", {}).get("progression_verification_target_state_if_not_castrate", ""),
            "post_prostatectomy_course": runtime_bundle.get("signals", {}).get("post_prostatectomy_course", ""),
            "transition_resolution": runtime_bundle.get("transition_resolution", {}),
            "care_intent_contract": runtime_bundle.get("care_intent_contract", {}),
            "palliative_transition_bundle": runtime_bundle.get("palliative_transition_bundle", {}),
            "palliative_monitoring_package": runtime_bundle.get("palliative_monitoring_package", {}),
            "survivorship_transition_bundle": runtime_bundle.get("survivorship_transition_bundle", {}),
            "survivorship_monitoring_package": runtime_bundle.get("survivorship_monitoring_package", {}),
            "late_effects_profile": runtime_bundle.get("late_effects_profile", {}),
            "functional_recovery_profile": runtime_bundle.get("functional_recovery_profile", {}),
            "survivorship_schedule_overlay": runtime_bundle.get("survivorship_schedule_overlay", {}),
            "survivorship_plan": runtime_bundle.get("survivorship_plan", {}),
            "symptom_burden_profile": runtime_bundle.get("symptom_burden_profile", {}),
            "advance_care_planning_status": runtime_bundle.get("advance_care_planning_status", {}),
            "hospice_eligibility": runtime_bundle.get("hospice_eligibility", {}),
            "acute_palliative_alerts": runtime_bundle.get("acute_palliative_alerts", []),
            "recommended_supportive_referrals": runtime_bundle.get("recommended_supportive_referrals", []),
            "outcome_events_summary": outcome_bundle.get("outcome_events_summary", {}),
            "pending_adjudications": outcome_bundle.get("pending_adjudications", []),
            "current_response_state": outcome_bundle.get("current_response_state", {}),
            "current_course_status": outcome_bundle.get("current_course_status", ""),
            "last_adjudicated_event": outcome_bundle.get("last_adjudicated_event", {}),
            "trial_comparable_endpoints": outcome_bundle.get("trial_comparable_endpoints", []),
            "current_trial_comparable_profile": outcome_bundle.get("current_trial_comparable_profile", {}),
            "prognostic_modifiers": prognostic_bundle.get("prognostic_modifiers", []),
            "prognostic_recommended_actions": prognostic_bundle.get("recommended_actions", []),
            "prognostic_followup_impact": prognostic_bundle.get("followup_impact", []),
            "prognostic_capture_targets": prognostic_bundle.get("capture_targets", []),
            "backbone_alignment": prognostic_bundle.get("backbone_alignment", {}),
            "cadence_adjusted_by": prognostic_bundle.get("cadence_adjusted_by", []),
            "psa_forecast": psa_forecast_bundle,
            "forecast_reliability": psa_forecast_bundle.get("reliability", {}),
            "live_benchmark": live_benchmark_bundle,
            "benchmark_reliability": live_benchmark_bundle.get("reliability", {}),
            "longitudinal_truth_snapshot": runtime_bundle.get("longitudinal_truth_snapshot", {}),
            "decision_recalculation_trace": runtime_bundle.get("decision_recalculation_trace", {}),
            "guideline_followup_plan": runtime_bundle.get("guideline_followup_plan", {}),
            "laboratory_intelligence_profile": runtime_bundle.get("laboratory_intelligence_profile", {}),
            "latest_clinically_decisive_visit": runtime_bundle.get("latest_clinically_decisive_visit", {}),
            "blocking_inputs": decision_input_requirements.get("blocking_inputs", []),
            "hard_blocking_inputs": decision_input_requirements.get("hard_blocking_inputs", []),
            "decision_blocking_inputs": decision_input_requirements.get("decision_blocking_inputs", []),
            "supportive_gaps": decision_input_requirements.get("supportive_gaps", []),
            "required_to_recalculate": decision_input_requirements.get("required_to_recalculate", []),
            "optional_context_inputs": decision_input_requirements.get("optional_context_inputs", []),
            "decision_domains_blocked": decision_input_requirements.get("decision_domains_blocked", []),
            "guideline_basis": runtime_bundle.get("guideline_followup_plan", {}).get("schedule_evidence_basis", []),
            "ui_contradiction_flags": list(ui_contradiction_flags or []),
            "crpc_copilot_bundle": crpc_copilot_bundle,
            "crpc_copilot_status": crpc_copilot_bundle.get("status", "not_applicable"),
            "post_rp_salvage_bundle": post_rp_salvage_bundle,
            "post_rp_copilot_status": post_rp_salvage_bundle.get("status", "not_applicable"),
            "mhspc_copilot_bundle": mhspc_copilot_bundle,
            "mhspc_copilot_status": mhspc_copilot_bundle.get("status", "not_applicable"),
            "diagnostic_biopsy_bundle": diagnostic_biopsy_bundle,
            "diagnostic_copilot_status": diagnostic_biopsy_bundle.get("status", "not_applicable"),
            "localized_surveillance_bundle": localized_surveillance_bundle,
            "localized_copilot_status": localized_surveillance_bundle.get("status", "not_applicable"),
            "post_rt_salvage_bundle": post_rt_salvage_bundle,
            "post_rt_copilot_status": post_rt_salvage_bundle.get("status", "not_applicable"),
            "salvage_window_status": post_rp_salvage_bundle.get("salvage_window_status", ""),
            "salvage_window_reason": post_rp_salvage_bundle.get("salvage_window_reason", ""),
            "post_rt_salvage_window_status": post_rt_salvage_bundle.get("post_rt_salvage_window_status", ""),
            "qa_passed": qa_passed,
            "sequence_summary": sequence_summary,
            "crpc_schedule_overlay": crpc_copilot_bundle.get("crpc_schedule_overlay", {}),
            "post_rp_schedule_overlay": post_rp_salvage_bundle.get("post_rp_schedule_overlay", {}),
            "mhspc_schedule_overlay": mhspc_copilot_bundle.get("mhspc_schedule_overlay", {}),
            "diagnostic_schedule_overlay": diagnostic_biopsy_bundle.get("diagnostic_schedule_overlay", {}),
            "localized_schedule_overlay": localized_surveillance_bundle.get("localized_schedule_overlay", {}),
            "post_rt_schedule_overlay": post_rt_salvage_bundle.get("post_rt_schedule_overlay", {}),
            "decision_governance_bundle": runtime_bundle.get("decision_governance_bundle", {}),
            "recommendation_block_status": runtime_bundle.get("recommendation_block_status", ""),
            "recommendation_block_reason": runtime_bundle.get("recommendation_block_reason", ""),
            "allowed_actions_while_blocked": runtime_bundle.get("allowed_actions_while_blocked", []),
            "decision_blocking_bundle": runtime_bundle.get("decision_blocking_bundle", {}),
            "diagnostic_certainty_bundle": runtime_bundle.get("diagnostic_certainty_bundle", {}),
            "staging_certainty_bundle": runtime_bundle.get("staging_certainty_bundle", {}),
            "minimum_decisive_dataset_bundle": runtime_bundle.get("minimum_decisive_dataset_bundle", {}),
            "decision_evidence_currentness_bundle": runtime_bundle.get("decision_evidence_currentness_bundle", {}),
            "selected_decision_evidence_status": (runtime_bundle.get("decision_evidence_currentness_bundle") or {}).get("selected_decision_evidence_status", ""),
            "selected_decision_release_status": (runtime_bundle.get("decision_evidence_currentness_bundle") or {}).get("selected_decision_release_status", ""),
            "decision_refresh_actions": (runtime_bundle.get("decision_evidence_currentness_bundle") or {}).get("refresh_actions", []),
            "therapeutic_window_bundle": runtime_bundle.get("therapeutic_window_bundle", {}),
            "window_worklist_bundle": runtime_bundle.get("window_worklist_bundle", {}),
            "therapeutic_readiness_bundle": runtime_bundle.get("therapeutic_readiness_bundle", {}),
            "clinical_readiness_tower": runtime_bundle.get("clinical_readiness_tower", {}),
            "tumor_board_os": runtime_bundle.get("tumor_board_os", {}),
            "care_pathway_os": runtime_bundle.get("care_pathway_os", {}),
            "clinical_memory_os": runtime_bundle.get("clinical_memory_os", {}),
            "advanced_followup_bundle": runtime_bundle.get("advanced_followup_bundle", {}),
            "staging_adjudication_bundle": runtime_bundle.get("staging_adjudication_bundle", {}),
            "supportive_care_toxicity_readiness_bundle": runtime_bundle.get("supportive_care_toxicity_readiness_bundle", {}),
            "supportive_readiness_status": (runtime_bundle.get("supportive_care_toxicity_readiness_bundle") or {}).get("supportive_readiness_status", ""),
            "supportive_priority": (runtime_bundle.get("supportive_care_toxicity_readiness_bundle") or {}).get("supportive_priority", ""),
            "required_support_actions": (runtime_bundle.get("supportive_care_toxicity_readiness_bundle") or {}).get("required_support_actions", []),
            "readiness_status": (runtime_bundle.get("therapeutic_readiness_bundle") or {}).get("readiness_status", ""),
            "release_blockers": (runtime_bundle.get("therapeutic_readiness_bundle") or {}).get("release_blockers", []),
            "safety_blockers": (runtime_bundle.get("therapeutic_readiness_bundle") or {}).get("safety_blockers", []),
            "required_to_release": (runtime_bundle.get("therapeutic_readiness_bundle") or {}).get("required_to_release", []),
            "next_best_action_if_not_ready": (runtime_bundle.get("therapeutic_readiness_bundle") or {}).get("next_best_action_if_not_ready", {}),
            "competing_intent": (runtime_bundle.get("therapeutic_readiness_bundle") or {}).get("competing_intent", {}),
            "localized_modality_fitness_bundle": runtime_bundle.get("localized_modality_fitness_bundle", {}),
            "localized_tradeoff_bundle": runtime_bundle.get("localized_tradeoff_bundle", {}),
            "radical_prostatectomy_candidacy_profile": runtime_bundle.get("radical_prostatectomy_candidacy_profile", {}),
            "localized_survival_context_bundle": runtime_bundle.get("localized_survival_context_bundle", {}),
            "active_surveillance_monitoring_profile": runtime_bundle.get("active_surveillance_monitoring_profile", {}),
            "patient_priority_profile": runtime_bundle.get("patient_priority_profile", {}),
            "clinician_decision_capture_bundle": runtime_bundle.get("clinician_decision_capture_bundle", {}),
            "state_transition_confirmation_bundle": runtime_bundle.get("state_transition_confirmation_bundle", {}),
            "adherence_tracking_bundle": runtime_bundle.get("adherence_tracking_bundle", {}),
            "tumor_board_outcome_bundle": runtime_bundle.get("tumor_board_outcome_bundle", {}),
            "pro_decision_bundle": runtime_bundle.get("pro_decision_bundle", {}),
            "shared_decision_bundle": runtime_bundle.get("shared_decision_bundle", {}),
            "ctdna_refinement_bundle": runtime_bundle.get("ctdna_refinement_bundle", {}),
            "multimodal_imaging_concordance_bundle": runtime_bundle.get("multimodal_imaging_concordance_bundle", {}),
            "precision_workflow_bundle": runtime_bundle.get("precision_workflow_bundle", {}),
            "registry_core_bundle": runtime_bundle.get("registry_core_bundle", {}),
            "endpoint_adjudication_bundle": runtime_bundle.get("endpoint_adjudication_bundle", {}),
            "data_certainty_bundle": runtime_bundle.get("data_certainty_bundle", {}),
            "ichom_compliance_bundle": runtime_bundle.get("ichom_compliance_bundle", {}),
            "treatment_adverse_event_bundle": runtime_bundle.get("treatment_adverse_event_bundle", {}),
            "population_survival_context_bundle": runtime_bundle.get("population_survival_context_bundle", {}),
            "cost_access_context_bundle": runtime_bundle.get("cost_access_context_bundle", {}),
            "score_interpretation_catalog_snapshot": runtime_bundle.get("score_interpretation_catalog_snapshot", {}),
            "clinical_fact_bundle": clinical_fact_bundle,
            "fact_freshness_summary": clinical_fact_bundle.get("freshness_summary", {}),
            "fact_conflict_summary": fact_conflict_summary,
            "contradiction_resolution_bundle": contradiction_resolution_bundle,
            "state_reclassification_bundle": state_reclassification_bundle,
        }
    )

    return {
        "signals": latest_snapshot,
        "runtime_bundle": runtime_bundle,
        "recommendation_block_status": runtime_bundle.get("recommendation_block_status", ""),
        "recommendation_block_reason": runtime_bundle.get("recommendation_block_reason", ""),
        "published_state": published_state,
        "published_track": published_track,
        "published_recommendation": published_recommendation,
    }
