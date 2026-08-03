# Crop Catalog and Workflow Model

Full detail: `CMP_MASTER_SPEC.md` §8; `CLAUDE.md` rules 1 and 9. This document summarizes the approved model as implemented in CMP-007; it does not restate the spec.

## Distinct concepts

- **Crop** — tenant-owned catalog entry (`code`, `common_name`, optional `scientific_name`, `crop_category` — `leafy_green` | `vine` | `herb` | `other`). Crop names never appear in code paths (`CLAUDE.md` rule 1); category is a controlled classification, not agronomic policy.
- **Variety** — belongs to exactly one crop and tenant (e.g. Iceberg Lettuce → Mamutik RZ). Code is unique case-insensitively within its crop, not globally.
- **Production system** — tenant-owned description of how a crop is physically produced (e.g. `nursery_seed_tray`, `leafy_cultivation_plate`). Carries no carrier/location-type link — those restrictions belong to individual workflow stages, where they have operational meaning; duplicating the occupancy-compatibility engine (`OCCUPANCY_MOVEMENT_MODEL.md`) at this level was rejected.
- **Workflow** — a named production process for one crop (and optional variety) and production system. Identity fields (`tenant_id`, `crop_id`, `variety_id`, `production_system_id`) become immutable once any version has been published.
- **Workflow version** — the unit of change control. States: `draft` → `published` → `retired`, one-way only. Version numbers are server-generated and sequential per workflow; the API never accepts a client-supplied version number. At most one version per workflow may be `published` at a time (partial unique index).
- **Workflow stage / transition** — belong to one workflow version. A stage carries `stage_category` (`seeding`, `germination`, `nursery`, `intermediate`, `production`, `harvest_ready`, `completed`, `rejected` — operational categories, not crop names), `is_start`/`is_terminal` flags, and optional `permitted_location_type`/`required_carrier_type` references. A transition connects two stages of the same version; self-transitions are rejected.

## Tenant integrity

Every tenant-owned table carries `tenant_id`, and every parent-child relationship between tenant-owned tables is enforced by a **composite foreign key** — `(tenant_id, parent_id) → parent(tenant_id, id)` — not application checks alone (`CLAUDE.md` rule 2). This is why `varieties`, `workflows`, `workflow_versions`, `workflow_stages`, and `workflow_transitions` each carry a denormalized `tenant_id` even though it is reachable through a parent. A workflow's variety is additionally constrained to belong to the workflow's own crop via a three-column composite key: `workflows (tenant_id, crop_id, variety_id) → varieties (tenant_id, crop_id, id)`. Transition endpoints are constrained the same way against `workflow_stages (tenant_id, workflow_version_id, id)`, so a direct SQL `UPDATE` — not just `INSERT` — can never turn a transition into a cross-tenant or cross-version reference.

## Draft and publication lifecycle

Stages and transitions may only be created, changed, or removed while their workflow version is `draft` — enforced by a database trigger, not the application alone. There is no update or delete API for stages, transitions, or workflows in CMP-007: a mistake in a draft is fixed by editing that draft (still `draft`, so still mutable at the DB level) or by creating a fresh draft version, never by editing published history.

Publishing is one atomic command (`POST .../publish`) that:

1. Loads and locks the workflow and the selected version (`SELECT ... FOR UPDATE`).
2. Validates the full stage/transition graph in Python (small graphs — a BFS reachability check and a DFS cycle check are clearer here than recursive SQL): exactly one start stage, at least one terminal stage, every non-terminal stage has an outgoing transition, terminal stages have none, every stage reachable from start, no cycles — plus that the referenced crop/variety/production system are `active`.
3. Retires the previously published version (if any) and publishes the selected one, in that order, within the same transaction — avoiding a transient two-published-versions state under the partial unique index.
4. Records one `workflow.published` audit event (workflow id, published version id, replaced version id, stage/transition counts, timestamp — never the full graph).

Any validation failure leaves the draft untouched, the previous published version untouched, and no audit event.

## Database protection

- `workflow_versions`: a trigger permits only `draft→published` and `published→retired`; `tenant_id`/`workflow_id`/`version_number`/`created_at` are immutable after insert. Published and retired versions cannot be hard-deleted.
- `workflow_stages` / `workflow_transitions`: a trigger rejects insert, update, and delete once the parent version is no longer `draft`.
- `workflows`: a trigger rejects changes to `tenant_id`/`crop_id`/`variety_id`/`production_system_id` once any version of that workflow has been published or retired.

## Deferred

Crop batches, sowing, seed lots/counts, germination observations, material consumption, transformations, harvest, packing, occupancy/movement, QR/scan identity, labels, frontend, RLS, role-specific authorization — plus (per spec §8 itself) harvest mode, observations/completion criteria, approvals/holds/split-merge, and quality/shelf-life fields, all left for later tickets.
