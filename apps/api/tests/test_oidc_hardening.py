"""AUTH-001A production-security/operational hardening review (pre-commit).
Covers: event-loop safety of the blocking JWKS call chain, the explicit
network timeout, JWKS-cache thread-safety/single-flight behavior, bounded
outbound-request cost under an unknown-kid spray, and defensive parsing of
a malformed JWKS document. Fully offline/deterministic -- see
tests/_oidc_test_support.py."""

import inspect
import threading
import uuid
from unittest.mock import patch

import pytest

from app.core import oidc
from app.core.auth import require_authenticated_principal, require_tenant_context
from app.core.oidc import (
    TokenVerificationError,
    _fetch_jwks_document,
    _JWKS_FETCH_TIMEOUT_SECONDS,
    _parse_jwks_keys,
    verify_bearer_token,
)
from app.core.settings import settings
from tests._oidc_test_support import (
    KID_PRIMARY,
    configured_oidc,  # noqa: F401
    mint_token,
)


# --- 1. Event-loop safety: structural guardrails ----------------------------


def test_auth_dependencies_and_token_verification_are_synchronous() -> None:
    """FastAPI only offloads *synchronous* (`def`, not `async def`)
    dependencies to a worker thread. If any of these were ever converted to
    `async def` while still calling the blocking `urllib` JWKS fetch, that
    call would execute directly on the event loop and stall every other
    in-flight request."""
    assert not inspect.iscoroutinefunction(require_tenant_context)
    assert not inspect.iscoroutinefunction(require_authenticated_principal)
    assert not inspect.iscoroutinefunction(verify_bearer_token)
    assert not inspect.iscoroutinefunction(_fetch_jwks_document)


def test_no_app_owned_route_handler_is_a_coroutine_function() -> None:
    """Every CMP-owned route handler (under `app.api.*`) is deliberately
    synchronous end-to-end, so every dependency it pulls in -- including
    the auth chain -- runs in FastAPI's worker threadpool, never on the
    event loop. Scoped to our own route modules only: FastAPI's built-in
    `/docs`/`/redoc`/`/openapi.json` handlers are legitimately async and
    never touch our sync business logic or the JWKS fetch."""
    from app.main import app

    offending = [
        route.path
        for route in app.routes
        if hasattr(route, "endpoint")
        and getattr(route.endpoint, "__module__", "").startswith("app.api")
        and inspect.iscoroutinefunction(route.endpoint)
    ]
    assert offending == []


# --- 2. JWKS network timeout -------------------------------------------------


def test_jwks_fetch_passes_an_explicit_finite_timeout() -> None:
    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def read(self):
            return b'{"keys": []}'

    with patch("app.core.oidc.urllib.request.urlopen", return_value=_FakeResponse()) as mock_urlopen:
        _fetch_jwks_document("https://issuer.test.example/.well-known/jwks.json")

    assert mock_urlopen.call_count == 1
    _args, kwargs = mock_urlopen.call_args
    assert kwargs.get("timeout") == _JWKS_FETCH_TIMEOUT_SECONDS
    assert isinstance(_JWKS_FETCH_TIMEOUT_SECONDS, (int, float)) and _JWKS_FETCH_TIMEOUT_SECONDS > 0


# --- 3 & 4. Cache concurrency safety + unknown-kid abuse ---------------------


def test_unknown_kid_spray_does_not_amplify_outbound_fetches(configured_oidc) -> None:
    """A burst of distinct unknown `kid`s in quick succession must not each
    force an independent network call once the cache has already attempted
    rotation discovery once within the cooldown window."""
    for _ in range(8):
        with pytest.raises(TokenVerificationError):
            verify_bearer_token(mint_token(kid=f"spray-{uuid.uuid4().hex}"))
    # Exactly two: the initial cold-cache refresh, plus one bounded
    # rotation-discovery refresh -- never one per sprayed kid.
    assert oidc.jwks_cache.fetch_call_count == 2


def test_rotation_cooldown_expiring_allows_a_further_discovery_refresh(configured_oidc) -> None:
    verify_bearer_token(mint_token(kid=KID_PRIMARY))  # fetch #1: primes a fresh cache
    assert oidc.jwks_cache.fetch_call_count == 1

    with pytest.raises(TokenVerificationError):
        verify_bearer_token(mint_token(kid="still-unknown-a"))  # fetch #2: rotation discovery
    assert oidc.jwks_cache.fetch_call_count == 2

    with pytest.raises(TokenVerificationError):
        verify_bearer_token(mint_token(kid="still-unknown-b"))  # within cooldown: no new fetch
    assert oidc.jwks_cache.fetch_call_count == 2

    # Simulate the cooldown window having fully elapsed.
    oidc.jwks_cache._last_rotation_refresh_at -= settings.oidc_jwks_min_refresh_interval_seconds + 1
    with pytest.raises(TokenVerificationError):
        verify_bearer_token(mint_token(kid="still-unknown-c"))  # cooldown expired: fetch #3
    assert oidc.jwks_cache.fetch_call_count == 3


def test_concurrent_unknown_kid_requests_coalesce_into_a_bounded_fetch_count(configured_oidc) -> None:
    """20 threads racing on the same unknown kid must still coalesce onto
    the same bounded refresh count as a single caller -- proving the lock
    prevents a concurrent stampede, not just a sequential one."""
    thread_count = 20
    barrier = threading.Barrier(thread_count)
    errors: list[BaseException] = []

    def worker() -> None:
        barrier.wait()
        try:
            verify_bearer_token(mint_token(kid="concurrent-unknown-kid"))
        except TokenVerificationError:
            pass
        except BaseException as exc:  # noqa: BLE001 -- captured for the assertion below, not swallowed
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(thread_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert oidc.jwks_cache.fetch_call_count == 2


def test_concurrent_valid_token_requests_share_a_single_cold_start_fetch(configured_oidc) -> None:
    """A cold-cache stampede of *valid*-token requests must also coalesce
    onto one fetch, not one per concurrent caller."""
    thread_count = 20
    barrier = threading.Barrier(thread_count)
    results: list[object] = []
    errors: list[BaseException] = []

    def worker() -> None:
        barrier.wait()
        try:
            results.append(verify_bearer_token(mint_token(kid=KID_PRIMARY)))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(thread_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert len(results) == thread_count
    assert oidc.jwks_cache.fetch_call_count == 1


# --- 8. Malformed JWKS response validation -----------------------------------


def test_non_object_jwks_document_is_a_clean_auth_failure() -> None:
    with pytest.raises(TokenVerificationError):
        _parse_jwks_keys(["not", "an", "object"])
    with pytest.raises(TokenVerificationError):
        _parse_jwks_keys("also not an object")
    with pytest.raises(TokenVerificationError):
        _parse_jwks_keys(None)


def test_missing_or_non_list_keys_field_is_a_clean_auth_failure() -> None:
    with pytest.raises(TokenVerificationError):
        _parse_jwks_keys({})
    with pytest.raises(TokenVerificationError):
        _parse_jwks_keys({"keys": "not-a-list"})
    with pytest.raises(TokenVerificationError):
        _parse_jwks_keys({"keys": {"kid": "x"}})


def test_malformed_key_entries_are_skipped_not_crashed_on() -> None:
    result = _parse_jwks_keys(
        {
            "keys": [
                "not-a-dict",
                {"no": "kid-field"},
                {"kid": 12345},
                {"kid": ""},
                {"kid": "valid-one", "kty": "RSA"},
            ]
        }
    )
    assert result == {"valid-one": {"kid": "valid-one", "kty": "RSA"}}


def test_duplicate_kid_last_entry_wins_without_crashing() -> None:
    result = _parse_jwks_keys(
        {
            "keys": [
                {"kid": "dup", "kty": "RSA", "n": "first"},
                {"kid": "dup", "kty": "RSA", "n": "second"},
            ]
        }
    )
    assert result["dup"]["n"] == "second"


def test_malformed_jwks_document_from_the_network_fails_verification_not_500(configured_oidc) -> None:
    oidc.jwks_cache.reset_for_testing(fetch=lambda url: {"not": "a keys document"})
    with pytest.raises(TokenVerificationError):
        verify_bearer_token(mint_token(kid=KID_PRIMARY))


def test_fetch_raising_a_transport_error_is_translated_to_verification_error(configured_oidc) -> None:
    def _broken_fetch(url: str) -> dict:
        raise OSError("connection refused")

    oidc.jwks_cache.reset_for_testing(fetch=_broken_fetch)
    with pytest.raises(TokenVerificationError):
        verify_bearer_token(mint_token(kid=KID_PRIMARY))


def test_fetch_returning_unparseable_json_shape_is_translated_to_verification_error(configured_oidc) -> None:
    def _bad_shape_fetch(url: str) -> dict:
        raise ValueError("Expecting value: line 1 column 1 (char 0)")

    oidc.jwks_cache.reset_for_testing(fetch=_bad_shape_fetch)
    with pytest.raises(TokenVerificationError):
        verify_bearer_token(mint_token(kid=KID_PRIMARY))


# --- 9. Cache clock source (already correct -- regression guard only) -------


def test_cache_freshness_is_governed_by_monotonic_elapsed_time(configured_oidc) -> None:
    """Behavioral (not just code-inspection) proof that TTL freshness is
    computed from `time.monotonic()`: driving a controllable fake monotonic
    clock forward past the configured TTL is what triggers the next fetch --
    the real wall clock is never consulted at all in this path."""
    fake_now = [1_000_000.0]
    with patch("app.core.oidc.time.monotonic", side_effect=lambda: fake_now[0]):
        verify_bearer_token(mint_token(kid=KID_PRIMARY))
        assert oidc.jwks_cache.fetch_call_count == 1

        # Well within the TTL: still fresh, no new fetch.
        fake_now[0] += 1
        verify_bearer_token(mint_token(kid=KID_PRIMARY))
        assert oidc.jwks_cache.fetch_call_count == 1

        # Past the configured TTL: now stale, forces a fresh fetch.
        fake_now[0] += settings.oidc_jwks_cache_ttl_seconds + 1
        verify_bearer_token(mint_token(kid=KID_PRIMARY))
        assert oidc.jwks_cache.fetch_call_count == 2
