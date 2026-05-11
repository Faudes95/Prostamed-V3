"""tests/test_audit65_gate51_onj_bone_targeted.py — Faubot 2026-04-25 (LXII).

Tests dedicados a Auditoría #65 — Gate 51 ONJ post-bisfos+denosumab AAOMS 2022.

Cubre H.G1786 - H.G1830 (45 hipótesis) en 8 secciones:

§A — Path A: ONJ explicit diagnosis flag (any AAOMS stage)
§B — Path B: hueso expuesto >8 sem compound (criterio AAOMS classic)
§C — Path C: AAOMS stage 2+ compound (3 conditions)
§D — Path D: ONJ stage 3 severo (emergencia quirúrgica)
§E — Override (resolución completa + dental clearance + endorsement)
§F — Regimen scoping (bone-targeted clase entera)
§G — Aliases multi-idioma (hueso_expuesto ES, mronj, dental)
§H — Catálogo + clasificadores + smoke E2E + coexistencia con gate 50

🆕 SEGUNDO gate del catálogo en categoría bone-targeted (post #64
hipocalcemia bone-targeted EXTENDIDA). Continúa categoría bone-modifying
agents iniciada en #64. Reusa REGIMEN_CODES_BONE_TARGETED (sin nueva
frozenset).
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


GATE_CODE = "bone_targeted_osteonecrosis_jaw"


# ───────────────────────────────────────────────
# §A — Path A: ONJ explicit diagnosis flag
# ───────────────────────────────────────────────


def test_g1786_path_a_onj_documented_flag_fires():
    """H.G1786 — osteonecrosis_jaw_documented flag dispara Path A."""
    r = _evaluate({"osteonecrosis_jaw_documented": "Sí"}, treatments=_tx("DENOSUMAB"))
    assert GATE_CODE in _gate_codes(r)


def test_g1787_path_a_alias_onj_documented_works():
    """H.G1787 — alias `onj_documented` dispara Path A."""
    r = _evaluate({"onj_documented": "Sí"}, treatments=_tx("ZOLEDRONATE"))
    assert GATE_CODE in _gate_codes(r)


def test_g1788_path_a_alias_mronj_documented_works():
    """H.G1788 — alias `mronj_documented` (Medication-Related ONJ) dispara Path A."""
    r = _evaluate({"mronj_documented": "Sí"}, treatments=_tx("XGEVA"))
    assert GATE_CODE in _gate_codes(r)


def test_g1789_path_a_alias_osteonecrosis_mandibula_es_works():
    """H.G1789 — alias `osteonecrosis_mandibula_documentada` (ES) dispara Path A."""
    r = _evaluate({"osteonecrosis_mandibula_documentada": "Sí"}, treatments=_tx("PAMIDRONATE"))
    assert GATE_CODE in _gate_codes(r)


def test_g1790_path_a_falsy_does_NOT_fire():
    """H.G1790 — ONJ flag falsy NO dispara Path A."""
    r = _evaluate({"osteonecrosis_jaw_documented": "No"}, treatments=_tx("DENOSUMAB"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1791_path_a_filters_denosumab_hard_block():
    """H.G1791 — gate 51 hard_block FILTRA denosumab (count=0)."""
    r = _evaluate({"osteonecrosis_jaw_documented": "Sí"}, treatments=_tx("DENOSUMAB"))
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 0


# ───────────────────────────────────────────────
# §B — Path B: hueso expuesto >8 sem compound (AAOMS classic)
# ───────────────────────────────────────────────


def test_g1792_path_b_compound_fires():
    """H.G1792 — hueso expuesto + duración >8 sem dispara Path B compound."""
    r = _evaluate({
        "oral_exposed_bone_documented": "Sí",
        "oral_exposed_bone_duration_weeks": 12,
    }, treatments=_tx("ZOLEDRONATE"))
    assert GATE_CODE in _gate_codes(r)


@pytest.mark.parametrize("weeks", [9, 10, 12, 16, 24])
def test_g1793_path_b_duration_above_8_fires(weeks):
    """H.G1793 — duración >8 sem dispara Path B (criterio AAOMS classic)."""
    r = _evaluate({
        "oral_exposed_bone_documented": "Sí",
        "oral_exposed_bone_duration_weeks": weeks,
    }, treatments=_tx("DENOSUMAB"))
    assert GATE_CODE in _gate_codes(r)


@pytest.mark.parametrize("weeks", [4, 6, 7, 8])
def test_g1794_path_b_duration_le_8_does_NOT_fire(weeks):
    """H.G1794 — duración ≤8 sem NO dispara Path B (boundary AAOMS — distingue de osteítis reactiva post-extracción)."""
    r = _evaluate({
        "oral_exposed_bone_documented": "Sí",
        "oral_exposed_bone_duration_weeks": weeks,
    }, treatments=_tx("DENOSUMAB"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1795_path_b_missing_exposed_bone_does_NOT_fire():
    """H.G1795 — Path B NO dispara sin hueso expuesto (compound all_of)."""
    r = _evaluate({
        "oral_exposed_bone_duration_weeks": 12,
        # oral_exposed_bone_documented = ausente
    }, treatments=_tx("DENOSUMAB"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1796_path_b_missing_duration_does_NOT_fire():
    """H.G1796 — Path B NO dispara sin duración documentada (compound all_of)."""
    r = _evaluate({
        "oral_exposed_bone_documented": "Sí",
        # oral_exposed_bone_duration_weeks = ausente
    }, treatments=_tx("DENOSUMAB"))
    assert GATE_CODE not in _gate_codes(r)


# ───────────────────────────────────────────────
# §C — Path C: AAOMS stage 2+ compound
# ───────────────────────────────────────────────


def test_g1797_path_c_compound_aaoms_stage_2_fires():
    """H.G1797 — Path C compound (hueso/fistula + síntomas + sin RT H&N) dispara."""
    r = _evaluate({
        "oral_exposed_bone_or_fistula_documented": "Sí",
        "jaw_pain_or_infection_symptoms_documented": "Sí",
        "no_prior_head_neck_radiation": "Sí",
    }, treatments=_tx("PAMIDRONATE"))
    assert GATE_CODE in _gate_codes(r)


def test_g1798_path_c_missing_bone_fistula_does_NOT_fire():
    """H.G1798 — Path C NO dispara sin hueso/fistula (compound all_of)."""
    r = _evaluate({
        "jaw_pain_or_infection_symptoms_documented": "Sí",
        "no_prior_head_neck_radiation": "Sí",
    }, treatments=_tx("DENOSUMAB"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1799_path_c_missing_symptoms_does_NOT_fire():
    """H.G1799 — Path C NO dispara sin síntomas mandibulares (compound all_of)."""
    r = _evaluate({
        "oral_exposed_bone_or_fistula_documented": "Sí",
        "no_prior_head_neck_radiation": "Sí",
    }, treatments=_tx("DENOSUMAB"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1800_path_c_with_prior_radiation_does_NOT_fire():
    """H.G1800 — Path C NO dispara con radiación H&N previa (descarta ONJ → osteorradionecrosis)."""
    r = _evaluate({
        "oral_exposed_bone_or_fistula_documented": "Sí",
        "jaw_pain_or_infection_symptoms_documented": "Sí",
        "no_prior_head_neck_radiation": "No",  # tiene RT H&N — NO ONJ
    }, treatments=_tx("DENOSUMAB"))
    assert GATE_CODE not in _gate_codes(r)


# ───────────────────────────────────────────────
# §D — Path D: ONJ stage 3 severo (emergencia)
# ───────────────────────────────────────────────


def test_g1801_path_d_onj_stage_3_fires():
    """H.G1801 — onj_stage_3_severe_documented dispara Path D (emergencia quirúrgica)."""
    r = _evaluate({"onj_stage_3_severe_documented": "Sí"}, treatments=_tx("XGEVA"))
    assert GATE_CODE in _gate_codes(r)


def test_g1802_path_d_alias_osteomielitis_es_works():
    """H.G1802 — alias `osteomielitis_mandibular_documentada` (ES) dispara Path D."""
    r = _evaluate({"osteomielitis_mandibular_documentada": "Sí"}, treatments=_tx("DENOSUMAB"))
    assert GATE_CODE in _gate_codes(r)


def test_g1803_path_d_alias_pathological_fracture_works():
    """H.G1803 — alias `mandibular_pathological_fracture_documented` dispara Path D."""
    r = _evaluate({"mandibular_pathological_fracture_documented": "Sí"}, treatments=_tx("ZOLEDRONATE"))
    assert GATE_CODE in _gate_codes(r)


# ───────────────────────────────────────────────
# §E — Override (resolución completa + dental clearance)
# ───────────────────────────────────────────────


def test_g1804_override_onj_resolved_disables():
    """H.G1804 — override `onj_resolved_for_bone_targeted=Sí` desactiva."""
    r = _evaluate({
        "osteonecrosis_jaw_documented": "Sí",
        "onj_resolved_for_bone_targeted": "Sí",
    }, treatments=_tx("DENOSUMAB"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1805_override_alias_osteonecrosis_jaw_resolved_works():
    """H.G1805 — alias override `osteonecrosis_jaw_resolved` desactiva."""
    r = _evaluate({
        "osteonecrosis_jaw_documented": "Sí",
        "osteonecrosis_jaw_resolved": "Sí",
    }, treatments=_tx("DENOSUMAB"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1806_override_alias_mronj_resolved_works():
    """H.G1806 — alias override `mronj_resolved` desactiva."""
    r = _evaluate({
        "osteonecrosis_jaw_documented": "Sí",
        "mronj_resolved": "Sí",
    }, treatments=_tx("DENOSUMAB"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1807_override_alias_aaoms_stage_0_documented_works():
    """H.G1807 — alias override `onj_aaoms_stage_0_documented` desactiva."""
    r = _evaluate({
        "osteonecrosis_jaw_documented": "Sí",
        "onj_aaoms_stage_0_documented": "Sí",
    }, treatments=_tx("DENOSUMAB"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1808_override_does_NOT_apply_with_path_b():
    """H.G1808 — override desactiva incluso con Path B compound trigger."""
    r = _evaluate({
        "oral_exposed_bone_documented": "Sí",
        "oral_exposed_bone_duration_weeks": 12,
        "onj_resolved_for_bone_targeted": "Sí",
    }, treatments=_tx("DENOSUMAB"))
    assert GATE_CODE not in _gate_codes(r)


# ───────────────────────────────────────────────
# §F — Regimen scoping (bone-targeted clase entera)
# ───────────────────────────────────────────────


@pytest.mark.parametrize("bone_code", [
    "DENOSUMAB", "XGEVA", "ZOLEDRONATE", "ZOMETA",
    "PAMIDRONATE", "ALENDRONATE", "FOSAMAX", "RISEDRONATE",
    "RADIUM_223", "LU177_PSMA617",
])
def test_g1809_bone_targeted_regimens_filtered(bone_code):
    """H.G1809 — gate 51 filtra TODOS los bone-targeted regimens."""
    r = _evaluate({"osteonecrosis_jaw_documented": "Sí"}, treatments=_tx(bone_code))
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 0, f"Bone-targeted {bone_code} debe ser filtrada"


def test_g1810_enzalutamide_NOT_filtered_by_gate_51():
    """H.G1810 — ENZALUTAMIDE NO es filtrada por gate 51 (no es bone-targeted)."""
    r = _evaluate({"osteonecrosis_jaw_documented": "Sí"}, treatments=_tx("ENZALUTAMIDE"))
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 1, "Enzalutamida no es bone-targeted, no debe filtrarse"


def test_g1811_apalutamide_NOT_filtered_by_gate_51():
    """H.G1811 — APALUTAMIDE NO es filtrada por gate 51."""
    r = _evaluate({"osteonecrosis_jaw_documented": "Sí"}, treatments=_tx("APALUTAMIDE"))
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 1


def test_g1812_abiraterone_NOT_filtered_by_gate_51():
    """H.G1812 — ABIRATERONE NO es filtrada por gate 51."""
    r = _evaluate({"osteonecrosis_jaw_documented": "Sí"}, treatments=_tx("ADT_ABIRATERONE"))
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 1


# ───────────────────────────────────────────────
# §G — Aliases multi-idioma
# ───────────────────────────────────────────────


def test_g1813_alias_hueso_expuesto_oral_es_works():
    """H.G1813 — alias `hueso_expuesto_oral` (ES) dispara Path B compound."""
    r = _evaluate({
        "hueso_expuesto_oral": "Sí",
        "oral_exposed_bone_duration_weeks": 12,
    }, treatments=_tx("DENOSUMAB"))
    assert GATE_CODE in _gate_codes(r)


def test_g1814_alias_duracion_exposicion_osea_es_works():
    """H.G1814 — alias `duracion_exposicion_osea_semanas` (ES) dispara Path B."""
    r = _evaluate({
        "oral_exposed_bone_documented": "Sí",
        "duracion_exposicion_osea_semanas": 12,
    }, treatments=_tx("DENOSUMAB"))
    assert GATE_CODE in _gate_codes(r)


def test_g1815_alias_dolor_mandibular_es_works():
    """H.G1815 — alias `dolor_mandibular_documentado` (ES) dispara Path C compound."""
    r = _evaluate({
        "oral_exposed_bone_or_fistula_documented": "Sí",
        "dolor_mandibular_documentado": "Sí",
        "no_prior_head_neck_radiation": "Sí",
    }, treatments=_tx("DENOSUMAB"))
    assert GATE_CODE in _gate_codes(r)


def test_g1816_alias_sin_radiacion_es_works():
    """H.G1816 — alias `sin_radiacion_cabeza_cuello_previa` (ES) dispara Path C."""
    r = _evaluate({
        "oral_exposed_bone_or_fistula_documented": "Sí",
        "jaw_pain_or_infection_symptoms_documented": "Sí",
        "sin_radiacion_cabeza_cuello_previa": "Sí",
    }, treatments=_tx("DENOSUMAB"))
    assert GATE_CODE in _gate_codes(r)


def test_g1817_alias_fistula_intraoral_extraoral_works():
    """H.G1817 — alias `fistula_intraoral_extraoral_documented` dispara Path C."""
    r = _evaluate({
        "fistula_intraoral_extraoral_documented": "Sí",
        "jaw_pain_or_infection_symptoms_documented": "Sí",
        "no_prior_head_neck_radiation": "Sí",
    }, treatments=_tx("DENOSUMAB"))
    assert GATE_CODE in _gate_codes(r)


# ───────────────────────────────────────────────
# §H — Catálogo + clasificadores + smoke E2E + coexistencia gate 50
# ───────────────────────────────────────────────


def test_g1818_gate_51_in_yaml_catalog():
    """H.G1818 — Gate 51 cargado en catálogo YAML."""
    from prostanet.shared.pivotal_gates_yaml_loader import get_loaded_yaml_codes
    assert GATE_CODE in get_loaded_yaml_codes()


def test_g1819_gate_51_in_active_codes():
    """H.G1819 — Gate 51 en `get_active_gate_codes()`."""
    from prostanet.shared.algorithm_version import get_active_gate_codes
    assert GATE_CODE in get_active_gate_codes()


def test_g1820_total_gates_at_least_51():
    """H.G1820 — Total gates activos ≥51."""
    from prostanet.shared.algorithm_version import get_active_gate_codes
    assert len(get_active_gate_codes()) >= 51


def test_g1821_classifier_pivotal_gate_delta_label():
    """H.G1821 — `_GATE_EXACT_CLASSES` incluye class label específico."""
    from prostanet.shared.pivotal_gate_delta import _GATE_EXACT_CLASSES
    label = _GATE_EXACT_CLASSES.get(GATE_CODE)
    assert label is not None
    assert "ONJ" in label
    assert "AAOMS" in label or "ASCO" in label


def test_g1822_classifier_profile_compass_label():
    """H.G1822 — profile_compass produce class label en by_class."""
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
    assert any("ONJ" in label for label in by_class.keys()), (
        f"Class label 'ONJ' debe estar en by_class — found: {list(by_class.keys())}"
    )


def test_g1823_evidence_tag_includes_aaoms_asco():
    """H.G1823 — evidence_tag cita AAOMS 2022 + ASCO Bone Health 2024."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files
    files = _load_yaml_files()
    config = files.get(GATE_CODE)
    assert config is not None
    et = config.get("evidence_tag", "").lower()
    assert "aaoms" in et and "asco_bone_health" in et


def test_g1824_severity_is_hard_block():
    """H.G1824 — Gate 51 severity='hard_block' (NO informacional)."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files
    files = _load_yaml_files()
    config = files.get(GATE_CODE)
    assert config is not None
    assert config.get("severity") == "hard_block"


def test_g1825_smoke_e2e_full_onj_panel():
    """H.G1825 — E2E paciente con ONJ stage 3 (4 paths) → gate fires + denosumab filtrado + evidence."""
    r = _evaluate({
        "osteonecrosis_jaw_documented": "Sí",  # Path A
        "oral_exposed_bone_documented": "Sí",
        "oral_exposed_bone_duration_weeks": 16,  # Path B compound
        "oral_exposed_bone_or_fistula_documented": "Sí",
        "jaw_pain_or_infection_symptoms_documented": "Sí",
        "no_prior_head_neck_radiation": "Sí",  # Path C compound
        "onj_stage_3_severe_documented": "Sí",  # Path D
    }, treatments=_tx("DENOSUMAB"))
    # Gate fires
    assert GATE_CODE in _gate_codes(r)
    # Denosumab filtrado (count=0)
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 0
    # Evidence tag presente
    gate_data = next((g for g in r["gates_triggered"] if g["code"] == GATE_CODE), None)
    assert gate_data is not None
    assert "aaoms" in gate_data.get("evidence_tag", "").lower()
    assert gate_data.get("severity") == "hard_block"


def test_g1826_smoke_e2e_healthy_denosumab_no_onj():
    """H.G1826 — paciente sano en denosumab NO dispara gate 51."""
    r = _evaluate({
        "osteonecrosis_jaw_documented": "No",
        "oral_exposed_bone_documented": "No",
    }, treatments=_tx("DENOSUMAB"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1827_coexistence_gate_50_hipocalcemia_and_gate_51_onj():
    """H.G1827 — Mismo paciente bone-targeted con hipocalcemia + ONJ activa AMBOS gates 50 + 51."""
    r = _evaluate({
        "corrected_calcium": 7.5,  # gate 50
        "osteonecrosis_jaw_documented": "Sí",  # gate 51
    }, treatments=_tx("DENOSUMAB"))
    codes = set(_gate_codes(r))
    assert "bone_targeted_hypocalcemia_extended" in codes  # gate 50
    assert GATE_CODE in codes  # gate 51


def test_g1828_message_cites_aaoms_staging_dental_clearance():
    """H.G1828 — Mensaje gate 51 cita AAOMS staging + dental clearance pre-inicio."""
    r = _evaluate({"osteonecrosis_jaw_documented": "Sí"}, treatments=_tx("DENOSUMAB"))
    gate_data = next((g for g in r["gates_triggered"] if g["code"] == GATE_CODE), None)
    assert gate_data is not None
    msg = gate_data.get("message", "")
    assert "AAOMS" in msg
    assert "dental clearance" in msg.lower() or "dental" in msg.lower()
    assert "stage" in msg.lower()


def test_g1829_total_field_specs_includes_8_gate_51():
    """H.G1829 — 8 nuevos FieldSpecs (1 dx flag + 2 Path B + 3 Path C + 1 stage 3 + 1 override)."""
    from prostanet.shared.advanced_support_fields import pivotal_gate_supporting_fields
    fields = pivotal_gate_supporting_fields()
    field_names = {f.name for f in fields}
    expected = {
        "osteonecrosis_jaw_documented",
        "oral_exposed_bone_documented",
        "oral_exposed_bone_duration_weeks",
        "oral_exposed_bone_or_fistula_documented",
        "jaw_pain_or_infection_symptoms_documented",
        "no_prior_head_neck_radiation",
        "onj_stage_3_severe_documented",
        "onj_resolved_for_bone_targeted",
    }
    assert expected.issubset(field_names), f"Missing FieldSpecs: {expected - field_names}"


def test_g1830_yaml_validation_passes():
    """H.G1830 — YAML config gate 51 pasa validación schema."""
    from prostanet.shared.pivotal_gates_yaml_loader import (
        _load_yaml_files,
        validate_yaml_gate_config,
    )
    files = _load_yaml_files()
    config = files.get(GATE_CODE)
    assert config is not None
    errors = validate_yaml_gate_config(config)
    assert errors == [], f"YAML validation errors: {errors}"
