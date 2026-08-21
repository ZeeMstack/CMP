"""transplant correction (reversal / replacement)

TRANSPLANT-CORRECTION-001 -- immutable correction/void of a biological
Transplant event: `TransplantEvent.event_kind` extends the pre-existing
RECORD shape with REVERSAL (reverses exactly one directly-corrected target,
`reverses_transplant_event_id`, required non-empty `correction_reason`) and
REPLACEMENT (re-declares the correct biological facts for exactly one
directly-corrected target, `corrects_transplant_event_id`). Both point at
the SAME target event directly -- never at each other -- mirroring the
Seedling Disposition RECORD/REVERSAL/replacement precedent
(`b4e8a1f0d6c2`) exactly, so a REPLACEMENT can itself later become the
target of a further correction with zero special-casing.

A REVERSAL restores ALL source effects of its target (transferred
quantity, damage, rejection, sample, other loss) via one new
SeedlingSourceCheckpoint per restored source, `remainder_after` equal to
the target's own frozen `source_plant_count`; it releases the target's
destination assignment(s) and -- only for a fully-exhausted source -- opens
a new, active `BatchCarrierAssignment` for the same physical Carrier
(`opening_transplant_reversal_event_id` / `restored_from_batch_carrier_
assignment_id`), never mutating or repointing the original assignment or
its `SeedlingEntry`. It has zero destination lines and zero allocations --
`enforce_transplant_reconciliation` grows a structural-only branch for
this shape; the checkpoint arithmetic itself remains independently proven
by `enforce_seedling_source_checkpoint_insert_integrity`.

Seven existing trigger functions are updated via `CREATE OR REPLACE` (their
own `CREATE TRIGGER`/`CREATE CONSTRAINT TRIGGER` statements, defined in
earlier, untouched historical migrations, keep firing against the new
bodies unchanged) -- the same precedent `c8f1d4a92b6e` and `7bddca3261cc`
already established:

1. `enforce_transplant_reconciliation` (`f3a8c2e1b975` / `c8f1d4a92b6e`) --
   REVERSAL-kind events take a new, purely structural branch (>=1 source
   line, zero destination lines, zero allocations); RECORD/REPLACEMENT
   validation is byte-for-byte unchanged. Also widened to resolve
   `v_event_id` from `opening_transplant_reversal_event_id` on
   `batch_carrier_assignments` INSERT, alongside the existing
   `opening_transplant_event_id`.
2. `enforce_transplant_source_line_insert_integrity` (`c8f1d4a92b6e`) -- the
   same restoration-lineage backward walk as (3) below; a REVERSAL skips
   its balance-derived `source_plant_count` check entirely (that concept
   does not apply to a restoration -- proven instead by the checkpoint
   arithmetic); REPLACEMENT gains the same one-time equal-effective-time
   exception as (3).
3. `enforce_seedling_source_checkpoint_insert_integrity` (`c8f1d4a92b6e`) --
   its exact-equality "belongs to this assignment" check becomes a
   bounded backward walk through `restored_from_batch_carrier_assignment_
   id` (a checkpoint may reference a restoration descendant, never only
   the SeedlingEntry's original assignment directly); its "latest prior
   checkpoint" lookup becomes the structural chain-tip query (no successor
   exists) shared with section 6 below, instead of `ORDER BY effective_
   time DESC`; its strict-monotonic effective_time check gains one
   narrowly-scoped exception (EQUAL is legal only when the new checkpoint's
   own event is REVERSAL- or REPLACEMENT-kind -- the two paired-correction
   transitions this ticket freezes). The remainder-arithmetic check and the
   already-released guard are unchanged and unrelaxed -- a checkpoint
   always references the CURRENTLY ACTIVE (by construction, unreleased)
   assignment in its lineage, so neither ever needs to tolerate a released
   assignment.
3. `enforce_batch_carrier_assignment_origin_insert_integrity_v2`
   (`a4d92f7c1e6b`) -- new fourth branch for `opening_transplant_reversal_
   event_id`: proves the opening event is REVERSAL-kind, same batch, same
   Carrier and same stage run as `restored_from_batch_carrier_assignment_
   id`'s own row, and that predecessor was released by exactly the event
   this reversal reverses.
4. `enforce_batch_carrier_assignment_closure_only_v2` (`a4d92f7c1e6b` /
   `c8f1d4a92b6e`) -- its protected-column list grows the two new opener/
   lineage columns (immutable post-insert, same as every other opener);
   its sowing-origin-only release branch widens to also accept a reversal-
   restored source assignment; a new REVERSAL-releaser branch permits
   releasing ONLY the destination assignment opened by the exact event
   being reversed (`opening_transplant_event_id = reverses_transplant_
   event_id`) -- proven server-side, unreachable via direct SQL.
5/6. `enforce_seedling_disposition_command_insert_integrity` and
   `enforce_seedling_disposition_event_insert_integrity` (`b4e8a1f0d6c2`)
   -- their "source assignment already released" guard, which resolved
   only `SeedlingEntry.batch_carrier_assignment_id` directly (always the
   permanently-released original once a source has ever been restored),
   becomes a forward lineage walk: does ANY currently-unreleased
   assignment exist in this SeedlingEntry's restoration lineage (the
   original, or any descendant reachable via `restored_from_batch_
   carrier_assignment_id`). Unchanged when no restoration has ever
   occurred.

Three new objects:

- `transplant_events`: `event_kind`, `reverses_transplant_event_id`,
  `corrects_transplant_event_id`, `correction_reason`, a same-row per-kind
  CHECK, and two partial unique indexes (`ux_transplant_events_reverses_
  once` / `..._corrects_once`) -- at most one REVERSAL and at most one
  REPLACEMENT may ever target a given event.
- `enforce_transplant_event_correction_target_kind` (new `BEFORE INSERT`
  trigger on `transplant_events`) -- a REVERSAL/REPLACEMENT's target must
  itself be RECORD- or REPLACEMENT-kind, same tenant -- a REVERSAL may
  never itself be corrected.
- `enforce_transplant_correction_pair_integrity` (new `DEFERRABLE INITIALLY
  DEFERRED` constraint trigger on `transplant_events`) -- if a REPLACEMENT
  corrects X, a REVERSAL reversing X must exist by commit. A pure void
  (REVERSAL only, no REPLACEMENT) remains valid -- this only fires for
  REPLACEMENT inserts.

`batch_carrier_assignments` gains exactly two columns --
`opening_transplant_reversal_event_id` / `restored_from_batch_carrier_
assignment_id` -- reusing the existing `released_by_transplant_event_id`
for every TransplantEvent-kind releaser (RECORD/REPLACEMENT exhaustion,
REVERSAL destination-closure alike); no new release column. A new
composite FK proves tenant/farm/batch equality between a restored
assignment and its immediate predecessor structurally; same-Carrier and
released-by-target-X linkage are cross-row facts proven by the widened
origin-integrity trigger instead.

Downgrade guard: refuses if any `TransplantEvent.event_kind <> 'RECORD'`
or any `BatchCarrierAssignment` row uses either new column -- mirrors
CMP-011's own downgrade-guard precedent exactly.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f4a8c1e93d27"
down_revision: str | None = "b7e2f4a9c1d6"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


# =====================================================================
# Original trigger function bodies (pre-this-migration), captured
# verbatim for downgrade -- restoring each function to exactly what it
# was before this migration ran, never re-deriving from memory.
# =====================================================================

_ORIGINAL_TRANSPLANT_RECONCILIATION_FUNCTION = """
    CREATE OR REPLACE FUNCTION enforce_transplant_reconciliation() RETURNS trigger AS $$
    DECLARE
        v_event_id UUID;
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
                v_event_id := NEW.opening_transplant_event_id;
            ELSE
                v_event_id := NEW.released_by_transplant_event_id;
            END IF;
        END IF;

        IF v_event_id IS NULL THEN
            RETURN NEW;
        END IF;

        SELECT effective_time INTO v_event_effective FROM transplant_events WHERE id = v_event_id;

        SELECT count(*) INTO v_source_line_count FROM transplant_source_lines WHERE transplant_event_id = v_event_id;
        SELECT count(*) INTO v_destination_line_count FROM transplant_destination_lines WHERE transplant_event_id = v_event_id;
        SELECT count(*) INTO v_allocation_count FROM transplant_allocations WHERE transplant_event_id = v_event_id;
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

_NEW_TRANSPLANT_RECONCILIATION_FUNCTION = """
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

        -- TRANSPLANT-CORRECTION-001 section 8/9: a REVERSAL creates no new
        -- biological destination output -- structural shape only (>=1
        -- source line, zero destination lines, zero allocations). Per-line/
        -- per-event arithmetic does NOT apply here (a REVERSAL's
        -- source_plant_count is a RESTORED quantity, not a consumption-
        -- derived one) -- it is instead fully and independently proven by
        -- enforce_seedling_source_checkpoint_insert_integrity. RECORD/
        -- REPLACEMENT below are completely unchanged from before this ticket.
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

_ORIGINAL_SOURCE_LINE_INTEGRITY_FUNCTION = """
    CREATE OR REPLACE FUNCTION enforce_transplant_source_line_insert_integrity() RETURNS trigger AS $$
    DECLARE
        v_event_batch_id UUID;
        v_event_effective TIMESTAMPTZ;
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
    BEGIN
        SELECT batch_id, effective_time INTO v_event_batch_id, v_event_effective
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

        SELECT id, starting_living_seedling_count, effective_time
        INTO v_entry_id, v_entry_starting, v_entry_effective
        FROM seedling_entries WHERE batch_carrier_assignment_id = NEW.source_batch_carrier_assignment_id;
        IF v_entry_id IS NULL THEN
            RAISE EXCEPTION 'source assignment has no Seedling biological entry; modern transplant requires a SeedlingEntry-anchored source';
        END IF;

        SELECT remainder_after, effective_time INTO v_anchor_value, v_anchor_time
        FROM seedling_source_checkpoints WHERE seedling_entry_id = v_entry_id
        ORDER BY effective_time DESC, recorded_at DESC, id DESC LIMIT 1;
        v_has_checkpoint := v_anchor_value IS NOT NULL;
        IF NOT v_has_checkpoint THEN
            v_anchor_value := v_entry_starting;
            v_anchor_time := v_entry_effective;
        END IF;

        IF v_has_checkpoint THEN
            IF v_event_effective <= v_anchor_time THEN
                RAISE EXCEPTION 'transplant effective_time must be strictly greater than the previous checkpoint''s own effective_time';
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

_NEW_SOURCE_LINE_INTEGRITY_FUNCTION = """
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

        -- TRANSPLANT-CORRECTION-001 section 10/17: resolve the SeedlingEntry
        -- via bounded backward restoration-lineage walk -- identical
        -- mechanism to enforce_seedling_source_checkpoint_insert_integrity's
        -- own walk (kept in sync deliberately; both trigger the same class
        -- of failure on a genuinely orphaned assignment).
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
            -- TRANSPLANT-CORRECTION-001 section 8/9: a REVERSAL restores a
            -- frozen pre-event quantity, not a balance-consumption
            -- derivation -- that concept does not apply here. Remainder
            -- arithmetic is independently proven by
            -- enforce_seedling_source_checkpoint_insert_integrity; structural
            -- shape by enforce_transplant_reconciliation. No further check
            -- on source_plant_count's exact value is performed by this
            -- trigger for a REVERSAL.
            RETURN NEW;
        END IF;

        -- TRANSPLANT-CORRECTION-001 section 6: chain-tip resolution, the
        -- same shared definition of "current checkpoint" used everywhere
        -- else -- never ORDER BY effective_time DESC.
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
                -- TRANSPLANT-CORRECTION-001 section 4/7: EQUAL is legal only
                -- for the paired-correction transitions (REPLACEMENT sharing
                -- its own REVERSAL's checkpoint time) -- ordinary
                -- independent RECORD chronology is unchanged and remains
                -- strict.
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

_ORIGINAL_CHECKPOINT_INTEGRITY_FUNCTION = """
    CREATE OR REPLACE FUNCTION enforce_seedling_source_checkpoint_insert_integrity() RETURNS trigger AS $$
    DECLARE
        v_line_tenant_id UUID;
        v_line_farm_id UUID;
        v_line_event_id UUID;
        v_line_assignment_id UUID;
        v_line_available INTEGER;
        v_line_discarded INTEGER;
        v_event_effective TIMESTAMPTZ;
        v_event_batch_id UUID;
        v_entry_batch_id UUID;
        v_entry_tenant_id UUID;
        v_entry_farm_id UUID;
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
        IF v_line_assignment_id <> NEW.source_batch_carrier_assignment_id THEN
            RAISE EXCEPTION 'checkpoint source assignment does not match its own transplant source line';
        END IF;

        SELECT effective_time, batch_id INTO v_event_effective, v_event_batch_id
        FROM transplant_events WHERE id = v_line_event_id;
        IF v_event_effective <> NEW.effective_time THEN
            RAISE EXCEPTION 'checkpoint effective_time must equal its transplant event''s own effective_time';
        END IF;
        IF v_event_batch_id <> NEW.batch_id THEN
            RAISE EXCEPTION 'checkpoint batch_id does not match its transplant event''s batch';
        END IF;

        SELECT tenant_id, farm_id, batch_id INTO v_entry_tenant_id, v_entry_farm_id, v_entry_batch_id
        FROM seedling_entries WHERE id = NEW.seedling_entry_id;
        IF v_entry_tenant_id IS NULL THEN
            RAISE EXCEPTION 'seedling entry not found';
        END IF;
        IF v_entry_tenant_id <> NEW.tenant_id OR v_entry_farm_id <> NEW.farm_id THEN
            RAISE EXCEPTION 'checkpoint seedling entry does not belong to this tenant/farm';
        END IF;
        IF v_entry_batch_id <> NEW.batch_id THEN
            RAISE EXCEPTION 'checkpoint seedling entry does not belong to this batch';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM seedling_entries
            WHERE id = NEW.seedling_entry_id AND batch_carrier_assignment_id = NEW.source_batch_carrier_assignment_id
        ) THEN
            RAISE EXCEPTION 'checkpoint seedling entry does not belong to the checkpoint''s own source assignment';
        END IF;

        SELECT released_effective_time INTO v_assignment_released
        FROM batch_carrier_assignments WHERE id = NEW.source_batch_carrier_assignment_id;
        IF v_assignment_released IS NOT NULL THEN
            RAISE EXCEPTION 'source assignment has already been released; no new checkpoint may be created';
        END IF;

        SELECT id, effective_time INTO v_prev_actual, v_prev_effective
        FROM seedling_source_checkpoints WHERE seedling_entry_id = NEW.seedling_entry_id
        ORDER BY effective_time DESC, recorded_at DESC, id DESC LIMIT 1;
        IF NEW.previous_checkpoint_id IS DISTINCT FROM v_prev_actual THEN
            RAISE EXCEPTION 'previous_checkpoint_id does not reference the actual latest prior checkpoint for this seedling entry';
        END IF;
        IF v_prev_effective IS NOT NULL AND NEW.effective_time <= v_prev_effective THEN
            RAISE EXCEPTION 'checkpoint effective_time must be strictly greater than the previous checkpoint''s own effective_time';
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

_NEW_CHECKPOINT_INTEGRITY_FUNCTION = """
    CREATE OR REPLACE FUNCTION enforce_seedling_source_checkpoint_insert_integrity() RETURNS trigger AS $$
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
        v_entry_batch_id UUID;
        v_entry_tenant_id UUID;
        v_entry_farm_id UUID;
        v_entry_own_assignment UUID;
        v_assignment_released TIMESTAMPTZ;
        v_prev_actual UUID;
        v_prev_effective TIMESTAMPTZ;
        v_allocated_sum INTEGER;
        v_expected_remainder INTEGER;
        v_walk_id UUID;
        v_hops INTEGER;
        v_lineage_valid BOOLEAN;
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
        IF v_line_assignment_id <> NEW.source_batch_carrier_assignment_id THEN
            RAISE EXCEPTION 'checkpoint source assignment does not match its own transplant source line';
        END IF;

        SELECT effective_time, batch_id, event_kind INTO v_event_effective, v_event_batch_id, v_new_event_kind
        FROM transplant_events WHERE id = v_line_event_id;
        IF v_event_effective <> NEW.effective_time THEN
            RAISE EXCEPTION 'checkpoint effective_time must equal its transplant event''s own effective_time';
        END IF;
        IF v_event_batch_id <> NEW.batch_id THEN
            RAISE EXCEPTION 'checkpoint batch_id does not match its transplant event''s batch';
        END IF;

        SELECT tenant_id, farm_id, batch_id, batch_carrier_assignment_id
        INTO v_entry_tenant_id, v_entry_farm_id, v_entry_batch_id, v_entry_own_assignment
        FROM seedling_entries WHERE id = NEW.seedling_entry_id;
        IF v_entry_tenant_id IS NULL THEN
            RAISE EXCEPTION 'seedling entry not found';
        END IF;
        IF v_entry_tenant_id <> NEW.tenant_id OR v_entry_farm_id <> NEW.farm_id THEN
            RAISE EXCEPTION 'checkpoint seedling entry does not belong to this tenant/farm';
        END IF;
        IF v_entry_batch_id <> NEW.batch_id THEN
            RAISE EXCEPTION 'checkpoint seedling entry does not belong to this batch';
        END IF;

        -- TRANSPLANT-CORRECTION-001 section 10: a checkpoint's own source
        -- assignment must be EITHER the SeedlingEntry's directly-owned
        -- (original) assignment OR a valid restoration descendant of it,
        -- reached by walking restored_from_batch_carrier_assignment_id
        -- backward -- bounded, cycle-safe (structurally acyclic by
        -- construction: opener/lineage columns are immutable post-insert,
        -- so a chain can only ever grow forward; the hop cap is pure
        -- insurance, never legitimately reached). The checkpoint records
        -- the ACTUAL CURRENT assignment (B/C when restored), never falsely
        -- the historical original.
        v_walk_id := NEW.source_batch_carrier_assignment_id;
        v_hops := 0;
        v_lineage_valid := FALSE;
        LOOP
            IF v_walk_id = v_entry_own_assignment THEN
                v_lineage_valid := TRUE;
                EXIT;
            END IF;
            v_hops := v_hops + 1;
            IF v_hops > 50 THEN
                RAISE EXCEPTION 'restoration lineage exceeds maximum depth for assignment %', NEW.source_batch_carrier_assignment_id;
            END IF;
            SELECT restored_from_batch_carrier_assignment_id INTO v_walk_id
            FROM batch_carrier_assignments WHERE id = v_walk_id;
            EXIT WHEN v_walk_id IS NULL;
        END LOOP;
        IF NOT v_lineage_valid THEN
            RAISE EXCEPTION 'checkpoint seedling entry does not belong to the checkpoint''s own source assignment lineage';
        END IF;

        SELECT released_effective_time INTO v_assignment_released
        FROM batch_carrier_assignments WHERE id = NEW.source_batch_carrier_assignment_id;
        IF v_assignment_released IS NOT NULL THEN
            RAISE EXCEPTION 'source assignment has already been released; no new checkpoint may be created';
        END IF;

        -- TRANSPLANT-CORRECTION-001 section 6: the structural chain TIP
        -- (no successor references it as previous_checkpoint_id) is the
        -- single shared definition of "current" -- identical to the
        -- Python-level resolver, never a second competing implementation,
        -- and correct even once paired-correction checkpoints legitimately
        -- share an effective_time with their predecessor.
        SELECT c.id, c.effective_time INTO v_prev_actual, v_prev_effective
        FROM seedling_source_checkpoints c
        WHERE c.seedling_entry_id = NEW.seedling_entry_id
          AND NOT EXISTS (
              SELECT 1 FROM seedling_source_checkpoints nxt WHERE nxt.previous_checkpoint_id = c.id
          );
        IF NEW.previous_checkpoint_id IS DISTINCT FROM v_prev_actual THEN
            RAISE EXCEPTION 'previous_checkpoint_id does not reference the actual latest prior checkpoint for this seedling entry';
        END IF;
        IF v_prev_effective IS NOT NULL THEN
            IF NEW.effective_time < v_prev_effective THEN
                RAISE EXCEPTION 'checkpoint effective_time must not precede the previous checkpoint''s own effective_time';
            ELSIF NEW.effective_time = v_prev_effective THEN
                -- TRANSPLANT-CORRECTION-001 section 4/7: EQUAL is legal
                -- ONLY for the two paired-correction transitions (target's
                -- checkpoint -> its REVERSAL's checkpoint; that REVERSAL's
                -- checkpoint -> its paired REPLACEMENT's checkpoint) --
                -- never for an ordinary independent RECORD, which remains
                -- strictly later exactly as before this ticket.
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

_ORIGINAL_ORIGIN_INTEGRITY_FUNCTION = """
    CREATE OR REPLACE FUNCTION enforce_batch_carrier_assignment_origin_insert_integrity_v2() RETURNS trigger AS $$
    DECLARE
        v_event_batch_id UUID;
        v_event_run_id UUID;
        v_event_effective TIMESTAMPTZ;
        v_run_stage_id UUID;
        v_required_type UUID;
        v_actual_type UUID;
        v_batch_created_by UUID;
        v_run_kind TEXT;
        v_run_event UUID;
    BEGIN
        IF NEW.opening_sowing_event_id IS NOT NULL THEN
            SELECT batch_id, active_batch_stage_run_id, effective_time
            INTO v_event_batch_id, v_event_run_id, v_event_effective
            FROM sowing_events WHERE id = NEW.opening_sowing_event_id;
            IF v_event_batch_id IS NULL THEN
                RAISE EXCEPTION 'opening sowing event not found';
            END IF;
            IF v_event_batch_id <> NEW.batch_id THEN
                RAISE EXCEPTION 'opening event batch mismatch';
            END IF;
            IF v_event_run_id <> NEW.batch_stage_run_id THEN
                RAISE EXCEPTION 'opening event stage-run mismatch';
            END IF;
            IF v_event_effective <> NEW.assigned_effective_time THEN
                RAISE EXCEPTION 'assigned_effective_time must match the opening event''s effective time';
            END IF;

            SELECT workflow_stage_id INTO v_run_stage_id FROM batch_stage_runs WHERE id = NEW.batch_stage_run_id;
            SELECT required_carrier_type_id INTO v_required_type FROM workflow_stages WHERE id = v_run_stage_id;
            SELECT carrier_type_id INTO v_actual_type FROM carriers WHERE id = NEW.carrier_id;
            IF v_required_type IS NULL OR v_actual_type IS DISTINCT FROM v_required_type THEN
                RAISE EXCEPTION 'carrier type does not match the stage''s required carrier type';
            END IF;
        ELSIF NEW.opening_transplant_event_id IS NOT NULL THEN
            SELECT batch_id, active_batch_stage_run_id, effective_time
            INTO v_event_batch_id, v_event_run_id, v_event_effective
            FROM transplant_events WHERE id = NEW.opening_transplant_event_id;
            IF v_event_batch_id IS NULL THEN
                RAISE EXCEPTION 'opening transplant event not found';
            END IF;
            IF v_event_batch_id <> NEW.batch_id THEN
                RAISE EXCEPTION 'opening event batch mismatch';
            END IF;
            IF v_event_run_id <> NEW.batch_stage_run_id THEN
                RAISE EXCEPTION 'opening event stage-run mismatch';
            END IF;
            IF v_event_effective <> NEW.assigned_effective_time THEN
                RAISE EXCEPTION 'assigned_effective_time must match the opening event''s effective time';
            END IF;

            SELECT workflow_stage_id INTO v_run_stage_id FROM batch_stage_runs WHERE id = NEW.batch_stage_run_id;
            SELECT required_carrier_type_id INTO v_required_type FROM workflow_stages WHERE id = v_run_stage_id;
            SELECT carrier_type_id INTO v_actual_type FROM carriers WHERE id = NEW.carrier_id;
            IF v_required_type IS NULL OR v_actual_type IS DISTINCT FROM v_required_type THEN
                RAISE EXCEPTION 'carrier type does not match the stage''s required carrier type';
            END IF;
        ELSE
            SELECT effective_time INTO v_event_effective
            FROM batch_derivation_events WHERE id = NEW.opening_batch_derivation_event_id;
            IF v_event_effective IS NULL THEN
                RAISE EXCEPTION 'opening batch derivation event not found';
            END IF;
            IF v_event_effective <> NEW.assigned_effective_time THEN
                RAISE EXCEPTION 'assigned_effective_time must match the opening derivation event''s effective time';
            END IF;

            SELECT created_by_batch_derivation_event_id INTO v_batch_created_by
            FROM crop_batches WHERE id = NEW.batch_id;
            IF v_batch_created_by IS DISTINCT FROM NEW.opening_batch_derivation_event_id THEN
                RAISE EXCEPTION 'destination batch was not created by this derivation event';
            END IF;

            SELECT t.command_kind, t.batch_derivation_event_id INTO v_run_kind, v_run_event
            FROM batch_stage_runs r JOIN batch_stage_transitions t ON t.id = r.opened_by_transition_id
            WHERE r.id = NEW.batch_stage_run_id;
            IF v_run_kind IS DISTINCT FROM 'derivation_entry'
               OR v_run_event IS DISTINCT FROM NEW.opening_batch_derivation_event_id THEN
                RAISE EXCEPTION 'destination stage run was not opened by this derivation event''s entry transition';
            END IF;
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

_NEW_ORIGIN_INTEGRITY_FUNCTION = """
    CREATE OR REPLACE FUNCTION enforce_batch_carrier_assignment_origin_insert_integrity_v2() RETURNS trigger AS $$
    DECLARE
        v_event_batch_id UUID;
        v_event_run_id UUID;
        v_event_effective TIMESTAMPTZ;
        v_run_stage_id UUID;
        v_required_type UUID;
        v_actual_type UUID;
        v_batch_created_by UUID;
        v_run_kind TEXT;
        v_run_event UUID;
        v_reversal_kind TEXT;
        v_reverses_id UUID;
        v_predecessor_carrier_id UUID;
        v_predecessor_run_id UUID;
        v_predecessor_released_by UUID;
    BEGIN
        IF NEW.opening_sowing_event_id IS NOT NULL THEN
            SELECT batch_id, active_batch_stage_run_id, effective_time
            INTO v_event_batch_id, v_event_run_id, v_event_effective
            FROM sowing_events WHERE id = NEW.opening_sowing_event_id;
            IF v_event_batch_id IS NULL THEN
                RAISE EXCEPTION 'opening sowing event not found';
            END IF;
            IF v_event_batch_id <> NEW.batch_id THEN
                RAISE EXCEPTION 'opening event batch mismatch';
            END IF;
            IF v_event_run_id <> NEW.batch_stage_run_id THEN
                RAISE EXCEPTION 'opening event stage-run mismatch';
            END IF;
            IF v_event_effective <> NEW.assigned_effective_time THEN
                RAISE EXCEPTION 'assigned_effective_time must match the opening event''s effective time';
            END IF;

            SELECT workflow_stage_id INTO v_run_stage_id FROM batch_stage_runs WHERE id = NEW.batch_stage_run_id;
            SELECT required_carrier_type_id INTO v_required_type FROM workflow_stages WHERE id = v_run_stage_id;
            SELECT carrier_type_id INTO v_actual_type FROM carriers WHERE id = NEW.carrier_id;
            IF v_required_type IS NULL OR v_actual_type IS DISTINCT FROM v_required_type THEN
                RAISE EXCEPTION 'carrier type does not match the stage''s required carrier type';
            END IF;
        ELSIF NEW.opening_transplant_event_id IS NOT NULL THEN
            SELECT batch_id, active_batch_stage_run_id, effective_time
            INTO v_event_batch_id, v_event_run_id, v_event_effective
            FROM transplant_events WHERE id = NEW.opening_transplant_event_id;
            IF v_event_batch_id IS NULL THEN
                RAISE EXCEPTION 'opening transplant event not found';
            END IF;
            IF v_event_batch_id <> NEW.batch_id THEN
                RAISE EXCEPTION 'opening event batch mismatch';
            END IF;
            IF v_event_run_id <> NEW.batch_stage_run_id THEN
                RAISE EXCEPTION 'opening event stage-run mismatch';
            END IF;
            IF v_event_effective <> NEW.assigned_effective_time THEN
                RAISE EXCEPTION 'assigned_effective_time must match the opening event''s effective time';
            END IF;

            SELECT workflow_stage_id INTO v_run_stage_id FROM batch_stage_runs WHERE id = NEW.batch_stage_run_id;
            SELECT required_carrier_type_id INTO v_required_type FROM workflow_stages WHERE id = v_run_stage_id;
            SELECT carrier_type_id INTO v_actual_type FROM carriers WHERE id = NEW.carrier_id;
            IF v_required_type IS NULL OR v_actual_type IS DISTINCT FROM v_required_type THEN
                RAISE EXCEPTION 'carrier type does not match the stage''s required carrier type';
            END IF;
        ELSIF NEW.opening_transplant_reversal_event_id IS NOT NULL THEN
            -- TRANSPLANT-CORRECTION-001 section 12: a reversal-restored
            -- source assignment is not a fresh stage-driven registration --
            -- it is the SAME physical Tray/stage-run identity reopened, so
            -- no carrier-type-vs-active-stage check applies (mirrors why a
            -- restored assignment is not itself a destination).
            SELECT batch_id, effective_time, event_kind, reverses_transplant_event_id
            INTO v_event_batch_id, v_event_effective, v_reversal_kind, v_reverses_id
            FROM transplant_events WHERE id = NEW.opening_transplant_reversal_event_id;
            IF v_event_batch_id IS NULL THEN
                RAISE EXCEPTION 'opening reversal event not found';
            END IF;
            IF v_reversal_kind <> 'REVERSAL' THEN
                RAISE EXCEPTION 'opening_transplant_reversal_event_id must reference a REVERSAL-kind transplant event';
            END IF;
            IF v_event_batch_id <> NEW.batch_id THEN
                RAISE EXCEPTION 'opening event batch mismatch';
            END IF;
            IF v_event_effective <> NEW.assigned_effective_time THEN
                RAISE EXCEPTION 'assigned_effective_time must match the opening event''s effective time';
            END IF;

            IF NEW.restored_from_batch_carrier_assignment_id IS NULL THEN
                RAISE EXCEPTION 'a reversal-opened assignment must reference restored_from_batch_carrier_assignment_id';
            END IF;
            SELECT carrier_id, batch_stage_run_id, released_by_transplant_event_id
            INTO v_predecessor_carrier_id, v_predecessor_run_id, v_predecessor_released_by
            FROM batch_carrier_assignments WHERE id = NEW.restored_from_batch_carrier_assignment_id;
            IF v_predecessor_carrier_id IS DISTINCT FROM NEW.carrier_id THEN
                RAISE EXCEPTION 'restored assignment must be for the same physical Carrier as its predecessor';
            END IF;
            IF v_predecessor_run_id IS DISTINCT FROM NEW.batch_stage_run_id THEN
                RAISE EXCEPTION 'restored assignment must preserve its predecessor''s own stage run';
            END IF;
            IF v_predecessor_released_by IS DISTINCT FROM v_reverses_id THEN
                RAISE EXCEPTION 'restored assignment predecessor must have been released by the exact event this reversal reverses';
            END IF;
        ELSE
            SELECT effective_time INTO v_event_effective
            FROM batch_derivation_events WHERE id = NEW.opening_batch_derivation_event_id;
            IF v_event_effective IS NULL THEN
                RAISE EXCEPTION 'opening batch derivation event not found';
            END IF;
            IF v_event_effective <> NEW.assigned_effective_time THEN
                RAISE EXCEPTION 'assigned_effective_time must match the opening derivation event''s effective time';
            END IF;

            SELECT created_by_batch_derivation_event_id INTO v_batch_created_by
            FROM crop_batches WHERE id = NEW.batch_id;
            IF v_batch_created_by IS DISTINCT FROM NEW.opening_batch_derivation_event_id THEN
                RAISE EXCEPTION 'destination batch was not created by this derivation event';
            END IF;

            SELECT t.command_kind, t.batch_derivation_event_id INTO v_run_kind, v_run_event
            FROM batch_stage_runs r JOIN batch_stage_transitions t ON t.id = r.opened_by_transition_id
            WHERE r.id = NEW.batch_stage_run_id;
            IF v_run_kind IS DISTINCT FROM 'derivation_entry'
               OR v_run_event IS DISTINCT FROM NEW.opening_batch_derivation_event_id THEN
                RAISE EXCEPTION 'destination stage run was not opened by this derivation event''s entry transition';
            END IF;
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

_ORIGINAL_CLOSURE_ONLY_FUNCTION = """
    CREATE OR REPLACE FUNCTION enforce_batch_carrier_assignment_closure_only_v2() RETURNS trigger AS $$
    DECLARE
        v_source_line_carrier UUID;
        v_transplant_batch_id UUID;
        v_transplant_effective TIMESTAMPTZ;
        v_derivation_effective TIMESTAMPTZ;
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
           OR NEW.actor_user_id <> OLD.actor_user_id
        THEN
            RAISE EXCEPTION 'only released_effective_time, released_by_transplant_event_id, and released_by_batch_derivation_event_id may change when releasing a batch_carrier_assignment';
        END IF;

        IF NEW.released_effective_time IS NULL
           OR (NEW.released_by_transplant_event_id IS NULL AND NEW.released_by_batch_derivation_event_id IS NULL)
        THEN
            RAISE EXCEPTION 'releasing a batch_carrier_assignment requires released_effective_time and exactly one typed releaser';
        END IF;

        IF NEW.released_by_transplant_event_id IS NOT NULL THEN
            IF NEW.opening_sowing_event_id IS NULL THEN
                RAISE EXCEPTION 'only sowing-origin assignments may be released by transplantation';
            END IF;

            SELECT batch_id, effective_time INTO v_transplant_batch_id, v_transplant_effective
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
        ELSE
            SELECT effective_time INTO v_derivation_effective
            FROM batch_derivation_events WHERE id = NEW.released_by_batch_derivation_event_id;
            IF v_derivation_effective IS NULL THEN
                RAISE EXCEPTION 'releasing batch derivation event not found';
            END IF;
            IF v_derivation_effective <> NEW.released_effective_time THEN
                RAISE EXCEPTION 'released_effective_time must match the releasing derivation event''s effective time';
            END IF;
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

_NEW_CLOSURE_ONLY_FUNCTION = """
    CREATE OR REPLACE FUNCTION enforce_batch_carrier_assignment_closure_only_v2() RETURNS trigger AS $$
    DECLARE
        v_source_line_carrier UUID;
        v_transplant_batch_id UUID;
        v_transplant_effective TIMESTAMPTZ;
        v_derivation_effective TIMESTAMPTZ;
        v_releaser_kind TEXT;
        v_reverses_id UUID;
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
           OR NEW.restored_from_batch_carrier_assignment_id IS DISTINCT FROM OLD.restored_from_batch_carrier_assignment_id
           OR NEW.actor_user_id <> OLD.actor_user_id
        THEN
            RAISE EXCEPTION 'only released_effective_time, released_by_transplant_event_id, and released_by_batch_derivation_event_id may change when releasing a batch_carrier_assignment';
        END IF;

        IF NEW.released_effective_time IS NULL
           OR (NEW.released_by_transplant_event_id IS NULL AND NEW.released_by_batch_derivation_event_id IS NULL)
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
                -- TRANSPLANT-CORRECTION-001 section 14 Case A: normal
                -- biological source exhaustion -- widened to also accept a
                -- reversal-restored source assignment, not only sowing-origin.
                IF NEW.opening_sowing_event_id IS NULL AND NEW.opening_transplant_reversal_event_id IS NULL THEN
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
                -- TRANSPLANT-CORRECTION-001 section 14 Case B: a REVERSAL
                -- may close ONLY the destination assignment opened by the
                -- exact event it reverses -- both sides resolved entirely
                -- server-side from already-committed rows, so no direct SQL
                -- can release an unrelated assignment via a REVERSAL.
                IF NEW.opening_transplant_event_id IS DISTINCT FROM v_reverses_id THEN
                    RAISE EXCEPTION 'a REVERSAL may only release the destination assignment opened by the exact event it reverses';
                END IF;
            ELSE
                RAISE EXCEPTION 'unrecognized releasing transplant event kind';
            END IF;
        ELSE
            SELECT effective_time INTO v_derivation_effective
            FROM batch_derivation_events WHERE id = NEW.released_by_batch_derivation_event_id;
            IF v_derivation_effective IS NULL THEN
                RAISE EXCEPTION 'releasing batch derivation event not found';
            END IF;
            IF v_derivation_effective <> NEW.released_effective_time THEN
                RAISE EXCEPTION 'released_effective_time must match the releasing derivation event''s effective time';
            END IF;
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

_ORIGINAL_DISPOSITION_COMMAND_INTEGRITY_FUNCTION = """
    CREATE OR REPLACE FUNCTION enforce_seedling_disposition_command_insert_integrity() RETURNS trigger AS $$
    DECLARE
        v_entry_tenant_id UUID;
        v_entry_farm_id UUID;
        v_entry_batch_id UUID;
        v_entry_assignment_id UUID;
        v_assignment_released TIMESTAMPTZ;
        v_target_seedling_entry_id UUID;
        v_target_tenant_id UUID;
        v_target_farm_id UUID;
    BEGIN
        SELECT tenant_id, farm_id, batch_id, batch_carrier_assignment_id
        INTO v_entry_tenant_id, v_entry_farm_id, v_entry_batch_id, v_entry_assignment_id
        FROM seedling_entries WHERE id = NEW.seedling_entry_id;
        IF v_entry_tenant_id IS NULL THEN
            RAISE EXCEPTION 'seedling entry not found';
        END IF;
        IF v_entry_tenant_id <> NEW.tenant_id OR v_entry_farm_id <> NEW.farm_id THEN
            RAISE EXCEPTION 'seedling entry does not belong to this tenant/farm';
        END IF;
        IF v_entry_batch_id <> NEW.batch_id THEN
            RAISE EXCEPTION 'seedling entry does not belong to this batch';
        END IF;

        SELECT released_effective_time INTO v_assignment_released
        FROM batch_carrier_assignments WHERE id = v_entry_assignment_id;
        IF v_assignment_released IS NOT NULL THEN
            RAISE EXCEPTION 'assignment has already been released; no new Seedling disposition command may be created';
        END IF;

        IF NEW.operation_kind = 'CORRECT' THEN
            SELECT seedling_entry_id, tenant_id, farm_id
            INTO v_target_seedling_entry_id, v_target_tenant_id, v_target_farm_id
            FROM seedling_disposition_events WHERE id = NEW.target_event_id;
            IF v_target_seedling_entry_id IS NULL THEN
                RAISE EXCEPTION 'target event not found';
            END IF;
            IF v_target_tenant_id <> NEW.tenant_id OR v_target_farm_id <> NEW.farm_id THEN
                RAISE EXCEPTION 'target event does not belong to this tenant/farm';
            END IF;
            IF v_target_seedling_entry_id <> NEW.seedling_entry_id THEN
                RAISE EXCEPTION 'target event does not belong to this seedling entry';
            END IF;
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

_NEW_DISPOSITION_COMMAND_INTEGRITY_FUNCTION = """
    CREATE OR REPLACE FUNCTION enforce_seedling_disposition_command_insert_integrity() RETURNS trigger AS $$
    DECLARE
        v_entry_tenant_id UUID;
        v_entry_farm_id UUID;
        v_entry_batch_id UUID;
        v_entry_assignment_id UUID;
        v_active_assignment_id UUID;
        v_target_seedling_entry_id UUID;
        v_target_tenant_id UUID;
        v_target_farm_id UUID;
    BEGIN
        SELECT tenant_id, farm_id, batch_id, batch_carrier_assignment_id
        INTO v_entry_tenant_id, v_entry_farm_id, v_entry_batch_id, v_entry_assignment_id
        FROM seedling_entries WHERE id = NEW.seedling_entry_id;
        IF v_entry_tenant_id IS NULL THEN
            RAISE EXCEPTION 'seedling entry not found';
        END IF;
        IF v_entry_tenant_id <> NEW.tenant_id OR v_entry_farm_id <> NEW.farm_id THEN
            RAISE EXCEPTION 'seedling entry does not belong to this tenant/farm';
        END IF;
        IF v_entry_batch_id <> NEW.batch_id THEN
            RAISE EXCEPTION 'seedling entry does not belong to this batch';
        END IF;

        -- TRANSPLANT-CORRECTION-001 section 18: a NEW command is permitted
        -- while ANY currently-unreleased assignment exists in this
        -- SeedlingEntry's restoration lineage (the original directly, or a
        -- descendant reached via restored_from_batch_carrier_assignment_id)
        -- -- not only when the original itself happens to still be active.
        -- Unchanged behavior when no restoration has ever occurred.
        WITH RECURSIVE lineage AS (
            SELECT id, released_effective_time FROM batch_carrier_assignments WHERE id = v_entry_assignment_id
            UNION ALL
            SELECT bca.id, bca.released_effective_time
            FROM batch_carrier_assignments bca
            JOIN lineage l ON bca.restored_from_batch_carrier_assignment_id = l.id
        )
        SELECT id INTO v_active_assignment_id FROM lineage WHERE released_effective_time IS NULL LIMIT 1;
        IF v_active_assignment_id IS NULL THEN
            RAISE EXCEPTION 'assignment has already been released; no new Seedling disposition command may be created';
        END IF;

        IF NEW.operation_kind = 'CORRECT' THEN
            SELECT seedling_entry_id, tenant_id, farm_id
            INTO v_target_seedling_entry_id, v_target_tenant_id, v_target_farm_id
            FROM seedling_disposition_events WHERE id = NEW.target_event_id;
            IF v_target_seedling_entry_id IS NULL THEN
                RAISE EXCEPTION 'target event not found';
            END IF;
            IF v_target_tenant_id <> NEW.tenant_id OR v_target_farm_id <> NEW.farm_id THEN
                RAISE EXCEPTION 'target event does not belong to this tenant/farm';
            END IF;
            IF v_target_seedling_entry_id <> NEW.seedling_entry_id THEN
                RAISE EXCEPTION 'target event does not belong to this seedling entry';
            END IF;
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

_ORIGINAL_DISPOSITION_EVENT_INTEGRITY_FUNCTION = """
    CREATE OR REPLACE FUNCTION enforce_seedling_disposition_event_insert_integrity() RETURNS trigger AS $$
    DECLARE
        v_cmd_tenant_id UUID;
        v_cmd_farm_id UUID;
        v_cmd_seedling_entry_id UUID;
        v_cmd_operation_kind TEXT;
        v_cmd_target_event_id UUID;
        v_entry_effective TIMESTAMPTZ;
        v_entry_starting INTEGER;
        v_assignment_id UUID;
        v_assignment_assigned TIMESTAMPTZ;
        v_assignment_released TIMESTAMPTZ;
        v_target_kind TEXT;
        v_target_tenant_id UUID;
        v_target_farm_id UUID;
        v_target_seedling_entry_id UUID;
        v_target_reason TEXT;
        v_target_delta INTEGER;
        v_target_effective TIMESTAMPTZ;
        v_running INTEGER;
        rec RECORD;
    BEGIN
        SELECT tenant_id, farm_id, seedling_entry_id, operation_kind, target_event_id
        INTO v_cmd_tenant_id, v_cmd_farm_id, v_cmd_seedling_entry_id, v_cmd_operation_kind, v_cmd_target_event_id
        FROM seedling_disposition_commands WHERE id = NEW.command_id;
        IF v_cmd_tenant_id IS NULL THEN
            RAISE EXCEPTION 'command not found';
        END IF;
        IF v_cmd_tenant_id <> NEW.tenant_id OR v_cmd_farm_id <> NEW.farm_id THEN
            RAISE EXCEPTION 'command does not belong to this tenant/farm';
        END IF;
        IF v_cmd_seedling_entry_id <> NEW.seedling_entry_id THEN
            RAISE EXCEPTION 'event does not belong to the same seedling entry as its command';
        END IF;

        SELECT effective_time, starting_living_seedling_count, batch_carrier_assignment_id
        INTO v_entry_effective, v_entry_starting, v_assignment_id
        FROM seedling_entries WHERE id = NEW.seedling_entry_id FOR UPDATE;

        SELECT assigned_effective_time, released_effective_time
        INTO v_assignment_assigned, v_assignment_released
        FROM batch_carrier_assignments WHERE id = v_assignment_id;

        IF v_assignment_released IS NOT NULL THEN
            RAISE EXCEPTION 'assignment has already been released; no new Seedling disposition event may be created';
        END IF;

        IF NEW.effective_time < v_entry_effective THEN
            RAISE EXCEPTION 'event effective_time precedes the SeedlingEntry''s own effective_time';
        END IF;
        IF NEW.effective_time < v_assignment_assigned THEN
            RAISE EXCEPTION 'event effective_time precedes the assignment''s assigned_effective_time';
        END IF;

        IF NEW.event_kind = 'REVERSAL' THEN
            SELECT tenant_id, farm_id, seedling_entry_id, event_kind, reason_code, quantity_delta, effective_time
            INTO v_target_tenant_id, v_target_farm_id, v_target_seedling_entry_id, v_target_kind,
                 v_target_reason, v_target_delta, v_target_effective
            FROM seedling_disposition_events WHERE id = NEW.reverses_event_id;
            IF v_target_tenant_id IS NULL THEN
                RAISE EXCEPTION 'reversal target event not found';
            END IF;
            IF v_target_tenant_id <> NEW.tenant_id OR v_target_farm_id <> NEW.farm_id THEN
                RAISE EXCEPTION 'reversal target does not belong to this tenant/farm';
            END IF;
            IF v_target_seedling_entry_id <> NEW.seedling_entry_id THEN
                RAISE EXCEPTION 'reversal target does not belong to this seedling entry';
            END IF;
            IF v_target_kind <> 'REDUCTION' THEN
                RAISE EXCEPTION 'only a REDUCTION event may be reversed';
            END IF;
            IF NEW.id = NEW.reverses_event_id THEN
                RAISE EXCEPTION 'a reversal cannot reference itself';
            END IF;
            IF NEW.quantity_delta <> -v_target_delta THEN
                RAISE EXCEPTION 'reversal quantity_delta must be the exact negation of the target event''s own delta';
            END IF;
            IF NEW.reason_code <> v_target_reason THEN
                RAISE EXCEPTION 'reversal reason_code must match the target event''s own reason_code';
            END IF;
            IF NEW.effective_time <> v_target_effective THEN
                RAISE EXCEPTION 'reversal effective_time must match the target event''s own effective_time';
            END IF;
            IF v_cmd_operation_kind <> 'CORRECT' OR v_cmd_target_event_id <> NEW.reverses_event_id THEN
                RAISE EXCEPTION 'reversal must belong to a CORRECT command targeting the same event';
            END IF;
        END IF;

        IF NEW.corrects_event_id IS NOT NULL THEN
            SELECT tenant_id, farm_id, seedling_entry_id, event_kind
            INTO v_target_tenant_id, v_target_farm_id, v_target_seedling_entry_id, v_target_kind
            FROM seedling_disposition_events WHERE id = NEW.corrects_event_id;
            IF v_target_tenant_id IS NULL THEN
                RAISE EXCEPTION 'correction target event not found';
            END IF;
            IF v_target_tenant_id <> NEW.tenant_id OR v_target_farm_id <> NEW.farm_id THEN
                RAISE EXCEPTION 'correction target does not belong to this tenant/farm';
            END IF;
            IF v_target_seedling_entry_id <> NEW.seedling_entry_id THEN
                RAISE EXCEPTION 'correction target does not belong to this seedling entry';
            END IF;
            IF v_target_kind <> 'REDUCTION' THEN
                RAISE EXCEPTION 'only a REDUCTION event may be corrected';
            END IF;
            IF v_cmd_operation_kind <> 'CORRECT' OR v_cmd_target_event_id <> NEW.corrects_event_id THEN
                RAISE EXCEPTION 'replacement must belong to a CORRECT command targeting the same event';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM seedling_disposition_events
                WHERE command_id = NEW.command_id AND event_kind = 'REVERSAL' AND reverses_event_id = NEW.corrects_event_id
            ) THEN
                RAISE EXCEPTION 'replacement must be accompanied by a reversal of the corrected event within the same command';
            END IF;
        END IF;

        v_running := v_entry_starting;
        FOR rec IN
            SELECT et, SUM(qd) AS net FROM (
                SELECT effective_time AS et, quantity_delta AS qd
                FROM seedling_disposition_events WHERE seedling_entry_id = NEW.seedling_entry_id
                UNION ALL
                SELECT NEW.effective_time, NEW.quantity_delta
            ) combined
            GROUP BY et
            ORDER BY et
        LOOP
            v_running := v_running + rec.net;
            IF v_running < 0 OR v_running > v_entry_starting THEN
                RAISE EXCEPTION 'CMP-DOMAIN-SEEDLING-003B chronological balance violated for seedling_entry %', NEW.seedling_entry_id
                    USING ERRCODE = 'check_violation';
            END IF;
        END LOOP;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

_NEW_DISPOSITION_EVENT_INTEGRITY_FUNCTION = """
    CREATE OR REPLACE FUNCTION enforce_seedling_disposition_event_insert_integrity() RETURNS trigger AS $$
    DECLARE
        v_cmd_tenant_id UUID;
        v_cmd_farm_id UUID;
        v_cmd_seedling_entry_id UUID;
        v_cmd_operation_kind TEXT;
        v_cmd_target_event_id UUID;
        v_entry_effective TIMESTAMPTZ;
        v_entry_starting INTEGER;
        v_assignment_id UUID;
        v_assignment_assigned TIMESTAMPTZ;
        v_active_assignment_id UUID;
        v_target_kind TEXT;
        v_target_tenant_id UUID;
        v_target_farm_id UUID;
        v_target_seedling_entry_id UUID;
        v_target_reason TEXT;
        v_target_delta INTEGER;
        v_target_effective TIMESTAMPTZ;
        v_running INTEGER;
        rec RECORD;
    BEGIN
        SELECT tenant_id, farm_id, seedling_entry_id, operation_kind, target_event_id
        INTO v_cmd_tenant_id, v_cmd_farm_id, v_cmd_seedling_entry_id, v_cmd_operation_kind, v_cmd_target_event_id
        FROM seedling_disposition_commands WHERE id = NEW.command_id;
        IF v_cmd_tenant_id IS NULL THEN
            RAISE EXCEPTION 'command not found';
        END IF;
        IF v_cmd_tenant_id <> NEW.tenant_id OR v_cmd_farm_id <> NEW.farm_id THEN
            RAISE EXCEPTION 'command does not belong to this tenant/farm';
        END IF;
        IF v_cmd_seedling_entry_id <> NEW.seedling_entry_id THEN
            RAISE EXCEPTION 'event does not belong to the same seedling entry as its command';
        END IF;

        SELECT effective_time, starting_living_seedling_count, batch_carrier_assignment_id
        INTO v_entry_effective, v_entry_starting, v_assignment_id
        FROM seedling_entries WHERE id = NEW.seedling_entry_id FOR UPDATE;

        SELECT assigned_effective_time INTO v_assignment_assigned
        FROM batch_carrier_assignments WHERE id = v_assignment_id;

        -- TRANSPLANT-CORRECTION-001 section 18: same forward lineage walk
        -- as the command-level trigger -- see its comment for rationale.
        WITH RECURSIVE lineage AS (
            SELECT id, released_effective_time FROM batch_carrier_assignments WHERE id = v_assignment_id
            UNION ALL
            SELECT bca.id, bca.released_effective_time
            FROM batch_carrier_assignments bca
            JOIN lineage l ON bca.restored_from_batch_carrier_assignment_id = l.id
        )
        SELECT id INTO v_active_assignment_id FROM lineage WHERE released_effective_time IS NULL LIMIT 1;
        IF v_active_assignment_id IS NULL THEN
            RAISE EXCEPTION 'assignment has already been released; no new Seedling disposition event may be created';
        END IF;

        IF NEW.effective_time < v_entry_effective THEN
            RAISE EXCEPTION 'event effective_time precedes the SeedlingEntry''s own effective_time';
        END IF;
        IF NEW.effective_time < v_assignment_assigned THEN
            RAISE EXCEPTION 'event effective_time precedes the assignment''s assigned_effective_time';
        END IF;

        IF NEW.event_kind = 'REVERSAL' THEN
            SELECT tenant_id, farm_id, seedling_entry_id, event_kind, reason_code, quantity_delta, effective_time
            INTO v_target_tenant_id, v_target_farm_id, v_target_seedling_entry_id, v_target_kind,
                 v_target_reason, v_target_delta, v_target_effective
            FROM seedling_disposition_events WHERE id = NEW.reverses_event_id;
            IF v_target_tenant_id IS NULL THEN
                RAISE EXCEPTION 'reversal target event not found';
            END IF;
            IF v_target_tenant_id <> NEW.tenant_id OR v_target_farm_id <> NEW.farm_id THEN
                RAISE EXCEPTION 'reversal target does not belong to this tenant/farm';
            END IF;
            IF v_target_seedling_entry_id <> NEW.seedling_entry_id THEN
                RAISE EXCEPTION 'reversal target does not belong to this seedling entry';
            END IF;
            IF v_target_kind <> 'REDUCTION' THEN
                RAISE EXCEPTION 'only a REDUCTION event may be reversed';
            END IF;
            IF NEW.id = NEW.reverses_event_id THEN
                RAISE EXCEPTION 'a reversal cannot reference itself';
            END IF;
            IF NEW.quantity_delta <> -v_target_delta THEN
                RAISE EXCEPTION 'reversal quantity_delta must be the exact negation of the target event''s own delta';
            END IF;
            IF NEW.reason_code <> v_target_reason THEN
                RAISE EXCEPTION 'reversal reason_code must match the target event''s own reason_code';
            END IF;
            IF NEW.effective_time <> v_target_effective THEN
                RAISE EXCEPTION 'reversal effective_time must match the target event''s own effective_time';
            END IF;
            IF v_cmd_operation_kind <> 'CORRECT' OR v_cmd_target_event_id <> NEW.reverses_event_id THEN
                RAISE EXCEPTION 'reversal must belong to a CORRECT command targeting the same event';
            END IF;
        END IF;

        IF NEW.corrects_event_id IS NOT NULL THEN
            SELECT tenant_id, farm_id, seedling_entry_id, event_kind
            INTO v_target_tenant_id, v_target_farm_id, v_target_seedling_entry_id, v_target_kind
            FROM seedling_disposition_events WHERE id = NEW.corrects_event_id;
            IF v_target_tenant_id IS NULL THEN
                RAISE EXCEPTION 'correction target event not found';
            END IF;
            IF v_target_tenant_id <> NEW.tenant_id OR v_target_farm_id <> NEW.farm_id THEN
                RAISE EXCEPTION 'correction target does not belong to this tenant/farm';
            END IF;
            IF v_target_seedling_entry_id <> NEW.seedling_entry_id THEN
                RAISE EXCEPTION 'correction target does not belong to this seedling entry';
            END IF;
            IF v_target_kind <> 'REDUCTION' THEN
                RAISE EXCEPTION 'only a REDUCTION event may be corrected';
            END IF;
            IF v_cmd_operation_kind <> 'CORRECT' OR v_cmd_target_event_id <> NEW.corrects_event_id THEN
                RAISE EXCEPTION 'replacement must belong to a CORRECT command targeting the same event';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM seedling_disposition_events
                WHERE command_id = NEW.command_id AND event_kind = 'REVERSAL' AND reverses_event_id = NEW.corrects_event_id
            ) THEN
                RAISE EXCEPTION 'replacement must be accompanied by a reversal of the corrected event within the same command';
            END IF;
        END IF;

        v_running := v_entry_starting;
        FOR rec IN
            SELECT et, SUM(qd) AS net FROM (
                SELECT effective_time AS et, quantity_delta AS qd
                FROM seedling_disposition_events WHERE seedling_entry_id = NEW.seedling_entry_id
                UNION ALL
                SELECT NEW.effective_time, NEW.quantity_delta
            ) combined
            GROUP BY et
            ORDER BY et
        LOOP
            v_running := v_running + rec.net;
            IF v_running < 0 OR v_running > v_entry_starting THEN
                RAISE EXCEPTION 'CMP-DOMAIN-SEEDLING-003B chronological balance violated for seedling_entry %', NEW.seedling_entry_id
                    USING ERRCODE = 'check_violation';
            END IF;
        END LOOP;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

_TARGET_KIND_FUNCTION = """
    CREATE FUNCTION enforce_transplant_event_correction_target_kind() RETURNS trigger AS $$
    DECLARE
        v_target_kind TEXT;
        v_target_tenant_id UUID;
    BEGIN
        IF NEW.event_kind = 'REVERSAL' THEN
            SELECT event_kind, tenant_id INTO v_target_kind, v_target_tenant_id
            FROM transplant_events WHERE id = NEW.reverses_transplant_event_id;
            IF v_target_kind IS NULL THEN
                RAISE EXCEPTION 'reversal target transplant event not found';
            END IF;
            IF v_target_tenant_id <> NEW.tenant_id THEN
                RAISE EXCEPTION 'reversal target transplant event does not belong to this tenant';
            END IF;
            IF v_target_kind NOT IN ('RECORD', 'REPLACEMENT') THEN
                RAISE EXCEPTION 'a REVERSAL may only target a RECORD or REPLACEMENT transplant event, never a REVERSAL';
            END IF;
        ELSIF NEW.event_kind = 'REPLACEMENT' THEN
            SELECT event_kind, tenant_id INTO v_target_kind, v_target_tenant_id
            FROM transplant_events WHERE id = NEW.corrects_transplant_event_id;
            IF v_target_kind IS NULL THEN
                RAISE EXCEPTION 'replacement target transplant event not found';
            END IF;
            IF v_target_tenant_id <> NEW.tenant_id THEN
                RAISE EXCEPTION 'replacement target transplant event does not belong to this tenant';
            END IF;
            IF v_target_kind NOT IN ('RECORD', 'REPLACEMENT') THEN
                RAISE EXCEPTION 'a REPLACEMENT may only correct a RECORD or REPLACEMENT transplant event, never a REVERSAL';
            END IF;
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

_PAIR_INTEGRITY_FUNCTION = """
    CREATE FUNCTION enforce_transplant_correction_pair_integrity() RETURNS trigger AS $$
    BEGIN
        IF NEW.event_kind = 'REPLACEMENT' THEN
            IF NOT EXISTS (
                SELECT 1 FROM transplant_events WHERE reverses_transplant_event_id = NEW.corrects_transplant_event_id
            ) THEN
                RAISE EXCEPTION 'a REPLACEMENT must be paired with a REVERSAL of the same target event by transaction commit';
            END IF;
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """


def upgrade() -> None:
    # --- transplant_events: correction identity ------------------------------------
    # Keep the server_default permanently (unlike a typical add-nullable-
    # false-column pattern) -- a raw-SQL INSERT that omits event_kind
    # entirely (existing direct-SQL DB-backstop tests do exactly this) must
    # keep resolving to an ordinary RECORD, exactly as before this column
    # existed. The ORM-level default= below covers the ORM insert path.
    op.add_column(
        "transplant_events", sa.Column("event_kind", sa.String(), nullable=False, server_default="RECORD")
    )
    op.add_column(
        "transplant_events",
        sa.Column(
            "reverses_transplant_event_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("transplant_events.id"), nullable=True,
        ),
    )
    op.add_column(
        "transplant_events",
        sa.Column(
            "corrects_transplant_event_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("transplant_events.id"), nullable=True,
        ),
    )
    op.add_column("transplant_events", sa.Column("correction_reason", sa.String(500), nullable=True))

    op.create_check_constraint(
        "ck_transplant_events_kind", "transplant_events", "event_kind IN ('RECORD', 'REVERSAL', 'REPLACEMENT')"
    )
    op.create_check_constraint(
        "ck_transplant_events_kind_field_shape",
        "transplant_events",
        "(event_kind = 'RECORD' AND reverses_transplant_event_id IS NULL "
        "  AND corrects_transplant_event_id IS NULL AND correction_reason IS NULL) "
        "OR (event_kind = 'REVERSAL' AND reverses_transplant_event_id IS NOT NULL "
        "  AND corrects_transplant_event_id IS NULL "
        "  AND correction_reason IS NOT NULL AND btrim(correction_reason) <> '') "
        "OR (event_kind = 'REPLACEMENT' AND reverses_transplant_event_id IS NULL "
        "  AND corrects_transplant_event_id IS NOT NULL AND correction_reason IS NULL)",
    )
    op.create_index(
        "ux_transplant_events_reverses_once", "transplant_events", ["reverses_transplant_event_id"],
        unique=True, postgresql_where=sa.text("reverses_transplant_event_id IS NOT NULL"),
    )
    op.create_index(
        "ux_transplant_events_corrects_once", "transplant_events", ["corrects_transplant_event_id"],
        unique=True, postgresql_where=sa.text("corrects_transplant_event_id IS NOT NULL"),
    )

    op.execute(_TARGET_KIND_FUNCTION)
    op.execute(
        """
        CREATE TRIGGER transplant_events_enforce_correction_target_kind
        BEFORE INSERT ON transplant_events
        FOR EACH ROW EXECUTE FUNCTION enforce_transplant_event_correction_target_kind();
        """
    )
    op.execute(_PAIR_INTEGRITY_FUNCTION)
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER transplant_events_enforce_correction_pair_integrity
        AFTER INSERT ON transplant_events
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_transplant_correction_pair_integrity();
        """
    )

    # --- batch_carrier_assignments: restoration lineage -----------------------------
    op.add_column(
        "batch_carrier_assignments",
        sa.Column(
            "opening_transplant_reversal_event_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("transplant_events.id"), nullable=True,
        ),
    )
    op.add_column(
        "batch_carrier_assignments",
        sa.Column(
            "restored_from_batch_carrier_assignment_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("batch_carrier_assignments.id"), nullable=True,
        ),
    )

    op.drop_constraint(
        "ck_batch_carrier_assignments_exactly_one_opener", "batch_carrier_assignments", type_="check"
    )
    op.create_check_constraint(
        "ck_batch_carrier_assignments_exactly_one_opener",
        "batch_carrier_assignments",
        "(CASE WHEN opening_sowing_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN opening_transplant_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN opening_batch_derivation_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN opening_transplant_reversal_event_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
    )
    op.drop_constraint(
        "ck_batch_carrier_assignments_only_sowing_origin_releasable", "batch_carrier_assignments", type_="check"
    )
    op.create_check_constraint(
        "ck_batch_carrier_assignments_only_sowing_origin_releasable",
        "batch_carrier_assignments",
        "released_by_transplant_event_id IS NULL "
        "OR opening_sowing_event_id IS NOT NULL "
        "OR opening_transplant_reversal_event_id IS NOT NULL "
        "OR opening_transplant_event_id IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_batch_carrier_assignments_restoration_opener_match",
        "batch_carrier_assignments",
        "(restored_from_batch_carrier_assignment_id IS NOT NULL) = (opening_transplant_reversal_event_id IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_batch_carrier_assignments_restoration_not_self",
        "batch_carrier_assignments",
        "restored_from_batch_carrier_assignment_id IS NULL OR restored_from_batch_carrier_assignment_id <> id",
    )

    op.create_unique_constraint(
        "uq_batch_carrier_assignments_tenant_farm_batch_id",
        "batch_carrier_assignments", ["tenant_id", "farm_id", "batch_id", "id"],
    )
    op.create_foreign_key(
        "fk_batch_carrier_assignments_opening_reversal_event",
        "batch_carrier_assignments", "transplant_events",
        ["tenant_id", "farm_id", "batch_id", "opening_transplant_reversal_event_id"],
        ["tenant_id", "farm_id", "batch_id", "id"],
    )
    op.create_foreign_key(
        "fk_batch_carrier_assignments_restored_from",
        "batch_carrier_assignments", "batch_carrier_assignments",
        ["tenant_id", "farm_id", "batch_id", "restored_from_batch_carrier_assignment_id"],
        ["tenant_id", "farm_id", "batch_id", "id"],
    )

    # --- trigger function replacements (all CREATE OR REPLACE, same names,
    # existing CREATE TRIGGER statements in earlier migrations keep firing) ---------
    op.execute(_NEW_TRANSPLANT_RECONCILIATION_FUNCTION)
    op.execute(_NEW_SOURCE_LINE_INTEGRITY_FUNCTION)
    op.execute(_NEW_CHECKPOINT_INTEGRITY_FUNCTION)
    op.execute(_NEW_ORIGIN_INTEGRITY_FUNCTION)
    op.execute(_NEW_CLOSURE_ONLY_FUNCTION)
    op.execute(_NEW_DISPOSITION_COMMAND_INTEGRITY_FUNCTION)
    op.execute(_NEW_DISPOSITION_EVENT_INTEGRITY_FUNCTION)

    # Widen the reconciliation "on open" constraint trigger's WHEN clause so
    # a reversal-opened (restored source) assignment also re-triggers
    # commit-time reconciliation of its owning REVERSAL event, exactly as an
    # ordinary transplant-opened destination assignment already does.
    op.execute(
        "DROP TRIGGER IF EXISTS batch_carrier_assignments_enforce_reconciliation_on_open ON batch_carrier_assignments"
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER batch_carrier_assignments_enforce_reconciliation_on_open
        AFTER INSERT ON batch_carrier_assignments
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW WHEN (
            NEW.opening_transplant_event_id IS NOT NULL OR NEW.opening_transplant_reversal_event_id IS NOT NULL
        )
        EXECUTE FUNCTION enforce_transplant_reconciliation();
        """
    )


def downgrade() -> None:
    bind = op.get_bind()

    unsafe = bind.execute(
        sa.text(
            "SELECT "
            "(SELECT count(*) FROM transplant_events WHERE event_kind <> 'RECORD') AS correction_count, "
            "(SELECT count(*) FROM batch_carrier_assignments "
            " WHERE opening_transplant_reversal_event_id IS NOT NULL "
            "    OR restored_from_batch_carrier_assignment_id IS NOT NULL) AS restoration_count"
        )
    ).mappings().first()
    if unsafe["correction_count"] > 0 or unsafe["restoration_count"] > 0:
        raise RuntimeError(
            "Cannot downgrade past TRANSPLANT-CORRECTION-001: "
            f"{unsafe['correction_count']} correction transplant_events row(s) and "
            f"{unsafe['restoration_count']} restoration batch_carrier_assignments row(s) exist. "
            "Downgrading would drop the columns/constraints that give this history its meaning. "
            "Move/export the affected data out-of-band before downgrading, or do not downgrade."
        )

    op.execute(
        "DROP TRIGGER IF EXISTS batch_carrier_assignments_enforce_reconciliation_on_open ON batch_carrier_assignments"
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER batch_carrier_assignments_enforce_reconciliation_on_open
        AFTER INSERT ON batch_carrier_assignments
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW WHEN (NEW.opening_transplant_event_id IS NOT NULL)
        EXECUTE FUNCTION enforce_transplant_reconciliation();
        """
    )

    op.execute(_ORIGINAL_DISPOSITION_EVENT_INTEGRITY_FUNCTION)
    op.execute(_ORIGINAL_DISPOSITION_COMMAND_INTEGRITY_FUNCTION)
    op.execute(_ORIGINAL_CLOSURE_ONLY_FUNCTION)
    op.execute(_ORIGINAL_ORIGIN_INTEGRITY_FUNCTION)
    op.execute(_ORIGINAL_CHECKPOINT_INTEGRITY_FUNCTION)
    op.execute(_ORIGINAL_SOURCE_LINE_INTEGRITY_FUNCTION)
    op.execute(_ORIGINAL_TRANSPLANT_RECONCILIATION_FUNCTION)

    op.execute(
        "DROP TRIGGER IF EXISTS transplant_events_enforce_correction_pair_integrity ON transplant_events"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_transplant_correction_pair_integrity()")
    op.execute(
        "DROP TRIGGER IF EXISTS transplant_events_enforce_correction_target_kind ON transplant_events"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_transplant_event_correction_target_kind()")

    op.drop_constraint(
        "fk_batch_carrier_assignments_restored_from", "batch_carrier_assignments", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_batch_carrier_assignments_opening_reversal_event", "batch_carrier_assignments", type_="foreignkey"
    )
    op.drop_constraint(
        "uq_batch_carrier_assignments_tenant_farm_batch_id", "batch_carrier_assignments", type_="unique"
    )
    op.drop_constraint(
        "ck_batch_carrier_assignments_restoration_not_self", "batch_carrier_assignments", type_="check"
    )
    op.drop_constraint(
        "ck_batch_carrier_assignments_restoration_opener_match",
        "batch_carrier_assignments", type_="check",
    )
    op.drop_constraint(
        "ck_batch_carrier_assignments_only_sowing_origin_releasable", "batch_carrier_assignments", type_="check"
    )
    op.create_check_constraint(
        "ck_batch_carrier_assignments_only_sowing_origin_releasable",
        "batch_carrier_assignments",
        "released_by_transplant_event_id IS NULL OR opening_sowing_event_id IS NOT NULL",
    )
    op.drop_constraint(
        "ck_batch_carrier_assignments_exactly_one_opener", "batch_carrier_assignments", type_="check"
    )
    op.create_check_constraint(
        "ck_batch_carrier_assignments_exactly_one_opener",
        "batch_carrier_assignments",
        "(CASE WHEN opening_sowing_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN opening_transplant_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN opening_batch_derivation_event_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
    )
    op.drop_column("batch_carrier_assignments", "restored_from_batch_carrier_assignment_id")
    op.drop_column("batch_carrier_assignments", "opening_transplant_reversal_event_id")

    op.drop_index("ux_transplant_events_corrects_once", table_name="transplant_events")
    op.drop_index("ux_transplant_events_reverses_once", table_name="transplant_events")
    op.drop_constraint("ck_transplant_events_kind_field_shape", "transplant_events", type_="check")
    op.drop_constraint("ck_transplant_events_kind", "transplant_events", type_="check")
    op.drop_column("transplant_events", "correction_reason")
    op.drop_column("transplant_events", "corrects_transplant_event_id")
    op.drop_column("transplant_events", "reverses_transplant_event_id")
    op.drop_column("transplant_events", "event_kind")
