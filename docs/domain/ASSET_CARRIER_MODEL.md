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

The trolley is a **mobile asset**. Its Levels (and, for a legacy Trolley, their child Slots) are **relative positions belonging to the trolley**, not independent farm locations — a tray's effective location is derived through the trolley's Level (or Level+Slot) and the trolley's own current Occupancy in a Germination Chamber (`LOCATION_MODEL.md`, `OCCUPANCY_MOVEMENT_MODEL.md`). The Chamber has no fixed/identifiable trolley parking positions of its own (no `chamber_position`) — the Trolley occupies the Chamber directly (NURSERY-OPS-002A).

**Level (PILOT-UX-001B, implemented).** A Level is the existing `shelf`-kind `AssetPosition` (see below) — a physical shelf/level of the trolley. `Level.capacity` is the number of Seed Tray carriers it may simultaneously hold, never a seed/cell/plant/biological quantity. A Level is classified purely from its own current structure, independently of every other Level on the same Trolley (a single Trolley may carry both kinds at once):

- **`direct_level`** — zero child Slots, `capacity` configured. A Seed Tray occupies the Level directly, up to `capacity` (the same generic, row-locked, N-occupant `AssetPosition.capacity` mechanism DOMAIN-FARM-002 already built for other targets — no schema change was needed for this). New Trolleys created through Farm Setup only ever produce Levels of this kind.
- **`legacy_level`** — has one or more child Slots (the pre-PILOT-UX-001B shape: one exclusive numbered Slot per tray). A Seed Tray occupies a child Slot; direct occupancy on the Level itself is rejected. Existing legacy Levels/Slots are never rewritten, renamed, or deleted — they remain fully readable and placeable exactly as before.
- **`invalid_level`** — zero child Slots AND `capacity IS NULL`: an unconfigured Level (a Farm Setup gap, not a normal state). Rejected as a placement target; NULL capacity is never silently treated as capacity=1.

## Grow bag

A grow bag is a **replaceable crop carrier only** — not an asset. It occupies a fixed grow-bag position (a location). The carrier and the position it occupies are separate records; the carrier can be replaced without affecting the position record. Any future maintenance or inventory treatment of grow bags (e.g. as a stock item in the input store) is handled separately from this classification and is not decided here.

## Grow tables and grow gutters

These have **linked asset and operational-location records**: the physical/maintainable structure is an asset; the occupiable positions it provides (table position, grow-bag position) are locations.

## Store custody (frozen design, STORE-INV-001 family — not yet implemented)

Physical presence of an Asset or a Carrier in a Store uses the existing Occupancy/Movement engine unchanged — a `store_bin` is just one more legal target, added via new `occupancy_compatibility_rules` rows. No quantity balance is ever created for an Asset or a Carrier; they keep their own individual identity, never generic stock. Human custody (an Asset "checked out" to a person) is deliberately **not** a third Occupancy target — a person is not a physical Location. It is a separate future concept, `AssetCustodyAssignment` (`STORE-INV-005`), independent of the Asset's real physical Occupancy. Full detail: `docs/domain/STORE_INVENTORY_MODEL.md` §12–13.

## Asset and carrier registry (implemented, CMP-005)

**Types.** Global, system-defined, seeded by migration — not tenant-configurable, no type-management API. `asset_types` (`germination_trolley`, `transfer_trolley`, `seeding_machine`, `weighing_scale`, `label_printer`) carry one behavior flag, `supports_positions` — true only for `germination_trolley`. `carrier_types` (`seed_tray`, `cultivation_plate`, `grow_cube`, `grow_bag`, `harvest_crate`) carry no extra flags. `grow_table`/`grow_gutter` asset records and finished-goods/pallet carrier types are deferred to a later ticket.

**Lifecycle status.** Both assets and carriers use `active`, `inactive`, `damaged`, `retired`, enforced by a `CHECK` constraint. A second `CHECK` requires `retired_date` whenever `status = 'retired'`. Maintenance condition is a separate, future concern — this status is registry lifecycle only. There is no status-change/retirement command in this ticket; records are created `active`.

**Codes.** Trimmed, uppercased, never blank, never a primary key. Unique case-insensitively **per tenant across the whole registry** (all assets in one scope, all carriers in another) — not per farm, not per type, not global across tenants. The same code may be reused by different tenants.

**Trolley positions.** One generic `asset_positions` table holds shelves ("Levels") and slots for any asset whose type has `supports_positions = true`. `position_kind` is `shelf` or `slot`; a `CHECK` constraint ties the two together with parent nullability (a shelf has no parent, a slot always does). Cross-row rules a `CHECK` can't express — the owning asset's type must support positions, and a slot's parent must be a shelf on the same asset — are enforced by a `BEFORE INSERT OR UPDATE` trigger. Sibling codes (shelves under one asset; slots under one shelf) are unique case-insensitively via two partial indexes, the same pattern used for locations. Introducing `direct_level` capacity (PILOT-UX-001B) required no change to this table, its constraints, or these triggers — only a new `occupancy_compatibility_rules` row (see `OCCUPANCY_MOVEMENT_MODEL.md`) and application-layer validation.

**Trolley structure generation.** Two generation paths exist, both server-generating codes from a prefix/count/padding, never client-supplied, capped at 1,000 total position rows per command:

- The GENERIC path (`asset_service.generate_positions`, the public `POST /farms/{farm_id}/assets/{asset_id}/positions` endpoint, `AssetPositionsGenerate`) creates the full legacy shelf+slot tree atomically, unchanged by PILOT-UX-001B — still the only way to create a legacy-shaped structure, and still available for any future generic use.
- The Nursery-Farm-Setup-specific path (`asset_service._generate_levels_core`, PILOT-UX-001B) creates ONLY root `shelf`-kind Levels, each with `capacity` set directly, and deliberately no child Slot rows. Its Level-code prefix is always derived server-side from the Trolley's own code (`{trolley.code}-L{NN}`, e.g. `GT-001-L01`) — never accepted as free text from the Farm Setup request — so the code cannot drift from the Trolley's real identity.

Either the whole structure is created or none of it is. One audit event is recorded per command, not per shelf or slot (Farm Setup bundles Trolley + Level creation into its own single `farm_setup.greenhouse_created` event, never a separate one per Trolley).

**Compatibility tripwire (PILOT-UX-001B).** `occupancy_compatibility_rules.target_position_kind` carries no AssetType scoping of its own — a rule matching `position_kind = 'shelf'` matches every `shelf`-kind `AssetPosition` regardless of which Asset owns it (neither `movement_service._check_compatibility` nor the `enforce_occupancy_insert_integrity` trigger join back to `assets`/`asset_types` when resolving compatibility). The `carrier:seed_tray -> position:shelf` row this ticket adds is safe ONLY because `germination_trolley` is currently the sole AssetType with `supports_positions = TRUE` (set once by the original asset/carrier registry migration, never changed since) — so no `shelf`-kind AssetPosition can exist under any other Asset today. **If a future ticket ever gives a second AssetType `supports_positions = TRUE`, this compatibility rule's target-side model (AssetType scoping) MUST be revisited before that ticket ships** — do not assume this row stays safely scoped on its own.

**Generic movement bypass (PILOT-UX-001B).** A Seed Tray Carrier may only be placed onto a Germination Trolley AssetPosition (Level or legacy Slot) through the Germination domain operation (`germination_service.place_tray`) — never through the generic `POST /farms/{farm_id}/movements` endpoint, which has no Germination-specific validation (sown-state, Trolley-currently-in-Chamber). This is enforced at the generic endpoint's own HTTP boundary only (`germination_service.reject_generic_bypass_for_seed_tray_placement`, called from `api/movements.py`) — `movement_service.execute_movement` itself stays fully generic, with no Germination-specific knowledge baked in, and `place_tray` continues to call it directly, unaffected.

**Audit.** `asset.registered`, `carrier.registered` per record; `carrier.bulk_registered`, `asset.positions_generated` once per command. A failed command leaves no partial records and no audit event.

**Deletion protection.** Assets, carriers, and asset positions are immutable history: a `BEFORE DELETE` trigger rejects direct SQL deletion, and no application service exposes a delete operation.

**Deferred:** occupancy, movement, farm-location assignment, crop batches/contents/quantities, transformations, QR/scan identity, label printing, maintenance work orders, and inventory valuation.

**Latest-assignment pointer (SEEDLING-DISPOSITION-LIFECYCLE-001).** `carriers.latest_batch_carrier_assignment_id` is derived infrastructure, never operator-editable: a forward-only pointer to the most recently created `BatchCarrierAssignment` for that physical Carrier, maintained by exactly one DB trigger on insert, untouched by release. It exists to answer one question the registry itself has no other way to answer — whether a given historical `BatchCarrierAssignment` is still this Carrier's latest-ever physical use — for the Seedling biological correction lifecycle documented in `TRANSPLANTATION_MODEL.md`. It carries no lifecycle-status meaning of its own and is unrelated to the `active`/`inactive`/`damaged`/`retired` registry status above.
