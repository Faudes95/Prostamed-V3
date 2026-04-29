"""tests/test_audit60_gate36_triplete_frailty.py — Faubot 2026-04-25 (L).

Tests dedicados a Auditoría #60 — Gate 36 Triplete ARSI+ADT+docetaxel × frailty G8 ≤14.

Cubre H.G1351 - H.G1375 (25 hipótesis).
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest


def _evaluate(payload, treatments=None):
    from prostanet.shared.pivotal_contraindication_gates import apply_pivotal_contraindication_gates
    return apply_pivotal_contraindication_gates(payload, treatments or [])


def _gate_codes(result):
    return [g["code"] for g in result.get("gates_triggered", [])]


# §A — Path A: G8 ≤14


@pytest.mark.parametrize("g8", [14, 12, 10, 8, 5])
def test_g1351_path_a_g8_below_15_fires(g8):
    """H.G1351 — G8 ≤14 dispara Path A (numeric_below 15)."""
    result = _evaluate({"g8_geriatric_score": g8})
    assert "triplete_frailty_g8_low" in _gate_codes(result)


@pytest.mark.parametrize("g8", [15, 16, 17])
def test_g1352_path_a_g8_above_14_does_NOT_fire(g8):
    """H.G1352 — G8 ≥15 (fit) NO dispara."""
    result = _evaluate({"g8_geriatric_score": g8})
    assert "triplete_frailty_g8_low" not in _gate_codes(result)


@pytest.mark.parametrize("alias", ["g8_score", "geriatric_g8_screening", "bellera_g8"])
def test_g1353_path_a_alias_variants(alias):
    """H.G1353 — aliases G8 funcionan."""
    result = _evaluate({alias: 12})
    assert "triplete_frailty_g8_low" in _gate_codes(result)


# §B — Path B: edad ≥80 + ECOG ≥2 (proxy si G8 no disponible)


def test_g1354_path_b_age_82_ecog_2_fires():
    """H.G1354 — edad 82 + ECOG 2 dispara Path B compound."""
    result = _evaluate({"age": 82, "ecog_score": 2})
    assert "triplete_frailty_g8_low" in _gate_codes(result)


def test_g1355_path_b_age_79_ecog_3_does_NOT_fire():
    """H.G1355 — edad 79 (NO ≥80) + ECOG 3 NO dispara Path B."""
    result = _evaluate({"age": 79, "ecog_score": 3})
    # NOTA: Other gate (`ecog_2_or_more_for_triplets` gate 6) sí dispararía,
    # pero gate 36 NO. Verificamos solo gate 36.
    assert "triplete_frailty_g8_low" not in _gate_codes(result)


def test_g1356_path_b_age_85_ecog_1_does_NOT_fire():
    """H.G1356 — edad 85 + ECOG 1 (NO ≥2) NO dispara Path B."""
    result = _evaluate({"age": 85, "ecog_score": 1})
    assert "triplete_frailty_g8_low" not in _gate_codes(result)


def test_g1357_path_b_alias_edad_age_at_assessment():
    """H.G1357 — alias edad + age_at_assessment funcionan."""
    result = _evaluate({"edad": 81, "ecog_score": 2})
    assert "triplete_frailty_g8_low" in _gate_codes(result)


# §C — Path C: flag CGA documentado


def test_g1358_path_c_canonical_flag_fires():
    """H.G1358 — cga_vulnerable_or_frail_documented=Sí dispara Path C."""
    result = _evaluate({"cga_vulnerable_or_frail_documented": "Sí"})
    assert "triplete_frailty_g8_low" in _gate_codes(result)


@pytest.mark.parametrize("alias", [
    "comprehensive_geriatric_assessment_vulnerable",
    "siog_frail_documented",
    "geriatric_unfit_for_chemo_documented",
])
def test_g1359_path_c_alias_variants(alias):
    """H.G1359 — aliases Path C funcionan."""
    result = _evaluate({alias: "Sí"})
    assert "triplete_frailty_g8_low" in _gate_codes(result)


# §D — Override


def test_g1360_override_canonical_disables():
    """H.G1360 — geriatric_clearance_for_triplete=Sí desactiva."""
    result = _evaluate({
        "g8_geriatric_score": 12,
        "geriatric_clearance_for_triplete": "Sí",
    })
    assert "triplete_frailty_g8_low" not in _gate_codes(result)


@pytest.mark.parametrize("alias", [
    "cga_clearance_for_triplete",
    "geriatric_endorsement_for_triplete",
    "siog_clearance_for_chemo_documented",
])
def test_g1361_override_alias_variants(alias):
    """H.G1361 — aliases override funcionan."""
    result = _evaluate({
        "g8_geriatric_score": 10,
        alias: "Sí",
    })
    assert "triplete_frailty_g8_low" not in _gate_codes(result)


def test_g1362_override_no_does_NOT_disable():
    """H.G1362 — override=No NO desactiva."""
    result = _evaluate({
        "g8_geriatric_score": 12,
        "geriatric_clearance_for_triplete": "No",
    })
    assert "triplete_frailty_g8_low" in _gate_codes(result)


# §E — Regimen scoping (TRIPLETS only)


@pytest.mark.parametrize("rc", [
    "ADT_DOCETAXEL_ABIRATERONE",  # PEACE-1
    "ADT_DOCETAXEL_DAROLUTAMIDE",  # ARASENS
])
def test_g1363_blocks_triplet_regimens(rc):
    """H.G1363 — Gate 36 filtra REGIMEN_CODES_TRIPLETS."""
    result = _evaluate(
        {"g8_geriatric_score": 12},
        [{"regimen_code": rc}],
    )
    filtered = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert rc not in filtered


@pytest.mark.parametrize("rc", [
    "ADT_DOCETAXEL",  # doblete
    "ADT_ABIRATERONE",
    "ADT_ENZALUTAMIDE", "ADT_DAROLUTAMIDE", "ADT_APALUTAMIDE",
    "DOCETAXEL", "CABAZITAXEL",
])
def test_g1364_does_NOT_block_doblets_or_monotherapies(rc):
    """H.G1364 — Gate 36 NO bloquea dobletes ni monoterapias."""
    result = _evaluate(
        {"g8_geriatric_score": 12},
        [{"regimen_code": rc}],
    )
    filtered = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert rc in filtered


# §F — Coexistencia con gate 6 (ECOG ≥2 triplete)


def test_g1365_gate_6_and_36_can_fire_simultaneously():
    """H.G1365 — gates 6+36 disparan juntos cuando ECOG ≥2 + G8 ≤14."""
    result = _evaluate({"ecog_score": 2, "g8_geriatric_score": 12})
    codes = _gate_codes(result)
    assert "triplete_frailty_g8_low" in codes
    assert "ecog_2_or_more_for_triplets" in codes


def test_g1366_gate_36_does_NOT_displace_gate_6():
    """H.G1366 — gate 36 NO desplaza a gate 6 (son complementarios).

    Caso: ECOG=2 + G8=16 (fit per G8 pero ECOG limita)."""
    result = _evaluate({"ecog_score": 2, "g8_geriatric_score": 16})
    codes = _gate_codes(result)
    # Gate 6 dispara por ECOG; gate 36 NO dispara por G8 fit
    assert "ecog_2_or_more_for_triplets" in codes
    assert "triplete_frailty_g8_low" not in codes


# §G — Catálogo + integración


def test_g1367_active_gate_codes_includes_36():
    """H.G1367 — get_active_gate_codes() incluye gate 36."""
    from prostanet.shared.algorithm_version import get_active_gate_codes
    assert "triplete_frailty_g8_low" in get_active_gate_codes()


def test_g1368_class_label_specific():
    """H.G1368 — class_label específico."""
    from prostanet.shared.pivotal_gate_delta import _classify_gate_for_message
    label = _classify_gate_for_message("triplete_frailty_g8_low")
    assert label == "Triplete + frailty G8 ≤14 (PEACE-1/ARASENS elderly subset)"


def test_g1369_three_new_fieldspecs_registered():
    """H.G1369 — 3 nuevos FieldSpecs gate 36 registrados."""
    from prostanet.shared.advanced_support_fields import pivotal_gate_supporting_fields
    names = {f.name for f in pivotal_gate_supporting_fields()}
    expected = {
        "g8_geriatric_score",
        "cga_vulnerable_or_frail_documented",
        "geriatric_clearance_for_triplete",
    }
    assert not (expected - names)


# §H — Smoke E2E


def test_g1370_smoke_e2e_elderly_frail_triplete_blocked():
    """H.G1370 — E2E: elderly G8=10 con triplete + dobletes → triplete bloqueado, dobletes preservados."""
    payload = {
        "age": 82, "g8_geriatric_score": 10, "ecog_score": 2,
        "metastatic": "1", "high_volume_disease": "1",
    }
    treatments = [
        {"regimen_code": "ADT_DOCETAXEL_ABIRATERONE", "regimen_name": "PEACE-1 triplete"},
        {"regimen_code": "ADT_DOCETAXEL_DAROLUTAMIDE", "regimen_name": "ARASENS triplete"},
        {"regimen_code": "ADT_ABIRATERONE", "regimen_name": "ADT+Abi (doblete)"},
        {"regimen_code": "ADT_DAROLUTAMIDE", "regimen_name": "ADT+Darolutamida (preferida elderly)"},
    ]
    result = _evaluate(payload, treatments)
    codes = _gate_codes(result)
    assert "triplete_frailty_g8_low" in codes
    filtered = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "ADT_DOCETAXEL_ABIRATERONE" not in filtered
    assert "ADT_DOCETAXEL_DAROLUTAMIDE" not in filtered
    # Dobletes preservados
    assert "ADT_ABIRATERONE" in filtered
    assert "ADT_DAROLUTAMIDE" in filtered
    msgs = " ".join(result.get("not_recommended_messages", []))
    assert "G8" in msgs or "PEACE-1" in msgs or "frail" in msgs.lower()


def test_g1371_g8_boundary_15_does_NOT_fire():
    """H.G1371 — G8=15 boundary NO dispara (numeric_below 15 strict)."""
    result = _evaluate({"g8_geriatric_score": 15})
    assert "triplete_frailty_g8_low" not in _gate_codes(result)


def test_g1372_per_gate_yaml_shas_includes_36():
    """H.G1372 — get_per_gate_yaml_shas() incluye SHA gate 36."""
    from prostanet.shared.algorithm_version import get_per_gate_yaml_shas
    assert "triplete_frailty_g8_low" in get_per_gate_yaml_shas()


def test_g1373_alias_age_at_assessment():
    """H.G1373 — alias age_at_assessment funciona en Path B."""
    result = _evaluate({"age_at_assessment": 80, "ecog_score": 2})
    assert "triplete_frailty_g8_low" in _gate_codes(result)


def test_g1374_no_payload_does_not_fire():
    """H.G1374 — payload vacío NO dispara."""
    result = _evaluate({})
    assert "triplete_frailty_g8_low" not in _gate_codes(result)


def test_g1375_combined_g8_and_cga_flag_both_fire_path_a_and_c():
    """H.G1375 — G8 ≤14 + CGA flag → Path A + C fire (1 gate triggered, no doble)."""
    result = _evaluate({"g8_geriatric_score": 12, "cga_vulnerable_or_frail_documented": "Sí"})
    codes = _gate_codes(result)
    # Gate 36 fires (regardless of which path); should appear ONCE not twice
    assert codes.count("triplete_frailty_g8_low") == 1
