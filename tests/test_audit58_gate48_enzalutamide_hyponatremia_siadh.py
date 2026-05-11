"""tests/test_audit58_gate48_enzalutamide_hyponatremia_siadh.py — Faubot 2026-04-25 (LIX).

Tests dedicados a Auditoría #58 — Gate 48 enzalutamida × hyponatremia/SIADH.

Cubre H.G1661 - H.G1700 (40 hipótesis) en 7 secciones:

§A — Path A: Na <125 mEq/L (CTCAE v5 G≥3 severo)
§B — Path B: Criterios SIADH compound (osm sérica <270 + osm urinaria >100 + euvolemia)
§C — Path C: Na <120 (CTCAE v5 G≥4 emergencia)
§D — Path D: flag clínico documentado
§E — Override (recovery + nephrology endorsement)
§F — Regimen scoping (enzalutamida-specific, NO apalutamida ni darolutamida)
§G — Aliases canónicos (sodio ES, na_serum, sodium_meq_l, etc.)
§H — Catálogo + clasificadores + integración + smoke E2E

🆕 PRIMER GATE DEL CATÁLOGO PARA ELECTRÓLITOS CRÍTICOS (Na/K).
Sienta arquitectura preparada para futuros gates electrólitos.
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


GATE_CODE = "enzalutamide_hyponatremia_siadh"


# ───────────────────────────────────────────────
# §A — Path A: Na <125 mEq/L (CTCAE G≥3 severo)
# ───────────────────────────────────────────────


@pytest.mark.parametrize("na_value", [124, 122, 120.5, 115, 110])
def test_g1661_path_a_sodium_below_125_fires(na_value):
    """H.G1661 — Na <125 dispara Path A (también activa Path C si <120)."""
    r = _evaluate({"sodium_serum": na_value}, treatments=_tx("ENZALUTAMIDE"))
    assert GATE_CODE in _gate_codes(r)


@pytest.mark.parametrize("na_value", [125, 130, 138, 142])
def test_g1662_path_a_sodium_ge_125_does_NOT_fire(na_value):
    """H.G1662 — Na ≥125 NO dispara Path A (boundary 125 NOT <125)."""
    r = _evaluate({"sodium_serum": na_value}, treatments=_tx("ENZALUTAMIDE"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1663_path_a_filters_enzalutamide_hard_block():
    """H.G1663 — gate 48 hard_block FILTRA enzalutamida (count=0)."""
    r = _evaluate({"sodium_serum": 122}, treatments=_tx("ENZALUTAMIDE"))
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 0, "Enzalutamida debe ser filtrada por gate 48 hard_block"


# ───────────────────────────────────────────────
# §B — Path B: Criterios SIADH compound (Bartter-Schwartz 1967)
# ───────────────────────────────────────────────


def test_g1664_path_b_siadh_compound_fires():
    """H.G1664 — SIADH compound (osm sérica <270 + osm urinaria >100 + euvolemia) dispara Path B."""
    r = _evaluate({
        "sodium_serum": 130,  # NOT <125 (path A no aplica)
        "serum_osmolality": 265,
        "urine_osmolality": 350,
        "euvolemia_documented_for_siadh": "Sí",
    }, treatments=_tx("ENZALUTAMIDE"))
    assert GATE_CODE in _gate_codes(r)


def test_g1665_path_b_missing_euvolemia_does_NOT_fire():
    """H.G1665 — Path B SIADH NO dispara sin euvolemia documentada (compound all_of)."""
    r = _evaluate({
        "sodium_serum": 130,
        "serum_osmolality": 265,
        "urine_osmolality": 350,
        # euvolemia_documented_for_siadh = ausente
    }, treatments=_tx("ENZALUTAMIDE"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1666_path_b_high_serum_osmolality_does_NOT_fire():
    """H.G1666 — Path B NO dispara con osmolaridad sérica normal (>=270)."""
    r = _evaluate({
        "sodium_serum": 130,
        "serum_osmolality": 285,  # normal
        "urine_osmolality": 350,
        "euvolemia_documented_for_siadh": "Sí",
    }, treatments=_tx("ENZALUTAMIDE"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1667_path_b_low_urine_osmolality_does_NOT_fire():
    """H.G1667 — Path B NO dispara con osmolaridad urinaria diluida (<=100, NO inadequada)."""
    r = _evaluate({
        "sodium_serum": 130,
        "serum_osmolality": 265,
        "urine_osmolality": 80,  # diluida apropiadamente — NO SIADH
        "euvolemia_documented_for_siadh": "Sí",
    }, treatments=_tx("ENZALUTAMIDE"))
    assert GATE_CODE not in _gate_codes(r)


# ───────────────────────────────────────────────
# §C — Path C: Na <120 (CTCAE v5 G≥4 emergencia)
# ───────────────────────────────────────────────


@pytest.mark.parametrize("na_value", [119, 115, 110, 105])
def test_g1668_path_c_sodium_below_120_fires(na_value):
    """H.G1668 — Na <120 dispara Path C (G4 emergencia neurológica)."""
    r = _evaluate({"sodium_serum": na_value}, treatments=_tx("ENZALUTAMIDE"))
    assert GATE_CODE in _gate_codes(r)


def test_g1669_path_c_boundary_120_does_NOT_fire_path_c_but_path_a_does():
    """H.G1669 — Na=120 NOT <120 (Path C no fires) pero <125 SÍ (Path A fires)."""
    r = _evaluate({"sodium_serum": 120}, treatments=_tx("ENZALUTAMIDE"))
    # Path A fires (Na <125)
    assert GATE_CODE in _gate_codes(r)


# ───────────────────────────────────────────────
# §D — Path D: flag clínico
# ───────────────────────────────────────────────


def test_g1670_path_d_siadh_documented_flag_fires():
    """H.G1670 — hyponatremia_siadh_documented_for_enzalutamide flag dispara Path D."""
    r = _evaluate({
        "hyponatremia_siadh_documented_for_enzalutamide": "Sí",
    }, treatments=_tx("ADT_ENZALUTAMIDE"))
    assert GATE_CODE in _gate_codes(r)


def test_g1671_path_d_alias_immune_siadh_works():
    """H.G1671 — alias `immune_siadh_for_enzalutamide` dispara Path D."""
    r = _evaluate({"immune_siadh_for_enzalutamide": "Sí"}, treatments=_tx("ENZALUTAMIDE"))
    assert GATE_CODE in _gate_codes(r)


def test_g1672_path_d_alias_enzalutamide_hyponatremia_documented_works():
    """H.G1672 — alias `enzalutamide_hyponatremia_documented` dispara Path D."""
    r = _evaluate({"enzalutamide_hyponatremia_documented": "Sí"}, treatments=_tx("ENZALUTAMIDE"))
    assert GATE_CODE in _gate_codes(r)


def test_g1673_path_d_falsy_does_NOT_fire():
    """H.G1673 — flag falsy NO dispara Path D."""
    r = _evaluate({"hyponatremia_siadh_documented_for_enzalutamide": "No"}, treatments=_tx("ENZALUTAMIDE"))
    assert GATE_CODE not in _gate_codes(r)


# ───────────────────────────────────────────────
# §E — Override (recovery + nephrology endorsement)
# ───────────────────────────────────────────────


def test_g1674_override_hyponatremia_resolved_disables():
    """H.G1674 — override `hyponatremia_resolved_for_enzalutamide=Sí` desactiva."""
    r = _evaluate({
        "sodium_serum": 122,
        "hyponatremia_resolved_for_enzalutamide": "Sí",
    }, treatments=_tx("ENZALUTAMIDE"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1675_override_alias_sodium_recovered_works():
    """H.G1675 — alias override `sodium_recovered_for_enzalutamide` desactiva."""
    r = _evaluate({
        "sodium_serum": 122,
        "sodium_recovered_for_enzalutamide": "Sí",
    }, treatments=_tx("ENZALUTAMIDE"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1676_override_alias_siadh_resolved_works():
    """H.G1676 — alias override `siadh_resolved_for_enzalutamide` desactiva."""
    r = _evaluate({
        "sodium_serum": 122,
        "siadh_resolved_for_enzalutamide": "Sí",
    }, treatments=_tx("ENZALUTAMIDE"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1677_override_does_NOT_apply_with_path_d_flag():
    """H.G1677 — override desactiva incluso con flag clínico Path D."""
    r = _evaluate({
        "hyponatremia_siadh_documented_for_enzalutamide": "Sí",
        "hyponatremia_resolved_for_enzalutamide": "Sí",
    }, treatments=_tx("ENZALUTAMIDE"))
    assert GATE_CODE not in _gate_codes(r)


# ───────────────────────────────────────────────
# §F — Regimen scoping (enzalutamida-specific)
# ───────────────────────────────────────────────


@pytest.mark.parametrize("enza_code", [
    "ENZALUTAMIDE", "ADT_ENZALUTAMIDE", "TALAZOPARIB_ENZALUTAMIDE", "ADT_TALAZO_ENZA_HRR",
])
def test_g1678_enzalutamide_regimens_filtered(enza_code):
    """H.G1678 — gate 48 filtra los 4 regímenes enzalutamida (count=0)."""
    r = _evaluate({"sodium_serum": 122}, treatments=_tx(enza_code))
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 0, f"Enzalutamida {enza_code} debe ser filtrada"


def test_g1679_apalutamide_NOT_filtered_by_gate_48():
    """H.G1679 — APALUTAMIDE NO es filtrada por gate 48 (scope enza-specific)."""
    r = _evaluate({"sodium_serum": 122}, treatments=_tx("APALUTAMIDE"))
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 1, "Apalutamida no debe filtrarse (gate 48 enza-specific)"


def test_g1680_darolutamide_NOT_filtered_by_gate_48():
    """H.G1680 — DAROLUTAMIDE NO es filtrada por gate 48 (perfil hyponatremia mínimo)."""
    r = _evaluate({"sodium_serum": 122}, treatments=_tx("ADT_DAROLUTAMIDE"))
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 1, "Darolutamida no debe filtrarse (perfil hyponatremia <0.3% G≥3)"


def test_g1681_abiraterone_NOT_filtered_by_gate_48():
    """H.G1681 — ABIRATERONE NO es filtrada por gate 48 (no-ARSI alternativa válida)."""
    r = _evaluate({"sodium_serum": 122}, treatments=_tx("ADT_ABIRATERONE"))
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 1


# ───────────────────────────────────────────────
# §G — Aliases canónicos (multi-idioma)
# ───────────────────────────────────────────────


@pytest.mark.parametrize("alias", [
    "sodium", "na_serum", "sodium_meq_l", "serum_na", "sodio",
])
def test_g1682_alias_for_sodium_works(alias):
    """H.G1682 — Aliases sodium (sodium, na_serum, sodium_meq_l, serum_na, sodio ES) dispara Path A."""
    r = _evaluate({alias: 122}, treatments=_tx("ENZALUTAMIDE"))
    assert GATE_CODE in _gate_codes(r)


def test_g1683_alias_serum_osmolarity_works():
    """H.G1683 — alias `serum_osmolarity` (sin -ity) dispara Path B."""
    r = _evaluate({
        "sodium_serum": 130,
        "serum_osmolarity": 265,
        "urine_osmolality": 350,
        "euvolemia_documented_for_siadh": "Sí",
    }, treatments=_tx("ENZALUTAMIDE"))
    assert GATE_CODE in _gate_codes(r)


def test_g1684_alias_osmolaridad_serica_es_works():
    """H.G1684 — alias `osmolaridad_serica` (ES) dispara Path B."""
    r = _evaluate({
        "sodium_serum": 130,
        "osmolaridad_serica": 265,
        "urine_osmolality": 350,
        "euvolemia_documented_for_siadh": "Sí",
    }, treatments=_tx("ENZALUTAMIDE"))
    assert GATE_CODE in _gate_codes(r)


def test_g1685_alias_euvolemia_present_works():
    """H.G1685 — alias `euvolemia_present` dispara Path B."""
    r = _evaluate({
        "sodium_serum": 130,
        "serum_osmolality": 265,
        "urine_osmolality": 350,
        "euvolemia_present": "Sí",
    }, treatments=_tx("ENZALUTAMIDE"))
    assert GATE_CODE in _gate_codes(r)


# ───────────────────────────────────────────────
# §H — Catálogo + clasificadores + integración + smoke E2E
# ───────────────────────────────────────────────


def test_g1686_gate_48_in_yaml_catalog():
    """H.G1686 — Gate 48 cargado en catálogo YAML."""
    from prostanet.shared.pivotal_gates_yaml_loader import get_loaded_yaml_codes
    assert GATE_CODE in get_loaded_yaml_codes()


def test_g1687_gate_48_in_active_codes():
    """H.G1687 — Gate 48 en `get_active_gate_codes()`."""
    from prostanet.shared.algorithm_version import get_active_gate_codes
    assert GATE_CODE in get_active_gate_codes()


def test_g1688_total_gates_at_least_48():
    """H.G1688 — Total gates activos ≥48."""
    from prostanet.shared.algorithm_version import get_active_gate_codes
    assert len(get_active_gate_codes()) >= 48


def test_g1689_classifier_pivotal_gate_delta_label():
    """H.G1689 — `_GATE_EXACT_CLASSES` incluye class label específico."""
    from prostanet.shared.pivotal_gate_delta import _GATE_EXACT_CLASSES
    label = _GATE_EXACT_CLASSES.get(GATE_CODE)
    assert label is not None
    assert "Hiponatremia" in label
    assert "SIADH" in label
    assert "PREVAIL" in label or "AFFIRM" in label


def test_g1690_classifier_profile_compass_label():
    """H.G1690 — profile_compass produce class label en by_class."""
    from prostanet.domains.patient_tracking.profile_compass import (
        _build_pivotal_contraindication_gates_panel as _builder,
    )
    raw_assessment = {
        "result_snapshot": {
            "pivotal_contraindication_gates": [{
                "code": GATE_CODE,
                "title": "x",
                "severity": "hard_block",
                "message": "x",
                "evidence_tag": "x",
                "trial_refs": [],
            }],
        },
    }
    panel = _builder(raw_assessment)
    by_class = panel.get("by_class") or {}
    assert any("Hiponatremia/SIADH enzalutamida" in label for label in by_class.keys()), (
        f"Class label 'Hiponatremia/SIADH enzalutamida' debe estar en by_class — "
        f"found: {list(by_class.keys())}"
    )


def test_g1691_evidence_tag_includes_prevail_affirm_bartter():
    """H.G1691 — evidence_tag cita PREVAIL+AFFIRM+Bartter-Schwartz."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files
    files = _load_yaml_files()
    config = files.get(GATE_CODE)
    assert config is not None
    et = config.get("evidence_tag", "").lower()
    assert "prevail" in et and "affirm" in et and "bartter_schwartz" in et


def test_g1692_severity_is_hard_block():
    """H.G1692 — Gate 48 severity='hard_block' (NO informacional como gate 47)."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files
    files = _load_yaml_files()
    config = files.get(GATE_CODE)
    assert config is not None
    assert config.get("severity") == "hard_block"


def test_g1693_smoke_e2e_full_siadh_panel():
    """H.G1693 — E2E paciente con SIADH completo (4 paths simultáneos) → gate fires + enza filtrada + evidence."""
    r = _evaluate({
        "sodium_serum": 118,  # Path A + Path C
        "serum_osmolality": 260,
        "urine_osmolality": 400,
        "euvolemia_documented_for_siadh": "Sí",  # Path B compound
        "hyponatremia_siadh_documented_for_enzalutamide": "Sí",  # Path D
    }, treatments=_tx("ENZALUTAMIDE"))
    # Gate fires
    assert GATE_CODE in _gate_codes(r)
    # Enzalutamida filtrada (count=0)
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 0
    # Evidence tag presente
    gate_data = next((g for g in r["gates_triggered"] if g["code"] == GATE_CODE), None)
    assert gate_data is not None
    assert "prevail" in gate_data.get("evidence_tag", "").lower()
    assert gate_data.get("severity") == "hard_block"


def test_g1694_smoke_e2e_healthy_enzalutamide_no_siadh():
    """H.G1694 — paciente sano en enza NO dispara gate 48."""
    r = _evaluate({
        "sodium_serum": 138,
        "serum_osmolality": 285,
        "urine_osmolality": 600,
        "euvolemia_documented_for_siadh": "No",
    }, treatments=_tx("ENZALUTAMIDE"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1695_coexistence_with_gate_47_psa_flare():
    """H.G1695 — gate 48 (hard_block) + gate 47 (soft_warning) coexisten en mismo paciente."""
    r = _evaluate({
        "sodium_serum": 122,  # gate 48
        "psa_flare_documented_first_month_arpi": "Sí",  # gate 47
    }, treatments=_tx("ENZALUTAMIDE"))
    codes = set(_gate_codes(r))
    assert GATE_CODE in codes
    assert "psa_flare_arpi_pseudoprogression" in codes
    # Gate 48 hard_block bloquea enza (gate 47 soft_warning no rescata)
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 0


def test_g1696_coexistence_with_gate_17_qtc_enzalutamide():
    """H.G1696 — gate 48 + gate 17 QTc coexisten (ambos hard_block, ambos enza-related)."""
    r = _evaluate({
        "sodium_serum": 122,
        "qtc_ms": 520,  # gate 17 enzalutamida QTc
    }, treatments=_tx("ENZALUTAMIDE"))
    codes = set(_gate_codes(r))
    assert GATE_CODE in codes
    assert "qtc_prolongation_grade3_for_enzalutamide" in codes
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 0


def test_g1697_coexistence_with_gate_19_arsi_cognitive():
    """H.G1697 — gate 48 + gate 19 ARSI cognitive coexisten (mismo paciente)."""
    r = _evaluate({
        "sodium_serum": 122,  # gate 48
        "cognitive_disturbance_ctcae_grade": 2,  # gate 19 (canonical field)
    }, treatments=_tx("ENZALUTAMIDE"))
    codes = set(_gate_codes(r))
    assert GATE_CODE in codes
    assert "arsi_in_cognitive_decline_grade2" in codes
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 0


def test_g1698_message_cites_pcwg3_alternatives():
    """H.G1698 — Mensaje gate 48 cita alternativas (apalutamida/darolutamida bajo perfil hyponatremia)."""
    r = _evaluate({"sodium_serum": 118}, treatments=_tx("ENZALUTAMIDE"))
    gate_data = next((g for g in r["gates_triggered"] if g["code"] == GATE_CODE), None)
    assert gate_data is not None
    msg = gate_data.get("message", "")
    assert "Apalutamida" in msg or "apalutamida" in msg.lower()
    assert "Darolutamida" in msg or "darolutamida" in msg.lower()
    assert "tolvaptán" in msg.lower() or "tolvaptan" in msg.lower()


def test_g1699_total_field_specs_includes_6_gate_48():
    """H.G1699 — 6 nuevos FieldSpecs (sodium + 2 osmolaridades + euvolemia + flag + override)."""
    from prostanet.shared.advanced_support_fields import pivotal_gate_supporting_fields
    fields = pivotal_gate_supporting_fields()
    field_names = {f.name for f in fields}
    expected = {
        "sodium_serum",
        "serum_osmolality",
        "urine_osmolality",
        "euvolemia_documented_for_siadh",
        "hyponatremia_siadh_documented_for_enzalutamide",
        "hyponatremia_resolved_for_enzalutamide",
    }
    assert expected.issubset(field_names), f"Missing FieldSpecs: {expected - field_names}"


def test_g1700_yaml_validation_passes():
    """H.G1700 — YAML config gate 48 pasa validación schema."""
    from prostanet.shared.pivotal_gates_yaml_loader import (
        _load_yaml_files,
        validate_yaml_gate_config,
    )
    files = _load_yaml_files()
    config = files.get(GATE_CODE)
    assert config is not None
    errors = validate_yaml_gate_config(config)
    assert errors == [], f"YAML validation errors: {errors}"
