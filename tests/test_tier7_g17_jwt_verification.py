"""tests/test_tier7_g17_jwt_verification.py — FAUBOT 2026-04-25 (XXX).

Tier 7 G1.7 — JWT signature verification offline (RS256 + JWKS).

Cobertura:
  - JWT parsing (header.payload.signature decode)
  - JWKS fetch + cache + key rotation refresh
  - RS256/RS384/RS512 signature verification
  - HS256/HS384/HS512 HMAC verification
  - Algorithm confusion protection (alg=none rejection)
  - Claims validation (iss, aud, exp, iat, nbf, nonce, sub)
  - Time skew tolerance
  - Hybrid resolver (JWT preferred, userinfo fallback)
  - Graceful degradation when cryptography unavailable
  - End-to-end OIDC flow with id_token verification

Hipótesis: H.G602-H.G660 (~60 hipótesis).

Genera RSA keys real-time para tests (cryptography ya disponible).
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import base64
import json
import time

import pytest


# ════════════════════════════════════════════════════════════════════
# §A. Test fixtures: real RSA key pair + signed JWT generator
# ════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
def rsa_keypair():
    """Generate a 2048-bit RSA keypair for tests (module-scoped for speed)."""
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.backends import default_backend
    key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048, backend=default_backend(),
    )
    return key


@pytest.fixture(scope="module")
def jwk_from_keypair(rsa_keypair):
    """Construct a JWK from the RSA public key."""
    pub_numbers = rsa_keypair.public_key().public_numbers()

    def b64url_int(i: int) -> str:
        b = i.to_bytes((i.bit_length() + 7) // 8, byteorder="big")
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")

    return {
        "kty": "RSA",
        "kid": "test-key-1",
        "use": "sig",
        "alg": "RS256",
        "n": b64url_int(pub_numbers.n),
        "e": b64url_int(pub_numbers.e),
    }


@pytest.fixture
def reset_jwks_cache_before_test():
    """Reset JWKS cache before each test for isolation."""
    from prostanet.shared.jwt_verifier import reset_jwks_cache
    reset_jwks_cache()


def _sign_jwt(rsa_key, *, header: dict, payload: dict) -> str:
    """Sign a JWT with given header + payload + RSA key (RS256)."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    def b64url(b: bytes) -> str:
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")

    h_b64 = b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    p_b64 = b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{h_b64}.{p_b64}".encode("ascii")
    alg = header.get("alg", "RS256")
    if alg == "RS256":
        sig = rsa_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    elif alg == "RS384":
        sig = rsa_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA384())
    elif alg == "RS512":
        sig = rsa_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA512())
    elif alg == "none":
        sig = b""
    else:
        raise ValueError(f"Unsupported alg: {alg}")
    sig_b64 = b64url(sig)
    return f"{h_b64}.{p_b64}.{sig_b64}"


def _make_valid_jwt(rsa_key, *, kid="test-key-1", alg="RS256", **claim_overrides) -> str:
    """Build a valid JWT with sensible defaults + claim_overrides."""
    now = int(time.time())
    header = {"alg": alg, "kid": kid, "typ": "JWT"}
    payload = {
        "iss": "https://idp.example.com",
        "sub": "user_001",
        "aud": "test-client",
        "exp": now + 3600,
        "iat": now,
        "email": "alice@hospital.org",
        "preferred_username": "alice",
    }
    payload.update(claim_overrides)
    return _sign_jwt(rsa_key, header=header, payload=payload)


@pytest.fixture
def populate_jwks_cache(jwk_from_keypair, reset_jwks_cache_before_test):
    """Populate JWKS cache with the test key (avoids HTTP calls)."""
    from prostanet.shared.jwt_verifier import _JWKS_CACHE
    jwks = {"keys": [jwk_from_keypair]}
    _JWKS_CACHE["http://test/jwks"] = (time.time(), jwks)
    yield jwks


# ════════════════════════════════════════════════════════════════════
# §B. Base64URL helpers (H.G602-H.G605)
# ════════════════════════════════════════════════════════════════════


def test_g602_b64url_decode_with_padding():
    """H.G602 — b64url_decode handles input with padding."""
    from prostanet.shared.jwt_verifier import b64url_decode
    assert b64url_decode("aGVsbG8=") == b"hello"


def test_g603_b64url_decode_without_padding():
    """H.G603 — b64url_decode handles input without padding (JWT standard)."""
    from prostanet.shared.jwt_verifier import b64url_decode
    assert b64url_decode("aGVsbG8") == b"hello"


def test_g604_b64url_decode_empty():
    """H.G604 — b64url_decode handles empty string."""
    from prostanet.shared.jwt_verifier import b64url_decode
    assert b64url_decode("") == b""


def test_g605_b64url_decode_to_int():
    """H.G605 — b64url_decode_to_int decodes to big int (RSA modulus)."""
    from prostanet.shared.jwt_verifier import b64url_decode_to_int
    # 65537 (common RSA exponent) → b'\\x01\\x00\\x01' → "AQAB" b64url
    assert b64url_decode_to_int("AQAB") == 65537


# ════════════════════════════════════════════════════════════════════
# §C. JWT parsing (H.G606-H.G611)
# ════════════════════════════════════════════════════════════════════


def test_g606_parse_jwt_returns_three_parts(rsa_keypair):
    """H.G606 — parse_jwt returns header + payload + signature."""
    from prostanet.shared.jwt_verifier import parse_jwt
    token = _make_valid_jwt(rsa_keypair)
    parsed = parse_jwt(token)
    assert parsed.header["alg"] == "RS256"
    assert parsed.payload["sub"] == "user_001"
    assert len(parsed.signature) > 0


def test_g607_parse_jwt_includes_signing_input(rsa_keypair):
    """H.G607 — parse_jwt includes signing_input bytes for verification."""
    from prostanet.shared.jwt_verifier import parse_jwt
    token = _make_valid_jwt(rsa_keypair)
    parsed = parse_jwt(token)
    # signing_input = header_b64 + '.' + payload_b64
    expected_prefix = ".".join(token.split(".")[:2]).encode("ascii")
    assert parsed.signing_input == expected_prefix


def test_g608_parse_jwt_malformed_raises():
    """H.G608 — Malformed JWT (wrong number of parts) raises ValueError."""
    from prostanet.shared.jwt_verifier import parse_jwt
    with pytest.raises(ValueError, match="3 parts"):
        parse_jwt("not.a.valid.jwt.token")
    with pytest.raises(ValueError, match="3 parts"):
        parse_jwt("only.two")
    with pytest.raises(ValueError, match="3 parts"):
        parse_jwt("only-one")


def test_g609_parse_jwt_empty_raises():
    """H.G609 — Empty token raises."""
    from prostanet.shared.jwt_verifier import parse_jwt
    with pytest.raises(ValueError):
        parse_jwt("")


def test_g610_parse_jwt_invalid_json_raises():
    """H.G610 — JWT with bad base64 raises."""
    from prostanet.shared.jwt_verifier import parse_jwt
    with pytest.raises(ValueError, match="decode failed"):
        parse_jwt("***.***.***")


def test_g611_parse_jwt_non_object_payload_raises():
    """H.G611 — Payload that decodes to non-dict raises."""
    from prostanet.shared.jwt_verifier import parse_jwt
    # Build a JWT with payload="[1,2,3]" (array, not object)
    h_b64 = base64.urlsafe_b64encode(b'{"alg":"RS256"}').rstrip(b"=").decode()
    p_b64 = base64.urlsafe_b64encode(b"[1,2,3]").rstrip(b"=").decode()
    s_b64 = base64.urlsafe_b64encode(b"sig").rstrip(b"=").decode()
    with pytest.raises(ValueError, match="JSON objects"):
        parse_jwt(f"{h_b64}.{p_b64}.{s_b64}")


# ════════════════════════════════════════════════════════════════════
# §D. JWKS find_jwk_by_kid (H.G612-H.G615)
# ════════════════════════════════════════════════════════════════════


def test_g612_find_jwk_by_kid_match(jwk_from_keypair):
    """H.G612 — find_jwk_by_kid returns the matching key."""
    from prostanet.shared.jwt_verifier import find_jwk_by_kid
    jwks = {"keys": [jwk_from_keypair, {"kid": "other-key", "kty": "RSA"}]}
    found = find_jwk_by_kid(jwks, "test-key-1")
    assert found == jwk_from_keypair


def test_g613_find_jwk_by_kid_no_match(jwk_from_keypair):
    """H.G613 — find_jwk_by_kid returns None if kid not in JWKS."""
    from prostanet.shared.jwt_verifier import find_jwk_by_kid
    jwks = {"keys": [jwk_from_keypair]}
    assert find_jwk_by_kid(jwks, "missing-kid") is None


def test_g614_find_jwk_by_kid_empty():
    """H.G614 — find_jwk_by_kid with empty JWKS returns None."""
    from prostanet.shared.jwt_verifier import find_jwk_by_kid
    assert find_jwk_by_kid({"keys": []}, "any") is None


def test_g615_find_jwk_by_kid_handles_none():
    """H.G615 — find_jwk_by_kid handles None inputs gracefully."""
    from prostanet.shared.jwt_verifier import find_jwk_by_kid
    assert find_jwk_by_kid(None, "x") is None
    assert find_jwk_by_kid({}, "") is None


# ════════════════════════════════════════════════════════════════════
# §E. JWK → RSA public key (H.G616-H.G618)
# ════════════════════════════════════════════════════════════════════


def test_g616_jwk_to_rsa_public_key_succeeds(jwk_from_keypair):
    """H.G616 — jwk_to_rsa_public_key constructs valid RSA key."""
    from prostanet.shared.jwt_verifier import jwk_to_rsa_public_key
    key = jwk_to_rsa_public_key(jwk_from_keypair)
    assert key is not None
    assert key.key_size == 2048


def test_g617_jwk_to_rsa_public_key_invalid_kty_raises():
    """H.G617 — jwk_to_rsa_public_key with kty != RSA raises."""
    from prostanet.shared.jwt_verifier import jwk_to_rsa_public_key
    with pytest.raises(ValueError, match="kty must be 'RSA'"):
        jwk_to_rsa_public_key({"kty": "EC", "n": "x", "e": "AQAB"})


def test_g618_jwk_to_rsa_public_key_missing_n_e_raises():
    """H.G618 — jwk_to_rsa_public_key missing n/e raises."""
    from prostanet.shared.jwt_verifier import jwk_to_rsa_public_key
    with pytest.raises(ValueError, match="missing 'n' or 'e'"):
        jwk_to_rsa_public_key({"kty": "RSA"})


# ════════════════════════════════════════════════════════════════════
# §F. RSA signature verification (H.G619-H.G623)
# ════════════════════════════════════════════════════════════════════


def test_g619_verify_signature_rs256_valid(rsa_keypair, jwk_from_keypair):
    """H.G619 — verify_signature_rs returns True for valid RS256."""
    from prostanet.shared.jwt_verifier import (
        parse_jwt, jwk_to_rsa_public_key, verify_signature_rs,
    )
    token = _make_valid_jwt(rsa_keypair)
    parsed = parse_jwt(token)
    pub_key = jwk_to_rsa_public_key(jwk_from_keypair)
    assert verify_signature_rs(parsed, pub_key, alg="RS256") is True


def test_g620_verify_signature_rs256_tampered_payload(rsa_keypair, jwk_from_keypair):
    """H.G620 — verify_signature_rs returns False if payload tampered."""
    from prostanet.shared.jwt_verifier import (
        parse_jwt, jwk_to_rsa_public_key, verify_signature_rs,
    )
    token = _make_valid_jwt(rsa_keypair)
    # Tamper: replace payload
    parts = token.split(".")
    fake_payload = base64.urlsafe_b64encode(
        b'{"sub":"attacker","aud":"test-client","exp":9999999999,"iss":"x"}'
    ).rstrip(b"=").decode()
    tampered = f"{parts[0]}.{fake_payload}.{parts[2]}"
    parsed = parse_jwt(tampered)
    pub_key = jwk_to_rsa_public_key(jwk_from_keypair)
    assert verify_signature_rs(parsed, pub_key, alg="RS256") is False


def test_g621_verify_signature_rs_rejects_non_rs_alg(rsa_keypair, jwk_from_keypair):
    """H.G621 — verify_signature_rs rejects non-RS algorithms."""
    from prostanet.shared.jwt_verifier import (
        parse_jwt, jwk_to_rsa_public_key, verify_signature_rs,
    )
    token = _make_valid_jwt(rsa_keypair)
    parsed = parse_jwt(token)
    pub_key = jwk_to_rsa_public_key(jwk_from_keypair)
    # Try to verify with HS256 alg → should reject
    assert verify_signature_rs(parsed, pub_key, alg="HS256") is False
    assert verify_signature_rs(parsed, pub_key, alg="none") is False


def test_g622_verify_signature_hs256_valid():
    """H.G622 — verify_signature_hs returns True for valid HS256."""
    import hmac, hashlib
    from prostanet.shared.jwt_verifier import (
        parse_jwt, verify_signature_hs,
    )
    secret = b"shared-secret-for-test"
    h_b64 = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=").decode()
    p_b64 = base64.urlsafe_b64encode(b'{"sub":"u1","exp":9999999999}').rstrip(b"=").decode()
    signing_input = f"{h_b64}.{p_b64}".encode("ascii")
    sig = hmac.new(secret, signing_input, hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
    token = f"{h_b64}.{p_b64}.{sig_b64}"
    parsed = parse_jwt(token)
    assert verify_signature_hs(parsed, secret, alg="HS256") is True


def test_g623_verify_signature_hs256_wrong_secret():
    """H.G623 — verify_signature_hs returns False with wrong secret."""
    import hmac, hashlib
    from prostanet.shared.jwt_verifier import (
        parse_jwt, verify_signature_hs,
    )
    secret = b"correct"
    h_b64 = base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=").decode()
    p_b64 = base64.urlsafe_b64encode(b'{"sub":"u1"}').rstrip(b"=").decode()
    signing_input = f"{h_b64}.{p_b64}".encode("ascii")
    sig = hmac.new(secret, signing_input, hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
    token = f"{h_b64}.{p_b64}.{sig_b64}"
    parsed = parse_jwt(token)
    assert verify_signature_hs(parsed, b"wrong-secret", alg="HS256") is False


# ════════════════════════════════════════════════════════════════════
# §G. Claims validation (H.G624-H.G632)
# ════════════════════════════════════════════════════════════════════


def test_g624_validate_claims_valid_minimal():
    """H.G624 — Valid minimal claims pass."""
    from prostanet.shared.jwt_verifier import validate_claims
    now = time.time()
    result = validate_claims({
        "sub": "u1", "exp": now + 3600,
    })
    assert result.valid is True


def test_g625_validate_claims_missing_sub_fails():
    """H.G625 — Missing sub claim fails."""
    from prostanet.shared.jwt_verifier import validate_claims
    result = validate_claims({"exp": time.time() + 3600})
    assert result.valid is False
    assert "sub" in result.reason


def test_g626_validate_claims_expired_fails():
    """H.G626 — exp in past fails."""
    from prostanet.shared.jwt_verifier import validate_claims
    result = validate_claims({"sub": "u1", "exp": time.time() - 3600})
    assert result.valid is False
    assert "expired" in result.reason


def test_g627_validate_claims_iss_mismatch():
    """H.G627 — iss claim mismatch fails."""
    from prostanet.shared.jwt_verifier import validate_claims
    result = validate_claims(
        {"sub": "u1", "exp": time.time() + 3600, "iss": "https://wrong.com"},
        expected_issuer="https://right.com",
    )
    assert result.valid is False
    assert "iss" in result.reason


def test_g628_validate_claims_aud_string_match():
    """H.G628 — aud as string match passes."""
    from prostanet.shared.jwt_verifier import validate_claims
    result = validate_claims(
        {"sub": "u1", "exp": time.time() + 3600, "aud": "client-a"},
        expected_audience="client-a",
    )
    assert result.valid is True


def test_g629_validate_claims_aud_list_includes():
    """H.G629 — aud as list with expected included passes."""
    from prostanet.shared.jwt_verifier import validate_claims
    result = validate_claims(
        {"sub": "u1", "exp": time.time() + 3600, "aud": ["x", "client-a", "y"]},
        expected_audience="client-a",
    )
    assert result.valid is True


def test_g630_validate_claims_aud_list_excludes_fails():
    """H.G630 — aud list missing expected fails."""
    from prostanet.shared.jwt_verifier import validate_claims
    result = validate_claims(
        {"sub": "u1", "exp": time.time() + 3600, "aud": ["x", "y"]},
        expected_audience="client-a",
    )
    assert result.valid is False


def test_g631_validate_claims_nonce_mismatch():
    """H.G631 — Nonce mismatch fails (replay protection)."""
    from prostanet.shared.jwt_verifier import validate_claims
    result = validate_claims(
        {"sub": "u1", "exp": time.time() + 3600, "nonce": "wrong"},
        expected_nonce="expected",
    )
    assert result.valid is False
    assert "nonce" in result.reason


def test_g632_validate_claims_time_skew_tolerance():
    """H.G632 — time_skew_sec allows small clock drift."""
    from prostanet.shared.jwt_verifier import validate_claims
    # Token expires 10s ago, but skew=30s → should still be valid
    result = validate_claims(
        {"sub": "u1", "exp": time.time() - 10},
        time_skew_sec=30,
    )
    assert result.valid is True


# ════════════════════════════════════════════════════════════════════
# §H. Algorithm confusion attacks (H.G633-H.G636)
# ════════════════════════════════════════════════════════════════════


def test_g633_verify_id_token_rejects_alg_none(rsa_keypair, populate_jwks_cache):
    """H.G633 — verify_id_token rejects alg=none (critical security)."""
    from prostanet.shared.jwt_verifier import verify_id_token
    # Create JWT with alg=none
    now = int(time.time())
    h_b64 = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=").decode()
    p_b64 = base64.urlsafe_b64encode(
        json.dumps({"sub": "attacker", "exp": now + 3600, "iss": "https://idp.example.com",
                    "aud": "test-client"}).encode("utf-8"),
    ).rstrip(b"=").decode()
    token = f"{h_b64}.{p_b64}."  # empty signature
    result = verify_id_token(
        token,
        jwks_uri="http://test/jwks",
        expected_issuer="https://idp.example.com",
        expected_audience="test-client",
    )
    assert result.valid is False
    assert "alg=none rejected" in result.reason


def test_g634_verify_id_token_rejects_unsupported_alg(rsa_keypair, populate_jwks_cache):
    """H.G634 — Unsupported algorithm rejected."""
    from prostanet.shared.jwt_verifier import verify_id_token
    h_b64 = base64.urlsafe_b64encode(b'{"alg":"BLAKE3","typ":"JWT"}').rstrip(b"=").decode()
    p_b64 = base64.urlsafe_b64encode(b'{"sub":"u1"}').rstrip(b"=").decode()
    sig_b64 = base64.urlsafe_b64encode(b"sig").rstrip(b"=").decode()  # valid b64
    token = f"{h_b64}.{p_b64}.{sig_b64}"
    result = verify_id_token(
        token, jwks_uri="http://test/jwks",
        expected_issuer="https://idp.example.com",
    )
    assert result.valid is False
    assert "unsupported alg" in result.reason


def test_g635_verify_id_token_kid_not_in_multikey_jwks(rsa_keypair, jwk_from_keypair):
    """H.G635 — JWT with kid not in JWKS (multi-key JWKS) rejected.

    Note: single-key JWKS uses the only key (some IDPs don't include kid).
    To test rejection, we need a JWKS with 2+ keys + JWT with unknown kid.
    """
    import time
    from prostanet.shared.jwt_verifier import verify_id_token, _JWKS_CACHE
    # Build a JWKS with 2 keys (neither matches "unknown-kid")
    second_jwk = dict(jwk_from_keypair)
    second_jwk["kid"] = "another-key-2"
    multi_jwks = {"keys": [jwk_from_keypair, second_jwk]}
    _JWKS_CACHE["http://test/jwks-multi"] = (time.time(), multi_jwks)

    token = _make_valid_jwt(rsa_keypair, kid="unknown-kid")
    result = verify_id_token(
        token,
        jwks_uri="http://test/jwks-multi",
        expected_issuer="https://idp.example.com",
        expected_audience="test-client",
    )
    assert result.valid is False
    assert "no JWK matching kid" in result.reason


def test_g636_verify_id_token_single_key_no_kid_required(rsa_keypair, populate_jwks_cache):
    """H.G636 — JWT without kid + single-key JWKS uses that key (some IDPs)."""
    from prostanet.shared.jwt_verifier import verify_id_token
    # Build JWT without kid in header
    now = int(time.time())
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    def b64url(b):
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")

    header = {"alg": "RS256", "typ": "JWT"}  # NO kid
    payload = {
        "iss": "https://idp.example.com", "sub": "u1",
        "aud": "test-client", "exp": now + 3600, "iat": now,
    }
    h_b64 = b64url(json.dumps(header, separators=(",", ":")).encode())
    p_b64 = b64url(json.dumps(payload, separators=(",", ":")).encode())
    sig = rsa_keypair.sign(
        f"{h_b64}.{p_b64}".encode("ascii"),
        padding.PKCS1v15(), hashes.SHA256(),
    )
    token = f"{h_b64}.{p_b64}.{b64url(sig)}"

    result = verify_id_token(
        token,
        jwks_uri="http://test/jwks",
        expected_issuer="https://idp.example.com",
        expected_audience="test-client",
    )
    assert result.valid is True


# ════════════════════════════════════════════════════════════════════
# §I. End-to-end verify_id_token (H.G637-H.G643)
# ════════════════════════════════════════════════════════════════════


def test_g637_verify_id_token_full_flow_succeeds(rsa_keypair, populate_jwks_cache):
    """H.G637 — verify_id_token end-to-end with valid JWT."""
    from prostanet.shared.jwt_verifier import verify_id_token
    token = _make_valid_jwt(rsa_keypair)
    result = verify_id_token(
        token,
        jwks_uri="http://test/jwks",
        expected_issuer="https://idp.example.com",
        expected_audience="test-client",
    )
    assert result.valid is True
    assert result.algorithm == "RS256"
    assert result.kid == "test-key-1"
    assert result.claims["sub"] == "user_001"


def test_g638_verify_id_token_full_flow_with_nonce(rsa_keypair, populate_jwks_cache):
    """H.G638 — verify_id_token validates nonce when supplied."""
    from prostanet.shared.jwt_verifier import verify_id_token
    token = _make_valid_jwt(rsa_keypair, nonce="my-nonce")
    result = verify_id_token(
        token,
        jwks_uri="http://test/jwks",
        expected_issuer="https://idp.example.com",
        expected_audience="test-client",
        expected_nonce="my-nonce",
    )
    assert result.valid is True


def test_g639_verify_id_token_nonce_mismatch_fails(rsa_keypair, populate_jwks_cache):
    """H.G639 — Nonce mismatch rejected."""
    from prostanet.shared.jwt_verifier import verify_id_token
    token = _make_valid_jwt(rsa_keypair, nonce="actual-nonce")
    result = verify_id_token(
        token,
        jwks_uri="http://test/jwks",
        expected_issuer="https://idp.example.com",
        expected_audience="test-client",
        expected_nonce="expected-nonce",
    )
    assert result.valid is False
    assert "nonce" in result.reason


def test_g640_verify_id_token_expired_fails(rsa_keypair, populate_jwks_cache):
    """H.G640 — Expired token rejected."""
    from prostanet.shared.jwt_verifier import verify_id_token
    token = _make_valid_jwt(
        rsa_keypair,
        exp=int(time.time()) - 7200,  # 2h ago
        iat=int(time.time()) - 10800,
    )
    result = verify_id_token(
        token,
        jwks_uri="http://test/jwks",
        expected_issuer="https://idp.example.com",
        expected_audience="test-client",
    )
    assert result.valid is False
    assert "expired" in result.reason


def test_g641_verify_id_token_issuer_mismatch_fails(rsa_keypair, populate_jwks_cache):
    """H.G641 — Issuer mismatch rejected."""
    from prostanet.shared.jwt_verifier import verify_id_token
    token = _make_valid_jwt(rsa_keypair, iss="https://attacker.com")
    result = verify_id_token(
        token,
        jwks_uri="http://test/jwks",
        expected_issuer="https://idp.example.com",
        expected_audience="test-client",
    )
    assert result.valid is False
    assert "iss mismatch" in result.reason


def test_g642_verify_id_token_audience_mismatch_fails(rsa_keypair, populate_jwks_cache):
    """H.G642 — Audience mismatch rejected."""
    from prostanet.shared.jwt_verifier import verify_id_token
    token = _make_valid_jwt(rsa_keypair, aud="other-client")
    result = verify_id_token(
        token,
        jwks_uri="http://test/jwks",
        expected_issuer="https://idp.example.com",
        expected_audience="test-client",
    )
    assert result.valid is False
    assert "aud mismatch" in result.reason


def test_g643_verify_id_token_no_jwks_uri_fails(rsa_keypair):
    """H.G643 — RS256 JWT without jwks_uri fails."""
    from prostanet.shared.jwt_verifier import verify_id_token
    token = _make_valid_jwt(rsa_keypair)
    result = verify_id_token(
        token,
        jwks_uri="",
        expected_issuer="https://idp.example.com",
        expected_audience="test-client",
    )
    assert result.valid is False
    assert "jwks_uri required" in result.reason


# ════════════════════════════════════════════════════════════════════
# §J. cryptography availability (H.G644-H.G645)
# ════════════════════════════════════════════════════════════════════


def test_g644_is_cryptography_available_returns_true():
    """H.G644 — In test env, cryptography should be available."""
    from prostanet.shared.jwt_verifier import is_cryptography_available
    assert is_cryptography_available() is True


def test_g645_cryptography_version_returns_string():
    """H.G645 — cryptography_version returns version string."""
    from prostanet.shared.jwt_verifier import cryptography_version
    v = cryptography_version()
    assert v
    assert "." in v


# ════════════════════════════════════════════════════════════════════
# §K. JWKS cache (H.G646-H.G648)
# ════════════════════════════════════════════════════════════════════


def test_g646_jwks_cache_reuses_after_first_fetch(populate_jwks_cache):
    """H.G646 — fetch_jwks reuses cached doc within TTL."""
    from prostanet.shared.jwt_verifier import fetch_jwks
    # Cache pre-populated
    doc1 = fetch_jwks("http://test/jwks")
    doc2 = fetch_jwks("http://test/jwks")
    assert doc1 is doc2  # same dict reference


def test_g647_jwks_cache_force_refresh_re_fetches(populate_jwks_cache, monkeypatch):
    """H.G647 — force_refresh=True bypasses cache."""
    from prostanet.shared.jwt_verifier import fetch_jwks, _JWKS_CACHE
    # Mock urllib.urlopen to detect re-fetch
    fetch_count = [0]

    class FakeResp:
        def __init__(self, body): self.body = body
        def read(self): return self.body
        def __enter__(self): return self
        def __exit__(self, *a): pass

    def fake_urlopen(req, timeout=10):
        fetch_count[0] += 1
        return FakeResp(json.dumps({"keys": [{"kid": "fresh"}]}).encode())

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    fetch_jwks("http://test/jwks", force_refresh=True)
    assert fetch_count[0] == 1


def test_g648_jwks_fetch_empty_uri_raises():
    """H.G648 — Empty jwks_uri raises ValueError."""
    from prostanet.shared.jwt_verifier import fetch_jwks
    with pytest.raises(ValueError, match="jwks_uri is required"):
        fetch_jwks("")


# ════════════════════════════════════════════════════════════════════
# §L. Hybrid resolver (JWT preferred, userinfo fallback) (H.G649-H.G655)
# ════════════════════════════════════════════════════════════════════


def test_g649_hybrid_uses_jwt_when_valid(rsa_keypair, populate_jwks_cache, monkeypatch):
    """H.G649 — Hybrid resolver uses JWT when valid."""
    from prostanet.shared.oidc_client import (
        OidcConfig, resolve_claims_with_jwt_or_userinfo,
    )
    config = OidcConfig(
        issuer="https://idp.example.com",
        client_id="test-client",
        verify_id_token=True,
    )
    discovery = {"jwks_uri": "http://test/jwks", "userinfo_endpoint": "http://test/userinfo"}
    token = _make_valid_jwt(rsa_keypair)
    result = resolve_claims_with_jwt_or_userinfo(
        config,
        id_token=token,
        access_token="any",
        discovery=discovery,
    )
    assert result.method == "jwt_verified"
    assert result.algorithm == "RS256"
    assert result.claims["sub"] == "user_001"


def test_g650_hybrid_falls_back_to_userinfo_when_jwt_invalid(
    rsa_keypair, populate_jwks_cache, monkeypatch,
):
    """H.G650 — Hybrid falls back to userinfo when JWT invalid."""
    from prostanet.shared.oidc_client import (
        OidcConfig, resolve_claims_with_jwt_or_userinfo,
    )

    # Mock fetch_userinfo to return canned data
    def fake_userinfo(config, token, discovery=None):
        return {"sub": "userinfo_user", "email": "u@x.com"}

    monkeypatch.setattr(
        "prostanet.shared.oidc_client.fetch_userinfo", fake_userinfo,
    )

    config = OidcConfig(
        issuer="https://idp.example.com",
        client_id="test-client",
        verify_id_token=True,
    )
    discovery = {"jwks_uri": "http://test/jwks", "userinfo_endpoint": "http://test/ui"}
    # Token with wrong audience → JWT verify fails
    bad_token = _make_valid_jwt(rsa_keypair, aud="wrong-client")
    result = resolve_claims_with_jwt_or_userinfo(
        config,
        id_token=bad_token,
        access_token="any",
        discovery=discovery,
    )
    assert result.method == "userinfo_fallback"
    assert "aud" in result.jwt_verify_reason or "claims_invalid" in result.jwt_verify_reason
    assert result.claims["sub"] == "userinfo_user"


def test_g651_hybrid_skips_jwt_when_disabled(monkeypatch):
    """H.G651 — verify_id_token=False skips JWT entirely → userinfo only."""
    from prostanet.shared.oidc_client import (
        OidcConfig, resolve_claims_with_jwt_or_userinfo,
    )

    def fake_userinfo(config, token, discovery=None):
        return {"sub": "u1"}

    monkeypatch.setattr(
        "prostanet.shared.oidc_client.fetch_userinfo", fake_userinfo,
    )

    config = OidcConfig(
        issuer="https://idp.example.com",
        client_id="x",
        verify_id_token=False,  # explicitly OFF
    )
    discovery = {"userinfo_endpoint": "http://test/ui", "jwks_uri": "x"}
    result = resolve_claims_with_jwt_or_userinfo(
        config,
        id_token="some-jwt",
        access_token="any",
        discovery=discovery,
    )
    assert result.method == "userinfo_fallback"
    assert "disabled" in result.jwt_verify_reason


def test_g652_hybrid_skips_jwt_when_no_id_token(monkeypatch):
    """H.G652 — Empty id_token → userinfo fallback."""
    from prostanet.shared.oidc_client import (
        OidcConfig, resolve_claims_with_jwt_or_userinfo,
    )

    def fake_userinfo(config, token, discovery=None):
        return {"sub": "u1"}

    monkeypatch.setattr(
        "prostanet.shared.oidc_client.fetch_userinfo", fake_userinfo,
    )

    config = OidcConfig(
        issuer="https://idp.example.com", client_id="x",
        verify_id_token=True,
    )
    discovery = {"userinfo_endpoint": "http://test/ui", "jwks_uri": "x"}
    result = resolve_claims_with_jwt_or_userinfo(
        config,
        id_token="",  # no id_token
        access_token="any",
        discovery=discovery,
    )
    assert result.method == "userinfo_fallback"
    assert "no id_token" in result.jwt_verify_reason


def test_g653_oidc_config_verify_id_token_default_true(monkeypatch):
    """H.G653 — OidcConfig.verify_id_token defaults to True."""
    monkeypatch.setenv("PROSTANET_OIDC_ISSUER", "https://x.com")
    monkeypatch.setenv("PROSTANET_OIDC_CLIENT_ID", "c")
    monkeypatch.delenv("PROSTANET_OIDC_VERIFY_ID_TOKEN", raising=False)
    from prostanet.shared.oidc_client import OidcConfig
    c = OidcConfig.from_env()
    assert c.verify_id_token is True


def test_g654_oidc_config_verify_id_token_can_disable(monkeypatch):
    """H.G654 — PROSTANET_OIDC_VERIFY_ID_TOKEN=false disables JWT verify."""
    monkeypatch.setenv("PROSTANET_OIDC_ISSUER", "https://x.com")
    monkeypatch.setenv("PROSTANET_OIDC_CLIENT_ID", "c")
    monkeypatch.setenv("PROSTANET_OIDC_VERIFY_ID_TOKEN", "false")
    from prostanet.shared.oidc_client import OidcConfig
    c = OidcConfig.from_env()
    assert c.verify_id_token is False


def test_g655_oidc_config_time_skew_configurable(monkeypatch):
    """H.G655 — PROSTANET_OIDC_TIME_SKEW_SEC is configurable."""
    monkeypatch.setenv("PROSTANET_OIDC_ISSUER", "https://x.com")
    monkeypatch.setenv("PROSTANET_OIDC_CLIENT_ID", "c")
    monkeypatch.setenv("PROSTANET_OIDC_TIME_SKEW_SEC", "120")
    from prostanet.shared.oidc_client import OidcConfig
    c = OidcConfig.from_env()
    assert c.time_skew_sec == 120


# ════════════════════════════════════════════════════════════════════
# §M. ParsedJwt structure + edge cases (H.G656-H.G660)
# ════════════════════════════════════════════════════════════════════


def test_g656_signing_input_format(rsa_keypair):
    """H.G656 — signing_input is bytes of header_b64.payload_b64."""
    from prostanet.shared.jwt_verifier import parse_jwt
    token = _make_valid_jwt(rsa_keypair)
    parsed = parse_jwt(token)
    assert isinstance(parsed.signing_input, bytes)
    assert b"." in parsed.signing_input


def test_g657_validate_claims_invalid_exp_type():
    """H.G657 — Non-numeric exp claim fails."""
    from prostanet.shared.jwt_verifier import validate_claims
    result = validate_claims({"sub": "u1", "exp": "not-a-number"})
    assert result.valid is False
    assert "exp must be number" in result.reason


def test_g658_validate_claims_nbf_in_future():
    """H.G658 — nbf in future fails."""
    from prostanet.shared.jwt_verifier import validate_claims
    result = validate_claims({
        "sub": "u1",
        "exp": time.time() + 7200,
        "nbf": time.time() + 3600,  # 1h in future
    }, time_skew_sec=30)
    assert result.valid is False
    assert "not yet valid" in result.reason


def test_g659_validate_claims_iat_in_future():
    """H.G659 — iat in future (beyond skew) fails."""
    from prostanet.shared.jwt_verifier import validate_claims
    result = validate_claims({
        "sub": "u1",
        "exp": time.time() + 7200,
        "iat": time.time() + 3600,
    }, time_skew_sec=30)
    assert result.valid is False
    assert "iat in future" in result.reason


def test_g660_jwt_verification_result_includes_metadata(rsa_keypair, populate_jwks_cache):
    """H.G660 — Successful verify includes algorithm + kid metadata."""
    from prostanet.shared.jwt_verifier import verify_id_token
    token = _make_valid_jwt(rsa_keypair, kid="test-key-1")
    result = verify_id_token(
        token,
        jwks_uri="http://test/jwks",
        expected_issuer="https://idp.example.com",
        expected_audience="test-client",
    )
    assert result.algorithm == "RS256"
    assert result.kid == "test-key-1"
    assert result.claims is not None
