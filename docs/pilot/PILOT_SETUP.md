# Pilot Setup — Master-Data Bootstrap

Read this only for pilot bootstrap work. Permanent coding rules are in the root `CLAUDE.md`; product/domain rules are in `docs/CMP_MASTER_SPEC.md`. This document explains **PILOT-SETUP-001A**, the config-driven bootstrap framework. It does not itself populate a real farm — that is **PILOT-SETUP-001B**, tracked separately.

## 1. Purpose

Before a real Iceberg-lettuce pilot batch can run through CMP (Seed Lot → Sowing → Germination → Seedling → Inter Leafy Greens → Production Transfer → Leafy Production → Harvest → Grading → Packing → Finished Goods → Cold Storage → Dispatch), a specific set of master/configuration data must already exist: a Farm, its Greenhouses and location hierarchy, Carrier Specifications and physical Carriers, the real Crop/Variety/Workflow, Grade and Pack specifications, and Cold Storage/Packing Hall locations.

This bootstrap gives that setup step a **repeatable, idempotent, config-driven mechanism** instead of ad-hoc manual API calls — safe to rerun, safe against partial failure, and explicit about exactly which real-world values it still needs from the farm.

## 2. What the bootstrap creates

Only master/configuration data, and only what the real Iceberg chain needs:

- Greenhouse and location structure (Nursery, Leafy Greens production greenhouses, Cold Store, Packing Hall)
- Carrier Specifications for Seed Tray, Nursery Cultivation Plate, Production Cultivation Plate
- Physical Carrier registration (Seed Trays, Nursery Cultivation Plates, Production Cultivation Plates) — registration only, never occupancy
- Crop, Variety, Production System
- Workflow, Workflow Stages, Workflow Transitions, published as one Workflow Version
- Grade Definitions and Grade Definition Versions
- Packaging Units, Pack Specifications and Pack Specification Versions
- Optionally, one real starting Seed Lot (see §12)

It resolves — but never creates — the Farm's owning Tenant and the administrative User/Membership it runs as (see §4).

## 3. What it deliberately does NOT create

No operational lifecycle transaction, ever. The config schema (`app.services.pilot_bootstrap_service.PilotConfig`) has **no field capable of expressing** any of the following — this is enforced by the schema's shape, not by a runtime check that could be bypassed:

- Sowing, Germination Outcome, Seedling Entry
- InterSalads (Inter Leafy Greens) Transplant, Production Transfer
- Biological/plant-loss disposition
- Harvest, Grading, Packing
- Finished-Goods storage movement, Dispatch
- Recall

It also never creates a Tenant, User, or Membership (§4), never adds a new HTTP endpoint, never touches Alembic, and never grants a permission or bypasses authorization — every write goes through the same permission-checked application service layer a real API request would use, called in-process.

Two invariants worth repeating, because they are easy to blur in casual conversation about "setup":

- **Carrier capacity is never living population.** A CarrierSpecification's `biological_position_count` is a physical/theoretical capacity fact (cells, holes). This bootstrap never derives or seeds a plant count, a biological occupancy row, or any "current population" from it.
- **Physical Carrier registration is never occupancy.** Registering a Carrier (a Seed Tray, a Cultivation Plate) creates a traceable physical asset row. It does not place that Carrier anywhere, and it does not imply anything is growing in it.

## 4. Tenant/User prerequisite — product-owned, not this bootstrap's

Production-safe Tenant/User/Membership provisioning is a **CMP product** concern (PILOT-SETUP-001B: controlled platform-admin-gated tenant onboarding — the platform-admin authority primitive (PILOT-SETUP-001B1) and `POST /platform/tenants` onboarding itself (PILOT-SETUP-001B2) are both built; see `docs/domain/AUTHORIZATION_MODEL.md`'s "Platform-level authority" and "Platform Tenant onboarding" sections), not this bootstrap's, and not exclusively DEPLOY-001's as earlier assumed (DEPLOY-001 remains responsible for infrastructure/auth-provider deployment). This module:

- never weakens the development-only `dev_bootstrap` guard,
- never enables dev bootstrap outside a development environment,
- never adds a production bootstrap HTTP route,
- never touches OIDC/auth behavior or the permission model.

Instead, `target.tenant_code` and `target.actor.{oidc_issuer,oidc_subject}` in the config file name an **already-provisioned** Tenant and an **already-provisioned** administrative User with an active Membership on that Tenant. `resolve_target()` looks both up and **fails loudly** — `PilotTargetNotResolvedError`, before any write is attempted — if either is missing, inactive, or unlinked. The error message says exactly this: provision the Tenant/User/Membership first (DEPLOY-001), then rerun.

## 5. Configuration file structure

One YAML file, validated by `app.services.pilot_bootstrap_service.PilotConfig` (Pydantic, `extra="forbid"` throughout — an unrecognized key is a hard error, not a silent no-op). Top-level sections: `target`, `farm`, `greenhouses`, `locations`, `carrier_specifications`, `carriers`, `crop`, `variety`, `production_system`, `workflow`, `grade_definitions`, `packaging_units`, `pack_specifications`, `seed_lot` (optional).

The `greenhouses[].nursery` / `greenhouses[].leafy` shapes are not a parallel invention — they reuse `app.schemas.farm_setup.NurserySetupConfig` / `LeafySetupConfig` directly, the exact Pydantic models `POST /farms/{farm_id}/farm-setup/greenhouses` itself validates against. There is no `vines` field anywhere in this schema; Vines is out of scope for this pilot and the schema excludes it rather than merely declining to populate it.

See `config/pilot/iceberg-pilot.example.yaml` for the full annotated template.

### Two placeholder mechanisms, on purpose

- **String identity fields** (codes, names, OIDC identifiers) use an obvious `REQUIRED_...` placeholder or `UNKNOWN`. These parse successfully — a file full of `REQUIRED_*` strings is syntactically valid — and are caught later by `find_placeholders()`, which walks the parsed config and returns every dotted path still holding one. This drives dry-run's "missing required configuration" report and blocks `--apply` outright.
- **Numeric/count fields the farm must supply** (table counts, carrier quantities, dimensions, capacities) are left at an invalid sentinel (`0`, which fails every such field's own positivity constraint) or omitted where optional. These fail at **schema/syntax validation** — the very first thing `--dry-run`/`--apply`/`--readiness` do — with Pydantic's own precise per-field message (e.g. `greenhouses.0.nursery.germination_chamber.trolley_capacity: Input should be greater than 0`). This is deliberate, not a limitation: several of these fields reuse real system schemas (`TableGeneratorConfig`, `GerminationChamberSetupConfig`, …) whose own required-int shape this bootstrap must not weaken just to make an unfinished template "run further."

In short: a config file can be schema-valid while still full of `REQUIRED_*` strings (dry-run reports these as missing), but it cannot be schema-valid while a required count/dimension is still a bare `0` — that fails immediately, by design.

## 6. Real values that must be supplied

Every `REQUIRED_*`/sentinel field in `config/pilot/iceberg-pilot.example.yaml`, grouped by who confirms it — this mirrors the real-data input matrix in the PILOT-SETUP-001 discovery audit:

| Who | What |
|---|---|
| **Farm/CTO** | Tenant code, actor OIDC identity, farm code/name/country/timezone, greenhouse codes, Nursery structure counts (seeding station, germination chamber + trolley capacity, trolley shelf/slot layout, seedling/InterSalads table counts), Leafy structure counts (zone/span/table codes and counts per greenhouse), Cold Store/Packing Hall codes and cold-store position counts, carrier specification dimensions and physical position counts, carrier quantities and code prefixes |
| **Head Grower** | The real Iceberg variety and its code, production system, the workflow's real stage list/order/durations/transitions (the template's stage list is illustrative only) |
| **QA/Commercial** | Grade Definition(s) and their real thresholds, Packaging Unit(s), Pack Specification(s) and their nominal weight/count, and the effective dates for whichever of those are activated |
| **System** | Every UUID, every `client_command_id`, every audit event — never hand-entered anywhere in the config |

## 7. Dry-run procedure

```
python scripts/bootstrap_pilot_master_data.py --config <path> --dry-run
```

Runs the identical step sequence `--apply` would run — including calling the real domain services — inside an outer database transaction that is **always rolled back**, regardless of outcome. This is deliberate: a dry run genuinely exercises real service-layer validation (hierarchy rules, capacity checks, workflow publish-graph validation, effective-date rules), not an approximation of it, while writing nothing. Every step is attempted and reported even if an earlier step failed, so one dry run surfaces the full picture rather than one error at a time.

Reports, per step: `CREATED` (would be created), `EXISTING` (already present and matching), `CONFLICT` (present but different — would block `--apply`), or `BLOCKED` (a prerequisite step did not resolve). Also reports any remaining template placeholders and the operational-table integrity check (§13).

## 8. Apply procedure

```
python scripts/bootstrap_pilot_master_data.py --config <path> --apply
```

Refuses to start at all if any `REQUIRED_*`/`UNKNOWN` placeholder remains. Otherwise runs the same step sequence as dry-run, inside one outer transaction, and **stops on the first `CONFLICT`/`BLOCKED` step** — the whole transaction is rolled back, so an aborted apply leaves the database exactly as it found it; nothing partial is ever committed. On success, commits once, at the very end, after re-confirming the operational-table integrity check (§13) passed.

## 9. Rerun / idempotency behavior

Safe to rerun at any time, including after a partial or fully successful prior run. Every entity is looked up by its human code (never assumed by UUID) before any create is attempted:

- Farm, Crop, Variety, Production System, Carrier Specification, generic Location (Cold Store/Packing Hall/positions), physical Carrier batches, Seed Lot: looked up by `(tenant, code)` (or the appropriate scoping key); if found, its identity-defining fields are compared against the config — an exact match is `EXISTING` (no-op), any difference is `CONFLICT`.
- Greenhouse structure, Grade Definition/Version, Packaging Unit, Pack Specification/Version: these services already implement `client_command_id` + fingerprint replay natively. This bootstrap derives a deterministic `client_command_id` from `(tenant, entity kind, code)`, so a byte-identical rerun replays for free through the service's own mechanism.
- Workflow: if a Workflow with the configured code already has a **published** version, its stage/transition shape is compared against the config; a match is `EXISTING`, a mismatch is `CONFLICT` (a published version is a historical fact and is never republished over). If no published version exists yet, a new draft version is created, staged, and published — never touching any existing version.

## 10. Conflict behavior

"Conflict" always means: something matching this code already exists, and it does not match what the config asked for. The bootstrap **never** silently renames a record, overwrites a capacity, changes a hierarchy, deactivates/reactivates a record, changes which version is active, or rewrites existing master history to make a conflict "go away." It reports the exact mismatched fields and stops (`--apply`) or continues past it to report everything else (`--dry-run`).

## 11. Bootstrap readiness verification (admin/CLI mechanism)

```
python scripts/bootstrap_pilot_master_data.py --config <path> --readiness
```

A separate, **read-only** check, safe to run at any time — including long after real UAT operations have created genuine operational history, which readiness deliberately does not look at. It answers one question: *does the environment **this config file** describes have everything the first real Sowing needs?* Every check is `PASS`, `MISSING`, or `CONFLICT`; the Seed Lot check is special-cased — if `seed_lot` was never configured, it reports `MISSING — BLOCKS FIRST SOWING` as an **informational** item that does not fail the overall readiness verdict on its own (every other item still must `PASS`), matching §12.

This is `pilot_bootstrap_service.run_readiness_check` — a config-aware admin/CLI mechanism, compared entity-by-entity against a hand-authored `PilotConfig` (`REQUIRED_*` placeholders included). It has no HTTP route, no UI, and is never the backend for the product Setup Checklist described next: a config file's contents are an intent to compare against, not the same question as "what has this Farm actually configured."

## 11a. Product Setup Readiness (persisted state, UI-facing)

**PILOT-SETUP-001B8** adds a second, entirely distinct readiness mechanism for real operators, not administrators:

```
GET /farms/{farm_id}/setup-readiness
```

exposed in the UI at `/farms/{farmId}/setup-readiness` (linked from Farm Setup). Implemented by `app.services.farm_setup_readiness_service.evaluate_farm_setup_readiness` — a read-only query over the **actual persisted Tenant/Farm state already in the database**. It takes no config file, no file path, no uploaded YAML, and never runs (or requires) the bootstrap CLI; it answers "what has this Farm actually configured" directly from Crop/Variety/Workflow/CarrierSpecification/Carrier/Location/SeedLot/GradeDefinition/PackagingUnit/PackSpecification rows.

Unlike §11's single pass/fail list, this view is staged into four milestones, because a Farm's operational milestones become ready at different times:

| Milestone | Question | Depends on |
|---|---|---|
| **Sowing** | Can this Farm start the first real Sowing? | Farm, Nursery structure, a coherent Crop/Variety/Production-System/published-Workflow chain, the Workflow's Sowing-stage carrier (Specification + physical Carriers), a real Seed Lot |
| **Production** | Can material move Nursery → Inter Leafy Greens → Leafy Production? | Nursery InterSalads structure, Nursery/Production Cultivation Plate Specifications + physical Carriers, Leafy Production Zone→Span→Grow-Table structure |
| **Post-Harvest** | Can harvested product be graded, packed, and structurally stored? | Packing Hall, Cold Store + position structure, an active Grade Definition version, an active Packaging Unit, an active Pack Specification version |
| **Full Pilot** | Is setup complete for the whole pilot through Dispatch/Traceability/Recall? | The union of the three milestones above — Dispatch/Traceability/Recall themselves add no extra master-data item because neither service has a structural master-data dependency the way Grading/Packing genuinely do |

**Sowing Readiness is deliberately unaffected by Grade/Pack/Cold Store configuration** — those items only ever appear under Post-Harvest/Full Pilot, never under Sowing or Production. An operator can be told "ready to sow" long before packing/commercial configuration exists.

Each item reports `pass` / `missing` / `warning` / `not_applicable`; each milestone reports `ready` (every item `pass`/`not_applicable`) or `incomplete`. There is no `CONFLICT`/`BLOCKED` state here — this is a V1 completeness view, not a validity/conflict engine. Because a tenant may configure multiple Crops/Workflows at once (CMP is crop-agnostic), the Sowing chain is found by walking every structurally coherent `Crop → Variety → Workflow(published) → Production System` link and reporting the most-complete one — never by assuming "any Crop plus any Workflow plus any Seed Lot existing somewhere" is sufficient. See the module docstring in `farm_setup_readiness_service.py` for the exact algorithm.

The endpoint enforces normal tenant isolation and the `farm.read` permission — no platform-admin authority is used or needed, and a cross-tenant Farm id returns a plain 404.

## 12. Seed Lot handling

Seed Lot is the one deliberate exception to "master data only." Per `docs/domain/SEED_SOWING_MODEL.md`, a `SeedLot` row carries no quantity-on-hand, cost, or biological data — it is an identity/catalog record (supplier, variety, code, dates), not a transaction. Registering the farm's real starting Seed Lot is therefore legitimate setup, not a simulated crop cycle.

But it is also the first real traceability link, so:

- The `seed_lot` config section is **entirely optional** — omit it and every other master-data step still applies/validates normally.
- The example template leaves it commented out, not filled with placeholder values, specifically so a config with a real seed lot not yet known cannot be mistaken for one that has been deliberately left blank by oversight.
- **Seed Lot required before first Sowing, but not necessarily before bootstrap framework validation.** `--dry-run` and `--apply` both succeed with no `seed_lot` configured; `--readiness` will correctly say the environment is not yet ready for a first Sowing, without that blocking any other readiness signal.

## 13. Master data vs. operational transactions

See §3 for what is excluded by construction. As a runtime self-check (not just a design claim), `--apply` captures row counts for every operational table (`crop_batches`, `sowing_events`, `germination_outcome_snapshots`, `seedling_entries`, `transplant_events`, `harvest_events`, `grading_events`, `packing_events`, `finished_goods_storage_movements`, `dispatch_events`, `recall_cases`), scoped to the resolved tenant, before and after the run, and refuses to commit if any of them changed. This should never trigger — the config schema has no path to any of these tables — but it is verified, not merely asserted.

## 14. From PILOT-SETUP to PILOT-UAT

Once `--readiness` reports every item `PASS` (or only the Seed Lot item outstanding, pending the real lot's arrival):

1. Register the real Seed Lot (`--apply` again with `seed_lot` filled in), or have the storekeeper do it live once the physical lot arrives.
2. Everything from that point — Sowing, Germination, Seedling, Inter Leafy Greens, Production Transfer, Leafy Production, Harvest, Grading, Packing, Cold Storage, Dispatch, Traceability/Recall — is real operator execution through the normal application UI/API, never this bootstrap. PILOT-SETUP-001A creates the stage; it never performs on it.
