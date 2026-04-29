"""tests/test_pivotal_gates_taxane_neuropathy_longitudinal.py — FAUBOT 2026-04-25 (XXVII).

Auditoría #39 — Gate 24: docetaxel × neuropatía longitudinal con timing post 4+ ciclos.

Diferencia con Gate 2 (severe_neuropathy_grade3):
  - Gate 2: G≥3 instant block (cualquier momento, sin condición timing)
  - Gate 24: G≥2 longitudinal post-4-ciclos (más permisivo en grado, pero
    requiere exposición acumulativa documentada)

Hipótesis verificadas: H.G451-H.G475 (25 hipótesis sobre triggers all_of
+ override + alias cycles + coexistencia con gate 2 + DDI cross-check +
supporting fields).

Convenciones (CLAUDE.md §8):
  - Tests parametrizados por trigger value + override + alias
  - Cada gate cita evidence_tag específico + trial_refs
  - Backward-compat con gates 1-23 anteriores
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest

from prostanet.shared.pivotal_contraindication_gates import (
    apply_pivotal_contraindication_gates,
    REGIMEN_CODES_TAXANE,
)
from prostanet.shared.pivotal_gates_yaml_loader import (
    get_loaded_yaml_codes,
    validate_all_yaml_gates,
)


GATE_CODE = "docetaxel_neuropathy_longitudinal_grade2_post_4_cycles"


def _gate_codes(payload: dict) -> list[str]:
    """Return list of triggered gate codes for a given payload."""
    r = apply_pivotal_contraindication_gates(payload, treatments=[])
    return [g["code"] for g in r["gates_triggered"]]


# ──────────────────────────────────────────────────────────────────────
# H.G451 — Gate 24 cargado en YAML catalog sin errores
# ──────────────────────────────────────────────────────────────────────


def test_gate_24_loaded_in_yaml_catalog():
    """H.G451 — Gate 24 está presente en YAML catalog."""
    codes = get_loaded_yaml_codes()
    assert GATE_CODE in codes


def test_gate_24_no_validation_errors():
    """H.G452 — Gate 24 YAML pasa validación sin errores."""
    errors = validate_all_yaml_gates()
    assert GATE_CODE not in errors or not errors[GATE_CODE]


def test_yaml_catalog_at_least_24_files():
    """H.G453 — YAML catalog ahora tiene ≥24 archivos (era 23 al cierre #38)."""
    codes = get_loaded_yaml_codes()
    assert len(codes) >= 24


# ──────────────────────────────────────────────────────────────────────
# H.G454 — Camino 1: explicit flag dispara independientemente de cycles
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("flag_value", ["Sí", "Si", "YES", "yes", "1", "true"])
def test_gate_24_fires_on_cumulative_neuropathy_documented_flag(flag_value):
    """H.G454 — Gate 24 dispara con flag cumulative_neuropathy_documented."""
    codes = _gate_codes({"cumulative_neuropathy_documented": flag_value})
    assert GATE_CODE in codes


@pytest.mark.parametrize("alias_field", [
    "cumulative_taxane_neuropathy",
    "taxane_neuropathy_grade2_post_treatment",
])
def test_gate_24_fires_on_flag_aliases(alias_field):
    """H.G455 — Gate 24 dispara con aliases del flag."""
    codes = _gate_codes({alias_field: "Sí"})
    assert GATE_CODE in codes


# ──────────────────────────────────────────────────────────────────────
# H.G456 — Camino 2: all_of (G≥2 AND cycles≥4)
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("grade,cycles", [
    (2, 4),
    (2, 5),
    (2, 6),
    (3, 4),
    (4, 8),
])
def test_gate_24_fires_when_grade_and_cycles_both_meet_threshold(grade, cycles):
    """H.G456 — Gate 24 dispara cuando AMBOS grado≥2 AND ciclos≥4."""
    codes = _gate_codes({
        "peripheral_neuropathy_grade": grade,
        "docetaxel_cycles_received": cycles,
    })
    assert GATE_CODE in codes


@pytest.mark.parametrize("grade,cycles", [
    (1, 4),  # grade 1 < threshold → no fire
    (1, 6),  # grade 1 < threshold → no fire
    (0, 4),  # grade 0 < threshold → no fire
])
def test_gate_24_does_not_fire_when_grade_below_2(grade, cycles):
    """H.G457 — Gate 24 NO dispara cuando grade < 2 (incluso con cycles altos)."""
    codes = _gate_codes({
        "peripheral_neuropathy_grade": grade,
        "docetaxel_cycles_received": cycles,
    })
    assert GATE_CODE not in codes


@pytest.mark.parametrize("grade,cycles", [
    (2, 0),  # cycles 0 < threshold → no fire
    (2, 1),  # cycles 1 < threshold → no fire
    (2, 2),  # cycles 2 < threshold → no fire
    (2, 3),  # cycles 3 < threshold → no fire
    (3, 3),  # cycles 3 < threshold → no fire (gate 2 sí dispara)
])
def test_gate_24_does_not_fire_when_cycles_below_4(grade, cycles):
    """H.G458 — Gate 24 NO dispara cuando cycles < 4."""
    codes = _gate_codes({
        "peripheral_neuropathy_grade": grade,
        "docetaxel_cycles_received": cycles,
    })
    assert GATE_CODE not in codes


def test_gate_24_does_not_fire_with_only_grade():
    """H.G459 — Gate 24 NO dispara con solo grade (sin cycles)."""
    codes = _gate_codes({"peripheral_neuropathy_grade": 2})
    assert GATE_CODE not in codes


def test_gate_24_does_not_fire_with_only_cycles():
    """H.G460 — Gate 24 NO dispara con solo cycles (sin grade)."""
    codes = _gate_codes({"docetaxel_cycles_received": 6})
    assert GATE_CODE not in codes


# ──────────────────────────────────────────────────────────────────────
# H.G461 — Aliases para docetaxel_cycles_received
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("alias_field", [
    "taxane_cycles_received",
    "docetaxel_cycle_count",
    "docetaxel_total_cycles",
])
def test_gate_24_fires_with_cycles_aliases(alias_field):
    """H.G461 — Gate 24 dispara cuando cycles vienen via alias."""
    codes = _gate_codes({
        "peripheral_neuropathy_grade": 2,
        alias_field: 4,
    })
    assert GATE_CODE in codes


# ──────────────────────────────────────────────────────────────────────
# H.G462 — Override neuropathy_recovered_post_docetaxel
# ──────────────────────────────────────────────────────────────────────


def test_gate_24_override_disables_with_grade_and_cycles():
    """H.G462 — Override desactiva gate 24 incluso con grade+cycles altos."""
    codes = _gate_codes({
        "peripheral_neuropathy_grade": 3,
        "docetaxel_cycles_received": 8,
        "neuropathy_recovered_post_docetaxel": "Sí",
    })
    assert GATE_CODE not in codes


def test_gate_24_override_disables_with_explicit_flag():
    """H.G463 — Override desactiva gate 24 incluso con flag explícito."""
    codes = _gate_codes({
        "cumulative_neuropathy_documented": "Sí",
        "neuropathy_recovered_post_docetaxel": "Sí",
    })
    assert GATE_CODE not in codes


@pytest.mark.parametrize("override_value", ["No", "Desconocido", ""])
def test_gate_24_does_not_disable_with_falsy_override(override_value):
    """H.G464 — Override falsy (No/Desconocido/vacío) NO desactiva gate 24."""
    codes = _gate_codes({
        "peripheral_neuropathy_grade": 2,
        "docetaxel_cycles_received": 5,
        "neuropathy_recovered_post_docetaxel": override_value,
    })
    assert GATE_CODE in codes


# ──────────────────────────────────────────────────────────────────────
# H.G465 — Coexistencia con Gate 2 (severe_neuropathy_grade3)
# ──────────────────────────────────────────────────────────────────────


def test_gate_2_still_fires_on_grade_3_alone():
    """H.G465 — Gate 2 sigue disparando con G≥3 instant (sin condición timing)."""
    codes = _gate_codes({"peripheral_neuropathy_grade": 3})
    assert "severe_neuropathy_grade3" in codes
    # gate 24 NO dispara sin cycles documented
    assert GATE_CODE not in codes


def test_gates_2_and_24_both_fire_when_grade_3_and_cycles_4():
    """H.G466 — Gates 2 + 24 ambos disparan con G≥3 AND cycles≥4."""
    codes = _gate_codes({
        "peripheral_neuropathy_grade": 3,
        "docetaxel_cycles_received": 6,
    })
    assert "severe_neuropathy_grade3" in codes
    assert GATE_CODE in codes


def test_gate_24_fires_alone_in_grade_2_post_4_cycles_zone():
    """H.G467 — Solo gate 24 (no gate 2) dispara en zona G2 post-4-cycles."""
    codes = _gate_codes({
        "peripheral_neuropathy_grade": 2,
        "docetaxel_cycles_received": 5,
    })
    assert GATE_CODE in codes
    assert "severe_neuropathy_grade3" not in codes


# ──────────────────────────────────────────────────────────────────────
# H.G468 — Bloqueo regimens taxane (docetaxel + cabazitaxel)
# ──────────────────────────────────────────────────────────────────────


def test_gate_24_blocks_taxane_regimens():
    """H.G468 — Gate 24 bloquea TODOS los taxanos (docetaxel + cabazitaxel)."""
    r = apply_pivotal_contraindication_gates(
        {"cumulative_neuropathy_documented": "Sí"},
        treatments=[],
    )
    gate = next(g for g in r["gates_triggered"] if g["code"] == GATE_CODE)
    affected = set(gate.get("affected_regimen_codes") or [])
    assert affected == REGIMEN_CODES_TAXANE


# ──────────────────────────────────────────────────────────────────────
# H.G469 — Healthy payload no dispara gate 24
# ──────────────────────────────────────────────────────────────────────


def test_healthy_payload_does_not_fire_gate_24():
    """H.G469 — Healthy payload (G0 + cycles 0) no dispara gate 24."""
    codes = _gate_codes({
        "peripheral_neuropathy_grade": 0,
        "docetaxel_cycles_received": 0,
    })
    assert GATE_CODE not in codes


def test_empty_payload_does_not_fire_gate_24():
    """H.G470 — Payload vacío no dispara gate 24."""
    codes = _gate_codes({})
    assert GATE_CODE not in codes


# ──────────────────────────────────────────────────────────────────────
# H.G471 — DDI cross-check mapping
# ──────────────────────────────────────────────────────────────────────


def test_gate_24_in_ddi_cross_check_mapping():
    """H.G471 — Gate 24 tiene DDI categories declaradas (cyp3a4_*)."""
    from prostanet.shared.gates_ddi_cross_check import (
        _GATE_TO_RELATED_DDI_CATEGORIES,
    )
    assert GATE_CODE in _GATE_TO_RELATED_DDI_CATEGORIES
    cats = _GATE_TO_RELATED_DDI_CATEGORIES[GATE_CODE]
    assert "cyp3a4_inhibition" in cats or "cyp3a4_induction" in cats


def test_gate_24_in_ddi_oncology_drugs_mapping():
    """H.G472 — Gate 24 tiene oncology drugs declaradas (docetaxel/cabazitaxel)."""
    from prostanet.shared.gates_ddi_cross_check import _GATE_TO_ONCOLOGY_DRUGS
    assert GATE_CODE in _GATE_TO_ONCOLOGY_DRUGS
    drugs = _GATE_TO_ONCOLOGY_DRUGS[GATE_CODE]
    assert "docetaxel" in drugs or "cabazitaxel" in drugs


def test_gate_24_in_ddi_summaries_mapping():
    """H.G473 — Gate 24 tiene UI summary declarado (Gate 24 marker)."""
    from prostanet.shared.gates_ddi_cross_check import _GATE_SUMMARIES
    assert GATE_CODE in _GATE_SUMMARIES
    assert "Gate 24" in _GATE_SUMMARIES[GATE_CODE]


# ──────────────────────────────────────────────────────────────────────
# H.G474 — Supporting FieldSpecs declared
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("field_name", [
    "docetaxel_cycles_received",
    "cumulative_neuropathy_documented",
    "neuropathy_recovered_post_docetaxel",
])
def test_gate_24_supporting_fields_declared(field_name):
    """H.G474 — Los 3 supporting FieldSpecs de gate 24 están declarados."""
    from prostanet.shared.advanced_support_fields import (
        pivotal_gate_supporting_fields,
    )
    fields = pivotal_gate_supporting_fields()
    names = {f.name for f in fields}
    assert field_name in names


def test_docetaxel_cycles_received_has_unit():
    """H.G475 — `docetaxel_cycles_received` (number) tiene unit declarado."""
    from prostanet.shared.advanced_support_fields import (
        pivotal_gate_supporting_fields,
    )
    fields = pivotal_gate_supporting_fields()
    cycles_field = next(
        f for f in fields if f.name == "docetaxel_cycles_received"
    )
    assert cycles_field.unit  # truthy


# ──────────────────────────────────────────────────────────────────────
# H.G476 — Active gate codes count includes gate 24
# ──────────────────────────────────────────────────────────────────────


def test_active_gate_codes_includes_gate_24():
    """H.G476 — get_active_gate_codes() incluye gate 24."""
    from prostanet.shared.algorithm_version import get_active_gate_codes
    codes = get_active_gate_codes()
    assert GATE_CODE in codes


def test_total_active_gates_at_least_24():
    """H.G477 — Total active gates ≥24 (era 23 al cierre #38, +1 en #39)."""
    from prostanet.shared.algorithm_version import get_active_gate_codes
    codes = get_active_gate_codes()
    assert len(codes) >= 24


# ──────────────────────────────────────────────────────────────────────
# H.G478 — E2E: paciente con docetaxel histórico + neuropatía actual
# ──────────────────────────────────────────────────────────────────────


def test_e2e_post_docetaxel_neuropathy_patient():
    """H.G478 — Paciente E2E: 6 ciclos docetaxel previos + G2 actual."""
    payload = {
        "peripheral_neuropathy_grade": 2,
        "docetaxel_cycles_received": 6,
    }
    r = apply_pivotal_contraindication_gates(payload, treatments=[])
    codes = [g["code"] for g in r["gates_triggered"]]
    assert GATE_CODE in codes
    # gate 2 NO dispara porque grade=2 (no >=3)
    assert "severe_neuropathy_grade3" not in codes
    # not_recommended_messages incluye warning del gate 24
    not_rec_msgs = r.get("not_recommended_messages") or []
    assert any("docetaxel" in m.lower() or "cabazitaxel" in m.lower() for m in not_rec_msgs)


def test_e2e_recovered_patient_can_re_rechallenge():
    """H.G479 — E2E: paciente recuperado tras dose-hold puede re-rechallenge."""
    payload = {
        "peripheral_neuropathy_grade": 2,
        "docetaxel_cycles_received": 6,
        "neuropathy_recovered_post_docetaxel": "Sí",
    }
    r = apply_pivotal_contraindication_gates(payload, treatments=[])
    codes = [g["code"] for g in r["gates_triggered"]]
    assert GATE_CODE not in codes
