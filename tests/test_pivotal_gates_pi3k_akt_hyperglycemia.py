"""tests/test_pivotal_gates_pi3k_akt_hyperglycemia.py — FAUBOT 2026-04-25 (XXXIII).

Auditoría #41 — Gate 25 ipatasertib × hyperglycemia G3 (IPATential150).

Cobertura:
  - Triggers: glucose_fasting > 250, HbA1c > 10, ctcae_grade ≥ 3, flag explícito
  - Override hyperglycemia_controlled_for_ipatasertib desactiva
  - Aliases para glucose_fasting (4) + hba1c (3)
  - Boundary cases (glucose ≤ 250, HbA1c ≤ 10)
  - Bloqueo solo regimens IPATASERTIB
  - Coexistencia con Gate 5 (uncontrolled_diabetes general)
  - DDI cross-check mapping (cyp3a4_inhibition + cyp3a4_induction)
  - 5 supporting FieldSpecs declarados
  - Total active gates ≥ 25 (forward-compat)

Hipótesis: H.G771-H.G820 (~50 hipótesis).

Convenciones (CLAUDE.md §8):
  - Tests parametrizados por trigger value + override + alias
  - Cita evidence_tag específico (ipatential150_sweeney_nejm_2022_ctcae_v5)
  - Backward-compat con gates 1-24 anteriores
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest

from prostanet.shared.pivotal_contraindication_gates import (
    apply_pivotal_contraindication_gates,
    REGIMEN_CODES_IPATASERTIB,
)
from prostanet.shared.pivotal_gates_yaml_loader import (
    get_loaded_yaml_codes,
    validate_all_yaml_gates,
)


GATE_CODE = "ipatasertib_hyperglycemia_grade3"


def _gate_codes(payload: dict) -> list[str]:
    """Return list of triggered gate codes for a given payload."""
    r = apply_pivotal_contraindication_gates(payload, treatments=[])
    return [g["code"] for g in r["gates_triggered"]]


# ──────────────────────────────────────────────────────────────────────
# §A. Catalog: Gate 25 cargado correctamente (H.G771-H.G773)
# ──────────────────────────────────────────────────────────────────────


def test_g771_gate_25_loaded_in_yaml_catalog():
    """H.G771 — Gate 25 está presente en YAML catalog."""
    codes = get_loaded_yaml_codes()
    assert GATE_CODE in codes


def test_g772_gate_25_no_validation_errors():
    """H.G772 — Gate 25 YAML pasa validación sin errores."""
    errors = validate_all_yaml_gates()
    assert GATE_CODE not in errors or not errors[GATE_CODE]


def test_g773_yaml_catalog_at_least_25_files():
    """H.G773 — YAML catalog tiene ≥25 archivos (era 24 al cierre #39)."""
    codes = get_loaded_yaml_codes()
    assert len(codes) >= 25


# ──────────────────────────────────────────────────────────────────────
# §B. Trigger 1: glucose_fasting > 250 (H.G774-H.G778)
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("glucose", [251, 280, 350, 500, 600])
def test_g774_fires_on_glucose_above_250(glucose):
    """H.G774 — Gate 25 dispara cuando glucose_fasting > 250."""
    codes = _gate_codes({"glucose_fasting": glucose})
    assert GATE_CODE in codes


@pytest.mark.parametrize("glucose", [80, 100, 150, 200, 250])
def test_g775_no_fire_on_glucose_at_or_below_250(glucose):
    """H.G775 — Gate 25 NO dispara cuando glucose_fasting ≤ 250."""
    codes = _gate_codes({"glucose_fasting": glucose})
    assert GATE_CODE not in codes


@pytest.mark.parametrize("alias_field", [
    "glucose_fasting_mg_dl",
    "fasting_glucose",
    "fasting_blood_glucose",
    "glucemia_ayuno",
])
def test_g776_fires_on_glucose_aliases(alias_field):
    """H.G776 — Gate 25 dispara con aliases canónicos de glucose_fasting."""
    codes = _gate_codes({alias_field: 280})
    assert GATE_CODE in codes


def test_g777_glucose_string_value_handled():
    """H.G777 — Glucose como string numérico también dispara."""
    codes = _gate_codes({"glucose_fasting": "300"})
    assert GATE_CODE in codes


def test_g778_glucose_boundary_exactly_250():
    """H.G778 — Glucose = 250 NO dispara (threshold strict >)."""
    codes = _gate_codes({"glucose_fasting": 250})
    assert GATE_CODE not in codes


# ──────────────────────────────────────────────────────────────────────
# §C. Trigger 2: HbA1c > 10 (H.G779-H.G783)
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("hba1c", [10.1, 11.0, 12.5, 14.0])
def test_g779_fires_on_hba1c_above_10(hba1c):
    """H.G779 — Gate 25 dispara cuando hba1c > 10%."""
    codes = _gate_codes({"hba1c": hba1c})
    assert GATE_CODE in codes


@pytest.mark.parametrize("hba1c", [5.0, 6.5, 7.5, 9.0, 10.0])
def test_g780_no_fire_on_hba1c_at_or_below_10(hba1c):
    """H.G780 — Gate 25 NO dispara cuando hba1c ≤ 10%."""
    codes = _gate_codes({"hba1c": hba1c})
    assert GATE_CODE not in codes


@pytest.mark.parametrize("alias_field", [
    "hba1c_percent",
    "hemoglobina_glucosilada",
    "a1c",
])
def test_g781_fires_on_hba1c_aliases(alias_field):
    """H.G781 — Gate 25 dispara con aliases de hba1c."""
    codes = _gate_codes({alias_field: 11.5})
    assert GATE_CODE in codes


def test_g782_hba1c_boundary_exactly_10():
    """H.G782 — HbA1c = 10.0 NO dispara (threshold strict >)."""
    codes = _gate_codes({"hba1c": 10.0})
    assert GATE_CODE not in codes


def test_g783_hba1c_string_value_handled():
    """H.G783 — HbA1c como string numérico dispara."""
    codes = _gate_codes({"hba1c": "11.2"})
    assert GATE_CODE in codes


# ──────────────────────────────────────────────────────────────────────
# §D. Trigger 3: hyperglycemia_ctcae_grade ≥ 3 (H.G784-H.G787)
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("grade", [3, 4, 5])
def test_g784_fires_on_hyperglycemia_ctcae_grade_3_plus(grade):
    """H.G784 — Gate 25 dispara cuando hyperglycemia_ctcae_grade ≥ 3."""
    codes = _gate_codes({"hyperglycemia_ctcae_grade": grade})
    assert GATE_CODE in codes


@pytest.mark.parametrize("grade", [0, 1, 2])
def test_g785_no_fire_on_grade_below_3(grade):
    """H.G785 — Gate 25 NO dispara cuando grade < 3."""
    codes = _gate_codes({"hyperglycemia_ctcae_grade": grade})
    assert GATE_CODE not in codes


def test_g786_grade_2_boundary_does_not_fire():
    """H.G786 — Grade 2 (161-250 mg/dL) NO dispara."""
    codes = _gate_codes({"hyperglycemia_ctcae_grade": 2})
    assert GATE_CODE not in codes


def test_g787_grade_3_boundary_fires():
    """H.G787 — Grade 3 (>250 sintomática) dispara."""
    codes = _gate_codes({"hyperglycemia_ctcae_grade": 3})
    assert GATE_CODE in codes


# ──────────────────────────────────────────────────────────────────────
# §E. Trigger 4: explicit flag + aliases (H.G788-H.G792)
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("flag_value", ["Sí", "Si", "YES", "yes", "1", "true"])
def test_g788_fires_on_explicit_flag(flag_value):
    """H.G788 — Gate 25 dispara con flag hyperglycemia_grade3_for_ipatasertib."""
    codes = _gate_codes({"hyperglycemia_grade3_for_ipatasertib": flag_value})
    assert GATE_CODE in codes


@pytest.mark.parametrize("alias_field", [
    "severe_hyperglycemia_for_ipatasertib",
    "hyperglycemic_crisis_active",
    "dka_history_treatment_emergent",
])
def test_g789_fires_on_flag_aliases(alias_field):
    """H.G789 — Gate 25 dispara con aliases del flag explícito."""
    codes = _gate_codes({alias_field: "Sí"})
    assert GATE_CODE in codes


@pytest.mark.parametrize("flag_value", ["No", "Desconocido", ""])
def test_g790_no_fire_on_falsy_flag(flag_value):
    """H.G790 — Flag falsy NO dispara."""
    codes = _gate_codes({"hyperglycemia_grade3_for_ipatasertib": flag_value})
    assert GATE_CODE not in codes


def test_g791_no_payload_no_fire():
    """H.G791 — Payload vacío no dispara."""
    codes = _gate_codes({})
    assert GATE_CODE not in codes


def test_g792_unrelated_field_no_fire():
    """H.G792 — Campo no relacionado no dispara gate 25."""
    codes = _gate_codes({"some_other_field": "Sí"})
    assert GATE_CODE not in codes


# ──────────────────────────────────────────────────────────────────────
# §F. Override hyperglycemia_controlled_for_ipatasertib (H.G793-H.G796)
# ──────────────────────────────────────────────────────────────────────


def test_g793_override_disables_with_glucose_high():
    """H.G793 — Override desactiva gate 25 con glucose alto."""
    codes = _gate_codes({
        "glucose_fasting": 350,
        "hyperglycemia_controlled_for_ipatasertib": "Sí",
    })
    assert GATE_CODE not in codes


def test_g794_override_disables_with_hba1c_high():
    """H.G794 — Override desactiva gate 25 con HbA1c alto."""
    codes = _gate_codes({
        "hba1c": 12.5,
        "hyperglycemia_controlled_for_ipatasertib": "Sí",
    })
    assert GATE_CODE not in codes


def test_g795_override_disables_with_explicit_flag():
    """H.G795 — Override desactiva gate 25 incluso con flag explícito."""
    codes = _gate_codes({
        "hyperglycemia_grade3_for_ipatasertib": "Sí",
        "hyperglycemia_controlled_for_ipatasertib": "Sí",
    })
    assert GATE_CODE not in codes


@pytest.mark.parametrize("override_value", ["No", "Desconocido", ""])
def test_g796_falsy_override_does_not_disable(override_value):
    """H.G796 — Override falsy NO desactiva."""
    codes = _gate_codes({
        "glucose_fasting": 280,
        "hyperglycemia_controlled_for_ipatasertib": override_value,
    })
    assert GATE_CODE in codes


# ──────────────────────────────────────────────────────────────────────
# §G. Bloqueo regimens IPATASERTIB (H.G797-H.G799)
# ──────────────────────────────────────────────────────────────────────


def test_g797_blocks_only_ipatasertib_regimens():
    """H.G797 — Gate 25 bloquea solo regimens IPATASERTIB."""
    r = apply_pivotal_contraindication_gates(
        {"glucose_fasting": 300}, treatments=[],
    )
    gate = next(g for g in r["gates_triggered"] if g["code"] == GATE_CODE)
    affected = set(gate.get("affected_regimen_codes") or [])
    assert affected == REGIMEN_CODES_IPATASERTIB


def test_g798_ipatasertib_regimen_codes_includes_combos():
    """H.G798 — REGIMEN_CODES_IPATASERTIB incluye monoterapia + combos."""
    assert "IPATASERTIB" in REGIMEN_CODES_IPATASERTIB
    assert "IPATASERTIB_ABIRATERONE" in REGIMEN_CODES_IPATASERTIB


def test_g799_keywords_ipatasertib_present():
    """H.G799 — Keywords ipatasertib disponibles."""
    from prostanet.shared.pivotal_contraindication_gates import KEYWORDS_IPATASERTIB
    assert "ipatasertib" in KEYWORDS_IPATASERTIB


# ──────────────────────────────────────────────────────────────────────
# §H. Coexistencia con Gate 5 uncontrolled_diabetes (H.G800-H.G802)
# ──────────────────────────────────────────────────────────────────────


def test_g800_gate_5_still_fires_on_uncontrolled_diabetes_flag():
    """H.G800 — Gate 5 sigue disparando con flag pre-existing."""
    codes = _gate_codes({"uncontrolled_diabetes": "Sí"})
    assert "uncontrolled_diabetes" in codes
    # Gate 25 NO dispara con solo el flag de gate 5 (sin valores numéricos)
    assert GATE_CODE not in codes


def test_g801_gates_5_and_25_both_fire_with_dm_and_acute_hyperglycemia():
    """H.G801 — Gates 5 + 25 ambos disparan con DM + hyperglycemia aguda."""
    codes = _gate_codes({
        "uncontrolled_diabetes": "Sí",
        "glucose_fasting": 320,
    })
    assert "uncontrolled_diabetes" in codes
    assert GATE_CODE in codes


def test_g802_gate_25_alone_in_treatment_emergent_zone():
    """H.G802 — Solo gate 25 (no gate 5) dispara en hyperglycemia aguda new-onset."""
    codes = _gate_codes({"glucose_fasting": 280})
    assert GATE_CODE in codes
    assert "uncontrolled_diabetes" not in codes


# ──────────────────────────────────────────────────────────────────────
# §I. DDI cross-check mapping (H.G803-H.G805)
# ──────────────────────────────────────────────────────────────────────


def test_g803_in_ddi_cross_check_mapping():
    """H.G803 — Gate 25 tiene DDI categories declaradas (cyp3a4_*)."""
    from prostanet.shared.gates_ddi_cross_check import (
        _GATE_TO_RELATED_DDI_CATEGORIES,
    )
    assert GATE_CODE in _GATE_TO_RELATED_DDI_CATEGORIES
    cats = _GATE_TO_RELATED_DDI_CATEGORIES[GATE_CODE]
    assert "cyp3a4_inhibition" in cats or "cyp3a4_induction" in cats


def test_g804_in_ddi_oncology_drugs_mapping():
    """H.G804 — Gate 25 tiene oncology_drugs (ipatasertib)."""
    from prostanet.shared.gates_ddi_cross_check import _GATE_TO_ONCOLOGY_DRUGS
    assert GATE_CODE in _GATE_TO_ONCOLOGY_DRUGS
    assert "ipatasertib" in _GATE_TO_ONCOLOGY_DRUGS[GATE_CODE]


def test_g805_in_ddi_summaries_mapping():
    """H.G805 — Gate 25 tiene UI summary."""
    from prostanet.shared.gates_ddi_cross_check import _GATE_SUMMARIES
    assert GATE_CODE in _GATE_SUMMARIES
    assert "Gate 25" in _GATE_SUMMARIES[GATE_CODE]


# ──────────────────────────────────────────────────────────────────────
# §J. Supporting FieldSpecs declarados (H.G806-H.G810)
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("field_name", [
    "glucose_fasting",
    "hba1c",
    "hyperglycemia_ctcae_grade",
    "hyperglycemia_grade3_for_ipatasertib",
    "hyperglycemia_controlled_for_ipatasertib",
])
def test_g806_field_declared(field_name):
    """H.G806 — Los 5 FieldSpecs de gate 25 están declarados."""
    from prostanet.shared.advanced_support_fields import (
        pivotal_gate_supporting_fields,
    )
    fields = pivotal_gate_supporting_fields()
    names = {f.name for f in fields}
    assert field_name in names


def test_g807_glucose_fasting_has_unit_mgdl():
    """H.G807 — glucose_fasting (number) tiene unit='mg/dL'."""
    from prostanet.shared.advanced_support_fields import (
        pivotal_gate_supporting_fields,
    )
    fields = pivotal_gate_supporting_fields()
    f = next(f for f in fields if f.name == "glucose_fasting")
    assert f.unit == "mg/dL"


def test_g808_hba1c_has_unit_percent():
    """H.G808 — hba1c (number) tiene unit='%'."""
    from prostanet.shared.advanced_support_fields import (
        pivotal_gate_supporting_fields,
    )
    fields = pivotal_gate_supporting_fields()
    f = next(f for f in fields if f.name == "hba1c")
    assert f.unit == "%"


def test_g809_hyperglycemia_ctcae_grade_has_unit_grado():
    """H.G809 — hyperglycemia_ctcae_grade tiene unit='grado'."""
    from prostanet.shared.advanced_support_fields import (
        pivotal_gate_supporting_fields,
    )
    fields = pivotal_gate_supporting_fields()
    f = next(f for f in fields if f.name == "hyperglycemia_ctcae_grade")
    assert f.unit == "grado"


def test_g810_evidence_tags_includes_ipatential150():
    """H.G810 — FieldSpecs cita evidence_tag IPATential150."""
    from prostanet.shared.advanced_support_fields import (
        pivotal_gate_supporting_fields,
    )
    fields = pivotal_gate_supporting_fields()
    glucose_field = next(f for f in fields if f.name == "glucose_fasting")
    assert "ipatential150" in glucose_field.evidence_tags


# ──────────────────────────────────────────────────────────────────────
# §K. Active gate codes count (H.G811-H.G813)
# ──────────────────────────────────────────────────────────────────────


def test_g811_active_gate_codes_includes_gate_25():
    """H.G811 — get_active_gate_codes() incluye gate 25."""
    from prostanet.shared.algorithm_version import get_active_gate_codes
    codes = get_active_gate_codes()
    assert GATE_CODE in codes


def test_g812_total_active_gates_at_least_25():
    """H.G812 — Total active gates ≥25 (era 24 al cierre #39, +1 en #41)."""
    from prostanet.shared.algorithm_version import get_active_gate_codes
    codes = get_active_gate_codes()
    assert len(codes) >= 25


def test_g813_yaml_loaded_count_at_least_25():
    """H.G813 — yaml_loaded_gates_count ≥ 25."""
    from prostanet.shared.algorithm_version import get_algorithm_version
    ver = get_algorithm_version()
    assert ver["yaml_loaded_gates_count"] >= 25


# ──────────────────────────────────────────────────────────────────────
# §L. Healthy payload + edge cases (H.G814-H.G816)
# ──────────────────────────────────────────────────────────────────────


def test_g814_healthy_payload_does_not_fire():
    """H.G814 — Payload sano no dispara gate 25."""
    codes = _gate_codes({
        "glucose_fasting": 95,
        "hba1c": 5.4,
        "hyperglycemia_ctcae_grade": 0,
    })
    assert GATE_CODE not in codes


def test_g815_borderline_pre_diabetes_does_not_fire():
    """H.G815 — Pre-diabetes (HbA1c 6.0-6.4) no dispara (gate 25 es G3 severo)."""
    codes = _gate_codes({"hba1c": 6.2})
    assert GATE_CODE not in codes


def test_g816_grade_4_dka_zone_fires():
    """H.G816 — Glucosa >500 (grade 4 DKA risk) dispara."""
    codes = _gate_codes({"glucose_fasting": 550})
    assert GATE_CODE in codes


# ──────────────────────────────────────────────────────────────────────
# §M. E2E + integration (H.G817-H.G820)
# ──────────────────────────────────────────────────────────────────────


def test_g817_e2e_acute_hyperglycemic_crisis_patient():
    """H.G817 — E2E: paciente con crisis hyperglycemic G4 dispara con razón."""
    payload = {
        "glucose_fasting": 480,
        "hba1c": 11.8,
        "hyperglycemia_ctcae_grade": 4,
    }
    r = apply_pivotal_contraindication_gates(payload, treatments=[])
    codes = [g["code"] for g in r["gates_triggered"]]
    assert GATE_CODE in codes
    # not_recommended_messages incluye warning de ipatasertib
    not_rec_msgs = r.get("not_recommended_messages") or []
    assert any("ipatasertib" in m.lower() for m in not_rec_msgs)


def test_g818_e2e_optimized_patient_can_re_initiate():
    """H.G818 — E2E: paciente optimizado puede re-iniciar (override)."""
    payload = {
        "glucose_fasting": 160,
        "hba1c": 7.2,
        "hyperglycemia_controlled_for_ipatasertib": "Sí",
    }
    codes = _gate_codes(payload)
    assert GATE_CODE not in codes


def test_g819_evidence_tag_in_message():
    """H.G819 — Message del gate cita IPATential150."""
    r = apply_pivotal_contraindication_gates(
        {"glucose_fasting": 280}, treatments=[],
    )
    gate = next(g for g in r["gates_triggered"] if g["code"] == GATE_CODE)
    assert "IPATential150" in gate.get("message", "")


def test_g820_trial_refs_includes_ipatential150():
    """H.G820 — trial_refs del gate incluye IPATential150."""
    r = apply_pivotal_contraindication_gates(
        {"hyperglycemia_grade3_for_ipatasertib": "Sí"}, treatments=[],
    )
    gate = next(g for g in r["gates_triggered"] if g["code"] == GATE_CODE)
    refs = gate.get("trial_refs") or []
    assert any("IPATential150" in r for r in refs)
