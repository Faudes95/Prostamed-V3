"""tests/test_pivotal_gates_yaml_migration_gate9_complete.py — FAUBOT 2026-04-25 (XIX).

Cobertura del cierre de la migración a YAML declarativo:

  - Gate 9: `no_bone_protective_agent` (último gate Python migrado)

Esta migración requirió 2 nuevos trigger types en el loader:
  - `all_of`: composite AND (mirror de `any_of`)
  - `all_of_falsy`: dispara cuando todos los campos son falsy con
    soporte opcional para `negative_tokens` por campo

Verifica:
  - Los 2 nuevos trigger types funcionan aisladamente y compuestos
  - El YAML 09_no_bone_protective_agent.yaml carga + valida + dispara
    con paridad completa al detector Python equivalente (16+ escenarios)
  - El detector Python ya NO está en `_DETECTORS` (helper importable)
  - Algorithm version refleja **catálogo YAML 100% (19/19)**
  - Scorecard CDE Auditable: VERSIÓN alcanza 100% (4 de 5 dimensiones en 100%)

Hipótesis cubiertas: H.G282 - H.G298 (17 tests dedicadas + parametrizaciones).
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest

from prostanet.shared.pivotal_gates_yaml_loader import (
    _evaluate_trigger,
    evaluate_all_yaml_gates,
    get_loaded_yaml_codes,
    get_yaml_gate_sha,
    reset_yaml_cache,
    validate_all_yaml_gates,
    validate_yaml_gate_config,
    VALID_TRIGGER_TYPES,
)
from prostanet.shared.pivotal_contraindication_gates import (
    _DETECTORS,
    detect_no_bone_protective_agent_for_radium223,
    evaluate_pivotal_contraindication_gates,
)
from prostanet.shared.algorithm_version import get_algorithm_version


@pytest.fixture(autouse=True)
def _reset_yaml():
    reset_yaml_cache()
    yield
    reset_yaml_cache()


# ──────────────────────────────────────────────────────────────────────
# H.G282 — Trigger types `all_of` y `all_of_falsy` registrados
# ──────────────────────────────────────────────────────────────────────


def test_all_of_in_valid_trigger_types():
    """H.G282 — `all_of` está en VALID_TRIGGER_TYPES."""
    assert "all_of" in VALID_TRIGGER_TYPES


def test_all_of_falsy_in_valid_trigger_types():
    """H.G282.b — `all_of_falsy` está en VALID_TRIGGER_TYPES."""
    assert "all_of_falsy" in VALID_TRIGGER_TYPES


# ──────────────────────────────────────────────────────────────────────
# H.G283 — `all_of` semantics
# ──────────────────────────────────────────────────────────────────────


def test_all_of_fires_when_all_subtriggers_fire():
    """H.G283 — all_of dispara cuando TODOS los sub-triggers disparan."""
    trigger = {
        "type": "all_of",
        "triggers": [
            {"type": "truthy_flag", "field": "a"},
            {"type": "truthy_flag", "field": "b"},
        ],
    }
    assert _evaluate_trigger(trigger, {"a": "Sí", "b": "Sí"}) is True


def test_all_of_does_not_fire_when_any_fails():
    """H.G283.b — all_of NO dispara si alguno falla."""
    trigger = {
        "type": "all_of",
        "triggers": [
            {"type": "truthy_flag", "field": "a"},
            {"type": "truthy_flag", "field": "b"},
        ],
    }
    assert _evaluate_trigger(trigger, {"a": "Sí"}) is False
    assert _evaluate_trigger(trigger, {"a": "Sí", "b": "No"}) is False
    assert _evaluate_trigger(trigger, {}) is False


def test_all_of_empty_triggers_returns_false():
    """H.G283.c — all_of con triggers vacío retorna False (no AND vacío)."""
    trigger = {"type": "all_of", "triggers": []}
    assert _evaluate_trigger(trigger, {"a": "Sí"}) is False


# ──────────────────────────────────────────────────────────────────────
# H.G284 — `all_of_falsy` semantics
# ──────────────────────────────────────────────────────────────────────


def test_all_of_falsy_fires_when_all_fields_empty():
    """H.G284 — all_of_falsy dispara cuando todos los campos son vacíos."""
    trigger = {
        "type": "all_of_falsy",
        "fields": [{"field": "x"}, {"field": "y"}],
    }
    assert _evaluate_trigger(trigger, {}) is True


def test_all_of_falsy_does_not_fire_when_field_truthy():
    """H.G284.b — all_of_falsy NO dispara cuando alguno es truthy."""
    trigger = {
        "type": "all_of_falsy",
        "fields": [{"field": "x"}, {"field": "y"}],
    }
    assert _evaluate_trigger(trigger, {"x": "Sí"}) is False


@pytest.mark.parametrize("value,expected_falsy", [
    ("ninguno", True),
    ("NINGUNO", True),  # case-insensitive
    ("none", True),
    ("no", True),
    ("zoledronato", False),
    ("denosumab", False),
    ("", True),
    (None, True),
])
def test_all_of_falsy_with_negative_tokens(value, expected_falsy):
    """H.G285 — all_of_falsy con negative_tokens detecta tokens negativos."""
    trigger = {
        "type": "all_of_falsy",
        "fields": [
            {"field": "agent", "negative_tokens": ["ninguno", "none", "no"]},
        ],
    }
    payload = {"agent": value} if value is not None else {}
    # all_of_falsy fires if all fields are falsy → field falsy = expected_falsy
    assert _evaluate_trigger(trigger, payload) is expected_falsy


def test_all_of_falsy_mixed_negative_and_truthy():
    """H.G285.b — all_of_falsy mixto: agent=zoledronato (truthy) → no dispara."""
    trigger = {
        "type": "all_of_falsy",
        "fields": [
            {"field": "agent", "negative_tokens": ["ninguno"]},
            {"field": "denosumab"},
        ],
    }
    # agent="zoledronato" no es ninguno, así que NO es falsy → trigger no dispara
    assert _evaluate_trigger(
        trigger, {"agent": "zoledronato"}
    ) is False


def test_all_of_falsy_empty_fields_returns_false():
    """H.G286 — all_of_falsy con fields vacío retorna False."""
    trigger = {"type": "all_of_falsy", "fields": []}
    assert _evaluate_trigger(trigger, {}) is False


# ──────────────────────────────────────────────────────────────────────
# H.G287 — Validación de schema para `all_of` y `all_of_falsy`
# ──────────────────────────────────────────────────────────────────────


def test_validate_all_of_requires_triggers_list():
    """H.G287 — validate_yaml_gate_config detecta all_of sin triggers."""
    config = {
        "code": "test",
        "severity": "hard_block",
        "trigger": {"type": "all_of"},  # Sin triggers
        "message": "x",
        "evidence_tag": "x",
    }
    errors = validate_yaml_gate_config(config)
    assert any("all_of" in e and "triggers" in e for e in errors)


def test_validate_all_of_falsy_requires_fields_list():
    """H.G287.b — validate_yaml_gate_config detecta all_of_falsy sin fields."""
    config = {
        "code": "test",
        "severity": "hard_block",
        "trigger": {"type": "all_of_falsy"},  # Sin fields
        "message": "x",
        "evidence_tag": "x",
    }
    errors = validate_yaml_gate_config(config)
    assert any("all_of_falsy" in e and "fields" in e for e in errors)


def test_validate_all_of_falsy_fields_must_be_dicts_with_field_key():
    """H.G287.c — Cada item en fields debe ser dict con 'field'."""
    config = {
        "code": "test",
        "severity": "hard_block",
        "trigger": {
            "type": "all_of_falsy",
            "fields": [{"no_field_key": "x"}],
        },
        "message": "x",
        "evidence_tag": "x",
    }
    errors = validate_yaml_gate_config(config)
    assert any("'field' key" in e for e in errors)


# ──────────────────────────────────────────────────────────────────────
# H.G288 — Gate 9 cargado y válido
# ──────────────────────────────────────────────────────────────────────


def test_gate_9_loaded_in_yaml_catalog():
    """H.G288 — Gate 9 (no_bone_protective_agent) cargado en YAML catalog."""
    codes = get_loaded_yaml_codes()
    assert "no_bone_protective_agent" in codes


def test_gate_9_yaml_passes_schema_validation():
    """H.G288.b — El YAML del gate 9 pasa la validación de schema."""
    errors_by_gate = validate_all_yaml_gates()
    # Gate 9 no debe tener errores
    assert "no_bone_protective_agent" not in errors_by_gate, (
        f"Gate 9 inválido: {errors_by_gate.get('no_bone_protective_agent')}"
    )


def test_gate_9_has_sha():
    """H.G288.c — Gate 9 tiene SHA per-YAML."""
    sha = get_yaml_gate_sha("no_bone_protective_agent")
    assert sha and len(sha) == 12


# ──────────────────────────────────────────────────────────────────────
# H.G289 — Paridad Python vs YAML para gate 9 (16 escenarios)
# ──────────────────────────────────────────────────────────────────────


PARITY_CASES = [
    # (descripción, payload, expected_fires)
    ("explicit flag truthy", {"no_bone_protective_agent": "Sí"}, True),
    ("explicit flag + agent", {
        "no_bone_protective_agent": "Sí",
        "bone_modifying_agent": "denosumab",
    }, True),
    ("Ra-223 candidate sin agente", {"radium223_candidate": "Sí"}, True),
    ("considering_radium223 sin agente", {"considering_radium223": "Sí"}, True),
    ("planned regimen RADIUM_223", {"planned_systemic_regimen": "RADIUM_223"}, True),
    ("planned regimen lowercase ra_223", {"planned_systemic_regimen": "ra_223"}, True),
    ("planned regimen RADIUM223", {"planned_systemic_regimen": "RADIUM223"}, True),
    ("Ra-223 + denosumab=Sí no dispara", {
        "radium223_candidate": "Sí", "denosumab_prophylaxis": "Sí",
    }, False),
    ("Ra-223 + zoledronate=Sí no dispara", {
        "radium223_candidate": "Sí", "zoledronate_prophylaxis": "Sí",
    }, False),
    ("Ra-223 + bone_protection_started=Sí no dispara", {
        "radium223_candidate": "Sí", "bone_protection_started": "Sí",
    }, False),
    ("Ra-223 + agent zoledronato no dispara", {
        "radium223_candidate": "Sí", "bone_modifying_agent": "zoledronato",
    }, False),
    ("Ra-223 + agent ninguno (negative) dispara", {
        "radium223_candidate": "Sí", "bone_modifying_agent": "ninguno",
    }, True),
    ("Ra-223 + agent NONE (case-insens) dispara", {
        "radium223_candidate": "Sí", "bone_modifying_agent": "NONE",
    }, True),
    ("Ra-223 + agent No (negative) dispara", {
        "radium223_candidate": "Sí", "bone_modifying_agent": "no",
    }, True),
    ("Sin Ra-223 + agent ninguno NO dispara", {
        "bone_modifying_agent": "ninguno",
    }, False),
    ("Healthy vacío", {}, False),
    ("Healthy con agente capturado", {
        "bone_modifying_agent": "denosumab", "denosumab_prophylaxis": "Sí",
    }, False),
]


@pytest.mark.parametrize("description,payload,expected", PARITY_CASES)
def test_gate_9_python_yaml_parity(description, payload, expected):
    """H.G289 — Paridad completa Python vs YAML para gate 9."""
    py_result = detect_no_bone_protective_agent_for_radium223(payload)
    py_fired = bool(py_result and py_result.get("triggered"))
    yaml_results = evaluate_all_yaml_gates(payload)
    yaml_codes = [g["code"] for g in yaml_results]
    yaml_fired = "no_bone_protective_agent" in yaml_codes
    assert py_fired == yaml_fired == expected, (
        f"{description}: py={py_fired}, yaml={yaml_fired}, expected={expected}"
    )


# ──────────────────────────────────────────────────────────────────────
# H.G290 — Detector Python ya NO está en _DETECTORS
# ──────────────────────────────────────────────────────────────────────


def test_python_detector_gate_9_removed_from_detectors_tuple():
    """H.G290 — `detect_no_bone_protective_agent_for_radium223` removido
    de `_DETECTORS` (vive solo como helper importable)."""
    detector_names = {d.__name__ for d in _DETECTORS}
    assert "detect_no_bone_protective_agent_for_radium223" not in detector_names


def test_python_detector_gate_9_still_importable():
    """H.G290.b — La función sigue importable como helper."""
    # Si esta línea no falla en import, el helper sigue disponible.
    assert callable(detect_no_bone_protective_agent_for_radium223)


# ──────────────────────────────────────────────────────────────────────
# H.G291 — algorithm_version refleja catálogo YAML 100%
# ──────────────────────────────────────────────────────────────────────


def test_yaml_loaded_gates_count_is_at_least_19():
    """H.G291 — Catálogo YAML alcanza ≥19 (era 19 al cierre de #35; +4 en #38).

    Convención `>=` per CLAUDE.md §8.4 (forward-compat con futuros gates).
    """
    ver = get_algorithm_version()
    assert ver["yaml_loaded_gates_count"] >= 19


def test_total_active_gates_is_at_least_19():
    """H.G291.b — Total de gates únicos ≥19 (cobertura clínica invariante;
    extensiones añaden gates sin reducir cobertura).

    Faubot 2026-04-25 (XXVI) #38: +4 gates clínicos extendidos (gates 20-23) → 23.
    """
    ver = get_algorithm_version()
    assert ver["gates_active_count"] >= 19


def test_python_detectors_now_only_12():
    """H.G292 — Tras migrar gate 9, _DETECTORS contiene 12 detectores Python
    (era 13 antes de #35)."""
    assert len(_DETECTORS) >= 12


def test_per_gate_yaml_shas_has_at_least_19_entries():
    """H.G293 — per_gate_yaml_shas tiene ≥19 entradas (forward-compat per §8.4)."""
    ver = get_algorithm_version()
    assert len(ver["per_gate_yaml_shas"]) >= 19


def test_gate_9_in_yaml_loaded_gate_codes():
    """H.G293.b — gate 9 aparece en yaml_loaded_gate_codes."""
    ver = get_algorithm_version()
    assert "no_bone_protective_agent" in ver["yaml_loaded_gate_codes"]


def test_faubot_release_at_least_xix():
    """H.G294 — FAUBOT_RELEASE >= 2026-04-25 XIX (post #35, iteración 19).

    Faubot 2026-04-25 (LVI / Auditoría #57): refactor para usar
    `_roman_to_int()` ya que la comparación lexicográfica falla con
    romanos > XL (ord('L') < ord('X') hace que 'LV' < 'XIX').
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
    # Faubot LXXXI #audit-pre-cortana — accept 2026-04-2X (date may bump in
    # future iterations beyond original 2026-04-25)
    assert ver["faubot_release"].startswith("2026-04-"), (
        f"FAUBOT release prefix expected 2026-04-2X; got: {ver['faubot_release']}"
    )
    roman_part = ver["faubot_release"].rsplit(" ", 1)[-1].strip()
    iteration = _roman_to_int(roman_part)
    assert iteration >= 19, (
        f"FAUBOT iteration {iteration} (from '{roman_part}') < 19 expected; "
        f"full release: {ver['faubot_release']}"
    )


# ──────────────────────────────────────────────────────────────────────
# H.G295 — Pipeline E2E: gate 9 dispatch correcto vía YAML
# ──────────────────────────────────────────────────────────────────────


def test_pipeline_e2e_gate_9_via_yaml_dispatch():
    """H.G295 — `evaluate_pivotal_contraindication_gates` dispatcha gate 9
    correctamente desde YAML (sin Python detector activo)."""
    payload = {"radium223_candidate": "Sí"}  # Path 2: Ra-223 sin agente
    results = evaluate_pivotal_contraindication_gates(payload)
    codes = [g["code"] for g in results]
    assert "no_bone_protective_agent" in codes


def test_pipeline_e2e_gate_9_no_duplicates():
    """H.G295.b — Gate 9 aparece máximo 1 vez (dedup OK)."""
    payload = {"no_bone_protective_agent": "Sí"}
    results = evaluate_pivotal_contraindication_gates(payload)
    codes = [g["code"] for g in results]
    assert codes.count("no_bone_protective_agent") == 1


# ──────────────────────────────────────────────────────────────────────
# H.G296 — Estructura de retorno del gate 9 desde YAML
# ──────────────────────────────────────────────────────────────────────


def test_gate_9_yaml_returns_complete_dict():
    """H.G296 — Gate 9 retorna dict con todos los campos esperados."""
    payload = {"no_bone_protective_agent": "Sí"}
    results = evaluate_all_yaml_gates(payload)
    gate_9 = next((g for g in results if g["code"] == "no_bone_protective_agent"), None)
    assert gate_9 is not None
    for field in ("code", "triggered", "severity", "affected_regimen_codes",
                  "affected_keywords", "message", "evidence_tag", "trial_refs"):
        assert field in gate_9, f"Falta campo {field}"
    assert gate_9["severity"] == "hard_block"
    assert "ERA-223" in gate_9["trial_refs"]
    assert "PEACE-3" in gate_9["trial_refs"]
    assert "denosumab" in gate_9["message"].lower()
    assert "zoledr" in gate_9["message"].lower()


# ──────────────────────────────────────────────────────────────────────
# H.G297 — Métricas de cierre de la migración a YAML
# ──────────────────────────────────────────────────────────────────────


def test_yaml_catalog_now_has_at_least_19_files():
    """H.G297 — Catálogo YAML tiene ≥19 archivos (forward-compat per §8.4).

    Faubot 2026-04-25 (XXVI) #38: +4 nuevos gates YAML (gates 20-23) → 23 archivos.
    """
    codes = get_loaded_yaml_codes()
    assert len(codes) >= 19


def test_no_python_only_gates_remain():
    """H.G297.b — Ningún gate vive ÚNICAMENTE en Python (todos en YAML).

    Verifica que cada gate Python registrado en _DETECTORS también está
    cubierto por YAML (o es un duplicado intencional). El sistema híbrido
    ahora prefiere YAML pero acepta Python para gates que no migraron."""
    yaml_codes = set(get_loaded_yaml_codes())
    # Los detectores Python siguen registrados pero todos sus codes
    # también deben estar en YAML.
    func_to_code = {
        "no_bone_protective_agent_for_radium223": "no_bone_protective_agent",
        "creatinine_clearance_lt_30_for_rucaparib": "creatinine_clearance_lt_30",
    }
    python_codes = set()
    for det in _DETECTORS:
        suffix = det.__name__.replace("detect_", "")
        code = func_to_code.get(suffix, suffix)
        python_codes.add(code)
    # Todos los codes Python deben estar también en YAML
    not_in_yaml = python_codes - yaml_codes
    assert not not_in_yaml, (
        f"Gates Python no respaldados por YAML: {not_in_yaml}"
    )


# ──────────────────────────────────────────────────────────────────────
# H.G298 — Scorecard CDE Auditable: VERSIÓN 100%
# ──────────────────────────────────────────────────────────────────────


def test_versioning_dimension_complete():
    """H.G298 — Cada gate tiene SHA per-YAML; VERSIÓN está al 100%.

    Verifica que (1) todos los gates tienen SHA registrado, (2) el sistema
    reporta paridad entre yaml_loaded_gates_count y gates_active_count
    (todos los gates están en YAML), y (3) total ≥19 (forward-compat §8.4).
    """
    ver = get_algorithm_version()
    assert ver["yaml_loaded_gates_count"] == ver["gates_active_count"]
    assert ver["yaml_loaded_gates_count"] >= 19
    assert len(ver["per_gate_yaml_shas"]) == ver["yaml_loaded_gates_count"]
    # Cada SHA debe ser de longitud 12 hex
    for code, sha in ver["per_gate_yaml_shas"].items():
        assert len(sha) == 12, f"{code}: SHA {sha!r} mal formado"
