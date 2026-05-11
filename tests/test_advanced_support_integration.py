# IEC 62304 §5.6 (Integration testing)
from __future__ import annotations

from prostanet.domains.patient_tracking.decision_input_requirements_engine import (
    build_decision_input_requirements,
)
from prostanet.shared.advanced_support_normalizer import normalize_advanced_support_payload


def test_advanced_stage_schema_exposes_dropdown_pros_and_structured_support_fields(app_client):
    client, _ = app_client

    response = client.get("/api/modules/m1_crpc/schema")
    assert response.status_code == 200
    schema = response.get_json()["schema"]
    fields = {field["name"]: field for field in schema["fields"]}

    for field_name in (
        "eq5d_vas_band",
        "fact_p_total_band",
        "bpi_worst_pain_band",
        "fatigue_score_band",
        "ddi_review_status",
        "mini_cog_score",
        "adverse_histology_variant_type",
        "active_liver_disease",
        "cirrhosis_or_portal_hypertension",
        "active_hepatitis_b_or_c",
        "prior_drug_induced_liver_injury",
    ):
        assert field_name in fields

    assert fields["eq5d_vas_band"]["field_type"] == "select"
    assert fields["fact_p_total_band"]["field_type"] == "select"
    assert fields["bpi_worst_pain_band"]["field_type"] == "select"
    assert fields["fatigue_score_band"]["field_type"] == "select"
    assert fields["ddi_review_status"]["field_type"] == "select"
    assert fields["mini_cog_score"]["field_type"] == "select"
    assert fields["adverse_histology_variant_type"]["conditional_visibility"] == {
        "rare_histology_variant": ["1"]
    }

    for legacy_field in (
        "baseline_qol",
        "drug_interaction_reviewed",
        "hepatic_risk_factors",
        "neurocognitive_baseline",
    ):
        assert legacy_field not in fields


def test_advanced_support_normalization_drives_canonical_bundles_and_histology_redirect():
    normalized = normalize_advanced_support_payload(
        {
            "eq5d_vas_band": "60_79",
            "fact_p_total_band": "70_89",
            "bpi_worst_pain_band": "4_6",
            "fatigue_score_band": "7_10",
            "ddi_review_status": "completed",
            "current_medications": "warfarina, rosuvastatina",
            "child_pugh_score": "B",
            "active_liver_disease": "1",
            "rare_histology_variant": "1",
            "adverse_histology_variant_type": "small_cell_neuroendocrine",
            "mini_cog_score": "2",
            "mini_cog_date": "2026-04-01",
        },
        state="m1_crpc",
    )

    assert normalized["eq5d_vas"] == 70
    assert normalized["fact_p_total"] == 80
    assert normalized["bpi_worst_pain"] == 5
    assert normalized["fatigue_score"] == 8
    assert normalized["baseline_qol"] == 70
    assert normalized["fatigue_baseline"] == 8
    assert normalized["drug_interaction_reviewed"] == "1"
    assert normalized["hepatic_risk_factors"] == "1"
    assert normalized["advanced_pro_bundle"]["status"] == "complete"
    assert normalized["hepatic_safety_bundle"]["hepatic_risk_present"] is True
    assert normalized["ddi_risk_bundle"]["ddi_review_status"] == "completed"
    assert normalized["variant_histology_bundle"]["hard_redirect"] is True
    assert normalized["neuroendocrine_features"] == "1"


def test_decision_requirements_and_mhspc_selection_use_new_canonical_fields(app_client):
    client, _ = app_client

    patient = {
        "baseline": {},
        "follow_ups": [],
        "stage_visits": [],
        "prior_history": {"current_state": "m1_crpc"},
        "latest_assessment": {
            "state": "m1_crpc",
            "input_snapshot": {
                "state": "m1_crpc",
                "management_track": "on_arpi",
                "testosterone": 18,
                "current_adt_context": "medical_adt_continuous",
                "progression_pattern": "radiographic",
                "conventional_imaging_status": "M1b",
                "line_of_therapy_number": 1,
                "drug_scheme": "Enzalutamide",
                "eq5d_vas_band": "80_100",
                "fact_p_total_band": "90_109",
                "bpi_worst_pain_band": "0_3",
                "fatigue_score_band": "4_6",
                "ddi_review_status": "completed",
                "current_medications": "warfarina",
                "child_pugh_score": "B",
                "active_liver_disease": "1",
                "rare_histology_variant": "1",
                "adverse_histology_variant_type": "small_cell_neuroendocrine",
                "mini_cog_score": "2",
                "mini_cog_date": "2026-04-01",
            },
        },
    }

    decision_bundle = build_decision_input_requirements(patient, effective_state="m1_crpc")

    assert decision_bundle["selection_safety_profile"]["ddi_review_status"] == "completed"
    assert decision_bundle["selection_safety_profile"]["advanced_pro_bundle"]["eq5d_vas"] == 90
    assert decision_bundle["selection_safety_profile"]["hepatic_safety_bundle"]["hepatic_risk_present"] is True
    assert decision_bundle["recommendation_block_status"] == "hard_stop"
    assert "neuroendocrina" in decision_bundle["recommendation_block_reason"].lower()

    response = client.post(
        "/api/modules/mcspc_low_volume_sync_oligo/evaluate",
        json={
            "metastasis_count": 2,
            "metastasis_site": "Bone",
            "ecog_score": 0,
            "comorbidity_seizure": 0,
            "comorbidity_cardio": 0,
            "cv_risk_documented": 0,
            "ddi_review_status": "completed",
            "rt_primary_received": 0,
            "frailty_status": "Fit",
            "child_pugh_score": "A",
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["preferred_frontline_regimen"]["regimen_code"] == "ADT_ENZALUTAMIDE"
