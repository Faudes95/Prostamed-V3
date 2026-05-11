from __future__ import annotations

import logging
import os
import secrets
from functools import wraps
from typing import Callable


logger = logging.getLogger(__name__)

CSRF_TOKEN_SESSION_KEY = "_prostanet_csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_FORM_FIELD_NAME = "csrf_token"

DEFAULT_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://cdn.tailwindcss.com https://unpkg.com; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com data:; "
    "img-src 'self' data: blob:; "
    "connect-src 'self'; "
    "frame-ancestors 'self'"
)


def _enabled(name: str, default: str = "0") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in {"1", "true", "yes", "on"}


def is_security_headers_enabled() -> bool:
    return _enabled("PROSTANET_SECURITY_HEADERS", "1")


def is_force_https_enabled() -> bool:
    return _enabled("PROSTANET_FORCE_HTTPS", "0")


def is_csrf_enabled() -> bool:
    return _enabled("PROSTANET_CSRF_ENABLED", "0")


def is_csp_nonces_enabled() -> bool:
    return _enabled("PROSTANET_CSP_NONCES", "0")


def generate_csp_nonce() -> str:
    return secrets.token_urlsafe(16)


def _csp_with_nonce(nonce: str) -> str:
    custom = os.environ.get("PROSTANET_CONTENT_SECURITY_POLICY", "").strip()
    csp = custom or DEFAULT_CSP
    if nonce and "'unsafe-inline'" in csp:
        csp = csp.replace("'unsafe-inline'", f"'unsafe-inline' 'nonce-{nonce}'", 1)
    return csp


def apply_security_headers(response):
    if not is_security_headers_enabled():
        return response
    try:
        from flask import g

        nonce = getattr(g, "csp_nonce", "")
    except Exception:
        nonce = ""
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Content-Security-Policy", _csp_with_nonce(nonce))
    return response


def enforce_https_before_request():
    if not is_force_https_enabled():
        return None
    try:
        from flask import redirect, request

        is_secure = request.is_secure or request.headers.get("X-Forwarded-Proto", "") == "https"
        if not is_secure and request.method in {"GET", "HEAD"}:
            return redirect(request.url.replace("http://", "https://", 1), code=301)
    except Exception as exc:
        logger.debug("HTTPS enforcement skipped: %s", exc)
    return None


def generate_csrf_token(session) -> str:
    token = session.get(CSRF_TOKEN_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[CSRF_TOKEN_SESSION_KEY] = token
    return str(token)


def validate_csrf_token(session, supplied_token: str | None) -> bool:
    expected = session.get(CSRF_TOKEN_SESSION_KEY)
    if not expected or not supplied_token:
        return False
    return secrets.compare_digest(str(expected), str(supplied_token))


def csrf_protect(func: Callable) -> Callable:
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not is_csrf_enabled():
            return func(*args, **kwargs)
        from flask import abort, request, session

        token = request.headers.get(CSRF_HEADER_NAME) or request.form.get(CSRF_FORM_FIELD_NAME)
        if request.method not in {"GET", "HEAD", "OPTIONS"} and not validate_csrf_token(session, token):
            abort(400, "CSRF token inválido o ausente")
        return func(*args, **kwargs)

    return wrapper


def register_security_middleware(app) -> None:
    @app.before_request
    def _https_redirect():
        return enforce_https_before_request()

    @app.before_request
    def _gen_csp_nonce():
        if not is_csp_nonces_enabled():
            return None
        from flask import g

        g.csp_nonce = generate_csp_nonce()
        return None

    @app.after_request
    def _security_headers(response):
        return apply_security_headers(response)

    @app.context_processor
    def _security_context():
        try:
            from flask import g, session

            token = generate_csrf_token(session) if is_csrf_enabled() else ""
            nonce = getattr(g, "csp_nonce", "")
        except Exception:
            token = ""
            nonce = ""
        return {
            "csrf_token": token,
            "csp_nonce": nonce,
            "csrf_header_name": CSRF_HEADER_NAME,
            "csrf_form_field_name": CSRF_FORM_FIELD_NAME,
        }


__all__ = [
    "CSRF_TOKEN_SESSION_KEY",
    "CSRF_HEADER_NAME",
    "CSRF_FORM_FIELD_NAME",
    "is_security_headers_enabled",
    "is_force_https_enabled",
    "is_csrf_enabled",
    "is_csp_nonces_enabled",
    "generate_csp_nonce",
    "apply_security_headers",
    "enforce_https_before_request",
    "generate_csrf_token",
    "validate_csrf_token",
    "csrf_protect",
    "register_security_middleware",
]
