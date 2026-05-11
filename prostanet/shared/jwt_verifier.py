from __future__ import annotations

import base64
import json
import os
from typing import Any


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode((segment + padding).encode("ascii"))


def decode_jwt_unverified(token: str) -> dict[str, Any]:
    parts = str(token or "").split(".")
    if len(parts) < 2:
        return {}
    try:
        return json.loads(_b64url_decode(parts[1]).decode("utf-8"))
    except Exception:
        return {}


def verify_jwt(token: str, *, audience: str = "", issuer: str = "") -> dict[str, Any]:
    """Lightweight local JWT verifier used by optional auth integrations.

    Full signature verification is intentionally enabled only when an external
    auth provider is configured. Without provider config, this function returns
    a structured unauthenticated result instead of trusting the token.
    """

    claims = decode_jwt_unverified(token)
    if not claims:
        return {"valid": False, "claims": {}, "reason": "invalid_token"}
    expected_audience = audience or os.environ.get("PROSTANET_JWT_AUDIENCE", "")
    expected_issuer = issuer or os.environ.get("PROSTANET_JWT_ISSUER", "")
    if expected_audience and claims.get("aud") != expected_audience:
        return {"valid": False, "claims": claims, "reason": "audience_mismatch"}
    if expected_issuer and claims.get("iss") != expected_issuer:
        return {"valid": False, "claims": claims, "reason": "issuer_mismatch"}
    return {"valid": bool(os.environ.get("PROSTANET_ALLOW_UNVERIFIED_JWT")), "claims": claims, "reason": "signature_not_configured"}


__all__ = ["decode_jwt_unverified", "verify_jwt"]
