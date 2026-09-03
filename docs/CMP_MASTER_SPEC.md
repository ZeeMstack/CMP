# CMP — Master Product and Domain Specification

Use this file only for product, domain, architecture, or hydroponic workflow work. Permanent coding rules are in the root `CLAUDE.md`.

## 1. Product

CMP is a multi-tenant operating and traceability platform for commercial hydroponic greenhouse farms. It creates a digital farm map and records how inputs, crop batches, carriers, harvest lots, pack lots, and finished goods move through it.

Initial market: hydroponic and substrate greenhouses using nursery propagation, leafy-green or vine production, packing, cold storage, and dispatch. Open-field agriculture and finance/HR functions are outside the initial scope.

Core promise: complete forward and backward traceability from supplier lot to customer dispatch.

## 2. Core Concepts

| Concept | Meaning | Examples |
|---|---|---|
| Location | Fixed occupiable place | chamber position, table position, grow-bag position, store bin |
| Asset | Managed physical item, often mobile | trolley, grow table asset, seeder, scale |
| Carrier | Identified object holding crop/product | seed tray, cultivation plate, grow cube, grow bag, crate, carton |
| Equipment | Performs work | seeder, printer, irrigation robot, packing line |
| Batch/Lot | Traceable production or inventory identity | crop batch, seed lot, harvest lot, pack lot |
| Occupancy | Who/what occupies a location during a period | tray on trolley Level |
| Movement | Same entity changes location | trolley moved to another chamber position |
| Transformation | Inputs become outputs | seedlings transferred from tray to plates |

A table, gutter, or cold room may have both a location record for occupancy and a linked asset record for maintenance.

A Carrier itself layers into three tiers. **CarrierType** is the platform-defined physical/operational role — seed tray, nursery cultivation plate, production cultivation plate, grow cube, grow bag, harvest crate — never defined by tenants. **CarrierSpecification** is a tenant-configured, reusable physical design for a CarrierType, recording facts such as dimensions and biological position count; not every CarrierType requires one, and Carriers registered before a specification existed (or of a CarrierType that does not yet require one) carry none. **Carrier** remains the individually traceable, farm-scoped physical instance with its own permanent identity, optionally built to one CarrierSpecification.

A CarrierType may be marked as requiring a specification before a new Carrier of that type can be registered; seed tray, nursery cultivation plate, and production cultivation plate all require one. Carriers registered before that requirement took effect keep no specification and remain valid. A specification's biological position count is a physical capacity fact, not an operational biological quantity — it is not the same as seed count. For Sowing, the physical sites actually used (sown site count) must not exceed a Seed Tray's known biological position count when both facts exist; seed count is never compared against it, since multiple seeds may legitimately occupy one planting position. For Transplant, the assigned plant count per destination Plate — a direct, 1:1 physical-position count — must not exceed that Plate's known biological position count when both facts exist; no capacity is invented where none is configured. Deactivating a CarrierSpecification blocks new Carrier registrations against it but never revokes an already-referencing Carrier's own eligibility for Sowing or Transplant.

## 3. Company and Farm Map

Administrative hierarchy:

```text
Tenant → Country → City/Region → Farm
```

Country and city support administration/reporting; normal crop occupancy starts within a farm.

A farm may contain nursery and production greenhouses, input store, packing hall, cold store, dispatch, hold/rejection, and waste areas.

Operational locations use one UUID-based parent-child tree. Farms select controlled templates and may omit optional levels; code must not assume a fixed depth.

### 3.1 Nursery Greenhouse

DOMAIN-FARM-001 (authoritative, implemented): does not use Zone/Span. Every section is a direct child of the Nursery greenhouse:

```text
Nursery
├─ Seeding Area / Station
├─ Germination Chamber
├─ Seedling Area → Seedling Table
├─ InterSalads → InterSalads Table
└─ InterVines → InterVines Table
```

- Seeder: equipment/work centre (`seeding_machine` asset type). CMP records which machine performed a sowing event.
- Germination Chamber (NURSERY-OPS-002A, implemented): occupiable directly, `capacity` = number of Trolleys it may simultaneously hold. There is no `Chamber Position` child location — a Germination Trolley Asset occupies the Chamber directly via `Occupancy`.
- Germination trolley: mobile asset, occupies a Germination Chamber directly (no intermediate chamber position). Carries one or more Levels (`shelf`-kind `AssetPosition`, one per physical shelf/level of the trolley).
- Germination Level (PILOT-UX-001B, implemented): a Level's `capacity` is the number of Seed Tray carriers it may simultaneously hold directly — never a seed/cell/plant/biological quantity. New Trolleys created through Farm Setup get Levels only, human-readable-coded `{trolley.code}-L{NN}` (e.g. `GT-001-L01`), with no child Slot layer. Trolleys created before PILOT-UX-001B may still carry legacy Levels with child Slot positions (one Seed Tray per Slot) — both shapes are classified per Level (`legacy_level` / `direct_level` / `invalid_level`, an unconfigured Level with neither a child Slot nor a configured capacity) and continue to coexist; legacy Slot data is never rewritten or deleted.
- Seed tray: carrier occupying a Trolley Level directly (new model) or one of that Level's Slots (legacy model). Aggregate capacity/seed-count only — individual tray cells/holes are not tracked.
- Nursery Cultivation Plate: carrier used in InterSalads — physically distinct from the Production Cultivation Plate used in Leafy-Greens greenhouses (§3.2); a leafy seedling transplants again, plate to plate, moving from Nursery to production. A Nursery Cultivation Plate occupies an InterSalads Table directly — no further child location level, matching the Production Cultivation Plate/Grow Table precedent. NURSERY-OPS-004B.1 (implemented): the biological Transplant onto a Nursery Cultivation Plate and its physical placement onto the selected InterSalads Table commit as one atomic operator command.
- Grow cube: carrier used in InterVines — one cube, one plant, travels with the plant into Vines production.

The system must derive a tray's effective location through `tray → Level (direct) → trolley → chamber` for the new model, or `tray → slot → Level → trolley → chamber` for a legacy Level — both resolve through the same generic, depth-agnostic recursive position-path walk.

### 3.2 Leafy-Greens Greenhouse

DOMAIN-FARM-001 (authoritative, implemented): exact chain, no shortcuts — Zone and Span are both mandatory, not optional, for this template:

```text
Greenhouse → Zone → Span → Grow Table
```

Stops at the table. The Production Cultivation Plate is a **carrier**, not a location — it occupies the Grow Table directly. There is no further "Table Position" location level: the farm does not define permanent, numbered plate positions on a table, because the physical plate itself is the numbered object. Default rule: one crop batch per plate; a table may hold multiple plates once its `capacity` is configured above 1 (capacity-aware occupancy, DOMAIN-FARM-002, implemented — see §5). `grow_table.default_occupiable` itself was not changed; Farm Setup creates the actual table instances with their real `occupiable`/`capacity` values.

### 3.3 Vines Greenhouse

DOMAIN-FARM-001 (authoritative, implemented): exact chain, no shortcuts:

```text
Greenhouse → Zone → Span → Grow Gutter → Grow-Bag Position
```

A grow-bag position is fixed; the grow bag is replaceable. **Grow Gutter Side (Left/Right) is not a placement level** — it describes plant canopy/branch training around the passage only, never a crop-location axis; every plant has branches trained on both sides regardless of gutter length. Plant/grow-cube positions (individual mortality/replacement tracking) are a later, explicitly-scoped ticket, not yet implemented.

### 3.4 Stores and Finished Goods

Use the same location engine:

```text
Store → [Store Area] → [Store Rack] → Store Bin   (Store Area/Rack optional; no Store Shelf — see docs/domain/STORE_INVENTORY_MODEL.md)
Cold Store → Room/Zone → Aisle/Rack → Position
```

Locations define allowed occupant types, status, capacity, and sanitation/release requirements. A Farm may have multiple Store root locations (e.g. Main Store, Chemical Store, Packaging Store) — distinguished by name/code, never by a store-kind column.

## 4. Identity and Labels

Every important record has a UUID, tenant ownership, human-readable code, status, and audit metadata. Codes are display/label identifiers, not relational keys.

QR codes contain a stable ID or lookup token. Record every print/reprint/replacement with actor, time, and reason.

## 5. Occupancy and Capacity

A crop batch can span many carriers and locations. Maintain active occupancy and historical periods rather than only a current-location field.

Occupancy supports:

- exclusive positions (one grow-bag position per grow bag; a Germination Trolley Level configured with `capacity=1`);
- quantity capacity (kg, crates, plates, plants, etc.);
- partial occupancy;
- effective and recorded timestamps;
- availability and history.

Use database constraints and transactional checks to prevent conflicting occupancy or capacity overflow.

DOMAIN-FARM-002 (authoritative, implemented): `locations.capacity`/`asset_positions.capacity` implement the "exclusive positions" case above plus multi-occupant targets — a configured positive integer count of simultaneously permitted *identified occupants* (Carrier/Asset occupancy rows), enforced by a row-locking DB trigger so no transaction can commit over capacity, even via direct SQL. `NULL`/`1` is exclusive (backward-compatible). This is not the "quantity capacity (kg, crates, plates, plants, etc.)" case above — biological/measured quantity per occupant remains unimplemented and out of DOMAIN-FARM-002's scope, as is Carrier-as-occupancy-target (e.g. a Grow Bag's contained Grow Cubes).

## 6. Movements

Movement keeps the same identity and changes its location. A movement command records source, destination, entity, batch, quantity/unit where applicable, work order, actor, device, effective time, recorded time, and idempotency key.

Validate before commit:

- tenant and farm access;
- active source occupancy;
- allowed destination type/status;
- capacity and sanitation/release;
- workflow permission and approval;
- duplicate/idempotent submission.

Commit the movement, occupancy changes, and audit event atomically. Corrections use reversal plus a corrected movement.

## 7. Transformations and Genealogy

Transformation converts identified inputs into outputs and preserves lineage.

Examples:

- seed lot + medium + empty trays → seeded trays;
- tray seedlings → cultivation plates or grow cubes;
- crop at production location → harvest lot;
- harvest lot → graded output, pack lots, rejection, and loss.

Support splits, partial transformations, remainder, rejection, samples, and controlled merges. Enforce:

```text
input = output + loss + rejection + sample + remainder
```

Merges must preserve every source batch/lot and require an approved rule.

## 8. Crop and Workflow Configuration

Crops are configuration, not code. A versioned workflow defines:

- crop/variety and production system;
- stages and allowed transitions;
- expected duration;
- permitted locations/carriers;
- observations and completion criteria;
- approvals, holds, rejection, split/merge rules;
- harvest mode: single, repeated, continuous, cut-and-regrow, or selective;
- quality, shelf-life, and storage requirements.

Existing batches remain linked to their assigned versions. Named crops may be used only as reference configurations to prove generic behavior.

## 9. Input Store

Store & Inventory is a first-class domain, not an appendix of the location engine. Full model: `docs/domain/STORE_INVENTORY_MODEL.md`. Consumable material (seeds, media, nutrients, crop protection, grow cubes/sponges/net pots, trays/plates/grow bags, labels, packaging, sanitation materials, spare parts) is tracked as quantity/UOM inventory; serialized equipment and reusable carriers keep their existing Asset/Carrier identity and are never duplicated as generic quantity stock.

How much material exists (an immutable existence ledger: receipt, consumption, scrap, adjustment, reversal) and where it currently is/who holds it (a separate custody/storage model: Store custody, Work Order custody, transfer, return) are two independent facts, never one. A Material Issue is a custody event, not consumption — it does not reduce existence quantity; only actual use, scrap, or a correction does.

Quality disposition (quarantined, released, held, rejected) is immutable event history, not a single mutable status field; expired is always derived from `expiry_date`, never a written state. Quarantined, held, rejected, or expired stock cannot normally be issued. Seed/input lot issuance links to the relevant work order; for seed specifically, actual consumption gains lineage to the crop batch only once it is created at the sowing event — never earlier.

## 10. Harvest, Packing, Cold Store, Dispatch

Required flow:

```text
Crop Batch/Location
→ Harvest Lot
→ Processing/Grading
→ Pack Lot / Finished-Goods SKU
→ QC Release
→ Cold-Store Position
→ Allocation/Pick
→ Dispatch
→ Customer
```

Support harvest work orders, containers and weights, partial/repeated harvest, grades, losses, processing batches, packaging use, QC hold/release, shelf life, pre-cooling, cold-store movements, temperature excursions, FEFO, picking, dispatch, returns, complaints, and recall.

Held, rejected, expired, or unreleased goods cannot be dispatched. FEFO override requires authorized reason.

Full genealogy:

```text
Supplier Lot → Material Issue → Crop Batch → Carrier/Location
→ Harvest Lot → Processing Batch → Pack Lot → Cold Store
→ Dispatch → Customer
```

## 11. Roles and Control

Backend permissions and farm access apply to all commands. Typical roles: tenant admin, facility manager, head grower, storekeeper, supervisor, operator, QC, auditor, packing/cold-store/dispatch users, and read-only management.

Where segregation matters, a user cannot approve or audit their own restricted transaction.

## 12. Offline Scanning

Use an online-first PWA with a local command outbox. Low-risk execution commands may queue offline; configuration, overrides, adjustments, and reversals remain online initially.

Each queued command has an idempotency key and status: queued, synchronized, rejected, or needs attention. Server validation remains authoritative.

## 13. Current Technical Milestone

Build only the foundation needed to prove the model:

1. Create Tenant A and Farm PB-01.
2. Create a nursery greenhouse and Germination Chamber GC-01 (occupiable, capacity = number of Trolleys).
3. Register Trolley GT-0001 with 8 Levels (`GT-0001-L01`...`GT-0001-L08`), each `capacity=5`.
4. Register Seed Tray ST-200-00001.
5. Place the trolley directly into Chamber GC-01 (no intermediate chamber position).
6. Place the tray directly onto Level GT-0001-L03.
7. Scan the tray and derive its complete location.
8. Move the trolley; preserve tray location history.
9. Prove Tenant B cannot access Tenant A data.

This milestone must demonstrate multi-tenancy, generic locations, relative/mobile containment, occupancy, movement, QR lookup, atomic audit history, and tenant isolation. Do not build crop-planning dashboards before it passes.

## 14. Deferred Sequence

After the milestone: asset/carrier lifecycle and labels → transformations/reconciliation → crop/workflow configuration → input store → production/quality → harvest/packing → cold store/dispatch → integrations.

Unresolved agronomic, quality, operational, and architecture decisions belong in `docs/product/OPEN-QUESTIONS.md`; do not guess.
