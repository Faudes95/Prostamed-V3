"""Tests del Gate 19 — ARSI × deterioro cognitivo grado ≥2.

Faubot 2026-04-25 (XIV) — Tier 4.G del backlog. **Primer gate
YAML-NATIVE** del catálogo: diseñado directamente como YAML
declarativo SIN pasar por Python primero. Demuestra que el loader
es suficientemente expresivo para añadir gates clínicos nuevos sin
tocar código.

Aporta a:
  - **POR QUÉ** (99% → ~99.5%): categoría neurológica nueva al catálogo
  - **EVIDENCIA** preserva 100%

Cobertura del test:
  A) Gate 19 cargado correctamente como YAML-native
  B) Triggers individuales (CTCAE grade, MMSE delta, MoCA delta, flag)
  C) Override (cognitive_recovered_for_arpi)
  D) REGIMEN_CODES_ARSI cubre 9 regímenes (3 ARSI × variantes)
  E) FieldSpecs cognitivos nuevos en advanced_cardio_fields
  F) Smoke E2E con ModuleRegistry m1_crpc + paciente con cognitive decline
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest

from prostanet.shared.pivotal_contraindication_gates import (
    KEYWORDS_ARSI,
    REGIMEN_CODES_ARSI,
    evaluate_pivotal_contraindication_gates,
)
from prostanet.shared.pivotal_gates_yaml_loader import (
    evaluate_all_yaml_gates,
    evaluate_yaml_gate,
    get_loaded_yaml_codes,
    reset_yaml_cache,
)


# Bridge — apply helper viene del módulo Python pero también lo hago
# importable aquí desde el loader si se usa en otros tests.
def apply_gates_via_python(payload, treatments):
    """Helper para usar el filtro Python directamente con un payload."""
    from prostanet.shared.pivotal_contraindication_gates import (
        apply_pivotal_contraindication_gates,
    )
    return apply_pivotal_contraindication_gates(payload, treatments)


# ── Sección A — Gate 19 cargado ────────────────────────────────────────────


class TestGate19Loaded:
    def setup_method(self):
        reset_yaml_cache()

    def test_gate_19_in_yaml_codes(self):
        codes = get_loaded_yaml_codes()
        assert "arsi_in_cognitive_decline_grade2" in codes

    def test_total_yamls_at_least_13(self):
        """Faubot 2026-04-25 (XVIII) — Tras la migración de gates 11-15 a YAML,
        el conteo de YAMLs cargados pasó de 13 a 18. Mantenemos `>=13` como
        guard contra regresión hacia abajo (el catálogo solo crece)."""
        codes = get_loaded_yaml_codes()
        assert len(codes) >= 13

    def test_gate_19_yaml_native_metadata(self):
        """Verifica el metadata `faubot_yaml_native: true` (primer YAML-native)."""
        from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files
        configs = _load_yaml_files()
        gate_19 = configs.get("arsi_in_cognitive_decline_grade2")
        assert gate_19 is not None
        assert gate_19.get("faubot_yaml_native") is True


# ── Sección B — Triggers individuales ─────────────────────────────────────


class TestGate19Triggers:
    def setup_method(self):
        reset_yaml_cache()

    @pytest.mark.parametrize(
        "grade,should_trigger",
        [(0, False), (1, False), (2, True), (3, True), (4, True), (5, True)],
    )
    def test_ctcae_grade_threshold(self, grade, should_trigger):
        results = evaluate_all_yaml_gates({"cognitive_disturbance_ctcae_grade": grade})
        codes = [g["code"] for g in results]
        if should_trigger:
            assert "arsi_in_cognitive_decline_grade2" in codes
        else:
            assert "arsi_in_cognitive_decline_grade2" not in codes

    @pytest.mark.parametrize(
        "baseline,current,should_trigger",
        [
            (28, 28, False),  # sin cambio
            (28, 27, False),  # caída 1 — boundary, NO dispara
            (28, 26, True),   # caída 2 — dispara
            (28, 25, True),   # caída 3
            (30, 24, True),   # caída 6
            (None, 25, False),  # baseline missing
            (28, None, False),  # current missing
        ],
    )
    def test_mmse_baseline_delta(self, baseline, current, should_trigger):
        payload = {}
        if baseline is not None:
            payload["mmse_baseline"] = baseline
        if current is not None:
            payload["mmse_current"] = current
        results = evaluate_all_yaml_gates(payload)
        codes = [g["code"] for g in results]
        if should_trigger:
            assert "arsi_in_cognitive_decline_grade2" in codes
        else:
            assert "arsi_in_cognitive_decline_grade2" not in codes

    @pytest.mark.parametrize(
        "baseline,current,should_trigger",
        [
            (26, 24, True),   # caída 2
            (26, 25, False),  # caída 1, NO dispara
            (26, 26, False),  # sin cambio
            (28, 20, True),   # caída 8
        ],
    )
    def test_moca_baseline_delta(self, baseline, current, should_trigger):
        payload = {"moca_baseline": baseline, "moca_current": current}
        results = evaluate_all_yaml_gates(payload)
        codes = [g["code"] for g in results]
        assert ("arsi_in_cognitive_decline_grade2" in codes) is should_trigger

    def test_explicit_flag_dispara(self):
        results = evaluate_all_yaml_gates(
            {"cognitive_decline_grade2_documented": "Sí"}
        )
        codes = [g["code"] for g in results]
        assert "arsi_in_cognitive_decline_grade2" in codes

    def test_explicit_flag_alias_dispara(self):
        results = evaluate_all_yaml_gates(
            {"cognitive_decline_documented": "Sí"}
        )
        codes = [g["code"] for g in results]
        assert "arsi_in_cognitive_decline_grade2" in codes

    def test_no_cognitive_data_no_dispara(self):
        results = evaluate_all_yaml_gates({"psa": 30})
        codes = [g["code"] for g in results]
        assert "arsi_in_cognitive_decline_grade2" not in codes


# ── Sección C — Override ──────────────────────────────────────────────────


class TestGate19Override:
    def test_override_neutralizes_ctcae_trigger(self):
        results = evaluate_all_yaml_gates({
            "cognitive_disturbance_ctcae_grade": 3,
            "cognitive_recovered_for_arpi": "Sí",
        })
        codes = [g["code"] for g in results]
        assert "arsi_in_cognitive_decline_grade2" not in codes

    def test_override_neutralizes_mmse_delta(self):
        results = evaluate_all_yaml_gates({
            "mmse_baseline": 28, "mmse_current": 25,
            "cognitive_recovered_for_arpi": "Sí",
        })
        codes = [g["code"] for g in results]
        assert "arsi_in_cognitive_decline_grade2" not in codes

    def test_override_no_negativo_no_neutraliza(self):
        results = evaluate_all_yaml_gates({
            "cognitive_disturbance_ctcae_grade": 3,
            "cognitive_recovered_for_arpi": "No",
        })
        codes = [g["code"] for g in results]
        assert "arsi_in_cognitive_decline_grade2" in codes


# ── Sección D — REGIMEN_CODES_ARSI ─────────────────────────────────────────


class TestRegimenCodesArsi:
    def test_arsi_combines_3_classes(self):
        from prostanet.shared.pivotal_contraindication_gates import (
            REGIMEN_CODES_ENZALUTAMIDE,
            REGIMEN_CODES_APALUTAMIDE,
            REGIMEN_CODES_DAROLUTAMIDE,
        )
        # ARSI = unión de los 3
        assert REGIMEN_CODES_ENZALUTAMIDE.issubset(REGIMEN_CODES_ARSI)
        assert REGIMEN_CODES_APALUTAMIDE.issubset(REGIMEN_CODES_ARSI)
        assert REGIMEN_CODES_DAROLUTAMIDE.issubset(REGIMEN_CODES_ARSI)

    def test_arsi_has_9_codes(self):
        # 4 enzalutamida + 2 apalutamida + 3 darolutamida = 9
        assert len(REGIMEN_CODES_ARSI) == 9

    def test_arsi_keywords_combine_all(self):
        from prostanet.shared.pivotal_contraindication_gates import (
            KEYWORDS_ENZALUTAMIDE,
            KEYWORDS_APALUTAMIDE,
            KEYWORDS_DAROLUTAMIDE,
        )
        for kw in KEYWORDS_ENZALUTAMIDE:
            assert kw in KEYWORDS_ARSI
        for kw in KEYWORDS_APALUTAMIDE:
            assert kw in KEYWORDS_ARSI
        for kw in KEYWORDS_DAROLUTAMIDE:
            assert kw in KEYWORDS_ARSI

    @pytest.mark.parametrize("regimen_code", sorted(REGIMEN_CODES_ARSI))
    def test_each_arsi_code_blocked_by_gate19(self, regimen_code):
        """Cada código canónico ARSI debe ser bloqueado por gate 19."""
        from prostanet.shared.pivotal_contraindication_gates import (
            apply_pivotal_contraindication_gates,
        )
        treatments = [{"name": "Foo", "regimen_code": regimen_code}]
        bundle = apply_pivotal_contraindication_gates(
            {"cognitive_disturbance_ctcae_grade": 3}, treatments
        )
        assert bundle["filtered_treatments"] == [], \
            f"Régimen {regimen_code} debería ser bloqueado por gate 19"


# ── Sección E — FieldSpecs cognitivos nuevos ──────────────────────────────


class TestNewFieldSpecs:
    def test_cognitive_disturbance_ctcae_grade_field_exists(self):
        from prostanet.shared.advanced_support_fields import advanced_cardio_fields
        fields = advanced_cardio_fields()
        codes = {f.name for f in fields}
        assert "cognitive_disturbance_ctcae_grade" in codes

    def test_mmse_fields_exist(self):
        from prostanet.shared.advanced_support_fields import advanced_cardio_fields
        fields = advanced_cardio_fields()
        codes = {f.name for f in fields}
        assert "mmse_baseline" in codes
        assert "mmse_current" in codes

    def test_moca_fields_exist(self):
        from prostanet.shared.advanced_support_fields import advanced_cardio_fields
        fields = advanced_cardio_fields()
        codes = {f.name for f in fields}
        assert "moca_baseline" in codes
        assert "moca_current" in codes

    def test_cognitive_recovered_override_field_exists(self):
        from prostanet.shared.advanced_support_fields import advanced_cardio_fields
        fields = advanced_cardio_fields()
        codes = {f.name for f in fields}
        assert "cognitive_recovered_for_arpi" in codes


# ── Sección F — Smoke E2E ─────────────────────────────────────────────────


class TestSmokeE2E:
    def test_module_registry_e2e_with_gate_19(self):
        """End-to-end: paciente m1_crpc con MMSE delta ≥2 → gate 19 dispara
        en el resultado del módulo."""
        from prostanet.application.module_registry import ModuleRegistry
        r = ModuleRegistry()
        result = r.evaluate_module("m1_crpc", {
            "psa": 30, "psa_doubling_time": 4, "metastatic": "1",
            "visceral_metastasis": "0", "bone_lesion_count": 4,
            "ecog_score": 1, "age": 82,  # mayor de 80
            "castrate_resistant": "1", "testosterone": 20,
            "mmse_baseline": 28,
            "mmse_current": 25,  # caída 3
        })
        gates = result.get("pivotal_contraindication_gates") or []
        codes = {g["code"] for g in gates}
        assert "arsi_in_cognitive_decline_grade2" in codes

    def test_e2e_with_ctcae_grade_2(self):
        from prostanet.application.module_registry import ModuleRegistry
        r = ModuleRegistry()
        result = r.evaluate_module("m1_crpc", {
            "psa": 30, "psa_doubling_time": 4, "metastatic": "1",
            "visceral_metastasis": "0", "bone_lesion_count": 4,
            "ecog_score": 1, "age": 85,
            "castrate_resistant": "1", "testosterone": 20,
            "cognitive_disturbance_ctcae_grade": 2,
        })
        gates = result.get("pivotal_contraindication_gates") or []
        codes = {g["code"] for g in gates}
        assert "arsi_in_cognitive_decline_grade2" in codes

    def test_e2e_recovered_does_not_trigger(self):
        from prostanet.application.module_registry import ModuleRegistry
        r = ModuleRegistry()
        result = r.evaluate_module("m1_crpc", {
            "psa": 30, "psa_doubling_time": 4, "metastatic": "1",
            "visceral_metastasis": "0", "bone_lesion_count": 4,
            "ecog_score": 1, "age": 82,
            "castrate_resistant": "1", "testosterone": 20,
            "cognitive_disturbance_ctcae_grade": 3,
            "cognitive_recovered_for_arpi": "Sí",
        })
        gates = result.get("pivotal_contraindication_gates") or []
        codes = {g["code"] for g in gates}
        assert "arsi_in_cognitive_decline_grade2" not in codes


# ── Sección G — Cobertura clínica ─────────────────────────────────────────


class TestClinicalCoverage:
    def test_evidence_tag_cites_ucsf_and_siog(self):
        results = evaluate_all_yaml_gates(
            {"cognitive_disturbance_ctcae_grade": 3}
        )
        gate = next(
            (g for g in results if g["code"] == "arsi_in_cognitive_decline_grade2"),
            None,
        )
        assert gate is not None
        assert "ucsf" in gate["evidence_tag"].lower()
        assert "siog" in gate["evidence_tag"].lower()

    def test_trial_refs_includes_ucsf_and_siog(self):
        results = evaluate_all_yaml_gates(
            {"cognitive_disturbance_ctcae_grade": 3}
        )
        gate = next(
            (g for g in results if g["code"] == "arsi_in_cognitive_decline_grade2"),
            None,
        )
        refs_str = " ".join(gate["trial_refs"]).lower()
        assert "ucsf" in refs_str
        assert "siog" in refs_str

    def test_message_includes_clinical_protocol(self):
        results = evaluate_all_yaml_gates(
            {"cognitive_disturbance_ctcae_grade": 3}
        )
        gate = next(
            (g for g in results if g["code"] == "arsi_in_cognitive_decline_grade2"),
            None,
        )
        msg = gate["message"].lower()
        assert "suspender arsi" in msg or "suspender" in msg
        assert "neurológica" in msg or "neurologica" in msg
        assert "darolutamida" in msg
        assert "cognitive_recovered_for_arpi" in msg
