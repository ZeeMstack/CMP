# Finished-Goods Opening Receipt Ledger Model

Full detail: `CMP_MASTER_SPEC.md` §2, §7, §8; `CLAUDE.md` rules 1, 3, 5, 7, 8, 10, 12. This document summarizes the approved model as implemented in CMP-016; it does not restate the spec.

## Scope

Every CMP-015 finished-goods lot receives exactly one immutable ledger receipt recording its original packed quantity — an append-only foundation one level up the chain from CMP-014's own produce-lot ledger, ready for a future typed dispatch debit to post against later. CMP-016 adds no dispatch, sales order, allocation, reservation, consumption, adjustment, transfer, correction, reversal, void, storage location, occupancy, palletization, customer ownership, costing, or valuation. The receipt is not a second user command — it is an automatic, atomic consequence of the packing command that already existed.

## Ledger entry and the one permitted kind

`finished_goods_ledger_entries` carries `tenant_id`, `farm_id`, `finished_goods_lot_id`, `packing_event_id`, `entry_kind`, `weight_delta_kg`, `package_count_delta`, `effective_time`, `recorded_time`, `actor_user_id`, `note`. CMP-016 permits exactly one `entry_kind`, `packing_receipt`. No balance, previous-balance, available-balance, status, location, cost, or valuation column exists — balance is always derived. Since only one kind exists today, the deterministic-ID, kind, and note-null rules are ordinary same-row `CHECK` constraints, not kind-guarded — a future ticket introducing a second kind (dispatch) must widen these the same way CMP-015 widened CMP-014's own weight/count CHECKs, and must not assume every row obeys today's unconditional shape.

## Deterministic receipt identity

A `packing_receipt` row is an exact, reconstructible projection of its finished-goods lot and packing event: `ledger_entry.id = finished_goods_lot_id = finished_goods_lot.id`; `packing_event_id`, `tenant_id`, `farm_id`, `weight_delta_kg` (from `net_packed_weight_kg`), `package_count_delta` (from `package_count`), and `effective_time` are copied exactly from the lot; `recorded_time` is copied from the lot's own `recorded_time` (never a fresh server default); `actor_user_id` is copied from the packing event; `note` is always `NULL`. No client-command UUID, request fingerprint, or second command identity is ever fabricated; the packing event remains the sole idempotency owner.

## Composite references

Unlike CMP-014's own situation with `harvested_produce_lots`, both `finished_goods_lots` and `packing_events` already carried a `(tenant_id, farm_id, id)` unique constraint before CMP-016 (both added by CMP-015 itself), so CMP-016 uses real composite foreign keys to both directly — no new composite uniqueness needed adding or removing on downgrade.

## One-to-one enforcement

Two partial unique indexes — kind-scoped, not table-wide — on `finished_goods_lot_id` and `packing_event_id`, so a future dispatch kind can reference the same lot repeatedly without being blocked by this ticket's one-receipt-per-lot rule.

## Packing transaction amendment

`packing_service.record_packing`'s write order gains one step: insert event → flush → insert finished-goods lot → flush → **insert the deterministic opening receipt** → flush → insert produce-lot input lines → flush → insert produce-lot consumption debits → flush → append the existing `produce_lot.packed` audit event → commit. All within the same single `try` block already established. Exact packing retry returns the original event and its already-existing receipt before any mutable-state validation. **No new audit event** is created, and the existing audit payload is not amended with a receipt-ID field — under the deterministic-ID convention it would always equal the already-present `finished_goods_lot_id`.

## Database integrity

One immediate `BEFORE INSERT` trigger validates only the cross-table (join-requiring) equalities a same-row `CHECK` cannot express: weight, package count, actor, and effective time against both the lot and the event, and recorded time against the lot. One shared deferred function, `enforce_finished_goods_ledger_reconciliation`, is attached via two `DEFERRABLE INITIALLY DEFERRED` constraint triggers — `AFTER INSERT` on `finished_goods_lots` (a second, distinctly-named trigger alongside CMP-015's own) and `AFTER INSERT` on `finished_goods_ledger_entries`. `packing_events` gets no attachment: CMP-015's own `enforce_packing_reconciliation` already proves exactly one finished-goods lot per packing event (a `count(*) <> 1` check); CMP-016 proves exactly one receipt per lot; the two compose transitively without a third attachment re-checking an already-proven invariant.

## Balance

`available_weight_kg`/`available_package_count` are `SUM`s over every ledger entry for a lot; `received_weight_kg`/`received_package_count` sum only `packing_receipt` entries. With only receipts possible today, received and available are numerically identical, but the query shape already supports a future typed debit without any editable balance column. Package count is never compared against a source produce lot's whole-unit count — different physical quantities, never reconciled.

## API

Exactly two new GET operations: `GET .../finished-goods-lots/{finished_goods_lot_id}/ledger` and `.../balance`. No mutation route exists. Existing finished-goods list/detail responses are not amended with an embedded balance.

## Migration backfill and downgrade

The upgrade creates the table/constraints/triggers, backfills one deterministic receipt per existing finished-goods lot via one `INSERT ... SELECT` joining `finished_goods_lots`/`packing_events`, then verifies — via explicit anti-join/`NOT EXISTS` checks in both directions, not merely a row-count comparison — that no lot is missing its receipt, no receipt is field-mismatched (`IS DISTINCT FROM` lot/event, lot -> receipt `LEFT JOIN`), and no receipt is orphaned (receipt -> lot `NOT EXISTS`), before attaching the deferred triggers. Downgrade follows CMP-014's own reconstructible-projection model, not CMP-015's unconditional block: it is allowed even while finished-goods/packing history exists, as long as every receipt is exactly reconstructible from its lot/event. The guard independently repeats all of the upgrade's own checks — unknown entry kind, missing/field-mismatched receipt (lot -> receipt), orphaned receipt (receipt -> lot, added during CMP-016 hardening: the lot-driven `LEFT JOIN` alone cannot see a receipt whose lot/event no longer resolves), and more-than-one receipt per lot or per event (defence in depth against already-corrupted state, since normal operation makes duplicates unreachable via the deterministic-id CHECK and the two partial unique indexes) — rather than trusting that the backfill or ordinary operation left the table well-formed. Re-upgrade after a clean downgrade reproduces byte-identical receipt rows, including `recorded_time`.

## Deferred

Dispatch, sales orders, allocation, reservation, consumption, adjustment, transfer, correction, reversal, void, cold-store storage/occupancy, palletization, cartons/package-carrier assets, repacking, unpacking, customer ownership, costing, valuation, editable balances, negative ledger entries, frontend, RLS, role-specific authorization. A future dispatch ticket will introduce the first typed negative entry kind.
