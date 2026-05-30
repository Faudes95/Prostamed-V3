# IEC 62304 §5.5 (Unit verification)
from __future__ import annotations

def _load_matrix60_module():
    from prostanet.domains.clinical_validation import matrix60_validation

    return matrix60_validation


def test_matrix60_persistent_psa_converges_with_catalog_oracle():
    module = _load_matrix60_module()

    case = module.catalog_case(
        "rp_bcr_01_persistent_psa",
        "bcr_post_rp",
        "post_rp",
        "post_prostatectomy_persistent_psa",
        focus="PSA persistente",
    )
    enriched = module.enrich_case_expectations(case)

    assert enriched["oracle_source"] == "clinical_oracle"
    assert enriched["expected_state_code"] == "recurrence_bcr"
    assert enriched["expected_action_label"] == "Activar salvage y reestadificación dirigida"
    assert enriched["catalog_expected_state"] == "recurrence_bcr"
    assert enriched["catalog_expected_action"] == "Activar salvage y reestadificación dirigida"
    assert enriched["raw_module_expected_state"] == "recurrence_bcr"
    assert enriched["oracle_drift"] is False


def test_matrix60_keeps_specific_module_label_when_it_matches_catalog_oracle():
    module = _load_matrix60_module()

    case = module.catalog_case(
        "rp_bcr_02_local_pelvic",
        "bcr_post_rp",
        "post_rp",
        "bcr_post_rp_local_pelvic",
        focus="salvage pélvico",
    )
    enriched = module.enrich_case_expectations(case)

    assert enriched["oracle_source"] == "clinical_oracle"
    assert enriched["expected_state_code"] == "recurrence_bcr"
    assert enriched["catalog_expected_action"] == "salvage"
    assert enriched["expected_action_label"] == enriched["raw_module_expected_action"]
    assert enriched["oracle_drift"] is False


def test_matrix60_summary_reports_no_oracle_drift_when_core_converges():
    module = _load_matrix60_module()

    case = module.catalog_case(
        "rp_bcr_01_persistent_psa",
        "bcr_post_rp",
        "post_rp",
        "post_prostatectomy_persistent_psa",
        focus="PSA persistente",
    )
    enriched = module.enrich_case_expectations(case)
    result = {
        **enriched,
        "ui": {
            "diagnosis": "Recurrencia bioquímica",
            "stage": "Recurrencia bioquímica",
            "decision_today": "Activar salvage y reestadificación dirigida",
            "next_best_action": "Activar salvage y reestadificación dirigida",
            "alerts": [],
            "schedule": [],
        },
        "state_pass": True,
        "action_status": "top",
        "action_pass": True,
        "forbidden_violation": False,
        "issues": [],
    }

    summary = module.summarize([result])
    markdown = module.build_summary_markdown(summary, [result])

    assert summary["oracle_drift_count"] == 0
    assert summary["oracle_drift_case_ids"] == []
    assert "## Drift de oracle" in markdown
    assert "Sin drift entre el oracle del catálogo y la salida raw del módulo." in markdown


def test_matrix60_nmcrpc_high_risk_case_seeds_conventional_negative_imaging_and_arpi_contract():
    module = _load_matrix60_module()

    case = module.catalog_case(
        "crpc_nm_02_high_risk_arpi",
        "crpc",
        "non_metastatic",
        "m0_crpc_high_risk_arpi",
        focus="nmCRPC ARPI",
    )
    enriched = module.enrich_case_expectations(case)

    assert case["payload"]["imaging_negative"] == 1
    assert case["payload"]["conventional_imaging_status"] == "M0"
    assert case["payload"]["conventional_imaging_modality"] == "TC + gammagrama óseo"
    assert case["payload"]["current_adt_context"] == "medical_adt_continuous"
    assert case["payload"]["progression_pattern"] == "biochemical_only"
    assert enriched["expected_action_label"] == "Darolutamida + terapia de privación androgénica"
    assert enriched["action_semantic_family"] == "arpi_nmcrpc"
    assert enriched["oracle_specificity_policy"] == "generic_or_specific_ok"


def test_matrix60_nmcrpc_cases_now_converge_without_oracle_drift():
    module = _load_matrix60_module()

    low_risk = module.catalog_case(
        "crpc_nm_01_low_psadt_slow",
        "crpc",
        "non_metastatic",
        "m0_crpc_low_risk_psadt_slow",
        focus="nmCRPC observación",
    )
    high_risk = module.catalog_case(
        "crpc_nm_02_high_risk_arpi",
        "crpc",
        "non_metastatic",
        "m0_crpc_high_risk_arpi",
        focus="nmCRPC ARPI",
    )
    contraindication = module.catalog_case(
        "crpc_nm_03_contraindication_daro",
        "crpc",
        "non_metastatic",
        "m0_crpc_contraindication_refines_choice",
        focus="riesgo convulsivo / darolutamida",
    )

    low_risk_enriched = module.enrich_case_expectations(low_risk)
    high_risk_enriched = module.enrich_case_expectations(high_risk)
    contraindication_enriched = module.enrich_case_expectations(contraindication)

    assert low_risk_enriched["raw_module_expected_action"] == "Vigilancia estrecha con ADT y monitorización"
    assert low_risk_enriched["oracle_drift"] is False
    assert high_risk_enriched["raw_module_expected_action"] == "Darolutamida + terapia de privación androgénica"
    assert high_risk_enriched["oracle_drift"] is False
    assert contraindication_enriched["raw_module_expected_action"] == "Darolutamida + terapia de privación androgénica"
    assert contraindication_enriched["oracle_drift"] is False


def test_matrix60_mhspc_rt_primary_case_marks_supporting_visibility_expectation():
    module = _load_matrix60_module()

    case = module.catalog_case(
        "mhspc_01_low_rt_primary",
        "mhspc",
        "low_volume",
        "mhspc_low_volume_sync_doublet",
        focus="RT al primario",
    )
    enriched = module.enrich_case_expectations(case)

    assert enriched["expected_action_label"] == "RT al primario"
    assert enriched["visibility_expectation"] == "supporting"
    assert "RT al primario" in enriched["oracle_action_contract"]["supporting_expected_aliases"]
    assert enriched["action_semantic_family"] == "local_primary_rt"


def test_matrix60_parp_oracle_contract_accepts_olaparib_as_specific_family_match():
    module = _load_matrix60_module()

    case = module.catalog_case(
        "crpc_m_09_parp_pathway",
        "crpc",
        "metastatic",
        "m1_crpc_parp_pathway",
        focus="PARP / BRCA2",
    )
    enriched = module.enrich_case_expectations(case)

    assert enriched["expected_action_label"] == "Olaparib"
    assert enriched["action_semantic_family"] == "parp_family"
    assert "PARP" in enriched["oracle_action_contract"]["headline_expected_aliases"]
    assert "Olaparib" in enriched["oracle_action_contract"]["headline_expected_aliases"]
    assert enriched["oracle_drift"] is False
