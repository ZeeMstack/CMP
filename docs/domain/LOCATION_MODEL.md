# Location Model

Full detail: `CMP_MASTER_SPEC.md` §3, `CLAUDE.md` "Farm Model". This document summarizes the approved semantics; it does not restate the template trees.

## Administrative vs operational

Administrative hierarchy is `Tenant → Country → City/Region → Farm`. Country and city exist for administration and reporting only — **operational occupancy starts at the farm or facility level**, never above it.

## Generic tree

Operational locations use a single UUID-based parent-child tree per farm. Code must never assume a fixed depth or repeat greenhouse/zone/span/table/gutter columns across operational tables (`CLAUDE.md` rule 3). The tree engine itself remains fully generic — see "Classification-aware topology (DOMAIN-FARM-001)" below for how each greenhouse's own template is now enforced *within* that generic tree, not by a separate, hardcoded mechanism.

## Fixed vs mobile, and linked records

- A **location** is fixed and occupiable (e.g. chamber position, grow-bag position, store bin).
- A **grow-bag position is a fixed location**; the grow bag occupying it is a replaceable carrier (see `ASSET_CARRIER_MODEL.md`) — the position and the carrier are distinct records.
- **Grow tables and grow gutters have linked asset and operational-location records**: one record represents the physical/maintainable object (asset), another represents the occupiable positions it provides (location). The two are related but not the same entity.

## Derived location

Some entities have no direct location of their own and must have their effective location derived through their containment chain — e.g. a seed tray's location is derived as `tray → trolley slot → trolley → chamber position` (spec §3.1). This derivation is required behavior, not an implementation detail to be reinvented per feature.

## Location engine (implemented, CMP-004)

**Location types.** Global, system-defined, seeded by migration — not tenant-configurable. 24 codes: the original 18 (`greenhouse`, `area`, `zone`, `span`, `seeding_station`, `germination_chamber`, `chamber_position`, `grow_table`, `table_position`, `grow_gutter`, `gutter_side`, `grow_bag_position`, `store`, `store_bin`, `packing_hall`, `cold_store`, `cold_store_position`, `dispatch_area`) plus six Nursery-specific types added by DOMAIN-FARM-001: `seedling_area`, `seedling_table`, `intersalads`, `intersalads_table`, `intervines`, `intervines_table`.

**Hierarchy rules — two independent rule sets, never mixed.** A `location_type_hierarchy_rules` table is the source of truth for which child type may nest under which parent type, now scoped by an optional `greenhouse_classification` column (DOMAIN-FARM-001):
- **Generic rules** (`greenhouse_classification IS NULL`) — the original 25 pairs, byte-for-byte unchanged since CMP-004. Farm-root rules (`parent_type_id IS NULL`: `greenhouse`, `store`, `packing_hall`, `cold_store`, `dispatch_area`) plus parent-location rules for everything else. These govern location creation **outside any greenhouse tree** — `store`/`cold_store`/`packing_hall`/`dispatch_area` trees, and the one edge that creates a greenhouse itself.
- **Classification-scoped rules** (`greenhouse_classification` = one of `nursery`/`leafy_greens`/`vines`) — added by DOMAIN-FARM-001, see "Classification-aware topology" below. These govern location creation **inside** a classified greenhouse tree, exclusively — there is no fallback to the generic set.

Uniqueness is enforced by three partial indexes: two for the generic set (mirroring the original two, now additionally scoped to `greenhouse_classification IS NULL`) and one covering `(greenhouse_classification, parent_type_id, child_type_id)` for scoped rows.

**Codes.** Trimmed and uppercased on input; never used as a primary key. Case-insensitive unique among siblings sharing a parent, and among a farm's root locations — the same code is freely reusable under a different parent, in a different farm, or in a different tenant.

**Greenhouse classification.** Exactly one of `nursery`, `leafy_greens`, `vines` (DOMAIN-FARM-001 removed `mixed` and `other` — no location row was ever observed using either, verified by the migration's own pre-narrowing guard). Required when `location_type = greenhouse`, forbidden otherwise, and **immutable once set** — all three rules enforced by one PostgreSQL `BEFORE INSERT OR UPDATE` trigger on `locations` (a plain `CHECK` constraint can't join to `location_types` to know a row's type, or compare `NEW` to `OLD`). No update API exists for it at any layer — the immutability guarantee is currently proven only at the DB layer, deliberately, since there is no application code path that could otherwise attempt a change.

**Farm tree and path.** The complete tree for a farm is loaded with a single tenant-and-farm-scoped query and assembled into a nested structure in application code — no per-node queries. A single location's path is produced by a recursive (`WITH RECURSIVE`) query at read time; **no materialized path is stored**, consistent with ADR-004.

**Bulk generation.** Numbered children (e.g. `P01`–`P20`) are generated atomically: codes are always server-generated from a prefix/range/padding — never client-supplied — capped at 500 per command, and either all children are created or none are. One audit event is recorded per bulk command, not one per generated child.

**Deferred:** updates, reparenting/move, and deletion of locations; capacity-aware occupancy (DOMAIN-FARM-002 — a location/asset-position may hold more than one active occupant, up to a configured capacity); Grow Cube individual-plant identity; carriers/occupancy/movement changes beyond what already exists.

## Classification-aware topology (implemented, DOMAIN-FARM-001)

Before this ticket, hierarchy validation was purely generic: any parent/child type pair permitted anywhere in the (single, global) rule table was legal everywhere, regardless of which greenhouse it sat inside. This let a Vines-classified greenhouse accept Nursery structure, or vice versa, with no objection — a real gap between the physical farm model and what the schema actually enforced.

**Resolution algorithm** (`location_service._resolve_governing_greenhouse_classification` + `_validate_hierarchy`), run on every `create_location`/`bulk_generate_children` call:
1. Walk the candidate's parent chain upward (inclusive of the parent itself) for the nearest `greenhouse`-typed ancestor, via one `WITH RECURSIVE` query.
2. If found, its `greenhouse_classification` **exclusively** governs — only rows in `location_type_hierarchy_rules` with a matching `greenhouse_classification` are consulted. The generic (`NULL`-classification) rule set is never consulted as a fallback, even if it happens to contain a matching parent/child pair — this is the specific guarantee that prevents a classification-specific restriction from being silently bypassed.
3. If not found (no parent at all — a farm-root creation — or the parent chain never reaches a greenhouse, e.g. a `store`/`cold_store`/`packing_hall`/`dispatch_area` tree), the generic rule set governs, exactly as before this ticket.

A greenhouse can never itself have a greenhouse ancestor (no rule, generic or scoped, permits nesting one), so "nearest" is unambiguous, and creating the greenhouse root itself is always governed by the generic rule set (there is nothing to resolve yet).

**Authoritative per-classification topology** (exact chains — every level shown is mandatory, no shortcuts, no skipping):

- **`nursery`** — flat, does not use zone/span: `greenhouse` → `seeding_station` | `germination_chamber` | `seedling_area` | `intersalads` | `intervines` (all direct children); `germination_chamber` → `chamber_position`; `seedling_area` → `seedling_table`; `intersalads` → `intersalads_table`; `intervines` → `intervines_table`.
- **`leafy_greens`** — `greenhouse` → `zone` → `span` → `grow_table`. Stops at the table: the Production Cultivation Plate is a **carrier**, not a location, so `table_position` is never a legal continuation here (it remains a legal generic type elsewhere, just not reachable inside a leafy-classified tree).
- **`vines`** — `greenhouse` → `zone` → `span` → `grow_gutter` → `grow_bag_position`. `gutter_side` is deliberately **absent** from this rule set — Grow Gutter Side (LEFT/RIGHT) describes plant canopy/branch training only, never a crop-placement location. The generic `grow_gutter → gutter_side → grow_bag_position` edges still exist in the DB (nothing was deleted, per migration-safety practice), but are unreachable from inside any classified greenhouse, which is the only place a `grow_gutter` is ever created.

**Occupancy compatibility.** One `occupancy_compatibility_rules` row was added alongside the topology correction: `cultivation_plate` (carrier) → `grow_table` (location) — a direct, necessary consequence of the Table now being the occupiable leaf in the Leafy topology (previously only `cultivation_plate → table_position` existed). This is data-only; no capacity/movement logic changed (that remains DOMAIN-FARM-002's scope).

**Finished-goods physical placement (CMP-018).** `cold_store_position` also serves as the sole storage-eligible location type for finished-goods physical occupancy — a separate concern from the location engine itself, with its own table (`finished_goods_storage_movements`). No location *type* or *hierarchy* change (`location_types`/`location_type_hierarchy_rules` are both untouched), but CMP-018 does add one narrow composite `UNIQUE(tenant_id, farm_id, id)` constraint (`uq_locations_tenant_farm_id`) to `locations` itself, backing real composite foreign keys from the new table — a genuine schema addition to `locations`, not "zero schema change". No column changes and no location row is touched. See `FINISHED_GOODS_STORAGE_MODEL.md`.
