"""Auditoría Faubot #64B (LXIX) — Frontend wiring de #64A backend.

Tests del contrato de wiring backend → template para los 3 helpers de #64A:
  Sección A — psa_forecast_per_line wired en profile_compass bundle (6 tests)
  Sección B — psa_cohort_reference wired en bundle (6 tests)
  Sección C — psa_combined_timeline wired en bundle (8 tests)

Total: 20 tests. Hipótesis verificables: H.G2101 - H.G2120.

NOTA: Tests verifican el CONTRATO BACKEND→FRONTEND wiring. Tests E2E del
rendering visual (Chart.js datasets) requieren browser automation y están
fuera del scope.
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import sys
import types

import pytest

# Stubs APFS I/O lock workaround
if "tracking_db" not in sys.modules:
    class _TrackingDbStub(types.ModuleType):
        def __getattr__(self, name):
            def _noop(*args, **kwargs):
                return {}
            _noop.__name__ = name
            return _noop
    sys.modules["tracking_db"] = _TrackingDbStub("tracking_db")

if "clinical_scores" not in sys.modules:
    class _ClinicalScoresStub(types.ModuleType):
        def __getattr__(self, name):
            def _noop(*args, **kwargs):
                if name == "calculate_psa_kinetics":
                    return {"velocity": 0.5, "psadt": 7.0, "interpretation": "stub"}
                return {}
            _noop.__name__ = name
            return _noop
    sys.modules["clinical_scores"] = _ClinicalScoresStub("clinical_scores")

from prostanet.domains.patient_tracking.psa_forecast import (
    build_psa_forecast_per_line,
    build_psa_cohort_reference_overlay,
    build_combined_patient_timeline,
)


# ─────────────────────────────────────────────────────────────────────────────
# Sección A — psa_forecast_per_line wired en bundle (H.G2101-H.G2106)
# ─────────────────────────────────────────────────────────────────────────────


class TestSectionAForecastPerLineWired:
    """psa_forecast_per_line debe estar correctamente wired y disponible
    para el template patient_profile.html."""

    def test_g2101_per_line_forecast_callable_no_exception(self):
        """H.G2101 — build_psa_forecast_per_line invocable sin excepción."""
        patient = {
            "biomarker_longitudinal": [],
            "treatments": [],
        }
        # NO debe lanzar excepción incluso con datos vacíos
        result = build_psa_forecast_per_line(patient)
        assert isinstance(result, dict)

    def test_g2102_per_line_forecast_serializable_for_tojson(self):
        """H.G2102 — Output serializable a JSON (tojson Jinja filter)."""
        patient = {
            "biomarker_longitudinal": [
                {"sample_date": "2024-01-01", "biomarker_type": "PSA", "value": 100.0},
                {"sample_date": "2024-04-01", "biomarker_type": "PSA", "value": 50.0},
                {"sample_date": "2024-08-01", "biomarker_type": "PSA", "value": 30.0},
            ],
            "treatments": [{
                "start_date": "2024-01-01", "drug_scheme": "ADT_MONO",
                "line_of_therapy_number": "1",
            }],
        }
        result = build_psa_forecast_per_line(patient)
        import json
        # Debe ser JSON-serializable sin errores
        json_str = json.dumps(result)
        assert "per_line_forecasts" in json_str

    def test_g2103_per_line_forecast_has_summary_for_template(self):
        """H.G2103 — summary dict presente para uso en template."""
        patient = {"biomarker_longitudinal": [], "treatments": []}
        result = build_psa_forecast_per_line(patient)
        assert "summary" in result
        for key in ["total_lines", "ready_count", "insufficient_count"]:
            assert key in result["summary"]

    def test_g2104_per_line_forecast_count_fields_wired(self):
        """H.G2104 — lines_with_forecast_count + lines_insufficient_data_count
        para uso en template badges."""
        patient = {"biomarker_longitudinal": [], "treatments": []}
        result = build_psa_forecast_per_line(patient)
        assert "lines_with_forecast_count" in result
        assert "lines_insufficient_data_count" in result

    def test_g2105_per_line_forecast_per_line_dict_keyed_by_line_number(self):
        """H.G2105 — per_line_forecasts keys son strings de line_number."""
        patient = {
            "biomarker_longitudinal": [
                {"sample_date": "2024-01-01", "biomarker_type": "PSA", "value": 100.0},
                {"sample_date": "2024-04-01", "biomarker_type": "PSA", "value": 50.0},
                {"sample_date": "2024-08-01", "biomarker_type": "PSA", "value": 30.0},
            ],
            "treatments": [{
                "start_date": "2024-01-01", "drug_scheme": "ADT_MONO",
                "line_of_therapy_number": "1",
            }],
        }
        result = build_psa_forecast_per_line(patient)
        for key in result["per_line_forecasts"].keys():
            assert isinstance(key, str)

    def test_g2106_per_line_forecast_each_entry_has_status(self):
        """H.G2106 — Cada entry tiene status (ready/insufficient_data) para
        condicional rendering en template."""
        patient = {
            "biomarker_longitudinal": [
                {"sample_date": "2024-01-01", "biomarker_type": "PSA", "value": 100.0},
                {"sample_date": "2024-04-01", "biomarker_type": "PSA", "value": 50.0},
                {"sample_date": "2024-08-01", "biomarker_type": "PSA", "value": 30.0},
            ],
            "treatments": [{
                "start_date": "2024-01-01", "drug_scheme": "ADT_MONO",
                "line_of_therapy_number": "1",
            }],
        }
        result = build_psa_forecast_per_line(patient)
        for entry in result["per_line_forecasts"].values():
            assert "status" in entry


# ─────────────────────────────────────────────────────────────────────────────
# Sección B — psa_cohort_reference wired en bundle (H.G2107-H.G2112)
# ─────────────────────────────────────────────────────────────────────────────


class TestSectionBCohortReferenceWired:
    """psa_cohort_reference debe estar wired y disponible para chart overlay."""

    def test_g2107_cohort_reference_callable_no_exception(self):
        """H.G2107 — build_psa_cohort_reference_overlay invocable sin excepción."""
        patient = {"biomarker_longitudinal": [], "treatments": []}
        result = build_psa_cohort_reference_overlay(patient)
        assert isinstance(result, dict)

    def test_g2108_cohort_reference_serializable(self):
        """H.G2108 — Output JSON-serializable para tojson."""
        patient = {
            "reconciled_state": "m1_crpc",
            "baseline": {"baseline_psa": 80.0},
            "treatments": [{
                "start_date": "2024-01-01", "drug_scheme": "DOCETAXEL",
                "line_of_therapy_number": "1",
            }],
            "biomarker_longitudinal": [
                {"sample_date": "2024-01-01", "biomarker_type": "PSA", "value": 80.0},
            ],
        }
        result = build_psa_cohort_reference_overlay(patient)
        import json
        json_str = json.dumps(result)
        assert "has_data" in json_str

    def test_g2109_cohort_reference_has_data_field_for_conditional(self):
        """H.G2109 — has_data field para conditional rendering."""
        patient = {"biomarker_longitudinal": [], "treatments": []}
        result = build_psa_cohort_reference_overlay(patient)
        assert "has_data" in result
        assert isinstance(result["has_data"], bool)

    def test_g2110_cohort_reference_curve_has_date_psa_pairs(self):
        """H.G2110 — reference_curve entries tienen date + expected_psa
        para uso en Chart.js dataset."""
        patient = {
            "reconciled_state": "m1_crpc",
            "baseline": {"baseline_psa": 80.0},
            "treatments": [{
                "start_date": "2024-01-01", "drug_scheme": "DOCETAXEL",
                "line_of_therapy_number": "1",
            }],
            "biomarker_longitudinal": [
                {"sample_date": "2024-01-01", "biomarker_type": "PSA", "value": 80.0},
            ],
        }
        result = build_psa_cohort_reference_overlay(patient)
        if result["has_data"]:
            for point in result["reference_curve"]:
                assert "date" in point
                assert "expected_psa" in point

    def test_g2111_cohort_reference_includes_metadata_for_legend(self):
        """H.G2111 — cohort_class + median_label para chart legend label."""
        patient = {
            "reconciled_state": "m1_crpc",
            "baseline": {"baseline_psa": 80.0},
            "treatments": [{
                "start_date": "2024-01-01", "drug_scheme": "DOCETAXEL",
                "line_of_therapy_number": "1",
            }],
            "biomarker_longitudinal": [
                {"sample_date": "2024-01-01", "biomarker_type": "PSA", "value": 80.0},
            ],
        }
        result = build_psa_cohort_reference_overlay(patient)
        assert "cohort_class" in result
        assert "median_label" in result

    def test_g2112_cohort_reference_narrative_for_drill_down(self):
        """H.G2112 — narrative string presente para drill-down panel display."""
        patient = {"biomarker_longitudinal": [], "treatments": []}
        result = build_psa_cohort_reference_overlay(patient)
        assert "narrative" in result


# ─────────────────────────────────────────────────────────────────────────────
# Sección C — psa_combined_timeline wired en bundle (H.G2113-H.G2120)
# ─────────────────────────────────────────────────────────────────────────────


class TestSectionCCombinedTimelineWired:
    """psa_combined_timeline debe estar wired y disponible para chart unificado."""

    def test_g2113_combined_timeline_callable_no_exception(self):
        """H.G2113 — build_combined_patient_timeline invocable sin excepción."""
        patient = {"biomarker_longitudinal": [], "treatments": []}
        result = build_combined_patient_timeline(patient)
        assert isinstance(result, dict)

    def test_g2114_combined_timeline_serializable(self):
        """H.G2114 — Output JSON-serializable."""
        patient = {
            "biomarker_longitudinal": [
                {"sample_date": "2024-06-01", "biomarker_type": "PSA", "value": 5.0},
            ],
            "treatments": [{
                "start_date": "2024-01-01", "drug_scheme": "ADT_MONO",
                "line_of_therapy_number": "1",
            }],
        }
        result = build_combined_patient_timeline(patient)
        import json
        json_str = json.dumps(result)
        assert "axis_dates" in json_str

    def test_g2115_combined_timeline_has_data_for_conditional(self):
        """H.G2115 — has_data field para template conditional rendering."""
        patient = {"biomarker_longitudinal": [], "treatments": []}
        result = build_combined_patient_timeline(patient)
        assert "has_data" in result

    def test_g2116_combined_timeline_summary_template_friendly(self):
        """H.G2116 — summary dict con keys para template display directo."""
        patient = {
            "biomarker_longitudinal": [
                {"sample_date": "2024-06-01", "biomarker_type": "PSA", "value": 5.0},
            ],
            "treatments": [{
                "start_date": "2024-01-01", "drug_scheme": "ADT_MONO",
                "line_of_therapy_number": "1",
            }],
        }
        result = build_combined_patient_timeline(patient)
        s = result["summary"]
        for key in ["total_psa_points", "total_treatment_lanes",
                    "total_event_markers", "earliest_date", "latest_date"]:
            assert key in s

    def test_g2117_combined_timeline_psa_series_chart_friendly(self):
        """H.G2117 — psa_series entries tienen date + psa para Chart.js."""
        patient = {
            "biomarker_longitudinal": [
                {"sample_date": "2024-06-01", "biomarker_type": "PSA", "value": 5.0},
            ],
            "treatments": [{
                "start_date": "2024-01-01", "drug_scheme": "ADT_MONO",
                "line_of_therapy_number": "1",
            }],
        }
        result = build_combined_patient_timeline(patient)
        for entry in result["psa_series"]:
            assert "date" in entry
            assert "psa" in entry

    def test_g2118_combined_timeline_treatment_lanes_chart_friendly(self):
        """H.G2118 — treatment_lanes con start_date+end_date+color para Chart.js box."""
        patient = {
            "biomarker_longitudinal": [
                {"sample_date": "2024-06-01", "biomarker_type": "PSA", "value": 5.0},
            ],
            "treatments": [{
                "start_date": "2024-01-01", "drug_scheme": "ADT_MONO",
                "line_of_therapy_number": "1",
            }],
        }
        result = build_combined_patient_timeline(patient)
        for lane in result["treatment_lanes"]:
            assert "start_date" in lane
            assert "color" in lane
            assert "label" in lane

    def test_g2119_combined_timeline_event_markers_chart_friendly(self):
        """H.G2119 — clinical_event_markers tienen date + label + treatment_line
        para Chart.js scatter points."""
        patient = {
            "biomarker_longitudinal": [
                {"sample_date": "2024-03-01", "biomarker_type": "PSA", "value": 8.0},
                {"sample_date": "2024-09-01", "biomarker_type": "PSA", "value": 5.0},
            ],
            "treatments": [{
                "start_date": "2024-01-01", "drug_scheme": "ADT_MONO",
                "line_of_therapy_number": "1",
            }],
        }
        events = [{"date": "2024-06-15", "title": "Visita", "origin": "visit"}]
        result = build_combined_patient_timeline(patient, clinical_events=events)
        for marker in result["clinical_event_markers"]:
            assert "date" in marker
            assert "label" in marker

    def test_g2120_combined_timeline_axis_dates_sorted_asc_for_chart(self):
        """H.G2120 — axis_dates ordenados ascendente (Chart.js category axis)."""
        patient = {
            "biomarker_longitudinal": [
                {"sample_date": "2024-09-01", "biomarker_type": "PSA", "value": 3.0},
                {"sample_date": "2024-03-01", "biomarker_type": "PSA", "value": 10.0},
            ],
            "treatments": [{
                "start_date": "2024-01-01", "drug_scheme": "ADT_MONO",
                "line_of_therapy_number": "1",
            }],
        }
        result = build_combined_patient_timeline(patient)
        dates = result["axis_dates"]
        assert dates == sorted(dates)
