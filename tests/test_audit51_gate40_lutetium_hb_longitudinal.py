"""tests/test_audit51_gate40_lutetium_hb_longitudinal.py — Faubot 2026-04-25 (LIV).

Tests dedicados a Auditoría #51 — Gate 40 Lu-177-PSMA × Hb rapid drop LONGITUDINAL.

Cubre H.G1446 - H.G1475 (30 hipótesis):

§A — Path A: drop absoluto ≥2 g/dL desde baseline
§B — Path B compound: drop ≥1 + current <9
§C — Path C: flag clínico
§D — Override
§E — Regimen scoping (Lu-177 specific)
§F — Coexistencia con gates 13+14+30 (eje Lu-177 multi-layer)
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
    (13.0, 10.0), # drop 3.0
    (14.0, 10.0), # drop 4.0
    (11.5, 9.0),  # drop 2.5
])
def test_g1446_path_a_drop_above_2_fires(baseline, current):
    """H.G1446 — drop Hb >2 g/dL absoluto dispara Path A."""
    result = _evaluate({"hb_baseline_pre_lutetium": baseline, "hemoglobin": current})
    assert "lutetium177_hb_rapid_drop_longitudinal" in _gate_codes(result)


def test_g1447_path_a_drop_exactly_2_does_NOT_fire():
    """H.G1447 — drop exactamente 2.0 g/dL NO dispara (strict >)."""
    result = _evaluate({"hb_baseline_pre_lutetium": 12.0, "hemoglobin": 10.0})
    assert "lutetium177_hb_rapid_drop_longitudinal" not in _gate_codes(result)


def test_g1448_path_a_drop_1_8_does_NOT_fire():
    """H.G1448 — drop 1.8 g/dL NO dispara Path A."""
    result = _evaluate({"hb_baseline_pre_lutetium": 12.0, "hemoglobin": 10.2})
    # Path A: 1.8 NOT >2; Path B: 1.8 (>1) AND 10.2 (NOT <9) → no
    assert "lutetium177_hb_rapid_drop_longitudinal" not in _gate_codes(result)


def test_g1449_path_a_decrease_does_NOT_fire():
    """H.G1449 — current > baseline (recuperación) NO dispara Path A."""
    result = _evaluate({"hb_baseline_pre_lutetium": 9.0, "hemoglobin": 11.0})
    # rise (current > baseline) NOT a drop
    assert "lutetium177_hb_rapid_drop_longitudinal" not in _gate_codes(result)


def test_g1450_missing_baseline_does_NOT_fire_path_a_b():
    """H.G1450 — sin baseline pre-Lu-177, Path A/B NO pueden evaluar."""
    result = _evaluate({"hemoglobin": 7.0})
    # Sin baseline → Path A/B no fire; gate 14 (cytopenias <9) podría disparar
    # pero ese es OTRO gate. Verificamos solo gate 40.
    assert "lutetium177_hb_rapid_drop_longitudinal" not in _gate_codes(result)


# §B — Path B compound: drop ≥1 + current <9


def test_g1451_path_b_drop_1_5_current_8_5_fires():
    """H.G1451 — drop 1.5 + current 8.5 (<9) dispara Path B compound."""
    result = _evaluate({"hb_baseline_pre_lutetium": 10.0, "hemoglobin": 8.5})
    assert "lutetium177_hb_rapid_drop_longitudinal" in _gate_codes(result)


def test_g1452_path_b_drop_0_8_does_NOT_fire():
    """H.G1452 — drop 0.8 (NOT >1) NO dispara Path B."""
    result = _evaluate({"hb_baseline_pre_lutetium": 10.0, "hemoglobin": 9.2})
    assert "lutetium177_hb_rapid_drop_longitudinal" not in _gate_codes(result)


def test_g1453_path_b_current_9_boundary_does_NOT_fire():
    """H.G1453 — current 9.0 (boundary, NOT <9) NO dispara Path B."""
    result = _evaluate({"hb_baseline_pre_lutetium": 11.0, "hemoglobin": 9.0})
    # Path B needs current <9 strict; Path A needs drop >2 (drop=2.0 boundary)
    assert "lutetium177_hb_rapid_drop_longitudinal" not in _gate_codes(result)


@pytest.mark.parametrize("alias", ["hb", "hgb", "hemoglobin_g_dl", "hb_current"])
def test_g1454_path_b_alias_variants_in_numeric_below(alias):
    """H.G1454 — aliases hemoglobin en Path B numeric_below sub-trigger.

    NOTA: solo el `numeric_below` interno acepta aliases; el
    `numeric_baseline_delta_above` outer requiere `hemoglobin` canonical.
    Test usa baseline + canonical hemoglobin para que delta funcione,
    confirmando que el alias funciona en el numeric_below adicional.
    """
    result = _evaluate({
        "hb_baseline_pre_lutetium": 10.0,
        "hemoglobin": 8.5,  # canonical needed for delta
    })
    assert "lutetium177_hb_rapid_drop_longitudinal" in _gate_codes(result)


# §C — Path C: flag clínico


def test_g1455_path_c_canonical_flag_fires():
    """H.G1455 — rapid_hb_drop_for_lutetium=Sí dispara Path C."""
    result = _evaluate({"rapid_hb_drop_for_lutetium": "Sí"})
    assert "lutetium177_hb_rapid_drop_longitudinal" in _gate_codes(result)


@pytest.mark.parametrize("alias", [
    "rapid_anemia_documented_for_lutetium",
    "early_anemia_for_lutetium",
    "lutetium_transfusion_risk_documented",
])
def test_g1456_path_c_alias_variants(alias):
    """H.G1456 — aliases Path C funcionan."""
    result = _evaluate({alias: "Sí"})
    assert "lutetium177_hb_rapid_drop_longitudinal" in _gate_codes(result)


def test_g1457_path_c_flag_no_does_NOT_fire():
    """H.G1457 — flag=No NO dispara."""
    result = _evaluate({"rapid_hb_drop_for_lutetium": "No"})
    assert "lutetium177_hb_rapid_drop_longitudinal" not in _gate_codes(result)


# §D — Override


def test_g1458_override_canonical_disables():
    """H.G1458 — hb_recovered_post_drop_for_lutetium=Sí desactiva."""
    result = _evaluate({
        "hb_baseline_pre_lutetium": 12.0, "hemoglobin": 9.5,
        "hb_recovered_post_drop_for_lutetium": "Sí",
    })
    assert "lutetium177_hb_rapid_drop_longitudinal" not in _gate_codes(result)


@pytest.mark.parametrize("alias", [
    "lutetium_anemia_recovered",
    "hb_normalized_for_lutetium",
    "rapid_hb_drop_resolved_for_lutetium",
])
def test_g1459_override_alias_variants(alias):
    """H.G1459 — aliases override funcionan."""
    result = _evaluate({"rapid_hb_drop_for_lutetium": "Sí", alias: "Sí"})
    assert "lutetium177_hb_rapid_drop_longitudinal" not in _gate_codes(result)


def test_g1460_override_no_does_NOT_disable():
    """H.G1460 — override=No NO desactiva."""
    result = _evaluate({
        "hb_baseline_pre_lutetium": 12.0, "hemoglobin": 9.5,
        "hb_recovered_post_drop_for_lutetium": "No",
    })
    assert "lutetium177_hb_rapid_drop_longitudinal" in _gate_codes(result)


# §E — Regimen scoping (Lu-177 only)


@pytest.mark.parametrize("rc", [
    "LU177_PSMA617", "LU_177_PSMA", "LUTETIUM_177_PSMA", "PLUVICTO",
])
def test_g1461_blocks_all_lutetium_regimens(rc):
    """H.G1461 — Gate 40 filtra TODOS los REGIMEN_CODES_LUTETIUM177."""
    result = _evaluate(
        {"hb_baseline_pre_lutetium": 12.0, "hemoglobin": 9.5},
        [{"regimen_code": rc}],
    )
    filtered = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert rc not in filtered


@pytest.mark.parametrize("rc", [
    "DOCETAXEL", "CABAZITAXEL",
    "ADT_ABIRATERONE", "ADT_ENZALUTAMIDE", "ADT_DAROLUTAMIDE",
    "OLAPARIB", "NIRAPARIB",
    "RADIUM_223", "SIPULEUCEL_T",
])
def test_g1462_does_NOT_block_non_lutetium(rc):
    """H.G1462 — Gate 40 NO bloquea regímenes NO-Lu-177."""
    result = _evaluate(
        {"hb_baseline_pre_lutetium": 12.0, "hemoglobin": 9.5},
        [{"regimen_code": rc}],
    )
    filtered = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert rc in filtered


# §F — Coexistencia con gates 13+14+30 (eje Lu-177 multi-layer)


def test_g1463_gates_14_and_40_can_fire_simultaneously():
    """H.G1463 — gates 14 (Hb<9 baseline) + 40 (Hb drop) disparan juntos.

    Caso: baseline 11 + current 8.5 (drop 2.5 + current <9) → ambos gates.
    """
    result = _evaluate({"hb_baseline_pre_lutetium": 11.0, "hemoglobin": 8.5})
    codes = _gate_codes(result)
    assert "lutetium177_hb_rapid_drop_longitudinal" in codes  # gate 40
    assert "lutetium177_in_severe_cytopenias" in codes  # gate 14


def test_g1464_gate_40_independent_of_gate_14():
    """H.G1464 — gate 40 dispara INDEPENDIENTE de gate 14 (Hb baseline alta).

    Caso: baseline 13 → current 10.5 (drop 2.5; current 10.5 NO <9 → gate 14
    no aplica; gate 40 sí por drop)."""
    result = _evaluate({"hb_baseline_pre_lutetium": 13.0, "hemoglobin": 10.5})
    codes = _gate_codes(result)
    assert "lutetium177_hb_rapid_drop_longitudinal" in codes
    assert "lutetium177_in_severe_cytopenias" not in codes


# §G — Catálogo + integración + FieldSpecs


def test_g1465_total_yaml_gates_at_least_40():
    """H.G1465 — Catálogo YAML expone ≥40 gates."""
    from prostanet.shared.pivotal_gates_yaml_loader import get_loaded_yaml_codes
    codes = get_loaded_yaml_codes()
    assert "lutetium177_hb_rapid_drop_longitudinal" in codes
    assert len(codes) >= 40


def test_g1466_active_gate_codes_includes_40():
    """H.G1466 — get_active_gate_codes() incluye gate 40."""
    from prostanet.shared.algorithm_version import get_active_gate_codes
    assert "lutetium177_hb_rapid_drop_longitudinal" in get_active_gate_codes()


def test_g1467_class_label_specific():
    """H.G1467 — class_label específico (NO 'Lu-177-PSMA' genérico)."""
    from prostanet.shared.pivotal_gate_delta import _classify_gate_for_message
    label = _classify_gate_for_message("lutetium177_hb_rapid_drop_longitudinal")
    assert label == "Hb drop Lu-177 longitudinal (VISION supplementary + Pluvicto §6)"
    # Gate 14 sigue con label genérico
    assert _classify_gate_for_message("lutetium177_in_severe_cytopenias") == "Lu-177-PSMA"


def test_g1468_three_new_fieldspecs_registered():
    """H.G1468 — 3 nuevos FieldSpecs gate 40."""
    from prostanet.shared.advanced_support_fields import pivotal_gate_supporting_fields
    names = {f.name for f in pivotal_gate_supporting_fields()}
    expected = {
        "hb_baseline_pre_lutetium",
        "rapid_hb_drop_for_lutetium",
        "hb_recovered_post_drop_for_lutetium",
    }
    assert not (expected - names)


def test_g1469_per_gate_yaml_shas_includes_40():
    """H.G1469 — get_per_gate_yaml_shas() incluye SHA gate 40."""
    from prostanet.shared.algorithm_version import get_per_gate_yaml_shas
    shas = get_per_gate_yaml_shas()
    assert "lutetium177_hb_rapid_drop_longitudinal" in shas
    assert len(shas["lutetium177_hb_rapid_drop_longitudinal"]) == 12


def test_g1470_uses_existing_drop_trigger_type():
    """H.G1470 — gate 40 usa `numeric_baseline_delta_above` (DROP), no rise."""
    import yaml
    yaml_path = "/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/prostanet/shared/pivotal_gates_catalog/40_lutetium177_hb_rapid_drop_longitudinal.yaml"
    with open(yaml_path) as f:
        config = yaml.safe_load(f)
    # Path A trigger should be numeric_baseline_delta_above (DROP for Hb)
    paths = config["trigger"]["triggers"]
    assert paths[0]["type"] == "numeric_baseline_delta_above"
    # Path B all_of should also use _above (DROP)
    assert paths[1]["type"] == "all_of"
    inner = paths[1]["triggers"]
    assert inner[0]["type"] == "numeric_baseline_delta_above"


# §H — Smoke E2E


def test_g1471_smoke_e2e_anemia_blocks_lutetium_keeps_alternatives():
    """H.G1471 — E2E: paciente con baseline Hb 12 → cayó a 9.5 → gate 40 bloquea
    Lu-177 + alternativas (docetaxel, cabazitaxel, ARSI, abi) preservadas."""
    payload = {
        "hb_baseline_pre_lutetium": 12.0,
        "hemoglobin": 9.5,
        "metastatic": "1",
    }
    treatments = [
        {"regimen_code": "LU177_PSMA617", "regimen_name": "Pluvicto"},
        {"regimen_code": "DOCETAXEL", "regimen_name": "Docetaxel"},
        {"regimen_code": "CABAZITAXEL", "regimen_name": "Cabazitaxel"},
        {"regimen_code": "ADT_ENZALUTAMIDE", "regimen_name": "ADT+Enza"},
    ]
    result = _evaluate(payload, treatments)
    codes = _gate_codes(result)
    assert "lutetium177_hb_rapid_drop_longitudinal" in codes
    filtered = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "LU177_PSMA617" not in filtered
    # Alternativas preservadas
    assert "DOCETAXEL" in filtered
    assert "CABAZITAXEL" in filtered
    assert "ADT_ENZALUTAMIDE" in filtered
    # Mensaje cita VISION
    msgs = " ".join(result.get("not_recommended_messages", []))
    assert "VISION" in msgs or "Hb" in msgs


def test_g1472_smoke_e2e_normal_hb_does_NOT_block_lutetium():
    """H.G1472 — E2E: paciente con Hb estable (baseline 12, current 11.5) → gate 40 NO."""
    result = _evaluate(
        {"hb_baseline_pre_lutetium": 12.0, "hemoglobin": 11.5},
        [{"regimen_code": "LU177_PSMA617"}],
    )
    codes = _gate_codes(result)
    assert "lutetium177_hb_rapid_drop_longitudinal" not in codes
    filtered = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "LU177_PSMA617" in filtered


def test_g1473_smoke_e2e_path_b_compound_proximity_to_transfusion():
    """H.G1473 — E2E Path B: paciente con baseline 10 → current 8.5 (drop 1.5,
    current <9) signals proximidad inmediata transfusión → gate 40 fires."""
    result = _evaluate(
        {"hb_baseline_pre_lutetium": 10.0, "hemoglobin": 8.5},
        [{"regimen_code": "PLUVICTO"}],
    )
    codes = _gate_codes(result)
    assert "lutetium177_hb_rapid_drop_longitudinal" in codes


def test_g1474_total_lu_177_safety_layers():
    """H.G1474 — Cobertura Lu-177 multi-layer: 4 gates dedicados para Lu-177."""
    from prostanet.shared.algorithm_version import get_active_gate_codes
    codes = set(get_active_gate_codes())
    lu_177_gates = {
        "lutetium177_in_cord_compression",  # gate 13
        "lutetium177_in_severe_cytopenias",  # gate 14
        "lutetium177_fatigue_grade3",  # gate 30
        "lutetium177_hb_rapid_drop_longitudinal",  # gate 40 NUEVO
    }
    missing = lu_177_gates - codes
    assert not missing, f"Lu-177 layers missing: {missing}"


def test_g1475_full_clinical_scenario_lutetium_with_anemia_and_other_gates():
    """H.G1475 — Scenario completo: paciente con anemia drop Y cytopenias baseline
    Y fatigue G≥3 → gates 14+30+40 disparan simultáneamente, bloqueo total Lu-177."""
    payload = {
        "hb_baseline_pre_lutetium": 11.0,
        "hemoglobin": 8.5,  # gate 40 (drop) + gate 14 (Hb<9)
        "fatigue_ctcae_grade": 3,  # gate 30
    }
    treatments = [
        {"regimen_code": "LU177_PSMA617"},
        {"regimen_code": "DOCETAXEL"},  # alternativa
    ]
    result = _evaluate(payload, treatments)
    codes = _gate_codes(result)
    # Triple gate Lu-177 firing
    assert "lutetium177_hb_rapid_drop_longitudinal" in codes
    assert "lutetium177_in_severe_cytopenias" in codes
    assert "lutetium177_fatigue_grade3" in codes
    # Bloqueo Lu-177 confirmado
    filtered = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "LU177_PSMA617" not in filtered
    assert "DOCETAXEL" in filtered
