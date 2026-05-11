from __future__ import annotations

from typing import Any


_GENERIC_RECOMMENDATION_FAMILIES = {
    "",
    "observation_family",
    "observación / backbone",
    "observacion / backbone",
    "post_rt_salvage",
    "ruta de rescate",
    "salvage",
    "control local / mdt",
    "local_mdt_family",
    "ruta post-rt",
    "confirmación post-rt",
    "confirmacion post-rt",
}


def _normalize_recommendation_family_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _is_generic_recommendation_family(value: Any) -> bool:
    return _normalize_recommendation_family_text(value) in _GENERIC_RECOMMENDATION_FAMILIES


def _should_backfill_recommendation_family(existing_value: Any, candidate_value: Any) -> bool:
    existing = str(existing_value or "").strip()
    candidate = str(candidate_value or "").strip()
    if not candidate:
        return False
    if not existing:
        return True
    if existing == candidate:
        return False
    if _is_generic_recommendation_family(existing) and not _is_generic_recommendation_family(candidate):
        return True
    return False


def build_runtime_context_bundle(
    *,
    bundle: dict[str, Any],
    signals: dict[str, Any],
    vertical_bundles: dict[str, Any],
    patient_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    patient_record = dict(patient_record or {})
    latest_testosterone_value = patient_record.get("latest_testosterone_value")
    castrate_status_resolved = str(
        (signals or {}).get("castrate_testosterone_status")
        or patient_record.get("castrate_status_resolved")
        or ""
    ).strip()
    if not castrate_status_resolved and latest_testosterone_value is not None:
        try:
            castrate_status_resolved = "confirmed_castrate" if float(latest_testosterone_value) <= 50 else "not_castrate"
        except (TypeError, ValueError):
            castrate_status_resolved = ""
    return {
        **dict(bundle or {}),
        "signals": dict(signals or {}),
        "clinical_kernel_snapshot": dict((bundle or {}).get("clinical_kernel_snapshot") or {}),
        "effective_state": str(
            (bundle or {}).get("effective_state")
            or (signals or {}).get("effective_state_final")
            or (signals or {}).get("effective_state")
            or (signals or {}).get("reconciled_state")
            or ""
        ),
        "effective_recommendation_family": str(
            (bundle or {}).get("effective_recommendation_family")
            or ((bundle or {}).get("therapeutic_readiness_bundle") or {}).get("candidate_family")
            or ((signals or {}).get("next_best_action") or {}).get("recommendation_family")
            or ""
        ),
        "surface_consistency_status": str((bundle or {}).get("surface_consistency_status") or "consistent"),
        "surface_consistency_flags": list((bundle or {}).get("surface_consistency_flags") or []),
        "latest_testosterone_value": latest_testosterone_value,
        "latest_testosterone_date": patient_record.get("latest_testosterone_date") or "",
        "castrate_status_resolved": castrate_status_resolved,
        "decision_evidence_currentness_bundle": dict((bundle or {}).get("decision_evidence_currentness_bundle") or {}),
        "therapeutic_readiness_bundle": dict((bundle or {}).get("therapeutic_readiness_bundle") or {}),
        "advanced_followup_bundle": dict((bundle or {}).get("advanced_followup_bundle") or {}),
        "staging_adjudication_bundle": dict((bundle or {}).get("staging_adjudication_bundle") or {}),
        "supportive_care_toxicity_readiness_bundle": dict((bundle or {}).get("supportive_care_toxicity_readiness_bundle") or {}),
        "crpc_copilot_bundle": dict(vertical_bundles.get("crpc_copilot_bundle") or {}),
        "post_rp_salvage_bundle": dict(vertical_bundles.get("post_rp_salvage_bundle") or {}),
        "mhspc_copilot_bundle": dict(vertical_bundles.get("mhspc_copilot_bundle") or {}),
        "diagnostic_biopsy_bundle": dict(vertical_bundles.get("diagnostic_biopsy_bundle") or {}),
        "localized_surveillance_bundle": dict(vertical_bundles.get("localized_surveillance_bundle") or {}),
        "post_rt_salvage_bundle": dict(vertical_bundles.get("post_rt_salvage_bundle") or {}),
    }


def prepare_runtime_publication_state(
    *,
    patient_record: dict[str, Any],
    bundle: dict[str, Any],
    signals: dict[str, Any],
    decision_input_requirements: dict[str, Any],
    vertical_bundles: dict[str, Any],
) -> dict[str, Any]:
    from prostanet.domains.patient_tracking.longitudinal_intelligence import (
        _align_next_best_action_with_care_intent,
    )

    patient_record = dict(patient_record or {})
    runtime_bundle = dict(bundle or {})
    signals = dict(signals or {})
    signals["next_best_action"] = _align_next_best_action_with_care_intent(
        signals.get("next_best_action", {}),
        runtime_bundle.get("care_intent_contract", {}),
        decision_input_requirements,
    )

    preferred_snapshot_regimen = (
        (((patient_record.get("latest_assessment") or {}).get("result_snapshot") or {}).get("preferred_frontline_regimen") or {})
        if isinstance((patient_record.get("latest_assessment") or {}).get("result_snapshot"), dict)
        else {}
    )
    preferred_snapshot_family = str(
        preferred_snapshot_regimen.get("family_label")
        or preferred_snapshot_regimen.get("family_code")
        or ""
    ).strip()
    published_state = str(signals.get("effective_state_final") or signals.get("effective_state") or "")
    preserve_runtime_recommendation_family = published_state == "post_radiotherapy_or_local_salvage"
    current_snapshot_family = str(
        (signals.get("next_best_action") or {}).get("recommendation_family") or ""
    ).strip()
    if preferred_snapshot_family and (
        not preserve_runtime_recommendation_family
        or _should_backfill_recommendation_family(current_snapshot_family, preferred_snapshot_family)
    ):
        signals.setdefault("next_best_action", {})
        signals["next_best_action"]["recommendation_family"] = preferred_snapshot_family
        current_snapshot_family = preferred_snapshot_family
    published_recommendation = dict(vertical_bundles.get("published_recommendation") or {})
    published_family = str(published_recommendation.get("recommendation_family") or "").strip()
    if published_recommendation and (
        not preserve_runtime_recommendation_family
        or _should_backfill_recommendation_family(current_snapshot_family, published_family)
    ):
        signals.setdefault("next_best_action", {})
        signals["next_best_action"]["recommendation_family"] = published_family

    runtime_context_bundle = build_runtime_context_bundle(
        bundle=runtime_bundle,
        signals=signals,
        vertical_bundles=vertical_bundles,
        patient_record=patient_record,
    )
    return {
        "signals": signals,
        "runtime_context_bundle": runtime_context_bundle,
    }


def build_runtime_publication_payload(
    *,
    patient_record: dict[str, Any],
    bundle: dict[str, Any],
    signals: dict[str, Any],
    orchestration: dict[str, Any],
    decision_input_requirements: dict[str, Any],
    outcome_bundle: dict[str, Any],
    prognostic_bundle: dict[str, Any],
    psa_forecast_bundle: dict[str, Any],
    live_benchmark_bundle: dict[str, Any],
    vertical_bundles: dict[str, Any],
    kernel_bundles: dict[str, Any],
    qa_passed: bool | None,
    sequence_summary: dict[str, Any] | str | None,
    clinical_ledger_bundle: dict[str, Any],
    copilot_alerts: list[dict[str, Any]] | list[Any],
    transition_proposals: list[dict[str, Any]] | list[Any],
    recommendation_audit: list[dict[str, Any]] | list[Any],
) -> dict[str, Any]:
    patient_record = dict(patient_record or {})
    runtime_bundle = dict(bundle or {})
    prepublication = prepare_runtime_publication_state(
        patient_record=patient_record,
        bundle=runtime_bundle,
        signals=signals,
        decision_input_requirements=decision_input_requirements,
        vertical_bundles=vertical_bundles,
    )
    signals = dict(prepublication.get("signals") or {})
    clinical_fact_bundle = dict(kernel_bundles.get("clinical_fact_bundle") or {})
    fact_conflict_summary = dict(kernel_bundles.get("fact_conflict_summary") or {})
    contradiction_resolution_bundle = dict(kernel_bundles.get("contradiction_resolution_bundle") or {})
    state_reclassification_bundle = dict(kernel_bundles.get("state_reclassification_bundle") or {})
    runtime_context_bundle = dict(prepublication.get("runtime_context_bundle") or {})
    latest_testosterone_value = patient_record.get("latest_testosterone_value")
    castrate_status_resolved = str(
        signals.get("castrate_testosterone_status")
        or patient_record.get("castrate_status_resolved")
        or ""
    ).strip()
    if not castrate_status_resolved and latest_testosterone_value is not None:
        try:
            castrate_status_resolved = "confirmed_castrate" if float(latest_testosterone_value) <= 50 else "not_castrate"
        except (TypeError, ValueError):
            castrate_status_resolved = ""
    signals_to_persist = {
        "signals": signals,
        "next_best_action": signals.get("next_best_action", {}),
    }

    crpc_copilot_bundle = dict(vertical_bundles.get("crpc_copilot_bundle") or {})
    post_rp_salvage_bundle = dict(vertical_bundles.get("post_rp_salvage_bundle") or {})
    mhspc_copilot_bundle = dict(vertical_bundles.get("mhspc_copilot_bundle") or {})
    diagnostic_biopsy_bundle = dict(vertical_bundles.get("diagnostic_biopsy_bundle") or {})
    localized_surveillance_bundle = dict(vertical_bundles.get("localized_surveillance_bundle") or {})
    post_rt_salvage_bundle = dict(vertical_bundles.get("post_rt_salvage_bundle") or {})

    open_proposals = [
        proposal for proposal in (transition_proposals or [])
        if proposal.get("proposal_status") == "open"
        and (runtime_bundle.get("transition_resolution") or {}).get("policy") == "manual_confirmation_required"
    ]
    recent_audit = list(recommendation_audit or [])[:8]
    therapeutic_readiness_bundle = dict(runtime_bundle.get("therapeutic_readiness_bundle") or {})
    decision_evidence_currentness_bundle = dict(runtime_bundle.get("decision_evidence_currentness_bundle") or {})

    public_payload = {
        "signals": signals,
        "clinical_kernel_snapshot": runtime_bundle.get("clinical_kernel_snapshot", {}),
        "effective_state": runtime_bundle.get("effective_state") or signals.get("effective_state_final") or signals.get("effective_state") or signals.get("reconciled_state") or "",
        "effective_recommendation_family": runtime_bundle.get("effective_recommendation_family") or therapeutic_readiness_bundle.get("candidate_family") or (signals.get("next_best_action") or {}).get("recommendation_family") or "",
        "surface_consistency_status": runtime_bundle.get("surface_consistency_status", "consistent"),
        "surface_consistency_flags": runtime_bundle.get("surface_consistency_flags", []),
        "latest_testosterone_value": latest_testosterone_value,
        "latest_testosterone_date": patient_record.get("latest_testosterone_date") or "",
        "castrate_status_resolved": castrate_status_resolved,
        "decision_evidence_currentness_bundle": decision_evidence_currentness_bundle,
        "selected_decision_evidence_status": decision_evidence_currentness_bundle.get("selected_decision_evidence_status", ""),
        "selected_decision_release_status": decision_evidence_currentness_bundle.get("selected_decision_release_status", ""),
        "decision_refresh_actions": decision_evidence_currentness_bundle.get("refresh_actions", []),
        "therapeutic_readiness_bundle": therapeutic_readiness_bundle,
        "readiness_status": therapeutic_readiness_bundle.get("readiness_status", ""),
        "release_blockers": therapeutic_readiness_bundle.get("release_blockers", []),
        "safety_blockers": therapeutic_readiness_bundle.get("safety_blockers", []),
        "required_to_release": therapeutic_readiness_bundle.get("required_to_release", []),
        "next_best_action_if_not_ready": therapeutic_readiness_bundle.get("next_best_action_if_not_ready", {}),
        "competing_intent": therapeutic_readiness_bundle.get("competing_intent", {}),
        "advanced_followup_bundle": runtime_bundle.get("advanced_followup_bundle", {}),
        "staging_adjudication_bundle": runtime_bundle.get("staging_adjudication_bundle", {}),
        "supportive_care_toxicity_readiness_bundle": runtime_bundle.get("supportive_care_toxicity_readiness_bundle", {}),
        "supportive_readiness_status": (runtime_bundle.get("supportive_care_toxicity_readiness_bundle") or {}).get("supportive_readiness_status", ""),
        "supportive_priority": (runtime_bundle.get("supportive_care_toxicity_readiness_bundle") or {}).get("supportive_priority", ""),
        "required_support_actions": (runtime_bundle.get("supportive_care_toxicity_readiness_bundle") or {}).get("required_support_actions", []),
        "metastatic_state_bundle": runtime_bundle.get("metastatic_state_bundle", {}),
        "transition_proposals": open_proposals,
        "next_best_action": signals.get("next_best_action") or runtime_bundle.get("next_best_action", {}),
        "recommendation_audit": recent_audit,
        "copilot_alerts": list(copilot_alerts or []),
        "alert_summary": orchestration.get("alert_summary", {}),
        "encounters": orchestration.get("encounters", []),
        "master_followup_plan": orchestration.get("master_followup_plan", {}),
        "master_followup_summary": orchestration.get("master_followup_summary", {}),
        "schedule_anchor_strength": orchestration.get("schedule_anchor_strength", "strong"),
        "comparative_eligibility_matrix": runtime_bundle.get("comparative_eligibility_matrix", {}),
        "sequence_transition_bundle": runtime_bundle.get("sequence_transition_bundle", {}),
        "active_regimen_monitoring_package": runtime_bundle.get("active_regimen_monitoring_package", {}),
        "systemic_regimen_scope": (
            runtime_bundle.get("systemic_regimen_scope")
            or (runtime_bundle.get("systemic_regimen_scope_contract") or {}).get("scope")
            or "not_applicable"
        ),
        "systemic_regimen_scope_contract": runtime_bundle.get("systemic_regimen_scope_contract", {}),
        "metastatic_stage_resolved": signals.get("metastatic_stage_resolved", "M0"),
        "metastatic_stage_label": signals.get("metastatic_stage_label", "M0"),
        "metastatic_detection_basis": signals.get("metastatic_detection_basis", "unknown"),
        "current_adt_context": signals.get("current_adt_context", ""),
        "castrate_testosterone_status": signals.get("castrate_testosterone_status", ""),
        "nmcrpc_eligible": signals.get("nmcrpc_eligible", False),
        "nmcrpc_ineligibility_reason": signals.get("nmcrpc_ineligibility_reason", ""),
        "state_reclassification_required": signals.get("state_reclassification_required", False),
        "state_reclassification_reason": signals.get("state_reclassification_reason", ""),
        "restaging_update_required": signals.get("restaging_update_required", False),
        "restaging_currentness_status": signals.get("restaging_currentness_status", "unknown"),
        "restaging_update_reason": signals.get("restaging_update_reason", ""),
        "progression_verification_required": signals.get("progression_verification_required", False),
        "progression_verification_required_fields": signals.get("progression_verification_required_fields", []),
        "progression_verification_missing_fields": signals.get("progression_verification_missing_fields", []),
        "progression_verification_target_state_if_confirmed": signals.get("progression_verification_target_state_if_confirmed", ""),
        "progression_verification_target_state_if_not_castrate": signals.get("progression_verification_target_state_if_not_castrate", ""),
        "outcome_events": outcome_bundle.get("outcome_events", []),
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
        "transition_resolution": runtime_bundle.get("transition_resolution", {}),
        "care_intent_contract": runtime_bundle.get("care_intent_contract", {}),
        "laboratory_intelligence_profile": runtime_bundle.get("laboratory_intelligence_profile", {}),
        "latest_clinically_decisive_visit": runtime_bundle.get("latest_clinically_decisive_visit", {}),
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
        "blocking_inputs": decision_input_requirements.get("blocking_inputs", []),
        "hard_blocking_inputs": decision_input_requirements.get("hard_blocking_inputs", []),
        "decision_blocking_inputs": decision_input_requirements.get("decision_blocking_inputs", []),
        "supportive_gaps": decision_input_requirements.get("supportive_gaps", []),
        "required_to_recalculate": decision_input_requirements.get("required_to_recalculate", []),
        "optional_context_inputs": decision_input_requirements.get("optional_context_inputs", []),
        "decision_domains_blocked": decision_input_requirements.get("decision_domains_blocked", []),
        "why_these_fields_now": decision_input_requirements.get("why_these_fields_now", []),
        "guideline_basis": runtime_bundle.get("guideline_followup_plan", {}).get("schedule_evidence_basis", []),
        "ui_contradiction_flags": signals.get("ui_contradiction_flags", []),
        "decision_governance_bundle": runtime_bundle.get("decision_governance_bundle", {}),
        "recommendation_block_status": runtime_bundle.get("recommendation_block_status", ""),
        "recommendation_block_reason": runtime_bundle.get("recommendation_block_reason", ""),
        "allowed_actions_while_blocked": runtime_bundle.get("allowed_actions_while_blocked", []),
        "decision_blocking_bundle": runtime_bundle.get("decision_blocking_bundle", {}),
        "diagnostic_certainty_bundle": runtime_bundle.get("diagnostic_certainty_bundle", {}),
        "staging_certainty_bundle": runtime_bundle.get("staging_certainty_bundle", {}),
        "minimum_decisive_dataset_bundle": runtime_bundle.get("minimum_decisive_dataset_bundle", {}),
        "therapeutic_window_bundle": runtime_bundle.get("therapeutic_window_bundle", {}),
        "window_worklist_bundle": runtime_bundle.get("window_worklist_bundle", {}),
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
        "clinical_ledger_bundle": dict(clinical_ledger_bundle or {}),
    }

    return {
        "signals": signals,
        "signals_to_persist": signals_to_persist,
        "runtime_context_bundle": runtime_context_bundle,
        "public_payload": public_payload,
    }
