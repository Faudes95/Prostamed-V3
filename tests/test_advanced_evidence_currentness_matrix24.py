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
    / "advanced_evidence_currentness_matrix24-20260413"
    / "run_mcp_advanced_currentness_validation.py"
)


def _load_runner():
    spec = importlib.util.spec_from_file_location("advanced_currentness_matrix24_runner", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_advanced_currentness_matrix24_case_distribution_and_size():
    module = _load_runner()

    cases = module.build_currentness_cases()

    assert len(cases) == 24
    assert sum(1 for case in cases if case["cohort"] == "m0_crpc") == 8
    assert sum(1 for case in cases if case["cohort"] == "mhspc") == 6
    assert sum(1 for case in cases if case["cohort"] == "m1_crpc") == 10


def test_advanced_currentness_matrix24_cases_carry_currentness_expectations():
    module = _load_runner()
    cases = {case["case_id"]: case for case in module.build_currentness_cases()}

    nm_stale = cases["ev_nm_06_arpi_stale_restaging"]["advanced_therapy_oracle_contract"]
    assert nm_stale["selected_evidence_status_aliases"]
    assert nm_stale["release_status_aliases"]
    assert nm_stale["refresh_action_aliases"]
    assert nm_stale["stale_block_field_aliases"]

    mh_aging = cases["ev_mh_04_triplet_aging_fitness"]["advanced_therapy_oracle_contract"]
    assert mh_aging["selected_evidence_status_aliases"]
    assert mh_aging["release_status_aliases"]
    assert mh_aging["refresh_action_aliases"]

    m1_parp = cases["ev_m1_08_parp_stale_report"]["advanced_therapy_oracle_contract"]
    assert m1_parp["selected_therapy_aliases"]
    assert m1_parp["selected_evidence_status_aliases"]
    assert m1_parp["release_status_aliases"]
    assert m1_parp["refresh_action_aliases"]
    assert m1_parp["stale_block_field_aliases"]


def test_configure_base_runner_points_outputs_to_currentness_matrix_dir():
    module = _load_runner()

    module.configure_base_runner()

    assert module.matrix60.OUTPUT_DIR == module.OUTPUT_DIR
    assert module.matrix60.RUN_ID == module.RUN_ID
    assert module.matrix60.build_cases is module.build_currentness_cases
