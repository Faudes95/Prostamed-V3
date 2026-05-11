"""tests/test_tier7_g16_federated_oidc.py — FAUBOT 2026-04-25 (XXIX).

Tier 7 G1.6 — Federación IDP via OIDC provider-agnostic.

Cobertura:
  - PKCE generation + state + nonce
  - OidcConfig env-driven (validation, defaults)
  - Discovery doc fetch + cache
  - Authorization URL builder
  - Token exchange (mock provider)
  - Userinfo fetch (mock provider)
  - JIT user provisioning (first OIDC login auto-creates clinical_users)
  - OidcBackend role mapping (generic + Keycloak realm_access)
  - HTTP endpoints /api/auth/oidc/login + /oidc/callback
  - State CSRF protection
  - Backward-compat: LocalPbkdf2Backend sigue funcionando

Hipótesis: H.G542-H.G601 (~60 hipótesis sobre OIDC flow + JIT + endpoints).

Usa MockOidcProvider que sirve discovery + token + userinfo en
http.server local — NO requiere external IDP services.
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import http.server
import json
import os
import socketserver
import sys
import threading
import time
import urllib.parse

import pytest


# ════════════════════════════════════════════════════════════════════
# §A. Mock OIDC Provider (local HTTP server for tests)
# ════════════════════════════════════════════════════════════════════


class MockOidcProvider:
    """Servidor HTTP local que simula OIDC IDP completo (discovery +
    token + userinfo).

    Uso:
        with MockOidcProvider() as provider:
            issuer = provider.issuer  # http://127.0.0.1:<port>
            # configure env vars + run tests
    """

    def __init__(self, port: int = 0):
        self.port = port
        self.httpd = None
        self.thread = None
        self.issuer = ""
        # In-memory state for tests
        self.codes: dict[str, dict] = {}     # code → {access_token, sub}
        self.access_tokens: dict[str, dict] = {}  # token → userinfo dict
        self.failure_mode: str = ""           # 'discovery'/'token'/'userinfo'

    def __enter__(self):
        provider = self  # closure capture

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a, **kw):  # silence
                pass

            def do_GET(self):
                if provider.failure_mode == "discovery" and "/.well-known/" in self.path:
                    self.send_response(503)
                    self.end_headers()
                    return

                if self.path == "/.well-known/openid-configuration":
                    body = json.dumps({
                        "issuer": provider.issuer,
                        "authorization_endpoint": f"{provider.issuer}/oauth/authorize",
                        "token_endpoint": f"{provider.issuer}/oauth/token",
                        "userinfo_endpoint": f"{provider.issuer}/oauth/userinfo",
                        "jwks_uri": f"{provider.issuer}/.well-known/jwks.json",
                        "response_types_supported": ["code"],
                        "subject_types_supported": ["public"],
                        "id_token_signing_alg_values_supported": ["RS256"],
                        "scopes_supported": ["openid", "email", "profile"],
                    }).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

                if self.path.startswith("/oauth/userinfo"):
                    if provider.failure_mode == "userinfo":
                        self.send_response(401)
                        self.end_headers()
                        return
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
                if provider.failure_mode == "token" and "/oauth/token" in self.path:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b'{"error":"invalid_grant"}')
                    return

                if self.path == "/oauth/token":
                    length = int(self.headers.get("Content-Length", "0"))
                    body_raw = self.rfile.read(length).decode("utf-8")
                    params = dict(urllib.parse.parse_qsl(body_raw))
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
                        "scope": "openid email profile",
                    }
                    body = json.dumps(response).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(body)
                    return

                self.send_response(404)
                self.end_headers()

        # Bind to ephemeral port
        self.httpd = socketserver.TCPServer(("127.0.0.1", self.port), Handler)
        self.port = self.httpd.server_address[1]
        self.issuer = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        # Brief sleep for socket to be ready
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
        realm_access_roles: list[str] | None = None,
    ) -> tuple[str, str]:
        """Pre-register a user available via auth code flow.

        Returns:
            (code, access_token) — use code in callback simulation.
        """
        code = f"code_{sub}_{int(time.time() * 1000)}"
        access_token = f"at_{sub}_{int(time.time() * 1000)}"
        userinfo = {"sub": sub}
        if email:
            userinfo["email"] = email
        if preferred_username:
            userinfo["preferred_username"] = preferred_username
        if roles:
            userinfo["roles"] = roles
        if realm_access_roles is not None:
            userinfo["realm_access"] = {"roles": realm_access_roles}
        self.codes[code] = {"access_token": access_token, "sub": sub}
        self.access_tokens[access_token] = userinfo
        return code, access_token


# ════════════════════════════════════════════════════════════════════
# Fixtures
# ════════════════════════════════════════════════════════════════════


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """DB SQLite limpia + reset state."""
    db_path = tmp_path / "test_g16.db"
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
def mock_oidc(isolated_db, monkeypatch):
    """Spawn mock OIDC provider on local port + configure env."""
    with MockOidcProvider() as provider:
        monkeypatch.setenv("PROSTANET_OIDC_ISSUER", provider.issuer)
        monkeypatch.setenv("PROSTANET_OIDC_CLIENT_ID", "test-client")
        monkeypatch.setenv("PROSTANET_OIDC_CLIENT_SECRET", "test-secret")
        monkeypatch.setenv(
            "PROSTANET_OIDC_REDIRECT_URI",
            "http://localhost:8080/api/auth/oidc/callback",
        )
        monkeypatch.setenv("PROSTANET_AUTH_BACKEND", "oidc")
        from prostanet.shared.auth_backends import reset_auth_backend_for_tests
        reset_auth_backend_for_tests()
        yield provider


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
# §B. PKCE + state + nonce generation (H.G542-H.G548)
# ════════════════════════════════════════════════════════════════════


def test_g542_pkce_pair_format():
    """H.G542 — PKCE pair: verifier 43-128 URL-safe chars."""
    from prostanet.shared.oidc_client import generate_pkce_pair
    v, c = generate_pkce_pair()
    assert 43 <= len(v) <= 128
    assert all(ch.isalnum() or ch in "-._~" for ch in v)
    assert len(c) == 43  # SHA256 base64url-nopad


def test_g543_pkce_challenge_is_sha256_of_verifier():
    """H.G543 — code_challenge = BASE64URL(SHA256(verifier))."""
    import base64, hashlib
    from prostanet.shared.oidc_client import generate_pkce_pair
    v, c = generate_pkce_pair()
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(v.encode("ascii")).digest(),
    ).decode("ascii").rstrip("=")
    assert c == expected


def test_g544_pkce_pairs_are_unique():
    """H.G544 — PKCE pairs son únicos por invocación."""
    from prostanet.shared.oidc_client import generate_pkce_pair
    v1, _ = generate_pkce_pair()
    v2, _ = generate_pkce_pair()
    assert v1 != v2


def test_g545_state_token_url_safe():
    """H.G545 — state token es URL-safe (no padding)."""
    from prostanet.shared.oidc_client import generate_state_token
    s = generate_state_token()
    assert "=" not in s
    assert all(ch.isalnum() or ch in "-_" for ch in s)


def test_g546_state_tokens_are_unique():
    """H.G546 — state tokens son únicos."""
    from prostanet.shared.oidc_client import generate_state_token
    s1 = generate_state_token()
    s2 = generate_state_token()
    assert s1 != s2


def test_g547_nonce_url_safe():
    """H.G547 — nonce URL-safe."""
    from prostanet.shared.oidc_client import generate_nonce
    n = generate_nonce()
    assert "=" not in n


def test_g548_nonce_unique_per_call():
    """H.G548 — nonces únicos."""
    from prostanet.shared.oidc_client import generate_nonce
    assert generate_nonce() != generate_nonce()


# ════════════════════════════════════════════════════════════════════
# §C. OidcConfig env-driven (H.G549-H.G554)
# ════════════════════════════════════════════════════════════════════


def test_g549_config_from_env_requires_issuer(monkeypatch):
    """H.G549 — from_env raises si PROSTANET_OIDC_ISSUER missing."""
    monkeypatch.delenv("PROSTANET_OIDC_ISSUER", raising=False)
    monkeypatch.setenv("PROSTANET_OIDC_CLIENT_ID", "x")
    from prostanet.shared.oidc_client import OidcConfig
    with pytest.raises(ValueError, match="OIDC config incomplete"):
        OidcConfig.from_env()


def test_g550_config_from_env_requires_client_id(monkeypatch):
    """H.G550 — from_env raises si PROSTANET_OIDC_CLIENT_ID missing."""
    monkeypatch.setenv("PROSTANET_OIDC_ISSUER", "https://x.com")
    monkeypatch.delenv("PROSTANET_OIDC_CLIENT_ID", raising=False)
    from prostanet.shared.oidc_client import OidcConfig
    with pytest.raises(ValueError, match="OIDC config incomplete"):
        OidcConfig.from_env()


def test_g551_config_from_env_minimal(monkeypatch):
    """H.G551 — from_env con minimal env vars (sin secret)."""
    monkeypatch.setenv("PROSTANET_OIDC_ISSUER", "https://idp.example.com")
    monkeypatch.setenv("PROSTANET_OIDC_CLIENT_ID", "myclient")
    from prostanet.shared.oidc_client import OidcConfig
    c = OidcConfig.from_env()
    assert c.issuer == "https://idp.example.com"
    assert c.client_id == "myclient"
    assert c.client_secret == ""
    assert c.scope == "openid email profile"  # default
    assert c.default_role == "clinician"


def test_g552_config_strips_trailing_slash(monkeypatch):
    """H.G552 — from_env strips trailing slash en issuer."""
    monkeypatch.setenv("PROSTANET_OIDC_ISSUER", "https://idp.example.com/")
    monkeypatch.setenv("PROSTANET_OIDC_CLIENT_ID", "x")
    from prostanet.shared.oidc_client import OidcConfig
    c = OidcConfig.from_env()
    assert c.issuer == "https://idp.example.com"


def test_g553_config_custom_scope(monkeypatch):
    """H.G553 — PROSTANET_OIDC_SCOPE custom override."""
    monkeypatch.setenv("PROSTANET_OIDC_ISSUER", "https://x.com")
    monkeypatch.setenv("PROSTANET_OIDC_CLIENT_ID", "x")
    monkeypatch.setenv("PROSTANET_OIDC_SCOPE", "openid email roles")
    from prostanet.shared.oidc_client import OidcConfig
    assert OidcConfig.from_env().scope == "openid email roles"


def test_g554_config_default_role_override(monkeypatch):
    """H.G554 — PROSTANET_OIDC_DEFAULT_ROLE override."""
    monkeypatch.setenv("PROSTANET_OIDC_ISSUER", "https://x.com")
    monkeypatch.setenv("PROSTANET_OIDC_CLIENT_ID", "x")
    monkeypatch.setenv("PROSTANET_OIDC_DEFAULT_ROLE", "auditor")
    from prostanet.shared.oidc_client import OidcConfig
    assert OidcConfig.from_env().default_role == "auditor"


# ════════════════════════════════════════════════════════════════════
# §D. Discovery doc + caching (H.G555-H.G558)
# ════════════════════════════════════════════════════════════════════


def test_g555_discovery_fetch_succeeds(mock_oidc):
    """H.G555 — fetch_discovery_doc retorna struct válido del mock."""
    from prostanet.shared.oidc_client import OidcConfig, fetch_discovery_doc
    config = OidcConfig.from_env()
    doc = fetch_discovery_doc(config)
    assert doc["issuer"] == mock_oidc.issuer
    assert doc["authorization_endpoint"]
    assert doc["token_endpoint"]
    assert doc["userinfo_endpoint"]


def test_g556_discovery_is_cached(mock_oidc):
    """H.G556 — Segunda llamada usa cache (verificable midiendo HTTP hits)."""
    from prostanet.shared.oidc_client import (
        OidcConfig, fetch_discovery_doc, _DISCOVERY_CACHE,
    )
    config = OidcConfig.from_env()
    fetch_discovery_doc(config)
    cache_keys_after_first = list(_DISCOVERY_CACHE.keys())
    fetch_discovery_doc(config)  # should hit cache
    assert list(_DISCOVERY_CACHE.keys()) == cache_keys_after_first


def test_g557_discovery_force_refresh(mock_oidc):
    """H.G557 — force_refresh=True hace nuevo fetch."""
    from prostanet.shared.oidc_client import (
        OidcConfig, fetch_discovery_doc, _DISCOVERY_CACHE,
    )
    config = OidcConfig.from_env()
    fetch_discovery_doc(config)
    # force_refresh should re-hit
    doc2 = fetch_discovery_doc(config, force_refresh=True)
    assert doc2["issuer"] == mock_oidc.issuer


def test_g558_discovery_failure_raises(mock_oidc):
    """H.G558 — Discovery doc fail raises ValueError."""
    from prostanet.shared.oidc_client import OidcConfig, fetch_discovery_doc, reset_discovery_cache
    mock_oidc.failure_mode = "discovery"
    reset_discovery_cache()
    config = OidcConfig.from_env()
    with pytest.raises(ValueError, match="Failed to fetch OIDC discovery"):
        fetch_discovery_doc(config)


# ════════════════════════════════════════════════════════════════════
# §E. Authorization URL builder (H.G559-H.G562)
# ════════════════════════════════════════════════════════════════════


def test_g559_authorization_url_includes_required_params(mock_oidc):
    """H.G559 — Auth URL incluye response_type=code, client_id, redirect_uri,
    scope, state, code_challenge, code_challenge_method."""
    from prostanet.shared.oidc_client import (
        OidcConfig, build_authorization_url, generate_pkce_pair,
        generate_state_token,
    )
    config = OidcConfig.from_env()
    _, challenge = generate_pkce_pair()
    state = generate_state_token()
    url = build_authorization_url(config, state=state, code_challenge=challenge)
    assert "response_type=code" in url
    assert "client_id=test-client" in url
    assert f"state={state}" in url
    assert f"code_challenge={challenge}" in url
    assert "code_challenge_method=S256" in url
    assert "scope=openid+email+profile" in url


def test_g560_authorization_url_includes_nonce_when_provided(mock_oidc):
    """H.G560 — Nonce included only si supplied."""
    from prostanet.shared.oidc_client import (
        OidcConfig, build_authorization_url, generate_pkce_pair,
        generate_state_token, generate_nonce,
    )
    config = OidcConfig.from_env()
    _, challenge = generate_pkce_pair()
    state = generate_state_token()
    nonce = generate_nonce()
    url = build_authorization_url(
        config, state=state, code_challenge=challenge, nonce=nonce,
    )
    assert f"nonce={nonce}" in url


def test_g561_authorization_url_omits_nonce_when_empty(mock_oidc):
    """H.G561 — Sin nonce, NO se incluye en URL."""
    from prostanet.shared.oidc_client import (
        OidcConfig, build_authorization_url, generate_pkce_pair,
        generate_state_token,
    )
    config = OidcConfig.from_env()
    _, challenge = generate_pkce_pair()
    url = build_authorization_url(
        config, state=generate_state_token(), code_challenge=challenge,
    )
    assert "nonce=" not in url


def test_g562_authorization_url_redirect_uri_encoded(mock_oidc):
    """H.G562 — redirect_uri queda URL-encoded en la URL."""
    from prostanet.shared.oidc_client import (
        OidcConfig, build_authorization_url, generate_pkce_pair,
        generate_state_token,
    )
    config = OidcConfig.from_env()
    _, challenge = generate_pkce_pair()
    url = build_authorization_url(
        config, state=generate_state_token(), code_challenge=challenge,
    )
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A8080%2Fapi%2Fauth%2Foidc%2Fcallback" in url


# ════════════════════════════════════════════════════════════════════
# §F. Token exchange (H.G563-H.G566)
# ════════════════════════════════════════════════════════════════════


def test_g563_token_exchange_succeeds(mock_oidc):
    """H.G563 — exchange_code_for_tokens retorna access_token válido."""
    from prostanet.shared.oidc_client import (
        OidcConfig, exchange_code_for_tokens, generate_pkce_pair,
    )
    code, expected_at = mock_oidc.add_authorized_user("user001", email="u1@x.com")
    config = OidcConfig.from_env()
    verifier, _ = generate_pkce_pair()
    resp = exchange_code_for_tokens(config, code=code, code_verifier=verifier)
    assert resp.access_token == expected_at
    assert resp.token_type == "Bearer"
    assert resp.expires_in > 0


def test_g564_token_exchange_invalid_code_raises(mock_oidc):
    """H.G564 — exchange con code invalid raises ValueError."""
    from prostanet.shared.oidc_client import (
        OidcConfig, exchange_code_for_tokens,
    )
    config = OidcConfig.from_env()
    with pytest.raises(ValueError, match="OIDC token exchange failed"):
        exchange_code_for_tokens(
            config, code="bogus", code_verifier="x" * 50,
        )


def test_g565_token_exchange_idp_error_raises(mock_oidc):
    """H.G565 — IDP returning error → ValueError."""
    from prostanet.shared.oidc_client import (
        OidcConfig, exchange_code_for_tokens, generate_pkce_pair,
    )
    code, _ = mock_oidc.add_authorized_user("user002")
    mock_oidc.failure_mode = "token"
    config = OidcConfig.from_env()
    verifier, _ = generate_pkce_pair()
    with pytest.raises(ValueError):
        exchange_code_for_tokens(config, code=code, code_verifier=verifier)


def test_g566_token_response_has_id_token(mock_oidc):
    """H.G566 — TokenResponse incluye id_token desde mock."""
    from prostanet.shared.oidc_client import (
        OidcConfig, exchange_code_for_tokens, generate_pkce_pair,
    )
    code, _ = mock_oidc.add_authorized_user("user003")
    verifier, _ = generate_pkce_pair()
    config = OidcConfig.from_env()
    resp = exchange_code_for_tokens(config, code=code, code_verifier=verifier)
    assert resp.id_token == "mock.id.token"


# ════════════════════════════════════════════════════════════════════
# §G. Userinfo endpoint (H.G567-H.G570)
# ════════════════════════════════════════════════════════════════════


def test_g567_userinfo_fetch_succeeds(mock_oidc):
    """H.G567 — fetch_userinfo retorna claims dict."""
    from prostanet.shared.oidc_client import OidcConfig, fetch_userinfo
    code, at = mock_oidc.add_authorized_user(
        "u_alice", email="alice@hospital.org",
        preferred_username="alice",
    )
    config = OidcConfig.from_env()
    info = fetch_userinfo(config, at)
    assert info["sub"] == "u_alice"
    assert info["email"] == "alice@hospital.org"
    assert info["preferred_username"] == "alice"


def test_g568_userinfo_invalid_token_raises(mock_oidc):
    """H.G568 — fetch_userinfo con token wrong raises."""
    from prostanet.shared.oidc_client import OidcConfig, fetch_userinfo
    config = OidcConfig.from_env()
    with pytest.raises(ValueError):
        fetch_userinfo(config, "bogus-token")


def test_g569_userinfo_missing_sub_raises(mock_oidc):
    """H.G569 — Si IDP retorna sin 'sub' claim, raises."""
    # Manually inject bogus token without sub
    mock_oidc.access_tokens["broken_at"] = {"email": "x@y.com"}
    from prostanet.shared.oidc_client import OidcConfig, fetch_userinfo
    config = OidcConfig.from_env()
    with pytest.raises(ValueError, match="missing 'sub' claim"):
        fetch_userinfo(config, "broken_at")


def test_g570_userinfo_failure_mode_raises(mock_oidc):
    """H.G570 — Userinfo HTTP failure raises ValueError."""
    code, at = mock_oidc.add_authorized_user("uX")
    mock_oidc.failure_mode = "userinfo"
    from prostanet.shared.oidc_client import OidcConfig, fetch_userinfo
    config = OidcConfig.from_env()
    with pytest.raises(ValueError):
        fetch_userinfo(config, at)


# ════════════════════════════════════════════════════════════════════
# §H. Username + external_id derivation (H.G571-H.G574)
# ════════════════════════════════════════════════════════════════════


def test_g571_username_priority_preferred_username():
    """H.G571 — preferred_username has highest priority."""
    from prostanet.shared.oidc_client import derive_username_from_userinfo
    info = {
        "preferred_username": "alice",
        "email": "alice@x.com",
        "sub": "u123",
    }
    assert derive_username_from_userinfo(info) == "alice"


def test_g572_username_fallback_to_email():
    """H.G572 — Sin preferred_username, usa email."""
    from prostanet.shared.oidc_client import derive_username_from_userinfo
    info = {"email": "bob@y.com", "sub": "u456"}
    assert derive_username_from_userinfo(info) == "bob@y.com"


def test_g573_username_fallback_to_sub():
    """H.G573 — Sin preferred_username/email, usa sub."""
    from prostanet.shared.oidc_client import derive_username_from_userinfo
    assert derive_username_from_userinfo({"sub": "auth0|999"}) == "auth0|999"


def test_g574_external_id_format():
    """H.G574 — external_id = `<issuer>|<sub>`."""
    from prostanet.shared.oidc_client import derive_external_id_from_userinfo
    info = {"sub": "user_abc"}
    assert derive_external_id_from_userinfo(info, "https://idp.example.com") == \
        "https://idp.example.com|user_abc"


# ════════════════════════════════════════════════════════════════════
# §I. JIT user provisioning (H.G575-H.G582)
# ════════════════════════════════════════════════════════════════════


def test_g575_jit_provisions_new_user(mock_oidc, isolated_db):
    """H.G575 — verify_userinfo_and_provision crea user si no existe."""
    from prostanet.shared.auth_backends import OidcBackend
    from prostanet.shared.auth_db import get_user_by_id
    backend = OidcBackend()
    userinfo = {
        "sub": "auth0|123abc",
        "email": "frank@hospital.org",
        "preferred_username": "frank",
    }
    uid = backend.verify_userinfo_and_provision(
        userinfo, issuer="https://idp.test",
    )
    assert uid > 0
    user = get_user_by_id(uid)
    assert user["username"] == "frank"
    assert user["email"] == "frank@hospital.org"
    assert user["backend"] == "oidc"
    assert user["external_id"] == "https://idp.test|auth0|123abc"


def test_g576_jit_returns_existing_user_on_repeat(mock_oidc, isolated_db):
    """H.G576 — Llamada repetida retorna mismo user_id (no duplica)."""
    from prostanet.shared.auth_backends import OidcBackend
    backend = OidcBackend()
    userinfo = {"sub": "u1", "email": "u1@x.com"}
    uid1 = backend.verify_userinfo_and_provision(userinfo, issuer="https://x.com")
    uid2 = backend.verify_userinfo_and_provision(userinfo, issuer="https://x.com")
    assert uid1 == uid2


def test_g577_jit_different_issuers_create_different_users(mock_oidc, isolated_db):
    """H.G577 — Mismo sub, diferentes issuers → diferentes users."""
    from prostanet.shared.auth_backends import OidcBackend
    backend = OidcBackend()
    info = {"sub": "shared_sub", "email": "x@y.com"}
    uid1 = backend.verify_userinfo_and_provision(info, issuer="https://a.com")
    uid2 = backend.verify_userinfo_and_provision(info, issuer="https://b.com")
    assert uid1 != uid2


def test_g578_jit_assigns_default_role(isolated_db):
    """H.G578 — JIT usa default_role del config si no hay claim."""
    from prostanet.shared.auth_backends import OidcBackend
    from prostanet.shared.auth_db import get_user_by_id
    backend = OidcBackend()
    uid = backend.verify_userinfo_and_provision(
        {"sub": "u1"}, issuer="https://x.com", default_role="auditor",
    )
    user = get_user_by_id(uid)
    assert user["role"] == "auditor"


def test_g579_jit_assigns_role_from_claim_when_valid(isolated_db):
    """H.G579 — JIT usa 'roles' claim cuando contiene role válido."""
    from prostanet.shared.auth_backends import OidcBackend
    from prostanet.shared.auth_db import get_user_by_id
    backend = OidcBackend()
    uid = backend.verify_userinfo_and_provision(
        {"sub": "u1", "roles": ["admin", "extra_role"]},
        issuer="https://x.com",
        default_role="viewer",
    )
    user = get_user_by_id(uid)
    assert user["role"] == "admin"


def test_g580_jit_keycloak_realm_access_role_mapping(isolated_db):
    """H.G580 — KeycloakBackend reads roles desde realm_access.roles."""
    from prostanet.shared.auth_backends import KeycloakBackend
    from prostanet.shared.auth_db import get_user_by_id
    backend = KeycloakBackend()
    uid = backend.verify_userinfo_and_provision(
        {
            "sub": "u1",
            "realm_access": {"roles": ["clinician", "default-roles-master"]},
        },
        issuer="https://kc.example.com",
        default_role="viewer",
    )
    user = get_user_by_id(uid)
    assert user["role"] == "clinician"


def test_g581_jit_missing_sub_raises(isolated_db):
    """H.G581 — Sin sub claim, raises ValueError."""
    from prostanet.shared.auth_backends import OidcBackend
    backend = OidcBackend()
    with pytest.raises(ValueError, match="missing 'sub' claim"):
        backend.verify_userinfo_and_provision(
            {"email": "x@y.com"}, issuer="https://x.com",
        )


def test_g582_jit_handles_username_collision(isolated_db):
    """H.G582 — Si dos OIDC subs producen mismo username, el 2do recibe suffix."""
    from prostanet.shared.auth_backends import OidcBackend
    from prostanet.shared.auth_db import get_user_by_id
    backend = OidcBackend()
    # Two users with same preferred_username but different subs
    uid1 = backend.verify_userinfo_and_provision(
        {"sub": "subA", "preferred_username": "alice"},
        issuer="https://x.com",
    )
    uid2 = backend.verify_userinfo_and_provision(
        {"sub": "subB", "preferred_username": "alice"},
        issuer="https://x.com",
    )
    user1 = get_user_by_id(uid1)
    user2 = get_user_by_id(uid2)
    assert user1["username"] != user2["username"]
    assert "alice" in user2["username"]


# ════════════════════════════════════════════════════════════════════
# §J. Backend registry includes OIDC (H.G583-H.G586)
# ════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("backend_name,expected_class", [
    ("oidc", "oidc"),
    ("auth0", "auth0"),
    ("keycloak", "keycloak"),
    ("oauth_google", "oauth_google"),
])
def test_g583_registry_selects_oidc_backends(monkeypatch, backend_name, expected_class):
    """H.G583 — Registry selecciona OIDC backends correctamente."""
    monkeypatch.setenv("PROSTANET_AUTH_BACKEND", backend_name)
    from prostanet.shared.auth_backends import (
        get_auth_backend, reset_auth_backend_for_tests, OidcBackend,
    )
    reset_auth_backend_for_tests()
    backend = get_auth_backend()
    assert backend.backend_name == expected_class
    assert isinstance(backend, OidcBackend)


def test_g584_local_backend_still_works(monkeypatch, isolated_db):
    """H.G584 — Backward-compat: LocalPbkdf2Backend still works post-G1.6."""
    monkeypatch.setenv("PROSTANET_AUTH_BACKEND", "local")
    from prostanet.shared.auth_backends import (
        get_auth_backend, reset_auth_backend_for_tests, LocalPbkdf2Backend,
    )
    reset_auth_backend_for_tests()
    backend = get_auth_backend()
    assert isinstance(backend, LocalPbkdf2Backend)
    uid = backend.create_user(username="lucas", password="lucas123")
    assert backend.verify("lucas", "lucas123") == uid


def test_g585_oidc_backend_create_user_raises():
    """H.G585 — OidcBackend.create_user raises NotImplementedError."""
    from prostanet.shared.auth_backends import OidcBackend
    backend = OidcBackend()
    with pytest.raises(NotImplementedError, match="JIT"):
        backend.create_user(username="x", password="y")


def test_g586_oidc_backend_verify_returns_none():
    """H.G586 — OidcBackend.verify(user, pass) returns None (no direct verify)."""
    from prostanet.shared.auth_backends import OidcBackend
    backend = OidcBackend()
    assert backend.verify("any", "any") is None


# ════════════════════════════════════════════════════════════════════
# §K. HTTP endpoints /api/auth/oidc/login + /callback (H.G587-H.G596)
# ════════════════════════════════════════════════════════════════════


def test_g587_oidc_login_endpoint_returns_redirect(mock_oidc, client):
    """H.G587 — GET /api/auth/oidc/login → 302 redirect to IDP."""
    resp = client.get("/api/auth/oidc/login", follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers.get("Location", "")
    assert mock_oidc.issuer in location
    assert "response_type=code" in location
    assert "code_challenge=" in location


def test_g588_oidc_login_stores_state_in_session(mock_oidc, client):
    """H.G588 — Después de /oidc/login, sesión tiene state + verifier + nonce."""
    with client.session_transaction() as sess:
        sess.clear()
    client.get("/api/auth/oidc/login", follow_redirects=False)
    with client.session_transaction() as sess:
        assert sess.get("_oidc_state")
        assert sess.get("_oidc_code_verifier")
        assert sess.get("_oidc_nonce")


def test_g589_oidc_login_when_misconfigured_returns_503(client, monkeypatch, isolated_db):
    """H.G589 — Si OIDC issuer no configurado, /oidc/login → 503."""
    monkeypatch.delenv("PROSTANET_OIDC_ISSUER", raising=False)
    monkeypatch.delenv("PROSTANET_OIDC_CLIENT_ID", raising=False)
    resp = client.get("/api/auth/oidc/login", follow_redirects=False)
    assert resp.status_code == 503


def test_g590_oidc_callback_validates_state(mock_oidc, client):
    """H.G590 — Callback con state mismatch → 400."""
    # Initiate login to set state
    client.get("/api/auth/oidc/login", follow_redirects=False)
    # Send callback with WRONG state
    resp = client.get("/api/auth/oidc/callback?code=x&state=WRONG_STATE")
    assert resp.status_code == 400
    data = resp.get_json()
    assert "state" in data["error"].lower()


def test_g591_oidc_callback_missing_state_in_session(mock_oidc, client):
    """H.G591 — Callback sin state previo en sesión → 400."""
    with client.session_transaction() as sess:
        sess.clear()
    resp = client.get("/api/auth/oidc/callback?code=x&state=foo")
    assert resp.status_code == 400


def test_g592_oidc_callback_missing_code(mock_oidc, client):
    """H.G592 — Callback sin code → 400."""
    client.get("/api/auth/oidc/login", follow_redirects=False)
    with client.session_transaction() as sess:
        valid_state = sess.get("_oidc_state")
    resp = client.get(f"/api/auth/oidc/callback?state={valid_state}")
    assert resp.status_code == 400


def test_g593_oidc_callback_idp_error_returns_401(mock_oidc, client):
    """H.G593 — Callback con error= param → 401."""
    client.get("/api/auth/oidc/login", follow_redirects=False)
    with client.session_transaction() as sess:
        valid_state = sess.get("_oidc_state")
    resp = client.get(
        f"/api/auth/oidc/callback?state={valid_state}&error=access_denied"
    )
    assert resp.status_code == 401


def test_g594_oidc_callback_full_flow_provisions_user(mock_oidc, client):
    """H.G594 — E2E callback: state ok + valid code → JIT provision + 200."""
    # Pre-register user in mock
    code, at = mock_oidc.add_authorized_user(
        "alice_sub", email="alice@hospital.org", preferred_username="alice",
    )
    # Initiate login (sets state + code_verifier)
    client.get("/api/auth/oidc/login", follow_redirects=False)
    with client.session_transaction() as sess:
        valid_state = sess.get("_oidc_state")
    # Callback with valid code + state
    resp = client.get(
        f"/api/auth/oidc/callback?code={code}&state={valid_state}"
    )
    assert resp.status_code == 200, f"Got {resp.status_code}: {resp.get_json()}"
    data = resp.get_json()
    assert data["success"] is True
    assert data["username"] == "alice"
    assert data["backend"] == "oidc"
    assert data["user_id"] > 0


def test_g595_oidc_callback_writes_audit_log(mock_oidc, client):
    """H.G595 — Callback exitoso persiste entry en clinical_audit_log."""
    from prostanet.shared.auth_db import get_audit_log_entries
    code, at = mock_oidc.add_authorized_user("bob_sub", email="bob@x.com")
    client.get("/api/auth/oidc/login", follow_redirects=False)
    with client.session_transaction() as sess:
        valid_state = sess.get("_oidc_state")
    client.get(f"/api/auth/oidc/callback?code={code}&state={valid_state}")
    entries = get_audit_log_entries(endpoint="oidc_callback", status="authorized")
    assert len(entries) >= 1


def test_g596_oidc_callback_session_persists_after_login(mock_oidc, client):
    """H.G596 — Después de OIDC callback, /whoami retorna autenticado."""
    code, at = mock_oidc.add_authorized_user("carol_sub", email="c@x.com")
    client.get("/api/auth/oidc/login", follow_redirects=False)
    with client.session_transaction() as sess:
        valid_state = sess.get("_oidc_state")
    client.get(f"/api/auth/oidc/callback?code={code}&state={valid_state}")
    resp = client.get("/api/auth/whoami")
    data = resp.get_json()
    assert data["authenticated"] is True


# ════════════════════════════════════════════════════════════════════
# §L. Cleanup + integration (H.G597-H.G601)
# ════════════════════════════════════════════════════════════════════


def test_g597_oidc_callback_cleans_session_keys(mock_oidc, client):
    """H.G597 — Tras callback exitoso, OIDC-specific keys removidas."""
    code, at = mock_oidc.add_authorized_user("dave_sub")
    client.get("/api/auth/oidc/login", follow_redirects=False)
    with client.session_transaction() as sess:
        valid_state = sess.get("_oidc_state")
    client.get(f"/api/auth/oidc/callback?code={code}&state={valid_state}")
    with client.session_transaction() as sess:
        # OIDC-specific keys removed (only persistent session keys remain)
        assert "_oidc_state" not in sess
        assert "_oidc_code_verifier" not in sess
        assert "_oidc_nonce" not in sess


def test_g598_audit_log_records_oidc_login_initiation(mock_oidc, client):
    """H.G598 — /oidc/login persiste entry tipo 'redirected' en audit log."""
    from prostanet.shared.auth_db import get_audit_log_entries
    client.get("/api/auth/oidc/login", follow_redirects=False)
    entries = get_audit_log_entries(endpoint="oidc_login_initiated")
    assert len(entries) >= 1
    assert entries[0]["status"] == "redirected"


def test_g599_token_exchange_failure_returns_502(mock_oidc, client):
    """H.G599 — Si token endpoint falla, callback retorna 502."""
    code, at = mock_oidc.add_authorized_user("err_user")
    mock_oidc.failure_mode = "token"
    client.get("/api/auth/oidc/login", follow_redirects=False)
    with client.session_transaction() as sess:
        valid_state = sess.get("_oidc_state")
    resp = client.get(f"/api/auth/oidc/callback?code={code}&state={valid_state}")
    assert resp.status_code == 502


def test_g600_repeated_oidc_login_creates_new_state(mock_oidc, client):
    """H.G600 — Cada /oidc/login regenera state (no reusa entre intentos)."""
    client.get("/api/auth/oidc/login", follow_redirects=False)
    with client.session_transaction() as sess:
        state1 = sess.get("_oidc_state")
    client.get("/api/auth/oidc/login", follow_redirects=False)
    with client.session_transaction() as sess:
        state2 = sess.get("_oidc_state")
    assert state1 != state2


def test_g601_full_oidc_flow_e2e(mock_oidc, client):
    """H.G601 — E2E completo: login → callback → whoami → logout → whoami."""
    code, at = mock_oidc.add_authorized_user(
        "ruth_sub", email="ruth@hospital.org", preferred_username="ruth",
    )
    # Login (302 redirect)
    r = client.get("/api/auth/oidc/login", follow_redirects=False)
    assert r.status_code == 302
    with client.session_transaction() as sess:
        valid_state = sess.get("_oidc_state")
    # Callback (200 + JIT provision)
    r = client.get(f"/api/auth/oidc/callback?code={code}&state={valid_state}")
    assert r.status_code == 200
    user_id = r.get_json()["user_id"]
    # Whoami (authenticated)
    r = client.get("/api/auth/whoami")
    assert r.get_json()["authenticated"] is True
    assert r.get_json()["user_id"] == user_id
    # Logout
    client.post("/api/auth/logout")
    # Whoami (not authenticated)
    r = client.get("/api/auth/whoami")
    assert r.get_json()["authenticated"] is False
