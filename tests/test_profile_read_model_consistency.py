# IEC 62304 §5.5 (Unit verification)
from prostanet.domains.patient_tracking.advanced_followup_builder import (
    build_advanced_followup_bundle,
)
from prostanet.domains.patient_tracking.profile_read_model_builder import (
    build_profile_support_projection,
    build_surface_consistency_projection,
)
from prostanet.domains.patient_tracking.staging_adjudication_builder import (
    build_staging_adjudication_bundle,
)


def test_surface_consistency_projection_hides_legacy_panel_when_scenario_conflicts():
    projection = build_surface_consistency_projection(
        {
            "prior_history": {"current_state": "post_radiotherapy_or_local_salvage"},
            "latest_signal_snapshot": {
                "effective_state_final": "post_radiotherapy_or_local_salvage",
                "next_best_action": {"recommendation_family": "salvage_rt_family"},
            },
        },
        {
            "signals": {
                "effective_state_final": "post_radiotherapy_or_local_salvage",
            }
        },
        latest_assessment={},
        recommendations={"scenario": "mHSPC"},
        therapeutic_readiness_bundle={"candidate_family": "salvage_rt_family"},
    )

    assert "clinical_kernel_snapshot" in projection
    assert projection["effective_state"] == "post_radiotherapy_or_local_salvage"
    assert projection["surface_consistency_status"] == "requires_review"
    assert projection["legacy_recommendation_panel"]["show"] is False
    assert projection["clinical_kernel_snapshot"]["surface_consistency_status"] == "requires_review"
    assert any("panel legacy" in flag.lower() for flag in projection["surface_consistency_flags"])


def test_surface_consistency_projection_accepts_string_flags_without_crashing():
    projection = build_surface_consistency_projection(
        {
            "prior_history": {"current_state": "m1_crpc"},
            "latest_signal_snapshot": {
                "effective_state_final": "m1_crpc",
                "surface_consistency_flags": [
                    "El panel visible requiere revisión manual.",
                    {"message": "La recomendación legacy no coincide con el carril efectivo."},
                ],
                "next_best_action": {"recommendation_family": "arpi_family"},
            },
        },
        {
            "signals": {
                "effective_state_final": "m1_crpc",
                "surface_consistency_flags": [
                    "El panel visible requiere revisión manual.",
                    {"reason": "Persisten banderas heredadas en la UI."},
                ],
            }
        },
        latest_assessment={},
        recommendations={"scenario": "mHSPC"},
        therapeutic_readiness_bundle={"candidate_family": "arpi_family"},
    )

    assert projection["surface_consistency_status"] == "requires_review"
    assert any("panel visible requiere revisión manual" in flag.lower() for flag in projection["surface_consistency_flags"])
    assert any("banderas heredadas" in flag.lower() for flag in projection["surface_consistency_flags"])


def test_advanced_followup_bundle_surfaces_longitudinal_capture_actions():
    bundle = build_advanced_followup_bundle(
        patient_record={
            "baseline": {
                "current_adt_context": "medical_adt_continuous",
                "prior_adt": 1,
            },
            "latest_signal_snapshot": {"restaging_update_required": True},
        },
        state="m0_crpc",
        latest_assessment={"input_snapshot": {}},
        longitudinal_bundle={},
        decision_input_requirements={
            "monitoring_capture_block": {
                "title": "Completar monitoreo longitudinal",
                "summary": "Cerrar testosterona, imagen y soporte óseo.",
                "fields": [
                    "testosterone",
                    "testosterone_history",
                    "conventional_imaging_status",
                    "dxa_baseline_done",
                    "calcium_vitd_started",
                    "bone_protection_started",
                ],
                "focus": "advanced_followup",
                "capture_target": "followup",
            }
        },
        signals={"restaging_update_required": True},
    )

    profile_payload = {"advanced_followup_bundle": bundle}
    assert bundle["available"] is True
    assert bundle["confidence_status"] == "degraded_by_missing_data"
    assert "testosterone" in bundle["missing_inputs"]
    assert bundle["capture_actions"][0]["title"] == "Completar monitoreo longitudinal"
    assert "Testosterona sérica" in " ".join(bundle["capture_actions"][0]["display_fields_summary"])
    assert profile_payload["advanced_followup_bundle"]["monitoring_checklist"]


def test_staging_adjudication_bundle_flags_psma_only_upstaging_and_missing_traceability():
    bundle = build_staging_adjudication_bundle(
        patient_record={
            "baseline": {
                "conventional_imaging_status": "M0",
                "psma_positive": 1,
            },
            "latest_signal_snapshot": {
                "metastatic_detection_basis": "psma_only",
                "psma_only_upstaging": True,
                "restaging_update_required": True,
            },
        },
        state="m1_crpc",
        latest_assessment={"input_snapshot": {}},
        longitudinal_bundle={},
        therapeutic_readiness_bundle={"candidate_family": "psma_rlt_family"},
        decision_input_requirements={
            "restaging_capture_block": {
                "title": "Completar adjudicación de imagen",
                "summary": "Correlacionar PSMA e imagen convencional.",
                "fields": [
                    "conventional_imaging_status",
                    "psma_pet_done",
                    "psma_positive",
                    "psma_negative_dominant_lesions",
                ],
                "focus": "staging_adjudication",
                "capture_target": "followup",
            }
        },
        signals={
            "metastatic_detection_basis": "psma_only",
            "psma_only_upstaging": True,
            "restaging_update_required": True,
        },
    )

    profile_payload = {"staging_adjudication_bundle": bundle}
    assert bundle["available"] is True
    assert bundle["psma_only_upstaging"] is True
    assert bundle["concordance_status"] == "insufficient_concordance"
    assert bundle["adjudication_release_status"] == "blocked_pending_adjudication"
    assert bundle["discordance_reason_category"] == "missing_critical_traceability"
    assert "psma_pet_done" in bundle["missing_critical_inputs"]
    assert bundle["capture_actions"][0]["title"] == "Completar adjudicación de imagen"
    assert profile_payload["staging_adjudication_bundle"]["traceability_checklist"]


def test_staging_adjudication_bundle_marks_context_changed_when_psma_changes_context_without_missing_traceability():
    bundle = build_staging_adjudication_bundle(
        patient_record={
            "baseline": {
                "conventional_imaging_status": "M0",
                "psma_positive": 1,
                "psma_pet_done": 1,
            },
            "latest_signal_snapshot": {
                "metastatic_detection_basis": "psma_only",
                "psma_only_upstaging": True,
            },
        },
        state="m0_crpc",
        latest_assessment={"input_snapshot": {"conventional_imaging_status": "M0", "psma_positive": 1, "psma_pet_done": 1}},
        longitudinal_bundle={},
        therapeutic_readiness_bundle={"candidate_family": "arpi_family"},
        decision_input_requirements={},
        signals={
            "metastatic_detection_basis": "psma_only",
            "psma_only_upstaging": True,
        },
    )

    assert bundle["available"] is True
    assert bundle["concordance_status"] == "context_changed"
    assert bundle["adjudication_release_status"] == "review_needed"
    assert bundle["discordance_reason_category"] == "psma_only_upstaging"
    assert "psma_only_upstaging" in bundle["context_change_triggers"]
    assert "conventional_imaging_status" in bundle["superseded_evidence"]
    assert bundle["recommended_adjudication_actions"]


def test_profile_support_projection_surfaces_decision_evidence_currentness_bundle():
    projection = build_profile_support_projection(
        {
            "latest_signal_snapshot": {
                "decision_evidence_currentness_bundle": {
                    "selected_decision_evidence_status": "aging",
                    "selected_decision_release_status": "aging_review_needed",
                    "refresh_actions": ["Actualizar PSA y mpMRI"],
                }
            }
        },
        {},
    )

    assert projection["decision_evidence_currentness_bundle"]["selected_decision_evidence_status"] == "aging"
    assert projection["decision_evidence_currentness_bundle"]["refresh_actions"] == ["Actualizar PSA y mpMRI"]
