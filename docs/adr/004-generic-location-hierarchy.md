# ADR 004: Generic Location Hierarchy

## Context

CMP must support many farm layouts (nursery, leafy-green, vine, stores, cold store) across many tenants, without hard-coding a fixed set of levels such as greenhouse/zone/span/table/gutter into the schema — new crops, workflows, and layouts must be configuration, not new code paths or tables.

## Decision

Use a single UUID-based parent-child location tree per farm. Locations reference a parent location by UUID; templates (nursery, leafy-green, vine, store, cold store) are expressed as configured paths through this generic tree, and farms may omit optional levels (e.g. zone). No operational table repeats fixed greenhouse/zone/span/table/gutter columns.

## Consequences

- New location templates or crop layouts can be added through configuration, without schema changes.
- Queries that need "effective location" must walk the parent-child tree (and, for carriers inside assets, the containment chain — `docs/domain/LOCATION_MODEL.md`) rather than reading a fixed set of columns.
- Depth-dependent logic (e.g. "the zone level") cannot be hard-coded and must be resolved generically.

## Rejected alternatives

- **Fixed-depth columns per operational table** (e.g. `greenhouse_id`, `zone_id`, `span_id`, `table_id` on every table) — rejected: violates the crop-agnostic requirement (`CLAUDE.md` rule 1) and cannot represent optional or varying depth across nursery/leafy/vine/store templates.
