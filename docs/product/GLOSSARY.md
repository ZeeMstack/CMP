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

## Terms introduced by approved architecture decisions

| Term | Meaning | Source |
|---|---|---|
| `scan_identity` | Record linking an opaque public QR token to the entity it identifies; the token itself carries no mutable data | `docs/adr/006-scan-identity-tokens.md` |
| Idempotency key | Client-generated UUID accompanying a command, enforced unique per tenant and command type by the server | `docs/adr/007-client-generated-idempotency.md` |
| Row-Level Security (RLS) | PostgreSQL feature enforcing tenant scoping at the database layer, used as defence in depth alongside mandatory application-level tenant scoping | `docs/domain/MULTI_TENANCY.md` |
| Tenant scoping | Application-level requirement that every query/command is filtered and authorized by `tenant_id` | `docs/domain/MULTI_TENANCY.md` |
