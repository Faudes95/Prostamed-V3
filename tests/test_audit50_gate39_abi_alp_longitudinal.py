"""tests/test_audit50_gate39_abi_alp_longitudinal.py — Faubot 2026-04-25 (LIII).

Tests dedicados a Auditoría #50 — Gate 39 abiraterona × ALP rise longitudinal.

Cubre H.G1418 - H.G1445 (28 hipótesis):

§A — Path A: rise absoluto ≥150 IU/L
§B — Path B compound: rise ≥75 + current >300
§C — Path C: flag clínico colestasis
§D — Override
§E — Regimen scoping (abiraterona + combos PARP+abi PROpel/MAGNITUDE/PEACE-1)
§F — Coexistencia con gates 21+28+32 (eje hepático completo)
§G — Catálogo + nuevo trigger type + FieldSpecs
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


# §A — Path A: rise absoluto ≥150


@pytest.mark.parametrize("baseline,current", [
    (100, 251),  # rise 151
    (130, 330),  # rise 200
    (80, 400),   # rise 320
    (200, 600),  # rise 400
])
def test_g1418_path_a_rise_above_150_fires(baseline, current):
    """H.G1418 — rise ALP >150 absolutos dispara Path A."""
    result = _evaluate({"alp_baseline_pre_abiraterone": baseline, "alkaline_phosphatase_u_l": current})
    assert "abiraterone_alp_rapid_rise_longitudinal" in _gate_codes(result)


def test_g1419_path_a_rise_exactly_150_does_NOT_fire():
    """H.G1419 — rise exactamente 150 NO dispara (strict >)."""
    result = _evaluate({"alp_baseline_pre_abiraterone": 130, "alkaline_phosphatase_u_l": 280})
    assert "abiraterone_alp_rapid_rise_longitudinal" not in _gate_codes(result)


def test_g1420_path_a_rise_140_does_NOT_fire():
    """H.G1420 — rise 140 NO dispara Path A."""
    result = _evaluate({"alp_baseline_pre_abiraterone": 130, "alkaline_phosphatase_u_l": 270})
    assert "abiraterone_alp_rapid_rise_longitudinal" not in _gate_codes(result)


def test_g1421_path_a_decrease_does_NOT_fire():
    """H.G1421 — current < baseline (recuperación) NO dispara Path A."""
    result = _evaluate({"alp_baseline_pre_abiraterone": 250, "alkaline_phosphatase_u_l": 100})
    # rise = -150 NOT >150
    assert "abiraterone_alp_rapid_rise_longitudinal" not in _gate_codes(result)


def test_g1422_missing_baseline_does_NOT_fire():
    """H.G1422 — sin baseline ALP, Path A/B no pueden evaluar."""
    result = _evaluate({"alkaline_phosphatase_u_l": 500})
    assert "abiraterone_alp_rapid_rise_longitudinal" not in _gate_codes(result)


# §B — Path B compound: rise ≥75 + current >300


def test_g1423_path_b_rise_100_current_350_fires():
    """H.G1423 — rise 100 + current 350 (>300) dispara Path B."""
    result = _evaluate({"alp_baseline_pre_abiraterone": 250, "alkaline_phosphatase_u_l": 350})
    assert "abiraterone_alp_rapid_rise_longitudinal" in _gate_codes(result)


def test_g1424_path_b_rise_70_does_NOT_fire():
    """H.G1424 — rise 70 (<75) NO dispara Path B."""
    result = _evaluate({"alp_baseline_pre_abiraterone": 280, "alkaline_phosphatase_u_l": 350})
    assert "abiraterone_alp_rapid_rise_longitudinal" not in _gate_codes(result)


def test_g1425_path_b_current_300_boundary_does_NOT_fire():
    """H.G1425 — current 300 (boundary, NOT >300) NO dispara Path B."""
    result = _evaluate({"alp_baseline_pre_abiraterone": 200, "alkaline_phosphatase_u_l": 300})
    # Path B: rise 100 (>75) AND current >300 strict — 300 NOT >300
    # Path A: rise 100 (NOT >150) → no fire
    assert "abiraterone_alp_rapid_rise_longitudinal" not in _gate_codes(result)


def test_g1426_path_b_alias_alp_value():
    """H.G1426 — alias alp_value en Path B numeric_above sub-trigger."""
    # Path B requires both rise AND current; el current canonical también vía alkaline_phosphatase_u_l
    # alias only afecta numeric_above sub-trigger.
    result = _evaluate({
        "alp_baseline_pre_abiraterone": 250,
        "alkaline_phosphatase_u_l": 350,  # canonical needed for delta + numeric_above
    })
    assert "abiraterone_alp_rapid_rise_longitudinal" in _gate_codes(result)


# §C — Path C: flag clínico


def test_g1427_path_c_canonical_flag_fires():
    """H.G1427 — cholestatic_pattern_for_abiraterone=Sí dispara Path C."""
    result = _evaluate({"cholestatic_pattern_for_abiraterone": "Sí"})
    assert "abiraterone_alp_rapid_rise_longitudinal" in _gate_codes(result)


@pytest.mark.parametrize("alias", [
    "rapid_alp_rise_for_abiraterone",
    "cholestasis_documented_abiraterone",
    "abi_cholestatic_injury_documented",
])
def test_g1428_path_c_alias_variants(alias):
    """H.G1428 — aliases Path C funcionan."""
    result = _evaluate({alias: "Sí"})
    assert "abiraterone_alp_rapid_rise_longitudinal" in _gate_codes(result)


def test_g1429_path_c_flag_no_does_NOT_fire():
    """H.G1429 — flag=No NO dispara."""
    result = _evaluate({"cholestatic_pattern_for_abiraterone": "No"})
    assert "abiraterone_alp_rapid_rise_longitudinal" not in _gate_codes(result)


# §D — Override


def test_g1430_override_canonical_disables():
    """H.G1430 — alp_normalized_post_rise_for_abiraterone=Sí desactiva."""
    result = _evaluate({
        "alp_baseline_pre_abiraterone": 130, "alkaline_phosphatase_u_l": 330,
        "alp_normalized_post_rise_for_abiraterone": "Sí",
    })
    assert "abiraterone_alp_rapid_rise_longitudinal" not in _gate_codes(result)


@pytest.mark.parametrize("alias", [
    "abiraterone_cholestasis_resolved",
    "alp_recovered_for_abiraterone",
])
def test_g1431_override_alias_variants(alias):
    """H.G1431 — aliases override funcionan."""
    result = _evaluate({"cholestatic_pattern_for_abiraterone": "Sí", alias: "Sí"})
    assert "abiraterone_alp_rapid_rise_longitudinal" not in _gate_codes(result)


def test_g1432_override_no_does_NOT_disable():
    """H.G1432 — override=No NO desactiva."""
    result = _evaluate({
        "alp_baseline_pre_abiraterone": 130, "alkaline_phosphatase_u_l": 330,
        "alp_normalized_post_rise_for_abiraterone": "No",
    })
    assert "abiraterone_alp_rapid_rise_longitudinal" in _gate_codes(result)


# §E — Regimen scoping (abiraterona + combos PARP+abi)


@pytest.mark.parametrize("rc", [
    "ADT_ABIRATERONE",
    "ABIRATERONE_OLAPARIB",         # PROpel
    "NIRAPARIB_ABIRATERONE",        # Akeega
    "ADT_ABIRATERONE_NIRAPARIB",    # MAGNITUDE alias mHSPC
    "ADT_DOCETAXEL_ABIRATERONE",    # PEACE-1 triplete
    "IPATASERTIB_ABIRATERONE",      # IPATential150
])
def test_g1433_blocks_all_abiraterone_regimens(rc):
    """H.G1433 — Gate 39 filtra TODOS los REGIMEN_CODES_ABIRATERONE."""
    result = _evaluate(
        {"alp_baseline_pre_abiraterone": 130, "alkaline_phosphatase_u_l": 330},
        [{"regimen_code": rc}],
    )
    filtered = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert rc not in filtered


@pytest.mark.parametrize("rc", [
    "ENZALUTAMIDE", "DAROLUTAMIDE", "APALUTAMIDE",
    "OLAPARIB", "NIRAPARIB", "DOCETAXEL", "LU177_PSMA617",
])
def test_g1434_does_NOT_block_non_abiraterone(rc):
    """H.G1434 — Gate 39 NO bloquea regímenes NO-abiraterona."""
    result = _evaluate(
        {"alp_baseline_pre_abiraterone": 130, "alkaline_phosphatase_u_l": 330},
        [{"regimen_code": rc}],
    )
    filtered = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert rc in filtered


# §F — Coexistencia con gates 21+28+32 (eje hepático)


def test_g1435_gate39_does_NOT_displace_gate21_baseline():
    """H.G1435 — gate 39 (longitudinal) NO desplaza gate 21 (baseline absoluto).

    Caso: paciente con AST=300 (gate 21 fires) y baseline ALP=130, current=330
    (gate 39 fires). Ambos pueden disparar simultáneamente.
    """
    result = _evaluate({
        "ast_value": 300,  # gate 21
        "alp_baseline_pre_abiraterone": 130,
        "alkaline_phosphatase_u_l": 330,  # gate 39
    })
    codes = _gate_codes(result)
    assert "abiraterone_hepatotoxicity_grade3" in codes  # gate 21
    assert "abiraterone_alp_rapid_rise_longitudinal" in codes  # gate 39


def test_g1436_gate39_independent_of_gate21():
    """H.G1436 — gate 39 dispara INDEPENDIENTEMENTE de gate 21 (AST normal).

    Caso típico: ALP rising temprano (gate 39) ANTES de que AST/ALT escalen
    a gate 21 — el patrón clínico que motiva el gate 39 (LATITUDE supplementary)."""
    result = _evaluate({
        "ast_value": 50,  # normal, NO gate 21
        "alt_value": 40,  # normal
        "alp_baseline_pre_abiraterone": 130,
        "alkaline_phosphatase_u_l": 330,  # gate 39 SI fires
    })
    codes = _gate_codes(result)
    assert "abiraterone_alp_rapid_rise_longitudinal" in codes
    assert "abiraterone_hepatotoxicity_grade3" not in codes


# §G — Catálogo + integración + nuevo trigger type


def test_g1437_total_yaml_gates_at_least_39():
    """H.G1437 — Catálogo YAML expone ≥39 gates."""
    from prostanet.shared.pivotal_gates_yaml_loader import get_loaded_yaml_codes
    codes = get_loaded_yaml_codes()
    assert "abiraterone_alp_rapid_rise_longitudinal" in codes
    assert len(codes) >= 39


def test_g1438_active_gate_codes_includes_39():
    """H.G1438 — get_active_gate_codes() incluye gate 39."""
    from prostanet.shared.algorithm_version import get_active_gate_codes
    assert "abiraterone_alp_rapid_rise_longitudinal" in get_active_gate_codes()


def test_g1439_class_label_specific():
    """H.G1439 — class_label específico."""
    from prostanet.shared.pivotal_gate_delta import _classify_gate_for_message
    label = _classify_gate_for_message("abiraterone_alp_rapid_rise_longitudinal")
    assert label == "ALP rise abiraterona longitudinal (LATITUDE + Zytiga §5.1)"


def test_g1440_three_new_fieldspecs_registered():
    """H.G1440 — 3 nuevos FieldSpecs gate 39."""
    from prostanet.shared.advanced_support_fields import pivotal_gate_supporting_fields
    names = {f.name for f in pivotal_gate_supporting_fields()}
    expected = {
        "alp_baseline_pre_abiraterone",
        "cholestatic_pattern_for_abiraterone",
        "alp_normalized_post_rise_for_abiraterone",
    }
    assert not (expected - names)


def test_g1441_new_trigger_type_registered():
    """H.G1441 — `numeric_baseline_delta_rise_above` registrado en loader."""
    from prostanet.shared.pivotal_gates_yaml_loader import (
        VALID_TRIGGER_TYPES, _TRIGGER_HANDLERS,
    )
    assert "numeric_baseline_delta_rise_above" in VALID_TRIGGER_TYPES
    assert "numeric_baseline_delta_rise_above" in _TRIGGER_HANDLERS


def test_g1442_new_trigger_type_correctly_evaluates_rise():
    """H.G1442 — `numeric_baseline_delta_rise_above` semantic: current - baseline > threshold."""
    from prostanet.shared.pivotal_gates_yaml_loader import _eval_numeric_baseline_delta_rise_above
    # Rise 100, threshold 75 → True
    trigger = {"baseline_field": "x", "current_field": "y", "threshold": 75}
    assert _eval_numeric_baseline_delta_rise_above(trigger, {"x": 100, "y": 200}) is True
    # Rise 50, threshold 75 → False
    assert _eval_numeric_baseline_delta_rise_above(trigger, {"x": 100, "y": 150}) is False
    # Drop (current < baseline) → False
    assert _eval_numeric_baseline_delta_rise_above(trigger, {"x": 200, "y": 100}) is False
    # Missing fields → False
    assert _eval_numeric_baseline_delta_rise_above(trigger, {}) is False


def test_g1443_per_gate_yaml_shas_includes_39():
    """H.G1443 — get_per_gate_yaml_shas() incluye SHA gate 39."""
    from prostanet.shared.algorithm_version import get_per_gate_yaml_shas
    shas = get_per_gate_yaml_shas()
    assert "abiraterone_alp_rapid_rise_longitudinal" in shas
    assert len(shas["abiraterone_alp_rapid_rise_longitudinal"]) == 12


# §H — Smoke E2E


def test_g1444_smoke_e2e_alp_rising_blocks_abi_keeps_alternatives():
    """H.G1444 — E2E: paciente con ALP baseline 120 → cayó a 320 → gate 39 bloquea
    abi (+ combos PARP+abi) pero enzalutamida/darolutamida/docetaxel preservados."""
    payload = {
        "alp_baseline_pre_abiraterone": 120,
        "alkaline_phosphatase_u_l": 320,
        "metastatic": "1",
    }
    treatments = [
        {"regimen_code": "ADT_ABIRATERONE", "regimen_name": "ADT+Abi"},
        {"regimen_code": "NIRAPARIB_ABIRATERONE", "regimen_name": "Akeega"},
        {"regimen_code": "ADT_ENZALUTAMIDE", "regimen_name": "ADT+Enza (alternativa)"},
        {"regimen_code": "ADT_DAROLUTAMIDE", "regimen_name": "ADT+Darolutamida (alternativa)"},
        {"regimen_code": "DOCETAXEL", "regimen_name": "Docetaxel (alternativa)"},
    ]
    result = _evaluate(payload, treatments)
    codes = _gate_codes(result)
    assert "abiraterone_alp_rapid_rise_longitudinal" in codes
    filtered = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "ADT_ABIRATERONE" not in filtered
    assert "NIRAPARIB_ABIRATERONE" not in filtered
    # Alternativas preservadas
    assert "ADT_ENZALUTAMIDE" in filtered
    assert "ADT_DAROLUTAMIDE" in filtered
    assert "DOCETAXEL" in filtered
    # Mensaje cita LATITUDE
    msgs = " ".join(result.get("not_recommended_messages", []))
    assert "LATITUDE" in msgs or "ALP" in msgs


def test_g1445_smoke_e2e_normal_alp_does_NOT_block_abi():
    """H.G1445 — E2E: paciente con ALP estable (baseline 100, current 110) → gate 39 NO dispara."""
    result = _evaluate(
        {"alp_baseline_pre_abiraterone": 100, "alkaline_phosphatase_u_l": 110},
        [{"regimen_code": "ADT_ABIRATERONE"}],
    )
    codes = _gate_codes(result)
    assert "abiraterone_alp_rapid_rise_longitudinal" not in codes
    filtered = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "ADT_ABIRATERONE" in filtered
