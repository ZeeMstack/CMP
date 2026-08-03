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

## Terms introduced by approved architecture decisions

| Term | Meaning | Source |
|---|---|---|
| `scan_identity` | Record linking an opaque public QR token to the entity it identifies; the token itself carries no mutable data | `docs/adr/006-scan-identity-tokens.md` |
| Idempotency key | Client-generated UUID accompanying a command, enforced unique per tenant and command type by the server | `docs/adr/007-client-generated-idempotency.md` |
| Row-Level Security (RLS) | PostgreSQL feature enforcing tenant scoping at the database layer, used as defence in depth alongside mandatory application-level tenant scoping | `docs/domain/MULTI_TENANCY.md` |
| Tenant scoping | Application-level requirement that every query/command is filtered and authorized by `tenant_id` | `docs/domain/MULTI_TENANCY.md` |
