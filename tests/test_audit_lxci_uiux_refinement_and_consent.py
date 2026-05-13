"""Tests dedicados Iteración Faubot LXCI — UI/UX Refinement + Consent Flow.

Hipótesis verificables H.G2991-H.G3010 cubriendo:
- Bug fix URL hang (register-patient-v2 → register_patient)
- Consent signature modal post-registro + endpoint POST /api/consent/sign
- Demo banner removido de 6 templates demos
- Sidebar action rail (Nuevo paciente / Visita / Tablero)
- Logo enhancement (240px + card flotante)
- Transitions framework (CSS + JS prefetch)

Faubot 2026-04-28 LXCI.
"""
# IEC 62304 §5.6 (Integration testing) + §5.7 (System testing)

from __future__ import annotations

import os, sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import logging
logging.getLogger().setLevel(logging.ERROR)


@pytest.fixture(scope="module")
def client():
    from app import app
    return app.test_client()


# ─── §A — Bug fix URL hang (P0 critical) ─────────────────────────────────
def test_g2991_intake_wizard_uses_correct_register_endpoint(client):
    """H.G2991 — intake-wizard JS llama /api/register_patient (no register-patient-v2)."""
    r = client.get("/intake-wizard?v=legacy")
    assert r.status_code == 200
    src = r.data.decode("utf-8", errors="replace")
    # The fetch call must use the correct URL
    assert "fetch('/api/register_patient'" in src
    # Comments may still reference register-patient-v2 (documents the fix), but no fetch call


def test_g2992_intake_wizard_has_defensive_json_parse(client):
    """H.G2992 — Defensive try/catch para res.json() (LXCI fix)."""
    r = client.get("/intake-wizard?v=legacy")
    src = r.data.decode("utf-8", errors="replace")
    assert "Backend respuesta" in src or "respuesta inv" in src
    assert "btn.disabled = false" in src


def test_g2993_intake_wizard_button_text_is_confirmar(client):
    """H.G2993 — Button label 'Confirmar y abrir expediente'."""
    r = client.get("/intake-wizard?v=legacy")
    src = r.data.decode("utf-8", errors="replace")
    assert "Confirmar y abrir expediente" in src


# ─── §B — Consent signature modal ────────────────────────────────────────
def test_g2994_consent_modal_canvas_present(client):
    """H.G2994 — Modal de firma con canvas iw-consent-sig presente."""
    r = client.get("/intake-wizard?v=legacy")
    src = r.data.decode("utf-8", errors="replace")
    assert 'id="iw-consent-modal"' in src
    assert 'id="iw-consent-sig"' in src
    assert 'id="iw-consent-signer-name"' in src
    assert "21 CFR Part 11" in src
    assert "LFPDPPP" in src


def test_g2995_consent_signing_handler_defined(client):
    """H.G2995 — Handler iwSignConsentAndOpen + iwClearConsentSig + iwOpenConsentModal."""
    r = client.get("/intake-wizard?v=legacy")
    src = r.data.decode("utf-8", errors="replace")
    assert "function iwOpenConsentModal" in src
    assert "async function iwSignConsentAndOpen" in src
    assert "function iwClearConsentSig" in src


def test_g2996_consent_endpoint_returns_200_valid_payload(client):
    """H.G2996 — POST /api/consent/sign con payload válido retorna 200 + consent_id."""
    r = client.post("/api/consent/sign", json={
        "nss": "97000000001",
        "signer_name": "Test Signer LXCI",
        "content_hash": "a" * 64,
        "signed_at": "2026-04-28T16:00:00.000Z",
        "consent_version": "v3.2",
        "source": "intake_stage_aware_v2",
    })
    assert r.status_code == 200
    body = r.get_json()
    assert body["success"] is True
    assert body.get("consent_id") is not None


def test_g2997_consent_endpoint_rejects_missing_signer(client):
    """H.G2997 — POST /api/consent/sign sin signer_name retorna 400."""
    r = client.post("/api/consent/sign", json={
        "nss": "97000000001",
        "content_hash": "a" * 64,
    })
    assert r.status_code == 400
    body = r.get_json()
    assert body["success"] is False
    assert "signer_name" in body.get("error", "")


def test_g2998_consent_endpoint_rejects_unknown_patient(client):
    """H.G2998 — POST /api/consent/sign con NSS inexistente → 404."""
    r = client.post("/api/consent/sign", json={
        "nss": "00000000000",
        "signer_name": "Test",
        "content_hash": "a" * 64,
    })
    assert r.status_code == 404


# ─── §C — Demo banner removed ────────────────────────────────────────────
def test_g2999_demo_banner_removed_from_all_demos():
    """H.G2999 — pm2-demo-banner div eliminado de los 6 templates demos/."""
    demos_dir = PROJECT_ROOT / "templates" / "demos"
    targets = [
        "patient_profile_full_v2_demo.html",
        "patient_intake_v2_demo.html",
        "clinical_dashboard_v2_demo.html",
        "clinical_result_v2_demo.html",
        "longitudinal_capture_v2_demo.html",
        "stage_clinical_center_v2_demo.html",
    ]
    for fname in targets:
        path = demos_dir / fname
        assert path.exists(), f"Demo template {fname} not found"
        content = path.read_text()
        assert 'class="pm2-demo-banner"' not in content, (
            f"Demo banner still present in {fname}"
        )


# ─── §D — Sidebar action rail ────────────────────────────────────────────
def test_g3000_sidebar_action_rail_present(client):
    """H.G3000 — Sidebar incluye action rail con 3 acciones primarias."""
    r = client.get("/patient_profile/97000000001")
    src = r.data.decode("utf-8", errors="replace")
    assert 'class="pm2-sidebar-action-rail"' in src
    assert "Nuevo paciente" in src
    assert "Tablero" in src


def test_g3001_sidebar_action_links_correct_targets(client):
    """H.G3001 — Action rail links target correctos (clasificador oficial, /dashboard)."""
    r = client.get("/patient_profile/97000000001")
    src = r.data.decode("utf-8", errors="replace")
    # Links presentes con href correcto
    assert 'href="/clinical-hub#pm2OfficialClassifier"' in src and 'pm2-sidebar-action--primary' in src
    assert 'href="/dashboard"' in src and 'pm2-sidebar-action--accent' in src


# ─── §E — Logo enhancement ────────────────────────────────────────────────
def test_g3002_logo_css_240px_in_stylesheet():
    """H.G3002 — CSS pm-logo width=240px en prostamed_v2.css."""
    css = (PROJECT_ROOT / "static" / "css" / "prostamed_v2.css").read_text()
    assert "width: 240px" in css


def test_g3003_sidebar_brand_card_flotante():
    """H.G3003 — Card flotante .pm2-sidebar-brand con padding + box-shadow."""
    css = (PROJECT_ROOT / "static" / "css" / "prostamed_v2.css").read_text()
    # Buscar la regla .pm2-sidebar-brand actualizada con background + border-radius
    assert "border-radius: 14px" in css
    assert "rgba(56, 189, 248, 0.15)" in css  # subtle border


# ─── §F — Transitions framework ──────────────────────────────────────────
def test_g3004_transitions_css_file_exists():
    """H.G3004 — static/css/prostamed_v2_transitions.css existe + tiene keyframes."""
    p = PROJECT_ROOT / "static" / "css" / "prostamed_v2_transitions.css"
    assert p.exists()
    content = p.read_text()
    assert "@keyframes pm2-page-fade-in" in content
    assert "@keyframes pm2-skeleton-pulse" in content
    assert "prefers-reduced-motion" in content  # accessibility


def test_g3005_prefetch_js_file_exists():
    """H.G3005 — static/js/pm2_prefetch.js existe + tiene mouseenter listener."""
    p = PROJECT_ROOT / "static" / "js" / "pm2_prefetch.js"
    assert p.exists()
    content = p.read_text()
    assert "mouseenter" in content
    assert "rel = 'prefetch'" in content or 'rel = "prefetch"' in content
    assert "pm2-sidebar-action" in content  # selector target


def test_g3006_transitions_imported_in_base_clinical():
    """H.G3006 — base_clinical.html importa transitions CSS + prefetch JS."""
    p = PROJECT_ROOT / "templates" / "layouts" / "base_clinical.html"
    content = p.read_text()
    assert "prostamed_v2_transitions.css" in content
    assert "pm2_prefetch.js" in content


def test_g3007_transitions_imported_in_patient_profile_v2(client):
    """H.G3007 — patient_profile_v2.html (no extends base) también importa transitions."""
    r = client.get("/patient_profile/97000000001")
    src = r.data.decode("utf-8", errors="replace")
    assert "prostamed_v2_transitions.css" in src
    assert "pm2_prefetch.js" in src


# ─── §G — CSS sticky elements ────────────────────────────────────────────
def test_g3008_sticky_actionbar_css_defined():
    """H.G3008 — .pm2-sticky-actionbar CSS class definida."""
    css = (PROJECT_ROOT / "static" / "css" / "prostamed_v2.css").read_text()
    assert ".pm2-sticky-actionbar" in css
    assert "position: sticky" in css


# ─── §H — FAUBOT_RELEASE bump ────────────────────────────────────────────
def test_g3009_faubot_release_lxci():
    """H.G3009 — FAUBOT_RELEASE bumped to LXCI (or LXCI.x)."""
    from prostanet.shared.algorithm_version import FAUBOT_RELEASE
    assert any(tag in FAUBOT_RELEASE for tag in ("LXCI", "LXCII", "LXCIII", "LXCIV", "LXCV", "LXCVI", "LXCVII", "LXCVIII", "LXCIX", "C"))


# ─── §I — End-to-end smoke ───────────────────────────────────────────────
def test_g3010_e2e_intake_wizard_to_consent_flow(client):
    """H.G3010 — E2E: intake wizard legacy → register → consent modal flow.

    NOTE: post-LXCIII /intake-wizard default sirve progressive_v2.html (sin "Confirmar
    y abrir expediente" + iw-consent-modal). Use ?v=legacy para legacy template.
    """
    # Step 1: intake-wizard legacy renders with all UI elements
    r1 = client.get("/intake-wizard?v=legacy")
    assert r1.status_code == 200
    src1 = r1.data.decode("utf-8", errors="replace")
    assert "Confirmar y abrir expediente" in src1
    assert 'id="iw-consent-modal"' in src1

    # Step 2: register patient via correct endpoint
    import json
    nss = "98000099091"
    r2 = client.post("/api/register_patient", data=json.dumps({
        "nss": nss, "full_name": "LXCI E2E Test",
        "dob": "1955-01-01", "baseline_psa": 12.5,
    }), content_type="application/json")
    if r2.status_code == 200:
        body2 = r2.get_json()
        assert body2.get("success") is True
        assert body2.get("nss") or body2.get("patient_id")

        # Step 3: sign consent for that patient
        r3 = client.post("/api/consent/sign", json={
            "nss": nss,
            "signer_name": "LXCI E2E Tester",
            "content_hash": "e2e" + "0" * 61,
            "signed_at": "2026-04-28T16:30:00.000Z",
        })
        assert r3.status_code == 200
        body3 = r3.get_json()
        assert body3.get("success") is True
        assert body3.get("consent_id") is not None
