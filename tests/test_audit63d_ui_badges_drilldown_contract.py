"""Auditoría Faubot #63D (LXVII) — UI badges + PSADT annotations + Drill-down panel.

Tests del contrato de datos backend → template para los componentes UI #63D:
  Sección A — line_segments contract (campos requeridos por template) (8 tests)
  Sección B — kinetics_classification mapping a badges (8 tests)
  Sección C — Edge cases para drill-down panel (5 tests)
  Sección D — Smoke E2E classification + drill-down data flow (4 tests)

Total: 25 tests. Hipótesis verificables: H.G2046 - H.G2070.

NOTA: Este test file valida solo el CONTRATO BACKEND para UI rendering.
Las pruebas E2E del rendering visual + drill-down panel requieren browser
automation (Playwright) y están fuera del scope de este test file.
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import sys
import types

import pytest

# Stubs APFS I/O lock workaround (mismo pattern #63B/C)
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

from prostanet.domains.patient_tracking.psa_line_monitor import (
    _segment_points_by_line,
    build_psa_by_treatment_line,
)


# ─────────────────────────────────────────────────────────────────────────────
# Sección A — line_segments contract para template rendering (H.G2046-H.G2053)
# ─────────────────────────────────────────────────────────────────────────────


class TestSectionALineSegmentsContract:
    """line_segments DEBE contener todos los campos que el template
    `patient_profile.html` consume para renderizar las cards + drill-down."""

    @pytest.fixture
    def standard_segment(self):
        points = [
            {"date": "2024-01-01", "psa": 100.0},
            {"date": "2024-04-01", "psa": 30.0},
        ]
        bands = [{
            "start_date": "2024-01-01", "end_date": "2024-12-31",
            "line_of_therapy_number": "1",
            "line_of_therapy_context": "mHSPC_initial",
            "drug_scheme": "ADT_MONO", "drug_scheme_label": "ADT mono",
            "label": "L1 · mHSPC inicial · ADT mono",
            "color": "rgba(59, 130, 246, 0.12)",
        }]
        return _segment_points_by_line(points, bands)[0]

    def test_g2046_segment_has_label_for_card_title(self, standard_segment):
        """H.G2046 — segment.label requerido para card title."""
        assert "label" in standard_segment
        assert standard_segment["label"]

    def test_g2047_segment_has_line_of_therapy_number_for_drill_down(self, standard_segment):
        """H.G2047 — line_of_therapy_number requerido para data-line-number."""
        assert "line_of_therapy_number" in standard_segment

    def test_g2048_segment_has_classification_for_badge(self, standard_segment):
        """H.G2048 — kinetics_classification requerido para badge."""
        assert "kinetics_classification" in standard_segment
        assert standard_segment["kinetics_classification"] in {
            "response", "partial_response", "stable", "progression",
            "primary_refractory", "insufficient_data",
        }

    def test_g2049_segment_has_baseline_psa_for_metric_card(self, standard_segment):
        """H.G2049 — baseline_psa requerido para card metric."""
        assert "baseline_psa" in standard_segment

    def test_g2050_segment_has_nadir_psa_for_metric_card(self, standard_segment):
        """H.G2050 — nadir_psa requerido para card metric."""
        assert "nadir_psa" in standard_segment

    def test_g2051_segment_has_psadt_during_progression_for_drill_down(self, standard_segment):
        """H.G2051 — psadt_during_progression requerido para drill-down PSADT badge."""
        assert "psadt_during_progression" in standard_segment

    def test_g2052_segment_has_time_to_nadir_for_drill_down(self, standard_segment):
        """H.G2052 — time_to_nadir_months requerido para drill-down métrica granular."""
        assert "time_to_nadir_months" in standard_segment

    def test_g2053_segment_has_duration_response_for_drill_down(self, standard_segment):
        """H.G2053 — duration_response_months requerido para drill-down métrica granular."""
        assert "duration_response_months" in standard_segment


# ─────────────────────────────────────────────────────────────────────────────
# Sección B — kinetics_classification mapping a badges (H.G2054-H.G2061)
# ─────────────────────────────────────────────────────────────────────────────


class TestSectionBClassificationToBadge:
    """Verifica que cada classification produce el badge correcto en el flujo
    backend → template. Los CSS classes de cada badge están en el template
    (Jinja conditionals). Aquí validamos que el classification value es
    determinista per input clínico."""

    def _make_segment(self, points_data, baseline=100.0):
        """Helper para construir segment desde lista [(date, psa)]."""
        points = [{"date": d, "psa": p} for d, p in points_data]
        bands = [{
            "start_date": points_data[0][0], "end_date": "2025-12-31",
            "line_of_therapy_number": "1", "label": "L1",
            "color": "rgba(59, 130, 246, 0.12)",
        }]
        return _segment_points_by_line(points, bands)[0]

    def test_g2054_response_50_pct_drop_no_progression(self):
        """H.G2054 — Drop ≥50% sin rebote → classification=response → badge emerald."""
        seg = self._make_segment([
            ("2024-01-01", 100.0),
            ("2024-06-01", 30.0),  # -70% nadir
        ])
        assert seg["kinetics_classification"] == "response"

    def test_g2055_partial_response_30_to_49_pct(self):
        """H.G2055 — Drop 30-49% → classification=partial_response → badge cyan."""
        seg = self._make_segment([
            ("2024-01-01", 100.0),
            ("2024-06-01", 60.0),  # -40% partial
        ])
        assert seg["kinetics_classification"] == "partial_response"

    def test_g2056_stable_minimal_change(self):
        """H.G2056 — Cambio < 30% sin rebote → classification=stable → badge slate."""
        seg = self._make_segment([
            ("2024-01-01", 10.0),
            ("2024-06-01", 9.0),  # -10%
        ])
        assert seg["kinetics_classification"] == "stable"

    def test_g2057_progression_post_nadir_rebound(self):
        """H.G2057 — Rebote ≥25% post-nadir → classification=progression → badge rose."""
        seg = self._make_segment([
            ("2024-01-01", 100.0),
            ("2024-04-01", 30.0),   # nadir
            ("2024-09-01", 60.0),   # rebote +100% desde nadir
        ])
        assert seg["kinetics_classification"] == "progression"

    def test_g2058_insufficient_data_with_one_point(self):
        """H.G2058 — Solo 1 point → classification=insufficient_data → badge slate gris."""
        seg = self._make_segment([("2024-01-01", 5.0)])
        assert seg["kinetics_classification"] == "insufficient_data"

    def test_g2059_classification_string_is_template_safe(self):
        """H.G2059 — classification es siempre string (no None) — Jinja safe."""
        seg = self._make_segment([("2024-01-01", 5.0)])
        assert isinstance(seg["kinetics_classification"], str)
        # No espacios ni caracteres raros que rompan template `data-classification`
        assert " " not in seg["kinetics_classification"]

    def test_g2060_psa50_achieved_independent_of_classification(self):
        """H.G2060 — psa50_achieved es independiente de classification (puede haber
        psa50 con progression posterior).
        """
        seg = self._make_segment([
            ("2024-01-01", 100.0),
            ("2024-04-01", 30.0),   # -70% → psa50 yes
            ("2024-09-01", 60.0),   # rebote → progression
        ])
        assert seg["psa50_achieved"] is True
        assert seg["kinetics_classification"] == "progression"

    def test_g2061_classification_consistent_across_calls(self):
        """H.G2061 — Misma input produce misma classification (idempotente)."""
        points = [("2024-01-01", 100.0), ("2024-06-01", 30.0)]
        seg1 = self._make_segment(points)
        seg2 = self._make_segment(points)
        assert seg1["kinetics_classification"] == seg2["kinetics_classification"]


# ─────────────────────────────────────────────────────────────────────────────
# Sección C — Edge cases para drill-down panel (H.G2062-H.G2066)
# ─────────────────────────────────────────────────────────────────────────────


class TestSectionCDrillDownEdgeCases:
    """Edge cases que el drill-down panel debe manejar correctamente."""

    def test_g2062_segment_with_none_psadt_progression_not_breaking(self):
        """H.G2062 — psadt_during_progression=None NO rompe template/JS."""
        points = [{"date": "2024-01-01", "psa": 100.0}]
        bands = [{"start_date": "2024-01-01", "end_date": "2024-12-31",
                  "line_of_therapy_number": "1", "label": "L1",
                  "color": "rgba(59, 130, 246, 0.12)"}]
        seg = _segment_points_by_line(points, bands)[0]
        # 1 point → insufficient_data → psadt_during_progression debería ser None
        assert seg["psadt_during_progression"] is None
        # Pero el campo DEBE estar presente para que `data-psadt-progression` no falte
        assert "psadt_during_progression" in seg

    def test_g2063_segment_with_zero_baseline_psa(self):
        """H.G2063 — baseline_psa=0 (edge case, e.g., post-RP indetectable)."""
        points = [
            {"date": "2024-01-01", "psa": 0.0},
            {"date": "2024-06-01", "psa": 0.0},
        ]
        bands = [{"start_date": "2024-01-01", "end_date": "2024-12-31",
                  "line_of_therapy_number": "1", "label": "L1",
                  "color": "rgba(59, 130, 246, 0.12)"}]
        seg = _segment_points_by_line(points, bands)[0]
        # baseline=0 nadir=0 → classification debe NO ser progression (no rebote)
        assert seg["kinetics_classification"] in {"stable", "insufficient_data"}

    def test_g2064_segment_with_long_label_truncation_safe(self):
        """H.G2064 — Labels largos OK para drill-down (CSS truncate aplica)."""
        long_label = "L1 · mHSPC inicial · ADT + Enzalutamida + Docetaxel triplete"
        points = [
            {"date": "2024-01-01", "psa": 100.0},
            {"date": "2024-06-01", "psa": 30.0},
        ]
        bands = [{"start_date": "2024-01-01", "end_date": "2024-12-31",
                  "line_of_therapy_number": "1", "label": long_label,
                  "color": "rgba(59, 130, 246, 0.12)"}]
        seg = _segment_points_by_line(points, bands)[0]
        assert seg["label"] == long_label
        # Template usa class="truncate" para manejar visual

    def test_g2065_multiple_segments_each_with_independent_classification(self):
        """H.G2065 — Múltiples segments cada uno con su propia classification."""
        points = [
            {"date": "2024-01-01", "psa": 100.0},
            {"date": "2024-04-01", "psa": 30.0},   # L1 nadir
            {"date": "2025-01-01", "psa": 80.0},
            {"date": "2025-06-01", "psa": 78.0},   # L2 stable
        ]
        bands = [
            {"start_date": "2024-01-01", "end_date": "2024-12-31",
             "line_of_therapy_number": "1", "label": "L1",
             "color": "rgba(59, 130, 246, 0.12)"},
            {"start_date": "2025-01-01", "end_date": "2025-12-31",
             "line_of_therapy_number": "2", "label": "L2",
             "color": "rgba(16, 185, 129, 0.12)"},
        ]
        segments = _segment_points_by_line(points, bands)
        assert len(segments) == 2
        # L1 = response (drop 70%); L2 = stable (mínimo cambio)
        assert segments[0]["kinetics_classification"] == "response"
        assert segments[1]["kinetics_classification"] in {"stable", "partial_response"}

    def test_g2066_segment_drug_scheme_propagated_for_drill_down(self):
        """H.G2066 — drug_scheme + drug_scheme_label propagados desde band para drill-down."""
        points = [
            {"date": "2024-01-01", "psa": 100.0},
            {"date": "2024-06-01", "psa": 30.0},
        ]
        bands = [{"start_date": "2024-01-01", "end_date": "2024-12-31",
                  "line_of_therapy_number": "1", "label": "L1",
                  "drug_scheme": "ADT_ENZALUTAMIDE",
                  "drug_scheme_label": "ADT + Enzalutamida",
                  "color": "rgba(59, 130, 246, 0.12)"}]
        seg = _segment_points_by_line(points, bands)[0]
        assert seg["drug_scheme"] == "ADT_ENZALUTAMIDE"
        assert seg["drug_scheme_label"] == "ADT + Enzalutamida"


# ─────────────────────────────────────────────────────────────────────────────
# Sección D — Smoke E2E classification + drill-down data flow (H.G2067-H.G2070)
# ─────────────────────────────────────────────────────────────────────────────


class TestSectionDSmokeClassificationDataFlow:
    """Smoke tests E2E: build_psa_by_treatment_line produce line_segments con
    todos los campos esperados por el template #63D, listos para renderizar
    badges + drill-down panel."""

    def test_g2067_build_returns_segments_with_all_drill_down_fields(self):
        """H.G2067 — build_psa_by_treatment_line.line_segments incluye TODOS
        los campos data-* del template."""
        patient = {
            "biomarker_longitudinal": [
                {"sample_date": "2024-01-01", "biomarker_type": "PSA", "value": 100.0},
                {"sample_date": "2024-06-01", "biomarker_type": "PSA", "value": 30.0},
            ],
            "treatments": [{
                "start_date": "2024-01-01", "drug_scheme": "ADT_MONO",
                "line_of_therapy_number": "1",
            }],
        }
        result = build_psa_by_treatment_line(patient)
        seg = result["line_segments"][0]
        required_fields = [
            "label", "line_of_therapy_number", "kinetics_classification",
            "baseline_psa", "nadir_psa", "current_psa", "best_pct_change",
            "psa50_achieved", "psa_velocity", "psadt", "point_count",
            "time_to_nadir_months", "duration_response_months",
            "psadt_during_progression", "drug_scheme", "drug_scheme_label",
            "start_date", "end_date",
        ]
        missing = [f for f in required_fields if f not in seg]
        assert not missing, f"Campos faltantes para drill-down: {missing}"

    def test_g2068_progression_classification_with_psadt_drives_badge_alert(self):
        """H.G2068 — Progression con psadt agresivo debe disparar badge rose +
        annotation 'gate 53'.

        Nota PCWG3 simplificado: progression_threshold = max(nadir × 1.25,
        nadir + 2.0). En valores bajos como 0.3, el threshold es 2.3, por
        eso usamos baseline alto + nadir alto + rebote claro.
        """
        patient = {
            "biomarker_longitudinal": [
                {"sample_date": "2024-01-01", "biomarker_type": "PSA", "value": 50.0},
                {"sample_date": "2024-04-01", "biomarker_type": "PSA", "value": 10.0},  # nadir
                {"sample_date": "2024-09-01", "biomarker_type": "PSA", "value": 25.0},  # rebote +150%
            ],
            "treatments": [{
                "start_date": "2024-01-01", "drug_scheme": "ADT_MONO",
                "line_of_therapy_number": "1",
            }],
        }
        result = build_psa_by_treatment_line(patient)
        seg = result["line_segments"][0]
        assert seg["kinetics_classification"] == "progression"
        # psadt_during_progression depende del stub (no crítico para test pero presente)
        assert "psadt_during_progression" in seg

    def test_g2069_response_with_long_duration_supports_chart_callout(self):
        """H.G2069 — Response ≥50% sostenida >12m → segment listo para chart
        callout 'kinetics no acelerados' en drill-down."""
        patient = {
            "biomarker_longitudinal": [
                {"sample_date": "2024-01-01", "biomarker_type": "PSA", "value": 100.0},
                {"sample_date": "2024-06-01", "biomarker_type": "PSA", "value": 20.0},  # nadir -80%
                {"sample_date": "2025-06-01", "biomarker_type": "PSA", "value": 18.0},  # 12m sostenida
            ],
            "treatments": [{
                "start_date": "2024-01-01", "drug_scheme": "ADT_ENZALUTAMIDE",
                "line_of_therapy_number": "1",
            }],
        }
        result = build_psa_by_treatment_line(patient)
        seg = result["line_segments"][0]
        assert seg["kinetics_classification"] == "response"
        # duration_response_months debe ser ≥12 meses (o =None si stub no calcula)
        # Aquí solo validamos que el campo existe
        assert "duration_response_months" in seg

    def test_g2070_no_segments_returns_empty_list_for_template(self):
        """H.G2070 — Sin treatments → line_segments=[] (template no renderiza grid)."""
        patient = {
            "biomarker_longitudinal": [
                {"sample_date": "2024-06-01", "biomarker_type": "PSA", "value": 5.0},
            ],
            # Sin treatments
        }
        result = build_psa_by_treatment_line(patient)
        assert result["line_segments"] == []
        # Template tiene `{% if psa_observability.line_segments %}` que NO renderiza grid
