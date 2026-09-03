# Open Questions

Unresolved matters requiring an explicit decision before the relevant work is built. Per `CLAUDE.md`, do not invent agronomic, quality, security, or architectural rules — record the gap here instead.

None of the items below are treated as invented values; they are recorded as open rather than answered.

## Technical decisions

- ~~**OIDC provider selection.**~~ Resolved: Auth0 is the implemented production identity provider, behind the OIDC-compatible application adapter approved here (`docs/domain/AUTHORIZATION_MODEL.md`, "Layered trust model").
- **PostgreSQL RLS policy detail.** RLS is approved as defence in depth alongside mandatory application-level tenant scoping, but concrete policy definitions (per-table policies, role setup) are not yet specified. Does not block application scaffolding.

## Operational greenhouse decisions

- Exact set of controlled location templates beyond nursery/leafy/vine examples in `CMP_MASTER_SPEC.md` §3 (e.g. additional greenhouse types) is not yet defined.
- Sanitation/release requirement definitions per location type (referenced in spec §3.4) are not yet specified.

## Agronomic decisions

- Crop/variety-specific stage definitions, expected durations, and harvest modes are explicitly deferred to versioned crop/workflow configuration (spec §8) and are not to be invented ahead of that configuration work.
- Quality/QC thresholds and release criteria are not yet defined.

## Store and inventory decisions

- **InventoryLot↔SeedLot cardinality.** `docs/domain/STORE_INVENTORY_MODEL.md` §15 freezes that `SeedLot` remains the crop-specific traceability identity and `InventoryLot` the generic quantity/lot identity, linked together — but the exact cardinality (one-to-one vs. one-to-many) must be confirmed against actual existing `SeedLot` semantics during `STORE-INV-002A` design, not assumed now.

## Deferred commercial decisions

- Customer specification structure and versioning details (spec §8) beyond "customer specifications are versioned" are not yet defined.
- Recall process detail beyond the traceability genealogy requirement (spec §10) is not yet defined.
