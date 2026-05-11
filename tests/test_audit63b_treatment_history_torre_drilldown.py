"""Auditoría Faubot #63B (LXV) — Treatment history timeline + Torre drill-down.

Sub-test file que NO depende de prostanet.domains.patient_tracking.service
(que requiere tracking_db + clinical_scores con APFS I/O issues).

Cobre las secciones B + C + D principal de la auditoría:
  Sección B — _annotate_points_with_treatment_line (12 tests, H.G1988-H.G1999)
  Sección C — build_psa_by_treatment_line drill-down (10 tests, H.G2000-H.G2009)
  Sección D — Smoke E2E con treatments[] preconfigurados (6 tests, H.G2010-H.G2015)

Section A (canonicalize_payload synthesis) está en el complementario
test_audit63b_canonicalize_treatments_synthesis.py que requiere service.py.

Nota: con stubs sys.modules para mock de tracking_db, esta separación permite
ejecutar la mayoría de tests independientemente del estado APFS de los módulos
clinical_scores/tracking_db locked.
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import sys
import types

import pytest

# APFS I/O lock workaround (Faubot LXV #63B): clinical_scores.py source
# está APFS-locked. psa_line_monitor.py hace lazy import dentro de
# build_psa_by_treatment_line. Stub mínimo bypassa el lock para tests
# que sólo necesitan validar la lógica drill-down (no kinetics math).
if "clinical_scores" not in sys.modules:
    # Stub agresivo: cualquier atributo solicitado retorna no-op callable.
    # Esto evita ImportError cascaded de risk_tools.py:7 cuando se ejecuta
    # cross-test-file (estado compartido sys.modules).
    class _ClinicalScoresStub(types.ModuleType):
        def __getattr__(self, name):
            def _noop(*args, **kwargs):
                if name == "calculate_psa_kinetics":
                    return {"velocity": None, "psadt": None, "interpretation": "stub"}
                return {}
            _noop.__name__ = name
            return _noop
    sys.modules["clinical_scores"] = _ClinicalScoresStub("clinical_scores")

from prostanet.domains.patient_tracking.psa_line_monitor import (
    _annotate_points_with_treatment_line,
    build_psa_by_treatment_line,
)


# ─────────────────────────────────────────────────────────────────────────────
# Sección B — _annotate_points_with_treatment_line (H.G1988-H.G1999)
# ─────────────────────────────────────────────────────────────────────────────


class TestSectionBAnnotatePointsByDate:
    """_annotate_points_with_treatment_line debe asignar a cada PSA point
    su treatment_line_number + treatment_color basado en fecha."""

    def test_g1988_point_within_band_gets_line_number(self):
        """H.G1988 — Point con fecha dentro de banda recibe line_of_therapy_number."""
        points = [{"date": "2024-06-01", "psa": 5.0, "source": "test"}]
        bands = [{
            "start_date": "2024-01-01", "end_date": "2024-12-31",
            "line_of_therapy_number": "1", "label": "L1 ADT",
            "color": "rgba(59, 130, 246, 0.12)",
        }]
        annotated = _annotate_points_with_treatment_line(points, bands)
        assert annotated[0].get("treatment_line_number") == "1"
        assert annotated[0].get("treatment_assignment_origin") == "auto_by_date"

    def test_g1989_point_before_first_band_marked_pretreatment(self):
        """H.G1989 — Point antes de 1ra banda → pretreatment."""
        points = [{"date": "2023-12-01", "psa": 10.0, "source": "test"}]
        bands = [{
            "start_date": "2024-01-01", "end_date": "2024-12-31",
            "line_of_therapy_number": "1", "label": "L1",
            "color": "rgba(59, 130, 246, 0.12)",
        }]
        annotated = _annotate_points_with_treatment_line(points, bands)
        assert annotated[0].get("treatment_assignment_origin") == "pretreatment"
        assert annotated[0].get("treatment_line_number") is None

    def test_g1990_point_between_bands_marked_between_lines(self):
        """H.G1990 — Point en gap entre bandas → between_lines."""
        points = [{"date": "2024-12-15", "psa": 8.0, "source": "test"}]
        bands = [
            {
                "start_date": "2024-01-01", "end_date": "2024-11-01",
                "line_of_therapy_number": "1", "label": "L1",
                "color": "rgba(59, 130, 246, 0.12)",
            },
            {
                "start_date": "2025-01-01", "end_date": "2025-06-01",
                "line_of_therapy_number": "2", "label": "L2",
                "color": "rgba(16, 185, 129, 0.12)",
            },
        ]
        annotated = _annotate_points_with_treatment_line(points, bands)
        assert annotated[0].get("treatment_assignment_origin") == "between_lines"

    def test_g1991_no_bands_marks_no_bands_origin(self):
        """H.G1991 — Sin bandas → todos points marcados no_bands."""
        points = [{"date": "2024-06-01", "psa": 5.0, "source": "test"}]
        annotated = _annotate_points_with_treatment_line(points, [])
        assert annotated[0].get("treatment_assignment_origin") == "no_bands"

    def test_g1992_empty_points_returns_empty(self):
        """H.G1992 — Sin points → retorna lista vacía."""
        annotated = _annotate_points_with_treatment_line([], [{"start_date": "2024-01-01"}])
        assert annotated == []

    def test_g1993_invalid_date_marked_invalid(self):
        """H.G1993 — Point con fecha inválida → treatment_assignment_origin=invalid_date."""
        points = [{"date": "not-a-date", "psa": 5.0, "source": "test"}]
        bands = [{
            "start_date": "2024-01-01", "end_date": "2024-12-31",
            "line_of_therapy_number": "1", "label": "L1",
            "color": "rgba(59, 130, 246, 0.12)",
        }]
        annotated = _annotate_points_with_treatment_line(points, bands)
        assert annotated[0].get("treatment_assignment_origin") == "invalid_date"

    def test_g1994_band_color_propagated(self):
        """H.G1994 — treatment_color de banda se propaga a point."""
        points = [{"date": "2024-06-01", "psa": 5.0, "source": "test"}]
        bands = [{
            "start_date": "2024-01-01", "end_date": "2024-12-31",
            "line_of_therapy_number": "1", "label": "L1",
            "color": "rgba(245, 158, 11, 0.12)",
        }]
        annotated = _annotate_points_with_treatment_line(points, bands)
        assert annotated[0].get("treatment_color") == "rgba(245, 158, 11, 0.12)"

    def test_g1995_band_index_assigned(self):
        """H.G1995 — Point recibe treatment_band_index correcto."""
        points = [
            {"date": "2024-03-01", "psa": 10.0, "source": "test"},
            {"date": "2025-03-01", "psa": 5.0, "source": "test"},
        ]
        bands = [
            {
                "start_date": "2024-01-01", "end_date": "2024-12-31",
                "line_of_therapy_number": "1", "label": "L1",
                "color": "rgba(59, 130, 246, 0.12)",
            },
            {
                "start_date": "2025-01-01", "end_date": "2025-12-31",
                "line_of_therapy_number": "2", "label": "L2",
                "color": "rgba(16, 185, 129, 0.12)",
            },
        ]
        annotated = _annotate_points_with_treatment_line(points, bands)
        assert annotated[0].get("treatment_band_index") == 0
        assert annotated[1].get("treatment_band_index") == 1

    def test_g1996_label_propagated_from_band(self):
        """H.G1996 — treatment_line_label de banda se propaga."""
        points = [{"date": "2024-06-01", "psa": 5.0, "source": "test"}]
        bands = [{
            "start_date": "2024-01-01", "end_date": "2024-12-31",
            "line_of_therapy_number": "1",
            "label": "L1 · mHSPC inicial · ADT + Enzalutamida",
            "color": "rgba(59, 130, 246, 0.12)",
        }]
        annotated = _annotate_points_with_treatment_line(points, bands)
        assert "mHSPC inicial" in annotated[0].get("treatment_line_label", "")

    def test_g1997_open_ended_band_includes_today(self):
        """H.G1997 — Banda sin end_date asume hasta hoy."""
        points = [{"date": "2026-04-01", "psa": 3.0, "source": "test"}]
        bands = [{
            "start_date": "2024-01-01",
            # end_date None — banda abierta
            "line_of_therapy_number": "1", "label": "L1",
            "color": "rgba(59, 130, 246, 0.12)",
        }]
        annotated = _annotate_points_with_treatment_line(points, bands)
        assert annotated[0].get("treatment_line_number") == "1"
        assert annotated[0].get("treatment_assignment_origin") == "auto_by_date"

    def test_g1998_original_point_immutable(self):
        """H.G1998 — Point original NO se muta; siempre se retorna copia."""
        original_point = {"date": "2024-06-01", "psa": 5.0, "source": "test"}
        bands = [{
            "start_date": "2024-01-01", "end_date": "2024-12-31",
            "line_of_therapy_number": "1", "label": "L1",
            "color": "rgba(59, 130, 246, 0.12)",
        }]
        _ = _annotate_points_with_treatment_line([original_point], bands)
        # Original no debe tener anotaciones
        assert "treatment_line_number" not in original_point
        assert "treatment_color" not in original_point

    def test_g1999_first_matching_band_wins(self):
        """H.G1999 — Si point cae en bandas solapadas (data error), 1ra gana."""
        points = [{"date": "2024-06-01", "psa": 5.0, "source": "test"}]
        bands = [
            {
                "start_date": "2024-01-01", "end_date": "2024-12-31",
                "line_of_therapy_number": "1", "label": "L1 first",
                "color": "rgba(59, 130, 246, 0.12)",
            },
            {
                "start_date": "2024-05-01", "end_date": "2024-08-31",
                "line_of_therapy_number": "2", "label": "L2 overlap",
                "color": "rgba(16, 185, 129, 0.12)",
            },
        ]
        annotated = _annotate_points_with_treatment_line(points, bands)
        assert annotated[0].get("treatment_line_label") == "L1 first"


# ─────────────────────────────────────────────────────────────────────────────
# Sección C — build_psa_by_treatment_line drill-down (H.G2000-H.G2009)
# ─────────────────────────────────────────────────────────────────────────────


class TestSectionCBuildDrillDown:
    """build_psa_by_treatment_line debe retornar points_by_line + métricas
    drill-down ready para chart."""

    def test_g2000_points_by_line_present_in_output(self):
        """H.G2000 — Output incluye points_by_line dict."""
        patient = {
            "biomarker_longitudinal": [
                {"sample_date": "2024-06-01", "biomarker_type": "PSA", "value": 5.0},
            ],
            "treatments": [
                {"start_date": "2024-01-01", "drug_scheme": "ADT_MONO",
                 "line_of_therapy_number": "1"},
            ],
        }
        result = build_psa_by_treatment_line(patient)
        assert "points_by_line" in result
        assert isinstance(result["points_by_line"], dict)

    def test_g2001_points_grouped_by_line_number(self):
        """H.G2001 — Points se agrupan por treatment_line_number."""
        patient = {
            "biomarker_longitudinal": [
                {"sample_date": "2024-06-01", "biomarker_type": "PSA", "value": 5.0},
                {"sample_date": "2024-09-01", "biomarker_type": "PSA", "value": 3.0},
                {"sample_date": "2025-03-01", "biomarker_type": "PSA", "value": 8.0},
            ],
            "treatments": [
                {"start_date": "2024-01-01", "end_date": "2024-12-31",
                 "drug_scheme": "ADT_MONO", "line_of_therapy_number": "1"},
                {"start_date": "2025-01-01", "drug_scheme": "ADT_ENZALUTAMIDE",
                 "line_of_therapy_number": "2"},
            ],
        }
        result = build_psa_by_treatment_line(patient)
        pbl = result["points_by_line"]
        assert "1" in pbl
        assert "2" in pbl
        assert len(pbl["1"]) == 2
        assert len(pbl["2"]) == 1

    def test_g2002_metrics_lines_with_points_count(self):
        """H.G2002 — metrics incluye lines_with_points_count."""
        patient = {
            "biomarker_longitudinal": [
                {"sample_date": "2024-06-01", "biomarker_type": "PSA", "value": 5.0},
                {"sample_date": "2025-03-01", "biomarker_type": "PSA", "value": 8.0},
            ],
            "treatments": [
                {"start_date": "2024-01-01", "end_date": "2024-12-31",
                 "drug_scheme": "ADT_MONO", "line_of_therapy_number": "1"},
                {"start_date": "2025-01-01", "drug_scheme": "ADT_ENZALUTAMIDE",
                 "line_of_therapy_number": "2"},
            ],
        }
        result = build_psa_by_treatment_line(patient)
        assert result["metrics"]["lines_with_points_count"] == 2

    def test_g2003_pretreatment_count(self):
        """H.G2003 — points_pretreatment_count refleja points antes 1ra banda."""
        patient = {
            "biomarker_longitudinal": [
                {"sample_date": "2023-12-01", "biomarker_type": "PSA", "value": 10.0},
                {"sample_date": "2024-06-01", "biomarker_type": "PSA", "value": 5.0},
            ],
            "treatments": [
                {"start_date": "2024-01-01", "drug_scheme": "ADT_MONO",
                 "line_of_therapy_number": "1"},
            ],
        }
        result = build_psa_by_treatment_line(patient)
        assert result["metrics"]["points_pretreatment_count"] == 1

    def test_g2004_between_lines_count(self):
        """H.G2004 — points_between_lines_count refleja gaps temporales."""
        patient = {
            "biomarker_longitudinal": [
                {"sample_date": "2024-12-15", "biomarker_type": "PSA", "value": 8.0},
            ],
            "treatments": [
                {"start_date": "2024-01-01", "end_date": "2024-11-01",
                 "drug_scheme": "ADT_MONO", "line_of_therapy_number": "1"},
                {"start_date": "2025-01-01", "drug_scheme": "ADT_ENZALUTAMIDE",
                 "line_of_therapy_number": "2"},
            ],
        }
        result = build_psa_by_treatment_line(patient)
        assert result["metrics"]["points_between_lines_count"] == 1

    def test_g2005_points_carry_treatment_color(self):
        """H.G2005 — Cada point en output incluye treatment_color de banda."""
        patient = {
            "biomarker_longitudinal": [
                {"sample_date": "2024-06-01", "biomarker_type": "PSA", "value": 5.0},
            ],
            "treatments": [
                {"start_date": "2024-01-01", "drug_scheme": "ADT_MONO",
                 "line_of_therapy_number": "1"},
            ],
        }
        result = build_psa_by_treatment_line(patient)
        point = result["points"][0]
        assert "treatment_color" in point

    def test_g2006_no_psa_data_returns_empty_metrics(self):
        """H.G2006 — Sin PSA data, metrics vacíos pero estructura intacta."""
        patient = {"treatments": []}
        result = build_psa_by_treatment_line(patient)
        assert result["has_data"] is False
        assert result["points"] == []

    def test_g2007_treatment_bands_still_returned(self):
        """H.G2007 — treatment_bands sigue funcionando (no regresión)."""
        patient = {
            "biomarker_longitudinal": [
                {"sample_date": "2024-06-01", "biomarker_type": "PSA", "value": 5.0},
            ],
            "treatments": [
                {"start_date": "2024-01-01", "drug_scheme": "ADT_MONO",
                 "line_of_therapy_number": "1"},
            ],
        }
        result = build_psa_by_treatment_line(patient)
        assert len(result["treatment_bands"]) == 1

    def test_g2008_line_segments_still_returned(self):
        """H.G2008 — line_segments sigue funcionando (no regresión)."""
        patient = {
            "biomarker_longitudinal": [
                {"sample_date": "2024-06-01", "biomarker_type": "PSA", "value": 5.0},
                {"sample_date": "2024-09-01", "biomarker_type": "PSA", "value": 3.0},
            ],
            "treatments": [
                {"start_date": "2024-01-01", "drug_scheme": "ADT_MONO",
                 "line_of_therapy_number": "1"},
            ],
        }
        result = build_psa_by_treatment_line(patient)
        assert len(result["line_segments"]) == 1
        assert result["line_segments"][0]["point_count"] == 2

    def test_g2009_line_events_still_returned(self):
        """H.G2009 — line_events siguen funcionando (no regresión)."""
        patient = {
            "biomarker_longitudinal": [
                {"sample_date": "2024-06-01", "biomarker_type": "PSA", "value": 5.0},
            ],
            "treatments": [
                {"start_date": "2024-01-01", "drug_scheme": "ADT_MONO",
                 "line_of_therapy_number": "1"},
            ],
        }
        result = build_psa_by_treatment_line(patient)
        assert len(result["line_events"]) >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Sección D — Smoke E2E con treatments[] preconfigurados (H.G2010-H.G2015)
# ─────────────────────────────────────────────────────────────────────────────


class TestSectionDSmokeIntakeToTorreDrillDown:
    """Smoke E2E: paciente con treatments[] preconfigurados (post-canonicalize)
    → build_psa_by_treatment_line consume y produce drill-down completo."""

    def test_g2010_two_lines_drill_down(self):
        """H.G2010 — Paciente con prior + current treatments → torre con 2
        bandas + points drill-down asignados correctamente."""
        patient = {
            "biomarker_longitudinal": [
                {"sample_date": "2024-03-01", "biomarker_type": "PSA", "value": 30.0},
                {"sample_date": "2024-09-01", "biomarker_type": "PSA", "value": 8.0},
                {"sample_date": "2025-03-01", "biomarker_type": "PSA", "value": 1.5},
                {"sample_date": "2026-01-01", "biomarker_type": "PSA", "value": 5.0},
            ],
            "treatments": [
                {"start_date": "2024-02-01", "end_date": "2024-12-15",
                 "drug_scheme": "ADT_MONO", "line_of_therapy_number": "1",
                 "source": "auto-treatment-history (Faubot LXV #63B)"},
                {"start_date": "2024-12-15", "drug_scheme": "ADT_ENZALUTAMIDE",
                 "line_of_therapy_number": "2",
                 "source": "auto-treatment-current (Faubot LXV #63B)"},
            ],
        }
        result = build_psa_by_treatment_line(patient)
        assert result["has_data"] is True
        assert len(result["treatment_bands"]) == 2
        assert result["metrics"]["lines_with_points_count"] >= 2

    def test_g2011_baseline_psa_in_history_drill_down(self):
        """H.G2011 — psa_history (post auto-baseline #63A) debe alimentar
        drill-down correctamente cuando se usa para construir biomarker_long."""
        patient = {
            "biomarker_longitudinal": [
                {"sample_date": "2024-06-01", "biomarker_type": "PSA", "value": 25.0,
                 "source": "auto-baseline (Faubot LXIV #63A)"},
            ],
            "treatments": [
                {"start_date": "2024-06-01", "drug_scheme": "ADT_MONO",
                 "line_of_therapy_number": "1"},
            ],
        }
        result = build_psa_by_treatment_line(patient)
        assert result["has_data"] is True
        assert result["points"][0].get("treatment_line_number") == "1"

    def test_g2012_drill_down_metrics_complete(self):
        """H.G2012 — Métricas drill-down completas: lines_count + pretreatment
        + between_lines."""
        patient = {
            "biomarker_longitudinal": [
                {"sample_date": "2024-03-01", "biomarker_type": "PSA", "value": 30.0},
                {"sample_date": "2024-09-01", "biomarker_type": "PSA", "value": 8.0},
            ],
            "treatments": [
                {"start_date": "2024-01-01", "drug_scheme": "ADT_ENZALUTAMIDE",
                 "line_of_therapy_number": "1"},
            ],
        }
        result = build_psa_by_treatment_line(patient)
        m = result["metrics"]
        assert "lines_with_points_count" in m
        assert "points_pretreatment_count" in m
        assert "points_between_lines_count" in m
        assert "current_psa" in m
        assert "nadir_psa" in m

    def test_g2013_no_treatments_falls_back_gracefully(self):
        """H.G2013 — Sin treatments, torre retorna has_data=True pero todos
        points se marcan no_bands (graceful degradation)."""
        patient = {
            "biomarker_longitudinal": [
                {"sample_date": "2024-06-01", "biomarker_type": "PSA", "value": 25.0},
            ],
        }
        result = build_psa_by_treatment_line(patient)
        assert result["has_data"] is True
        assert result["points"][0].get("treatment_assignment_origin") == "no_bands"

    def test_g2014_reason_for_change_traceable_in_treatments(self):
        """H.G2014 — reason_for_change persistido en treatments[] llega
        intacto sin que build_psa_by_treatment_line lo descarte."""
        patient = {
            "biomarker_longitudinal": [
                {"sample_date": "2024-06-01", "biomarker_type": "PSA", "value": 5.0},
            ],
            "treatments": [
                {"start_date": "2024-01-01", "end_date": "2024-12-15",
                 "drug_scheme": "ADT_MONO", "line_of_therapy_number": "1",
                 "reason_for_change": "progression_psa"},
            ],
        }
        result = build_psa_by_treatment_line(patient)
        # build_psa_by_treatment_line no extrae reason_for_change pero
        # tampoco lo destruye en el patient input
        assert patient["treatments"][0].get("reason_for_change") == "progression_psa"
        assert result["has_data"] is True

    def test_g2015_drill_down_color_propagation_e2e(self):
        """H.G2015 — Auditoría #63B end-to-end: treatments+psa → torre →
        cada point dentro de banda tiene treatment_color propagado."""
        patient = {
            "biomarker_longitudinal": [
                {"sample_date": "2024-06-01", "biomarker_type": "PSA", "value": 5.0},
                {"sample_date": "2024-09-01", "biomarker_type": "PSA", "value": 3.0},
            ],
            "treatments": [
                {"start_date": "2024-01-01", "drug_scheme": "ADT_MONO",
                 "line_of_therapy_number": "1"},
            ],
        }
        result = build_psa_by_treatment_line(patient)
        assert result["has_data"] is True
        active_points = [
            p for p in result["points"]
            if p.get("treatment_assignment_origin") == "auto_by_date"
        ]
        assert len(active_points) >= 1
        for point in active_points:
            assert point.get("treatment_color") is not None
            assert point.get("treatment_line_number") == "1"
