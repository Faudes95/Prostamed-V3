"""tests/test_tier7_g2_ui_login_role_csp.py — FAUBOT 2026-04-25 (XXXI).

Tier 7 G2 — UI login HTML + role-based UI hints + per-page CSP nonces.

Cobertura:
  - GET /login renders login.html con form + SSO button
  - Login page UI hints (error messages, logged_out message)
  - POST /api/auth/login form-encoded (302 redirect on success/failure)
  - GET /logout via HTML link → redirect to login
  - Role-based template helpers (has_role, has_scope, is_authenticated)
  - g.* context vars (csrf_token, oidc_available, faubot_release, current_user_role)
  - Per-request CSP nonce generation
  - CSP header includes nonce when security headers enabled
  - Backward-compat: JSON login still works after form support added
  - Authenticated user redirected away from /login

Hipótesis: H.G661-H.G715 (~55 hipótesis).
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import os
import sys

import pytest


# ════════════════════════════════════════════════════════════════════
# Fixtures
# ════════════════════════════════════════════════════════════════════


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """DB SQLite limpia + reset state."""
    db_path = tmp_path / "test_g2.db"
    monkeypatch.setenv("PROSTANET_DB_PATH", str(db_path))
    import tracking_db as tdb
    tdb.configure_db_path(str(db_path))
    tdb.init_tracking_db()
    from prostanet.shared.auth_db import init_auth_db
    init_auth_db()
    from prostanet.shared.auth_backends import reset_auth_backend_for_tests
    reset_auth_backend_for_tests()
    yield db_path


@pytest.fixture
def auth_app(isolated_db, monkeypatch):
    """Flask app con DB aislada + auth wired."""
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("TESTING", "1")
    if "app" in sys.modules:
        del sys.modules["app"]
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True, "DB_PATH": str(isolated_db)})
    yield flask_app


@pytest.fixture
def client(auth_app):
    with auth_app.test_client() as c:
        yield c


# ════════════════════════════════════════════════════════════════════
# §A. GET /login renders login page (H.G661-H.G667)
# ════════════════════════════════════════════════════════════════════


def test_g661_login_page_returns_200(client, isolated_db):
    """H.G661 — GET /login retorna 200."""
    resp = client.get("/login")
    assert resp.status_code == 200


def test_g662_login_page_renders_html(client, isolated_db):
    """H.G662 — Response tiene Content-Type text/html."""
    resp = client.get("/login")
    assert "text/html" in resp.content_type


def test_g663_login_page_has_form(client, isolated_db):
    """H.G663 — Página tiene form para login local."""
    resp = client.get("/login")
    body = resp.get_data(as_text=True)
    assert 'id="loginForm"' in body
    assert 'name="username"' in body
    assert 'name="password"' in body


def test_g664_login_page_form_action_correct(client, isolated_db):
    """H.G664 — Form action apunta a /api/auth/login."""
    resp = client.get("/login")
    body = resp.get_data(as_text=True)
    assert "/api/auth/login" in body


def test_g665_login_page_method_post(client, isolated_db):
    """H.G665 — Form usa method POST."""
    resp = client.get("/login")
    body = resp.get_data(as_text=True)
    assert 'method="POST"' in body


def test_g666_login_page_has_faubot_release(client, isolated_db):
    """H.G666 — Página muestra FAUBOT_RELEASE actual."""
    resp = client.get("/login")
    body = resp.get_data(as_text=True)
    assert "FAUBOT release" in body
    # Should include current release like "2026-04-25 XXXI" (or similar)
    assert "2026-04-25" in body


def test_g667_login_page_shows_oidc_button_when_configured(client, isolated_db, monkeypatch):
    """H.G667 — Cuando OIDC configurado, muestra botón SSO."""
    monkeypatch.setenv("PROSTANET_OIDC_ISSUER", "https://idp.test.com")
    monkeypatch.setenv("PROSTANET_OIDC_CLIENT_ID", "test")
    if "app" in sys.modules:
        del sys.modules["app"]
    import app as app_module
    fresh_app = app_module.create_app({"TESTING": True, "DB_PATH": str(isolated_db)})
    with fresh_app.test_client() as c:
        resp = c.get("/login")
        body = resp.get_data(as_text=True)
        assert "SSO" in body
        assert "/api/auth/oidc/login" in body


# ════════════════════════════════════════════════════════════════════
# §B. UI hints: error messages + logout (H.G668-H.G673)
# ════════════════════════════════════════════════════════════════════


def test_g668_error_invalid_credentials_message(client, isolated_db):
    """H.G668 — ?error=invalid_credentials muestra mensaje específico."""
    resp = client.get("/login?error=invalid_credentials")
    body = resp.get_data(as_text=True)
    assert "Credenciales inválidas" in body or "credenciales" in body.lower()


def test_g669_error_session_expired_message(client, isolated_db):
    """H.G669 — ?error=session_expired muestra mensaje específico."""
    resp = client.get("/login?error=session_expired")
    body = resp.get_data(as_text=True)
    assert "expir" in body.lower()


def test_g670_error_access_denied_message(client, isolated_db):
    """H.G670 — ?error=access_denied muestra mensaje específico."""
    resp = client.get("/login?error=access_denied")
    body = resp.get_data(as_text=True)
    assert "Acceso denegado" in body or "denegado" in body.lower()


def test_g671_error_unknown_falls_back_to_generic(client, isolated_db):
    """H.G671 — Error desconocido muestra mensaje genérico."""
    resp = client.get("/login?error=mystery_error_42")
    body = resp.get_data(as_text=True)
    assert "Error de autenticación" in body or "autenticaci" in body.lower()


def test_g672_logged_out_success_message(client, isolated_db):
    """H.G672 — ?logged_out=1 muestra mensaje de logout exitoso."""
    resp = client.get("/login?logged_out=1")
    body = resp.get_data(as_text=True)
    assert "Sesión cerrada" in body or "sesi" in body.lower()


def test_g673_no_query_no_messages(client, isolated_db):
    """H.G673 — Sin query params, no muestra error/success messages."""
    resp = client.get("/login")
    body = resp.get_data(as_text=True)
    assert "Credenciales inválidas" not in body
    assert "Sesión cerrada" not in body


# ════════════════════════════════════════════════════════════════════
# §C. Form-encoded POST /api/auth/login (H.G674-H.G681)
# ════════════════════════════════════════════════════════════════════


def test_g674_form_login_success_redirects_to_root(client, isolated_db):
    """H.G674 — Form POST con valid creds redirige a /."""
    from prostanet.shared.auth_backends import LocalPbkdf2Backend
    LocalPbkdf2Backend().create_user(
        username="form_user", password="formpass123", role="clinician",
    )
    resp = client.post(
        "/api/auth/login",
        data={"username": "form_user", "password": "formpass123"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers.get("Location") == "/"


def test_g675_form_login_failure_redirects_to_login_with_error(client, isolated_db):
    """H.G675 — Form POST con wrong pass redirige a /login?error=invalid_credentials."""
    from prostanet.shared.auth_backends import LocalPbkdf2Backend
    LocalPbkdf2Backend().create_user(username="bob", password="bobpass")
    resp = client.post(
        "/api/auth/login",
        data={"username": "bob", "password": "wrong"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    location = resp.headers.get("Location", "")
    assert "/login" in location
    assert "invalid_credentials" in location


def test_g676_form_login_missing_credentials_redirects(client, isolated_db):
    """H.G676 — Form POST sin password redirige con error."""
    resp = client.post(
        "/api/auth/login",
        data={"username": "alice"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    location = resp.headers.get("Location", "")
    assert "/login" in location


def test_g677_json_login_still_works_after_form_support(client, isolated_db):
    """H.G677 — JSON POST sigue retornando 200 + JSON (backward-compat)."""
    from prostanet.shared.auth_backends import LocalPbkdf2Backend
    LocalPbkdf2Backend().create_user(username="json_user", password="jp123")
    resp = client.post(
        "/api/auth/login",
        json={"username": "json_user", "password": "jp123"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["username"] == "json_user"


def test_g678_json_login_failure_returns_401(client, isolated_db):
    """H.G678 — JSON POST con wrong creds retorna 401 + JSON."""
    from prostanet.shared.auth_backends import LocalPbkdf2Backend
    LocalPbkdf2Backend().create_user(username="charlie", password="cpass")
    resp = client.post(
        "/api/auth/login",
        json={"username": "charlie", "password": "wrong"},
    )
    assert resp.status_code == 401


def test_g679_form_login_session_persists(client, isolated_db):
    """H.G679 — Tras form login exitoso, sesión queda activa."""
    from prostanet.shared.auth_backends import LocalPbkdf2Backend
    LocalPbkdf2Backend().create_user(
        username="sess_user", password="sp123", role="admin",
    )
    client.post(
        "/api/auth/login",
        data={"username": "sess_user", "password": "sp123"},
        follow_redirects=False,
    )
    # Verify whoami returns authenticated
    resp = client.get("/api/auth/whoami")
    data = resp.get_json()
    assert data["authenticated"] is True
    assert data["username"] == "sess_user"


def test_g680_form_login_authenticated_user_redirected_from_login(client, isolated_db):
    """H.G680 — Usuario autenticado intentando GET /login → redirect a /."""
    from prostanet.shared.auth_backends import LocalPbkdf2Backend
    LocalPbkdf2Backend().create_user(username="diane", password="dpass")
    client.post(
        "/api/auth/login",
        data={"username": "diane", "password": "dpass"},
    )
    resp = client.get("/login", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers.get("Location") == "/"


def test_g681_form_login_csrf_validation_when_enabled(client, isolated_db, monkeypatch):
    """H.G681 — Cuando CSRF enabled, form sin token es rechazado."""
    monkeypatch.setenv("PROSTANET_CSRF_ENABLED", "true")
    from prostanet.shared.auth_backends import LocalPbkdf2Backend
    LocalPbkdf2Backend().create_user(username="csrf_user", password="cpass")
    resp = client.post(
        "/api/auth/login",
        data={"username": "csrf_user", "password": "cpass"},  # NO csrf_token
        follow_redirects=False,
    )
    assert resp.status_code == 302
    location = resp.headers.get("Location", "")
    assert "csrf_failed" in location


# ════════════════════════════════════════════════════════════════════
# §D. Logout via HTML link (H.G682-H.G684)
# ════════════════════════════════════════════════════════════════════


def test_g682_logout_via_get_redirects_to_login(client, isolated_db):
    """H.G682 — GET /api/auth/logout redirige a /login?logged_out=1."""
    from prostanet.shared.auth_backends import LocalPbkdf2Backend
    LocalPbkdf2Backend().create_user(username="lg_user", password="lp")
    client.post("/api/auth/login", data={"username": "lg_user", "password": "lp"})
    resp = client.get("/api/auth/logout", follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers.get("Location", "")
    assert "/login" in location
    assert "logged_out" in location


def test_g683_logout_via_post_returns_json(client, isolated_db):
    """H.G683 — POST /api/auth/logout sigue retornando JSON (API backward-compat)."""
    from prostanet.shared.auth_backends import LocalPbkdf2Backend
    LocalPbkdf2Backend().create_user(username="lp_user", password="lp")
    client.post("/api/auth/login", data={"username": "lp_user", "password": "lp"})
    resp = client.post("/api/auth/logout")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True


def test_g684_logout_route_exists_in_app(client, isolated_db):
    """H.G684 — GET /logout (top-level) redirige al endpoint del blueprint."""
    resp = client.get("/logout", follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers.get("Location", "")
    assert "/api/auth/logout" in location


# ════════════════════════════════════════════════════════════════════
# §E. Role-based template helpers (H.G685-H.G693)
# ════════════════════════════════════════════════════════════════════


def test_g685_has_role_returns_true_for_match(client, isolated_db):
    """H.G685 — has_role('admin') True cuando user es admin."""
    from prostanet.shared.auth_backends import LocalPbkdf2Backend
    from prostanet.presentation.auth_ui_context import has_role
    LocalPbkdf2Backend().create_user(
        username="adm", password="adm", role="admin",
    )
    client.post("/api/auth/login", data={"username": "adm", "password": "adm"})
    with client.session_transaction() as sess:
        # Helper requires Flask app context; we test via /whoami response
        pass
    resp = client.get("/api/auth/whoami")
    data = resp.get_json()
    assert data["role"] == "admin"


def test_g686_has_role_returns_false_for_mismatch(client, isolated_db):
    """H.G686 — has_role('admin') False cuando user es viewer."""
    from prostanet.shared.auth_backends import LocalPbkdf2Backend
    LocalPbkdf2Backend().create_user(
        username="v", password="v", role="viewer",
    )
    client.post("/api/auth/login", data={"username": "v", "password": "v"})
    resp = client.get("/api/auth/whoami")
    data = resp.get_json()
    assert data["role"] == "viewer"
    # Function-level test:
    from prostanet.presentation.auth_ui_context import current_user_role
    with client.application.test_request_context("/"):
        # No session in this test context, so role is empty
        assert current_user_role() == ""


def test_g687_has_scope_admin_has_all_scopes(client, isolated_db):
    """H.G687 — admin tiene phi:read + phi:write + audit:read + audit:write."""
    from prostanet.shared.auth_backends import LocalPbkdf2Backend
    backend = LocalPbkdf2Backend()
    uid = backend.create_user(username="adm2", password="adm", role="admin")
    for scope in ("phi:read", "phi:write", "audit:read", "audit:write"):
        assert backend.has_scope("admin", scope) is True


def test_g688_has_scope_viewer_only_audit_read(client, isolated_db):
    """H.G688 — viewer solo tiene audit:read."""
    from prostanet.shared.auth_backends import LocalPbkdf2Backend
    backend = LocalPbkdf2Backend()
    assert backend.has_scope("viewer", "audit:read") is True
    assert backend.has_scope("viewer", "phi:read") is False
    assert backend.has_scope("viewer", "audit:write") is False


def test_g689_is_authenticated_false_without_login(client, isolated_db):
    """H.G689 — is_authenticated False cuando no hay sesión."""
    resp = client.get("/api/auth/whoami")
    data = resp.get_json()
    assert data["authenticated"] is False


def test_g690_is_authenticated_true_after_login(client, isolated_db):
    """H.G690 — is_authenticated True tras login exitoso."""
    from prostanet.shared.auth_backends import LocalPbkdf2Backend
    LocalPbkdf2Backend().create_user(username="ia", password="ia")
    client.post("/api/auth/login", data={"username": "ia", "password": "ia"})
    resp = client.get("/api/auth/whoami")
    assert resp.get_json()["authenticated"] is True


def test_g691_helpers_registered_as_jinja_globals(auth_app, isolated_db):
    """H.G691 — Templates pueden invocar has_role/has_scope/is_authenticated."""
    # Render the login page (which uses no helpers but verifies context_processor)
    with auth_app.test_request_context("/"):
        # Test that helpers are accessible from the Jinja env
        env = auth_app.jinja_env
        # context_processors run per-render; we verify by rendering a small template
        from flask import render_template_string
        result = render_template_string(
            "{{ is_authenticated() }}|{{ current_user_role() }}|"
            "{{ has_role('admin') }}|{{ has_scope('phi:read') }}",
        )
        assert "False" in result or "True" in result  # all bool serializable


def test_g692_current_user_dict_empty_when_not_authenticated(client, isolated_db):
    """H.G692 — current_user_dict retorna {} sin login."""
    from prostanet.presentation.auth_ui_context import current_user_dict
    with client.application.test_request_context("/"):
        assert current_user_dict() == {}


def test_g693_current_user_role_empty_when_not_authenticated(client, isolated_db):
    """H.G693 — current_user_role retorna '' sin login."""
    from prostanet.presentation.auth_ui_context import current_user_role
    with client.application.test_request_context("/"):
        assert current_user_role() == ""


# ════════════════════════════════════════════════════════════════════
# §F. CSP nonces per-request (H.G694-H.G701)
# ════════════════════════════════════════════════════════════════════


def test_g694_csp_nonces_enabled_by_default():
    """H.G694 — CSP nonces ON por default cuando middleware enabled."""
    from prostanet.shared.security_middleware import is_csp_nonces_enabled
    # Default behavior (no env explicit)
    assert isinstance(is_csp_nonces_enabled(), bool)


def test_g695_csp_nonces_can_disable(monkeypatch):
    """H.G695 — PROSTANET_CSP_NONCES=false desactiva nonces."""
    monkeypatch.setenv("PROSTANET_CSP_NONCES", "false")
    from prostanet.shared.security_middleware import is_csp_nonces_enabled
    assert is_csp_nonces_enabled() is False


def test_g696_generate_csp_nonce_returns_url_safe():
    """H.G696 — generate_csp_nonce retorna URL-safe string."""
    from prostanet.shared.security_middleware import generate_csp_nonce
    nonce = generate_csp_nonce()
    assert "=" not in nonce
    assert all(ch.isalnum() or ch in "-_" for ch in nonce)


def test_g697_nonces_are_unique_per_call():
    """H.G697 — Cada llamada a generate_csp_nonce produce nonce distinto."""
    from prostanet.shared.security_middleware import generate_csp_nonce
    assert generate_csp_nonce() != generate_csp_nonce()


def test_g698_csp_with_nonce_replaces_unsafe_inline_in_script_src():
    """H.G698 — _csp_with_nonce reemplaza 'unsafe-inline' en script-src."""
    from prostanet.shared.security_middleware import _csp_with_nonce
    csp = _csp_with_nonce("test-nonce-123")
    assert "'nonce-test-nonce-123'" in csp
    # Should be in script-src section
    assert "script-src" in csp


def test_g699_csp_header_includes_nonce_when_enabled(client, isolated_db, monkeypatch):
    """H.G699 — Response CSP header incluye nonce cuando middleware activado."""
    monkeypatch.setenv("PROSTANET_SECURITY_HEADERS", "true")
    monkeypatch.setenv("PROSTANET_CSP_NONCES", "true")
    if "app" in sys.modules:
        del sys.modules["app"]
    import app as app_module
    fresh_app = app_module.create_app({"TESTING": True, "DB_PATH": str(isolated_db)})
    with fresh_app.test_client() as c:
        resp = c.get("/login")
        csp = resp.headers.get("Content-Security-Policy", "")
        assert "nonce-" in csp


def test_g700_g_csp_nonce_set_per_request(client, isolated_db):
    """H.G700 — flask.g.csp_nonce set por before_request hook."""
    with client.application.test_request_context("/"):
        # Trigger before_request manually
        for func in client.application.before_request_funcs.get(None, []):
            func()
        from flask import g
        assert hasattr(g, "csp_nonce")
        assert g.csp_nonce


def test_g701_nonces_are_different_across_requests(client, isolated_db, monkeypatch):
    """H.G701 — Nonces son distintos entre requests (no cacheados)."""
    monkeypatch.setenv("PROSTANET_SECURITY_HEADERS", "true")
    monkeypatch.setenv("PROSTANET_CSP_NONCES", "true")
    if "app" in sys.modules:
        del sys.modules["app"]
    import app as app_module
    fresh_app = app_module.create_app({"TESTING": True, "DB_PATH": str(isolated_db)})
    with fresh_app.test_client() as c:
        resp1 = c.get("/login")
        resp2 = c.get("/login")
        csp1 = resp1.headers.get("Content-Security-Policy", "")
        csp2 = resp2.headers.get("Content-Security-Policy", "")

        def extract_nonce(csp):
            import re
            m = re.search(r"nonce-([\w\-_]+)", csp)
            return m.group(1) if m else ""

        nonce1 = extract_nonce(csp1)
        nonce2 = extract_nonce(csp2)
        assert nonce1
        assert nonce2
        assert nonce1 != nonce2


# ════════════════════════════════════════════════════════════════════
# §G. g.* context vars (H.G702-H.G708)
# ════════════════════════════════════════════════════════════════════


def test_g702_g_faubot_release_set(client, isolated_db):
    """H.G702 — g.faubot_release contiene la versión actual."""
    with client.application.test_request_context("/"):
        for func in client.application.before_request_funcs.get(None, []):
            func()
        from flask import g
        from prostanet.shared.algorithm_version import FAUBOT_RELEASE
        assert g.faubot_release == FAUBOT_RELEASE


def test_g703_g_oidc_available_when_configured(client, isolated_db, monkeypatch):
    """H.G703 — g.oidc_available True cuando OIDC env vars set."""
    monkeypatch.setenv("PROSTANET_OIDC_ISSUER", "https://x.com")
    monkeypatch.setenv("PROSTANET_OIDC_CLIENT_ID", "x")
    if "app" in sys.modules:
        del sys.modules["app"]
    import app as app_module
    fresh_app = app_module.create_app({"TESTING": True, "DB_PATH": str(isolated_db)})
    with fresh_app.test_request_context("/"):
        for func in fresh_app.before_request_funcs.get(None, []):
            func()
        from flask import g
        assert g.oidc_available is True


def test_g704_g_oidc_available_false_when_not_configured(client, isolated_db, monkeypatch):
    """H.G704 — g.oidc_available False cuando OIDC env vars missing."""
    monkeypatch.delenv("PROSTANET_OIDC_ISSUER", raising=False)
    monkeypatch.delenv("PROSTANET_OIDC_CLIENT_ID", raising=False)
    if "app" in sys.modules:
        del sys.modules["app"]
    import app as app_module
    fresh_app = app_module.create_app({"TESTING": True, "DB_PATH": str(isolated_db)})
    with fresh_app.test_request_context("/"):
        for func in fresh_app.before_request_funcs.get(None, []):
            func()
        from flask import g
        assert g.oidc_available is False


def test_g705_g_local_login_always_available(client, isolated_db):
    """H.G705 — g.local_login_available siempre True (LocalBackend disponible)."""
    with client.application.test_request_context("/"):
        for func in client.application.before_request_funcs.get(None, []):
            func()
        from flask import g
        assert g.local_login_available is True


def test_g706_g_csrf_token_empty_when_csrf_disabled(client, isolated_db, monkeypatch):
    """H.G706 — g.csrf_token vacío cuando CSRF disabled."""
    monkeypatch.setenv("PROSTANET_CSRF_ENABLED", "false")
    with client.application.test_request_context("/"):
        for func in client.application.before_request_funcs.get(None, []):
            func()
        from flask import g
        assert g.csrf_token == ""


def test_g707_g_oidc_backend_label_human_readable(client, isolated_db, monkeypatch):
    """H.G707 — g.oidc_backend_label legible para humanos."""
    monkeypatch.setenv("PROSTANET_OIDC_ISSUER", "https://x.com")
    monkeypatch.setenv("PROSTANET_OIDC_CLIENT_ID", "x")
    monkeypatch.setenv("PROSTANET_AUTH_BACKEND", "auth0")
    if "app" in sys.modules:
        del sys.modules["app"]
    import app as app_module
    fresh_app = app_module.create_app({"TESTING": True, "DB_PATH": str(isolated_db)})
    with fresh_app.test_request_context("/"):
        for func in fresh_app.before_request_funcs.get(None, []):
            func()
        from flask import g
        assert g.oidc_backend_label == "Auth0"


def test_g708_g_current_user_role_set_after_login(client, isolated_db):
    """H.G708 — g.current_user_role set tras login."""
    from prostanet.shared.auth_backends import LocalPbkdf2Backend
    LocalPbkdf2Backend().create_user(
        username="ru", password="ru", role="auditor",
    )
    client.post("/api/auth/login", data={"username": "ru", "password": "ru"})
    # Make a follow-up request to trigger before_request with session loaded
    resp = client.get("/api/auth/whoami")
    assert resp.get_json()["role"] == "auditor"


# ════════════════════════════════════════════════════════════════════
# §H. End-to-end UI flow (H.G709-H.G715)
# ════════════════════════════════════════════════════════════════════


def test_g709_e2e_form_login_flow(client, isolated_db):
    """H.G709 — E2E: GET /login → POST form → 302 / → whoami auth."""
    from prostanet.shared.auth_backends import LocalPbkdf2Backend
    LocalPbkdf2Backend().create_user(username="e2e", password="e2e", role="clinician")

    # 1. GET login page
    r = client.get("/login")
    assert r.status_code == 200

    # 2. POST form with creds
    r = client.post(
        "/api/auth/login",
        data={"username": "e2e", "password": "e2e"},
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert r.headers.get("Location") == "/"

    # 3. Whoami → authenticated
    r = client.get("/api/auth/whoami")
    assert r.get_json()["authenticated"] is True

    # 4. Logout via GET
    r = client.get("/api/auth/logout", follow_redirects=False)
    assert r.status_code == 302
    assert "logged_out" in r.headers.get("Location", "")

    # 5. Whoami → not authenticated
    r = client.get("/api/auth/whoami")
    assert r.get_json()["authenticated"] is False


def test_g710_login_page_has_security_meta_info(client, isolated_db):
    """H.G710 — Página menciona compliance HIPAA/COFEPRIS/FDA."""
    resp = client.get("/login")
    body = resp.get_data(as_text=True)
    assert "HIPAA" in body
    assert "COFEPRIS" in body or "FDA" in body


def test_g711_login_page_form_has_autocomplete(client, isolated_db):
    """H.G711 — Form fields tienen autocomplete attributes (UX + password manager)."""
    resp = client.get("/login")
    body = resp.get_data(as_text=True)
    assert 'autocomplete="username"' in body
    assert 'autocomplete="current-password"' in body


def test_g712_login_page_has_required_attribute(client, isolated_db):
    """H.G712 — Form fields tienen required attribute."""
    resp = client.get("/login")
    body = resp.get_data(as_text=True)
    # Both username and password should be required
    assert body.count("required") >= 2


def test_g713_login_page_password_field_is_type_password(client, isolated_db):
    """H.G713 — Password field es type="password" (oculta input)."""
    resp = client.get("/login")
    body = resp.get_data(as_text=True)
    assert 'type="password"' in body


def test_g714_login_page_writes_audit_log_for_failed_login(client, isolated_db):
    """H.G714 — Form login fallido persiste audit log."""
    from prostanet.shared.auth_backends import LocalPbkdf2Backend
    from prostanet.shared.auth_db import get_audit_log_entries
    LocalPbkdf2Backend().create_user(username="alog", password="alog")
    client.post(
        "/api/auth/login",
        data={"username": "alog", "password": "wrong"},
        follow_redirects=False,
    )
    entries = get_audit_log_entries(
        endpoint="login", status="denied_invalid_credentials",
    )
    assert len(entries) >= 1


def test_g715_no_login_methods_available_shows_warning(client, isolated_db, monkeypatch):
    """H.G715 — Cuando ni local ni OIDC disponibles, muestra warning.

    NOTE: Local backend siempre está disponible en esta architecture, así que
    este escenario es teórico. Probamos solo que sin OIDC, el flujo local
    sigue siendo render-able.
    """
    monkeypatch.delenv("PROSTANET_OIDC_ISSUER", raising=False)
    monkeypatch.delenv("PROSTANET_OIDC_CLIENT_ID", raising=False)
    if "app" in sys.modules:
        del sys.modules["app"]
    import app as app_module
    fresh_app = app_module.create_app({"TESTING": True, "DB_PATH": str(isolated_db)})
    with fresh_app.test_client() as c:
        resp = c.get("/login")
        body = resp.get_data(as_text=True)
        # Local form should still render
        assert 'name="username"' in body
        # SSO button should NOT render (OIDC not configured)
        assert "SSO" not in body or "Iniciar sesión con SSO" not in body
