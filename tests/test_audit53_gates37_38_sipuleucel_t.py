"""tests/test_audit53_gates37_38_sipuleucel_t.py — Faubot 2026-04-25 (LI).

Tests dedicados a Auditoría #53 — Gates 37 + 38 Sipuleucel-T (immunoterapia primera clase).

Cubre H.G1376 - H.G1410 (35 hipótesis):
- §A: Gate 37 (sipuleucel_t_severe_irr) Path A history IRR
- §B: Gate 37 Path B IRR grade documented
- §C: Gate 37 Path C anaphylaxis
- §D: Gate 37 override premedicación
- §E: Gate 38 (sipuleucel_t_febrile_neutropenia_post_leukapheresis) Path A febrile + ANC<500
- §F: Gate 38 Path B baseline ANC<1500 + no GCSF
- §G: Gate 38 Path C flag prior febrile event
- §H: Gate 38 override GCSF prophylaxis
- §I: Regimen scoping (Sipuleucel-T specific)
- §J: REGIMEN_CODES_SIPULEUCEL_T frozenset + KEYWORDS
- §K: Catálogo + integración + class_labels
- §L: Smoke E2E
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest


def _evaluate(payload, treatments=None):
    from prostanet.shared.pivotal_contraindication_gates import apply_pivotal_contraindication_gates
    return apply_pivotal_contraindication_gates(payload, treatments or [])


def _gate_codes(result):
    return [g["code"] for g in result.get("gates_triggered", [])]


# ════════════════════════════════════════════════════════════════════
# Gate 37 — sipuleucel_t_severe_irr
# ════════════════════════════════════════════════════════════════════


# §A — Path A: history IRR severo


def test_g1376_path_a_canonical_flag_fires():
    """H.G1376 — history_severe_irr_for_immunotherapy=Sí dispara Path A."""
    result = _evaluate({"history_severe_irr_for_immunotherapy": "Sí"})
    assert "sipuleucel_t_severe_irr" in _gate_codes(result)


@pytest.mark.parametrize("alias", [
    "prior_severe_infusion_reaction",
    "history_irr_grade_3_or_higher",
    "severe_irr_documented",
])
def test_g1377_path_a_alias_variants(alias):
    """H.G1377 — aliases Path A funcionan."""
    result = _evaluate({alias: "Sí"})
    assert "sipuleucel_t_severe_irr" in _gate_codes(result)


# §B — Path B: IRR grade ≥3 documentado


@pytest.mark.parametrize("grade", [3, 4])
def test_g1378_path_b_irr_grade_above_3_fires(grade):
    """H.G1378 — irr_grade_documented ≥3 dispara Path B."""
    result = _evaluate({"irr_grade_documented": grade})
    assert "sipuleucel_t_severe_irr" in _gate_codes(result)


@pytest.mark.parametrize("grade", [0, 1, 2])
def test_g1379_path_b_irr_grade_below_3_does_NOT_fire(grade):
    """H.G1379 — irr_grade_documented <3 NO dispara."""
    result = _evaluate({"irr_grade_documented": grade})
    assert "sipuleucel_t_severe_irr" not in _gate_codes(result)


@pytest.mark.parametrize("alias", ["infusion_reaction_ctcae_grade", "irr_ctcae_grade"])
def test_g1380_path_b_alias_variants(alias):
    """H.G1380 — aliases Path B funcionan."""
    result = _evaluate({alias: 3})
    assert "sipuleucel_t_severe_irr" in _gate_codes(result)


# §C — Path C: anafilaxis history


def test_g1381_path_c_canonical_flag_fires():
    """H.G1381 — anaphylaxis_history_documented=Sí dispara Path C."""
    result = _evaluate({"anaphylaxis_history_documented": "Sí"})
    assert "sipuleucel_t_severe_irr" in _gate_codes(result)


@pytest.mark.parametrize("alias", [
    "prior_anaphylaxis", "history_anaphylactic_reaction", "anaphylaxis_pa2024_documented",
])
def test_g1382_path_c_alias_variants(alias):
    """H.G1382 — aliases Path C funcionan."""
    result = _evaluate({alias: "Sí"})
    assert "sipuleucel_t_severe_irr" in _gate_codes(result)


# §D — Override gate 37


def test_g1383_override_canonical_disables():
    """H.G1383 — irr_premedication_protocol_active=Sí desactiva gate 37."""
    result = _evaluate({
        "history_severe_irr_for_immunotherapy": "Sí",
        "irr_premedication_protocol_active": "Sí",
    })
    assert "sipuleucel_t_severe_irr" not in _gate_codes(result)


@pytest.mark.parametrize("alias", [
    "sipuleucel_premedication_documented",
    "irr_prophylaxis_protocol_active",
])
def test_g1384_override_alias_variants(alias):
    """H.G1384 — aliases override gate 37 funcionan."""
    result = _evaluate({
        "anaphylaxis_history_documented": "Sí",
        alias: "Sí",
    })
    assert "sipuleucel_t_severe_irr" not in _gate_codes(result)


# ════════════════════════════════════════════════════════════════════
# Gate 38 — sipuleucel_t_febrile_neutropenia_post_leukapheresis
# ════════════════════════════════════════════════════════════════════


# §E — Path A: febrile (T≥38.3) + ANC <500


def test_g1385_path_a_temp_39_anc_300_fires():
    """H.G1385 — T 39°C + ANC 300 dispara Path A febrile neutropenia."""
    result = _evaluate({"temperature_celsius": 39.0, "anc": 300})
    assert "sipuleucel_t_febrile_neutropenia_post_leukapheresis" in _gate_codes(result)


def test_g1386_path_a_temp_38_2_does_NOT_fire():
    """H.G1386 — T 38.2°C (NO ≥38.3) + ANC 300 NO dispara Path A."""
    result = _evaluate({"temperature_celsius": 38.2, "anc": 300})
    assert "sipuleucel_t_febrile_neutropenia_post_leukapheresis" not in _gate_codes(result)


def test_g1387_path_a_anc_500_does_NOT_fire():
    """H.G1387 — ANC 500 (NO <500) + T 39 NO dispara Path A."""
    result = _evaluate({"temperature_celsius": 39.0, "anc": 500})
    assert "sipuleucel_t_febrile_neutropenia_post_leukapheresis" not in _gate_codes(result)


@pytest.mark.parametrize("alias", ["temperature", "body_temperature_c", "fever_celsius"])
def test_g1388_path_a_temperature_aliases(alias):
    """H.G1388 — aliases temperature en Path A."""
    result = _evaluate({alias: 39.0, "anc": 300})
    assert "sipuleucel_t_febrile_neutropenia_post_leukapheresis" in _gate_codes(result)


# §F — Path B: ANC baseline <1500 + sin GCSF


def test_g1389_path_b_anc_1200_no_gcsf_fires():
    """H.G1389 — ANC 1200 + no_gcsf_prophylaxis_planned=Sí dispara Path B."""
    result = _evaluate({"anc": 1200, "no_gcsf_prophylaxis_planned": "Sí"})
    assert "sipuleucel_t_febrile_neutropenia_post_leukapheresis" in _gate_codes(result)


def test_g1390_path_b_anc_1600_no_gcsf_does_NOT_fire():
    """H.G1390 — ANC 1600 (NO <1500) + no GCSF NO dispara Path B."""
    result = _evaluate({"anc": 1600, "no_gcsf_prophylaxis_planned": "Sí"})
    assert "sipuleucel_t_febrile_neutropenia_post_leukapheresis" not in _gate_codes(result)


def test_g1391_path_b_anc_1200_with_gcsf_does_NOT_fire():
    """H.G1391 — ANC 1200 + no_gcsf=No NO dispara Path B (tiene GCSF)."""
    result = _evaluate({"anc": 1200, "no_gcsf_prophylaxis_planned": "No"})
    assert "sipuleucel_t_febrile_neutropenia_post_leukapheresis" not in _gate_codes(result)


@pytest.mark.parametrize("alias", ["gcsf_not_planned", "sin_profilaxis_gcsf"])
def test_g1392_path_b_no_gcsf_aliases(alias):
    """H.G1392 — aliases no_gcsf_prophylaxis_planned funcionan."""
    result = _evaluate({"anc": 1200, alias: "Sí"})
    assert "sipuleucel_t_febrile_neutropenia_post_leukapheresis" in _gate_codes(result)


# §G — Path C: flag prior febrile event


def test_g1393_path_c_canonical_flag_fires():
    """H.G1393 — febrile_neutropenia_for_immunotherapy=Sí dispara Path C."""
    result = _evaluate({"febrile_neutropenia_for_immunotherapy": "Sí"})
    assert "sipuleucel_t_febrile_neutropenia_post_leukapheresis" in _gate_codes(result)


@pytest.mark.parametrize("alias", [
    "febrile_neutropenia_post_sipuleucel",
    "sepsis_post_leukapheresis_documented",
    "prior_febrile_event_immunotherapy",
])
def test_g1394_path_c_alias_variants(alias):
    """H.G1394 — aliases Path C funcionan."""
    result = _evaluate({alias: "Sí"})
    assert "sipuleucel_t_febrile_neutropenia_post_leukapheresis" in _gate_codes(result)


# §H — Override gate 38


def test_g1395_override_canonical_disables():
    """H.G1395 — gcsf_prophylaxis_active_for_sipuleucel=Sí desactiva gate 38."""
    result = _evaluate({
        "temperature_celsius": 39, "anc": 300,
        "gcsf_prophylaxis_active_for_sipuleucel": "Sí",
    })
    assert "sipuleucel_t_febrile_neutropenia_post_leukapheresis" not in _gate_codes(result)


@pytest.mark.parametrize("alias", [
    "pegfilgrastim_prophylaxis_documented",
    "filgrastim_prophylaxis_active",
    "sipuleucel_neutropenia_prophylaxis_active",
])
def test_g1396_override_alias_variants(alias):
    """H.G1396 — aliases override gate 38 funcionan."""
    result = _evaluate({
        "febrile_neutropenia_for_immunotherapy": "Sí",
        alias: "Sí",
    })
    assert "sipuleucel_t_febrile_neutropenia_post_leukapheresis" not in _gate_codes(result)


# §I — Regimen scoping (ambos gates 37+38 → SIPULEUCEL_T)


@pytest.mark.parametrize("rc", ["SIPULEUCEL_T", "PROVENGE"])
def test_g1397_gate37_blocks_sipuleucel_regimens(rc):
    """H.G1397 — Gate 37 filtra ambos códigos canónicos Sipuleucel-T."""
    result = _evaluate(
        {"history_severe_irr_for_immunotherapy": "Sí"},
        [{"regimen_code": rc}],
    )
    filtered = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert rc not in filtered


@pytest.mark.parametrize("rc", ["SIPULEUCEL_T", "PROVENGE"])
def test_g1398_gate38_blocks_sipuleucel_regimens(rc):
    """H.G1398 — Gate 38 filtra ambos códigos canónicos Sipuleucel-T."""
    result = _evaluate(
        {"temperature_celsius": 39, "anc": 300},
        [{"regimen_code": rc}],
    )
    filtered = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert rc not in filtered


@pytest.mark.parametrize("rc", [
    "ADT_ABIRATERONE", "ADT_ENZALUTAMIDE", "DOCETAXEL",
])
def test_g1399_gates_37_38_do_NOT_block_non_sipuleucel(rc):
    """H.G1399 — Gates 37+38 NO bloquean regímenes NO-Sipuleucel-T.

    NOTA: usamos solo flags clínicos (sin `anc <500`) para evitar trigger
    colateral de gate 14 (lutetium177_in_severe_cytopenias) que SÍ
    bloquearía LU177_PSMA617 — comportamiento correcto y esperado, pero
    fuera del scope de este test que valida ÚNICAMENTE gates 37+38."""
    result = _evaluate(
        {
            "history_severe_irr_for_immunotherapy": "Sí",
            "febrile_neutropenia_for_immunotherapy": "Sí",  # Path C flag (no triggers gate 14/15)
        },
        [{"regimen_code": rc}],
    )
    filtered = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert rc in filtered


# §J — REGIMEN_CODES_SIPULEUCEL_T frozenset + KEYWORDS


def test_g1400_regimen_codes_sipuleucel_exports():
    """H.G1400 — REGIMEN_CODES_SIPULEUCEL_T exporta códigos canónicos."""
    from prostanet.shared.pivotal_contraindication_gates import (
        REGIMEN_CODES_SIPULEUCEL_T, KEYWORDS_SIPULEUCEL_T,
    )
    assert "SIPULEUCEL_T" in REGIMEN_CODES_SIPULEUCEL_T
    assert "PROVENGE" in REGIMEN_CODES_SIPULEUCEL_T
    assert "sipuleucel" in KEYWORDS_SIPULEUCEL_T
    assert "provenge" in KEYWORDS_SIPULEUCEL_T


# §K — Catálogo + integración + class_labels


def test_g1401_active_gate_codes_includes_37_and_38():
    """H.G1401 — get_active_gate_codes() incluye gates 37 y 38."""
    from prostanet.shared.algorithm_version import get_active_gate_codes
    codes = get_active_gate_codes()
    assert "sipuleucel_t_severe_irr" in codes
    assert "sipuleucel_t_febrile_neutropenia_post_leukapheresis" in codes


def test_g1402_class_labels_specific():
    """H.G1402 — class_labels específicos para gates 37+38."""
    from prostanet.shared.pivotal_gate_delta import _classify_gate_for_message
    label37 = _classify_gate_for_message("sipuleucel_t_severe_irr")
    label38 = _classify_gate_for_message("sipuleucel_t_febrile_neutropenia_post_leukapheresis")
    assert label37 == "Sipuleucel-T IRR severo (IMPACT + Provenge §5.1)"
    assert label38 == "Sipuleucel-T febrile neutropenia (IMPACT + Provenge §5.2)"


def test_g1403_per_gate_yaml_shas_includes_37_38():
    """H.G1403 — get_per_gate_yaml_shas() incluye SHAs de gates 37+38."""
    from prostanet.shared.algorithm_version import get_per_gate_yaml_shas
    shas = get_per_gate_yaml_shas()
    assert "sipuleucel_t_severe_irr" in shas
    assert "sipuleucel_t_febrile_neutropenia_post_leukapheresis" in shas


def test_g1404_eight_new_fieldspecs_registered():
    """H.G1404 — 8 nuevos FieldSpecs gates 37+38 registrados."""
    from prostanet.shared.advanced_support_fields import pivotal_gate_supporting_fields
    names = {f.name for f in pivotal_gate_supporting_fields()}
    expected = {
        "history_severe_irr_for_immunotherapy",
        "irr_grade_documented",
        "anaphylaxis_history_documented",
        "irr_premedication_protocol_active",
        "temperature_celsius",
        "no_gcsf_prophylaxis_planned",
        "febrile_neutropenia_for_immunotherapy",
        "gcsf_prophylaxis_active_for_sipuleucel",
    }
    assert not (expected - names)


def test_g1405_total_yaml_gates_at_least_38():
    """H.G1405 — Catálogo YAML expone ≥38 gates."""
    from prostanet.shared.pivotal_gates_yaml_loader import get_loaded_yaml_codes
    assert len(get_loaded_yaml_codes()) >= 38


# §L — Smoke E2E


def test_g1406_smoke_e2e_irr_history_blocks_sipuleucel_keeps_alternatives():
    """H.G1406 — E2E: paciente con historia IRR severa y Provenge en consideración."""
    payload = {
        "history_severe_irr_for_immunotherapy": "Sí",
        "metastatic": "1",
    }
    treatments = [
        {"regimen_code": "SIPULEUCEL_T", "regimen_name": "Provenge"},
        {"regimen_code": "ADT_ENZALUTAMIDE", "regimen_name": "ADT+Enza"},
        {"regimen_code": "ADT_ABIRATERONE", "regimen_name": "ADT+Abi"},
    ]
    result = _evaluate(payload, treatments)
    codes = _gate_codes(result)
    assert "sipuleucel_t_severe_irr" in codes
    filtered = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "SIPULEUCEL_T" not in filtered
    assert "ADT_ENZALUTAMIDE" in filtered  # alternativa NO-immunoterapia
    assert "ADT_ABIRATERONE" in filtered


def test_g1407_smoke_e2e_febrile_neutropenia_blocks_provenge():
    """H.G1407 — E2E: paciente con febrile neutropenia → Provenge bloqueado."""
    result = _evaluate(
        {"temperature_celsius": 39.5, "anc": 200},
        [{"regimen_code": "PROVENGE"}, {"regimen_code": "DOCETAXEL"}],
    )
    codes = _gate_codes(result)
    assert "sipuleucel_t_febrile_neutropenia_post_leukapheresis" in codes
    filtered = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "PROVENGE" not in filtered
    assert "DOCETAXEL" in filtered  # NO bloqueado por gate 38


def test_g1408_smoke_e2e_premedication_protocol_re_enables_sipuleucel():
    """H.G1408 — E2E: paciente IRR previo + premedicación → Provenge re-disponible."""
    result = _evaluate(
        {
            "history_severe_irr_for_immunotherapy": "Sí",
            "irr_premedication_protocol_active": "Sí",
        },
        [{"regimen_code": "SIPULEUCEL_T"}],
    )
    codes = _gate_codes(result)
    assert "sipuleucel_t_severe_irr" not in codes
    filtered = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "SIPULEUCEL_T" in filtered


def test_g1409_gates_37_and_38_can_fire_simultaneously():
    """H.G1409 — gates 37+38 pueden disparar simultáneamente (paciente alto riesgo)."""
    result = _evaluate({
        "history_severe_irr_for_immunotherapy": "Sí",
        "temperature_celsius": 39, "anc": 300,
    })
    codes = _gate_codes(result)
    assert "sipuleucel_t_severe_irr" in codes
    assert "sipuleucel_t_febrile_neutropenia_post_leukapheresis" in codes


def test_g1410_no_payload_does_not_fire_either_gate():
    """H.G1410 — payload vacío NO dispara ninguno de los gates Sipuleucel-T."""
    result = _evaluate({})
    codes = _gate_codes(result)
    assert "sipuleucel_t_severe_irr" not in codes
    assert "sipuleucel_t_febrile_neutropenia_post_leukapheresis" not in codes
