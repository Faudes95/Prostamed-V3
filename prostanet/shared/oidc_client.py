"""oidc_client.py — FAUBOT 2026-04-25 (XXIX) — Tier 7 G1.6.

Cliente OIDC (OpenID Connect) **provider-agnostic** que funciona con:
  - Keycloak (self-hosted)
  - Auth0 (SaaS)
  - OAuth Google (Google Workspace)
  - Okta
  - Microsoft Azure AD / Entra ID
  - Cualquier IDP OIDC-compliant

Implementa OAuth 2.0 Authorization Code Flow con PKCE (RFC 7636) +
state CSRF protection + nonce replay protection + userinfo endpoint
para validación de identidad (NO requiere JWT signature parsing —
delega validación al IDP via HTTPS llamando userinfo).

Diseño:
  - **stdlib-only** (urllib + secrets + hashlib + base64) — sin
    dependencia de PyJWT/python-jose/authlib (minimiza supply-chain).
  - Configuración via env vars (ver `OidcConfig.from_env`):
      PROSTANET_OIDC_ISSUER         (e.g., https://accounts.google.com)
      PROSTANET_OIDC_CLIENT_ID
      PROSTANET_OIDC_CLIENT_SECRET  (opcional para PKCE-only flows)
      PROSTANET_OIDC_REDIRECT_URI
      PROSTANET_OIDC_SCOPE          (default "openid email profile")
      PROSTANET_OIDC_DEFAULT_ROLE   (default "clinician" para JIT users)
  - Discovery automático via `.well-known/openid-configuration`.
  - Cache de discovery doc (5 min TTL) para no hit IDP en cada login.

Aporte a auditabilidad:
  - **VERSIÓN:** issuer URL queda registrado en clinical_users.external_id
    para trazar qué IDP emitió el sub claim.
  - **DATOS:** email + name capturados desde userinfo endpoint, no PHI.
  - **POR QUÉ:** rejections (state mismatch, code exchange fail) loguean
    razón específica con trace_id.

Activación:
  - Default: NO activo. Set PROSTANET_AUTH_BACKEND=oidc para habilitar.
  - Backward-compat: LocalPbkdf2Backend sigue siendo default.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════
# Configuration (env-driven)
# ════════════════════════════════════════════════════════════════════


@dataclass
class OidcConfig:
    """Configuración del OIDC client.

    Provider-agnostic: el mismo struct sirve para Keycloak/Auth0/Google/etc.
    """
    issuer: str                                          # IDP base URL
    client_id: str
    client_secret: str = ""                              # Optional para PKCE
    redirect_uri: str = "http://localhost:8080/api/auth/oidc/callback"
    scope: str = "openid email profile"
    default_role: str = "clinician"                      # Role for JIT users
    discovery_url: str = ""                              # Override autodiscovery
    timeout_sec: int = 10
    verify_id_token: bool = True                         # G1.7: prefer JWT verify
    time_skew_sec: int = 30                              # JWT exp/iat skew tolerance
    # HTTP timeouts in tests/mocks may be smaller

    @classmethod
    def from_env(cls) -> OidcConfig:
        """Construye OidcConfig desde env vars. Raises si faltantes obligatorios."""
        issuer = os.environ.get("PROSTANET_OIDC_ISSUER", "").rstrip("/")
        client_id = os.environ.get("PROSTANET_OIDC_CLIENT_ID", "")
        if not issuer or not client_id:
            raise ValueError(
                "OIDC config incomplete: set PROSTANET_OIDC_ISSUER + "
                "PROSTANET_OIDC_CLIENT_ID env vars."
            )
        verify_jwt_env = os.environ.get(
            "PROSTANET_OIDC_VERIFY_ID_TOKEN", "true",
        ).lower() in {"true", "yes", "1"}
        return cls(
            issuer=issuer,
            client_id=client_id,
            client_secret=os.environ.get("PROSTANET_OIDC_CLIENT_SECRET", ""),
            redirect_uri=os.environ.get(
                "PROSTANET_OIDC_REDIRECT_URI",
                "http://localhost:8080/api/auth/oidc/callback",
            ),
            scope=os.environ.get(
                "PROSTANET_OIDC_SCOPE", "openid email profile",
            ),
            default_role=os.environ.get(
                "PROSTANET_OIDC_DEFAULT_ROLE", "clinician",
            ),
            discovery_url=os.environ.get("PROSTANET_OIDC_DISCOVERY_URL", ""),
            timeout_sec=int(os.environ.get("PROSTANET_OIDC_TIMEOUT_SEC", "10")),
            verify_id_token=verify_jwt_env,
            time_skew_sec=int(os.environ.get(
                "PROSTANET_OIDC_TIME_SKEW_SEC", "30",
            )),
        )


# ════════════════════════════════════════════════════════════════════
# PKCE helpers (RFC 7636)
# ════════════════════════════════════════════════════════════════════


def generate_pkce_pair() -> tuple[str, str]:
    """Genera par (code_verifier, code_challenge) para PKCE.

    code_verifier: 43-128 chars [A-Z a-z 0-9 - . _ ~] (RFC 7636 §4.1).
    code_challenge: BASE64URL-NOPAD(SHA256(code_verifier)) (RFC 7636 §4.2).

    Returns:
        (verifier, challenge) — ambos URL-safe strings.
    """
    # 43 bytes Base64-URL = 64 chars sin padding (cumple 43-128 limit)
    verifier = base64.urlsafe_b64encode(
        secrets.token_bytes(48),
    ).decode("ascii").rstrip("=")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def generate_state_token(num_bytes: int = 32) -> str:
    """Genera state token URL-safe para CSRF protection en OAuth flow."""
    return secrets.token_urlsafe(num_bytes)


def generate_nonce(num_bytes: int = 16) -> str:
    """Genera nonce URL-safe para replay protection en OIDC ID token."""
    return secrets.token_urlsafe(num_bytes)


# ════════════════════════════════════════════════════════════════════
# OIDC discovery (cached)
# ════════════════════════════════════════════════════════════════════


_DISCOVERY_CACHE: dict[str, tuple[float, dict]] = {}
_DISCOVERY_TTL_SEC = 300  # 5 minutes


def _discovery_url_for(issuer: str, override: str = "") -> str:
    """Computa URL del discovery doc OIDC."""
    if override:
        return override
    return f"{issuer.rstrip('/')}/.well-known/openid-configuration"


def fetch_discovery_doc(
    config: OidcConfig,
    *,
    force_refresh: bool = False,
) -> dict:
    """Descarga (o reusa cache) el OIDC discovery document.

    Returns:
        dict con keys como 'authorization_endpoint', 'token_endpoint',
        'userinfo_endpoint', 'issuer', 'jwks_uri', etc.

    Raises:
        URLError / ValueError si IDP no alcanzable o doc malformado.
    """
    url = _discovery_url_for(config.issuer, config.discovery_url)
    now = time.time()
    if not force_refresh and url in _DISCOVERY_CACHE:
        ts, doc = _DISCOVERY_CACHE[url]
        if now - ts < _DISCOVERY_TTL_SEC:
            return doc

    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=config.timeout_sec) as resp:
            raw = resp.read().decode("utf-8")
        doc = json.loads(raw)
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"Failed to fetch OIDC discovery doc from {url}: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    if not isinstance(doc, dict):
        raise ValueError(f"OIDC discovery doc is not a JSON object: {type(doc)}")

    _DISCOVERY_CACHE[url] = (now, doc)
    return doc


def reset_discovery_cache() -> None:
    """Limpia cache de discovery (test-only)."""
    _DISCOVERY_CACHE.clear()


# ════════════════════════════════════════════════════════════════════
# Authorization URL builder
# ════════════════════════════════════════════════════════════════════


def build_authorization_url(
    config: OidcConfig,
    *,
    state: str,
    code_challenge: str,
    nonce: str = "",
    discovery: dict | None = None,
) -> str:
    """Construye URL para iniciar Authorization Code Flow con PKCE.

    Args:
        config: OidcConfig
        state: token CSRF (validar al recibir callback)
        code_challenge: PKCE challenge (S256 method)
        nonce: opcional, para replay protection en ID token
        discovery: discovery doc (si None, se descarga)

    Returns:
        URL completa lista para redirect 302.
    """
    if discovery is None:
        discovery = fetch_discovery_doc(config)
    auth_endpoint = discovery.get("authorization_endpoint")
    if not auth_endpoint:
        raise ValueError("OIDC discovery doc missing authorization_endpoint")

    params = {
        "response_type": "code",
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "scope": config.scope,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if nonce:
        params["nonce"] = nonce

    return f"{auth_endpoint}?{urllib.parse.urlencode(params)}"


# ════════════════════════════════════════════════════════════════════
# Token exchange (code → access_token + id_token)
# ════════════════════════════════════════════════════════════════════


@dataclass
class TokenResponse:
    """Respuesta del token endpoint OIDC."""
    access_token: str
    token_type: str = "Bearer"
    id_token: str = ""
    refresh_token: str = ""
    expires_in: int = 0
    scope: str = ""
    raw: dict = field(default_factory=dict)


def exchange_code_for_tokens(
    config: OidcConfig,
    *,
    code: str,
    code_verifier: str,
    discovery: dict | None = None,
) -> TokenResponse:
    """Intercambia el `code` recibido en callback por tokens.

    Hace POST al token_endpoint con grant_type=authorization_code +
    PKCE code_verifier.

    Returns:
        TokenResponse con access_token + id_token.

    Raises:
        ValueError si exchange falla (HTTP error, malformed response).
    """
    if discovery is None:
        discovery = fetch_discovery_doc(config)
    token_endpoint = discovery.get("token_endpoint")
    if not token_endpoint:
        raise ValueError("OIDC discovery doc missing token_endpoint")

    body_params = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": config.redirect_uri,
        "client_id": config.client_id,
        "code_verifier": code_verifier,
    }
    if config.client_secret:
        body_params["client_secret"] = config.client_secret

    body = urllib.parse.urlencode(body_params).encode("utf-8")
    req = urllib.request.Request(
        token_endpoint,
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=config.timeout_sec) as resp:
            raw = resp.read().decode("utf-8")
        data = json.loads(raw)
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"OIDC token exchange failed: {type(exc).__name__}: {exc}"
        ) from exc

    if not isinstance(data, dict) or "access_token" not in data:
        raise ValueError(
            f"OIDC token endpoint returned invalid response: keys={list(data.keys()) if isinstance(data, dict) else type(data)}"
        )

    return TokenResponse(
        access_token=str(data["access_token"]),
        token_type=str(data.get("token_type", "Bearer")),
        id_token=str(data.get("id_token", "")),
        refresh_token=str(data.get("refresh_token", "")),
        expires_in=int(data.get("expires_in", 0)),
        scope=str(data.get("scope", "")),
        raw=data,
    )


# ════════════════════════════════════════════════════════════════════
# Refresh token exchange (Faubot 2026-04-25 XXXVII — Tier 7 G4)
# ════════════════════════════════════════════════════════════════════


def exchange_refresh_token_for_tokens(
    config: OidcConfig,
    *,
    refresh_token: str,
    discovery: dict | None = None,
) -> TokenResponse:
    """Intercambia un refresh_token por un nuevo access_token + (rotated) refresh_token.

    Faubot 2026-04-25 (XXXVII) — Tier 7 G4: implementa OAuth refresh
    token flow estándar (RFC 6749 §6). Permite renovar sesiones long-
    running sin re-login del usuario.

    Hace POST al token_endpoint con grant_type=refresh_token. Algunos
    IDPs (Auth0, Keycloak) rotan el refresh_token (return new one);
    otros (Google) reutilizan el mismo. Esta función propaga ambos casos:
    si el IDP devuelve nuevo refresh_token, usar ese; si no, mantener
    el original (caller decide).

    Args:
        config: OidcConfig con client_id + (opcional) client_secret
        refresh_token: token de refresh emitido en authorization_code flow

    Returns:
        TokenResponse con nuevos access_token + (opcional) refresh_token rotado

    Raises:
        ValueError si refresh falla (token expired, IDP error, malformed)
    """
    if not refresh_token:
        raise ValueError("refresh_token is required")

    if discovery is None:
        discovery = fetch_discovery_doc(config)
    token_endpoint = discovery.get("token_endpoint")
    if not token_endpoint:
        raise ValueError("OIDC discovery doc missing token_endpoint")

    body_params = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": config.client_id,
    }
    if config.client_secret:
        body_params["client_secret"] = config.client_secret
    # Optional: scope can be specified to narrow scope; default uses
    # original scope from previous grant (per RFC 6749 §6).

    body = urllib.parse.urlencode(body_params).encode("utf-8")
    req = urllib.request.Request(
        token_endpoint,
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=config.timeout_sec) as resp:
            raw = resp.read().decode("utf-8")
        data = json.loads(raw)
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"OIDC refresh token exchange failed: {type(exc).__name__}: {exc}"
        ) from exc

    if not isinstance(data, dict) or "access_token" not in data:
        raise ValueError(
            f"OIDC refresh endpoint returned invalid response: "
            f"keys={list(data.keys()) if isinstance(data, dict) else type(data)}"
        )

    # Per RFC 6749 §6: server MAY return a new refresh_token. If it does
    # NOT, caller should keep using the original. We return whatever
    # server provides (empty string if not rotated).
    return TokenResponse(
        access_token=str(data["access_token"]),
        token_type=str(data.get("token_type", "Bearer")),
        id_token=str(data.get("id_token", "")),
        refresh_token=str(data.get("refresh_token", "")),
        expires_in=int(data.get("expires_in", 0)),
        scope=str(data.get("scope", "")),
        raw=data,
    )


# ════════════════════════════════════════════════════════════════════
# Userinfo endpoint (validación de identidad sin JWT signature parsing)
# ════════════════════════════════════════════════════════════════════


def fetch_userinfo(
    config: OidcConfig,
    access_token: str,
    *,
    discovery: dict | None = None,
) -> dict:
    """GET userinfo endpoint con access_token. Devuelve claims del usuario.

    Esta es la ESTRATEGIA DE VALIDACIÓN preferida en G1.6 — al llamar
    userinfo con un access_token válido, el IDP confirma identidad sin
    necesidad de parsear/verificar JWT signature client-side.

    Trade-off: 1 HTTP request extra por login vs evitar dependencia
    `cryptography` para RSA verification. Para healthcare con login
    frequency baja (≤10/día/user), el trade-off es aceptable.

    Returns:
        dict con claims OIDC estándar: sub, email, name, given_name,
        family_name, picture, locale, etc. (depende del scope).

    Raises:
        ValueError si userinfo endpoint rechaza o malformed.
    """
    if discovery is None:
        discovery = fetch_discovery_doc(config)
    userinfo_endpoint = discovery.get("userinfo_endpoint")
    if not userinfo_endpoint:
        raise ValueError("OIDC discovery doc missing userinfo_endpoint")

    req = urllib.request.Request(
        userinfo_endpoint,
        method="GET",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=config.timeout_sec) as resp:
            raw = resp.read().decode("utf-8")
        data = json.loads(raw)
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"OIDC userinfo fetch failed: {type(exc).__name__}: {exc}"
        ) from exc

    if not isinstance(data, dict) or "sub" not in data:
        raise ValueError(
            f"OIDC userinfo response missing 'sub' claim: keys={list(data.keys()) if isinstance(data, dict) else type(data)}"
        )

    return data


# ════════════════════════════════════════════════════════════════════
# JIT user provisioning (first OIDC login)
# ════════════════════════════════════════════════════════════════════


def derive_username_from_userinfo(userinfo: dict) -> str:
    """Deriva username canónico desde claims OIDC.

    Prioridad: preferred_username > email > sub.
    """
    candidates = [
        userinfo.get("preferred_username"),
        userinfo.get("email"),
        userinfo.get("sub"),
    ]
    for c in candidates:
        if c and isinstance(c, str):
            return c.strip()
    return f"oidc_user_{secrets.token_hex(8)}"  # fallback


def derive_external_id_from_userinfo(userinfo: dict, issuer: str) -> str:
    """Deriva external_id estable desde claims OIDC.

    Formato: `<issuer>|<sub>` — único globalmente, estable a través de
    cambios de email/username.
    """
    sub = str(userinfo.get("sub", "")).strip()
    if not sub:
        return ""
    return f"{issuer}|{sub}"


# ════════════════════════════════════════════════════════════════════
# G1.7 — Hybrid claim resolver (JWT verify preferred, userinfo fallback)
# ════════════════════════════════════════════════════════════════════


@dataclass
class ClaimsResolution:
    """Resultado del proceso híbrido JWT-verify-or-userinfo."""
    claims: dict
    method: str          # "jwt_verified" | "userinfo_fallback"
    algorithm: str = ""  # JWT alg si method=jwt_verified
    kid: str = ""        # JWT kid si method=jwt_verified
    jwt_verify_reason: str = ""  # razón si JWT fallback ocurrió


def resolve_claims_with_jwt_or_userinfo(
    config: OidcConfig,
    *,
    id_token: str,
    access_token: str,
    expected_nonce: str = "",
    discovery: dict | None = None,
) -> ClaimsResolution:
    """Estrategia híbrida G1.7: prefiere JWT verify, cae a userinfo si falla.

    Orden de preferencia:
        1. Si `config.verify_id_token=True` AND id_token disponible AND
           cryptography disponible → verify offline (no extra HTTP)
        2. Si JWT verify falla → log warning + cae a userinfo (G1.6 path)
        3. Si verify_id_token=False → directo userinfo (skip JWT entirely)

    Args:
        config: OidcConfig
        id_token: JWT id_token desde token endpoint (puede ser "")
        access_token: access_token para userinfo fallback
        expected_nonce: nonce que enviamos en authorization request
        discovery: discovery doc (si None, se descarga)

    Returns:
        ClaimsResolution con claims + método usado.
    """
    if discovery is None:
        discovery = fetch_discovery_doc(config)

    # Try JWT verification path first (if enabled + token available)
    if config.verify_id_token and id_token:
        try:
            from prostanet.shared.jwt_verifier import (
                verify_id_token, is_cryptography_available,
            )
            if is_cryptography_available():
                jwks_uri = discovery.get("jwks_uri", "")
                result = verify_id_token(
                    id_token,
                    jwks_uri=jwks_uri,
                    expected_issuer=config.issuer,
                    expected_audience=config.client_id,
                    expected_nonce=expected_nonce,
                    time_skew_sec=config.time_skew_sec,
                    timeout_sec=config.timeout_sec,
                )
                if result.valid and result.claims:
                    logger.info(
                        f"OIDC claims via JWT verify (alg={result.algorithm}, "
                        f"kid={result.kid[:20]}) — no userinfo HTTP request"
                    )
                    return ClaimsResolution(
                        claims=result.claims,
                        method="jwt_verified",
                        algorithm=result.algorithm,
                        kid=result.kid,
                    )
                # JWT verify failed → log + fall through to userinfo
                logger.warning(
                    f"OIDC JWT verify failed: {result.reason}. "
                    "Falling back to userinfo endpoint."
                )
                jwt_fail_reason = result.reason
            else:
                jwt_fail_reason = "cryptography package unavailable"
        except Exception as exc:  # pragma: no cover
            logger.warning(
                f"OIDC JWT verify exception: {type(exc).__name__}: {exc}. "
                "Falling back to userinfo."
            )
            jwt_fail_reason = f"jwt_verify_exception: {type(exc).__name__}"
    else:
        jwt_fail_reason = (
            "verify_id_token disabled" if not config.verify_id_token
            else "no id_token in token response"
        )

    # Fallback path: userinfo endpoint
    userinfo = fetch_userinfo(config, access_token, discovery=discovery)
    return ClaimsResolution(
        claims=userinfo,
        method="userinfo_fallback",
        jwt_verify_reason=jwt_fail_reason,
    )
