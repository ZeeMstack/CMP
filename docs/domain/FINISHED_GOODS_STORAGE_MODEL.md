# Cold-Store Location and Finished-Goods Physical Occupancy Foundation

Full detail: `CMP_MASTER_SPEC.md` §3.4, §10; `CLAUDE.md` rules 1, 3, 4, 5, 6, 7, 8, 10, 12. This document summarizes the approved model as implemented in CMP-018; it does not restate the spec.

## Scope

CMP-017's finished-goods ledger answers *how much* commercially available finished-goods inventory a lot has. CMP-018 answers a genuinely separate question — *where* that inventory is physically sitting — without ever touching commercial quantity. A storage movement (`place`, `transfer`, `release`) records physical relocation only; it never creates, destroys, dispatches, receives, adjusts, or values commercial inventory. `finished_goods_lots` gains no `location_id` — a lot may be split across several locations at once, and physical placement is a strict subset of (never more than) the lot's own commercial availability. Out of scope: sales orders, customers, reservations, allocations, FIFO/FEFO, pallets, cartons, storage capacity, pricing, invoicing, transport, delivery confirmation, corrections, reversals, adjustments, valuation, frontend functionality, RLS, role-specific authorization.

## Location reuse

No location *type* or *hierarchy* change. `cold_store` (farm-root) → `cold_store_position` (occupiable leaf) was already seeded by CMP-004 with zero code touching `location_types`/`location_type_hierarchy_rules` before this ticket, and neither table is touched by CMP-018 either. A location is storage-eligible exactly when its `location_type.code = 'cold_store_position'`. This is *not* the same as "zero schema change to `locations`": CMP-018 does add one narrow composite `UNIQUE(tenant_id, farm_id, id)` constraint (`uq_locations_tenant_farm_id`) to the `locations` table itself, purely so source/destination location references can use real composite foreign keys — see "Storage movement table" and "Migration and downgrade" below. No column is added, removed, or retyped on `locations`, and no existing location row is touched. The existing `Occupancy`/`Movement`/`occupancy_compatibility_rules` tables are deliberately untouched: direct inspection confirmed they model exclusive, identity-only occupancy (asset XOR carrier, one active occupant per target via partial unique indexes) — structurally incompatible with quantity-bearing, multi-lot-per-location, multi-location-per-lot placement. `finished_goods_storage_movements` is an independent new table, not a reuse of that model.

## Storage movement table

One append-only table, `finished_goods_storage_movements`: `id`, `tenant_id`, `farm_id`, `finished_goods_lot_id`, `movement_kind`, `source_location_id` (nullable), `destination_location_id` (nullable), `moved_weight_kg`, `moved_package_count`, `effective_time`, `recorded_time` (server-generated), `actor_user_id`, `client_command_id`, `request_fingerprint`, an optional `note`. `movement_kind` is exactly one of `place` (unplaced → destination), `transfer` (source → destination), `release` (source → unplaced); a CHECK enforces the corresponding NULL/NOT-NULL shape exactly, including `source_location_id <> destination_location_id` for `transfer`. Weight is strictly positive, at most three decimal places, bounded below 100000000000; package count is a strictly positive `BIGINT`, never inferred from weight. `UPDATE` and `DELETE` are rejected by the same `reject_append_only_mutation`/`reject_hard_delete` triggers used everywhere else in this codebase. Composite foreign keys tie `(tenant_id, farm_id, finished_goods_lot_id)` to `finished_goods_lots` and `(tenant_id, farm_id, source/destination_location_id)` to a new `uq_locations_tenant_farm_id` composite unique on `locations` — the first ticket to add this idiom to `locations`, extending the same pattern already used for `finished_goods_lots`/`packing_events`/`dispatch_events`/`dispatch_lines`.

## Unplaced quantity — always derived, never stored

There is no "unplaced" location row and no stored balance column anywhere. `total_placed(lot) = SUM(weight WHERE kind='place') − SUM(weight WHERE kind='release')`; transfers cancel out of this total by construction, since they only relocate. `unplaced = available(lot) − total_placed(lot)`, where `available` is CMP-017's own `SUM(weight_delta_kg)` over `finished_goods_ledger_entries`. A location's own balance is `SUM(weight arriving) − SUM(weight leaving)` for that location. The exact same SQL shape is expressed twice — once in `finished_goods_storage_service`, once in the immediate insert-integrity trigger's PL/pgSQL — never as a view or a mutable column, so there is nothing to keep in sync.

## Source versus destination eligibility — deliberately asymmetric

A destination must be the same tenant/farm, type exactly `cold_store_position`, and `status = 'active'`. A source must be the same tenant/farm and type `cold_store_position`, but is **not** required to be active. This asymmetry is intentional: CMP-018 adds no location-deactivation guard, so requiring an active source would permanently trap stock already recorded at a position an operator later deactivates. `transfer`/`release` off an inactive position remain fully permitted; only placing *into* an inactive position is rejected.

## Relationship to packing

No change to packing. A newly packed finished-goods lot begins with zero storage movements — fully unplaced by construction, never backfilled or fabricated.

## Relationship to dispatch — release-before-dispatch

Dispatch may consume only currently *unplaced* quantity, on top of (never instead of) CMP-017's own commercial-balance checks: each dispatch line independently requires `dispatched ≤ available` **and** `dispatched ≤ unplaced`, in both weight and package count. There is no auto-release and no automatic storage-location selection — an operator must explicitly `release` stock before it can be dispatched. `dispatch_service` enforces this in application code; the amended finished-goods ledger trigger (below) enforces the same rule independently at the database level, so a direct-SQL `dispatch_issue` insert cannot bypass it either.

## Combined ledger/storage effective-time chronology

A single monotonic timeline is enforced across *both* tables for a given lot, in both directions:

- A storage movement's `effective_time` must not be future, must not precede the lot's own `effective_time`, must not precede the latest prior storage movement for that lot, and must not precede the latest `finished_goods_ledger_entries` row for that lot (so a movement can never be backdated to before a dispatch that already happened).
- A dispatch issue's `effective_time` must not precede the latest prior ledger entry (CMP-017's own rule, unchanged) **and** must not precede the latest storage movement for that lot (new) — a dispatch can never be backdated to before a placement/transfer/release that already happened.

Both rules are enforced in both the relevant service (`finished_goods_storage_service`, `dispatch_service`) and both relevant database triggers, never in only one layer.

## Ledger trigger versioning: v2 → v3

CMP-017's own `enforce_finished_goods_ledger_entry_insert_integrity_v2` function is never modified or dropped — the fourth use of this codebase's versioned-replacement idiom (CMP-014→015, CMP-015→016, CMP-016→017). CMP-018 attaches a new function, `enforce_finished_goods_ledger_entry_insert_integrity_v3`, which reproduces every v2 rule byte-for-byte and adds, only in the `dispatch_issue` branch: a check that the dispatch's `effective_time` is not before the lot's latest storage movement, and a check that the resulting available weight/count never falls below the lot's currently physically placed weight/count. The `packing_receipt` branch is untouched. On clean downgrade, the v3 attachment and function are dropped and the exact v2 attachment is restored — the v2 function itself was never touched, so it is only re-attached, never recreated.

## Locking

One shared serialization point: `finished_goods_lots` is locked `FOR UPDATE` first by every writer that can change a lot's available or placed quantity — `finished_goods_storage_service.record_movement`, the movement table's own immediate trigger, `dispatch_service.record_dispatch`, and the v3 ledger trigger. Dispatch and storage movements are therefore transitively serialized against each other through this one row, with no new lock resource. After the lot lock, a storage movement additionally locks any referenced location row(s) — sorted by UUID, at most two, via `with_for_update(of=Location)` (never locking the shared `location_types` row a location joins to) — **before** final eligibility validation. This closes a real TOCTOU window: without it, a destination could be read as active, then concurrently deactivated, before the movement's own commit. With the lock, either the deactivation commits first (and the movement correctly rejects) or the movement holds the lock and completes first (and the deactivation, unconditional, still succeeds afterward) — never a commit based on stale eligibility. Dispatch never needs a storage-location lock; a writer must never lock a storage location and then attempt to acquire the finished-goods-lot lock, which would invert this order.

## No deferred reconciliation trigger

Unlike dispatch (`dispatch_event` → `dispatch_lines` → `dispatch_issue` fan-out, reconciled by a deferred constraint trigger) or harvest/packing, a storage movement is one self-contained immutable row with no child rows to reconcile against it. No deferred trigger is added for this table — a deliberate simplification, not an oversight.

## Quality holds

Placement/transfer/release are **not** blocked by an open quality hold on the lot's contributing batch(es). Dispatch remains blocked by CMP-017's own existing rule, unchanged. Rationale: physical relocation may be exactly what is needed to segregate held product into quarantine; blocking movement would work against that. No finished-goods-level hold target is introduced.

## Idempotency

Same shape as every other typed command in this codebase: tenant-scoped `client_command_id` unique index plus a SHA-256 fingerprint over every material field (tenant/farm/actor, lot ID, kind, source/destination location, canonical-Decimal weight, exact count, effective_time, note), checked before and after the lock tiers.

## API

Exactly four operations, no PUT/PATCH/DELETE: `POST .../finished-goods-storage-movements`; `GET .../finished-goods-lots/{id}/storage-movements` (ordered by effective_time, recorded_time, id); `GET .../finished-goods-lots/{id}/placements` (available/total_placed/unplaced weight and count, plus positive-balance location rows); `GET .../locations/{id}/finished-goods-inventory` (positive-balance lots only; rejects a non-storage-eligible location type, but an *inactive* cold-store position remains readable so stranded stock can still be found). Cross-tenant/farm access returns 404. Weights are canonical Decimal strings throughout.

## Audit

Exactly one `finished_goods.storage_moved` audit event per successful movement command — never one per balance read.

## Migration and downgrade

Adds `finished_goods_storage_movements`, its triggers/function, `enforce_finished_goods_ledger_entry_insert_integrity_v3`, and `uq_locations_tenant_farm_id` on `locations`. Downgrade blocks unconditionally whenever any storage movement row exists — CMP-015/017's own unconditional-block model: a movement row is independent operational data, never reconstructible, and the guard fires on row *existence*, not net balance (a place immediately followed by a matching release still blocks downgrade). When clean, downgrade drops the storage table/triggers/function, drops the v3 function, restores the exact CMP-017 v2 attachment (the v2 function itself was never modified, so only re-attached), and removes only the CMP-018-added `uq_locations_tenant_farm_id` constraint. Every packing/dispatch/audit row is untouched. CMP-016A's own `env.py` guard targets a different, unrelated revision and is unaffected.

## Deferred

Sales orders, customers, reservations, allocations, FIFO/FEFO, pallets, cartons, storage capacity, pricing, invoicing, transport, delivery confirmation, corrections, reversals, adjustments, valuation, frontend, RLS, role-specific authorization, automatic storage-location selection, auto-release.
