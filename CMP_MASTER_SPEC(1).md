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
| Occupancy | Who/what occupies a location during a period | tray in trolley slot |
| Movement | Same entity changes location | trolley moved to another chamber position |
| Transformation | Inputs become outputs | seedlings transferred from tray to plates |

A table, gutter, or cold room may have both a location record for occupancy and a linked asset record for maintenance.

## 3. Company and Farm Map

Administrative hierarchy:

```text
Tenant → Country → City/Region → Farm
```

Country and city support administration/reporting; normal crop occupancy starts within a farm.

A farm may contain nursery and production greenhouses, input store, packing hall, cold store, dispatch, hold/rejection, and waste areas.

Operational locations use one UUID-based parent-child tree. Farms select controlled templates and may omit optional levels; code must not assume a fixed depth.

### 3.1 Nursery Greenhouse

```text
Nursery
├─ Seeding Area / Station
├─ Germination Area → Chamber → Chamber Position
├─ Seedling Area → [Zone] → Grow Table → Table Position
├─ InterVines → [Zone] → Grow Table → Table Position
└─ InterSalads → [Zone] → Grow Table → Table Position
```

- Seeder: equipment/work centre.
- Germination trolley: mobile asset with shelves and slots.
- Seed tray: carrier occupying a trolley slot.
- Trolley: occupies a chamber position.
- Grow cube: carrier used in InterVines.
- Cultivation plate: carrier used in InterSalads.

The system must derive a tray’s effective location through `tray → trolley slot → trolley → chamber position`.

### 3.2 Leafy-Greens Greenhouse

```text
Greenhouse → [Zone] → Span → Grow Table → Table Position
```

Cultivation plates occupy positions. Default rule: one crop batch per plate; a table may hold multiple batches if every plate is identified.

### 3.3 Vines Greenhouse

```text
Greenhouse → [Zone] → Span → Grow Gutter → [Left/Right] → Grow-Bag Position
```

A grow-bag position is fixed; the grow bag is replaceable. Single-sided gutters must be supported. Plant/grow-cube positions may be added when plant-level traceability is configured.

### 3.4 Stores and Finished Goods

Use the same location engine:

```text
Input Store → Zone → Rack → Shelf/Bin
Cold Store → Room/Zone → Aisle/Rack → Position
```

Locations define allowed occupant types, status, capacity, and sanitation/release requirements.

## 4. Identity and Labels

Every important record has a UUID, tenant ownership, human-readable code, status, and audit metadata. Codes are display/label identifiers, not relational keys.

QR codes contain a stable ID or lookup token. Record every print/reprint/replacement with actor, time, and reason.

## 5. Occupancy and Capacity

A crop batch can span many carriers and locations. Maintain active occupancy and historical periods rather than only a current-location field.

Occupancy supports:

- exclusive positions (one trolley per chamber position, one tray per trolley slot);
- quantity capacity (kg, crates, plates, plants, etc.);
- partial occupancy;
- effective and recorded timestamps;
- availability and history.

Use database constraints and transactional checks to prevent conflicting occupancy or capacity overflow.

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

Operational inventory uses an immutable stock ledger. Typical items: seeds, media, nutrients, crop protection, grow cubes/sponges/net pots, trays/plates/grow bags, labels, packaging, and sanitation materials.

Typical states: received, quarantine, approved, held, rejected, reserved, issued, partly consumed, consumed, expired, returned.

Quarantined, held, rejected, or expired stock cannot be issued. Seed/input lot issuance must link to the relevant work order and crop batch.

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
2. Create a nursery greenhouse and Germination Chamber GC-01.
3. Generate 20 chamber positions.
4. Register Trolley GT-0001 with 8 shelves × 5 slots.
5. Register Seed Tray ST-200-00001.
6. Place the tray at Shelf 03 / Slot 04.
7. Place the trolley at Chamber Position 12.
8. Scan the tray and derive its complete location.
9. Move the trolley; preserve tray location history.
10. Prove Tenant B cannot access Tenant A data.

This milestone must demonstrate multi-tenancy, generic locations, relative/mobile containment, occupancy, movement, QR lookup, atomic audit history, and tenant isolation. Do not build crop-planning dashboards before it passes.

## 14. Deferred Sequence

After the milestone: asset/carrier lifecycle and labels → transformations/reconciliation → crop/workflow configuration → input store → production/quality → harvest/packing → cold store/dispatch → integrations.

Unresolved agronomic, quality, operational, and architecture decisions belong in `docs/product/OPEN-QUESTIONS.md`; do not guess.
