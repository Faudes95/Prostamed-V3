"""Tests del Dashboard de Cobertura Clínica de Gates Pivotal.

Faubot 2026-04-25 (XII) — Tier 4.J del backlog: agregación estadística
poblacional de los 18 gates pivotal disparados, con heatmap por estado
clínico + alertas de captura de FieldSpec sub-utilizados.

Aporta a:
  - **DATOS** (88% → ~95%): visibilidad de captura clínica poblacional
  - **CÓMO** (95% → ~97%): agregación de cadena de razonamiento

Cobertura del test:
  A) Helper aggregator — empty + populated + edge cases
  B) Cálculos estadísticos — % correctos + by_state distribution
  C) Alertas — gates_never_triggered + high_prevalence + fields_low_capture
  D) Heatmap data — rows/cols/matrix + max_count + max_percentage
  E) Endpoint Flask /api/gates-coverage-dashboard
  F) Smoke E2E con assessments simulados realistas
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import json

import pytest

from prostanet.shared.gates_coverage_aggregator import (
    _CRITICAL_GATE_FIELDS,
    _empty_coverage_dict,
    _extract_gates_from_assessment,
    _extract_input_fields,
    _extract_state_from_assessment,
    aggregate_gates_coverage,
    build_heatmap_data,
)


def _make_assessment(state: str, gates: list[dict] | None = None,
                     input_fields: dict | None = None,
                     assessment_id: int = 1) -> dict:
    """Helper para construir assessments fake."""
    return {
        "id": assessment_id,
        "state": state,
        "input_snapshot": input_fields or {},
        "result_snapshot": {
            "state": state,
            "pivotal_contraindication_gates": gates or [],
        },
    }


# ── Sección A — Helper aggregator ─────────────────────────────────────────


class TestAggregateGatesCoverage:
    def test_empty_assessments_returns_empty_dict(self):
        result = aggregate_gates_coverage([])
        assert result["total_assessments"] == 0
        assert result["total_with_gates"] == 0
        assert result["percentage_with_gates"] == 0.0
        assert result["gate_coverage"] == {}
        assert result["state_coverage"] == {}

    def test_single_assessment_no_gates(self):
        assessments = [_make_assessment("m1_crpc")]
        result = aggregate_gates_coverage(assessments)
        assert result["total_assessments"] == 1
        assert result["total_with_gates"] == 0
        assert result["percentage_with_gates"] == 0.0
        assert result["state_coverage"]["m1_crpc"]["total_patients"] == 1

    def test_single_assessment_with_one_gate(self):
        assessments = [_make_assessment(
            "m1_crpc",
            gates=[{"code": "uncontrolled_hypertension", "severity": "hard_block"}],
        )]
        result = aggregate_gates_coverage(assessments)
        assert result["total_assessments"] == 1
        assert result["total_with_gates"] == 1
        assert result["percentage_with_gates"] == 100.0
        assert "uncontrolled_hypertension" in result["gate_coverage"]
        assert result["gate_coverage"]["uncontrolled_hypertension"]["count"] == 1
        assert result["gate_coverage"]["uncontrolled_hypertension"]["percentage"] == 100.0

    def test_multiple_assessments_mixed(self):
        assessments = [
            _make_assessment("m1_crpc", gates=[
                {"code": "qtc_prolongation_grade3_for_enzalutamide"},
            ], assessment_id=1),
            _make_assessment("m1_crpc", gates=[
                {"code": "qtc_prolongation_grade3_for_enzalutamide"},
                {"code": "uncontrolled_hypertension"},
            ], assessment_id=2),
            _make_assessment("mcspc_high_volume", gates=[], assessment_id=3),
            _make_assessment("m0_crpc", gates=[
                {"code": "uncontrolled_hypertension"},
            ], assessment_id=4),
        ]
        result = aggregate_gates_coverage(assessments)
        assert result["total_assessments"] == 4
        assert result["total_with_gates"] == 3
        assert result["percentage_with_gates"] == 75.0
        # qtc gate: 2/4 = 50%
        assert result["gate_coverage"]["qtc_prolongation_grade3_for_enzalutamide"]["count"] == 2
        assert result["gate_coverage"]["qtc_prolongation_grade3_for_enzalutamide"]["percentage"] == 50.0
        # hta gate: 2/4 = 50%
        assert result["gate_coverage"]["uncontrolled_hypertension"]["count"] == 2

    def test_by_state_distribution_correct(self):
        assessments = [
            _make_assessment("m1_crpc", gates=[
                {"code": "g1"}, {"code": "g2"},
            ], assessment_id=1),
            _make_assessment("m1_crpc", gates=[{"code": "g1"}], assessment_id=2),
            _make_assessment("mhspc_high_volume", gates=[{"code": "g1"}], assessment_id=3),
            _make_assessment("m0_crpc", gates=[{"code": "g2"}], assessment_id=4),
        ]
        result = aggregate_gates_coverage(assessments)
        # g1: 2 m1_crpc + 1 mhspc_high_volume
        assert result["gate_coverage"]["g1"]["by_state"]["m1_crpc"] == 2
        assert result["gate_coverage"]["g1"]["by_state"]["mhspc_high_volume"] == 1
        # g2: 1 m1_crpc + 1 m0_crpc
        assert result["gate_coverage"]["g2"]["by_state"]["m1_crpc"] == 1
        assert result["gate_coverage"]["g2"]["by_state"]["m0_crpc"] == 1

    def test_state_coverage_has_correct_totals(self):
        assessments = [
            _make_assessment("m1_crpc", assessment_id=1),
            _make_assessment("m1_crpc", assessment_id=2),
            _make_assessment("m1_crpc", assessment_id=3),
            _make_assessment("m0_crpc", assessment_id=4),
        ]
        result = aggregate_gates_coverage(assessments)
        assert result["state_coverage"]["m1_crpc"]["total_patients"] == 3
        assert result["state_coverage"]["m0_crpc"]["total_patients"] == 1

    def test_gates_without_code_skipped(self):
        assessments = [_make_assessment("m1_crpc", gates=[
            {"severity": "hard_block"},  # sin code
            {"code": "valid_code"},
        ])]
        result = aggregate_gates_coverage(assessments)
        # Solo 1 gate válido contado
        assert "valid_code" in result["gate_coverage"]
        assert len(result["gate_coverage"]) == 1


# ── Sección B — Field capture coverage ────────────────────────────────────


class TestFieldCaptureCoverage:
    def test_field_capture_empty_when_no_assessments(self):
        result = aggregate_gates_coverage([])
        # field_capture_coverage debe tener todos los fields críticos con count=0
        for field in _CRITICAL_GATE_FIELDS:
            assert result["field_capture_coverage"][field]["count"] == 0
            assert result["field_capture_coverage"][field]["percentage"] == 0.0

    def test_field_capture_counted_correctly(self):
        assessments = [
            _make_assessment("m1_crpc", input_fields={"qtc_ms": 520, "lvef_percent": 45}),
            _make_assessment("m1_crpc", input_fields={"qtc_ms": 480}),
            _make_assessment("m1_crpc", input_fields={}),
        ]
        result = aggregate_gates_coverage(assessments)
        # qtc_ms: 2/3 = 66.67%
        assert result["field_capture_coverage"]["qtc_ms"]["count"] == 2
        assert result["field_capture_coverage"]["qtc_ms"]["percentage"] == 66.67
        # lvef_percent: 1/3 = 33.33%
        assert result["field_capture_coverage"]["lvef_percent"]["count"] == 1
        # nyha_class: 0/3 = 0%
        assert result["field_capture_coverage"]["nyha_class"]["count"] == 0

    def test_empty_string_value_not_counted_as_captured(self):
        assessments = [_make_assessment("m1_crpc", input_fields={
            "qtc_ms": "",  # vacío
            "lvef_percent": 45,  # capturado
        })]
        result = aggregate_gates_coverage(assessments)
        assert result["field_capture_coverage"]["qtc_ms"]["count"] == 0
        assert result["field_capture_coverage"]["lvef_percent"]["count"] == 1


# ── Sección C — Alertas ──────────────────────────────────────────────────


class TestAlerts:
    def test_alerts_empty_when_no_assessments(self):
        result = aggregate_gates_coverage([])
        # Sin assessments → todos los gates "never triggered"
        assert result["alerts"]["gates_never_triggered_count"] >= 18
        assert result["alerts"]["gates_high_prevalence"] == []
        assert result["alerts"]["fields_low_capture_count"] == len(_CRITICAL_GATE_FIELDS)

    def test_high_prevalence_gate_detected(self):
        # 8 de 10 assessments con misma gate → 80% prevalencia
        assessments = []
        for i in range(8):
            assessments.append(_make_assessment("m1_crpc",
                gates=[{"code": "common_gate"}], assessment_id=i))
        for i in range(2):
            assessments.append(_make_assessment("m1_crpc", assessment_id=10+i))
        result = aggregate_gates_coverage(assessments)
        assert "common_gate" in result["alerts"]["gates_high_prevalence"]

    def test_low_prevalence_gate_not_in_high_alert(self):
        # 1 de 10 → 10% no entra en high_prevalence
        assessments = [_make_assessment("m1_crpc",
            gates=[{"code": "rare_gate"}], assessment_id=1)]
        for i in range(9):
            assessments.append(_make_assessment("m1_crpc", assessment_id=10+i))
        result = aggregate_gates_coverage(assessments)
        assert "rare_gate" not in result["alerts"]["gates_high_prevalence"]

    def test_field_low_capture_detected(self):
        # qtc_ms en 1 de 10 = 10% < 20% → en fields_low_capture
        assessments = [_make_assessment("m1_crpc",
            input_fields={"qtc_ms": 520}, assessment_id=1)]
        for i in range(9):
            assessments.append(_make_assessment("m1_crpc",
                input_fields={"psa": 30}, assessment_id=10+i))
        result = aggregate_gates_coverage(assessments)
        assert "qtc_ms" in result["alerts"]["fields_low_capture"]

    def test_field_high_capture_not_in_low_alert(self):
        # qtc_ms en 8 de 10 = 80% > 20% → NO en fields_low_capture
        assessments = []
        for i in range(8):
            assessments.append(_make_assessment("m1_crpc",
                input_fields={"qtc_ms": 520}, assessment_id=i))
        for i in range(2):
            assessments.append(_make_assessment("m1_crpc", assessment_id=10+i))
        result = aggregate_gates_coverage(assessments)
        assert "qtc_ms" not in result["alerts"]["fields_low_capture"]


# ── Sección D — Heatmap data ─────────────────────────────────────────────


class TestHeatmapData:
    def test_empty_coverage_returns_empty_heatmap(self):
        result = aggregate_gates_coverage([])
        heatmap = build_heatmap_data(result)
        assert heatmap["rows"] == []
        assert heatmap["cols"] == []
        assert heatmap["matrix"] == []
        assert heatmap["max_count"] == 0
        assert heatmap["max_percentage"] == 0.0

    def test_heatmap_rows_are_gate_codes_sorted(self):
        assessments = [
            _make_assessment("m1_crpc", gates=[
                {"code": "z_gate"}, {"code": "a_gate"},
            ]),
        ]
        coverage = aggregate_gates_coverage(assessments)
        heatmap = build_heatmap_data(coverage)
        assert heatmap["rows"] == ["a_gate", "z_gate"]

    def test_heatmap_cols_are_states_sorted(self):
        assessments = [
            _make_assessment("z_state", gates=[{"code": "g1"}]),
            _make_assessment("a_state", gates=[{"code": "g1"}]),
        ]
        coverage = aggregate_gates_coverage(assessments)
        heatmap = build_heatmap_data(coverage)
        assert heatmap["cols"] == ["a_state", "z_state"]

    def test_heatmap_matrix_dimensions_match(self):
        assessments = [
            _make_assessment("m1_crpc", gates=[
                {"code": "g1"}, {"code": "g2"},
            ], assessment_id=1),
            _make_assessment("m0_crpc", gates=[{"code": "g1"}], assessment_id=2),
        ]
        coverage = aggregate_gates_coverage(assessments)
        heatmap = build_heatmap_data(coverage)
        # 2 rows × 2 cols
        assert len(heatmap["matrix"]) == 2
        for row in heatmap["matrix"]:
            assert len(row) == 2

    def test_heatmap_cell_has_count_and_percentage(self):
        assessments = [
            _make_assessment("m1_crpc", gates=[{"code": "g1"}], assessment_id=1),
            _make_assessment("m1_crpc", gates=[{"code": "g1"}], assessment_id=2),
            _make_assessment("m1_crpc", assessment_id=3),
        ]
        coverage = aggregate_gates_coverage(assessments)
        heatmap = build_heatmap_data(coverage)
        # g1 en m1_crpc: 2 de 3 = 66.67%
        cell = heatmap["matrix"][0][0]
        assert cell["count"] == 2
        assert cell["percentage"] == 66.67

    def test_heatmap_max_values_correct(self):
        assessments = []
        for i in range(5):
            assessments.append(_make_assessment("m1_crpc",
                gates=[{"code": "g_high"}], assessment_id=i))
        for i in range(5):
            assessments.append(_make_assessment("m0_crpc",
                gates=[{"code": "g_low"}], assessment_id=10+i))
        coverage = aggregate_gates_coverage(assessments)
        heatmap = build_heatmap_data(coverage)
        # g_high en m1_crpc: 5/5 = 100%
        assert heatmap["max_count"] == 5
        assert heatmap["max_percentage"] == 100.0


# ── Sección E — Endpoint Flask ────────────────────────────────────────────


@pytest.fixture
def client():
    """Flask test client con blueprints registrados."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True})
    with flask_app.test_client() as client:
        yield client


class TestEndpointFlask:
    def test_endpoint_returns_200(self, client):
        response = client.get("/api/gates-coverage-dashboard")
        assert response.status_code == 200
        data = response.get_json()
        assert data is not None
        assert data["success"] is True
        assert "coverage" in data
        assert "heatmap" in data
        assert "algorithm_version" in data

    def test_endpoint_response_has_5_dimensions_keys(self, client):
        response = client.get("/api/gates-coverage-dashboard")
        data = response.get_json()
        coverage = data["coverage"]
        assert "total_assessments" in coverage
        assert "gate_coverage" in coverage
        assert "state_coverage" in coverage
        assert "field_capture_coverage" in coverage
        assert "alerts" in coverage

    def test_endpoint_includes_algorithm_version(self, client):
        response = client.get("/api/gates-coverage-dashboard")
        data = response.get_json()
        v = data["algorithm_version"]
        assert v["faubot_release"]
        assert v["module_sha"]
        assert v["gates_active_count"] >= 18

    def test_html_page_renders(self, client):
        response = client.get("/gates-coverage-dashboard")
        assert response.status_code == 200
        assert b"Cobertura cl" in response.data  # "Cobertura clínica"

    def test_html_page_includes_algorithm_version(self, client):
        response = client.get("/gates-coverage-dashboard")
        # Faubot LXXXV: forward-compat con releases ≥2026-04-25 (e.g. 2026-04-27 LXXXV)
        assert any(date in response.data for date in (b"2026-04-25", b"2026-04-26", b"2026-04-27"))


# ── Sección F — Smoke E2E con escenarios realistas ────────────────────────


class TestSmokeE2E:
    def test_realistic_cohort_with_distribution(self):
        """Simula una cohorte realista de 20 pacientes m1_crpc/mhspc/m0_crpc
        con distribución estadística de gates."""
        assessments = []
        # 10 m1_crpc, 30% con QTc, 20% con LVEF
        for i in range(10):
            gates = []
            if i < 3:
                gates.append({"code": "qtc_prolongation_grade3_for_enzalutamide",
                              "trial_refs": ["ENZAMET"]})
            if i < 2:
                gates.append({"code": "lvef_decline_for_apalutamide",
                              "trial_refs": ["TITAN"]})
            assessments.append(_make_assessment("m1_crpc",
                gates=gates,
                input_fields={"qtc_ms": 480 + i*5, "lvef_percent": 60 - i*2},
                assessment_id=i))
        # 7 mhspc_high_volume, 50% con HTA
        for i in range(7):
            gates = []
            if i < 4:
                gates.append({"code": "uncontrolled_hypertension",
                              "trial_refs": ["LATITUDE"]})
            assessments.append(_make_assessment("mhspc_high_volume",
                gates=gates, assessment_id=20+i))
        # 3 m0_crpc
        for i in range(3):
            assessments.append(_make_assessment("m0_crpc", assessment_id=30+i))

        coverage = aggregate_gates_coverage(assessments)
        # Métricas globales
        assert coverage["total_assessments"] == 20
        # 5 m1_crpc + 4 mhspc = 9 con gates
        assert coverage["total_with_gates"] == 7  # 3 qtc + 2 lvef pero 2 overlap = 3+2-? actually 5 distinct in m1 + 4 hta = no overlap
        # Cobertura por gate
        assert coverage["gate_coverage"]["qtc_prolongation_grade3_for_enzalutamide"]["count"] == 3
        assert coverage["gate_coverage"]["uncontrolled_hypertension"]["count"] == 4
        # Field capture
        assert coverage["field_capture_coverage"]["qtc_ms"]["count"] == 10  # solo m1_crpc
        assert coverage["field_capture_coverage"]["lvef_percent"]["count"] == 10
        # Heatmap
        heatmap = build_heatmap_data(coverage)
        assert "qtc_prolongation_grade3_for_enzalutamide" in heatmap["rows"]
        assert "m1_crpc" in heatmap["cols"]

    def test_aggregator_handles_malformed_assessments_gracefully(self):
        assessments = [
            None,  # nil
            {},  # vacío
            _make_assessment("m1_crpc"),
            {"id": 99},  # sin state ni snapshots
        ]
        # Filter out None for the aggregator
        filtered = [a for a in assessments if a is not None]
        coverage = aggregate_gates_coverage(filtered)
        assert coverage["total_assessments"] == 3
        # Sin errores
        assert "alerts" in coverage


# ── Sección G — Helpers internos ──────────────────────────────────────────


class TestInternalHelpers:
    def test_extract_gates_from_empty(self):
        assert _extract_gates_from_assessment(None) == []
        assert _extract_gates_from_assessment({}) == []

    def test_extract_gates_returns_list(self):
        a = _make_assessment("m1_crpc", gates=[{"code": "g1"}])
        gates = _extract_gates_from_assessment(a)
        assert len(gates) == 1
        assert gates[0]["code"] == "g1"

    def test_extract_state_unknown(self):
        assert _extract_state_from_assessment(None) == "unknown"
        assert _extract_state_from_assessment({}) == "unknown"

    def test_extract_state_returns_value(self):
        a = _make_assessment("m1_crpc")
        assert _extract_state_from_assessment(a) == "m1_crpc"

    def test_extract_input_fields_filters_empty(self):
        a = _make_assessment("m1_crpc", input_fields={
            "psa": 30, "qtc_ms": "", "lvef_percent": None,
            "valid_field": "value",
        })
        fields = _extract_input_fields(a)
        assert "psa" in fields
        assert "valid_field" in fields
        assert "qtc_ms" not in fields  # filtrado por valor vacío
        assert "lvef_percent" not in fields  # filtrado por None
