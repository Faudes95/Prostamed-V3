"""tests/test_audit63a_gates_53_54_55_psa_kinetics.py — Faubot 2026-04-25 (LXIV).

Tests dedicados a Auditoría #63A — Gates 53/54/55 PSA Kinetics.

Cubre H.G1876 - H.G1955 (~80 hipótesis) en 9 secciones:

§A — Gate 53: BCR aggressive post-RP (Stephenson criteria)
§B — Gate 54: PSA bounce post-RT (Phoenix criteria + anti-misinterpretation)
§C — Gate 55: PSADT progressive m0CRPC ARPI eligibility (SPARTAN/PROSPER/ARAMIS)
§D — Severity soft_warning behavior (NO bloquea ARPI)
§E — Coexistencia entre los 3 gates kinetics + gate 47
§F — REGIMEN_CODES_OBSERVATION_ONLY catálogo
§G — Aliases multi-idioma (ES + variantes)
§H — Catálogo + clasificadores + smoke E2E
§I — Cumplimiento NCCN/EAU/RTOG-ASTRO Phoenix

🆕 PRIMER trio gates PSA kinetics post-RP/RT/m0CRPC. Sienta categoría
kinetics PSA del catálogo. Los 3 son severity=soft_warning
(informacionales/anti-misinterpretation per pattern gate 47 #62).
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


GATE_53 = "psa_velocity_bcr_aggressive"
GATE_54 = "psa_bounce_post_rt_pseudoprogression"
GATE_55 = "psa_doubling_time_progressive"
ALL_KINETICS_GATES = {GATE_53, GATE_54, GATE_55}


# ───────────────────────────────────────────────
# §A — Gate 53: BCR aggressive post-RP
# ───────────────────────────────────────────────


@pytest.mark.parametrize("psadt", [2.9, 2.5, 2.0, 1.5, 1.0])
def test_g1876_path_a_psadt_below_3_post_rp_fires(psadt):
    """H.G1876 — PSADT <3 + post-RP dispara Path A (Stephenson criteria)."""
    r = _evaluate({
        "psa_doubling_time_months": psadt,
        "prior_radical_prostatectomy_documented": "Sí",
    }, treatments=_tx("OBSERVATION"))
    assert GATE_53 in _gate_codes(r)


@pytest.mark.parametrize("psadt", [3.0, 5.0, 10.0, 20.0])
def test_g1877_path_a_psadt_ge_3_does_NOT_fire(psadt):
    """H.G1877 — PSADT ≥3 NO dispara Path A (boundary 3.0 NOT <3.0)."""
    r = _evaluate({
        "psa_doubling_time_months": psadt,
        "prior_radical_prostatectomy_documented": "Sí",
    }, treatments=_tx("OBSERVATION"))
    assert GATE_53 not in _gate_codes(r)


def test_g1878_path_a_psadt_low_without_rp_does_NOT_fire():
    """H.G1878 — PSADT <3 sin post-RP NO dispara Path A (compound all_of)."""
    r = _evaluate({
        "psa_doubling_time_months": 2.0,
        # prior_radical_prostatectomy_documented = ausente
    }, treatments=_tx("OBSERVATION"))
    assert GATE_53 not in _gate_codes(r)


def test_g1879_path_b_compound_velocity_psa_rp_fires():
    """H.G1879 — velocity >2 + PSA >0.5 + post-RP dispara Path B compound."""
    r = _evaluate({
        "psa_velocity_ng_ml_year": 3.5,
        "psa_value": 0.8,
        "prior_radical_prostatectomy_documented": "Sí",
    }, treatments=_tx("OBSERVATION"))
    assert GATE_53 in _gate_codes(r)


def test_g1880_path_b_velocity_below_2_does_NOT_fire():
    """H.G1880 — Path B NO dispara con velocity ≤2 (boundary)."""
    r = _evaluate({
        "psa_velocity_ng_ml_year": 1.5,
        "psa_value": 0.8,
        "prior_radical_prostatectomy_documented": "Sí",
    }, treatments=_tx("OBSERVATION"))
    assert GATE_53 not in _gate_codes(r)


def test_g1881_path_b_psa_below_05_does_NOT_fire():
    """H.G1881 — Path B NO dispara con PSA ≤0.5 (boundary BCR)."""
    r = _evaluate({
        "psa_velocity_ng_ml_year": 3.5,
        "psa_value": 0.3,  # PSA <0.5 NOT BCR confirmed
        "prior_radical_prostatectomy_documented": "Sí",
    }, treatments=_tx("OBSERVATION"))
    assert GATE_53 not in _gate_codes(r)


def test_g1882_path_c_flag_documented_fires():
    """H.G1882 — bcr_high_risk_aggressive_documented flag dispara Path C."""
    r = _evaluate({
        "bcr_high_risk_aggressive_documented": "Sí",
    }, treatments=_tx("OBSERVATION"))
    assert GATE_53 in _gate_codes(r)


def test_g1883_override_bcr_treated_for_salvage_disables():
    """H.G1883 — override `bcr_aggressive_treated_for_salvage=Sí` desactiva."""
    r = _evaluate({
        "psa_doubling_time_months": 2.0,
        "prior_radical_prostatectomy_documented": "Sí",
        "bcr_aggressive_treated_for_salvage": "Sí",
    }, treatments=_tx("OBSERVATION"))
    assert GATE_53 not in _gate_codes(r)


def test_g1884_severity_is_soft_warning():
    """H.G1884 — Gate 53 severity='soft_warning' (informacional, NO bloquea)."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files
    files = _load_yaml_files()
    config = files.get(GATE_53)
    assert config is not None
    assert config.get("severity") == "soft_warning"


def test_g1885_does_NOT_filter_any_treatment():
    """H.G1885 — Gate 53 soft_warning NO filtra ENZALUTAMIDE ni otros."""
    r = _evaluate({
        "psa_doubling_time_months": 2.0,
        "prior_radical_prostatectomy_documented": "Sí",
    }, treatments=_tx("ENZALUTAMIDE"))
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 1, "soft_warning gate NO debe filtrar tratamientos"


# ───────────────────────────────────────────────
# §B — Gate 54: PSA bounce post-RT
# ───────────────────────────────────────────────


def test_g1886_path_a_bounce_compound_fires():
    """H.G1886 — rise <2 + 12-30m post-RT + sin imagen progresión dispara Path A."""
    r = _evaluate({
        "psa_rise_above_nadir_ng_ml": 0.8,
        "months_post_rt": 18,
        "no_image_progression_documented": "Sí",
    }, treatments=_tx("OBSERVATION"))
    assert GATE_54 in _gate_codes(r)


@pytest.mark.parametrize("rise", [0.4, 0.8, 1.5, 1.9])
def test_g1887_path_a_rise_below_2_fires(rise):
    """H.G1887 — rise <2 ng/mL above nadir (con tiempo + sin imagen) dispara Path A."""
    r = _evaluate({
        "psa_rise_above_nadir_ng_ml": rise,
        "months_post_rt": 18,
        "no_image_progression_documented": "Sí",
    }, treatments=_tx("OBSERVATION"))
    assert GATE_54 in _gate_codes(r)


@pytest.mark.parametrize("rise", [2.0, 2.5, 3.0, 5.0])
def test_g1888_path_a_rise_ge_2_does_NOT_fire(rise):
    """H.G1888 — rise ≥2 ng/mL above nadir = Phoenix BCR criterion (NO bounce)."""
    r = _evaluate({
        "psa_rise_above_nadir_ng_ml": rise,
        "months_post_rt": 18,
        "no_image_progression_documented": "Sí",
    }, treatments=_tx("OBSERVATION"))
    assert GATE_54 not in _gate_codes(r)


@pytest.mark.parametrize("months", [13, 18, 24, 30])
def test_g1889_path_a_months_in_window_fires(months):
    """H.G1889 — Tiempo post-RT en ventana 12-30 meses dispara Path A."""
    r = _evaluate({
        "psa_rise_above_nadir_ng_ml": 0.8,
        "months_post_rt": months,
        "no_image_progression_documented": "Sí",
    }, treatments=_tx("OBSERVATION"))
    assert GATE_54 in _gate_codes(r)


@pytest.mark.parametrize("months", [6, 8, 10, 12])
def test_g1890_path_a_months_too_early_does_NOT_fire(months):
    """H.G1890 — Tiempo post-RT ≤12m NO dispara Path A (boundary >12)."""
    r = _evaluate({
        "psa_rise_above_nadir_ng_ml": 0.8,
        "months_post_rt": months,
        "no_image_progression_documented": "Sí",
    }, treatments=_tx("OBSERVATION"))
    assert GATE_54 not in _gate_codes(r)


@pytest.mark.parametrize("months", [31, 36, 48, 60])
def test_g1891_path_a_months_too_late_does_NOT_fire(months):
    """H.G1891 — Tiempo post-RT >30m NO dispara Path A (fuera ventana bounce)."""
    r = _evaluate({
        "psa_rise_above_nadir_ng_ml": 0.8,
        "months_post_rt": months,
        "no_image_progression_documented": "Sí",
    }, treatments=_tx("OBSERVATION"))
    assert GATE_54 not in _gate_codes(r)


def test_g1892_path_b_flag_documented_fires():
    """H.G1892 — psa_bounce_documented_post_rt flag dispara Path B."""
    r = _evaluate({
        "psa_bounce_documented_post_rt": "Sí",
    }, treatments=_tx("OBSERVATION"))
    assert GATE_54 in _gate_codes(r)


def test_g1893_path_c_unconfirmed_pcwg3_fires():
    """H.G1893 — psa_elevation_unconfirmed_post_rt dispara Path C (PCWG3)."""
    r = _evaluate({
        "psa_elevation_unconfirmed_post_rt": "Sí",
    }, treatments=_tx("OBSERVATION"))
    assert GATE_54 in _gate_codes(r)


def test_g1894_severity_is_soft_warning():
    """H.G1894 — Gate 54 severity='soft_warning' (anti-misinterpretation)."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files
    files = _load_yaml_files()
    config = files.get(GATE_54)
    assert config is not None
    assert config.get("severity") == "soft_warning"


def test_g1895_no_override_field_in_yaml():
    """H.G1895 — Gate 54 NO tiene override (gate informacional puro per gate 47 pattern)."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files
    files = _load_yaml_files()
    config = files.get(GATE_54)
    assert config is not None
    assert config.get("override") is None


# ───────────────────────────────────────────────
# §C — Gate 55: PSADT progressive m0CRPC
# ───────────────────────────────────────────────


def test_g1896_path_a_psadt_le_10_m0crpc_arpi_naive_fires():
    """H.G1896 — PSADT ≤10 + m0CRPC + ARPI naive dispara Path A (SPARTAN/PROSPER/ARAMIS)."""
    r = _evaluate({
        "psa_doubling_time_months": 8.0,
        "m0_crpc_state_confirmed": "Sí",
        "no_active_arpi_for_m0_crpc": "Sí",
    }, treatments=_tx("OBSERVATION"))
    assert GATE_55 in _gate_codes(r)


@pytest.mark.parametrize("psadt", [10.0, 9.5, 8.0, 5.0, 3.0])
def test_g1897_path_a_psadt_le_10_fires(psadt):
    """H.G1897 — PSADT ≤10 (numeric_below 11) dispara Path A."""
    r = _evaluate({
        "psa_doubling_time_months": psadt,
        "m0_crpc_state_confirmed": "Sí",
        "no_active_arpi_for_m0_crpc": "Sí",
    }, treatments=_tx("OBSERVATION"))
    assert GATE_55 in _gate_codes(r)


@pytest.mark.parametrize("psadt", [11.0, 12.0, 15.0, 24.0])
def test_g1898_path_a_psadt_above_10_does_NOT_fire(psadt):
    """H.G1898 — PSADT >10 NO dispara Path A (fuera criterio SPARTAN/PROSPER/ARAMIS)."""
    r = _evaluate({
        "psa_doubling_time_months": psadt,
        "m0_crpc_state_confirmed": "Sí",
        "no_active_arpi_for_m0_crpc": "Sí",
    }, treatments=_tx("OBSERVATION"))
    assert GATE_55 not in _gate_codes(r)


def test_g1899_path_a_missing_m0crpc_does_NOT_fire():
    """H.G1899 — Path A NO dispara sin m0_crpc_state_confirmed (compound all_of)."""
    r = _evaluate({
        "psa_doubling_time_months": 8.0,
        "no_active_arpi_for_m0_crpc": "Sí",
    }, treatments=_tx("OBSERVATION"))
    assert GATE_55 not in _gate_codes(r)


def test_g1900_path_b_compound_aggressive_psadt_le_8_castrate_fires():
    """H.G1900 — PSADT ≤8 + castrate + naive dispara Path B compound (criterio agresivo)."""
    r = _evaluate({
        "psa_doubling_time_months": 6.0,
        "castrate_testosterone_status_confirmed": "Sí",
        "no_active_arpi_for_m0_crpc": "Sí",
    }, treatments=_tx("OBSERVATION"))
    assert GATE_55 in _gate_codes(r)


def test_g1901_path_c_flag_documented_fires():
    """H.G1901 — psadt_progressive_for_arpi_eligibility flag dispara Path C."""
    r = _evaluate({
        "psadt_progressive_for_arpi_eligibility": "Sí",
    }, treatments=_tx("OBSERVATION"))
    assert GATE_55 in _gate_codes(r)


def test_g1902_override_arpi_already_initiated_disables():
    """H.G1902 — override `arpi_already_initiated_for_m0_crpc=Sí` desactiva."""
    r = _evaluate({
        "psa_doubling_time_months": 8.0,
        "m0_crpc_state_confirmed": "Sí",
        "no_active_arpi_for_m0_crpc": "Sí",
        "arpi_already_initiated_for_m0_crpc": "Sí",
    }, treatments=_tx("OBSERVATION"))
    assert GATE_55 not in _gate_codes(r)


def test_g1903_severity_is_soft_warning():
    """H.G1903 — Gate 55 severity='soft_warning' (informacional)."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files
    files = _load_yaml_files()
    config = files.get(GATE_55)
    assert config is not None
    assert config.get("severity") == "soft_warning"


# ───────────────────────────────────────────────
# §D — Severity soft_warning behavior (NO filtra)
# ───────────────────────────────────────────────


@pytest.mark.parametrize("treatment_code", [
    "ENZALUTAMIDE", "APALUTAMIDE", "ADT_DAROLUTAMIDE",
    "DOCETAXEL", "OLAPARIB", "RADIUM_223",
])
def test_g1904_gates_53_55_do_NOT_filter_active_treatments(treatment_code):
    """H.G1904 — Gates 53/55 soft_warning NO filtran tratamientos activos (alertan, no bloquean)."""
    r = _evaluate({
        "psa_doubling_time_months": 2.0,
        "prior_radical_prostatectomy_documented": "Sí",  # gate 53
        "psadt_progressive_for_arpi_eligibility": "Sí",  # gate 55
    }, treatments=_tx(treatment_code))
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 1, f"{treatment_code} no debe ser filtrada por gates soft_warning"


def test_g1905_gate_47_psa_flare_pattern_consistency():
    """H.G1905 — Gates 53/54/55 siguen el mismo patrón soft_warning de gate 47 #62."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files
    files = _load_yaml_files()
    for code in [GATE_53, GATE_54, GATE_55, "psa_flare_arpi_pseudoprogression"]:
        config = files.get(code)
        assert config is not None
        assert config.get("severity") == "soft_warning", f"{code} debe ser soft_warning per pattern #62"


# ───────────────────────────────────────────────
# §E — Coexistencia entre gates kinetics + gate 47
# ───────────────────────────────────────────────


def test_g1906_coexistence_all_3_kinetics_gates_simultaneous():
    """H.G1906 — Los 3 gates kinetics pueden disparar simultáneamente (escenario raro paciente complejo)."""
    r = _evaluate({
        # Gate 53: BCR aggressive
        "psa_doubling_time_months": 2.5,
        "prior_radical_prostatectomy_documented": "Sí",
        # Gate 54: PSA bounce
        "psa_bounce_documented_post_rt": "Sí",
        # Gate 55: PSADT progressive
        "psadt_progressive_for_arpi_eligibility": "Sí",
    }, treatments=_tx("OBSERVATION"))
    codes = set(_gate_codes(r))
    assert ALL_KINETICS_GATES.issubset(codes)


def test_g1907_coexistence_with_gate_47_psa_flare_arpi():
    """H.G1907 — Gate 53 + gate 47 (PSA flare ARPI) pueden coexistir si paciente recibió ARPI post-salvage."""
    r = _evaluate({
        "psa_doubling_time_months": 2.0,
        "prior_radical_prostatectomy_documented": "Sí",  # gate 53
        "psa_flare_documented_first_month_arpi": "Sí",  # gate 47
    }, treatments=_tx("ENZALUTAMIDE"))
    codes = set(_gate_codes(r))
    assert GATE_53 in codes
    assert "psa_flare_arpi_pseudoprogression" in codes


# ───────────────────────────────────────────────
# §F — REGIMEN_CODES_OBSERVATION_ONLY catálogo
# ───────────────────────────────────────────────


def test_g1908_regimen_codes_observation_only_exists():
    """H.G1908 — REGIMEN_CODES_OBSERVATION_ONLY frozenset definida."""
    from prostanet.shared.pivotal_contraindication_gates import REGIMEN_CODES_OBSERVATION_ONLY
    assert isinstance(REGIMEN_CODES_OBSERVATION_ONLY, frozenset)
    assert len(REGIMEN_CODES_OBSERVATION_ONLY) >= 7


@pytest.mark.parametrize("code", [
    "OBSERVATION", "OBSERVATION_ONLY", "ACTIVE_SURVEILLANCE",
    "WATCHFUL_WAITING", "VIGILANCIA_ACTIVA", "NO_TREATMENT", "NO_TX",
])
def test_g1909_observation_codes_in_frozenset(code):
    """H.G1909 — REGIMEN_CODES_OBSERVATION_ONLY incluye codes esperados."""
    from prostanet.shared.pivotal_contraindication_gates import REGIMEN_CODES_OBSERVATION_ONLY
    assert code in REGIMEN_CODES_OBSERVATION_ONLY


def test_g1910_keywords_observation_only_includes_es_en():
    """H.G1910 — KEYWORDS_OBSERVATION_ONLY incluye términos ES + EN."""
    from prostanet.shared.pivotal_contraindication_gates import KEYWORDS_OBSERVATION_ONLY
    expected = {"observación", "active surveillance", "vigilancia activa", "watchful waiting"}
    assert expected.issubset(set(KEYWORDS_OBSERVATION_ONLY))


# ───────────────────────────────────────────────
# §G — Aliases multi-idioma (ES + variantes)
# ───────────────────────────────────────────────


def test_g1911_alias_psadt_months_works():
    """H.G1911 — alias `psadt_months` dispara Path A gate 53."""
    r = _evaluate({
        "psadt_months": 2.0,
        "prior_radical_prostatectomy_documented": "Sí",
    }, treatments=_tx("OBSERVATION"))
    assert GATE_53 in _gate_codes(r)


def test_g1912_alias_tiempo_duplicacion_psa_es_works():
    """H.G1912 — alias `tiempo_duplicacion_psa_meses` (ES) dispara Path A gate 55."""
    r = _evaluate({
        "tiempo_duplicacion_psa_meses": 8.0,
        "m0_crpc_state_confirmed": "Sí",
        "no_active_arpi_for_m0_crpc": "Sí",
    }, treatments=_tx("OBSERVATION"))
    assert GATE_55 in _gate_codes(r)


def test_g1913_alias_meses_post_rt_es_works():
    """H.G1913 — alias `meses_post_rt` (ES) dispara Path A gate 54."""
    r = _evaluate({
        "psa_rise_above_nadir_ng_ml": 0.8,
        "meses_post_rt": 18,
        "no_image_progression_documented": "Sí",
    }, treatments=_tx("OBSERVATION"))
    assert GATE_54 in _gate_codes(r)


def test_g1914_alias_velocidad_psa_es_works():
    """H.G1914 — alias `velocidad_psa_ng_ml_anio` (ES) dispara Path B gate 53."""
    r = _evaluate({
        "velocidad_psa_ng_ml_anio": 3.5,
        "psa_value": 0.8,
        "prior_radical_prostatectomy_documented": "Sí",
    }, treatments=_tx("OBSERVATION"))
    assert GATE_53 in _gate_codes(r)


def test_g1915_alias_prostatectomia_radical_previa_es_works():
    """H.G1915 — alias `prostatectomia_radical_previa` (ES) dispara Path A gate 53."""
    r = _evaluate({
        "psa_doubling_time_months": 2.0,
        "prostatectomia_radical_previa": "Sí",
    }, treatments=_tx("OBSERVATION"))
    assert GATE_53 in _gate_codes(r)


def test_g1916_alias_no_imaging_progression_works():
    """H.G1916 — alias `no_imaging_progression` dispara Path A gate 54."""
    r = _evaluate({
        "psa_rise_above_nadir_ng_ml": 0.8,
        "months_post_rt": 18,
        "no_imaging_progression": "Sí",
    }, treatments=_tx("OBSERVATION"))
    assert GATE_54 in _gate_codes(r)


def test_g1917_alias_m0_crpc_documented_works():
    """H.G1917 — alias `m0_crpc_documented` dispara Path A gate 55."""
    r = _evaluate({
        "psa_doubling_time_months": 8.0,
        "m0_crpc_documented": "Sí",
        "no_active_arpi_for_m0_crpc": "Sí",
    }, treatments=_tx("OBSERVATION"))
    assert GATE_55 in _gate_codes(r)


def test_g1918_alias_arpi_naive_es_works():
    """H.G1918 — alias `arpi_naive_for_m0_crpc` (variant) dispara Path A gate 55."""
    r = _evaluate({
        "psa_doubling_time_months": 8.0,
        "m0_crpc_state_confirmed": "Sí",
        "arpi_naive_for_m0_crpc": "Sí",
    }, treatments=_tx("OBSERVATION"))
    assert GATE_55 in _gate_codes(r)


# ───────────────────────────────────────────────
# §H — Catálogo + clasificadores + smoke E2E
# ───────────────────────────────────────────────


@pytest.mark.parametrize("gate_code", [GATE_53, GATE_54, GATE_55])
def test_g1919_gates_53_55_in_yaml_catalog(gate_code):
    """H.G1919 — Gates 53/54/55 cargados en catálogo YAML."""
    from prostanet.shared.pivotal_gates_yaml_loader import get_loaded_yaml_codes
    assert gate_code in get_loaded_yaml_codes()


@pytest.mark.parametrize("gate_code", [GATE_53, GATE_54, GATE_55])
def test_g1920_gates_53_55_in_active_codes(gate_code):
    """H.G1920 — Gates 53/54/55 en `get_active_gate_codes()`."""
    from prostanet.shared.algorithm_version import get_active_gate_codes
    assert gate_code in get_active_gate_codes()


def test_g1921_total_gates_at_least_55():
    """H.G1921 — Total gates activos ≥55 (forward-compat con catálogo creciente)."""
    from prostanet.shared.algorithm_version import get_active_gate_codes
    assert len(get_active_gate_codes()) >= 55


def test_g1922_classifier_pivotal_gate_delta_labels():
    """H.G1922 — `_GATE_EXACT_CLASSES` incluye los 3 class labels específicos."""
    from prostanet.shared.pivotal_gate_delta import _GATE_EXACT_CLASSES
    assert _GATE_EXACT_CLASSES.get(GATE_53) is not None
    assert _GATE_EXACT_CLASSES.get(GATE_54) is not None
    assert _GATE_EXACT_CLASSES.get(GATE_55) is not None
    assert "Stephenson" in _GATE_EXACT_CLASSES.get(GATE_53, "")
    assert "Crook" in _GATE_EXACT_CLASSES.get(GATE_54, "") or "Phoenix" in _GATE_EXACT_CLASSES.get(GATE_54, "")
    assert "SPARTAN" in _GATE_EXACT_CLASSES.get(GATE_55, "") or "PROSPER" in _GATE_EXACT_CLASSES.get(GATE_55, "")


def test_g1923_classifier_profile_compass_labels():
    """H.G1923 — profile_compass produce 3 class labels en by_class."""
    from prostanet.domains.patient_tracking.profile_compass import (
        _build_pivotal_contraindication_gates_panel as _builder,
    )
    raw_assessment = {
        "result_snapshot": {
            "pivotal_contraindication_gates": [
                {"code": GATE_53, "title": "x", "severity": "soft_warning", "message": "x", "evidence_tag": "x", "trial_refs": []},
                {"code": GATE_54, "title": "x", "severity": "soft_warning", "message": "x", "evidence_tag": "x", "trial_refs": []},
                {"code": GATE_55, "title": "x", "severity": "soft_warning", "message": "x", "evidence_tag": "x", "trial_refs": []},
            ],
        },
    }
    panel = _builder(raw_assessment)
    by_class = set((panel.get("by_class") or {}).keys())
    assert any("BCR agresivo" in label for label in by_class)
    assert any("PSA bounce" in label for label in by_class)
    assert any("PSADT" in label and "m0CRPC" in label for label in by_class)


def test_g1924_evidence_tags_include_pivotal_trials():
    """H.G1924 — evidence_tags citan ensayos pivotales (Stephenson, Crook, SPARTAN/PROSPER/ARAMIS)."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files
    files = _load_yaml_files()
    assert "stephenson" in files[GATE_53].get("evidence_tag", "").lower()
    assert "crook" in files[GATE_54].get("evidence_tag", "").lower() or "phoenix" in files[GATE_54].get("evidence_tag", "").lower()
    assert "spartan" in files[GATE_55].get("evidence_tag", "").lower()


def test_g1925_yaml_validation_passes():
    """H.G1925 — YAML configs gates 53/54/55 pasan validación schema."""
    from prostanet.shared.pivotal_gates_yaml_loader import (
        _load_yaml_files,
        validate_yaml_gate_config,
    )
    files = _load_yaml_files()
    for code in [GATE_53, GATE_54, GATE_55]:
        config = files.get(code)
        assert config is not None
        errors = validate_yaml_gate_config(config)
        assert errors == [], f"YAML validation errors for {code}: {errors}"


def test_g1926_smoke_e2e_full_psa_kinetics_panel():
    """H.G1926 — E2E paciente complejo con 3 escenarios kinetics → todos los gates fire."""
    r = _evaluate({
        # Gate 53 — BCR aggressive
        "psa_doubling_time_months": 2.0,
        "prior_radical_prostatectomy_documented": "Sí",
        # Gate 54 — PSA bounce post-RT
        "psa_rise_above_nadir_ng_ml": 0.8,
        "months_post_rt": 20,
        "no_image_progression_documented": "Sí",
        # Gate 55 — PSADT m0CRPC
        "m0_crpc_state_confirmed": "Sí",
        "no_active_arpi_for_m0_crpc": "Sí",
    }, treatments=_tx("OBSERVATION"))
    codes = set(_gate_codes(r))
    assert ALL_KINETICS_GATES.issubset(codes)


def test_g1927_smoke_e2e_healthy_patient_no_kinetics_alerts():
    """H.G1927 — Paciente sano (PSADT >12, sin RP, sin RT, sin m0CRPC) NO dispara gates kinetics."""
    r = _evaluate({
        "psa_doubling_time_months": 24.0,
        "psa_value": 0.2,
    }, treatments=_tx("OBSERVATION"))
    codes = set(_gate_codes(r))
    assert not ALL_KINETICS_GATES.intersection(codes)


def test_g1928_message_gate_53_cites_stephenson_salvage_rt():
    """H.G1928 — Mensaje gate 53 cita Stephenson + salvage RT urgente + GETUG-AFU-16/RTOG-9601."""
    r = _evaluate({
        "psa_doubling_time_months": 2.0,
        "prior_radical_prostatectomy_documented": "Sí",
    }, treatments=_tx("OBSERVATION"))
    gate_data = next((g for g in r["gates_triggered"] if g["code"] == GATE_53), None)
    assert gate_data is not None
    msg = gate_data.get("message", "")
    assert "Stephenson" in msg
    assert "salvage RT" in msg.lower() or "salvage rt" in msg.lower()
    assert "GETUG-AFU-16" in msg or "RTOG-9601" in msg


def test_g1929_message_gate_54_cites_phoenix_pcwg3():
    """H.G1929 — Mensaje gate 54 cita Phoenix criteria + PCWG3 + bounce evidence."""
    r = _evaluate({
        "psa_bounce_documented_post_rt": "Sí",
    }, treatments=_tx("OBSERVATION"))
    gate_data = next((g for g in r["gates_triggered"] if g["code"] == GATE_54), None)
    assert gate_data is not None
    msg = gate_data.get("message", "")
    assert "Phoenix" in msg
    assert "Crook" in msg or "bounce" in msg.lower()


def test_g1930_message_gate_55_cites_spartan_prosper_aramis():
    """H.G1930 — Mensaje gate 55 cita los 3 ensayos pivote SPARTAN/PROSPER/ARAMIS."""
    r = _evaluate({
        "psa_doubling_time_months": 8.0,
        "m0_crpc_state_confirmed": "Sí",
        "no_active_arpi_for_m0_crpc": "Sí",
    }, treatments=_tx("OBSERVATION"))
    gate_data = next((g for g in r["gates_triggered"] if g["code"] == GATE_55), None)
    assert gate_data is not None
    msg = gate_data.get("message", "")
    assert "SPARTAN" in msg
    assert "PROSPER" in msg
    assert "ARAMIS" in msg


# ───────────────────────────────────────────────
# §I — Cumplimiento NCCN/EAU/RTOG-ASTRO Phoenix
# ───────────────────────────────────────────────


def test_g1931_message_gate_53_cites_eau_2026():
    """H.G1931 — Mensaje gate 53 cita EAU 2026 §6.4.1 + NCCN PROS-G v5.2026."""
    r = _evaluate({
        "psa_doubling_time_months": 2.0,
        "prior_radical_prostatectomy_documented": "Sí",
    }, treatments=_tx("OBSERVATION"))
    gate_data = next((g for g in r["gates_triggered"] if g["code"] == GATE_53), None)
    assert gate_data is not None
    msg = gate_data.get("message", "")
    assert "EAU 2026" in msg or "EAU Guidelines" in msg
    assert "NCCN" in msg


def test_g1932_message_gate_54_cites_rtog_astro_phoenix_2006():
    """H.G1932 — Mensaje gate 54 cita Roach RTOG-ASTRO Phoenix 2006."""
    r = _evaluate({
        "psa_bounce_documented_post_rt": "Sí",
    }, treatments=_tx("OBSERVATION"))
    gate_data = next((g for g in r["gates_triggered"] if g["code"] == GATE_54), None)
    assert gate_data is not None
    msg = gate_data.get("message", "")
    assert "Phoenix" in msg or "Roach" in msg or "RTOG" in msg


def test_g1933_message_gate_55_cites_mfs_benefit_data():
    """H.G1933 — Mensaje gate 55 cita beneficio MFS específico (40m vs 16m, HR 0.28)."""
    r = _evaluate({
        "psa_doubling_time_months": 8.0,
        "m0_crpc_state_confirmed": "Sí",
        "no_active_arpi_for_m0_crpc": "Sí",
    }, treatments=_tx("OBSERVATION"))
    gate_data = next((g for g in r["gates_triggered"] if g["code"] == GATE_55), None)
    assert gate_data is not None
    msg = gate_data.get("message", "")
    assert "MFS" in msg
    # Check at least one of the pivotal HR values is mentioned
    assert "0.28" in msg or "0.29" in msg or "0.41" in msg


def test_g1934_total_field_specs_includes_13_gates_53_55():
    """H.G1934 — 13 nuevos FieldSpecs (3 gates × ~4 fields cada uno)."""
    from prostanet.shared.advanced_support_fields import pivotal_gate_supporting_fields
    fields = pivotal_gate_supporting_fields()
    field_names = {f.name for f in fields}
    expected = {
        # Gate 53
        "psa_doubling_time_months",
        "psa_velocity_ng_ml_year",
        "prior_radical_prostatectomy_documented",
        "bcr_high_risk_aggressive_documented",
        "bcr_aggressive_treated_for_salvage",
        # Gate 54
        "psa_rise_above_nadir_ng_ml",
        "months_post_rt",
        "psa_bounce_documented_post_rt",
        "psa_elevation_unconfirmed_post_rt",
        # Gate 55
        "m0_crpc_state_confirmed",
        "castrate_testosterone_status_confirmed",
        "no_active_arpi_for_m0_crpc",
        "psadt_progressive_for_arpi_eligibility",
        "arpi_already_initiated_for_m0_crpc",
    }
    missing = expected - field_names
    assert not missing, f"Missing FieldSpecs: {missing}"


def test_g1935_severity_distribution_post_63a():
    """H.G1935 — Post #63A: 4 gates soft_warning (47+53+54+55) + 51 gates hard_block."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files
    files = _load_yaml_files()
    soft_warning_count = sum(1 for c in files.values() if c.get("severity") == "soft_warning")
    hard_block_count = sum(1 for c in files.values() if c.get("severity") == "hard_block")
    assert soft_warning_count >= 4, f"Esperaba ≥4 soft_warning, encontró {soft_warning_count}"
    assert hard_block_count >= 51, f"Esperaba ≥51 hard_block, encontró {hard_block_count}"
