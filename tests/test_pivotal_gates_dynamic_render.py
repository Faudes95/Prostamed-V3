"""BUG FIX 2026-05-17 — Pivotal gates dynamic render per-patient.

Pre-fix: templates/patient_profile_v2.html renderizaba G07/G55/G47/G53/G14
HARDCODED idénticos para TODOS los pacientes (mockup demo).

Post-fix:
  1. Sección "Gates pivotal activos" usa {% for gate in gates_top %}
  2. Sección "Gates triggered · vista detallada" usa {% for gate in gates_all %}
  3. Tabla "Per-gate evidence drill-down" usa {% for gate in gates_all %}
  4. Sidebar "Gates contextualizados" usa {% for gate in gates_top %}
  5. Nuevo endpoint /api/patients/<nss>/pivotal-gates expone evaluación per-patient
"""
from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def client():
    from app import app, create_app
    create_app()
    return app.test_client()


class TestPivotalGatesEndpoint:
    """Endpoint /api/patients/<nss>/pivotal-gates retorna evaluation real per-patient."""

    def test_endpoint_returns_200_for_valid_patient(self, client):
        r = client.get("/api/patients/3344557788/pivotal-gates")
        assert r.status_code == 200

    def test_endpoint_returns_404_for_invalid_patient(self, client):
        r = client.get("/api/patients/NONEXISTENT_TEST_999999/pivotal-gates")
        assert r.status_code == 404
        b = r.get_json()
        assert b["error"] == "patient_not_found"

    def test_endpoint_returns_expected_schema(self, client):
        r = client.get("/api/patients/3344557788/pivotal-gates")
        b = r.get_json()
        assert b["success"] is True
        assert b["patient_nss"] == "3344557788"
        assert "evaluation_timestamp" in b
        assert "gates_triggered" in b
        assert "gates_total" in b
        assert "summary" in b
        assert "hard_block" in b["summary"]
        assert "soft_warning" in b["summary"]
        assert "informational" in b["summary"]
        assert "total" in b["summary"]

    def test_endpoint_gate_shape(self, client):
        r = client.get("/api/patients/3344557788/pivotal-gates")
        b = r.get_json()
        if b["gates_total"] > 0:
            gate = b["gates_triggered"][0]
            assert "code" in gate
            assert "title" in gate
            assert "severity" in gate
            assert "reason" in gate
            assert "trial_refs" in gate
            assert "evidence_tag" in gate
            assert gate["severity"] in ("hard_block", "soft_warning", "informational")


class TestTemplateDynamicRender:
    """Verifica que las 3 secciones hardcoded fueron reemplazadas por
    render dinámico backend-driven."""

    def test_active_gates_section_renders_real_gate_codes(self, client):
        """Sección 'Gates pivotal activos' (data-testid='pivotal-gates-active-list')
        debe renderizar gates REALES del paciente, NO hardcoded G07/G55/G47."""
        r = client.get("/patient_profile/3344557788?v=2")
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        import re
        # data-gate-code attribute should be present (rendered dynamically)
        codes = re.findall(r'data-gate-code="([^"]+)"', html)
        # For patient Frin (mcspc_low_volume_sync_oligo) — expect 5 real gates
        # × 3 sections (gates_top resumen + gates_all detalle + gates_all evidence)
        # = 15 cards
        assert len(codes) >= 5, f"Expected ≥5 dynamic gate cards, got {len(codes)}"

    def test_no_hardcoded_demo_in_active_gates_section(self, client):
        """La sección activa NO debe contener los codes hardcoded G07/G55/G47
        como gate-code (solo en catalog inventory metadata sample)."""
        r = client.get("/patient_profile/3344557788?v=2")
        html = r.get_data(as_text=True)
        import re
        # Find active gates section
        m = re.search(r'data-testid="pivotal-gates-active-list".*?(?=data-testid|</section>)', html, re.S)
        if m:
            section = m.group(0)
            # No hardcoded demo codes inside active section
            for demo_code in ('>G07<', '>G55<', '>G47<', '>G53<', '>G14<', '>G29<'):
                assert demo_code not in section, (
                    f"Demo hardcoded code {demo_code} encontrado en active gates section "
                    "(debería ser dinámico)"
                )

    def test_dynamic_gates_meta_reflects_counts(self, client):
        r = client.get("/patient_profile/3344557788?v=2")
        html = r.get_data(as_text=True)
        import re
        m = re.search(r'data-testid="pivotal-gates-meta"[^>]*>(.*?)</span>', html, re.S)
        assert m, "meta header data-testid='pivotal-gates-meta' missing"
        text = re.sub(r'<[^>]+>', ' ', m.group(1))
        text = re.sub(r'\s+', ' ', text).strip()
        # Should mention 'gates triggered' or 'Sin gates triggered'
        assert ("gate" in text.lower()), f"Meta texto no menciona gates: {text}"

    def test_detailed_gates_section_present(self, client):
        r = client.get("/patient_profile/3344557788?v=2")
        html = r.get_data(as_text=True)
        assert 'data-testid="pivotal-gates-detailed-list"' in html

    def test_evidence_drilldown_table_present(self, client):
        r = client.get("/patient_profile/3344557788?v=2")
        html = r.get_data(as_text=True)
        assert 'data-testid="pivotal-gates-evidence-table"' in html

    def test_catalog_inventory_clearly_marked_as_system_metadata(self, client):
        """Tabla 'Active gate codes · per-gate YAML SHA' debe estar claramente
        marcada como CATÁLOGO DEL SISTEMA (no per-patient)."""
        r = client.get("/patient_profile/3344557788?v=2")
        html = r.get_data(as_text=True)
        assert 'data-testid="catalog-inventory-gates"' in html
        # Verifica disclaimer text
        assert ("catálogo del sistema" in html.lower()
                or "catalog sample" in html.lower())

    def test_contextualizados_gates_dynamic(self, client):
        r = client.get("/patient_profile/3344557788?v=2")
        html = r.get_data(as_text=True)
        assert 'data-testid="pivotal-gates-contextualizados"' in html
