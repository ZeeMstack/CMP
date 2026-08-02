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

## Terms introduced by approved architecture decisions

| Term | Meaning | Source |
|---|---|---|
| `scan_identity` | Record linking an opaque public QR token to the entity it identifies; the token itself carries no mutable data | `docs/adr/006-scan-identity-tokens.md` |
| Idempotency key | Client-generated UUID accompanying a command, enforced unique per tenant and command type by the server | `docs/adr/007-client-generated-idempotency.md` |
| Row-Level Security (RLS) | PostgreSQL feature enforcing tenant scoping at the database layer, used as defence in depth alongside mandatory application-level tenant scoping | `docs/domain/MULTI_TENANCY.md` |
| Tenant scoping | Application-level requirement that every query/command is filtered and authorized by `tenant_id` | `docs/domain/MULTI_TENANCY.md` |
