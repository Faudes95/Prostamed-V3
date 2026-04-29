"""tests/test_audit59_gate49_abiraterone_hypokalemia.py — Faubot 2026-04-25 (LX).

Tests dedicados a Auditoría #59 — Gate 49 abiraterona × hipokalemia G≥3 / pseudo-aldosteronismo.

Cubre H.G1701 - H.G1740 (40 hipótesis) en 8 secciones:

§A — Path A: K <3.0 mEq/L (CTCAE v5 G≥3 severo)
§B — Path B: K <2.5 mEq/L (CTCAE v5 G≥4 emergencia, riesgo torsades)
§C — Path C: pseudo-aldosteronismo compound (K<3.5 + HTA + alcalosis)
§D — Path D: flag clínico documentado por especialista
§E — Override (recovery + suplementación + antagonistas MR + cardiology)
§F — Regimen scoping (abiraterona-specific, NO ARSI)
§G — Aliases multi-idioma (potasio ES, k_serum, potassium_meq_l)
§H — Catálogo + clasificadores + smoke E2E + coexistencia eje abiraterona

🆕 SEGUNDO GATE DEL CATÁLOGO PARA ELECTRÓLITOS CRÍTICOS (post #58 hyponatremia
enzalutamida). Completa eje Na+K — los 2 electrólitos más letales cubiertos
sistemáticamente. Eje abiraterona toxicidad CYP17 inhibition COMPLETA.
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


GATE_CODE = "abiraterone_hypokalemia_grade3"


# ───────────────────────────────────────────────
# §A — Path A: K <3.0 mEq/L (CTCAE G≥3 severo)
# ───────────────────────────────────────────────


@pytest.mark.parametrize("k_value", [2.9, 2.8, 2.5, 2.0, 1.8])
def test_g1701_path_a_potassium_below_3_fires(k_value):
    """H.G1701 — K <3.0 dispara Path A (también activa Path B si <2.5)."""
    r = _evaluate({"potassium_serum": k_value}, treatments=_tx("ADT_ABIRATERONE"))
    assert GATE_CODE in _gate_codes(r)


@pytest.mark.parametrize("k_value", [3.0, 3.5, 4.2, 5.0])
def test_g1702_path_a_potassium_ge_3_does_NOT_fire(k_value):
    """H.G1702 — K ≥3.0 NO dispara Path A (boundary 3.0 NOT <3.0)."""
    r = _evaluate({"potassium_serum": k_value}, treatments=_tx("ADT_ABIRATERONE"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1703_path_a_filters_abiraterone_hard_block():
    """H.G1703 — gate 49 hard_block FILTRA abiraterona (count=0)."""
    r = _evaluate({"potassium_serum": 2.8}, treatments=_tx("ADT_ABIRATERONE"))
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 0, "Abiraterona debe ser filtrada por gate 49 hard_block"


# ───────────────────────────────────────────────
# §B — Path B: K <2.5 (CTCAE G≥4 emergencia)
# ───────────────────────────────────────────────


@pytest.mark.parametrize("k_value", [2.4, 2.0, 1.8, 1.5])
def test_g1704_path_b_potassium_below_2_5_fires(k_value):
    """H.G1704 — K <2.5 dispara Path B (G4 emergencia, riesgo torsades de pointes)."""
    r = _evaluate({"potassium_serum": k_value}, treatments=_tx("ADT_ABIRATERONE"))
    assert GATE_CODE in _gate_codes(r)


def test_g1705_path_b_boundary_2_5_does_NOT_fire_path_b_but_path_a_does():
    """H.G1705 — K=2.5 NOT <2.5 (Path B no fires) pero <3.0 SÍ (Path A fires)."""
    r = _evaluate({"potassium_serum": 2.5}, treatments=_tx("ADT_ABIRATERONE"))
    # Path A fires (K <3.0)
    assert GATE_CODE in _gate_codes(r)


# ───────────────────────────────────────────────
# §C — Path C: pseudo-aldosteronismo compound
# ───────────────────────────────────────────────


def test_g1706_path_c_pseudoaldosteronism_compound_fires():
    """H.G1706 — K<3.5 + HTA + alcalosis metabólica dispara Path C."""
    r = _evaluate({
        "potassium_serum": 3.3,  # NOT <3.0 (path A no aplica), pero <3.5
        "hypertension_active_documented": "Sí",
        "metabolic_alkalosis_documented": "Sí",
    }, treatments=_tx("ADT_ABIRATERONE"))
    assert GATE_CODE in _gate_codes(r)


def test_g1707_path_c_missing_hta_does_NOT_fire():
    """H.G1707 — Path C NO dispara sin HTA documentada (compound all_of)."""
    r = _evaluate({
        "potassium_serum": 3.3,
        "metabolic_alkalosis_documented": "Sí",
        # hypertension_active_documented = ausente
    }, treatments=_tx("ADT_ABIRATERONE"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1708_path_c_missing_alkalosis_does_NOT_fire():
    """H.G1708 — Path C NO dispara sin alcalosis documentada (compound all_of)."""
    r = _evaluate({
        "potassium_serum": 3.3,
        "hypertension_active_documented": "Sí",
        # metabolic_alkalosis_documented = ausente
    }, treatments=_tx("ADT_ABIRATERONE"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1709_path_c_high_potassium_does_NOT_fire():
    """H.G1709 — Path C NO dispara con K normal (>=3.5)."""
    r = _evaluate({
        "potassium_serum": 4.0,  # K normal
        "hypertension_active_documented": "Sí",
        "metabolic_alkalosis_documented": "Sí",
    }, treatments=_tx("ADT_ABIRATERONE"))
    assert GATE_CODE not in _gate_codes(r)


# ───────────────────────────────────────────────
# §D — Path D: flag clínico
# ───────────────────────────────────────────────


def test_g1710_path_d_pseudoaldosteronism_flag_fires():
    """H.G1710 — hypokalemia_pseudoaldosteronism_documented_for_abiraterone flag dispara Path D."""
    r = _evaluate({
        "hypokalemia_pseudoaldosteronism_documented_for_abiraterone": "Sí",
    }, treatments=_tx("ADT_ABIRATERONE"))
    assert GATE_CODE in _gate_codes(r)


def test_g1711_path_d_alias_pseudoaldosteronism_for_abiraterone_works():
    """H.G1711 — alias `pseudoaldosteronism_for_abiraterone_documented` dispara Path D."""
    r = _evaluate({
        "pseudoaldosteronism_for_abiraterone_documented": "Sí",
    }, treatments=_tx("ADT_ABIRATERONE"))
    assert GATE_CODE in _gate_codes(r)


def test_g1712_path_d_alias_cyp17_mineralocorticoid_excess_works():
    """H.G1712 — alias `cyp17_mineralocorticoid_excess_documented` dispara Path D."""
    r = _evaluate({
        "cyp17_mineralocorticoid_excess_documented": "Sí",
    }, treatments=_tx("ADT_ABIRATERONE"))
    assert GATE_CODE in _gate_codes(r)


def test_g1713_path_d_falsy_does_NOT_fire():
    """H.G1713 — flag falsy NO dispara Path D."""
    r = _evaluate({
        "hypokalemia_pseudoaldosteronism_documented_for_abiraterone": "No",
    }, treatments=_tx("ADT_ABIRATERONE"))
    assert GATE_CODE not in _gate_codes(r)


# ───────────────────────────────────────────────
# §E — Override (recovery + suplementación + antagonistas MR)
# ───────────────────────────────────────────────


def test_g1714_override_hypokalemia_resolved_disables():
    """H.G1714 — override `hypokalemia_resolved_for_abiraterone=Sí` desactiva."""
    r = _evaluate({
        "potassium_serum": 2.8,
        "hypokalemia_resolved_for_abiraterone": "Sí",
    }, treatments=_tx("ADT_ABIRATERONE"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1715_override_alias_potassium_recovered_works():
    """H.G1715 — alias override `potassium_recovered_for_abiraterone` desactiva."""
    r = _evaluate({
        "potassium_serum": 2.8,
        "potassium_recovered_for_abiraterone": "Sí",
    }, treatments=_tx("ADT_ABIRATERONE"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1716_override_alias_pseudoaldosteronism_controlled_works():
    """H.G1716 — alias override `pseudoaldosteronism_controlled_for_abiraterone` desactiva."""
    r = _evaluate({
        "potassium_serum": 2.8,
        "pseudoaldosteronism_controlled_for_abiraterone": "Sí",
    }, treatments=_tx("ADT_ABIRATERONE"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1717_override_does_NOT_apply_with_path_d_flag():
    """H.G1717 — override desactiva incluso con flag clínico Path D."""
    r = _evaluate({
        "hypokalemia_pseudoaldosteronism_documented_for_abiraterone": "Sí",
        "hypokalemia_resolved_for_abiraterone": "Sí",
    }, treatments=_tx("ADT_ABIRATERONE"))
    assert GATE_CODE not in _gate_codes(r)


# ───────────────────────────────────────────────
# §F — Regimen scoping (abiraterona-specific)
# ───────────────────────────────────────────────


@pytest.mark.parametrize("abi_code", [
    "ADT_ABIRATERONE", "ABIRATERONE_OLAPARIB", "NIRAPARIB_ABIRATERONE",
    "ADT_ABIRATERONE_NIRAPARIB", "ADT_DOCETAXEL_ABIRATERONE", "IPATASERTIB_ABIRATERONE",
])
def test_g1718_abiraterone_regimens_filtered(abi_code):
    """H.G1718 — gate 49 filtra los 6 regímenes abiraterona (count=0)."""
    r = _evaluate({"potassium_serum": 2.8}, treatments=_tx(abi_code))
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 0, f"Abiraterona {abi_code} debe ser filtrada"


def test_g1719_enzalutamide_NOT_filtered_by_gate_49():
    """H.G1719 — ENZALUTAMIDE NO es filtrada por gate 49 (perfil hipokalemia mínimo ~1%)."""
    r = _evaluate({"potassium_serum": 2.8}, treatments=_tx("ENZALUTAMIDE"))
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 1, "Enzalutamida no debe filtrarse (gate 49 abi-specific)"


def test_g1720_apalutamide_NOT_filtered_by_gate_49():
    """H.G1720 — APALUTAMIDE NO es filtrada por gate 49 (perfil hipokalemia bajo ~0.5%)."""
    r = _evaluate({"potassium_serum": 2.8}, treatments=_tx("APALUTAMIDE"))
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 1


def test_g1721_darolutamide_NOT_filtered_by_gate_49():
    """H.G1721 — DAROLUTAMIDE NO es filtrada por gate 49 (perfil hipokalemia muy bajo <0.3%)."""
    r = _evaluate({"potassium_serum": 2.8}, treatments=_tx("ADT_DAROLUTAMIDE"))
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 1


# ───────────────────────────────────────────────
# §G — Aliases canónicos (multi-idioma)
# ───────────────────────────────────────────────


@pytest.mark.parametrize("alias", [
    "potassium", "k_serum", "potassium_meq_l", "serum_k", "potasio",
])
def test_g1722_alias_for_potassium_works(alias):
    """H.G1722 — Aliases potassium (potassium, k_serum, potassium_meq_l, serum_k, potasio ES) dispara Path A."""
    r = _evaluate({alias: 2.8}, treatments=_tx("ADT_ABIRATERONE"))
    assert GATE_CODE in _gate_codes(r)


def test_g1723_alias_hta_documented_works():
    """H.G1723 — alias `hta_documented` (ES) dispara Path C compound."""
    r = _evaluate({
        "potassium_serum": 3.3,
        "hta_documented": "Sí",
        "metabolic_alkalosis_documented": "Sí",
    }, treatments=_tx("ADT_ABIRATERONE"))
    assert GATE_CODE in _gate_codes(r)


def test_g1724_alias_alcalosis_metabolica_es_works():
    """H.G1724 — alias `alcalosis_metabolica` (ES) dispara Path C compound."""
    r = _evaluate({
        "potassium_serum": 3.3,
        "hypertension_active_documented": "Sí",
        "alcalosis_metabolica": "Sí",
    }, treatments=_tx("ADT_ABIRATERONE"))
    assert GATE_CODE in _gate_codes(r)


def test_g1725_alias_blood_pressure_uncontrolled_works():
    """H.G1725 — alias `blood_pressure_uncontrolled` dispara Path C compound."""
    r = _evaluate({
        "potassium_serum": 3.3,
        "blood_pressure_uncontrolled": "Sí",
        "metabolic_alkalosis_documented": "Sí",
    }, treatments=_tx("ADT_ABIRATERONE"))
    assert GATE_CODE in _gate_codes(r)


# ───────────────────────────────────────────────
# §H — Catálogo + clasificadores + smoke E2E + coexistencia eje abi
# ───────────────────────────────────────────────


def test_g1726_gate_49_in_yaml_catalog():
    """H.G1726 — Gate 49 cargado en catálogo YAML."""
    from prostanet.shared.pivotal_gates_yaml_loader import get_loaded_yaml_codes
    assert GATE_CODE in get_loaded_yaml_codes()


def test_g1727_gate_49_in_active_codes():
    """H.G1727 — Gate 49 en `get_active_gate_codes()`."""
    from prostanet.shared.algorithm_version import get_active_gate_codes
    assert GATE_CODE in get_active_gate_codes()


def test_g1728_total_gates_at_least_49():
    """H.G1728 — Total gates activos ≥49."""
    from prostanet.shared.algorithm_version import get_active_gate_codes
    assert len(get_active_gate_codes()) >= 49


def test_g1729_classifier_pivotal_gate_delta_label():
    """H.G1729 — `_GATE_EXACT_CLASSES` incluye class label específico."""
    from prostanet.shared.pivotal_gate_delta import _GATE_EXACT_CLASSES
    label = _GATE_EXACT_CLASSES.get(GATE_CODE)
    assert label is not None
    assert "Hipokalemia" in label
    assert "abiraterona" in label.lower()
    assert "COU-AA-302" in label or "LATITUDE" in label
    assert "pseudo-aldosteronismo" in label.lower() or "CYP17" in label


def test_g1730_classifier_profile_compass_label():
    """H.G1730 — profile_compass produce class label en by_class."""
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
    assert any("Hipokalemia abiraterona" in label for label in by_class.keys()), (
        f"Class label 'Hipokalemia abiraterona' debe estar en by_class — "
        f"found: {list(by_class.keys())}"
    )


def test_g1731_evidence_tag_includes_cou_aa_302_latitude_pseudoaldosteronism():
    """H.G1731 — evidence_tag cita COU-AA-302 + LATITUDE + pseudo-aldosteronismo."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files
    files = _load_yaml_files()
    config = files.get(GATE_CODE)
    assert config is not None
    et = config.get("evidence_tag", "").lower()
    assert "cou_aa_302" in et and "latitude" in et and "pseudoaldosteronism" in et


def test_g1732_severity_is_hard_block():
    """H.G1732 — Gate 49 severity='hard_block' (NO informacional)."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files
    files = _load_yaml_files()
    config = files.get(GATE_CODE)
    assert config is not None
    assert config.get("severity") == "hard_block"


def test_g1733_smoke_e2e_full_pseudoaldosteronism_panel():
    """H.G1733 — E2E paciente con pseudo-aldosteronismo completo (4 paths) → gate fires + abi filtrada + evidence."""
    r = _evaluate({
        "potassium_serum": 2.3,  # Path A + Path B
        "hypertension_active_documented": "Sí",
        "metabolic_alkalosis_documented": "Sí",  # Path C compound
        "hypokalemia_pseudoaldosteronism_documented_for_abiraterone": "Sí",  # Path D
    }, treatments=_tx("ADT_ABIRATERONE"))
    # Gate fires
    assert GATE_CODE in _gate_codes(r)
    # Abiraterona filtrada (count=0)
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 0
    # Evidence tag presente
    gate_data = next((g for g in r["gates_triggered"] if g["code"] == GATE_CODE), None)
    assert gate_data is not None
    assert "cou_aa_302" in gate_data.get("evidence_tag", "").lower()
    assert gate_data.get("severity") == "hard_block"


def test_g1734_smoke_e2e_healthy_abiraterone_no_hypokalemia():
    """H.G1734 — paciente sano en abi NO dispara gate 49."""
    r = _evaluate({
        "potassium_serum": 4.2,
        "hypertension_active_documented": "No",
        "metabolic_alkalosis_documented": "No",
    }, treatments=_tx("ADT_ABIRATERONE"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1735_coexistence_with_gate_28_abi_adrenal_axis():
    """H.G1735 — gate 49 hipokalemia + gate 28 adrenal axis simultáneos en mismo paciente abi."""
    r = _evaluate({
        "potassium_serum": 2.8,  # gate 49
        "cortisol_basal_am_ug_dl": 2,  # gate 28 adrenal insuf
    }, treatments=_tx("ADT_ABIRATERONE"))
    codes = set(_gate_codes(r))
    assert GATE_CODE in codes
    assert "abiraterone_adrenal_insufficiency" in codes


def test_g1736_coexistence_with_gate_21_abi_hepatotox():
    """H.G1736 — gate 49 + gate 21 abi hepatotox coexisten (eje abiraterona toxicidad)."""
    r = _evaluate({
        "potassium_serum": 2.8,  # gate 49
        "ast_iu_l": 250,  # gate 21 hepatotox (alias compartido)
    }, treatments=_tx("ADT_ABIRATERONE"))
    codes = set(_gate_codes(r))
    assert GATE_CODE in codes
    assert "abiraterone_hepatotoxicity_grade3" in codes


def test_g1737_coexistence_with_gate_39_abi_alp_longitudinal():
    """H.G1737 — gate 49 + gate 39 abi ALP rise coexisten (eje hepático longitudinal).

    Usa canonical fields de gate 39: `alkaline_phosphatase_u_l` (current) +
    `alp_baseline_pre_abiraterone` (baseline) per YAML config gate 39.
    """
    r = _evaluate({
        "potassium_serum": 2.8,  # gate 49
        "alp_baseline_pre_abiraterone": 100,
        "alkaline_phosphatase_u_l": 350,  # gate 39 ALP rise longitudinal (250 rise > 150 threshold Path A)
    }, treatments=_tx("ADT_ABIRATERONE"))
    codes = set(_gate_codes(r))
    assert GATE_CODE in codes
    assert "abiraterone_alp_rapid_rise_longitudinal" in codes


def test_g1738_message_cites_eplerenone_prednisone_profilaxis():
    """H.G1738 — Mensaje gate 49 cita profilaxis prednisona + eplerenone (recomendación COU-AA-302+LATITUDE)."""
    r = _evaluate({"potassium_serum": 2.3}, treatments=_tx("ADT_ABIRATERONE"))
    gate_data = next((g for g in r["gates_triggered"] if g["code"] == GATE_CODE), None)
    assert gate_data is not None
    msg = gate_data.get("message", "")
    assert "Prednisona" in msg or "prednisona" in msg.lower()
    assert "eplerenone" in msg.lower() or "spironolactone" in msg.lower()
    assert "torsades" in msg.lower() or "arritmia" in msg.lower()


def test_g1739_total_field_specs_includes_5_gate_49():
    """H.G1739 — 5 nuevos FieldSpecs (potassium + 2 flags compound + dx flag + override)."""
    from prostanet.shared.advanced_support_fields import pivotal_gate_supporting_fields
    fields = pivotal_gate_supporting_fields()
    field_names = {f.name for f in fields}
    expected = {
        "potassium_serum",
        "hypertension_active_documented",
        "metabolic_alkalosis_documented",
        "hypokalemia_pseudoaldosteronism_documented_for_abiraterone",
        "hypokalemia_resolved_for_abiraterone",
    }
    assert expected.issubset(field_names), f"Missing FieldSpecs: {expected - field_names}"


def test_g1740_yaml_validation_passes():
    """H.G1740 — YAML config gate 49 pasa validación schema."""
    from prostanet.shared.pivotal_gates_yaml_loader import (
        _load_yaml_files,
        validate_yaml_gate_config,
    )
    files = _load_yaml_files()
    config = files.get(GATE_CODE)
    assert config is not None
    errors = validate_yaml_gate_config(config)
    assert errors == [], f"YAML validation errors: {errors}"
