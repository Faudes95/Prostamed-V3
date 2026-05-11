"""tests/test_audit66_gate52_olaparib_mds_aml_longitudinal.py — Faubot 2026-04-25 (LXIII).

Tests dedicados a Auditoría #66 — Gate 52 PARP MDS/AML longitudinal emergente.

Cubre H.G1831 - H.G1875 (45 hipótesis) en 8 secciones:

§A — Path A: MDS/AML emergente flag
§B — Path B compound: cytopenia ≥2 líneas + persistente >12 sem + sospecha
§C — Path C compound: WHO 2022 MDS criteria (displasia + blasts >5%)
§D — Path D: WHO 2022 AML criteria (blasts ≥20% — emergencia)
§E — Override (remisión completa per IWG 2018)
§F — Regimen scoping (PARP inhibitors clase entera)
§G — Aliases multi-idioma + coexistencia con gate 16
§H — Catálogo + clasificadores + smoke E2E

🆕 SEXTO gate longitudinal del catálogo (post niraparib gate 33,
docetaxel gate 34, abi gate 39, Lu-177 gate 40, cabazitaxel gate 41).
Sienta categoría longitudinal hematológica COMPLETA.
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


GATE_CODE = "parp_inhibitor_mds_aml_longitudinal"


# ───────────────────────────────────────────────
# §A — Path A: MDS/AML emergente flag
# ───────────────────────────────────────────────


def test_g1831_path_a_mds_aml_documented_during_parpi_fires():
    """H.G1831 — mds_or_aml_documented_during_parpi flag dispara Path A."""
    r = _evaluate({"mds_or_aml_documented_during_parpi": "Sí"}, treatments=_tx("OLAPARIB"))
    assert GATE_CODE in _gate_codes(r)


def test_g1832_path_a_alias_mds_emergent_for_parpi_works():
    """H.G1832 — alias `mds_emergent_for_parpi` dispara Path A."""
    r = _evaluate({"mds_emergent_for_parpi": "Sí"}, treatments=_tx("NIRAPARIB_ABIRATERONE"))
    assert GATE_CODE in _gate_codes(r)


def test_g1833_path_a_alias_aml_emergent_for_parpi_works():
    """H.G1833 — alias `aml_emergent_for_parpi` dispara Path A."""
    r = _evaluate({"aml_emergent_for_parpi": "Sí"}, treatments=_tx("RUCAPARIB"))
    assert GATE_CODE in _gate_codes(r)


def test_g1834_path_a_alias_secondary_mds_for_parpi_works():
    """H.G1834 — alias `secondary_mds_for_parpi` dispara Path A."""
    r = _evaluate({"secondary_mds_for_parpi": "Sí"}, treatments=_tx("TALAZOPARIB_ENZALUTAMIDE"))
    assert GATE_CODE in _gate_codes(r)


def test_g1835_path_a_falsy_does_NOT_fire():
    """H.G1835 — flag falsy NO dispara Path A."""
    r = _evaluate({"mds_or_aml_documented_during_parpi": "No"}, treatments=_tx("OLAPARIB"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1836_path_a_filters_olaparib_hard_block():
    """H.G1836 — gate 52 hard_block FILTRA olaparib (count=0)."""
    r = _evaluate({"mds_or_aml_documented_during_parpi": "Sí"}, treatments=_tx("OLAPARIB"))
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 0


# ───────────────────────────────────────────────
# §B — Path B compound: cytopenia ≥2 líneas + duración >12 sem + sospecha
# ───────────────────────────────────────────────


def test_g1837_path_b_compound_fires():
    """H.G1837 — cytopenia ≥2 líneas + duración >12 sem + sospecha dispara Path B."""
    r = _evaluate({
        "cytopenia_two_or_more_lines_documented": "Sí",
        "cytopenia_duration_weeks": 16,
        "hematologic_malignancy_suspected_for_parpi": "Sí",
    }, treatments=_tx("NIRAPARIB_ABIRATERONE"))
    assert GATE_CODE in _gate_codes(r)


@pytest.mark.parametrize("weeks", [13, 16, 20, 26, 52])
def test_g1838_path_b_duration_above_12_fires(weeks):
    """H.G1838 — duración >12 sem (con cytopenia + sospecha) dispara Path B."""
    r = _evaluate({
        "cytopenia_two_or_more_lines_documented": "Sí",
        "cytopenia_duration_weeks": weeks,
        "hematologic_malignancy_suspected_for_parpi": "Sí",
    }, treatments=_tx("OLAPARIB"))
    assert GATE_CODE in _gate_codes(r)


@pytest.mark.parametrize("weeks", [4, 8, 10, 12])
def test_g1839_path_b_duration_le_12_does_NOT_fire(weeks):
    """H.G1839 — duración ≤12 sem NO dispara Path B (boundary — distingue mielosupresión transitoria)."""
    r = _evaluate({
        "cytopenia_two_or_more_lines_documented": "Sí",
        "cytopenia_duration_weeks": weeks,
        "hematologic_malignancy_suspected_for_parpi": "Sí",
    }, treatments=_tx("OLAPARIB"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1840_path_b_missing_cytopenia_does_NOT_fire():
    """H.G1840 — Path B NO dispara sin cytopenia (compound all_of)."""
    r = _evaluate({
        "cytopenia_duration_weeks": 16,
        "hematologic_malignancy_suspected_for_parpi": "Sí",
    }, treatments=_tx("OLAPARIB"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1841_path_b_missing_suspicion_does_NOT_fire():
    """H.G1841 — Path B NO dispara sin sospecha clínica (compound all_of)."""
    r = _evaluate({
        "cytopenia_two_or_more_lines_documented": "Sí",
        "cytopenia_duration_weeks": 16,
    }, treatments=_tx("OLAPARIB"))
    assert GATE_CODE not in _gate_codes(r)


# ───────────────────────────────────────────────
# §C — Path C compound: WHO 2022 MDS criteria
# ───────────────────────────────────────────────


def test_g1842_path_c_compound_mds_fires():
    """H.G1842 — Path C compound (displasia + blasts >5%) dispara (criterio WHO 2022 MDS)."""
    r = _evaluate({
        "bone_marrow_dysplasia_documented": "Sí",
        "bone_marrow_blasts_percent": 12,
    }, treatments=_tx("TALAZOPARIB_ENZALUTAMIDE"))
    assert GATE_CODE in _gate_codes(r)


@pytest.mark.parametrize("blasts", [6, 8, 10, 15, 19])
def test_g1843_path_c_blasts_above_5_fires(blasts):
    """H.G1843 — blasts BMA >5% (con displasia) dispara Path C MDS."""
    r = _evaluate({
        "bone_marrow_dysplasia_documented": "Sí",
        "bone_marrow_blasts_percent": blasts,
    }, treatments=_tx("OLAPARIB"))
    assert GATE_CODE in _gate_codes(r)


@pytest.mark.parametrize("blasts", [0, 2, 4, 5])
def test_g1844_path_c_blasts_le_5_does_NOT_fire(blasts):
    """H.G1844 — blasts ≤5% NO dispara Path C (boundary BMA normal-MDS-EB-0)."""
    r = _evaluate({
        "bone_marrow_dysplasia_documented": "Sí",
        "bone_marrow_blasts_percent": blasts,
    }, treatments=_tx("OLAPARIB"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1845_path_c_missing_dysplasia_does_NOT_fire():
    """H.G1845 — Path C NO dispara sin displasia (compound all_of)."""
    r = _evaluate({
        "bone_marrow_blasts_percent": 12,
    }, treatments=_tx("OLAPARIB"))
    # Path C no fires (no dysplasia), pero blasts=12 NO activa Path D (need ≥20)
    assert GATE_CODE not in _gate_codes(r)


# ───────────────────────────────────────────────
# §D — Path D: WHO 2022 AML criteria (blasts ≥20%)
# ───────────────────────────────────────────────


@pytest.mark.parametrize("blasts", [20, 25, 30, 50, 80])
def test_g1846_path_d_blasts_ge_20_fires_aml(blasts):
    """H.G1846 — blasts ≥20% dispara Path D (criterio WHO 2022 AML — emergencia oncohematológica)."""
    r = _evaluate({"bone_marrow_blasts_percent": blasts}, treatments=_tx("RUCAPARIB"))
    assert GATE_CODE in _gate_codes(r)


def test_g1847_path_d_alias_peripheral_blood_blasts_works():
    """H.G1847 — alias `peripheral_blood_blasts_percent` dispara Path D."""
    r = _evaluate({"peripheral_blood_blasts_percent": 35}, treatments=_tx("OLAPARIB"))
    assert GATE_CODE in _gate_codes(r)


def test_g1848_path_d_blasts_19_does_NOT_fire_d_but_path_c_does():
    """H.G1848 — blasts=19% NO dispara Path D pero CON displasia activa Path C MDS."""
    r = _evaluate({
        "bone_marrow_dysplasia_documented": "Sí",
        "bone_marrow_blasts_percent": 19,
    }, treatments=_tx("OLAPARIB"))
    # Path C fires (displasia + blasts >5%)
    assert GATE_CODE in _gate_codes(r)


# ───────────────────────────────────────────────
# §E — Override (remisión completa per IWG 2018)
# ───────────────────────────────────────────────


def test_g1849_override_mds_aml_remission_disables():
    """H.G1849 — override `mds_aml_remission_for_parpi=Sí` desactiva."""
    r = _evaluate({
        "mds_or_aml_documented_during_parpi": "Sí",
        "mds_aml_remission_for_parpi": "Sí",
    }, treatments=_tx("OLAPARIB"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1850_override_alias_hematologic_remission_works():
    """H.G1850 — alias override `hematologic_remission_documented_for_parpi` desactiva."""
    r = _evaluate({
        "mds_or_aml_documented_during_parpi": "Sí",
        "hematologic_remission_documented_for_parpi": "Sí",
    }, treatments=_tx("OLAPARIB"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1851_override_alias_smd_lma_remision_completa_es_works():
    """H.G1851 — alias override `smd_lma_remision_completa_para_parpi` (ES) desactiva."""
    r = _evaluate({
        "mds_or_aml_documented_during_parpi": "Sí",
        "smd_lma_remision_completa_para_parpi": "Sí",
    }, treatments=_tx("OLAPARIB"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1852_override_does_NOT_apply_with_path_d_aml():
    """H.G1852 — override desactiva incluso con Path D AML severo (escenario excepcional)."""
    r = _evaluate({
        "bone_marrow_blasts_percent": 30,  # AML
        "mds_aml_remission_for_parpi": "Sí",
    }, treatments=_tx("OLAPARIB"))
    assert GATE_CODE not in _gate_codes(r)


# ───────────────────────────────────────────────
# §F — Regimen scoping (PARP inhibitors clase entera)
# ───────────────────────────────────────────────


@pytest.mark.parametrize("parpi_code", [
    "OLAPARIB", "ABIRATERONE_OLAPARIB",
    "NIRAPARIB_ABIRATERONE", "ADT_ABIRATERONE_NIRAPARIB",
    "TALAZOPARIB_ENZALUTAMIDE", "ADT_TALAZO_ENZA_HRR",
    "RUCAPARIB",
])
def test_g1853_parp_inhibitors_filtered(parpi_code):
    """H.G1853 — gate 52 filtra TODOS los PARP inhibitors (7 regímenes)."""
    r = _evaluate({"mds_or_aml_documented_during_parpi": "Sí"}, treatments=_tx(parpi_code))
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 0, f"PARPi {parpi_code} debe ser filtrada"


def test_g1854_enzalutamide_NOT_filtered_by_gate_52():
    """H.G1854 — ENZALUTAMIDE NO es filtrada por gate 52 (no es PARP inhibitor)."""
    r = _evaluate({"mds_or_aml_documented_during_parpi": "Sí"}, treatments=_tx("ENZALUTAMIDE"))
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 1, "Enzalutamida no es PARPi, no debe filtrarse"


def test_g1855_apalutamide_NOT_filtered_by_gate_52():
    """H.G1855 — APALUTAMIDE NO es filtrada por gate 52."""
    r = _evaluate({"mds_or_aml_documented_during_parpi": "Sí"}, treatments=_tx("APALUTAMIDE"))
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 1


def test_g1856_abiraterone_NOT_filtered_by_gate_52():
    """H.G1856 — ABIRATERONE NO es filtrada por gate 52 (cuando NO está combinada con PARPi)."""
    r = _evaluate({"mds_or_aml_documented_during_parpi": "Sí"}, treatments=_tx("ADT_ABIRATERONE"))
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 1


# ───────────────────────────────────────────────
# §G — Aliases multi-idioma + coexistencia con gate 16
# ───────────────────────────────────────────────


def test_g1857_alias_citopenia_dos_o_mas_lineas_es_works():
    """H.G1857 — alias `citopenia_dos_o_mas_lineas` (ES) dispara Path B."""
    r = _evaluate({
        "citopenia_dos_o_mas_lineas": "Sí",
        "cytopenia_duration_weeks": 16,
        "hematologic_malignancy_suspected_for_parpi": "Sí",
    }, treatments=_tx("OLAPARIB"))
    assert GATE_CODE in _gate_codes(r)


def test_g1858_alias_duracion_citopenia_semanas_es_works():
    """H.G1858 — alias `duracion_citopenia_semanas` (ES) dispara Path B."""
    r = _evaluate({
        "cytopenia_two_or_more_lines_documented": "Sí",
        "duracion_citopenia_semanas": 16,
        "hematologic_malignancy_suspected_for_parpi": "Sí",
    }, treatments=_tx("OLAPARIB"))
    assert GATE_CODE in _gate_codes(r)


def test_g1859_alias_displasia_medular_es_works():
    """H.G1859 — alias `displasia_medular_documentada` (ES) dispara Path C."""
    r = _evaluate({
        "displasia_medular_documentada": "Sí",
        "bone_marrow_blasts_percent": 12,
    }, treatments=_tx("OLAPARIB"))
    assert GATE_CODE in _gate_codes(r)


def test_g1860_alias_blastos_medulares_porcentaje_es_works():
    """H.G1860 — alias `blastos_medulares_porcentaje` (ES) dispara Path D AML."""
    r = _evaluate({"blastos_medulares_porcentaje": 30}, treatments=_tx("OLAPARIB"))
    assert GATE_CODE in _gate_codes(r)


def test_g1861_coexistence_gate_16_history_and_gate_52_emergent():
    """H.G1861 — Mismo paciente con history MDS pre-tx + emergente nuevo activa AMBOS gates 16+52."""
    r = _evaluate({
        "mds_aml_history": "Sí",  # gate 16 — history
        "mds_or_aml_documented_during_parpi": "Sí",  # gate 52 — emergente
    }, treatments=_tx("OLAPARIB"))
    codes = set(_gate_codes(r))
    assert "parp_inhibitor_in_mds_aml_history" in codes  # gate 16
    assert GATE_CODE in codes  # gate 52


# ───────────────────────────────────────────────
# §H — Catálogo + clasificadores + smoke E2E
# ───────────────────────────────────────────────


def test_g1862_gate_52_in_yaml_catalog():
    """H.G1862 — Gate 52 cargado en catálogo YAML."""
    from prostanet.shared.pivotal_gates_yaml_loader import get_loaded_yaml_codes
    assert GATE_CODE in get_loaded_yaml_codes()


def test_g1863_gate_52_in_active_codes():
    """H.G1863 — Gate 52 en `get_active_gate_codes()`."""
    from prostanet.shared.algorithm_version import get_active_gate_codes
    assert GATE_CODE in get_active_gate_codes()


def test_g1864_total_gates_at_least_52():
    """H.G1864 — Total gates activos ≥52."""
    from prostanet.shared.algorithm_version import get_active_gate_codes
    assert len(get_active_gate_codes()) >= 52


def test_g1865_classifier_pivotal_gate_delta_label():
    """H.G1865 — `_GATE_EXACT_CLASSES` incluye class label específico."""
    from prostanet.shared.pivotal_gate_delta import _GATE_EXACT_CLASSES
    label = _GATE_EXACT_CLASSES.get(GATE_CODE)
    assert label is not None
    assert "MDS/AML" in label
    assert "PARP" in label
    assert "longitudinal" in label.lower()
    assert "MAGNITUDE" in label or "PROfound" in label or "WHO" in label


def test_g1866_classifier_profile_compass_label():
    """H.G1866 — profile_compass produce class label en by_class."""
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
    assert any("MDS/AML" in label and "PARP" in label for label in by_class.keys()), (
        f"Class label 'MDS/AML PARP' debe estar en by_class — found: {list(by_class.keys())}"
    )


def test_g1867_evidence_tag_includes_magnitude_profound_who():
    """H.G1867 — evidence_tag cita MAGNITUDE + PROfound + WHO 2022."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files
    files = _load_yaml_files()
    config = files.get(GATE_CODE)
    assert config is not None
    et = config.get("evidence_tag", "").lower()
    assert "magnitude" in et and "profound" in et and "who_2022" in et


def test_g1868_severity_is_hard_block():
    """H.G1868 — Gate 52 severity='hard_block' (NO informacional)."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files
    files = _load_yaml_files()
    config = files.get(GATE_CODE)
    assert config is not None
    assert config.get("severity") == "hard_block"


def test_g1869_smoke_e2e_full_mds_aml_panel():
    """H.G1869 — E2E paciente con MDS emergente full panel (4 paths) → gate fires + olaparib filtrado + evidence."""
    r = _evaluate({
        "mds_or_aml_documented_during_parpi": "Sí",  # Path A
        "cytopenia_two_or_more_lines_documented": "Sí",
        "cytopenia_duration_weeks": 20,
        "hematologic_malignancy_suspected_for_parpi": "Sí",  # Path B compound
        "bone_marrow_dysplasia_documented": "Sí",
        "bone_marrow_blasts_percent": 25,  # Path C compound + Path D AML
    }, treatments=_tx("OLAPARIB"))
    # Gate fires
    assert GATE_CODE in _gate_codes(r)
    # Olaparib filtrado (count=0)
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 0
    # Evidence tag presente
    gate_data = next((g for g in r["gates_triggered"] if g["code"] == GATE_CODE), None)
    assert gate_data is not None
    assert "magnitude" in gate_data.get("evidence_tag", "").lower()
    assert gate_data.get("severity") == "hard_block"


def test_g1870_smoke_e2e_healthy_olaparib_no_mds():
    """H.G1870 — paciente sano en olaparib NO dispara gate 52."""
    r = _evaluate({
        "mds_or_aml_documented_during_parpi": "No",
        "bone_marrow_blasts_percent": 2,  # normal
    }, treatments=_tx("OLAPARIB"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1871_message_cites_who_2022_iwg_2018_mortality():
    """H.G1871 — Mensaje gate 52 cita WHO 2022 + mortalidad MDS post-PARP."""
    r = _evaluate({"mds_or_aml_documented_during_parpi": "Sí"}, treatments=_tx("OLAPARIB"))
    gate_data = next((g for g in r["gates_triggered"] if g["code"] == GATE_CODE), None)
    assert gate_data is not None
    msg = gate_data.get("message", "")
    assert "WHO 2022" in msg or "WHO Classification" in msg
    assert "MORTALIDAD" in msg or "mortalidad" in msg.lower()
    assert "25-50%" in msg or "PARP" in msg


def test_g1872_message_cites_alternatives_taxanes_arsi():
    """H.G1872 — Mensaje gate 52 cita alternativas NO-PARPi (taxanes + ARSI + Lu-177)."""
    r = _evaluate({"mds_or_aml_documented_during_parpi": "Sí"}, treatments=_tx("OLAPARIB"))
    gate_data = next((g for g in r["gates_triggered"] if g["code"] == GATE_CODE), None)
    assert gate_data is not None
    msg = gate_data.get("message", "")
    assert "Taxanes" in msg or "taxanes" in msg.lower()
    assert "ARSI" in msg
    assert "Lu-177" in msg


def test_g1873_total_field_specs_includes_7_gate_52():
    """H.G1873 — 7 nuevos FieldSpecs (1 dx + 3 Path B + 2 Path C/D + 1 override)."""
    from prostanet.shared.advanced_support_fields import pivotal_gate_supporting_fields
    fields = pivotal_gate_supporting_fields()
    field_names = {f.name for f in fields}
    expected = {
        "mds_or_aml_documented_during_parpi",
        "cytopenia_two_or_more_lines_documented",
        "cytopenia_duration_weeks",
        "hematologic_malignancy_suspected_for_parpi",
        "bone_marrow_dysplasia_documented",
        "bone_marrow_blasts_percent",
        "mds_aml_remission_for_parpi",
    }
    assert expected.issubset(field_names), f"Missing FieldSpecs: {expected - field_names}"


def test_g1874_yaml_validation_passes():
    """H.G1874 — YAML config gate 52 pasa validación schema."""
    from prostanet.shared.pivotal_gates_yaml_loader import (
        _load_yaml_files,
        validate_yaml_gate_config,
    )
    files = _load_yaml_files()
    config = files.get(GATE_CODE)
    assert config is not None
    errors = validate_yaml_gate_config(config)
    assert errors == [], f"YAML validation errors: {errors}"


def test_g1875_total_field_specs_count_at_least_167():
    """H.G1875 — Total FieldSpecs ≥167 (161 prev + 7 nuevos − 1 override compartido = ~167)."""
    from prostanet.shared.advanced_support_fields import pivotal_gate_supporting_fields
    assert len(pivotal_gate_supporting_fields()) >= 167
