# Store and Inventory Model

Full detail: `CMP_MASTER_SPEC.md` §3.4, §9; `CLAUDE.md` rules 1, 3, 4, 5, 7, 8, 10, 12. This document is the **frozen design contract** for the Store & Inventory domain, approved by CTO + Chief Grower following the STORE-INV-001 discovery. **Nothing described here is implemented yet** — sections are marked per-ticket (`STORE-INV-001`, `STORE-INV-002A`, …) exactly like other domain docs mark `(implemented, CMP-xxx)`; the absence of that tag means design-only. This document does not restate the spec, and it does not duplicate the generic engines it builds on — see `LOCATION_MODEL.md`, `ASSET_CARRIER_MODEL.md`, `OCCUPANCY_MOVEMENT_MODEL.md` for those.

## Governing model — four separate questions

GrowCMP deliberately separates four independent inventory questions. They are never collapsed into one mutable stock-status or quantity field, and no future ticket may merge any two of them:

1. **Existence quantity** — how much material still physically exists? Answered only by the authoritative, immutable existence/quantity ledger (§8A).
2. **Physical/operational custody** — where is that existing quantity, and which operational custody currently holds it? Answered by the separate custody/storage model (§8B); Issue is a custody transfer, never destruction.
3. **Reservation** — who has claimed quantity for future use? Answered by §9; a reservation neither moves nor consumes stock.
4. **Usability** — can that stock legally/operationally be used right now? Derived from quality disposition, expiry, and other eligibility rules (§11) — never itself a stored quantity.

Each question has its own model in the sections below; none is ever inferred from another.

## 1. Purpose and scope

Store & Inventory is a first-class GrowCMP domain covering the physical farm store(s), the consumable materials held in them, and their traceable movement into production. It answers three questions GrowCMP does not yet answer: what consumable material exists, how much of it exists, and who currently has custody of it.

`STORE-INV-001` itself builds only master data (`UnitOfMeasure`, `InventoryCategory`, `InventoryItem`) and Store location hierarchy support. No lot, no ledger, no receipt, no reservation, no issue, and no operational inventory transaction exists until `STORE-INV-002A` and later tickets (§18).

## 2. Domain boundaries

- Store & Inventory owns: physical receipt, traceable inventory lot identity, lot/expiry, quality disposition, farm Store/bin location, reservation, issue/custody, consumption, return, operational transfer, and crop-input traceability.
- Store & Inventory does **not** own: supplier master, purchase requisition/order, supplier invoice, accounting, or financial inventory valuation — see §16 (Odoo boundary).
- Store & Inventory does not own crop/workflow policy: a Crop Batch is never created by a reservation or an issue, only by an actual sowing event (§14). `InventoryCategory` is reporting/classification metadata only and must never determine business behavior (§5) — this is the domain's own instance of `CLAUDE.md` rule 1 (crop/config-agnostic code).

## 3. Resource classification — frozen

Three resource classes are permanently distinct. They are never collapsed into one generic quantity-stock model, and existing identities are never duplicated:

| Class | Represented by | Tracked as |
|---|---|---|
| Consumable material | New `InventoryItem`/`InventoryLot` (§5, §7) | Quantity + UOM, via the existence ledger (§8) |
| Serialized / reusable equipment | Existing `Asset` (unchanged) | Individual identity, via `Occupancy`/`Movement` (§12) |
| Reusable farm carrier | Existing `Carrier` (unchanged) | Individual identity, via `Occupancy`/`Movement`/`BatchCarrierAssignment` (§12) |

Invariant: **no quantity ledger is ever created for an Asset or a Carrier.** An EC meter, a sprayer, a seed tray, or a cultivation plate is never represented as "N units on hand" — it already has permanent individual identity in its own registry.

## 4. Store location hierarchy — frozen

A **Store is an existing `Location`** (`location_type = store`). No competing `Store` table is introduced — `store → store_bin` was already seeded by CMP-004 and remains the base case (see `LOCATION_MODEL.md`). A Farm may have multiple root Store Locations (Main Store, Chemical Store, Packaging Store, Maintenance Store, a satellite greenhouse's own Store, etc.) — plain `Location` rows distinguished by `name`/`code`, not by a store-kind enum.

Two new optional intermediate `location_types` extend the tree, mirroring how Zone/Span are optional-but-typed levels elsewhere:

```text
store → store_bin
store → store_area → store_bin
store → store_rack → store_bin
store → store_area → store_rack → store_bin
```

- **Store Area** and **Store Rack** are both optional and independently omittable — a small store may go straight to `store_bin`; a larger one may use either or both levels.
- **`store_shelf` is explicitly not introduced now.** If a future need for shelf-level granularity below Rack emerges, it is a new decision, not assumed here.
- **`store_bin`** remains the occupiable, stock-placement leaf — the only Store-tree location type that is ever a movement/occupancy target or a future storage-movement location (§8's physical layer, when built).
- These are additive `location_type_hierarchy_rules` rows only (generic/`NULL`-classification scope — a Store never sits inside a greenhouse tree), with no structural change to `locations` itself and no effect on any existing `store`/`store_bin` row.

**`StoreProfile` is deferred, not decided against.** If future metadata (hazard class, temperature class, access restriction, responsible role) becomes genuinely necessary, it is added later as a 1:1 table against the root Store `Location` — not built now, and not represented by overloading `Location.name`/`code`.

## 5. Inventory master data — frozen

`STORE-INV-001`'s actual implementation scope, in full:

| Entity | Scope | Notes |
|---|---|---|
| `UnitOfMeasure` | Global, system-seeded | No tenant scoping — same pattern as `location_types`/`carrier_types` |
| Global UOM conversions | Global, system-seeded | Only universally-true, explicitly-approved pairs (§6) |
| `InventoryCategory` | Tenant-configured | Classification/reporting metadata **only** |
| `InventoryItem` | Tenant-scoped catalog | Reusable across every Farm in the tenant |
| Store location hierarchy | `Location`/`location_type` additions | §4 |

**`InventoryCategory` must never determine business behavior.** No code may branch on a category code (e.g. `if category.code == "seed"`) — a tenant is free to organize categories however it wants, and GrowCMP must not silently depend on any tenant's particular scheme. If a future feature genuinely needs a controlled semantic role (e.g. "this item is seed-traceable"), that role must be an explicit, system-controlled field or relationship — for seed specifically, that role is the `InventoryLot.seed_lot_id` linkage (§15), never an inference from category.

**`InventoryItem`** is the tenant-level consumable-material master, conceptually carrying: an immutable tenant-unique human-readable `code`; `name`; `InventoryCategory`; `base_uom`; an optional default purchase UOM and default issue UOM; an item-specific purchase-to-base conversion where the purchase UOM differs from base (§6); `lot_tracking_required`; `expiry_tracking_required`; `qc_release_required`; and an `active`/`retired` lifecycle. Reorder/minimum-stock metadata is explicitly deferred beyond `STORE-INV-001`. No price, cost, or accounting field is ever added to `InventoryItem` — that ownership stays with Odoo (§16).

## 6. UOM rules — frozen

Ledger quantities are eventually always stored in `InventoryItem.base_uom` — no ledger entry is ever recorded in a purchase or issue unit.

- **Global conversions** are permitted only where the relationship is universally, physically true and explicitly seeded — e.g. `kg ↔ g`, `L ↔ mL`. `SEED` and `EA` are both count concepts but are **not** automatically interchangeable; sharing a `quantity_kind` never implies automatic convertibility.
- **Item-specific conversions** (`1 fertilizer bag = 25 kg`, `1 seed can = 5,000 seeds`) belong to `InventoryItem`, never to a global table — `BAG`, `CAN`, `PACK`, and similar packaging units are never universal conversions.
- **Auditability requirement:** every operational command that enters a quantity in a non-base UOM must preserve all three of: the quantity/UOM as entered by the operator, the conversion factor actually used, and the resulting normalized base-UOM quantity. Example: operator enters `2 BAG`; the applied conversion is `25 kg/BAG`; the recorded base quantity is `50 kg` — all three facts persist, not just the final number.
- No generic enterprise UOM conversion graph is built. This mirrors the deliberate simplicity already established by `CarrierSpecification`'s single-canonical-unit dimensions (`ASSET_CARRIER_MODEL.md`), scaled up only as far as Inventory's real seeds/kg/L variety actually requires.

## 7. InventoryLot semantics — frozen (design for `STORE-INV-002A`)

Not implemented in `STORE-INV-001`.

`InventoryLot` represents the material's **traceable lot identity** — it does **not** mean "one Goods Receipt." The same supplier/manufacturer lot may arrive across more than one Goods Receipt and still reference the same `InventoryLot`, provided its immutable lot attributes match:

```text
InventoryLot RZ-MAM-LOT-17
├── Goods Receipt 001 — 50,000 seeds
└── Goods Receipt 017 — 25,000 seeds
```

`InventoryLot` = traceable lot identity. `GoodsReceiptLine` = one receipt transaction's quantity against that identity. The model must not structurally force one `InventoryLot` per receipt.

## 8. Quantity/existence ledger vs. storage/custody — critical frozen rule

This is the single most important correction from the STORE-INV-001 discovery: **a Material Issue does not reduce existence quantity.** Two questions are answered by two independent, separately-designed models — this deliberately parallels GrowCMP's own existing split between the finished-goods commercial ledger and finished-goods physical storage movements (`PRODUCE_LOT_LEDGER_MODEL.md`, `FINISHED_GOODS_STORAGE_MODEL.md`), which was built as two separate tickets for exactly this reason.

**A. How much material still exists** — the authoritative, immutable existence/quantity ledger. Conceptual entry families:

| Entry kind | Sign |
|---|---|
| Receipt | `+` |
| Consumption | `−` |
| Scrap | `−` |
| Adjustment | `+` or `−` |
| Reversal | opposite/corrective effect of the entry it reverses |

A normal Material Issue is **not** one of these — it never appears in the existence ledger as a debit. Only actual use (Consumption), loss (Scrap), a correction (Adjustment), or a correction-of-a-correction (Reversal) changes how much material exists.

**B. Where the existing material is / who has custody** — a separate storage/custody movement model, conceptually:

```text
Main Store → Work Order custody → Return to Store
Main Store → Work Order custody → Consumption
```

**Worked example** (seed, matching the frozen ticket exactly):

| Step | Existence quantity | Store custody | Work Order custody |
|---|---|---|---|
| Receipt 10,500 | 10,500 | 10,500 | 0 |
| Issue 10,500 to Work Order | 10,500 (unchanged) | 0 | 10,500 |
| Consume 10,200 | 300 | 0 | 300 |
| Return 300 | 300 (unchanged) | 300 | 0 |

No double decrement is ever permitted: existence quantity only changes on Consumption/Scrap/Adjustment/Reversal; custody only changes on Issue/Return/Transfer. The same quantity can never simultaneously sit in both Store custody and Work Order custody.

## 9. Reservation model — frozen

Reservation is **item-level by default** — `InventoryItem` required, `InventoryLot` **not** required, quantity required:

```text
InventoryItem: Mamutik Seed
InventoryLot:  NULL
Required Quantity: 10,200
```

FEFO lot selection happens at Issue time, against whichever lots currently carry a released quality disposition (§11) — reservation must not force premature lot selection during ordinary planning.

A reservation **may** optionally target a specific `InventoryLot` when an operational/QC/agronomic reason requires it — e.g. an approved seed lot, an isolated pesticide lot, a deliberately-selected expiring lot, or an investigation/control requirement. This is the exception, not the default path.

## 10. Issue vs. consumption — frozen

Material Issue is a **custody event**. Actual Consumption is a **destruction/use event**. These are never collapsed (§8). Unused issued quantity may be returned, consumed, or scrapped/lost-with-reason. A Work Order's material reconciliation must eventually be able to compare, per material: **Required, Reserved, Issued, Consumed, Returned, Scrapped, Variance** — each a distinct fact, never derived by assuming Issued = Consumed.

## 11. Quality / disposition — corrected frozen direction

A mutable `InventoryLot.qc_status` field is **not** the authoritative quality history. For controlled inventory, disposition history must be auditable, so disposition is modeled as immutable events — conceptually:

```text
RECEIVED_QUARANTINED
RELEASED
HELD
HOLD_RELEASED
REJECTED
```

(Exact event names may be refined during `STORE-INV-002A` design.) Current usable disposition is always **derivable from event history**. A cached "current status" column may exist later purely for query performance, but it can never replace the authoritative event log — the same discipline `QualityHold`'s own derived open/released state already establishes (`OBSERVATION_QUALITY_MODEL.md`).

**Expired is derived**, never a manually written lifecycle state: `expiry_date < current date`. Quarantined, held, rejected, or expired stock is not normally issuable. **Physical location and quality disposition are separate facts** — a material may be physically relocated (e.g. into a quarantine bin) while held, exactly as the existing finished-goods model already permits movement of held stock without releasing the hold (`FINISHED_GOODS_STORAGE_MODEL.md`, "Quality holds").

**QC segregation of duties (frozen):** wherever `InventoryItem.qc_release_required = true`, the user who records/owns the receipt must not be the sole user authorizing release — at minimum, `Received By ≠ Released By`. Standard role/permission checks (`AUTHORIZATION_MODEL.md`) apply on top of, not instead of, this identity check. This rule applies only where QC release is actually required for that item.

## 12. Asset/Carrier integration — frozen

Assets and Carriers keep their existing identities and lifecycle unchanged. Physical presence in a Store uses the existing `Occupancy`/`Movement` engine wherever compatible — `store_bin` simply becomes one more legal occupancy target (via new, additive `occupancy_compatibility_rules` rows), the same way `store_bin` already composes with the generic engine everywhere else in this codebase.

```text
Carrier:  Store Bin → Seeding → Nursery → cleaning → Store Bin
Asset:    Equipment Store → operational Location → Store
```

No quantity balance is ever created for a serialized Asset or a reusable Carrier (§3) — their presence in a Store is Occupancy, not Inventory.

## 13. Person custody rule — frozen (previously open, now closed)

`Occupancy` is **not** extended so that a User/person becomes a third physical target kind alongside Location and AssetPosition. A person is not a physical Location, and `Occupancy`'s target stays exactly the Location-XOR-AssetPosition shape it has always had (`OCCUPANCY_MOVEMENT_MODEL.md`).

Future equipment checkout instead uses a separate custody concept, conceptually `AssetCustodyAssignment`:

- Asset
- Custodian User
- Work Order (optional)
- Checked Out At
- Returned At
- Condition Out
- Condition In

Physical occupancy and human custody are **independent facts**, both true at once:

```text
Physical occupancy: GH-01 Nutrient Room
Custodian:           Ahmed
Work Order:          WO-FERT-084
```

An Asset must never be left "physically in Store" merely to avoid representing custody properly once it has genuinely been checked out — `AssetCustodyAssignment` and the Asset's real physical `Occupancy` are recorded independently and truthfully. This is `STORE-INV-005` scope; not implemented earlier.

## 14. Work Order integration — frozen boundary

`WorkOrder` is not implemented by any Store & Inventory ticket in this family. The future conceptual flow:

```text
Production Requirement
  → Work Order
  → Material Requirement
  → Reservation
  → Issue
  → Consumption / Return / Scrap
  → Reconciliation
```

Seeding example:

```text
Production Requirement
  → Seeding Work Order
  → reserve seed
  → issue seed
  → execute sowing
  → CropBatch created AT sowing
  → actual consumed seed gains Batch lineage
```

Pre-sowing material preparation (reservation, issue) must never create the biological `CropBatch` — it is created only by the sowing event itself, exactly as today (`SEED_SOWING_MODEL.md`). The existence ledger and reservation/issue tables reserve a nullable, currently-unused typed-reference seam for the eventual Work Order FK, following the same "add a new versioned trigger function, widen the CHECK in place, never touch the old function" idiom this codebase already uses four times (`PRODUCE_LOT_LEDGER_MODEL.md`) — `STORE-INV-002A`/`003` must not guess that column's name or target now.

## 15. Traceability patterns — frozen

Inventory itself stays generic; the **consuming** operational domain owns the specific Batch/Asset/Location traceability reference. `InventoryCategory` never drives which lineage applies (§2/§5) — only an explicit, system-controlled link (e.g. `InventoryLot.seed_lot_id`) does.

| Material | Lineage |
|---|---|
| Seed | `InventoryItem → InventoryLot → SeedLot linkage → SowingEvent/SowingEventLine → CropBatch` |
| Crop protection / biological | `InventoryLot → Treatment Event → affected Batch Placement(s)` |
| Fertigation | `Nutrient InventoryLot → Nutrient Preparation → Tank/Fertigation System → Application period → actual Locations/crop placements served` |
| Packaging | `InventoryLot → Packing operation/Work Order → Packed Lot` |
| Sanitation | `InventoryLot → Sanitation Work Order → Location/Asset cleaned` |
| Spare part | `InventoryLot → Maintenance Work Order → Asset repaired` |

**Seed:** `SeedLot` remains the existing crop-specific traceability identity (`crop_id`/`variety_id` scoped, unchanged — `SEED_SOWING_MODEL.md`). `InventoryLot` is the generic, crop-agnostic quantity/lot identity. The Batch still begins only at actual sowing — reservation or issue of seed never creates a `CropBatch`. **The exact `InventoryLot`↔`SeedLot` cardinality (one-to-one vs. one-to-many) is confirmed from actual existing `SeedLot` semantics during `STORE-INV-002A` design, not guessed here** — see `docs/product/OPEN_QUESTIONS.md`.

**Fertigation:** exact per-Batch nutrient consumption is never fabricated when one system feeds multiple batches — the consumption ledger entry references the system/location scope actually served. Future analytics may compute *estimated* per-batch allocations (by plant count, area, irrigation duration, flow, or other agronomic policy) but any such figure must be explicitly labeled **DERIVED/ESTIMATED** and must never replace the authoritative consumption fact. No estimated per-batch attribution is required for MVP.

## 16. Odoo boundary — corrected frozen direction

| GrowCMP owns | Odoo owns (future) |
|---|---|
| Physical receipt | Supplier master (where appropriate) |
| Traceable inventory lot | Purchase requisition |
| Lot/expiry | Purchase order |
| Quality disposition | Supplier invoice |
| Farm Store/bin location | Accounting |
| Reservation | Financial inventory valuation |
| Issue/custody | |
| Consumption | |
| Return | |
| Operational transfer | |
| Crop-input traceability | |

**Supplier Lot, an Odoo Purchase Order, an Odoo Receipt, and a GrowCMP `InventoryLot` are four distinct facts and are never conflated.** Rather than one generic `InventoryLot.external_reference` field standing in for all external context, `GoodsReceipt`/`GoodsReceiptLine` (`STORE-INV-002A`) preserve distinct, stable integration references — conceptually `external_system`, `external_document_id`, `external_line_id` — so a future sync can address the exact external document/line, not a blurred single string. Supplier/manufacturer lot identity (already partly captured on `SeedLot.supplier_lot_reference` today) is a separate fact from any of these external references. No Odoo integration is implemented by any ticket in this family.

## 17. Invariants

- Consumable inventory and serialized resources are different domain concepts (§3) — never merged.
- No quantity ledger exists for an Asset or a Carrier (§3, §12).
- Available stock never goes negative.
- No negative physical/custody balance.
- Issue does not destroy material — only Consumption/Scrap/Adjustment/Reversal change existence quantity (§8).
- Consumption can never exceed outstanding issued custody.
- Return can never exceed outstanding issued custody.
- The same quantity can never exist simultaneously in Store custody and Work Order custody (§8).
- The same Asset/Carrier can never have two active physical occupancies at once (existing `Occupancy` exclusivity, unchanged).
- Quality disposition is immutable event history — a later event corrects the previous disposition, it never rewrites it (§11).
- Expired stock is always derived from `expiry_date`, never a manually written state (§11).
- Quarantined/held/rejected/expired stock is not normally issuable (§11).
- Reservation must eventually be concurrency-safe (locking the relevant balance before insert).
- Every stock-writing command requires idempotency (`client_command_id` + fingerprint, the universal codebase convention).
- Cross-Farm movement requires an explicit transfer — never an implicit cross-farm issue.
- Tenant/Farm isolation applies to every new table exactly as everywhere else in GrowCMP.
- Immutable lot traceability attributes cannot silently change once set (mirrors `CarrierSpecification`'s structural freeze).
- Corrections use reversal/adjustment plus a stated reason — never an in-place rewrite of a prior transaction.
- Effective time and recorded time remain distinct wherever operationally relevant (receipt, issue, consumption, disposition events).

## 18. Roadmap / ticket boundaries

| Ticket | Scope |
|---|---|
| `STORE-INV-001` | Master data & Store foundation: `UnitOfMeasure`, global approved conversions, `InventoryCategory`, `InventoryItem`, `store_area`, `store_rack`, Store hierarchy rules, relevant Farm Setup UI (`Stores & Bins`, `Inventory Categories`, `Inventory Items`, `Units of Measure` — see `CEO_ALIGNMENT_SPEC.md`, "Approved later extension"). **Explicitly excludes:** `InventoryLot`, Goods Receipt, the quantity/existence ledger, the storage/custody ledger, reservation, material issue, Work Order, consumption, return, and any operational Store & Inventory pages. |
| `STORE-INV-002A` | Goods Receipt + Lot + Quantity Existence: `InventoryLot`, `GoodsReceipt`/`GoodsReceiptLine`, existence ledger (receipt/adjustment/reversal), quality/disposition events, stock-quantity read model. |
| `STORE-INV-002B` | Physical Storage: inventory storage movement, receipt placement, Store/bin quantity, bin-to-bin transfer, lot × location balance. |
| `WORK-ORDER-001` | Operational Work Orders: Seeding Work Order first, material requirements. |
| `STORE-INV-003` | Reservation & Material Issue: item-level default reservation, optional lot-specific reservation, FEFO, issue/custody transfer. |
| `STORE-INV-004` | Consumption / Return / Reconciliation: consumption, return, scrap/loss, variance, Work Order reconciliation. |
| `STORE-INV-005` | Asset & Carrier Custody: `AssetCustodyAssignment`, equipment checkout/return, Carrier Store lifecycle, cleaning/return. |
| `STORE-INV-006` | Extended Traceability: treatment, fertigation, packaging, maintenance integrations. |

## 19. Glossary of core terms

| Term | Meaning |
|---|---|
| Store | An existing `Location` with `location_type = store`; a Farm root; a Farm may have several |
| Store Area | Optional intermediate Store location level, between Store and Store Bin/Store Rack |
| Store Rack | Optional intermediate Store location level, between Store (or Store Area) and Store Bin |
| Store Bin | The occupiable, stock-placement leaf of the Store location tree |
| UnitOfMeasure | Global, system-seeded unit catalog entry (e.g. `kg`, `g`, `L`, `mL`, `EA`, `SEED`) |
| InventoryCategory | Tenant-configured classification/reporting metadata for `InventoryItem` — never a behavior switch |
| InventoryItem | Tenant-scoped consumable-material master, reusable across the tenant's Farms |
| InventoryLot | Traceable lot identity for consumable material — not the same thing as one Goods Receipt |
| GoodsReceipt / GoodsReceiptLine | A receipt transaction (header/line) recording quantity received against one or more `InventoryLot`s |
| Existence Quantity | How much material currently exists, per the immutable existence ledger — unaffected by Issue |
| Custody | Where existing material currently is / who holds it (Store vs. Work Order) — a separate fact from existence quantity |
| Material Issue | A custody event moving material from Store custody to Work Order custody; does not reduce existence quantity |
| Consumption | A destruction/use event that reduces existence quantity |
| Reservation | A soft allocation against an `InventoryItem` (lot optional) for a future Issue |
| Quality Disposition Event | One immutable event in a lot's quarantine/release/hold/reject history |
| AssetCustodyAssignment | Future (`STORE-INV-005`) record of a person's custody of an Asset, independent of the Asset's physical `Occupancy` |
