"""batch carrier population checkpoint

NURSERY-OPS-005A -- introduces the authoritative population/source-accounting
boundary for a transplant-created biological placement (e.g. a Nursery
Cultivation Plate) that is itself later consumed as a Transplant source, the
sibling authority to `seedling_source_checkpoints` for the SeedlingEntry/Seed
Tray lifecycle. See `docs/domain/TRANSPLANTATION_MODEL.md` for the full model
writeup; this docstring summarizes only what the migration itself does.

`SeedlingEntry`/`seedling_source_checkpoints` are UNCHANGED in meaning and
schema -- this is a genuinely separate authority, never a generalization of
that one.

One new table:

`batch_carrier_population_checkpoints` -- immutable, insert-only boundary
marker, one row per `TransplantSourceLine` that consumes a
`BatchCarrierAssignment`-anchored (rather than `SeedlingEntry`-anchored)
biological placement. Chained via `previous_checkpoint_id` to the actual
latest prior checkpoint for the same assignment (or NULL for the first), the
identical structural chain-tip shape `seedling_source_checkpoints` already
uses. A normal (never-restored) assignment needs no row at all until first
consumed -- its opening population is derived structurally, at read time, from
its own `TransplantDestinationLine.assigned_plant_count` (mirrors
`SeedlingEntry.starting_living_seedling_count`'s identical role); a restored
assignment (opened by a Transplant REVERSAL) gets its first checkpoint written
immediately by that REVERSAL, anchored to a REVERSAL-synthesized
`TransplantSourceLine`, exactly mirroring how `seedling_source_checkpoints`
restoration already works. No backfill DML: historical chained consumption of
a Nursery Cultivation Plate could not previously exist (the prior
`SourceAssignmentHasNoSeedlingEntryError` guard made it categorically
impossible), so this table starts empty legitimately, and every
transplant-created destination's opening authority is derived, never stored.

Three existing trigger functions are updated via `CREATE OR REPLACE` (their
own `CREATE TRIGGER` statements, defined in earlier, untouched historical
migrations, keep firing against the new function bodies unchanged) -- mirrors
the exact precedent `c8f1d4a92b6e`/`f4a8c1e93d27` already established:

1. `enforce_transplant_source_line_insert_integrity` -- fires BEFORE the
   checkpoint trigger below, at the moment the `TransplantSourceLine` itself
   is inserted (earlier in the write sequence than any checkpoint). Its
   existing SeedlingEntry-lineage walk is entirely unchanged; only when that
   walk finds NO SeedlingEntry at all does it now check whether the source
   Carrier is `nursery_cultivation_plate`-typed (unconditional rejection
   otherwise, same message as before) and, if so, validate `source_plant_
   count` against the SAME anchor-resolution logic `batch_carrier_population_
   checkpoints`' own trigger uses (structural chain-tip if a checkpoint
   exists, else derived from the assignment's own `TransplantDestinationLine`).

2. `enforce_transplant_reconciliation` -- for a non-REVERSAL transplant event
   (REVERSAL's own structural-only check, added by `f4a8c1e93d27`, is
   unchanged and still returns early before any checkpoint-table logic), the
   "exactly one checkpoint per source line", per-source-line remainder
   reconciliation, event-level total reconciliation, and conditional-release
   checks now count/verify across BOTH `seedling_source_checkpoints` and
   `batch_carrier_population_checkpoints` -- a source line's checkpoint may
   live in either table, never both, and the existing seedling-side queries
   are untouched, only summed alongside a new parallel set for the sibling
   table. Also gains a new `TG_TABLE_NAME = 'batch_carrier_population_
   checkpoints'` dispatch branch, identical in shape to the existing
   `seedling_source_checkpoints` one.

3. `enforce_batch_carrier_assignment_closure_only_v2` -- its release-via-
   transplantation origin check currently requires sowing-origin or
   reversal-restored ancestry (`only sowing-origin or reversal-restored
   source assignments may be released by transplantation`), which would
   reject releasing an ordinary transplant-created destination (e.g. a
   Nursery Cultivation Plate opened by a prior RECORD-kind transplant, not by
   sowing) once NURSERY-OPS-005A allows it to become a Transplant source in
   its own right. Widened to also accept a release backed by an actual
   `batch_carrier_population_checkpoints` row for the exact (assignment,
   releasing event) pair -- tied directly to the authority mechanism itself,
   not to Carrier type, and it is never satisfied by an ordinary
   `production_cultivation_plate` destination, which never gets consulted
   this way at all (the service layer's own eligibility allowlist keeps that
   type out of the Transplant-source path entirely; this trigger only
   widens what a LEGITIMATE 005A-authorized release looks like). No other
   branch of this function changes.

One new trigger function, `enforce_batch_carrier_population_checkpoint_
insert_integrity` (BEFORE INSERT on `batch_carrier_population_checkpoints`)
plus append-only triggers, reusing the existing `reject_append_only_
mutation()` function (not redefined here) -- structurally the same three-
trigger shape `seedling_source_checkpoints` already has, minus the
SeedlingEntry-ownership/lineage-walk checks (no separate "entry" identity
exists for this authority -- the `BatchCarrierAssignment` itself is that
identity, so no lineage walk is needed; each restoration generation owns its
own checkpoint chain, scoped by its own `batch_carrier_assignment_id`).

No changes to `seed_tray`/Seedling source-authority semantics, no Leafy
Production composite API/UI, no `production_cultivation_plate` -> `grow_table`
occupancy compatibility (NURSERY-OPS-005B scope).

Revision ID: 283bad02bb69
Revises: e2a7c9f4b816
Create Date: 2026-08-23 11:12:13.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "283bad02bb69"
down_revision: str | None = "e2a7c9f4b816"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

# =====================================================================
# enforce_transplant_reconciliation -- pre-005A (f4a8c1e93d27) and
# unified-authority-aware (this migration) versions.
# =====================================================================

_PRE_005A_TRANSPLANT_RECONCILIATION_FUNCTION = """
    CREATE OR REPLACE FUNCTION enforce_transplant_reconciliation() RETURNS trigger AS $$
    DECLARE
        v_event_id UUID;
        v_event_kind TEXT;
        v_source_line_count INTEGER;
        v_destination_line_count INTEGER;
        v_allocation_count INTEGER;
        v_checkpoint_count INTEGER;
        v_bad_source_count INTEGER;
        v_bad_destination_count INTEGER;
        v_total_source INTEGER;
        v_total_destination INTEGER;
        v_total_discarded INTEGER;
        v_total_remainder INTEGER;
        v_unreleased_source_count INTEGER;
        v_unopened_destination_count INTEGER;
        v_extra_release_count INTEGER;
        v_remainder_release_count INTEGER;
        v_extra_open_count INTEGER;
        v_event_effective TIMESTAMPTZ;
    BEGIN
        IF TG_TABLE_NAME = 'transplant_events' THEN
            v_event_id := NEW.id;
        ELSIF TG_TABLE_NAME = 'transplant_source_lines' THEN
            v_event_id := NEW.transplant_event_id;
        ELSIF TG_TABLE_NAME = 'transplant_destination_lines' THEN
            v_event_id := NEW.transplant_event_id;
        ELSIF TG_TABLE_NAME = 'transplant_allocations' THEN
            v_event_id := NEW.transplant_event_id;
        ELSIF TG_TABLE_NAME = 'seedling_source_checkpoints' THEN
            SELECT transplant_event_id INTO v_event_id FROM transplant_source_lines WHERE id = NEW.transplant_source_line_id;
        ELSIF TG_TABLE_NAME = 'batch_carrier_assignments' THEN
            IF TG_OP = 'INSERT' THEN
                v_event_id := COALESCE(NEW.opening_transplant_event_id, NEW.opening_transplant_reversal_event_id);
            ELSE
                v_event_id := NEW.released_by_transplant_event_id;
            END IF;
        END IF;

        IF v_event_id IS NULL THEN
            RETURN NEW;
        END IF;

        SELECT effective_time, event_kind INTO v_event_effective, v_event_kind FROM transplant_events WHERE id = v_event_id;

        SELECT count(*) INTO v_source_line_count FROM transplant_source_lines WHERE transplant_event_id = v_event_id;
        SELECT count(*) INTO v_destination_line_count FROM transplant_destination_lines WHERE transplant_event_id = v_event_id;
        SELECT count(*) INTO v_allocation_count FROM transplant_allocations WHERE transplant_event_id = v_event_id;

        IF v_event_kind = 'REVERSAL' THEN
            IF v_source_line_count = 0 THEN
                RAISE EXCEPTION 'reversal transplant event % has no source lines', v_event_id;
            END IF;
            IF v_destination_line_count <> 0 THEN
                RAISE EXCEPTION 'reversal transplant event % must have zero destination lines', v_event_id;
            END IF;
            IF v_allocation_count <> 0 THEN
                RAISE EXCEPTION 'reversal transplant event % must have zero allocations', v_event_id;
            END IF;
            RETURN NEW;
        END IF;

        SELECT count(*) INTO v_checkpoint_count
        FROM seedling_source_checkpoints sc
        JOIN transplant_source_lines sl ON sl.id = sc.transplant_source_line_id
        WHERE sl.transplant_event_id = v_event_id;

        IF v_source_line_count = 0 THEN
            RAISE EXCEPTION 'transplant event % has no source lines', v_event_id;
        END IF;
        IF v_destination_line_count = 0 THEN
            RAISE EXCEPTION 'transplant event % has no destination lines', v_event_id;
        END IF;
        IF v_allocation_count = 0 THEN
            RAISE EXCEPTION 'transplant event % has no allocations', v_event_id;
        END IF;
        IF v_checkpoint_count <> v_source_line_count THEN
            RAISE EXCEPTION 'transplant event % does not have exactly one checkpoint per source line', v_event_id;
        END IF;

        SELECT count(*) INTO v_bad_source_count
        FROM transplant_source_lines sl
        JOIN seedling_source_checkpoints sc ON sc.transplant_source_line_id = sl.id
        WHERE sl.transplant_event_id = v_event_id
          AND sl.discarded_plant_count + sc.remainder_after + COALESCE(
              (SELECT sum(a.allocated_plant_count) FROM transplant_allocations a WHERE a.source_line_id = sl.id), 0
          ) <> sl.source_plant_count;
        IF v_bad_source_count > 0 THEN
            RAISE EXCEPTION 'transplant event % has unreconciled source lines', v_event_id;
        END IF;

        SELECT count(*) INTO v_bad_destination_count
        FROM transplant_destination_lines dl
        WHERE dl.transplant_event_id = v_event_id
          AND COALESCE(
              (SELECT sum(a.allocated_plant_count) FROM transplant_allocations a WHERE a.destination_line_id = dl.id), 0
          ) <> dl.assigned_plant_count;
        IF v_bad_destination_count > 0 THEN
            RAISE EXCEPTION 'transplant event % has unreconciled destination lines', v_event_id;
        END IF;

        SELECT sum(sl.source_plant_count), sum(sl.discarded_plant_count)
        INTO v_total_source, v_total_discarded
        FROM transplant_source_lines sl WHERE sl.transplant_event_id = v_event_id;
        SELECT sum(dl.assigned_plant_count) INTO v_total_destination
        FROM transplant_destination_lines dl WHERE dl.transplant_event_id = v_event_id;
        SELECT sum(sc.remainder_after) INTO v_total_remainder
        FROM seedling_source_checkpoints sc
        JOIN transplant_source_lines sl ON sl.id = sc.transplant_source_line_id
        WHERE sl.transplant_event_id = v_event_id;
        IF v_total_source IS DISTINCT FROM (
            COALESCE(v_total_destination, 0) + COALESCE(v_total_discarded, 0) + COALESCE(v_total_remainder, 0)
        ) THEN
            RAISE EXCEPTION 'transplant event % totals do not reconcile', v_event_id;
        END IF;

        SELECT count(*) INTO v_unreleased_source_count
        FROM transplant_source_lines sl
        JOIN seedling_source_checkpoints sc ON sc.transplant_source_line_id = sl.id
        JOIN batch_carrier_assignments a ON a.id = sl.source_batch_carrier_assignment_id
        WHERE sl.transplant_event_id = v_event_id
          AND sc.remainder_after = 0
          AND (a.released_by_transplant_event_id IS DISTINCT FROM v_event_id
               OR a.released_effective_time IS DISTINCT FROM v_event_effective);
        IF v_unreleased_source_count > 0 THEN
            RAISE EXCEPTION 'transplant event % has a fully-consumed source line whose assignment was not released by this event', v_event_id;
        END IF;

        SELECT count(*) INTO v_remainder_release_count
        FROM transplant_source_lines sl
        JOIN seedling_source_checkpoints sc ON sc.transplant_source_line_id = sl.id
        JOIN batch_carrier_assignments a ON a.id = sl.source_batch_carrier_assignment_id
        WHERE sl.transplant_event_id = v_event_id
          AND sc.remainder_after > 0
          AND a.released_by_transplant_event_id = v_event_id;
        IF v_remainder_release_count > 0 THEN
            RAISE EXCEPTION 'transplant event % released a source assignment that still has remainder', v_event_id;
        END IF;

        SELECT count(*) INTO v_extra_release_count
        FROM batch_carrier_assignments a
        WHERE a.released_by_transplant_event_id = v_event_id
          AND NOT EXISTS (
              SELECT 1 FROM transplant_source_lines sl
              WHERE sl.source_batch_carrier_assignment_id = a.id AND sl.transplant_event_id = v_event_id
          );
        IF v_extra_release_count > 0 THEN
            RAISE EXCEPTION 'transplant event % released an assignment without a matching source line', v_event_id;
        END IF;

        SELECT count(*) INTO v_unopened_destination_count
        FROM transplant_destination_lines dl
        JOIN batch_carrier_assignments a ON a.id = dl.destination_batch_carrier_assignment_id
        WHERE dl.transplant_event_id = v_event_id
          AND (a.opening_transplant_event_id IS DISTINCT FROM v_event_id
               OR a.assigned_effective_time IS DISTINCT FROM v_event_effective);
        IF v_unopened_destination_count > 0 THEN
            RAISE EXCEPTION 'transplant event % has a destination line whose assignment was not opened by this event', v_event_id;
        END IF;

        SELECT count(*) INTO v_extra_open_count
        FROM batch_carrier_assignments a
        WHERE a.opening_transplant_event_id = v_event_id
          AND NOT EXISTS (
              SELECT 1 FROM transplant_destination_lines dl
              WHERE dl.destination_batch_carrier_assignment_id = a.id AND dl.transplant_event_id = v_event_id
          );
        IF v_extra_open_count > 0 THEN
            RAISE EXCEPTION 'transplant event % opened an assignment without a matching destination line', v_event_id;
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

_UNIFIED_AUTHORITY_TRANSPLANT_RECONCILIATION_FUNCTION = """
    CREATE OR REPLACE FUNCTION enforce_transplant_reconciliation() RETURNS trigger AS $$
    DECLARE
        v_event_id UUID;
        v_event_kind TEXT;
        v_source_line_count INTEGER;
        v_destination_line_count INTEGER;
        v_allocation_count INTEGER;
        v_checkpoint_count INTEGER;
        v_population_checkpoint_count INTEGER;
        v_bad_source_count INTEGER;
        v_bad_population_source_count INTEGER;
        v_bad_destination_count INTEGER;
        v_total_source INTEGER;
        v_total_destination INTEGER;
        v_total_discarded INTEGER;
        v_total_remainder INTEGER;
        v_total_population_remainder INTEGER;
        v_unreleased_source_count INTEGER;
        v_unreleased_population_source_count INTEGER;
        v_unopened_destination_count INTEGER;
        v_extra_release_count INTEGER;
        v_remainder_release_count INTEGER;
        v_remainder_population_release_count INTEGER;
        v_extra_open_count INTEGER;
        v_event_effective TIMESTAMPTZ;
    BEGIN
        IF TG_TABLE_NAME = 'transplant_events' THEN
            v_event_id := NEW.id;
        ELSIF TG_TABLE_NAME = 'transplant_source_lines' THEN
            v_event_id := NEW.transplant_event_id;
        ELSIF TG_TABLE_NAME = 'transplant_destination_lines' THEN
            v_event_id := NEW.transplant_event_id;
        ELSIF TG_TABLE_NAME = 'transplant_allocations' THEN
            v_event_id := NEW.transplant_event_id;
        ELSIF TG_TABLE_NAME = 'seedling_source_checkpoints' THEN
            SELECT transplant_event_id INTO v_event_id FROM transplant_source_lines WHERE id = NEW.transplant_source_line_id;
        ELSIF TG_TABLE_NAME = 'batch_carrier_population_checkpoints' THEN
            SELECT transplant_event_id INTO v_event_id FROM transplant_source_lines WHERE id = NEW.transplant_source_line_id;
        ELSIF TG_TABLE_NAME = 'batch_carrier_assignments' THEN
            IF TG_OP = 'INSERT' THEN
                v_event_id := COALESCE(NEW.opening_transplant_event_id, NEW.opening_transplant_reversal_event_id);
            ELSE
                v_event_id := NEW.released_by_transplant_event_id;
            END IF;
        END IF;

        IF v_event_id IS NULL THEN
            RETURN NEW;
        END IF;

        SELECT effective_time, event_kind INTO v_event_effective, v_event_kind FROM transplant_events WHERE id = v_event_id;

        SELECT count(*) INTO v_source_line_count FROM transplant_source_lines WHERE transplant_event_id = v_event_id;
        SELECT count(*) INTO v_destination_line_count FROM transplant_destination_lines WHERE transplant_event_id = v_event_id;
        SELECT count(*) INTO v_allocation_count FROM transplant_allocations WHERE transplant_event_id = v_event_id;

        IF v_event_kind = 'REVERSAL' THEN
            IF v_source_line_count = 0 THEN
                RAISE EXCEPTION 'reversal transplant event % has no source lines', v_event_id;
            END IF;
            IF v_destination_line_count <> 0 THEN
                RAISE EXCEPTION 'reversal transplant event % must have zero destination lines', v_event_id;
            END IF;
            IF v_allocation_count <> 0 THEN
                RAISE EXCEPTION 'reversal transplant event % must have zero allocations', v_event_id;
            END IF;
            RETURN NEW;
        END IF;

        SELECT count(*) INTO v_checkpoint_count
        FROM seedling_source_checkpoints sc
        JOIN transplant_source_lines sl ON sl.id = sc.transplant_source_line_id
        WHERE sl.transplant_event_id = v_event_id;
        -- NURSERY-OPS-005A: a source line's checkpoint may instead live in
        -- the sibling batch_carrier_population_checkpoints table (nursery_
        -- cultivation_plate-backed sources) -- counted separately and
        -- summed below, never a second competing implementation of "one
        -- checkpoint per source line", just the same invariant proven
        -- across both tables.
        SELECT count(*) INTO v_population_checkpoint_count
        FROM batch_carrier_population_checkpoints bc
        JOIN transplant_source_lines sl ON sl.id = bc.transplant_source_line_id
        WHERE sl.transplant_event_id = v_event_id;

        IF v_source_line_count = 0 THEN
            RAISE EXCEPTION 'transplant event % has no source lines', v_event_id;
        END IF;
        IF v_destination_line_count = 0 THEN
            RAISE EXCEPTION 'transplant event % has no destination lines', v_event_id;
        END IF;
        IF v_allocation_count = 0 THEN
            RAISE EXCEPTION 'transplant event % has no allocations', v_event_id;
        END IF;
        IF (v_checkpoint_count + v_population_checkpoint_count) <> v_source_line_count THEN
            RAISE EXCEPTION 'transplant event % does not have exactly one checkpoint per source line', v_event_id;
        END IF;

        SELECT count(*) INTO v_bad_source_count
        FROM transplant_source_lines sl
        JOIN seedling_source_checkpoints sc ON sc.transplant_source_line_id = sl.id
        WHERE sl.transplant_event_id = v_event_id
          AND sl.discarded_plant_count + sc.remainder_after + COALESCE(
              (SELECT sum(a.allocated_plant_count) FROM transplant_allocations a WHERE a.source_line_id = sl.id), 0
          ) <> sl.source_plant_count;
        IF v_bad_source_count > 0 THEN
            RAISE EXCEPTION 'transplant event % has unreconciled source lines', v_event_id;
        END IF;

        SELECT count(*) INTO v_bad_population_source_count
        FROM transplant_source_lines sl
        JOIN batch_carrier_population_checkpoints bc ON bc.transplant_source_line_id = sl.id
        WHERE sl.transplant_event_id = v_event_id
          AND sl.discarded_plant_count + bc.remainder_after + COALESCE(
              (SELECT sum(a.allocated_plant_count) FROM transplant_allocations a WHERE a.source_line_id = sl.id), 0
          ) <> sl.source_plant_count;
        IF v_bad_population_source_count > 0 THEN
            RAISE EXCEPTION 'transplant event % has unreconciled source lines', v_event_id;
        END IF;

        SELECT count(*) INTO v_bad_destination_count
        FROM transplant_destination_lines dl
        WHERE dl.transplant_event_id = v_event_id
          AND COALESCE(
              (SELECT sum(a.allocated_plant_count) FROM transplant_allocations a WHERE a.destination_line_id = dl.id), 0
          ) <> dl.assigned_plant_count;
        IF v_bad_destination_count > 0 THEN
            RAISE EXCEPTION 'transplant event % has unreconciled destination lines', v_event_id;
        END IF;

        SELECT sum(sl.source_plant_count), sum(sl.discarded_plant_count)
        INTO v_total_source, v_total_discarded
        FROM transplant_source_lines sl WHERE sl.transplant_event_id = v_event_id;
        SELECT sum(dl.assigned_plant_count) INTO v_total_destination
        FROM transplant_destination_lines dl WHERE dl.transplant_event_id = v_event_id;
        SELECT sum(sc.remainder_after) INTO v_total_remainder
        FROM seedling_source_checkpoints sc
        JOIN transplant_source_lines sl ON sl.id = sc.transplant_source_line_id
        WHERE sl.transplant_event_id = v_event_id;
        SELECT sum(bc.remainder_after) INTO v_total_population_remainder
        FROM batch_carrier_population_checkpoints bc
        JOIN transplant_source_lines sl ON sl.id = bc.transplant_source_line_id
        WHERE sl.transplant_event_id = v_event_id;
        IF v_total_source IS DISTINCT FROM (
            COALESCE(v_total_destination, 0) + COALESCE(v_total_discarded, 0)
            + COALESCE(v_total_remainder, 0) + COALESCE(v_total_population_remainder, 0)
        ) THEN
            RAISE EXCEPTION 'transplant event % totals do not reconcile', v_event_id;
        END IF;

        SELECT count(*) INTO v_unreleased_source_count
        FROM transplant_source_lines sl
        JOIN seedling_source_checkpoints sc ON sc.transplant_source_line_id = sl.id
        JOIN batch_carrier_assignments a ON a.id = sl.source_batch_carrier_assignment_id
        WHERE sl.transplant_event_id = v_event_id
          AND sc.remainder_after = 0
          AND (a.released_by_transplant_event_id IS DISTINCT FROM v_event_id
               OR a.released_effective_time IS DISTINCT FROM v_event_effective);
        IF v_unreleased_source_count > 0 THEN
            RAISE EXCEPTION 'transplant event % has a fully-consumed source line whose assignment was not released by this event', v_event_id;
        END IF;

        SELECT count(*) INTO v_unreleased_population_source_count
        FROM transplant_source_lines sl
        JOIN batch_carrier_population_checkpoints bc ON bc.transplant_source_line_id = sl.id
        JOIN batch_carrier_assignments a ON a.id = sl.source_batch_carrier_assignment_id
        WHERE sl.transplant_event_id = v_event_id
          AND bc.remainder_after = 0
          AND (a.released_by_transplant_event_id IS DISTINCT FROM v_event_id
               OR a.released_effective_time IS DISTINCT FROM v_event_effective);
        IF v_unreleased_population_source_count > 0 THEN
            RAISE EXCEPTION 'transplant event % has a fully-consumed source line whose assignment was not released by this event', v_event_id;
        END IF;

        SELECT count(*) INTO v_remainder_release_count
        FROM transplant_source_lines sl
        JOIN seedling_source_checkpoints sc ON sc.transplant_source_line_id = sl.id
        JOIN batch_carrier_assignments a ON a.id = sl.source_batch_carrier_assignment_id
        WHERE sl.transplant_event_id = v_event_id
          AND sc.remainder_after > 0
          AND a.released_by_transplant_event_id = v_event_id;
        IF v_remainder_release_count > 0 THEN
            RAISE EXCEPTION 'transplant event % released a source assignment that still has remainder', v_event_id;
        END IF;

        SELECT count(*) INTO v_remainder_population_release_count
        FROM transplant_source_lines sl
        JOIN batch_carrier_population_checkpoints bc ON bc.transplant_source_line_id = sl.id
        JOIN batch_carrier_assignments a ON a.id = sl.source_batch_carrier_assignment_id
        WHERE sl.transplant_event_id = v_event_id
          AND bc.remainder_after > 0
          AND a.released_by_transplant_event_id = v_event_id;
        IF v_remainder_population_release_count > 0 THEN
            RAISE EXCEPTION 'transplant event % released a source assignment that still has remainder', v_event_id;
        END IF;

        SELECT count(*) INTO v_extra_release_count
        FROM batch_carrier_assignments a
        WHERE a.released_by_transplant_event_id = v_event_id
          AND NOT EXISTS (
              SELECT 1 FROM transplant_source_lines sl
              WHERE sl.source_batch_carrier_assignment_id = a.id AND sl.transplant_event_id = v_event_id
          );
        IF v_extra_release_count > 0 THEN
            RAISE EXCEPTION 'transplant event % released an assignment without a matching source line', v_event_id;
        END IF;

        SELECT count(*) INTO v_unopened_destination_count
        FROM transplant_destination_lines dl
        JOIN batch_carrier_assignments a ON a.id = dl.destination_batch_carrier_assignment_id
        WHERE dl.transplant_event_id = v_event_id
          AND (a.opening_transplant_event_id IS DISTINCT FROM v_event_id
               OR a.assigned_effective_time IS DISTINCT FROM v_event_effective);
        IF v_unopened_destination_count > 0 THEN
            RAISE EXCEPTION 'transplant event % has a destination line whose assignment was not opened by this event', v_event_id;
        END IF;

        SELECT count(*) INTO v_extra_open_count
        FROM batch_carrier_assignments a
        WHERE a.opening_transplant_event_id = v_event_id
          AND NOT EXISTS (
              SELECT 1 FROM transplant_destination_lines dl
              WHERE dl.destination_batch_carrier_assignment_id = a.id AND dl.transplant_event_id = v_event_id
          );
        IF v_extra_open_count > 0 THEN
            RAISE EXCEPTION 'transplant event % opened an assignment without a matching destination line', v_event_id;
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

# =====================================================================
# enforce_batch_carrier_assignment_closure_only_v2 -- pre-005A (e2a7c9f4b816)
# and unified-authority-aware (this migration) versions.
# =====================================================================

_PRE_005A_CLOSURE_ONLY_FUNCTION = """
    CREATE OR REPLACE FUNCTION enforce_batch_carrier_assignment_closure_only_v2() RETURNS trigger AS $$
    DECLARE
        v_source_line_carrier UUID;
        v_transplant_batch_id UUID;
        v_transplant_effective TIMESTAMPTZ;
        v_derivation_effective TIMESTAMPTZ;
        v_releaser_kind TEXT;
        v_reverses_id UUID;
        v_disposition_batch_id UUID;
        v_disposition_kind TEXT;
        v_disposition_effective TIMESTAMPTZ;
        v_disposition_entry_id UUID;
        v_entry_root_assignment_id UUID;
        v_in_lineage BOOLEAN;
        v_anchor_value INTEGER;
        v_anchor_time TIMESTAMPTZ;
        v_available_after INTEGER;
    BEGIN
        IF OLD.released_effective_time IS NOT NULL THEN
            RAISE EXCEPTION 'batch_carrier_assignment is already released and cannot be modified';
        END IF;

        IF NEW.tenant_id <> OLD.tenant_id
           OR NEW.farm_id <> OLD.farm_id
           OR NEW.batch_id <> OLD.batch_id
           OR NEW.carrier_id <> OLD.carrier_id
           OR NEW.batch_stage_run_id <> OLD.batch_stage_run_id
           OR NEW.assigned_effective_time <> OLD.assigned_effective_time
           OR NEW.opening_sowing_event_id IS DISTINCT FROM OLD.opening_sowing_event_id
           OR NEW.opening_transplant_event_id IS DISTINCT FROM OLD.opening_transplant_event_id
           OR NEW.opening_batch_derivation_event_id IS DISTINCT FROM OLD.opening_batch_derivation_event_id
           OR NEW.opening_transplant_reversal_event_id IS DISTINCT FROM OLD.opening_transplant_reversal_event_id
           OR NEW.opening_seedling_disposition_reversal_event_id IS DISTINCT FROM OLD.opening_seedling_disposition_reversal_event_id
           OR NEW.restored_from_batch_carrier_assignment_id IS DISTINCT FROM OLD.restored_from_batch_carrier_assignment_id
           OR NEW.actor_user_id <> OLD.actor_user_id
        THEN
            RAISE EXCEPTION 'only released_effective_time and exactly one typed releaser field may change when releasing a batch_carrier_assignment';
        END IF;

        IF NEW.released_effective_time IS NULL
           OR (NEW.released_by_transplant_event_id IS NULL
               AND NEW.released_by_batch_derivation_event_id IS NULL
               AND NEW.released_by_seedling_disposition_event_id IS NULL)
        THEN
            RAISE EXCEPTION 'releasing a batch_carrier_assignment requires released_effective_time and exactly one typed releaser';
        END IF;

        IF NEW.released_by_transplant_event_id IS NOT NULL THEN
            SELECT batch_id, effective_time, event_kind, reverses_transplant_event_id
            INTO v_transplant_batch_id, v_transplant_effective, v_releaser_kind, v_reverses_id
            FROM transplant_events WHERE id = NEW.released_by_transplant_event_id;
            IF v_transplant_batch_id IS NULL THEN
                RAISE EXCEPTION 'releasing transplant event not found';
            END IF;
            IF v_transplant_batch_id <> NEW.batch_id THEN
                RAISE EXCEPTION 'releasing transplant event batch mismatch';
            END IF;
            IF v_transplant_effective <> NEW.released_effective_time THEN
                RAISE EXCEPTION 'released_effective_time must match the releasing transplant event''s effective time';
            END IF;

            IF v_releaser_kind IN ('RECORD', 'REPLACEMENT') THEN
                IF NEW.opening_sowing_event_id IS NULL
                   AND NEW.opening_transplant_reversal_event_id IS NULL
                   AND NEW.opening_seedling_disposition_reversal_event_id IS NULL
                THEN
                    RAISE EXCEPTION 'only sowing-origin or reversal-restored source assignments may be released by transplantation';
                END IF;

                SELECT source_carrier_id INTO v_source_line_carrier
                FROM transplant_source_lines
                WHERE source_batch_carrier_assignment_id = NEW.id
                  AND transplant_event_id = NEW.released_by_transplant_event_id;
                IF v_source_line_carrier IS NULL THEN
                    RAISE EXCEPTION 'no transplant source line found for this assignment and its releasing transplant event';
                END IF;
                IF v_source_line_carrier <> NEW.carrier_id THEN
                    RAISE EXCEPTION 'source line carrier does not match assignment carrier';
                END IF;
            ELSIF v_releaser_kind = 'REVERSAL' THEN
                IF NEW.opening_transplant_event_id IS DISTINCT FROM v_reverses_id THEN
                    RAISE EXCEPTION 'a REVERSAL may only release the destination assignment opened by the exact event it reverses';
                END IF;
            ELSE
                RAISE EXCEPTION 'unrecognized releasing transplant event kind';
            END IF;
        ELSIF NEW.released_by_batch_derivation_event_id IS NOT NULL THEN
            SELECT effective_time INTO v_derivation_effective
            FROM batch_derivation_events WHERE id = NEW.released_by_batch_derivation_event_id;
            IF v_derivation_effective IS NULL THEN
                RAISE EXCEPTION 'releasing batch derivation event not found';
            END IF;
            IF v_derivation_effective <> NEW.released_effective_time THEN
                RAISE EXCEPTION 'released_effective_time must match the releasing derivation event''s effective time';
            END IF;
        ELSE
            SELECT c.batch_id, e.event_kind, e.effective_time, e.seedling_entry_id
            INTO v_disposition_batch_id, v_disposition_kind, v_disposition_effective, v_disposition_entry_id
            FROM seedling_disposition_events e
            JOIN seedling_disposition_commands c ON c.id = e.command_id
            WHERE e.id = NEW.released_by_seedling_disposition_event_id;
            IF v_disposition_entry_id IS NULL THEN
                RAISE EXCEPTION 'releasing seedling disposition event not found';
            END IF;
            IF v_disposition_batch_id <> NEW.batch_id THEN
                RAISE EXCEPTION 'releasing disposition event batch mismatch';
            END IF;
            IF v_disposition_kind <> 'REDUCTION' THEN
                RAISE EXCEPTION 'only a REDUCTION event may release a batch_carrier_assignment';
            END IF;
            IF v_disposition_effective <> NEW.released_effective_time THEN
                RAISE EXCEPTION 'released_effective_time must match the releasing disposition event''s effective time';
            END IF;

            SELECT batch_carrier_assignment_id INTO v_entry_root_assignment_id
            FROM seedling_entries WHERE id = v_disposition_entry_id;

            WITH RECURSIVE lineage AS (
                SELECT id FROM batch_carrier_assignments WHERE id = v_entry_root_assignment_id
                UNION ALL
                SELECT bca.id FROM batch_carrier_assignments bca
                JOIN lineage l ON bca.restored_from_batch_carrier_assignment_id = l.id
            )
            SELECT EXISTS (SELECT 1 FROM lineage WHERE id = NEW.id) INTO v_in_lineage;
            IF NOT v_in_lineage THEN
                RAISE EXCEPTION 'this assignment does not belong to the releasing disposition event''s SeedlingEntry restoration lineage';
            END IF;

            SELECT c.remainder_after, c.effective_time INTO v_anchor_value, v_anchor_time
            FROM seedling_source_checkpoints c
            WHERE c.seedling_entry_id = v_disposition_entry_id
              AND NOT EXISTS (SELECT 1 FROM seedling_source_checkpoints nxt WHERE nxt.previous_checkpoint_id = c.id);
            IF v_anchor_value IS NULL THEN
                SELECT starting_living_seedling_count, effective_time INTO v_anchor_value, v_anchor_time
                FROM seedling_entries WHERE id = v_disposition_entry_id;
            END IF;

            SELECT v_anchor_value + COALESCE(SUM(quantity_delta), 0) INTO v_available_after
            FROM seedling_disposition_events
            WHERE seedling_entry_id = v_disposition_entry_id
              AND effective_time > v_anchor_time AND effective_time <= v_disposition_effective;

            IF v_available_after <> 0 THEN
                RAISE EXCEPTION 'releasing seedling disposition event does not leave source availability at zero (got %)', v_available_after;
            END IF;
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

_UNIFIED_AUTHORITY_CLOSURE_ONLY_FUNCTION = """
    CREATE OR REPLACE FUNCTION enforce_batch_carrier_assignment_closure_only_v2() RETURNS trigger AS $$
    DECLARE
        v_source_line_carrier UUID;
        v_transplant_batch_id UUID;
        v_transplant_effective TIMESTAMPTZ;
        v_derivation_effective TIMESTAMPTZ;
        v_releaser_kind TEXT;
        v_reverses_id UUID;
        v_disposition_batch_id UUID;
        v_disposition_kind TEXT;
        v_disposition_effective TIMESTAMPTZ;
        v_disposition_entry_id UUID;
        v_entry_root_assignment_id UUID;
        v_in_lineage BOOLEAN;
        v_anchor_value INTEGER;
        v_anchor_time TIMESTAMPTZ;
        v_available_after INTEGER;
        v_has_population_checkpoint BOOLEAN;
    BEGIN
        IF OLD.released_effective_time IS NOT NULL THEN
            RAISE EXCEPTION 'batch_carrier_assignment is already released and cannot be modified';
        END IF;

        IF NEW.tenant_id <> OLD.tenant_id
           OR NEW.farm_id <> OLD.farm_id
           OR NEW.batch_id <> OLD.batch_id
           OR NEW.carrier_id <> OLD.carrier_id
           OR NEW.batch_stage_run_id <> OLD.batch_stage_run_id
           OR NEW.assigned_effective_time <> OLD.assigned_effective_time
           OR NEW.opening_sowing_event_id IS DISTINCT FROM OLD.opening_sowing_event_id
           OR NEW.opening_transplant_event_id IS DISTINCT FROM OLD.opening_transplant_event_id
           OR NEW.opening_batch_derivation_event_id IS DISTINCT FROM OLD.opening_batch_derivation_event_id
           OR NEW.opening_transplant_reversal_event_id IS DISTINCT FROM OLD.opening_transplant_reversal_event_id
           OR NEW.opening_seedling_disposition_reversal_event_id IS DISTINCT FROM OLD.opening_seedling_disposition_reversal_event_id
           OR NEW.restored_from_batch_carrier_assignment_id IS DISTINCT FROM OLD.restored_from_batch_carrier_assignment_id
           OR NEW.actor_user_id <> OLD.actor_user_id
        THEN
            RAISE EXCEPTION 'only released_effective_time and exactly one typed releaser field may change when releasing a batch_carrier_assignment';
        END IF;

        IF NEW.released_effective_time IS NULL
           OR (NEW.released_by_transplant_event_id IS NULL
               AND NEW.released_by_batch_derivation_event_id IS NULL
               AND NEW.released_by_seedling_disposition_event_id IS NULL)
        THEN
            RAISE EXCEPTION 'releasing a batch_carrier_assignment requires released_effective_time and exactly one typed releaser';
        END IF;

        IF NEW.released_by_transplant_event_id IS NOT NULL THEN
            SELECT batch_id, effective_time, event_kind, reverses_transplant_event_id
            INTO v_transplant_batch_id, v_transplant_effective, v_releaser_kind, v_reverses_id
            FROM transplant_events WHERE id = NEW.released_by_transplant_event_id;
            IF v_transplant_batch_id IS NULL THEN
                RAISE EXCEPTION 'releasing transplant event not found';
            END IF;
            IF v_transplant_batch_id <> NEW.batch_id THEN
                RAISE EXCEPTION 'releasing transplant event batch mismatch';
            END IF;
            IF v_transplant_effective <> NEW.released_effective_time THEN
                RAISE EXCEPTION 'released_effective_time must match the releasing transplant event''s effective time';
            END IF;

            IF v_releaser_kind IN ('RECORD', 'REPLACEMENT') THEN
                -- NURSERY-OPS-005A: an ordinary transplant-created
                -- destination (opening_transplant_event_id) is now ALSO a
                -- legitimate origin for release-by-transplantation, when
                -- (and only when) an actual batch_carrier_population_
                -- checkpoints row backs this exact (assignment, releasing
                -- event) pair -- tied directly to the authority mechanism
                -- itself, never to Carrier type. A production_cultivation_
                -- plate destination, or any other transplant-created
                -- destination the service layer never allows to become a
                -- Transplant source, can never satisfy this (no such
                -- checkpoint row could ever exist for it).
                SELECT EXISTS (
                    SELECT 1 FROM batch_carrier_population_checkpoints bc
                    JOIN transplant_source_lines sl ON sl.id = bc.transplant_source_line_id
                    WHERE bc.batch_carrier_assignment_id = NEW.id
                      AND sl.transplant_event_id = NEW.released_by_transplant_event_id
                ) INTO v_has_population_checkpoint;

                IF NEW.opening_sowing_event_id IS NULL
                   AND NEW.opening_transplant_reversal_event_id IS NULL
                   AND NEW.opening_seedling_disposition_reversal_event_id IS NULL
                   AND NOT v_has_population_checkpoint
                THEN
                    RAISE EXCEPTION 'only sowing-origin, reversal-restored, or batch-carrier-population-authority source assignments may be released by transplantation';
                END IF;

                SELECT source_carrier_id INTO v_source_line_carrier
                FROM transplant_source_lines
                WHERE source_batch_carrier_assignment_id = NEW.id
                  AND transplant_event_id = NEW.released_by_transplant_event_id;
                IF v_source_line_carrier IS NULL THEN
                    RAISE EXCEPTION 'no transplant source line found for this assignment and its releasing transplant event';
                END IF;
                IF v_source_line_carrier <> NEW.carrier_id THEN
                    RAISE EXCEPTION 'source line carrier does not match assignment carrier';
                END IF;
            ELSIF v_releaser_kind = 'REVERSAL' THEN
                IF NEW.opening_transplant_event_id IS DISTINCT FROM v_reverses_id THEN
                    RAISE EXCEPTION 'a REVERSAL may only release the destination assignment opened by the exact event it reverses';
                END IF;
            ELSE
                RAISE EXCEPTION 'unrecognized releasing transplant event kind';
            END IF;
        ELSIF NEW.released_by_batch_derivation_event_id IS NOT NULL THEN
            SELECT effective_time INTO v_derivation_effective
            FROM batch_derivation_events WHERE id = NEW.released_by_batch_derivation_event_id;
            IF v_derivation_effective IS NULL THEN
                RAISE EXCEPTION 'releasing batch derivation event not found';
            END IF;
            IF v_derivation_effective <> NEW.released_effective_time THEN
                RAISE EXCEPTION 'released_effective_time must match the releasing derivation event''s effective time';
            END IF;
        ELSE
            SELECT c.batch_id, e.event_kind, e.effective_time, e.seedling_entry_id
            INTO v_disposition_batch_id, v_disposition_kind, v_disposition_effective, v_disposition_entry_id
            FROM seedling_disposition_events e
            JOIN seedling_disposition_commands c ON c.id = e.command_id
            WHERE e.id = NEW.released_by_seedling_disposition_event_id;
            IF v_disposition_entry_id IS NULL THEN
                RAISE EXCEPTION 'releasing seedling disposition event not found';
            END IF;
            IF v_disposition_batch_id <> NEW.batch_id THEN
                RAISE EXCEPTION 'releasing disposition event batch mismatch';
            END IF;
            IF v_disposition_kind <> 'REDUCTION' THEN
                RAISE EXCEPTION 'only a REDUCTION event may release a batch_carrier_assignment';
            END IF;
            IF v_disposition_effective <> NEW.released_effective_time THEN
                RAISE EXCEPTION 'released_effective_time must match the releasing disposition event''s effective time';
            END IF;

            SELECT batch_carrier_assignment_id INTO v_entry_root_assignment_id
            FROM seedling_entries WHERE id = v_disposition_entry_id;

            WITH RECURSIVE lineage AS (
                SELECT id FROM batch_carrier_assignments WHERE id = v_entry_root_assignment_id
                UNION ALL
                SELECT bca.id FROM batch_carrier_assignments bca
                JOIN lineage l ON bca.restored_from_batch_carrier_assignment_id = l.id
            )
            SELECT EXISTS (SELECT 1 FROM lineage WHERE id = NEW.id) INTO v_in_lineage;
            IF NOT v_in_lineage THEN
                RAISE EXCEPTION 'this assignment does not belong to the releasing disposition event''s SeedlingEntry restoration lineage';
            END IF;

            SELECT c.remainder_after, c.effective_time INTO v_anchor_value, v_anchor_time
            FROM seedling_source_checkpoints c
            WHERE c.seedling_entry_id = v_disposition_entry_id
              AND NOT EXISTS (SELECT 1 FROM seedling_source_checkpoints nxt WHERE nxt.previous_checkpoint_id = c.id);
            IF v_anchor_value IS NULL THEN
                SELECT starting_living_seedling_count, effective_time INTO v_anchor_value, v_anchor_time
                FROM seedling_entries WHERE id = v_disposition_entry_id;
            END IF;

            SELECT v_anchor_value + COALESCE(SUM(quantity_delta), 0) INTO v_available_after
            FROM seedling_disposition_events
            WHERE seedling_entry_id = v_disposition_entry_id
              AND effective_time > v_anchor_time AND effective_time <= v_disposition_effective;

            IF v_available_after <> 0 THEN
                RAISE EXCEPTION 'releasing seedling disposition event does not leave source availability at zero (got %)', v_available_after;
            END IF;
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

# =====================================================================
# enforce_transplant_source_line_insert_integrity -- pre-005A (f4a8c1e93d27)
# and unified-authority-aware (this migration) versions. Fires BEFORE
# enforce_batch_carrier_population_checkpoint_insert_integrity ever runs
# (it validates the TransplantSourceLine itself, inserted earlier in the
# same write sequence) -- unconditionally required a SeedlingEntry
# anywhere in the source assignment's own restoration lineage, which
# would reject every nursery_cultivation_plate-backed source outright
# before NURSERY-OPS-005A's own new checkpoint table is ever reached.
# =====================================================================

_PRE_005A_SOURCE_LINE_INTEGRITY_FUNCTION = """
    CREATE OR REPLACE FUNCTION enforce_transplant_source_line_insert_integrity() RETURNS trigger AS $$
    DECLARE
        v_event_batch_id UUID;
        v_event_effective TIMESTAMPTZ;
        v_event_kind TEXT;
        v_assignment_batch_id UUID;
        v_assignment_carrier UUID;
        v_assignment_released TIMESTAMPTZ;
        v_entry_id UUID;
        v_entry_starting INTEGER;
        v_entry_effective TIMESTAMPTZ;
        v_anchor_value INTEGER;
        v_anchor_time TIMESTAMPTZ;
        v_has_checkpoint BOOLEAN;
        v_latest_disposition TIMESTAMPTZ;
        v_delta_sum INTEGER;
        v_available_before INTEGER;
        v_walk_id UUID;
        v_hops INTEGER;
    BEGIN
        SELECT batch_id, effective_time, event_kind INTO v_event_batch_id, v_event_effective, v_event_kind
        FROM transplant_events WHERE id = NEW.transplant_event_id;

        SELECT batch_id, carrier_id, released_effective_time
        INTO v_assignment_batch_id, v_assignment_carrier, v_assignment_released
        FROM batch_carrier_assignments WHERE id = NEW.source_batch_carrier_assignment_id;
        IF v_assignment_batch_id IS NULL THEN
            RAISE EXCEPTION 'source assignment not found';
        END IF;
        IF v_assignment_batch_id <> v_event_batch_id THEN
            RAISE EXCEPTION 'source assignment does not belong to this transplant event''s batch';
        END IF;
        IF v_assignment_carrier <> NEW.source_carrier_id THEN
            RAISE EXCEPTION 'source carrier does not match assignment carrier';
        END IF;
        IF v_assignment_released IS NOT NULL THEN
            RAISE EXCEPTION 'source assignment is already released';
        END IF;

        v_walk_id := NEW.source_batch_carrier_assignment_id;
        v_hops := 0;
        v_entry_id := NULL;
        LOOP
            SELECT id, starting_living_seedling_count, effective_time
            INTO v_entry_id, v_entry_starting, v_entry_effective
            FROM seedling_entries WHERE batch_carrier_assignment_id = v_walk_id;
            EXIT WHEN v_entry_id IS NOT NULL;
            v_hops := v_hops + 1;
            IF v_hops > 50 THEN
                RAISE EXCEPTION 'restoration lineage exceeds maximum depth for assignment %', NEW.source_batch_carrier_assignment_id;
            END IF;
            SELECT restored_from_batch_carrier_assignment_id INTO v_walk_id
            FROM batch_carrier_assignments WHERE id = v_walk_id;
            EXIT WHEN v_walk_id IS NULL;
        END LOOP;
        IF v_entry_id IS NULL THEN
            RAISE EXCEPTION 'source assignment has no Seedling biological entry; modern transplant requires a SeedlingEntry-anchored source';
        END IF;

        IF v_event_kind = 'REVERSAL' THEN
            RETURN NEW;
        END IF;

        SELECT c.remainder_after, c.effective_time INTO v_anchor_value, v_anchor_time
        FROM seedling_source_checkpoints c
        WHERE c.seedling_entry_id = v_entry_id
          AND NOT EXISTS (SELECT 1 FROM seedling_source_checkpoints nxt WHERE nxt.previous_checkpoint_id = c.id);
        v_has_checkpoint := v_anchor_value IS NOT NULL;
        IF NOT v_has_checkpoint THEN
            v_anchor_value := v_entry_starting;
            v_anchor_time := v_entry_effective;
        END IF;

        IF v_has_checkpoint THEN
            IF v_event_effective < v_anchor_time THEN
                RAISE EXCEPTION 'transplant effective_time must not precede the previous checkpoint''s own effective_time';
            ELSIF v_event_effective = v_anchor_time THEN
                IF v_event_kind <> 'REPLACEMENT' THEN
                    RAISE EXCEPTION 'transplant effective_time must be strictly greater than the previous checkpoint''s own effective_time';
                END IF;
            END IF;
        ELSE
            IF v_event_effective < v_anchor_time THEN
                RAISE EXCEPTION 'transplant effective_time precedes the SeedlingEntry''s own effective_time';
            END IF;
        END IF;

        SELECT MAX(effective_time) INTO v_latest_disposition
        FROM seedling_disposition_events
        WHERE seedling_entry_id = v_entry_id AND effective_time > v_anchor_time;
        IF v_latest_disposition IS NOT NULL AND v_event_effective < v_latest_disposition THEN
            RAISE EXCEPTION 'transplant effective_time precedes a disposition already recorded in the currently-open balance window';
        END IF;

        SELECT COALESCE(SUM(quantity_delta), 0) INTO v_delta_sum
        FROM seedling_disposition_events
        WHERE seedling_entry_id = v_entry_id
          AND effective_time > v_anchor_time AND effective_time <= v_event_effective;
        v_available_before := v_anchor_value + v_delta_sum;

        IF NEW.source_plant_count <> v_available_before THEN
            RAISE EXCEPTION 'source_plant_count does not match the authoritative server-derived source availability';
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

_UNIFIED_AUTHORITY_SOURCE_LINE_INTEGRITY_FUNCTION = """
    CREATE OR REPLACE FUNCTION enforce_transplant_source_line_insert_integrity() RETURNS trigger AS $$
    DECLARE
        v_event_batch_id UUID;
        v_event_effective TIMESTAMPTZ;
        v_event_kind TEXT;
        v_assignment_batch_id UUID;
        v_assignment_carrier UUID;
        v_assignment_released TIMESTAMPTZ;
        v_carrier_type_code TEXT;
        v_entry_id UUID;
        v_entry_starting INTEGER;
        v_entry_effective TIMESTAMPTZ;
        v_anchor_value INTEGER;
        v_anchor_time TIMESTAMPTZ;
        v_has_checkpoint BOOLEAN;
        v_latest_disposition TIMESTAMPTZ;
        v_delta_sum INTEGER;
        v_available_before INTEGER;
        v_walk_id UUID;
        v_hops INTEGER;
    BEGIN
        SELECT batch_id, effective_time, event_kind INTO v_event_batch_id, v_event_effective, v_event_kind
        FROM transplant_events WHERE id = NEW.transplant_event_id;

        SELECT batch_id, carrier_id, released_effective_time
        INTO v_assignment_batch_id, v_assignment_carrier, v_assignment_released
        FROM batch_carrier_assignments WHERE id = NEW.source_batch_carrier_assignment_id;
        IF v_assignment_batch_id IS NULL THEN
            RAISE EXCEPTION 'source assignment not found';
        END IF;
        IF v_assignment_batch_id <> v_event_batch_id THEN
            RAISE EXCEPTION 'source assignment does not belong to this transplant event''s batch';
        END IF;
        IF v_assignment_carrier <> NEW.source_carrier_id THEN
            RAISE EXCEPTION 'source carrier does not match assignment carrier';
        END IF;
        IF v_assignment_released IS NOT NULL THEN
            RAISE EXCEPTION 'source assignment is already released';
        END IF;

        -- Resolve the SeedlingEntry via the existing bounded backward
        -- restoration-lineage walk, UNCHANGED.
        v_walk_id := NEW.source_batch_carrier_assignment_id;
        v_hops := 0;
        v_entry_id := NULL;
        LOOP
            SELECT id, starting_living_seedling_count, effective_time
            INTO v_entry_id, v_entry_starting, v_entry_effective
            FROM seedling_entries WHERE batch_carrier_assignment_id = v_walk_id;
            EXIT WHEN v_entry_id IS NOT NULL;
            v_hops := v_hops + 1;
            IF v_hops > 50 THEN
                RAISE EXCEPTION 'restoration lineage exceeds maximum depth for assignment %', NEW.source_batch_carrier_assignment_id;
            END IF;
            SELECT restored_from_batch_carrier_assignment_id INTO v_walk_id
            FROM batch_carrier_assignments WHERE id = v_walk_id;
            EXIT WHEN v_walk_id IS NULL;
        END LOOP;

        IF v_entry_id IS NOT NULL THEN
            -- Existing seed_tray/SeedlingEntry path -- entirely unchanged.
            IF v_event_kind = 'REVERSAL' THEN
                RETURN NEW;
            END IF;

            SELECT c.remainder_after, c.effective_time INTO v_anchor_value, v_anchor_time
            FROM seedling_source_checkpoints c
            WHERE c.seedling_entry_id = v_entry_id
              AND NOT EXISTS (SELECT 1 FROM seedling_source_checkpoints nxt WHERE nxt.previous_checkpoint_id = c.id);
            v_has_checkpoint := v_anchor_value IS NOT NULL;
            IF NOT v_has_checkpoint THEN
                v_anchor_value := v_entry_starting;
                v_anchor_time := v_entry_effective;
            END IF;

            IF v_has_checkpoint THEN
                IF v_event_effective < v_anchor_time THEN
                    RAISE EXCEPTION 'transplant effective_time must not precede the previous checkpoint''s own effective_time';
                ELSIF v_event_effective = v_anchor_time THEN
                    IF v_event_kind <> 'REPLACEMENT' THEN
                        RAISE EXCEPTION 'transplant effective_time must be strictly greater than the previous checkpoint''s own effective_time';
                    END IF;
                END IF;
            ELSE
                IF v_event_effective < v_anchor_time THEN
                    RAISE EXCEPTION 'transplant effective_time precedes the SeedlingEntry''s own effective_time';
                END IF;
            END IF;

            SELECT MAX(effective_time) INTO v_latest_disposition
            FROM seedling_disposition_events
            WHERE seedling_entry_id = v_entry_id AND effective_time > v_anchor_time;
            IF v_latest_disposition IS NOT NULL AND v_event_effective < v_latest_disposition THEN
                RAISE EXCEPTION 'transplant effective_time precedes a disposition already recorded in the currently-open balance window';
            END IF;

            SELECT COALESCE(SUM(quantity_delta), 0) INTO v_delta_sum
            FROM seedling_disposition_events
            WHERE seedling_entry_id = v_entry_id
              AND effective_time > v_anchor_time AND effective_time <= v_event_effective;
            v_available_before := v_anchor_value + v_delta_sum;

            IF NEW.source_plant_count <> v_available_before THEN
                RAISE EXCEPTION 'source_plant_count does not match the authoritative server-derived source availability';
            END IF;

            RETURN NEW;
        END IF;

        -- NURSERY-OPS-005A: no SeedlingEntry anywhere in this assignment's
        -- own restoration lineage -- the only other currently-supported
        -- source authority is BatchCarrierAssignment/BatchCarrierPopulation
        -- Checkpoint, eligible only for a nursery_cultivation_plate-typed
        -- Carrier. Any other Carrier type is rejected with the SAME message
        -- as before -- never silently accepted.
        SELECT ct.code INTO v_carrier_type_code
        FROM carriers c JOIN carrier_types ct ON ct.id = c.carrier_type_id
        WHERE c.id = v_assignment_carrier;
        IF v_carrier_type_code IS DISTINCT FROM 'nursery_cultivation_plate' THEN
            RAISE EXCEPTION 'source assignment has no Seedling biological entry; modern transplant requires a SeedlingEntry-anchored source';
        END IF;

        IF v_event_kind = 'REVERSAL' THEN
            RETURN NEW;
        END IF;

        SELECT c.remainder_after, c.effective_time INTO v_anchor_value, v_anchor_time
        FROM batch_carrier_population_checkpoints c
        WHERE c.batch_carrier_assignment_id = NEW.source_batch_carrier_assignment_id
          AND NOT EXISTS (SELECT 1 FROM batch_carrier_population_checkpoints nxt WHERE nxt.previous_checkpoint_id = c.id);
        v_has_checkpoint := v_anchor_value IS NOT NULL;
        IF NOT v_has_checkpoint THEN
            SELECT dl.assigned_plant_count, te.effective_time INTO v_anchor_value, v_anchor_time
            FROM transplant_destination_lines dl
            JOIN transplant_events te ON te.id = dl.transplant_event_id
            WHERE dl.destination_batch_carrier_assignment_id = NEW.source_batch_carrier_assignment_id;
            IF v_anchor_value IS NULL THEN
                RAISE EXCEPTION 'nursery_cultivation_plate source assignment has no BatchCarrierPopulationCheckpoint and no TransplantDestinationLine of its own';
            END IF;
        END IF;

        IF v_has_checkpoint THEN
            IF v_event_effective < v_anchor_time THEN
                RAISE EXCEPTION 'transplant effective_time must not precede the previous checkpoint''s own effective_time';
            ELSIF v_event_effective = v_anchor_time THEN
                IF v_event_kind <> 'REPLACEMENT' THEN
                    RAISE EXCEPTION 'transplant effective_time must be strictly greater than the previous checkpoint''s own effective_time';
                END IF;
            END IF;
        ELSE
            IF v_event_effective < v_anchor_time THEN
                RAISE EXCEPTION 'transplant effective_time precedes the destination line''s own transplant event effective_time';
            END IF;
        END IF;

        -- No disposition-style delta ledger exists for this authority in
        -- NURSERY-OPS-005A's scope -- available IS the anchor value.
        IF NEW.source_plant_count <> v_anchor_value THEN
            RAISE EXCEPTION 'source_plant_count does not match the authoritative server-derived source availability';
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

# =====================================================================
# batch_carrier_population_checkpoints insert integrity (new) -- mirrors
# enforce_seedling_source_checkpoint_insert_integrity's structural shape
# exactly, minus the SeedlingEntry-ownership/restoration-lineage-walk
# section (no separate "entry" identity exists for this authority).
# =====================================================================

_POPULATION_CHECKPOINT_INTEGRITY_FUNCTION = """
    CREATE FUNCTION enforce_batch_carrier_population_checkpoint_insert_integrity() RETURNS trigger AS $$
    DECLARE
        v_line_tenant_id UUID;
        v_line_farm_id UUID;
        v_line_event_id UUID;
        v_line_assignment_id UUID;
        v_line_available INTEGER;
        v_line_discarded INTEGER;
        v_event_effective TIMESTAMPTZ;
        v_event_batch_id UUID;
        v_new_event_kind TEXT;
        v_assignment_tenant_id UUID;
        v_assignment_farm_id UUID;
        v_assignment_batch_id UUID;
        v_assignment_released TIMESTAMPTZ;
        v_prev_actual UUID;
        v_prev_effective TIMESTAMPTZ;
        v_allocated_sum INTEGER;
        v_expected_remainder INTEGER;
    BEGIN
        SELECT tenant_id, farm_id, transplant_event_id, source_batch_carrier_assignment_id,
               source_plant_count, discarded_plant_count
        INTO v_line_tenant_id, v_line_farm_id, v_line_event_id, v_line_assignment_id,
             v_line_available, v_line_discarded
        FROM transplant_source_lines WHERE id = NEW.transplant_source_line_id;
        IF v_line_tenant_id IS NULL THEN
            RAISE EXCEPTION 'transplant source line not found';
        END IF;
        IF v_line_tenant_id <> NEW.tenant_id OR v_line_farm_id <> NEW.farm_id THEN
            RAISE EXCEPTION 'checkpoint does not belong to this tenant/farm';
        END IF;
        IF v_line_assignment_id <> NEW.batch_carrier_assignment_id THEN
            RAISE EXCEPTION 'checkpoint assignment does not match its own transplant source line';
        END IF;

        SELECT effective_time, batch_id, event_kind INTO v_event_effective, v_event_batch_id, v_new_event_kind
        FROM transplant_events WHERE id = v_line_event_id;
        IF v_event_effective <> NEW.effective_time THEN
            RAISE EXCEPTION 'checkpoint effective_time must equal its transplant event''s own effective_time';
        END IF;
        IF v_event_batch_id <> NEW.batch_id THEN
            RAISE EXCEPTION 'checkpoint batch_id does not match its transplant event''s batch';
        END IF;

        SELECT tenant_id, farm_id, batch_id, released_effective_time
        INTO v_assignment_tenant_id, v_assignment_farm_id, v_assignment_batch_id, v_assignment_released
        FROM batch_carrier_assignments WHERE id = NEW.batch_carrier_assignment_id;
        IF v_assignment_tenant_id IS NULL THEN
            RAISE EXCEPTION 'batch carrier assignment not found';
        END IF;
        IF v_assignment_tenant_id <> NEW.tenant_id OR v_assignment_farm_id <> NEW.farm_id THEN
            RAISE EXCEPTION 'checkpoint assignment does not belong to this tenant/farm';
        END IF;
        IF v_assignment_batch_id <> NEW.batch_id THEN
            RAISE EXCEPTION 'checkpoint assignment does not belong to this batch';
        END IF;
        IF v_assignment_released IS NOT NULL THEN
            RAISE EXCEPTION 'source assignment has already been released; no new checkpoint may be created';
        END IF;

        SELECT c.id, c.effective_time INTO v_prev_actual, v_prev_effective
        FROM batch_carrier_population_checkpoints c
        WHERE c.batch_carrier_assignment_id = NEW.batch_carrier_assignment_id
          AND NOT EXISTS (
              SELECT 1 FROM batch_carrier_population_checkpoints nxt WHERE nxt.previous_checkpoint_id = c.id
          );
        IF NEW.previous_checkpoint_id IS DISTINCT FROM v_prev_actual THEN
            RAISE EXCEPTION 'previous_checkpoint_id does not reference the actual latest prior checkpoint for this assignment';
        END IF;
        IF v_prev_effective IS NOT NULL THEN
            IF NEW.effective_time < v_prev_effective THEN
                RAISE EXCEPTION 'checkpoint effective_time must not precede the previous checkpoint''s own effective_time';
            ELSIF NEW.effective_time = v_prev_effective THEN
                IF v_new_event_kind NOT IN ('REVERSAL', 'REPLACEMENT') THEN
                    RAISE EXCEPTION 'checkpoint effective_time must be strictly greater than the previous checkpoint''s own effective_time';
                END IF;
            END IF;
        END IF;

        SELECT COALESCE(SUM(allocated_plant_count), 0) INTO v_allocated_sum
        FROM transplant_allocations WHERE source_line_id = NEW.transplant_source_line_id;
        v_expected_remainder := v_line_available - v_allocated_sum - v_line_discarded;
        IF NEW.remainder_after <> v_expected_remainder THEN
            RAISE EXCEPTION 'remainder_after does not match source_available_before - successful_transfer - discarded_plant_count';
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """


def upgrade() -> None:
    bind = op.get_bind()

    # --- 1. batch_carrier_population_checkpoints (new) ------------------------------
    op.create_table(
        "batch_carrier_population_checkpoints",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("crop_batches.id"), nullable=False),
        sa.Column(
            "batch_carrier_assignment_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("batch_carrier_assignments.id"), nullable=False,
        ),
        sa.Column(
            "transplant_source_line_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("transplant_source_lines.id"), nullable=False,
        ),
        sa.Column(
            "previous_checkpoint_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("batch_carrier_population_checkpoints.id"), nullable=True,
        ),
        sa.Column("remainder_after", sa.Integer(), nullable=False),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "remainder_after >= 0", name="ck_batch_carrier_population_checkpoints_remainder_non_negative"
        ),
        sa.UniqueConstraint(
            "transplant_source_line_id", name="ux_batch_carrier_population_checkpoints_source_line"
        ),
        sa.UniqueConstraint(
            "tenant_id", "farm_id", "id", name="uq_batch_carrier_population_checkpoints_tenant_farm_id"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_batch_carrier_population_checkpoints_tenant_farm_batch",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_carrier_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id", "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_batch_carrier_population_checkpoints_tenant_farm_assignment",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "transplant_source_line_id"],
            [
                "transplant_source_lines.tenant_id", "transplant_source_lines.farm_id",
                "transplant_source_lines.id",
            ],
            name="fk_batch_carrier_population_checkpoints_tenant_farm_source_line",
        ),
    )
    op.create_index(
        "ux_batch_carrier_population_checkpoints_previous_once",
        "batch_carrier_population_checkpoints", ["previous_checkpoint_id"], unique=True,
    )
    op.create_index(
        "ix_batch_carrier_population_checkpoints_assignment_effective",
        "batch_carrier_population_checkpoints", ["batch_carrier_assignment_id", "effective_time"],
    )

    op.execute(_POPULATION_CHECKPOINT_INTEGRITY_FUNCTION)
    op.execute(
        """
        CREATE TRIGGER batch_carrier_population_checkpoints_enforce_insert_integrity
        BEFORE INSERT ON batch_carrier_population_checkpoints
        FOR EACH ROW EXECUTE FUNCTION enforce_batch_carrier_population_checkpoint_insert_integrity();
        """
    )
    op.execute(
        """
        CREATE TRIGGER batch_carrier_population_checkpoints_no_update
        BEFORE UPDATE ON batch_carrier_population_checkpoints
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER batch_carrier_population_checkpoints_no_delete
        BEFORE DELETE ON batch_carrier_population_checkpoints
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER batch_carrier_population_checkpoints_enforce_reconciliation
        AFTER INSERT ON batch_carrier_population_checkpoints
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_transplant_reconciliation();
        """
    )

    # --- 2. CREATE OR REPLACE the three unified-authority-aware trigger functions ----
    bind.execute(sa.text(_UNIFIED_AUTHORITY_SOURCE_LINE_INTEGRITY_FUNCTION))
    bind.execute(sa.text(_UNIFIED_AUTHORITY_TRANSPLANT_RECONCILIATION_FUNCTION))
    bind.execute(sa.text(_UNIFIED_AUTHORITY_CLOSURE_ONLY_FUNCTION))


def downgrade() -> None:
    bind = op.get_bind()

    # --- downgrade guard -- never discard population-authority history -------------
    checkpoint_count = bind.execute(
        sa.text("SELECT count(*) FROM batch_carrier_population_checkpoints")
    ).scalar_one()
    if checkpoint_count > 0:
        raise RuntimeError(
            "Cannot downgrade past NURSERY-OPS-005A: "
            f"{checkpoint_count} batch_carrier_population_checkpoints row(s) exist. Downgrading would drop "
            "real chained-Transplant source-accounting history. Move/export the affected data out-of-band "
            "before downgrading, or do not downgrade."
        )

    bind.execute(sa.text(_PRE_005A_CLOSURE_ONLY_FUNCTION))
    bind.execute(sa.text(_PRE_005A_TRANSPLANT_RECONCILIATION_FUNCTION))
    bind.execute(sa.text(_PRE_005A_SOURCE_LINE_INTEGRITY_FUNCTION))

    op.execute(
        "DROP TRIGGER IF EXISTS batch_carrier_population_checkpoints_enforce_reconciliation "
        "ON batch_carrier_population_checkpoints"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS batch_carrier_population_checkpoints_no_delete "
        "ON batch_carrier_population_checkpoints"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS batch_carrier_population_checkpoints_no_update "
        "ON batch_carrier_population_checkpoints"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS batch_carrier_population_checkpoints_enforce_insert_integrity "
        "ON batch_carrier_population_checkpoints"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_batch_carrier_population_checkpoint_insert_integrity()")
    op.drop_index(
        "ix_batch_carrier_population_checkpoints_assignment_effective",
        table_name="batch_carrier_population_checkpoints",
    )
    op.drop_index(
        "ux_batch_carrier_population_checkpoints_previous_once",
        table_name="batch_carrier_population_checkpoints",
    )
    op.drop_table("batch_carrier_population_checkpoints")
