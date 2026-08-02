# ADR 005: Active Occupancy Plus Immutable History

## Context

A batch can occupy several carriers and locations over time, and can move between them repeatedly. CMP must be able to answer both "where is this now" and "where has this been," and must never lose or silently rewrite that history — traceability is the platform's core promise.

## Decision

Maintain occupancy as active occupancy records plus a full history of past occupancy periods, rather than only a mutable `current_location_id` field. Production, inventory, quality, movement, transformation, harvest, pack, cold-store, dispatch, label, and audit history are never hard-deleted or rewritten; corrections are made through reversal/void plus a new transaction.

## Consequences

- "Current location" queries read the active occupancy record(s); "history" queries read closed occupancy periods — both are first-class, not derived from a single mutable pointer.
- Every correction produces new records (reversal + new transaction) rather than mutating existing ones, which grows history size over time but preserves full auditability.
- Application code must never provide a path that updates a location pointer in place without also writing/closing occupancy and audit records.

## Rejected alternatives

- **Mutable current-state-only model** (single `current_location_id` field, overwritten on each move) — rejected: cannot represent multi-location/multi-carrier occupancy, loses history needed for traceability and recall, and conflicts directly with `CLAUDE.md` rules 5 and 7.
