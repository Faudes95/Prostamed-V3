"""Tests del loader YAML declarativo de gates pivotal.

Faubot 2026-04-25 (XI) — Cierra Tier 4.H del backlog (parcial):
migración piloto de 4 gates simples a YAML declarativo + sistema
híbrido YAML+Python con deduplicación por code.

Aporta a:
  - **VERSIÓN** (80% → ~95%): cada gate YAML tiene su propio SHA
  - **EVIDENCIA** (97% → ~99%): trial_refs + references explícitos en YAML

Cobertura del test:
  A) Loader carga 4 gates piloto correctamente
  B) Schema validation — required fields + valid types
  C) Trigger evaluation — truthy_flag + numeric_threshold + numeric_below + string_match
  D) Override evaluation — desactiva el gate cuando aplica
  E) Resolución de catálogos compartidos (REGIMEN_CODES_DAROLUTAMIDE etc.)
  F) Equivalencia funcional con detectores Python (regresión cero)
  G) Deduplicación: gate YAML + Python no duplica
  H) Per-gate SHA + algorithm_version extendido
  I) Smoke E2E con paciente realista
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest

from prostanet.shared.algorithm_version import (
    get_algorithm_version,
    get_per_gate_yaml_shas,
    get_yaml_loaded_gate_codes,
)
from prostanet.shared.pivotal_contraindication_gates import (
    evaluate_pivotal_contraindication_gates,
)
from prostanet.shared.pivotal_gates_yaml_loader import (
    CATALOG_DIR,
    _evaluate_override,
    _evaluate_trigger,
    _resolve_keywords,
    _resolve_regimen_codes,
    evaluate_all_yaml_gates,
    evaluate_yaml_gate,
    get_all_yaml_gate_shas,
    get_loaded_yaml_codes,
    get_yaml_gate_sha,
    reset_yaml_cache,
    validate_all_yaml_gates,
    validate_yaml_gate_config,
)


# ── Sección A — Loader carga 4 gates piloto ───────────────────────────────


class TestLoaderLoadsPilotGates:
    def test_catalog_directory_exists(self):
        assert CATALOG_DIR.exists()
        assert CATALOG_DIR.is_dir()

    def test_4_pilot_gates_loaded(self):
        codes = get_loaded_yaml_codes()
        # Al menos los 4 gates piloto migrados en #27
        assert "prior_arpi_exposure_mhspc" in codes
        assert "uncontrolled_hypertension" in codes
        assert "uncontrolled_diabetes" in codes
        assert "darolutamide_hypersensitivity" in codes
        assert len(codes) >= 4

    def test_loaded_codes_sorted(self):
        codes = get_loaded_yaml_codes()
        assert codes == sorted(codes)


# ── Sección B — Schema validation ─────────────────────────────────────────


class TestSchemaValidation:
    def test_all_yaml_gates_pass_validation(self):
        errors = validate_all_yaml_gates()
        assert errors == {}, f"Validation errors: {errors}"

    def test_validation_detects_missing_code(self):
        errors = validate_yaml_gate_config({"severity": "hard_block"})
        assert any("code" in e for e in errors)

    def test_validation_detects_missing_severity(self):
        errors = validate_yaml_gate_config({"code": "x", "trigger": {"type": "truthy_flag", "field": "x"}})
        assert any("severity" in e or "Missing" in e for e in errors)

    def test_validation_detects_invalid_severity(self):
        errors = validate_yaml_gate_config({
            "code": "x", "severity": "invalid_severity",
            "trigger": {"type": "truthy_flag", "field": "x"},
            "message": "test", "evidence_tag": "test",
        })
        assert any("severity" in e.lower() for e in errors)

    def test_validation_detects_invalid_trigger_type(self):
        errors = validate_yaml_gate_config({
            "code": "x", "severity": "hard_block",
            "trigger": {"type": "invalid_trigger", "field": "x"},
            "message": "test", "evidence_tag": "test",
        })
        assert any("trigger" in e.lower() for e in errors)

    def test_validation_detects_missing_trigger_field(self):
        errors = validate_yaml_gate_config({
            "code": "x", "severity": "hard_block",
            "trigger": {"type": "truthy_flag"},
            "message": "test", "evidence_tag": "test",
        })
        assert any("field" in e.lower() for e in errors)

    def test_validation_passes_minimal_valid_config(self):
        errors = validate_yaml_gate_config({
            "code": "x",
            "severity": "hard_block",
            "trigger": {"type": "truthy_flag", "field": "x"},
            "message": "msg",
            "evidence_tag": "tag",
        })
        assert errors == []


# ── Sección C — Trigger evaluation ────────────────────────────────────────


class TestTriggerEvaluation:
    def test_truthy_flag_trigger_yes(self):
        assert _evaluate_trigger(
            {"type": "truthy_flag", "field": "f1"},
            {"f1": "Sí"},
        ) is True

    def test_truthy_flag_trigger_no(self):
        assert _evaluate_trigger(
            {"type": "truthy_flag", "field": "f1"},
            {"f1": "No"},
        ) is False

    def test_truthy_flag_alias_fields(self):
        assert _evaluate_trigger(
            {"type": "truthy_flag", "field": "primary", "alias_fields": ["alias1", "alias2"]},
            {"alias2": "1"},
        ) is True

    @pytest.mark.parametrize(
        "value,expected",
        [(2, False), (3, True), (4, True), (10, True)],
    )
    def test_numeric_threshold_trigger(self, value, expected):
        assert _evaluate_trigger(
            {"type": "numeric_threshold", "field": "f1", "threshold": 3},
            {"f1": value},
        ) is expected

    @pytest.mark.parametrize(
        "value,expected",
        [(15, True), (29, True), (30, False), (50, False)],
    )
    def test_numeric_below_trigger(self, value, expected):
        """numeric_below dispara cuando value < threshold."""
        assert _evaluate_trigger(
            {"type": "numeric_below", "field": "f1", "threshold": 30},
            {"f1": value},
        ) is expected

    def test_string_match_case_insensitive_default(self):
        assert _evaluate_trigger(
            {"type": "string_match", "field": "f1", "match_values": ["III", "IV"]},
            {"f1": "iii"},
        ) is True

    def test_string_match_no_match(self):
        assert _evaluate_trigger(
            {"type": "string_match", "field": "f1", "match_values": ["III", "IV"]},
            {"f1": "II"},
        ) is False

    def test_unknown_trigger_type_returns_false(self):
        assert _evaluate_trigger(
            {"type": "unknown", "field": "f1"},
            {"f1": "x"},
        ) is False


# ── Sección D — Override evaluation ───────────────────────────────────────


class TestOverrideEvaluation:
    def test_no_override_returns_false(self):
        assert _evaluate_override(None, {"x": "Sí"}) is False
        assert _evaluate_override({}, {"x": "Sí"}) is False

    def test_override_truthy_flag_disables_gate(self):
        gate_config = {
            "code": "x", "severity": "hard_block",
            "trigger": {"type": "truthy_flag", "field": "trigger_field"},
            "override": {"type": "truthy_flag", "field": "override_field"},
            "message": "msg", "evidence_tag": "tag",
        }
        # Trigger disparado pero override activo → None
        assert evaluate_yaml_gate(
            gate_config, {"trigger_field": "Sí", "override_field": "Sí"}
        ) is None

    def test_trigger_without_override_returns_gate(self):
        gate_config = {
            "code": "x", "severity": "hard_block",
            "trigger": {"type": "truthy_flag", "field": "trigger_field"},
            "override": {"type": "truthy_flag", "field": "override_field"},
            "message": "msg", "evidence_tag": "tag",
        }
        result = evaluate_yaml_gate(
            gate_config, {"trigger_field": "Sí", "override_field": "No"}
        )
        assert result is not None
        assert result["code"] == "x"


# ── Sección E — Resolución de catálogos compartidos ───────────────────────


class TestCatalogResolution:
    def test_resolve_regimen_codes_from_canonical_name(self):
        codes = _resolve_regimen_codes(["REGIMEN_CODES_DAROLUTAMIDE"])
        assert "DAROLUTAMIDE" in codes
        assert "ADT_DAROLUTAMIDE" in codes

    def test_resolve_regimen_codes_with_literal_strings(self):
        codes = _resolve_regimen_codes(["MY_LITERAL_CODE", "ANOTHER_CODE"])
        assert "MY_LITERAL_CODE" in codes
        assert "ANOTHER_CODE" in codes

    def test_resolve_regimen_codes_mixed(self):
        codes = _resolve_regimen_codes(["REGIMEN_CODES_DAROLUTAMIDE", "EXTRA_CODE"])
        assert "DAROLUTAMIDE" in codes
        assert "EXTRA_CODE" in codes

    def test_resolve_keywords_from_canonical_name(self):
        kws = _resolve_keywords(["KEYWORDS_DAROLUTAMIDE"])
        assert "darolutamida" in kws

    def test_resolve_unknown_catalog_returns_empty_or_literal(self):
        codes = _resolve_regimen_codes(["REGIMEN_CODES_NONEXISTENT_FOO"])
        # No debe romper, retorna empty
        assert isinstance(codes, frozenset)


# ── Sección F — Equivalencia funcional con detectores Python ──────────────


class TestFunctionalEquivalence:
    """Los 4 gates migrados a YAML deben producir el MISMO resultado que
    los detectores Python originales (regresión cero)."""

    def test_prior_arpi_exposure_mhspc_yaml_matches_python(self):
        from prostanet.shared.pivotal_contraindication_gates import (
            detect_prior_arpi_exposure_mhspc,
        )
        payload = {"prior_arpi_exposure_mhspc": "Sí"}
        py_result = detect_prior_arpi_exposure_mhspc(payload)
        yaml_results = evaluate_all_yaml_gates(payload)
        yaml_result = next(
            (g for g in yaml_results if g["code"] == "prior_arpi_exposure_mhspc"), None
        )
        assert py_result is not None
        assert yaml_result is not None
        # code, severity, regimen_codes, keywords, trial_refs deben coincidir
        assert yaml_result["code"] == py_result["code"]
        assert yaml_result["severity"] == py_result["severity"]
        assert yaml_result["affected_regimen_codes"] == py_result["affected_regimen_codes"]
        assert set(yaml_result["affected_keywords"]) == set(py_result["affected_keywords"])
        # trial_refs deben coincidir
        assert set(yaml_result["trial_refs"]) == set(py_result["trial_refs"])
        # evidence_tag debe coincidir
        assert yaml_result["evidence_tag"] == py_result["evidence_tag"]

    def test_uncontrolled_hypertension_yaml_matches_python(self):
        from prostanet.shared.pivotal_contraindication_gates import (
            detect_uncontrolled_hypertension,
        )
        payload = {"uncontrolled_hypertension": "Sí"}
        py_result = detect_uncontrolled_hypertension(payload)
        yaml_results = evaluate_all_yaml_gates(payload)
        yaml_result = next(
            (g for g in yaml_results if g["code"] == "uncontrolled_hypertension"), None
        )
        assert py_result is not None
        assert yaml_result is not None
        assert yaml_result["affected_regimen_codes"] == py_result["affected_regimen_codes"]
        assert set(yaml_result["trial_refs"]) == set(py_result["trial_refs"])
        assert yaml_result["evidence_tag"] == py_result["evidence_tag"]

    def test_uncontrolled_diabetes_yaml_matches_python(self):
        from prostanet.shared.pivotal_contraindication_gates import (
            detect_uncontrolled_diabetes,
        )
        payload = {"uncontrolled_diabetes": "Sí"}
        py_result = detect_uncontrolled_diabetes(payload)
        yaml_results = evaluate_all_yaml_gates(payload)
        yaml_result = next(
            (g for g in yaml_results if g["code"] == "uncontrolled_diabetes"), None
        )
        assert yaml_result is not None
        assert yaml_result["affected_regimen_codes"] == py_result["affected_regimen_codes"]

    def test_darolutamide_hypersensitivity_yaml_matches_python(self):
        from prostanet.shared.pivotal_contraindication_gates import (
            detect_darolutamide_hypersensitivity,
        )
        payload = {"darolutamide_hypersensitivity": "Sí"}
        py_result = detect_darolutamide_hypersensitivity(payload)
        yaml_results = evaluate_all_yaml_gates(payload)
        yaml_result = next(
            (g for g in yaml_results if g["code"] == "darolutamide_hypersensitivity"), None
        )
        assert yaml_result is not None
        assert yaml_result["affected_regimen_codes"] == py_result["affected_regimen_codes"]

    def test_yaml_alias_uncontrolled_diabetes_works(self):
        """uncontrolled_diabetes YAML acepta alias `diabetes_uncontrolled`."""
        results = evaluate_all_yaml_gates({"diabetes_uncontrolled": "1"})
        codes = {g["code"] for g in results}
        assert "uncontrolled_diabetes" in codes

    def test_no_yaml_gate_triggers_when_payload_irrelevant(self):
        """Payload sin campos relevantes → 0 YAML gates triggered."""
        results = evaluate_all_yaml_gates({"irrelevant_field": "abc"})
        assert results == []


# ── Sección G — Deduplicación YAML + Python ───────────────────────────────


class TestDeduplication:
    def test_yaml_gate_does_not_duplicate_with_python(self):
        """uncontrolled_hypertension dispara via YAML; el detector Python
        del mismo gate NO debe duplicar el resultado."""
        gates = evaluate_pivotal_contraindication_gates({"uncontrolled_hypertension": "Sí"})
        codes = [g["code"] for g in gates]
        # Sin duplicados
        assert len(codes) == len(set(codes))
        # uncontrolled_hypertension debe aparecer exactamente UNA vez
        assert codes.count("uncontrolled_hypertension") == 1

    def test_yaml_only_gates_appear(self):
        """Gates migrados a YAML aparecen vía YAML loader."""
        gates = evaluate_pivotal_contraindication_gates({"prior_arpi_exposure_mhspc": "Sí"})
        codes = [g["code"] for g in gates]
        assert "prior_arpi_exposure_mhspc" in codes

    def test_python_only_gates_still_work(self):
        """Gates NO migrados (e.g., severe_neuropathy_grade3) siguen
        funcionando vía Python."""
        gates = evaluate_pivotal_contraindication_gates({"peripheral_neuropathy_grade": 4})
        codes = [g["code"] for g in gates]
        assert "severe_neuropathy_grade3" in codes

    def test_mixed_yaml_and_python_payload(self):
        """Payload que dispara 2 YAML + 1 Python gates → 3 gates total
        sin duplicados."""
        gates = evaluate_pivotal_contraindication_gates({
            "uncontrolled_hypertension": "Sí",      # YAML
            "uncontrolled_diabetes": "Sí",          # YAML
            "peripheral_neuropathy_grade": 4,       # Python
        })
        codes = [g["code"] for g in gates]
        assert len(codes) == len(set(codes))
        assert "uncontrolled_hypertension" in codes
        assert "uncontrolled_diabetes" in codes
        assert "severe_neuropathy_grade3" in codes


# ── Sección H — Per-gate SHA + algorithm_version extendido ────────────────


class TestPerGateSha:
    def test_get_yaml_gate_sha_returns_12_chars(self):
        sha = get_yaml_gate_sha("prior_arpi_exposure_mhspc")
        assert sha is not None
        assert len(sha) == 12
        assert all(c in "0123456789abcdef" for c in sha)

    def test_get_yaml_gate_sha_returns_none_for_unknown(self):
        assert get_yaml_gate_sha("nonexistent_gate_xyz") is None

    def test_get_all_yaml_gate_shas_includes_4_pilot(self):
        shas = get_all_yaml_gate_shas()
        assert "prior_arpi_exposure_mhspc" in shas
        assert "uncontrolled_hypertension" in shas
        assert "uncontrolled_diabetes" in shas
        assert "darolutamide_hypersensitivity" in shas
        # Cada SHA es de 12 chars
        for sha in shas.values():
            assert len(sha) == 12

    def test_per_gate_shas_in_algorithm_version(self):
        v = get_algorithm_version()
        assert "yaml_loaded_gates_count" in v
        assert "yaml_loaded_gate_codes" in v
        assert "per_gate_yaml_shas" in v
        assert v["yaml_loaded_gates_count"] >= 4
        assert "prior_arpi_exposure_mhspc" in v["yaml_loaded_gate_codes"]
        assert len(v["per_gate_yaml_shas"]) == v["yaml_loaded_gates_count"]


# ── Sección I — Smoke E2E ─────────────────────────────────────────────────


class TestSmokeE2E:
    def test_paciente_con_3_yaml_gates_simultaneous(self):
        """Paciente con 3 condiciones simultáneas → 3 gates triggered."""
        gates = evaluate_pivotal_contraindication_gates({
            "uncontrolled_hypertension": "Sí",
            "uncontrolled_diabetes": "Sí",
            "darolutamide_hypersensitivity": "Sí",
        })
        codes = {g["code"] for g in gates}
        assert "uncontrolled_hypertension" in codes
        assert "uncontrolled_diabetes" in codes
        assert "darolutamide_hypersensitivity" in codes

    def test_total_gates_count_at_least_19(self):
        """El sistema híbrido total expone ≥19 gates (Python+YAML únicos).

        Faubot 2026-04-25 (XIX) cierra la migración a YAML: gate 9 también
        migrado, los detectores Python bajaron a 12, los YAMLs subieron a 19.
        Faubot 2026-04-25 (XXVI) #38: +4 nuevos YAML-native (gates 20-23) → 23.

        Convención `>=` per CLAUDE.md §8.4 (forward-compat con futuros gates).
        """
        from prostanet.shared.pivotal_contraindication_gates import _DETECTORS
        # Detectores Python ahora son 12 (6 migrados a YAML)
        assert len(_DETECTORS) >= 12
        # El total de gates activos (Python + YAML, deduplicado) debe ser ≥19
        all_active = set(get_active_gate_codes_from_module())
        assert len(all_active) >= 19

    def test_algorithm_version_reflects_yaml_migration(self):
        v = get_algorithm_version()
        # Faubot 2026-04-25 (XIV) — release bumped to XIV after gate 19;
        # accept any 2026-04-25 release.
        # Faubot LXXXI #audit-pre-cortana — accept 2026-04-2X.
        # Faubot Iteración C (2026-05-15) — forward-compat para futuros años:
        # accept 2026-* y posteriores. El formato canónico sigue siendo
        # "YYYY-MM-DD ROMAN_NUMERAL".
        assert v["faubot_release"].startswith("2026-")
        assert v["yaml_loaded_gates_count"] >= 4

    def test_module_registry_smoke_with_yaml_gates(self):
        """End-to-end: m1_crpc service ejecuta correctamente con YAML gates."""
        from prostanet.application.module_registry import ModuleRegistry
        r = ModuleRegistry()
        result = r.evaluate_module("m1_crpc", {
            "psa": 30, "psa_doubling_time": 4, "metastatic": "1",
            "visceral_metastasis": "0", "bone_lesion_count": 4,
            "ecog_score": 1, "age": 70,
            "castrate_resistant": "1", "testosterone": 20,
            "uncontrolled_hypertension": "Sí",  # → YAML gate dispara
        })
        gates = result.get("pivotal_contraindication_gates") or []
        codes = {g["code"] for g in gates}
        assert "uncontrolled_hypertension" in codes


# Helper para test específico
def get_active_gate_codes_from_module() -> list[str]:
    """Helper que reusa la introspección dinámica de algorithm_version."""
    from prostanet.shared.algorithm_version import get_active_gate_codes
    return get_active_gate_codes()
