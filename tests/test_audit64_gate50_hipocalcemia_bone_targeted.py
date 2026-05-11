"""tests/test_audit64_gate50_hipocalcemia_bone_targeted.py — Faubot 2026-04-25 (LXI).

Tests dedicados a Auditoría #64 — Gate 50 Hipocalcemia EXTENDIDA bone-targeted.

Cubre H.G1741 - H.G1785 (45 hipótesis) en 8 secciones:

§A — REGIMEN_CODES_BONE_TARGETED catálogo (Ra-223 + Lu-177 + denosumab + bisfos)
§B — Path A: Ca corregido <8.0 mg/dL (CTCAE v5 G≥3 severo)
§C — Path B: Ca <7.0 mg/dL (G≥4 emergencia tetania)
§D — Path C: Ca ionizado <1.0 mmol/L (gold standard)
§E — Path D: tetania compound (Chvostek+Trousseau+parestesias)
§F — Path E + Override
§G — Coexistencia con gate 12 (Ra-223 limitado)
§H — Catálogo + clasificadores + smoke E2E

🆕 EXTIENDE GATE 12 (Ra-223 limitado) → CLASE ENTERA bone-targeted.
Sienta categoría bone-modifying agents completa (Ra-223 + Lu-177 +
denosumab + bisfosfonatos).
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


GATE_CODE = "bone_targeted_hypocalcemia_extended"


# ───────────────────────────────────────────────
# §A — REGIMEN_CODES_BONE_TARGETED catálogo
# ───────────────────────────────────────────────


def test_g1741_regimen_codes_bone_targeted_exists():
    """H.G1741 — REGIMEN_CODES_BONE_TARGETED frozenset definida."""
    from prostanet.shared.pivotal_contraindication_gates import REGIMEN_CODES_BONE_TARGETED
    assert isinstance(REGIMEN_CODES_BONE_TARGETED, frozenset)
    assert len(REGIMEN_CODES_BONE_TARGETED) >= 14  # Ra-223 (3) + Lu-177 (4) + denosumab (3) + bisfos (8)


@pytest.mark.parametrize("code", [
    # Radiopharmaceuticals
    "RADIUM_223", "RA_223", "RADIUM223",
    "LU177_PSMA617", "LU_177_PSMA", "LUTETIUM_177_PSMA", "PLUVICTO",
    # Denosumab
    "DENOSUMAB", "XGEVA", "DENOSUMAB_120MG",
    # Bisfosfonatos IV
    "ZOLEDRONATE", "ZOLEDRONIC_ACID", "ZOMETA",
    "PAMIDRONATE", "AREDIA",
    # Bisfosfonatos PO
    "ALENDRONATE", "FOSAMAX", "RISEDRONATE", "ACTONEL",
    "IBANDRONATE", "BONIVA",
])
def test_g1742_regimen_codes_bone_targeted_includes_all(code):
    """H.G1742 — REGIMEN_CODES_BONE_TARGETED incluye los 21 códigos esperados."""
    from prostanet.shared.pivotal_contraindication_gates import REGIMEN_CODES_BONE_TARGETED
    assert code in REGIMEN_CODES_BONE_TARGETED


def test_g1743_keywords_bone_targeted_includes_brand_names():
    """H.G1743 — KEYWORDS_BONE_TARGETED incluye brand names + ES + bisfosfonato."""
    from prostanet.shared.pivotal_contraindication_gates import KEYWORDS_BONE_TARGETED
    expected = {
        "denosumab", "xgeva", "zoledronate", "zometa",
        "alendronate", "fosamax", "bisphosphonate",
        "ácido zoledrónico", "bisfosfonato",
        "lu-177", "ra-223", "pluvicto",
    }
    assert expected.issubset(set(KEYWORDS_BONE_TARGETED))


# ───────────────────────────────────────────────
# §B — Path A: Ca corregido <8.0 mg/dL
# ───────────────────────────────────────────────


@pytest.mark.parametrize("ca_value", [7.9, 7.5, 7.0, 6.5, 6.0])
def test_g1744_path_a_calcium_below_8_fires(ca_value):
    """H.G1744 — Ca corregido <8.0 dispara Path A (también activa Path B si <7.0)."""
    r = _evaluate({"corrected_calcium": ca_value}, treatments=_tx("DENOSUMAB"))
    assert GATE_CODE in _gate_codes(r)


@pytest.mark.parametrize("ca_value", [8.0, 8.5, 9.0, 10.0])
def test_g1745_path_a_calcium_ge_8_does_NOT_fire(ca_value):
    """H.G1745 — Ca corregido ≥8.0 NO dispara Path A (boundary 8.0 NOT <8.0)."""
    r = _evaluate({"corrected_calcium": ca_value}, treatments=_tx("DENOSUMAB"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1746_path_a_filters_denosumab_hard_block():
    """H.G1746 — gate 50 hard_block FILTRA denosumab (count=0)."""
    r = _evaluate({"corrected_calcium": 7.5}, treatments=_tx("DENOSUMAB"))
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 0


@pytest.mark.parametrize("bone_code", [
    "DENOSUMAB", "XGEVA", "ZOLEDRONATE", "ZOMETA",
    "PAMIDRONATE", "ALENDRONATE", "LU177_PSMA617", "PLUVICTO",
])
def test_g1747_bone_targeted_regimens_filtered(bone_code):
    """H.G1747 — gate 50 filtra TODOS los regímenes bone-targeted."""
    r = _evaluate({"corrected_calcium": 7.5}, treatments=_tx(bone_code))
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 0, f"Bone-targeted {bone_code} debe ser filtrada"


# ───────────────────────────────────────────────
# §C — Path B: Ca <7.0 (G4 emergencia)
# ───────────────────────────────────────────────


@pytest.mark.parametrize("ca_value", [6.9, 6.5, 6.0, 5.5])
def test_g1748_path_b_calcium_below_7_fires(ca_value):
    """H.G1748 — Ca <7.0 dispara Path B (G4 emergencia, riesgo tetania franca)."""
    r = _evaluate({"corrected_calcium": ca_value}, treatments=_tx("ZOLEDRONATE"))
    assert GATE_CODE in _gate_codes(r)


def test_g1749_path_b_boundary_7_does_NOT_fire_path_b_but_path_a_does():
    """H.G1749 — Ca=7.0 NOT <7.0 (Path B no fires) pero <8.0 SÍ (Path A fires)."""
    r = _evaluate({"corrected_calcium": 7.0}, treatments=_tx("ZOLEDRONATE"))
    # Path A fires (Ca <8.0)
    assert GATE_CODE in _gate_codes(r)


# ───────────────────────────────────────────────
# §D — Path C: Ca ionizado <1.0 mmol/L (gold standard)
# ───────────────────────────────────────────────


@pytest.mark.parametrize("ica_value", [0.99, 0.90, 0.80, 0.70])
def test_g1750_path_c_ionized_calcium_below_1_fires(ica_value):
    """H.G1750 — Ca ionizado <1.0 mmol/L dispara Path C (gold standard, sin afect albúmina)."""
    r = _evaluate({"ionized_calcium_mmol_l": ica_value}, treatments=_tx("XGEVA"))
    assert GATE_CODE in _gate_codes(r)


@pytest.mark.parametrize("ica_value", [1.0, 1.10, 1.20, 1.30])
def test_g1751_path_c_ionized_calcium_ge_1_does_NOT_fire(ica_value):
    """H.G1751 — Ca ionizado ≥1.0 NO dispara Path C (boundary 1.0 NOT <1.0)."""
    r = _evaluate({"ionized_calcium_mmol_l": ica_value}, treatments=_tx("XGEVA"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1752_path_c_alias_calcio_ionizado_es_works():
    """H.G1752 — alias `calcio_ionizado` (ES) dispara Path C."""
    r = _evaluate({"calcio_ionizado": 0.9}, treatments=_tx("DENOSUMAB"))
    assert GATE_CODE in _gate_codes(r)


# ───────────────────────────────────────────────
# §E — Path D: tetania compound
# ───────────────────────────────────────────────


def test_g1753_path_d_tetany_compound_fires():
    """H.G1753 — Chvostek + Trousseau + parestesias compound dispara Path D (patognomónico)."""
    r = _evaluate({
        "chvostek_sign_positive": "Sí",
        "trousseau_sign_positive": "Sí",
        "perioral_paresthesias_documented": "Sí",
    }, treatments=_tx("PAMIDRONATE"))
    assert GATE_CODE in _gate_codes(r)


def test_g1754_path_d_missing_chvostek_does_NOT_fire():
    """H.G1754 — Path D NO dispara sin Chvostek (compound all_of)."""
    r = _evaluate({
        "trousseau_sign_positive": "Sí",
        "perioral_paresthesias_documented": "Sí",
    }, treatments=_tx("DENOSUMAB"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1755_path_d_missing_trousseau_does_NOT_fire():
    """H.G1755 — Path D NO dispara sin Trousseau (compound all_of)."""
    r = _evaluate({
        "chvostek_sign_positive": "Sí",
        "perioral_paresthesias_documented": "Sí",
    }, treatments=_tx("DENOSUMAB"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1756_path_d_missing_paresthesias_does_NOT_fire():
    """H.G1756 — Path D NO dispara sin parestesias (compound all_of)."""
    r = _evaluate({
        "chvostek_sign_positive": "Sí",
        "trousseau_sign_positive": "Sí",
    }, treatments=_tx("DENOSUMAB"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1757_path_d_alias_chvostek_positivo_es_works():
    """H.G1757 — alias `chvostek_positivo` (ES) en Path D compound."""
    r = _evaluate({
        "chvostek_positivo": "Sí",
        "trousseau_positivo": "Sí",
        "parestesias_periorales": "Sí",
    }, treatments=_tx("DENOSUMAB"))
    assert GATE_CODE in _gate_codes(r)


# ───────────────────────────────────────────────
# §F — Path E + Override
# ───────────────────────────────────────────────


def test_g1758_path_e_flag_documented_fires():
    """H.G1758 — hypocalcemia_documented_for_bone_targeted flag dispara Path E."""
    r = _evaluate({
        "hypocalcemia_documented_for_bone_targeted": "Sí",
    }, treatments=_tx("LU177_PSMA617"))
    assert GATE_CODE in _gate_codes(r)


def test_g1759_path_e_alias_severe_hypocalcemia_for_bone_modifying_works():
    """H.G1759 — alias `severe_hypocalcemia_for_bone_modifying` dispara Path E."""
    r = _evaluate({
        "severe_hypocalcemia_for_bone_modifying": "Sí",
    }, treatments=_tx("DENOSUMAB"))
    assert GATE_CODE in _gate_codes(r)


def test_g1760_override_hypocalcemia_resolved_disables():
    """H.G1760 — override `hypocalcemia_resolved_for_bone_targeted=Sí` desactiva."""
    r = _evaluate({
        "corrected_calcium": 7.5,
        "hypocalcemia_resolved_for_bone_targeted": "Sí",
    }, treatments=_tx("DENOSUMAB"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1761_override_alias_calcium_recovered_works():
    """H.G1761 — alias override `calcium_recovered_for_bone_targeted` desactiva."""
    r = _evaluate({
        "corrected_calcium": 7.5,
        "calcium_recovered_for_bone_targeted": "Sí",
    }, treatments=_tx("DENOSUMAB"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1762_override_alias_hypocalcemia_corrected_for_bone_targeted_works():
    """H.G1762 — alias override `hypocalcemia_corrected_for_bone_targeted` desactiva."""
    r = _evaluate({
        "corrected_calcium": 7.5,
        "hypocalcemia_corrected_for_bone_targeted": "Sí",
    }, treatments=_tx("DENOSUMAB"))
    assert GATE_CODE not in _gate_codes(r)


# ───────────────────────────────────────────────
# §G — Coexistencia con gate 12 (Ra-223 limitado)
# ───────────────────────────────────────────────
# Gate 50 es SUPERSET de gate 12. Mismo paciente con Ra-223 puede activar
# AMBOS gates. Tests validan back-compat (gate 12 sigue funcional).


def test_g1763_coexistence_gate_12_and_gate_50_with_radium223():
    """H.G1763 — Ra-223 + Ca <8.0 dispara AMBOS gate 12 (Ra-223 limitado) + gate 50 (extendido)."""
    r = _evaluate({"corrected_calcium": 7.5}, treatments=_tx("RADIUM_223"))
    codes = set(_gate_codes(r))
    assert "radium223_in_hypocalcemia" in codes  # gate 12
    assert GATE_CODE in codes  # gate 50


def test_g1764_gate_50_only_for_denosumab():
    """H.G1764 — Denosumab + Ca <8.0 dispara gate 50 (gate 12 también fires pero no bloquea denosumab)."""
    r = _evaluate({"corrected_calcium": 7.5}, treatments=_tx("DENOSUMAB"))
    codes = set(_gate_codes(r))
    assert GATE_CODE in codes
    # Gate 12 también dispara (su trigger es independiente del scope), pero
    # solo bloquea Ra-223 — denosumab es bloqueado por gate 50.
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 0  # denosumab filtrada por gate 50


def test_g1765_enzalutamide_NOT_filtered_by_gate_50():
    """H.G1765 — ENZALUTAMIDE NO es filtrada por gate 50 (no es bone-targeted)."""
    r = _evaluate({"corrected_calcium": 7.5}, treatments=_tx("ENZALUTAMIDE"))
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 1, "Enzalutamida no es bone-targeted, no debe filtrarse"


def test_g1766_apalutamide_NOT_filtered_by_gate_50():
    """H.G1766 — APALUTAMIDE NO es filtrada por gate 50."""
    r = _evaluate({"corrected_calcium": 7.5}, treatments=_tx("APALUTAMIDE"))
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 1


def test_g1767_abiraterone_NOT_filtered_by_gate_50():
    """H.G1767 — ABIRATERONE NO es filtrada por gate 50."""
    r = _evaluate({"corrected_calcium": 7.5}, treatments=_tx("ADT_ABIRATERONE"))
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 1


# ───────────────────────────────────────────────
# §H — Catálogo + clasificadores + smoke E2E
# ───────────────────────────────────────────────


def test_g1768_gate_50_in_yaml_catalog():
    """H.G1768 — Gate 50 cargado en catálogo YAML."""
    from prostanet.shared.pivotal_gates_yaml_loader import get_loaded_yaml_codes
    assert GATE_CODE in get_loaded_yaml_codes()


def test_g1769_gate_50_in_active_codes():
    """H.G1769 — Gate 50 en `get_active_gate_codes()`."""
    from prostanet.shared.algorithm_version import get_active_gate_codes
    assert GATE_CODE in get_active_gate_codes()


def test_g1770_total_gates_at_least_50():
    """H.G1770 — Total gates activos ≥50."""
    from prostanet.shared.algorithm_version import get_active_gate_codes
    assert len(get_active_gate_codes()) >= 50


def test_g1771_classifier_pivotal_gate_delta_label():
    """H.G1771 — `_GATE_EXACT_CLASSES` incluye class label específico."""
    from prostanet.shared.pivotal_gate_delta import _GATE_EXACT_CLASSES
    label = _GATE_EXACT_CLASSES.get(GATE_CODE)
    assert label is not None
    assert "Hipocalcemia" in label
    assert "bone-targeted" in label.lower()
    assert "ASCO" in label or "Henry" in label


def test_g1772_classifier_profile_compass_label():
    """H.G1772 — profile_compass produce class label en by_class."""
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
    assert any("Hipocalcemia bone-targeted" in label for label in by_class.keys()), (
        f"Class label 'Hipocalcemia bone-targeted' debe estar en by_class — "
        f"found: {list(by_class.keys())}"
    )


def test_g1773_evidence_tag_includes_asco_henry_fizazi():
    """H.G1773 — evidence_tag cita ASCO Bone Health 2024 + Henry/Fizazi 2011."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files
    files = _load_yaml_files()
    config = files.get(GATE_CODE)
    assert config is not None
    et = config.get("evidence_tag", "").lower()
    assert "asco_bone_health" in et
    assert "henry" in et or "fizazi" in et


def test_g1774_severity_is_hard_block():
    """H.G1774 — Gate 50 severity='hard_block' (NO informacional)."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files
    files = _load_yaml_files()
    config = files.get(GATE_CODE)
    assert config is not None
    assert config.get("severity") == "hard_block"


def test_g1775_smoke_e2e_full_hypocalcemia_panel():
    """H.G1775 — E2E paciente con hipocalcemia G4 + tetania (5 paths) → gate fires + denosumab filtrado + evidence."""
    r = _evaluate({
        "corrected_calcium": 6.5,  # Path A + Path B
        "ionized_calcium_mmol_l": 0.85,  # Path C
        "chvostek_sign_positive": "Sí",
        "trousseau_sign_positive": "Sí",
        "perioral_paresthesias_documented": "Sí",  # Path D compound
        "hypocalcemia_documented_for_bone_targeted": "Sí",  # Path E
    }, treatments=_tx("DENOSUMAB"))
    # Gate fires
    assert GATE_CODE in _gate_codes(r)
    # Denosumab filtrado (count=0)
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 0
    # Evidence tag presente
    gate_data = next((g for g in r["gates_triggered"] if g["code"] == GATE_CODE), None)
    assert gate_data is not None
    assert "asco_bone_health" in gate_data.get("evidence_tag", "").lower()
    assert gate_data.get("severity") == "hard_block"


def test_g1776_smoke_e2e_healthy_denosumab_no_hypocalcemia():
    """H.G1776 — paciente sano en denosumab NO dispara gate 50."""
    r = _evaluate({
        "corrected_calcium": 9.5,
        "ionized_calcium_mmol_l": 1.20,
        "chvostek_sign_positive": "No",
        "trousseau_sign_positive": "No",
    }, treatments=_tx("DENOSUMAB"))
    assert GATE_CODE not in _gate_codes(r)


def test_g1777_message_cites_profilaxis_vitd_calcio():
    """H.G1777 — Mensaje gate 50 cita PROFILAXIS vitD + Ca + monitoring."""
    r = _evaluate({"corrected_calcium": 6.5}, treatments=_tx("DENOSUMAB"))
    gate_data = next((g for g in r["gates_triggered"] if g["code"] == GATE_CODE), None)
    assert gate_data is not None
    msg = gate_data.get("message", "")
    assert "vitamina d" in msg.lower() or "vitd" in msg.lower() or "vitamina D" in msg
    assert "calcio" in msg.lower() or "Ca" in msg
    assert "tetania" in msg.lower()


def test_g1778_message_cites_alternatives_denosumab_bisfos():
    """H.G1778 — Mensaje gate 50 cita alternativas (cambiar denosumab→bisfos o viceversa)."""
    r = _evaluate({"corrected_calcium": 6.5}, treatments=_tx("DENOSUMAB"))
    gate_data = next((g for g in r["gates_triggered"] if g["code"] == GATE_CODE), None)
    assert gate_data is not None
    msg = gate_data.get("message", "")
    assert "denosumab" in msg.lower()
    assert "bisfos" in msg.lower() or "rebound" in msg.lower()


def test_g1779_total_field_specs_includes_6_gate_50():
    """H.G1779 — 6 nuevos FieldSpecs (Ca ionizado + 3 tetania flags + dx flag + override)."""
    from prostanet.shared.advanced_support_fields import pivotal_gate_supporting_fields
    fields = pivotal_gate_supporting_fields()
    field_names = {f.name for f in fields}
    expected = {
        "ionized_calcium_mmol_l",
        "chvostek_sign_positive",
        "trousseau_sign_positive",
        "perioral_paresthesias_documented",
        "hypocalcemia_documented_for_bone_targeted",
        "hypocalcemia_resolved_for_bone_targeted",
    }
    assert expected.issubset(field_names), f"Missing FieldSpecs: {expected - field_names}"


def test_g1780_yaml_validation_passes():
    """H.G1780 — YAML config gate 50 pasa validación schema."""
    from prostanet.shared.pivotal_gates_yaml_loader import (
        _load_yaml_files,
        validate_yaml_gate_config,
    )
    files = _load_yaml_files()
    config = files.get(GATE_CODE)
    assert config is not None
    errors = validate_yaml_gate_config(config)
    assert errors == [], f"YAML validation errors: {errors}"


def test_g1781_regimen_codes_bone_targeted_is_superset_of_radium223():
    """H.G1781 — REGIMEN_CODES_BONE_TARGETED es superset de REGIMEN_CODES_RADIUM223."""
    from prostanet.shared.pivotal_contraindication_gates import (
        REGIMEN_CODES_BONE_TARGETED,
        REGIMEN_CODES_RADIUM223,
    )
    assert REGIMEN_CODES_RADIUM223.issubset(REGIMEN_CODES_BONE_TARGETED)


def test_g1782_regimen_codes_bone_targeted_is_superset_of_lutetium177():
    """H.G1782 — REGIMEN_CODES_BONE_TARGETED es superset de REGIMEN_CODES_LUTETIUM177."""
    from prostanet.shared.pivotal_contraindication_gates import (
        REGIMEN_CODES_BONE_TARGETED,
        REGIMEN_CODES_LUTETIUM177,
    )
    assert REGIMEN_CODES_LUTETIUM177.issubset(REGIMEN_CODES_BONE_TARGETED)


def test_g1783_regimen_codes_bone_targeted_includes_bisphosphonates():
    """H.G1783 — REGIMEN_CODES_BONE_TARGETED incluye bisfosfonatos (zoledronato, pamidronato, alendronato)."""
    from prostanet.shared.pivotal_contraindication_gates import REGIMEN_CODES_BONE_TARGETED
    bisfos = {"ZOLEDRONATE", "PAMIDRONATE", "ALENDRONATE"}
    assert bisfos.issubset(REGIMEN_CODES_BONE_TARGETED)


def test_g1784_regimen_codes_bone_targeted_includes_denosumab():
    """H.G1784 — REGIMEN_CODES_BONE_TARGETED incluye denosumab + Xgeva."""
    from prostanet.shared.pivotal_contraindication_gates import REGIMEN_CODES_BONE_TARGETED
    denos = {"DENOSUMAB", "XGEVA"}
    assert denos.issubset(REGIMEN_CODES_BONE_TARGETED)


def test_g1785_total_field_specs_count_at_least_152():
    """H.G1785 — Total FieldSpecs en pivotal_gate_supporting_fields() ≥152 (147 prev + 6 nuevos = 153, allow margin)."""
    from prostanet.shared.advanced_support_fields import pivotal_gate_supporting_fields
    assert len(pivotal_gate_supporting_fields()) >= 152
