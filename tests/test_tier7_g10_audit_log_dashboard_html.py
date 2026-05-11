"""tests/test_tier7_g10_audit_log_dashboard_html.py — Faubot 2026-04-25 (XLVI).

Tests dedicados a Tier 7 G10: UI dashboard /audit-log HTML.

Cubre H.G1241 - H.G1265 (25 hipótesis):

§A — Route registration + render
  H.G1241: GET /audit-log dormant mode → 200
  H.G1242: response es text/html (no JSON)
  H.G1243: response contiene marca FAUBOT + título
  H.G1244: extends base_clinical (top_nav presente)

§B — Filter form structure
  H.G1245: form #pm-audit-filters presente con autocomplete=off
  H.G1246: input user_id (number, min=1)
  H.G1247: input endpoint (text, maxlength=100)
  H.G1248: select status con opciones canónicas (authorized, denied_*, etc.)
  H.G1249: input limit (number, min=1, max=500, default 50)
  H.G1250: inputs from + to (datetime-local)
  H.G1251: botón submit + botón clear

§C — Tabla + pagination
  H.G1252: tabla #pm-audit-tbody con 9 columnas
  H.G1253: pagination buttons #pm-audit-prev + #pm-audit-next
  H.G1254: pagination indicator span
  H.G1255: status banner aria-live=polite
  H.G1256: empty state inicial visible

§D — JS fetch logic
  H.G1257: data-api-url="/api/auth/audit-log"
  H.G1258: JS fetch() con credentials=same-origin
  H.G1259: JS escapeHtml previene XSS en user-controlled fields
  H.G1260: redirect a /login en caso de 401

§E — Security + accessibility
  H.G1261: <script nonce="{{ g.csp_nonce }}"> honra CSP
  H.G1262: aria-live + aria-atomic para screen readers
  H.G1263: ABAC enforcement: anonymous + auth ENABLED → 302 redirect a /login
  H.G1264: ABAC enforcement: clinician role + auth ENABLED → 200 (audit:read default)
  H.G1265: passive=True per G7: NO toca last_activity en auth ACTIVE
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest


# ════════════════════════════════════════════════════════════════════
# Fixtures
# ════════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Clean auth env vars before each test."""
    for var in (
        "CLINICAL_AUTH_ENABLED",
        "PROSTANET_CLINICAL_AUTH_ENABLED",
    ):
        monkeypatch.delenv(var, raising=False)
    import importlib
    import prostanet.shared.auth_backends
    importlib.reload(prostanet.shared.auth_backends)


@pytest.fixture
def app():
    from app import create_app
    return create_app()


@pytest.fixture
def client(app):
    return app.test_client()


# ════════════════════════════════════════════════════════════════════
# §A — Route registration + render
# ════════════════════════════════════════════════════════════════════


def test_g1241_get_audit_log_dormant_returns_200(client):
    """H.G1241 — GET /audit-log dormant mode → 200."""
    resp = client.get("/audit-log")
    assert resp.status_code == 200


def test_g1242_response_is_html(client):
    """H.G1242 — response es text/html (no JSON)."""
    resp = client.get("/audit-log")
    assert "text/html" in resp.headers.get("Content-Type", "")
    body = resp.get_data(as_text=True)
    assert body.strip().startswith("<!DOCTYPE html>") or "<html" in body[:200]


def test_g1243_contains_title_and_compliance_marker(client):
    """H.G1243 — response contiene título Audit Log + HIPAA reference."""
    resp = client.get("/audit-log")
    html = resp.get_data(as_text=True)
    assert "Audit Log" in html
    assert "HIPAA" in html
    assert "164.312" in html  # specific section reference


def test_g1244_extends_base_clinical(client):
    """H.G1244 — extends base_clinical (top_nav + footer presentes)."""
    resp = client.get("/audit-log")
    html = resp.get_data(as_text=True)
    # base_clinical.html includes the top_nav macro and pm-footer
    assert "ProstaMed" in html  # nav brand
    assert "pm-footer" in html


# ════════════════════════════════════════════════════════════════════
# §B — Filter form structure
# ════════════════════════════════════════════════════════════════════


def test_g1245_filters_form_present(client):
    """H.G1245 — form #pm-audit-filters presente con autocomplete=off."""
    resp = client.get("/audit-log")
    html = resp.get_data(as_text=True)
    assert 'id="pm-audit-filters"' in html
    assert 'autocomplete="off"' in html


def test_g1246_user_id_input(client):
    """H.G1246 — input user_id (number, min=1)."""
    resp = client.get("/audit-log")
    html = resp.get_data(as_text=True)
    assert 'id="filter-user-id"' in html
    assert 'name="user_id"' in html
    assert 'type="number"' in html


def test_g1247_endpoint_input(client):
    """H.G1247 — input endpoint (text, maxlength=100)."""
    resp = client.get("/audit-log")
    html = resp.get_data(as_text=True)
    assert 'id="filter-endpoint"' in html
    assert 'name="endpoint"' in html
    assert 'maxlength="100"' in html


def test_g1248_status_select_with_canonical_options(client):
    """H.G1248 — select status con opciones canónicas."""
    resp = client.get("/audit-log")
    html = resp.get_data(as_text=True)
    assert 'id="filter-status"' in html
    # Deben aparecer al menos estas opciones canónicas
    expected_options = [
        "authorized",
        "denied_invalid_credentials",
        "denied_session_idle_timeout",
        "denied_session_absolute_timeout",
        "denied_invalid_scope",
        "denied_no_refresh_token",
    ]
    for opt in expected_options:
        assert f'value="{opt}"' in html, f"Missing status option: {opt}"


def test_g1249_limit_input_with_defaults(client):
    """H.G1249 — input limit (number, min=1, max=500, default value=50)."""
    resp = client.get("/audit-log")
    html = resp.get_data(as_text=True)
    assert 'id="filter-limit"' in html
    assert 'name="limit"' in html
    assert 'min="1"' in html
    assert 'max="500"' in html
    assert 'value="50"' in html


def test_g1250_date_range_inputs(client):
    """H.G1250 — inputs from + to (datetime-local)."""
    resp = client.get("/audit-log")
    html = resp.get_data(as_text=True)
    assert 'id="filter-from"' in html
    assert 'id="filter-to"' in html
    assert 'type="datetime-local"' in html


def test_g1251_submit_and_clear_buttons(client):
    """H.G1251 — botón submit + botón clear."""
    resp = client.get("/audit-log")
    html = resp.get_data(as_text=True)
    assert 'type="submit"' in html
    assert "Aplicar filtros" in html
    assert 'id="pm-audit-clear"' in html
    assert "Limpiar" in html


# ════════════════════════════════════════════════════════════════════
# §C — Tabla + pagination
# ════════════════════════════════════════════════════════════════════


def test_g1252_table_with_9_columns(client):
    """H.G1252 — tabla #pm-audit-tbody con 9 columnas."""
    resp = client.get("/audit-log")
    html = resp.get_data(as_text=True)
    assert 'id="pm-audit-tbody"' in html
    expected_headers = [
        "Timestamp", "User", "Endpoint", "Method",
        "Status", "Path", "Reason", "IP", "Backend",
    ]
    for header in expected_headers:
        assert f">{header}<" in html, f"Missing column header: {header}"


def test_g1253_pagination_buttons_present(client):
    """H.G1253 — pagination buttons #pm-audit-prev + #pm-audit-next."""
    resp = client.get("/audit-log")
    html = resp.get_data(as_text=True)
    assert 'id="pm-audit-prev"' in html
    assert 'id="pm-audit-next"' in html
    # Initially disabled (data is loaded via JS)
    assert "Anterior" in html
    assert "Siguiente" in html


def test_g1254_pagination_indicator(client):
    """H.G1254 — pagination indicator span."""
    resp = client.get("/audit-log")
    html = resp.get_data(as_text=True)
    assert "pm-audit-page-indicator" in html


def test_g1255_status_banner_aria_live(client):
    """H.G1255 — status banner aria-live=polite + aria-atomic."""
    resp = client.get("/audit-log")
    html = resp.get_data(as_text=True)
    assert 'aria-live="polite"' in html
    assert 'aria-atomic="true"' in html


def test_g1256_empty_state_initial(client):
    """H.G1256 — empty state inicial visible (mientras JS carga)."""
    resp = client.get("/audit-log")
    html = resp.get_data(as_text=True)
    # Initial loading message
    assert "Cargando audit log…" in html or "Cargando…" in html


# ════════════════════════════════════════════════════════════════════
# §D — JS fetch logic
# ════════════════════════════════════════════════════════════════════


def test_g1257_data_api_url_attribute(client):
    """H.G1257 — data-api-url='/api/auth/audit-log'."""
    resp = client.get("/audit-log")
    html = resp.get_data(as_text=True)
    assert 'data-api-url="/api/auth/audit-log"' in html


def test_g1258_js_fetch_with_credentials(client):
    """H.G1258 — JS fetch() con credentials=same-origin."""
    resp = client.get("/audit-log")
    html = resp.get_data(as_text=True)
    assert "fetch(" in html
    assert "same-origin" in html


def test_g1259_js_escapehtml_xss_protection(client):
    """H.G1259 — JS escapeHtml() previene XSS en user-controlled fields."""
    resp = client.get("/audit-log")
    html = resp.get_data(as_text=True)
    # escapeHtml function should be defined
    assert "escapeHtml" in html
    # Should escape & < > " '
    assert "replace(/&/g" in html
    assert "replace(/</g" in html


def test_g1260_redirect_on_401(client):
    """H.G1260 — JS redirige a /login con error=session_expired si 401."""
    resp = client.get("/audit-log")
    html = resp.get_data(as_text=True)
    assert "401" in html
    assert "/login?error=session_expired" in html


# ════════════════════════════════════════════════════════════════════
# §E — Security + accessibility
# ════════════════════════════════════════════════════════════════════


def test_g1261_csp_nonce_honored_in_inline_script(client):
    """H.G1261 — <script nonce='{{ g.csp_nonce }}'> honra CSP."""
    resp = client.get("/audit-log")
    html = resp.get_data(as_text=True)
    # The nonce attribute must be present (even if empty in dormant mode)
    assert "<script nonce=" in html


def test_g1262_accessibility_aria_attributes(client):
    """H.G1262 — aria-live + aria-atomic + aria-busy attributes presentes."""
    resp = client.get("/audit-log")
    html = resp.get_data(as_text=True)
    assert 'aria-live="polite"' in html
    assert 'aria-atomic="true"' in html
    # aria-busy is set via JS dynamically; we check the JS code includes it
    assert "aria-busy" in html


def test_g1263_anonymous_with_auth_enabled_redirects_to_login(monkeypatch, app):
    """H.G1263 — anonymous + auth ENABLED → 302 redirect a /login (HTML behavior)."""
    monkeypatch.setenv("CLINICAL_AUTH_ENABLED", "true")
    monkeypatch.setenv("PROSTANET_CLINICAL_AUTH_ENABLED", "true")
    client = app.test_client()
    resp = client.get("/audit-log", follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers.get("Location", "")
    assert "/login" in location


def test_g1264_clinician_role_returns_200(monkeypatch, app):
    """H.G1264 — clinician role + auth ENABLED → 200 (audit:read default ABAC)."""
    monkeypatch.setenv("CLINICAL_AUTH_ENABLED", "true")
    monkeypatch.setenv("PROSTANET_CLINICAL_AUTH_ENABLED", "true")

    from prostanet.shared.auth_backends import LocalPbkdf2Backend
    from prostanet.shared import auth_db
    auth_db.init_auth_db()
    backend = LocalPbkdf2Backend()
    existing = auth_db.get_user_by_username("g10_clinician_test")
    uid = existing["id"] if existing else backend.create_user(
        username="g10_clinician_test", password="P@ssw0rd!",
        email="g10_clinician@x.local", role="clinician",
    )

    client = app.test_client()
    now = datetime.now(timezone.utc).isoformat()
    with client.session_transaction() as sess:
        sess["_clinical_user_id"] = uid
        sess["_clinical_login_time"] = now
        sess["_clinical_last_activity"] = now
        sess["_clinical_backend"] = "local_pbkdf2"

    resp = client.get("/audit-log")
    assert resp.status_code == 200, (
        f"clinician should pass; got {resp.status_code} "
        f"body={resp.get_data(as_text=True)[:200]}"
    )
    html = resp.get_data(as_text=True)
    assert "Audit Log" in html


def test_g1265_passive_does_not_touch_last_activity(monkeypatch, app):
    """H.G1265 — GET /audit-log NO toca last_activity (passive=True per G7)."""
    monkeypatch.setenv("CLINICAL_AUTH_ENABLED", "true")
    monkeypatch.setenv("PROSTANET_CLINICAL_AUTH_ENABLED", "true")

    from prostanet.shared.auth_backends import LocalPbkdf2Backend
    from prostanet.shared import auth_db
    auth_db.init_auth_db()
    backend = LocalPbkdf2Backend()
    existing = auth_db.get_user_by_username("g10_passive_test")
    uid = existing["id"] if existing else backend.create_user(
        username="g10_passive_test", password="P@ssw0rd!",
        email="g10_passive@x.local", role="auditor",
    )

    client = app.test_client()
    now = datetime.now(timezone.utc)
    stale = (now - timedelta(seconds=180)).isoformat()
    with client.session_transaction() as sess:
        sess["_clinical_user_id"] = uid
        sess["_clinical_login_time"] = now.isoformat()
        sess["_clinical_last_activity"] = stale
        sess["_clinical_touch_count"] = 7
        sess["_clinical_backend"] = "local_pbkdf2"

    resp = client.get("/audit-log")
    assert resp.status_code == 200

    with client.session_transaction() as sess_after:
        # passive=True → last_activity + touch_count UNCHANGED
        assert sess_after["_clinical_last_activity"] == stale
        assert sess_after["_clinical_touch_count"] == 7
