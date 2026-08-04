# Carrier Release and Transplantation Transformation Model

Full detail: `CMP_MASTER_SPEC.md` §2, §8; `CLAUDE.md` rules 1, 3, 4, 5, 6, 7, 8, 10, 12. This document summarizes the approved model as implemented in CMP-011; it does not restate the spec.

## Scope

CMP-011 is the first *transformation* (rule 6): a controlled, single-step move of a crop batch's identity off its seed-tray carriers (assigned by CMP-009 sowing) and onto new destination carriers, with exact integer plant-count lineage. It amends the CMP-009 `batch_carrier_assignment` shape — adding a typed closing command and a second typed opener — rather than building a parallel model, exactly as CMP-009's own model doc anticipated. Out of scope: repeated/chained transplantation, batch split/merge, new batch creation, stage progression (automatic or otherwise), carrier movement or occupancy changes, capacity configuration, inventory deduction, observations, quality scoring, harvest, packing, QR/labels, frontend, RLS, role-specific authorization, and releasing a transplant-created assignment (only sowing-origin assignments are releasable in CMP-011).

## Assignment origin and release

A `batch_carrier_assignment` now has exactly one opener — `opening_sowing_event_id` (CMP-009) or `opening_transplant_event_id` (CMP-011), enforced by a CHECK constraint — and an optional release, `released_by_transplant_event_id`, present if and only if `released_effective_time` is present. Only a sowing-origin assignment may ever be released (`CHECK (released_by_transplant_event_id IS NULL OR opening_sowing_event_id IS NOT NULL)`); a transplant-created assignment cannot itself be transplanted again in CMP-011. `required_carrier_type_id` on a `workflow_stage` identifies the carrier type a stage-specific operation may *newly assign* — for seeding, sown carriers; for transplanting, destination carriers — it does not retroactively require carriers already active when the batch entered that stage to match. This is why a batch's original seed-tray assignments remain active and untouched while the batch sits in a transplanting-category stage; only a transplant command's destination carriers are checked against it.

## Transplant events, source lines, destination lines, allocations

One `transplant_event` is one command, tied by trigger to the batch's exact active stage run, which must be `transplanting`-category with a configured `required_carrier_type_id`. It carries one or more `transplant_source_lines` (one active, sowing-origin assignment each — `UNIQUE(source_batch_carrier_assignment_id)` globally, so a given assignment can be the source of at most one transplant, ever) and one or more `transplant_destination_lines` (one carrier each, freshly assigned — `UNIQUE(destination_batch_carrier_assignment_id)` globally). `transplant_allocations` are the many-to-many bridge between them, each an integer plant count moving from one source line to one destination line (`UNIQUE(source_line_id, destination_line_id)`).

**Fully-discarded source policy**: a source line may have zero allocations only when `discarded_plant_count == source_plant_count` — a total-loss tray. Every other source line requires at least one allocation; every destination line always requires at least one (`assigned_plant_count > 0` forces it). An event whose sources are all fully discarded is impossible in practice since the schema also requires at least one destination line and one allocation.

## Reconciliation

Per source line: `discarded_plant_count + sum(its allocations) == source_plant_count`. Per destination line: `sum(its allocations) == assigned_plant_count`. Per event (rule 8): `total_source_plant_count == total_destination_plant_count + total_discarded_plant_count`. No difference is ever hidden — a mismatch anywhere rejects the whole command.

Reconciliation is validated twice: in-memory before any write, and again by a single database function (`enforce_transplant_reconciliation`) attached to **six** `DEFERRABLE INITIALLY DEFERRED` constraint triggers — `AFTER INSERT` on `transplant_events`, `transplant_source_lines`, `transplant_destination_lines`, and `transplant_allocations`; `AFTER INSERT` on `batch_carrier_assignments` when a transplant-origin opener is set; `AFTER UPDATE` on `batch_carrier_assignments` when a release transitions from unset to set. All six resolve to the same affected event and re-validate its *complete* state at real transaction commit, not at each individual insert — this is what defends against a later, separate transaction inserting an extra row (e.g. a stray allocation) against an already-committed event via direct SQL.

## Locking and idempotency

Locking order: the crop batch row, its active stage run, then all source and destination carriers together in one sorted-UUID set (not two separately ordered groups, to avoid deadlocking against a concurrent command touching an overlapping carrier set from the other side), then the source assignments in sorted-UUID order. `UNIQUE(tenant_id, client_command_id)` on `transplant_events`; the fingerprint covers tenant, farm, actor, batch, UTC effective time, normalized note, and the source/destination/allocation lines sorted by their stable domain identifiers (`source_assignment_id`, `destination_carrier_id`) — it excludes the active stage-run id and current assignment/carrier state, so a retry still returns the original event after the batch has progressed or carriers have changed state.

## Database protection

Composite foreign keys (`(tenant_id, farm_id, batch_id, id)`-style, matching CMP-008/009/010) prove tenant/farm/batch consistency structurally for all four new tables, including 4-column FKs from `transplant_allocations` to its source/destination lines that structurally prove same-event membership. The CMP-009 `batch_carrier_assignments` insert-integrity and no-update triggers/functions are left completely untouched in the database; only their trigger *attachments* were dropped and replaced with new CMP-011-named triggers/functions (`enforce_batch_carrier_assignment_origin_insert_integrity`, branching on whichever opener is set; `enforce_batch_carrier_assignment_closure_only`, allowing exactly the release fields to move once). This means a downgrade restores CMP-009's original behavior by simply re-attaching a trigger to the original function — zero risk of textual divergence. All four new tables are append-only/no-delete (`reject_append_only_mutation`, shared with CMP-008/009/010).

## Downgrade guard

Downgrading past CMP-011 is destructive to production history by nature (it would drop the assignment-origin/release columns and the four transplant tables). The migration's `downgrade()` therefore queries, before any DDL, for the existence of any `transplant_events` row, any `batch_carrier_assignment` with a transplant-origin opener or release, or any `workflow_stage` with `stage_category = 'transplanting'`; if any exist, it raises `RuntimeError` and aborts with zero schema change. Only on a database that has never run a transplant and never configured a transplanting-category stage does downgrade proceed, fully restoring the exact CMP-009 shape.

## Deferred

Repeated/chained transplantation, releasing a transplant-created assignment, batch split/merge, new batch creation, stage auto-progression, carrier movement/occupancy, capacity enforcement, inventory, quality-hold-blocks-transplantation (holds remain a stage-progression lock only), harvest, packing, QR identities, labels, frontend, RLS, role-specific authorization.
