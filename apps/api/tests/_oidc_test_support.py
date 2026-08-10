"""Deterministic, offline OIDC test support (AUTH-001A). No live IdP, no
network access -- a real RSA keypair is generated once per test session,
test tokens are signed for real (genuine signature verification is
exercised, never bypassed), and JWKS "fetches" are served from an
in-memory document via monkeypatching `app.core.oidc._fetch_jwks_document`.
Not a test file itself (pytest's default `test_*.py` glob does not match
this name)."""

import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from app.core import oidc

TEST_ISSUER = "https://issuer.test.example"
TEST_AUDIENCE = "cmp-api-test"
TEST_JWKS_URL = "https://issuer.test.example/.well-known/jwks.json"
KID_PRIMARY = "test-key-primary"
KID_SECONDARY = "test-key-secondary"

_PRIMARY_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_SECONDARY_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
# A third keypair whose public half is deliberately never published in any
# JWKS document below -- used to mint a token with a genuinely invalid
# signature (a real, well-formed-but-wrong signature, not a corrupted string).
_UNTRUSTED_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwk_for(key: rsa.RSAPrivateKey, kid: str) -> dict:
    jwk = RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    jwk["kid"] = kid
    jwk["alg"] = "RS256"
    jwk["use"] = "sig"
    return jwk


def jwks_document(*, include_secondary: bool = False) -> dict:
    keys = [_jwk_for(_PRIMARY_KEY, KID_PRIMARY)]
    if include_secondary:
        keys.append(_jwk_for(_SECONDARY_KEY, KID_SECONDARY))
    return {"keys": keys}


def mint_token(
    *,
    issuer: str = TEST_ISSUER,
    audience: str = TEST_AUDIENCE,
    subject: str | None = "user-subject-001",
    kid: str | None = KID_PRIMARY,
    algorithm: str = "RS256",
    signing_key: rsa.RSAPrivateKey | None = None,
    expires_in_seconds: int | None = 300,
    not_before_delta_seconds: int | None = None,
    email: str | None = "person@example.com",
    email_verified: bool | None = True,
    extra_claims: dict | None = None,
    omit_exp: bool = False,
) -> str:
    """Mints a real, signed test token. `signing_key` defaults to the
    primary trusted key; pass `_UNTRUSTED_KEY` to produce a token whose
    signature genuinely does not verify against any published JWKS key."""
    key = signing_key if signing_key is not None else _PRIMARY_KEY
    now = int(time.time())
    claims: dict = {"iss": issuer, "aud": audience, "iat": now}
    if subject is not None:
        claims["sub"] = subject
    if not omit_exp and expires_in_seconds is not None:
        claims["exp"] = now + expires_in_seconds
    if not_before_delta_seconds is not None:
        claims["nbf"] = now + not_before_delta_seconds
    if email is not None:
        claims["email"] = email
    if email_verified is not None:
        claims["email_verified"] = email_verified
    if extra_claims:
        claims.update(extra_claims)

    headers = {"kid": kid} if kid is not None else {}
    return jwt.encode(claims, key, algorithm=algorithm, headers=headers)


def mint_hs256_token(*, issuer: str = TEST_ISSUER, audience: str = TEST_AUDIENCE, subject: str = "user-subject-001") -> str:
    """A token signed with a symmetric algorithm -- must always be
    rejected by the allowlist before any key lookup even happens."""
    now = int(time.time())
    return jwt.encode(
        {"iss": issuer, "aud": audience, "sub": subject, "iat": now, "exp": now + 300},
        "shared-secret-not-a-real-key-but-long-enough-for-hmac-sha256",
        algorithm="HS256",
        headers={"kid": "irrelevant"},
    )


def mint_none_alg_token(*, issuer: str = TEST_ISSUER, audience: str = TEST_AUDIENCE, subject: str = "user-subject-001") -> str:
    """`alg: none` -- must always be rejected by the allowlist."""
    now = int(time.time())
    return jwt.encode(
        {"iss": issuer, "aud": audience, "sub": subject, "iat": now, "exp": now + 300},
        key=None,
        algorithm="none",
    )


def untrusted_signing_key() -> rsa.RSAPrivateKey:
    return _UNTRUSTED_KEY


def secondary_signing_key() -> rsa.RSAPrivateKey:
    return _SECONDARY_KEY


def unique_subject() -> str:
    return f"subject-{uuid.uuid4().hex[:12]}"


@pytest.fixture
def configured_oidc(monkeypatch):
    """Configures real-auth settings and points the JWKS cache at an
    in-memory fetch function -- no network call, ever, in any test that
    uses this fixture. Shared across test files (imported, not
    redefined) so every bearer-auth test exercises the exact same
    configuration/caching contract."""
    monkeypatch.setattr(oidc.settings, "oidc_issuer", TEST_ISSUER)
    monkeypatch.setattr(oidc.settings, "oidc_audience", TEST_AUDIENCE)
    monkeypatch.setattr(oidc.settings, "oidc_jwks_url", TEST_JWKS_URL)
    monkeypatch.setattr(oidc.settings, "oidc_allowed_algorithms", ["RS256"])
    monkeypatch.setattr(oidc.settings, "oidc_clock_skew_seconds", 60)
    monkeypatch.setattr(oidc.settings, "oidc_jwks_cache_ttl_seconds", 300)

    calls = {"count": 0}

    def fake_fetch(url: str) -> dict:
        calls["count"] += 1
        return jwks_document(include_secondary=calls.get("include_secondary", False))

    oidc.jwks_cache.reset_for_testing(fetch=fake_fetch)
    yield calls
    oidc.jwks_cache.reset_for_testing()


def bearer_headers(**mint_kwargs) -> dict[str, str]:
    """Convenience: mints a token and wraps it as a ready-to-send
    Authorization header dict."""
    return {"Authorization": f"Bearer {mint_token(**mint_kwargs)}"}
