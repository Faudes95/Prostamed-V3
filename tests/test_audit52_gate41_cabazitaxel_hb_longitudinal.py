"""tests/test_audit52_gate41_cabazitaxel_hb_longitudinal.py — Faubot 2026-04-25 (LV).

Tests dedicados a Auditoría #52 — Gate 41 cabazitaxel × Hb rapid drop LONGITUDINAL.

Cubre H.G1476 - H.G1500 (25 hipótesis):

§A — Path A: drop absoluto ≥2 g/dL
§B — Path B compound: drop ≥1 + current <9
§C — Path C: flag clínico
§D — Override
§E — Regimen scoping (cabazitaxel-specific, NO docetaxel ni taxanos generales)
§F — Coexistencia con gates 40 (Lu-177 Hb) — gates longitudinales pueden coexistir
§G — Catálogo + integración + FieldSpecs
§H — Smoke E2E
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest


def _evaluate(payload, treatments=None):
    from prostanet.shared.pivotal_contraindication_gates import apply_pivotal_contraindication_gates
    return apply_pivotal_contraindication_gates(payload, treatments or [])


def _gate_codes(result):
    return [g["code"] for g in result.get("gates_triggered", [])]


# §A — Path A: drop absoluto ≥2 g/dL


@pytest.mark.parametrize("baseline,current", [
    (12.0, 9.5),  # drop 2.5
    (13.0, 10.5), # drop 2.5
    (14.0, 10.0), # drop 4.0
    (11.5, 9.0),  # drop 2.5
])
def test_g1476_path_a_drop_above_2_fires(baseline, current):
    """H.G1476 — drop Hb >2 g/dL absoluto dispara Path A."""
    result = _evaluate({"hb_baseline_pre_cabazitaxel": baseline, "hemoglobin": current})
    assert "cabazitaxel_hb_rapid_drop_longitudinal" in _gate_codes(result)


def test_g1477_path_a_drop_exactly_2_does_NOT_fire():
    """H.G1477 — drop exactamente 2.0 NO dispara (strict >)."""
    result = _evaluate({"hb_baseline_pre_cabazitaxel": 12.0, "hemoglobin": 10.0})
    assert "cabazitaxel_hb_rapid_drop_longitudinal" not in _gate_codes(result)


def test_g1478_path_a_decrease_does_NOT_fire():
    """H.G1478 — current > baseline (recuperación) NO dispara Path A."""
    result = _evaluate({"hb_baseline_pre_cabazitaxel": 9.0, "hemoglobin": 11.0})
    assert "cabazitaxel_hb_rapid_drop_longitudinal" not in _gate_codes(result)


def test_g1479_missing_baseline_does_NOT_fire():
    """H.G1479 — sin baseline pre-cabazitaxel, Path A/B NO pueden evaluar."""
    result = _evaluate({"hemoglobin": 7.0})
    assert "cabazitaxel_hb_rapid_drop_longitudinal" not in _gate_codes(result)


# §B — Path B compound: drop ≥1 + current <9


def test_g1480_path_b_drop_1_5_current_8_5_fires():
    """H.G1480 — drop 1.5 + current 8.5 (<9) dispara Path B compound."""
    result = _evaluate({"hb_baseline_pre_cabazitaxel": 10.0, "hemoglobin": 8.5})
    assert "cabazitaxel_hb_rapid_drop_longitudinal" in _gate_codes(result)


def test_g1481_path_b_drop_0_8_does_NOT_fire():
    """H.G1481 — drop 0.8 (NOT >1) NO dispara Path B."""
    result = _evaluate({"hb_baseline_pre_cabazitaxel": 10.0, "hemoglobin": 9.2})
    assert "cabazitaxel_hb_rapid_drop_longitudinal" not in _gate_codes(result)


def test_g1482_path_b_current_9_boundary_does_NOT_fire():
    """H.G1482 — current 9.0 (boundary, NOT <9) NO dispara Path B."""
    result = _evaluate({"hb_baseline_pre_cabazitaxel": 11.0, "hemoglobin": 9.0})
    assert "cabazitaxel_hb_rapid_drop_longitudinal" not in _gate_codes(result)


# §C — Path C: flag clínico


def test_g1483_path_c_canonical_flag_fires():
    """H.G1483 — rapid_hb_drop_for_cabazitaxel=Sí dispara Path C."""
    result = _evaluate({"rapid_hb_drop_for_cabazitaxel": "Sí"})
    assert "cabazitaxel_hb_rapid_drop_longitudinal" in _gate_codes(result)


@pytest.mark.parametrize("alias", [
    "rapid_anemia_documented_for_cabazitaxel",
    "early_anemia_for_cabazitaxel",
    "cabazitaxel_transfusion_risk_documented",
])
def test_g1484_path_c_alias_variants(alias):
    """H.G1484 — aliases Path C funcionan."""
    result = _evaluate({alias: "Sí"})
    assert "cabazitaxel_hb_rapid_drop_longitudinal" in _gate_codes(result)


def test_g1485_path_c_flag_no_does_NOT_fire():
    """H.G1485 — flag=No NO dispara."""
    result = _evaluate({"rapid_hb_drop_for_cabazitaxel": "No"})
    assert "cabazitaxel_hb_rapid_drop_longitudinal" not in _gate_codes(result)


# §D — Override


def test_g1486_override_canonical_disables():
    """H.G1486 — hb_recovered_post_drop_for_cabazitaxel=Sí desactiva."""
    result = _evaluate({
        "hb_baseline_pre_cabazitaxel": 12.0, "hemoglobin": 9.5,
        "hb_recovered_post_drop_for_cabazitaxel": "Sí",
    })
    assert "cabazitaxel_hb_rapid_drop_longitudinal" not in _gate_codes(result)


@pytest.mark.parametrize("alias", [
    "cabazitaxel_anemia_recovered",
    "hb_normalized_for_cabazitaxel",
    "rapid_hb_drop_resolved_for_cabazitaxel",
])
def test_g1487_override_alias_variants(alias):
    """H.G1487 — aliases override funcionan."""
    result = _evaluate({"rapid_hb_drop_for_cabazitaxel": "Sí", alias: "Sí"})
    assert "cabazitaxel_hb_rapid_drop_longitudinal" not in _gate_codes(result)


def test_g1488_override_no_does_NOT_disable():
    """H.G1488 — override=No NO desactiva."""
    result = _evaluate({
        "hb_baseline_pre_cabazitaxel": 12.0, "hemoglobin": 9.5,
        "hb_recovered_post_drop_for_cabazitaxel": "No",
    })
    assert "cabazitaxel_hb_rapid_drop_longitudinal" in _gate_codes(result)


# §E — Regimen scoping (cabazitaxel-specific)


def test_g1489_blocks_cabazitaxel():
    """H.G1489 — Gate 41 filtra CABAZITAXEL."""
    result = _evaluate(
        {"hb_baseline_pre_cabazitaxel": 12.0, "hemoglobin": 9.5},
        [{"regimen_code": "CABAZITAXEL"}],
    )
    filtered = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "CABAZITAXEL" not in filtered


@pytest.mark.parametrize("rc", [
    "DOCETAXEL", "ADT_DOCETAXEL",
    "ADT_DOCETAXEL_ABIRATERONE",  # PEACE-1 triplete
    "ADT_DOCETAXEL_DAROLUTAMIDE",  # ARASENS triplete
    "ADT_ABIRATERONE", "ADT_ENZALUTAMIDE", "ADT_DAROLUTAMIDE",
    "OLAPARIB", "NIRAPARIB",
    "LU177_PSMA617",
])
def test_g1490_does_NOT_block_non_cabazitaxel(rc):
    """H.G1490 — Gate 41 NO bloquea regímenes NO-cabazitaxel.

    NOTA: gate 34 cubre docetaxel ANC longitudinal específicamente;
    gate 40 cubre Lu-177 Hb longitudinal. Gate 41 es CABAZITAXEL-specific
    y NO debe interferir con scope de gates 34/40.
    """
    result = _evaluate(
        {"hb_baseline_pre_cabazitaxel": 12.0, "hemoglobin": 9.5},
        [{"regimen_code": rc}],
    )
    filtered = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert rc in filtered


# §F — Coexistencia con gate 40 (Lu-177 Hb longitudinal)


def test_g1491_gates_40_and_41_can_coexist_independent_baselines():
    """H.G1491 — gates 40 (Lu-177) + 41 (cabazitaxel) coexisten con
    baselines INDEPENDIENTES (cada uno su propio baseline pre-fármaco)."""
    result = _evaluate({
        "hb_baseline_pre_cabazitaxel": 12.0,
        "hb_baseline_pre_lutetium": 12.0,
        "hemoglobin": 9.0,  # drop 3 desde ambos baselines
    })
    codes = _gate_codes(result)
    assert "cabazitaxel_hb_rapid_drop_longitudinal" in codes
    assert "lutetium177_hb_rapid_drop_longitudinal" in codes


def test_g1492_gate_41_independent_of_gate_40():
    """H.G1492 — gate 41 dispara INDEPENDIENTE de gate 40 cuando solo hay
    baseline pre-cabazitaxel (no Lu-177 baseline)."""
    result = _evaluate({"hb_baseline_pre_cabazitaxel": 12.0, "hemoglobin": 9.5})
    codes = _gate_codes(result)
    assert "cabazitaxel_hb_rapid_drop_longitudinal" in codes
    assert "lutetium177_hb_rapid_drop_longitudinal" not in codes


# §G — Catálogo + integración + FieldSpecs


def test_g1493_total_yaml_gates_at_least_41():
    """H.G1493 — Catálogo YAML expone ≥41 gates."""
    from prostanet.shared.pivotal_gates_yaml_loader import get_loaded_yaml_codes
    codes = get_loaded_yaml_codes()
    assert "cabazitaxel_hb_rapid_drop_longitudinal" in codes
    assert len(codes) >= 41


def test_g1494_active_gate_codes_includes_41():
    """H.G1494 — get_active_gate_codes() incluye gate 41."""
    from prostanet.shared.algorithm_version import get_active_gate_codes
    assert "cabazitaxel_hb_rapid_drop_longitudinal" in get_active_gate_codes()


def test_g1495_class_label_specific():
    """H.G1495 — class_label específico."""
    from prostanet.shared.pivotal_gate_delta import _classify_gate_for_message
    label = _classify_gate_for_message("cabazitaxel_hb_rapid_drop_longitudinal")
    assert label == "Hb drop cabazitaxel longitudinal (TROPIC + CARD + Jevtana §6)"


def test_g1496_three_new_fieldspecs_registered():
    """H.G1496 — 3 nuevos FieldSpecs gate 41."""
    from prostanet.shared.advanced_support_fields import pivotal_gate_supporting_fields
    names = {f.name for f in pivotal_gate_supporting_fields()}
    expected = {
        "hb_baseline_pre_cabazitaxel",
        "rapid_hb_drop_for_cabazitaxel",
        "hb_recovered_post_drop_for_cabazitaxel",
    }
    assert not (expected - names)


def test_g1497_regimen_codes_cabazitaxel_exports():
    """H.G1497 — REGIMEN_CODES_CABAZITAXEL + KEYWORDS_CABAZITAXEL exportan."""
    from prostanet.shared.pivotal_contraindication_gates import (
        REGIMEN_CODES_CABAZITAXEL, KEYWORDS_CABAZITAXEL,
    )
    assert "CABAZITAXEL" in REGIMEN_CODES_CABAZITAXEL
    # NO debe incluir docetaxel ni triplete combos
    assert "DOCETAXEL" not in REGIMEN_CODES_CABAZITAXEL
    assert "ADT_DOCETAXEL_ABIRATERONE" not in REGIMEN_CODES_CABAZITAXEL
    assert "cabazitaxel" in KEYWORDS_CABAZITAXEL
    assert "jevtana" in KEYWORDS_CABAZITAXEL


# §H — Smoke E2E


def test_g1498_smoke_e2e_anemia_blocks_cabazitaxel_keeps_alternatives():
    """H.G1498 — E2E: paciente con baseline Hb 12 → cayó a 9.5 → gate 41 bloquea
    cabazitaxel; docetaxel + ARSI + Lu-177 preservados."""
    payload = {
        "hb_baseline_pre_cabazitaxel": 12.0,
        "hemoglobin": 9.5,
        "metastatic": "1",
    }
    treatments = [
        {"regimen_code": "CABAZITAXEL", "regimen_name": "Cabazitaxel"},
        {"regimen_code": "DOCETAXEL", "regimen_name": "Docetaxel"},
        {"regimen_code": "ADT_ENZALUTAMIDE", "regimen_name": "ADT+Enza"},
        {"regimen_code": "LU177_PSMA617", "regimen_name": "Pluvicto"},
        {"regimen_code": "OLAPARIB", "regimen_name": "Olaparib (HRR+)"},
    ]
    result = _evaluate(payload, treatments)
    codes = _gate_codes(result)
    assert "cabazitaxel_hb_rapid_drop_longitudinal" in codes
    filtered = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "CABAZITAXEL" not in filtered
    # Alternativas preservadas
    assert "DOCETAXEL" in filtered
    assert "ADT_ENZALUTAMIDE" in filtered
    assert "LU177_PSMA617" in filtered
    assert "OLAPARIB" in filtered
    msgs = " ".join(result.get("not_recommended_messages", []))
    assert "TROPIC" in msgs or "CARD" in msgs or "cabazitaxel" in msgs.lower()


def test_g1499_smoke_e2e_normal_hb_does_NOT_block_cabazitaxel():
    """H.G1499 — E2E: paciente con Hb estable (baseline 12, current 11.8) → gate 41 NO."""
    result = _evaluate(
        {"hb_baseline_pre_cabazitaxel": 12.0, "hemoglobin": 11.8},
        [{"regimen_code": "CABAZITAXEL"}],
    )
    codes = _gate_codes(result)
    assert "cabazitaxel_hb_rapid_drop_longitudinal" not in codes
    filtered = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "CABAZITAXEL" in filtered


def test_g1500_total_longitudinal_gates_count():
    """H.G1500 — Catálogo expone 6 gates longitudinales (33+34+39+40+41+19 parcial)."""
    from prostanet.shared.algorithm_version import get_active_gate_codes
    codes = set(get_active_gate_codes())
    longitudinal_gates = {
        "niraparib_thrombocytopenia_rapid_drop",  # gate 33
        "docetaxel_neutropenia_rapid_drop",  # gate 34
        "abiraterone_alp_rapid_rise_longitudinal",  # gate 39 (RISE)
        "lutetium177_hb_rapid_drop_longitudinal",  # gate 40
        "cabazitaxel_hb_rapid_drop_longitudinal",  # gate 41 NUEVO
    }
    missing = longitudinal_gates - codes
    assert not missing, f"Longitudinal gates missing: {missing}"
    # Total: 5 gates puramente longitudinales (más gate 19 ARSI cognitive con
    # MMSE/MoCA delta como path opcional — total 6 gates con dimensión longitudinal)
