"""tests/test_audit56_gate35_arsi_abi_vte_risk.py — Faubot 2026-04-25 (XLIX).

Tests dedicados a Auditoría #56 — Gate 35 ARSI/abiraterona × riesgo TEV elevado.

Cubre H.G1326 - H.G1350 (25 hipótesis).
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest


def _evaluate(payload, treatments=None):
    from prostanet.shared.pivotal_contraindication_gates import apply_pivotal_contraindication_gates
    return apply_pivotal_contraindication_gates(payload, treatments or [])


def _gate_codes(result):
    return [g["code"] for g in result.get("gates_triggered", [])]


# §A — Path A: history TEV


def test_g1326_path_a_history_vte_canonical():
    """H.G1326 — history_vte_documented=Sí dispara Path A."""
    result = _evaluate({"history_vte_documented": "Sí"})
    assert "arsi_abiraterone_vte_risk_high" in _gate_codes(result)


@pytest.mark.parametrize("alias", [
    "prior_vte_event", "history_pulmonary_embolism",
    "history_dvt", "vte_history_documented",
])
def test_g1327_path_a_alias_variants(alias):
    """H.G1327 — aliases Path A funcionan."""
    result = _evaluate({alias: "Sí"})
    assert "arsi_abiraterone_vte_risk_high" in _gate_codes(result)


# §B — Path B: edad ≥75 + IMC ≥30


def test_g1328_path_b_age_80_bmi_32_fires():
    """H.G1328 — edad 80 + IMC 32 dispara Path B."""
    result = _evaluate({"age": 80, "bmi": 32})
    assert "arsi_abiraterone_vte_risk_high" in _gate_codes(result)


def test_g1329_path_b_age_74_bmi_35_does_NOT_fire():
    """H.G1329 — edad 74 (NO ≥75) + IMC 35 NO dispara."""
    result = _evaluate({"age": 74, "bmi": 35})
    assert "arsi_abiraterone_vte_risk_high" not in _gate_codes(result)


def test_g1330_path_b_age_80_bmi_28_does_NOT_fire():
    """H.G1330 — edad 80 + IMC 28 (NO ≥30) NO dispara."""
    result = _evaluate({"age": 80, "bmi": 28})
    assert "arsi_abiraterone_vte_risk_high" not in _gate_codes(result)


def test_g1331_path_b_alias_imc():
    """H.G1331 — alias imc + edad funciona."""
    result = _evaluate({"edad": 80, "imc": 33})
    assert "arsi_abiraterone_vte_risk_high" in _gate_codes(result)


# §C — Path C: D-dimer >1000


@pytest.mark.parametrize("d_dimer", [1001, 2000, 5000])
def test_g1332_path_c_d_dimer_above_1000_fires(d_dimer):
    """H.G1332 — D-dímero >1000 dispara Path C."""
    result = _evaluate({"d_dimer_ng_ml": d_dimer})
    assert "arsi_abiraterone_vte_risk_high" in _gate_codes(result)


@pytest.mark.parametrize("d_dimer", [500, 800, 1000])
def test_g1333_path_c_d_dimer_below_or_equal_1000_does_NOT_fire(d_dimer):
    """H.G1333 — D-dímero ≤1000 NO dispara Path C."""
    result = _evaluate({"d_dimer_ng_ml": d_dimer})
    assert "arsi_abiraterone_vte_risk_high" not in _gate_codes(result)


@pytest.mark.parametrize("alias", ["d_dimer", "ddimer", "dimer_d"])
def test_g1334_path_c_alias_variants(alias):
    """H.G1334 — aliases D-dimer funcionan."""
    result = _evaluate({alias: 1500})
    assert "arsi_abiraterone_vte_risk_high" in _gate_codes(result)


# §D — Path D: flag explícito


def test_g1335_path_d_canonical_flag_fires():
    """H.G1335 — vte_high_risk_for_arsi_documented=Sí dispara Path D."""
    result = _evaluate({"vte_high_risk_for_arsi_documented": "Sí"})
    assert "arsi_abiraterone_vte_risk_high" in _gate_codes(result)


@pytest.mark.parametrize("alias", [
    "khorana_score_high", "improve_score_high", "thromboembolic_risk_documented",
])
def test_g1336_path_d_alias_variants(alias):
    """H.G1336 — aliases Path D funcionan."""
    result = _evaluate({alias: "Sí"})
    assert "arsi_abiraterone_vte_risk_high" in _gate_codes(result)


# §E — Override


def test_g1337_override_canonical_disables():
    """H.G1337 — anticoagulation_therapeutic_active=Sí desactiva."""
    result = _evaluate({
        "history_vte_documented": "Sí",
        "anticoagulation_therapeutic_active": "Sí",
    })
    assert "arsi_abiraterone_vte_risk_high" not in _gate_codes(result)


@pytest.mark.parametrize("alias", [
    "therapeutic_anticoagulation_documented",
    "doac_therapeutic_active",
    "warfarin_therapeutic_inr_documented",
])
def test_g1338_override_alias_variants(alias):
    """H.G1338 — aliases override funcionan."""
    result = _evaluate({
        "history_vte_documented": "Sí",
        alias: "Sí",
    })
    assert "arsi_abiraterone_vte_risk_high" not in _gate_codes(result)


def test_g1339_override_no_does_NOT_disable():
    """H.G1339 — override=No NO desactiva."""
    result = _evaluate({
        "history_vte_documented": "Sí",
        "anticoagulation_therapeutic_active": "No",
    })
    assert "arsi_abiraterone_vte_risk_high" in _gate_codes(result)


# §F — Regimen scoping (ARSI ∪ Abiraterone)


@pytest.mark.parametrize("rc", [
    "ENZALUTAMIDE", "ADT_ENZALUTAMIDE",
    "APALUTAMIDE", "ADT_APALUTAMIDE",
    "DAROLUTAMIDE", "ADT_DAROLUTAMIDE",
    "ADT_ABIRATERONE",
    "NIRAPARIB_ABIRATERONE",  # Akeega combo
    "ABIRATERONE_OLAPARIB",   # PROpel combo
])
def test_g1340_blocks_arsi_and_abiraterone_regimens(rc):
    """H.G1340 — Gate 35 filtra ARSIs + abiraterona + combos."""
    result = _evaluate(
        {"history_vte_documented": "Sí"},
        [{"regimen_code": rc}],
    )
    filtered = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert rc not in filtered


@pytest.mark.parametrize("rc", [
    "DOCETAXEL", "CABAZITAXEL", "OLAPARIB", "NIRAPARIB",
    "LU177_PSMA617", "RADIUM_223", "SIPULEUCEL_T",
])
def test_g1341_does_NOT_block_non_arsi_non_abi(rc):
    """H.G1341 — NO bloquea regímenes NO-ARSI NO-abiraterona."""
    result = _evaluate(
        {"history_vte_documented": "Sí"},
        [{"regimen_code": rc}],
    )
    filtered = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert rc in filtered


# §G — Catálogo + integración


def test_g1342_active_gate_codes_includes_35():
    """H.G1342 — get_active_gate_codes() incluye gate 35."""
    from prostanet.shared.algorithm_version import get_active_gate_codes
    assert "arsi_abiraterone_vte_risk_high" in get_active_gate_codes()


def test_g1343_class_label_specific():
    """H.G1343 — class_label específico."""
    from prostanet.shared.pivotal_gate_delta import _classify_gate_for_message
    label = _classify_gate_for_message("arsi_abiraterone_vte_risk_high")
    assert label == "TEV ARSI/abiraterona (COU-AA-302 + LATITUDE + Klil-Drori 2019)"


def test_g1344_five_new_fieldspecs_registered():
    """H.G1344 — 5 nuevos FieldSpecs gate 35 registrados."""
    from prostanet.shared.advanced_support_fields import pivotal_gate_supporting_fields
    names = {f.name for f in pivotal_gate_supporting_fields()}
    expected = {
        "history_vte_documented", "bmi", "d_dimer_ng_ml",
        "vte_high_risk_for_arsi_documented", "anticoagulation_therapeutic_active",
    }
    assert not (expected - names)


# §H — Smoke E2E


def test_g1345_smoke_e2e_high_vte_risk_patient():
    """H.G1345 — E2E: paciente alto riesgo TEV con opciones ARSI vs alternativas."""
    payload = {
        "history_vte_documented": "Sí",
        "age": 78, "bmi": 31,
        "metastatic": "1",
    }
    treatments = [
        {"regimen_code": "ADT_ENZALUTAMIDE", "regimen_name": "ADT+Enza"},
        {"regimen_code": "ADT_ABIRATERONE", "regimen_name": "ADT+Abi"},
        {"regimen_code": "DOCETAXEL", "regimen_name": "Docetaxel (alternativa)"},
        {"regimen_code": "LU177_PSMA617", "regimen_name": "Pluvicto (alternativa)"},
    ]
    result = _evaluate(payload, treatments)
    codes = _gate_codes(result)
    assert "arsi_abiraterone_vte_risk_high" in codes
    filtered = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "ADT_ENZALUTAMIDE" not in filtered
    assert "ADT_ABIRATERONE" not in filtered
    # Alternativas preservadas
    assert "DOCETAXEL" in filtered
    assert "LU177_PSMA617" in filtered
    msgs = " ".join(result.get("not_recommended_messages", []))
    assert "TEV" in msgs or "VTE" in msgs.upper() or "trombo" in msgs.lower()


# §I — Edge cases / boundary


def test_g1346_age_75_bmi_30_boundary_fires():
    """H.G1346 — edad=75 boundary inclusive + IMC=30 boundary inclusive dispara."""
    result = _evaluate({"age": 75, "bmi": 30})
    # numeric_threshold semantic = ≥; ambos boundaries inclusive
    assert "arsi_abiraterone_vte_risk_high" in _gate_codes(result)


def test_g1347_path_b_no_age_only_bmi_does_NOT_fire():
    """H.G1347 — solo IMC sin edad NO dispara Path B compound."""
    result = _evaluate({"bmi": 35})
    assert "arsi_abiraterone_vte_risk_high" not in _gate_codes(result)


def test_g1348_per_gate_yaml_shas_includes_35():
    """H.G1348 — get_per_gate_yaml_shas() incluye SHA gate 35."""
    from prostanet.shared.algorithm_version import get_per_gate_yaml_shas
    shas = get_per_gate_yaml_shas()
    assert "arsi_abiraterone_vte_risk_high" in shas


def test_g1349_no_payload_does_not_fire():
    """H.G1349 — payload vacío NO dispara gate 35."""
    result = _evaluate({})
    assert "arsi_abiraterone_vte_risk_high" not in _gate_codes(result)


def test_g1350_anticoagulation_with_history_vte_safely_treats():
    """H.G1350 — paciente con historia TEV pero anticoagulado: gate desactivado, ARSIs disponibles."""
    result = _evaluate(
        {"history_vte_documented": "Sí", "anticoagulation_therapeutic_active": "Sí"},
        [{"regimen_code": "ADT_ENZALUTAMIDE"}, {"regimen_code": "ADT_ABIRATERONE"}],
    )
    codes = _gate_codes(result)
    assert "arsi_abiraterone_vte_risk_high" not in codes
    filtered = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "ADT_ENZALUTAMIDE" in filtered
    assert "ADT_ABIRATERONE" in filtered
