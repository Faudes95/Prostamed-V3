from pathlib import Path


def test_gate_contract_matrix_covers_all_103_yaml_gates():
    from prostanet.shared.clinical_contract_audit import summarize_gate_contract_matrix

    summary = summarize_gate_contract_matrix()

    assert summary["total_gates"] == 103
    assert summary["covered_gates"] == 103
    assert summary["uncovered_gates"] == []
    assert set(summary["phase_counts"]).issubset({
        "covered_at_classifier",
        "covered_at_initial_wizard",
        "covered_at_longitudinal_followup",
    })


def test_all_47_trials_have_evaluator_and_empty_payload_is_not_eligible():
    from prostanet.shared.trial_criteria_registry import TRIAL_CRITERIA_REGISTRY
    from prostanet.shared.trial_eligibility_engine import (
        evaluate_trial_eligibility,
        get_total_evaluators_count,
        list_supported_trials,
    )

    supported = list_supported_trials()
    assert len(TRIAL_CRITERIA_REGISTRY) == 47
    assert get_total_evaluators_count() == 47
    assert set(supported) == set(TRIAL_CRITERIA_REGISTRY)

    for trial_id in supported:
        result = evaluate_trial_eligibility({}, trial_id)
        assert result["eligible"] is False, trial_id
        assert result["status"] == "requires_data", trial_id
        assert result["eligibility_status"] == "requires_data", trial_id
        assert "Estado clínico actual" in result["missing_data"], trial_id


def test_trial_with_missing_decisive_data_is_indeterminate_not_eligible():
    from prostanet.shared.trial_eligibility_engine import evaluate_trial_eligibility

    result = evaluate_trial_eligibility({"disease_state": "mcspc", "ecog_current": 1}, "CHAARTED")

    assert result["eligible"] is False
    assert result["status"] == "requires_data"
    assert result["missing_data"]


def test_testosterone_value_from_classifier_feeds_unified_testosterone_seed():
    import tracking_db

    value, source = tracking_db._preferred_testosterone_longitudinal_value({
        "testosterone_value": 18,
        "testosterone_current": "",
        "testosterone": "",
        "testosterone_baseline": "",
    })

    assert value == 18
    assert source == "testosterone_value"


def test_psa_observability_does_not_invent_treatment_line_for_unassigned_psa():
    from prostanet.presentation.v2_adapters import _psa_observability

    obs = _psa_observability({
        "psa_observability": {
            "points": [{"sample_date": "2026-05-01", "psa_value": 7.2}],
            "treatment_bands": [],
            "line_segments": [],
            "metrics": {},
        }
    })

    assert obs["n_points"] == 1
    assert obs["n_lines"] == 0
    assert obs["points"][0]["line"] is None


def test_patient_profile_v2_contains_no_demo_treatment_or_psa_tower_fallbacks():
    template = Path("templates/patient_profile_v2.html").read_text(encoding="utf-8")

    forbidden = [
        "L1 ADT+Daro+Doce",
        "ADT_DAROLUTAMIDE_DOCETAXEL",
        "ADT_DARO_DOCE",
        "PSA 12.0",
        "3.8 ng",
        "11 puntos",
        "const psaValues = [45.0",
    ]
    for token in forbidden:
        assert token not in template
