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

## Occupancy and movement engine (implemented, CMP-006)

**Occupant and target.** An occupancy row refers to exactly one occupant (an asset **or** a carrier, never both) and exactly one target (a fixed location **or** an asset-relative position, never both), enforced by CHECK constraints. `assets`/`carriers`/`locations` carry no `current_location_id` — occupancy is the only source of placement, current and historical.

**Exclusivity.** Four partial unique indexes (`WHERE end_time IS NULL`) enforce one active occupancy per asset, one per carrier, one active occupant per location, one per asset position. This is the authoritative race-condition backstop, not the application layer.

**Compatibility.** A global, seeded `occupancy_compatibility_rules` table (same style as `location_type_hierarchy_rules`) lists which occupant type may occupy which target type/position-kind — e.g. `germination_trolley → chamber_position`, `seed_tray → slot`, `grow_bag → grow_bag_position`. Four partial unique indexes cover each occupant-kind × target-kind shape. Enforced in the service layer and, as a backstop, by a PostgreSQL trigger on `occupancies` insert.

**Movement command.** `POST /farms/{farm_id}/movements` is the only write path — there is no direct occupancy-insertion endpoint. One command covers placement (no prior occupancy), a normal move (closes the old occupancy, opens a new one), and removal (closes only, no destination); the source is always server-derived from the occupant's current active occupancy and is never accepted from the client. Movements are immutable (insert-only, enforced by trigger) and carry a client-generated `client_command_id`; uniqueness is enforced per `(tenant_id, command_type, client_command_id)`. A retried command with an identical payload returns the original movement; the same id with a different payload is rejected. Concurrent duplicate submissions are resolved the same way once serialized by the occupant row lock.

**Closing an occupancy** is the only update an occupancy row ever receives, and only transitions `end_time`/`closed_by_movement_id` together from NULL to populated — enforced by a trigger, since "which columns changed" and "was it already closed" both require comparing OLD and NEW, not expressible as a CHECK.

**Derived location.** Reading an occupant's resolved location never touches occupancy rows other than its own: an asset resolves directly through its fixed-location path; a carrier in an asset position resolves its relative position path, then separately looks up the *containing asset's own* active occupancy to continue into the fixed-location path — reporting an explicit unresolved reason if the containing asset isn't placed anywhere, rather than fabricating one. Moving the containing asset never touches the carrier's occupancy row.

**Deferred:** crop batches, transformations, QR/scan identity, maintenance, multi-capacity targets, and location reparenting all remain out of scope.
