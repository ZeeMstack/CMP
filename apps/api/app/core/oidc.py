"""OIDC API access-token verification (AUTH-001A).

Verifies a bearer *access* token intended for the CMP API's own resource
audience -- never an ID token, and never against a frontend OIDC client
ID (`oidc_audience` is the CMP API's own audience identifier). Produces
only an `AuthenticatedIdentity` (external identity facts); this module
has no concept of CMP users, tenants, or roles -- that resolution happens
one layer up, in `app.core.auth`.

No custom cryptography: signature/issuer/audience/expiry/not-before
verification is delegated entirely to PyJWT + cryptography (the standard,
maintained combination). This module owns only the JWKS fetch/cache/
refresh orchestration -- plain Python control flow, not cryptography --
so the "at most one bounded refresh on an unknown kid, never unbounded
retry" behavior is our own explicit, directly testable code rather than
an assumption about a third-party library's internal caching semantics.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from dataclasses import dataclass
from typing import Callable

import jwt

from app.core.settings import settings

# A finite, explicit, deliberately bounded network timeout -- no bearer-auth
# request may hang indefinitely waiting for the configured JWKS endpoint. A
# dedicated Settings field is not warranted here: this is an internal
# transport-level bound, not something an operator should be tuning per
# deployment (unlike the cache TTL/rotation-cooldown, which shape the
# request/discovery-latency tradeoff and are deliberately configurable).
_JWKS_FETCH_TIMEOUT_SECONDS = 5


class TokenVerificationError(Exception):
    """Raised for any bearer-token verification failure. The message is
    for logs/tests only -- callers (see app.core.auth) must translate this
    into a generic 401 and never surface the specific reason to a client,
    to avoid handing an attacker a verification oracle."""


@dataclass(frozen=True)
class AuthenticatedIdentity:
    """Verified external identity facts only -- deliberately excludes any
    notion of tenant or CMP role, and does not carry raw token claims.
    `email`/`email_verified` are optional: CMP resolves identity through
    (issuer, subject) only (see app.core.auth), never through email."""

    issuer: str
    subject: str
    email: str | None
    email_verified: bool | None


def _fetch_jwks_document(jwks_url: str) -> dict:
    """The only network call this module makes. A standalone,
    monkeypatchable function -- tests replace *this*, not the cache
    orchestration around it, so the bounded-refresh behavior itself is
    exercised for real against a fake transport, never skipped. A finite
    explicit timeout is mandatory: no bearer-auth request may hang
    indefinitely waiting for the configured JWKS endpoint."""
    with urllib.request.urlopen(jwks_url, timeout=_JWKS_FETCH_TIMEOUT_SECONDS) as response:  # noqa: S310 -- fixed, operator-configured URL, not user input
        return json.loads(response.read().decode("utf-8"))


def _parse_jwks_keys(document: object) -> dict[str, dict]:
    """Defensive parsing of a fetched JWKS document. Any malformed shape --
    a non-object document, a missing/non-list `keys`, or key entries that
    are not objects with a string `kid` -- must fail as a clean
    authentication failure (`TokenVerificationError`), never as an
    unhandled exception that would otherwise surface as a 500. Duplicate
    `kid`s: the last matching entry in the document wins, exactly like any
    dict-keyed lookup -- no special detection is needed, only that it never
    crashes."""
    if not isinstance(document, dict):
        raise TokenVerificationError("JWKS document is not a JSON object")
    keys = document.get("keys")
    if not isinstance(keys, list):
        raise TokenVerificationError("JWKS document is missing a 'keys' array")
    return {
        key["kid"]: key
        for key in keys
        if isinstance(key, dict) and isinstance(key.get("kid"), str) and key["kid"]
    }


class JWKSCache:
    """Caches the JWKS document for `settings.oidc_jwks_cache_ttl_seconds`.

    Thread-safe: every cache read/refresh happens under a single lock, so
    concurrent requests (FastAPI runs each synchronous dependency in a
    worker thread -- see `verify_bearer_token`'s docstring) coalesce onto
    one in-flight fetch rather than each independently hitting the network
    ("single-flight").

    On a `kid` miss against an otherwise-fresh cache, refreshes at most
    once per `settings.oidc_jwks_min_refresh_interval_seconds` cooldown --
    covers real key rotation (a newly-published key becomes discoverable
    without waiting for the full TTL to elapse) without letting a spray of
    unknown/invalid `kid`s force an independent outbound fetch per request.
    """

    def __init__(self, fetch: Callable[[str], dict] = _fetch_jwks_document) -> None:
        self._fetch = fetch
        self._keys_by_kid: dict[str, dict] = {}
        self._fetched_at: float | None = None
        self._last_rotation_refresh_at: float | None = None
        self._lock = threading.Lock()
        self.fetch_call_count = 0

    def _is_fresh(self) -> bool:
        return self._fetched_at is not None and (
            time.monotonic() - self._fetched_at
        ) < settings.oidc_jwks_cache_ttl_seconds

    def _rotation_cooldown_active(self) -> bool:
        return self._last_rotation_refresh_at is not None and (
            time.monotonic() - self._last_rotation_refresh_at
        ) < settings.oidc_jwks_min_refresh_interval_seconds

    def _refresh_locked(self) -> None:
        """Must only be called while holding `self._lock`."""
        if not settings.oidc_jwks_url:
            raise TokenVerificationError("OIDC_JWKS_URL is not configured")
        self.fetch_call_count += 1
        try:
            document = self._fetch(settings.oidc_jwks_url)
        except TokenVerificationError:
            raise
        except Exception as exc:
            # Network failure, timeout, or malformed JSON -- always a clean
            # auth failure, never an unhandled exception reaching the route.
            raise TokenVerificationError("Failed to fetch JWKS document") from exc
        self._keys_by_kid = _parse_jwks_keys(document)
        self._fetched_at = time.monotonic()

    def get_key(self, kid: str) -> dict:
        with self._lock:
            if not self._is_fresh():
                self._refresh_locked()
            if kid in self._keys_by_kid:
                return self._keys_by_kid[kid]
            # Bounded: at most one extra "rotation discovery" refresh per
            # cooldown window on a kid miss -- never an unbounded retry,
            # and never one outbound fetch per unknown-kid request.
            if not self._rotation_cooldown_active():
                self._refresh_locked()
                self._last_rotation_refresh_at = time.monotonic()
            if kid not in self._keys_by_kid:
                raise TokenVerificationError(f"Unknown signing key id: {kid!r}")
            return self._keys_by_kid[kid]

    def reset_for_testing(self, fetch: Callable[[str], dict] | None = None) -> None:
        """Test-only hook: clears cached state and, when `fetch` is given,
        replaces the fetch function too (the constructor default is bound
        once at import time, so monkeypatching the module-level
        `_fetch_jwks_document` function alone would not affect an
        already-constructed cache instance)."""
        with self._lock:
            self._keys_by_kid = {}
            self._fetched_at = None
            self._last_rotation_refresh_at = None
            self.fetch_call_count = 0
            if fetch is not None:
                self._fetch = fetch


jwks_cache = JWKSCache()


def verify_bearer_token(token: str) -> AuthenticatedIdentity:
    """Verifies signature, issuer, audience, expiration, and not-before
    (when present) against the configured allowlisted algorithms only.
    Raises `TokenVerificationError` on any failure -- callers must not
    translate the specific reason into anything visible to the client.

    This function (and everything it calls, including the blocking JWKS
    fetch) is a plain, synchronous function -- deliberately never
    `async def`. Every caller in this codebase reaches it only through a
    plain-`def` FastAPI dependency (`app.core.auth.require_tenant_context`
    / `require_authenticated_principal`), and FastAPI runs synchronous
    dependencies in a worker thread (`starlette.concurrency.run_in_threadpool`),
    never on the event loop. If this function or its callers were ever
    changed to `async def`, the blocking `urllib` call inside it would run
    directly on the event loop and stall every other in-flight request --
    see `tests/test_oidc_hardening.py` for a structural regression guard."""
    if not settings.oidc_issuer or not settings.oidc_audience or not settings.oidc_jwks_url:
        raise TokenVerificationError("OIDC bearer verification is not configured")

    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError as exc:
        raise TokenVerificationError("Malformed token header") from exc

    algorithm = header.get("alg")
    # Explicit allowlist, checked before any key lookup: rejects "none"
    # and any HMAC/shared-secret algorithm outright, regardless of what a
    # would-be JWKS entry might otherwise support.
    if algorithm not in settings.oidc_allowed_algorithms:
        raise TokenVerificationError(f"Disallowed algorithm: {algorithm!r}")

    kid = header.get("kid")
    if not kid:
        raise TokenVerificationError("Token header is missing 'kid'")

    jwk_data = jwks_cache.get_key(kid)
    try:
        signing_key = jwt.PyJWK(jwk_data, algorithm=algorithm)
    except jwt.PyJWKError as exc:
        raise TokenVerificationError("Unusable signing key") from exc

    try:
        claims = jwt.decode(
            token,
            key=signing_key.key,
            algorithms=settings.oidc_allowed_algorithms,
            audience=settings.oidc_audience,
            issuer=settings.oidc_issuer,
            leeway=settings.oidc_clock_skew_seconds,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except jwt.InvalidTokenError as exc:
        raise TokenVerificationError("Token failed verification") from exc

    subject = str(claims.get("sub", "")).strip()
    if not subject:
        raise TokenVerificationError("Token subject (sub) is empty")

    return AuthenticatedIdentity(
        issuer=str(claims["iss"]),
        subject=subject,
        email=claims.get("email"),
        email_verified=claims.get("email_verified"),
    )
