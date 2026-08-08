# Typed Packing Consumption and Finished-Goods Lot Model

Full detail: `CMP_MASTER_SPEC.md` §2, §7, §8; `CLAUDE.md` rules 1, 3, 5, 7, 8, 10, 12. This document summarizes the approved model as implemented in CMP-015; it does not restate the spec.

## Scope

CMP-015 is the first typed consumer of the CMP-014 produce-lot ledger: one packing command consumes weight (and, where the source lot tracks it, whole-unit count) from one or more harvested produce lots and creates exactly one finished-goods lot. Out of scope: multiple output lots per event, multiple grades/SKUs per event, finished-goods inventory ledger, packaging-material inventory, packaging specifications, pack-size catalog, grading, sorting, repacking, unpacking, reservations, allocation, cold storage, finished-goods occupancy, dispatch, sales orders, invoicing, costing, valuation, a generic produce-lot consumption/adjustment command, manual ledger mutation, correction, reversal, void, frontend, RLS, role-specific authorization. Different output grades or commercial products require separate packing commands until a later specification model exists.

## Packing event, input lines, and finished-goods lot

One `packing_event` is one command. It carries one or more immutable `packing_input_lines` (1–50, one source produce lot each — `UNIQUE(packing_event_id, harvested_produce_lot_id)`) and drives exactly one immutable `finished_goods_lot` (`packing_event_id UNIQUE`). Unlike CMP-013's harvest, a packing event is farm-scoped, not batch-scoped — its inputs may come from different harvest events, different crop batches, and different workflow versions, provided every source lot shares the same crop and (null-safe) variety. A harvested produce lot remains usable after its crop batch closes or is superseded, unless a quality hold blocks it.

**Package count vs. source unit count**: `finished_goods_lots.package_count` (number of finished packs/containers) and a source lot's `total_whole_unit_count` (harvested whole units) are never reconciled against each other — they are different physical quantities with no fixed ratio.

## Produce-lot ledger amendment

`produce_lot_ledger_entries` gains a second `entry_kind`, `packing_consumption`, and a new nullable `packing_event_id` column; `harvest_event_id` becomes nullable. A CHECK (`ck_produce_lot_ledger_entries_typed_source_shape`) enforces the typed-source XOR: `harvest_receipt` rows always have `harvest_event_id` populated and `packing_event_id` NULL; `packing_consumption` rows the reverse. The weight-envelope and count CHECKs (same names as CMP-014, bodies replaced — the same drop/recreate idiom CMP-013 used to widen a CHECK) become kind-signed: receipts stay strictly positive, consumption strictly negative — zero is never valid for either kind. A `packing_consumption` row's identity is deterministic, mirroring CMP-014's own convention: `ledger_entry.id = packing_input_line.id`, one exact debit per line, no client-command ID or fingerprint of its own — the packing event owns command idempotency.

**Two insert-integrity triggers on one table, deliberately**: CMP-014's own `enforce_produce_lot_ledger_entry_insert_integrity` function is never modified. CMP-015 instead drops only its trigger *attachment* and attaches a new function, `enforce_produce_lot_ledger_entry_insert_integrity_v2`, which validates both entry kinds (reproducing every CMP-014 receipt rule exactly, plus the new consumption rules below). On clean downgrade, the v2 attachment and function are dropped and the original attachment is recreated pointing at the still-untouched original function — no two triggers ever coexist on the same insert event, and a future ticket must not assume this table has only ever had one insert-integrity function.

## Availability, overconsumption, and residual synchronization

Available weight/count are always `SUM(weight_delta_kg)`/`SUM(whole_unit_count_delta)` over a lot's ledger entries — unchanged in shape from CMP-014, now correctly decreasing as negative `packing_consumption` deltas post. The v2 trigger's `packing_consumption` branch locks the source produce-lot row `FOR UPDATE` and computes the balance prior to the proposed insert, inside the same transaction — this lock is the serialization point for all current and future typed consumers, not just packing. It rejects a resulting negative weight or count, and enforces count-mode compatibility: a source lot with no tracked count must receive a NULL count delta; a count-tracked lot requires one. **Residual synchronization** is enforced when the source lot tracks count: consumption may not leave the lot with exactly one of (remaining weight, remaining count) at zero while the other stays positive — both must reach zero together, or both remain positive. This is a low-cost sanity check specific to CMP-015's narrow scope (no grading/repack): weight and count are two measurements of the identical physical remainder, entered independently per line, so no legitimate workflow ever needs them to diverge to zero independently. The service layer enforces the identical rule before any write; the trigger is the independent database-level proof.

## Locking and idempotency

`packing_service.record_packing` locks strictly more than harvest does, in two tiers: source crop-batch rows (sorted by id, `FOR UPDATE`) before checking quality holds, then source produce-lot rows (sorted by id, `FOR UPDATE`) before computing balances — mirroring `batch_derivation_service.merge_batches`'s own multi-batch locking idiom. Idempotency is tenant-wide `client_command_id` + SHA-256 fingerprint on `packing_events`, checked before and after the batch-row lock (closing the same TOCTOU window CMP-013 already closes), excluding event/lot/line/ledger IDs and any current mutable state (balances, holds, batch state). An open quality hold on any source lot's crop batch blocks a genuinely new packing command exactly like it blocks harvest; an exact retry still returns its original result even if a hold was placed afterward, or a later packing event reduced a source balance.

## Quality-hold policy

Extends the same net documented in `docs/domain/OBSERVATION_QUALITY_MODEL.md`: CMP-015 packing also blocks on an open hold against any source produce lot's crop batch, checked at the service layer (after locking batches, before mutable-state validation) and, independently, inside the packing-input-line insert-integrity trigger, which locates the source lot's batch, locks it `FOR UPDATE`, and checks for an open hold itself — the same self-contained style `quality_holds_enforce_insert_integrity` already uses.

## Reconciliation

Exact Decimal arithmetic throughout, reusing the CMP-013/014 envelope and helpers unchanged. `total_input_weight_kg = packed_output_weight_kg + process_loss_weight_kg + rejected_weight_kg` is a same-row CHECK on `packing_events` (immediate); `total_input_weight_kg = SUM(packing_input_lines.consumed_weight_kg)`, `packed_output_weight_kg = finished_goods_lots.net_packed_weight_kg`, deterministic line/debit identity and field equality, and "no orphan input/output/debit references the event" are all proven by one shared deferred function, `enforce_packing_reconciliation`, attached to four `DEFERRABLE INITIALLY DEFERRED` constraint triggers (`packing_events`, `packing_input_lines`, `finished_goods_lots` all `AFTER INSERT`; `produce_lot_ledger_entries AFTER INSERT`, no-op unless `entry_kind = 'packing_consumption'`).

## API

Exactly five operations: `POST/GET .../packing-events`, `GET .../packing-events/{id}`, `GET .../finished-goods-lots`, `GET .../finished-goods-lots/{id}`. No PUT/PATCH/DELETE anywhere. The existing CMP-014 ledger/balance GET routes are unmodified but now also return `packing_consumption` rows and a decreased `available_*`.

## Audit

Exactly one `produce_lot.packed` audit event per successful command — never one per input line or ledger debit. Exact retries create no additional audit event.

## Migration and downgrade

Adds `uq_harvested_produce_lots_tenant_farm_id` (a composite unique constraint CMP-013/014 never added) so `packing_input_lines` can use a real database-enforced composite foreign key to its source lot, rather than trigger-only consistency (the pattern `produce_lot_ledger_entries.produce_lot_id` was forced into). Downgrade blocks unconditionally whenever any packing event, input line, finished-goods lot, or `packing_consumption` ledger row exists — unlike CMP-014's own reconstructible-projection guard, packing history is genuinely new operational data, never discardable. When clean, downgrade restores `produce_lot_ledger_entries` and `harvested_produce_lots` to their exact CMP-014 shape, including byte-identical CHECK constraint bodies and the original trigger attachment; the CMP-013/014 migration files themselves are never modified.

## Finished-goods opening receipt

Every finished-goods lot now also receives one immutable opening-receipt ledger entry, created automatically inside the same packing transaction — see `docs/domain/FINISHED_GOODS_LEDGER_MODEL.md` (CMP-016). It reads only the just-inserted lot/event, adds no new command, audit event, or API route on this model, and does not change any behavior described above. CMP-017 (`docs/domain/DISPATCH_MODEL.md`) later adds the first typed negative entry against that same ledger — a dispatch issue — with no change to packing itself. CMP-018 (`docs/domain/FINISHED_GOODS_STORAGE_MODEL.md`) adds physical storage placement as a wholly separate table with no change to packing either: a newly packed finished-goods lot begins with zero storage movements, and is therefore fully unplaced by construction until an operator explicitly places it.

CMP-019's recall traceability reads `packing_events`/`packing_input_lines` (a true M:N with produce lots, never collapsed) for both backward trace and forward impact — read-only, no behavior change here. See `docs/domain/TRACEABILITY_MODEL.md`.

## Deferred

Grading, repacking, unpacking, correction, reversal, void, finished-goods inventory/storage/occupancy, dispatch, sales orders, invoicing, costing, valuation, multi-output packing, packaging-material inventory, frontend, RLS, role-specific authorization.
