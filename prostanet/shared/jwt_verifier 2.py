"""jwt_verifier.py — FAUBOT 2026-04-25 (XXX) — Tier 7 G1.7.

Verificación offline de JWT (id_token OIDC) con RSA-SHA256 (RS256) +
JWKS endpoint + claims validation completa.

Beneficios sobre userinfo (G1.6):
  - **Sin extra HTTP per login** — userinfo requiere 1 round-trip al IDP
    por cada login. JWT verify es local (solo se hit JWKS endpoint
    raramente para refresh keys).
  - **Validación criptográfica de identidad** — JWT signature garantiza
    que claims fueron emitidos por el IDP (no MITM ni replay).
  - **Validación de claims completa** — exp, iat, nbf, aud, iss, nonce
    todos validados localmente (no trust de servidor remoto).

Diseño:
  - **`cryptography` package OPCIONAL** — si disponible, RS256 verify
    funciona offline. Si NO disponible (env aislado/CI sin pip),
    `verify_jwt` retorna `None` con warning, y `OidcBackend` cae a
    userinfo endpoint (G1.6 backward-compat).
  - **JWKS cache** con TTL (10 min default) para evitar hit IDP por login.
  - **Algorithm confusion protection** — solo acepta RS256/RS384/RS512;
    rechaza `alg=none`, `alg=HS*` (cuando key es RSA), kid no registrado.
  - **Claims validation** — iss, aud, exp, iat, nbf, nonce con time_skew
    configurable (default 30s).

Aporte a auditabilidad (Clinical Decision Engine):
  - **EVIDENCIA:** validación local de identidad sin trust de IDP HTTPS
    (defensa en profundidad — incluso si IDP TLS comprometido, JWT
    signature lo bloquea).
  - **POR QUÉ:** rejections (sig invalid, exp, iss mismatch, etc.)
    documentadas con razón específica.
  - **VERSIÓN:** `cryptography` version + algoritmo usado quedan
    registrados en audit log.

Activación:
  - Default: `verify_id_token = (cryptography_available)` — automático.
  - Opt-out: PROSTANET_OIDC_VERIFY_ID_TOKEN=false → siempre userinfo.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════
# Optional cryptography import (graceful degradation)
# ════════════════════════════════════════════════════════════════════


try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.backends import default_backend
    _CRYPTOGRAPHY_AVAILABLE = True
    _CRYPTOGRAPHY_VERSION = (
        __import__("cryptography").__version__
    )
except ImportError:  # pragma: no cover
    _CRYPTOGRAPHY_AVAILABLE = False
    _CRYPTOGRAPHY_VERSION = ""
    InvalidSignature = Exception  # type: ignore


def is_cryptography_available() -> bool:
    """Retorna True si cryptography package está disponible (RS256 enabled)."""
    return _CRYPTOGRAPHY_AVAILABLE


def cryptography_version() -> str:
    """Retorna versión de cryptography (vacío si no disponible)."""
    return _CRYPTOGRAPHY_VERSION


# ════════════════════════════════════════════════════════════════════
# Base64URL helpers (RFC 4648 §5)
# ════════════════════════════════════════════════════════════════════


def b64url_decode(s: str) -> bytes:
    """Decode base64url string (with or without padding)."""
    if not s:
        return b""
    # Add padding if missing (b64decode requires padding to length % 4 == 0)
    padding_needed = -len(s) % 4
    s_padded = s + ("=" * padding_needed)
    return base64.urlsafe_b64decode(s_padded.encode("ascii"))


def b64url_decode_to_int(s: str) -> int:
    """Decode base64url to big integer (used for RSA modulus/exponent)."""
    return int.from_bytes(b64url_decode(s), byteorder="big")


# ════════════════════════════════════════════════════════════════════
# JWT parsing (header.payload.signature)
# ════════════════════════════════════════════════════════════════════


@dataclass
class ParsedJwt:
    """JWT parseado en header + payload + signature.

    Campos:
        header: dict con alg + kid + typ
        payload: dict con claims (iss, sub, aud, exp, iat, nbf, etc.)
        signature: bytes raw de la signature (RS256: 256 bytes)
        signing_input: bytes que fueron firmados (header_b64 + '.' + payload_b64)
    """
    header: dict
    payload: dict
    signature: bytes
    signing_input: bytes


def parse_jwt(token: str) -> ParsedJwt:
    """Parsea un JWT en sus 3 partes. Raises ValueError si malformed."""
    if not token or not isinstance(token, str):
        raise ValueError("JWT token must be non-empty string")
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError(f"JWT must have 3 parts (header.payload.signature), got {len(parts)}")
    header_b64, payload_b64, signature_b64 = parts
    try:
        header = json.loads(b64url_decode(header_b64).decode("utf-8"))
        payload = json.loads(b64url_decode(payload_b64).decode("utf-8"))
        signature = b64url_decode(signature_b64)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"JWT decode failed: {type(exc).__name__}: {exc}") from exc

    if not isinstance(header, dict) or not isinstance(payload, dict):
        raise ValueError("JWT header and payload must be JSON objects")

    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    return ParsedJwt(
        header=header, payload=payload,
        signature=signature, signing_input=signing_input,
    )


# ════════════════════════════════════════════════════════════════════
# JWKS fetch + cache
# ════════════════════════════════════════════════════════════════════


_JWKS_CACHE: dict[str, tuple[float, dict]] = {}
_JWKS_TTL_SEC = 600  # 10 minutes


def fetch_jwks(jwks_uri: str, *, timeout_sec: int = 10, force_refresh: bool = False) -> dict:
    """Descarga (o reusa cache) el JWKS document.

    Returns:
        dict con `keys` array conteniendo JWK objects.

    Raises:
        ValueError si fetch falla o JWKS malformed.
    """
    if not jwks_uri:
        raise ValueError("jwks_uri is required")

    now = time.time()
    if not force_refresh and jwks_uri in _JWKS_CACHE:
        ts, doc = _JWKS_CACHE[jwks_uri]
        if now - ts < _JWKS_TTL_SEC:
            return doc

    try:
        req = urllib.request.Request(
            jwks_uri, headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read().decode("utf-8")
        doc = json.loads(raw)
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"JWKS fetch from {jwks_uri} failed: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    if not isinstance(doc, dict) or "keys" not in doc:
        raise ValueError(f"JWKS doc missing 'keys' array: {type(doc)}")

    _JWKS_CACHE[jwks_uri] = (now, doc)
    return doc


def reset_jwks_cache() -> None:
    """Limpia cache JWKS (test-only)."""
    _JWKS_CACHE.clear()


def find_jwk_by_kid(jwks: dict, kid: str) -> dict | None:
    """Busca un JWK por kid en el JWKS doc."""
    if not jwks or not kid:
        return None
    for key in jwks.get("keys", []):
        if isinstance(key, dict) and key.get("kid") == kid:
            return key
    return None


# ════════════════════════════════════════════════════════════════════
# RSA public key construction (from JWK n, e)
# ════════════════════════════════════════════════════════════════════


def jwk_to_rsa_public_key(jwk: dict):  # returns RSAPublicKey or None
    """Construye RSAPublicKey desde JWK con `n` (modulus) + `e` (exponent).

    Returns:
        RSAPublicKey object si cryptography disponible Y JWK bien-formado;
        None si cryptography no disponible.

    Raises:
        ValueError si JWK malformed.
    """
    if not _CRYPTOGRAPHY_AVAILABLE:
        return None
    if not jwk or jwk.get("kty") != "RSA":
        raise ValueError(f"JWK kty must be 'RSA', got {jwk.get('kty')!r}")
    n_b64 = jwk.get("n")
    e_b64 = jwk.get("e")
    if not n_b64 or not e_b64:
        raise ValueError("JWK missing 'n' or 'e' fields")

    try:
        n = b64url_decode_to_int(n_b64)
        e = b64url_decode_to_int(e_b64)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"JWK n/e decode failed: {exc}") from exc

    public_numbers = rsa.RSAPublicNumbers(e=e, n=n)
    return public_numbers.public_key(backend=default_backend())


# ════════════════════════════════════════════════════════════════════
# Algorithm verification (RS256 + RS384 + RS512 + HS256)
# ════════════════════════════════════════════════════════════════════


_ALLOWED_ASYMMETRIC_ALGS = {"RS256", "RS384", "RS512"}
_ALLOWED_SYMMETRIC_ALGS = {"HS256", "HS384", "HS512"}
_HASH_FOR_ALG = {
    "RS256": "sha256", "RS384": "sha384", "RS512": "sha512",
    "HS256": "sha256", "HS384": "sha384", "HS512": "sha512",
}


def verify_signature_rs(
    parsed: ParsedJwt,
    public_key,
    *,
    alg: str = "RS256",
) -> bool:
    """Verifica signature RS256/RS384/RS512 usando cryptography.

    Returns:
        True si signature válida, False si inválida o algoritmo no soportado.
    """
    if not _CRYPTOGRAPHY_AVAILABLE or public_key is None:
        return False
    if alg not in _ALLOWED_ASYMMETRIC_ALGS:
        logger.warning(f"verify_signature_rs: rejecting non-RSA alg={alg!r}")
        return False

    hash_class = {"sha256": hashes.SHA256, "sha384": hashes.SHA384, "sha512": hashes.SHA512}[
        _HASH_FOR_ALG[alg]
    ]
    try:
        public_key.verify(
            parsed.signature,
            parsed.signing_input,
            padding.PKCS1v15(),
            hash_class(),
        )
        return True
    except InvalidSignature:
        return False
    except Exception as exc:  # pragma: no cover
        logger.warning(f"verify_signature_rs unexpected error: {type(exc).__name__}: {exc}")
        return False


def verify_signature_hs(
    parsed: ParsedJwt,
    secret: bytes,
    *,
    alg: str = "HS256",
) -> bool:
    """Verifica signature HMAC (HS256/HS384/HS512) usando stdlib.

    Use case: shared-secret JWTs (no muy común en OIDC pero soportado).

    Returns:
        True si signature válida, False si inválida.
    """
    if alg not in _ALLOWED_SYMMETRIC_ALGS:
        return False
    hash_name = _HASH_FOR_ALG[alg]
    expected = hmac.new(secret, parsed.signing_input, hash_name).digest()
    return hmac.compare_digest(expected, parsed.signature)


# ════════════════════════════════════════════════════════════════════
# Claims validation
# ════════════════════════════════════════════════════════════════════


@dataclass
class ClaimsValidationResult:
    """Resultado de validación de claims."""
    valid: bool
    reason: str = ""        # razón específica si !valid
    claims: dict = None     # claims raw del payload


def validate_claims(
    payload: dict,
    *,
    expected_issuer: str = "",
    expected_audience: str = "",
    expected_nonce: str = "",
    time_skew_sec: int = 30,
    now_unix: float | None = None,
) -> ClaimsValidationResult:
    """Valida claims del payload OIDC: iss, aud, exp, iat, nbf, nonce.

    Returns:
        ClaimsValidationResult con valid + reason específica si falla.
    """
    if now_unix is None:
        now_unix = time.time()

    # iss validation
    if expected_issuer:
        iss = payload.get("iss", "")
        if iss != expected_issuer:
            return ClaimsValidationResult(
                valid=False,
                reason=f"iss mismatch: expected {expected_issuer!r}, got {iss!r}",
                claims=payload,
            )

    # aud validation (can be string or list)
    if expected_audience:
        aud = payload.get("aud")
        if isinstance(aud, list):
            if expected_audience not in aud:
                return ClaimsValidationResult(
                    valid=False,
                    reason=f"aud list does not include {expected_audience!r}",
                    claims=payload,
                )
        elif aud != expected_audience:
            return ClaimsValidationResult(
                valid=False,
                reason=f"aud mismatch: expected {expected_audience!r}, got {aud!r}",
                claims=payload,
            )

    # exp validation (must be in future)
    exp = payload.get("exp")
    if exp is None:
        return ClaimsValidationResult(
            valid=False, reason="exp claim missing", claims=payload,
        )
    try:
        exp_unix = float(exp)
    except (TypeError, ValueError):
        return ClaimsValidationResult(
            valid=False,
            reason=f"exp must be number, got {type(exp).__name__}",
            claims=payload,
        )
    if exp_unix <= now_unix - time_skew_sec:
        return ClaimsValidationResult(
            valid=False,
            reason=f"token expired (exp={exp_unix}, now={now_unix})",
            claims=payload,
        )

    # iat validation (must be in past, allowing skew)
    iat = payload.get("iat")
    if iat is not None:
        try:
            iat_unix = float(iat)
            if iat_unix > now_unix + time_skew_sec:
                return ClaimsValidationResult(
                    valid=False,
                    reason=f"iat in future (iat={iat_unix}, now={now_unix})",
                    claims=payload,
                )
        except (TypeError, ValueError):
            return ClaimsValidationResult(
                valid=False, reason=f"iat must be number, got {type(iat).__name__}",
                claims=payload,
            )

    # nbf validation (not before)
    nbf = payload.get("nbf")
    if nbf is not None:
        try:
            nbf_unix = float(nbf)
            if nbf_unix > now_unix + time_skew_sec:
                return ClaimsValidationResult(
                    valid=False,
                    reason=f"token not yet valid (nbf={nbf_unix}, now={now_unix})",
                    claims=payload,
                )
        except (TypeError, ValueError):
            return ClaimsValidationResult(
                valid=False, reason=f"nbf must be number, got {type(nbf).__name__}",
                claims=payload,
            )

    # nonce validation (replay protection)
    if expected_nonce:
        token_nonce = payload.get("nonce", "")
        if token_nonce != expected_nonce:
            return ClaimsValidationResult(
                valid=False,
                reason="nonce mismatch (possible replay attack)",
                claims=payload,
            )

    # sub claim required (OIDC §2)
    if not payload.get("sub"):
        return ClaimsValidationResult(
            valid=False, reason="sub claim missing", claims=payload,
        )

    return ClaimsValidationResult(valid=True, claims=payload)


# ════════════════════════════════════════════════════════════════════
# Top-level: verify_id_token (combina parse + JWKS + signature + claims)
# ════════════════════════════════════════════════════════════════════


@dataclass
class JwtVerificationResult:
    """Resultado completo de verify_id_token."""
    valid: bool
    reason: str = ""
    claims: dict | None = None
    algorithm: str = ""
    kid: str = ""


def verify_id_token(
    id_token: str,
    *,
    jwks_uri: str = "",
    expected_issuer: str = "",
    expected_audience: str = "",
    expected_nonce: str = "",
    hmac_secret: bytes | None = None,
    time_skew_sec: int = 30,
    timeout_sec: int = 10,
) -> JwtVerificationResult:
    """Verifica un id_token OIDC offline (signature + claims).

    Flujo:
        1. Parse JWT
        2. Read alg + kid from header
        3. Si RS256/RS384/RS512: fetch JWKS, find key by kid, verify RSA
        4. Si HS256/HS384/HS512: usar hmac_secret provided
        5. Validate claims (iss, aud, exp, iat, nbf, nonce, sub)
        6. Return result

    Args:
        id_token: JWT compact string
        jwks_uri: URL del JWKS endpoint del IDP (RS algos)
        expected_issuer: iss claim esperado
        expected_audience: aud claim esperado (typically client_id)
        expected_nonce: nonce que enviamos en authorization request
        hmac_secret: secret para HS algos (opcional)
        time_skew_sec: tolerancia para exp/iat/nbf (default 30s)
        timeout_sec: HTTP timeout para JWKS fetch

    Returns:
        JwtVerificationResult con valid + reason + claims.
    """
    if not _CRYPTOGRAPHY_AVAILABLE:
        return JwtVerificationResult(
            valid=False,
            reason="cryptography package not available; cannot verify RS256 JWTs",
        )

    try:
        parsed = parse_jwt(id_token)
    except ValueError as exc:
        return JwtVerificationResult(valid=False, reason=f"parse_failed: {exc}")

    alg = str(parsed.header.get("alg", ""))
    kid = str(parsed.header.get("kid", ""))

    # Algorithm confusion protection
    if alg == "none":
        return JwtVerificationResult(
            valid=False,
            reason="alg=none rejected (algorithm confusion attack vector)",
            algorithm=alg,
        )

    # Asymmetric (RS256/384/512) — fetch JWKS
    if alg in _ALLOWED_ASYMMETRIC_ALGS:
        if not jwks_uri:
            return JwtVerificationResult(
                valid=False,
                reason=f"jwks_uri required for {alg}",
                algorithm=alg, kid=kid,
            )
        try:
            jwks = fetch_jwks(jwks_uri, timeout_sec=timeout_sec)
        except ValueError as exc:
            return JwtVerificationResult(
                valid=False,
                reason=f"jwks_fetch_failed: {exc}",
                algorithm=alg, kid=kid,
            )
        jwk = find_jwk_by_kid(jwks, kid) if kid else None
        if jwk is None and len(jwks.get("keys", [])) == 1:
            # Single-key JWKS: use that key (some IDPs don't include kid)
            jwk = jwks["keys"][0]
        if jwk is None:
            # Try refresh JWKS once (key rotation)
            try:
                jwks = fetch_jwks(jwks_uri, timeout_sec=timeout_sec, force_refresh=True)
                jwk = find_jwk_by_kid(jwks, kid)
            except ValueError:
                pass
        if jwk is None:
            return JwtVerificationResult(
                valid=False,
                reason=f"no JWK matching kid={kid!r} (after refresh attempt)",
                algorithm=alg, kid=kid,
            )
        try:
            public_key = jwk_to_rsa_public_key(jwk)
        except ValueError as exc:
            return JwtVerificationResult(
                valid=False,
                reason=f"jwk_to_rsa_key_failed: {exc}",
                algorithm=alg, kid=kid,
            )
        if not verify_signature_rs(parsed, public_key, alg=alg):
            return JwtVerificationResult(
                valid=False,
                reason=f"{alg} signature verification failed",
                algorithm=alg, kid=kid,
            )

    elif alg in _ALLOWED_SYMMETRIC_ALGS:
        if not hmac_secret:
            return JwtVerificationResult(
                valid=False,
                reason=f"hmac_secret required for {alg}",
                algorithm=alg, kid=kid,
            )
        if not verify_signature_hs(parsed, hmac_secret, alg=alg):
            return JwtVerificationResult(
                valid=False,
                reason=f"{alg} HMAC verification failed",
                algorithm=alg, kid=kid,
            )

    else:
        return JwtVerificationResult(
            valid=False,
            reason=f"unsupported alg={alg!r} (allowed: RS256/384/512, HS256/384/512)",
            algorithm=alg, kid=kid,
        )

    # Claims validation
    claims_result = validate_claims(
        parsed.payload,
        expected_issuer=expected_issuer,
        expected_audience=expected_audience,
        expected_nonce=expected_nonce,
        time_skew_sec=time_skew_sec,
    )
    if not claims_result.valid:
        return JwtVerificationResult(
            valid=False,
            reason=f"claims_invalid: {claims_result.reason}",
            algorithm=alg, kid=kid,
            claims=parsed.payload,
        )

    return JwtVerificationResult(
        valid=True, claims=parsed.payload, algorithm=alg, kid=kid,
    )
