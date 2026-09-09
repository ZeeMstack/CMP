# Open Questions

Unresolved matters requiring an explicit decision before the relevant work is built. Per `CLAUDE.md`, do not invent agronomic, quality, security, or architectural rules — record the gap here instead.

None of the items below are treated as invented values; they are recorded as open rather than answered.

## Technical decisions

- ~~**OIDC provider selection.**~~ Resolved: Auth0 is the implemented production identity provider, behind the OIDC-compatible application adapter approved here (`docs/domain/AUTHORIZATION_MODEL.md`, "Layered trust model").
- **PostgreSQL RLS policy detail.** RLS is approved as defence in depth alongside mandatory application-level tenant scoping, but concrete policy definitions (per-table policies, role setup) are not yet specified. Does not block application scaffolding.
- **Frontend effective-permission signal.** No endpoint currently exposes a caller's effective permission set to the frontend — every screen renders its actions unconditionally and relies on the backend's `403` to reject an unauthorized attempt. A proper permission-aware action UX (hiding/disabling actions a role cannot perform, rather than rendering and failing) is a cross-product future concern affecting every module, not a Store & Inventory-specific gap. `UX-IA-001` deliberately continues relying on existing backend authorization and does not add a Store-only workaround; do not invent a client-side role→permission mapping in the meantime.

## Operational greenhouse decisions

- Exact set of controlled location templates beyond nursery/leafy/vine examples in `CMP_MASTER_SPEC.md` §3 (e.g. additional greenhouse types) is not yet defined.
- Sanitation/release requirement definitions per location type (referenced in spec §3.4) are not yet specified.

## Agronomic decisions

- Crop/variety-specific stage definitions, expected durations, and harvest modes are explicitly deferred to versioned crop/workflow configuration (spec §8) and are not to be invented ahead of that configuration work.
- Quality/QC thresholds and release criteria are not yet defined.

## Store and inventory decisions

- ~~**InventoryLot↔SeedLot cardinality.**~~ Resolved by the `STORE-INV-002A` discovery: `SeedLot.inventory_lot_id` (nullable FK, not the reverse direction) — one tenant-wide `InventoryLot` may link to many Farm-scoped `SeedLot`s, at most one per Farm. See `docs/domain/STORE_INVENTORY_MODEL.md` §15.

## Deferred commercial decisions

- Customer specification structure and versioning details (spec §8) beyond "customer specifications are versioned" are not yet defined.
- Recall process detail beyond the traceability genealogy requirement (spec §10) is not yet defined.

## Vines Production decisions

- **Vines Grow Cube disposition correction: replace-mode deferred.** `VINES-OPS-002` implements void-only correction (`production_disposition_service.correct_grow_cube_disposition`) for a Vines `grow_bag` disposition REDUCTION -- a pure reversal that restores every one of the target event's own named Grow Cube(s) to disposal eligibility, delegating unmodified to the already carrier-agnostic `correct_disposition`. REPLACE-mode correction (voiding an original loss and simultaneously recording a corrected replacement REDUCTION) is NOT exposed for Vines: `correct_disposition`'s existing REPLACE shape carries only a bare `plant_loss_count`, with no field for which specific Grow Cube(s) the replacement names, and fabricating that identity (e.g. reusing the original event's own Grow Cubes) would be an invented fact, not a derived one, when the correction's whole point may be that the ORIGINAL identification was wrong. Extending `ProductionDispositionEvent`'s REPLACE shape to carry an explicit corrected Grow Cube set is left for a follow-up ticket rather than rushed here (per the ticket's own instruction: "if extending correction materially complicates this ticket, STOP ONLY that subpart"). Void-then-re-record (two separate, already-supported commands) is the current operator path for a full "I identified the wrong plant" correction.

## Migration graph decisions

- **`seed_lots.inventory_lot_id` vs. pre-STORE-INV-004 downgrade-guard tests.** `VINES-OPS-001B` adds the first Alembic merge revision (`475ed950cb4e`) joining the previously separate, never-connected Nursery/InterSalads branch (`b7e2f4a9c1d6`) and the STORE-INV-004 branch (`86b9cf24d6ff`) into one continuous chain. Before this merge, a full downgrade/re-upgrade walk that crosses *both* lineages in one continuous Alembic history was structurally impossible, so an existing incompatibility between them was unreachable and undetected. It is now reachable: four pre-existing downgrade-guard tests (`test_recall_downgrade_guard.py::test_clean_downgrade_with_no_recall_history_reupgrade_restores_exact_prior_state`, `test_migrations.py::test_migration_backfill_matches_pre_existing_lot_and_survives_downgrade_reupgrade`, `test_migrations.py::test_migration_upgrade_preserves_legacy_germination_check_rows`, `test_nursery_ops_downgrade_guard.py::test_migration_upgrade_blocked_by_pre_existing_mixed_seed_lot_lines`) downgrade the schema to a point that predates STORE-INV-004's `seed_lots.inventory_lot_id` column, then call the current, head-shaped `sowing_service.register_seed_lot` (whose INSERT unconditionally includes that column) against that older schema, and fail with `psycopg.errors.UndefinedColumn`. Confirmed structural (reproduces on a freshly reset, data-clean `cmp_test`), not a data-leakage artifact. Deciding how to reconcile this — e.g. making the column write conditional on schema state, giving these test helpers a raw-SQL seed-lot insert path for pre-STORE-INV-004 schema states, or something else — is a STORE-INV-004/NURSERY-OPS/CMP-020 test-fixture ownership decision, not a `VINES-OPS-001B` (Grow Cube/Grow Bag business logic) change, and is left unresolved here rather than silently patched. `VINES-OPS-001B`'s own new migrations (`475ed950cb4e`, `810e24e6ce43`, `43246a360bbd`) upgrade and downgrade cleanly on both legs of the merge; they are not implicated in the failure.
