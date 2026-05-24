"""auth_backends.py — FAUBOT 2026-04-25 (XXVIII) — Tier 7 G1.5.

Abstracción de backends de autenticación para `require_clinical_session`.
Permite swap entre IDPs sin cambiar el decorador o los endpoints.

Backends soportados:
  - LocalPbkdf2Backend (default) — usuarios locales con hash PBKDF2-SHA256
    (stdlib-only, sin dependencias externas, NIST SP 800-132 compliant).
  - Auth0Backend (placeholder) — Tier 7 G1.6+ activación con Auth0 SaaS.
  - KeycloakBackend (placeholder) — Tier 7 G1.6+ activación con Keycloak.
  - OAuthGoogleBackend (placeholder) — Tier 7 G1.6+ activación con OAuth.

Diseño:
  - Sin side-effects en imports (clases puras).
  - Backend seleccionable vía env var `PROSTANET_AUTH_BACKEND` (default: "local").
  - Cada backend implementa la interfaz `AuthBackend` (verify, create, get).
  - Usuarios persisten en `clinical_users` table (LocalPbkdf2Backend); para
    backends federados (Auth0, Keycloak) la tabla solo cachea metadata.

Aporte a auditabilidad (Clinical Decision Engine):
  - **VERSIÓN:** `PROSTANET_AUTH_BACKEND` queda registrado en algorithm_version
    para trazar qué backend emitió la sesión cuando se hizo la decisión.
  - **DATOS:** cada login/logout/audit_log_event queda en clinical_audit_log
    con user_id + timestamp + scope + trace_id correlacionable.
  - **POR QUÉ:** sesiones expiradas, scope mismatch, role mismatch retornan
    mensajes específicos sin filtrar PHI o detalles internos.

Activación:
  - Default `CLINICAL_AUTH_ENABLED=false` → todos los endpoints decorados
    permanecen en modo dormant (passes-through), preservando compatibility.
  - Set `CLINICAL_AUTH_ENABLED=true` → require_clinical_session valida
    sesión real + scope + role.

Faubot 2026-04-25 (XXVIII):
  - Implementación stdlib-only (sin flask-login/bcrypt) para minimizar
    supply-chain risk en healthcare deployment.
  - PBKDF2-SHA256 con 600,000 iteraciones (OWASP 2024 recommendation).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════
# PBKDF2 helpers (stdlib-only, NIST SP 800-132 compliant)
# ════════════════════════════════════════════════════════════════════


# OWASP 2024 recommendation for PBKDF2-SHA256: 600,000 iterations.
PBKDF2_ITERATIONS = 600_000
PBKDF2_HASH_NAME = "sha256"
PBKDF2_SALT_BYTES = 32
PBKDF2_KEY_LENGTH = 64


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    """Hash password con PBKDF2-SHA256.

    Args:
        password: contraseña en plaintext (UTF-8).
        salt: salt explícito (32 bytes); si None, genera uno random.

    Returns:
        String formato `pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>`
        (parseable + portable, sigue convención Django/Werkzeug).

    Notar:
        - PBKDF2-SHA256 es NIST-approved (SP 800-132).
        - 600k iterations = OWASP 2024 recomendado.
        - Fixed-time comparación via `verify_password`.
    """
    if not password:
        raise ValueError("Password cannot be empty")
    if salt is None:
        salt = secrets.token_bytes(PBKDF2_SALT_BYTES)
    elif len(salt) != PBKDF2_SALT_BYTES:
        raise ValueError(f"Salt must be {PBKDF2_SALT_BYTES} bytes")

    derived_key = hashlib.pbkdf2_hmac(
        PBKDF2_HASH_NAME,
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
        dklen=PBKDF2_KEY_LENGTH,
    )
    return (
        f"pbkdf2_{PBKDF2_HASH_NAME}${PBKDF2_ITERATIONS}$"
        f"{salt.hex()}${derived_key.hex()}"
    )


def verify_password(password: str, encoded_hash: str) -> bool:
    """Verifica password contra hash PBKDF2 (constant-time comparison).

    Args:
        password: contraseña en plaintext (UTF-8).
        encoded_hash: hash producido por `hash_password()`.

    Returns:
        True si match, False si mismatch o hash mal-formado.
    """
    if not password or not encoded_hash:
        return False
    try:
        algo, iterations_s, salt_hex, hash_hex = encoded_hash.split("$")
        if algo != f"pbkdf2_{PBKDF2_HASH_NAME}":
            return False
        iterations = int(iterations_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        derived_key = hashlib.pbkdf2_hmac(
            PBKDF2_HASH_NAME,
            password.encode("utf-8"),
            salt,
            iterations,
            dklen=len(expected),
        )
        # Constant-time comparison (resistant to timing attacks)
        return hmac.compare_digest(derived_key, expected)
    except (ValueError, AttributeError) as exc:
        logger.warning(f"verify_password: malformed hash | {type(exc).__name__}")
        return False


# ════════════════════════════════════════════════════════════════════
# Auth backend abstraction
# ════════════════════════════════════════════════════════════════════


class AuthBackend(ABC):
    """Interfaz abstracta para backends de autenticación clínica.

    Cada backend implementa:
        - verify(username, password) → user_id (None si invalid)
        - get_user(user_id) → dict con id/username/role/email
        - create_user(username, password, role, email) → user_id
    """

    backend_name: str = "abstract"

    @abstractmethod
    def verify(self, username: str, password: str) -> int | None:
        """Verifica credenciales. Retorna user_id si valid, None si invalid."""
        raise NotImplementedError

    @abstractmethod
    def get_user(self, user_id: int) -> dict | None:
        """Obtiene metadata del usuario por id. Retorna None si no existe."""
        raise NotImplementedError

    @abstractmethod
    def create_user(
        self,
        *,
        username: str,
        password: str,
        role: str = "clinician",
        email: str = "",
    ) -> int:
        """Crea nuevo usuario. Retorna user_id. Lanza ValueError si duplicate."""
        raise NotImplementedError

    def has_scope(self, user_role: str, required_scope: str) -> bool:
        """Mapping role → scopes (default ABAC: clinician puede leer PHI;
        admin todo; auditor solo audit:read; viewer solo basic).

        Override en subclases para mappings federados (e.g., OAuth claims).
        """
        role_to_scopes = {
            "admin": {"phi:read", "phi:write", "audit:read", "audit:write"},
            "clinician": {"phi:read", "phi:write", "audit:read"},
            "auditor": {"audit:read"},
            "viewer": {"audit:read"},
        }
        scopes = role_to_scopes.get(user_role, set())
        return required_scope in scopes


class LocalPbkdf2Backend(AuthBackend):
    """Backend local con PBKDF2-SHA256 (stdlib-only).

    Usuarios persisten en `clinical_users` SQLite table. No requiere
    dependencias externas. Apropiado para deployments self-hosted
    pequeños-medianos (single-tenant, single-org).

    Para deployments multi-tenant o con SSO corporativo, swap a
    Auth0Backend o KeycloakBackend (placeholder por ahora).
    """

    backend_name = "local_pbkdf2"

    def verify(self, username: str, password: str) -> int | None:
        if not username or not password:
            return None
        from prostanet.shared.auth_db import get_user_by_username
        user = get_user_by_username(username)
        if not user:
            # Constant-time: hash a dummy password to prevent timing attacks
            # that could enumerate valid usernames.
            verify_password(
                password,
                "pbkdf2_sha256$600000$"
                + "00" * PBKDF2_SALT_BYTES + "$"
                + "00" * PBKDF2_KEY_LENGTH,
            )
            return None
        if not user.get("password_hash"):
            return None
        if verify_password(password, user["password_hash"]):
            return int(user["id"])
        return None

    def get_user(self, user_id: int) -> dict | None:
        from prostanet.shared.auth_db import get_user_by_id
        return get_user_by_id(user_id)

    def create_user(
        self,
        *,
        username: str,
        password: str,
        role: str = "clinician",
        email: str = "",
    ) -> int:
        if not username or not password:
            raise ValueError("username and password required")
        if role not in {"admin", "clinician", "auditor", "viewer"}:
            raise ValueError(f"role must be one of admin/clinician/auditor/viewer, got {role!r}")
        from prostanet.shared.auth_db import create_user_record
        password_hash = hash_password(password)
        return create_user_record(
            username=username,
            password_hash=password_hash,
            role=role,
            email=email,
        )


class OidcBackend(AuthBackend):
    """Backend OIDC provider-agnostic (Tier 7 G1.6).

    Funciona con CUALQUIER IDP OIDC-compliant — Keycloak, Auth0,
    Google Workspace, Okta, Microsoft Azure AD/Entra ID, etc. — vía
    OAuth 2.0 Authorization Code Flow + PKCE + userinfo endpoint.

    Diseño:
      - `verify(username, password)` NO se usa con OIDC (auth via redirect).
        Las verificaciones de OIDC ocurren en el callback handler que
        llama directamente a `verify_userinfo_and_provision()`.
      - `get_user(user_id)` reusa `auth_db.get_user_by_id` (cacheado en
        `clinical_users` table tras JIT provisioning).
      - `create_user` deshabilitado (los users se crean automáticamente
        en el callback flow vía `verify_userinfo_and_provision`).

    Configuración via env vars (ver oidc_client.OidcConfig.from_env):
      PROSTANET_OIDC_ISSUER, _CLIENT_ID, _CLIENT_SECRET,
      _REDIRECT_URI, _SCOPE, _DEFAULT_ROLE.

    Habilitación: `PROSTANET_AUTH_BACKEND=oidc`.

    Cuando se quiere _scope-specific config_ (e.g., Keycloak vs Auth0
    necesitan diferentes claim mappings), basta subclasear OidcBackend
    y override `_role_from_userinfo` o `derive_username_from_userinfo`.
    """

    backend_name = "oidc"

    def verify(self, username: str, password: str) -> int | None:
        """OIDC NO usa verify(user, pass) — auth ocurre via Authorization
        Code Flow. Los endpoints OIDC handlers llaman directamente a
        `verify_userinfo_and_provision()` desde el callback.

        Retorna None siempre (interfaz mantenida por backward-compat con
        `AuthBackend` ABC; no debería invocarse en producción).
        """
        logger.warning(
            "OidcBackend.verify(username, password) called — OIDC uses "
            "redirect-based flow, not direct verify. Use "
            "verify_userinfo_and_provision instead."
        )
        return None

    def get_user(self, user_id: int) -> dict | None:
        """Lookup user from clinical_users (cached desde JIT provision)."""
        from prostanet.shared.auth_db import get_user_by_id
        return get_user_by_id(user_id)

    def create_user(
        self,
        *,
        username: str,
        password: str,
        role: str = "clinician",
        email: str = "",
    ) -> int:
        """OIDC users se crean automáticamente via JIT en
        `verify_userinfo_and_provision`. Esta función NO debe usarse
        para OIDC users (sin password).

        Si necesitas crear un OIDC user offline (admin pre-provision),
        usa `auth_db.create_user_record` directamente con
        `password_hash=""` + `backend="oidc"` + `external_id=<issuer>|<sub>`.
        """
        raise NotImplementedError(
            "OidcBackend does not support direct create_user. "
            "Users are auto-provisioned on first OIDC login (JIT). "
            "For pre-provisioning, use auth_db.create_user_record directly."
        )

    def verify_userinfo_and_provision(
        self,
        userinfo: dict,
        issuer: str,
        *,
        default_role: str = "clinician",
    ) -> int:
        """Verifica userinfo OIDC + crea/encuentra clinical_users record.

        Llamado desde `/api/auth/oidc/callback` después de exitoso token
        exchange + userinfo fetch. JIT provisioning: si el user no existe
        en clinical_users (lookup por external_id), se crea.

        Args:
            userinfo: claims dict desde IDP userinfo endpoint
            issuer: URL del IDP (para componer external_id)
            default_role: role asignado a JIT users (default 'clinician')

        Returns:
            user_id de clinical_users (existente o recién creado).

        Raises:
            ValueError si userinfo missing 'sub' claim.
        """
        from prostanet.shared.auth_db import (
            create_user_record, _row_to_dict,
        )
        try:
            from tracking_db import _connect
        except ImportError:
            raise RuntimeError("tracking_db not available")

        from prostanet.shared.oidc_client import (
            derive_username_from_userinfo, derive_external_id_from_userinfo,
        )

        external_id = derive_external_id_from_userinfo(userinfo, issuer)
        if not external_id:
            raise ValueError("OIDC userinfo missing 'sub' claim")

        # Lookup by external_id
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM clinical_users "
                "WHERE external_id = ? AND is_active = 1",
                (external_id,),
            )
            existing = _row_to_dict(cur.fetchone())
        finally:
            try:
                conn.close()
            except Exception:
                pass

        if existing:
            return int(existing["id"])

        # JIT provisioning
        username = derive_username_from_userinfo(userinfo)
        email = str(userinfo.get("email", ""))
        role = self._role_from_userinfo(userinfo, default=default_role)

        # Defensive: username collisions when two different OIDC subs
        # produce same preferred_username — append suffix from sub
        sub_short = str(userinfo.get("sub", ""))[-8:]
        candidate_username = username
        attempts = 0
        while True:
            try:
                user_id = create_user_record(
                    username=candidate_username,
                    password_hash="",  # OIDC users have no local password
                    role=role,
                    email=email,
                    backend="oidc",
                    external_id=external_id,
                )
                logger.info(
                    f"OIDC JIT provision | username={candidate_username} | "
                    f"role={role} | external_id={external_id[:60]}..."
                )
                return user_id
            except ValueError as exc:
                if "already exists" not in str(exc) or attempts >= 5:
                    raise
                attempts += 1
                candidate_username = f"{username}_{sub_short}_{attempts}"

    def _role_from_userinfo(self, userinfo: dict, *, default: str) -> str:
        """Extrae role desde claims OIDC (override en subclass para
        provider-specific claim mappings).

        Sprint 7.B: lookup en claims COMUNES + claims provider-specific
        (Keycloak realm_access.roles, Auth0 https://prostanet/roles).

        Roles válidos alineados con api_auth.CLINICIAN_ROLES + ADMIN_ROLES
        (Sprint 6 middleware) — garantiza que role asignado vía OIDC sea
        reconocido por los decorators @require_clinician/@require_admin.
        """
        # Sprint 7.B: mantener sincronía con prostanet/shared/api_auth.py
        # CLINICIAN_ROLES = {clinician, admin, researcher, physician}
        # ADMIN_ROLES = {admin}
        valid_roles = {
            "admin", "clinician", "researcher", "physician",
            "auditor", "viewer",
        }
        candidates: list[str] = []

        # Standard OIDC claims
        for key in ("roles", "role", "groups"):
            v = userinfo.get(key)
            if isinstance(v, list):
                candidates.extend(str(x).lower() for x in v)
            elif isinstance(v, str):
                candidates.append(v.lower())

        # Sprint 7.B: Keycloak realm_access.roles
        realm_access = userinfo.get("realm_access") or {}
        if isinstance(realm_access, dict):
            rroles = realm_access.get("roles") or []
            if isinstance(rroles, list):
                candidates.extend(str(x).lower() for x in rroles)

        # Sprint 7.B: Keycloak resource_access.<client_id>.roles
        resource_access = userinfo.get("resource_access") or {}
        if isinstance(resource_access, dict):
            for client_roles in resource_access.values():
                if isinstance(client_roles, dict):
                    cr = client_roles.get("roles") or []
                    if isinstance(cr, list):
                        candidates.extend(str(x).lower() for x in cr)

        # Sprint 7.B: Auth0 custom namespaced claims
        # (configurar en Auth0 Action: api.idToken.setCustomClaim("https://prostanet/roles", roles))
        for claim_key in userinfo.keys():
            if "/roles" in str(claim_key) or "/role" in str(claim_key):
                v = userinfo[claim_key]
                if isinstance(v, list):
                    candidates.extend(str(x).lower() for x in v)
                elif isinstance(v, str):
                    candidates.append(v.lower())

        # Match priority: admin > physician > clinician > researcher > auditor > viewer
        priority = ["admin", "physician", "clinician", "researcher", "auditor", "viewer"]
        for p in priority:
            if p in candidates and p in valid_roles:
                return p
        return default


# Backward-compat aliases (los nombres viejos siguen disponibles, pero
# ahora todos apuntan al mismo OidcBackend con JIT provisioning).
# Si en el futuro se quieren provider-specific subclases (e.g., para
# claim mappings distintos), basta subclasear OidcBackend.
class Auth0Backend(OidcBackend):
    """OIDC backend con default config para Auth0 SaaS.

    Usa misma implementación que OidcBackend; nombre separado solo para
    log clarity + permite override de claim mappings específicos de
    Auth0 (e.g., custom namespaced claims).
    """
    backend_name = "auth0"


class KeycloakBackend(OidcBackend):
    """OIDC backend con default config para Keycloak self-hosted."""
    backend_name = "keycloak"

    def _role_from_userinfo(self, userinfo: dict, *, default: str) -> str:
        """Keycloak emite roles en `realm_access.roles` o
        `resource_access.<client_id>.roles`."""
        valid_roles = {"admin", "clinician", "auditor", "viewer"}
        # Keycloak realm roles
        realm_access = userinfo.get("realm_access") or {}
        if isinstance(realm_access, dict):
            for r in realm_access.get("roles") or []:
                if str(r).lower() in valid_roles:
                    return str(r).lower()
        # Fallback to standard claims
        return super()._role_from_userinfo(userinfo, default=default)


class OAuthGoogleBackend(OidcBackend):
    """OIDC backend con default config para Google Workspace OAuth.

    Google emite hd (hosted domain) en lugar de roles formales — la
    asignación de role queda en default (PROSTANET_OIDC_DEFAULT_ROLE).
    Para role-based en Google, usar Google Groups + custom claim mapping.
    """
    backend_name = "oauth_google"


# ════════════════════════════════════════════════════════════════════
# Backend registry + selector
# ════════════════════════════════════════════════════════════════════


AUTH_BACKEND_REGISTRY: dict[str, type[AuthBackend]] = {
    "local": LocalPbkdf2Backend,
    "local_pbkdf2": LocalPbkdf2Backend,
    "oidc": OidcBackend,                  # Generic OIDC (Tier 7 G1.6)
    "auth0": Auth0Backend,                # OIDC with Auth0 defaults
    "keycloak": KeycloakBackend,          # OIDC with Keycloak realm role mapping
    "oauth_google": OAuthGoogleBackend,   # OIDC for Google Workspace
}


_BACKEND_INSTANCE: AuthBackend | None = None


def get_auth_backend() -> AuthBackend:
    """Retorna el backend singleton actual según `PROSTANET_AUTH_BACKEND` env.

    Default: `local` (LocalPbkdf2Backend). Cacheado entre llamadas.
    """
    global _BACKEND_INSTANCE
    if _BACKEND_INSTANCE is not None:
        return _BACKEND_INSTANCE
    backend_name = os.environ.get("PROSTANET_AUTH_BACKEND", "local").lower()
    backend_cls = AUTH_BACKEND_REGISTRY.get(backend_name)
    if backend_cls is None:
        logger.warning(
            f"Unknown PROSTANET_AUTH_BACKEND={backend_name!r}, "
            "falling back to LocalPbkdf2Backend"
        )
        backend_cls = LocalPbkdf2Backend
    _BACKEND_INSTANCE = backend_cls()
    logger.info(f"Auth backend initialized: {_BACKEND_INSTANCE.backend_name}")
    return _BACKEND_INSTANCE


def reset_auth_backend_for_tests() -> None:
    """Reset singleton backend (test-only)."""
    global _BACKEND_INSTANCE
    _BACKEND_INSTANCE = None


# ════════════════════════════════════════════════════════════════════
# Session helpers (Flask session-based, signed cookie)
# ════════════════════════════════════════════════════════════════════


SESSION_USER_ID_KEY = "_clinical_user_id"
SESSION_LOGIN_TIME_KEY = "_clinical_login_time"
SESSION_BACKEND_NAME_KEY = "_clinical_backend"
# Faubot 2026-04-25 (XXXVII) — Tier 7 G4: refresh token storage
SESSION_REFRESH_TOKEN_KEY = "_clinical_refresh_token"
SESSION_ACCESS_TOKEN_KEY = "_clinical_access_token"
SESSION_TOKEN_EXPIRES_AT_KEY = "_clinical_token_expires_at"
SESSION_REFRESH_COUNT_KEY = "_clinical_refresh_count"
SESSION_LAST_REFRESH_AT_KEY = "_clinical_last_refresh_at"
# Faubot 2026-04-25 (XXXIX) — Tier 7 G7: idle vs absolute timeout split
SESSION_LAST_ACTIVITY_KEY = "_clinical_last_activity"
SESSION_TOUCH_COUNT_KEY = "_clinical_touch_count"

# ─── Timeout configuration ────────────────────────────────────────────
# Two-tier session timeout (Tier 7 G7):
#   - ABSOLUTE: hard cap from login_time (cannot be reset by activity)
#   - IDLE:     sliding window from last_activity (reset on user actions)
# Session is valid IFF both predicates hold.
#
# Backward compat: PROSTANET_CLINICAL_SESSION_TIMEOUT_SEC (legacy, default 8h)
# is still honored as the ABSOLUTE timeout. The new canonical env var is
# PROSTANET_CLINICAL_SESSION_ABSOLUTE_TIMEOUT_SEC (preferred when set).
# IDLE timeout has its own env var with default 30min (clinical workstation
# unattended risk: HHS HIPAA Security Rule §164.312(a)(2)(iii) recommends
# automatic logoff for ePHI access; 30min aligns with NIST SP 800-66 Rev. 2).

_LEGACY_TIMEOUT_ENV = os.environ.get(
    "PROSTANET_CLINICAL_SESSION_TIMEOUT_SEC", str(8 * 3600),  # 8h default
)
SESSION_ABSOLUTE_TIMEOUT_SECONDS = int(os.environ.get(
    "PROSTANET_CLINICAL_SESSION_ABSOLUTE_TIMEOUT_SEC", _LEGACY_TIMEOUT_ENV,
))
SESSION_IDLE_TIMEOUT_SECONDS = int(os.environ.get(
    "PROSTANET_CLINICAL_SESSION_IDLE_TIMEOUT_SEC", str(30 * 60),  # 30min default
))
# Backward-compat alias: code that imported SESSION_TIMEOUT_SECONDS pre-G7
# continues to work, mapping to the absolute timeout (the historical semantics).
SESSION_TIMEOUT_SECONDS = SESSION_ABSOLUTE_TIMEOUT_SECONDS


def session_login(session: dict, user_id: int, backend_name: str) -> None:
    """Marca la sesión como autenticada con user_id + timestamp + backend.

    Compatible con dict (tests aislados) y Flask SecureCookieSession
    (que tiene atributo `permanent`).

    Faubot 2026-04-25 (XXXIX) — Tier 7 G7: además del login_time (que ancla
    el ABSOLUTE timeout), inicializa last_activity = login_time para que el
    IDLE timeout empiece a contar desde el primer momento.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    session[SESSION_USER_ID_KEY] = int(user_id)
    session[SESSION_LOGIN_TIME_KEY] = now_iso
    session[SESSION_BACKEND_NAME_KEY] = backend_name
    # G7: idle timeout sliding-window anchor
    session[SESSION_LAST_ACTIVITY_KEY] = now_iso
    session[SESSION_TOUCH_COUNT_KEY] = 0
    # Flask sessions tienen .permanent; dicts no — graceful skip.
    try:
        session.permanent = True
    except (AttributeError, TypeError):
        pass


# ════════════════════════════════════════════════════════════════════
# Faubot 2026-04-25 (XXXIX) — Tier 7 G7: idle activity tracking
# ════════════════════════════════════════════════════════════════════


def session_touch_activity(session: dict) -> int:
    """Resetea el sliding-window IDLE: marca last_activity = now().

    Llamado por:
      - require_clinical_session(passive=False) tras un auth check OK
      - /api/auth/touch endpoint en respuesta a interacción del usuario
        (click/keydown/scroll, debounced en JS)

    NO llamado por endpoints "pasivos" (whoami, session-status, refresh)
    para que el polling del badge no extienda artificialmente la sesión.

    Returns:
        Nuevo touch_count (int >= 1) — útil para audit trail granular.
    """
    if not session.get(SESSION_USER_ID_KEY):
        return 0
    session[SESSION_LAST_ACTIVITY_KEY] = datetime.now(timezone.utc).isoformat()
    count = int(session.get(SESSION_TOUCH_COUNT_KEY, 0)) + 1
    session[SESSION_TOUCH_COUNT_KEY] = count
    return count


def _parse_session_iso(value: Any) -> datetime | None:
    """Parse ISO timestamp from session, returning timezone-aware UTC datetime
    or None if missing/malformed."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def session_absolute_seconds_remaining(session: dict) -> int:
    """Faubot G7 — segundos restantes hasta el ABSOLUTE timeout.

    Returns 0 si la sesión no tiene login_time o ya excedió el cap.
    """
    login_dt = _parse_session_iso(session.get(SESSION_LOGIN_TIME_KEY))
    if login_dt is None:
        return 0
    elapsed = (datetime.now(timezone.utc) - login_dt).total_seconds()
    return max(0, int(SESSION_ABSOLUTE_TIMEOUT_SECONDS - elapsed))


def session_idle_seconds_remaining(session: dict) -> int:
    """Faubot G7 — segundos restantes hasta el IDLE timeout (sliding window).

    Returns 0 si la sesión no tiene last_activity o ya excedió el window.
    Si por alguna razón last_activity falta pero login_time existe, usa
    login_time como fallback (sesión legacy pre-G7 sin actividad registrada).
    """
    last_dt = _parse_session_iso(session.get(SESSION_LAST_ACTIVITY_KEY))
    if last_dt is None:
        # Fallback: pre-G7 sessions stored only login_time
        last_dt = _parse_session_iso(session.get(SESSION_LOGIN_TIME_KEY))
    if last_dt is None:
        return 0
    elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
    return max(0, int(SESSION_IDLE_TIMEOUT_SECONDS - elapsed))


# Sentinel reasons for session_expiry_reason (string constants for stable
# audit log + UI redirect query params).
SESSION_REASON_VALID = "valid"
SESSION_REASON_UNAUTHENTICATED = "unauthenticated"
SESSION_REASON_EXPIRED_IDLE = "expired_idle"
SESSION_REASON_EXPIRED_ABSOLUTE = "expired_absolute"
SESSION_REASON_MALFORMED = "malformed"

# Faubot 2026-04-25 (XL) — Tier 7 G8: redirect query reason → canonical sentinel
# whitelist. Login UI / clientes JS reciben "idle" o "absolute" en
# `?error=session_expired&reason=*`; aquí los normalizamos a la sentinel
# canónica para que el template Jinja pueda hacer el render contextual sin
# correr lógica de string concatenation. Cualquier valor fuera del
# whitelist → SESSION_REASON_UNAUTHENTICATED (default seguro: "sesión
# expiró" genérico).
_REDIRECT_REASON_WHITELIST: dict[str, str] = {
    "idle": SESSION_REASON_EXPIRED_IDLE,
    "absolute": SESSION_REASON_EXPIRED_ABSOLUTE,
    SESSION_REASON_EXPIRED_IDLE: SESSION_REASON_EXPIRED_IDLE,
    SESSION_REASON_EXPIRED_ABSOLUTE: SESSION_REASON_EXPIRED_ABSOLUTE,
}


def decode_session_expiry_reason(qparam: Any) -> str:
    """Faubot G8 — Convierte el query param `reason=` del redirect post-expiry
    en su sentinel canónico (`SESSION_REASON_EXPIRED_IDLE` /
    `_EXPIRED_ABSOLUTE`).

    Sanitization defensiva:
      - Strings vacíos / None / no-string → SESSION_REASON_UNAUTHENTICATED
        (= mensaje genérico "sesión expiró")
      - Cualquier valor fuera del whitelist → SESSION_REASON_UNAUTHENTICATED
        (rejecta XSS / scope bleed)
      - Case-insensitive (`IDLE` y `idle` mapean igual)

    Returns:
        Sentinel canónico de SESSION_REASON_*. Nunca retorna el qparam
        crudo (whitelist enforcement).
    """
    if not isinstance(qparam, str):
        return SESSION_REASON_UNAUTHENTICATED
    normalized = qparam.strip().lower()
    if not normalized:
        return SESSION_REASON_UNAUTHENTICATED
    return _REDIRECT_REASON_WHITELIST.get(normalized, SESSION_REASON_UNAUTHENTICATED)


def session_expiry_reason(session: dict) -> str:
    """Faubot G7 — diagnóstico explícito del estado de la sesión.

    Returns:
      - SESSION_REASON_VALID:           sesión válida (ambos timeouts OK)
      - SESSION_REASON_UNAUTHENTICATED: no hay user_id en sesión
      - SESSION_REASON_MALFORMED:       falta login_time o es inválido
      - SESSION_REASON_EXPIRED_ABSOLUTE: superó el hard cap (re-login obligatorio)
      - SESSION_REASON_EXPIRED_IDLE:    excedió el sliding window de idle

    Prioriza ABSOLUTE sobre IDLE cuando ambos expiran simultáneamente — el
    motivo "más restrictivo" gana, porque ABSOLUTE no se puede extender via
    /api/auth/touch (re-login obligatorio).
    """
    if not session.get(SESSION_USER_ID_KEY):
        return SESSION_REASON_UNAUTHENTICATED
    login_dt = _parse_session_iso(session.get(SESSION_LOGIN_TIME_KEY))
    if login_dt is None:
        return SESSION_REASON_MALFORMED
    now = datetime.now(timezone.utc)
    if (now - login_dt).total_seconds() >= SESSION_ABSOLUTE_TIMEOUT_SECONDS:
        return SESSION_REASON_EXPIRED_ABSOLUTE
    last_dt = _parse_session_iso(session.get(SESSION_LAST_ACTIVITY_KEY)) or login_dt
    if (now - last_dt).total_seconds() >= SESSION_IDLE_TIMEOUT_SECONDS:
        return SESSION_REASON_EXPIRED_IDLE
    return SESSION_REASON_VALID


def session_store_oidc_tokens(
    session: dict,
    *,
    access_token: str,
    refresh_token: str,
    expires_in: int,
) -> None:
    """Faubot 2026-04-25 (XXXVII) — Tier 7 G4: almacena tokens OIDC en sesión.

    Llamado tras token exchange exitoso (authorization_code flow) o tras
    refresh exitoso. Persiste:
      - access_token: para subsequent userinfo calls
      - refresh_token: para auto-renew sin re-login
      - expires_at: timestamp ISO del expiry calculado (now + expires_in)

    Las claves usan prefijo `_clinical_` para no colisionar con otras
    sesiones del app.
    """
    if access_token:
        session[SESSION_ACCESS_TOKEN_KEY] = access_token
    if refresh_token:
        session[SESSION_REFRESH_TOKEN_KEY] = refresh_token
    if expires_in and expires_in > 0:
        from datetime import timedelta
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        session[SESSION_TOKEN_EXPIRES_AT_KEY] = expires_at.isoformat()


def session_increment_refresh_count(session: dict) -> int:
    """Faubot 2026-04-25 (XXXVII) — Tier 7 G4: incrementa contador de refreshes
    y actualiza timestamp del último refresh. Retorna nuevo count.

    Útil para audit trail (¿cuántas veces se refrescó esta sesión?).
    """
    count = int(session.get(SESSION_REFRESH_COUNT_KEY, 0)) + 1
    session[SESSION_REFRESH_COUNT_KEY] = count
    session[SESSION_LAST_REFRESH_AT_KEY] = datetime.now(timezone.utc).isoformat()
    return count


def session_get_refresh_token(session: dict) -> str:
    """Retorna refresh_token almacenado, '' si no existe."""
    return str(session.get(SESSION_REFRESH_TOKEN_KEY, ""))


def session_get_access_token(session: dict) -> str:
    """Retorna access_token almacenado, '' si no existe."""
    return str(session.get(SESSION_ACCESS_TOKEN_KEY, ""))


def session_token_seconds_until_expiry(session: dict) -> int:
    """Retorna segundos hasta expiry del access_token actual.

    Returns:
      > 0 si token aún válido (segundos restantes)
      <= 0 si token expirado o sin expires_at almacenado
    """
    iso = session.get(SESSION_TOKEN_EXPIRES_AT_KEY, "")
    if not iso:
        return 0
    try:
        expires_at = datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return 0
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    delta = (expires_at - datetime.now(timezone.utc)).total_seconds()
    return max(0, int(delta))


def session_logout(session: dict) -> None:
    """Limpia los marcadores de sesión clínica (logout).

    Faubot 2026-04-25 (XXXVII) — Tier 7 G4: también limpia tokens OIDC
    + refresh count. Importante para no dejar tokens persistidos tras
    logout (security: aunque la sesión esté firmada por Flask, no debe
    contener tokens activos post-logout).

    Faubot 2026-04-25 (XXXIX) — Tier 7 G7: limpia también
    last_activity + touch_count.
    """
    for k in (
        SESSION_USER_ID_KEY, SESSION_LOGIN_TIME_KEY, SESSION_BACKEND_NAME_KEY,
        SESSION_REFRESH_TOKEN_KEY, SESSION_ACCESS_TOKEN_KEY,
        SESSION_TOKEN_EXPIRES_AT_KEY, SESSION_REFRESH_COUNT_KEY,
        SESSION_LAST_REFRESH_AT_KEY,
        # G7 (XXXIX)
        SESSION_LAST_ACTIVITY_KEY, SESSION_TOUCH_COUNT_KEY,
    ):
        session.pop(k, None)


def session_is_valid(session: dict) -> bool:
    """Verifica si la sesión tiene user_id válido + no ha expirado.

    Faubot 2026-04-25 (XXXIX) — Tier 7 G7: ahora se evalúan DOS timeouts
    simultáneos (ABSOLUTE + IDLE). La sesión es válida solo si ambos
    predicados pasan. Delega a `session_expiry_reason` para mantener una
    única fuente de verdad y permitir auditoría granular del motivo de
    expiración.
    """
    return session_expiry_reason(session) == SESSION_REASON_VALID


def session_user_id(session: dict) -> int | None:
    """Retorna user_id si sesión es válida, None si no."""
    if not session_is_valid(session):
        return None
    try:
        return int(session.get(SESSION_USER_ID_KEY))
    except (TypeError, ValueError):
        return None
