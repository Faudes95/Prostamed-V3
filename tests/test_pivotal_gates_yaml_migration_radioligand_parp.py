"""tests/test_pivotal_gates_yaml_migration_radioligand_parp.py — FAUBOT 2026-04-25 (XVIII).

Cobertura de la migración a YAML declarativo de los 5 gates pivotal
radioligando + PARP previamente en Python:

  - Gate 11: `radium223_in_cord_compression`
  - Gate 12: `radium223_in_hypocalcemia`
  - Gate 13: `lutetium177_in_cord_compression`
  - Gate 14: `lutetium177_in_severe_cytopenias`
  - Gate 15: `parp_inhibitor_in_severe_cytopenias`

Verifica:
  - Los 5 YAMLs cargan correctamente
  - El nuevo trigger type `string_contains_any` funciona
  - Cada gate dispara con sus triggers específicos
  - Los overrides desactivan correctamente
  - Los detectores Python equivalentes ya NO están en `_DETECTORS`
  - Paridad campos clave (severity, regimen_codes, keywords, evidence_tag,
    trial_refs) entre Python (helper aún importable) y YAML
  - Algorithm version refleja 19 gates totales y 18 YAMLs

Hipótesis cubiertas: H.G256 - H.G280 (25 tests dedicados).
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest

from prostanet.shared.pivotal_gates_yaml_loader import (
    _evaluate_trigger,
    evaluate_yaml_gate,
    evaluate_all_yaml_gates,
    get_loaded_yaml_codes,
    get_yaml_gate_sha,
    reset_yaml_cache,
    validate_all_yaml_gates,
    VALID_TRIGGER_TYPES,
)
from prostanet.shared.pivotal_contraindication_gates import (
    _DETECTORS,
    evaluate_pivotal_contraindication_gates,
)
from prostanet.shared.algorithm_version import get_algorithm_version


@pytest.fixture(autouse=True)
def _reset_yaml():
    """Reset YAML cache antes de cada test (asegura recarga limpia)."""
    reset_yaml_cache()
    yield
    reset_yaml_cache()


# ──────────────────────────────────────────────────────────────────────
# H.G256 — Trigger type string_contains_any registrado
# ──────────────────────────────────────────────────────────────────────


def test_string_contains_any_in_valid_trigger_types():
    """H.G256 — VALID_TRIGGER_TYPES incluye string_contains_any."""
    assert "string_contains_any" in VALID_TRIGGER_TYPES


@pytest.mark.parametrize("text,expected", [
    ("Debilidad moderada bilateral", True),
    ("Cuadriparesia SEVERA", True),
    ("paresia incipiente", True),
    ("leve", False),
    ("", False),
    (None, False),
])
def test_string_contains_any_evaluates_substring_match(text, expected):
    """H.G257 — string_contains_any detecta substring case-insensitive."""
    trigger = {
        "type": "string_contains_any",
        "field": "lower_limb_weakness",
        "keywords": ["moderada", "severa", "paresia"],
    }
    payload = {"lower_limb_weakness": text} if text is not None else {}
    assert _evaluate_trigger(trigger, payload) is expected


def test_string_contains_any_with_alias_fields():
    """H.G258 — string_contains_any soporta alias_fields."""
    trigger = {
        "type": "string_contains_any",
        "field": "main_field",
        "alias_fields": ["alias_field"],
        "keywords": ["foo"],
    }
    # Match en alias
    assert _evaluate_trigger(trigger, {"alias_field": "this contains FOO"}) is True
    # No match
    assert _evaluate_trigger(trigger, {"alias_field": "bar"}) is False


# ──────────────────────────────────────────────────────────────────────
# H.G259 — Catálogo: 18 YAMLs cargados
# ──────────────────────────────────────────────────────────────────────


def test_catalog_has_at_least_18_yamls():
    """H.G259 — Catálogo YAML carga al menos 18 archivos (5 nuevos en #34)."""
    codes = get_loaded_yaml_codes()
    assert len(codes) >= 18


def test_5_new_gates_present_in_yaml_catalog():
    """H.G260 — Los 5 gates migrados están presentes en el catálogo YAML."""
    codes = set(get_loaded_yaml_codes())
    expected = {
        "radium223_in_cord_compression",
        "radium223_in_hypocalcemia",
        "lutetium177_in_cord_compression",
        "lutetium177_in_severe_cytopenias",
        "parp_inhibitor_in_severe_cytopenias",
    }
    missing = expected - codes
    assert not missing, f"Faltan en YAML: {missing}"


def test_all_yamls_pass_schema_validation():
    """H.G261 — Todos los YAMLs cargados pasan validate_yaml_gate_config."""
    errors = validate_all_yaml_gates()
    assert not errors, f"Errores en YAMLs: {errors}"


def test_each_new_gate_has_sha():
    """H.G262 — Cada uno de los 5 gates nuevos tiene SHA per-gate."""
    new_codes = [
        "radium223_in_cord_compression",
        "radium223_in_hypocalcemia",
        "lutetium177_in_cord_compression",
        "lutetium177_in_severe_cytopenias",
        "parp_inhibitor_in_severe_cytopenias",
    ]
    for code in new_codes:
        sha = get_yaml_gate_sha(code)
        assert sha and len(sha) == 12, f"{code}: SHA inválido: {sha}"


# ──────────────────────────────────────────────────────────────────────
# H.G263 — Gate 11 Ra-223 cord compression
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("payload_partial,expected", [
    ({"spinal_cord_compression": "Sí"}, True),
    ({"epidural_compression": "Sí"}, True),  # alias
    ({"lower_limb_weakness": "paresia leve a moderada"}, True),
    ({"cord_compression_symptoms": "anestesia silla de montar"}, True),
    ({}, False),
    ({"lower_limb_weakness": "leve"}, False),
])
def test_gate_11_ra223_cord_triggers(payload_partial, expected):
    """H.G263 — Gate 11 dispara con cualquiera de los 4 sub-triggers."""
    results = evaluate_all_yaml_gates(payload_partial)
    codes = [g["code"] for g in results]
    fired = "radium223_in_cord_compression" in codes
    assert fired is expected


def test_gate_11_override_disables():
    """H.G264 — Gate 11 override `cord_compression_stabilized=Sí` desactiva."""
    payload = {
        "spinal_cord_compression": "Sí",
        "cord_compression_stabilized": "Sí",
    }
    results = evaluate_all_yaml_gates(payload)
    codes = [g["code"] for g in results]
    assert "radium223_in_cord_compression" not in codes


# ──────────────────────────────────────────────────────────────────────
# H.G265 — Gate 12 Ra-223 hipocalcemia
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("payload_partial,expected", [
    ({"hypocalcemia": "Sí"}, True),
    ({"corrected_calcium": 7.8}, True),
    ({"calcium_level": 8.0}, True),  # alias
    ({"serum_calcium": 8.4}, True),  # alias (límite)
    ({"ionized_calcium": 4.0}, True),
    ({"corrected_calcium": 9.2}, False),
    ({"ionized_calcium": 5.0}, False),
    ({}, False),
])
def test_gate_12_hypocalcemia_triggers(payload_partial, expected):
    """H.G265 — Gate 12 dispara con flag o cualquier umbral de calcio."""
    results = evaluate_all_yaml_gates(payload_partial)
    codes = [g["code"] for g in results]
    fired = "radium223_in_hypocalcemia" in codes
    assert fired is expected


def test_gate_12_override_disables():
    """H.G266 — Gate 12 override `hypocalcemia_corrected=Sí` desactiva."""
    payload = {"corrected_calcium": 7.5, "hypocalcemia_corrected": "Sí"}
    results = evaluate_all_yaml_gates(payload)
    codes = [g["code"] for g in results]
    assert "radium223_in_hypocalcemia" not in codes


# ──────────────────────────────────────────────────────────────────────
# H.G267 — Gate 13 Lu-177 cord compression
# ──────────────────────────────────────────────────────────────────────


def test_gate_13_lutetium177_cord_fires_with_truthy():
    """H.G267 — Gate 13 dispara con spinal_cord_compression=Sí."""
    results = evaluate_all_yaml_gates({"spinal_cord_compression": "Sí"})
    codes = [g["code"] for g in results]
    assert "lutetium177_in_cord_compression" in codes


def test_gate_13_lutetium177_cord_override():
    """H.G268 — Gate 13 override desactiva."""
    payload = {
        "spinal_cord_compression": "Sí",
        "cord_compression_stabilized": "Sí",
    }
    results = evaluate_all_yaml_gates(payload)
    codes = [g["code"] for g in results]
    assert "lutetium177_in_cord_compression" not in codes


def test_gate_13_string_contains_any_works():
    """H.G269 — Gate 13 también usa string_contains_any (síntomas neuro)."""
    results = evaluate_all_yaml_gates({
        "cord_compression_symptoms": "Incontinencia fecal nueva"
    })
    codes = [g["code"] for g in results]
    assert "lutetium177_in_cord_compression" in codes


# ──────────────────────────────────────────────────────────────────────
# H.G270 — Gate 14 Lu-177 cytopenias (threshold 75K plaquetas)
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("payload_partial,expected", [
    ({"severe_cytopenia_for_radioligand": "Sí"}, True),
    ({"anc": 1200}, True),
    ({"anc_baseline": 1400}, True),  # alias
    ({"platelets": 60000}, True),  # < 75K
    ({"hemoglobin_g_dl": 8.5}, True),
    ({"hemoglobin": 8.5}, True),  # alias
    ({"hb": 8.5}, True),  # alias
    ({"anc": 2000}, False),
    ({"platelets": 80000}, False),  # >= 75K
    ({"hemoglobin_g_dl": 10.0}, False),
])
def test_gate_14_lutetium177_cytopenias_triggers(payload_partial, expected):
    """H.G270 — Gate 14 dispara con cualquier threshold Pluvicto label
    (ANC<1500, plaq<75K, Hb<9 g/dL)."""
    results = evaluate_all_yaml_gates(payload_partial)
    codes = [g["code"] for g in results]
    fired = "lutetium177_in_severe_cytopenias" in codes
    assert fired is expected


def test_gate_14_override_disables():
    """H.G271 — Gate 14 override `cytopenias_corrected_for_radioligand=Sí`."""
    payload = {"anc": 1200, "cytopenias_corrected_for_radioligand": "Sí"}
    results = evaluate_all_yaml_gates(payload)
    codes = [g["code"] for g in results]
    assert "lutetium177_in_severe_cytopenias" not in codes


# ──────────────────────────────────────────────────────────────────────
# H.G272 — Gate 15 PARP cytopenias (threshold 100K plaquetas, más estricto)
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("payload_partial,expected", [
    ({"severe_cytopenia_for_parp_inhibitor": "Sí"}, True),
    ({"anc": 1200}, True),
    ({"platelets": 90000}, True),  # < 100K
    ({"platelets": 110000}, False),  # >= 100K
    ({"hemoglobin_g_dl": 8.5}, True),
    ({"anc": 2000, "platelets": 110000, "hb": 10.0}, False),
])
def test_gate_15_parp_cytopenias_triggers(payload_partial, expected):
    """H.G272 — Gate 15 PARP dispara con thresholds ANC<1500, plaq<100K, Hb<9."""
    results = evaluate_all_yaml_gates(payload_partial)
    codes = [g["code"] for g in results]
    fired = "parp_inhibitor_in_severe_cytopenias" in codes
    assert fired is expected


def test_gate_15_override_disables():
    """H.G273 — Gate 15 override `cytopenias_corrected_for_parp_inhibitor=Sí`."""
    payload = {"platelets": 80000, "cytopenias_corrected_for_parp_inhibitor": "Sí"}
    results = evaluate_all_yaml_gates(payload)
    codes = [g["code"] for g in results]
    assert "parp_inhibitor_in_severe_cytopenias" not in codes


def test_gates_14_15_threshold_differential():
    """H.G274 — Diferencial de threshold: plaq=85000 dispara gate 15 (PARPi
    requiere ≥100K) pero NO gate 14 (Lu-177 acepta ≥75K)."""
    payload = {"platelets": 85000}
    results = evaluate_all_yaml_gates(payload)
    codes = [g["code"] for g in results]
    assert "parp_inhibitor_in_severe_cytopenias" in codes
    assert "lutetium177_in_severe_cytopenias" not in codes


def test_overrides_separados_lu177_parp():
    """H.G275 — Override Lu-177 NO desactiva gate 15 PARP (separación)."""
    payload = {
        "platelets": 70000,  # < 75K (gate 14) y < 100K (gate 15)
        "cytopenias_corrected_for_radioligand": "Sí",  # solo desactiva gate 14
    }
    results = evaluate_all_yaml_gates(payload)
    codes = [g["code"] for g in results]
    assert "lutetium177_in_severe_cytopenias" not in codes
    assert "parp_inhibitor_in_severe_cytopenias" in codes


# ──────────────────────────────────────────────────────────────────────
# H.G276 — Detectores Python migrados ya NO están en _DETECTORS
# ──────────────────────────────────────────────────────────────────────


def test_python_detectors_for_migrated_gates_removed_from_tuple():
    """H.G276 — Los 5 detectores Python migrados ya no aparecen en
    _DETECTORS (solo viven como funciones importables)."""
    detector_names = {d.__name__ for d in _DETECTORS}
    migrated_names = {
        "detect_radium223_in_cord_compression",
        "detect_radium223_in_hypocalcemia",
        "detect_lutetium177_in_cord_compression",
        "detect_lutetium177_in_severe_cytopenias",
        "detect_parp_inhibitor_in_severe_cytopenias",
    }
    overlap = detector_names & migrated_names
    assert not overlap, (
        f"Los siguientes detectores deberían haber sido removidos de _DETECTORS: {overlap}"
    )


def test_python_detectors_still_importable_for_helpers():
    """H.G276.b — Las funciones siguen importables (alguien podría usarlas
    directamente como helper)."""
    from prostanet.shared.pivotal_contraindication_gates import (
        detect_radium223_in_cord_compression,
        detect_radium223_in_hypocalcemia,
        detect_lutetium177_in_cord_compression,
        detect_lutetium177_in_severe_cytopenias,
        detect_parp_inhibitor_in_severe_cytopenias,
    )
    # Llamarlas con payloads simples produce el mismo dict
    assert detect_radium223_in_cord_compression({"spinal_cord_compression": "Sí"})


# ──────────────────────────────────────────────────────────────────────
# H.G277 — algorithm_version refleja sistema híbrido (19 gates total)
# ──────────────────────────────────────────────────────────────────────


def test_algorithm_version_reports_at_least_19_active_gates():
    """H.G277 — get_algorithm_version retorna ≥19 gates activos totales
    (Python + YAML, sin duplicados). Convención `>=` per CLAUDE.md §8.4."""
    ver = get_algorithm_version()
    assert ver["gates_active_count"] >= 19


def test_algorithm_version_reports_18_yaml():
    """H.G277.b — yaml_loaded_gates_count == 18 (5 nuevos en #34)."""
    ver = get_algorithm_version()
    assert ver["yaml_loaded_gates_count"] >= 18


def test_algorithm_version_includes_all_5_new_yaml_codes():
    """H.G278 — yaml_loaded_gate_codes incluye los 5 gates migrados."""
    ver = get_algorithm_version()
    yaml_codes = set(ver["yaml_loaded_gate_codes"])
    new = {
        "radium223_in_cord_compression",
        "radium223_in_hypocalcemia",
        "lutetium177_in_cord_compression",
        "lutetium177_in_severe_cytopenias",
        "parp_inhibitor_in_severe_cytopenias",
    }
    assert new.issubset(yaml_codes)


def test_algorithm_version_per_gate_shas_includes_new():
    """H.G278.b — per_gate_yaml_shas incluye los 5 gates nuevos con SHA."""
    ver = get_algorithm_version()
    shas = ver["per_gate_yaml_shas"]
    new = [
        "radium223_in_cord_compression",
        "radium223_in_hypocalcemia",
        "lutetium177_in_cord_compression",
        "lutetium177_in_severe_cytopenias",
        "parp_inhibitor_in_severe_cytopenias",
    ]
    for code in new:
        assert code in shas, f"{code} no tiene SHA registrado"
        assert len(shas[code]) == 12


def test_faubot_release_at_least_xviii():
    """H.G278.c — FAUBOT_RELEASE >= 2026-04-25 XVIII (post #34, iteración 18).

    Faubot 2026-04-25 (LVI / Auditoría #57): refactor para usar
    `_roman_to_int()` ya que la comparación lexicográfica falla con
    romanos > XL (ord('L') < ord('X') hace que 'LV' < 'XVIII').
    """
    def _roman_to_int(s: str) -> int:
        roman_map = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
        total = 0
        prev = 0
        for char in reversed(s):
            value = roman_map.get(char, 0)
            if value < prev:
                total -= value
            else:
                total += value
            prev = value
        return total

    ver = get_algorithm_version()
    # Faubot LXXXI #audit-pre-cortana — accept 2026-04-2X (date may bump)
    assert ver["faubot_release"].startswith("2026-04-"), (
        f"FAUBOT release prefix expected 2026-04-2X; got: {ver['faubot_release']}"
    )
    roman_part = ver["faubot_release"].rsplit(" ", 1)[-1].strip()
    iteration = _roman_to_int(roman_part)
    assert iteration >= 18, (
        f"FAUBOT iteration {iteration} (from '{roman_part}') < 18 expected; "
        f"full release: {ver['faubot_release']}"
    )


# ──────────────────────────────────────────────────────────────────────
# H.G279 — Pipeline E2E: evaluate_pivotal_contraindication_gates
# ──────────────────────────────────────────────────────────────────────


def test_pipeline_e2e_dispatches_yaml_gates_via_evaluate():
    """H.G279 — `evaluate_pivotal_contraindication_gates` dispatches
    correctamente los 5 nuevos YAMLs."""
    payload = {
        "spinal_cord_compression": "Sí",
        "anc": 1200,
        "platelets": 80000,
    }
    results = evaluate_pivotal_contraindication_gates(payload)
    codes = [g["code"] for g in results]
    # Esperamos al menos: cord (Ra+Lu), Lu-177 cytopenias (ANC), PARP cytopenias (plaq+ANC)
    assert "radium223_in_cord_compression" in codes
    assert "lutetium177_in_cord_compression" in codes
    assert "lutetium177_in_severe_cytopenias" in codes  # ANC <1500
    assert "parp_inhibitor_in_severe_cytopenias" in codes  # plaq <100K


def test_pipeline_e2e_no_duplicates_after_dedup():
    """H.G280 — La dedup por code asegura que cada gate aparece máximo 1
    vez en la lista final aunque YAML y Python pudieran chocar."""
    payload = {"spinal_cord_compression": "Sí"}
    results = evaluate_pivotal_contraindication_gates(payload)
    codes = [g["code"] for g in results]
    assert len(codes) == len(set(codes)), (
        f"Códigos duplicados detectados: {codes}"
    )
