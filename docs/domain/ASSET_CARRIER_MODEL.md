# Asset and Carrier Model

Full detail: `CMP_MASTER_SPEC.md` §2, §3.1; `CLAUDE.md` rule 4. This document summarizes the approved classification; it does not restate the spec.

## Distinct concepts

Fixed locations, mobile assets, crop carriers, and equipment are distinct record types (`CLAUDE.md` rule 4):

- **Asset** — a managed physical item, often mobile (e.g. trolley, seeder, scale). Assets can require maintenance tracking.
- **Carrier** — an identified object that holds crop/product and is replaceable (e.g. seed tray, cultivation plate, grow cube, grow bag, crate, carton).
- **Equipment** — performs work (e.g. seeder, printer, irrigation robot, packing line).
- **Location** — see `LOCATION_MODEL.md`.

A structure such as a table or gutter may have both a linked asset record (for maintenance) and a linked location record (for occupancy) — see `LOCATION_MODEL.md`.

## Germination trolley

The trolley is a **mobile asset**. Its shelves and slots are **relative positions belonging to the trolley**, not independent farm locations — a tray's effective location is derived through the trolley's slot and the trolley's own current Occupancy in a Germination Chamber (`LOCATION_MODEL.md`, `OCCUPANCY_MOVEMENT_MODEL.md`). The Chamber has no fixed/identifiable trolley parking positions of its own (no `chamber_position`) — the Trolley occupies the Chamber directly (NURSERY-OPS-002A).

## Grow bag

A grow bag is a **replaceable crop carrier only** — not an asset. It occupies a fixed grow-bag position (a location). The carrier and the position it occupies are separate records; the carrier can be replaced without affecting the position record. Any future maintenance or inventory treatment of grow bags (e.g. as a stock item in the input store) is handled separately from this classification and is not decided here.

## Grow tables and grow gutters

These have **linked asset and operational-location records**: the physical/maintainable structure is an asset; the occupiable positions it provides (table position, grow-bag position) are locations.

## Asset and carrier registry (implemented, CMP-005)

**Types.** Global, system-defined, seeded by migration — not tenant-configurable, no type-management API. `asset_types` (`germination_trolley`, `transfer_trolley`, `seeding_machine`, `weighing_scale`, `label_printer`) carry one behavior flag, `supports_positions` — true only for `germination_trolley`. `carrier_types` (`seed_tray`, `cultivation_plate`, `grow_cube`, `grow_bag`, `harvest_crate`) carry no extra flags. `grow_table`/`grow_gutter` asset records and finished-goods/pallet carrier types are deferred to a later ticket.

**Lifecycle status.** Both assets and carriers use `active`, `inactive`, `damaged`, `retired`, enforced by a `CHECK` constraint. A second `CHECK` requires `retired_date` whenever `status = 'retired'`. Maintenance condition is a separate, future concern — this status is registry lifecycle only. There is no status-change/retirement command in this ticket; records are created `active`.

**Codes.** Trimmed, uppercased, never blank, never a primary key. Unique case-insensitively **per tenant across the whole registry** (all assets in one scope, all carriers in another) — not per farm, not per type, not global across tenants. The same code may be reused by different tenants.

**Trolley positions.** One generic `asset_positions` table holds shelves and slots for any asset whose type has `supports_positions = true`. `position_kind` is `shelf` or `slot`; a `CHECK` constraint ties the two together with parent nullability (a shelf has no parent, a slot always does). Cross-row rules a `CHECK` can't express — the owning asset's type must support positions, and a slot's parent must be a shelf on the same asset — are enforced by a `BEFORE INSERT OR UPDATE` trigger. Sibling codes (shelves under one asset; slots under one shelf) are unique case-insensitively via two partial indexes, the same pattern used for locations.

**Trolley structure generation.** One command creates the full shelf/slot tree atomically — shelf and slot codes are always server-generated from a prefix/count/padding, never client-supplied, capped at 1,000 total position rows per command (a technical safety limit, not a commercial capacity assumption). Either the whole structure is created or none of it is. One audit event is recorded per command, not per shelf or slot.

**Audit.** `asset.registered`, `carrier.registered` per record; `carrier.bulk_registered`, `asset.positions_generated` once per command. A failed command leaves no partial records and no audit event.

**Deletion protection.** Assets, carriers, and asset positions are immutable history: a `BEFORE DELETE` trigger rejects direct SQL deletion, and no application service exposes a delete operation.

**Deferred:** occupancy, movement, farm-location assignment, crop batches/contents/quantities, transformations, QR/scan identity, label printing, maintenance work orders, and inventory valuation.
