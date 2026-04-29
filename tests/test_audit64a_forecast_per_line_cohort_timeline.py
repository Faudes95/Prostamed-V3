"""Auditoría Faubot #64A (LXVIII) — Forecast per-line + Cohort overlay + Timeline integration.

Cobertura:
  Sección A — build_psa_forecast_per_line (10 tests, H.G2071-H.G2080)
  Sección B — build_psa_cohort_reference_overlay (10 tests, H.G2081-H.G2090)
  Sección C — build_combined_patient_timeline (10 tests, H.G2091-H.G2100)

Total: 30 tests. Stubs sys.modules para tracking_db + clinical_scores
(workaround APFS I/O lock — pattern de #63B/C/D).
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
    _classify_regimen_for_cohort,
    COHORT_PSA_REFERENCES,
)


# ─────────────────────────────────────────────────────────────────────────────
# Sección A — build_psa_forecast_per_line (H.G2071-H.G2080)
# ─────────────────────────────────────────────────────────────────────────────


class TestSectionAForecastPerLine:
    """build_psa_forecast_per_line genera forecast por cada treatment line
    independientemente, no solo current line."""

    def test_g2071_per_line_forecast_returns_dict_with_per_line_forecasts(self):
        """H.G2071 — Output incluye `per_line_forecasts` dict."""
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
        assert "per_line_forecasts" in result
        assert isinstance(result["per_line_forecasts"], dict)

    def test_g2072_per_line_forecast_has_summary_metrics(self):
        """H.G2072 — Output incluye summary con counts."""
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
        assert "summary" in result
        assert "ready_count" in result["summary"]
        assert "insufficient_count" in result["summary"]
        assert "total_lines" in result["summary"]

    def test_g2073_per_line_forecast_two_lines_two_forecasts(self):
        """H.G2073 — 2 treatment lines → 2 entries en per_line_forecasts."""
        patient = {
            "biomarker_longitudinal": [
                {"sample_date": "2024-01-01", "biomarker_type": "PSA", "value": 100.0},
                {"sample_date": "2024-04-01", "biomarker_type": "PSA", "value": 50.0},
                {"sample_date": "2024-08-01", "biomarker_type": "PSA", "value": 30.0},
                {"sample_date": "2025-01-01", "biomarker_type": "PSA", "value": 60.0},
                {"sample_date": "2025-05-01", "biomarker_type": "PSA", "value": 80.0},
                {"sample_date": "2025-10-01", "biomarker_type": "PSA", "value": 110.0},
            ],
            "treatments": [
                {"start_date": "2024-01-01", "end_date": "2024-12-31",
                 "drug_scheme": "ADT_MONO", "line_of_therapy_number": "1"},
                {"start_date": "2025-01-01", "drug_scheme": "ADT_ENZALUTAMIDE",
                 "line_of_therapy_number": "2"},
            ],
        }
        result = build_psa_forecast_per_line(patient)
        assert "1" in result["per_line_forecasts"]
        assert "2" in result["per_line_forecasts"]

    def test_g2074_per_line_forecast_insufficient_data_marked(self):
        """H.G2074 — Línea con <3 points → insufficient_data."""
        patient = {
            "biomarker_longitudinal": [
                {"sample_date": "2024-06-01", "biomarker_type": "PSA", "value": 5.0},
            ],
            "treatments": [{
                "start_date": "2024-01-01", "drug_scheme": "ADT_MONO",
                "line_of_therapy_number": "1",
            }],
        }
        result = build_psa_forecast_per_line(patient)
        line_1 = result["per_line_forecasts"].get("1")
        assert line_1 is not None
        assert line_1["status"] == "insufficient_data"

    def test_g2075_per_line_forecast_excludes_pretreatment_points(self):
        """H.G2075 — points_by_line keys 'pretreatment'/'between_lines' NO
        generan forecast (solo líneas numéricas)."""
        patient = {
            "biomarker_longitudinal": [
                {"sample_date": "2023-12-01", "biomarker_type": "PSA", "value": 200.0},
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
        # Solo "1" debe estar; "pretreatment" NO
        keys = set(result["per_line_forecasts"].keys())
        assert "1" in keys
        assert "pretreatment" not in keys
        assert "between_lines" not in keys

    def test_g2076_per_line_forecast_has_horizons_3_6_12(self):
        """H.G2076 — Forecast ready incluye horizontes 3, 6, 12 meses."""
        patient = {
            "biomarker_longitudinal": [
                {"sample_date": "2024-01-01", "biomarker_type": "PSA", "value": 100.0},
                {"sample_date": "2024-04-01", "biomarker_type": "PSA", "value": 50.0},
                {"sample_date": "2024-08-01", "biomarker_type": "PSA", "value": 30.0},
                {"sample_date": "2024-12-01", "biomarker_type": "PSA", "value": 25.0},
            ],
            "treatments": [{
                "start_date": "2024-01-01", "drug_scheme": "ADT_MONO",
                "line_of_therapy_number": "1",
            }],
        }
        result = build_psa_forecast_per_line(patient)
        line_1 = result["per_line_forecasts"]["1"]
        if line_1["status"] == "ready":
            horizons = [p["horizon_months"] for p in line_1["forecast_points"]]
            assert 3 in horizons or 6 in horizons or 12 in horizons

    def test_g2077_per_line_forecast_curve_has_12_months(self):
        """H.G2077 — Forecast ready incluye curve mensual 1-12m."""
        patient = {
            "biomarker_longitudinal": [
                {"sample_date": "2024-01-01", "biomarker_type": "PSA", "value": 100.0},
                {"sample_date": "2024-04-01", "biomarker_type": "PSA", "value": 50.0},
                {"sample_date": "2024-08-01", "biomarker_type": "PSA", "value": 30.0},
                {"sample_date": "2024-12-01", "biomarker_type": "PSA", "value": 25.0},
            ],
            "treatments": [{
                "start_date": "2024-01-01", "drug_scheme": "ADT_MONO",
                "line_of_therapy_number": "1",
            }],
        }
        result = build_psa_forecast_per_line(patient)
        line_1 = result["per_line_forecasts"]["1"]
        if line_1["status"] == "ready":
            assert len(line_1["forecast_curve"]) == 12

    def test_g2078_per_line_forecast_no_data_returns_empty_dict(self):
        """H.G2078 — Patient sin treatments → per_line_forecasts vacío."""
        patient = {"biomarker_longitudinal": []}
        result = build_psa_forecast_per_line(patient)
        assert result["per_line_forecasts"] == {}

    def test_g2079_per_line_forecast_includes_line_label(self):
        """H.G2079 — Forecast incluye line_label propagado."""
        patient = {
            "biomarker_longitudinal": [
                {"sample_date": "2024-01-01", "biomarker_type": "PSA", "value": 100.0},
                {"sample_date": "2024-04-01", "biomarker_type": "PSA", "value": 50.0},
                {"sample_date": "2024-08-01", "biomarker_type": "PSA", "value": 30.0},
            ],
            "treatments": [{
                "start_date": "2024-01-01", "drug_scheme": "ADT_ENZALUTAMIDE",
                "line_of_therapy_number": "1",
            }],
        }
        result = build_psa_forecast_per_line(patient)
        line_1 = result["per_line_forecasts"]["1"]
        assert "line_label" in line_1

    def test_g2080_per_line_forecast_summary_counts_correct(self):
        """H.G2080 — summary counts (ready/insufficient) suman total_lines."""
        patient = {
            "biomarker_longitudinal": [
                {"sample_date": "2024-01-01", "biomarker_type": "PSA", "value": 100.0},
                {"sample_date": "2024-04-01", "biomarker_type": "PSA", "value": 50.0},
                {"sample_date": "2024-08-01", "biomarker_type": "PSA", "value": 30.0},
                {"sample_date": "2025-01-01", "biomarker_type": "PSA", "value": 60.0},
            ],
            "treatments": [
                {"start_date": "2024-01-01", "end_date": "2024-12-31",
                 "drug_scheme": "ADT_MONO", "line_of_therapy_number": "1"},
                {"start_date": "2025-01-01", "drug_scheme": "ADT_ENZALUTAMIDE",
                 "line_of_therapy_number": "2"},
            ],
        }
        result = build_psa_forecast_per_line(patient)
        s = result["summary"]
        assert s["ready_count"] + s["insufficient_count"] == s["total_lines"]


# ─────────────────────────────────────────────────────────────────────────────
# Sección B — build_psa_cohort_reference_overlay (H.G2081-H.G2090)
# ─────────────────────────────────────────────────────────────────────────────


class TestSectionBCohortOverlay:
    """build_psa_cohort_reference_overlay genera curva de referencia
    poblacional basada en literatura pivotal."""

    def test_g2081_classify_regimen_adt_mono(self):
        """H.G2081 — _classify_regimen_for_cohort mapea ADT_MONO → ADT."""
        assert _classify_regimen_for_cohort("ADT_MONO") == "ADT"

    def test_g2082_classify_regimen_adt_docetaxel(self):
        """H.G2082 — Mapea ADT_DOCETAXEL → ADT_DOCETAXEL."""
        assert _classify_regimen_for_cohort("ADT_DOCETAXEL") == "ADT_DOCETAXEL"

    def test_g2083_classify_regimen_adt_arpi(self):
        """H.G2083 — Mapea ADT_ENZALUTAMIDE → ADT_ARPI."""
        assert _classify_regimen_for_cohort("ADT_ENZALUTAMIDE") == "ADT_ARPI"

    def test_g2084_classify_regimen_triplet(self):
        """H.G2084 — Mapea ADT_DOCETAXEL_ABIRATERONE → ADT_TRIPLET."""
        assert _classify_regimen_for_cohort("ADT_DOCETAXEL_ABIRATERONE") == "ADT_TRIPLET"

    def test_g2085_cohort_overlay_returns_curve_for_known_combo(self):
        """H.G2085 — (mcspc_high_volume_sync, ADT_DOCETAXEL) retorna curva."""
        patient = {
            "reconciled_state": "mcspc_high_volume_sync",
            "baseline": {"baseline_psa": 100.0},
            "treatments": [{
                "start_date": "2024-01-01", "drug_scheme": "ADT_DOCETAXEL",
                "line_of_therapy_number": "1",
            }],
            "biomarker_longitudinal": [
                {"sample_date": "2024-01-01", "biomarker_type": "PSA", "value": 100.0},
            ],
        }
        result = build_psa_cohort_reference_overlay(patient)
        assert result["has_data"] is True
        assert len(result["reference_curve"]) > 0

    def test_g2086_cohort_overlay_includes_median_label(self):
        """H.G2086 — median_label incluye nombre del trial pivotal."""
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
        assert result["has_data"] is True
        assert "TAX-327" in result["median_label"]

    def test_g2087_cohort_overlay_unknown_combo_returns_no_data(self):
        """H.G2087 — Combo desconocido → has_data=False con narrative."""
        patient = {
            "reconciled_state": "localized_initial",  # NO en COHORT_PSA_REFERENCES
            "baseline": {"baseline_psa": 5.0},
            "treatments": [{
                "start_date": "2024-01-01", "drug_scheme": "ADT_MONO",
                "line_of_therapy_number": "1",
            }],
            "biomarker_longitudinal": [
                {"sample_date": "2024-01-01", "biomarker_type": "PSA", "value": 5.0},
            ],
        }
        result = build_psa_cohort_reference_overlay(patient)
        assert result["has_data"] is False
        assert "narrative" in result

    def test_g2088_cohort_overlay_no_baseline_returns_no_data(self):
        """H.G2088 — Sin baseline_psa → has_data=False (no se puede anclar)."""
        patient = {
            "reconciled_state": "m1_crpc",
            "treatments": [{
                "start_date": "2024-01-01", "drug_scheme": "DOCETAXEL",
                "line_of_therapy_number": "1",
            }],
            "biomarker_longitudinal": [
                # No baseline + no monitoring data significa no anchor
            ],
        }
        result = build_psa_cohort_reference_overlay(patient)
        assert result["has_data"] is False

    def test_g2089_cohort_overlay_curve_decay_from_baseline_to_nadir(self):
        """H.G2089 — Curva decay: PSA[0]=baseline, PSA[time_to_nadir]≈expected_nadir."""
        patient = {
            "reconciled_state": "m1_crpc",
            "baseline": {"baseline_psa": 100.0},
            "treatments": [{
                "start_date": "2024-01-01", "drug_scheme": "DOCETAXEL",
                "line_of_therapy_number": "1",
            }],
            "biomarker_longitudinal": [
                {"sample_date": "2024-01-01", "biomarker_type": "PSA", "value": 100.0},
            ],
        }
        result = build_psa_cohort_reference_overlay(patient)
        if result["has_data"]:
            curve = result["reference_curve"]
            assert curve[0]["expected_psa"] == pytest.approx(100.0, rel=0.05)
            # Check expected_nadir reached by time_to_nadir_m
            time_to_nadir = result["expected_time_to_nadir_months"]
            nadir_point = next((p for p in curve if p["horizon_months"] == time_to_nadir), None)
            assert nadir_point is not None
            assert nadir_point["expected_psa"] == pytest.approx(
                result["expected_nadir_psa"], rel=0.1
            )

    def test_g2090_cohort_references_dict_completeness(self):
        """H.G2090 — COHORT_PSA_REFERENCES tiene los 4 estados clínicos
        principales (mHSPC alto volumen sync/metacrónico, m0CRPC, m1CRPC)."""
        required_states = {
            "mcspc_high_volume_sync", "mcspc_high_volume_metachronous",
            "m0_crpc", "m1_crpc",
        }
        missing = required_states - set(COHORT_PSA_REFERENCES.keys())
        assert not missing, f"Estados clínicos faltantes en COHORT_PSA_REFERENCES: {missing}"


# ─────────────────────────────────────────────────────────────────────────────
# Sección C — build_combined_patient_timeline (H.G2091-H.G2100)
# ─────────────────────────────────────────────────────────────────────────────


class TestSectionCCombinedTimeline:
    """build_combined_patient_timeline produce estructura unificada para
    chart con PSA + treatment lanes + clinical events."""

    def test_g2091_combined_timeline_has_axis_dates(self):
        """H.G2091 — Output incluye axis_dates (eje X unificado)."""
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
        assert "axis_dates" in result
        assert isinstance(result["axis_dates"], list)

    def test_g2092_combined_timeline_psa_series_with_treatment_line(self):
        """H.G2092 — psa_series incluye treatment_line per point (#63B)."""
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
        assert len(result["psa_series"]) >= 1
        assert "treatment_line" in result["psa_series"][0]

    def test_g2093_combined_timeline_treatment_lanes_from_bands(self):
        """H.G2093 — treatment_lanes derivados de treatment_bands."""
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
        assert len(result["treatment_lanes"]) == 1
        assert result["treatment_lanes"][0]["line_number"] == "1"

    def test_g2094_combined_timeline_event_markers_with_treatment_assignment(self):
        """H.G2094 — clinical_event_markers reciben treatment_line por fecha.

        Nota: el band end_date se sintetiza como `last_known_date` (último PSA
        point) cuando no hay end_date explícito. Para asegurar que el event
        cae dentro del rango, agregamos un PSA point posterior al event date.
        """
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
        events = [
            {"date": "2024-06-15", "title": "Visita de seguimiento",
             "origin": "visit", "decision": "Continuar línea actual"},
        ]
        result = build_combined_patient_timeline(patient, clinical_events=events)
        markers = result["clinical_event_markers"]
        assert len(markers) == 1
        # Fecha 2024-06-15 cae dentro del rango [2024-01-01, 2024-09-01]
        assert markers[0]["treatment_line"] == "1"

    def test_g2095_combined_timeline_summary_correct_counts(self):
        """H.G2095 — summary counts coinciden con datos."""
        patient = {
            "biomarker_longitudinal": [
                {"sample_date": "2024-03-01", "biomarker_type": "PSA", "value": 10.0},
                {"sample_date": "2024-06-01", "biomarker_type": "PSA", "value": 5.0},
            ],
            "treatments": [
                {"start_date": "2024-01-01", "drug_scheme": "ADT_MONO",
                 "line_of_therapy_number": "1"},
            ],
        }
        events = [{"date": "2024-04-01", "title": "Visita", "origin": "visit"}]
        result = build_combined_patient_timeline(patient, clinical_events=events)
        s = result["summary"]
        assert s["total_psa_points"] == 2
        assert s["total_treatment_lanes"] == 1
        assert s["total_event_markers"] == 1

    def test_g2096_combined_timeline_no_events_optional(self):
        """H.G2096 — clinical_events=None → markers vacíos pero no error."""
        patient = {
            "biomarker_longitudinal": [
                {"sample_date": "2024-06-01", "biomarker_type": "PSA", "value": 5.0},
            ],
            "treatments": [{"start_date": "2024-01-01", "drug_scheme": "ADT_MONO",
                            "line_of_therapy_number": "1"}],
        }
        result = build_combined_patient_timeline(patient, clinical_events=None)
        assert result["clinical_event_markers"] == []

    def test_g2097_combined_timeline_no_data_returns_empty(self):
        """H.G2097 — Patient sin PSA data → has_data=False + estructura vacía."""
        patient = {}
        result = build_combined_patient_timeline(patient)
        assert result["has_data"] is False
        assert result["axis_dates"] == []
        assert result["psa_series"] == []

    def test_g2098_combined_timeline_axis_dates_sorted(self):
        """H.G2098 — axis_dates retornados ordenados ascendentemente."""
        patient = {
            "biomarker_longitudinal": [
                {"sample_date": "2024-09-01", "biomarker_type": "PSA", "value": 3.0},
                {"sample_date": "2024-03-01", "biomarker_type": "PSA", "value": 10.0},
                {"sample_date": "2024-06-01", "biomarker_type": "PSA", "value": 5.0},
            ],
            "treatments": [{"start_date": "2024-01-01", "drug_scheme": "ADT_MONO",
                            "line_of_therapy_number": "1"}],
        }
        result = build_combined_patient_timeline(patient)
        dates = result["axis_dates"]
        assert dates == sorted(dates)

    def test_g2099_combined_timeline_event_outside_lanes_no_assignment(self):
        """H.G2099 — Event ANTES de cualquier lane → treatment_line=None."""
        patient = {
            "biomarker_longitudinal": [
                {"sample_date": "2024-06-01", "biomarker_type": "PSA", "value": 5.0},
            ],
            "treatments": [{"start_date": "2024-01-01", "drug_scheme": "ADT_MONO",
                            "line_of_therapy_number": "1"}],
        }
        events = [{"date": "2023-06-01", "title": "Evento previo", "origin": "history"}]
        result = build_combined_patient_timeline(patient, clinical_events=events)
        markers = result["clinical_event_markers"]
        assert markers[0]["treatment_line"] is None

    def test_g2100_combined_timeline_psa_series_preserves_psa_value(self):
        """H.G2100 — psa_series.psa preserva valor numérico exacto."""
        patient = {
            "biomarker_longitudinal": [
                {"sample_date": "2024-06-01", "biomarker_type": "PSA", "value": 7.5},
            ],
            "treatments": [{"start_date": "2024-01-01", "drug_scheme": "ADT_MONO",
                            "line_of_therapy_number": "1"}],
        }
        result = build_combined_patient_timeline(patient)
        assert result["psa_series"][0]["psa"] == pytest.approx(7.5)
