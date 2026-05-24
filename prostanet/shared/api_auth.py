"""api_auth.py — Sprint 6 (FAUBOT CXLIV).

Auth + autorización transversal para endpoints REST clínicos.

Cierra los hallazgos CRITICAL C1-C5 de la verificación REST APIs estricta
(FAUBOT CXLIII):
  - C1: ml_inference_routes (5 endpoints) sin auth
  - C2: trajectory_routes sin auth
  - C3: decision_override_routes POST sin auth + clinician_id del payload
  - C4: data_integrity_routes /audit/apply mutación masiva sin auth
  - C5: data_integrity_routes /<nss>/resolve mutación sin auth

Diseño:
  - Decorators ligeros sobre Flask request → cierre temprano si sesión inválida
  - Reusa session_user_id (auth_backends.py) ya existente
  - Devuelve JSON 401/403 con shape estable {success: False, error: code}
  - No expone si el endpoint existe pero requiere auth vs si NSS no existe
  - Captura user_id en `flask.g.api_auth_user_id` para uso posterior en handlers
    (audit trail, override clinician_id desde session NO payload)

Roles soportados:
  - clinician  → operación clínica per-paciente (GET + POST scoped)
  - admin      → operaciones poblacionales (mass-mutation, stats, apply)

Patrón de uso:
    from prostanet.shared.api_auth import require_clinician, require_admin

    @bp.route("/api/foo/<nss>", methods=["GET"])
    @require_clinician
    def my_handler(nss):
        user_id = current_api_user_id()  # garantizado not-None aquí
        ...
"""
from __future__ import annotations

import logging
from functools import wraps
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Shape estable de errores
# ─────────────────────────────────────────────────────────────────────


def _unauth_response(reason: str, status: int = 401) -> tuple:
    """Respuesta uniforme para fallos auth. No leakea detalle interno."""
    try:
        from flask import jsonify
        return jsonify({
            "success": False,
            "error": reason,
            "message": (
                "Sesión clínica requerida. Inicie sesión vía POST /api/auth/login."
                if status == 401 else
                "Permisos insuficientes para esta operación."
            ),
        }), status
    except Exception:
        # Fallback en tests sin Flask context
        return ({"success": False, "error": reason}, status)


# ─────────────────────────────────────────────────────────────────────
# Core: resolve session → user_id
# ─────────────────────────────────────────────────────────────────────


def _resolve_session_user_id() -> int | None:
    """Devuelve user_id de la sesión Flask actual o None.

    Encapsula el import lazy + el try defensive para que los handlers
    no necesiten conocer la mecánica de session storage.
    """
    try:
        from flask import session
        from prostanet.shared.auth_backends import session_user_id
        return session_user_id(session)
    except Exception as exc:
        logger.warning(
            "api_auth: session resolution failed: %s: %s",
            type(exc).__name__, exc,
        )
        return None


def _resolve_user_role(user_id: int) -> str | None:
    """Devuelve role del user desde DB. None si no se puede resolver."""
    try:
        from prostanet.shared.auth_backends import get_auth_backend
        backend = get_auth_backend()
        user = backend.get_user(user_id) or {}
        return str(user.get("role") or "").strip().lower() or None
    except Exception as exc:
        logger.warning(
            "api_auth: role resolution failed for user_id=%s: %s",
            user_id, exc,
        )
        return None


# ─────────────────────────────────────────────────────────────────────
# Public API: decorators + accessors
# ─────────────────────────────────────────────────────────────────────


CLINICIAN_ROLES = {"clinician", "admin", "researcher", "physician"}
"""Roles autorizados para operaciones clínicas per-paciente."""

ADMIN_ROLES = {"admin"}
"""Roles autorizados para mutaciones poblacionales + stats globales."""


def current_api_user_id() -> int | None:
    """Devuelve user_id del request actual (set por @require_*).

    Para uso DENTRO de handlers decorados — fuera del decorator devuelve None.
    """
    try:
        from flask import g
        return getattr(g, "api_auth_user_id", None)
    except Exception:
        return None


def current_api_user_role() -> str | None:
    """Devuelve role del request actual (set por @require_*)."""
    try:
        from flask import g
        return getattr(g, "api_auth_user_role", None)
    except Exception:
        return None


def require_clinician(func: Callable) -> Callable:
    """Requiere sesión clínica válida.

    Si la sesión no es válida → 401.
    Si el role no está en CLINICIAN_ROLES → 403.
    Set `flask.g.api_auth_user_id` + `api_auth_user_role` para el handler.

    Test bypass: si env var `PROSTANET_API_AUTH_BYPASS=1` está set,
    permite passing sin validación. Útil para pytest aislado sin sesión.
    Producción NUNCA debe set este flag.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        import os
        from flask import g

        # Test bypass
        if os.environ.get("PROSTANET_API_AUTH_BYPASS") == "1":
            try:
                g.api_auth_user_id = 0
                g.api_auth_user_role = "test_bypass"
            except Exception:
                pass
            return func(*args, **kwargs)

        user_id = _resolve_session_user_id()
        if user_id is None:
            return _unauth_response("session_required", 401)

        role = _resolve_user_role(user_id)
        if role is None or role not in CLINICIAN_ROLES:
            return _unauth_response("clinician_role_required", 403)

        try:
            g.api_auth_user_id = user_id
            g.api_auth_user_role = role
        except Exception:
            pass

        return func(*args, **kwargs)

    return wrapper


def require_admin(func: Callable) -> Callable:
    """Requiere sesión admin válida.

    Diferencia respecto a `require_clinician`: este decorator EXIGE role
    admin específicamente (no acepta clinician/researcher).

    Aplicar a:
      - Mutaciones poblacionales (data_integrity /audit/apply)
      - Stats agregadas que exponen IP institucional (override /stats)
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        import os
        from flask import g

        # Test bypass
        if os.environ.get("PROSTANET_API_AUTH_BYPASS") == "1":
            try:
                g.api_auth_user_id = 0
                g.api_auth_user_role = "test_bypass_admin"
            except Exception:
                pass
            return func(*args, **kwargs)

        user_id = _resolve_session_user_id()
        if user_id is None:
            return _unauth_response("session_required", 401)

        role = _resolve_user_role(user_id)
        if role is None or role not in ADMIN_ROLES:
            return _unauth_response("admin_role_required", 403)

        try:
            g.api_auth_user_id = user_id
            g.api_auth_user_role = role
        except Exception:
            pass

        return func(*args, **kwargs)

    return wrapper


# ─────────────────────────────────────────────────────────────────────
# Helper para audit trail con user from session (no del payload)
# ─────────────────────────────────────────────────────────────────────


def audit_actor() -> dict[str, Any]:
    """Devuelve dict con user_id + role del request actual para audit logging.

    Patrón:
        actor = audit_actor()
        log.insert(actor_user_id=actor['user_id'], actor_role=actor['role'], ...)
    """
    return {
        "user_id": current_api_user_id(),
        "role": current_api_user_role() or "unknown",
    }


__all__ = [
    "require_clinician",
    "require_admin",
    "current_api_user_id",
    "current_api_user_role",
    "audit_actor",
    "CLINICIAN_ROLES",
    "ADMIN_ROLES",
]
