"""auth_ui_context.py — FAUBOT 2026-04-25 (XXXI/XXXVIII/XXXIX) — Tier 7 G2+G6+G7.

Context processor + helper functions para templates Jinja:
  - g.current_user_id, g.current_user, g.current_user_role
  - g.csrf_token (auto-generated cuando CSRF enabled)
  - g.local_login_available (LocalPbkdf2Backend disponible)
  - g.oidc_available (OIDC config completo)
  - g.oidc_backend_label (label legible: "Auth0", "Keycloak", "Google", etc.)
  - g.faubot_release (versión actual)
  - **(G6 XXXVIII)** g.session_indicator_enabled (bool — show countdown badge)
  - **(G6 XXXVIII)** g.session_indicator_poll_interval_ms (int — JS setInterval)
  - **(G6 XXXVIII)** g.session_indicator_refresh_threshold_sec (int — auto-refresh trigger)
  - **(G6 XXXVIII)** g.session_indicator_warning_threshold_sec (int — color → warning)
  - **(NUEVO G7 XXXIX)** g.session_indicator_idle_warning_threshold_sec (int — banner idle)
  - **(NUEVO G7 XXXIX)** g.session_indicator_touch_url (str — POST /api/auth/touch)
  - **(NUEVO G7 XXXIX)** g.session_indicator_touch_debounce_ms (int — debounce activity ping)
  - **(NUEVO G7 XXXIX)** g.session_indicator_idle_timeout_sec (int — server config display)
  - **(NUEVO G7 XXXIX)** g.session_indicator_absolute_timeout_sec (int — server config display)

Helpers para role-based UI rendering:
  - has_role(role)         — True si current user tiene ese role exacto
  - has_scope(scope)       — True si current user tiene ese scope ABAC
  - is_authenticated()     — True si current user logueado
"""
from __future__ import annotations

import logging
import os

from flask import g, session

from prostanet.shared.algorithm_version import FAUBOT_RELEASE
from prostanet.shared.auth_backends import (
    get_auth_backend, session_user_id, LocalPbkdf2Backend, OidcBackend,
    # G7 (XXXIX): session config exposed to UI
    SESSION_ABSOLUTE_TIMEOUT_SECONDS, SESSION_IDLE_TIMEOUT_SECONDS,
)
from prostanet.shared.security_middleware import (
    generate_csrf_token, is_csrf_enabled,
)

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════
# Backend label lookup (UI-friendly)
# ════════════════════════════════════════════════════════════════════


_BACKEND_LABELS = {
    "local_pbkdf2": "Usuario local",
    "local": "Usuario local",
    "oidc": "SSO OIDC",
    "auth0": "Auth0",
    "keycloak": "Keycloak",
    "oauth_google": "Google Workspace",
}


def _backend_label(backend_name: str) -> str:
    return _BACKEND_LABELS.get(backend_name, backend_name)


def _is_oidc_configured() -> bool:
    """Check si OIDC env vars completos."""
    return bool(
        os.environ.get("PROSTANET_OIDC_ISSUER")
        and os.environ.get("PROSTANET_OIDC_CLIENT_ID")
    )


# ════════════════════════════════════════════════════════════════════
# G6 XXXVIII — Session indicator UX configuration
# ════════════════════════════════════════════════════════════════════


# Defaults conservadores: poll cada 60s, auto-refresh cuando faltan <=10min,
# warning amber cuando faltan <=5min. Los 3 son env-overridable por
# despliegues que necesiten otro tradeoff entre carga del IDP y UX.
DEFAULT_SESSION_POLL_INTERVAL_MS = 60_000          # 60s entre polls a /session-status
DEFAULT_SESSION_REFRESH_THRESHOLD_SEC = 600        # auto-refresh cuando expires_in <= 600s (10min)
DEFAULT_SESSION_WARNING_THRESHOLD_SEC = 300        # badge amber cuando expires_in <= 300s (5min)
MIN_POLL_INTERVAL_MS = 5_000                       # nunca permitir <5s entre polls (anti-DoS local)
MAX_POLL_INTERVAL_MS = 600_000                     # nunca permitir >10min entre polls (UX-degraded)

# G7 (XXXIX): idle warning + touch debounce defaults
DEFAULT_SESSION_IDLE_WARNING_THRESHOLD_SEC = 120  # banner cuando idle_remaining <= 2min
DEFAULT_SESSION_TOUCH_DEBOUNCE_MS = 5_000         # 1 touch máximo cada 5s
MIN_TOUCH_DEBOUNCE_MS = 1_000                     # nunca <1s (anti-spam)
MAX_TOUCH_DEBOUNCE_MS = 60_000                    # nunca >60s (perdería precisión idle)


def _get_int_env(var: str, default: int, *, lo: int, hi: int) -> int:
    """Get env var as int, clamping to [lo, hi]; default if missing/invalid."""
    raw = os.environ.get(var, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except (ValueError, TypeError):
        logger.warning(f"{var}={raw!r} not int, using default {default}")
        return default
    return max(lo, min(hi, value))


def get_session_indicator_config() -> dict:
    """Compute session indicator config from env (called per-request).

    Returns dict with:
      - enabled: bool — True only when CLINICAL_AUTH_ENABLED=true
        AND user is authenticated (the indicator is meaningless otherwise)
      - poll_interval_ms: int — JS setInterval period to poll /session-status
      - refresh_threshold_sec: int — when expires_in <= this, JS auto-calls /refresh
      - warning_threshold_sec: int — when expires_in <= this, badge turns amber

    Env vars:
      PROSTANET_SESSION_INDICATOR_ENABLED — "true" to force-enable even when auth dormant
      PROSTANET_SESSION_INDICATOR_POLL_INTERVAL_MS — int (clamped [5000, 600000])
      PROSTANET_SESSION_INDICATOR_REFRESH_THRESHOLD_SEC — int (clamped [60, 3600])
      PROSTANET_SESSION_INDICATOR_WARNING_THRESHOLD_SEC — int (clamped [30, 1800])
    """
    from prostanet.shared.security_helpers import is_clinical_auth_enabled

    auth_on = is_clinical_auth_enabled()
    force_enabled = os.environ.get(
        "PROSTANET_SESSION_INDICATOR_ENABLED", ""
    ).strip().lower() in ("true", "1", "yes", "on")

    enabled = (auth_on or force_enabled) and is_authenticated()

    poll_ms = _get_int_env(
        "PROSTANET_SESSION_INDICATOR_POLL_INTERVAL_MS",
        DEFAULT_SESSION_POLL_INTERVAL_MS,
        lo=MIN_POLL_INTERVAL_MS,
        hi=MAX_POLL_INTERVAL_MS,
    )
    refresh_threshold = _get_int_env(
        "PROSTANET_SESSION_INDICATOR_REFRESH_THRESHOLD_SEC",
        DEFAULT_SESSION_REFRESH_THRESHOLD_SEC,
        lo=60,
        hi=3600,
    )
    warning_threshold = _get_int_env(
        "PROSTANET_SESSION_INDICATOR_WARNING_THRESHOLD_SEC",
        DEFAULT_SESSION_WARNING_THRESHOLD_SEC,
        lo=30,
        hi=1800,
    )
    # Coherence: warning_threshold must be <= refresh_threshold
    # (warning fires before auto-refresh kicks in)
    if warning_threshold > refresh_threshold:
        warning_threshold = refresh_threshold

    # G7 (XXXIX): idle warning + touch debounce config
    idle_warning_threshold = _get_int_env(
        "PROSTANET_SESSION_INDICATOR_IDLE_WARNING_THRESHOLD_SEC",
        DEFAULT_SESSION_IDLE_WARNING_THRESHOLD_SEC,
        lo=15,
        hi=900,
    )
    touch_debounce_ms = _get_int_env(
        "PROSTANET_SESSION_INDICATOR_TOUCH_DEBOUNCE_MS",
        DEFAULT_SESSION_TOUCH_DEBOUNCE_MS,
        lo=MIN_TOUCH_DEBOUNCE_MS,
        hi=MAX_TOUCH_DEBOUNCE_MS,
    )

    return {
        "enabled": enabled,
        "poll_interval_ms": poll_ms,
        "refresh_threshold_sec": refresh_threshold,
        "warning_threshold_sec": warning_threshold,
        # G7 (XXXIX)
        "idle_warning_threshold_sec": idle_warning_threshold,
        "touch_debounce_ms": touch_debounce_ms,
        "idle_timeout_sec": SESSION_IDLE_TIMEOUT_SECONDS,
        "absolute_timeout_sec": SESSION_ABSOLUTE_TIMEOUT_SECONDS,
    }


# ════════════════════════════════════════════════════════════════════
# Template helpers exportados como Jinja globals
# ════════════════════════════════════════════════════════════════════


def is_authenticated() -> bool:
    """True si hay usuario autenticado en la sesión actual."""
    return session_user_id(session) is not None


def current_user_role() -> str:
    """Retorna role del usuario actual o '' si no autenticado."""
    user = current_user_dict()
    if not user:
        return ""
    return str(user.get("role", "")).lower()


def current_user_dict() -> dict:
    """Retorna dict del usuario actual (sin password_hash) o {} si no autenticado."""
    uid = session_user_id(session)
    if uid is None:
        return {}
    try:
        backend = get_auth_backend()
        return backend.get_user(uid) or {}
    except Exception as exc:  # pragma: no cover
        logger.warning(f"current_user_dict error: {type(exc).__name__}: {exc}")
        return {}


def has_role(role: str) -> bool:
    """Template helper: True si current user tiene ese role exacto.

    Uso en Jinja:
        {% if has_role('admin') %}<a href="/admin">Admin</a>{% endif %}
    """
    return current_user_role() == role.lower()


def has_scope(scope: str) -> bool:
    """Template helper: True si current user tiene ese scope ABAC.

    Uso en Jinja:
        {% if has_scope('audit:read') %}
            <a href="/gates-coverage-dashboard">Auditoría</a>
        {% endif %}
    """
    role = current_user_role()
    if not role:
        return False
    try:
        backend = get_auth_backend()
        return backend.has_scope(role, scope)
    except Exception:
        return False


# ════════════════════════════════════════════════════════════════════
# Context processor + before_request setup
# ════════════════════════════════════════════════════════════════════


def register_auth_ui_context(app) -> None:
    """Registra context_processor + before_request hook + Jinja globals.

    Llamar desde `create_app` después de `register_security_middleware`.
    """

    @app.before_request
    def _populate_auth_g():
        """Populate `g` with auth UI context (per-request)."""
        # CSRF token (siempre disponible si CSRF enabled o nonces enabled)
        if is_csrf_enabled():
            try:
                g.csrf_token = generate_csrf_token(session)
            except Exception:
                g.csrf_token = ""
        else:
            g.csrf_token = ""

        # Backend availability
        g.local_login_available = True  # LocalPbkdf2Backend siempre disponible
        g.oidc_available = _is_oidc_configured()
        backend_name = os.environ.get("PROSTANET_AUTH_BACKEND", "local").lower()
        g.oidc_backend_label = _backend_label(backend_name) if g.oidc_available else ""

        # Versioning
        g.faubot_release = FAUBOT_RELEASE

        # Current user metadata
        g.current_user = current_user_dict()
        g.current_user_role = current_user_role()
        g.is_authenticated = is_authenticated()

        # G6 XXXVIII — Session indicator config (countdown badge + auto-refresh)
        indicator_cfg = get_session_indicator_config()
        g.session_indicator_enabled = indicator_cfg["enabled"]
        g.session_indicator_poll_interval_ms = indicator_cfg["poll_interval_ms"]
        g.session_indicator_refresh_threshold_sec = indicator_cfg[
            "refresh_threshold_sec"
        ]
        g.session_indicator_warning_threshold_sec = indicator_cfg[
            "warning_threshold_sec"
        ]
        # G7 XXXIX — Idle/absolute differentiation + touch endpoint
        g.session_indicator_idle_warning_threshold_sec = indicator_cfg[
            "idle_warning_threshold_sec"
        ]
        g.session_indicator_touch_debounce_ms = indicator_cfg[
            "touch_debounce_ms"
        ]
        g.session_indicator_touch_url = "/api/auth/touch"
        g.session_indicator_idle_timeout_sec = indicator_cfg[
            "idle_timeout_sec"
        ]
        g.session_indicator_absolute_timeout_sec = indicator_cfg[
            "absolute_timeout_sec"
        ]

    @app.context_processor
    def _inject_auth_helpers():
        """Make helpers callable from Jinja templates."""
        return {
            "has_role": has_role,
            "has_scope": has_scope,
            "is_authenticated": is_authenticated,
            "current_user_role": current_user_role,
        }

    logger.info(
        f"auth_ui_context registered | "
        f"oidc_available={_is_oidc_configured()} | "
        f"csrf_enabled={is_csrf_enabled()}"
    )
