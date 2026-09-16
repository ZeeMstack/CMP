# Glossary

## Core domain concepts (`CMP_MASTER_SPEC.md` §2)

| Term | Meaning | Examples |
|---|---|---|
| Location | Fixed occupiable place | chamber position, table position, grow-bag position, store bin |
| Asset | Managed physical item, often mobile | trolley, grow table asset, seeder, scale |
| Carrier | Identified object holding crop/product | seed tray, cultivation plate, grow cube, grow bag, crate, carton |
| Equipment | Performs work | seeder, printer, irrigation robot, packing line |
| Batch/Lot | Traceable production or inventory identity | crop batch, seed lot, harvest lot, pack lot |
| Occupancy | Who/what occupies a location during a period | tray in trolley slot |
| Movement | Same entity changes location | trolley moved to another chamber position |
| Transformation | Inputs become outputs | seedlings transferred from tray to plates |

## Crop and workflow configuration (`CMP_MASTER_SPEC.md` §8, `docs/domain/CROP_WORKFLOW_MODEL.md`)

| Term | Meaning |
|---|---|
| Crop | Tenant-owned catalog entry identifying what is grown (e.g. Iceberg Lettuce); crop-agnostic — never referenced by name in code |
| Variety | A specific cultivar of one crop, belonging to exactly one crop and tenant (e.g. Mamutik RZ under Iceberg Lettuce) |
| Production System | Tenant-owned description of how a crop is physically produced (e.g. nursery seed tray, leafy cultivation plate) |
| Workflow | A named production process for one crop, optional variety, and production system, owned by one tenant |
| Workflow Version | An immutable-once-published revision of a workflow's stage/transition structure; states `draft` → `published` → `retired` |
| Workflow Stage | A step within one workflow version, carrying a stage category, optional expected duration, and optional location/carrier constraints |
| Workflow Transition | A permitted movement between two stages of the same workflow version |

## Crop batch execution (`CMP_MASTER_SPEC.md` §2, §8, `docs/domain/CROP_BATCH_MODEL.md`)

| Term | Meaning |
|---|---|
| Crop Batch | One real production run, tenant- and farm-owned, permanently bound to the workflow version published at its creation |
| Batch Stage Run | Immutable-history record of one batch occupying one workflow stage; the batch's current stage is always its one run with no exit time |
| Batch Stage Transition | Immutable, insert-only record of one stage-progression command — either a batch's initial entry or a configured-transition move |

## Seed sowing and carrier assignment (`CMP_MASTER_SPEC.md` §2, §8, `docs/domain/SEED_SOWING_MODEL.md`)

| Term | Meaning |
|---|---|
| Seed Lot | Tenant- and farm-owned identity of a supplier seed source for one crop/variety; traceability only, no inventory balance |
| Sowing Event | Immutable, insert-only record of one sowing command, tied to the batch's exact active seeding-stage run at execution time |
| Sowing Event Line | One immutable per-carrier line of a sowing event: one carrier, one seed lot, sown-site count, seed count |
| Batch Carrier Assignment | Immutable-history record of one carrier holding one crop batch; answers "what batch", never "where" (see Occupancy) |

## Observations and quality holds (`CMP_MASTER_SPEC.md` §2, §8, `docs/domain/OBSERVATION_QUALITY_MODEL.md`)

| Term | Meaning |
|---|---|
| Observation Definition | Tenant-owned, reusable structured metric (type, unit, target scope, bounds); immutable once created except `status` |
| Observation Event | Immutable, insert-only record of one observation command, tied to the batch's exact active stage run at execution time |
| Observation Value | One immutable typed value within an observation event, targeting a crop batch, a carrier assignment, or both depending on its definition |
| Germination Check | Immutable, narrow (non-generic) inspection record for one carrier assignment; same-row `CHECK` constraints enforce category counts against the inspected population |
| Quality Hold | Immutable, batch-level block on stage progression; multiple simultaneous open holds are permitted; open/released state is derived, never stored |
| Quality-Hold Release | Immutable decision record removing one quality hold; a new record, never a mutation of the original hold |

## Carrier release and transplantation (`CMP_MASTER_SPEC.md` §2, §8, `docs/domain/TRANSPLANTATION_MODEL.md`)

| Term | Meaning |
|---|---|
| Transplant Event | Immutable, insert-only record of one transplantation command, tied to the batch's exact active transplanting-stage run at execution time |
| Transplant Source Line | One immutable line of a transplant event naming a released, sowing-origin carrier assignment and its plant/discard counts; each assignment can be a source at most once, ever |
| Transplant Destination Line | One immutable line of a transplant event naming a freshly assigned destination carrier and its plant count |
| Transplant Allocation | One immutable integer plant count moving from one source line to one destination line; the many-to-many bridge between them |
| Assignment Origin | Which command opened a `batch_carrier_assignment` — exactly one of a sowing event (CMP-009) or a transplant event (CMP-011) |
| Assignment Release | The closing of a sowing-origin `batch_carrier_assignment` by a transplant event; only sowing-origin assignments are releasable in CMP-011 |

## Crop-batch split and merge lineage (`CMP_MASTER_SPEC.md` §2, §8, `docs/domain/BATCH_DERIVATION_MODEL.md`)

| Term | Meaning |
|---|---|
| Batch Derivation | Umbrella term for the two CMP-012 commands that change crop-batch identity: split and merge |
| Batch Split | One active crop batch becomes two or more new active crop batches; its active carrier assignments are partitioned among the outputs |
| Batch Merge | Two or more compatible active crop batches become one new active crop batch; all their active carrier assignments move to the output |
| Source Batch | A batch consumed by a derivation event; becomes superseded, never terminally closed |
| Output Batch | A batch newly created by a derivation event; never an existing batch selected by the client |
| Superseded Batch | Terminal crop-batch lifecycle state reached only via one valid split or merge event; distinct from `closed` |
| Assignment Transfer | One immutable record of a single carrier's complete active assignment moving from a source batch to an output batch |
| Derivation Entry | Internal, non-client-facing `batch_stage_transition` provenance record opening an output batch's first active stage run |

## Harvest event and harvested produce lot (`CMP_MASTER_SPEC.md` §2, §8, `docs/domain/HARVEST_MODEL.md`)

| Term | Meaning |
|---|---|
| Harvest Event | Immutable, insert-only record of one harvest command, tied to the batch's exact active harvesting-stage run at execution time |
| Harvest Source Line | One immutable per-assignment line of a harvest event naming an active carrier assignment and its harvested weight/count; the same assignment may be harvested again in a later, separate event |
| Harvested Produce Lot | Immutable identity created by exactly one harvest event, carrying the event's total harvested weight/count and snapshot batch/workflow/crop/variety traceability; not yet inventory |
| Harvest Weight | The authoritative harvested quantity, in kilograms, stored as an exact Decimal — never binary float, never derived from count |
| Whole-Unit Count | Optional per-line unit count; an event is either all-lines-counted or zero-lines-counted, never partial, and is never derived from weight |

## Produce-lot opening receipt ledger (`CMP_MASTER_SPEC.md` §2, §7, §8, `docs/domain/PRODUCE_LOT_LEDGER_MODEL.md`)

| Term | Meaning |
|---|---|
| Produce-Lot Ledger | Immutable, append-only `produce_lot_ledger_entries` record of every quantity movement against one harvested produce lot; CMP-014 permits opening receipts, CMP-015 adds typed packing debits |
| Harvest Receipt | The one immutable ledger entry every harvested produce lot receives automatically, inside the harvest transaction, recording its original harvested weight/count; not a second user command |
| Ledger Entry | One immutable row in the produce-lot ledger, typed by `entry_kind`, carrying a weight delta (and optional whole-unit-count delta) rather than a stored balance |
| Available Produce Weight | Derived `SUM(weight_delta_kg)` across a lot's ledger entries — never a stored/editable column; decreases as `packing_consumption` debits post |
| Available Whole-Unit Count | Derived `SUM(whole_unit_count_delta)` across a lot's ledger entries — never a stored/editable column; null when the lot itself carries no unit count |

## Typed packing consumption and finished-goods lots (`CMP_MASTER_SPEC.md` §2, §7, §8, `docs/domain/PACKING_MODEL.md`)

| Term | Meaning |
|---|---|
| Packing Event | Immutable, insert-only record of one packing command, consuming weight/count from one or more source harvested produce lots and creating exactly one finished-goods lot |
| Packing Input Line | One immutable line of a packing event naming a source harvested produce lot and the weight/optional count consumed from it; one lot appears at most once per event |
| Packing Consumption | The `entry_kind` of the one negative ledger debit each packing input line creates automatically, inside the packing transaction; its id equals its input line's own id |
| Finished-Goods Lot | Immutable identity created by exactly one packing event, carrying its packed-output weight and package count; carries no balance, status, storage location, grade, SKU, customer, or cost |
| Packed Output Weight | The portion of a packing event's total input weight that became the finished-goods lot's own net weight |
| Process Loss | The portion of a packing event's total input weight lost to processing; zero or positive, never negative |
| Rejected Weight | The portion of a packing event's total input weight rejected during packing; zero or positive, never negative |
| Package Count | The number of finished packs or containers a packing event produced; not the same semantic quantity as a source lot's whole-unit count, and never reconciled against it |

## Finished-goods opening receipt ledger (`CMP_MASTER_SPEC.md` §2, §7, §8, `docs/domain/FINISHED_GOODS_LEDGER_MODEL.md`)

| Term | Meaning |
|---|---|
| Finished-Goods Ledger | Immutable, append-only `finished_goods_ledger_entries` record of every quantity movement against one finished-goods lot; CMP-016 permits only opening receipts |
| Packing Receipt | The one immutable ledger entry every finished-goods lot receives automatically, inside the packing transaction, recording its original packed weight/package count; not a second user command |
| Finished-Goods Available Weight | Derived `SUM(weight_delta_kg)` across a lot's ledger entries — never a stored/editable column; equals received weight until a future typed entry kind exists |
| Available Package Count | Derived `SUM(package_count_delta)` across a lot's ledger entries — never a stored/editable column; distinct from a source produce lot's whole-unit count, never reconciled against it |

## Typed finished-goods dispatch foundation (`CMP_MASTER_SPEC.md` §2, §7, §8, `docs/domain/DISPATCH_MODEL.md`)

| Term | Meaning |
|---|---|
| Dispatch Event | Immutable, insert-only record of one dispatch command, reducing weight/count from one or more finished-goods lots; a successfully inserted row is a completed dispatch — there is no status or editable completion flag |
| Dispatch Line | One immutable line of a dispatch event naming a finished-goods lot and the weight/package count dispatched from it; one lot appears at most once per event |
| Dispatch Issue | The `entry_kind` of the one negative ledger entry each dispatch line creates automatically, inside the dispatch transaction; its id equals its dispatch line's own id |
| Dispatched Weight | The weight, in kilograms, removed from a finished-goods lot by one dispatch line; always strictly positive on the line, always strictly negative on its ledger issue |
| Dispatched Package Count | The number of packages removed from a finished-goods lot by one dispatch line; always strictly positive on the line, always strictly negative on its ledger issue; not the same semantic quantity as any source produce lot's whole-unit count |

## Cold-store location and finished-goods physical occupancy (`CMP_MASTER_SPEC.md` §3.4, §10, `docs/domain/FINISHED_GOODS_STORAGE_MODEL.md`)

| Term | Meaning |
|---|---|
| Storage Movement | One immutable, insert-only row in `finished_goods_storage_movements` recording a single physical relocation (`place`, `transfer`, or `release`) of a finished-goods lot; never alters the finished-goods ledger's own commercial quantity |
| Place | A storage movement moving quantity from unplaced into a named storage-eligible location (source NULL, destination required) |
| Transfer | A storage movement moving quantity from one storage-eligible location directly to another (both required, must differ) |
| Release | A storage movement moving quantity from a named location back to unplaced (source required, destination NULL) |
| Storage-Eligible Location | A location whose type is exactly `cold_store_position`; the sole eligible target/source for storage movements |
| Total Placed Quantity | Derived `SUM(place) − SUM(release)` across a lot's storage movements — never a stored column; transfers have zero net effect on this total by construction |
| Unplaced Quantity | Derived `available − total_placed` for a finished-goods lot — never a stored column and never a fake "unplaced location" row |
| Location Balance | Derived `SUM(weight/count arriving) − SUM(weight/count leaving)` for one location across a lot's storage movements — always ≥ 0 |
| Release-Before-Dispatch | The rule that a dispatch line may consume only currently unplaced quantity, in addition to CMP-017's own commercial-balance checks; there is no automatic release |

## Store and inventory (frozen design, STORE-INV-001 family, `CMP_MASTER_SPEC.md` §3.4, §9, `docs/domain/STORE_INVENTORY_MODEL.md`)

| Term | Meaning |
|---|---|
| Store | An existing `Location` with `location_type = store`; a Farm root; a Farm may have several |
| Store Area / Store Rack | Optional intermediate Store location levels between Store and Store Bin; no Store Shelf |
| Store Bin | The occupiable, stock-placement leaf of the Store location tree |
| Unit of Measure | Global, system-seeded unit catalog entry (e.g. `kg`, `g`, `L`, `mL`, `EA`, `SEED`) |
| Inventory Category | Tenant-configured classification/reporting metadata for an Inventory Item — never a behavior switch |
| Inventory Item | Tenant-scoped consumable-material master, reusable across the tenant's Farms |
| Inventory Lot | Traceable lot identity for consumable material; not the same thing as one Goods Receipt |
| Existence Quantity | How much material currently exists, per the immutable existence ledger — unaffected by Issue |
| Custody | Where existing material currently is / who holds it (Store vs. Work Order) — a separate fact from existence quantity |
| Material Issue | A custody event moving material from Store custody to Work Order custody; does not reduce existence quantity |
| Consumption | A destruction/use event that reduces existence quantity |
| Quality Disposition Event | One immutable event in a lot's quarantine/release/hold/reject history; current disposition is always derived from event history |
| Asset Custody Assignment | Future (`STORE-INV-005`) record of a person's custody of an Asset, independent of the Asset's physical Occupancy |

## End-to-end recall and traceability (`CMP_MASTER_SPEC.md` §2, §7, §8, §10, `docs/domain/TRACEABILITY_MODEL.md`)

| Term | Meaning |
|---|---|
| Backward Trace | A read-only query starting from one finished-goods lot, resolving its complete provable upstream lineage (packing → harvest → crop-batch ancestry → seed/sowing origin) plus current storage/dispatch/quality state |
| Forward Impact | A read-only query starting from one crop batch or harvested produce lot, resolving every reachable downstream finished-goods lot and dispatch that may contain material from it |
| Potentially Affected Quantity | A finished-goods lot's own entire current available/placed/unplaced/dispatched quantity, reported for a forward-impact result — never a quantity computed by scaling a source input against the lot's total; CMP-019 never invents proportional attribution |
| Source Input Quantity | The exact weight/count of an affected upstream input that entered one packing event — a known fact, distinct from (and never used to derive) the potentially affected output quantity |
| Trace Completeness | The `trace_complete`/`limitations`/`capability_limitations` triad describing whether a trace fully resolved within CMP's modeled graph; a legitimately empty branch is complete, a missing optional historical edge is a limitation, and a genuine invariant violation (e.g. a lineage cycle) is a `TraceabilityIntegrityError`, never a silent partial result |

## Recall case and containment (`CMP_MASTER_SPEC.md` §2, §7, §8, §10, `docs/domain/RECALL_CONTAINMENT_MODEL.md`)

| Term | Meaning |
|---|---|
| Recall Case | Immutable, insert-only formal food-safety containment decision (CMP-020); the row itself is the "opened" fact — no separate opened-event row, no mutable status column; exactly one typed source (crop batch, harvested produce lot, or finished-goods lot) |
| Recall Case Closure | Immutable, insert-only decision ending one recall case's active containment; at most one per case; never implies product recovery, customer notification, or quality-hold release |
| Frozen Scope | The immutable set of crop-batch/harvested-produce-lot/finished-goods-lot IDs computed and locked at recall-case opening — entity identity only, never a balance or the recall's own open/closed state |
| Containment | The derived, always-current fact that a specific entity is a member of an OPEN recall case's frozen scope; begins at open-commit, ends at close-commit, never based on effective-time arithmetic |
| Live State | Current available/placed/unplaced/dispatch reads for a recall case's scoped finished-goods lots — always computed fresh, distinct from and never merged with frozen scope |

## Farm work engine and shift handover (`docs/domain/FARM_WORK_ITEM_MODEL.md`)

| Term | Meaning |
|---|---|
| Farm Work Item | A small, operator-facing task/assignment record ("Today on the Farm") — never a substitute for the authoritative farm transaction (harvest, observation, ...) it may relate to |
| Completion Mode | `MANUAL_RECORD` (explicit operator checkbox) vs. `OPERATIONAL_RECORD` (can only complete by linking the real resulting GrowCMP record — never a checkbox) |
| Result Reference | The structured `result_entity_type`/`result_entity_id`/`result_recorded_at` an `OPERATIONAL_RECORD` Work Item stores once linked — the answer to "what record proves this work was completed?" |
| Blocked | A Work Item's active-but-stalled state; requires a reason; Unblock/Resume always returns it to `IN_PROGRESS` |
| Shift Handover | A small, immutable, insert-only note a user finishing a shift leaves for the farm; may reference unresolved Work Items but never closes or clones them |

## QR labels and scan context (`docs/adr/006-scan-identity-tokens.md`, `docs/domain/QR_SCAN_MODEL.md`)

| Term | Meaning |
|---|---|
| QR Identifier | This ticket's concrete implementation of ADR 006's `scan_identity` concept (`qr_identifiers` table/`QrIdentifier` model) — links an opaque public token to exactly one of eight supported entities; one active identifier per entity, reused on reprint, never regenerated |
| Scan Context | The typed, discriminated-by-`entity_type` response a resolved QR token returns — current authoritative facts read fresh at scan time, never stored on the QR row itself |
| Permanent identity | Carrier/Asset/Location — the QR label stays with the physical object/place for its life; never prints a mutable fact (current Batch/location/status) |
| Operational identity | Crop Batch/Batch Carrier Assignment ("placement")/Harvested Produce Lot/Graded Produce Lot/Finished Goods Lot — identifies an operational record; may print stable creation-time metadata (crop/variety), never current stage/status |
| Batch Carrier Assignment ("Placement") QR | The stable identity of ONE physical portion of a Batch (one Carrier's worth) — deliberately independent of both the Carrier's own permanent identity and the parent Batch's identity, since a Batch may occupy several Carriers/Locations at once |
| Permanent Physical Identity | (PILOT-SCAN-001D, frozen) The rule that every Location, Carrier, and Asset receives its permanent QR identity automatically the instant it is created (`qr_provisioning.ensure_qr_identifier_for_new_entity`, wired into every current creation path — see `docs/domain/QR_SCAN_MODEL.md`) — never a manual "Generate QR" step, and never later than that creation command's own commit. The QR never changes because the Batch occupant changes, the location changes, status changes, specification metadata changes, the resource becomes empty, or it is cleaned/reused for a different Batch — none of those are the entity's own identity. Carrier, Asset, and Location remain distinct domain primitives (never collapsed into one polymorphic "resource" concept); they merely share this one behavior |
| Current Occupancy | The existing, unmodified Occupancy/Movement mechanism (`docs/domain/` movement model) recording what physically occupies what RIGHT NOW; a Carrier's or Asset's own permanent QR always resolves the CURRENT occupancy dynamically at scan time, never a value stored on the QR row itself |
| Historical Assignment | A `BatchCarrierAssignment` whose `released_effective_time` is set — the relationship it names has ended, but the row (and its own QR, if one was generated) remains permanently resolvable and answers "ended," never silently re-resolving as if it were some other, later relationship on the same physical Carrier |
| Batch Master Label | (PILOT-SCAN-001B) A printed label whose QR identifies the Crop Batch itself (`entity_type = "crop_batch"`). Printed once per Batch (e.g. at Sowing); never printed as the sole identifier for a physical tray/plate/cube/bag — a Batch may occupy several carriers/locations at once, so this label alone can never answer "which physical thing am I standing next to?" |
| Operational Placement Label | (PILOT-SCAN-001B, entity rule frozen at FINAL CLOSURE) A printed label identifying ONE specific physical carrier/placement (a Seed Tray, Nursery/Production Cultivation Plate, Grow Cube, or Grow Bag) together with a print-time snapshot of the Batch/stage/location context it currently holds. The QR **always** identifies the stable Batch-placement identity — `entity_type = "batch_carrier_assignment"` — from the stage's own authoritative result/read model; **no implicit fallback to the Carrier's own Permanent Carrier Label identity exists**. If that stable identity is genuinely unavailable (Germination placement's own command response carries none, and the fallback worklist lookup can fail), NO Operational Placement Label is generated at all — the operator sees an explicit "Placement identity is not available yet. Refresh before printing." message instead, never a silently-substituted Carrier QR. The QR payload never encodes the stage/location itself — only the printed TEXT is stage-aware |
| Permanent Carrier Label | (PILOT-SCAN-001) A printed label whose QR identifies a Carrier's own permanent physical identity (`entity_type = "carrier"`), with no stage-specific context — PILOT-SCAN-001's original generic "Print Label" content. Distinct from an Operational Placement Label (above): a Carrier is reusable across Batches, so its own QR always resolves whatever it currently holds, while an Operational Placement Label's `batch_carrier_assignment` QR keeps resolving its one specific original placement for life, even after the same physical Carrier is later reused for a different Batch |
| Stage Label | (PILOT-SCAN-001B) Umbrella term for any label printed immediately after a workflow command records a batch/carrier/placement's move to a new operational stage (Sowing, Germination, Seedling, InterSalads, Leafy Production, InterVines, Vines Production) — always an Operational Placement Label (or, for the Batch itself, a Batch Master Label), built from that command's own already-authoritative result data, never a second source of truth |
| Print Request | (PILOT-SCAN-001) The recorded fact that a "Print Labels" action was clicked and the backend was asked to prepare a label for one QR identity (`AuditEvent` action `qr_label_print_requested`) — never a claim that a physical label actually left a printer |
| Reprint | (PILOT-SCAN-001) A second (or later) Print Request against the same already-existing QR identity — never a new QR, a new Batch/Lot/Carrier, or a new operational event. PILOT-SCAN-001B's per-stage "Print Labels" actions are always an initial print request for a freshly created identity. "**Reprint Current Label**" (PILOT-SCAN-001B FINAL CLOSURE) is the entry point offered from a current-context listing screen (the Germination worklist, the Seedling workspace, Leafy Production's Active Production Plates table) for reproducing a damaged current Stage Label — it links to the entity's own generic label/reprint route (`/farms/[farmId]/labels/[entityType]/[entityId]`), which re-resolves current authoritative context (current Batch/carrier/location, or "released") fresh every time, so a placement that has since moved to a new stage reprints its CURRENT label, never an obsolete prior-stage snapshot; never a new/second historical-label-reproduction feature |

**QR identity != printed mutable context.** A QR token (`qr_identifiers` row) never stores or encodes a Batch's stage, a Carrier's current occupant, a location, or any quantity — it is a permanent, opaque pointer to one entity, resolved fresh on every scan (`docs/domain/QR_SCAN_MODEL.md`). The human-readable TEXT printed alongside that same QR on a Stage Label may show a snapshot of current context taken at print time (Batch code, stage name, Chamber/Trolley/Level, destination table/gutter) — but that snapshot is presentation only, printed once, and immediately goes stale as soon as the entity moves again; it is never written back into the QR identifier row, and reprinting always re-resolves fresh authoritative context rather than reusing the old snapshot.

## Growing Protocol and Crop Inspection (`docs/domain/GROWING_PROTOCOL_INSPECTION_MODEL.md`)

| Term | Meaning |
|---|---|
| Growing Protocol | The versioned identity of one agronomic program (e.g. "Iceberg Lettuce — DWC — Summer Standard"), scoped by Crop/Variety/ProductionSystem — what SHOULD happen, never proof anything did |
| Growing Protocol Version | One immutable-once-ACTIVE set of agronomic content (`DRAFT -> ACTIVE -> RETIRED`, never edited in place once ACTIVE — a new version is created instead) |
| Protocol Observation Requirement | A protocol-version's expectation that a given, EXISTING `ObservationDefinition` be recorded during a given `stage_category` — required/recommended, with an optional frequency/due window; never a second Observation architecture |
| Protocol Care Activity | A small, non-agronomic-dosing structured crop-care expectation (inspect roots, scout pests, prune, ...) a protocol stage carries; never a nutrient recipe, dosing, or irrigation instruction (PILOT-WATER-001 territory) |
| Batch Protocol Assignment | Which `GrowingProtocolVersion` a Batch is actually following, with full history — one current (open-ended) row per Batch, closed and replaced (never rewritten) when the assignment changes |
| Grower Inspection | A structured, immutable, ACTUAL floor check a grower recorded — never proof a protocol requirement was followed. May reference (never duplicate) an `ObservationEvent` recorded in the same command |
| Inspection Finding | One practical observation category (vigor, roots, pest evidence, ...) recorded within a Grower Inspection, with `affected_count` (descriptive only — never reduces living inventory) and a `suspected_cause` |
| Crop Issue | A persistent crop problem opened from a significant Inspection Finding — `OPEN -> RESOLVED -> CLOSED`, never auto-created, never auto-resolved, never a Loss by itself |
| Suspected Cause / Confirmed Diagnosis | Two permanently distinct fields on a Crop Issue — the system never promotes one into the other; confirming a diagnosis is always its own deliberate, authorized command |
| Crop Issue Follow-up | A recorded IMPROVED/UNCHANGED/WORSENED/RESOLVED outcome against an open Crop Issue — descriptive only; a RESOLVED outcome never silently closes the Issue |
| Due / Overdue / Outside Expected Window | Deterministic, read-only labels computed from actual Batch timestamps, actual current stage, the assigned Protocol Version, and the most recent relevant Inspection/Observation — never persisted, never a trigger for an automatic stage change, movement, or farm event |

**Protocol != Operation. Age != Stage. Issue != Loss. Suspected Cause != Confirmed Diagnosis. Work Item Complete != Issue Resolved. Abnormal/Weak Living Plant != Loss.** These six frozen distinctions (`docs/domain/GROWING_PROTOCOL_INSPECTION_MODEL.md`) govern every command in this domain.

## Terms introduced by approved architecture decisions

| Term | Meaning | Source |
|---|---|---|
| `scan_identity` | Record linking an opaque public QR token to the entity it identifies; the token itself carries no mutable data | `docs/adr/006-scan-identity-tokens.md` |
| Idempotency key | Client-generated UUID accompanying a command, enforced unique per tenant and command type by the server | `docs/adr/007-client-generated-idempotency.md` |
| Row-Level Security (RLS) | PostgreSQL feature enforcing tenant scoping at the database layer, used as defence in depth alongside mandatory application-level tenant scoping | `docs/domain/MULTI_TENANCY.md` |
| Tenant scoping | Application-level requirement that every query/command is filtered and authorized by `tenant_id` | `docs/domain/MULTI_TENANCY.md` |
