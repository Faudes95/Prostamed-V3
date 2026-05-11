"""security_helpers.py — Faubot 2026-04-25 (XXV) — Tier 7 G1 hardening.

Helpers de seguridad para endpoints HTTP:

  * **error_response_with_trace_id()** (CRIT-4): respuesta de error
    sanitizada que reemplaza `str(exc)` por un `trace_id` opaco. La
    excepción real se loguea en el server-side log para debugging
    sin filtrar paths/versiones al cliente HTTP.

  * **scrub_phi_for_audit()** (CRIT-1): allowlist + redact patterns
    para `decision_audit_builder._build_datos_dimension`. Redacta
    valores de campos sensibles (PHI) preservando el schema para
    consumers downstream (auditor regulatorio).

  * **safe_patient_identity()** (CRIT-1 cont): construye un identity
    "minimal-disclosure" por defecto. Se preserva `id` opaco; `nss`
    y `full_name` solo si el caller solicita scope `phi:read` (hook
    listo para CRIT-3 cuando se integre IDP).

  * **require_clinical_session()** (CRIT-3 placeholder): decorator
    no-op que registra el endpoint como "PHI-protected". Cuando
    `CLINICAL_AUTH_ENABLED=True` (futuro Tier 7 G1.5), aplicará
    Flask-Login + ABAC. Por ahora solo etiqueta + log de acceso.

Aporte a las 5 dimensiones (Tier 7 G1):
  - **DATOS**: PHI scrubbed en endpoints públicos
  - **VERSIÓN**: trace_id permite correlacionar exception ↔ FAUBOT_RELEASE
  - **CÓMO/POR QUÉ/EVIDENCIA**: preservadas (no degraded por security)
"""
from __future__ import annotations

import logging
import os
import re
import uuid
from functools import wraps
from typing import Any, Callable

from flask import jsonify, request

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════
# CRIT-4 — Error sanitization
# ════════════════════════════════════════════════════════════════════


def error_response_with_trace_id(
    exc: Exception,
    *,
    status_code: int = 500,
    user_message: str = "Internal server error.",
    log_extra: dict | None = None,
) -> tuple:
    """Faubot 2026-04-25 (XXV) — CRIT-4 sanitization.

    Construye una respuesta JSON de error sin filtrar `str(exc)` al
    cliente. Genera un `trace_id` UUID4 opaco que el cliente puede
    citar al reportar el incidente; el server-side log contiene la
    excepción real correlacionada por el `trace_id`.

    Replaces:
        return jsonify({"success": False, "error": str(exc)}), 500

    Con:
        return error_response_with_trace_id(exc)

    Args:
        exc: la excepción capturada
        status_code: código HTTP de respuesta (default 500)
        user_message: mensaje genérico al cliente (sin info técnica)
        log_extra: contexto adicional para el log (e.g., patient_ref)

    Returns:
        Tupla (Flask Response, status_code) compatible con `return ...` directo.
    """
    trace_id = str(uuid.uuid4())
    log_payload = {
        "trace_id": trace_id,
        "exc_type": type(exc).__name__,
        "exc_msg": str(exc)[:500],  # cap para logs
        "endpoint": getattr(request, "endpoint", "unknown"),
        "path": getattr(request, "path", "unknown"),
    }
    if log_extra:
        log_payload.update(log_extra)
    logger.error(f"endpoint_error | {log_payload}")
    return jsonify({
        "success": False,
        "error": user_message,
        "trace_id": trace_id,
    }), status_code


# ════════════════════════════════════════════════════════════════════
# CRIT-1 — PHI scrubbing for decision audit
# ════════════════════════════════════════════════════════════════════

# Tokens que indican un campo PHI directo (siempre redactar)
_PHI_FIELD_NAMES = frozenset({
    "nss", "social_security_number", "ssn",
    "full_name", "patient_name", "name",
    "first_name", "last_name", "middle_name",
    "address", "street_address", "postal_code", "zip_code",
    "phone", "phone_number", "telephone", "mobile",
    "email", "email_address",
    "birth_date", "date_of_birth", "dob",
    "passport", "passport_number",
    "national_id", "curp", "rfc",
})

# Patrones PHI en valores (números largos sospechosos, etc.)
_PHI_VALUE_PATTERNS = [
    re.compile(r"\b\d{11}\b"),  # NSS mexicano (11 dígitos)
    re.compile(r"\b\d{10}\b"),  # phone CDMX (10 dígitos)
    re.compile(r"\b[A-Z]{4}\d{6}[A-Z0-9]{8}\b"),  # CURP
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),  # email
]

_REDACTED = "[REDACTED-PHI]"


def _value_looks_like_phi(value: Any) -> bool:
    """Heurística: detecta si un valor escalar contiene patrón PHI."""
    if not isinstance(value, str):
        return False
    return any(p.search(value) for p in _PHI_VALUE_PATTERNS)


def scrub_phi_for_audit(snapshot: dict | None) -> dict:
    """Faubot 2026-04-25 (XXV) — CRIT-1 sanitization.

    Recorre el `input_snapshot` recursivamente y redacta:
      * Campos cuyo `name` está en `_PHI_FIELD_NAMES`
      * Valores escalares que matcheen `_PHI_VALUE_PATTERNS`

    Preserva la estructura del schema (todas las claves siguen
    presentes) para que consumers downstream (auditor regulatorio,
    UI dashboard) no rompan, pero los valores sensibles quedan
    `[REDACTED-PHI]`.

    Los valores clínicos (PSA, Gleason, qtc_ms, etc.) se preservan
    porque son críticos para la dimensión DATOS del audit.

    Args:
        snapshot: dict del input_snapshot original

    Returns:
        Dict con misma estructura + PHI redactado
    """
    if not snapshot:
        return {}
    return _scrub_recursive(snapshot)


def _scrub_recursive(obj: Any) -> Any:
    """Helper recursivo de scrub_phi_for_audit."""
    if isinstance(obj, dict):
        return {
            k: (_REDACTED if k.lower() in _PHI_FIELD_NAMES
                else _scrub_recursive(v))
            for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return [_scrub_recursive(v) for v in obj]
    if _value_looks_like_phi(obj):
        return _REDACTED
    return obj


def safe_patient_identity(
    identity: dict | None,
    *,
    include_phi: bool = False,
) -> dict:
    """Faubot 2026-04-25 (XXV) — CRIT-1 identity minimization.

    Construye un identity dict para el endpoint `/api/decision-audit`
    aplicando minimal-disclosure por default:

      * `display_label`: derivado opaco (e.g., "P-{id_hash}")
      * `id`: numérico opaco (puede ser usado para enumerar visitas)
      * `nss`, `full_name`: solo si `include_phi=True` (futuro: scope
        `phi:read` validado por CRIT-3 auth decorator)

    Args:
        identity: dict original con id/nss/full_name/etc.
        include_phi: si True, retorna nss + full_name. Default False.

    Returns:
        Dict con `display_label`, `id`, y opcionalmente nss/full_name.
    """
    if not identity:
        return {"display_label": "P-unknown", "id": None}

    pid = identity.get("id")
    # Display label opaco (no PHI, derivado del ID)
    display = f"P-{abs(hash(str(pid))) % 100000:05d}" if pid else "P-unknown"

    base = {
        "display_label": display,
        "id": pid,
    }

    if include_phi:
        base.update({
            "nss": identity.get("nss"),
            "full_name": identity.get("full_name"),
            "phi_disclosed": True,
        })
    else:
        base["phi_disclosed"] = False
        base["phi_note"] = (
            "PHI fields (nss, full_name) redacted. "
            "Request with scope=phi:read after auth (Tier 7 G1.5)."
        )

    return base


# ════════════════════════════════════════════════════════════════════
# CRIT-3 — Clinical session decorator (placeholder for G1.5 IDP)
# ════════════════════════════════════════════════════════════════════


def is_clinical_auth_enabled() -> bool:
    """Lee `CLINICAL_AUTH_ENABLED` env var. Default `false` para no
    romper desarrollo local. En producción debe ser `true`.

    Cuando True, `require_clinical_session` exigirá auth real.
    Cuando False (default), el decorator solo loguea acceso.
    """
    return os.environ.get("CLINICAL_AUTH_ENABLED", "false").lower() in {
        "true", "yes", "1",
    }


def _client_prefers_html() -> bool:
    """Detecta si el cliente prefiere HTML sobre JSON.

    Faubot 2026-04-25 (XXXII) — Tier 7 G5: usado por
    `require_clinical_session` para 302 redirect a /login en HTML
    requests vs 401 JSON en API requests.
    """
    try:
        accept = request.headers.get("Accept", "")
    except Exception:
        return False
    accept_lower = accept.lower()
    # JSON explícito → API client
    if "application/json" in accept_lower and "text/html" not in accept_lower:
        return False
    # HTML explícito o wildcard sin JSON → HTML client (browser)
    if "text/html" in accept_lower:
        return True
    # Wildcard `*/*` o vacío: assume HTML (browsers default)
    if not accept or accept_lower.startswith("*/*") or accept_lower == "*":
        return True
    return False


def require_clinical_session(
    *,
    scope: str = "phi:read",
    audit_log: bool = True,
    redirect_to_login: bool | None = None,
    passive: bool = False,
) -> Callable:
    """Faubot 2026-04-25 (XXV→XXVIII→XXXII) — CRIT-3 dormant→active (G1.5)
    + auth gateway HTML (G5).

    Decorator para endpoints que manejan PHI. Modo dual + behavior dual:

      - DORMANT (`CLINICAL_AUTH_ENABLED=false`, default):
        Solo loguea acceso sin bloquear (preserva backward-compat).
      - ACTIVE (`CLINICAL_AUTH_ENABLED=true`, post-G1.5):
        Valida session via auth_backends + scope ABAC + persiste audit log.

    Behavior on auth failure (G5):
      - JSON request (Accept: application/json) → 401/403 JSON response
      - HTML request (Accept: text/html, browser) → 302 redirect a /login
      - Override explícito via `redirect_to_login=True/False`

    Uso (G1.5 — sin cambio):
        @app.route("/api/decision-audit/<patient_ref>")
        @require_clinical_session(scope="phi:read")
        def decision_audit(patient_ref): ...

    Uso (G5 — HTML endpoints):
        @app.route("/patient_profile/<nss>")
        @require_clinical_session(scope="phi:read", redirect_to_login=True)
        def patient_profile(nss): ...

    Args:
        scope: scope ABAC requerido (e.g., "phi:read", "phi:write",
            "audit:read", "audit:write")
        audit_log: si True, persiste cada acceso a clinical_audit_log
            (cuando AUTH_ENABLED) + log structured siempre
        redirect_to_login: si True, auth fail → 302 redirect a /login.
            Si False, auth fail → 401/403 JSON (G1.5 behavior).
            Si None (default), auto-detecta según Accept header.
        passive: si True (G7 XXXIX), el endpoint NO resetea el sliding
            window IDLE — útil para endpoints de polling (whoami,
            session-status, refresh) que no deben extender la sesión
            artificialmente. Default False (la mayoría de endpoints
            son user-driven y deben contar como actividad).

    Returns:
        Decorator function que retorna:
          - 401/403 JSON si JSON request + auth fail
          - 302 redirect a /login si HTML request + auth fail
          - response del endpoint si pasa o si DORMANT mode
    """
    def decorator(func: Callable) -> Callable:
        # Marcar el endpoint como PHI-protected (introspectable)
        func._clinical_session_required = True
        func._required_scope = scope

        @wraps(func)
        def wrapper(*args, **kwargs):
            endpoint_name = func.__name__
            request_path = getattr(request, "path", "unknown")
            request_method = getattr(request, "method", "")
            request_ip = getattr(request, "remote_addr", "")
            request_ua = (request.headers.get("User-Agent", "")
                          if hasattr(request, "headers") else "")

            # Always log structured access (no PHI here)
            if audit_log:
                logger.info(
                    f"clinical_endpoint_access | "
                    f"endpoint={endpoint_name} | scope={scope} | "
                    f"path={request_path} | "
                    f"auth_enabled={is_clinical_auth_enabled()}"
                )

            if not is_clinical_auth_enabled():
                # DORMANT mode: pass-through (backward-compat)
                return func(*args, **kwargs)

            # ── ACTIVE mode (Faubot XXVIII / Tier 7 G1.5) ────────────
            try:
                from flask import session as flask_session
                from prostanet.shared.auth_backends import (
                    session_user_id, get_auth_backend,
                    # G7 (XXXIX): granular expiry diagnostics + touch
                    session_expiry_reason, session_touch_activity,
                    SESSION_REASON_VALID, SESSION_REASON_EXPIRED_IDLE,
                    SESSION_REASON_EXPIRED_ABSOLUTE,
                )
                from prostanet.shared.auth_db import write_audit_log_entry
            except ImportError:
                # If auth modules unavailable, fail-closed (deny by default)
                return jsonify({
                    "success": False,
                    "error": "Authentication subsystem unavailable.",
                }), 503

            # G7 (XXXIX): compute expiry reason BEFORE user_id (so we can
            # distinguish idle vs absolute timeouts in audit log + redirect)
            reason_code = session_expiry_reason(flask_session)
            user_id = session_user_id(flask_session)

            # G5: decide response format per request
            should_redirect = (
                redirect_to_login
                if redirect_to_login is not None
                else _client_prefers_html()
            )

            # No session or expired
            if user_id is None:
                # G7: differentiate audit_log status by reason
                if reason_code == SESSION_REASON_EXPIRED_IDLE:
                    audit_status = "denied_session_idle_timeout"
                    audit_reason = (
                        "Session expired due to idle timeout "
                        "(no activity beyond IDLE window)"
                    )
                    redirect_query = "?error=session_expired&reason=idle"
                elif reason_code == SESSION_REASON_EXPIRED_ABSOLUTE:
                    audit_status = "denied_session_absolute_timeout"
                    audit_reason = (
                        "Session expired due to absolute timeout "
                        "(login_time + ABSOLUTE window exceeded; re-login required)"
                    )
                    redirect_query = "?error=session_expired&reason=absolute"
                else:
                    audit_status = "denied_no_session"
                    audit_reason = "No valid session or session expired"
                    redirect_query = "?error=session_expired"

                if audit_log:
                    write_audit_log_entry(
                        endpoint=endpoint_name,
                        status=audit_status,
                        path=request_path,
                        method=request_method,
                        scope=scope,
                        ip_address=request_ip,
                        user_agent=request_ua,
                        reason=audit_reason,
                    )
                if should_redirect:
                    from flask import redirect as flask_redirect
                    return flask_redirect("/login" + redirect_query, code=302)
                return jsonify({
                    "success": False,
                    "error": "Authentication required.",
                    "reason": reason_code,
                }), 401

            # Session valid → check scope
            backend = get_auth_backend()
            user = backend.get_user(user_id)
            if user is None:
                if audit_log:
                    write_audit_log_entry(
                        endpoint=endpoint_name,
                        status="denied_user_not_found",
                        user_id=user_id,
                        path=request_path,
                        method=request_method,
                        scope=scope,
                        ip_address=request_ip,
                        user_agent=request_ua,
                        backend=backend.backend_name,
                        reason="User_id in session does not match active user",
                    )
                if should_redirect:
                    from flask import redirect as flask_redirect
                    return flask_redirect("/login?error=session_expired", code=302)
                return jsonify({
                    "success": False,
                    "error": "Session user not found or inactive.",
                }), 401

            user_role = str(user.get("role", "viewer"))
            if not backend.has_scope(user_role, scope):
                if audit_log:
                    write_audit_log_entry(
                        endpoint=endpoint_name,
                        status="denied_invalid_scope",
                        user_id=user_id,
                        username=str(user.get("username", "")),
                        path=request_path,
                        method=request_method,
                        scope=scope,
                        ip_address=request_ip,
                        user_agent=request_ua,
                        backend=backend.backend_name,
                        reason=f"role={user_role} lacks scope={scope}",
                    )
                if should_redirect:
                    from flask import redirect as flask_redirect
                    return flask_redirect(
                        "/login?error=access_denied", code=302,
                    )
                return jsonify({
                    "success": False,
                    "error": "Insufficient permissions for this resource.",
                }), 403

            # G7 (XXXIX): touch IDLE sliding window for user-driven endpoints.
            # Passive endpoints (whoami, session-status, refresh) opt-out via
            # `passive=True` so polling doesn't artificially extend session.
            if not passive:
                try:
                    session_touch_activity(flask_session)
                except Exception:  # pragma: no cover — defensive
                    pass

            # Authorized — log + invoke endpoint
            if audit_log:
                write_audit_log_entry(
                    endpoint=endpoint_name,
                    status="authorized",
                    user_id=user_id,
                    username=str(user.get("username", "")),
                    path=request_path,
                    method=request_method,
                    scope=scope,
                    ip_address=request_ip,
                    user_agent=request_ua,
                    backend=backend.backend_name,
                )
            return func(*args, **kwargs)

        return wrapper

    return decorator


# ════════════════════════════════════════════════════════════════════
# CRIT-2 — Bind/secret_key helpers (used by app.py)
# ════════════════════════════════════════════════════════════════════


def get_bind_host() -> str:
    """Determina el bind host del Flask app server.

    Default: `127.0.0.1` (localhost-only, seguro).
    Para escuchar en `0.0.0.0` (accesible desde red), set
    `PROSTANET_ALLOW_PUBLIC_BIND=true` explícitamente. Esto previene
    exposiciones accidentales del server en redes compartidas.
    """
    if os.environ.get("PROSTANET_ALLOW_PUBLIC_BIND", "false").lower() in {
        "true", "yes", "1",
    }:
        host = os.environ.get("PROSTANET_BIND_HOST", "0.0.0.0")
        logger.warning(
            f"⚠️  Flask bind host set to {host} (public). "
            "Ensure reverse proxy + TLS + auth are configured upstream."
        )
        return host
    return "127.0.0.1"


def get_secret_key() -> str:
    """Faubot 2026-04-25 (XXV) — CRIT-2.

    Lee `app.secret_key` desde `PROSTANET_SECRET_KEY` env var.
    Si no está set:
      - En modo TESTING: usa una key dev determinística (acepta tests).
      - En modo desarrollo: emite warning + genera key aleatoria por sesión.
      - En modo producción (`FLASK_ENV=production`): RAISES RuntimeError
        para forzar configuración explícita.

    Returns:
        Secret key string para `app.secret_key`.
    """
    key = os.environ.get("PROSTANET_SECRET_KEY")
    if key:
        return key

    is_production = os.environ.get("FLASK_ENV", "").lower() == "production"
    if is_production:
        raise RuntimeError(
            "PROSTANET_SECRET_KEY env var REQUIRED in production. "
            "Set it to a long random string before starting Flask."
        )

    # Dev/test fallback
    is_testing = os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("TESTING")
    if is_testing:
        return "dev-test-secret-key-not-for-production-faubot-xxv"

    # Dev mode: random per session + warning
    random_key = uuid.uuid4().hex
    logger.warning(
        "⚠️  PROSTANET_SECRET_KEY not set; using random per-session key. "
        "Set it explicitly for stable sessions across restarts."
    )
    return random_key
