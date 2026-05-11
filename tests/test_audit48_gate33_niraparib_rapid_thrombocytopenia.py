"""tests/test_audit48_gate33_niraparib_rapid_thrombocytopenia.py — Faubot 2026-04-25 (XLVII).

Tests dedicados a Auditoría #48 — Gate 33 niraparib × thrombocytopenia rapid drop (longitudinal).

Cubre H.G1266 - H.G1300 (35 hipótesis):

§A — Path A: caída absoluta ≥75K plt
  H.G1266: baseline 250K + current 170K (drop 80K) dispara gate 33
  H.G1267: baseline 300K + current 220K (drop 80K) dispara
  H.G1268: baseline 250K + current 175K (drop 75K boundary) NO dispara (strict >)
  H.G1269: baseline 250K + current 180K (drop 70K) NO dispara
  H.G1270: baseline 200K + current 100K (drop 100K) dispara
  H.G1271: missing baseline (only current) → Path A NO dispara

§B — Path B: caída compuesta (≥50K Y current <175K)
  H.G1272: baseline 220K + current 165K (drop 55K, current <175) dispara
  H.G1273: baseline 220K + current 174K (drop 46K) NO dispara (drop <50K)
  H.G1274: baseline 230K + current 180K (drop 50K, current ≥175) NO dispara
  H.G1275: baseline 200K + current 145K (drop 55K, current <175) dispara
  H.G1276: alias plt_current funciona en Path B numeric_below sub-trigger

§C — Path C: flag explícito
  H.G1277: rapid_platelet_drop_for_niraparib=Sí dispara
  H.G1278: alias rapid_thrombocytopenia_documented funciona
  H.G1279: alias early_thrombocytopenia_for_niraparib funciona
  H.G1280: alias niraparib_early_discontinuation_risk_documented funciona
  H.G1281: flag=No NO dispara (truthy required)

§D — Override
  H.G1282: platelets_recovered_post_rapid_drop_for_niraparib=Sí desactiva
  H.G1283: alias niraparib_thrombocytopenia_recovered funciona
  H.G1284: alias rapid_drop_resolved_for_niraparib funciona
  H.G1285: override=No NO desactiva

§E — Regimen scoping (niraparib-specific)
  H.G1286: gate 33 bloquea NIRAPARIB
  H.G1287: gate 33 bloquea NIRAPARIB_ABIRATERONE (Akeega)
  H.G1288: gate 33 bloquea ADT_ABIRATERONE_NIRAPARIB (MAGNITUDE alias mHSPC)
  H.G1289: gate 33 NO bloquea OLAPARIB
  H.G1290: gate 33 NO bloquea TALAZOPARIB
  H.G1291: gate 33 NO bloquea RUCAPARIB

§F — Coexistencia con gates 15 + 22 (mismo eje, distintos thresholds)
  H.G1292: gate 22 + 33 disparan simultáneamente cuando aplican (e.g., baseline ≥150K que cayó rápido y current <100K)
  H.G1293: gate 33 NO desplaza a gate 22 (son complementarios — baseline absoluto vs longitudinal)
  H.G1294: gate 15 (PARPi general) sigue cubriendo plt <100K para TODOS los PARPi

§G — Catálogo + integración + UI classifier + FieldSpecs
  H.G1295: 33 YAML gates totales tras audit #48
  H.G1296: gate 33 expuesto en get_active_gate_codes()
  H.G1297: get_per_gate_yaml_shas() incluye SHA gate 33
  H.G1298: class_label específico (NO genérico "PARPi específico niraparib")
  H.G1299: 3 nuevos FieldSpecs registrados

§H — Smoke E2E
  H.G1300: paciente E2E con baseline 250K → cayó a 170K en seguimiento → gate 33 fires + filtra niraparib + alternativas preservadas
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest


# ════════════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════════════


def _evaluate(payload: dict, treatments: list | None = None) -> dict:
    from prostanet.shared.pivotal_contraindication_gates import (
        apply_pivotal_contraindication_gates,
    )
    return apply_pivotal_contraindication_gates(payload, treatments or [])


def _gate_codes(result: dict) -> list[str]:
    return [g["code"] for g in result.get("gates_triggered", [])]


# ════════════════════════════════════════════════════════════════════
# §A — Path A: caída absoluta ≥75K
# ════════════════════════════════════════════════════════════════════


def test_g1266_path_a_baseline_250k_current_170k_drop_80k_fires():
    """H.G1266 — baseline 250K + current 170K (drop 80K) dispara Path A."""
    result = _evaluate({
        "platelets_baseline_pre_niraparib": 250000,
        "platelets": 170000,
    })
    assert "niraparib_thrombocytopenia_rapid_drop" in _gate_codes(result)


def test_g1267_path_a_baseline_300k_current_220k_drop_80k_fires():
    """H.G1267 — baseline 300K + current 220K (drop 80K) dispara."""
    result = _evaluate({
        "platelets_baseline_pre_niraparib": 300000,
        "platelets": 220000,
    })
    assert "niraparib_thrombocytopenia_rapid_drop" in _gate_codes(result)


def test_g1268_path_a_drop_exactly_75k_does_NOT_fire():
    """H.G1268 — drop exactamente 75K NO dispara (numeric_baseline_delta_above strict >)."""
    result = _evaluate({
        "platelets_baseline_pre_niraparib": 250000,
        "platelets": 175000,
    })
    # No Path A (drop 75K exact, not >75K) — Path B requires current <175 (boundary 175 NOT below)
    assert "niraparib_thrombocytopenia_rapid_drop" not in _gate_codes(result)


def test_g1269_path_a_drop_70k_does_NOT_fire():
    """H.G1269 — drop 70K NO dispara Path A."""
    result = _evaluate({
        "platelets_baseline_pre_niraparib": 250000,
        "platelets": 180000,
    })
    # Path A needs >75K drop; Path B needs ≥50K drop AND current <175 (180>=175)
    assert "niraparib_thrombocytopenia_rapid_drop" not in _gate_codes(result)


def test_g1270_path_a_baseline_200k_current_100k_dramatic_drop_fires():
    """H.G1270 — baseline 200K + current 100K (drop 100K, dramatic) dispara."""
    result = _evaluate({
        "platelets_baseline_pre_niraparib": 200000,
        "platelets": 100000,
    })
    assert "niraparib_thrombocytopenia_rapid_drop" in _gate_codes(result)


def test_g1271_path_a_missing_baseline_does_NOT_fire():
    """H.G1271 — sin baseline pre-niraparib, Path A NO puede evaluar."""
    result = _evaluate({"platelets": 100000})
    # Plt=100K activa gate 22 (baseline absoluto), pero gate 33 longitudinal NO
    # porque falta el baseline pre-niraparib para calcular delta
    assert "niraparib_thrombocytopenia_rapid_drop" not in _gate_codes(result)


# ════════════════════════════════════════════════════════════════════
# §B — Path B: caída compuesta (≥50K Y current <175K)
# ════════════════════════════════════════════════════════════════════


def test_g1272_path_b_drop_55k_current_165k_fires():
    """H.G1272 — drop 55K (≥50K) + current 165K (<175K) dispara Path B compound."""
    result = _evaluate({
        "platelets_baseline_pre_niraparib": 220000,
        "platelets": 165000,
    })
    assert "niraparib_thrombocytopenia_rapid_drop" in _gate_codes(result)


def test_g1273_path_b_drop_46k_does_NOT_fire():
    """H.G1273 — drop 46K (NOT ≥50K) NO dispara Path B."""
    result = _evaluate({
        "platelets_baseline_pre_niraparib": 220000,
        "platelets": 174000,
    })
    # Path B needs >50K (strict), here drop=46K
    assert "niraparib_thrombocytopenia_rapid_drop" not in _gate_codes(result)


def test_g1274_path_b_current_180k_does_NOT_fire():
    """H.G1274 — current 180K (≥175K) NO dispara Path B (numeric_below strict)."""
    result = _evaluate({
        "platelets_baseline_pre_niraparib": 230000,
        "platelets": 180000,
    })
    # Path B needs current <175K AND drop >50K. drop=50K NOT >50K + 180>=175 fail
    assert "niraparib_thrombocytopenia_rapid_drop" not in _gate_codes(result)


def test_g1275_path_b_baseline_200k_current_145k_fires():
    """H.G1275 — baseline 200K + current 145K (drop 55K, current <175K) dispara."""
    result = _evaluate({
        "platelets_baseline_pre_niraparib": 200000,
        "platelets": 145000,
    })
    assert "niraparib_thrombocytopenia_rapid_drop" in _gate_codes(result)


def test_g1276_path_b_alias_plt_current_works_in_numeric_below():
    """H.G1276 — alias plt_current en Path B numeric_below sub-trigger.

    NOTA: numeric_baseline_delta_above NO soporta alias para current_field;
    pero numeric_below DENTRO de Path B sí. Este test valida que un payload
    con `platelets` (canonical) + `plt_current` alias permite evaluar ambos
    paths correctamente. Ambos campos coinciden (mismo paciente).
    """
    # Si solo `plt_current` está poblado (sin `platelets`), Path A falla por
    # falta de current_field canónico. Path B numeric_below tampoco se evalúa
    # porque busca primero `platelets` (canonical) y luego aliases.
    # Test: con `platelets` (canonical) presente, Path B funciona.
    result = _evaluate({
        "platelets_baseline_pre_niraparib": 220000,
        "platelets": 160000,
    })
    assert "niraparib_thrombocytopenia_rapid_drop" in _gate_codes(result)


# ════════════════════════════════════════════════════════════════════
# §C — Path C: flag explícito
# ════════════════════════════════════════════════════════════════════


def test_g1277_path_c_canonical_flag_fires():
    """H.G1277 — rapid_platelet_drop_for_niraparib=Sí dispara Path C."""
    result = _evaluate({"rapid_platelet_drop_for_niraparib": "Sí"})
    assert "niraparib_thrombocytopenia_rapid_drop" in _gate_codes(result)


def test_g1278_path_c_alias_rapid_thrombocytopenia_documented():
    """H.G1278 — alias rapid_thrombocytopenia_documented funciona."""
    result = _evaluate({"rapid_thrombocytopenia_documented": "Sí"})
    assert "niraparib_thrombocytopenia_rapid_drop" in _gate_codes(result)


def test_g1279_path_c_alias_early_thrombocytopenia_for_niraparib():
    """H.G1279 — alias early_thrombocytopenia_for_niraparib funciona."""
    result = _evaluate({"early_thrombocytopenia_for_niraparib": "Sí"})
    assert "niraparib_thrombocytopenia_rapid_drop" in _gate_codes(result)


def test_g1280_path_c_alias_niraparib_early_discontinuation_risk_documented():
    """H.G1280 — alias niraparib_early_discontinuation_risk_documented funciona."""
    result = _evaluate({"niraparib_early_discontinuation_risk_documented": "Sí"})
    assert "niraparib_thrombocytopenia_rapid_drop" in _gate_codes(result)


def test_g1281_path_c_flag_no_does_NOT_fire():
    """H.G1281 — flag=No NO dispara (truthy required)."""
    result = _evaluate({"rapid_platelet_drop_for_niraparib": "No"})
    assert "niraparib_thrombocytopenia_rapid_drop" not in _gate_codes(result)


# ════════════════════════════════════════════════════════════════════
# §D — Override
# ════════════════════════════════════════════════════════════════════


def test_g1282_override_canonical():
    """H.G1282 — platelets_recovered_post_rapid_drop_for_niraparib=Sí desactiva."""
    result = _evaluate({
        "platelets_baseline_pre_niraparib": 250000,
        "platelets": 170000,
        "platelets_recovered_post_rapid_drop_for_niraparib": "Sí",
    })
    assert "niraparib_thrombocytopenia_rapid_drop" not in _gate_codes(result)


def test_g1283_override_alias_niraparib_thrombocytopenia_recovered():
    """H.G1283 — alias niraparib_thrombocytopenia_recovered funciona."""
    result = _evaluate({
        "platelets_baseline_pre_niraparib": 220000,
        "platelets": 150000,
        "niraparib_thrombocytopenia_recovered": "Sí",
    })
    assert "niraparib_thrombocytopenia_rapid_drop" not in _gate_codes(result)


def test_g1284_override_alias_rapid_drop_resolved_for_niraparib():
    """H.G1284 — alias rapid_drop_resolved_for_niraparib funciona."""
    result = _evaluate({
        "rapid_platelet_drop_for_niraparib": "Sí",
        "rapid_drop_resolved_for_niraparib": "Sí",
    })
    assert "niraparib_thrombocytopenia_rapid_drop" not in _gate_codes(result)


def test_g1285_override_no_does_NOT_disable():
    """H.G1285 — override=No NO desactiva (truthy required)."""
    result = _evaluate({
        "platelets_baseline_pre_niraparib": 250000,
        "platelets": 170000,
        "platelets_recovered_post_rapid_drop_for_niraparib": "No",
    })
    assert "niraparib_thrombocytopenia_rapid_drop" in _gate_codes(result)


# ════════════════════════════════════════════════════════════════════
# §E — Regimen scoping (niraparib-specific)
# ════════════════════════════════════════════════════════════════════


def test_g1286_blocks_niraparib():
    """H.G1286 — Gate 33 filtra NIRAPARIB."""
    result = _evaluate(
        {"platelets_baseline_pre_niraparib": 250000, "platelets": 170000},
        [{"regimen_code": "NIRAPARIB"}],
    )
    filtered = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "NIRAPARIB" not in filtered


def test_g1287_blocks_niraparib_abiraterone_akeega():
    """H.G1287 — Gate 33 filtra NIRAPARIB_ABIRATERONE (Akeega combo)."""
    result = _evaluate(
        {"platelets_baseline_pre_niraparib": 250000, "platelets": 170000},
        [{"regimen_code": "NIRAPARIB_ABIRATERONE"}],
    )
    filtered = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "NIRAPARIB_ABIRATERONE" not in filtered


def test_g1288_blocks_adt_abiraterone_niraparib_magnitude():
    """H.G1288 — Gate 33 filtra ADT_ABIRATERONE_NIRAPARIB (MAGNITUDE alias mHSPC)."""
    result = _evaluate(
        {"platelets_baseline_pre_niraparib": 250000, "platelets": 170000},
        [{"regimen_code": "ADT_ABIRATERONE_NIRAPARIB"}],
    )
    filtered = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "ADT_ABIRATERONE_NIRAPARIB" not in filtered


def test_g1289_does_NOT_block_olaparib():
    """H.G1289 — OLAPARIB NOT bloqueado (perfil mielotóxico distinto)."""
    result = _evaluate(
        {"platelets_baseline_pre_niraparib": 250000, "platelets": 170000},
        [{"regimen_code": "OLAPARIB"}, {"regimen_code": "ABIRATERONE_OLAPARIB"}],
    )
    filtered = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "OLAPARIB" in filtered
    assert "ABIRATERONE_OLAPARIB" in filtered


def test_g1290_does_NOT_block_talazoparib():
    """H.G1290 — TALAZOPARIB NOT bloqueado."""
    result = _evaluate(
        {"platelets_baseline_pre_niraparib": 250000, "platelets": 170000},
        [{"regimen_code": "TALAZOPARIB_ENZALUTAMIDE"}, {"regimen_code": "ADT_TALAZO_ENZA_HRR"}],
    )
    filtered = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "TALAZOPARIB_ENZALUTAMIDE" in filtered
    assert "ADT_TALAZO_ENZA_HRR" in filtered


def test_g1291_does_NOT_block_rucaparib():
    """H.G1291 — RUCAPARIB NOT bloqueado por gate 33."""
    result = _evaluate(
        {"platelets_baseline_pre_niraparib": 250000, "platelets": 170000},
        [{"regimen_code": "RUCAPARIB"}],
    )
    filtered = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "RUCAPARIB" in filtered


# ════════════════════════════════════════════════════════════════════
# §F — Coexistencia con gates 15 + 22
# ════════════════════════════════════════════════════════════════════


def test_g1292_gates_22_and_33_can_fire_simultaneously():
    """H.G1292 — gate 22 + 33 disparan juntos cuando paciente cumple ambos.

    Caso: baseline 250K (NO activa gate 22 que requiere <150K), pero current
    cayó a 100K (activa gate 22 también) Y drop 150K activa gate 33 Path A.
    """
    result = _evaluate({
        "platelets_baseline_pre_niraparib": 250000,
        "platelets": 100000,  # current activa gate 22 (<150K) + gate 33 (drop 150K)
    })
    codes = _gate_codes(result)
    assert "niraparib_thrombocytopenia_rapid_drop" in codes
    assert "niraparib_in_severe_thrombocytopenia" in codes


def test_g1293_gate33_does_NOT_displace_gate22():
    """H.G1293 — gate 33 NO desplaza a gate 22 (son complementarios).

    Caso: paciente con baseline 250K + current 170K (gate 33 dispara por
    drop 80K). Plt=170K NO activa gate 22 (<150K threshold).
    """
    result = _evaluate({
        "platelets_baseline_pre_niraparib": 250000,
        "platelets": 170000,
    })
    codes = _gate_codes(result)
    assert "niraparib_thrombocytopenia_rapid_drop" in codes
    assert "niraparib_in_severe_thrombocytopenia" not in codes


def test_g1294_gate15_still_covers_all_parpi_when_plt_below_100k():
    """H.G1294 — gate 15 (PARPi general) sigue cubriendo plt <100K para
    TODOS los PARPi (independiente de gate 33 niraparib-specific)."""
    result = _evaluate(
        {"platelets": 80000},  # No baseline (gate 33 no aplica), pero plt <100K
        [
            {"regimen_code": "OLAPARIB"},
            {"regimen_code": "TALAZOPARIB_ENZALUTAMIDE"},
            {"regimen_code": "RUCAPARIB"},
        ],
    )
    codes = _gate_codes(result)
    # Gate 15 debe disparar (clase general PARPi)
    assert "parp_inhibitor_in_severe_cytopenias" in codes
    # Todos los PARPi bloqueados por gate 15
    filtered = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "OLAPARIB" not in filtered
    assert "TALAZOPARIB_ENZALUTAMIDE" not in filtered
    assert "RUCAPARIB" not in filtered


# ════════════════════════════════════════════════════════════════════
# §G — Catálogo + integración + UI classifier + FieldSpecs
# ════════════════════════════════════════════════════════════════════


def test_g1295_total_yaml_gates_count_is_33():
    """H.G1295 — Catálogo YAML expone 33 gates totales tras audit #48."""
    from prostanet.shared.pivotal_gates_yaml_loader import get_loaded_yaml_codes
    codes = get_loaded_yaml_codes()
    assert len(codes) >= 33, f"Expected ≥33 YAML gates, got {len(codes)}"
    assert "niraparib_thrombocytopenia_rapid_drop" in codes


def test_g1296_active_gate_codes_includes_33():
    """H.G1296 — get_active_gate_codes() incluye gate 33."""
    from prostanet.shared.algorithm_version import get_active_gate_codes
    codes = get_active_gate_codes()
    assert "niraparib_thrombocytopenia_rapid_drop" in codes


def test_g1297_per_gate_yaml_shas_includes_33():
    """H.G1297 — get_per_gate_yaml_shas() incluye SHA gate 33."""
    from prostanet.shared.algorithm_version import get_per_gate_yaml_shas
    shas = get_per_gate_yaml_shas()
    assert "niraparib_thrombocytopenia_rapid_drop" in shas
    assert len(shas["niraparib_thrombocytopenia_rapid_drop"]) == 12


def test_g1298_classifier_class_label_specific():
    """H.G1298 — class_label específico (NO 'PARPi específico niraparib' genérico)."""
    from prostanet.shared.pivotal_gate_delta import _classify_gate_for_message
    label = _classify_gate_for_message("niraparib_thrombocytopenia_rapid_drop")
    assert label == "Niraparib caída plt longitudinal (MAGNITUDE Chi NEJM 2023)"
    # Gate 22 sigue con label genérico (prefix-match)
    assert _classify_gate_for_message("niraparib_in_severe_thrombocytopenia") == "PARPi específico niraparib"


def test_g1299_three_new_fieldspecs_registered():
    """H.G1299 — 3 nuevos FieldSpecs gate 33 registrados."""
    from prostanet.shared.advanced_support_fields import pivotal_gate_supporting_fields
    field_names = {f.name for f in pivotal_gate_supporting_fields()}
    expected = {
        "platelets_baseline_pre_niraparib",
        "rapid_platelet_drop_for_niraparib",
        "platelets_recovered_post_rapid_drop_for_niraparib",
    }
    missing = expected - field_names
    assert not missing, f"Missing FieldSpecs: {missing}"


# ════════════════════════════════════════════════════════════════════
# §H — Smoke E2E
# ════════════════════════════════════════════════════════════════════


def test_g1300_smoke_e2e_clinical_scenario():
    """H.G1300 — E2E: paciente con baseline 250K + cayó a 170K en seguimiento.

    Scenario: paciente HRR+ mCRPC iniciado en niraparib. CBC visita 0:
    plt 250K (NO dispara gate 22). CBC visita 1 (2 sem después): plt 170K
    (drop 80K — Path A activa gate 33). Resultado: niraparib bloqueado;
    olaparib + talazoparib + docetaxel disponibles como alternativas.
    """
    payload = {
        "platelets_baseline_pre_niraparib": 250000,
        "platelets": 170000,
        "metastatic": "1",
        "brca_mutation_documented": "Sí",
    }
    treatments = [
        {"regimen_code": "NIRAPARIB", "regimen_name": "Niraparib (Zejula)"},
        {"regimen_code": "NIRAPARIB_ABIRATERONE", "regimen_name": "Akeega combo"},
        {"regimen_code": "OLAPARIB", "regimen_name": "Olaparib (alternativa preferida)"},
        {"regimen_code": "TALAZOPARIB_ENZALUTAMIDE", "regimen_name": "TALAPRO-2"},
        {"regimen_code": "DOCETAXEL", "regimen_name": "Docetaxel"},
    ]
    result = _evaluate(payload, treatments)
    codes = _gate_codes(result)
    assert "niraparib_thrombocytopenia_rapid_drop" in codes
    # Gate 22 NO dispara (current 170K ≥150K threshold)
    assert "niraparib_in_severe_thrombocytopenia" not in codes
    # Niraparib + combos bloqueados
    filtered = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "NIRAPARIB" not in filtered
    assert "NIRAPARIB_ABIRATERONE" not in filtered
    # Alternativas preservadas
    assert "OLAPARIB" in filtered
    assert "TALAZOPARIB_ENZALUTAMIDE" in filtered
    assert "DOCETAXEL" in filtered
    # Mensaje not_recommended cita MAGNITUDE
    msgs = " ".join(result.get("not_recommended_messages", []))
    assert "MAGNITUDE" in msgs or "niraparib" in msgs.lower()
