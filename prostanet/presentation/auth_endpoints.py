"""auth_endpoints.py — FAUBOT 2026-04-25 (XXVIII) — Tier 7 G1.5.

Endpoints HTTP de autenticación clínica:
  - POST /api/auth/login         — Username + password → session
  - POST /api/auth/logout        — Invalida sesión
  - GET  /api/auth/whoami        — Retorna user_id + role + backend si autenticado
  - GET  /api/auth/csrf-token    — Devuelve CSRF token para clientes (cuando enabled)

Diseño:
  - Stdlib-only (sin Flask-Login).
  - Endpoints públicos (no requieren sesión) — dummy en `require_clinical_session`
    si CLINICAL_AUTH_ENABLED=true (login es la única forma de entrar).
  - JSON-first (no HTML forms; clientes deben usar JS o curl).

Aporte a auditabilidad:
  - Cada login (success + failure) queda registrado en clinical_audit_log.
  - whoami expone backend usado para trazar versión.

Uso desde app.py:
    from prostanet.presentation.auth_endpoints import auth_bp
    app.register_blueprint(auth_bp)
"""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request, session

from prostanet.shared.auth_backends import (
    get_auth_backend, session_login, session_logout, session_user_id,
    # Faubot 2026-04-25 (XXXVII) — Tier 7 G4: refresh token helpers
    session_store_oidc_tokens, session_get_refresh_token,
    session_get_access_token, session_token_seconds_until_expiry,
    session_increment_refresh_count,
    SESSION_REFRESH_COUNT_KEY, SESSION_LAST_REFRESH_AT_KEY,
    # Faubot 2026-04-25 (XXXIX) — Tier 7 G7: idle vs absolute timeout
    session_touch_activity, session_idle_seconds_remaining,
    session_absolute_seconds_remaining, session_expiry_reason,
    SESSION_ABSOLUTE_TIMEOUT_SECONDS, SESSION_IDLE_TIMEOUT_SECONDS,
    SESSION_TOUCH_COUNT_KEY, SESSION_LAST_ACTIVITY_KEY,
    SESSION_REASON_VALID,
)
from prostanet.shared.auth_db import (
    write_audit_log_entry, update_last_login,
    # Faubot 2026-04-25 (XLV) — Tier 7 G9: dashboard endpoint helpers
    query_audit_log_entries, count_audit_log_entries_filtered,
)
from prostanet.shared.security_helpers import (
    error_response_with_trace_id, is_clinical_auth_enabled,
    require_clinical_session,
)
from prostanet.shared.security_middleware import (
    generate_csrf_token, is_csrf_enabled,
)

logger = logging.getLogger(__name__)


auth_bp = Blueprint("clinical_auth", __name__, url_prefix="/api/auth")


# ════════════════════════════════════════════════════════════════════
# /api/auth/login — POST {username, password}
# ════════════════════════════════════════════════════════════════════


@auth_bp.route("/login", methods=["POST"])
def login():
    """Autentica usuario clínico.

    Body (acepta JSON o form-encoded):
        {"username": "...", "password": "..."}    # JSON
        username=...&password=...                   # form

    Returns:
        - JSON request: 200 + {success: true, user_id, role, backend} si valid;
          401 + {success: false, error: "..."} si invalid
        - Form request: 302 redirect a / (success) o /login?error=... (failure)

    Faubot 2026-04-25 (XXXI) — Tier 7 G2: form-encoded POST support
    para login.html HTML form submission.
    """
    from flask import redirect, url_for

    request_path = request.path
    request_method = request.method
    request_ip = request.remote_addr or ""
    request_ua = request.headers.get("User-Agent", "")[:200]

    # Detect if this is a form submission vs JSON API call
    is_form_request = bool(request.form) or (
        request.content_type and "application/x-www-form-urlencoded" in request.content_type
    )

    if is_form_request:
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        # CSRF token from form (if CSRF enabled)
        from prostanet.shared.security_middleware import is_csrf_enabled, validate_csrf_token
        if is_csrf_enabled():
            csrf_supplied = request.form.get("csrf_token", "")
            if not validate_csrf_token(session, csrf_supplied):
                return redirect(url_for("login_page", error="csrf_failed"))
    else:
        try:
            body = request.get_json(silent=True) or {}
        except Exception:
            body = {}
        username = (body.get("username") or "").strip()
        password = body.get("password") or ""

    if not username or not password:
        write_audit_log_entry(
            endpoint="login",
            status="denied_missing_credentials",
            path=request_path,
            method=request_method,
            ip_address=request_ip,
            user_agent=request_ua,
            reason="username or password missing",
        )
        if is_form_request:
            return redirect(url_for("login_page", error="missing_credentials"))
        return jsonify({
            "success": False,
            "error": "Username and password required.",
        }), 400

    try:
        backend = get_auth_backend()
        user_id = backend.verify(username, password)
    except NotImplementedError as exc:
        # Federated backend placeholder
        logger.warning(f"login: backend not implemented | {exc}")
        return jsonify({
            "success": False,
            "error": "Authentication backend not yet configured.",
        }), 503
    except Exception as exc:
        return error_response_with_trace_id(
            exc,
            user_message="Authentication error.",
            log_extra={"username": username[:50]},
        )

    if user_id is None:
        write_audit_log_entry(
            endpoint="login",
            status="denied_invalid_credentials",
            username=username,
            path=request_path,
            method=request_method,
            ip_address=request_ip,
            user_agent=request_ua,
            backend=backend.backend_name,
            reason="Invalid username or password",
        )
        if is_form_request:
            return redirect(url_for("login_page", error="invalid_credentials"))
        # Constant-time response (don't reveal which was wrong)
        return jsonify({
            "success": False,
            "error": "Invalid credentials.",
        }), 401

    # Success — establish session
    session_login(session, user_id=user_id, backend_name=backend.backend_name)
    update_last_login(user_id)

    user = backend.get_user(user_id) or {}
    write_audit_log_entry(
        endpoint="login",
        status="authorized",
        user_id=user_id,
        username=username,
        path=request_path,
        method=request_method,
        ip_address=request_ip,
        user_agent=request_ua,
        backend=backend.backend_name,
    )

    if is_form_request:
        # Form login → redirect a home (clinical hub)
        return redirect("/")
    return jsonify({
        "success": True,
        "user_id": user_id,
        "username": username,
        "role": user.get("role"),
        "backend": backend.backend_name,
    }), 200


# ════════════════════════════════════════════════════════════════════
# /api/auth/logout — POST + GET (G2 supports HTML link logout)
# ════════════════════════════════════════════════════════════════════


@auth_bp.route("/logout", methods=["POST", "GET"])
def logout():
    """Invalida la sesión del usuario actual.

    Faubot G2: GET method allows logout via HTML link click.
    POST method preserved for API/programmatic use.
    """
    from flask import redirect, url_for
    user_id = session_user_id(session)
    if user_id is not None:
        write_audit_log_entry(
            endpoint="logout",
            status="authorized",
            user_id=user_id,
            path=request.path,
            method=request.method,
            ip_address=request.remote_addr or "",
            user_agent=request.headers.get("User-Agent", "")[:200],
        )
    session_logout(session)

    # GET request → redirect to login (HTML flow); POST → JSON (API flow)
    if request.method == "GET":
        return redirect(url_for("login_page", logged_out="1"))
    return jsonify({"success": True, "message": "Session ended."}), 200


# ════════════════════════════════════════════════════════════════════
# /api/auth/whoami — GET
# ════════════════════════════════════════════════════════════════════


@auth_bp.route("/whoami", methods=["GET"])
def whoami():
    """Retorna user_id + role del usuario actual (si autenticado)."""
    user_id = session_user_id(session)
    if user_id is None:
        return jsonify({
            "success": True,
            "authenticated": False,
            "auth_enabled": is_clinical_auth_enabled(),
        }), 200
    try:
        backend = get_auth_backend()
        user = backend.get_user(user_id)
    except Exception:
        user = None
    if user is None:
        return jsonify({
            "success": True,
            "authenticated": False,
            "auth_enabled": is_clinical_auth_enabled(),
        }), 200
    return jsonify({
        "success": True,
        "authenticated": True,
        "auth_enabled": is_clinical_auth_enabled(),
        "user_id": user_id,
        "username": user.get("username"),
        "role": user.get("role"),
        "backend": user.get("backend"),
        "last_login_at": user.get("last_login_at"),
    }), 200


# ════════════════════════════════════════════════════════════════════
# /api/auth/csrf-token — GET (when CSRF enabled)
# ════════════════════════════════════════════════════════════════════


@auth_bp.route("/csrf-token", methods=["GET"])
def csrf_token():
    """Genera/devuelve CSRF token de la sesión actual.

    Solo útil cuando PROSTANET_CSRF_ENABLED=true.
    """
    if not is_csrf_enabled():
        return jsonify({
            "success": True,
            "csrf_enabled": False,
            "message": "CSRF protection is disabled.",
        }), 200
    token = generate_csrf_token(session)
    return jsonify({
        "success": True,
        "csrf_enabled": True,
        "csrf_token": token,
    }), 200


# ════════════════════════════════════════════════════════════════════
# OIDC endpoints (Tier 7 G1.6) — /oidc/login + /oidc/callback
# ════════════════════════════════════════════════════════════════════


_OIDC_STATE_SESSION_KEY = "_oidc_state"
_OIDC_VERIFIER_SESSION_KEY = "_oidc_code_verifier"
_OIDC_NONCE_SESSION_KEY = "_oidc_nonce"


@auth_bp.route("/oidc/login", methods=["GET"])
def oidc_login():
    """Inicia OIDC Authorization Code Flow + PKCE.

    Construye URL de autorización del IDP (vía discovery doc), almacena
    state + code_verifier + nonce en session, y redirige al IDP.

    Requiere PROSTANET_AUTH_BACKEND=oidc (o auth0/keycloak/oauth_google)
    + PROSTANET_OIDC_ISSUER + PROSTANET_OIDC_CLIENT_ID env vars.

    Returns:
        302 redirect al IDP authorization endpoint, o
        503 si OIDC no configurado / unreachable.
    """
    try:
        from flask import redirect
        from prostanet.shared.oidc_client import (
            OidcConfig, build_authorization_url, generate_pkce_pair,
            generate_state_token, generate_nonce, fetch_discovery_doc,
        )
    except Exception as exc:
        return error_response_with_trace_id(
            exc,
            user_message="OIDC subsystem unavailable.",
            status_code=503,
        )

    try:
        config = OidcConfig.from_env()
    except ValueError as exc:
        return error_response_with_trace_id(
            exc,
            user_message="OIDC not configured. Set PROSTANET_OIDC_ISSUER + PROSTANET_OIDC_CLIENT_ID.",
            status_code=503,
        )

    try:
        discovery = fetch_discovery_doc(config)
    except ValueError as exc:
        return error_response_with_trace_id(
            exc,
            user_message="OIDC IDP discovery failed.",
            status_code=503,
        )

    # PKCE + state + nonce generation
    code_verifier, code_challenge = generate_pkce_pair()
    state = generate_state_token()
    nonce = generate_nonce()

    # Store in session (Flask signed cookie) for callback validation
    session[_OIDC_STATE_SESSION_KEY] = state
    session[_OIDC_VERIFIER_SESSION_KEY] = code_verifier
    session[_OIDC_NONCE_SESSION_KEY] = nonce

    auth_url = build_authorization_url(
        config,
        state=state,
        code_challenge=code_challenge,
        nonce=nonce,
        discovery=discovery,
    )

    write_audit_log_entry(
        endpoint="oidc_login_initiated",
        status="redirected",
        path=request.path,
        method=request.method,
        ip_address=request.remote_addr or "",
        user_agent=request.headers.get("User-Agent", "")[:200],
        backend=os.environ.get("PROSTANET_AUTH_BACKEND", "oidc"),
        reason=f"Redirected to OIDC IDP {config.issuer}",
    )

    return redirect(auth_url, code=302)


@auth_bp.route("/oidc/callback", methods=["GET"])
def oidc_callback():
    """Handler del OIDC callback tras user authentication en IDP.

    Recibe `?code=...&state=...` del IDP, valida state contra session,
    intercambia code por tokens (con PKCE verifier), llama userinfo,
    y JIT-provisiona el clinical_user (si no existe).

    Returns:
        200 + {success, user_id, role, backend} si exitoso, o
        400 si state inválido / code missing, o
        503 si IDP error.
    """
    # Validate state (CSRF protection for OAuth)
    received_state = request.args.get("state", "")
    expected_state = session.get(_OIDC_STATE_SESSION_KEY, "")
    if not received_state or not expected_state:
        write_audit_log_entry(
            endpoint="oidc_callback",
            status="denied_state_missing",
            path=request.path,
            method=request.method,
            ip_address=request.remote_addr or "",
            user_agent=request.headers.get("User-Agent", "")[:200],
            reason="State token missing in callback or session",
        )
        return jsonify({
            "success": False,
            "error": "Invalid OIDC callback (missing state).",
        }), 400

    if not _constant_time_eq(received_state, expected_state):
        write_audit_log_entry(
            endpoint="oidc_callback",
            status="denied_state_mismatch",
            path=request.path,
            method=request.method,
            ip_address=request.remote_addr or "",
            user_agent=request.headers.get("User-Agent", "")[:200],
            reason="State token mismatch (possible CSRF attempt)",
        )
        return jsonify({
            "success": False,
            "error": "Invalid OIDC callback (state mismatch).",
        }), 400

    # Check for IDP error
    idp_error = request.args.get("error")
    if idp_error:
        write_audit_log_entry(
            endpoint="oidc_callback",
            status="denied_idp_error",
            path=request.path,
            method=request.method,
            ip_address=request.remote_addr or "",
            user_agent=request.headers.get("User-Agent", "")[:200],
            reason=f"IDP returned error: {idp_error}",
        )
        return jsonify({
            "success": False,
            "error": "OIDC authentication failed at IDP.",
        }), 401

    code = request.args.get("code", "")
    if not code:
        return jsonify({
            "success": False,
            "error": "Invalid OIDC callback (missing code).",
        }), 400

    code_verifier = session.get(_OIDC_VERIFIER_SESSION_KEY, "")
    if not code_verifier:
        return jsonify({
            "success": False,
            "error": "Invalid OIDC session (missing verifier).",
        }), 400

    try:
        from prostanet.shared.oidc_client import (
            OidcConfig, exchange_code_for_tokens,
            resolve_claims_with_jwt_or_userinfo,
        )
    except Exception as exc:
        return error_response_with_trace_id(
            exc,
            user_message="OIDC subsystem unavailable.",
            status_code=503,
        )

    nonce_in_session = session.get(_OIDC_NONCE_SESSION_KEY, "")
    try:
        config = OidcConfig.from_env()
        token_resp = exchange_code_for_tokens(
            config, code=code, code_verifier=code_verifier,
        )
        # G1.7 hybrid: try JWT verify first, fall back to userinfo
        claims_result = resolve_claims_with_jwt_or_userinfo(
            config,
            id_token=token_resp.id_token,
            access_token=token_resp.access_token,
            expected_nonce=nonce_in_session,
        )
        userinfo = claims_result.claims
    except (ValueError, RuntimeError) as exc:
        write_audit_log_entry(
            endpoint="oidc_callback",
            status="denied_token_exchange_failed",
            path=request.path,
            method=request.method,
            ip_address=request.remote_addr or "",
            user_agent=request.headers.get("User-Agent", "")[:200],
            reason=f"Token exchange or userinfo failed: {type(exc).__name__}",
        )
        return error_response_with_trace_id(
            exc,
            user_message="OIDC token exchange failed.",
            status_code=502,
        )

    # JIT provision via OidcBackend
    backend = get_auth_backend()
    if not isinstance(backend, _OidcBackendCheck()):
        # Backend mismatch — shouldn't happen if OIDC enabled correctly
        return jsonify({
            "success": False,
            "error": "OIDC backend not active. Set PROSTANET_AUTH_BACKEND=oidc.",
        }), 503

    try:
        user_id = backend.verify_userinfo_and_provision(
            userinfo,
            issuer=config.issuer,
            default_role=config.default_role,
        )
    except (ValueError, RuntimeError) as exc:
        return error_response_with_trace_id(
            exc,
            user_message="OIDC user provisioning failed.",
            status_code=500,
        )

    # Establish session
    session_login(session, user_id=user_id, backend_name=backend.backend_name)
    update_last_login(user_id)

    # Faubot 2026-04-25 (XXXVII) — Tier 7 G4: persist OIDC tokens for
    # auto-renewal (refresh_token + access_token + expires_at).
    session_store_oidc_tokens(
        session,
        access_token=token_resp.access_token,
        refresh_token=token_resp.refresh_token,
        expires_in=token_resp.expires_in,
    )

    # Clean up OIDC-specific session keys
    for k in (_OIDC_STATE_SESSION_KEY, _OIDC_VERIFIER_SESSION_KEY,
              _OIDC_NONCE_SESSION_KEY):
        session.pop(k, None)

    user = backend.get_user(user_id) or {}
    # Faubot G1.7: include claims resolution method in audit log
    auth_reason = (
        f"claims_via={claims_result.method}"
        + (f"; alg={claims_result.algorithm}" if claims_result.algorithm else "")
        + (f"; jwt_fail={claims_result.jwt_verify_reason[:120]}"
           if claims_result.jwt_verify_reason else "")
    )
    write_audit_log_entry(
        endpoint="oidc_callback",
        status="authorized",
        user_id=user_id,
        username=str(user.get("username", "")),
        path=request.path,
        method=request.method,
        ip_address=request.remote_addr or "",
        user_agent=request.headers.get("User-Agent", "")[:200],
        backend=backend.backend_name,
        reason=auth_reason,
    )

    return jsonify({
        "success": True,
        "user_id": user_id,
        "username": user.get("username"),
        "role": user.get("role"),
        "backend": backend.backend_name,
        "external_id_prefix": str(user.get("external_id", ""))[:60],
        "claims_method": claims_result.method,
    }), 200


def _constant_time_eq(a: str, b: str) -> bool:
    """Constant-time string comparison via hmac.compare_digest."""
    import hmac as _hmac
    return _hmac.compare_digest(str(a).encode("utf-8"), str(b).encode("utf-8"))


def _OidcBackendCheck():
    """Lazy import for isinstance check (avoids circular import)."""
    from prostanet.shared.auth_backends import OidcBackend
    return OidcBackend


# Import os at module level for env var lookup in oidc_login audit log
import os


# ════════════════════════════════════════════════════════════════════
# Faubot 2026-04-25 (XXXVII) — Tier 7 G4: Refresh token + session-status
# ════════════════════════════════════════════════════════════════════


@auth_bp.route("/refresh", methods=["POST"])
def refresh():
    """Renueva la sesión OIDC usando refresh_token almacenado.

    Faubot 2026-04-25 (XXXVII) — Tier 7 G4: implementa OAuth refresh
    token flow estándar (RFC 6749 §6). Permite que clínicos en sesión
    long-running renueven su access_token sin re-login.

    Flujo:
      1. Verifica que hay sesión activa con refresh_token almacenado
      2. Llama a IDP `/token` con grant_type=refresh_token
      3. Almacena nuevos tokens (access_token + posible nuevo refresh_token)
      4. Incrementa refresh_count + actualiza last_refresh_at
      5. Persiste audit log entry tipo `refresh, status=authorized`

    Returns:
        200 + {success: true, expires_in, refresh_count, expires_at} si OK
        401 si no hay sesión o refresh_token
        502 si IDP rechaza el refresh
        503 si OIDC no configurado
    """
    user_id = session_user_id(session)
    if user_id is None:
        return jsonify({
            "success": False,
            "error": "No active session.",
        }), 401

    refresh_token = session_get_refresh_token(session)
    if not refresh_token:
        write_audit_log_entry(
            endpoint="refresh",
            status="denied_no_refresh_token",
            user_id=user_id,
            path=request.path,
            method=request.method,
            ip_address=request.remote_addr or "",
            user_agent=request.headers.get("User-Agent", "")[:200],
            reason="No refresh_token stored in session (LocalPbkdf2 backend or OIDC didn't issue one)",
        )
        return jsonify({
            "success": False,
            "error": "No refresh token available. Please re-login.",
        }), 401

    try:
        from prostanet.shared.oidc_client import (
            OidcConfig, exchange_refresh_token_for_tokens,
        )
    except Exception as exc:
        return error_response_with_trace_id(
            exc,
            user_message="OIDC subsystem unavailable.",
            status_code=503,
        )

    try:
        config = OidcConfig.from_env()
        token_resp = exchange_refresh_token_for_tokens(
            config, refresh_token=refresh_token,
        )
    except ValueError as exc:
        # Refresh failed (token expired/revoked, IDP error)
        write_audit_log_entry(
            endpoint="refresh",
            status="denied_refresh_failed",
            user_id=user_id,
            path=request.path,
            method=request.method,
            ip_address=request.remote_addr or "",
            user_agent=request.headers.get("User-Agent", "")[:200],
            reason=f"Refresh token exchange failed: {type(exc).__name__}",
        )
        # Per security best practice: invalidate session if refresh fails
        # (refresh_token may be revoked/expired)
        session_logout(session)
        return jsonify({
            "success": False,
            "error": "Session refresh failed. Please re-login.",
        }), 502

    # Update tokens (refresh_token may rotate per RFC 6749 §6 — use new one
    # if provided, else keep existing)
    new_refresh_token = token_resp.refresh_token or refresh_token
    session_store_oidc_tokens(
        session,
        access_token=token_resp.access_token,
        refresh_token=new_refresh_token,
        expires_in=token_resp.expires_in,
    )
    refresh_count = session_increment_refresh_count(session)

    # Audit log: successful refresh
    backend = get_auth_backend()
    user = backend.get_user(user_id) or {}
    write_audit_log_entry(
        endpoint="refresh",
        status="authorized",
        user_id=user_id,
        username=str(user.get("username", "")),
        path=request.path,
        method=request.method,
        ip_address=request.remote_addr or "",
        user_agent=request.headers.get("User-Agent", "")[:200],
        backend=backend.backend_name,
        reason=(
            f"refresh_count={refresh_count}; "
            f"new_expires_in={token_resp.expires_in}; "
            f"refresh_token_rotated={'yes' if token_resp.refresh_token else 'no'}"
        ),
    )

    return jsonify({
        "success": True,
        "user_id": user_id,
        "expires_in": token_resp.expires_in,
        "refresh_count": refresh_count,
        "refresh_token_rotated": bool(token_resp.refresh_token),
    }), 200


@auth_bp.route("/session-status", methods=["GET"])
def session_status():
    """Faubot 2026-04-25 (XXXVII→XXXIX) — Tier 7 G4 + G7: estado de sesión.

    Endpoint **pasivo** (NO resetea idle window): clientes (browser JS,
    mobile apps) consultan cuándo expira el access_token y la sesión
    para decidir si llamar `/refresh`, `/touch` o re-login. Permite
    implementar auto-renewal en background sin extender artificialmente
    la sesión por el simple hecho de hacer polling.

    Faubot G7 (XXXIX): expone DOS dimensiones de timeout:
      - IDLE (sliding, reseteable via /api/auth/touch o user-driven endpoint)
      - ABSOLUTE (hard cap desde login_time, NO reseteable; force re-login)

    Returns:
        200 + dict con:
          - authenticated: bool
          - user_id, username, role (si auth)
          - has_refresh_token: bool
          - access_token_seconds_until_expiry: int
          - session_seconds_until_timeout: int — min(idle, absolute) (back-compat)
          - session_seconds_until_idle_timeout: int  ★ G7
          - session_seconds_until_absolute_timeout: int  ★ G7
          - idle_timeout_sec: int (configured threshold)  ★ G7
          - absolute_timeout_sec: int (configured threshold)  ★ G7
          - touch_count: int (cuántas veces se renovó actividad)  ★ G7
          - expiry_reason: str — "valid" / "expired_idle" / "expired_absolute"  ★ G7
          - refresh_count, last_refresh_at (Tier 7 G4)
    """
    uid = session_user_id(session)
    if uid is None:
        # G7: still surface expiry_reason for unauthenticated path so
        # client UI can distinguish "never logged in" from "session expired".
        return jsonify({
            "success": True,
            "authenticated": False,
            "expiry_reason": session_expiry_reason(session),
            "idle_timeout_sec": SESSION_IDLE_TIMEOUT_SECONDS,
            "absolute_timeout_sec": SESSION_ABSOLUTE_TIMEOUT_SECONDS,
        }), 200

    try:
        backend = get_auth_backend()
        user = backend.get_user(uid)
    except Exception:
        user = None

    refresh_token = session_get_refresh_token(session)
    access_token_remaining = session_token_seconds_until_expiry(session)

    # G7: granular per-dimension remaining + back-compat min
    idle_remaining = session_idle_seconds_remaining(session)
    absolute_remaining = session_absolute_seconds_remaining(session)
    session_remaining = min(idle_remaining, absolute_remaining)

    return jsonify({
        "success": True,
        "authenticated": True,
        "user_id": uid,
        "username": (user or {}).get("username", ""),
        "role": (user or {}).get("role", ""),
        "has_refresh_token": bool(refresh_token),
        "access_token_seconds_until_expiry": access_token_remaining,
        # Backward-compat: pre-G7 clients only know about this one field.
        "session_seconds_until_timeout": session_remaining,
        # G7 granular fields
        "session_seconds_until_idle_timeout": idle_remaining,
        "session_seconds_until_absolute_timeout": absolute_remaining,
        "idle_timeout_sec": SESSION_IDLE_TIMEOUT_SECONDS,
        "absolute_timeout_sec": SESSION_ABSOLUTE_TIMEOUT_SECONDS,
        "touch_count": int(session.get(SESSION_TOUCH_COUNT_KEY, 0)),
        "last_activity_at": session.get(SESSION_LAST_ACTIVITY_KEY, ""),
        "expiry_reason": session_expiry_reason(session),
        # Tier 7 G4 fields
        "refresh_count": int(session.get(SESSION_REFRESH_COUNT_KEY, 0)),
        "last_refresh_at": session.get(SESSION_LAST_REFRESH_AT_KEY, ""),
    }), 200


# ════════════════════════════════════════════════════════════════════
# Faubot 2026-04-25 (XXXIX) — Tier 7 G7: /api/auth/touch
# ════════════════════════════════════════════════════════════════════


@auth_bp.route("/touch", methods=["POST"])
def touch():
    """Renueva el sliding window IDLE marcando last_activity = now().

    Faubot 2026-04-25 (XXXIX) — Tier 7 G7. Endpoint llamado por el badge
    de sesión del frontend en respuesta a interacción real del usuario
    (click/keydown/scroll, debounced en JS para no saturar el backend).

    NO renueva el access_token OIDC ni extiende el ABSOLUTE timeout — esos
    requieren `/api/auth/refresh` (rotación de refresh_token via IDP) o
    re-login completo. `/touch` solo valida que el usuario está presente
    y reinicia el contador de inactividad.

    Body: vacío (no se requieren campos).

    Returns:
        200 + {success: true, touch_count, idle_remaining, absolute_remaining,
               expiry_reason} si la sesión sigue válida tras el touch.
        401 + {success: false, error, reason: <expiry_reason>} si la sesión
              ya expiró (idle o absolute) — el touch llega tarde.
    """
    uid = session_user_id(session)
    if uid is None:
        # Sesión expirada o inexistente: no tocamos.
        reason_code = session_expiry_reason(session)
        return jsonify({
            "success": False,
            "error": "Cannot touch expired session.",
            "reason": reason_code,
        }), 401

    new_count = session_touch_activity(session)

    # Audit log: solo cada N touches para no saturar (clínico activo
    # podría disparar 100+ touches/h). Conservamos el primero y luego
    # 1 cada 25 para auditoría sampling.
    if new_count == 1 or (new_count % 25) == 0:
        try:
            backend = get_auth_backend()
            user = backend.get_user(uid) or {}
            write_audit_log_entry(
                endpoint="touch",
                status="authorized",
                user_id=uid,
                username=str(user.get("username", "")),
                path=request.path,
                method=request.method,
                ip_address=request.remote_addr or "",
                user_agent=request.headers.get("User-Agent", "")[:200],
                backend=backend.backend_name,
                reason=f"touch_count={new_count}; sampled audit entry",
            )
        except Exception:  # pragma: no cover — defensive
            pass

    return jsonify({
        "success": True,
        "touch_count": new_count,
        "session_seconds_until_idle_timeout": session_idle_seconds_remaining(session),
        "session_seconds_until_absolute_timeout": session_absolute_seconds_remaining(session),
        "expiry_reason": session_expiry_reason(session),
    }), 200


# ════════════════════════════════════════════════════════════════════
# Faubot 2026-04-25 (XLV) — Tier 7 G9: /api/auth/audit-log dashboard
# ════════════════════════════════════════════════════════════════════


# Defensive caps locales al endpoint (replican `auth_db.query_audit_log_entries`
# para que el cliente nunca envíe valores fuera de rango sin feedback claro).
_AUDIT_LOG_DEFAULT_LIMIT = 50
_AUDIT_LOG_MAX_LIMIT = 500
_AUDIT_LOG_MAX_OFFSET = 100_000  # protección anti-OOM en queries con miles de pages


def _parse_int_qparam(name: str, default: int, *, lo: int, hi: int) -> int:
    """Parse an int query param with clamping; returns default on missing/invalid."""
    raw = (request.args.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except (ValueError, TypeError):
        return default
    return max(lo, min(hi, value))


@auth_bp.route("/audit-log", methods=["GET"])
@require_clinical_session(scope="audit:read", passive=True)
def audit_log_dashboard():
    """Faubot 2026-04-25 (XLV) — Tier 7 G9: dashboard endpoint para audit log.

    Cierra brecha compliance HIPAA §164.312(b) (audit trail consultable):
    convierte el `clinical_audit_log` table de "evento aislado escrito por
    middleware" a "trail agregado consultable por auditores y compliance
    officers".

    Requiere ABAC scope `audit:read` (auditor + admin roles per
    LocalPbkdf2Backend defaults). `passive=True` previene que el polling
    del dashboard extienda el sliding window IDLE artificialmente
    (Tier 7 G7 semantics).

    Query params (todos opcionales):
        ?user_id=42           — filter exact match (int)
        ?endpoint=login       — filter exact match (e.g., "login", "refresh", "touch")
        ?status=authorized    — filter exact match (e.g., "authorized", "denied_no_session")
        ?from=2026-04-25T00:00:00Z   — ISO8601 lower bound on timestamp (>=)
        ?to=2026-04-26T00:00:00Z     — ISO8601 upper bound on timestamp (<=)
        ?limit=50             — rows per page (default 50, max 500)
        ?offset=0             — pagination offset (default 0, max 100000)

    Returns:
        200 + {
          "success": true,
          "total": 1234,                    # count con filtros aplicados (pre-pagination)
          "limit": 50,
          "offset": 0,
          "has_more": true,                 # offset + limit < total
          "filters_applied": {              # snapshot de filtros recibidos (post-clamp)
            "user_id": 42, "endpoint": "login", "status": "authorized",
            "from": "...", "to": "..."
          },
          "entries": [{...}, ...]           # filas ordenadas DESC por id
        }

    Cada entry incluye TODAS las columnas de clinical_audit_log:
      id, user_id, username, endpoint, path, method, scope, status,
      reason, trace_id, ip_address, user_agent, backend, timestamp.

    NOTAS de seguridad:
      - El endpoint NO permite WRITE — solo SELECT — el audit log es
        immutable por diseño.
      - User_agent + ip_address ya vienen truncados (200/genérico) en
        write_audit_log_entry, no se hace re-sanitization aquí.
      - reason field puede contener detalles de denial; depende del
        scope ABAC del usuario consultante (roles auditor/admin).
    """
    # Parse + clamp query params
    user_id_raw = (request.args.get("user_id") or "").strip()
    user_id = None
    if user_id_raw:
        try:
            user_id = int(user_id_raw)
        except (ValueError, TypeError):
            user_id = None

    endpoint_filter = (request.args.get("endpoint") or "").strip()[:100] or None
    status_filter = (request.args.get("status") or "").strip()[:50] or None
    timestamp_from = (request.args.get("from") or "").strip()[:64] or None
    timestamp_to = (request.args.get("to") or "").strip()[:64] or None

    limit = _parse_int_qparam(
        "limit", _AUDIT_LOG_DEFAULT_LIMIT,
        lo=1, hi=_AUDIT_LOG_MAX_LIMIT,
    )
    offset = _parse_int_qparam(
        "offset", 0,
        lo=0, hi=_AUDIT_LOG_MAX_OFFSET,
    )

    # Common kwargs reused for both query + count (DRY)
    filter_kwargs = dict(
        user_id=user_id,
        endpoint=endpoint_filter,
        status=status_filter,
        timestamp_from=timestamp_from,
        timestamp_to=timestamp_to,
    )

    try:
        total = count_audit_log_entries_filtered(**filter_kwargs)
        entries = query_audit_log_entries(
            limit=limit, offset=offset, **filter_kwargs,
        )
    except Exception as exc:  # pragma: no cover — defensive
        return error_response_with_trace_id(
            exc,
            user_message="Audit log query failed.",
            status_code=500,
        )

    return jsonify({
        "success": True,
        "total": int(total),
        "limit": int(limit),
        "offset": int(offset),
        "has_more": (offset + limit) < int(total),
        "filters_applied": {
            "user_id": user_id,
            "endpoint": endpoint_filter,
            "status": status_filter,
            "from": timestamp_from,
            "to": timestamp_to,
        },
        "entries": entries,
    }), 200


# ════════════════════════════════════════════════════════════════════
# Sprint 7.B — GET /api/auth/oidc/status (diagnostic + observability)
# ════════════════════════════════════════════════════════════════════


@auth_bp.route("/oidc/status", methods=["GET"])
def oidc_status():
    """Sprint 7.B — Diagnóstico del backend OIDC.

    Útil para:
      - Health check post-deploy ("¿está OIDC configurado correctamente?")
      - Smoke pre-piloto ("¿el discovery endpoint del IDP responde?")
      - Debug de roles ("¿qué claims devuelve mi IDP?")

    NO requiere auth — es observabilidad operativa. NO expone secrets
    (client_secret, tokens) — solo configuración pública + estado.

    Returns:
        200 + {success, backend_active, configured, issuer, discovery_reachable,
               oidc_users_count, recent_provisions[]}
    """
    import os
    from datetime import datetime, timezone

    backend_env = os.environ.get("PROSTANET_AUTH_BACKEND", "local").lower()
    is_oidc = backend_env in ("oidc", "auth0", "keycloak", "oauth_google")

    response: dict = {
        "success": True,
        "backend_active": backend_env,
        "is_oidc_backend": is_oidc,
        "configured": False,
        "issuer": None,
        "client_id_set": False,
        "redirect_uri": None,
        "discovery_reachable": None,
        "discovery_error": None,
        "scope": None,
        "default_role": None,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }

    if not is_oidc:
        response["note"] = (
            f"Active backend is '{backend_env}' (local PBKDF2). "
            f"To enable OIDC: PROSTANET_AUTH_BACKEND=oidc + PROSTANET_OIDC_ISSUER + "
            f"PROSTANET_OIDC_CLIENT_ID."
        )
        return jsonify(response), 200

    # Try to load OIDC config (env vars)
    try:
        from prostanet.shared.oidc_client import OidcConfig, fetch_discovery_doc
        config = OidcConfig.from_env()
        response["configured"] = True
        response["issuer"] = getattr(config, "issuer", None) or getattr(config, "discovery_url", None)
        response["client_id_set"] = bool(os.environ.get("PROSTANET_OIDC_CLIENT_ID"))
        response["redirect_uri"] = config.redirect_uri
        response["scope"] = config.scope
        response["default_role"] = config.default_role
    except ValueError as exc:
        response["configured"] = False
        response["note"] = f"OIDC env vars missing: {exc}"
        return jsonify(response), 200
    except Exception as exc:
        logger.warning("OIDC status config load failed: %s", exc)
        response["configured"] = False
        response["discovery_error"] = "config_load_failed"
        return jsonify(response), 200

    # Try to reach discovery doc
    try:
        discovery = fetch_discovery_doc(config)
        response["discovery_reachable"] = True
        response["discovery_endpoints"] = {
            "authorization": discovery.get("authorization_endpoint"),
            "token": discovery.get("token_endpoint"),
            "userinfo": discovery.get("userinfo_endpoint"),
            "jwks": discovery.get("jwks_uri"),
        }
    except Exception as exc:
        response["discovery_reachable"] = False
        response["discovery_error"] = f"{type(exc).__name__}: {str(exc)[:160]}"

    # Stats: cuántos OIDC users hay en clinical_users + recientes
    try:
        import sqlite3
        from tracking_db import DB_PATH
        conn = sqlite3.connect(DB_PATH, timeout=5.0)
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM clinical_users WHERE backend = 'oidc'"
        )
        response["oidc_users_count"] = cur.fetchone()[0]
        cur.execute(
            """
            SELECT username, role, created_at
              FROM clinical_users
             WHERE backend = 'oidc' AND is_active = 1
             ORDER BY id DESC LIMIT 5
            """
        )
        response["recent_oidc_provisions"] = [
            {"username": r[0], "role": r[1], "created_at": r[2]}
            for r in cur.fetchall()
        ]
        conn.close()
    except Exception as exc:
        logger.warning("OIDC status DB query failed: %s", exc)
        response["oidc_users_count"] = None
        response["recent_oidc_provisions"] = []

    return jsonify(response), 200
