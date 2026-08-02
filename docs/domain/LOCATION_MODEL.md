# Location Model

Full detail: `CMP_MASTER_SPEC.md` §3, `CLAUDE.md` "Farm Model". This document summarizes the approved semantics; it does not restate the template trees.

## Administrative vs operational

Administrative hierarchy is `Tenant → Country → City/Region → Farm`. Country and city exist for administration and reporting only — **operational occupancy starts at the farm or facility level**, never above it.

## Generic tree

Operational locations use a single UUID-based parent-child tree per farm. Code must never assume a fixed depth or repeat greenhouse/zone/span/table/gutter columns across operational tables (`CLAUDE.md` rule 3). Farms select controlled templates (nursery, leafy-green, vine, store, cold store — spec §3.1–3.4) and may omit optional levels (e.g. zone).

## Fixed vs mobile, and linked records

- A **location** is fixed and occupiable (e.g. chamber position, grow-bag position, store bin).
- A **grow-bag position is a fixed location**; the grow bag occupying it is a replaceable carrier (see `ASSET_CARRIER_MODEL.md`) — the position and the carrier are distinct records.
- **Grow tables and grow gutters have linked asset and operational-location records**: one record represents the physical/maintainable object (asset), another represents the occupiable positions it provides (location). The two are related but not the same entity.

## Derived location

Some entities have no direct location of their own and must have their effective location derived through their containment chain — e.g. a seed tray's location is derived as `tray → trolley slot → trolley → chamber position` (spec §3.1). This derivation is required behavior, not an implementation detail to be reinvented per feature.

## Location engine (implemented, CMP-004)

**Location types.** Global, system-defined, seeded by migration — not tenant-configurable. The 18 codes: `greenhouse`, `area`, `zone`, `span`, `seeding_station`, `germination_chamber`, `chamber_position`, `grow_table`, `table_position`, `grow_gutter`, `gutter_side`, `grow_bag_position`, `store`, `store_bin`, `packing_hall`, `cold_store`, `cold_store_position`, `dispatch_area`.

**Hierarchy rules.** A `location_type_hierarchy_rules` table is the source of truth for which child type may nest under which parent type — 25 approved pairs total, enforced at creation, not a fixed schema shape. Two kinds of rule:
- **Farm-root rules** (`parent_type_id IS NULL`): `greenhouse`, `store`, `packing_hall`, `cold_store`, `dispatch_area` may all be created directly under a farm.
- **Parent-location rules**: e.g. `greenhouse → area/zone/span`, `area → seeding_station/germination_chamber/grow_table/zone/span`, `zone → span/grow_table/grow_gutter`, `span → grow_table/grow_gutter`, `germination_chamber → chamber_position`, `grow_table → table_position`, `grow_gutter → gutter_side/grow_bag_position`, `gutter_side → grow_bag_position`, `store → store_bin`, `cold_store → cold_store_position`. **Zone and gutter side are optional at every level that offers them** — e.g. `area → span` and `grow_gutter → grow_bag_position` are both directly permitted, skipping zone or gutter side respectively.

Uniqueness of rules is enforced by two partial indexes (`(parent_type_id, child_type_id)` where parent is not null; `child_type_id` alone where parent is null), since a normal nullable composite unique constraint would allow unlimited duplicate root rules.

**Codes.** Trimmed and uppercased on input; never used as a primary key. Case-insensitive unique among siblings sharing a parent, and among a farm's root locations — the same code is freely reusable under a different parent, in a different farm, or in a different tenant.

**Greenhouse classification.** One of `nursery`, `leafy_greens`, `vines`, `mixed`, `other`. Required when `location_type = greenhouse`, forbidden otherwise — enforced twice: in the request schema/service (fast rejection) and by a PostgreSQL `BEFORE INSERT OR UPDATE` trigger on `locations` (authoritative backstop, since a plain `CHECK` constraint cannot join to `location_types` to know a row's type).

**Farm tree and path.** The complete tree for a farm is loaded with a single tenant-and-farm-scoped query and assembled into a nested structure in application code — no per-node queries. A single location's path is produced by a recursive (`WITH RECURSIVE`) query at read time; **no materialized path is stored**, consistent with ADR-004.

**Bulk generation.** Numbered children (e.g. `P01`–`P20`) are generated atomically: codes are always server-generated from a prefix/range/padding — never client-supplied — capped at 500 per command, and either all children are created or none are. One audit event is recorded per bulk command, not one per generated child.

**Deferred:** updates, reparenting/move, and deletion of locations; assets, carriers, occupancy, and movement all remain out of scope until later tickets.
