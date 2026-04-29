# IEC 62304 §5.5 (Unit verification)
from prostanet.domains.localized_initial.service import LocalizedInitialService
from prostanet.domains.patient_tracking.localized_modality import (
    build_localized_modality_fitness_bundle,
    build_localized_survival_context_bundle,
    build_localized_tradeoff_bundle,
)
from prostanet.domains.localized_initial.schemas import LOCALIZED_SCHEMA
from prostanet.shared.epic26 import normalize_epic26_payload, score_epic26_response_packet
from prostanet.shared.pcothercause import build_pcothercause_life_expectancy_bundle


def _epic26_packet(overrides=None):
    responses = {
        "ui1_leak_frequency": "rarely_or_never",
        "ui2_urinary_control": "total_control",
        "ui3_pads_per_day": "none",
        "ui4_leaking_problem": "none",
        "uo1_pain_burning_urination": "none",
        "uo2_bloody_urine": "none",
        "uo3_weak_stream_incomplete_emptying": "none",
        "uo4_daytime_frequency": "none",
        "u_overall_bother": "none",
        "b1_urgency": "none",
        "b2_frequency": "none",
        "b3_losing_control": "none",
        "b4_bloody_stools": "none",
        "b5_painful_bowel_movements": "none",
        "b6_overall_bowel_problem": "none",
        "s1_ability_erection": "good",
        "s2_ability_orgasm": "good",
        "s3_erection_quality": "firm_enough_for_intercourse",
        "s4_erection_frequency": "whenever_wanted",
        "s5_overall_sexual_function": "very_good",
        "s6_sexual_problem": "none",
        "h1_hot_flashes": "none",
        "h2_breast_tenderness": "none",
        "h3_feeling_depressed": "none",
        "h4_lack_of_energy": "none",
        "h5_change_in_body_weight": "none",
    }
    responses.update(overrides or {})
    return {"responses": responses}


def _localized_payload(overrides=None):
    payload = {
        "age": 68,
        "occam_height_cm": 172,
        "occam_weight_kg": 80,
        "occam_diabetes": "0",
        "occam_hypertension": "1",
        "occam_stroke": "0",
        "occam_smoking_status": "former",
        "occam_education": "not_used",
        "occam_marital_status": "not_used",
        "psa": 8.5,
        "clinical_tstage": "T2b",
        "gleason_primary": 3,
        "gleason_secondary": 4,
        "isup_grade": 2,
        "num_cores_positive": 3,
        "total_cores": 12,
        "nodal_status": "N0",
        "metastasis_site": "M0",
        "ecog_score": "0",
        "charlson_score": 1,
        "frailty_status": "Fit",
        "g8_score": 15,
        "anesthesia_surgical_fitness": "Fit",
        "radiotherapy_feasibility": "feasible",
        "brachy_feasibility": "feasible",
        "prostate_volume_ml": 42,
        "baseline_obstruction": "moderate",
        "plnd_likely_indicated": "unknown",
        "patient_priority_profile": "preserve_urinary_function,avoid_bowel_toxicity",
        "ipss_score": 12,
        "iief5_score": 20,
        "epic26_response_packet": _epic26_packet(),
    }
    payload.update(overrides or {})
    return payload


def test_epic26_scoring_returns_five_official_domains_and_legacy_alias():
    scored = score_epic26_response_packet(_epic26_packet())

    assert scored["available"] is True
    assert scored["derived_scores"]["epic26_urinary_incontinence_domain"] == 100.0
    assert scored["derived_scores"]["epic26_urinary_irritative_domain"] == 100.0
    assert scored["derived_scores"]["epic26_bowel_domain"] == 100.0
    assert scored["derived_scores"]["epic26_sexual_domain"] == 100.0
    assert scored["derived_scores"]["epic26_hormonal_domain"] == 100.0
    assert scored["derived_scores"]["epic26_overall_urinary_bother"] == 100.0
    assert scored["derived_scores"]["epic26_urinary_domain"] == 100.0
    assert scored["completion_status_by_domain"]["urinary_incontinence"] == "complete"
    assert scored["instrument_locale"] == "es"


def test_epic26_scoring_invalidates_domain_when_missingness_exceeds_threshold():
    packet = _epic26_packet()
    packet["responses"].pop("ui4_leaking_problem")

    scored = score_epic26_response_packet(packet)

    assert scored["derived_scores"]["epic26_urinary_incontinence_domain"] is None
    assert scored["completion_status_by_domain"]["urinary_incontinence"] == "not_calculable"
    assert scored["derived_scores"]["epic26_urinary_irritative_domain"] == 100.0


def test_normalize_epic26_payload_backfills_split_urinary_domains_from_legacy_alias():
    normalized = normalize_epic26_payload({"epic26_urinary_domain": 42, "epic26_sexual_domain": 75})

    assert normalized["epic26_urinary_incontinence_domain"] == 42
    assert normalized["epic26_urinary_irritative_domain"] == 42
    assert normalized["epic26_urinary_domain"] == 42.0


def test_localized_schema_exposes_spanish_epic26_questionnaire_widget():
    epic26_field = next(field for field in LOCALIZED_SCHEMA["fields"] if field["name"] == "epic26_response_packet")

    assert epic26_field["field_type"] == "epic26_questionnaire"
    assert epic26_field["widget_config"]["instrument_locale"] == "es"
    assert len(epic26_field["widget_config"]["groups"]) == 6
    assert len(epic26_field["widget_config"]["items"]) == 26
    assert any(item["prompt"].startswith("Durante las últimas 4 semanas") for item in epic26_field["widget_config"]["items"])


def test_localized_schema_exposes_occam_widget_in_spanish():
    occam_field = next(field for field in LOCALIZED_SCHEMA["fields"] if field["name"] == "life_expectancy_years")

    assert occam_field["field_type"] == "occam_life_expectancy"
    assert occam_field["widget_config"]["instrument_locale"] == "es"
    assert "models" in occam_field["widget_config"]
    assert occam_field["widget_config"]["source_repo"].endswith("/PCOtherCause")


def test_pcothercause_bundle_uses_reduced_public_variant_when_social_inputs_are_omitted():
    bundle = build_pcothercause_life_expectancy_bundle(
        {
            "age": 62,
            "occam_height_cm": 175,
            "occam_weight_kg": 78,
            "occam_diabetes": "0",
            "occam_hypertension": "0",
            "occam_stroke": "0",
            "occam_smoking_status": "never",
            "occam_education": "not_used",
            "occam_marital_status": "not_used",
            "ecog_score": "0",
            "charlson_score": "1",
        }
    )

    assert bundle["available"] is True
    assert bundle["variant"] == "reduced"
    assert bundle["source"] == "pcothercause_public_repo"
    assert bundle["life_expectancy_years"] >= 10


def test_pcothercause_bundle_switches_to_full_variant_when_optional_social_inputs_are_present():
    bundle = build_pcothercause_life_expectancy_bundle(
        {
            "age": 62,
            "occam_height_cm": 175,
            "occam_weight_kg": 78,
            "occam_diabetes": "0",
            "occam_hypertension": "0",
            "occam_stroke": "0",
            "occam_smoking_status": "never",
            "occam_education": "college_graduate",
            "occam_marital_status": "married",
            "ecog_score": "0",
            "charlson_score": "1",
        }
    )

    assert bundle["available"] is True
    assert bundle["variant"] == "full"
    assert bundle["source"] == "pcothercause_public_repo"


def test_localized_service_uses_occam_and_ecog_charlson_to_limit_benefit_horizon():
    result = LocalizedInitialService().evaluate(
        _localized_payload(
            {
                "age": 78,
                "occam_height_cm": 170,
                "occam_weight_kg": 86,
                "occam_diabetes": "1",
                "occam_hypertension": "1",
                "occam_stroke": "1",
                "occam_smoking_status": "current",
                "ecog_score": "2",
                "charlson_score": 5,
                "frailty_status": "Vulnerable",
                "g8_score": 13,
                "psa": 6.2,
                "clinical_tstage": "T1c",
                "gleason_primary": 3,
                "gleason_secondary": 3,
                "isup_grade": 1,
                "num_cores_positive": 2,
                "total_cores": 12,
            }
        )
    )

    occam_bundle = result["occam_life_expectancy_bundle"]
    survival_bundle = result["localized_survival_context_bundle"]

    assert occam_bundle["source"] == "pcothercause_public_repo"
    assert occam_bundle["life_expectancy_years"] < 10
    assert survival_bundle["benefit_horizon_band"] == "limited_benefit"
    assert survival_bundle["prefer_observation"] is True


def test_localized_survival_context_substratifies_le5_vs_5_to_10_years():
    under_5 = build_localized_survival_context_bundle({"life_expectancy_years": 4.8})
    between_5_and_10 = build_localized_survival_context_bundle({"life_expectancy_years": 7.2})

    assert under_5["life_expectancy_horizon_band"] == "le_5_years"
    assert under_5["observation_guidance"] == "strongly_favor_observation"
    assert under_5["observation_preference_strength"] == "very_high"
    assert between_5_and_10["life_expectancy_horizon_band"] == "between_5_and_10_years"
    assert between_5_and_10["observation_guidance"] == "favor_observation"
    assert between_5_and_10["observation_preference_strength"] == "high"


def test_favorable_intermediate_with_occam_horizon_under_10_years_prefers_observation():
    result = LocalizedInitialService().evaluate(
        _localized_payload(
            {
                "age": 78,
                "occam_height_cm": 170,
                "occam_weight_kg": 86,
                "occam_diabetes": "1",
                "occam_hypertension": "1",
                "occam_stroke": "1",
                "occam_smoking_status": "current",
                "ecog_score": "1",
                "charlson_score": 5,
                "frailty_status": "Fit",
                "g8_score": 15,
                "psa": 8.5,
                "clinical_tstage": "T2a",
                "gleason_primary": 3,
                "gleason_secondary": 4,
                "isup_grade": 2,
                "num_cores_positive": 2,
                "total_cores": 12,
                "pct_cores_positive": 0.17,
            }
        )
    )

    assert result["nccn_primary"]["risk_group"] == "FAVORABLE INTERMEDIATE"
    assert result["occam_life_expectancy_bundle"]["life_expectancy_years"] < 10
    assert result["localized_survival_context_bundle"]["prefer_observation"] is True
    assert result["localized_modality_fitness_bundle"]["dominant_modality"] == "observation"
    assert result["preferred_frontline_regimen"]["regimen_code"] == "OBSERVATION"


def test_favorable_intermediate_5_to_10_years_prefers_observation_but_keeps_local_options_visible():
    result = LocalizedInitialService().evaluate(
        _localized_payload(
            {
                "occam_height_cm": "",
                "occam_weight_kg": "",
                "occam_diabetes": "",
                "occam_hypertension": "",
                "occam_stroke": "",
                "occam_smoking_status": "",
                "life_expectancy_years": 7.0,
                "psa": 8.5,
                "clinical_tstage": "T2a",
                "gleason_primary": 3,
                "gleason_secondary": 4,
                "isup_grade": 2,
                "num_cores_positive": 2,
                "total_cores": 12,
                "pct_cores_positive": 0.17,
            }
        )
    )

    by_code = {item["regimen_code"]: item for item in result["eligible_treatments"]}

    assert result["localized_survival_context_bundle"]["life_expectancy_horizon_band"] == "between_5_and_10_years"
    assert result["preferred_frontline_regimen"]["regimen_code"] == "OBSERVATION"
    assert by_code["DEFINITIVE_RT"]["eligibility_status"] == "eligible_nonpreferred"
    assert by_code["RADICAL_PROSTATECTOMY"]["eligibility_status"] == "eligible_nonpreferred"
    assert "5 y 10 años" in result["nccn_primary"]["recommendation"]


def test_favorable_intermediate_le5_years_downgrades_local_definitive_options_to_caution():
    result = LocalizedInitialService().evaluate(
        _localized_payload(
            {
                "occam_height_cm": "",
                "occam_weight_kg": "",
                "occam_diabetes": "",
                "occam_hypertension": "",
                "occam_stroke": "",
                "occam_smoking_status": "",
                "life_expectancy_years": 4.5,
                "psa": 8.5,
                "clinical_tstage": "T2a",
                "gleason_primary": 3,
                "gleason_secondary": 4,
                "isup_grade": 2,
                "num_cores_positive": 2,
                "total_cores": 12,
                "pct_cores_positive": 0.17,
            }
        )
    )

    by_code = {item["regimen_code"]: item for item in result["eligible_treatments"]}

    assert result["localized_survival_context_bundle"]["life_expectancy_horizon_band"] == "le_5_years"
    assert result["preferred_frontline_regimen"]["regimen_code"] == "OBSERVATION"
    assert by_code["DEFINITIVE_RT"]["eligibility_status"] == "eligible_with_caution"
    assert by_code["RADICAL_PROSTATECTOMY"]["eligibility_status"] == "eligible_with_caution"
    assert "menor o igual a 5 años" in result["nccn_primary"]["recommendation"]


def test_localized_service_exposes_epic26_domain_scores_and_snapshot():
    result = LocalizedInitialService().evaluate(_localized_payload())

    assert "score_interpretation_catalog_snapshot" in result
    assert result["score_interpretation_catalog_snapshot"]["epic26_urinary_incontinence_domain"]["score_grade_es"] == "Preservada"
    assert result["score_interpretation_catalog_snapshot"]["epic26_hormonal_domain"]["score_grade_es"] == "Preservada"
    assert [item["score_key"] for item in result["epic26_domain_scores"]] == [
        "epic26_urinary_incontinence_domain",
        "epic26_urinary_irritative_domain",
        "epic26_bowel_domain",
        "epic26_sexual_domain",
        "epic26_hormonal_domain",
        "epic26_overall_urinary_bother",
    ]


def test_localized_api_exposes_epic26_domain_scores_and_snapshot(app_client):
    client, _db_path = app_client

    response = client.post("/api/modules/localized_initial/evaluate", json=_localized_payload())
    assert response.status_code == 200
    result = response.get_json()["result"]

    assert "score_interpretation_catalog_snapshot" in result
    assert result["score_interpretation_catalog_snapshot"]["epic26_urinary_incontinence_domain"]["score_grade_es"] == "Preservada"
    assert result["epic26_domain_scores"][0]["score_key"] == "epic26_urinary_incontinence_domain"
    assert result["epic26_domain_scores"][-1]["score_key"] == "epic26_overall_urinary_bother"


def test_localized_modality_keeps_epic26_as_shared_decision_signal_without_downgrading_rt_status():
    payload = {
        "clinical_tstage": "T2a",
        "nodal_status": "N0",
        "metastasis_site": "M0",
        "ecog_score": 1,
        "charlson_score": 1,
        "frailty_status": "Fit",
        "g8_score": 15,
        "anesthesia_surgical_fitness": "Fit",
        "radiotherapy_feasibility": "feasible",
        "baseline_obstruction": "mild",
        "ipss_score": 12,
        "iief5_score": 20,
        "prostate_volume_ml": 42,
        "patient_priority_profile": "preserve_urinary_function,avoid_bowel_toxicity",
        "epic26_response_packet": _epic26_packet(
            {
                "uo1_pain_burning_urination": "big",
                "uo3_weak_stream_incomplete_emptying": "moderate",
                "uo4_daytime_frequency": "big",
                "u_overall_bother": "moderate",
                "b1_urgency": "big",
                "b2_frequency": "moderate",
                "b3_losing_control": "small",
                "b5_painful_bowel_movements": "small",
                "b6_overall_bowel_problem": "moderate",
            }
        ),
    }

    bundle = build_localized_modality_fitness_bundle(
        payload,
        nccn_group="FAVORABLE INTERMEDIATE",
        as_position={"eligible": False, "status": "not_recommended"},
    )

    assert bundle["radiotherapy_status"] == "reasonable"
    assert "epic26_urinary_incontinence_domain" not in bundle["modality_tradeoff_gaps"]
    assert "epic26_urinary_irritative_domain" not in bundle["modality_tradeoff_gaps"]
    assert "epic26_hormonal_domain" not in bundle["modality_tradeoff_gaps"]
    assert bundle["epic26_role_summary"].startswith("EPIC-26 se usa en localizada")
    assert any("intestinal" in reason.lower() for reason in bundle["epic26_shared_decision_signals"])
    assert bundle["epic26_governance_contract"]["primary_guideline_driver"] == "nccn_2026"
    assert bundle["epic26_governance_contract"]["governance_status"] == "baseline_tradeoff_followup_quality_only"


def test_localized_tradeoff_raises_rt_functional_cost_when_hormonal_burden_is_high_and_adt_is_plausible():
    payload = {
        "clinical_tstage": "T2b",
        "nodal_status": "N0",
        "metastasis_site": "M0",
        "ecog_score": 1,
        "charlson_score": 1,
        "frailty_status": "Fit",
        "g8_score": 15,
        "anesthesia_surgical_fitness": "Fit",
        "radiotherapy_feasibility": "feasible",
        "baseline_obstruction": "mild",
        "ipss_score": 7,
        "iief5_score": 18,
        "prostate_volume_ml": 40,
        "patient_priority_profile": "maximize_cancer_control",
        "epic26_response_packet": _epic26_packet(
            {
                "h1_hot_flashes": "big",
                "h2_breast_tenderness": "moderate",
                "h3_feeling_depressed": "moderate",
                "h4_lack_of_energy": "big",
                "h5_change_in_body_weight": "small",
            }
        ),
    }

    modality_bundle = build_localized_modality_fitness_bundle(
        payload,
        nccn_group="HIGH",
        as_position={"eligible": False, "status": "not_recommended"},
    )
    tradeoff_bundle = build_localized_tradeoff_bundle(
        payload,
        nccn_group="HIGH",
        modality_bundle=modality_bundle,
        as_position={"eligible": False, "status": "not_recommended"},
    )

    assert tradeoff_bundle["modalities"]["radiotherapy"]["functional_cost_profile"] == "high"


def test_epic26_does_not_flip_dominant_modality_by_itself_in_high_risk_localized_case():
    base_payload = {
        "clinical_tstage": "T2b",
        "nodal_status": "N0",
        "metastasis_site": "M0",
        "ecog_score": 0,
        "charlson_score": 1,
        "frailty_status": "Fit",
        "g8_score": 16,
        "anesthesia_surgical_fitness": "Fit",
        "radiotherapy_feasibility": "feasible",
        "baseline_obstruction": "mild",
        "ipss_score": 7,
        "iief5_score": 20,
        "prostate_volume_ml": 40,
        "patient_priority_profile": "maximize_cancer_control",
        "epic26_response_packet": _epic26_packet(),
    }
    worse_payload = dict(base_payload)
    worse_payload["epic26_response_packet"] = _epic26_packet(
        {
            "uo1_pain_burning_urination": "big",
            "uo3_weak_stream_incomplete_emptying": "big",
            "uo4_daytime_frequency": "moderate",
            "u_overall_bother": "moderate",
            "b1_urgency": "big",
            "b5_painful_bowel_movements": "big",
            "b6_overall_bowel_problem": "moderate",
            "h1_hot_flashes": "big",
            "h3_feeling_depressed": "big",
            "h4_lack_of_energy": "big",
            "h5_change_in_body_weight": "moderate",
        }
    )

    base_bundle = build_localized_modality_fitness_bundle(
        base_payload,
        nccn_group="HIGH",
        as_position={"eligible": False, "status": "not_recommended"},
    )
    worse_bundle = build_localized_modality_fitness_bundle(
        worse_payload,
        nccn_group="HIGH",
        as_position={"eligible": False, "status": "not_recommended"},
    )

    assert base_bundle["dominant_modality"] == "radiotherapy"
    assert worse_bundle["dominant_modality"] == "radiotherapy"
    assert base_bundle["radiotherapy_status"] == "reasonable"
    assert worse_bundle["radiotherapy_status"] == "reasonable"
    assert worse_bundle["epic26_shared_decision_signals"]


def test_epic26_sexual_domain_does_not_flip_primary_modality_without_iief_support():
    payload = {
        "clinical_tstage": "T2a",
        "nodal_status": "N0",
        "metastasis_site": "M0",
        "ecog_score": 0,
        "charlson_score": 1,
        "frailty_status": "Fit",
        "g8_score": 16,
        "anesthesia_surgical_fitness": "Fit",
        "radiotherapy_feasibility": "feasible",
        "baseline_obstruction": "mild",
        "ipss_score": 7,
        "iief5_score": 8,
        "prostate_volume_ml": 38,
        "patient_priority_profile": "preserve_sexual_function",
        "epic26_response_packet": _epic26_packet(
            {
                "s1_ability_erection": "good",
                "s2_ability_orgasm": "good",
                "s3_erection_quality": "firm_enough_for_intercourse",
                "s4_erection_frequency": "whenever_wanted",
                "s5_overall_sexual_function": "very_good",
                "s6_sexual_problem": "none",
            }
        ),
    }

    bundle = build_localized_modality_fitness_bundle(
        payload,
        nccn_group="FAVORABLE INTERMEDIATE",
        as_position={"eligible": False, "status": "not_recommended"},
    )
    tradeoff_bundle = build_localized_tradeoff_bundle(
        payload,
        nccn_group="FAVORABLE INTERMEDIATE",
        modality_bundle=bundle,
        as_position={"eligible": False, "status": "not_recommended"},
    )

    assert bundle["dominant_modality"] == "surgery"
    assert bundle["epic26_shared_decision_signals"]
    assert any("función sexual basal" in signal.lower() for signal in bundle["epic26_shared_decision_signals"])
    assert tradeoff_bundle["epic26_governance_contract"]["governance_guardrail"]
