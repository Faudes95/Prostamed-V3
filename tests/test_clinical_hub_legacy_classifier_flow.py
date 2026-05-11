"""Regression coverage for the clinical hub official quick-classifier flow."""

from prostanet.domains.state_classifier.service import StateClassifierService


def _classify(payload: dict) -> str:
    return StateClassifierService().classify(payload)["state"]


def test_official_flow_prediagnosis_negative_biopsy_routes_to_followup():
    assert _classify({
        "known_cancer_diagnosis": "0",
        "prior_negative_biopsy": "1",
    }) == "post_negative_biopsy_followup"


def test_official_flow_prediagnosis_screening_routes_to_screening():
    assert _classify({
        "known_cancer_diagnosis": "0",
        "screening_context": "1",
        "encounter_type": "screening",
    }) == "screening"


def test_official_flow_confirmed_localized_routes_to_localized_initial():
    assert _classify({
        "known_cancer_diagnosis": "1",
        "metastatic_disease_known": "0",
        "prior_prostatectomy": "0",
        "prior_radiation": "0",
    }) == "localized_initial"


def test_official_flow_post_rp_bcr_routes_to_recurrence_bcr():
    assert _classify({
        "known_cancer_diagnosis": "1",
        "prior_prostatectomy": "1",
        "bcr_detected": "1",
        "bcr_psa": "0.24",
        "bcr_date": "2026-05-01",
    }) == "recurrence_bcr"


def test_official_flow_post_rt_without_failure_routes_to_followup():
    assert _classify({
        "known_cancer_diagnosis": "1",
        "prior_radiation": "1",
        "psa_nadir_post_rt": "0.4",
        "phoenix_delta": "0.8",
    }) == "post_radiotherapy_followup"


def test_official_flow_post_rt_phoenix_routes_to_local_salvage():
    assert _classify({
        "known_cancer_diagnosis": "1",
        "prior_radiation": "1",
        "psa_nadir_post_rt": "0.4",
        "phoenix_delta": "2.2",
        "failure_confirmation_basis": "phoenix_confirmed",
    }) == "post_radiotherapy_or_local_salvage"


def test_official_flow_m1_low_volume_routes_to_mcspc_low_volume():
    assert _classify({
        "known_cancer_diagnosis": "1",
        "metastatic_disease_known": "1",
        "metastasis_site": "M1b",
        "bone_metastasis_present": "1",
        "bone_axial_count": "2",
        "bone_appendicular_count": "0",
        "metachronous_metastasis": "0",
    }) == "mcspc_low_volume_sync_oligo"


def test_official_flow_m1_high_volume_routes_to_mcspc_high_volume_sync():
    assert _classify({
        "known_cancer_diagnosis": "1",
        "metastatic_disease_known": "1",
        "metastasis_site": "M1b",
        "bone_metastasis_present": "1",
        "bone_axial_count": "3",
        "bone_appendicular_count": "1",
        "metachronous_metastasis": "0",
    }) == "mcspc_high_volume_sync"


def test_official_flow_suspicious_crpc_routes_to_adt_verification():
    assert _classify({
        "known_cancer_diagnosis": "1",
        "current_adt_context": "medical_adt_continuous",
        "systemic_progression_context": "progression_on_adt_verify_castration",
        "castrate_testosterone_status": "unknown",
        "conventional_imaging_status": "M0",
    }) == "adt_progression_verification"


def test_official_flow_confirmed_m0_crpc_routes_to_m0_crpc():
    assert _classify({
        "known_cancer_diagnosis": "1",
        "current_adt_context": "medical_adt_continuous",
        "systemic_progression_context": "confirmed_crpc",
        "castrate_testosterone_status": "confirmed_castrate",
        "conventional_imaging_status": "M0",
    }) == "m0_crpc"


def test_official_flow_confirmed_m1_crpc_routes_to_m1_crpc():
    assert _classify({
        "known_cancer_diagnosis": "1",
        "current_adt_context": "medical_adt_continuous",
        "systemic_progression_context": "confirmed_crpc",
        "castrate_testosterone_status": "confirmed_castrate",
        "conventional_imaging_status": "M1",
        "metastatic_disease_known": "1",
        "metastasis_site": "M1c",
        "visceral_metastasis_present": "1",
        "visceral_lesion_count": "1",
    }) == "m1_crpc"
