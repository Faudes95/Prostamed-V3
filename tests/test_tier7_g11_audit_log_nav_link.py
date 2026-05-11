"""tests/test_tier7_g11_audit_log_nav_link.py — Faubot 2026-04-25 (LII).

Tests dedicados a Tier 7 G11: Top nav link a /audit-log para roles con audit:read scope.

Cubre H.G1411 - H.G1417 (7 hipótesis):

§A — Visibility por scope ABAC
  H.G1411: Anonymous (auth dormant + no session) → link AUSENTE
  H.G1412: Auditor role + auth ENABLED → link presente (desktop + mobile)
  H.G1413: Admin role → link presente
  H.G1414: Clinician role → link presente (audit:read default ABAC)

§B — Estructura HTML del link
  H.G1415: href="/audit-log" + texto "Audit Log" + título HIPAA
  H.G1416: Active state aplicado cuando request.path == /audit-log

§C — Imports + integración
  H.G1417: base_clinical.html usa `with context` para top_nav (necesario
           para has_scope + g + request en macro)
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

from datetime import datetime, timezone

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("CLINICAL_AUTH_ENABLED", "PROSTANET_CLINICAL_AUTH_ENABLED"):
        monkeypatch.delenv(var, raising=False)
    import importlib
    import prostanet.shared.auth_backends
    importlib.reload(prostanet.shared.auth_backends)


@pytest.fixture
def app():
    from app import create_app
    return create_app()


def _login_user(app, username, role):
    from prostanet.shared.auth_backends import LocalPbkdf2Backend
    from prostanet.shared import auth_db
    auth_db.init_auth_db()
    backend = LocalPbkdf2Backend()
    existing = auth_db.get_user_by_username(username)
    uid = existing["id"] if existing else backend.create_user(
        username=username, password="P@ssw0rd!",
        email=f"{username}@x.local", role=role,
    )
    client = app.test_client()
    now = datetime.now(timezone.utc).isoformat()
    with client.session_transaction() as sess:
        sess["_clinical_user_id"] = uid
        sess["_clinical_login_time"] = now
        sess["_clinical_last_activity"] = now
        sess["_clinical_backend"] = "local_pbkdf2"
    return client


# ════════════════════════════════════════════════════════════════════
# §A — Visibility por scope ABAC
# ════════════════════════════════════════════════════════════════════


def test_g1411_anonymous_dormant_no_link(app):
    """H.G1411 — Anonymous + auth dormant → link AUSENTE en /audit-log render."""
    client = app.test_client()
    resp = client.get("/audit-log")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    # En dormant + no auth, has_scope returns False → link no renderiza
    assert "pm-nav-audit-link" not in html


def test_g1412_auditor_role_link_visible_desktop_mobile(app, monkeypatch):
    """H.G1412 — Auditor + auth ENABLED → link visible en desktop Y mobile."""
    monkeypatch.setenv("CLINICAL_AUTH_ENABLED", "true")
    monkeypatch.setenv("PROSTANET_CLINICAL_AUTH_ENABLED", "true")
    client = _login_user(app, "g1412_auditor", "auditor")
    resp = client.get("/audit-log")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    # 2 occurrences = desktop nav + mobile nav
    assert html.count("pm-nav-audit-link") == 2


def test_g1413_admin_role_link_visible(app, monkeypatch):
    """H.G1413 — Admin role → link visible (admin tiene todos los scopes)."""
    monkeypatch.setenv("CLINICAL_AUTH_ENABLED", "true")
    monkeypatch.setenv("PROSTANET_CLINICAL_AUTH_ENABLED", "true")
    client = _login_user(app, "g1413_admin", "admin")
    resp = client.get("/audit-log")
    html = resp.get_data(as_text=True)
    assert "pm-nav-audit-link" in html


def test_g1414_clinician_role_link_visible(app, monkeypatch):
    """H.G1414 — Clinician role → link visible (audit:read default ABAC)."""
    monkeypatch.setenv("CLINICAL_AUTH_ENABLED", "true")
    monkeypatch.setenv("PROSTANET_CLINICAL_AUTH_ENABLED", "true")
    client = _login_user(app, "g1414_clinician", "clinician")
    resp = client.get("/audit-log")
    html = resp.get_data(as_text=True)
    assert "pm-nav-audit-link" in html


# ════════════════════════════════════════════════════════════════════
# §B — Estructura HTML del link
# ════════════════════════════════════════════════════════════════════


def test_g1415_link_href_and_label(app, monkeypatch):
    """H.G1415 — href='/audit-log' + texto 'Audit Log' + title HIPAA."""
    monkeypatch.setenv("CLINICAL_AUTH_ENABLED", "true")
    monkeypatch.setenv("PROSTANET_CLINICAL_AUTH_ENABLED", "true")
    client = _login_user(app, "g1415_auditor", "auditor")
    resp = client.get("/audit-log")
    html = resp.get_data(as_text=True)
    assert 'href="/audit-log"' in html
    assert "Audit Log" in html
    # Title attribute con citation HIPAA
    assert "HIPAA §164.312(b)" in html


def test_g1416_active_state_on_audit_log_path(app, monkeypatch):
    """H.G1416 — Active state (`bg-cyan-500`) cuando request.path == /audit-log."""
    monkeypatch.setenv("CLINICAL_AUTH_ENABLED", "true")
    monkeypatch.setenv("PROSTANET_CLINICAL_AUTH_ENABLED", "true")
    client = _login_user(app, "g1416_auditor", "auditor")

    # En /audit-log → link debe tener active state
    resp_active = client.get("/audit-log")
    html_active = resp_active.get_data(as_text=True)
    # Buscar el link audit-log con clase active (bg-cyan-500 text-slate-950)
    # El link tiene class que incluye estas clases si request.path == /audit-log
    assert 'pm-nav-audit-link' in html_active
    # En la línea con pm-nav-audit-link debe aparecer bg-cyan-500
    audit_link_lines = [line for line in html_active.split("\n") if "pm-nav-audit-link" in line]
    # Al menos una línea (desktop) debe tener active state
    has_active_state = any("bg-cyan-500 text-slate-950" in line for line in audit_link_lines)
    assert has_active_state, f"Active state NOT applied. Lines: {audit_link_lines[:2]}"


# ════════════════════════════════════════════════════════════════════
# §C — Imports + integración
# ════════════════════════════════════════════════════════════════════


def test_g1417_base_clinical_uses_with_context_for_top_nav():
    """H.G1417 — base_clinical.html usa `with context` para top_nav (Jinja
    isolation requiere esto para que macro pueda acceder a has_scope + g + request)."""
    base_template = "/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/templates/layouts/base_clinical.html"
    with open(base_template) as f:
        content = f.read()
    # Verificar que el import incluye `with context`
    assert "import top_nav" in content
    assert "with context" in content, (
        "base_clinical.html debe importar top_nav `with context` para que "
        "el macro tenga acceso a has_scope/g/request en el link condicional"
    )
