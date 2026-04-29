"""tests/test_audit57_gate42_apalutamide_sjs_ten.py — Faubot 2026-04-25 (LVI).

Tests dedicados a Auditoría #57 — Gate 42 apalutamida × Severe rash / SJS-TEN.

Cubre H.G1501 - H.G1535 (35 hipótesis) en 8 secciones:

§A — Path A: rash CTCAE G≥3
§B — Path B: skin blistering documented (vesículas/ampollas)
§C — Path C: mucosal involvement documented
§D — Path D: erythema multiforme documented (target lesions)
§E — Path E: SJS/TEN explicit suspicion or diagnosis
§F — ⚠️ NO override (DISCONTINUACIÓN PERMANENTE per Erleada §5.2)
§G — Regimen scoping (apalutamide-specific, NO enzalutamida ni darolutamida)
§H — Catálogo + clasificadores + integración + smoke E2E

🎯 PRIMER GATE DERMATOLÓGICO + PRIMER GATE SIN OVERRIDE del catálogo.
Sienta precedente arquitectónico para gates con contraindicación absoluta
irreversible (interstitial pneumonitis, anaphylaxis fatal, hepatic
failure G4, etc.).
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest


def _evaluate(payload, treatments=None):
    from prostanet.shared.pivotal_contraindication_gates import apply_pivotal_contraindication_gates
    return apply_pivotal_contraindication_gates(payload, treatments or [])


def _gate_codes(result):
    return [g["code"] for g in result.get("gates_triggered", [])]


def _tx(code: str) -> list[dict]:
    return [{"name": code, "regimen_code": code}]


GATE_CODE = "apalutamide_severe_rash_sjs_ten"


# ───────────────────────────────────────────────
# §A — Path A: rash CTCAE G≥3
# ───────────────────────────────────────────────


@pytest.mark.parametrize("grade", [3, 4, 5])
def test_g1501_path_a_rash_ctcae_grade_ge_3_fires(grade):
    """H.G1501 — rash CTCAE G≥3 dispara Path A."""
    result = _evaluate({"rash_ctcae_grade": grade}, treatments=_tx("ADT_APALUTAMIDE"))
    assert GATE_CODE in _gate_codes(result)


@pytest.mark.parametrize("grade", [0, 1, 2])
def test_g1502_path_a_rash_ctcae_grade_lt_3_does_NOT_fire(grade):
    """H.G1502 — rash CTCAE G<3 NO dispara (G2 ≠ severe per CTCAE v5)."""
    result = _evaluate({"rash_ctcae_grade": grade}, treatments=_tx("ADT_APALUTAMIDE"))
    assert GATE_CODE not in _gate_codes(result)


def test_g1503_path_a_alias_rash_grade_works():
    """H.G1503 — alias `rash_grade` (sin _ctcae) dispara Path A."""
    result = _evaluate({"rash_grade": 4}, treatments=_tx("ADT_APALUTAMIDE"))
    assert GATE_CODE in _gate_codes(result)


def test_g1504_path_a_alias_skin_rash_ctcae_grade_works():
    """H.G1504 — alias `skin_rash_ctcae_grade` dispara Path A."""
    result = _evaluate({"skin_rash_ctcae_grade": 3}, treatments=_tx("ADT_APALUTAMIDE"))
    assert GATE_CODE in _gate_codes(result)


def test_g1505_path_a_alias_rash_severity_ctcae_works():
    """H.G1505 — alias `rash_severity_ctcae` dispara Path A."""
    result = _evaluate({"rash_severity_ctcae": 3}, treatments=_tx("ADT_APALUTAMIDE"))
    assert GATE_CODE in _gate_codes(result)


def test_g1506_path_a_missing_rash_field_does_NOT_fire():
    """H.G1506 — sin field rash, Path A NO puede evaluar (otros paths siguen disponibles)."""
    result = _evaluate({}, treatments=_tx("ADT_APALUTAMIDE"))
    assert GATE_CODE not in _gate_codes(result)


# ───────────────────────────────────────────────
# §B — Path B: skin blistering documented (vesículas/ampollas)
# ───────────────────────────────────────────────


@pytest.mark.parametrize("flag_value", ["Sí", "Si", "yes", "True", True, 1])
def test_g1507_path_b_skin_blistering_truthy_fires(flag_value):
    """H.G1507 — skin_blistering_documented truthy dispara Path B (precursor SJS/TEN)."""
    result = _evaluate(
        {"skin_blistering_documented": flag_value},
        treatments=_tx("ADT_APALUTAMIDE"),
    )
    assert GATE_CODE in _gate_codes(result)


@pytest.mark.parametrize("flag_value", ["No", "Desconocido", False, 0, ""])
def test_g1508_path_b_skin_blistering_falsy_does_NOT_fire(flag_value):
    """H.G1508 — skin_blistering_documented falsy NO dispara Path B."""
    result = _evaluate(
        {"skin_blistering_documented": flag_value},
        treatments=_tx("ADT_APALUTAMIDE"),
    )
    assert GATE_CODE not in _gate_codes(result)


def test_g1509_path_b_alias_skin_vesicles_documented_works():
    """H.G1509 — alias `skin_vesicles_documented` dispara Path B."""
    result = _evaluate({"skin_vesicles_documented": "Sí"}, treatments=_tx("APALUTAMIDE"))
    assert GATE_CODE in _gate_codes(result)


def test_g1510_path_b_alias_vesiculobullous_lesions_documented_works():
    """H.G1510 — alias `vesiculobullous_lesions_documented` dispara Path B."""
    result = _evaluate(
        {"vesiculobullous_lesions_documented": "Sí"},
        treatments=_tx("ADT_APALUTAMIDE"),
    )
    assert GATE_CODE in _gate_codes(result)


# ───────────────────────────────────────────────
# §C — Path C: mucosal involvement documented
# ───────────────────────────────────────────────


def test_g1511_path_c_mucosal_involvement_fires():
    """H.G1511 — mucosal_involvement_documented dispara Path C (patognomónico SJS-spectrum)."""
    result = _evaluate(
        {"mucosal_involvement_documented": "Sí"},
        treatments=_tx("ADT_APALUTAMIDE"),
    )
    assert GATE_CODE in _gate_codes(result)


def test_g1512_path_c_alias_mucositis_documented_for_apalutamide_works():
    """H.G1512 — alias `mucositis_documented_for_apalutamide` dispara Path C."""
    result = _evaluate(
        {"mucositis_documented_for_apalutamide": "Sí"},
        treatments=_tx("ADT_APALUTAMIDE"),
    )
    assert GATE_CODE in _gate_codes(result)


def test_g1513_path_c_alias_oral_mucosal_lesions_works():
    """H.G1513 — alias `oral_mucosal_lesions_documented` dispara Path C."""
    result = _evaluate(
        {"oral_mucosal_lesions_documented": "Sí"},
        treatments=_tx("ADT_APALUTAMIDE"),
    )
    assert GATE_CODE in _gate_codes(result)


def test_g1514_path_c_alias_conjunctival_involvement_works():
    """H.G1514 — alias `conjunctival_involvement_documented` dispara Path C."""
    result = _evaluate(
        {"conjunctival_involvement_documented": "Sí"},
        treatments=_tx("ADT_APALUTAMIDE"),
    )
    assert GATE_CODE in _gate_codes(result)


# ───────────────────────────────────────────────
# §D — Path D: erythema multiforme documented (target lesions)
# ───────────────────────────────────────────────


def test_g1515_path_d_erythema_multiforme_fires():
    """H.G1515 — erythema_multiforme_documented dispara Path D (EM-major / SJS overlap)."""
    result = _evaluate(
        {"erythema_multiforme_documented": "Sí"},
        treatments=_tx("ADT_APALUTAMIDE"),
    )
    assert GATE_CODE in _gate_codes(result)


def test_g1516_path_d_alias_em_major_documented_works():
    """H.G1516 — alias `em_major_documented` dispara Path D."""
    result = _evaluate({"em_major_documented": "Sí"}, treatments=_tx("ADT_APALUTAMIDE"))
    assert GATE_CODE in _gate_codes(result)


def test_g1517_path_d_alias_target_lesions_documented_works():
    """H.G1517 — alias `target_lesions_documented` dispara Path D."""
    result = _evaluate(
        {"target_lesions_documented": "Sí"},
        treatments=_tx("ADT_APALUTAMIDE"),
    )
    assert GATE_CODE in _gate_codes(result)


# ───────────────────────────────────────────────
# §E — Path E: SJS/TEN explicit suspicion or diagnosis
# ───────────────────────────────────────────────


def test_g1518_path_e_sjs_ten_explicit_fires():
    """H.G1518 — sjs_ten_suspected_or_diagnosed dispara Path E (cualquier sospecha clínica)."""
    result = _evaluate(
        {"sjs_ten_suspected_or_diagnosed": "Sí"},
        treatments=_tx("ADT_APALUTAMIDE"),
    )
    assert GATE_CODE in _gate_codes(result)


def test_g1519_path_e_alias_stevens_johnson_syndrome_documented_works():
    """H.G1519 — alias `stevens_johnson_syndrome_documented` dispara Path E."""
    result = _evaluate(
        {"stevens_johnson_syndrome_documented": "Sí"},
        treatments=_tx("ADT_APALUTAMIDE"),
    )
    assert GATE_CODE in _gate_codes(result)


def test_g1520_path_e_alias_toxic_epidermal_necrolysis_documented_works():
    """H.G1520 — alias `toxic_epidermal_necrolysis_documented` dispara Path E."""
    result = _evaluate(
        {"toxic_epidermal_necrolysis_documented": "Sí"},
        treatments=_tx("ADT_APALUTAMIDE"),
    )
    assert GATE_CODE in _gate_codes(result)


def test_g1521_path_e_alias_scar_documented_for_apalutamide_works():
    """H.G1521 — alias `scar_documented_for_apalutamide` (SCAR genérico) dispara Path E."""
    result = _evaluate(
        {"scar_documented_for_apalutamide": "Sí"},
        treatments=_tx("ADT_APALUTAMIDE"),
    )
    assert GATE_CODE in _gate_codes(result)


# ───────────────────────────────────────────────
# §F — ⚠️ NO OVERRIDE (DISCONTINUACIÓN PERMANENTE per Erleada §5.2)
# ───────────────────────────────────────────────
# Esta sección valida arquitectónicamente que gate 42 NO tiene override
# definido en el YAML. Es un DISTINTIVO ESTRUCTURAL — sienta precedente
# para gates futuros con contraindicación absoluta irreversible.


def test_g1522_no_override_in_yaml_config():
    """H.G1522 — Gate 42 NO tiene override en YAML config (Erleada §5.2 mandate)."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files
    files = _load_yaml_files()
    config = files.get(GATE_CODE)
    assert config is not None, f"Gate {GATE_CODE} no encontrado en catálogo"
    assert config.get("override") is None, (
        "Gate 42 NO debe tener override per Erleada §5.2 — "
        "DISCONTINUACIÓN PERMANENTE absoluta irreversible"
    )


def test_g1523_no_override_field_recovers_gate_with_rash_g3():
    """H.G1523 — flags hipotéticos override-style NO desactivan gate 42 con rash G3."""
    result = _evaluate(
        {
            "rash_ctcae_grade": 3,
            "rash_resolved": "Sí",  # flag hipotético no existe
            "rash_recovered_for_apalutamide": "Sí",  # flag hipotético no existe
            "skin_recovered_for_apalutamide": "Sí",  # flag hipotético no existe
        },
        treatments=_tx("ADT_APALUTAMIDE"),
    )
    assert GATE_CODE in _gate_codes(result), (
        "Gate 42 NO debe desactivarse aunque flags override-style estén presentes"
    )


def test_g1524_no_override_field_recovers_gate_with_blistering():
    """H.G1524 — flags hipotéticos override NO desactivan gate 42 con blistering."""
    result = _evaluate(
        {
            "skin_blistering_documented": "Sí",
            "blistering_resolved": "Sí",  # flag hipotético no existe
            "skin_normalized_for_apalutamide": "Sí",  # flag hipotético no existe
        },
        treatments=_tx("ADT_APALUTAMIDE"),
    )
    assert GATE_CODE in _gate_codes(result)


def test_g1525_no_override_field_recovers_gate_with_sjs_ten():
    """H.G1525 — flags hipotéticos NO desactivan gate 42 con SJS/TEN diagnosed (caso más severo)."""
    result = _evaluate(
        {
            "sjs_ten_suspected_or_diagnosed": "Sí",
            "sjs_ten_resolved": "Sí",  # flag hipotético no existe
            "scar_recovered_for_apalutamide": "Sí",  # flag hipotético no existe
        },
        treatments=_tx("ADT_APALUTAMIDE"),
    )
    assert GATE_CODE in _gate_codes(result), (
        "SJS/TEN diagnosis = DISCONTINUACIÓN PERMANENTE per Erleada §5.2"
    )


# ───────────────────────────────────────────────
# §G — Regimen scoping (apalutamide-specific)
# ───────────────────────────────────────────────


@pytest.mark.parametrize("apa_code", ["ADT_APALUTAMIDE", "APALUTAMIDE"])
def test_g1526_apalutamide_regimens_filtered(apa_code):
    """H.G1526 — gates dispara y bloquea APALUTAMIDE regimens (filtered count = 0)."""
    result = _evaluate({"rash_ctcae_grade": 3}, treatments=_tx(apa_code))
    filt = result.get("filtered_treatments") or []
    assert len(filt) == 0, f"Apalutamida {apa_code} debe ser filtrada"


def test_g1527_enzalutamide_NOT_filtered_by_gate_42():
    """H.G1527 — ENZALUTAMIDE NO es filtrada por gate 42 (scope mismatch)."""
    result = _evaluate({"rash_ctcae_grade": 3}, treatments=_tx("ENZALUTAMIDE"))
    filt = result.get("filtered_treatments") or []
    assert len(filt) == 1, "Enzalutamida no debe ser filtrada por gate 42 (apa-specific)"


def test_g1528_darolutamide_NOT_filtered_by_gate_42():
    """H.G1528 — DAROLUTAMIDE NO es filtrada por gate 42 (scope mismatch)."""
    result = _evaluate({"rash_ctcae_grade": 3}, treatments=_tx("ADT_DAROLUTAMIDE"))
    filt = result.get("filtered_treatments") or []
    assert len(filt) == 1, "Darolutamida no debe ser filtrada por gate 42 (apa-specific)"


def test_g1529_abiraterone_NOT_filtered_by_gate_42():
    """H.G1529 — ABIRATERONE NO es filtrada por gate 42 (no-ARSI alternativa válida)."""
    result = _evaluate({"rash_ctcae_grade": 3}, treatments=_tx("ADT_ABIRATERONE"))
    filt = result.get("filtered_treatments") or []
    assert len(filt) == 1, "Abiraterona NO debe ser filtrada (no-ARSI alternativa)"


# ───────────────────────────────────────────────
# §H — Catálogo + clasificadores + integración + smoke E2E
# ───────────────────────────────────────────────


def test_g1530_gate_42_in_yaml_catalog():
    """H.G1530 — Gate 42 está en catálogo YAML cargado."""
    from prostanet.shared.pivotal_gates_yaml_loader import get_loaded_yaml_codes
    assert GATE_CODE in get_loaded_yaml_codes()


def test_g1531_gate_42_in_active_gate_codes():
    """H.G1531 — Gate 42 está en `get_active_gate_codes()` (Python+YAML híbrido)."""
    from prostanet.shared.algorithm_version import get_active_gate_codes
    assert GATE_CODE in get_active_gate_codes()


def test_g1532_total_gates_at_least_42():
    """H.G1532 — Total gates activos ≥42 (forward-compat con catálogo creciente)."""
    from prostanet.shared.algorithm_version import get_active_gate_codes
    assert len(get_active_gate_codes()) >= 42


def test_g1533_classifier_profile_compass_label():
    """H.G1533 — `_classify` en profile_compass.py retorna class label específico con citation."""
    from prostanet.domains.patient_tracking.profile_compass import (
        _build_pivotal_contraindication_gates_panel as _builder,
    )
    # Indirect test: pasamos raw_assessment con result_snapshot.pivotal_contraindication_gates
    # y verificamos que by_class contenga el class_label específico (sincronizado con
    # _GATE_EXACT_CLASSES en pivotal_gate_delta.py).
    raw_assessment = {
        "result_snapshot": {
            "pivotal_contraindication_gates": [{
                "code": GATE_CODE,
                "title": "test",
                "severity": "hard_block",
                "message": "test message",
                "evidence_tag": "x",
                "trial_refs": [],
            }],
        },
    }
    panel = _builder(raw_assessment)
    by_class = panel.get("by_class") or {}
    expected_label = "SJS/TEN apalutamida (Erleada §5.2 + SPARTAN/TITAN)"
    assert expected_label in by_class, (
        f"Class label '{expected_label}' debe estar en by_class — found: {list(by_class.keys())}"
    )


def test_g1534_classifier_pivotal_gate_delta_label():
    """H.G1534 — `_GATE_EXACT_CLASSES` en pivotal_gate_delta.py incluye label específico."""
    from prostanet.shared.pivotal_gate_delta import _GATE_EXACT_CLASSES
    expected_label = "SJS/TEN apalutamida (Erleada §5.2 + SPARTAN/TITAN)"
    assert _GATE_EXACT_CLASSES.get(GATE_CODE) == expected_label


def test_g1535_smoke_e2e_apalutamide_with_sjs_ten_complete():
    """H.G1535 — Smoke E2E: apalutamida + rash G4 + blistering + mucositis + SJS dx → gate dispara + apa filtrada + evidence_tag presente."""
    result = _evaluate(
        {
            "rash_ctcae_grade": 4,
            "skin_blistering_documented": "Sí",
            "mucosal_involvement_documented": "Sí",
            "erythema_multiforme_documented": "Sí",
            "sjs_ten_suspected_or_diagnosed": "Sí",
        },
        treatments=_tx("ADT_APALUTAMIDE"),
    )
    # Gate dispara
    assert GATE_CODE in _gate_codes(result)
    # Apalutamida filtrada (count = 0)
    filt = result.get("filtered_treatments") or []
    assert len(filt) == 0
    # Evidence tag presente
    gate_data = next((g for g in result["gates_triggered"] if g["code"] == GATE_CODE), None)
    assert gate_data is not None
    assert gate_data.get("evidence_tag") == "erleada_label_section_5_2_spartan_titan_sjs_ten_ctcae_v5"
    # Trial refs presentes
    refs = gate_data.get("trial_refs") or ()
    assert "SPARTAN" in refs
    assert "TITAN" in refs
    assert "Erleada label §5.2" in refs
    # Severity hard_block
    assert gate_data.get("severity") == "hard_block"
