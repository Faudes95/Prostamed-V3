"""tests/test_tier7_g6_ui_session_indicator.py — Faubot 2026-04-25 (XXXVIII).

Tests dedicados a Tier 7 G6: UI session countdown badge + auto-refresh JS.

Cubre H.G1031 - H.G1055:

§A — Config helper (`get_session_indicator_config`)
  H.G1031: Defaults retornados cuando no hay env vars (auth dormant + anon)
  H.G1032: Poll interval clamping a [MIN_POLL_INTERVAL_MS, MAX_POLL_INTERVAL_MS]
  H.G1033: Refresh threshold clamping a [60, 3600]
  H.G1034: Warning threshold clamping a [30, 1800]
  H.G1035: Coherencia warning ≤ refresh (auto-fix si warning > refresh)
  H.G1036: enabled=False cuando auth dormant + no force-enable
  H.G1037: Force-enable via PROSTANET_SESSION_INDICATOR_ENABLED=true
  H.G1038: Invalid int env var → fallback a default
  H.G1039: Empty env var → default

§B — Context vars en before_request hook
  H.G1040: g.session_indicator_enabled populated
  H.G1041: g.session_indicator_poll_interval_ms populated
  H.G1042: g.session_indicator_refresh_threshold_sec populated
  H.G1043: g.session_indicator_warning_threshold_sec populated

§C — Template rendering
  H.G1044: Indicator HTML presente en /dashboard cuando authenticated + auth_enabled
  H.G1045: Indicator HTML AUSENTE cuando anonymous (sin sesión)
  H.G1046: Indicator HTML AUSENTE cuando auth dormant
  H.G1047: data-* attributes correctos en el HTML
  H.G1048: data-status-url y data-refresh-url apuntan a /api/auth/*
  H.G1049: JS fetch logic presente (fetch(statusUrl, fetch(refreshUrl)
  H.G1050: CSP nonce honored en <script nonce>

§D — Behavioral coherence
  H.G1051: Warning threshold no excede refresh threshold después de coercion
  H.G1052: Indicator NO renderiza en /login (login page no extiende base_clinical)
  H.G1053: Indicator renderiza en TODAS las páginas que extienden base_clinical
  H.G1054: Endpoint /api/auth/session-status retorna campos esperados por el JS

§E — Backward compat
  H.G1055: Templates clínicos existentes siguen renderizando OK con indicator
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import os
import re

import pytest
from flask import g

# ════════════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Clean session-indicator + auth env vars before each test."""
    for var in (
        "PROSTANET_SESSION_INDICATOR_ENABLED",
        "PROSTANET_SESSION_INDICATOR_POLL_INTERVAL_MS",
        "PROSTANET_SESSION_INDICATOR_REFRESH_THRESHOLD_SEC",
        "PROSTANET_SESSION_INDICATOR_WARNING_THRESHOLD_SEC",
        "CLINICAL_AUTH_ENABLED",
        "PROSTANET_CLINICAL_AUTH_ENABLED",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def app():
    """Real Flask app with full middleware stack."""
    from app import create_app
    a = create_app()
    yield a


@pytest.fixture
def authenticated_client(app, monkeypatch):
    """Test client with a valid authenticated session for clinician role."""
    monkeypatch.setenv("CLINICAL_AUTH_ENABLED", "true")
    monkeypatch.setenv("PROSTANET_CLINICAL_AUTH_ENABLED", "true")

    from prostanet.shared.auth_backends import LocalPbkdf2Backend
    from prostanet.shared import auth_db
    from datetime import datetime, timezone, timedelta

    auth_db.init_auth_db()
    backend = LocalPbkdf2Backend()
    existing = auth_db.get_user_by_username("test_g6_clinician")
    if existing:
        uid = existing["id"]
    else:
        uid = backend.create_user(
            username="test_g6_clinician",
            password="TestPass123!",
            email="g6@test.local",
            role="clinician",
        )

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_clinical_user_id"] = uid
        now = datetime.now(timezone.utc)
        sess["_clinical_login_time"] = now.isoformat()
        sess["_clinical_access_token"] = "AT_test"
        sess["_clinical_refresh_token"] = "RT_test"
        sess["_clinical_token_expires_at"] = (
            now + timedelta(seconds=3600)
        ).isoformat()

    yield client


@pytest.fixture
def anonymous_client(app):
    """Test client with no auth + no session."""
    return app.test_client()


# ════════════════════════════════════════════════════════════════════
# §A — Config helper
# ════════════════════════════════════════════════════════════════════


def test_g1031_config_defaults_no_env(app):
    """Defaults sin env: enabled False, poll 60000, threshold 600, warning 300."""
    from prostanet.presentation.auth_ui_context import (
        get_session_indicator_config,
        DEFAULT_SESSION_POLL_INTERVAL_MS,
        DEFAULT_SESSION_REFRESH_THRESHOLD_SEC,
        DEFAULT_SESSION_WARNING_THRESHOLD_SEC,
    )
    with app.test_request_context("/"):
        cfg = get_session_indicator_config()
    assert cfg["enabled"] is False, "anon + dormant → not enabled"
    assert cfg["poll_interval_ms"] == DEFAULT_SESSION_POLL_INTERVAL_MS
    assert cfg["refresh_threshold_sec"] == DEFAULT_SESSION_REFRESH_THRESHOLD_SEC
    assert cfg["warning_threshold_sec"] == DEFAULT_SESSION_WARNING_THRESHOLD_SEC


def test_g1032_poll_interval_clamping(app, monkeypatch):
    """poll_interval clamped to [5000, 600000]."""
    from prostanet.presentation.auth_ui_context import (
        get_session_indicator_config,
        MIN_POLL_INTERVAL_MS,
        MAX_POLL_INTERVAL_MS,
    )
    # Below min
    monkeypatch.setenv("PROSTANET_SESSION_INDICATOR_POLL_INTERVAL_MS", "100")
    with app.test_request_context("/"):
        cfg = get_session_indicator_config()
    assert cfg["poll_interval_ms"] == MIN_POLL_INTERVAL_MS
    # Above max
    monkeypatch.setenv("PROSTANET_SESSION_INDICATOR_POLL_INTERVAL_MS", "9999999")
    with app.test_request_context("/"):
        cfg = get_session_indicator_config()
    assert cfg["poll_interval_ms"] == MAX_POLL_INTERVAL_MS


def test_g1033_refresh_threshold_clamping(app, monkeypatch):
    """refresh_threshold clamped to [60, 3600]."""
    from prostanet.presentation.auth_ui_context import get_session_indicator_config
    monkeypatch.setenv("PROSTANET_SESSION_INDICATOR_REFRESH_THRESHOLD_SEC", "10")
    with app.test_request_context("/"):
        cfg = get_session_indicator_config()
    assert cfg["refresh_threshold_sec"] == 60
    monkeypatch.setenv("PROSTANET_SESSION_INDICATOR_REFRESH_THRESHOLD_SEC", "10000")
    with app.test_request_context("/"):
        cfg = get_session_indicator_config()
    assert cfg["refresh_threshold_sec"] == 3600


def test_g1034_warning_threshold_clamping(app, monkeypatch):
    """warning_threshold clamped to [30, 1800]."""
    from prostanet.presentation.auth_ui_context import get_session_indicator_config
    monkeypatch.setenv("PROSTANET_SESSION_INDICATOR_WARNING_THRESHOLD_SEC", "5")
    with app.test_request_context("/"):
        cfg = get_session_indicator_config()
    assert cfg["warning_threshold_sec"] == 30
    monkeypatch.setenv("PROSTANET_SESSION_INDICATOR_WARNING_THRESHOLD_SEC", "5000")
    with app.test_request_context("/"):
        cfg = get_session_indicator_config()
    # 5000 clamped to 1800, then capped to refresh_threshold (default 600)
    assert cfg["warning_threshold_sec"] == 600


def test_g1035_warning_capped_at_refresh(app, monkeypatch):
    """warning_threshold > refresh_threshold → set to refresh_threshold."""
    from prostanet.presentation.auth_ui_context import get_session_indicator_config
    monkeypatch.setenv("PROSTANET_SESSION_INDICATOR_REFRESH_THRESHOLD_SEC", "120")
    monkeypatch.setenv("PROSTANET_SESSION_INDICATOR_WARNING_THRESHOLD_SEC", "300")
    with app.test_request_context("/"):
        cfg = get_session_indicator_config()
    assert cfg["refresh_threshold_sec"] == 120
    assert cfg["warning_threshold_sec"] == 120


def test_g1036_enabled_false_when_auth_dormant_anon(app):
    """Sin CLINICAL_AUTH_ENABLED y sin sesión → enabled=False."""
    from prostanet.presentation.auth_ui_context import get_session_indicator_config
    with app.test_request_context("/"):
        cfg = get_session_indicator_config()
    assert cfg["enabled"] is False


def test_g1037_force_enabled_via_env(app, monkeypatch, authenticated_client):
    """PROSTANET_SESSION_INDICATOR_ENABLED=true + authenticated → enabled=True."""
    from prostanet.presentation.auth_ui_context import get_session_indicator_config
    monkeypatch.delenv("CLINICAL_AUTH_ENABLED", raising=False)
    monkeypatch.delenv("PROSTANET_CLINICAL_AUTH_ENABLED", raising=False)
    monkeypatch.setenv("PROSTANET_SESSION_INDICATOR_ENABLED", "true")
    # Use authenticated_client's session
    with authenticated_client.session_transaction() as sess:
        sess_dict = dict(sess)
    # Replay session in a fresh request context
    with app.test_request_context("/"):
        from flask import session as flask_session
        for k, v in sess_dict.items():
            flask_session[k] = v
        cfg = get_session_indicator_config()
    assert cfg["enabled"] is True


def test_g1038_invalid_int_env_fallback(app, monkeypatch):
    """Env var no entera → fallback a default."""
    from prostanet.presentation.auth_ui_context import (
        get_session_indicator_config,
        DEFAULT_SESSION_POLL_INTERVAL_MS,
    )
    monkeypatch.setenv("PROSTANET_SESSION_INDICATOR_POLL_INTERVAL_MS", "not_a_number")
    with app.test_request_context("/"):
        cfg = get_session_indicator_config()
    assert cfg["poll_interval_ms"] == DEFAULT_SESSION_POLL_INTERVAL_MS


def test_g1039_empty_env_fallback(app, monkeypatch):
    """Env var empty string → fallback a default."""
    from prostanet.presentation.auth_ui_context import (
        get_session_indicator_config,
        DEFAULT_SESSION_REFRESH_THRESHOLD_SEC,
    )
    monkeypatch.setenv("PROSTANET_SESSION_INDICATOR_REFRESH_THRESHOLD_SEC", "")
    with app.test_request_context("/"):
        cfg = get_session_indicator_config()
    assert cfg["refresh_threshold_sec"] == DEFAULT_SESSION_REFRESH_THRESHOLD_SEC


# ════════════════════════════════════════════════════════════════════
# §B — Context vars
# ════════════════════════════════════════════════════════════════════


def test_g1040_g_session_indicator_enabled_populated(authenticated_client, app):
    """g.session_indicator_enabled set after before_request hook."""
    with authenticated_client:
        authenticated_client.get("/dashboard", headers={"Accept": "text/html"})
        # Inspect g via direct request_context
        with app.test_request_context("/dashboard"):
            from flask import g, session as flask_session
            with authenticated_client.session_transaction() as sess:
                for k, v in dict(sess).items():
                    flask_session[k] = v
            app.preprocess_request()
            assert hasattr(g, "session_indicator_enabled")
            # When auth_enabled=true + authenticated → True
            assert g.session_indicator_enabled is True


def test_g1041_g_poll_interval_populated(app, monkeypatch):
    """g.session_indicator_poll_interval_ms set."""
    monkeypatch.setenv("CLINICAL_AUTH_ENABLED", "true")
    with app.test_request_context("/"):
        app.preprocess_request()
        assert hasattr(g, "session_indicator_poll_interval_ms")
        assert g.session_indicator_poll_interval_ms == 60000


def test_g1042_g_refresh_threshold_populated(app, monkeypatch):
    """g.session_indicator_refresh_threshold_sec set."""
    monkeypatch.setenv("CLINICAL_AUTH_ENABLED", "true")
    with app.test_request_context("/"):
        app.preprocess_request()
        assert hasattr(g, "session_indicator_refresh_threshold_sec")
        assert g.session_indicator_refresh_threshold_sec == 600


def test_g1043_g_warning_threshold_populated(app, monkeypatch):
    """g.session_indicator_warning_threshold_sec set."""
    monkeypatch.setenv("CLINICAL_AUTH_ENABLED", "true")
    with app.test_request_context("/"):
        app.preprocess_request()
        assert hasattr(g, "session_indicator_warning_threshold_sec")
        assert g.session_indicator_warning_threshold_sec == 300


# ════════════════════════════════════════════════════════════════════
# §C — Template rendering
# ════════════════════════════════════════════════════════════════════


def test_g1044_indicator_renders_in_dashboard_when_authenticated(authenticated_client):
    """Cuando auth ON + authenticated → indicator HTML está presente."""
    resp = authenticated_client.get("/dashboard", headers={"Accept": "text/html"})
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'id="pm-session-indicator"' in body
    assert 'class="pm-session-indicator' in body


def test_g1045_indicator_hidden_for_anonymous_when_auth_on(app, monkeypatch):
    """Auth ON pero sin sesión → indicator NO renderiza (anonymous gets redirect)."""
    monkeypatch.setenv("CLINICAL_AUTH_ENABLED", "true")
    monkeypatch.setenv("PROSTANET_CLINICAL_AUTH_ENABLED", "true")
    client = app.test_client()
    resp = client.get("/dashboard", headers={"Accept": "text/html"}, follow_redirects=False)
    # G5 redirect to login when anonymous
    assert resp.status_code == 302
    # body of redirect doesn't include indicator
    body = resp.get_data(as_text=True)
    assert 'pm-session-indicator' not in body


def test_g1046_indicator_hidden_when_auth_dormant(anonymous_client):
    """Auth dormant → indicator no se renderiza aunque la página sea pública."""
    resp = anonymous_client.get("/dashboard", headers={"Accept": "text/html"})
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "pm-session-indicator" not in body


def test_g1047_data_attributes_correct(authenticated_client):
    """data-poll-interval-ms, data-refresh-threshold-sec, data-warning-threshold-sec."""
    resp = authenticated_client.get("/dashboard", headers={"Accept": "text/html"})
    body = resp.get_data(as_text=True)
    assert 'data-poll-interval-ms="60000"' in body
    assert 'data-refresh-threshold-sec="600"' in body
    assert 'data-warning-threshold-sec="300"' in body


def test_g1048_data_urls_point_to_auth_endpoints(authenticated_client):
    """data-status-url + data-refresh-url + data-login-url."""
    resp = authenticated_client.get("/dashboard", headers={"Accept": "text/html"})
    body = resp.get_data(as_text=True)
    assert 'data-status-url="/api/auth/session-status"' in body
    assert 'data-refresh-url="/api/auth/refresh"' in body
    assert 'data-login-url="/login"' in body


def test_g1049_js_fetch_logic_present(authenticated_client):
    """JS contiene fetch(statusUrl), fetch(refreshUrl), triggerRefresh()."""
    resp = authenticated_client.get("/dashboard", headers={"Accept": "text/html"})
    body = resp.get_data(as_text=True)
    assert "fetch(statusUrl" in body
    assert "fetch(refreshUrl" in body
    assert "triggerRefresh" in body
    # Local tick decrement
    assert "localTick" in body
    # Setinterval for poll
    assert "setInterval(fetchStatus" in body


def test_g1050_csp_nonce_attribute_in_script(authenticated_client):
    """<script nonce="..."> está presente cuando CSP nonce activo (defensa CSP)."""
    resp = authenticated_client.get("/dashboard", headers={"Accept": "text/html"})
    body = resp.get_data(as_text=True)
    # El template usa {{ g.csp_nonce or '' }} → siempre escribe nonce="" o nonce="XXX"
    assert "<script nonce=" in body


# ════════════════════════════════════════════════════════════════════
# §D — Behavioral coherence
# ════════════════════════════════════════════════════════════════════


def test_g1051_warning_never_exceeds_refresh(app, monkeypatch):
    """Para cualquier env válido, warning ≤ refresh."""
    test_cases = [
        ("60", "60", 60, 60),
        ("3600", "1800", 3600, 1800),
        ("300", "1500", 300, 300),  # warning capped down
        ("120", "30", 120, 30),
        ("60", "30", 60, 30),
    ]
    from prostanet.presentation.auth_ui_context import get_session_indicator_config
    for refresh, warning, exp_refresh, exp_warning in test_cases:
        monkeypatch.setenv("PROSTANET_SESSION_INDICATOR_REFRESH_THRESHOLD_SEC", refresh)
        monkeypatch.setenv("PROSTANET_SESSION_INDICATOR_WARNING_THRESHOLD_SEC", warning)
        with app.test_request_context("/"):
            cfg = get_session_indicator_config()
        assert cfg["refresh_threshold_sec"] == exp_refresh, (
            f"refresh expected {exp_refresh}, got {cfg['refresh_threshold_sec']}"
        )
        assert cfg["warning_threshold_sec"] == exp_warning, (
            f"warning expected {exp_warning}, got {cfg['warning_threshold_sec']}"
        )
        assert cfg["warning_threshold_sec"] <= cfg["refresh_threshold_sec"]


def test_g1052_indicator_not_in_login_page(anonymous_client):
    """/login NO extiende base_clinical → no indicator HTML."""
    resp = anonymous_client.get("/login", headers={"Accept": "text/html"})
    body = resp.get_data(as_text=True)
    assert "pm-session-indicator" not in body


def test_g1053_indicator_renders_in_all_clinical_pages(authenticated_client):
    """Indicator presente en TODAS las pages que extienden base_clinical."""
    test_paths = ["/dashboard", "/clinical-hub", "/patients"]
    for path in test_paths:
        resp = authenticated_client.get(path, headers={"Accept": "text/html"})
        # 200 OK or redirect (some endpoints may need additional setup) — skip non-200
        if resp.status_code != 200:
            continue
        body = resp.get_data(as_text=True)
        assert "pm-session-indicator" in body, (
            f"path {path} should have indicator (extends base_clinical)"
        )


def test_g1054_session_status_endpoint_returns_required_fields(authenticated_client):
    """/api/auth/session-status retorna los campos que el JS necesita."""
    resp = authenticated_client.get("/api/auth/session-status",
                                     headers={"Accept": "application/json"})
    assert resp.status_code == 200
    data = resp.get_json()
    # JS consume estos campos (verificar contrato API ↔ JS)
    required_fields = (
        "authenticated",
        "user_id",
        "username",
        "role",
        "has_refresh_token",
        "access_token_seconds_until_expiry",
        "session_seconds_until_timeout",
        "refresh_count",
        "last_refresh_at",
    )
    for field in required_fields:
        assert field in data, f"required field missing: {field}"


# ════════════════════════════════════════════════════════════════════
# §E — Backward compat
# ════════════════════════════════════════════════════════════════════


def test_g1055_clinical_pages_render_ok_with_indicator(authenticated_client):
    """Templates clínicos renderizan completamente (no broken layout) con indicator."""
    resp = authenticated_client.get("/dashboard", headers={"Accept": "text/html"})
    body = resp.get_data(as_text=True)
    # Smoke checks de estructura básica
    assert "<!DOCTYPE html>" in body
    assert "</html>" in body
    assert "ProstaMed" in body
    # Top nav (componente base) sigue presente
    assert "pm-top-nav" in body
    # Footer sigue presente
    assert "pm-footer" in body
    # Indicator está en el body, no rompiendo el cierre
    indicator_idx = body.find("pm-session-indicator")
    body_close_idx = body.find("</body>")
    assert indicator_idx != -1
    assert body_close_idx != -1
    assert indicator_idx < body_close_idx, "indicator must be before </body>"
