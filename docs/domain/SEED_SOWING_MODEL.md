# Seed Lot, Sowing, and Initial Carrier Assignment Model

Full detail: `CMP_MASTER_SPEC.md` §2, §8; `CLAUDE.md` rules 1, 3, 4, 5, 7, 10, 12. This document summarizes the approved model as implemented in CMP-009; it does not restate the spec.

## Scope

CMP-009 connects an active, seeding-stage crop batch (CMP-008) to its first physical carriers and records where its seed came from. It proves traceability and per-carrier quantities only — no seed-inventory balance, no capacity, no release/reassignment, no occupancy or movement. Sowing never creates, closes, or infers a CMP-006 occupancy row; assignment answers "what crop batch does this carrier contain", occupancy answers "where is it physically" — the two never intersect in this ticket.

## Seed lots

A `seed_lot` is tenant- and farm-owned identity for a supplier seed source: crop, variety, a normalized tenant-wide-unique code, optional supplier name/lot reference, optional received/expiry dates, and `active`/`inactive` status. It carries no quantity-on-hand, cost, or germination-test data — that is deferred to a later input-store ledger ticket. `supplier_lot_reference` is optional: many suppliers never issue one, and the internal `code` already gives identity, so requiring it would force a fabricated value.

## Variety-specific sowing

CMP-007 permits variety-agnostic workflows (`workflows.variety_id` nullable), but a seed lot always identifies one variety. Rather than adding an operational-variety column to `crop_batches`, CMP-009 requires the batch's permanently bound workflow to already carry a non-null, active `variety_id` as a precondition of sowing — checked at sowing time, not creation time. This is the smaller design: it needs no schema change to `crop_batches`, and the batch's variety remains derivable, as it always has been, through `crop_batch → workflow_version → workflow → variety`. A batch whose workflow has no variety restriction simply cannot be sown until re-created against a variety-specific workflow. A sowing line is also rejected if its seed lot's crop or variety differs from the batch's workflow-derived crop/variety — this is what prevents a batch from ever holding two varieties.

## Batch carrier assignment

A `batch_carrier_assignment` is the immutable-history record answering "what batch does this carrier hold right now". One carrier has at most one active (`released_effective_time IS NULL`) assignment at a time, enforced by a partial unique index on `(tenant_id, carrier_id)`; one batch may have many active carriers. `released_effective_time` is a reserved nullable column: no CMP-009 command ever populates it, and every UPDATE/DELETE on the table is rejected outright by a DB trigger — there is no closure logic yet. A future release/transformation ticket adds a typed closing-command reference and replaces this trigger with a closure-only variant, so that migration is additive rather than a rewrite of already-populated history.

## Sowing events and lines

One `sowing_event` is one command: it is tied, by trigger, to the exact `batch_stage_run` that was active and unclosed at the moment it executed, and that run's stage must be `seeding`-category with a configured `required_carrier_type_id` — CMP-009 never hardcodes a carrier type code; the requirement is read from `workflow_stages.required_carrier_type_id` (already present since CMP-007). Each event carries one or more `sowing_event_lines`, one row per carrier: seed-lot id, sown-site count, seed count (`seed_count >= sown_site_count > 0`), and exactly one line per assignment (`UNIQUE(batch_carrier_assignment_id)`). A batch may be sown multiple times as separate carriers become ready, but the same carrier can never be sown twice while its assignment stays active. A command is capped at 500 lines — a technical API limit, not a greenhouse-capacity statement (carrier capacity is not configured yet).

## Idempotency and concurrency

`UNIQUE(tenant_id, client_command_id)` on `sowing_events`. The fingerprint covers tenant, farm, actor, batch, UTC effective time, normalized note, and lines sorted by carrier id — it deliberately excludes the active stage-run id, current carrier-assignment state, seed-lot status, and workflow state, all of which can legitimately change between the original command and a retry; a retry must still return the original event after the batch has progressed, carriers are assigned, or a seed lot goes inactive. Locking order for a genuinely new command: the batch row, its active stage run, then carriers, then seed lots — each of the latter two in sorted-UUID order, preventing deadlocks across overlapping carrier lists and letting a losing concurrent duplicate resolve as an idempotent replay rather than a raw constraint failure.

## Farm-local date validation

Seed-lot `received_date`/`expiry_date` are farm-local calendar dates, not UTC instants. Sowing converts the UTC `effective_time` into the farm's IANA timezone (`farms.timezone`) and compares the resulting local date — inclusive on both bounds — rather than comparing a UTC date directly against a farm-local date, which would misclassify sowings near local midnight.

## Database protection

Composite foreign keys prove tenant/farm/batch consistency structurally, reusing CMP-008's `(tenant_id, farm_id, batch_id, id)`-style composite-FK pattern (now also applied to `batch_stage_runs` and `carriers`, added as additive constraints). Triggers cover the cross-row rules a CHECK cannot express: a `sowing_event`'s stage run must actually be the batch's own currently-open, seeding-category run with a configured carrier type; a `batch_carrier_assignment` must match its opening event's batch/stage-run/effective-time and the carrier's type must equal the stage's required type; a `sowing_event_line`'s assignment must belong to the same event and carrier, and its seed lot's crop/variety must match the batch's workflow-derived crop/variety. Append-only/no-delete triggers (`reject_append_only_mutation`, `reject_hard_delete`, both shared with CMP-008) protect all four new tables.

## Deferred

Seed inventory balances, material issues, stock deduction, costing, germination observations, carrier-capacity configuration, carrier release, reassignment, transplanting, transformations, quality, harvest, packing, QR identities, labels, frontend, RLS, role-specific authorization.

Carrier release/reassignment (transplanting, CMP-011) and split/merge (CMP-012) are both now implemented — see `docs/domain/TRANSPLANTATION_MODEL.md` and `docs/domain/BATCH_DERIVATION_MODEL.md`. Both amend the `batch_carrier_assignment` shape described here (adding typed openers/releasers) rather than replacing it.
