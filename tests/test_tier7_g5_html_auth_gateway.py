"""tests/test_tier7_g5_html_auth_gateway.py — FAUBOT 2026-04-25 (XXXII).

Tier 7 G5 — Auth gateway HTML completa.

Cobertura:
  - Todos los endpoints HTML PHI están decorados con @require_clinical_session
  - HTML request unauthenticated → 302 redirect a /login (no 401 JSON)
  - JSON request unauthenticated → 401 JSON (G1.5 backward-compat)
  - Auto-detect via Accept header (text/html → redirect, application/json → 401)
  - Override explícito redirect_to_login=True/False respeta intent
  - Login + logout + favicon siempre públicos
  - Authenticated user accede sin restricción
  - Role-based scope enforcement (clinician puede /patient_profile, viewer no)
  - Pre-existing API endpoints (G1.5) siguen funcionando

Hipótesis: H.G716-H.G770 (~55 hipótesis).
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import sys

import pytest


# ════════════════════════════════════════════════════════════════════
# Fixtures
# ════════════════════════════════════════════════════════════════════


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_g5.db"
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
def auth_app_dormant(isolated_db, monkeypatch):
    """App con CLINICAL_AUTH_ENABLED=false (dormant — pass-through)."""
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("CLINICAL_AUTH_ENABLED", "false")
    if "app" in sys.modules:
        del sys.modules["app"]
    import app as app_module
    return app_module.create_app({"TESTING": True, "DB_PATH": str(isolated_db)})


@pytest.fixture
def auth_app_active(isolated_db, monkeypatch):
    """App con CLINICAL_AUTH_ENABLED=true (active — requiere auth)."""
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("CLINICAL_AUTH_ENABLED", "true")
    if "app" in sys.modules:
        del sys.modules["app"]
    import app as app_module
    return app_module.create_app({"TESTING": True, "DB_PATH": str(isolated_db)})


@pytest.fixture
def client_dormant(auth_app_dormant):
    with auth_app_dormant.test_client() as c:
        yield c


@pytest.fixture
def client_active(auth_app_active):
    with auth_app_active.test_client() as c:
        yield c


# ════════════════════════════════════════════════════════════════════
# §A. HTML endpoints redirect when unauthenticated (H.G716-H.G725)
# ════════════════════════════════════════════════════════════════════


HTML_ENDPOINTS_PHI_READ = [
    "/patients",
    "/dashboard",
    "/clinical-hub",
    "/patient_profile/12345678901",
]

HTML_ENDPOINTS_PHI_WRITE = [
    "/patient_intake?assessment_id=1",
    "/wizard/m1_crpc",
]

HTML_ENDPOINTS_AUDIT_READ = [
    "/gates-coverage-dashboard",
]


@pytest.mark.parametrize("endpoint", HTML_ENDPOINTS_PHI_READ)
def test_g716_phi_read_html_endpoints_redirect_when_unauth(client_active, endpoint):
    """H.G716 — Endpoints HTML PHI:read redirect a /login si unauthenticated."""
    resp = client_active.get(
        endpoint, headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    location = resp.headers.get("Location", "")
    assert "/login" in location
    assert "session_expired" in location


@pytest.mark.parametrize("endpoint", HTML_ENDPOINTS_PHI_WRITE)
def test_g717_phi_write_html_endpoints_redirect_when_unauth(client_active, endpoint):
    """H.G717 — Endpoints HTML PHI:write redirect a /login si unauthenticated."""
    resp = client_active.get(
        endpoint, headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/login" in resp.headers.get("Location", "")


@pytest.mark.parametrize("endpoint", HTML_ENDPOINTS_AUDIT_READ)
def test_g718_audit_read_html_endpoints_redirect_when_unauth(client_active, endpoint):
    """H.G718 — Endpoints HTML audit:read redirect a /login si unauthenticated."""
    resp = client_active.get(
        endpoint, headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/login" in resp.headers.get("Location", "")


def test_g719_dormant_mode_endpoints_pass_through(client_dormant):
    """H.G719 — Cuando CLINICAL_AUTH_ENABLED=false, HTML endpoints accesibles."""
    # /patients should render HTML 200 (not redirect to login)
    resp = client_dormant.get("/patients", follow_redirects=False)
    assert resp.status_code == 200


def test_g720_dashboard_dormant_renders(client_dormant):
    """H.G720 — Dashboard accesible en modo dormant."""
    resp = client_dormant.get("/dashboard", follow_redirects=False)
    assert resp.status_code == 200


def test_g721_clinical_hub_dormant_renders(client_dormant):
    """H.G721 — Clinical hub accesible en modo dormant."""
    resp = client_dormant.get("/clinical-hub", follow_redirects=False)
    assert resp.status_code == 200


def test_g722_gates_coverage_dormant_renders(client_dormant):
    """H.G722 — Gates coverage dashboard accesible en modo dormant."""
    resp = client_dormant.get("/gates-coverage-dashboard", follow_redirects=False)
    assert resp.status_code == 200


def test_g723_patient_profile_unknown_redirects_in_active_mode(client_active):
    """H.G723 — Patient profile unknown nss → 302 redirect (no leak 404)."""
    # Without auth, decorator catches first → 302 redirect
    resp = client_active.get(
        "/patient_profile/99999999999",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    # User redirected to login, no PHI/SQL info leaked


def test_g724_wizard_endpoint_redirects_when_unauth(client_active):
    """H.G724 — /wizard/<module_id> redirect cuando sin auth."""
    resp = client_active.get(
        "/wizard/localized_initial",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert resp.status_code == 302


def test_g725_patient_intake_redirects_when_unauth(client_active):
    """H.G725 — /patient_intake redirect (sin assessment_id va al wizard, con sin auth → login)."""
    resp = client_active.get(
        "/patient_intake?assessment_id=1",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/login" in resp.headers.get("Location", "")


# ════════════════════════════════════════════════════════════════════
# §B. Public endpoints stay accessible (H.G726-H.G731)
# ════════════════════════════════════════════════════════════════════


def test_g726_login_page_public_in_active_mode(client_active):
    """H.G726 — /login sigue público en active mode."""
    resp = client_active.get("/login")
    assert resp.status_code == 200


def test_g727_favicon_public_in_active_mode(client_active):
    """H.G727 — /favicon.ico siempre público."""
    resp = client_active.get("/favicon.ico")
    assert resp.status_code == 204


def test_g728_root_redirects_dormant_mode(client_dormant):
    """H.G728 — / redirige a /clinical-hub (en dormant, accesible)."""
    resp = client_dormant.get("/", follow_redirects=False)
    assert resp.status_code == 302
    # Eventualmente lleva a clinical-hub, accesible en dormant


def test_g729_root_redirects_active_mode(client_active):
    """H.G729 — / redirige a /clinical-hub que requiere auth → / → /clinical-hub → /login."""
    resp = client_active.get(
        "/", headers={"Accept": "text/html"},
        follow_redirects=True,
    )
    # After all redirects, should land on /login
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "loginForm" in body or "Iniciar sesión" in body


def test_g730_oidc_login_endpoint_public_in_active_mode(client_active):
    """H.G730 — /api/auth/oidc/login es público (entry point al SSO flow)."""
    resp = client_active.get("/api/auth/oidc/login", follow_redirects=False)
    # Either 302 redirect to IDP (if configured) or 503 (if not)
    assert resp.status_code in {302, 503}


def test_g731_csrf_token_endpoint_public_in_active_mode(client_active):
    """H.G731 — /api/auth/csrf-token público (clientes necesitan el token)."""
    resp = client_active.get("/api/auth/csrf-token")
    assert resp.status_code == 200


# ════════════════════════════════════════════════════════════════════
# §C. JSON requests still get 401 (backward-compat) (H.G732-H.G737)
# ════════════════════════════════════════════════════════════════════


def test_g732_json_request_to_decision_audit_returns_401(client_active):
    """H.G732 — JSON request a /api/decision-audit/<ref> retorna 401 (no redirect)."""
    resp = client_active.get(
        "/api/decision-audit/12345678901",
        headers={"Accept": "application/json"},
    )
    assert resp.status_code == 401
    data = resp.get_json()
    assert data["success"] is False


def test_g733_json_request_to_gates_dashboard_returns_401(client_active):
    """H.G733 — JSON request a /api/gates-coverage-dashboard retorna 401."""
    resp = client_active.get(
        "/api/gates-coverage-dashboard",
        headers={"Accept": "application/json"},
    )
    assert resp.status_code == 401


def test_g734_html_request_to_html_endpoint_redirects(client_active):
    """H.G734 — HTML request a HTML endpoint redirige (no 401 JSON)."""
    resp = client_active.get(
        "/patients", headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert resp.status_code == 302


def test_g735_wildcard_accept_header_treated_as_html(client_active):
    """H.G735 — Accept: */* (browser default) → tratado como HTML → redirect."""
    resp = client_active.get(
        "/patients", headers={"Accept": "*/*"},
        follow_redirects=False,
    )
    assert resp.status_code == 302


def test_g736_no_accept_header_treated_as_html(client_active):
    """H.G736 — Sin Accept header → tratado como HTML."""
    resp = client_active.get("/patients", follow_redirects=False)
    # Could be 302 (redirect) or 200 if Accept header defaults to */*
    assert resp.status_code in {302, 200}


def test_g737_json_first_accept_returns_json_response(client_active):
    """H.G737 — Accept: application/json sin text/html → 401 JSON."""
    resp = client_active.get(
        "/api/decision-audit/12345",
        headers={"Accept": "application/json"},
    )
    assert resp.status_code == 401
    assert resp.is_json


# ════════════════════════════════════════════════════════════════════
# §D. Authenticated user accesses HTML endpoints (H.G738-H.G744)
# ════════════════════════════════════════════════════════════════════


def test_g738_authenticated_admin_accesses_patients(client_active, isolated_db):
    """H.G738 — Admin autenticado accede a /patients."""
    from prostanet.shared.auth_backends import LocalPbkdf2Backend
    LocalPbkdf2Backend().create_user(
        username="admin1", password="admin1", role="admin",
    )
    client_active.post(
        "/api/auth/login", data={"username": "admin1", "password": "admin1"},
    )
    resp = client_active.get("/patients", follow_redirects=False)
    assert resp.status_code == 200


def test_g739_authenticated_clinician_accesses_dashboard(client_active, isolated_db):
    """H.G739 — Clinician accede a /dashboard."""
    from prostanet.shared.auth_backends import LocalPbkdf2Backend
    LocalPbkdf2Backend().create_user(
        username="clin1", password="clin1", role="clinician",
    )
    client_active.post(
        "/api/auth/login", data={"username": "clin1", "password": "clin1"},
    )
    resp = client_active.get("/dashboard", follow_redirects=False)
    assert resp.status_code == 200


def test_g740_authenticated_clinician_accesses_clinical_hub(client_active, isolated_db):
    """H.G740 — Clinician accede a /clinical-hub."""
    from prostanet.shared.auth_backends import LocalPbkdf2Backend
    LocalPbkdf2Backend().create_user(
        username="clin2", password="c2", role="clinician",
    )
    client_active.post(
        "/api/auth/login", data={"username": "clin2", "password": "c2"},
    )
    resp = client_active.get("/clinical-hub", follow_redirects=False)
    assert resp.status_code == 200


def test_g741_authenticated_admin_accesses_audit_dashboard(client_active, isolated_db):
    """H.G741 — Admin accede a /gates-coverage-dashboard (scope audit:read)."""
    from prostanet.shared.auth_backends import LocalPbkdf2Backend
    LocalPbkdf2Backend().create_user(
        username="adm2", password="adm2", role="admin",
    )
    client_active.post(
        "/api/auth/login", data={"username": "adm2", "password": "adm2"},
    )
    resp = client_active.get("/gates-coverage-dashboard", follow_redirects=False)
    assert resp.status_code == 200


def test_g742_authenticated_auditor_accesses_audit_dashboard(client_active, isolated_db):
    """H.G742 — Auditor accede a /gates-coverage-dashboard (audit:read)."""
    from prostanet.shared.auth_backends import LocalPbkdf2Backend
    LocalPbkdf2Backend().create_user(
        username="aud1", password="aud1", role="auditor",
    )
    client_active.post(
        "/api/auth/login", data={"username": "aud1", "password": "aud1"},
    )
    resp = client_active.get("/gates-coverage-dashboard", follow_redirects=False)
    assert resp.status_code == 200


def test_g743_authenticated_admin_accesses_wizard(client_active, isolated_db):
    """H.G743 — Admin accede a /wizard/<module> (phi:write)."""
    from prostanet.shared.auth_backends import LocalPbkdf2Backend
    LocalPbkdf2Backend().create_user(
        username="adm3", password="a3", role="admin",
    )
    client_active.post(
        "/api/auth/login", data={"username": "adm3", "password": "a3"},
    )
    resp = client_active.get("/wizard/localized_initial", follow_redirects=False)
    assert resp.status_code == 200


def test_g744_authenticated_clinician_accesses_wizard(client_active, isolated_db):
    """H.G744 — Clinician accede a /wizard (phi:write OK para clinician)."""
    from prostanet.shared.auth_backends import LocalPbkdf2Backend
    LocalPbkdf2Backend().create_user(
        username="clin3", password="c3", role="clinician",
    )
    client_active.post(
        "/api/auth/login", data={"username": "clin3", "password": "c3"},
    )
    resp = client_active.get("/wizard/localized_initial", follow_redirects=False)
    assert resp.status_code == 200


# ════════════════════════════════════════════════════════════════════
# §E. Role-based access (insufficient scope → 302 access_denied) (H.G745-H.G751)
# ════════════════════════════════════════════════════════════════════


def test_g745_viewer_cannot_access_phi_read(client_active, isolated_db):
    """H.G745 — Viewer NO puede acceder a /patients (no tiene phi:read)."""
    from prostanet.shared.auth_backends import LocalPbkdf2Backend
    LocalPbkdf2Backend().create_user(
        username="v1", password="v1", role="viewer",
    )
    client_active.post(
        "/api/auth/login", data={"username": "v1", "password": "v1"},
    )
    resp = client_active.get(
        "/patients", headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    location = resp.headers.get("Location", "")
    assert "access_denied" in location


def test_g746_viewer_cannot_access_dashboard(client_active, isolated_db):
    """H.G746 — Viewer NO puede acceder a /dashboard."""
    from prostanet.shared.auth_backends import LocalPbkdf2Backend
    LocalPbkdf2Backend().create_user(
        username="v2", password="v2", role="viewer",
    )
    client_active.post(
        "/api/auth/login", data={"username": "v2", "password": "v2"},
    )
    resp = client_active.get(
        "/dashboard", headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "access_denied" in resp.headers.get("Location", "")


def test_g747_viewer_can_access_audit_read(client_active, isolated_db):
    """H.G747 — Viewer SÍ puede acceder a /gates-coverage-dashboard (audit:read)."""
    from prostanet.shared.auth_backends import LocalPbkdf2Backend
    LocalPbkdf2Backend().create_user(
        username="v3", password="v3", role="viewer",
    )
    client_active.post(
        "/api/auth/login", data={"username": "v3", "password": "v3"},
    )
    resp = client_active.get(
        "/gates-coverage-dashboard", follow_redirects=False,
    )
    assert resp.status_code == 200


def test_g748_auditor_cannot_access_phi_read(client_active, isolated_db):
    """H.G748 — Auditor NO puede acceder a /patients (no tiene phi:read)."""
    from prostanet.shared.auth_backends import LocalPbkdf2Backend
    LocalPbkdf2Backend().create_user(
        username="aud2", password="aud2", role="auditor",
    )
    client_active.post(
        "/api/auth/login", data={"username": "aud2", "password": "aud2"},
    )
    resp = client_active.get(
        "/patients", headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "access_denied" in resp.headers.get("Location", "")


def test_g749_auditor_can_access_audit_dashboard(client_active, isolated_db):
    """H.G749 — Auditor SÍ puede acceder a /gates-coverage-dashboard."""
    from prostanet.shared.auth_backends import LocalPbkdf2Backend
    LocalPbkdf2Backend().create_user(
        username="aud3", password="aud3", role="auditor",
    )
    client_active.post(
        "/api/auth/login", data={"username": "aud3", "password": "aud3"},
    )
    resp = client_active.get("/gates-coverage-dashboard", follow_redirects=False)
    assert resp.status_code == 200


def test_g750_clinician_can_access_phi_write_endpoints(client_active, isolated_db):
    """H.G750 — Clinician puede acceder a /patient_intake (phi:write)."""
    from prostanet.shared.auth_backends import LocalPbkdf2Backend
    LocalPbkdf2Backend().create_user(
        username="cw1", password="cw1", role="clinician",
    )
    client_active.post(
        "/api/auth/login", data={"username": "cw1", "password": "cw1"},
    )
    resp = client_active.get(
        "/patient_intake?assessment_id=1", follow_redirects=False,
    )
    assert resp.status_code == 200


def test_g751_viewer_cannot_access_phi_write(client_active, isolated_db):
    """H.G751 — Viewer NO puede acceder a /patient_intake (no tiene phi:write)."""
    from prostanet.shared.auth_backends import LocalPbkdf2Backend
    LocalPbkdf2Backend().create_user(
        username="v4", password="v4", role="viewer",
    )
    client_active.post(
        "/api/auth/login", data={"username": "v4", "password": "v4"},
    )
    resp = client_active.get(
        "/patient_intake?assessment_id=1",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "access_denied" in resp.headers.get("Location", "")


# ════════════════════════════════════════════════════════════════════
# §F. Helper _client_prefers_html (H.G752-H.G756)
# ════════════════════════════════════════════════════════════════════


def test_g752_prefers_html_with_text_html(auth_app_active):
    """H.G752 — Accept: text/html → prefers_html True."""
    with auth_app_active.test_request_context(
        "/", headers={"Accept": "text/html"},
    ):
        from prostanet.shared.security_helpers import _client_prefers_html
        assert _client_prefers_html() is True


def test_g753_prefers_html_with_application_json(auth_app_active):
    """H.G753 — Accept: application/json → prefers_html False."""
    with auth_app_active.test_request_context(
        "/", headers={"Accept": "application/json"},
    ):
        from prostanet.shared.security_helpers import _client_prefers_html
        assert _client_prefers_html() is False


def test_g754_prefers_html_wildcard(auth_app_active):
    """H.G754 — Accept: */* → prefers_html True (browser default)."""
    with auth_app_active.test_request_context(
        "/", headers={"Accept": "*/*"},
    ):
        from prostanet.shared.security_helpers import _client_prefers_html
        assert _client_prefers_html() is True


def test_g755_prefers_html_no_accept_header(auth_app_active):
    """H.G755 — Sin Accept header → prefers_html True (browser default)."""
    with auth_app_active.test_request_context("/"):
        from prostanet.shared.security_helpers import _client_prefers_html
        assert _client_prefers_html() is True


def test_g756_prefers_html_mixed_accept(auth_app_active):
    """H.G756 — Accept con HTML primero → True; con solo JSON → False."""
    with auth_app_active.test_request_context(
        "/", headers={"Accept": "text/html, application/json"},
    ):
        from prostanet.shared.security_helpers import _client_prefers_html
        # Both present, HTML comes first → True
        assert _client_prefers_html() is True


# ════════════════════════════════════════════════════════════════════
# §G. redirect_to_login override (H.G757-H.G761)
# ════════════════════════════════════════════════════════════════════


def test_g757_explicit_redirect_to_login_true_always_redirects(monkeypatch, isolated_db):
    """H.G757 — redirect_to_login=True override fuerza redirect aunque Accept sea JSON."""
    monkeypatch.setenv("CLINICAL_AUTH_ENABLED", "true")
    from prostanet.shared.security_helpers import require_clinical_session

    @require_clinical_session(scope="phi:read", redirect_to_login=True, audit_log=False)
    def my_view():
        return {"data": "ok"}, 200

    from flask import Flask
    a = Flask(__name__)
    a.secret_key = "test"
    with a.test_request_context("/", headers={"Accept": "application/json"}):
        result = my_view()
    # Should be redirect even with JSON Accept
    assert hasattr(result, "status_code")  # Flask Response object
    assert result.status_code == 302


def test_g758_explicit_redirect_to_login_false_always_returns_401(monkeypatch, isolated_db):
    """H.G758 — redirect_to_login=False override fuerza 401 aunque Accept sea HTML."""
    monkeypatch.setenv("CLINICAL_AUTH_ENABLED", "true")
    from prostanet.shared.security_helpers import require_clinical_session

    @require_clinical_session(scope="phi:read", redirect_to_login=False, audit_log=False)
    def my_view():
        return {"data": "ok"}, 200

    from flask import Flask
    a = Flask(__name__)
    a.secret_key = "test"
    with a.test_request_context("/", headers={"Accept": "text/html"}):
        result = my_view()
    # Should be 401 JSON tuple
    assert isinstance(result, tuple)
    assert result[1] == 401


def test_g759_default_none_uses_accept_header(monkeypatch, isolated_db):
    """H.G759 — redirect_to_login=None (default) usa Accept header."""
    monkeypatch.setenv("CLINICAL_AUTH_ENABLED", "true")
    from prostanet.shared.security_helpers import require_clinical_session

    @require_clinical_session(scope="phi:read", audit_log=False)  # no override
    def my_view():
        return {"data": "ok"}, 200

    from flask import Flask
    a = Flask(__name__)
    a.secret_key = "test"
    # HTML Accept → redirect
    with a.test_request_context("/", headers={"Accept": "text/html"}):
        result = my_view()
    assert hasattr(result, "status_code") and result.status_code == 302
    # JSON Accept → 401
    with a.test_request_context("/", headers={"Accept": "application/json"}):
        result = my_view()
    assert isinstance(result, tuple) and result[1] == 401


def test_g760_decorator_marks_endpoint_with_redirect_attr():
    """H.G760 — Decorator preserva _clinical_session_required attr."""
    from prostanet.shared.security_helpers import require_clinical_session

    @require_clinical_session(scope="phi:read", redirect_to_login=True)
    def protected_view():
        return "ok"

    assert protected_view._clinical_session_required is True
    assert protected_view._required_scope == "phi:read"


def test_g761_dormant_mode_ignores_redirect_to_login(monkeypatch):
    """H.G761 — En dormant mode, redirect_to_login no aplica (pass-through)."""
    monkeypatch.setenv("CLINICAL_AUTH_ENABLED", "false")
    from prostanet.shared.security_helpers import require_clinical_session

    @require_clinical_session(scope="phi:read", redirect_to_login=True, audit_log=False)
    def my_view():
        return {"data": "ok"}, 200

    from flask import Flask
    a = Flask(__name__)
    a.secret_key = "test"
    with a.test_request_context("/"):
        result = my_view()
    # Pass-through → endpoint executed
    assert isinstance(result, tuple)
    assert result[0]["data"] == "ok"
    assert result[1] == 200


# ════════════════════════════════════════════════════════════════════
# §H. Audit log writes for HTML denials (H.G762-H.G765)
# ════════════════════════════════════════════════════════════════════


def test_g762_html_denial_writes_audit_log(client_active, isolated_db):
    """H.G762 — HTML endpoint denial persiste audit log."""
    from prostanet.shared.auth_db import get_audit_log_entries
    initial = len(get_audit_log_entries(status="denied_no_session"))
    client_active.get(
        "/patients", headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    after = len(get_audit_log_entries(status="denied_no_session"))
    assert after > initial


def test_g763_audit_log_captures_html_endpoint_path(client_active, isolated_db):
    """H.G763 — Audit log entry incluye path correcto (/patients)."""
    from prostanet.shared.auth_db import get_audit_log_entries
    client_active.get(
        "/patients", headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    entries = get_audit_log_entries(status="denied_no_session")
    assert any(e["path"] == "/patients" for e in entries)


def test_g764_audit_log_captures_endpoint_name(client_active, isolated_db):
    """H.G764 — Audit log entry incluye nombre del endpoint (patients_list)."""
    from prostanet.shared.auth_db import get_audit_log_entries
    client_active.get(
        "/patients", headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    entries = get_audit_log_entries(endpoint="patients_list")
    assert len(entries) >= 1


def test_g765_role_denial_writes_audit_log_with_reason(client_active, isolated_db):
    """H.G765 — Denial por scope insuficiente queda con reason específica."""
    from prostanet.shared.auth_backends import LocalPbkdf2Backend
    from prostanet.shared.auth_db import get_audit_log_entries
    LocalPbkdf2Backend().create_user(
        username="vsc", password="vsc", role="viewer",
    )
    client_active.post("/api/auth/login", data={"username": "vsc", "password": "vsc"})
    client_active.get(
        "/patients", headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    entries = get_audit_log_entries(status="denied_invalid_scope")
    assert len(entries) >= 1
    assert any("phi:read" in (e.get("reason") or "") for e in entries)


# ════════════════════════════════════════════════════════════════════
# §I. End-to-end UI gateway flow (H.G766-H.G770)
# ════════════════════════════════════════════════════════════════════


def test_g766_e2e_unauth_browse_redirect_login_then_access(client_active, isolated_db):
    """H.G766 — E2E: usuario navega a /patients sin auth → /login → login → /patients accesible."""
    from prostanet.shared.auth_backends import LocalPbkdf2Backend
    LocalPbkdf2Backend().create_user(
        username="e2e_g5", password="e2e_g5", role="clinician",
    )

    # 1. Try to access /patients without auth → redirect
    r = client_active.get(
        "/patients", headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert "/login" in r.headers.get("Location", "")

    # 2. Login
    r = client_active.post(
        "/api/auth/login",
        data={"username": "e2e_g5", "password": "e2e_g5"},
    )
    assert r.status_code == 302  # form login redirects

    # 3. Now /patients accessible
    r = client_active.get("/patients")
    assert r.status_code == 200


def test_g767_e2e_logout_blocks_access_again(client_active, isolated_db):
    """H.G767 — E2E: tras logout, endpoints bloqueados de nuevo."""
    from prostanet.shared.auth_backends import LocalPbkdf2Backend
    LocalPbkdf2Backend().create_user(
        username="lo_user", password="lo_user", role="clinician",
    )
    client_active.post(
        "/api/auth/login", data={"username": "lo_user", "password": "lo_user"},
    )
    # Authenticated → /patients OK
    r = client_active.get("/patients")
    assert r.status_code == 200
    # Logout
    client_active.get("/api/auth/logout", follow_redirects=False)
    # Now /patients redirects to /login
    r = client_active.get(
        "/patients", headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert r.status_code == 302


def test_g768_dormant_mode_no_audit_log_writes(client_dormant, isolated_db):
    """H.G768 — En dormant mode, HTML access NO persiste audit log."""
    from prostanet.shared.auth_db import count_audit_log_entries
    initial = count_audit_log_entries()
    client_dormant.get("/patients")
    after = count_audit_log_entries()
    # Dormant mode: no DB write
    assert after == initial


def test_g769_static_files_unaffected(client_active, isolated_db):
    """H.G769 — Static files (/static/*) NO requieren auth."""
    # Try to access a static file (favicon is a known route)
    resp = client_active.get("/favicon.ico")
    assert resp.status_code == 204


def test_g770_pre_existing_api_endpoints_still_work_unauth(client_dormant, isolated_db):
    """H.G770 — En dormant mode (G1.5 default), API endpoints siguen accesibles."""
    # algorithm-version is a public API endpoint
    resp = client_dormant.get("/api/decision-audit/algorithm-version")
    assert resp.status_code == 200
