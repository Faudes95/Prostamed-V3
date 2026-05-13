"""Deterministic electronic signature envelopes for ProstaMed records.

This module is intentionally small and local-first. It does not prescribe,
does not mutate clinical facts, and does not replace the clinical audit trail.
It creates a tamper-evident envelope that binds:

- a human signer identity,
- an explicit signing intent,
- an authentication method/factor assertion,
- a record content hash,
- software/version context,
- and an HMAC signature over the canonical envelope.

Production deployments must provide a stable signing secret through
``PROSTAMED_ESIGN_SECRET`` or ``PROSTANET_SECRET_KEY``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from typing import Any, Mapping


SIGNATURE_SCHEMA_VERSION = "prostamed_electronic_signature_v1"
SIGNATURE_ALGORITHM = "HMAC-SHA256"
HASH_ALGORITHM = "sha256"

APPROVED_SIGNATURE_MEANINGS = {
    "reviewed_and_approved",
    "clinical_decision_signed",
    "source_document_verified",
    "voice_extraction_accepted",
    "loop_patch_authorized",
    "consent_signed",
}

APPROVED_AUTH_METHODS = {
    "clinical_session_reauth",
    "password_reentry",
    "idp_reauth",
    "voice_consent_review",
    "human_patch_authorization",
}


@dataclass(frozen=True)
class SignatureValidation:
    """Validation result for an electronic signature envelope."""

    valid: bool
    reason: str
    signature_id: str = ""


def canonical_json(value: Any) -> str:
    """Return a stable JSON representation used for hashing/signing."""

    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def record_content_hash(record_payload: Any) -> str:
    """Hash a signable record payload without storing PHI in logs."""

    digest = hashlib.sha256(canonical_json(record_payload).encode("utf-8")).hexdigest()
    return f"{HASH_ALGORITHM}:{digest}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalize(value: Any) -> str:
    return str(value or "").strip()


def _require_nonempty(name: str, value: Any) -> str:
    text = _normalize(value)
    if not text:
        raise ValueError(f"{name} is required")
    return text


def _signature_secret(secret: str | bytes | None = None) -> bytes:
    if isinstance(secret, bytes) and secret:
        return secret
    if isinstance(secret, str) and secret.strip():
        return secret.encode("utf-8")

    configured = (
        os.environ.get("PROSTAMED_ESIGN_SECRET")
        or os.environ.get("PROSTANET_SECRET_KEY")
        or ""
    ).strip()
    if configured:
        return configured.encode("utf-8")

    env_name = (os.environ.get("FLASK_ENV") or os.environ.get("PROSTANET_ENV") or "").lower()
    if env_name in {"production", "prod"}:
        raise RuntimeError("PROSTAMED_ESIGN_SECRET is required for production electronic signatures")

    return b"prostamed-dev-electronic-signature-secret"


def _signature_base(envelope: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in dict(envelope).items()
        if key not in {"signature_id", "signature_value"}
    }


def _hmac_signature(base: Mapping[str, Any], secret: str | bytes | None = None) -> str:
    return hmac.new(
        _signature_secret(secret),
        canonical_json(base).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _base_identifier(base: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(canonical_json(base).encode("utf-8")).hexdigest()
    return f"esign_{digest[:24]}"


def create_electronic_signature(
    *,
    record_type: str,
    record_ref: str,
    record_payload: Any | None = None,
    content_hash: str | None = None,
    signer_id: str,
    signer_name: str,
    signer_role: str,
    meaning: str,
    reason: str = "",
    auth_method: str,
    authentication_factors: list[str] | tuple[str, ...] | None = None,
    session_id: str = "",
    signed_at: str | None = None,
    software_version: str = "",
    secret: str | bytes | None = None,
) -> dict[str, Any]:
    """Create a tamper-evident electronic signature envelope.

    ``content_hash`` can be supplied by an existing audit bundle. If omitted,
    ``record_payload`` is canonically hashed. The raw payload is never stored in
    the returned envelope.
    """

    record_type = _require_nonempty("record_type", record_type)
    record_ref = _require_nonempty("record_ref", record_ref)
    signer_id = _require_nonempty("signer_id", signer_id)
    signer_name = _require_nonempty("signer_name", signer_name)
    signer_role = _require_nonempty("signer_role", signer_role)
    meaning = _require_nonempty("meaning", meaning)
    auth_method = _require_nonempty("auth_method", auth_method)

    if meaning not in APPROVED_SIGNATURE_MEANINGS:
        raise ValueError(f"unsupported signature meaning: {meaning}")
    if auth_method not in APPROVED_AUTH_METHODS:
        raise ValueError(f"unsupported auth method: {auth_method}")

    factors = [_normalize(item) for item in list(authentication_factors or []) if _normalize(item)]
    if not factors:
        raise ValueError("authentication_factors must include at least one verified factor")

    if not content_hash:
        if record_payload is None:
            raise ValueError("content_hash or record_payload is required")
        content_hash = record_content_hash(record_payload)
    content_hash = _require_nonempty("content_hash", content_hash)
    if not content_hash.startswith(f"{HASH_ALGORITHM}:"):
        raise ValueError("content_hash must use sha256:<hex>")

    session_id_hash = ""
    if session_id:
        session_id_hash = record_content_hash({"session_id": session_id})

    envelope: dict[str, Any] = {
        "schema_version": SIGNATURE_SCHEMA_VERSION,
        "record": {
            "record_type": record_type,
            "record_ref": record_ref,
            "content_hash": content_hash,
            "hash_algorithm": HASH_ALGORITHM,
        },
        "signer": {
            "signer_id": signer_id,
            "signer_name": signer_name,
            "signer_role": signer_role,
        },
        "intent": {
            "meaning": meaning,
            "reason": _normalize(reason),
        },
        "auth": {
            "method": auth_method,
            "factors": factors,
            "session_id_hash": session_id_hash,
        },
        "signed_at": signed_at or _utc_now(),
        "software_version": _normalize(software_version),
        "signature_algorithm": SIGNATURE_ALGORITHM,
    }
    base = _signature_base(envelope)
    envelope["signature_id"] = _base_identifier(base)
    envelope["signature_value"] = _hmac_signature(base, secret=secret)
    return envelope


def validate_electronic_signature(
    envelope: Mapping[str, Any],
    *,
    record_payload: Any | None = None,
    secret: str | bytes | None = None,
) -> SignatureValidation:
    """Validate envelope shape, record hash binding, and HMAC signature."""

    if not isinstance(envelope, Mapping):
        return SignatureValidation(False, "envelope_not_mapping")

    if envelope.get("schema_version") != SIGNATURE_SCHEMA_VERSION:
        return SignatureValidation(False, "schema_version_mismatch")
    if envelope.get("signature_algorithm") != SIGNATURE_ALGORITHM:
        return SignatureValidation(False, "signature_algorithm_mismatch")

    record = envelope.get("record") or {}
    signer = envelope.get("signer") or {}
    intent = envelope.get("intent") or {}
    auth = envelope.get("auth") or {}
    signature_id = _normalize(envelope.get("signature_id"))

    required_paths = {
        "record.record_type": record.get("record_type"),
        "record.record_ref": record.get("record_ref"),
        "record.content_hash": record.get("content_hash"),
        "signer.signer_id": signer.get("signer_id"),
        "signer.signer_name": signer.get("signer_name"),
        "signer.signer_role": signer.get("signer_role"),
        "intent.meaning": intent.get("meaning"),
        "auth.method": auth.get("method"),
        "signed_at": envelope.get("signed_at"),
        "signature_id": signature_id,
        "signature_value": envelope.get("signature_value"),
    }
    for name, value in required_paths.items():
        if not _normalize(value):
            return SignatureValidation(False, f"missing_{name}", signature_id)

    if intent.get("meaning") not in APPROVED_SIGNATURE_MEANINGS:
        return SignatureValidation(False, "unsupported_signature_meaning", signature_id)
    if auth.get("method") not in APPROVED_AUTH_METHODS:
        return SignatureValidation(False, "unsupported_auth_method", signature_id)
    if not list(auth.get("factors") or []):
        return SignatureValidation(False, "missing_authentication_factor", signature_id)

    if record_payload is not None:
        expected_hash = record_content_hash(record_payload)
        if record.get("content_hash") != expected_hash:
            return SignatureValidation(False, "record_payload_hash_mismatch", signature_id)

    base = _signature_base(envelope)
    expected_id = _base_identifier(base)
    if signature_id != expected_id:
        return SignatureValidation(False, "signature_id_mismatch", signature_id)

    expected_value = _hmac_signature(base, secret=secret)
    actual_value = _normalize(envelope.get("signature_value"))
    if not hmac.compare_digest(actual_value, expected_value):
        return SignatureValidation(False, "signature_value_mismatch", signature_id)

    return SignatureValidation(True, "valid", signature_id)
