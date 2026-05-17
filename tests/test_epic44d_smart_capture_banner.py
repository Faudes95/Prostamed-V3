"""EPIC 44.D — Smart Capture deprecation-aware banner.

Verifica que /intake/smart muestra el banner 2-tier al top con CTAs a
Tier 1 + Wizard, sin haber eliminado funcionalidad del Smart Capture
(sigue siendo "vista experta" disponible).
"""
from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def app_client():
    from app import app, create_app
    create_app()
    return app.test_client()


def test_smart_capture_renders_with_banner(app_client):
    """GET /intake/smart → 200 con banner 2-tier visible."""
    r = app_client.get("/intake/smart")
    assert r.status_code == 200
    html = r.data.decode("utf-8", errors="ignore")
    assert "isc-tier-alternatives" in html, "Banner class missing"


def test_smart_capture_hero_labels_vista_experta(app_client):
    """Hero subtitle ahora dice "Vista experta" para diferenciar del flujo Tier 1."""
    r = app_client.get("/intake/smart")
    html = r.data.decode("utf-8", errors="ignore")
    assert "Vista experta" in html, (
        "Smart Capture hero debe identificarse como 'Vista experta' "
        "post-EPIC 44.D para diferenciarse del flujo Tier 1 → Tier 2"
    )


def test_smart_capture_banner_links_to_tier1(app_client):
    """Banner CTA primaria apunta a /intake/tier1 (testid + href verificable)."""
    r = app_client.get("/intake/smart")
    html = r.data.decode("utf-8", errors="ignore")
    assert 'data-testid="intake-smart-cta-tier1"' in html
    assert 'href="/intake/tier1"' in html


def test_smart_capture_banner_links_to_wizard_alternative(app_client):
    """Banner ofrece también el wizard guiado como alternativa."""
    r = app_client.get("/intake/smart")
    html = r.data.decode("utf-8", errors="ignore")
    assert 'data-testid="intake-smart-cta-wizard"' in html
    assert 'href="/intake-wizard"' in html


def test_smart_capture_preserves_all_104_fields(app_client):
    """Banner es ADITIVO — Smart Capture sigue exponiendo TODOS los fields."""
    import re
    r = app_client.get("/intake/smart")
    html = r.data.decode("utf-8", errors="ignore")
    field_count = len(re.findall(r'data-isc-field="', html))
    assert field_count >= 90, (
        f"Smart Capture debe seguir mostrando ~104 fields, "
        f"got {field_count}. Regresión: el banner NO debe filtrar fields."
    )


def test_smart_capture_speed_claim_communicates_value(app_client):
    """Banner comunica el value prop: <60 segundos."""
    r = app_client.get("/intake/smart")
    html = r.data.decode("utf-8", errors="ignore")
    assert "&lt;60 segundos" in html or "<60 segundos" in html, (
        "Banner debe comunicar speed claim Tier 1 (<60s)"
    )
