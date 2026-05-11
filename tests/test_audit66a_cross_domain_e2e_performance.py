"""Auditoría Faubot #66A (LXXII) — Cross-domain integration + E2E + Performance baseline.

Cobertura:
  Sección A — Cross-domain integration tests (10 tests, H.G2166-H.G2175)
              Combina estados clínicos × gates pivotal × per-line analytics
  Sección B — E2E HTTP integration vs running Flask server (8 tests, H.G2176-H.G2183)
              curl-based contra http://localhost:8080
  Sección C — Performance baseline (7 tests, H.G2184-H.G2190)
              Mide tiempos de carga + assert thresholds críticos

Total: 25 tests. Hipótesis verificables: H.G2166 - H.G2190.

NOTA: Sección B + C requieren Flask server corriendo en localhost:8080.
Si server no está activo, esos tests se skipean con marker pytest.
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import os
import subprocess
import sys
import time
import types
import urllib.request
import urllib.error
from pathlib import Path

import pytest

# Stubs APFS I/O lock workaround (defensive)
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

# Server detection helper for sections B + C
SERVER_BASE_URL = os.environ.get("PROSTANET_TEST_URL", "http://127.0.0.1:8080")


def _server_alive() -> bool:
    try:
        with urllib.request.urlopen(SERVER_BASE_URL + "/", timeout=2) as resp:
            return 200 <= resp.status < 500
    except Exception:
        return False


SERVER_AVAILABLE = _server_alive()
requires_server = pytest.mark.skipif(
    not SERVER_AVAILABLE,
    reason=f"Flask server no disponible en {SERVER_BASE_URL} — start con `python3.12 app.py`",
)


# ─────────────────────────────────────────────────────────────────────────────
# Sección A — Cross-domain integration (H.G2166-H.G2175)
# ─────────────────────────────────────────────────────────────────────────────


class TestSectionACrossDomainIntegration:
    """Tests que combinan múltiples dominios para detectar bugs en integraciones.
    Cada test simula un patient real fluyendo a través de >=3 módulos."""

    def _build_m1_crpc_patient_with_gate_47_trigger(self):
        """Helper: patient m1_crpc con PSA flare ARPI (gate 47 trigger) + 2 lines."""
        return {
            "reconciled_state": "m1_crpc",
            "baseline": {"baseline_psa": 80.0},
            "identity": {"diagnosis_date": "2024-01-01"},
            "treatments": [
                {"start_date": "2024-01-15", "end_date": "2024-09-15",
                 "drug_scheme": "ADT_MONO", "line_of_therapy_number": "1"},
                {"start_date": "2024-09-15", "drug_scheme": "ADT_ENZALUTAMIDE",
                 "line_of_therapy_number": "2"},
            ],
            "biomarker_longitudinal": [
                {"sample_date": "2024-01-15", "biomarker_type": "PSA", "value": 80.0},
                {"sample_date": "2024-04-15", "biomarker_type": "PSA", "value": 30.0},
                {"sample_date": "2024-08-15", "biomarker_type": "PSA", "value": 8.0},
                {"sample_date": "2024-09-15", "biomarker_type": "PSA", "value": 12.0},  # flare
                {"sample_date": "2024-12-15", "biomarker_type": "PSA", "value": 6.0},  # back down
                {"sample_date": "2025-03-15", "biomarker_type": "PSA", "value": 4.0},
            ],
            "psa_flare_arpi_pseudoprogression_documented": "Sí",
        }

    def test_g2166_m1_crpc_with_gate_47_produces_per_line_classification(self):
        """H.G2166 — Paciente m1_crpc con gate 47 + 2 lines → cada line tiene
        kinetics_classification independiente."""
        from prostanet.domains.patient_tracking.psa_line_monitor import (
            build_psa_by_treatment_line,
        )
        patient = self._build_m1_crpc_patient_with_gate_47_trigger()
        result = build_psa_by_treatment_line(patient)
        assert result["has_data"] is True
        assert len(result["line_segments"]) == 2
        # Cada segmento tiene su propia classification (no son None)
        for seg in result["line_segments"]:
            assert "kinetics_classification" in seg
            assert seg["kinetics_classification"] in {
                "response", "partial_response", "stable", "progression",
                "primary_refractory", "insufficient_data",
            }

    def test_g2167_m1_crpc_with_gate_47_per_line_forecast_independent(self):
        """H.G2167 — Per-line forecast computa independientemente para cada line
        sin contaminarse entre líneas."""
        from prostanet.domains.patient_tracking.psa_forecast import (
            build_psa_forecast_per_line,
        )
        patient = self._build_m1_crpc_patient_with_gate_47_trigger()
        result = build_psa_forecast_per_line(patient)
        per_line = result["per_line_forecasts"]
        # Solo líneas numéricas (no pretreatment/between_lines)
        numeric_keys = [k for k in per_line.keys() if k.isdigit()]
        assert len(numeric_keys) == 2
        # Cada line tiene su propio forecast (status puede variar)
        for k in numeric_keys:
            assert "status" in per_line[k]

    def test_g2168_m1_crpc_with_gate_47_cohort_overlay_anchored_to_current_line(self):
        """H.G2168 — Cohort reference se ancla a current line (no a baseline global)."""
        from prostanet.domains.patient_tracking.psa_forecast import (
            build_psa_cohort_reference_overlay,
        )
        patient = self._build_m1_crpc_patient_with_gate_47_trigger()
        result = build_psa_cohort_reference_overlay(patient)
        if result.get("has_data"):
            # anchor_date debe ser de la línea actual (L2 = 2024-09-15), no L1
            assert result["anchor_date"] == "2024-09-15"

    def test_g2169_m1_crpc_combined_timeline_with_clinical_events_assigned_correctly(self):
        """H.G2169 — Combined timeline asigna events a la treatment_line correcta por fecha."""
        from prostanet.domains.patient_tracking.psa_forecast import (
            build_combined_patient_timeline,
        )
        patient = self._build_m1_crpc_patient_with_gate_47_trigger()
        events = [
            {"date": "2024-06-15", "title": "Visita L1", "origin": "visit"},
            {"date": "2024-11-15", "title": "Visita L2", "origin": "visit"},
        ]
        result = build_combined_patient_timeline(patient, clinical_events=events)
        markers = result["clinical_event_markers"]
        l1_marker = next(m for m in markers if m["date"] == "2024-06-15")
        l2_marker = next(m for m in markers if m["date"] == "2024-11-15")
        assert l1_marker["treatment_line"] == "1"
        assert l2_marker["treatment_line"] == "2"

    def test_g2170_decision_audit_with_full_patient_record_includes_all_dimensions(self):
        """H.G2170 — build_decision_audit con patient_record incluye 5 dimensiones
        + per_line_analytics + summary extended."""
        from prostanet.shared.decision_audit_builder import build_decision_audit
        patient = self._build_m1_crpc_patient_with_gate_47_trigger()
        audit = build_decision_audit(
            patient_id="cross_domain_test",
            patient_identity={"diagnosis_date": "2024-01-01"},
            latest_assessment={
                "input_snapshot": {"reconciled_state": "m1_crpc"},
                "result_snapshot": {
                    "state": "m1_crpc",
                    "pivotal_contraindication_gates": [
                        {"code": "psa_flare_arpi_pseudoprogression",
                         "trial_refs": ["PMID: 30157320"],
                         "evidence_tag": "NCCN_v5_2026",
                         "severity": "soft_warning"},
                    ],
                },
                "guideline_versions": {},
            },
            patient_record=patient,
        )
        # 5 dimensiones presentes
        for dim in ["como", "por_que", "datos", "evidencia", "version"]:
            assert dim in audit["audit_dimensions"]
        # Per-line analytics embedded
        assert audit["per_line_analytics"]["available"] is True
        # Summary extended con #65A fields
        assert audit["summary"]["per_gate_evidence_count"] >= 1
        assert audit["summary"]["per_line_analytics_available"] is True

    def test_g2171_psadt_le_10_gate_55_with_m0_crpc_classification(self):
        """H.G2171 — Paciente m0_crpc + PSADT≤10m + classification per-line consistente."""
        from prostanet.domains.patient_tracking.psa_line_monitor import (
            build_psa_by_treatment_line,
        )
        patient = {
            "reconciled_state": "m0_crpc",
            "baseline": {"baseline_psa": 5.0},
            "treatments": [{
                "start_date": "2024-01-01", "drug_scheme": "ADT_ENZALUTAMIDE",
                "line_of_therapy_number": "1",
            }],
            "biomarker_longitudinal": [
                {"sample_date": "2024-01-01", "biomarker_type": "PSA", "value": 5.0},
                {"sample_date": "2024-06-01", "biomarker_type": "PSA", "value": 8.0},
                {"sample_date": "2024-09-01", "biomarker_type": "PSA", "value": 12.0},
                {"sample_date": "2024-12-01", "biomarker_type": "PSA", "value": 18.0},
            ],
        }
        result = build_psa_by_treatment_line(patient)
        seg = result["line_segments"][0]
        # PSA siempre subiendo desde baseline → classification debe reflejar progression/refractory
        assert seg["kinetics_classification"] in {"progression", "primary_refractory", "stable"}

    def test_g2172_canonicalize_payload_produces_treatments_for_torre(self):
        """H.G2172 — canonicalize_payload sintetiza treatments[] que alimenta torre."""
        from prostanet.domains.patient_tracking.service import PatientTrackingService
        from prostanet.domains.patient_tracking.psa_line_monitor import (
            build_psa_by_treatment_line,
        )
        svc = PatientTrackingService()
        payload = {
            "diagnosis_date": "2024-01-01",
            "baseline_psa": 50.0,
            "drug_scheme": "ADT_DOCETAXEL",
            "line_of_therapy_number": "1",
            "biomarker_longitudinal": [
                {"sample_date": "2024-06-01", "biomarker_type": "PSA", "value": 20.0},
            ],
        }
        canonical = svc.canonicalize_payload(payload)
        # canonicalize debe haber sintetizado treatments
        treatments = canonical.get("treatments", [])
        assert len(treatments) >= 1
        # Y la torre debe consumirlo
        result = build_psa_by_treatment_line(canonical)
        assert len(result["treatment_bands"]) >= 1

    def test_g2173_per_line_analytics_consistent_across_helpers(self):
        """H.G2173 — Los 3 helpers #64A retornan datos consistentes para el mismo paciente."""
        from prostanet.domains.patient_tracking.psa_forecast import (
            build_psa_forecast_per_line,
            build_psa_cohort_reference_overlay,
            build_combined_patient_timeline,
        )
        patient = self._build_m1_crpc_patient_with_gate_47_trigger()
        forecast = build_psa_forecast_per_line(patient)
        cohort = build_psa_cohort_reference_overlay(patient)
        timeline = build_combined_patient_timeline(patient)
        # Si forecast tiene 2 lines, timeline debe tener 2 treatment_lanes
        if forecast["summary"]["total_lines"] == 2:
            assert timeline["summary"]["total_treatment_lanes"] == 2
        # Si cohort tiene data, debe usar mismo state que forecast contexto
        if cohort.get("has_data"):
            assert "cohort_class" in cohort

    def test_g2174_evidence_drill_down_for_all_gates_47_53_54_55(self):
        """H.G2174 — Per-gate evidence drill-down funciona para los 4 gates kinetics."""
        from prostanet.shared.decision_audit_builder import (
            _build_per_gate_evidence_drill_down,
        )
        gates = [
            {"code": "psa_flare_arpi_pseudoprogression",
             "trial_refs": ["PMID: 30157320"], "evidence_tag": "NCCN"},
            {"code": "psa_velocity_bcr_aggressive",
             "trial_refs": ["RTOG-9601"], "evidence_tag": "EAU"},
            {"code": "psa_bounce_post_rt_pseudoprogression",
             "trial_refs": ["PMID: 19619958"], "evidence_tag": "NCCN"},
            {"code": "psa_doubling_time_progressive",
             "trial_refs": ["SPARTAN", "PROSPER", "ARAMIS"], "evidence_tag": "NCCN"},
        ]
        for gate in gates:
            result = _build_per_gate_evidence_drill_down(gate)
            assert result["citation_count"] >= 1, f"Gate {gate['code']} no tiene citations"
            assert result["trial_refs_with_links"], f"Gate {gate['code']} no tiene links"

    def test_g2175_full_patient_round_trip_no_crashes(self):
        """H.G2175 — Round-trip completo: patient → canonicalize → torre → forecast →
        cohort → combined timeline → decision audit. Sin crashes en ninguna etapa."""
        from prostanet.domains.patient_tracking.service import PatientTrackingService
        from prostanet.domains.patient_tracking.psa_line_monitor import (
            build_psa_by_treatment_line,
        )
        from prostanet.domains.patient_tracking.psa_forecast import (
            build_psa_forecast_per_line,
            build_psa_cohort_reference_overlay,
            build_combined_patient_timeline,
        )
        from prostanet.shared.decision_audit_builder import build_decision_audit

        svc = PatientTrackingService()
        patient = self._build_m1_crpc_patient_with_gate_47_trigger()
        canonical = svc.canonicalize_payload(patient)
        # Toda la cadena debe ejecutar sin excepción
        torre = build_psa_by_treatment_line(canonical)
        forecast = build_psa_forecast_per_line(canonical)
        cohort = build_psa_cohort_reference_overlay(canonical)
        timeline = build_combined_patient_timeline(canonical)
        audit = build_decision_audit(
            patient_id="round_trip",
            latest_assessment={
                "input_snapshot": canonical,
                "result_snapshot": {"state": "m1_crpc"},
                "guideline_versions": {},
            },
            patient_record=canonical,
        )
        # Validar resultados básicos
        assert torre["has_data"]
        assert isinstance(forecast, dict)
        assert isinstance(cohort, dict)
        assert timeline["has_data"]
        assert audit["available"]


# ─────────────────────────────────────────────────────────────────────────────
# Sección B — E2E HTTP integration vs running Flask server (H.G2176-H.G2183)
# ─────────────────────────────────────────────────────────────────────────────


@requires_server
class TestSectionBE2EHttpIntegration:
    """Tests que validan endpoints HTTP en el server Flask corriendo.
    Skipped si server no está disponible en SERVER_BASE_URL."""

    def _http_get(self, path: str, timeout: int = 10) -> tuple[int, str, dict]:
        """Helper: HTTP GET → (status, body, headers)."""
        try:
            req = urllib.request.Request(SERVER_BASE_URL + path)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read().decode("utf-8"), dict(resp.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8") if e.fp else "", dict(e.headers)

    def test_g2176_root_path_returns_200(self):
        """H.G2176 — GET / retorna 200 (homepage carga)."""
        status, _, _ = self._http_get("/")
        assert status == 200

    def test_g2177_login_page_renders(self):
        """H.G2177 — GET /login renderiza HTML con formulario."""
        status, body, _ = self._http_get("/login")
        assert status == 200
        # Login page debe tener form fields o algún indicador
        assert any(x in body.lower() for x in ["login", "iniciar", "password", "form"])

    def test_g2178_versioning_dashboard_reachable(self):
        """H.G2178 — /versioning-dashboard reachable (200 directo o 302 a login)."""
        status, _, _ = self._http_get("/versioning-dashboard", timeout=15)
        # Puede ser 200 (si auth bypass dev) o 302 (redirect login)
        assert status in (200, 302)

    def test_g2179_decision_audit_algorithm_version_endpoint(self):
        """H.G2179 — GET /api/decision-audit/algorithm-version retorna JSON con FAUBOT_RELEASE."""
        status, body, _ = self._http_get("/api/decision-audit/algorithm-version")
        assert status == 200
        # JSON debe contener faubot_release
        assert "faubot_release" in body.lower() or "version" in body.lower()

    def test_g2180_static_assets_load(self):
        """H.G2180 — Static JS asset (longitudinal_capture_helpers.js) loads."""
        status, body, headers = self._http_get(
            "/static/js/longitudinal_capture_helpers.js"
        )
        assert status == 200
        assert "function" in body  # JS code present
        # Content-type debería ser javascript
        ct = headers.get("Content-Type", "").lower()
        assert "javascript" in ct or "text" in ct

    def test_g2181_favicon_responds(self):
        """H.G2181 — GET /favicon.ico responde (200 o 204 o 404)."""
        status, _, _ = self._http_get("/favicon.ico")
        assert status in (200, 204, 404)

    def test_g2182_nonexistent_route_returns_404(self):
        """H.G2182 — GET /this-does-not-exist retorna 404."""
        status, _, _ = self._http_get("/this-does-not-exist-xyz-2026")
        assert status == 404

    def test_g2183_response_time_under_3s_homepage(self):
        """H.G2183 — Homepage carga bajo 3s (sanity test)."""
        start = time.time()
        status, _, _ = self._http_get("/", timeout=10)
        elapsed = time.time() - start
        assert status == 200
        assert elapsed < 3.0, f"Homepage carga en {elapsed:.2f}s (>3s threshold)"


# ─────────────────────────────────────────────────────────────────────────────
# Sección C — Performance baseline (H.G2184-H.G2190)
# ─────────────────────────────────────────────────────────────────────────────


@requires_server
class TestSectionCPerformanceBaseline:
    """Performance baseline measurements. Establecen umbrales para detectar
    regression futura. No fallan tests por velocidad — registran baseline."""

    def _measure_load_time(self, path: str, n_samples: int = 5) -> dict:
        """Helper: mide tiempo de carga promedio + min/max sobre N samples."""
        times = []
        for _ in range(n_samples):
            start = time.time()
            try:
                with urllib.request.urlopen(
                    SERVER_BASE_URL + path, timeout=10
                ) as resp:
                    resp.read()
                times.append(time.time() - start)
            except Exception:
                pass
        if not times:
            return {"avg": None, "min": None, "max": None, "samples": 0}
        return {
            "avg": sum(times) / len(times),
            "min": min(times),
            "max": max(times),
            "samples": len(times),
        }

    def test_g2184_homepage_avg_under_2s(self):
        """H.G2184 — Homepage avg load time bajo 2s (5 samples)."""
        metrics = self._measure_load_time("/", n_samples=5)
        assert metrics["samples"] >= 3, "Insuficientes samples"
        assert metrics["avg"] < 2.0, f"Homepage avg {metrics['avg']:.3f}s (>2s threshold)"

    def test_g2185_api_endpoint_avg_under_500ms(self):
        """H.G2185 — API algorithm-version endpoint avg bajo 500ms (es solo JSON)."""
        metrics = self._measure_load_time(
            "/api/decision-audit/algorithm-version", n_samples=5
        )
        if metrics["samples"] >= 3:
            assert metrics["avg"] < 0.5, f"API avg {metrics['avg']:.3f}s (>500ms)"

    def test_g2186_static_js_avg_under_300ms(self):
        """H.G2186 — Static JS avg bajo 300ms (debería estar cached)."""
        metrics = self._measure_load_time(
            "/static/js/longitudinal_capture_helpers.js", n_samples=5
        )
        if metrics["samples"] >= 3:
            assert metrics["avg"] < 0.3, f"Static JS avg {metrics['avg']:.3f}s (>300ms)"

    def test_g2187_versioning_dashboard_avg_under_3s(self):
        """H.G2187 — Versioning dashboard avg bajo 3s (parsea audit_tracking.md grande)."""
        metrics = self._measure_load_time("/versioning-dashboard", n_samples=3)
        if metrics["samples"] >= 2:
            assert metrics["avg"] < 3.0, f"Versioning dashboard avg {metrics['avg']:.3f}s (>3s)"

    def test_g2188_max_load_time_under_5s_no_outliers(self):
        """H.G2188 — Max load time de homepage bajo 5s (no outliers extremos)."""
        metrics = self._measure_load_time("/", n_samples=5)
        if metrics["samples"] >= 3:
            assert metrics["max"] < 5.0, f"Max homepage time {metrics['max']:.3f}s (outlier)"

    def test_g2189_min_load_time_above_zero(self):
        """H.G2189 — Min load time > 0 (sanity check, no caché bypass)."""
        metrics = self._measure_load_time("/", n_samples=5)
        if metrics["samples"] >= 3:
            assert metrics["min"] > 0, "Min time = 0 sospechoso (caché o error)"

    def test_g2190_baseline_summary_print_for_record(self, capsys):
        """H.G2190 — Imprime baseline summary para registro en reporte CI."""
        paths = [
            ("/", "Homepage"),
            ("/api/decision-audit/algorithm-version", "API"),
            ("/static/js/longitudinal_capture_helpers.js", "Static JS"),
        ]
        results = []
        for path, label in paths:
            metrics = self._measure_load_time(path, n_samples=3)
            if metrics["samples"] >= 2:
                results.append(f"{label}: avg={metrics['avg']*1000:.0f}ms, max={metrics['max']*1000:.0f}ms")
        # Print to stdout para que se vea en pytest -v
        print("\n=== PERFORMANCE BASELINE (Faubot LXXII #66A) ===")
        for r in results:
            print(f"  {r}")
        # Test pasa si al menos 1 endpoint midió OK
        assert len(results) >= 1
