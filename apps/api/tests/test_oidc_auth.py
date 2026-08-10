"""AUTH-001A bearer-token verification matrix (`app.core.oidc`). Fully
offline/deterministic -- see tests/_oidc_test_support.py. Exercises real
signature verification against a real (test-generated) RSA keypair; no
step here bypasses cryptographic verification to make the test easier."""

import pytest

from app.core import oidc
from app.core.oidc import TokenVerificationError, verify_bearer_token
from tests._oidc_test_support import (
    KID_PRIMARY,
    KID_SECONDARY,
    TEST_ISSUER,
    configured_oidc,  # noqa: F401 -- pytest fixture, used via parameter name
    mint_hs256_token,
    mint_none_alg_token,
    mint_token,
    secondary_signing_key,
    untrusted_signing_key,
)


def test_valid_token_resolves_to_authenticated_identity(configured_oidc) -> None:
    token = mint_token(subject="user-001", email="a@example.com", email_verified=True)
    identity = verify_bearer_token(token)
    assert identity.issuer == TEST_ISSUER
    assert identity.subject == "user-001"
    assert identity.email == "a@example.com"
    assert identity.email_verified is True


def test_token_without_email_still_verifies(configured_oidc) -> None:
    token = mint_token(subject="user-002", email=None, email_verified=None)
    identity = verify_bearer_token(token)
    assert identity.subject == "user-002"
    assert identity.email is None


def test_wrong_issuer_rejected(configured_oidc) -> None:
    token = mint_token(issuer="https://not-our-issuer.example")
    with pytest.raises(TokenVerificationError):
        verify_bearer_token(token)


def test_wrong_audience_rejected(configured_oidc) -> None:
    token = mint_token(audience="some-other-audience")
    with pytest.raises(TokenVerificationError):
        verify_bearer_token(token)


def test_expired_token_rejected(configured_oidc) -> None:
    token = mint_token(expires_in_seconds=-3600)
    with pytest.raises(TokenVerificationError):
        verify_bearer_token(token)


def test_not_yet_valid_token_rejected(configured_oidc) -> None:
    token = mint_token(not_before_delta_seconds=3600)
    with pytest.raises(TokenVerificationError):
        verify_bearer_token(token)


def test_not_before_within_clock_skew_is_accepted(configured_oidc) -> None:
    # 30s in the future, well within the configured 60s leeway.
    token = mint_token(not_before_delta_seconds=30)
    identity = verify_bearer_token(token)
    assert identity.subject is not None


def test_invalid_signature_rejected(configured_oidc) -> None:
    # A real, well-formed signature -- just from a key never published in
    # any JWKS document the verifier trusts.
    token = mint_token(signing_key=untrusted_signing_key())
    with pytest.raises(TokenVerificationError):
        verify_bearer_token(token)


def test_disallowed_hmac_algorithm_rejected(configured_oidc) -> None:
    token = mint_hs256_token()
    with pytest.raises(TokenVerificationError):
        verify_bearer_token(token)


def test_none_algorithm_rejected(configured_oidc) -> None:
    token = mint_none_alg_token()
    with pytest.raises(TokenVerificationError):
        verify_bearer_token(token)


def test_missing_subject_rejected(configured_oidc) -> None:
    token = mint_token(subject=None)
    with pytest.raises(TokenVerificationError):
        verify_bearer_token(token)


def test_empty_subject_rejected(configured_oidc) -> None:
    token = mint_token(subject="   ")
    with pytest.raises(TokenVerificationError):
        verify_bearer_token(token)


def test_missing_exp_rejected(configured_oidc) -> None:
    token = mint_token(omit_exp=True)
    with pytest.raises(TokenVerificationError):
        verify_bearer_token(token)


def test_malformed_jwt_rejected(configured_oidc) -> None:
    with pytest.raises(TokenVerificationError):
        verify_bearer_token("not-a-jwt-at-all")


def test_unknown_kid_triggers_one_bounded_refresh_then_fails(configured_oidc) -> None:
    token = mint_token(kid="totally-unknown-kid")
    with pytest.raises(TokenVerificationError):
        verify_bearer_token(token)
    # Exactly one refresh attempt: the initial miss forces a fetch, the
    # still-missing kid forces exactly one more -- never an unbounded loop.
    assert oidc.jwks_cache.fetch_call_count == 2


def test_key_rotation_succeeds_once_the_refreshed_jwks_contains_the_key(configured_oidc, monkeypatch) -> None:
    # Prime the cache with a primary-only JWKS fetch (simulates the
    # verifier having started up before the new key existed).
    verify_bearer_token(mint_token(kid=KID_PRIMARY))
    assert oidc.jwks_cache.fetch_call_count == 1

    # Simulate the secondary key rotating in at the provider *after* our
    # cache was primed. A token using it is unknown on the cached
    # snapshot, but present once the bounded refresh re-fetches.
    monkeypatch.setitem(configured_oidc, "include_secondary", True)
    token = mint_token(kid=KID_SECONDARY, signing_key=secondary_signing_key())
    identity = verify_bearer_token(token)
    assert identity.subject is not None
    # The kid miss forces exactly one bounded refresh -- two fetches
    # total across this test, never an unbounded retry loop.
    assert oidc.jwks_cache.fetch_call_count == 2


def test_cached_jwks_avoids_a_fetch_on_every_request(configured_oidc) -> None:
    token = mint_token()
    verify_bearer_token(token)
    first_count = oidc.jwks_cache.fetch_call_count
    verify_bearer_token(token)
    second_count = oidc.jwks_cache.fetch_call_count
    assert first_count == 1
    assert second_count == 1


def test_not_configured_raises_verification_error(monkeypatch) -> None:
    monkeypatch.setattr(oidc.settings, "oidc_issuer", None)
    monkeypatch.setattr(oidc.settings, "oidc_audience", None)
    monkeypatch.setattr(oidc.settings, "oidc_jwks_url", None)
    with pytest.raises(TokenVerificationError):
        verify_bearer_token(mint_token())
