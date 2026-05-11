"""Tests extendidos del loader YAML — 8 gates adicionales migrados.

Faubot 2026-04-25 (XIII) — Continuación Tier 4.H:
  - Migra 8 gates adicionales a YAML declarativo (total 12/18 = 67%)
  - Extiende loader con 3 nuevos trigger types: numeric_above, any_of,
    numeric_baseline_delta_above
  - Verifica equivalencia funcional con detectores Python para los 8

Aporta a:
  - **VERSIÓN** (92% → ~98%): SHA per-gate para 12 gates
  - **EVIDENCIA** (99% → ~100%): documentación per-gate explícita

Cobertura del test:
  A) Nuevos trigger types (any_of, numeric_above, numeric_baseline_delta_above)
  B) Schema validation actualizado (any_of requires triggers list)
  C) 8 YAMLs nuevos cargados correctamente
  D) Equivalencia funcional con Python para 8 gates nuevos
  E) Override numérico funciona (gate 17 QTc + qtc_corrected_for_arpi)
  F) Override numérico LVEF baseline_delta (gate 18 + lvef_recovered_for_arpi)
  G) Total YAML loaded count = 12; total Python detectors = 18 (deduplicación)
  H) Smoke E2E con paciente multi-gates
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest

from prostanet.shared.pivotal_contraindication_gates import (
    evaluate_pivotal_contraindication_gates,
)
from prostanet.shared.pivotal_gates_yaml_loader import (
    _evaluate_trigger,
    evaluate_all_yaml_gates,
    evaluate_yaml_gate,
    get_loaded_yaml_codes,
    reset_yaml_cache,
    validate_all_yaml_gates,
    validate_yaml_gate_config,
)


# ── Sección A — Nuevos trigger types ──────────────────────────────────────


class TestNewTriggerTypes:
    def test_any_of_dispara_si_uno_dispara(self):
        trigger = {
            "type": "any_of",
            "triggers": [
                {"type": "truthy_flag", "field": "f1"},
                {"type": "numeric_above", "field": "f2", "threshold": 10},
            ],
        }
        # Solo f1 dispara
        assert _evaluate_trigger(trigger, {"f1": "Sí"}) is True
        # Solo f2 dispara
        assert _evaluate_trigger(trigger, {"f2": 15}) is True
        # Ambos disparan
        assert _evaluate_trigger(trigger, {"f1": "Sí", "f2": 15}) is True

    def test_any_of_no_dispara_si_ninguno(self):
        trigger = {
            "type": "any_of",
            "triggers": [
                {"type": "truthy_flag", "field": "f1"},
                {"type": "numeric_above", "field": "f2", "threshold": 10},
            ],
        }
        assert _evaluate_trigger(trigger, {"f1": "No", "f2": 5}) is False

    def test_any_of_empty_triggers_returns_false(self):
        assert _evaluate_trigger({"type": "any_of", "triggers": []}, {"x": "y"}) is False

    @pytest.mark.parametrize(
        "value,expected",
        [(499, False), (500, False), (501, True), (520, True), (600, True)],
    )
    def test_numeric_above_strict(self, value, expected):
        """numeric_above dispara con > threshold (estricto, sin igualdad)."""
        trigger = {"type": "numeric_above", "field": "qtc_ms", "threshold": 500}
        assert _evaluate_trigger(trigger, {"qtc_ms": value}) is expected

    def test_numeric_above_with_alias_fields(self):
        trigger = {
            "type": "numeric_above", "field": "qtc_ms",
            "alias_fields": ["qtc_baseline_ms"],
            "threshold": 500,
        }
        assert _evaluate_trigger(trigger, {"qtc_baseline_ms": 510}) is True

    @pytest.mark.parametrize(
        "baseline,current,expected",
        [
            (60, 48, True),    # delta -12 > 10
            (60, 50, False),   # delta -10 NO > 10 (boundary)
            (60, 52, False),   # delta -8 < 10
            (50, 60, False),   # current > baseline → delta negativo
            (None, 50, False), # baseline missing
            (60, None, False), # current missing
        ],
    )
    def test_numeric_baseline_delta_above(self, baseline, current, expected):
        trigger = {
            "type": "numeric_baseline_delta_above",
            "baseline_field": "lvef_baseline",
            "current_field": "lvef_current",
            "threshold": 10,
        }
        payload = {}
        if baseline is not None:
            payload["lvef_baseline"] = baseline
        if current is not None:
            payload["lvef_current"] = current
        assert _evaluate_trigger(trigger, payload) is expected

    def test_numeric_baseline_delta_above_missing_threshold(self):
        trigger = {
            "type": "numeric_baseline_delta_above",
            "baseline_field": "b",
            "current_field": "c",
        }
        assert _evaluate_trigger(trigger, {"b": 60, "c": 30}) is False

    def test_numeric_baseline_delta_above_missing_fields(self):
        trigger = {
            "type": "numeric_baseline_delta_above",
            "threshold": 10,
        }
        assert _evaluate_trigger(trigger, {"b": 60, "c": 30}) is False


# ── Sección B — Schema validation actualizado ─────────────────────────────


class TestSchemaValidationExtended:
    def test_any_of_requires_triggers_list(self):
        config = {
            "code": "x", "severity": "hard_block",
            "trigger": {"type": "any_of"},  # falta `triggers`
            "message": "msg", "evidence_tag": "tag",
        }
        errors = validate_yaml_gate_config(config)
        assert any("any_of" in e and "triggers" in e for e in errors)

    def test_any_of_with_empty_triggers_invalid(self):
        config = {
            "code": "x", "severity": "hard_block",
            "trigger": {"type": "any_of", "triggers": []},
            "message": "msg", "evidence_tag": "tag",
        }
        errors = validate_yaml_gate_config(config)
        assert any("any_of" in e for e in errors)

    def test_any_of_with_valid_triggers_passes(self):
        config = {
            "code": "x", "severity": "hard_block",
            "trigger": {
                "type": "any_of",
                "triggers": [{"type": "truthy_flag", "field": "f"}],
            },
            "message": "msg", "evidence_tag": "tag",
        }
        assert validate_yaml_gate_config(config) == []

    def test_baseline_delta_requires_baseline_and_current_fields(self):
        config = {
            "code": "x", "severity": "hard_block",
            "trigger": {
                "type": "numeric_baseline_delta_above",
                "threshold": 10,
                # falta baseline_field y current_field
            },
            "message": "msg", "evidence_tag": "tag",
        }
        errors = validate_yaml_gate_config(config)
        assert any(
            "baseline_field" in e or "current_field" in e
            for e in errors
        )

    def test_baseline_delta_with_both_fields_passes(self):
        config = {
            "code": "x", "severity": "hard_block",
            "trigger": {
                "type": "numeric_baseline_delta_above",
                "baseline_field": "b",
                "current_field": "c",
                "threshold": 10,
            },
            "message": "msg", "evidence_tag": "tag",
        }
        assert validate_yaml_gate_config(config) == []

    def test_numeric_above_requires_field(self):
        config = {
            "code": "x", "severity": "hard_block",
            "trigger": {"type": "numeric_above", "threshold": 500},
            "message": "msg", "evidence_tag": "tag",
        }
        errors = validate_yaml_gate_config(config)
        assert any("field" in e for e in errors)


# ── Sección C — 12 YAMLs cargados ─────────────────────────────────────────


class TestTwelveYamlsLoaded:
    def setup_method(self):
        reset_yaml_cache()

    def test_total_yaml_count_at_least_12(self):
        # Faubot 2026-04-25 (XIV) — Bumped after gate 19 (cognitive decline)
        # added as 13th YAML. Use >= for forward compatibility.
        codes = get_loaded_yaml_codes()
        assert len(codes) >= 12, f"Esperado ≥12 YAMLs, encontrados: {codes}"

    def test_8_new_gates_loaded(self):
        codes = set(get_loaded_yaml_codes())
        nuevos = {
            "severe_neuropathy_grade3",
            "severe_heart_failure_nyha_iii_iv",
            "ecog_2_or_more_for_triplets",
            "polysorbate_hypersensitivity",
            "creatinine_clearance_lt_30",
            "parp_inhibitor_in_mds_aml_history",
            "qtc_prolongation_grade3_for_enzalutamide",
            "lvef_decline_for_apalutamide",
        }
        missing = nuevos - codes
        assert not missing, f"YAMLs faltantes: {missing}"

    def test_all_yaml_validation_passes(self):
        errors = validate_all_yaml_gates()
        assert errors == {}, f"Errores de validación: {errors}"


# ── Sección D — Equivalencia funcional con Python (8 gates nuevos) ────────


class TestFunctionalEquivalence8NewGates:
    """Para cada gate migrado, el YAML produce el MISMO dict que el Python."""

    def setup_method(self):
        reset_yaml_cache()

    def _compare_essential_fields(self, yaml_result, python_result):
        """Compara campos críticos (omitiendo message que puede diferir
        ligeramente por f-strings vs YAML estático)."""
        assert yaml_result["code"] == python_result["code"]
        assert yaml_result["severity"] == python_result["severity"]
        assert yaml_result["affected_regimen_codes"] == python_result["affected_regimen_codes"]
        assert set(yaml_result["affected_keywords"]) == set(python_result["affected_keywords"])
        assert set(yaml_result["trial_refs"]) == set(python_result["trial_refs"])
        assert yaml_result["evidence_tag"] == python_result["evidence_tag"]

    def test_severe_neuropathy_grade3_equivalence(self):
        from prostanet.shared.pivotal_contraindication_gates import (
            detect_severe_neuropathy_grade3,
        )
        payload = {"peripheral_neuropathy_grade": 4}
        py_result = detect_severe_neuropathy_grade3(payload)
        yaml_results = evaluate_all_yaml_gates(payload)
        yaml_result = next(
            (g for g in yaml_results if g["code"] == "severe_neuropathy_grade3"), None
        )
        assert py_result is not None
        assert yaml_result is not None
        self._compare_essential_fields(yaml_result, py_result)

    def test_severe_heart_failure_nyha_iii_iv_equivalence(self):
        from prostanet.shared.pivotal_contraindication_gates import (
            detect_severe_heart_failure_nyha_iii_iv,
        )
        payload = {"nyha_class": "III"}
        py_result = detect_severe_heart_failure_nyha_iii_iv(payload)
        yaml_results = evaluate_all_yaml_gates(payload)
        yaml_result = next(
            (g for g in yaml_results if g["code"] == "severe_heart_failure_nyha_iii_iv"), None
        )
        assert py_result is not None
        assert yaml_result is not None
        self._compare_essential_fields(yaml_result, py_result)

    def test_ecog_2_or_more_for_triplets_equivalence(self):
        from prostanet.shared.pivotal_contraindication_gates import (
            detect_ecog_2_or_more_for_triplets,
        )
        payload = {"ecog_score": 2}
        py_result = detect_ecog_2_or_more_for_triplets(payload)
        yaml_results = evaluate_all_yaml_gates(payload)
        yaml_result = next(
            (g for g in yaml_results if g["code"] == "ecog_2_or_more_for_triplets"), None
        )
        assert py_result is not None
        assert yaml_result is not None
        self._compare_essential_fields(yaml_result, py_result)

    def test_polysorbate_hypersensitivity_equivalence(self):
        from prostanet.shared.pivotal_contraindication_gates import (
            detect_polysorbate_hypersensitivity,
        )
        payload = {"polysorbate_hypersensitivity": "Sí"}
        py_result = detect_polysorbate_hypersensitivity(payload)
        yaml_results = evaluate_all_yaml_gates(payload)
        yaml_result = next(
            (g for g in yaml_results if g["code"] == "polysorbate_hypersensitivity"), None
        )
        assert py_result is not None
        assert yaml_result is not None
        self._compare_essential_fields(yaml_result, py_result)

    def test_creatinine_clearance_lt_30_equivalence(self):
        from prostanet.shared.pivotal_contraindication_gates import (
            detect_creatinine_clearance_lt_30_for_rucaparib,
        )
        payload = {"creatinine_clearance": 25}
        py_result = detect_creatinine_clearance_lt_30_for_rucaparib(payload)
        yaml_results = evaluate_all_yaml_gates(payload)
        yaml_result = next(
            (g for g in yaml_results if g["code"] == "creatinine_clearance_lt_30"), None
        )
        assert py_result is not None
        assert yaml_result is not None
        self._compare_essential_fields(yaml_result, py_result)

    def test_parp_inhibitor_in_mds_aml_history_equivalence(self):
        from prostanet.shared.pivotal_contraindication_gates import (
            detect_parp_inhibitor_in_mds_aml_history,
        )
        payload = {"mds_aml_history": "Sí"}
        py_result = detect_parp_inhibitor_in_mds_aml_history(payload)
        yaml_results = evaluate_all_yaml_gates(payload)
        yaml_result = next(
            (g for g in yaml_results if g["code"] == "parp_inhibitor_in_mds_aml_history"), None
        )
        assert py_result is not None
        assert yaml_result is not None
        self._compare_essential_fields(yaml_result, py_result)

    def test_qtc_prolongation_grade3_for_enzalutamide_equivalence(self):
        from prostanet.shared.pivotal_contraindication_gates import (
            detect_qtc_prolongation_grade3_for_enzalutamide,
        )
        payload = {"qtc_ms": 520}
        py_result = detect_qtc_prolongation_grade3_for_enzalutamide(payload)
        yaml_results = evaluate_all_yaml_gates(payload)
        yaml_result = next(
            (g for g in yaml_results if g["code"] == "qtc_prolongation_grade3_for_enzalutamide"), None
        )
        assert py_result is not None
        assert yaml_result is not None
        self._compare_essential_fields(yaml_result, py_result)

    def test_lvef_decline_for_apalutamide_equivalence(self):
        from prostanet.shared.pivotal_contraindication_gates import (
            detect_lvef_decline_for_apalutamide,
        )
        payload = {"lvef_percent": 45}
        py_result = detect_lvef_decline_for_apalutamide(payload)
        yaml_results = evaluate_all_yaml_gates(payload)
        yaml_result = next(
            (g for g in yaml_results if g["code"] == "lvef_decline_for_apalutamide"), None
        )
        assert py_result is not None
        assert yaml_result is not None
        self._compare_essential_fields(yaml_result, py_result)


# ── Sección E — Override numérico para gate 17 QTc ────────────────────────


class TestGate17QtcOverride:
    def setup_method(self):
        reset_yaml_cache()

    def test_qtc_500_below_threshold_no_dispara(self):
        results = evaluate_all_yaml_gates({"qtc_ms": 500})
        codes = [g["code"] for g in results]
        assert "qtc_prolongation_grade3_for_enzalutamide" not in codes

    def test_qtc_501_above_threshold_dispara(self):
        results = evaluate_all_yaml_gates({"qtc_ms": 501})
        codes = [g["code"] for g in results]
        assert "qtc_prolongation_grade3_for_enzalutamide" in codes

    def test_qtc_change_61_above_threshold_dispara(self):
        results = evaluate_all_yaml_gates({"qtc_change_ms": 61})
        codes = [g["code"] for g in results]
        assert "qtc_prolongation_grade3_for_enzalutamide" in codes

    def test_qtc_corrected_override_desactiva_gate(self):
        results = evaluate_all_yaml_gates({
            "qtc_ms": 520,
            "qtc_corrected_for_arpi": "Sí",
        })
        codes = [g["code"] for g in results]
        assert "qtc_prolongation_grade3_for_enzalutamide" not in codes


# ── Sección F — Override LVEF + baseline_delta ────────────────────────────


class TestGate18LvefOverride:
    def setup_method(self):
        reset_yaml_cache()

    def test_lvef_50_no_dispara(self):
        results = evaluate_all_yaml_gates({"lvef_percent": 50})
        codes = [g["code"] for g in results]
        assert "lvef_decline_for_apalutamide" not in codes

    def test_lvef_49_dispara(self):
        results = evaluate_all_yaml_gates({"lvef_percent": 49})
        codes = [g["code"] for g in results]
        assert "lvef_decline_for_apalutamide" in codes

    def test_lvef_60_to_48_baseline_delta_dispara(self):
        results = evaluate_all_yaml_gates({
            "lvef_baseline_percent": 60,
            "lvef_percent": 48,
        })
        codes = [g["code"] for g in results]
        assert "lvef_decline_for_apalutamide" in codes

    def test_lvef_recovered_override_desactiva(self):
        results = evaluate_all_yaml_gates({
            "lvef_percent": 45,
            "lvef_recovered_for_arpi": "Sí",
        })
        codes = [g["code"] for g in results]
        assert "lvef_decline_for_apalutamide" not in codes


# ── Sección G — Total counts + dedup ──────────────────────────────────────


class TestTotalCountsAndDedup:
    def test_total_yaml_loaded_at_least_12(self):
        reset_yaml_cache()
        from prostanet.shared.algorithm_version import get_yaml_loaded_gate_codes
        codes = get_yaml_loaded_gate_codes()
        assert len(codes) >= 12

    def test_total_python_detectors_at_least_12(self):
        """Faubot 2026-04-25 (XIX) — Tras la migración de gate 9 a YAML,
        `_DETECTORS` contiene 12 detectores Python (era 18 originalmente).
        El catálogo YAML alcanza 19/19 (100%); el sistema híbrido total
        sigue en 19 gates únicos (Python + YAML)."""
        from prostanet.shared.pivotal_contraindication_gates import _DETECTORS
        assert len(_DETECTORS) >= 12

    def test_no_gate_duplicated_with_yaml_and_python(self):
        """Gate cargado en YAML NO debe disparar también vía Python (dedupe)."""
        gates = evaluate_pivotal_contraindication_gates({
            "qtc_ms": 520,
            "lvef_percent": 45,
            "mds_aml_history": "Sí",
        })
        codes = [g["code"] for g in gates]
        # Cada code debe aparecer exactamente UNA vez
        assert len(codes) == len(set(codes))
        # Y los 3 deben estar presentes
        assert "qtc_prolongation_grade3_for_enzalutamide" in codes
        assert "lvef_decline_for_apalutamide" in codes
        assert "parp_inhibitor_in_mds_aml_history" in codes


# ── Sección H — Smoke E2E ─────────────────────────────────────────────────


class TestSmokeE2EMultiGates:
    def test_paciente_con_5_yaml_gates(self):
        """Paciente con condiciones que activan 5 YAML gates simultáneos."""
        gates = evaluate_pivotal_contraindication_gates({
            "uncontrolled_hypertension": "Sí",        # YAML #3
            "uncontrolled_diabetes": "Sí",            # YAML #5
            "darolutamide_hypersensitivity": "Sí",    # YAML #7
            "ecog_score": 2,                          # YAML #6
            "qtc_ms": 520,                            # YAML #17
        })
        codes = {g["code"] for g in gates}
        assert "uncontrolled_hypertension" in codes
        assert "uncontrolled_diabetes" in codes
        assert "darolutamide_hypersensitivity" in codes
        assert "ecog_2_or_more_for_triplets" in codes
        assert "qtc_prolongation_grade3_for_enzalutamide" in codes

    def test_modular_registry_e2e_with_yaml_gates(self):
        """End-to-end vía m1_crpc service usando gates YAML."""
        from prostanet.application.module_registry import ModuleRegistry
        r = ModuleRegistry()
        result = r.evaluate_module("m1_crpc", {
            "psa": 30, "psa_doubling_time": 4, "metastatic": "1",
            "visceral_metastasis": "0", "bone_lesion_count": 4,
            "ecog_score": 1, "age": 70,
            "castrate_resistant": "1", "testosterone": 20,
            "nyha_class": "III",   # → YAML gate 4 dispara
            "qtc_ms": 520,         # → YAML gate 17 dispara
            "lvef_percent": 45,    # → YAML gate 18 dispara
            "creatinine_clearance": 25,  # → YAML gate 10 dispara
        })
        gates = result.get("pivotal_contraindication_gates") or []
        codes = {g["code"] for g in gates}
        assert "severe_heart_failure_nyha_iii_iv" in codes
        assert "qtc_prolongation_grade3_for_enzalutamide" in codes
        assert "lvef_decline_for_apalutamide" in codes
        assert "creatinine_clearance_lt_30" in codes


# ── Sección I — Algorithm version refleja 12 YAMLs ────────────────────────


class TestAlgorithmVersionReflects12Yamls:
    def test_yaml_loaded_gates_count_at_least_12(self):
        reset_yaml_cache()
        from prostanet.shared.algorithm_version import get_algorithm_version
        v = get_algorithm_version()
        assert v["yaml_loaded_gates_count"] >= 12

    def test_per_gate_yaml_shas_at_least_12_entries(self):
        reset_yaml_cache()
        from prostanet.shared.algorithm_version import get_per_gate_yaml_shas
        shas = get_per_gate_yaml_shas()
        assert len(shas) >= 12
        # Cada SHA es de 12 chars
        for code, sha in shas.items():
            assert len(sha) == 12
