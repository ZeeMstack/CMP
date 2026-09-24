"""UX-OPS-001D (N03): complete, deterministic request identity for the four
operational Water write commands (Measurement, Nutrient Mix, Reservoir
Event, Water Delivery Event).

`client_command_id` is the lookup key; the fingerprint below is the
material payload it must match. Every material path/request fact
participates -- including farm scope, so one command can never replay
through another farm's path. Serialization is canonical JSON:

- `None` stays JSON `null`, never `""`, so a null note never collides with
  an empty-string note;
- timezone-aware instants are normalized to UTC ISO-8601, so the same
  instant expressed in a different offset fingerprints identically, while
  a `None` "server now" sentinel stays `null` (never the resolved time);
- decimals are normalized numerically (`6.10` == `6.1`, the same fact the
  `Numeric` column persists), never via float;
- list order (Mix inputs) is preserved.

The PILOT-WATER-001A fingerprints omitted several of these facts. Rows
already recorded under that legacy calculation are never rewritten; see
`is_replay` for the bounded legacy replay path."""

import hashlib
import json
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal


def canonical_instant(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(timezone.utc).isoformat()


def canonical_decimal(value: object) -> str | None:
    if value is None:
        return None
    normalized = Decimal(str(value)).normalize()
    # `normalize()` may produce exponent notation (1E+2); fixed-point keeps
    # one textual form per numeric value.
    return format(normalized, "f")


def canonical_uuid(value: uuid.UUID | str | None) -> str | None:
    return None if value is None else str(value)


def complete_fingerprint(command: str, payload: dict) -> str:
    """`payload` must already be canonical (strings/None/ints/lists/dicts)."""
    body = {"command": command, **payload}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def legacy_fingerprint(*parts: object) -> str:
    """The PILOT-WATER-001A calculation, byte-for-byte -- used ONLY to
    recognize rows recorded before N03. Never stored for a new command."""
    return hashlib.sha256("|".join("" if p is None else str(p) for p in parts).encode("utf-8")).hexdigest()


def decimals_equal(a: object, b: object) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return Decimal(str(a)) == Decimal(str(b))


def instants_equal(persisted: datetime | None, requested: datetime | None) -> bool:
    if persisted is None or requested is None:
        return persisted is None and requested is None
    return persisted == requested


def effective_time_matches(persisted: datetime, requested: datetime | None) -> bool:
    """A requested `None` is the "server now" sentinel: the original row's
    effective time was resolved by the server, so any persisted instant is
    the one that command produced. The legacy fingerprint (which encoded
    the sentinel as `""`) has already proven the original request was also
    `None` before this is consulted."""
    return True if requested is None else persisted == requested


def is_replay(
    *, stored_fingerprint: str, complete: str, legacy: str, persisted_facts_match: Callable[[], bool]
) -> bool:
    """Same command + same complete payload -> replay.

    Bounded legacy path: a row whose stored fingerprint equals the legacy
    calculation for THIS request replays only when every persisted header
    (and child) fact -- including the fields the legacy fingerprint
    omitted -- equals the request; a difference in a formerly omitted
    field is a conflict. Anything else is a conflict."""
    if stored_fingerprint == complete:
        return True
    if stored_fingerprint == legacy:
        return persisted_facts_match()
    return False
