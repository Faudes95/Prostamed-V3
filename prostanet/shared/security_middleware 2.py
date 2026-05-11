"""security_middleware.py — FAUBOT 2026-04-25 (XXVIII) — Tier 7 G1.5.

Middleware Flask para hardening de seguridad pre-beta clínica:
  - Security headers (CSP, X-Frame-Options, X-Content-Type-Options, HSTS)
  - CSRF token generation + validation
  - HTTPS enforcement (opt-in via PROSTANET_FORCE_HTTPS=true)

Stdlib-only implementation — sin dependencia de Flask-Talisman/Flask-WTF
para minimizar supply-chain risk. Si en el futuro se quiere swap a
Talisman/WTF, basta reemplazar este módulo.

Aporte a auditabilidad:
  - **POR QUÉ:** rechazos de CSRF retornan trace_id correlacionable
  - **VERSIÓN:** security headers configurables via env vars

Activación:
  - Default OFF (no rompe deployment local). Set PROSTANET_SECURITY_HEADERS=true
  - HTTPS enforcement: PROSTANET_FORCE_HTTPS=true (default false)
  - CSRF: PROSTANET_CSRF_ENABLED=true (default false; activar con auth)
"""
from __future__ import annotations

import logging
import os
import secrets
from functools import wraps
from typing import Callable

logger = logging.getLogger(__name__)


CSRF_TOKEN_SESSION_KEY = "_csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_FORM_FIELD_NAME = "csrf_token"


# ════════════════════════════════════════════════════════════════════
# Env helpers
# ════════════════════════════════════════════════════════════════════


def is_security_headers_enabled() -> bool:
    return os.environ.get("PROSTANET_SECURITY_HEADERS", "false").lower() in {
        "true", "yes", "1",
    }


def is_force_https_enabled() -> bool:
    return os.environ.get("PROSTANET_FORCE_HTTPS", "false").lower() in {
        "true", "yes", "1",
    }


def is_csrf_enabled() -> bool:
    return os.environ.get("PROSTANET_CSRF_ENABLED", "false").lower() in {
        "true", "yes", "1",
    }


# ════════════════════════════════════════════════════════════════════
# Security headers
# ════════════════════════════════════════════════════════════════════


# Default CSP whitelist (permite inline scripts mínimos en gates_coverage_dashboard.html)
# Para producción endurecer aún más con nonces per-request.
DEFAULT_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


def is_csp_nonces_enabled() -> bool:
    """Faubot 2026-04-25 (XXXI) — Tier 7 G2: per-page CSP nonces.

    Default ON cuando security headers activos (más estricto que
    `'unsafe-inline'`). Set PROSTANET_CSP_NONCES=false para legacy.
    """
    return os.environ.get("PROSTANET_CSP_NONCES", "true").lower() in {
        "true", "yes", "1",
    }


def generate_csp_nonce() -> str:
    """Faubot 2026-04-25 (XXXI) — Tier 7 G2: genera nonce per-request.

    Almacenado en `flask.g.csp_nonce` por before_request hook;
    inyectado en `<script nonce="...">` por templates Jinja.
    """
    return secrets.token_urlsafe(16)


def _csp_with_nonce(nonce: str) -> str:
    """Construye CSP con nonce per-request (más estricto que 'unsafe-inline').

    Reemplaza `'unsafe-inline'` en `script-src` con `'nonce-XXX'`.
    Mantiene `'unsafe-inline'` en `style-src` (Tailwind CDN inline necesario).
    """
    custom = os.environ.get("PROSTANET_CSP", "")
    if custom:
        # User custom CSP — apply nonce only if 'unsafe-inline' present
        return custom.replace(
            "script-src 'self' 'unsafe-inline'",
            f"script-src 'self' 'nonce-{nonce}'",
        )
    # Default CSP: replace script-src 'unsafe-inline' with nonce
    # Keep style-src 'unsafe-inline' for Tailwind CDN
    return (
        "default-src 'self'; "
        f"script-src 'self' 'nonce-{nonce}' https://cdn.tailwindcss.com https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; "
        "img-src 'self' data:; "
        "font-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )


def apply_security_headers(response):
    """Aplica security headers al response. Llamado desde Flask after_request hook.

    Idempotente — sobrescribe headers si ya existen.
    """
    if not is_security_headers_enabled():
        return response

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Permissions-Policy"] = (
        "geolocation=(), microphone=(), camera=(), payment=()"
    )

    # Faubot G2 — per-request CSP nonce when enabled
    if is_csp_nonces_enabled():
        try:
            from flask import g
            nonce = getattr(g, "csp_nonce", None)
        except (ImportError, RuntimeError):
            nonce = None
        if nonce:
            response.headers["Content-Security-Policy"] = _csp_with_nonce(nonce)
        else:
            # Fallback to default CSP if nonce missing (e.g., before_request not run)
            response.headers["Content-Security-Policy"] = os.environ.get(
                "PROSTANET_CSP", DEFAULT_CSP,
            )
    else:
        response.headers["Content-Security-Policy"] = os.environ.get(
            "PROSTANET_CSP", DEFAULT_CSP,
        )

    if is_force_https_enabled():
        # HSTS: 1 year, includeSubDomains (estricto). Solo activar tras
        # confirmación de TLS funcional para evitar lockout HTTP.
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )

    return response


# ════════════════════════════════════════════════════════════════════
# HTTPS enforcement (before_request)
# ════════════════════════════════════════════════════════════════════


def enforce_https_before_request():
    """Si PROSTANET_FORCE_HTTPS, redirige HTTP→HTTPS. Llamado desde before_request.

    Soporta `X-Forwarded-Proto` header (común en reverse proxies como nginx/cloudflare).
    """
    if not is_force_https_enabled():
        return None
    try:
        from flask import request, redirect
    except ImportError:
        return None

    # Detectar si la conexión es HTTPS (directa o vía proxy)
    is_secure = request.is_secure or (
        request.headers.get("X-Forwarded-Proto", "").lower() == "https"
    )
    if is_secure:
        return None
    # Build HTTPS URL preserving path + query
    url = request.url.replace("http://", "https://", 1)
    return redirect(url, code=301)


# ════════════════════════════════════════════════════════════════════
# CSRF token generation + validation
# ════════════════════════════════════════════════════════════════════


def generate_csrf_token(session: dict) -> str:
    """Genera (o reusa) un token CSRF para esta sesión.

    El token se almacena en session (signed cookie) y se valida contra
    request.form[csrf_token] o request.headers[X-CSRF-Token].
    """
    if not session.get(CSRF_TOKEN_SESSION_KEY):
        session[CSRF_TOKEN_SESSION_KEY] = secrets.token_urlsafe(32)
    return session[CSRF_TOKEN_SESSION_KEY]


def validate_csrf_token(session: dict, supplied_token: str | None) -> bool:
    """Valida el token CSRF supplied contra el de la sesión.

    Constant-time comparison.
    """
    if not is_csrf_enabled():
        return True  # CSRF no activo, todo pasa
    expected = session.get(CSRF_TOKEN_SESSION_KEY)
    if not expected or not supplied_token:
        return False
    import hmac as _hmac
    return _hmac.compare_digest(str(expected), str(supplied_token))


def csrf_protect(func: Callable) -> Callable:
    """Decorator para endpoints POST/PUT/DELETE que requieren CSRF.

    Lee token de:
        1. request.headers["X-CSRF-Token"]
        2. request.form["csrf_token"]
        3. request.json["csrf_token"]

    Retorna 403 si no match.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not is_csrf_enabled():
            return func(*args, **kwargs)
        try:
            from flask import request, session, jsonify
        except ImportError:
            return func(*args, **kwargs)

        if request.method.upper() not in {"POST", "PUT", "DELETE", "PATCH"}:
            return func(*args, **kwargs)

        supplied = (
            request.headers.get(CSRF_HEADER_NAME)
            or (request.form.get(CSRF_FORM_FIELD_NAME) if request.form else None)
        )
        if not supplied and request.is_json:
            try:
                supplied = (request.get_json(silent=True) or {}).get(
                    CSRF_FORM_FIELD_NAME,
                )
            except Exception:
                supplied = None

        if not validate_csrf_token(session, supplied):
            from prostanet.shared.security_helpers import error_response_with_trace_id
            try:
                raise PermissionError("CSRF token missing or invalid")
            except PermissionError as exc:
                return error_response_with_trace_id(
                    exc,
                    status_code=403,
                    user_message="CSRF token validation failed.",
                )
        return func(*args, **kwargs)

    return wrapper


# ════════════════════════════════════════════════════════════════════
# Setup helper for create_app integration
# ════════════════════════════════════════════════════════════════════


def register_security_middleware(app) -> None:
    """Registra hooks before_request + after_request en Flask app.

    Llamar desde `create_app` tras `init_auth_db`.

    Faubot 2026-04-25 (XXXI) — Tier 7 G2:
        - Generate per-request CSP nonce on `flask.g.csp_nonce` (always,
          even if security headers off — templates can still use it).
        - Apply CSP header (with nonce) when security headers enabled.
    """
    # Always install nonce generator (templates depend on it)
    @app.before_request
    def _gen_csp_nonce():
        try:
            from flask import g
            g.csp_nonce = generate_csp_nonce()
        except Exception:
            pass

    if not (is_security_headers_enabled() or is_force_https_enabled()):
        logger.info(
            "security_middleware: no env flag set; CSP nonce generator "
            "registered (set PROSTANET_SECURITY_HEADERS=true for full CSP)"
        )
        return

    @app.before_request
    def _https_redirect():
        return enforce_https_before_request()

    @app.after_request
    def _security_headers(response):
        return apply_security_headers(response)

    logger.info(
        f"security_middleware registered | "
        f"headers={is_security_headers_enabled()} | "
        f"https={is_force_https_enabled()} | "
        f"csrf={is_csrf_enabled()} | "
        f"csp_nonces={is_csp_nonces_enabled()}"
    )
