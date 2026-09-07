# STORE-INV-002A.2 — Quality + Operational Store UX — Build Plan

**Not a source of domain truth.** Canonical model: `docs/domain/STORE_INVENTORY_MODEL.md` §11 (as amended by the `STORE-INV-002A` discovery), `docs/product/CEO_ALIGNMENT_SPEC.md` ("GrowCMP navigation & UX principle"), `CLAUDE.md`. On any conflict between this document and the canonical domain model, **the canonical domain model wins**. Procedural rules are in `STORE_INV_002A_COMMON_BUILD_PROCEDURE.md`.

This phase builds on `.1` and **must not redesign the `.1` foundation** — `InventoryLot`, `GoodsReceiptLine`, `InventoryQuantityCohort`, and the existence ledger schema are frozen as `.1` shipped them. If `.2`'s work reveals a genuine defect in that foundation, stop and report it — do not silently patch around it inside `.2`.

---

## Objective

Make the material `.1` correctly withheld (quarantined/quantity-partitioned material) actually usable through real, auditable, segregation-of-duty-respecting quality decisions — and give operators the first real Store & Inventory workspace to do all of this without touching an API client or a database console.

## Prerequisites

1. Verify `.1`'s PR is merged to `main` and, if a production deployment gate applies to this rollout, that `.1`'s migration is live in production (per `STORE_INV_002A_COMMON_BUILD_PROCEDURE.md` §3) before starting `.2`'s own branch.
2. Re-read `.1`'s actual shipped schema/service code (not this build plan's description of it) — confirm field names, table names, and lock behavior exactly as merged, since minor naming may have shifted during `.1`'s own implementation review.

## Scope

The release/hold/reject/hold-release commands; human quality correction; the partial-quantity-disposition operator command ("Apply disposition to part of quantity," internally invoking `.1`'s `split_cohort` primitive — `split_cohort` itself remains an internal technical primitive, never an operator-facing concept, permission, or route); segregation-of-duty enforcement; the usable-existence read model; the first operational **Store & Inventory** navigation module (Overview / Receive Goods / Inventory / Quality).

## Explicit Out-of-Scope

Everything `.1` already excluded (custody/bin balance, Reservation/Issue/Consumption/Return/Transfer, Supplier Master, Odoo integration) remains out of scope here too — `.2` only unlocks *usability*, it does not add any new existence-changing or custody concept.

---

## Sequence

1. **Verify `.1` merged/current** (Prerequisites, above).
2. **Quality transition service** — implement `record_disposition(cohort_id, event_kind, actor, reason?)` enforcing the exact state machine from `STORE_INVENTORY_MODEL.md` §11:
   ```
   (no events, qc_release_required=false)  --> implicit RELEASED
   RECEIVED_QUARANTINED --> { RELEASED, HELD, REJECTED }
   implicit RELEASED    --> { HELD, REJECTED }
   RELEASED (explicit)  --> { HELD, REJECTED }
   HELD                 --> { HOLD_RELEASED, REJECTED }
   HOLD_RELEASED        --> { HELD, REJECTED }
   REJECTED             --> terminal (ordinary transition), correctable via Step 4
   ```
   `HELD`/`REJECTED` reachable directly from any non-terminal state, including implicit `RELEASED` — do not require an intermediate `HOLD` before a direct `REJECTED`. Own `client_command_id`/fingerprint pair, standard cohort-lock discipline.
3. **Partial quantity quality action** — a real, permissioned, idempotent operator command, gated by `inventory_quality.manage`, that **internally invokes** `.1`'s internal `split_cohort` primitive as an implementation detail. User-facing label **"Apply disposition to part of quantity"** (or equivalent plain language) — **never** "Split Cohort" anywhere in UI copy, error messages, route names, or API-facing field labels visible to an operator; `split_cohort` itself remains a private, unrouted technical primitive with no `Permission` of its own — `inventory_quality.manage` authorizes this quality command, not generic quantity partitioning as a standalone capability. Internally: split the source cohort, apply the caller-chosen initial disposition to each resulting child, retain the source's own disposition/remainder untouched for a partial split. Exact reconciliation (per `.1`'s own trigger) and full audit/idempotency, reusing `.1`'s primitive verbatim — do not reimplement split mechanics here.
4. **Human quality correction / current-event reversal** — `correct_disposition(cohort_id, reason, replacement?)`. This command corrects **human decisions only** — `RELEASED`, `HELD`, `HOLD_RELEASED`, `REJECTED`. The automatic opening `RECEIVED_QUARANTINED` event is a system/receipt fact, not a human decision, and is **permanently excluded from this command — it is never a valid `cohort`'s "current event" target for correction, under any circumstance, with or without a replacement.** If a receipt/item-policy mistake means a cohort should never have opened `RECEIVED_QUARANTINED` at all, the remedy is a receipt/configuration correction (`.1`'s domain), never a reversal of the opening quarantine fact.
   - Targets only the **current** (latest, not-yet-reversed) **human** `QualityDispositionEvent` for that cohort — reject a request naming any other event, or the opening event, as "not current"/"not eligible," never silently reinterpret it.
   - Mandatory `reason`.
   - No mutation or deletion of the original event — insert one `REVERSAL` row.
   - No reversal-of-reversal (partial unique index on `reverses_event_id`, plus a same-row CHECK that a `REVERSAL`'s own target is never itself a `REVERSAL`, and — reiterating `.1`'s own DB backstop — never `RECEIVED_QUARANTINED`).
   - Optionally bundles one immediate replacement human decision in the same transaction.
5. **Segregation-of-duties enforcement** — service-layer identity check, independent of the permission grant: any command (an original human disposition **or** a correction) whose **net resulting state** is usable (`RELEASED` or `HOLD_RELEASED`) requires `actor_user_id != cohort → source_goods_receipt_line → goods_receipt.received_by_user_id` — **the comparison is against the original receiver of the Goods Receipt, and only that.** It is never anchored to the prior QC actor, the cohort's creator, the split's creator, or whoever performed the disposition event now being corrected — those identities are irrelevant to this check. A restrictive outcome (`HELD`, `REJECTED`) carries no such restriction — a receiver holding `inventory_quality.manage` may freely place their own delivery on Hold or Reject it. Do not invent any restriction beyond this exact rule.
6. **Usable-existence derivation** — `usable_quantity(item|lot) = SUM(current balance of every cohort whose current derived disposition ∈ {implicit RELEASED, RELEASED, HOLD_RELEASED} AND NOT expired)`. Never label this **"available"** — Reservation does not exist yet, and "available" implies unreserved availability this ticket does not model.
7. **Operational Store & Inventory navigation/workspace** — see UX section below. This is the first turn this module is allowed to appear in primary navigation at all (`CEO_ALIGNMENT_SPEC.md`'s "no placeholder/disabled entries for modules that aren't functional yet" rule) — it must not ship until every screen below is real and working end-to-end.
8. **Receive Goods UI** — thin client over `.1`'s already-shipped `record_goods_receipt` command; no new backend behavior introduced here beyond what `.1` built.
9. **Inventory UI** — existence + usable-quantity read views over `.1`'s (existence) and `.2`'s (usable) read models.
10. **Quality UI** — the new, `.2`-specific work surface (release/hold/reject/hold-release, partial-quantity action, correction).
11. **Overview** — factual summary landing page, no invented readiness score.
12. **Focused tests** — see below.
13. **PR / deployment evidence** — per the common procedure; see Production implications below.

---

## Permissions

`inventory_quality.manage` (defined in `.1`, Step 14 there) is now bound to real routes: `record_disposition`, the partial-quantity action, `correct_disposition`. If `.1` deferred defining this permission until a real route existed, define it now. Activate the proposed `.1` role grants (`storekeeper`, `qc_officer`, `farm_manager`, `tenant_admin`) in `ROLE_PERMISSIONS` at this point if they were not already activated in `.1` — confirm with the CTO which phase actually flips the switch in `ROLE_PERMISSIONS`, mirroring this codebase's own precedent of separating "permission exists in the model" from "role grant is active" (the AUTHZ-002B1 → AUTHZ-002B2 split). Do not duplicate this permission mapping in the frontend — unconditional rendering, backend-403-driven, unchanged posture from `.1`.

---

## Store & Inventory Operational UX

Top-level module appears **only now**, and only because the workflow is genuinely complete end-to-end:

```
Store & Inventory
├── Overview
├── Receive Goods
├── Inventory
└── Quality
```

Workflow-first — **no primary page named** `Inventory Lot`, `Quantity Cohort`, `Existence Ledger`, or `GoodsReceiptLine`. Those stay internal/drill-down concepts, never their own navigation destination (`CEO_ALIGNMENT_SPEC.md`'s frozen navigation principle).

**Overview** — factual summary only: recent receipts, quantities awaiting a quality action, useful next actions. No invented "Store & Inventory Ready" score (mirrors the existing, correct restraint already established for the Store & Inventory Setup workspace's own Overview).

**Receive Goods** — Farm-scoped, currently-selected Farm clearly visible; multi-line client-side form (add line, review, submit — no server Draft); direct-quantity or packaging entry with a normalized-quantity preview; manufacturer name/lot reference/expiry fields shown when relevant to the selected item's tracking policy; seed-specific fields (link/create Seed Lot) shown **only** for an item that **has Seed Details** (an `InventoryItemSeedProfile` exists for it — no "active"/"inactive" state, since the entity carries none) — never offered generically. Review → **Record Receipt**.

**Inventory** — company-wide existence and company-wide usable quantity, by Item, with drill-down to Lot/receipt/cohort lineage. Must explicitly state that current Store/Bin location is not yet tracked (that's `STORE-INV-002B`). "Received at `<Farm>`" is shown only as provenance, never as current location. The Farm selector in the app shell must not change the company-wide numbers shown here.

**Quality** — a work queue: quantity, item, manufacturer lot (if applicable), receipt origin, current disposition. Actions: Release / Hold / Reject / Hold-Release, the partial-quantity disposition action, and Correct (on the current event only). Segregation-of-duty rejections must be surfaced as clear, actionable errors ("You received this delivery — ask another authorized user to release it"), never a generic permission-denied message that leaves the operator guessing why an action they otherwise hold permission for was refused.

**Do not expose** Issue, Reservation, Return, or Transfer anywhere in this module — none of them exist yet.

---

## Focused Test Requirements

- Quality state machine: every legal transition in Step 2's diagram succeeds; every illegal transition (e.g. `REJECTED → RELEASED` directly) is rejected; `HELD`/`REJECTED` reachable directly from implicit `RELEASED` with no forced intermediate step.
- Correction: reversal of the current human event succeeds; reversal of a superseded (non-current) human event is rejected; reversal-of-reversal is rejected; **any attempt to reverse the automatic opening `RECEIVED_QUARANTINED` event is rejected outright, with or without a proposed replacement** (proves `.1`'s DB backstop holds even if a service-layer bug tried to allow it); derived current-state-after-reversal is proven to fall through correctly (not defaulting to `RELEASED`).
- Segregation of duty: an actor equal to the **Goods Receipt's original `received_by_user_id`** attempting `RELEASED`/`HOLD_RELEASED` (original or via correction) is rejected; the same actor attempting `HELD`/`REJECTED` (original or via correction) is permitted; an actor who merely placed a *prior* disposition event (e.g. the `HELD` now being corrected), or who created the cohort/split, but is **not** the original receiver, is permitted to grant usability — proving the check is anchored to the receiver alone, never to any intermediate actor; a correction whose net effect is restrictive is unrestricted regardless of actor.
- Partial-quantity action: full end-to-end operator-command test (not just `.1`'s internal primitive) proving the resulting child cohorts, their independent disposition, and unchanged parent lineage.
- Usable-existence read model: matches the worked examples in `STORE_INVENTORY_MODEL.md` §11/§7 exactly (e.g. 450 kg Released + 50 kg Rejected out of one 500 kg line → usable = 450; a later 100 kg partial Hold out of an already-Released 500 kg line → usable = 400); never labeled "available" anywhere in API response or UI copy.
- Permission/authorization architecture-walk test extended to cover the new `.2` routes (mirrors `test_authz_mutation_enforcement_architecture.py`'s existing style): every new mutation route requires `require_permission`, is `.manage`-gated, denies a zero-permission role, produces zero side effects and zero audit writes on denial.
- UI: Receive Goods happy path (direct and packaging entry, seed-linked and non-seed); Quality work queue lists and actions correctly, including a visible segregation-of-duty rejection; Inventory view shows correct company-wide totals and correct provenance labeling; navigation module does not appear behind an incomplete-feature flag anywhere in this pass.
- No full suite during implementation iterations, per the common procedure.

---

## Acceptance Criteria / Completion Evidence

Use `STORE_INV_002A_COMMON_BUILD_PROCEDURE.md` §4's categories. `.2` is the first phase where `UI COMPLETE` applies. `DATABASE COMPLETE`/`MIGRATION VERIFIED` apply only if `.2` genuinely needs a schema change (expected: **none** — see Production implications below); if implementation reveals a real need for one, stop and report it rather than silently adding it, since it would mean `.1`'s foundation was incomplete.

## Commit / PR Boundary

One PR (commits may still separate service-layer, API, and frontend concerns). Must not touch `.1`'s already-merged schema/service files except to *use* them — no redesign, per this document's own opening constraint.

## Production Migration / Deployment Implications

**No new migration is expected.** `.1` already shipped the complete `QualityDispositionEvent` table (including `REVERSAL` support) and the complete cohort/split schema — `.2` is additive service/API/UI work only, on top of already-live schema. Deployment is therefore the standard code-only path (API + Web image deploy, `/health`/`/ready` verification, UI smoke) per `STORE_INV_002A_COMMON_BUILD_PROCEDURE.md` §3, skipping the migration-specific steps (5–8) entirely. If implementation genuinely uncovers a need for a schema change, treat that as a signal to stop and re-review `.1`'s foundation before proceeding, not as a routine addition.
