"""tests/test_audit49_gate34_docetaxel_anc_longitudinal.py — Faubot 2026-04-25 (XLVIII).

Tests dedicados a Auditoría #49 — Gate 34 docetaxel × ANC rapid drop longitudinal.

Cubre H.G1301 - H.G1325 (25 hipótesis).
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest


def _evaluate(payload, treatments=None):
    from prostanet.shared.pivotal_contraindication_gates import apply_pivotal_contraindication_gates
    return apply_pivotal_contraindication_gates(payload, treatments or [])


def _gate_codes(result):
    return [g["code"] for g in result.get("gates_triggered", [])]


# §A — Path A: caída absoluta ≥1500 ANC


@pytest.mark.parametrize("anc", [3499, 2500, 1500, 500, 100])
def test_g1301_path_a_drop_above_1500_fires(anc):
    """H.G1301 — drop ANC >1500 dispara Path A."""
    result = _evaluate({"anc_baseline_pre_docetaxel": 5000, "anc": anc})
    assert "docetaxel_neutropenia_rapid_drop" in _gate_codes(result)


def test_g1302_path_a_drop_exactly_1500_does_NOT_fire():
    """H.G1302 — drop exactamente 1500 NO dispara (strict >)."""
    result = _evaluate({"anc_baseline_pre_docetaxel": 5000, "anc": 3500})
    # Path A needs >1500 drop; Path B needs >1000 + current <2000 (3500 NOT <2000)
    assert "docetaxel_neutropenia_rapid_drop" not in _gate_codes(result)


def test_g1303_path_a_dramatic_drop_baseline_8000_current_3000_fires():
    """H.G1303 — drop 5000 (baseline 8000 → current 3000) dispara."""
    result = _evaluate({"anc_baseline_pre_docetaxel": 8000, "anc": 3000})
    assert "docetaxel_neutropenia_rapid_drop" in _gate_codes(result)


def test_g1304_missing_baseline_does_NOT_fire_path_a():
    """H.G1304 — sin baseline pre-docetaxel, Path A NO puede evaluar."""
    result = _evaluate({"anc": 100})
    # ANC 100 puede no activar otros gates específicos; Path A/B requieren baseline
    assert "docetaxel_neutropenia_rapid_drop" not in _gate_codes(result)


# §B — Path B: caída ≥1000 + current <2000


def test_g1305_path_b_drop_1100_current_1800_fires():
    """H.G1305 — drop 1100 (≥1000) + current 1800 (<2000) dispara Path B."""
    result = _evaluate({"anc_baseline_pre_docetaxel": 2900, "anc": 1800})
    assert "docetaxel_neutropenia_rapid_drop" in _gate_codes(result)


def test_g1306_path_b_drop_900_does_NOT_fire():
    """H.G1306 — drop 900 (<1000) NO dispara Path B."""
    result = _evaluate({"anc_baseline_pre_docetaxel": 2700, "anc": 1800})
    assert "docetaxel_neutropenia_rapid_drop" not in _gate_codes(result)


def test_g1307_path_b_current_2000_does_NOT_fire():
    """H.G1307 — current 2000 (boundary, NOT <2000) NO dispara Path B."""
    result = _evaluate({"anc_baseline_pre_docetaxel": 3100, "anc": 2000})
    assert "docetaxel_neutropenia_rapid_drop" not in _gate_codes(result)


def test_g1308_path_c_flag_works_when_baseline_missing():
    """H.G1308 — Path C flag funciona como fallback cuando data
    longitudinal está incompleta (e.g., baseline pre-docetaxel no
    documentado). Esta es la motivación del Path C en el diseño."""
    # Sin baseline ANC + flag clínico → solo Path C dispara
    result = _evaluate({"absolute_neutrophil_count": 1700, "rapid_anc_drop_for_docetaxel": "Sí"})
    assert "docetaxel_neutropenia_rapid_drop" in _gate_codes(result)


# §C — Path C: flag explícito


def test_g1309_path_c_canonical_flag_fires():
    """H.G1309 — rapid_anc_drop_for_docetaxel=Sí dispara Path C."""
    result = _evaluate({"rapid_anc_drop_for_docetaxel": "Sí"})
    assert "docetaxel_neutropenia_rapid_drop" in _gate_codes(result)


@pytest.mark.parametrize("alias", [
    "rapid_neutropenia_documented",
    "early_neutropenia_for_docetaxel",
    "docetaxel_early_discontinuation_risk_documented",
])
def test_g1310_path_c_alias_variants(alias):
    """H.G1310 — aliases Path C funcionan."""
    result = _evaluate({alias: "Sí"})
    assert "docetaxel_neutropenia_rapid_drop" in _gate_codes(result)


# §D — Override


def test_g1311_override_canonical_disables():
    """H.G1311 — anc_recovered_post_drop_for_docetaxel=Sí desactiva."""
    result = _evaluate({
        "anc_baseline_pre_docetaxel": 5000,
        "anc": 2000,
        "anc_recovered_post_drop_for_docetaxel": "Sí",
    })
    assert "docetaxel_neutropenia_rapid_drop" not in _gate_codes(result)


def test_g1312_override_alias_docetaxel_neutropenia_recovered():
    """H.G1312 — alias docetaxel_neutropenia_recovered."""
    result = _evaluate({
        "rapid_anc_drop_for_docetaxel": "Sí",
        "docetaxel_neutropenia_recovered": "Sí",
    })
    assert "docetaxel_neutropenia_rapid_drop" not in _gate_codes(result)


def test_g1313_override_no_does_NOT_disable():
    """H.G1313 — override=No NO desactiva."""
    result = _evaluate({
        "anc_baseline_pre_docetaxel": 5000,
        "anc": 2000,
        "anc_recovered_post_drop_for_docetaxel": "No",
    })
    assert "docetaxel_neutropenia_rapid_drop" in _gate_codes(result)


# §E — Regimen scoping


@pytest.mark.parametrize("rc", [
    "DOCETAXEL", "ADT_DOCETAXEL",
    "ADT_DOCETAXEL_ABIRATERONE",  # PEACE-1 triplete
    "ADT_DOCETAXEL_DAROLUTAMIDE",  # ARASENS triplete
    "CABAZITAXEL",
])
def test_g1314_blocks_taxane_regimens(rc):
    """H.G1314 — Gate 34 filtra todos los REGIMEN_CODES_TAXANE."""
    result = _evaluate(
        {"anc_baseline_pre_docetaxel": 5000, "anc": 2500},
        [{"regimen_code": rc}],
    )
    filtered = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert rc not in filtered


@pytest.mark.parametrize("rc", [
    "ADT_ENZALUTAMIDE", "ADT_DAROLUTAMIDE", "ADT_ABIRATERONE",
    "OLAPARIB", "NIRAPARIB", "LU177_PSMA617",
])
def test_g1315_does_NOT_block_non_taxane(rc):
    """H.G1315 — Gate 34 NO bloquea regímenes NO-taxano."""
    result = _evaluate(
        {"anc_baseline_pre_docetaxel": 5000, "anc": 2500},
        [{"regimen_code": rc}],
    )
    filtered = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert rc in filtered


# §F — Coexistencia + catálogo


def test_g1316_total_yaml_gates_count_at_least_38():
    """H.G1316 — Catálogo YAML ≥38 gates tras audit batch."""
    from prostanet.shared.pivotal_gates_yaml_loader import get_loaded_yaml_codes
    codes = get_loaded_yaml_codes()
    assert "docetaxel_neutropenia_rapid_drop" in codes
    assert len(codes) >= 38


def test_g1317_active_gate_codes_includes_34():
    """H.G1317 — get_active_gate_codes() incluye gate 34."""
    from prostanet.shared.algorithm_version import get_active_gate_codes
    assert "docetaxel_neutropenia_rapid_drop" in get_active_gate_codes()


def test_g1318_class_label_specific():
    """H.G1318 — class_label específico (NO 'Otros')."""
    from prostanet.shared.pivotal_gate_delta import _classify_gate_for_message
    label = _classify_gate_for_message("docetaxel_neutropenia_rapid_drop")
    assert label == "Docetaxel caída ANC longitudinal (TAX-327 + STAMPEDE Arm C)"


def test_g1319_three_new_fieldspecs_registered():
    """H.G1319 — 3 nuevos FieldSpecs gate 34 registrados."""
    from prostanet.shared.advanced_support_fields import pivotal_gate_supporting_fields
    names = {f.name for f in pivotal_gate_supporting_fields()}
    expected = {
        "anc_baseline_pre_docetaxel",
        "rapid_anc_drop_for_docetaxel",
        "anc_recovered_post_drop_for_docetaxel",
    }
    assert not (expected - names)


def test_g1320_smoke_e2e_clinical_scenario():
    """H.G1320 — E2E: paciente con ANC baseline 5000 → cayó a 2500 → gate 34 fires."""
    payload = {"anc_baseline_pre_docetaxel": 5000, "anc": 2500, "metastatic": "1"}
    treatments = [
        {"regimen_code": "DOCETAXEL"},
        {"regimen_code": "ADT_DOCETAXEL_ABIRATERONE"},
        {"regimen_code": "ADT_ENZALUTAMIDE"},  # alternativa NO-taxano
    ]
    result = _evaluate(payload, treatments)
    codes = _gate_codes(result)
    assert "docetaxel_neutropenia_rapid_drop" in codes
    filtered = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "DOCETAXEL" not in filtered
    assert "ADT_DOCETAXEL_ABIRATERONE" not in filtered
    assert "ADT_ENZALUTAMIDE" in filtered  # alternativa preservada
    msgs = " ".join(result.get("not_recommended_messages", []))
    assert "TAX-327" in msgs or "docetaxel" in msgs.lower()


# §G — Edge cases


def test_g1321_anc_baseline_zero_safe():
    """H.G1321 — baseline ANC 0 no crashea (edge case)."""
    result = _evaluate({"anc_baseline_pre_docetaxel": 0, "anc": 0})
    # NO debe disparar Path A (drop 0 NOT >1500); NO debe crashear
    assert isinstance(_gate_codes(result), list)


def test_g1322_anc_current_higher_than_baseline_no_fire():
    """H.G1322 — current > baseline (recuperación) NO dispara Path A."""
    result = _evaluate({"anc_baseline_pre_docetaxel": 3000, "anc": 4500})
    # Drop = 3000-4500 = -1500 NOT >1500
    assert "docetaxel_neutropenia_rapid_drop" not in _gate_codes(result)


def test_g1323_baseline_plt_gate_22_unaffected_by_gate_34():
    """H.G1323 — Gate 22 niraparib (plt baseline) sigue disparando independientemente."""
    result = _evaluate({"platelets": 80000})
    # Gate 22 (niraparib_in_severe_thrombocytopenia) debe disparar por plt <150
    codes = _gate_codes(result)
    assert "niraparib_in_severe_thrombocytopenia" in codes
    # Gate 34 NO dispara (no ANC data)
    assert "docetaxel_neutropenia_rapid_drop" not in codes


def test_g1324_per_gate_yaml_shas_includes_34():
    """H.G1324 — get_per_gate_yaml_shas() incluye SHA gate 34."""
    from prostanet.shared.algorithm_version import get_per_gate_yaml_shas
    shas = get_per_gate_yaml_shas()
    assert "docetaxel_neutropenia_rapid_drop" in shas
    assert len(shas["docetaxel_neutropenia_rapid_drop"]) == 12


def test_g1325_loader_limitation_documented():
    """H.G1325 — Documenta limitación del loader: `numeric_baseline_delta_above`
    NO honra `alias_fields` para `current_field` — solo el campo canónico
    (`anc`) cuenta para Path A/B delta. Aliases (absolute_neutrophil_count,
    neutrophils_absolute, anc_current) funcionan SOLO en Path B
    `numeric_below` sub-trigger. Esta limitación es heredada de gate 33
    (niraparib delta plt) y aplica a TODOS los gates longitudinales.

    Workaround clínico: usar Path C flag (`rapid_anc_drop_for_docetaxel`)
    cuando baseline + current no están en campos canónicos."""
    # Solo `anc` (canonical) hace que Path A/B funcionen
    result_canonical = _evaluate({"anc_baseline_pre_docetaxel": 3000, "anc": 1500})
    assert "docetaxel_neutropenia_rapid_drop" in _gate_codes(result_canonical)

    # Solo aliases sin `anc` canonical → Path A/B NO disparan
    # (esto es el comportamiento documentado por la limitación del loader)
    result_alias_only = _evaluate({
        "anc_baseline_pre_docetaxel": 3000,
        "neutrophils_absolute": 1500,  # alias sin canonical anc
    })
    assert "docetaxel_neutropenia_rapid_drop" not in _gate_codes(result_alias_only)
