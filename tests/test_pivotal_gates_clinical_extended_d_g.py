"""tests/test_pivotal_gates_clinical_extended_d_g.py — FAUBOT 2026-04-25 (XXVI).

Tier 2/3 D-F (Gates 20-23): Clinical extended pivotal gates.
  - Gate 20 — ARSI × seizure history grade ≥3 (Xtandi/Erleada/Nubeqa labels)
  - Gate 21 — Abiraterone × hepatotoxicity grade 3 (Zytiga §5.1, AST/ALT >5× ULN)
  - Gate 22 — Niraparib × thrombocytopenia <150K (Akeega §5.1, MAGNITUDE 28% G3)
  - Gate 23 — Niraparib × HTA grade 3 (Akeega §5.2, MAGNITUDE DAT inhibition)

Hipótesis verificadas: H.G411-H.G450 (40 hipótesis sobre triggers + overrides
+ regimen blocking + DDI cross-check + supporting fields + alias coverage).

Convenciones:
  - Tests parametrizados por trigger value + regimen + alias (CLAUDE.md §8.2)
  - Override desactiva todos los triggers (`*_recovered_for_*`, etc.)
  - Cada gate cita evidence_tag específico + trial_refs (CLAUDE.md §8.5)
  - Backward-compatibility con gates 1-19 anteriores (CLAUDE.md §8.4)
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest

from prostanet.shared.pivotal_contraindication_gates import (
    apply_pivotal_contraindication_gates,
    REGIMEN_CODES_ARSI,
    REGIMEN_CODES_ABIRATERONE,
    REGIMEN_CODES_NIRAPARIB,
)
from prostanet.shared.pivotal_gates_yaml_loader import (
    _load_yaml_files,
    get_loaded_yaml_codes,
    validate_all_yaml_gates,
)


# ──────────────────────────────────────────────────────────────────────
# Setup helper
# ──────────────────────────────────────────────────────────────────────


def _gate_codes(payload: dict) -> list[str]:
    """Return list of triggered gate codes for a given payload."""
    r = apply_pivotal_contraindication_gates(payload, treatments=[])
    return [g["code"] for g in r["gates_triggered"]]


# ──────────────────────────────────────────────────────────────────────
# H.G411 — Catálogo: 23 YAML gates loaded sin errores
# ──────────────────────────────────────────────────────────────────────


def test_catalog_at_least_23_yaml_gates_loaded():
    """H.G411 — YAML catalog loads ≥23 gates (Tier 2/3 D-F adds 4 to 19→23)."""
    codes = get_loaded_yaml_codes()
    assert len(codes) >= 23


def test_catalog_no_validation_errors():
    """H.G412 — All YAML gates pass validate_yaml_gate_config."""
    errors = validate_all_yaml_gates()
    assertion_errors = {k: v for k, v in errors.items() if v}
    assert not assertion_errors, f"YAML validation errors: {assertion_errors}"


@pytest.mark.parametrize("gate_code", [
    "arsi_in_seizure_history_grade3",
    "abiraterone_hepatotoxicity_grade3",
    "niraparib_in_severe_thrombocytopenia",
    "niraparib_hypertension_grade3_magnitude",
])
def test_gates_20_to_23_present_in_catalog(gate_code):
    """H.G413 — Each new gate code is present in the YAML catalog."""
    codes = get_loaded_yaml_codes()
    assert gate_code in codes


# ──────────────────────────────────────────────────────────────────────
# H.G414 — Gate 20: ARSI × seizure history grade ≥3
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("seizure_grade", [3, 4, 5])
def test_gate_20_fires_on_seizure_ctcae_grade_3_plus(seizure_grade):
    """H.G414 — Gate 20 fires when seizure_ctcae_grade ≥ 3."""
    codes = _gate_codes({"seizure_ctcae_grade": seizure_grade})
    assert "arsi_in_seizure_history_grade3" in codes


@pytest.mark.parametrize("seizure_grade", [0, 1, 2])
def test_gate_20_does_not_fire_on_seizure_grade_below_3(seizure_grade):
    """H.G415 — Gate 20 does NOT fire when seizure_ctcae_grade < 3."""
    codes = _gate_codes({"seizure_ctcae_grade": seizure_grade})
    assert "arsi_in_seizure_history_grade3" not in codes


@pytest.mark.parametrize("flag_value", ["Sí", "Si", "YES", "yes", "1", "true"])
def test_gate_20_fires_on_active_seizure_disorder(flag_value):
    """H.G416 — Gate 20 fires on active_seizure_disorder truthy flag."""
    codes = _gate_codes({"active_seizure_disorder": flag_value})
    assert "arsi_in_seizure_history_grade3" in codes


@pytest.mark.parametrize("alias_field", [
    "epilepsy_active",
    "seizure_disorder_active",
])
def test_gate_20_fires_on_seizure_disorder_aliases(alias_field):
    """H.G417 — Gate 20 fires on aliases of active_seizure_disorder."""
    codes = _gate_codes({alias_field: "Sí"})
    assert "arsi_in_seizure_history_grade3" in codes


def test_gate_20_fires_on_seizure_history_grade3_documented():
    """H.G418 — Gate 20 fires on explicit grade3 documented flag."""
    codes = _gate_codes({"seizure_history_grade3_documented": "Sí"})
    assert "arsi_in_seizure_history_grade3" in codes


def test_gate_20_override_seizure_disorder_controlled_disables():
    """H.G419 — Override seizure_disorder_controlled_for_arpi disables gate 20."""
    codes = _gate_codes({
        "seizure_ctcae_grade": 4,
        "active_seizure_disorder": "Sí",
        "seizure_disorder_controlled_for_arpi": "Sí",
    })
    assert "arsi_in_seizure_history_grade3" not in codes


def test_gate_20_blocks_all_arsi_regimens():
    """H.G420 — Gate 20 blocks ALL ARSI codes (enza/apa/darolutamide)."""
    r = apply_pivotal_contraindication_gates(
        {"seizure_ctcae_grade": 3},
        treatments=[],
    )
    gate = next(
        g for g in r["gates_triggered"]
        if g["code"] == "arsi_in_seizure_history_grade3"
    )
    affected = set(gate.get("affected_regimen_codes") or [])
    # Should include the union of ENZALUTAMIDE + APALUTAMIDE + DAROLUTAMIDE
    expected = REGIMEN_CODES_ARSI
    assert affected == expected


# ──────────────────────────────────────────────────────────────────────
# H.G421 — Gate 21: Abiraterone × hepatotoxicity grade 3
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("ast_value", [201, 250, 500, 1000])
def test_gate_21_fires_on_ast_above_200(ast_value):
    """H.G421 — Gate 21 fires when ast_value > 200 IU/L (~5× ULN typical 40)."""
    codes = _gate_codes({"ast_value": ast_value})
    assert "abiraterone_hepatotoxicity_grade3" in codes


@pytest.mark.parametrize("ast_value", [0, 40, 100, 200])
def test_gate_21_does_not_fire_on_ast_at_or_below_200(ast_value):
    """H.G422 — Gate 21 does NOT fire when ast_value ≤ 200."""
    codes = _gate_codes({"ast_value": ast_value})
    assert "abiraterone_hepatotoxicity_grade3" not in codes


@pytest.mark.parametrize("alt_value", [201, 300, 800])
def test_gate_21_fires_on_alt_above_200(alt_value):
    """H.G423 — Gate 21 fires when alt_value > 200 IU/L."""
    codes = _gate_codes({"alt_value": alt_value})
    assert "abiraterone_hepatotoxicity_grade3" in codes


@pytest.mark.parametrize("alias_field,value", [
    ("ast_iu_l", 250),
    ("ast_baseline", 220),
    ("ast_serum", 300),
    ("sgot", 250),
    ("alt_iu_l", 220),
    ("alt_baseline", 250),
    ("alt_serum", 300),
    ("sgpt", 220),
])
def test_gate_21_fires_on_ast_alt_aliases(alias_field, value):
    """H.G424 — Gate 21 fires on AST/ALT aliases (sgot, sgpt, etc.)."""
    codes = _gate_codes({alias_field: value})
    assert "abiraterone_hepatotoxicity_grade3" in codes


@pytest.mark.parametrize("bilirubin", [3.1, 5.0, 10.0])
def test_gate_21_fires_on_bilirubin_above_3(bilirubin):
    """H.G425 — Gate 21 fires when bilirubin_total_mg_dl > 3.0."""
    codes = _gate_codes({"bilirubin_total_mg_dl": bilirubin})
    assert "abiraterone_hepatotoxicity_grade3" in codes


@pytest.mark.parametrize("hepatotox_grade", [3, 4, 5])
def test_gate_21_fires_on_hepatotox_ctcae_grade_3_plus(hepatotox_grade):
    """H.G426 — Gate 21 fires when hepatotoxicity_ctcae_grade ≥ 3."""
    codes = _gate_codes({"hepatotoxicity_ctcae_grade": hepatotox_grade})
    assert "abiraterone_hepatotoxicity_grade3" in codes


def test_gate_21_fires_on_explicit_flag():
    """H.G427 — Gate 21 fires on explicit flag hepatotoxicity_grade3_for_abiraterone."""
    codes = _gate_codes({"hepatotoxicity_grade3_for_abiraterone": "Sí"})
    assert "abiraterone_hepatotoxicity_grade3" in codes


def test_gate_21_override_hepatic_function_recovered_disables():
    """H.G428 — Override hepatic_function_recovered_for_abiraterone disables gate 21."""
    codes = _gate_codes({
        "ast_value": 500,
        "alt_value": 500,
        "bilirubin_total_mg_dl": 5,
        "hepatic_function_recovered_for_abiraterone": "Sí",
    })
    assert "abiraterone_hepatotoxicity_grade3" not in codes


def test_gate_21_blocks_only_abiraterone_regimens():
    """H.G429 — Gate 21 blocks ONLY abiraterone regimens (not enzalutamide/apalutamide)."""
    r = apply_pivotal_contraindication_gates(
        {"ast_value": 500},
        treatments=[],
    )
    gate = next(
        g for g in r["gates_triggered"]
        if g["code"] == "abiraterone_hepatotoxicity_grade3"
    )
    affected = set(gate.get("affected_regimen_codes") or [])
    assert affected == REGIMEN_CODES_ABIRATERONE


# ──────────────────────────────────────────────────────────────────────
# H.G430 — Gate 22: Niraparib × thrombocytopenia
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("platelets", [149999, 100000, 50000, 25000])
def test_gate_22_fires_on_platelets_below_150k(platelets):
    """H.G430 — Gate 22 fires when platelets < 150 000/µL (more strict than gate 15)."""
    codes = _gate_codes({"platelets": platelets})
    assert "niraparib_in_severe_thrombocytopenia" in codes


@pytest.mark.parametrize("platelets", [150000, 200000, 350000])
def test_gate_22_does_not_fire_on_platelets_at_or_above_150k(platelets):
    """H.G431 — Gate 22 does NOT fire when platelets ≥ 150K."""
    codes = _gate_codes({"platelets": platelets})
    assert "niraparib_in_severe_thrombocytopenia" not in codes


@pytest.mark.parametrize("alias_field", [
    "platelets_baseline",
    "platelet_count",
    "thrombocytes",
])
def test_gate_22_fires_on_platelets_aliases(alias_field):
    """H.G432 — Gate 22 fires on platelets aliases."""
    codes = _gate_codes({alias_field: 100000})
    assert "niraparib_in_severe_thrombocytopenia" in codes


@pytest.mark.parametrize("trombo_grade", [3, 4])
def test_gate_22_fires_on_thrombocytopenia_ctcae_grade_3_plus(trombo_grade):
    """H.G433 — Gate 22 fires when thrombocytopenia_ctcae_grade ≥ 3."""
    codes = _gate_codes({"thrombocytopenia_ctcae_grade": trombo_grade})
    assert "niraparib_in_severe_thrombocytopenia" in codes


def test_gate_22_fires_on_explicit_flag():
    """H.G434 — Gate 22 fires on explicit flag for niraparib trombo."""
    codes = _gate_codes({"thrombocytopenia_grade3_for_niraparib": "Sí"})
    assert "niraparib_in_severe_thrombocytopenia" in codes


@pytest.mark.parametrize("hemorrhage_grade", [3, 4, 5])
def test_gate_22_fires_on_hemorrhage_grade_3_plus(hemorrhage_grade):
    """H.G435 — Gate 22 fires when hemorrhage_ctcae_grade ≥ 3 (active bleeding)."""
    codes = _gate_codes({"hemorrhage_ctcae_grade": hemorrhage_grade})
    assert "niraparib_in_severe_thrombocytopenia" in codes


def test_gate_22_override_platelet_count_recovered_disables():
    """H.G436 — Override platelet_count_recovered_for_niraparib disables gate 22."""
    codes = _gate_codes({
        "platelets": 50000,
        "thrombocytopenia_ctcae_grade": 4,
        "platelet_count_recovered_for_niraparib": "Sí",
    })
    assert "niraparib_in_severe_thrombocytopenia" not in codes


def test_gate_22_blocks_only_niraparib_regimens():
    """H.G437 — Gate 22 blocks ONLY niraparib regimens (not olaparib/talazo/ruca)."""
    r = apply_pivotal_contraindication_gates(
        {"platelets": 100000},
        treatments=[],
    )
    gate = next(
        g for g in r["gates_triggered"]
        if g["code"] == "niraparib_in_severe_thrombocytopenia"
    )
    affected = set(gate.get("affected_regimen_codes") or [])
    assert affected == REGIMEN_CODES_NIRAPARIB


def test_gate_22_coexists_with_gate_15():
    """H.G438 — Gate 22 fires AND gate 15 (PARPi general) fires when platelets <100K."""
    # Platelets 90K: triggers BOTH gate 15 (<100K all PARPi) AND gate 22 (<150K niraparib)
    codes = _gate_codes({"platelets": 90000})
    assert "niraparib_in_severe_thrombocytopenia" in codes
    assert "parp_inhibitor_in_severe_cytopenias" in codes


# ──────────────────────────────────────────────────────────────────────
# H.G439 — Gate 23: Niraparib × hypertension
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("sbp", [180, 200, 250])
def test_gate_23_fires_on_systolic_bp_at_or_above_180(sbp):
    """H.G439 — Gate 23 fires when systolic_blood_pressure ≥ 180 (>179)."""
    codes = _gate_codes({"systolic_blood_pressure": sbp})
    assert "niraparib_hypertension_grade3_magnitude" in codes


@pytest.mark.parametrize("sbp", [120, 140, 160, 179])
def test_gate_23_does_not_fire_on_systolic_bp_below_180(sbp):
    """H.G440 — Gate 23 does NOT fire when systolic BP < 180."""
    codes = _gate_codes({"systolic_blood_pressure": sbp})
    assert "niraparib_hypertension_grade3_magnitude" not in codes


@pytest.mark.parametrize("dbp", [120, 130, 150])
def test_gate_23_fires_on_diastolic_bp_at_or_above_120(dbp):
    """H.G441 — Gate 23 fires when diastolic_blood_pressure ≥ 120 (>119)."""
    codes = _gate_codes({"diastolic_blood_pressure": dbp})
    assert "niraparib_hypertension_grade3_magnitude" in codes


@pytest.mark.parametrize("alias_field,value", [
    ("sbp", 200),
    ("systolic_bp", 190),
    ("blood_pressure_systolic", 185),
    ("dbp", 130),
    ("diastolic_bp", 125),
    ("blood_pressure_diastolic", 130),
])
def test_gate_23_fires_on_bp_aliases(alias_field, value):
    """H.G442 — Gate 23 fires on BP aliases."""
    codes = _gate_codes({alias_field: value})
    assert "niraparib_hypertension_grade3_magnitude" in codes


@pytest.mark.parametrize("hta_grade", [3, 4, 5])
def test_gate_23_fires_on_hta_ctcae_grade_3_plus(hta_grade):
    """H.G443 — Gate 23 fires when hypertension_ctcae_grade ≥ 3."""
    codes = _gate_codes({"hypertension_ctcae_grade": hta_grade})
    assert "niraparib_hypertension_grade3_magnitude" in codes


def test_gate_23_fires_on_explicit_flag():
    """H.G444 — Gate 23 fires on explicit flag for niraparib HTA."""
    codes = _gate_codes({"hypertension_grade3_for_niraparib": "Sí"})
    assert "niraparib_hypertension_grade3_magnitude" in codes


def test_gate_23_override_hypertension_controlled_disables():
    """H.G445 — Override hypertension_controlled_for_niraparib disables gate 23."""
    codes = _gate_codes({
        "systolic_blood_pressure": 200,
        "diastolic_blood_pressure": 130,
        "hypertension_ctcae_grade": 4,
        "hypertension_controlled_for_niraparib": "Sí",
    })
    assert "niraparib_hypertension_grade3_magnitude" not in codes


def test_gate_23_blocks_only_niraparib_regimens():
    """H.G446 — Gate 23 blocks ONLY niraparib regimens."""
    r = apply_pivotal_contraindication_gates(
        {"systolic_blood_pressure": 200},
        treatments=[],
    )
    gate = next(
        g for g in r["gates_triggered"]
        if g["code"] == "niraparib_hypertension_grade3_magnitude"
    )
    affected = set(gate.get("affected_regimen_codes") or [])
    assert affected == REGIMEN_CODES_NIRAPARIB


# ──────────────────────────────────────────────────────────────────────
# H.G447 — Soft penalties NO se eliminan (coexistencia hard+soft)
# ──────────────────────────────────────────────────────────────────────


def test_gates_20_to_23_dont_break_existing_gates():
    """H.G447 — Pre-existing gates (1-19) still fire correctly with new gates active."""
    # Mix payload: triggers gate 4 (NYHA III-IV) + gate 20 (seizure)
    codes = _gate_codes({
        "nyha_class": "III",
        "seizure_ctcae_grade": 3,
    })
    assert "severe_heart_failure_nyha_iii_iv" in codes
    assert "arsi_in_seizure_history_grade3" in codes


def test_healthy_payload_does_not_fire_gates_20_to_23():
    """H.G448 — Healthy payload (sin signos de gates 20-23) no dispara."""
    codes = _gate_codes({
        "ast_value": 30,
        "alt_value": 25,
        "bilirubin_total_mg_dl": 0.8,
        "platelets": 250000,
        "systolic_blood_pressure": 120,
        "diastolic_blood_pressure": 75,
        "seizure_ctcae_grade": 0,
    })
    new_gate_codes = {
        "arsi_in_seizure_history_grade3",
        "abiraterone_hepatotoxicity_grade3",
        "niraparib_in_severe_thrombocytopenia",
        "niraparib_hypertension_grade3_magnitude",
    }
    triggered_new = set(codes) & new_gate_codes
    assert not triggered_new, f"Healthy payload triggered: {triggered_new}"


# ──────────────────────────────────────────────────────────────────────
# H.G449 — DDI cross-check mapping coverage
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("gate_code", [
    "arsi_in_seizure_history_grade3",
    "abiraterone_hepatotoxicity_grade3",
    "niraparib_in_severe_thrombocytopenia",
    "niraparib_hypertension_grade3_magnitude",
])
def test_new_gates_have_ddi_categories_mapped(gate_code):
    """H.G449 — Each new gate has DDI categories declared in cross-check map."""
    from prostanet.shared.gates_ddi_cross_check import (
        _GATE_TO_RELATED_DDI_CATEGORIES,
    )
    assert gate_code in _GATE_TO_RELATED_DDI_CATEGORIES
    cats = _GATE_TO_RELATED_DDI_CATEGORIES[gate_code]
    assert isinstance(cats, tuple) and len(cats) >= 1


@pytest.mark.parametrize("gate_code", [
    "arsi_in_seizure_history_grade3",
    "abiraterone_hepatotoxicity_grade3",
    "niraparib_in_severe_thrombocytopenia",
    "niraparib_hypertension_grade3_magnitude",
])
def test_new_gates_have_oncology_drugs_mapped(gate_code):
    """H.G450 — Each new gate has oncology drugs declared for DDI cross-check."""
    from prostanet.shared.gates_ddi_cross_check import _GATE_TO_ONCOLOGY_DRUGS
    assert gate_code in _GATE_TO_ONCOLOGY_DRUGS
    drugs = _GATE_TO_ONCOLOGY_DRUGS[gate_code]
    assert isinstance(drugs, list) and len(drugs) >= 1


@pytest.mark.parametrize("gate_code,expected_summary_substring", [
    ("arsi_in_seizure_history_grade3", "Gate 20"),
    ("abiraterone_hepatotoxicity_grade3", "Gate 21"),
    ("niraparib_in_severe_thrombocytopenia", "Gate 22"),
    ("niraparib_hypertension_grade3_magnitude", "Gate 23"),
])
def test_new_gates_have_summaries_for_ui(gate_code, expected_summary_substring):
    """H.G451 — Each new gate has UI summary in cross-check (Gate XX label)."""
    from prostanet.shared.gates_ddi_cross_check import _GATE_SUMMARIES
    assert gate_code in _GATE_SUMMARIES
    assert expected_summary_substring in _GATE_SUMMARIES[gate_code]


# ──────────────────────────────────────────────────────────────────────
# H.G452 — Supporting FieldSpecs declared in advanced_support_fields
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("field_name", [
    # Gate 20
    "seizure_ctcae_grade",
    "active_seizure_disorder",
    "seizure_history_grade3_documented",
    "seizure_disorder_controlled_for_arpi",
    # Gate 21
    "ast_value",
    "alt_value",
    "bilirubin_total_mg_dl",
    "hepatotoxicity_ctcae_grade",
    "hepatotoxicity_grade3_for_abiraterone",
    "hepatic_function_recovered_for_abiraterone",
    # Gate 22
    "thrombocytopenia_ctcae_grade",
    "thrombocytopenia_grade3_for_niraparib",
    "hemorrhage_ctcae_grade",
    "platelet_count_recovered_for_niraparib",
    # Gate 23
    "systolic_blood_pressure",
    "diastolic_blood_pressure",
    "hypertension_ctcae_grade",
    "hypertension_grade3_for_niraparib",
    "hypertension_controlled_for_niraparib",
])
def test_gates_20_23_supporting_fields_declared(field_name):
    """H.G452 — All 19 supporting FieldSpecs for gates 20-23 are declared."""
    from prostanet.shared.advanced_support_fields import (
        pivotal_gate_supporting_fields,
    )
    fields = pivotal_gate_supporting_fields()
    names = {f.name for f in fields}
    assert field_name in names


# ──────────────────────────────────────────────────────────────────────
# H.G453 — Active gate codes count includes new gates
# ──────────────────────────────────────────────────────────────────────


def test_active_gate_codes_include_new_gates():
    """H.G453 — get_active_gate_codes() includes the 4 new gate codes."""
    from prostanet.shared.algorithm_version import get_active_gate_codes
    codes = get_active_gate_codes()
    new_codes = {
        "arsi_in_seizure_history_grade3",
        "abiraterone_hepatotoxicity_grade3",
        "niraparib_in_severe_thrombocytopenia",
        "niraparib_hypertension_grade3_magnitude",
    }
    assert new_codes.issubset(set(codes))


def test_total_active_gates_at_least_23():
    """H.G454 — Total active gates ≥23 (was 19, now +4 = 23)."""
    from prostanet.shared.algorithm_version import get_active_gate_codes
    codes = get_active_gate_codes()
    assert len(codes) >= 23


# ──────────────────────────────────────────────────────────────────────
# H.G455 — Smoke test E2E del bundle apply_pivotal_contraindication_gates
# ──────────────────────────────────────────────────────────────────────


def test_e2e_complex_payload_fires_all_4_new_gates():
    """H.G455 — E2E payload con triggers para los 4 gates nuevos dispara los 4."""
    payload = {
        "seizure_ctcae_grade": 3,                   # gate 20
        "ast_value": 300, "alt_value": 250,         # gate 21
        "platelets": 80000,                         # gates 22 + 15
        "systolic_blood_pressure": 200,             # gate 23
    }
    codes = _gate_codes(payload)
    assert "arsi_in_seizure_history_grade3" in codes
    assert "abiraterone_hepatotoxicity_grade3" in codes
    assert "niraparib_in_severe_thrombocytopenia" in codes
    assert "niraparib_hypertension_grade3_magnitude" in codes
