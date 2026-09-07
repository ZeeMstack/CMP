# STORE-INV-002A.1 — Receipt + Lot + Quantity Foundation — Build Plan

**Not a source of domain truth.** Canonical model: `docs/domain/STORE_INVENTORY_MODEL.md` §§4–21 (as amended by the `STORE-INV-002A` discovery), `docs/product/OPEN_QUESTIONS.md`, `CLAUDE.md`. On any conflict between this document and the canonical domain model, **the canonical domain model wins**. Procedural rules (execution discipline, Git/PR flow, deployment steps, acceptance-checklist categories) are in `STORE_INV_002A_COMMON_BUILD_PROCEDURE.md` and are not repeated here except where phase-specific.

---

## Objective

Build the schema and service-layer foundation that lets GrowCMP correctly answer *"how much of this material exists, and is it usable?"* for a Goods Receipt — without yet exposing any quality-action command or any operational UI. This phase must be safe to ship on its own: a `qc_release_required` item received under `.1` alone must never be reported as usable before `.2`'s release mechanism exists.

## Prerequisites

- Branch `store-inv-002a-goods-receipt-lot-existence` (or a fresh branch cut from verified merged `main`, per the common procedure).
- Confirmed clean working tree, confirmed current Alembic head (`10430de8731e` at time of writing — **re-confirm from the repo, never from this document, before starting** — see Step 1).
- `docs/domain/STORE_INVENTORY_MODEL.md` and this build plan read in full.

## Scope

`InventoryItemPackaging`; `InventoryItemSeedProfile`; tenant-wide `InventoryLot`; `SeedLot.inventory_lot_id`; `GoodsReceipt`/`GoodsReceiptLine`; `InventoryQuantityCohort` (including the split schema); `InventoryExistenceLedgerEntry` (`receipt`/`adjustment`/`reversal`/`split_out`/`split_in`); the `QualityDispositionEvent` table and the automatic `RECEIVED_QUARANTINED` opening event; the `base_uom_id`/tracking-policy/Seed-Profile structural freeze; the company-wide existence read model; `inventory.read`/`inventory_receipt.manage`/`inventory_adjustment.manage`/`inventory_quality.manage` permission definitions.

## Explicit Out-of-Scope

- No physical custody/bin-balance table (`STORE-INV-002B`).
- No release/hold/reject/correction command, no `split_cohort` operator endpoint, no Quality UI (`STORE-INV-002A.2`).
- No Reservation, Issue, Consumption, Return, Transfer (`STORE-INV-003`/`004`).
- No Store & Inventory navigation/workspace (ships only with `.2`).
- No Supplier Master, no Odoo integration, no costing/valuation.

---

## Step 1 — Repository Discovery / Pre-flight

Before any edit:

- `git status`, `git branch --show-current`, confirm clean tree.
- Confirm current `main`/base commit (`git log origin/main -1`).
- Confirm the current Alembic head by scanning `apps/api/migrations/versions/*.py` for the revision with no other file's `down_revision` pointing to it (do not trust any hard-coded revision id in this document or prior discovery — re-derive it).
- Re-read, in full, current state of:
  - `apps/api/app/models/inventory_item.py`, `inventory_category.py`, `unit_of_measure.py`
  - `apps/api/app/services/inventory_item_service.py`, `inventory_category_service.py`
  - `apps/api/app/models/seed_lot.py`, `apps/api/app/services/seed_lot_service.py` (or equivalent), `apps/api/app/schemas/seed_lot.py`
  - The closest ledger precedents: `apps/api/app/models/produce_lot_ledger_entry.py`, `finished_goods_ledger_entry.py`, and their services (`produce_lot_ledger_service.py`, `finished_goods_ledger_service.py`) — for the exact deterministic-ID, signed-envelope-CHECK, and typed-source-XOR idioms.
  - `apps/api/app/models/carrier_specification.py` + `apps/api/app/services/carrier_specification_service.py` — for the `_is_referenced`/structural-freeze idiom.
  - `apps/api/app/models/quality_hold.py` (or equivalent) and `apps/api/app/services/quality_hold_service.py` — for the derived open/released-by-absence idiom.
  - `apps/api/app/core/permissions.py` — exact current `Permission` enum and `ROLE_PERMISSIONS` mapping.
  - `apps/api/app/services/audit.py` — `append_audit_event` signature.
  - The most recent one or two migration downgrade-guard implementations (e.g. `dd8b86a52acf_finished_goods_storage_foundation.py`) — for the unconditional-block-on-row-existence idiom this phase's own migration must follow.
  - Current API client-type-generation command (check `apps/web/package.json` scripts and any OpenAPI-generation config).
  - Current `Numeric`/precision convention: quantities are `Numeric`, CHECK-constrained to `= trunc(x, 3)` and bounded below `100000000000` (confirmed convention, e.g. `finished_goods_ledger_entry.py`) — reuse exactly, do not invent a different precision rule.

No implementation proceeds from assumptions carried over from the discovery conversation alone — every fact above must be re-verified against the actual current file.

## Step 2 — Model / Migration Design

One migration (or a small number if the diff review genuinely warrants a split — decide only after Step 1's actual-file inspection, not in advance), down-revision = the confirmed current head. New tables: `inventory_item_packaging`, `inventory_item_seed_profiles`, `inventory_lots`, `goods_receipts`, `goods_receipt_lines`, `inventory_quantity_cohorts`, `inventory_existence_ledger_entries`, `quality_disposition_events`. One additive column: `seed_lots.inventory_lot_id` (nullable FK). No changes to `inventory_items`/`inventory_categories`/`unit_of_measures` columns — the structural-freeze checks (Step 12) are service-layer/`_is_referenced`-style queries against the *new* tables, needing no new column on the old ones.

**Do NOT create physical custody/bin-balance tables in this phase** — that is `STORE-INV-002B` and out of scope here regardless of how tempting it is to "just add the location column while we're in here."

## Step 3 — Inventory Item Packaging

Tenant-wide master/config data, `InventoryItem`-scoped. Fields: `id`, `tenant_id`, `inventory_item_id`, immutable `code`, editable `display_name`, `package_quantity` (Numeric, in the item's own `base_uom` — never a separate `package_uom`), `status` (`active`/`inactive`, reversible — mirrors `CarrierSpecification`, explicitly not `PackagingUnit`'s one-way retire), the standard create/update/deactivate/reactivate `client_command_id`+`request_fingerprint` idempotency quadruple (mirrors `InventoryCategory` exactly).

- `package_quantity` structurally frozen the instant any `GoodsReceiptLine` references this packaging record (`_is_referenced`, same shape as `carrier_specification_service._is_referenced`). `display_name`/`status` remain editable regardless.
- No hard delete, ever.
- Receipt-time snapshot (Step 7): a line using packaging freezes `packaging_id`, `package_count`, and a copy of `package_quantity` *as it was at receipt time* — never re-read from the (possibly later-deactivated, but never later-edited-after-first-use) packaging row.
- Do not model `BAG`/`CAN`/`PACK` as a `UnitOfMeasure` row or add any purchase/issue UOM field to `InventoryItem` — forbidden by `STORE_INVENTORY_MODEL.md` §5/§6.

## Step 4 — Seed Details (`InventoryItemSeedProfile`)

Internal table name `InventoryItemSeedProfile`; user-facing label **"Seed Details"** — never expose the table name in any UI copy. Fields: `id`, `tenant_id`, `inventory_item_id` (FK, **unique**), `crop_id`, `variety_id`, `created_by_user_id`, `created_at`. **No `status` column.**

- Before the item's first posted `GoodsReceiptLine`: create, update `crop_id`/`variety_id`, or remove (a genuine `DELETE` — the one narrow, explicitly-scoped hard-delete exception in this domain family, justified because nothing can reference an unused profile yet). Removal is audited (`inventory_item_seed_profile.removed`).
- After the item's first posted `GoodsReceiptLine`: the row is fully immutable — reject `UPDATE` and `DELETE` outright (service-layer check + DB trigger, mirroring the freeze idiom). A profile can never be newly created for an item that already has receipt history and never had one.
- Do not infer seed semantics from `InventoryCategory` anywhere in this step — no `if category.code == ...` of any kind.
- SeedLot linking (Step 6) is only offered at receipt time for an item that **has Seed Details** (an `InventoryItemSeedProfile` row exists) — there is no "active"/"inactive" state to check, since the entity carries no status field at all.

## Step 5 — Inventory Lot

Tenant-wide. Fields: `id`, `tenant_id`, `inventory_item_id`, immutable server-generated `code` (tenant-sequential), `manufacturer_name` (nullable), `manufacturer_lot_reference` (nullable), `manufacturing_date` (nullable), `expiry_date` (nullable, required if `item.expiry_tracking_required`). No `farm_id`. No mutable QC/status field of any kind.

Same-row CHECK: `manufacturer_lot_reference IS NULL OR manufacturer_name IS NOT NULL`.

**Canonical identity — manufacturer name + manufacturer lot reference ONLY. `manufacturing_date`/`expiry_date` are immutable attributes of that identity, never uniqueness dimensions** (implement exactly, do not weaken; do not fold either date into the matching/uniqueness key):
- Both `manufacturer_name` and `manufacturer_lot_reference` present → resolve-or-create, tenant-wide, for the same `InventoryItem`, keyed on `(tenant_id, inventory_item_id, lower(trim(manufacturer_name)), lower(trim(manufacturer_lot_reference)))` only:
  - Canonical key matches an existing lot, and `manufacturing_date`/`expiry_date` are exactly equal (including both NULL) → reuse the existing `InventoryLot`.
  - Canonical key matches an existing lot, but `manufacturing_date`/`expiry_date` disagree (a NULL-vs-known mismatch, or two different known values) → raise an explicit conflict (`ConflictingInventoryLotIdentityError`); never silently create a second lot under the same canonical identity, never silently merge disagreeing attribute facts.
- Either field missing → **always create a new `InventoryLot`**, never auto-matched.

**Database uniqueness under concurrency** — the canonical identity alone is the unique index; dates are never part of it:

```sql
CREATE UNIQUE INDEX ux_inventory_lots_tenant_item_manufacturer_identity
  ON inventory_lots (
    tenant_id, inventory_item_id,
    lower(trim(manufacturer_name)), lower(trim(manufacturer_lot_reference))
  )
  WHERE manufacturer_name IS NOT NULL AND manufacturer_lot_reference IS NOT NULL;
```

Concurrent create: attempt resolution (service-layer lookup) → attempt insert → catch this index's `IntegrityError` → re-select the canonical row → compare `manufacturing_date`/`expiry_date` against the just-lost race's own values → reuse if compatible, else surface the same `ConflictingInventoryLotIdentityError` (the standard insert-then-catch-`IntegrityError`-then-re-select idiom, matching `inventory_item_service.register_inventory_item` exactly).

## Step 6 — SeedLot Linkage

Add `seed_lots.inventory_lot_id` (nullable FK), plus `UNIQUE(inventory_lot_id, farm_id) WHERE inventory_lot_id IS NOT NULL`. Preserve every existing `SeedLot` row and every existing sowing behavior exactly — **no backfill**.

- A DB trigger enforces: when `inventory_lot_id IS NOT NULL`, `SeedLot.supplier_lot_reference` = the linked `InventoryLot.manufacturer_lot_reference` and `SeedLot.expiry_date` = the linked `InventoryLot.expiry_date`, exactly (field-equality projection check, mirroring `enforce_produce_lot_ledger_reconciliation`'s existing pattern) — **do not** null out `SeedLot`'s own columns; existing sowing farm-local-date validation reads them directly and must not break.
- `SeedLot.received_date` is not part of this equality — it stays owned by `SeedLot` alone, populated (for a newly-linked SeedLot created through a seed receipt) from the linking `GoodsReceiptLine`'s effective time, farm-local.
- New seed receipts: `InventoryItemSeedProfile` → resolve/create `InventoryLot` → resolve/create Farm-scoped `SeedLot` (reuse existing `seed_lot_service` creation path unchanged) → set `SeedLot.inventory_lot_id` → existing `SowingEventLine` lineage untouched.
- Do not create two independently-writable authorities for the same fact — verify with a direct test that editing is impossible on the `SeedLot` side once linked (there is no update path on `SeedLot` today regardless; confirm this remains true and is not accidentally reintroduced).

## Step 7 — Goods Receipt

One atomic multi-line `record_goods_receipt` command. **No server-side Draft state.**

**Header** (`GoodsReceipt`): `id`, `tenant_id`, `farm_id` (required), server-generated immutable `code` (`GR-<farm_code>-YYYYMMDD-NNN`, farm-sequential per local date), `received_at`, `recorded_at` (server default), `received_by_user_id`, `supplier_name` (nullable, informational only — never used for lot matching), `external_system`/`external_document_id` (nullable), `notes` (nullable), header-level `client_command_id`/`request_fingerprint`.

**Lines** (`GoodsReceiptLine`): immutable, `inventory_item_id`, `inventory_lot_id` (nullable, resolved per Step 5), direct-UOM-entry **XOR** packaging-entry (same-row CHECK), entered quantity/UOM or `(packaging_id, package_count, package_quantity_snapshot)`, `base_quantity` (`Numeric`, `trunc(x,3)`, `> 0`, bounded `< 100000000000`), `external_line_id` (nullable).

- All-or-nothing: any single line failing (inactive item, invalid packaging, tracking-policy violation, lot conflict) rolls back the entire receipt.
- Reject any `InventoryItem` that is not `active`.
- Idempotency: header-level `client_command_id`/fingerprint only — lines are never independently retryable.

## Step 8 — Root Quantity Cohort

For **every** posted `GoodsReceiptLine`, in the same atomic transaction: insert exactly one `InventoryQuantityCohort` with `id = goods_receipt_line_id` (deterministic, mirroring `harvest_receipt.id = produce_lot_id`), `parent_cohort_id = NULL`, `source_goods_receipt_line_id` = the line, `inventory_item_id`/`inventory_lot_id`/`receiving_farm_id` denormalized from the line. **No stored quantity or status column** — the root cohort's "opening quantity" is simply its own deterministic `receipt` ledger entry (Step 9); its current state is always `SUM()`-derived.

## Step 9 — Existence Ledger

`InventoryExistenceLedgerEntry`, append-only, targeting `inventory_quantity_cohort_id` (required; `inventory_item_id`/`inventory_lot_id`/`receiving_farm_id` denormalized). `.1` implements `entry_kind` values: `receipt`, `adjustment`, `reversal`, `split_out`, `split_in`. Reserve (unused, but the CHECK's `IN (...)` list should already be written to accept them cleanly in a future `_v2` widening) `consumption`/`scrap` for `STORE-INV-004`.

- `receipt`: exactly one deterministic opening entry per root cohort (`id = goods_receipt_line_id`, same as the cohort's own id — both share the deterministic value, matching the existing "reuse a PK value across two tables" precedent).
- `adjustment`: explicit `inventory_quantity_cohort_id` target (never invented — if no cohort exists for a physical discovery, the answer is a corrective Goods Receipt through Step 7, never a fabricated adjustment target), signed non-zero `quantity_delta_base`, mandatory `reason`, gated by the **separate** `inventory_adjustment.manage` permission (Step 14) — never bundled with `inventory_receipt.manage`. Cannot produce a negative cohort balance (lock the cohort `FOR UPDATE`, `SUM()` current balance, validate `balance + delta >= 0` before insert).
- `reversal`: append-only, `reversal_of_entry_id` FK to another entry of the **same** cohort, at most one reversal per target (partial unique index), no reversal-of-reversal, exact negation enforced by trigger.
- `split_out`/`split_in`: see Step 10.
- Balance is **always** `SUM()` — never a stored, authoritative "current_quantity" column anywhere in this schema.

## Step 10 — Quantity Split Foundation

Implement the **schema and internal service primitive only** — `split_cohort(source_cohort_id, allocations, actor, reason)`. This is a technical primitive, **internal to the codebase, not a domain command in its own right** — it is never described as an operator command, a public/primary route, a UI action, or a permission concept anywhere in code, comments, or API docs. It has no `Permission` of its own and is never routed. `.2`'s real operator-facing quality command ("Apply disposition to part of quantity" — never "Split Cohort") invokes this primitive internally, gated by `inventory_quality.manage`, which authorizes the *quality workflow*, not unrestricted generic quantity partitioning. A future domain (e.g. a later ticket needing to partition a cohort for an unrelated reason) may reuse this same internal primitive under its own command and its own permission — this primitive itself must not be tied to quality authorization at the service-function level, only at the calling command's level.

A split: locks the source cohort (`FOR UPDATE`); computes current balance; validates `SUM(allocation quantities) <= balance`; for each allocation, inserts one `split_out` entry (negative) on the source and one new child `InventoryQuantityCohort` (`parent_cohort_id` = source, same `inventory_lot_id`/`inventory_item_id`/`source_goods_receipt_line_id` as the source) with a matching `split_in` entry (positive). Supports partial (source retains a nonzero remainder, its own disposition chain untouched) and full (source balance fully allocated away) splits. Never fabricates a new `InventoryLot`. Reconciliation (`source_balance_before = SUM(allocations) + source_balance_after`) is enforced by a DB trigger validating the `split_out`/`split_in` pair magnitudes match exactly, in addition to the service-layer check.

If `.2`'s actual quality command needs this primitive, `.1` exposes it as an internal, non-routed service function only — no `Permission`, no route, until `.2`.

## Step 11 — Quality Foundation in `.1`

`.1` **must** create the `QualityDispositionEvent` table (`RECEIVED_QUARANTINED`, `RELEASED`, `HELD`, `HOLD_RELEASED`, `REJECTED`, `REVERSAL`; `inventory_quantity_cohort_id` required; `reverses_event_id` nullable, one-per-target, no reversal-of-reversal) — even though the release/hold/reject/correct commands are `.2` scope. This is not optional: without the table and the automatic opening event, a `qc_release_required` item's usable-quantity read model (Step 13) would have no fact to check against and would either wrongly report full usability (a real safety hole) or require a hard-coded, throwaway "always 0 usable" stub that `.2` would have to unwind.

- `qc_release_required = true`: the receipt transaction itself writes the opening `RECEIVED_QUARANTINED` event on the root cohort, atomically. This event is a **system/receipt fact, not a human decision, and is NEVER manually reversible — not in `.1`, not in `.2`, not ever.** It must not be an eligible `REVERSAL` target at either the service layer or the database layer (Step 18's DB backstops must enforce this, not just the service). If a receipt/item-policy mistake means this event should never have been written, the remedy is a receipt/configuration correction, never a reversal of the opening quarantine fact itself.
- `qc_release_required = false`: no opening event is written. Derived starting state is implicit `RELEASED`.
- **Do not** implement `RELEASED`/`HELD`/`HOLD_RELEASED`/`REJECTED`/human-correction commands, their permission wiring, or any UI in `.1` — that is `.2`. When `.2` adds human correction, it targets only the current, unreversed **human** disposition event (`RELEASED`/`HELD`/`HOLD_RELEASED`/`REJECTED`) — never the automatic opening event, which stays permanently outside the correction mechanism.

## Step 12 — Item / Seed-Profile Policy Freeze

Freeze trigger, uniform across every structural field in this domain family: **the item's first posted `GoodsReceiptLine`** — `_is_referenced(item_id) = EXISTS(SELECT 1 FROM goods_receipt_lines WHERE inventory_item_id = item_id)`, never a check against `inventory_lots` (which may not exist for a non-lot-tracked item). Freezes: `InventoryItem.base_uom_id`, `lot_tracking_required`, `expiry_tracking_required`, `qc_release_required`; `InventoryItemSeedProfile`'s very existence/`crop_id`/`variety_id` (Step 4). `name`/`inventory_category_id`/`status` on `InventoryItem` remain editable per the existing rules, unchanged. An `inactive` `InventoryItem` cannot be referenced by a **new** `GoodsReceiptLine` (Step 7).

## Step 13 — Existence Read Model Foundation

Read endpoints answering:
- Company-wide existence by `InventoryItem` (`SUM` over every cohort with that `inventory_item_id`, any lot, any Farm).
- Company-wide existence by `InventoryLot` (`SUM` over every cohort with that `inventory_lot_id`).
- Cohort/receipt provenance drill-down (which `GoodsReceiptLine`s and cohorts contribute to a total, with `receiving_farm_id` shown).

**Must not claim**: current Farm, Store, Bin, available-to-issue, or reserved quantity — none of those exist until `STORE-INV-002B`/`003`. Every provenance display reads **"Received at `<Farm>`"**, never "Current location" or "Currently at." Farm selection in the surrounding app shell must not change the company-wide number this endpoint returns.

## Step 14 — Permissions

Define, in `app/core/permissions.py`: `inventory.read`, `inventory_receipt.manage`, `inventory_adjustment.manage`, `inventory_quality.manage`. Wire `inventory_receipt.manage` to `POST .../goods-receipts`; `inventory_adjustment.manage` to the adjustment/reversal endpoints. `inventory_quality.manage` may be defined now (needed for a stable permission-catalog/migration boundary and for `tests/test_authz_mutation_enforcement_architecture.py`-style "every `.manage` bound to a route" checks) even though its routes don't exist until `.2` — if that structural test requires every `.manage` permission to be bound to a route, either defer defining `inventory_quality.manage` until `.2` or add a placeholder-free real route in `.2` before merge; **do not bind it to a fake or stub route just to satisfy the test.**

Proposed (not necessarily activated in `ROLE_PERMISSIONS` within `.1` — confirm with the same phased-activation posture this codebase already used for the observation-permission split): `storekeeper` → `inventory.read`, `inventory_receipt.manage`; `qc_officer` → `inventory.read`, `inventory_quality.manage`; `farm_manager` → `inventory.read`, `inventory_adjustment.manage` (mirrors the `recall.manage` seniority precedent — never `inventory_receipt.manage`/`inventory_quality.manage`); `tenant_admin` → all four automatically.

**Do not bundle receipt and adjustment authority into one permission.** Do not duplicate this backend permission policy in the frontend — render unconditionally, rely on backend `403`s, exactly matching the already-accepted, already-documented gap in `docs/product/OPEN_QUESTIONS.md` ("Frontend effective-permission signal").

## Step 15 — Audit

At minimum: `inventory_item_packaging.created`/`.updated`/`.deactivated`/`.reactivated`; `inventory_item_seed_profile.created`/`.updated`/`.removed`; `goods_receipt.posted`; `inventory_adjustment.recorded`; `inventory_existence_reversal.recorded`. **Do not** duplicate every immutable ledger row as a separate audit event when the ledger row already supplies the full transactional fact (matches `PRODUCE_LOT_LEDGER_MODEL.md`'s own restraint: no audit event for the deterministic harvest-receipt row). Audit write and the transactional write commit atomically, in the same `db.commit()`, never as a separate step that could fail independently.

## Step 16 — Idempotency

`client_command_id` + `request_fingerprint`, exactly this codebase's existing pattern (`inventory_item_service.py` is the direct template) for: the Goods Receipt command (header-level); every `InventoryItemPackaging`/`InventoryItemSeedProfile` mutation; Adjustment; Reversal; the internal split primitive (even though unrouted in `.1`, give it its own idempotency pair now so `.2` doesn't need a schema change to add one later). Do not invent a second idempotency mechanism.

## Step 17 — Concurrency

- Lock target for every existence-writing command: the `InventoryQuantityCohort` row (`FOR UPDATE`) — never `InventoryLot` (too coarse; would over-serialize sibling cohorts of the same lot).
- Multi-cohort operations (a split producing several children) lock only the one source cohort; new child rows need no lock (they don't exist yet).
- `InventoryLot` resolve-or-create must survive concurrent receipt posting without producing a duplicate canonical lot — insert, catch the Step 5 partial unique index's `IntegrityError`, re-select, verify the normalized identity actually matches, else surface the conflict error (never silently pick one).
- Adjustments/reversals against the same cohort are serialized by the cohort lock and cannot race into a negative balance — prove this with a real two-connection concurrency test (`threading.Barrier`, matching this codebase's own precedent — e.g. `test_farm_setup_idempotency_concurrency.py`), not merely a single-threaded unit test.
- A split cannot race with an adjustment (or, later, a consumption) against the same source cohort — both acquire the same `FOR UPDATE` lock on that cohort, so they serialize naturally; prove this with the same two-connection pattern.

## Step 18 — Database Backstops

Require explicit review (add DB constraints/triggers only where they materially protect integrity — do not move every business rule into SQL):

- Tenant consistency on every new table (composite FKs, `(tenant_id, id)` unique constraints, matching the existing pattern on every sibling ledger table).
- `InventoryLot.inventory_item_id`/`GoodsReceiptLine.inventory_item_id` consistency; cohort/lot/line consistency (a cohort's `inventory_lot_id` must equal its `source_goods_receipt_line_id`'s own resolved lot, and a split child's `inventory_lot_id` must equal its parent's).
- Direct-UOM vs. packaging-entry XOR CHECK on `GoodsReceiptLine`.
- `base_quantity > 0`, `= trunc(x,3)`, bounded, matching the existing weight-envelope convention.
- Append-only/no-hard-delete triggers (`reject_append_only_mutation`/`reject_hard_delete`) on every new table except `InventoryItemSeedProfile` pre-use (Step 4's narrow exception) and the reversible-lifecycle fields of `InventoryItemPackaging`.
- Signed-envelope CHECK per `entry_kind` on `InventoryExistenceLedgerEntry`.
- `split_out`/`split_in` reconciliation trigger (Step 10).
- Exactly one root cohort per `GoodsReceiptLine`; exactly one opening `receipt` ledger entry per root cohort; exactly one automatic opening `RECEIVED_QUARANTINED` event where `qc_release_required = true` (all three via the deterministic-id convention plus partial unique indexes, not solely application logic).
- The automatic opening `RECEIVED_QUARANTINED` event can **never** be the target of a `REVERSAL` row — a same-row/trigger CHECK on `QualityDispositionEvent` rejects any `REVERSAL` whose `reverses_event_id` points to an `event_kind = 'RECEIVED_QUARANTINED'` row, independent of and in addition to the fact that `.1` exposes no route that could attempt it.
- Non-negative existence — deferred-constraint trigger backstop in addition to the service-layer lock+check (mirroring `enforce_produce_lot_ledger_reconciliation`'s deferred-trigger pattern).
- The manufacturer-lot uniqueness/concurrency backstop index (Step 5).
- `SeedLot` ↔ `InventoryLot` field-equality trigger (Step 6).
- No cross-tenant reference possible from any new FK (every composite FK includes `tenant_id`).

---

## Focused Test Requirements

**Packaging**: create/update/deactivate/reactivate; quantity freeze after first receipt use; snapshot survives later deactivation/name change; package belongs to the correct item.

**Seed Details**: create/update/remove before first receipt; cannot add/change/remove after first receipt; a non-seed item remains non-seed after operational use; removal is audited; `SeedLot` linking follows crop/variety semantics.

**Lot**: tenant-wide resolve across Farms; same manufacturer+reference resolves the same lot; different manufacturers sharing a lot reference never merge; incomplete manufacturer identity never auto-matches; same canonical identity with compatible (including both-NULL) `manufacturing_date`/`expiry_date` reuses the existing lot; same canonical identity with a NULL-vs-known mismatch on either date raises the explicit conflict; same canonical identity with two different known values on either date raises the explicit conflict; concurrent resolve/create against the same canonical identity never duplicates a lot (two-connection test).

**Receipt**: atomic multi-line success; one bad line rolls back the whole receipt; inactive item rejected; direct-UOM path; packaging path; normalized-quantity snapshots preserved; idempotent replay; command-id-reused-with-different-payload conflict; Farm/tenant isolation.

**Cohort**: exactly one deterministic root per receipt line; opening quantity equals the line's base quantity; a non-lot-tracked item's cohort has `inventory_lot_id = NULL`; no fake/shadow lot anywhere.

**Ledger**: deterministic receipt opening entry; positive and negative adjustments; a resulting negative balance is rejected; `reason` mandatory; append-only reversal; hard-delete/update attempts rejected; concurrent negative adjustments proven safe under a real two-connection test.

**Split foundation**: partial split; full split; exact source/child reconciliation; total existence unchanged across a split; a child retains item/lot/source-line lineage; a split cannot race with another quantity mutation into a corrupted balance (two-connection test).

**Quality foundation**: a QC-required receipt auto-creates `RECEIVED_QUARANTINED`; a non-QC item gets no meaningless opening event; **the automatic opening `RECEIVED_QUARANTINED` event cannot be reversed — proven at the database layer directly** (a direct-SQL/direct-service attempt to insert a `REVERSAL` row targeting it is rejected by the trigger CHECK from Step 18, not merely absent because `.1` exposes no route for it); the opening event attaches to the root cohort; a failed receipt rolls back its opening event along with everything else.

**Policy freeze**: every structural item field freezes after the first posted line; Seed Details existence freezes identically.

**Read model**: company-wide existence aggregates correctly across Farms; "Received at `<Farm>`" is shown as provenance only; changing the selected-Farm context does not change the company-wide number.

**Migration**: clean upgrade; single head after upgrade; clean downgrade on an empty/pre-ticket DB; downgrade blocked once any operational row (`goods_receipts`, `inventory_lots`, ledger, disposition, cohort) exists.

**No full suite during implementation iterations** — focused tests only, per the common procedure.

---

## Acceptance Criteria / Completion Evidence

Use the categories defined in `STORE_INV_002A_COMMON_BUILD_PROCEDURE.md` §4. For `.1` specifically: `UI COMPLETE` is not applicable (no UI ships in `.1`); every other category applies. Completion evidence = the actual focused-test output for every case listed above, plus a clean migration upgrade/downgrade run against the guarded test-database tooling (`scripts/reset_test_database.py` / `tests/conftest.py::migrations_alembic_config()` — never a bare Alembic invocation, per `CLAUDE.md`).

## Commit / PR Boundary

`.1` is one PR (internally, commits may still be split by concern — migration+models, service layer, API routes — per the common procedure). It must not include any release/hold/reject/correction/`split_cohort` route, any Quality UI, or any Store & Inventory navigation entry — those are `.2`'s PR boundary.

## Production Migration / Deployment Implications

This phase **does** ship a migration. Follow `STORE_INV_002A_COMMON_BUILD_PROCEDURE.md` §3 exactly. Because `.1` includes the `QualityDispositionEvent` table and the automatic opening event but no way to act on it, a `qc_release_required` item received in production between `.1`'s deployment and `.2`'s deployment will correctly show as **not usable** (never falsely usable) and will simply wait for `.2`'s release mechanism — this is the intended, safe partial-slice behavior, not a defect to route around.
