"""tests/test_audit62_gate47_psa_flare_arpi.py — Faubot 2026-04-25 (LVIII).

Tests dedicados a Auditoría #62 — Gate 47 PSA flare primer mes ARPI = pseudo-progresión.

Cubre H.G1621 - H.G1660 (45 hipótesis) en 7 secciones:

§A — Path A: PSA rise ≥25% + tiempo <9 sem + sin imagen progresión
§B — Path B: flag clínico documentado por urólogo/oncólogo
§C — Path C: PSA rise ≥50% + tiempo <5 sem (flare clásico)
§D — ⚠️ severity="soft_warning" — NO bloquea ARPI (decisión arquitectónica nueva)
§E — Coexistencia con gates ARSI hard_block (17-21+31+42)
§F — Aliases canónicos (PSA tracking)
§G — Catálogo + clasificadores + integración

🆕 PRIMER GATE INFORMACIONAL/ANTI-MISINTERPRETATION DEL CATÁLOGO.
Sienta nueva categoría arquitectónica: gates que NO bloquean el régimen
sino que ALERTAN al clínico contra una decisión clínica INCORRECTA
(discontinuación prematura ARPI por mala interpretación de PSA flare).
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


GATE_CODE = "psa_flare_arpi_pseudoprogression"


# ───────────────────────────────────────────────
# §A — Path A: PSA rise ≥25% + tiempo <9 sem + sin imagen progresión
# ───────────────────────────────────────────────


@pytest.mark.parametrize("rise_percent,weeks", [
    (26, 4), (30, 6), (50, 8), (100, 8.5),
])
def test_g1621_path_a_fires(rise_percent, weeks):
    """H.G1621 — Path A dispara con rise>25% + weeks<9 + sin imagen progresión."""
    r = _evaluate({
        "psa_change_percent_since_arpi_start": rise_percent,
        "psa_weeks_since_arpi_start": weeks,
        "no_image_progression_documented": "Sí",
    }, treatments=_tx("ENZALUTAMIDE"))
    assert GATE_CODE in _gate_codes(r)


def test_g1622_path_a_boundary_rise_25_does_NOT_fire():
    """H.G1622 — rise=25 boundary NO dispara (NOT >25)."""
    r = _evaluate({
        "psa_change_percent_since_arpi_start": 25,
        "psa_weeks_since_arpi_start": 4,
        "no_image_progression_documented": "Sí",
    }, treatments=_tx("ENZALUTAMIDE"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1623_path_a_boundary_weeks_9_does_NOT_fire():
    """H.G1623 — weeks=9 boundary NO dispara (NOT <9)."""
    r = _evaluate({
        "psa_change_percent_since_arpi_start": 30,
        "psa_weeks_since_arpi_start": 9,
        "no_image_progression_documented": "Sí",
    }, treatments=_tx("ENZALUTAMIDE"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1624_path_a_with_image_progression_does_NOT_fire():
    """H.G1624 — Path A NO dispara si imagen progresión documentada (no es flare benigno)."""
    r = _evaluate({
        "psa_change_percent_since_arpi_start": 50,
        "psa_weeks_since_arpi_start": 4,
        "no_image_progression_documented": "No",  # imagen muestra progresión
    }, treatments=_tx("ENZALUTAMIDE"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1625_path_a_missing_no_image_flag_does_NOT_fire():
    """H.G1625 — Path A NO dispara sin flag no_image_progression_documented (compound all_of)."""
    r = _evaluate({
        "psa_change_percent_since_arpi_start": 30,
        "psa_weeks_since_arpi_start": 4,
        # no_image_progression_documented = ausente
    }, treatments=_tx("ENZALUTAMIDE"))
    assert GATE_CODE not in _gate_codes(r)


# ───────────────────────────────────────────────
# §B — Path B: flag clínico documentado
# ───────────────────────────────────────────────


def test_g1626_path_b_flag_documented_fires():
    """H.G1626 — psa_flare_documented_first_month_arpi flag dispara Path B."""
    r = _evaluate({
        "psa_flare_documented_first_month_arpi": "Sí",
    }, treatments=_tx("APALUTAMIDE"))
    assert GATE_CODE in _gate_codes(r)


def test_g1627_path_b_alias_psa_flare_arpi_documented_works():
    """H.G1627 — alias `psa_flare_arpi_documented` dispara Path B."""
    r = _evaluate({"psa_flare_arpi_documented": "Sí"}, treatments=_tx("DAROLUTAMIDE"))
    assert GATE_CODE in _gate_codes(r)


def test_g1628_path_b_alias_pseudoprogression_psa_for_arpi_works():
    """H.G1628 — alias `pseudoprogression_psa_for_arpi` dispara Path B."""
    r = _evaluate({"pseudoprogression_psa_for_arpi": "Sí"}, treatments=_tx("ENZALUTAMIDE"))
    assert GATE_CODE in _gate_codes(r)


def test_g1629_path_b_falsy_does_NOT_fire():
    """H.G1629 — flag falsy NO dispara Path B."""
    r = _evaluate({"psa_flare_documented_first_month_arpi": "No"}, treatments=_tx("ENZALUTAMIDE"))
    assert GATE_CODE not in _gate_codes(r)


# ───────────────────────────────────────────────
# §C — Path C: PSA rise ≥50% + tiempo <5 sem (flare clásico)
# ───────────────────────────────────────────────


@pytest.mark.parametrize("rise_percent,weeks", [
    (51, 3), (60, 4), (80, 4.5), (100, 4.9),
])
def test_g1630_path_c_fires(rise_percent, weeks):
    """H.G1630 — Path C dispara con rise>50% + weeks<5 (no requiere no_image flag)."""
    r = _evaluate({
        "psa_change_percent_since_arpi_start": rise_percent,
        "psa_weeks_since_arpi_start": weeks,
    }, treatments=_tx("ENZALUTAMIDE"))
    assert GATE_CODE in _gate_codes(r)


def test_g1631_path_c_boundary_rise_50_does_NOT_fire():
    """H.G1631 — rise=50 boundary NO dispara (NOT >50)."""
    r = _evaluate({
        "psa_change_percent_since_arpi_start": 50,
        "psa_weeks_since_arpi_start": 3,
    }, treatments=_tx("ENZALUTAMIDE"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1632_path_c_boundary_weeks_5_does_NOT_fire():
    """H.G1632 — weeks=5 boundary NO dispara (NOT <5)."""
    r = _evaluate({
        "psa_change_percent_since_arpi_start": 80,
        "psa_weeks_since_arpi_start": 5,
    }, treatments=_tx("ENZALUTAMIDE"))
    # Pero Path A puede disparar si rise>25 + weeks<9 + sin imagen — verificar combinación
    # Aquí sin no_image flag → Path A NO dispara, Path C NO dispara → gate NO fires
    assert GATE_CODE not in _gate_codes(r)


# ───────────────────────────────────────────────
# §D — ⚠️ severity="soft_warning" NO bloquea ARPI
# ───────────────────────────────────────────────
# Esta sección valida arquitectónicamente la nueva categoría de gates
# informacional/anti-misinterpretation. Sienta precedente para gates futuros.


def test_g1633_yaml_severity_is_soft_warning():
    """H.G1633 — Gate 47 YAML config tiene severity='soft_warning' (decisión arquitectónica)."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files
    files = _load_yaml_files()
    config = files.get(GATE_CODE)
    assert config is not None
    assert config.get("severity") == "soft_warning", (
        "Gate 47 debe tener severity='soft_warning' — gate informacional/anti-misinterpretation"
    )


@pytest.mark.parametrize("arpi_code", ["ENZALUTAMIDE", "ADT_ENZALUTAMIDE", "APALUTAMIDE", "ADT_APALUTAMIDE", "DAROLUTAMIDE", "ADT_DAROLUTAMIDE"])
def test_g1634_soft_warning_does_NOT_filter_arpi(arpi_code):
    """H.G1634 — Gate 47 dispara pero NO filtra ARPI (soft_warning behavior)."""
    r = _evaluate({
        "psa_change_percent_since_arpi_start": 30,
        "psa_weeks_since_arpi_start": 4,
        "no_image_progression_documented": "Sí",
    }, treatments=_tx(arpi_code))
    assert GATE_CODE in _gate_codes(r)
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 1, f"ARPI {arpi_code} debe seguir disponible (gate 47 soft_warning)"


def test_g1635_message_in_gate_data_for_clinician_display():
    """H.G1635 — Gate 47 mensaje educacional accesible en gate data para UI display."""
    r = _evaluate({
        "psa_flare_documented_first_month_arpi": "Sí",
    }, treatments=_tx("ENZALUTAMIDE"))
    gate_data = next((g for g in r["gates_triggered"] if g["code"] == GATE_CODE), None)
    assert gate_data is not None
    msg = gate_data.get("message", "")
    assert "PSA FLARE" in msg or "flare" in msg.lower()
    assert "PCWG3" in msg
    assert "discontinuar" in msg.lower() or "continuar" in msg.lower()


def test_g1636_filter_treatments_by_gates_skips_soft_warning():
    """H.G1636 — Verificar arquitectónicamente que filter_treatments_by_gates respeta severity."""
    from prostanet.shared.pivotal_contraindication_gates import filter_treatments_by_gates
    treatments = [{"name": "ENZALUTAMIDE", "regimen_code": "ENZALUTAMIDE"}]
    soft_gate = {
        "code": "test_soft",
        "severity": "soft_warning",
        "affected_regimen_codes": frozenset({"ENZALUTAMIDE"}),
        "affected_keywords": ("enzalutamide",),
        "message": "test message",
    }
    filtered, msgs = filter_treatments_by_gates(treatments, [soft_gate])
    assert len(filtered) == 1, "soft_warning gates NO deben filtrar treatments"
    assert msgs == [], "soft_warning gates NO deben añadir mensajes a not_recommended"


def test_g1637_filter_treatments_by_gates_blocks_hard_block():
    """H.G1637 — filter_treatments_by_gates SÍ bloquea con severity=hard_block (back-compat)."""
    from prostanet.shared.pivotal_contraindication_gates import filter_treatments_by_gates
    treatments = [{"name": "ENZALUTAMIDE", "regimen_code": "ENZALUTAMIDE"}]
    hard_gate = {
        "code": "test_hard",
        "severity": "hard_block",
        "affected_regimen_codes": frozenset({"ENZALUTAMIDE"}),
        "affected_keywords": ("enzalutamide",),
        "message": "test hard block message",
    }
    filtered, msgs = filter_treatments_by_gates(treatments, [hard_gate])
    assert len(filtered) == 0, "hard_block gates DEBEN filtrar treatments"
    assert "test hard block message" in msgs


def test_g1638_filter_treatments_by_gates_default_is_hard_block():
    """H.G1638 — Gates SIN severity explícita defaultean a hard_block (back-compat con gates pre-#62)."""
    from prostanet.shared.pivotal_contraindication_gates import filter_treatments_by_gates
    treatments = [{"name": "ENZALUTAMIDE", "regimen_code": "ENZALUTAMIDE"}]
    legacy_gate = {
        "code": "test_legacy",
        # NO severity — default hard_block
        "affected_regimen_codes": frozenset({"ENZALUTAMIDE"}),
        "affected_keywords": ("enzalutamide",),
        "message": "legacy gate message",
    }
    filtered, msgs = filter_treatments_by_gates(treatments, [legacy_gate])
    assert len(filtered) == 0, "Legacy gates sin severity defaultean a hard_block (back-compat)"


# ───────────────────────────────────────────────
# §E — Coexistencia con gates ARSI hard_block (17-21+31+42)
# ───────────────────────────────────────────────


def test_g1639_coexistence_with_gate_17_qtc():
    """H.G1639 — Gate 17 QTc (hard_block) bloquea ARPI; gate 47 (soft_warning) coexiste sin filtrar adicional."""
    r = _evaluate({
        "qtc_ms": 520,  # gate 17 hard_block
        "psa_change_percent_since_arpi_start": 30,
        "psa_weeks_since_arpi_start": 4,
        "no_image_progression_documented": "Sí",
    }, treatments=_tx("ENZALUTAMIDE"))
    codes = set(_gate_codes(r))
    # Ambos gates disparan
    assert GATE_CODE in codes
    assert "qtc_prolongation_grade3_for_enzalutamide" in codes
    # ENZALUTAMIDE filtrada por gate 17 (no por gate 47)
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 0


def test_g1640_coexistence_with_gate_42_sjs_apalutamide():
    """H.G1640 — Gate 42 SJS (hard_block, sin override) bloquea apalutamida; gate 47 coexiste."""
    r = _evaluate({
        "sjs_ten_suspected_or_diagnosed": "Sí",  # gate 42
        "psa_flare_documented_first_month_arpi": "Sí",  # gate 47
    }, treatments=_tx("APALUTAMIDE"))
    codes = set(_gate_codes(r))
    assert GATE_CODE in codes
    assert "apalutamide_severe_rash_sjs_ten" in codes
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 0


def test_g1641_coexistence_with_gate_31_enzalutamide_cognitive():
    """H.G1641 — Gate 31 enza cognitive elderly + gate 47 coexisten en mismo paciente."""
    r = _evaluate({
        "patient_age": 80,
        "mmse_baseline_score": 22,  # gate 31
        "psa_change_percent_since_arpi_start": 80,
        "psa_weeks_since_arpi_start": 3,  # gate 47 Path C
    }, treatments=_tx("ENZALUTAMIDE"))
    codes = set(_gate_codes(r))
    assert GATE_CODE in codes
    assert "enzalutamide_cognitive_decline_elderly" in codes


# ───────────────────────────────────────────────
# §F — Aliases canónicos
# ───────────────────────────────────────────────


def test_g1642_alias_psa_change_percent_works():
    """H.G1642 — alias `psa_change_percent` dispara (sin _since_arpi_start)."""
    r = _evaluate({
        "psa_change_percent": 30,
        "psa_weeks_since_arpi_start": 4,
        "no_image_progression_documented": "Sí",
    }, treatments=_tx("ENZALUTAMIDE"))
    assert GATE_CODE in _gate_codes(r)


def test_g1643_alias_psa_relative_change_works():
    """H.G1643 — alias `psa_relative_change` dispara."""
    r = _evaluate({
        "psa_relative_change": 80,
        "psa_weeks_since_arpi_start": 3,
    }, treatments=_tx("ENZALUTAMIDE"))
    assert GATE_CODE in _gate_codes(r)


def test_g1644_alias_weeks_on_arpi_works():
    """H.G1644 — alias `weeks_on_arpi` dispara."""
    r = _evaluate({
        "psa_change_percent_since_arpi_start": 30,
        "weeks_on_arpi": 4,
        "no_image_progression_documented": "Sí",
    }, treatments=_tx("ENZALUTAMIDE"))
    assert GATE_CODE in _gate_codes(r)


def test_g1645_alias_no_imaging_progression_works():
    """H.G1645 — alias `no_imaging_progression` dispara Path A."""
    r = _evaluate({
        "psa_change_percent_since_arpi_start": 30,
        "psa_weeks_since_arpi_start": 4,
        "no_imaging_progression": "Sí",
    }, treatments=_tx("ENZALUTAMIDE"))
    assert GATE_CODE in _gate_codes(r)


def test_g1646_alias_imaging_stable_during_psa_flare_works():
    """H.G1646 — alias `imaging_stable_during_psa_flare` dispara Path A."""
    r = _evaluate({
        "psa_change_percent_since_arpi_start": 30,
        "psa_weeks_since_arpi_start": 4,
        "imaging_stable_during_psa_flare": "Sí",
    }, treatments=_tx("ENZALUTAMIDE"))
    assert GATE_CODE in _gate_codes(r)


# ───────────────────────────────────────────────
# §G — Catálogo + clasificadores + integración
# ───────────────────────────────────────────────


def test_g1647_gate_47_in_yaml_catalog():
    """H.G1647 — Gate 47 cargado en catálogo YAML."""
    from prostanet.shared.pivotal_gates_yaml_loader import get_loaded_yaml_codes
    assert GATE_CODE in get_loaded_yaml_codes()


def test_g1648_gate_47_in_active_codes():
    """H.G1648 — Gate 47 en `get_active_gate_codes()`."""
    from prostanet.shared.algorithm_version import get_active_gate_codes
    assert GATE_CODE in get_active_gate_codes()


def test_g1649_total_gates_at_least_47():
    """H.G1649 — Total gates activos ≥47."""
    from prostanet.shared.algorithm_version import get_active_gate_codes
    assert len(get_active_gate_codes()) >= 47


def test_g1650_classifier_pivotal_gate_delta_label():
    """H.G1650 — `_GATE_EXACT_CLASSES` incluye class label específico."""
    from prostanet.shared.pivotal_gate_delta import _GATE_EXACT_CLASSES
    label = _GATE_EXACT_CLASSES.get(GATE_CODE)
    assert label is not None
    assert "PSA flare" in label
    assert "PCWG3" in label
    assert "anti-misinterpretation" in label


def test_g1651_classifier_profile_compass_label():
    """H.G1651 — profile_compass _classify produce class label en by_class."""
    from prostanet.domains.patient_tracking.profile_compass import (
        _build_pivotal_contraindication_gates_panel as _builder,
    )
    raw_assessment = {
        "result_snapshot": {
            "pivotal_contraindication_gates": [{
                "code": GATE_CODE,
                "title": "x",
                "severity": "soft_warning",
                "message": "x",
                "evidence_tag": "x",
                "trial_refs": [],
            }],
        },
    }
    panel = _builder(raw_assessment)
    by_class = panel.get("by_class") or {}
    assert any("PSA flare ARPI" in label for label in by_class.keys()), (
        f"Class label 'PSA flare ARPI' debe estar en by_class — found: {list(by_class.keys())}"
    )


def test_g1652_evidence_tag_pcwg3():
    """H.G1652 — evidence_tag cita PCWG3 + ARPI trials."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files
    files = _load_yaml_files()
    config = files.get(GATE_CODE)
    assert config is not None
    et = config.get("evidence_tag", "")
    assert "pcwg3" in et.lower()
    refs = config.get("trial_refs") or []
    assert "PCWG3 Scher JCO 2016" in refs


def test_g1653_smoke_e2e_psa_flare_continues_arpi():
    """H.G1653 — E2E: paciente con PSA flare + ARPI → gate fires + ARPI continues + mensaje educa."""
    r = _evaluate({
        "psa_change_percent_since_arpi_start": 60,
        "psa_weeks_since_arpi_start": 3,
        "no_image_progression_documented": "Sí",
    }, treatments=_tx("ENZALUTAMIDE"))
    # Gate fires
    codes = _gate_codes(r)
    assert GATE_CODE in codes
    # ARPI continues
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 1
    # Mensaje educacional accesible
    gate_data = next((g for g in r["gates_triggered"] if g["code"] == GATE_CODE), None)
    assert gate_data.get("severity") == "soft_warning"
    msg = gate_data.get("message", "")
    assert "NO discontinuar" in msg or "no discontinuar" in msg.lower()


def test_g1654_healthy_patient_no_psa_flare():
    """H.G1654 — paciente sin PSA flare NO dispara gate 47."""
    r = _evaluate({
        "psa_change_percent_since_arpi_start": 5,
        "psa_weeks_since_arpi_start": 8,
    }, treatments=_tx("ENZALUTAMIDE"))
    assert GATE_CODE not in _gate_codes(r)
