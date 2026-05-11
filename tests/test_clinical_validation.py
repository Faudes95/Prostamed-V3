# IEC 62304 §5.7 (System testing)
from collections import Counter

from prostanet.domains.clinical_validation import build_trajectory_catalog
from prostanet.domains.m0_crpc.schemas import M0_CRPC_SCHEMA


def test_clinical_validation_catalog_has_72_trajectories_with_expected_family_distribution():
    # EPIC 1 (Phoenix enforcement): +2 trayectorias en `recurrence_bcr`
    # (bcr_pre_phoenix_deferral y bcr_post_phoenix_salvage) para bloquear
    # salvage prematuro post-RT cuando PSA aún no cumple nadir + 2 ng/mL.
    # EPIC 9 (hardening + schema-governance): +18 trayectorias
    # `scenario_family="epic9_hardening"` cubriendo GAP-1..GAP-17 + GAP-A.
    trajectories = build_trajectory_catalog()

    assert len(trajectories) == 72

    family_counts = Counter(item["scenario_family"] for item in trajectories)
    assert family_counts == {
        "diagnostic_workup": 5,
        "post_negative_biopsy_followup": 4,
        "localized_initial": 7,
        "active_surveillance": 5,
        "post_prostatectomy": 5,
        "recurrence_bcr": 7,
        "post_radiotherapy_or_local_salvage": 4,
        "adt_progression_verification": 5,
        "m0_crpc": 3,
        "mHSPC": 4,
        "m1_crpc": 5,
        "epic9_hardening": 18,
    }

    scenario_ids = [item["scenario_id"] for item in trajectories]
    assert len(set(scenario_ids)) == len(scenario_ids)
    # Las dos trayectorias EPIC 1 deben aparecer exactamente una vez.
    assert "bcr_pre_phoenix_deferral" in scenario_ids
    assert "bcr_post_phoenix_salvage" in scenario_ids
    # Las 18 trayectorias EPIC 9 deben estar presentes.
    epic9_ids = {item["scenario_id"] for item in trajectories if item["scenario_family"] == "epic9_hardening"}
    assert len(epic9_ids) == 18
    assert {
        "elderly_75_arpi_attenuated",
        "qtc_prolonged_enza_penalty",
        "nyha_iii_abiraterone_block",
        "arv7_positive_sequencer_tagged",
        "confirmatory_biopsy_exposed_schema",
        "ari_medication_psa_corrected",
        "prostate_volume_psad_derived",
        "crpc_drug_scheme_required",
        "oos12_readiness_fallback_m0crpc_psma",
        "epic26_post_prostatectomy_captured",
        "peace1_metachronous_not_applicable",
        "child_pugh_b_abiraterone_hardblock",
        "docetaxel_fitness_arasens_trial",
        "talapro3_hrr_bonus",
        "primary_rt_low_volume_offered",
        "ddi_runtime_contraindicated_hardblock",
        "cyp2c19_abiraterone_clopidogrel_moderate",
        "bcr_psadt_defensive_closed",
    } <= epic9_ids


def test_validation_trajectories_endpoint_exposes_catalog_and_family_counts(app_client):
    client, _ = app_client

    response = client.get("/api/validation/trajectories")
    assert response.status_code == 200

    payload = response.get_json()
    assert payload["success"] is True
    assert payload["total_trajectories"] == 72
    assert len(payload["trajectories"]) == 72
    assert payload["family_counts"]["m1_crpc"] == 5
    assert payload["family_counts"]["post_prostatectomy"] == 5
    assert payload["family_counts"]["adt_progression_verification"] == 5
    # EPIC 1 Phoenix: recurrence_bcr ahora incluye 2 escenarios Phoenix.
    assert payload["family_counts"]["recurrence_bcr"] == 7
    # EPIC 9 hardening: 18 trayectorias (GAP-1..GAP-17 + GAP-A) bajo
    # scenario_family="epic9_hardening".
    assert payload["family_counts"]["epic9_hardening"] == 18
    assert any(item["scenario_id"] == "post_prostatectomy_persistent_psa" for item in payload["trajectories"])
    assert any(item["scenario_id"] == "m1_crpc_abiraterone_hepatic_safety" for item in payload["trajectories"])
    assert any(item["scenario_id"] == "high_volume_progression_on_adt_unclosed_castration" for item in payload["trajectories"])


def test_post_prostatectomy_persistent_psa_keeps_family_but_updates_clinical_oracle():
    trajectories = build_trajectory_catalog()
    scenario = next(item for item in trajectories if item["scenario_id"] == "post_prostatectomy_persistent_psa")

    assert scenario["scenario_family"] == "post_prostatectomy"
    assert scenario["baseline_oracle"]["expected_effective_state"] == "post_prostatectomy"
    assert scenario["clinical_oracle"]["expected_effective_state"] == "recurrence_bcr"
    assert scenario["clinical_oracle"]["expected_action_contains"] == "salvage"
    assert scenario["clinical_oracle"]["expected_action_label"] == "Activar salvage y reestadificación dirigida"
    assert scenario["visits"][-1]["oracle"]["expected_effective_state"] == "recurrence_bcr"


def test_validation_catalog_encodes_supporting_visibility_for_mhspc_local_adjuncts():
    trajectories = build_trajectory_catalog()
    rt_primary = next(item for item in trajectories if item["scenario_id"] == "mhspc_low_volume_sync_doublet")
    mdt_case = next(item for item in trajectories if item["scenario_id"] == "mhspc_oligometachronous_mdt")

    assert rt_primary["clinical_oracle"]["visibility_expectation"] == "supporting"
    assert "RT al primario" in rt_primary["clinical_oracle"]["supporting_expected_aliases"]
    assert rt_primary["clinical_oracle"]["action_semantic_family"] == "local_primary_rt"

    assert mdt_case["clinical_oracle"]["visibility_expectation"] == "supporting"
    assert "MDT" in mdt_case["clinical_oracle"]["supporting_expected_aliases"]
    assert mdt_case["clinical_oracle"]["action_semantic_family"] == "mdt_candidate"


def test_validation_catalog_strengthens_nmcrpc_seed_requirements_and_specific_aliases():
    trajectories = build_trajectory_catalog()
    nmcrpc = next(item for item in trajectories if item["scenario_id"] == "m0_crpc_high_risk_arpi")
    parp = next(item for item in trajectories if item["scenario_id"] == "m1_crpc_parp_pathway")

    assert nmcrpc["baseline_payload"]["imaging_negative"] == 1
    assert nmcrpc["baseline_payload"]["conventional_imaging_status"] == "M0"
    assert nmcrpc["baseline_payload"]["conventional_imaging_modality"] == "TC + gammagrama óseo"
    assert nmcrpc["baseline_payload"]["current_adt_context"] == "medical_adt_continuous"
    assert nmcrpc["baseline_payload"]["progression_pattern"] == "biochemical_only"
    assert nmcrpc["clinical_oracle"]["expected_action_label"] == "Darolutamida + terapia de privación androgénica"

    assert parp["clinical_oracle"]["expected_action_label"] == "Olaparib"
    assert "PARP" in parp["clinical_oracle"]["headline_expected_aliases"]


def test_validation_catalog_nmcrpc_low_and_contraindication_scenarios_close_m0_and_biochemical_pattern():
    trajectories = build_trajectory_catalog()
    low_risk = next(item for item in trajectories if item["scenario_id"] == "m0_crpc_low_risk_psadt_slow")
    contraindication = next(item for item in trajectories if item["scenario_id"] == "m0_crpc_contraindication_refines_choice")

    for scenario in (low_risk, contraindication):
        assert scenario["baseline_payload"]["conventional_imaging_status"] == "M0"
        assert scenario["baseline_payload"]["progression_pattern"] == "biochemical_only"
        assert scenario["visits"][-1]["payload"]["conventional_imaging_status"] == "M0"
        assert scenario["visits"][-1]["payload"]["progression_pattern"] == "biochemical_only"


def test_m0_crpc_schema_exposes_explicit_imaging_status_and_progression_pattern():
    field_names = {field["name"] for field in M0_CRPC_SCHEMA["fields"]}

    assert "conventional_imaging_status" in field_names
    assert "progression_pattern" in field_names
