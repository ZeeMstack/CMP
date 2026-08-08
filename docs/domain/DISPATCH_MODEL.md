# Typed Finished-Goods Dispatch Foundation

Full detail: `CMP_MASTER_SPEC.md` §2, §7, §8; `CLAUDE.md` rules 1, 3, 5, 7, 8, 10, 12. This document summarizes the approved model as implemented in CMP-017; it does not restate the spec.

## Scope

CMP-017 is the first typed consumer of the CMP-016 finished-goods ledger and the first negative ledger operation in the system: one dispatch command reduces weight and package count from one or more finished-goods lots, each backed by a new, deterministic `dispatch_issue` ledger entry. A dispatch is final and immutable the moment it is recorded — there is no status, no editable completion flag, no correction, and no reversal. Out of scope: customers, sales orders, reservations, allocations, pricing, invoicing, storage locations, pallets, transport, delivery confirmation, returns, cancellation, correction, reversal, write-off, costing, valuation, frontend functionality, RLS, role-specific authorization. A future correction/reversal needs a separate typed compensating entry kind; this ticket does not attempt one.

## Dispatch event and dispatch lines

One `dispatch_event` is one command: `id`, `tenant_id`, `farm_id`, `code`, `client_command_id`, `request_fingerprint`, `effective_time`, `recorded_time` (server-generated), `actor_user_id`, an optional `external_reference`, an optional `note`. Insertion is completion — there is no status column. `dispatch_events.code` is farm-scoped, case-insensitive unique — a deliberate exception to this codebase's otherwise-universal tenant-scoped `*_code` convention: a dispatch code is a facility-local document number, not a tenant-wide identity like a produce/finished-goods lot code.

One or more immutable `dispatch_lines` (at least one; no approved maximum) each name one finished-goods lot and the weight/package count dispatched from it — `UNIQUE(dispatch_event_id, finished_goods_lot_id)` enforces one line per lot per event. Weight is strictly positive, at most three decimal places, and bounded below 100000000000; package count is a strictly positive `BIGINT`. Both `dispatch_events` and `dispatch_lines` are append-only: `UPDATE` and `DELETE` are rejected by the same `reject_append_only_mutation`/`reject_hard_delete` triggers used everywhere else in this codebase. There is deliberately no per-command line-count cap: a commercial dispatch may legitimately name more finished-goods lots than any arbitrary limit would allow, and no approved domain requirement establishes one.

## Finished-goods ledger amendment

`finished_goods_ledger_entries` gains a second `entry_kind`, `dispatch_issue`, and a new nullable `dispatch_line_id` column; `packing_event_id` becomes nullable. A CHECK (`ck_finished_goods_ledger_entries_typed_source_shape`) enforces the typed-source XOR, matching CMP-015's own `ck_produce_lot_ledger_entries_typed_source_shape` idiom exactly: `packing_receipt` rows always have `packing_event_id` populated and `dispatch_line_id` NULL; `dispatch_issue` rows the reverse. The weight-envelope and count CHECKs (same names as CMP-016 where practical, bodies replaced — the same drop/recreate idiom CMP-015 used against CMP-014's own CHECKs) become kind-signed: receipts stay strictly positive, issues strictly negative — zero is never valid for either kind. The package-count CHECK deliberately never applies `ABS()` to the `BIGINT` minimum (`-9223372036854775808`, which has no positive `int64` equivalent): the issue lower bound is the explicit, asymmetric `-9223372036854775807`. A `dispatch_issue` row's identity is deterministic, mirroring CMP-016's own convention one level up the chain: `ledger_entry.id = dispatch_line.id`, one exact issue per line, no client-command ID or fingerprint of its own — the dispatch event owns command idempotency.

**Two insert-integrity triggers on this table, deliberately, for the third time in this codebase**: CMP-016's own `enforce_finished_goods_ledger_entry_insert_integrity` function is never modified. CMP-017 instead drops only its trigger *attachment* and attaches a new function, `enforce_finished_goods_ledger_entry_insert_integrity_v2`, which validates both entry kinds (reproducing every CMP-016 receipt rule exactly, plus the new issue rules below). On clean downgrade, the v2 attachment and function are dropped and the original attachment is recreated pointing at the still-untouched original function.

## Lineage and quality holds

A finished-goods lot carries no batch reference of its own; dispatch derives the complete, deterministic lineage back to every contributing crop batch through the existing chain: `finished_goods_lot -> packing_event -> packing_input_lines -> harvested_produce_lot -> batch`. Every requested lot must resolve at least one input line; a lot with no resolvable lineage is rejected outright (`DispatchFinishedGoodsLotNotFoundError`), never silently dispatched. The complete, deduplicated set of contributing batch IDs is sorted and locked `FOR UPDATE` before checking `quality_hold_service.has_open_quality_hold` per batch — a genuinely new dispatch command is blocked while any contributing source batch has an open hold, exactly as CMP-013/015 already extend for harvest/packing. No finished-goods-level hold target is invented.

## Balance enforcement

Weight and package count are checked independently against `SUM(weight_delta_kg)`/`SUM(package_count_delta)` over a lot's existing ledger entries — never inferred from each other. Exact-zero residual balance is permitted. The v2 trigger's `dispatch_issue` branch re-locks the finished-goods lot row `FOR UPDATE` (a no-op within the same transaction as the application's own lock, and the sole serialization point for a direct-SQL writer that bypasses the service) and recomputes the balance from persisted rows only — a `BEFORE INSERT` trigger naturally excludes the row being inserted — before rejecting a resulting negative weight or count.

## Locking and idempotency

`dispatch_service.record_dispatch` locks in two tiers, both sorted by id: the derived source crop-batch rows first (for hold-checking), then the finished-goods-lot rows (for balance validation and issue insertion) — a direct-SQL multi-lot writer that does not presort its own locks can still deadlock against another such writer, exactly as any `FOR UPDATE`-guarded table can; this is a documented limitation, not a bug. Idempotency is tenant-wide `client_command_id` + SHA-256 fingerprint on `dispatch_events`, checked before and after the lock tiers (closing the same TOCTOU window every prior typed command already closes), covering every material field including the normalized code/external_reference/note and every line's lot ID, canonical weight, and exact count, with lines sorted by finished-goods-lot UUID. Duplicate lot IDs within one command are rejected explicitly, never silently deduplicated. An open quality hold blocks a genuinely new dispatch exactly like it blocks packing; an exact retry still returns its original result even if a hold was placed afterward, or a later dispatch reduced a source balance.

## Effective-time rules

A dispatch's `effective_time` may not be in the future, may not precede the finished-goods lot's own `effective_time`, and may not precede the latest existing ledger entry's `effective_time` for that lot. Each issue's `effective_time` and `recorded_time` are copied exactly from the owning dispatch event — never a fresh value of their own.

## Reconciliation

One shared deferred function, `enforce_dispatch_reconciliation`, is attached via three `DEFERRABLE INITIALLY DEFERRED` constraint triggers — `AFTER INSERT` on `dispatch_events`, `dispatch_lines`, and (a third, sibling attachment alongside CMP-016's own, untouched) `finished_goods_ledger_entries`. It proves every dispatch event has at least one line, every line has exactly one matching, field-correct issue, and no line has more than one issue. CMP-016's own `enforce_finished_goods_ledger_reconciliation` keeps firing for every insert on `finished_goods_ledger_entries` too; it only ever counts `packing_receipt` rows, so a `dispatch_issue` insert is a harmless no-op re-confirmation for it — it is never edited, so packing-receipt reconciliation is never weakened.

## API

Exactly three operations: `POST/GET .../dispatches`, `GET .../dispatches/{id}`. No PUT/PATCH/DELETE anywhere. The existing CMP-016 ledger/balance GET routes are unmodified but now also return `dispatch_issue` rows and a decreased `available_*`.

## Audit

Exactly one `finished_goods.dispatched` audit event per successful command — never one per line or ledger issue. Exact retries create no additional audit event.

## Migration and downgrade

Adds `uq_dispatch_events_tenant_farm_id` and `uq_dispatch_lines_tenant_farm_id` (composite unique constraints backing real composite foreign keys, matching every other typed source in this codebase) plus a new composite foreign key from `finished_goods_ledger_entries` to `dispatch_lines`. Downgrade blocks unconditionally whenever any dispatch event, line, or `dispatch_issue` ledger row exists — CMP-015's own unconditional-block model, not CMP-016's reconstructible-projection one: dispatch history is genuinely new, independent operational data, never discardable. The guard independently checks event/line/issue existence, an unrecognized future entry kind, and a non-null `dispatch_line_id` even under a manipulated kind — never trusting that `entry_kind` alone reflects the true state. When clean, downgrade restores `finished_goods_ledger_entries` to its exact byte-identical CMP-016 shape — the CHECK bodies and trigger attachment are copied literally from the CMP-016 migration source, never derived dynamically from the currently-active (already CMP-017-shaped) constraints, since by downgrade time the live schema no longer reflects CMP-016's own bodies. The CMP-016/CMP-016A migration files themselves are never modified, and CMP-016A's own env.py guard (targeting a different, unrelated revision) is unaffected.

## Deferred

Customers, sales orders, reservations, allocations, pricing, invoicing, pallets, transport, delivery confirmation, returns, cancellation, correction, reversal, write-off, costing, valuation, frontend, RLS, role-specific authorization. A future correction ticket will introduce the first typed compensating entry kind.

> **CMP-018 update**: storage locations are no longer deferred. `dispatch_service.record_dispatch` gains a release-before-dispatch rule — each line now additionally requires `dispatched ≤ unplaced` (weight and count independently), on top of the balance checks above — and a dispatch's `effective_time` may no longer precede the lot's latest storage movement. The v2 ledger trigger described above is itself superseded by `..._v3`. See `docs/domain/FINISHED_GOODS_STORAGE_MODEL.md`.
