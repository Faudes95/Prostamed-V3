"""tests/test_tier7_g4_refresh_token.py — FAUBOT 2026-04-25 (XXXVII).

Tier 7 G4 — Refresh token + auto session renewal.

Cobertura:
  - exchange_refresh_token_for_tokens (RFC 6749 §6)
  - Session storage helpers (store_oidc_tokens, get_refresh_token, etc.)
  - Refresh count tracking + last_refresh_at timestamp
  - logout clears tokens (security: no leak post-logout)
  - POST /api/auth/refresh endpoint (success + denial cases)
  - GET /api/auth/session-status endpoint (auth + unauth states)
  - MockOidcProvider extension: handle grant_type=refresh_token
  - Audit log writes for each refresh attempt
  - Edge cases: refresh expired, refresh_token rotation, no refresh_token
  - Backward-compat: LocalPbkdf2Backend sessions sin refresh_token funcionan

Hipótesis: H.G991-H.G1040 (~50 hipótesis).
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import http.server
import json
import socketserver
import sys
import threading
import time
import urllib.parse

import pytest


# ════════════════════════════════════════════════════════════════════
# §A. MockOidcProvider extended para refresh_token (H.G991-H.G992)
# ════════════════════════════════════════════════════════════════════


class MockOidcProviderWithRefresh:
    """Extension of MockOidcProvider that handles grant_type=refresh_token.

    Soporta:
      - authorization_code grant (return access + refresh + id tokens)
      - refresh_token grant (return new access + optional rotated refresh)
      - failure_mode='refresh' to simulate IDP rejection
    """

    def __init__(self, *, rotate_refresh_tokens: bool = True):
        self.port = 0
        self.httpd = None
        self.thread = None
        self.issuer = ""
        self.codes: dict[str, dict] = {}
        self.access_tokens: dict[str, dict] = {}  # token → userinfo dict
        self.refresh_tokens: dict[str, str] = {}  # rt → username (for tracking)
        self.failure_mode: str = ""
        self.rotate_refresh_tokens = rotate_refresh_tokens

    def __enter__(self):
        provider = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a, **kw):
                pass

            def do_GET(self):
                if self.path == "/.well-known/openid-configuration":
                    body = json.dumps({
                        "issuer": provider.issuer,
                        "authorization_endpoint": f"{provider.issuer}/oauth/authorize",
                        "token_endpoint": f"{provider.issuer}/oauth/token",
                        "userinfo_endpoint": f"{provider.issuer}/oauth/userinfo",
                        "jwks_uri": f"{provider.issuer}/.well-known/jwks.json",
                        "response_types_supported": ["code"],
                        "scopes_supported": ["openid", "email", "profile", "offline_access"],
                        "grant_types_supported": ["authorization_code", "refresh_token"],
                    }).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(body)
                    return

                if self.path.startswith("/oauth/userinfo"):
                    auth = self.headers.get("Authorization", "")
                    token = auth.replace("Bearer ", "").strip()
                    userinfo = provider.access_tokens.get(token)
                    if not userinfo:
                        self.send_response(401)
                        self.end_headers()
                        return
                    body = json.dumps(userinfo).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(body)
                    return

                self.send_response(404)
                self.end_headers()

            def do_POST(self):
                if self.path == "/oauth/token":
                    length = int(self.headers.get("Content-Length", "0"))
                    body_raw = self.rfile.read(length).decode("utf-8")
                    params = dict(urllib.parse.parse_qsl(body_raw))
                    grant_type = params.get("grant_type", "")

                    # Handle refresh_token grant
                    if grant_type == "refresh_token":
                        if provider.failure_mode == "refresh":
                            self.send_response(400)
                            self.end_headers()
                            self.wfile.write(b'{"error":"invalid_grant"}')
                            return
                        rt = params.get("refresh_token", "")
                        username = provider.refresh_tokens.get(rt)
                        if not username:
                            self.send_response(400)
                            self.end_headers()
                            self.wfile.write(b'{"error":"invalid_grant"}')
                            return
                        # Generate new tokens (rotation per provider config)
                        new_at = f"at_refreshed_{int(time.time() * 1000)}"
                        # Find userinfo for this user
                        userinfo = None
                        for at, info in provider.access_tokens.items():
                            if info.get("preferred_username") == username:
                                userinfo = info
                                break
                        if userinfo:
                            provider.access_tokens[new_at] = userinfo

                        response = {
                            "access_token": new_at,
                            "token_type": "Bearer",
                            "expires_in": 3600,
                        }
                        if provider.rotate_refresh_tokens:
                            new_rt = f"rt_rotated_{int(time.time() * 1000)}"
                            provider.refresh_tokens[new_rt] = username
                            response["refresh_token"] = new_rt
                            # Optionally invalidate old refresh_token (depends on IDP)
                            # provider.refresh_tokens.pop(rt, None)

                        body = json.dumps(response).encode("utf-8")
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(body)
                        return

                    # Handle authorization_code grant (existing)
                    code = params.get("code", "")
                    code_data = provider.codes.get(code)
                    if not code_data:
                        self.send_response(400)
                        self.end_headers()
                        self.wfile.write(b'{"error":"invalid_grant"}')
                        return

                    response = {
                        "access_token": code_data["access_token"],
                        "token_type": "Bearer",
                        "expires_in": 3600,
                        "id_token": "mock.id.token",
                        "refresh_token": code_data.get("refresh_token", ""),
                    }
                    body = json.dumps(response).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(body)
                    return

                self.send_response(404)
                self.end_headers()

        self.httpd = socketserver.TCPServer(("127.0.0.1", self.port), Handler)
        self.port = self.httpd.server_address[1]
        self.issuer = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        time.sleep(0.05)
        return self

    def __exit__(self, *exc):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()

    def add_authorized_user(
        self,
        sub: str,
        *,
        email: str = "",
        preferred_username: str = "",
        roles: list[str] | None = None,
    ) -> tuple[str, str, str]:
        """Pre-register user. Returns (code, access_token, refresh_token)."""
        code = f"code_{sub}_{int(time.time() * 1000)}"
        access_token = f"at_{sub}_{int(time.time() * 1000)}"
        refresh_token = f"rt_{sub}_{int(time.time() * 1000)}"
        userinfo = {"sub": sub}
        if email:
            userinfo["email"] = email
        if preferred_username:
            userinfo["preferred_username"] = preferred_username
        if roles:
            userinfo["roles"] = roles

        self.codes[code] = {
            "access_token": access_token,
            "refresh_token": refresh_token,
        }
        self.access_tokens[access_token] = userinfo
        self.refresh_tokens[refresh_token] = preferred_username or sub
        return code, access_token, refresh_token


# ════════════════════════════════════════════════════════════════════
# Fixtures
# ════════════════════════════════════════════════════════════════════


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_g4.db"
    monkeypatch.setenv("PROSTANET_DB_PATH", str(db_path))
    import tracking_db as tdb
    tdb.configure_db_path(str(db_path))
    tdb.init_tracking_db()
    from prostanet.shared.auth_db import init_auth_db
    init_auth_db()
    from prostanet.shared.auth_backends import reset_auth_backend_for_tests
    reset_auth_backend_for_tests()
    from prostanet.shared.oidc_client import reset_discovery_cache
    reset_discovery_cache()
    yield db_path


@pytest.fixture
def mock_oidc_with_refresh(isolated_db, monkeypatch):
    """Spawn mock OIDC + configure env for refresh tests."""
    with MockOidcProviderWithRefresh() as provider:
        monkeypatch.setenv("PROSTANET_OIDC_ISSUER", provider.issuer)
        monkeypatch.setenv("PROSTANET_OIDC_CLIENT_ID", "test-client")
        monkeypatch.setenv("PROSTANET_OIDC_CLIENT_SECRET", "test-secret")
        monkeypatch.setenv("PROSTANET_AUTH_BACKEND", "oidc")
        from prostanet.shared.auth_backends import reset_auth_backend_for_tests
        reset_auth_backend_for_tests()
        yield provider


@pytest.fixture
def auth_app_with_oidc(isolated_db, mock_oidc_with_refresh, monkeypatch):
    """Flask app with OIDC backend enabled."""
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("TESTING", "1")
    if "app" in sys.modules:
        del sys.modules["app"]
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True, "DB_PATH": str(isolated_db)})
    yield flask_app


@pytest.fixture
def client_oidc(auth_app_with_oidc):
    with auth_app_with_oidc.test_client() as c:
        yield c


# ════════════════════════════════════════════════════════════════════
# §B. exchange_refresh_token_for_tokens — RFC 6749 §6 (H.G991-H.G997)
# ════════════════════════════════════════════════════════════════════


def test_g991_exchange_refresh_token_succeeds(mock_oidc_with_refresh):
    """H.G991 — Refresh token exchange retorna nuevo access_token."""
    from prostanet.shared.oidc_client import (
        OidcConfig, exchange_refresh_token_for_tokens,
    )
    code, at, rt = mock_oidc_with_refresh.add_authorized_user(
        "u1", preferred_username="alice",
    )
    config = OidcConfig.from_env()
    resp = exchange_refresh_token_for_tokens(config, refresh_token=rt)
    assert resp.access_token
    assert resp.access_token != at  # new token
    assert resp.token_type == "Bearer"
    assert resp.expires_in > 0


def test_g992_refresh_token_rotation_provided(mock_oidc_with_refresh):
    """H.G992 — Si IDP rota refresh_token, response incluye nuevo refresh_token."""
    from prostanet.shared.oidc_client import (
        OidcConfig, exchange_refresh_token_for_tokens,
    )
    code, at, rt = mock_oidc_with_refresh.add_authorized_user(
        "u2", preferred_username="bob",
    )
    config = OidcConfig.from_env()
    resp = exchange_refresh_token_for_tokens(config, refresh_token=rt)
    assert resp.refresh_token  # rotation enabled in mock
    assert resp.refresh_token != rt


def test_g993_refresh_token_empty_raises():
    """H.G993 — Refresh con empty token raises ValueError."""
    from prostanet.shared.oidc_client import (
        OidcConfig, exchange_refresh_token_for_tokens,
    )
    config = OidcConfig(
        issuer="https://x.com", client_id="x",
    )
    with pytest.raises(ValueError, match="refresh_token is required"):
        exchange_refresh_token_for_tokens(config, refresh_token="")


def test_g994_refresh_invalid_token_raises(mock_oidc_with_refresh):
    """H.G994 — Refresh con token inválido (no en mock) raises ValueError."""
    from prostanet.shared.oidc_client import (
        OidcConfig, exchange_refresh_token_for_tokens,
    )
    config = OidcConfig.from_env()
    with pytest.raises(ValueError):
        exchange_refresh_token_for_tokens(config, refresh_token="bogus_rt")


def test_g995_refresh_idp_failure_raises(mock_oidc_with_refresh):
    """H.G995 — Si IDP responde error, raises ValueError."""
    from prostanet.shared.oidc_client import (
        OidcConfig, exchange_refresh_token_for_tokens,
    )
    code, at, rt = mock_oidc_with_refresh.add_authorized_user("u3")
    mock_oidc_with_refresh.failure_mode = "refresh"
    config = OidcConfig.from_env()
    with pytest.raises(ValueError):
        exchange_refresh_token_for_tokens(config, refresh_token=rt)


def test_g996_refresh_response_includes_expires_in(mock_oidc_with_refresh):
    """H.G996 — Refresh response incluye expires_in."""
    from prostanet.shared.oidc_client import (
        OidcConfig, exchange_refresh_token_for_tokens,
    )
    code, at, rt = mock_oidc_with_refresh.add_authorized_user("u4")
    config = OidcConfig.from_env()
    resp = exchange_refresh_token_for_tokens(config, refresh_token=rt)
    assert resp.expires_in == 3600


def test_g997_refresh_no_rotation_returns_empty_refresh_token(mock_oidc_with_refresh):
    """H.G997 — Si IDP no rota (Google), response refresh_token=''."""
    from prostanet.shared.oidc_client import (
        OidcConfig, exchange_refresh_token_for_tokens,
    )
    mock_oidc_with_refresh.rotate_refresh_tokens = False
    code, at, rt = mock_oidc_with_refresh.add_authorized_user("u5")
    config = OidcConfig.from_env()
    resp = exchange_refresh_token_for_tokens(config, refresh_token=rt)
    assert resp.refresh_token == ""  # not rotated; caller keeps original


# ════════════════════════════════════════════════════════════════════
# §C. Session storage helpers (H.G998-H.G1006)
# ════════════════════════════════════════════════════════════════════


def test_g998_session_store_oidc_tokens_basic():
    """H.G998 — store_oidc_tokens persiste tokens correctamente."""
    from prostanet.shared.auth_backends import (
        session_store_oidc_tokens, session_get_access_token,
        session_get_refresh_token,
    )
    sess = {}
    session_store_oidc_tokens(
        sess, access_token="AT", refresh_token="RT", expires_in=3600,
    )
    assert session_get_access_token(sess) == "AT"
    assert session_get_refresh_token(sess) == "RT"


def test_g999_session_token_seconds_until_expiry():
    """H.G999 — seconds_until_expiry calcula correctamente."""
    from prostanet.shared.auth_backends import (
        session_store_oidc_tokens, session_token_seconds_until_expiry,
    )
    sess = {}
    session_store_oidc_tokens(
        sess, access_token="AT", refresh_token="RT", expires_in=3600,
    )
    seconds = session_token_seconds_until_expiry(sess)
    assert 3590 <= seconds <= 3600  # allow 10s for test execution time


def test_g1000_session_token_seconds_zero_when_no_expiry():
    """H.G1000 — Si no hay expires_at almacenado, retorna 0."""
    from prostanet.shared.auth_backends import session_token_seconds_until_expiry
    assert session_token_seconds_until_expiry({}) == 0


def test_g1001_session_increment_refresh_count():
    """H.G1001 — increment_refresh_count incrementa + retorna count."""
    from prostanet.shared.auth_backends import (
        session_increment_refresh_count, SESSION_REFRESH_COUNT_KEY,
        SESSION_LAST_REFRESH_AT_KEY,
    )
    sess = {}
    c1 = session_increment_refresh_count(sess)
    c2 = session_increment_refresh_count(sess)
    c3 = session_increment_refresh_count(sess)
    assert c1 == 1
    assert c2 == 2
    assert c3 == 3
    assert sess[SESSION_REFRESH_COUNT_KEY] == 3
    assert sess[SESSION_LAST_REFRESH_AT_KEY]


def test_g1002_session_logout_clears_tokens():
    """H.G1002 — Logout limpia tokens (security: no leak post-logout)."""
    from prostanet.shared.auth_backends import (
        session_store_oidc_tokens, session_logout,
        session_get_access_token, session_get_refresh_token,
    )
    sess = {}
    session_store_oidc_tokens(
        sess, access_token="AT", refresh_token="RT", expires_in=3600,
    )
    session_logout(sess)
    assert session_get_access_token(sess) == ""
    assert session_get_refresh_token(sess) == ""


def test_g1003_session_logout_clears_refresh_count():
    """H.G1003 — Logout limpia refresh_count + last_refresh_at."""
    from prostanet.shared.auth_backends import (
        session_increment_refresh_count, session_logout,
        SESSION_REFRESH_COUNT_KEY, SESSION_LAST_REFRESH_AT_KEY,
    )
    sess = {SESSION_REFRESH_COUNT_KEY: 5}
    session_increment_refresh_count(sess)  # makes it 6
    session_logout(sess)
    assert SESSION_REFRESH_COUNT_KEY not in sess
    assert SESSION_LAST_REFRESH_AT_KEY not in sess


def test_g1004_session_get_refresh_token_empty_default():
    """H.G1004 — get_refresh_token retorna '' por default."""
    from prostanet.shared.auth_backends import session_get_refresh_token
    assert session_get_refresh_token({}) == ""


def test_g1005_session_get_access_token_empty_default():
    """H.G1005 — get_access_token retorna '' por default."""
    from prostanet.shared.auth_backends import session_get_access_token
    assert session_get_access_token({}) == ""


def test_g1006_store_oidc_tokens_partial_data():
    """H.G1006 — store_oidc_tokens maneja campos parciales (some empty)."""
    from prostanet.shared.auth_backends import (
        session_store_oidc_tokens, session_get_access_token,
        session_get_refresh_token, session_token_seconds_until_expiry,
    )
    sess = {}
    # Solo access_token, sin refresh
    session_store_oidc_tokens(
        sess, access_token="AT", refresh_token="", expires_in=0,
    )
    assert session_get_access_token(sess) == "AT"
    assert session_get_refresh_token(sess) == ""
    assert session_token_seconds_until_expiry(sess) == 0  # no expires_at set


# ════════════════════════════════════════════════════════════════════
# §D. POST /api/auth/refresh endpoint (H.G1007-H.G1015)
# ════════════════════════════════════════════════════════════════════


def test_g1007_refresh_endpoint_no_session_returns_401(client_oidc):
    """H.G1007 — POST /refresh sin sesión → 401."""
    resp = client_oidc.post("/api/auth/refresh")
    assert resp.status_code == 401
    assert resp.get_json()["success"] is False


def test_g1008_refresh_endpoint_no_token_returns_401(client_oidc, mock_oidc_with_refresh):
    """H.G1008 — POST /refresh con sesión pero sin refresh_token → 401."""
    # OIDC login flow to set session
    code, at, rt = mock_oidc_with_refresh.add_authorized_user(
        "alice_g1008", preferred_username="alice",
    )
    client_oidc.get("/api/auth/oidc/login", follow_redirects=False)
    with client_oidc.session_transaction() as sess:
        valid_state = sess.get("_oidc_state")
    client_oidc.get(f"/api/auth/oidc/callback?code={code}&state={valid_state}")

    # Manually clear refresh_token from session
    with client_oidc.session_transaction() as sess:
        sess.pop("_clinical_refresh_token", None)

    resp = client_oidc.post("/api/auth/refresh")
    assert resp.status_code == 401
    assert "refresh token" in resp.get_json()["error"].lower()


def test_g1009_refresh_endpoint_success(client_oidc, mock_oidc_with_refresh):
    """H.G1009 — POST /refresh con sesión + refresh_token → 200."""
    code, at, rt = mock_oidc_with_refresh.add_authorized_user(
        "alice_g1009", preferred_username="alice",
    )
    client_oidc.get("/api/auth/oidc/login", follow_redirects=False)
    with client_oidc.session_transaction() as sess:
        valid_state = sess.get("_oidc_state")
    client_oidc.get(f"/api/auth/oidc/callback?code={code}&state={valid_state}")

    resp = client_oidc.post("/api/auth/refresh")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["expires_in"] > 0
    assert data["refresh_count"] == 1


def test_g1010_refresh_increments_count_per_call(client_oidc, mock_oidc_with_refresh):
    """H.G1010 — Múltiples refreshes incrementan refresh_count secuencial."""
    code, at, rt = mock_oidc_with_refresh.add_authorized_user(
        "bob_g1010", preferred_username="bob",
    )
    client_oidc.get("/api/auth/oidc/login", follow_redirects=False)
    with client_oidc.session_transaction() as sess:
        valid_state = sess.get("_oidc_state")
    client_oidc.get(f"/api/auth/oidc/callback?code={code}&state={valid_state}")

    counts = []
    for _ in range(3):
        r = client_oidc.post("/api/auth/refresh")
        counts.append(r.get_json()["refresh_count"])
    assert counts == [1, 2, 3]


def test_g1011_refresh_idp_failure_invalidates_session(client_oidc, mock_oidc_with_refresh):
    """H.G1011 — Si refresh falla, sesión es invalidated (security)."""
    code, at, rt = mock_oidc_with_refresh.add_authorized_user(
        "carol_g1011", preferred_username="carol",
    )
    client_oidc.get("/api/auth/oidc/login", follow_redirects=False)
    with client_oidc.session_transaction() as sess:
        valid_state = sess.get("_oidc_state")
    client_oidc.get(f"/api/auth/oidc/callback?code={code}&state={valid_state}")

    # Simulate IDP failure
    mock_oidc_with_refresh.failure_mode = "refresh"
    resp = client_oidc.post("/api/auth/refresh")
    assert resp.status_code == 502

    # Session should be invalidated
    whoami_resp = client_oidc.get("/api/auth/whoami")
    assert whoami_resp.get_json()["authenticated"] is False


def test_g1012_refresh_writes_audit_log_on_success(client_oidc, mock_oidc_with_refresh, isolated_db):
    """H.G1012 — Refresh exitoso persiste audit log entry."""
    from prostanet.shared.auth_db import get_audit_log_entries

    code, at, rt = mock_oidc_with_refresh.add_authorized_user(
        "diane_g1012", preferred_username="diane",
    )
    client_oidc.get("/api/auth/oidc/login", follow_redirects=False)
    with client_oidc.session_transaction() as sess:
        valid_state = sess.get("_oidc_state")
    client_oidc.get(f"/api/auth/oidc/callback?code={code}&state={valid_state}")

    client_oidc.post("/api/auth/refresh")
    entries = get_audit_log_entries(endpoint="refresh", status="authorized")
    assert len(entries) >= 1
    assert "refresh_count=1" in (entries[0].get("reason") or "")


def test_g1013_refresh_writes_audit_log_on_failure(client_oidc, mock_oidc_with_refresh, isolated_db):
    """H.G1013 — Refresh fallido persiste audit log con razón específica."""
    from prostanet.shared.auth_db import get_audit_log_entries

    code, at, rt = mock_oidc_with_refresh.add_authorized_user("eve_g1013")
    client_oidc.get("/api/auth/oidc/login", follow_redirects=False)
    with client_oidc.session_transaction() as sess:
        valid_state = sess.get("_oidc_state")
    client_oidc.get(f"/api/auth/oidc/callback?code={code}&state={valid_state}")

    mock_oidc_with_refresh.failure_mode = "refresh"
    client_oidc.post("/api/auth/refresh")
    entries = get_audit_log_entries(
        endpoint="refresh", status="denied_refresh_failed",
    )
    assert len(entries) >= 1


def test_g1014_refresh_response_includes_rotation_flag(client_oidc, mock_oidc_with_refresh):
    """H.G1014 — Refresh response indica si refresh_token fue rotado."""
    code, at, rt = mock_oidc_with_refresh.add_authorized_user(
        "frank_g1014", preferred_username="frank",
    )
    client_oidc.get("/api/auth/oidc/login", follow_redirects=False)
    with client_oidc.session_transaction() as sess:
        valid_state = sess.get("_oidc_state")
    client_oidc.get(f"/api/auth/oidc/callback?code={code}&state={valid_state}")

    resp = client_oidc.post("/api/auth/refresh")
    assert resp.get_json()["refresh_token_rotated"] is True


def test_g1015_refresh_persists_new_tokens_in_session(client_oidc, mock_oidc_with_refresh):
    """H.G1015 — Refresh actualiza session con nuevos tokens."""
    code, at, rt = mock_oidc_with_refresh.add_authorized_user(
        "grace_g1015", preferred_username="grace",
    )
    client_oidc.get("/api/auth/oidc/login", follow_redirects=False)
    with client_oidc.session_transaction() as sess:
        valid_state = sess.get("_oidc_state")
    client_oidc.get(f"/api/auth/oidc/callback?code={code}&state={valid_state}")

    # Capture original tokens
    with client_oidc.session_transaction() as sess:
        original_at = sess.get("_clinical_access_token")
        original_rt = sess.get("_clinical_refresh_token")

    client_oidc.post("/api/auth/refresh")

    # Verify tokens changed
    with client_oidc.session_transaction() as sess:
        new_at = sess.get("_clinical_access_token")
        new_rt = sess.get("_clinical_refresh_token")
    assert new_at != original_at
    assert new_rt != original_rt  # mock rotates


# ════════════════════════════════════════════════════════════════════
# §E. GET /api/auth/session-status endpoint (H.G1016-H.G1023)
# ════════════════════════════════════════════════════════════════════


def test_g1016_session_status_unauthenticated(client_oidc):
    """H.G1016 — session-status sin auth retorna authenticated:false."""
    resp = client_oidc.get("/api/auth/session-status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["authenticated"] is False


def test_g1017_session_status_authenticated_oidc(client_oidc, mock_oidc_with_refresh):
    """H.G1017 — session-status authenticated retorna user info + token state."""
    code, at, rt = mock_oidc_with_refresh.add_authorized_user(
        "henry_g1017", preferred_username="henry", roles=["clinician"],
    )
    client_oidc.get("/api/auth/oidc/login", follow_redirects=False)
    with client_oidc.session_transaction() as sess:
        valid_state = sess.get("_oidc_state")
    client_oidc.get(f"/api/auth/oidc/callback?code={code}&state={valid_state}")

    resp = client_oidc.get("/api/auth/session-status")
    data = resp.get_json()
    assert data["authenticated"] is True
    assert data["username"] == "henry"
    assert data["role"] == "clinician"
    assert data["has_refresh_token"] is True


def test_g1018_session_status_includes_token_expiry(client_oidc, mock_oidc_with_refresh):
    """H.G1018 — session-status incluye access_token_seconds_until_expiry."""
    code, at, rt = mock_oidc_with_refresh.add_authorized_user(
        "ivan_g1018", preferred_username="ivan",
    )
    client_oidc.get("/api/auth/oidc/login", follow_redirects=False)
    with client_oidc.session_transaction() as sess:
        valid_state = sess.get("_oidc_state")
    client_oidc.get(f"/api/auth/oidc/callback?code={code}&state={valid_state}")

    resp = client_oidc.get("/api/auth/session-status")
    data = resp.get_json()
    assert data["access_token_seconds_until_expiry"] > 3000  # ~3600 minus test overhead


def test_g1019_session_status_includes_session_timeout(client_oidc, mock_oidc_with_refresh):
    """H.G1019 — session-status incluye session_seconds_until_timeout
    (campo back-compat = min(idle, absolute) tras Tier 7 G7 XXXIX).

    Este test originalmente asumía que `session_seconds_until_timeout`
    era el ABSOLUTE timeout (~28800s = 8h). Tras G7 ese campo expone
    el MÍNIMO de idle/absolute (porque es la dimensión más restrictiva
    que el cliente debe respetar). Ahora verificamos:
      - El campo legacy refleja el mínimo (~1800s = 30min idle por defecto)
      - El nuevo campo explícito `session_seconds_until_absolute_timeout`
        sigue exponiendo el cap absoluto.
    """
    code, at, rt = mock_oidc_with_refresh.add_authorized_user("judy_g1019")
    client_oidc.get("/api/auth/oidc/login", follow_redirects=False)
    with client_oidc.session_transaction() as sess:
        valid_state = sess.get("_oidc_state")
    client_oidc.get(f"/api/auth/oidc/callback?code={code}&state={valid_state}")

    resp = client_oidc.get("/api/auth/session-status")
    data = resp.get_json()
    # Back-compat field: min(idle, absolute) → idle wins (1800s default).
    assert data["session_seconds_until_timeout"] > 0
    assert data["session_seconds_until_timeout"] <= 1800
    # G7 explicit absolute field still ~28800.
    assert data["session_seconds_until_absolute_timeout"] > 28000


def test_g1020_session_status_refresh_count_zero_initially(client_oidc, mock_oidc_with_refresh):
    """H.G1020 — refresh_count es 0 antes del primer refresh."""
    code, at, rt = mock_oidc_with_refresh.add_authorized_user("kate_g1020")
    client_oidc.get("/api/auth/oidc/login", follow_redirects=False)
    with client_oidc.session_transaction() as sess:
        valid_state = sess.get("_oidc_state")
    client_oidc.get(f"/api/auth/oidc/callback?code={code}&state={valid_state}")

    resp = client_oidc.get("/api/auth/session-status")
    assert resp.get_json()["refresh_count"] == 0


def test_g1021_session_status_refresh_count_increments_after_refresh(client_oidc, mock_oidc_with_refresh):
    """H.G1021 — refresh_count incrementa tras refresh exitoso."""
    code, at, rt = mock_oidc_with_refresh.add_authorized_user("leo_g1021")
    client_oidc.get("/api/auth/oidc/login", follow_redirects=False)
    with client_oidc.session_transaction() as sess:
        valid_state = sess.get("_oidc_state")
    client_oidc.get(f"/api/auth/oidc/callback?code={code}&state={valid_state}")

    # Refresh twice
    client_oidc.post("/api/auth/refresh")
    client_oidc.post("/api/auth/refresh")

    resp = client_oidc.get("/api/auth/session-status")
    data = resp.get_json()
    assert data["refresh_count"] == 2
    assert data["last_refresh_at"]


def test_g1022_session_status_after_logout(client_oidc, mock_oidc_with_refresh):
    """H.G1022 — Tras logout, session-status retorna authenticated:false."""
    code, at, rt = mock_oidc_with_refresh.add_authorized_user("mia_g1022")
    client_oidc.get("/api/auth/oidc/login", follow_redirects=False)
    with client_oidc.session_transaction() as sess:
        valid_state = sess.get("_oidc_state")
    client_oidc.get(f"/api/auth/oidc/callback?code={code}&state={valid_state}")
    client_oidc.post("/api/auth/logout")

    resp = client_oidc.get("/api/auth/session-status")
    assert resp.get_json()["authenticated"] is False


def test_g1023_session_status_local_pbkdf2_no_refresh_token(client_oidc, isolated_db, monkeypatch):
    """H.G1023 — Local PBKDF2 backend session: has_refresh_token=False (no OIDC flow)."""
    monkeypatch.setenv("PROSTANET_AUTH_BACKEND", "local")
    if "app" in sys.modules:
        del sys.modules["app"]
    import app as app_module
    fresh_app = app_module.create_app({"TESTING": True, "DB_PATH": str(isolated_db)})
    with fresh_app.test_client() as c:
        from prostanet.shared.auth_backends import LocalPbkdf2Backend
        LocalPbkdf2Backend().create_user(
            username="local_user", password="local_pass", role="clinician",
        )
        c.post("/api/auth/login", json={"username": "local_user", "password": "local_pass"})
        resp = c.get("/api/auth/session-status")
        data = resp.get_json()
        assert data["authenticated"] is True
        assert data["has_refresh_token"] is False  # local backend doesn't issue OIDC tokens


# ════════════════════════════════════════════════════════════════════
# §F. End-to-end flows (H.G1024-H.G1030)
# ════════════════════════════════════════════════════════════════════


def test_g1024_e2e_oidc_login_then_refresh_keeps_session(client_oidc, mock_oidc_with_refresh):
    """H.G1024 — E2E: login OIDC → /refresh → /whoami sigue authenticated."""
    code, at, rt = mock_oidc_with_refresh.add_authorized_user(
        "ruth_e2e", preferred_username="ruth",
    )
    client_oidc.get("/api/auth/oidc/login", follow_redirects=False)
    with client_oidc.session_transaction() as sess:
        valid_state = sess.get("_oidc_state")
    client_oidc.get(f"/api/auth/oidc/callback?code={code}&state={valid_state}")

    # Initial whoami
    r = client_oidc.get("/api/auth/whoami")
    assert r.get_json()["authenticated"] is True
    assert r.get_json()["username"] == "ruth"

    # Refresh
    r = client_oidc.post("/api/auth/refresh")
    assert r.status_code == 200

    # Still authenticated
    r = client_oidc.get("/api/auth/whoami")
    assert r.get_json()["authenticated"] is True


def test_g1025_e2e_session_status_decreases_after_passage_of_time(client_oidc, mock_oidc_with_refresh):
    """H.G1025 — access_token_seconds_until_expiry decrementa con el paso del tiempo."""
    code, at, rt = mock_oidc_with_refresh.add_authorized_user("sam_g1025")
    client_oidc.get("/api/auth/oidc/login", follow_redirects=False)
    with client_oidc.session_transaction() as sess:
        valid_state = sess.get("_oidc_state")
    client_oidc.get(f"/api/auth/oidc/callback?code={code}&state={valid_state}")

    # First call
    s1 = client_oidc.get("/api/auth/session-status").get_json()
    time.sleep(1.5)
    s2 = client_oidc.get("/api/auth/session-status").get_json()

    assert s2["access_token_seconds_until_expiry"] < s1["access_token_seconds_until_expiry"]


def test_g1026_e2e_refresh_resets_token_expiry_window(client_oidc, mock_oidc_with_refresh):
    """H.G1026 — Tras refresh, access_token_seconds_until_expiry vuelve a ~3600."""
    code, at, rt = mock_oidc_with_refresh.add_authorized_user("tina_g1026")
    client_oidc.get("/api/auth/oidc/login", follow_redirects=False)
    with client_oidc.session_transaction() as sess:
        valid_state = sess.get("_oidc_state")
    client_oidc.get(f"/api/auth/oidc/callback?code={code}&state={valid_state}")

    time.sleep(2)
    s1 = client_oidc.get("/api/auth/session-status").get_json()
    expiry_before = s1["access_token_seconds_until_expiry"]

    client_oidc.post("/api/auth/refresh")
    s2 = client_oidc.get("/api/auth/session-status").get_json()
    expiry_after = s2["access_token_seconds_until_expiry"]

    # After refresh, expiry should reset to ~3600 (was ~3598 before refresh)
    assert expiry_after > expiry_before


def test_g1027_e2e_failed_refresh_then_session_status_shows_unauth(client_oidc, mock_oidc_with_refresh):
    """H.G1027 — Failed refresh invalidates session; session-status confirms."""
    code, at, rt = mock_oidc_with_refresh.add_authorized_user("uma_g1027")
    client_oidc.get("/api/auth/oidc/login", follow_redirects=False)
    with client_oidc.session_transaction() as sess:
        valid_state = sess.get("_oidc_state")
    client_oidc.get(f"/api/auth/oidc/callback?code={code}&state={valid_state}")

    # Sanity check: authenticated initially
    s = client_oidc.get("/api/auth/session-status").get_json()
    assert s["authenticated"] is True

    # Force failure
    mock_oidc_with_refresh.failure_mode = "refresh"
    client_oidc.post("/api/auth/refresh")

    # Now unauthenticated
    s = client_oidc.get("/api/auth/session-status").get_json()
    assert s["authenticated"] is False


def test_g1028_e2e_logout_after_refresh_clears_everything(client_oidc, mock_oidc_with_refresh):
    """H.G1028 — Logout post-refresh limpia tokens + refresh_count."""
    code, at, rt = mock_oidc_with_refresh.add_authorized_user("victor_g1028")
    client_oidc.get("/api/auth/oidc/login", follow_redirects=False)
    with client_oidc.session_transaction() as sess:
        valid_state = sess.get("_oidc_state")
    client_oidc.get(f"/api/auth/oidc/callback?code={code}&state={valid_state}")

    client_oidc.post("/api/auth/refresh")
    client_oidc.post("/api/auth/refresh")
    client_oidc.post("/api/auth/logout")

    with client_oidc.session_transaction() as sess:
        assert "_clinical_refresh_token" not in sess
        assert "_clinical_access_token" not in sess
        assert "_clinical_refresh_count" not in sess


def test_g1029_e2e_audit_log_captures_full_refresh_lifecycle(
    client_oidc, mock_oidc_with_refresh, isolated_db,
):
    """H.G1029 — Audit log captura: login → refresh × N → logout completo."""
    from prostanet.shared.auth_db import get_audit_log_entries

    code, at, rt = mock_oidc_with_refresh.add_authorized_user("wendy_g1029")
    client_oidc.get("/api/auth/oidc/login", follow_redirects=False)
    with client_oidc.session_transaction() as sess:
        valid_state = sess.get("_oidc_state")
    client_oidc.get(f"/api/auth/oidc/callback?code={code}&state={valid_state}")
    client_oidc.post("/api/auth/refresh")
    client_oidc.post("/api/auth/refresh")
    client_oidc.post("/api/auth/refresh")
    client_oidc.post("/api/auth/logout")

    # Should have: 1 oidc_callback authorized + 3 refresh authorized + 1 logout authorized
    refresh_entries = get_audit_log_entries(
        endpoint="refresh", status="authorized",
    )
    assert len(refresh_entries) == 3
    # refresh_count progression: 1, 2, 3
    counts = sorted([
        int(e["reason"].split("refresh_count=")[1].split(";")[0])
        for e in refresh_entries
    ])
    assert counts == [1, 2, 3]


def test_g1030_e2e_concurrent_refresh_calls_consistent(client_oidc, mock_oidc_with_refresh):
    """H.G1030 — Múltiples refreshes secuenciales actualizan token consistentemente."""
    code, at, rt = mock_oidc_with_refresh.add_authorized_user("xavier_g1030")
    client_oidc.get("/api/auth/oidc/login", follow_redirects=False)
    with client_oidc.session_transaction() as sess:
        valid_state = sess.get("_oidc_state")
    client_oidc.get(f"/api/auth/oidc/callback?code={code}&state={valid_state}")

    # 5 sequential refreshes
    for i in range(1, 6):
        r = client_oidc.post("/api/auth/refresh")
        assert r.status_code == 200
        assert r.get_json()["refresh_count"] == i
