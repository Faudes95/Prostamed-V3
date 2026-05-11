# IEC 62304 §5.5 (Unit verification)
from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = (
    REPO_ROOT
    / "output"
    / "playwright"
    / "validation"
    / "advanced_sequencing_matrix40-20260413"
    / "run_mcp_advanced_validation.py"
)


def _load_runner():
    spec = importlib.util.spec_from_file_location("advanced_matrix40_runner", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_advanced_matrix40_case_distribution_and_size():
    module = _load_runner()

    cases = module.build_advanced_cases()

    assert len(cases) == 40
    assert sum(1 for case in cases if case["cohort"] == "m0_crpc") == 10
    assert sum(1 for case in cases if case["cohort"] == "mhspc") == 15
    assert sum(1 for case in cases if case["cohort"] == "m1_crpc") == 15


def test_advanced_matrix40_cases_carry_structured_advanced_oracle_contracts():
    module = _load_runner()
    cases = {case["case_id"]: case for case in module.build_advanced_cases()}

    assert cases["crpc_nm_02_high_risk_arpi"]["advanced_therapy_oracle_contract"]["selected_therapy_aliases"]
    assert cases["mhspc_01_low_rt_primary"]["advanced_therapy_oracle_contract"]["local_adjunct_aliases"]
    assert cases["crpc_m_09_parp_pathway"]["advanced_therapy_oracle_contract"]["selected_therapy_aliases"]

    assert cases["adv_nm_06_restaging_required"]["advanced_therapy_oracle_contract"]["prerequisite_action_aliases"]
    assert cases["adv_m1_16_confirm_castration_gate"]["advanced_therapy_oracle_contract"]["prerequisite_action_aliases"]
    assert cases["adv_m1_19_post_taxane_immunotherapy_overlay"]["advanced_therapy_oracle_contract"]["deprioritized_therapy_aliases"]


def test_configure_base_runner_points_outputs_to_advanced_matrix_dir():
    module = _load_runner()

    module.configure_base_runner()

    assert module.matrix60.OUTPUT_DIR == module.OUTPUT_DIR
    assert module.matrix60.RUN_ID == module.RUN_ID
    assert module.matrix60.build_cases is module.build_advanced_cases
