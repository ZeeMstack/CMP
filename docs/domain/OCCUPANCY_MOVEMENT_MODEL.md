# Occupancy and Movement Model

Full detail: `CMP_MASTER_SPEC.md` §5–§6; `CLAUDE.md` rules 5–6, 10. This document summarizes the approved semantics; it does not restate the spec.

## Occupancy

A batch may occupy several carriers and locations at once. The system maintains **active occupancy plus history** — it never relies only on a single `current_location_id` field (`CLAUDE.md` rule 5). Occupancy supports exclusive positions, quantity capacity, partial occupancy, effective and recorded timestamps, and availability/history queries (spec §5).

## Movement vs transformation

- **Movement**: the same entity changes location. Identity is preserved.
- **Transformation**: inputs are converted into outputs (see `AUDIT_MODEL.md` for reconciliation rules).

These are distinct command types (`CLAUDE.md` rule 6) and must not be conflated in the API — movement is never expressed as a generic `PATCH` (`CLAUDE.md` "API and Offline Rules").

## Movement command validation

Before commit, a movement command validates: tenant and farm access; active source occupancy; allowed destination type/status; capacity and sanitation/release; workflow permission and approval; and duplicate/idempotent submission (spec §6). The movement, occupancy changes, and audit event commit atomically. Corrections use reversal plus a corrected movement — never a rewrite of history (`AUDIT_MODEL.md`).

## Idempotency

Every command (including movement) carries a client-generated UUID idempotency key. The server enforces uniqueness **per tenant and per command type** — a duplicate submission of the same key for the same tenant/command type is rejected or returns the original result rather than re-executing (`docs/adr/007-client-generated-idempotency.md`). Offline UI states are `queued`, `synchronized`, `rejected`, `needs attention`; queued work is never shown as server-confirmed.
