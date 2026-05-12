"""Local-first encryption helpers for ProstaMed Voice Clinical OS."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class VoiceSecurityError(RuntimeError):
    """Raised when voice PHI cannot be protected safely."""


def _is_production() -> bool:
    values = {
        os.environ.get("FLASK_ENV", ""),
        os.environ.get("PROSTANET_ENV", ""),
        os.environ.get("ENV", ""),
    }
    return any(str(value).lower() in {"prod", "production"} for value in values)


def _decode_key(raw: str) -> bytes:
    value = str(raw or "").strip()
    if value.startswith("base64:"):
        value = value.split(":", 1)[1]
    if len(value) == 64 and all(ch in "0123456789abcdefABCDEF" for ch in value):
        key = bytes.fromhex(value)
    else:
        padding = "=" * (-len(value) % 4)
        key = base64.urlsafe_b64decode((value + padding).encode("ascii"))
    if len(key) != 32:
        raise VoiceSecurityError("VOICE_MASTER_KEY debe decodificar a 32 bytes.")
    return key


def _development_key(db_path: str | None = None) -> bytes:
    root = Path(db_path or os.environ.get("PROSTANET_DB_PATH", "prostanet_tracking.db")).resolve().parent
    key_path = root / ".prostanet_private" / "voice" / "dev_master.key"
    if key_path.exists():
        return _decode_key(key_path.read_text(encoding="utf-8").strip())
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    key_path.write_text(base64.urlsafe_b64encode(key).decode("ascii"), encoding="utf-8")
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass
    return key


def load_voice_master_key(*, testing: bool = False, db_path: str | None = None) -> bytes:
    """Load the voice encryption key.

    Production is fail-closed: a configured 32-byte key is required. Tests and
    local development can use deterministic or private local keys without
    sending audio/transcripts to external services.
    """

    raw = os.environ.get("PROSTANET_VOICE_MASTER_KEY") or os.environ.get("VOICE_MASTER_KEY")
    if raw:
        return _decode_key(raw)
    require_key = os.environ.get("PROSTANET_VOICE_REQUIRE_KEY", "").lower() in {"1", "true", "yes"}
    if _is_production() or require_key:
        raise VoiceSecurityError("Falta PROSTANET_VOICE_MASTER_KEY para cifrar voz clínica.")
    if testing or os.environ.get("PYTEST_CURRENT_TEST"):
        return hashlib.sha256(b"prostanet-voice-test-key").digest()
    return _development_key(db_path=db_path)


@dataclass(frozen=True)
class VoiceCrypto:
    """AES-GCM envelope for temporary voice PHI."""

    key: bytes

    def encrypt_bytes(self, plaintext: bytes, *, aad: str = "") -> dict[str, Any]:
        if plaintext is None:
            plaintext = b""
        nonce = secrets.token_bytes(12)
        aes = AESGCM(self.key)
        aad_bytes = aad.encode("utf-8") if aad else None
        ciphertext = aes.encrypt(nonce, plaintext, aad_bytes)
        return {
            "algorithm": "AES-256-GCM",
            "nonce": base64.urlsafe_b64encode(nonce).decode("ascii"),
            "ciphertext": base64.urlsafe_b64encode(ciphertext).decode("ascii"),
            "sha256": hashlib.sha256(plaintext).hexdigest(),
            "aad": aad,
        }

    def decrypt_bytes(self, envelope: dict[str, Any] | str | None) -> bytes:
        if not envelope:
            return b""
        if isinstance(envelope, str):
            envelope = json.loads(envelope)
        if envelope.get("algorithm") != "AES-256-GCM":
            raise VoiceSecurityError("Algoritmo de cifrado de voz no soportado.")
        aes = AESGCM(self.key)
        nonce = base64.urlsafe_b64decode(envelope["nonce"].encode("ascii"))
        ciphertext = base64.urlsafe_b64decode(envelope["ciphertext"].encode("ascii"))
        aad = envelope.get("aad") or ""
        return aes.decrypt(nonce, ciphertext, aad.encode("utf-8") if aad else None)

    def encrypt_text(self, text: str, *, aad: str = "") -> dict[str, Any]:
        return self.encrypt_bytes(str(text or "").encode("utf-8"), aad=aad)

    def decrypt_text(self, envelope: dict[str, Any] | str | None) -> str:
        return self.decrypt_bytes(envelope).decode("utf-8")


def get_voice_crypto(*, testing: bool = False, db_path: str | None = None) -> VoiceCrypto:
    return VoiceCrypto(load_voice_master_key(testing=testing, db_path=db_path))

