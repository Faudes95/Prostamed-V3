# IEC 62304 §5.7 (software system testing).

def _lane(bundle, key):
    for lane in bundle["lanes"]:
        if lane["key"] == key:
            return lane
    raise AssertionError(f"lane not found: {key}")


def test_bcr_activates_salvage_and_excludes_crpc_parp_psma():
    from prostanet.domains.patient_tracking.clinical_readiness_tower import (
        build_clinical_readiness_tower,
    )

    patient = {
        "identity": {"nss": "BCR-001"},
        "baseline": {
            "prior_prostatectomy": 1,
            "bcr_detected": 1,
            "psa_value": 0.42,
            "psa_doubling_time_months": 7.0,
        },
        "latest_assessment": {"state": "recurrence_bcr"},
        "treatments": [],
    }

    bundle = build_clinical_readiness_tower(patient, state="recurrence_bcr")

    assert _lane(bundle, "bcr_salvage_readiness")["status"] != "not_applicable"
    assert _lane(bundle, "m1crpc_sequence_readiness")["status"] == "not_applicable"
    assert _lane(bundle, "parp_hrr_readiness")["status"] == "not_applicable"
    assert _lane(bundle, "psma_rlt_readiness")["status"] == "not_applicable"


def test_bcr_salvage_window_minimum_requires_psadt_and_context():
    from prostanet.domains.patient_tracking.clinical_readiness_tower import (
        build_clinical_readiness_tower,
    )

    bundle = build_clinical_readiness_tower(
        {
            "identity": {"nss": "BCR-MIN-001"},
            "baseline": {
                "prior_prostatectomy": 1,
                "psa_value": 0.35,
            },
            "latest_assessment": {"state": "recurrence_bcr"},
            "treatments": [],
        },
        state="recurrence_bcr",
        patient_ref="BCR-MIN-001",
    )

    lane = _lane(bundle, "bcr_salvage_readiness")

    assert lane["status"] == "requires_data"
    assert "psa_doubling_time_months" in lane["missing_fields"]
    assert "salvage_context_marker" in lane["missing_fields"]
    assert lane["cta_url"].endswith("/wizard/recurrence_bcr?readiness_lane=bcr_salvage_readiness")
    assert _lane(bundle, "m1crpc_sequence_readiness")["status"] == "not_applicable"
    assert _lane(bundle, "parp_hrr_readiness")["status"] == "not_applicable"
    assert _lane(bundle, "psma_rlt_readiness")["status"] == "not_applicable"


def test_bcr_salvage_window_minimum_can_be_satisfied_by_legacy_aliases():
    from prostanet.domains.patient_tracking.clinical_readiness_tower import (
        build_clinical_readiness_tower,
    )

    bundle = build_clinical_readiness_tower(
        {
            "identity": {"nss": "BCR-MIN-002"},
            "baseline": {
                "prior_radiation_therapy_documented": "1",
                "psa_value": 2.7,
                "psadt_months": 7.4,
                "phoenix_failure_confirmed": "1",
            },
            "latest_assessment": {"state": "recurrence_bcr"},
            "treatments": [],
        },
        state="recurrence_bcr",
    )

    lane = _lane(bundle, "bcr_salvage_readiness")

    assert lane["status"] == "ready"
    assert lane["missing_fields"] == []


def test_m0crpc_requires_psadt_testosterone_and_conventional_m0():
    from prostanet.domains.patient_tracking.clinical_readiness_tower import (
        build_clinical_readiness_tower,
    )

    bundle = build_clinical_readiness_tower(
        {
            "identity": {"nss": "M0-001"},
            "baseline": {"psa_value": 8.0},
            "latest_assessment": {"state": "m0_crpc"},
            "treatments": [],
        },
        state="m0_crpc",
    )

    lane = _lane(bundle, "m0crpc_arpi_readiness")
    assert lane["status"] == "requires_data"
    assert "psa_doubling_time_months" in lane["missing_fields"]
    assert "testosterone_value" in lane["missing_fields"]
    assert "conventional_imaging_status" in lane["missing_fields"]


def test_m1crpc_without_treatment_does_not_invent_line_or_adt_safety():
    from prostanet.domains.patient_tracking.clinical_readiness_tower import (
        build_clinical_readiness_tower,
    )

    bundle = build_clinical_readiness_tower(
        {
            "identity": {"nss": "M1-EMPTY-TX"},
            "baseline": {"metastasis_site": "M1b", "psa_value": 12.0, "testosterone_value": 18},
            "latest_assessment": {"state": "m1_crpc"},
            "treatments": [],
        },
        state="m1_crpc",
    )

    assert bundle["summary"]["has_real_treatment_line"] is False
    assert bundle["summary"]["real_treatment_line_count"] == 0
    assert "real_treatment_line" in _lane(bundle, "m1crpc_sequence_readiness")["missing_fields"]
    assert _lane(bundle, "adt_arpi_safety_readiness")["status"] == "not_applicable"


def test_patient_with_one_real_line_reports_exactly_one_line():
    from prostanet.domains.patient_tracking.clinical_readiness_tower import (
        build_clinical_readiness_tower,
    )

    bundle = build_clinical_readiness_tower(
        {
            "identity": {"nss": "TX-001"},
            "baseline": {
                "metastasis_site": "M1b",
                "psa_value": 20.0,
                "testosterone_value": 22,
                "progression_pattern": "psa",
                "ecog_score": 1,
                "prior_docetaxel_exposure": 1,
                "prior_arpi_exposure": 1,
            },
            "latest_assessment": {"state": "m1_crpc"},
            "treatments": [
                {"line_of_therapy": 1, "drug_scheme": "ADT + docetaxel", "start_date": "2025-01-10"},
            ],
        },
        state="m1_crpc",
    )

    assert bundle["summary"]["real_treatment_line_count"] == 1
    assert bundle["summary"]["real_treatment_lines"][0]["label"] == "ADT + docetaxel"
    assert "real_treatment_line" not in _lane(bundle, "m1crpc_sequence_readiness")["missing_fields"]


def test_localized_without_symptoms_does_not_open_supportive_lane():
    from prostanet.domains.patient_tracking.clinical_readiness_tower import (
        build_clinical_readiness_tower,
    )

    bundle = build_clinical_readiness_tower(
        {
            "identity": {"nss": "LOC-001"},
            "baseline": {
                "psa_value": 8.5,
                "clinical_risk_group": "intermediate",
                "life_expectancy_years": 15,
            },
            "latest_assessment": {"state": "localized_initial"},
            "treatments": [],
        },
        state="localized_initial",
    )

    assert _lane(bundle, "localized_treatment_readiness")["status"] != "not_applicable"
    assert _lane(bundle, "supportive_palliative_readiness")["status"] == "not_applicable"


def test_diagnostic_truth_minimum_requires_dominant_decision_fields():
    from prostanet.domains.patient_tracking.clinical_readiness_tower import (
        build_clinical_readiness_tower,
    )

    bundle = build_clinical_readiness_tower(
        {
            "identity": {"nss": "DX-MIN-001"},
            "baseline": {"psa_value": 7.1},
            "latest_assessment": {"state": "diagnostic_workup"},
            "treatments": [],
        },
        state="diagnostic_workup",
        patient_ref="DX-MIN-001",
    )

    lane = _lane(bundle, "diagnostic_biopsy_readiness")

    assert lane["status"] == "requires_data"
    assert lane["capture_surface"] == "initial_wizard"
    assert {
        "psa_density",
        "mri_pirads_score",
        "dre_suspicious",
        "biopsy_status",
        "family_history",
        "germline_risk",
    } <= set(lane["missing_fields"])
    assert lane["cta_url"].endswith("/wizard/diagnostic_workup?readiness_lane=diagnostic_biopsy_readiness")


def test_diagnostic_truth_minimum_can_be_satisfied_by_legacy_aliases():
    from prostanet.domains.patient_tracking.clinical_readiness_tower import (
        build_clinical_readiness_tower,
    )

    bundle = build_clinical_readiness_tower(
        {
            "identity": {"nss": "DX-MIN-002"},
            "baseline": {
                "psa_value": 6.4,
                "psad": 0.17,
                "prior_mpmri_pirads_score": 4,
                "dre_finding": "normal",
                "primary_biopsy_completed_or_planned": "1",
                "family_history_positive": "0",
                "germline_risk_mutation": "negative",
            },
            "latest_assessment": {"state": "diagnostic_workup"},
            "treatments": [],
        },
        state="diagnostic_workup",
    )

    lane = _lane(bundle, "diagnostic_biopsy_readiness")

    assert lane["status"] == "ready"
    assert lane["missing_fields"] == []


def test_localized_function_preference_minimum_blocks_as_rp_rt_until_complete():
    from prostanet.domains.patient_tracking.clinical_readiness_tower import (
        build_clinical_readiness_tower,
    )

    bundle = build_clinical_readiness_tower(
        {
            "identity": {"nss": "LOC-PREF-001"},
            "baseline": {
                "clinical_risk_group": "intermediate",
                "life_expectancy_years": 15,
            },
            "latest_assessment": {"state": "localized_initial"},
            "treatments": [],
        },
        state="localized_initial",
        patient_ref="LOC-PREF-001",
    )

    lane = _lane(bundle, "localized_treatment_readiness")

    assert lane["status"] == "requires_data"
    assert lane["capture_surface"] == "initial_wizard"
    assert {
        "urinary_function_baseline",
        "sexual_function_baseline",
        "bowel_function_baseline",
        "rp_rt_as_tradeoff_documented",
        "localized_patient_values",
    } <= set(lane["missing_fields"])
    assert lane["cta_url"].endswith("/wizard/localized_initial?readiness_lane=localized_treatment_readiness")


def test_localized_function_preference_minimum_can_be_satisfied_by_preference_aliases():
    from prostanet.domains.patient_tracking.clinical_readiness_tower import (
        build_clinical_readiness_tower,
    )

    bundle = build_clinical_readiness_tower(
        {
            "identity": {"nss": "LOC-PREF-002"},
            "baseline": {
                "clinical_risk_group": "intermediate",
                "life_expectancy_years": 15,
                "ipss_score": 7,
                "iief5_score": 18,
                "bowel_function_baseline": "sin sintomas relevantes",
                "shared_decision_local_options": "AS/RP/RT revisadas",
                "patient_preferences": "prioriza continencia y menor toxicidad intestinal",
            },
            "latest_assessment": {"state": "localized_initial"},
            "treatments": [],
        },
        state="localized_initial",
    )

    lane = _lane(bundle, "localized_treatment_readiness")

    assert lane["status"] == "ready"
    assert "localized_patient_values" not in lane["missing_fields"]


def test_patient_twin_preference_pro_minimum_requires_values_pros_and_thresholds():
    from prostanet.domains.patient_tracking.clinical_readiness_tower import (
        build_clinical_readiness_tower,
    )

    bundle = build_clinical_readiness_tower(
        {
            "identity": {"nss": "PTWIN-001"},
            "baseline": {
                "clinical_risk_group": "intermediate",
                "life_expectancy_years": 15,
                "urinary_function_baseline": 8,
                "sexual_function_baseline": 17,
                "bowel_function_baseline": "sin sintomas relevantes",
                "rp_rt_as_tradeoff_documented": "documentado con paciente",
            },
            "latest_assessment": {"state": "localized_initial"},
            "treatments": [],
        },
        state="localized_initial",
        patient_ref="PTWIN-001",
    )

    lane = _lane(bundle, "patient_twin_readiness")

    assert lane["status"] == "requires_data"
    assert lane["capture_surface"] == "longitudinal_followup"
    assert "patient_values" in lane["missing_fields"]
    assert "toxicity_tolerance" in lane["missing_fields"]
    assert "redecision_threshold" in lane["missing_fields"]
    assert "baseline_pro" not in lane["missing_fields"]
    assert "decision_tradeoff" not in lane["missing_fields"]
    assert "readiness_lane=patient_twin_readiness" in lane["cta_url"]


def test_parp_hrr_lane_requires_traceable_hrr_when_parp_competes():
    from prostanet.domains.patient_tracking.clinical_readiness_tower import (
        build_clinical_readiness_tower,
    )

    bundle = build_clinical_readiness_tower(
        {
            "identity": {"nss": "PARP-001"},
            "baseline": {"metastasis_site": "M1b", "psa_value": 15.0},
            "latest_assessment": {"state": "m1_crpc"},
            "treatments": [{"line_of_therapy": 2, "drug_scheme": "ADT + enzalutamide"}],
        },
        longitudinal_bundle={"therapeutic_readiness_bundle": {"candidate_family": "parp"}},
        state="m1_crpc",
    )

    lane = _lane(bundle, "parp_hrr_readiness")
    assert lane["status"] == "requires_data"
    assert "hrr_brca_status" in lane["missing_fields"]
    assert "molecular_report_source" in lane["missing_fields"]


def test_readiness_gate_contracts_cover_103_gates():
    from prostanet.domains.patient_tracking.clinical_readiness_tower import (
        summarize_readiness_gate_contracts,
    )

    summary = summarize_readiness_gate_contracts()

    assert summary["total_gates"] == 103
    assert summary["covered_gates"] == 103
    assert summary["uncovered_gates"] == []


def test_trial_empty_payload_guard_remains_47_of_47():
    from prostanet.domains.patient_tracking.clinical_readiness_tower import (
        build_clinical_readiness_tower,
    )

    bundle = build_clinical_readiness_tower({"identity": {"nss": "EMPTY"}})

    assert bundle["summary"]["trial_contract_total"] == 47
    assert bundle["summary"]["trial_requires_data_on_empty_payload"] == 47


def test_router_can_filter_longitudinal_fields_by_readiness_lane():
    from prostanet.presentation.clinical_field_router import build_clinical_field_router

    routed = build_clinical_field_router(
        "m1_crpc",
        phase="longitudinal_followup",
        readiness_lane="psma_rlt_readiness",
    )
    names = {
        field["name"]
        for group in routed["group_order"]
        for field in group.get("fields", [])
    }

    assert routed["summary"]["readiness_filter_active"] is True
    assert "psma_pet_positive_current" in names
    assert "psa_nadir_post_rt" not in names


def test_router_can_filter_patient_twin_preference_and_pro_fields():
    from prostanet.presentation.clinical_field_router import build_clinical_field_router

    routed = build_clinical_field_router(
        "localized_initial",
        phase="longitudinal_followup",
        readiness_lane="patient_twin_readiness",
    )
    names = {
        field["name"]
        for group in routed["group_order"]
        for field in group.get("fields", [])
    }

    assert routed["summary"]["readiness_filter_active"] is True
    assert {
        "patient_values",
        "baseline_pro",
        "toxicity_tolerance",
        "decision_tradeoff",
        "redecision_threshold",
    } <= names
    assert "psma_pet_positive_current" not in names


def test_router_can_filter_localized_function_preference_fields_in_wizard():
    from prostanet.presentation.clinical_field_router import build_clinical_field_router

    routed = build_clinical_field_router(
        "localized_initial",
        phase="initial_wizard",
        readiness_lane="localized_treatment_readiness",
    )
    names = {
        field["name"]
        for group in routed["group_order"]
        for field in group.get("fields", [])
    }

    assert routed["summary"]["readiness_filter_active"] is True
    assert {
        "localized_patient_values",
        "urinary_function_baseline",
        "sexual_function_baseline",
        "bowel_function_baseline",
        "decision_rp_vs_rt_active",
    } <= names
    assert "psma_pet_positive_current" not in names


def test_field_router_diagnostic_truth_minimum_is_compact_and_state_scoped():
    from prostanet.presentation.clinical_field_router import build_clinical_field_router

    routed = build_clinical_field_router(
        "diagnostic_workup",
        phase="initial_wizard",
        readiness_lane="diagnostic_truth_minimum",
    )
    names = {
        field["name"]
        for group in routed["group_order"]
        for field in group.get("fields", [])
    }
    blob = " ".join(sorted(names)).lower()

    assert routed["summary"]["readiness_filter_active"] is True
    assert {
        "psa_density",
        "mri_pirads_score",
        "biopsy_status",
        "family_history",
        "germline_risk",
        "phi_value",
        "fourkscore_value",
    } <= names
    assert not any(token in blob for token in ("crpc", "parp", "testosterone", "salvage", "psma_rlt"))
    assert routed["summary"]["total_fields"] <= 18
