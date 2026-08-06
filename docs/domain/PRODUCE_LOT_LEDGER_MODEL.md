# Produce-Lot Opening Receipt Ledger Model

Full detail: `CMP_MASTER_SPEC.md` §2, §7, §8; `CLAUDE.md` rules 1, 3, 5, 7, 8, 10, 12. This document summarizes the approved model as implemented in CMP-014; it does not restate the spec.

## Scope

Every CMP-013 harvested produce lot receives exactly one immutable ledger receipt recording its original harvested quantity. CMP-014 itself added no consumption, reservation, allocation, adjustment, correction, waste, rejection, shrinkage, transfer, cold-store receipt, storage location, dispatch, costing, valuation, editable balance, reversal, or void — the receipt is not a second user command, it is an automatic, atomic consequence of the harvest command that already existed. CMP-015 (see `docs/domain/PACKING_MODEL.md`) is the first typed consumer, adding a second `entry_kind` and negative deltas exactly as anticipated below; the rest of this document's scope boundary is otherwise unchanged.

## Ledger entry and entry kinds

`produce_lot_ledger_entries` carries `tenant_id`, `farm_id`, `produce_lot_id`, `harvest_event_id` (nullable since CMP-015), `packing_event_id` (added by CMP-015, nullable), `entry_kind`, `weight_delta_kg`, `whole_unit_count_delta`, `effective_time`, `recorded_time`, `actor_user_id`, `note`. CMP-014 permitted exactly one `entry_kind`, `harvest_receipt`; CMP-015 widened this to also permit `packing_consumption`, with a CHECK enforcing that each kind's own source-event reference (`harvest_event_id` vs. `packing_event_id`) is populated exclusively (see `PACKING_MODEL.md`). No balance, previous-balance, available-balance, consumed-balance, reserved-balance, status, location, cost, or valuation column exists — balance is always derived (see below).

## Deterministic receipt identity

A `harvest_receipt` row is an exact, reconstructible projection of its produce lot and harvest event, not an independent command: `ledger_entry.id = produce_lot_id = harvested_produce_lot.id`; `harvest_event_id`, `tenant_id`, `farm_id`, `weight_delta_kg`, `whole_unit_count_delta`, and `effective_time` are copied exactly from the lot; `recorded_time` is copied from the lot's own `recorded_at` (never a fresh server default — this is what makes live creation and migration backfill always produce byte-identical rows); `actor_user_id` is copied from the harvest event; `note` is always `NULL` — the harvest event already owns the user-provided note. No client-command UUID, request fingerprint, or second audit-command identity is ever fabricated for the receipt; the harvest event remains the sole idempotency owner. Reusing a primary-key value across two tables (`produce_lot_ledger_entries.id` = `harvested_produce_lots.id`) is a new pattern in this codebase — future tickets must not assume ledger-entry IDs are always independently generated once a second `entry_kind` exists.

## One-to-one enforcement

Two partial unique indexes — `UNIQUE(produce_lot_id) WHERE entry_kind = 'harvest_receipt'` and `UNIQUE(harvest_event_id) WHERE entry_kind = 'harvest_receipt'` — are kind-scoped, not table-wide, so CMP-015's `packing_consumption` kind can reference the same lot repeatedly (across separate packing events) without being blocked by this ticket's one-receipt-per-lot rule. A third partial index, `UNIQUE(packing_event_id, produce_lot_id) WHERE entry_kind = 'packing_consumption'`, was added by CMP-015 for its own one-lot-per-event rule. In practice, the deterministic-ID convention already makes a second `harvest_receipt` row for the same lot collide on the primary key before either index is even reached.

## Harvest transaction amendment

`harvest_service.record_harvest`'s write order is now: insert event → flush → insert lot → flush → insert the deterministic opening receipt (values taken from the just-flushed lot/event) → flush → insert source lines → flush → append the existing `crop_batch.harvested` audit event → commit. All within the same single `try` block CMP-013 already established — a failure anywhere leaves no event, lot, receipt, source line, or audit event. Exact harvest retry returns the original event and its already-existing receipt before any mutable-state validation, and creates neither a duplicate event nor a duplicate receipt. **No new audit event** is created for the receipt, and the existing `crop_batch.harvested` payload is not amended with a `receipt_id` field — under the deterministic-ID convention that field would always equal the already-present `produce_lot_id`, so adding it would be pure redundancy while shaping future audit rows differently from historical ones for no new information.

## Database integrity

One immediate `BEFORE INSERT` trigger independently re-verifies, for `harvest_receipt` rows: tenant/farm match, the lot exists and points to the given event, the deterministic id equals `produce_lot_id`, weight/count/actor/`effective_time`/`recorded_time` all exactly match the lot/event, and `note IS NULL` — reusing the same shared `reject_append_only_mutation`/`reject_hard_delete` functions CMP-013 already established for UPDATE/DELETE. One shared deferred function, `enforce_produce_lot_ledger_reconciliation`, is attached via two `DEFERRABLE INITIALLY DEFERRED` constraint triggers — `AFTER INSERT` on `harvested_produce_lots` (a second, distinctly-named trigger alongside CMP-013's own, which is left completely untouched) and `AFTER INSERT` on `produce_lot_ledger_entries` — validating complete field equality (not just a row count) at commit. `harvest_events` gets no third attachment: CMP-013 already guarantees exactly one lot per event, and CMP-014 guarantees exactly one receipt per lot, so event-to-receipt 1:1 holds transitively without re-checking the same invariant a third time.

## Balance

`available_weight_kg` and `available_whole_unit_count` are `SUM`s over every ledger entry for a lot; `received_weight_kg`/`received_whole_unit_count` sum only `harvest_receipt` entries — the lot's original inflow, which never shrinks regardless of later consumption. Since CMP-015, `available_*` correctly decreases as negative `packing_consumption` deltas post, with no query-shape change from what CMP-014 already anticipated.

## API

Exactly two GET operations: `GET .../harvested-produce-lots/{produce_lot_id}/ledger` and `.../balance`. No POST/PUT/PATCH/DELETE ledger route exists — CMP-015's packing consumption still posts only through the packing command, never through a ledger route.

## Migration backfill and downgrade

The upgrade creates the table/constraints/triggers, backfills one deterministic receipt per existing lot via one `INSERT ... SELECT` joining `harvested_produce_lots`/`harvest_events`, then explicitly verifies — via `IS DISTINCT FROM` field-by-field comparison, not merely a row-count match — that no lot is missing its receipt and no receipt is malformed, before attaching the deferred triggers. Downgrade past CMP-014 is allowed (unlike CMP-013's own destructive-downgrade guard) because every receipt is a deterministic projection of already-immutable CMP-013 data, exactly reconstructible by re-running the same backfill; the guard still rejects downgrade if any entry kind other than `harvest_receipt` exists, or if any receipt no longer exactly reconstructs from its lot/event (both scenarios are unreachable through the current schema alone — the `entry_kind` CHECK and the insert-integrity trigger already prevent them — and exist purely as forward-compatibility tripwires). Re-upgrade after a clean downgrade reproduces byte-identical receipt rows, including `recorded_time`.

## Deferred

Grading, reservations, allocation, generic adjustment, correction, waste, rejection, shrinkage, transfer, cold-store receipt, storage location, dispatch, costing, valuation, customer ownership, editable quantity-on-hand, reversal, void, frontend, RLS, role-specific authorization. Packing consumption (CMP-015) is implemented — see `docs/domain/PACKING_MODEL.md`.
