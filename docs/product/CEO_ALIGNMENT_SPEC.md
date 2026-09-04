# CEO-ALIGN-001 — Product & UI Alignment Specification

Status: **Approved** (product-owner decisions final, 2026-08-28). This document is the
authoritative output of the CEO-ALIGN-001 discovery process and governs the scope of
**UI-OPT-001**. It supersedes the CEO HTML mockups' wording and structure wherever they
conflict with the decisions below; the mockups remain valid input for visual/IA design
only.

Full domain detail: `CMP_MASTER_SPEC.md` and `docs/domain/*`. This document does not
restate domain rules — it records product-owner decisions and the scope they authorize.

## Product name decision

**Superseded by PILOT-UX-001A (approved 2026-09-01).** The brand presentation below
(`ImperialFarms CMP`) conflated the SaaS product's own brand with the first production
Tenant's name and is no longer current. See "Product name decision (superseded
2026-09-01)" further down for the historical record, and the current decision
immediately below.

Official SaaS/product brand: **GrowCMP**. "Crop Management Platform" (internal/domain
acronym **CMP**) may be used only as a secondary descriptor/subtitle, never as the
primary product brand. GrowCMP is never replaced by a Tenant or Farm name; Tenant
(e.g. Imperial Limited) and Farm (e.g. Imperial Farms) names are separate, real,
data-derived identities shown alongside the GrowCMP brand where relevant -- never
hardcoded, and never presented as though they were the product's own name.

The CEO mockups' wording "Cultivation Management Platform" is not adopted. Where the
mockups' visual treatment of the brand block is reused, only the brand text/tagline
changes.

### Product name decision (superseded 2026-09-01)

Official product name: **Crop Management Platform**, acronym **CMP**.

Brand presentation: `ImperialFarms CMP` / `Crop Management Platform`.

This wording is retained here only as the historical record of the original
CEO-ALIGN-001 decision; it no longer governs the shipped brand (see above).

## CEO design principles (adopted)

The following are adopted from the three CEO mockups as the visual/IA foundation for
UI-OPT-001:

- Editorial visual identity: serif display headings, sage/soil/amber palette, soft
  rounded cards, pill-style tabs, chip-based multi-select with inline "+ Add New".
- Grouped, collapsible top-level navigation replacing the current flat sidebar list.
- **Qualification on chip-based "+ Add New":** chip-based selectors and inline
  "+ Add New" are allowed only where the target resource already has an approved
  create workflow. This design pattern does not authorize new master-data CRUD in
  UI-OPT-001 (see Deferred functionality).
- Capacity/quantity calculators surfaced to the operator before commit (e.g. trays
  needed, plates needed), as read-only advisory displays only.
- A round-up/round-down helper where an entered quantity doesn't divide evenly across
  a fixed carrier capacity.
- Master-data grouped conceptually under one "Farm Setup & Master Data" navigation
  umbrella, even though most of that master data is not built yet (see Deferred).

These are visual and interaction-pattern principles only. None of them authorize new
domain behavior; see Frozen domain protections.

## GrowCMP navigation & UX principle (frozen, UX-IA-001, approved 2026-09-04)

Extends beyond UI-OPT-001's own scope — this principle governs all future GrowCMP
navigation and screen design, not just the tree frozen below:

GrowCMP navigation and screens are organized around user jobs, workflows, decisions,
and next actions — not backend entities or database tables. A backend entity does not
automatically deserve its own navigation item. Setup experiences should guide
configuration and maintenance; operational experiences should represent the
operator's work, not expose the underlying command/entity structure.

Every configurable object must have a defined maintenance lifecycle. Creation-only
configuration is incomplete UX. See `docs/domain/LOCATION_MODEL.md`, "Location
maintenance lifecycle," for the first applied instance of this principle, and "Store &
Inventory Setup navigation" below for the first applied instance of the navigation
principle.

## Final navigation

Frozen for UI-OPT-001's own scope. This is the complete navigation tree UI-OPT-001
itself ships — nothing beyond it ships under UI-OPT-001, and no placeholder/disabled
entries are shown for modules that aren't functional yet (see Future modules must stay
hidden, below). A later, separately-approved product decision may still extend this
tree under its own scope — see "Approved later extension (STORE-INV-001A)" below.

```
Home

Nursery Operations
 - Seeding
 - Germination
 - Seedling
 - Transfer to Inter Leafy Greens

Production Operations
 - Leafy Production
 - Transfer to Production

Harvest & Post-Harvest
 - Harvest
 - Grading
 - Graded Produce
 - Packing
 - Finished Goods
 - Cold Storage

Dispatch & Traceability
 - Dispatch
 - Traceability
 - Recall Cases

Farm Setup & Master Data
 - Greenhouse & Locations
 - Carrier Specifications
```

Notes on mapping to existing routes:

- **Harvest** moves out of Production Operations and into Harvest & Post-Harvest.
  Production Operations retains only Leafy Production and Transfer to Production.
- **Traceability** remains a top-level operator navigation item. If no dedicated
  landing route currently exists, UI-OPT-001 may add a frontend-only read/search entry
  point built on existing traceability APIs/read models (per
  `docs/domain/TRACEABILITY_MODEL.md`, including the crop-batch detail view's Origin &
  Splits panel). It must not add new backend genealogy, traceability entities,
  mutation commands, or lineage semantics.
- **Farm Setup & Master Data** in this frozen tree contains only Greenhouse & Locations
  and Carrier Specifications. Crop & Variety Master, Cultivation Method Templates, and
  Input Master are not navigation entries in UI-OPT-001 (see Deferred functionality).
- **Carrier Specifications** (`apps/web/app/carrier-specifications/page.tsx`) gets a
  navigation entry for the first time — it currently exists but is unreachable except
  by direct URL.
- Every other route in the current app that isn't named above (e.g. any future/partial
  screen) either maps into one of the groups above or stays out of navigation entirely
  until its module is functional.

### Store & Inventory Setup navigation (supersedes STORE-INV-001A, UX-IA-001, 2026-09-04)

**Farm Setup & Master Data** gains exactly ONE entry for this domain: **Store &
Inventory Setup** — a single setup workspace (Overview / Storage / Inventory Catalog /
Settings views; these are workspace sections, not separate primary sidebar modules).
Full workspace structure, scope-communication wording, and Setup Summary UX are frozen
in `docs/domain/STORE_INVENTORY_MODEL.md` ("Store & Inventory Setup workspace UX").

The four routes named in the now-superseded extension below remain technically live
(deep-link/bookmark access only) but are no longer primary navigation destinations —
the same "removed from primary navigation, route stays live" precedent already used
elsewhere in this app (see `apps/web/components/AppShell.tsx`'s own module
documentation for the existing examples this now joins).

A new top-level **Store & Inventory** operational module is planned, but does not
appear until `STORE-INV-002` or later actually provides real stock/operational
inventory functionality — the same "no placeholder/disabled entries for modules that
aren't functional yet" rule this document already applies everywhere else governs this
module too; no placeholder or disabled entry ships before that. Full domain detail:
`docs/domain/STORE_INVENTORY_MODEL.md`.

#### Approved later extension (STORE-INV-001A) — superseded 2026-09-04

Retained only as the historical record of the original decision; it no longer governs
navigation (see above).

This is an approved later product extension, not an accidental UI-OPT-001 scope
expansion — the tree above stays exactly as frozen for UI-OPT-001 itself.

**Farm Setup & Master Data** gains four new entries once `STORE-INV-001` ships: `Stores
& Bins`, `Inventory Categories`, `Inventory Items`, `Units of Measure`.

## Terminology decisions

| Concept | Internal/domain terminology (unchanged) | Operator-facing terminology |
|---|---|---|
| Product name | CMP | GrowCMP (superseded PILOT-UX-001A, 2026-09-01; was "Crop Management Platform") |
| InterSalads stage | `intersalads`, `IntersaladsTransplantForm`, `intersalads_table`, etc. | **Inter Leafy Greens** |

The InterSalads → "Inter Leafy Greens" change is a **UI display-label adaptation only**.
Do not rename database tables, columns, enums, API fields, route segments, component
names, or any other domain/code identifier. `docs/domain/LOCATION_MODEL.md` and
`docs/product/GLOSSARY.md` remain authoritative for the internal term.

No other terminology renames are approved by this specification.

## ADOPT / ADAPT / REJECT decisions

| Concept | Decision | Notes |
|---|---|---|
| CEO visual language (typography/color/cards) | ADOPT | Applies across the full pilot journey (see UI-OPT-001 scope) |
| Grouped/collapsible navigation | ADOPT | Rebuilt as real routed nav per Final navigation above |
| Product name wording | ADAPT | Keep visual brand block; brand text is now GrowCMP (superseded PILOT-UX-001A, 2026-09-01) |
| InterSalads → Inter Leafy Greens | ADAPT | Display label only, see Terminology decisions |
| Capacity calculators, round-up/down helper | ADOPT | Read-only advisory UI only |
| Inspection presented as one guided stage | ADAPT | Visual/flow grouping only — see Frozen domain protections |
| Same-day/variety batch merge on re-sowing | REJECT | Violates one-Sowing-per-batch rule; not implemented |
| Client-previewed sequential Batch ID | REJECT | Batch codes remain server-generated, never previewed |
| Whole-batch "Reject Batch" action | REJECT | No corresponding lifecycle state; not implemented |
| Admin + 2FA unlock-to-edit for saved Greenhouse records | REJECT | No basis in the append-only architecture; not implemented |
| Vines "Crop Allocation" embedded in Farm Setup | REJECT (placement) | Belongs to a future production-planning surface, not permanent infrastructure |
| Missing mandatory Zone level in Leafy/Vine setup forms | REJECT | Zone remains mandatory; any setup UI touched in UI-OPT-001 must reflect this |
| Free-form Nursery section builder | REJECT | Existing fixed optional-section template already matches the domain model; not replaced |
| Crop & Variety Master / Cultivation Method Templates / Input Master CRUD | DEFER | Out of UI-OPT-001; see Deferred functionality |
| Production Plan Reference | ADAPT / DEFER | Strategically valid, needs dedicated future domain design; not faked in UI-OPT-001 |
| InterVines transfer screen | DEFER | Not an Iceberg pilot blocker; later Vines workstream |
| KPI & Reporting | FUTURE MODULE | Reclassified from gated/REJECT; architectural gate satisfied, but not built in UI-OPT-001 |
| Task & Labor Management, Maintenance & Assets, remaining Production Operations items (crop cycle monitoring, nutrient/irrigation, pest/disease, pruning) | FUTURE MODULE | No current implementation or domain backing; own discovery required |

## Frozen domain protections

UI-OPT-001 (and any future work building on it) must not violate the following,
regardless of what the CEO mockups depict:

1. One Sowing command produces exactly one Crop Batch and one Sowing Event, ever — no
   merging of separate sowings by day/variety/seed lot.
2. Batch codes are always server-generated; never client-generated, entered, or
   exactly previewed before save.
3. Leafy-greens and Vines location hierarchies keep Zone and Span as mandatory levels;
   Nursery does not use Zone/Span.
4. Nursery Cultivation Plate and Production Cultivation Plate remain distinct carrier
   types; a plant transplants from one to the other, never in place.
5. Production, audit, genealogy, movement, traceability and referenced
   operational/master-data history must not be hard-deleted. Corrections use the
   appropriate reversal, disposition, supersession, deactivation or new-version
   mechanism.
6. Crop workflows, recipes, and variety parameters are versioned; a Crop Batch stays
   permanently bound to the workflow version active at its creation.
7. UI-OPT-001 must not introduce in-place mutation of immutable operational history or
   an "unlock and overwrite" pattern for saved Greenhouse structures. Existing
   command/audit architecture remains authoritative. This specification does NOT
   permanently prohibit every future use of PUT/PATCH/DELETE for unrelated
   administrative resources.
8. Germination Record Outcome and Move to Seedling remain two separate backend
   commands (including the provisional-vs-final assessment distinction). UI may present
   them as one coherent guided operator stage; the underlying commands are not merged.
9. Biological loss/rejection/mortality is recorded only through the existing
   disposition/loss ledger mechanisms (e.g. `SeedlingDispositionEvent`), at carrier/line
   granularity. There is no whole-batch reject action.
10. Grow Gutter Side (left/right) remains non-locational — canopy/training data only.
11. Existing genealogy, ledgers, movements, occupancy, recall containment, reversals,
    and permissions architecture are not redesigned as part of this work.
12. Tray cells, carrier capacity, plate capacity and other theoretical capacity values
    are planning aids only. They must never be treated as authoritative living
    population. Authoritative living population comes from CMP biological
    observations, population checkpoints, and subsequent disposition/transfer ledgers.
13. At Germination, normal and abnormal/weak emerged seedlings are both living.
    Weak/abnormal living seedlings remain living and are not recorded as loss merely
    because of condition. If later removed, removal is recorded as a separate
    disposition/loss event — the original Germination observation is not rewritten.
14. Exactly one factual dispatch temperature is recorded at DispatchEvent/vehicle
    level and applies to the whole dispatch. No per-Finished-Goods-lot, per-product,
    per-container, or per-dispatch-line temperature fields may be introduced.

## UI-OPT-001 exact scope

UI-OPT-001 is a **visual and navigation alignment pass**, not a domain or feature
build. It applies the adopted CEO design language and the frozen navigation tree
across the **complete currently-built Iceberg pilot journey** — not only the three
screens the CEO mockups covered. In scope:

- Nursery (Seeding, Germination, Seedling, Transfer to Inter Leafy Greens)
- Leafy Production, Transfer to Production
- Harvest
- Grading, Graded Produce Lots, Packing, Finished Goods, Cold Storage
- Dispatch, Traceability, Recall Cases
- Farm Setup (Greenhouse & Locations), Carrier Specifications

For the screens beyond the three CEO mockups (Leafy Production, Harvest, Grading,
Graded Produce, Packing, Finished Goods, Cold Storage, Dispatch, Traceability, Recall
Cases), there is no CEO-supplied mockup — apply the same design system (typography,
color tokens, card/tab treatment) extracted from the three mockups that do exist,
rather than inventing new per-screen visual concepts.

**Domain behavior must remain unchanged unless separately approved.** UI-OPT-001 may
restyle, regroup navigation, relabel (per Terminology decisions), and add read-only
advisory UI (calculators, previews of already-server-authoritative data). It must not
add, remove, merge, or reshape backend commands, endpoints, entities, or lifecycle
states.

Within setup/registration screens touched by this work, the mandatory Zone level
(Leafy/Vine) must be present if it is not already — this is a correction to bring the
UI in line with the existing, already-implemented domain rule, not a new rule.

## Explicitly deferred functionality

Not implemented in UI-OPT-001 or PILOT-SETUP-001:

- **InterVines transfer screen** — not an Iceberg pilot blocker; deferred to a later
  Vines workstream.
- **KPI & Reporting** — reclassified to Future Module (architectural gate satisfied);
  not built now.
- **Production Plan Reference** — reclassified to ADAPT/DEFER; a strategically valid
  concept that needs a dedicated future production-planning domain design. No fake or
  placeholder version of it is implemented in the meantime.
- **Crop & Variety Master, Cultivation Method Templates, Input Master** — not part of
  UI-OPT-001. "Farm Setup & Master Data" may exist as a navigation umbrella label, but
  no CRUD or other unsupported domain functionality is invented under it.
- **Admin + 2FA unlock-to-edit for saved Greenhouse records**, and any
  structural-edit/supersession command for Farm Setup — not built in UI-OPT-001.
  Structural correction/versioning for Farm Setup can be separately designed later if
  operationally required; existing authorization and audit architecture remains
  authoritative until then.
- **Whole-batch Reject Batch action** — not implemented; existing per-carrier
  disposition/loss mechanisms remain authoritative.
- **Collapsing Record Outcome and Move to Seedling into one backend command** — not
  done; only the presentation may be unified into a guided stage.

## Future product implications

- **Task & Labor Management**, **Maintenance & Assets**, and the unbuilt parts of
  **Production Operations** (crop cycle monitoring, nutrient/irrigation management,
  pest/disease scouting, pruning/training) remain Future Modules with no current
  implementation or domain-model backing. Each requires its own discovery pass, and,
  where it introduces new domain concepts, an ADR, before implementation.
- **KPI & Reporting** is now unblocked at the architectural level but still requires
  its own scoping/discovery pass before any build begins.
- **Production Plan Reference** requires a dedicated domain design (grouping/entity
  model, relationship to Crop Batch, versioning) before any UI work references it.
- **InterVines transfer** requires a build matching the rigor of the existing
  InterSalads/Inter Leafy Greens transplant flow (per-source loss capture, carrier
  validation) when the Vines workstream picks it up.
- Per product-owner decision, **future modules are not shown as disabled or
  "Coming Soon" entries in production navigation** — a module is added to the
  navigation tree only once it is functional. This specification's Final navigation
  section will be revised at that time, not extended speculatively now.
