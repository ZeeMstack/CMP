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

**Bulk generation.** Numbered children (e.g. `P01`–`P20`) are generated atomically: codes are always server-generated from a prefix/range/padding — never client-supplied — capped at 500 per command, and either all children are created or none are. One audit event is recorded per bulk command, not one per generated child. `capacity` (see below), when supplied, is applied identically to every generated row — never a guessed per-type default.

**Capacity (DOMAIN-FARM-002).** Both `create_location` and `bulk_generate_children` accept an optional `capacity` (positive integer, `NULL` when omitted). `NULL`/`1` means the pre-existing exclusive behavior (at most one active occupant); `>1` permits that many simultaneous identified occupants, enforced at the DB layer — see `OCCUPANCY_MOVEMENT_MODEL.md`. `capacity` is orthogonal to `occupiable`: a non-occupiable location with `capacity > 1` configured is still never a valid movement target. `grow_table.default_occupiable` was **not** changed by this ticket — Farm Setup creates the actual table instances with their real `occupiable`/`capacity` values; CMP never invents a plate/tray/hole count.

**Deferred:** updates, reparenting/move, and deletion of locations; Grow Cube individual-plant identity; Carrier-as-occupancy-target (`target_carrier_id`); carriers/occupancy/movement changes beyond what already exists.

## Farm Setup (implemented, FARM-SETUP-001, extended FARM-SETUP-001.1)

The first usable physical-configuration experience, built entirely on the primitives above — no new Location/capacity semantics, no crop-agnostic-rule exceptions. Purpose: let an authorized user answer "what physical farm do I have?" and configure it truthfully, without manual SQL, fabricated locations, or invented Imperial-specific data in domain logic.

**Scope: create + read only.** A Farm Setup command creates a Greenhouse plus its classification-specific structure. There is no structural editing, reparenting, or deletion in this ticket, and no crop operations of any kind (no Crop Batch, Seed Lot, Sowing, Germination Check, Transplant, harvest, packing, dispatch) — Farm Setup configures the empty physical shell only.

**Orchestration and atomicity.** `app.services.farm_setup_service.create_greenhouse_setup` creates the Greenhouse and its entire requested structure (locations, and for Nursery optionally Germination Trolley/Seeding Machine assets) in **one database transaction, one commit**. This required extracting `_create_location_core`/`_bulk_generate_children_core`/`_register_asset_core`/`_generate_positions_core` — validate+insert+flush only, no per-call commit/audit — from the existing `location_service`/`asset_service` public functions (which still behave identically; the commit/audit responsibility moved to the thin public wrappers). Any failure at any depth (an invalid structure, a duplicate code) rolls back the entire command: no Greenhouse, no partial Zones/Spans/Tables/Gutters/Bag Positions/assets ever survive a failed setup command.

**Idempotency.** Reuses the existing `audit_events` table — no new schema. The command's own audit event (`farm_setup.greenhouse_created`) carries the caller's `client_command_id`, a request fingerprint, `farm_id`, and an `includes_assets` flag in `event_data`; an exact replay (same id, same content) returns the original result instead of creating a second Greenhouse, and a same-id-different-payload retry is rejected, mirroring `movement_service`'s established `client_command_id` convention.

**Idempotency concurrency (FARM-SETUP-001.1).** Sequential replay alone cannot prove correctness against two callers racing to submit the *same* `client_command_id` at the same time — both could observe "no prior audit event" before either commits. `create_greenhouse_setup` acquires a transaction-scoped Postgres advisory lock (`pg_advisory_xact_lock(hashtextextended(tenant_id || ':' || client_command_id, 0))`) as its very first action, before the idempotency check. This serializes every concurrent attempt sharing the same tenant+command id — the loser blocks until the winner's transaction commits or rolls back, then re-runs the idempotency check and either returns the same replayed result (identical payload) or raises the existing same-id-different-payload conflict (different payload) — never a second physical Greenhouse. No new table; reuses a native Postgres primitive, auto-released at commit/rollback. See `test_farm_setup_idempotency_concurrency.py` for the deterministic two-connection proofs (`threading.Barrier`, no sleeps).

**Per-classification structure support:**
- **Leafy Greens** — `Greenhouse → Zone → Span → Table` (stops at the table; no Table Position generated). Table `occupiable=True` is set explicitly per created row (`grow_table.default_occupiable` stays `False`).
- **Vines** — `Greenhouse → Zone → Span → Grow Gutter → Grow Bag Position` (no Gutter Side node). Grow Bag Position `capacity` is never accepted from the setup request — always the domain default (effective 1).
- **Nursery** — the complete Nursery topology is configurable in one command: optional Seeding Station and optional Germination Chamber (each a single, user-coded section directly under the Greenhouse — never a generated group, unlike the table generators), plus the Seedling/InterSalads/InterVines tables directly under their respective area node (no Zone/Span anywhere in a Nursery greenhouse). Each of the five sections is independently optional — at least one of the five (or a Trolley/Seeding Machine, see below) must be configured. No `chamber_position` generation is performed under the Germination Chamber — Farm Setup creates the Chamber itself only, never fabricated positions inside it.

**Trolley/Seeding Machine are farm-level equipment, not Nursery structure (FARM-SETUP-001.1).** `Asset` has no `location_id`/`greenhouse_id` column, and Farm Setup never creates an `Occupancy` for a registered Trolley/Seeding Machine (no placement, no movement) — so nothing durably ties either Asset to the specific Nursery Greenhouse the setup command happened to also create. Registering them stays bundled into the same Farm Setup command (removing a working, tested capability was judged unnecessary), but both the API authorization and the UI copy present them honestly as farm-level equipment registered *alongside* this command, not *owned by* this Nursery. A Trolley/Seeding Machine alone (no Seeding Station/Germination Chamber/tables) leaves the Nursery's own structural status at `partial`, never `configured`.

**Capacity meaning.** Every capacity value configured through Farm Setup counts *identified physical occupant objects* (trays, plates, gutters' bag positions fixed at 1, Grow Cubes), matching DOMAIN-FARM-002 exactly — never a biological quantity (seeds, kg, holes, heads). A Grow Cube itself is defined elsewhere as one physical carrier carrying exactly one plant, so "capacity = N Grow Cubes" is a count of identified carriers, not a direct plant-count field.

**Status derivation.** `empty` / `partial` / `configured` — never a persisted boolean, always derived from the current structural counts. Leafy is `configured` once `tables > 0`; Vines once `bag_positions > 0` (each has one mandatory leaf type). Nursery has no single mandatory leaf — it is `configured` if **any** of its five sections (Seeding Station, Germination Chamber, Seedling tables, InterSalads tables, InterVines tables) is present, `partial` if some other descendant (including a Trolley/Seeding Machine) exists but none of the five sections do, else `empty`.

**Read endpoints.** `GET /farms/{farm_id}/farm-setup/greenhouses` (overview, derived counts + status) and `GET /farms/{farm_id}/farm-setup/greenhouses/{id}` (one greenhouse's structure, classification-shaped, bounded to that greenhouse's own subtree — never farm-wide; for Nursery includes `nursery_seeding_station`/`nursery_germination_chamber` alongside the three table groups). Both authorized on `location.read`; the create command requires **both** `location.manage` and `asset.manage` (FARM-SETUP-001.1) — stacked as two separate FastAPI dependencies, since this command can register Assets and must not rely on the incidental fact that every role currently holding `location.manage` also holds `asset.manage`.

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
