"""seedling disposition lifecycle (assignment release / restoration)

SEEDLING-DISPOSITION-LIFECYCLE-001 -- closes the Seedling Disposition
source-assignment lifecycle gap: today a Disposition may reduce
authoritative source availability to exactly zero while the active
`BatchCarrierAssignment` stays open, permanently stranding the reusable
physical Seed Tray. This ticket makes an exactly-zero-exhausting
`SeedlingDispositionEvent` (REDUCTION) release the CURRENT active
assignment in its SeedlingEntry's restoration lineage, and makes
correcting that exhausting Disposition -- restoring positive biology --
open a new, active restoration assignment (never reactivating the
predecessor), following exactly the same immutable-history,
restoration-lineage pattern TRANSPLANT-CORRECTION-001 already
established, reusing the SAME shared `restored_from_batch_carrier_
assignment_id` lineage (never a parallel Disposition-only chain).

Biological authority is unchanged: the structural `SeedlingSourceCheckpoint`
chain-tip anchor plus applicable signed `SeedlingDispositionEvent` deltas
remains the sole balance formula (`get_source_available`). Disposition
events remain strictly append-only; a REVERSAL is the exact negation of
one specific REDUCTION, never a rewrite.

Three new nullable columns:

- `batch_carrier_assignments.released_by_seedling_disposition_event_id` --
  a third typed releaser (never reusing `released_by_transplant_event_id`/
  `released_by_batch_derivation_event_id`), unique when non-null (one
  REDUCTION releases at most one assignment).
- `batch_carrier_assignments.opening_seedling_disposition_reversal_
  event_id` -- the restoration opener (mirrors `opening_transplant_
  reversal_event_id`), unique when non-null (one REVERSAL opens at most
  one restored assignment) -- Seedling Disposition targets exactly one
  Seedling source, unlike Transplant's many-to-many shape.
- `seedling_disposition_commands.active_batch_stage_run_id` -- the
  CropBatch's currently-active `BatchStageRun` at command-insert time,
  mirroring `TransplantEvent.active_batch_stage_run_id` exactly. Every
  NEW command (RECORD or CORRECT) must populate it (DB-enforced);
  historical (pre-this-migration) rows keep it NULL, deliberately never
  backfilled -- a correction targeting a legacy NULL-stage-run command is
  rejected outright rather than guessing stage context.

One new nullable column carrying genuinely new physical-use-order
authority, since neither `assigned_effective_time` (caller-backdatable),
`recorded_at` (transaction-start semantics, not commit order), nor
restoration lineage alone (an unrelated new Sowing reusing a released
Carrier sets no restoration link at all) can answer "has this physical
Carrier been used by anything else since this specific assignment":

- `carriers.latest_batch_carrier_assignment_id` -- forward-only pointer to
  the most recently CREATED `BatchCarrierAssignment` for that Carrier.
  Release never changes it; only a new assignment's creation does
  (maintained by the new `maintain_carrier_latest_assignment_pointer`
  trigger, centralizing pointer maintenance in exactly one place rather
  than duplicating it across five Python creators). Backfilled ONLY from
  each Carrier's currently-active assignment (unambiguous because
  `ux_batch_carrier_assignments_active_carrier` already guarantees at
  most one) -- no historical physical-use chronology before that point is
  reconstructed or needed; correcting an exhausting Disposition later
  checks `Carrier.latest_batch_carrier_assignment_id == <released
  predecessor>.id` under `Carrier FOR UPDATE`, which is blind to any use
  before the predecessor's own creation and permanently blocks (even past
  a subsequent release) once anything newer has claimed the Carrier.

Five trigger functions updated via `CREATE OR REPLACE` (existing
`CREATE TRIGGER` statements in earlier migrations keep firing against the
new bodies):

1. `enforce_batch_carrier_assignment_closure_only_v2` -- protected-column
   list grows the new opener column; the "exactly one typed releaser"
   branch grows a third arm validating the Disposition releaser
   (REDUCTION-kind, same batch via its owning command, release time
   match, membership in the correct SeedlingEntry's restoration lineage,
   and -- the hardest single piece of this ticket -- an independent,
   checkpoint-aware re-derivation proving authoritative post-event source
   availability is exactly zero, never the cruder whole-entry-history
   check `enforce_seedling_disposition_event_insert_integrity` already
   uses for its own, different purpose).
2. `enforce_batch_carrier_assignment_origin_insert_integrity_v2` -- new
   branch for `opening_seedling_disposition_reversal_event_id`, mirroring
   the existing `opening_transplant_reversal_event_id` branch exactly
   (REVERSAL-kind, same batch, effective-time match, same-Carrier/
   same-stage-run/released-by-exact-target predecessor proof).
3. `enforce_seedling_disposition_command_insert_integrity` -- the
   "some assignment in this lineage must be active" gate generalizes to a
   chain-TIP resolution (structural `NOT EXISTS` successor, exactly the
   established checkpoint chain-tip pattern): if the tip is released,
   continuation is permitted only for a CORRECT command whose
   `target_event_id` exactly matches the tip's own
   `released_by_seedling_disposition_event_id` -- released by Transplant,
   Batch Derivation, or a DIFFERENT Disposition event remains rejected.
   Also gains the new stage-run-identity requirement: every NEW command
   must carry a non-null `active_batch_stage_run_id` referencing an
   open `BatchStageRun` for the same tenant/farm/batch.
4. `enforce_seedling_disposition_event_insert_integrity` -- the identical
   chain-tip generalization applied at the EVENT level (this trigger
   independently re-derives the same "some assignment must be active"
   gate the command trigger already enforces): a REVERSAL reopening
   exactly the assignment its own `reverses_event_id` released is the one
   legitimate exception.

One new trigger:

- `maintain_carrier_latest_assignment_pointer` (`AFTER INSERT ON
  batch_carrier_assignments`) -- the single, centralized authority
  maintaining `carriers.latest_batch_carrier_assignment_id`; every
  production assignment-creation path (Sowing, Transplant
  destination/restoration, Batch Derivation output, and now Disposition
  restoration) already locks the Carrier row before insert (the existing,
  unchanged global lock order `CropBatch(es) -> Carrier(s) -> assignment
  insert`), so this trigger's own implicit `UPDATE carriers` reuses that
  already-held row lock -- no new lock ordering is introduced.

Downgrade guard: refuses if any `BatchCarrierAssignment.released_by_
seedling_disposition_event_id`/`opening_seedling_disposition_reversal_
event_id` or `SeedlingDispositionCommand.active_batch_stage_run_id` is
non-null -- mirrors `f4a8c1e93d27`'s own guard precedent exactly. The
Carrier pointer backfill alone never blocks downgrade (it is populated
unconditionally during THIS upgrade for every Carrier with a currently
active assignment, regardless of whether the new Disposition lifecycle
is ever used) -- only genuine new semantic history does.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e2a7c9f4b816"
down_revision: str | None = "f4a8c1e93d27"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


# =====================================================================
# Original trigger function bodies (pre-this-migration), captured
# verbatim for downgrade -- restoring each function to exactly what it
# was after f4a8c1e93d27, never re-deriving from memory.
# =====================================================================

_ORIGINAL_CLOSURE_ONLY_FUNCTION = """
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

_ORIGINAL_DISPOSITION_COMMAND_INTEGRITY_FUNCTION = """
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


# =====================================================================
# New trigger function bodies (this migration).
# =====================================================================

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

_NEW_CLOSURE_ONLY_FUNCTION = """
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
                -- SEEDLING-DISPOSITION-LIFECYCLE-001 section 32: widened
                -- again -- a Disposition-restored source assignment is
                -- equally eligible for ordinary future Transplant exhaustion.
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
            -- SEEDLING-DISPOSITION-LIFECYCLE-001: released_by_seedling_
            -- disposition_event_id branch. Independently re-derives the
            -- SAME checkpoint-anchored authority get_source_available uses
            -- (never the cruder whole-entry-history walk) to prove this
            -- REDUCTION genuinely leaves availability at exactly zero --
            -- unreachable via direct SQL otherwise.
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
        v_predecessor_released_by_disposition UUID;
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
        ELSIF NEW.opening_seedling_disposition_reversal_event_id IS NOT NULL THEN
            -- SEEDLING-DISPOSITION-LIFECYCLE-001: mirrors the
            -- opening_transplant_reversal_event_id branch exactly, resolved
            -- through the event's owning command for batch_id (Seedling
            -- Disposition events carry no batch_id column of their own).
            SELECT c.batch_id, e.effective_time, e.event_kind, e.reverses_event_id
            INTO v_event_batch_id, v_event_effective, v_reversal_kind, v_reverses_id
            FROM seedling_disposition_events e
            JOIN seedling_disposition_commands c ON c.id = e.command_id
            WHERE e.id = NEW.opening_seedling_disposition_reversal_event_id;
            IF v_event_batch_id IS NULL THEN
                RAISE EXCEPTION 'opening seedling disposition reversal event not found';
            END IF;
            IF v_reversal_kind <> 'REVERSAL' THEN
                RAISE EXCEPTION 'opening_seedling_disposition_reversal_event_id must reference a REVERSAL-kind seedling disposition event';
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
            SELECT carrier_id, batch_stage_run_id, released_by_seedling_disposition_event_id
            INTO v_predecessor_carrier_id, v_predecessor_run_id, v_predecessor_released_by_disposition
            FROM batch_carrier_assignments WHERE id = NEW.restored_from_batch_carrier_assignment_id;
            IF v_predecessor_carrier_id IS DISTINCT FROM NEW.carrier_id THEN
                RAISE EXCEPTION 'restored assignment must be for the same physical Carrier as its predecessor';
            END IF;
            IF v_predecessor_run_id IS DISTINCT FROM NEW.batch_stage_run_id THEN
                RAISE EXCEPTION 'restored assignment must preserve its predecessor''s own stage run';
            END IF;
            IF v_predecessor_released_by_disposition IS DISTINCT FROM v_reverses_id THEN
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

_NEW_DISPOSITION_COMMAND_INTEGRITY_FUNCTION = """
    CREATE OR REPLACE FUNCTION enforce_seedling_disposition_command_insert_integrity() RETURNS trigger AS $$
    DECLARE
        v_entry_tenant_id UUID;
        v_entry_farm_id UUID;
        v_entry_batch_id UUID;
        v_entry_assignment_id UUID;
        v_tip_assignment_id UUID;
        v_tip_released TIMESTAMPTZ;
        v_tip_released_by_disposition UUID;
        v_target_seedling_entry_id UUID;
        v_target_tenant_id UUID;
        v_target_farm_id UUID;
        v_stage_run_batch_id UUID;
        v_stage_run_exited TIMESTAMPTZ;
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

        -- SEEDLING-DISPOSITION-LIFECYCLE-001 section 12: generalizes the
        -- old "some assignment must be active" gate to a structural
        -- chain-TIP resolution (NOT EXISTS successor, the same pattern
        -- already used for checkpoint chain-tip resolution). If the tip is
        -- released, a new command is permitted ONLY when it is itself the
        -- CORRECT command reopening exactly what its own target released --
        -- released by Transplant, Batch Derivation, or a DIFFERENT
        -- Disposition event remains rejected.
        WITH RECURSIVE lineage AS (
            SELECT id FROM batch_carrier_assignments WHERE id = v_entry_assignment_id
            UNION ALL
            SELECT bca.id FROM batch_carrier_assignments bca
            JOIN lineage l ON bca.restored_from_batch_carrier_assignment_id = l.id
        )
        SELECT id INTO v_tip_assignment_id FROM lineage
        WHERE NOT EXISTS (SELECT 1 FROM batch_carrier_assignments nxt WHERE nxt.restored_from_batch_carrier_assignment_id = lineage.id);

        SELECT released_effective_time, released_by_seedling_disposition_event_id
        INTO v_tip_released, v_tip_released_by_disposition
        FROM batch_carrier_assignments WHERE id = v_tip_assignment_id;

        IF v_tip_released IS NOT NULL THEN
            IF NEW.operation_kind <> 'CORRECT' OR v_tip_released_by_disposition IS DISTINCT FROM NEW.target_event_id THEN
                RAISE EXCEPTION 'assignment has already been released; no new Seedling disposition command may be created';
            END IF;
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

        -- SEEDLING-DISPOSITION-LIFECYCLE-001 section 13/14: every NEW
        -- command (RECORD or CORRECT) must carry a valid, currently-open
        -- stage-run identity. Historical (pre-this-migration) rows are
        -- never re-validated by this trigger (it only fires on INSERT), so
        -- their NULL stays exactly as it was.
        IF NEW.active_batch_stage_run_id IS NULL THEN
            RAISE EXCEPTION 'active_batch_stage_run_id is required for every new seedling disposition command';
        END IF;
        SELECT batch_id, exited_effective_time INTO v_stage_run_batch_id, v_stage_run_exited
        FROM batch_stage_runs WHERE id = NEW.active_batch_stage_run_id;
        IF v_stage_run_batch_id IS NULL THEN
            RAISE EXCEPTION 'active_batch_stage_run_id references a batch_stage_run that does not exist';
        END IF;
        IF v_stage_run_batch_id <> NEW.batch_id THEN
            RAISE EXCEPTION 'active_batch_stage_run_id does not belong to this command''s batch';
        END IF;
        IF v_stage_run_exited IS NOT NULL THEN
            RAISE EXCEPTION 'active_batch_stage_run_id must reference the batch''s currently-open stage run';
        END IF;

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
        v_tip_assignment_id UUID;
        v_tip_released TIMESTAMPTZ;
        v_tip_released_by_disposition UUID;
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

        -- SEEDLING-DISPOSITION-LIFECYCLE-001 section 12: same chain-TIP
        -- generalization as the command-level trigger (two statements: the
        -- CTE resolves the tip id, a separate plain SELECT reads its
        -- state -- a WITH RECURSIVE alias cannot be referenced across
        -- separate statements). A REVERSAL reopening exactly the
        -- assignment its own reverses_event_id released is the one
        -- legitimate exception to "the tip must be active".
        WITH RECURSIVE lineage AS (
            SELECT id FROM batch_carrier_assignments WHERE id = v_assignment_id
            UNION ALL
            SELECT bca.id FROM batch_carrier_assignments bca
            JOIN lineage l ON bca.restored_from_batch_carrier_assignment_id = l.id
        )
        SELECT id INTO v_tip_assignment_id FROM lineage
        WHERE NOT EXISTS (SELECT 1 FROM batch_carrier_assignments nxt WHERE nxt.restored_from_batch_carrier_assignment_id = lineage.id);

        SELECT released_effective_time, released_by_seedling_disposition_event_id
        INTO v_tip_released, v_tip_released_by_disposition
        FROM batch_carrier_assignments WHERE id = v_tip_assignment_id;

        IF v_tip_released IS NOT NULL THEN
            IF NEW.event_kind <> 'REVERSAL' OR v_tip_released_by_disposition IS DISTINCT FROM NEW.reverses_event_id THEN
                RAISE EXCEPTION 'assignment has already been released; no new Seedling disposition event may be created';
            END IF;
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

_CARRIER_POINTER_TRIGGER_FUNCTION = """
    CREATE OR REPLACE FUNCTION maintain_carrier_latest_assignment_pointer() RETURNS trigger AS $$
    BEGIN
        UPDATE carriers SET latest_batch_carrier_assignment_id = NEW.id WHERE id = NEW.carrier_id;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """


def upgrade() -> None:
    # --- new columns -----------------------------------------------------------------
    op.add_column(
        "carriers", sa.Column("latest_batch_carrier_assignment_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        "batch_carrier_assignments",
        sa.Column("released_by_seedling_disposition_event_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "batch_carrier_assignments",
        sa.Column("opening_seedling_disposition_reversal_event_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "seedling_disposition_commands",
        sa.Column("active_batch_stage_run_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    # --- unique-constraint FK targets ------------------------------------------------
    op.create_unique_constraint(
        "uq_seedling_disposition_events_tenant_farm_id", "seedling_disposition_events", ["tenant_id", "farm_id", "id"],
    )
    op.create_unique_constraint(
        "uq_batch_carrier_assignments_tenant_farm_id_carrier",
        "batch_carrier_assignments", ["tenant_id", "farm_id", "id", "carrier_id"],
    )

    # --- Carrier latest-assignment pointer backfill (current-state only) ------------
    # Unambiguous because ux_batch_carrier_assignments_active_carrier already
    # guarantees at most one active assignment per Carrier -- no historical
    # physical-use chronology before this point is reconstructed.
    op.execute(
        """
        UPDATE carriers c
        SET latest_batch_carrier_assignment_id = bca.id
        FROM batch_carrier_assignments bca
        WHERE bca.carrier_id = c.id AND bca.released_effective_time IS NULL
        """
    )

    # --- FKs --------------------------------------------------------------------------
    op.create_foreign_key(
        "fk_carriers_latest_assignment", "carriers", "batch_carrier_assignments",
        ["tenant_id", "farm_id", "latest_batch_carrier_assignment_id", "id"],
        ["tenant_id", "farm_id", "id", "carrier_id"],
    )
    op.create_foreign_key(
        "fk_batch_carrier_assignments_released_by_disposition_event",
        "batch_carrier_assignments", "seedling_disposition_events",
        ["tenant_id", "farm_id", "released_by_seedling_disposition_event_id"],
        ["tenant_id", "farm_id", "id"],
    )
    op.create_foreign_key(
        "fk_batch_carrier_assignments_opening_disposition_reversal_event",
        "batch_carrier_assignments", "seedling_disposition_events",
        ["tenant_id", "farm_id", "opening_seedling_disposition_reversal_event_id"],
        ["tenant_id", "farm_id", "id"],
    )
    op.create_foreign_key(
        "fk_seedling_disposition_commands_active_stage_run",
        "seedling_disposition_commands", "batch_stage_runs",
        ["tenant_id", "farm_id", "batch_id", "active_batch_stage_run_id"],
        ["tenant_id", "farm_id", "batch_id", "id"],
    )

    # --- widened / new CHECK constraints on batch_carrier_assignments ---------------
    op.drop_constraint(
        "ck_batch_carrier_assignments_exactly_one_opener", "batch_carrier_assignments", type_="check"
    )
    op.create_check_constraint(
        "ck_batch_carrier_assignments_exactly_one_opener",
        "batch_carrier_assignments",
        "(CASE WHEN opening_sowing_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN opening_transplant_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN opening_batch_derivation_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN opening_transplant_reversal_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN opening_seedling_disposition_reversal_event_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
    )
    op.drop_constraint(
        "ck_batch_carrier_assignments_release_fields_together", "batch_carrier_assignments", type_="check"
    )
    op.create_check_constraint(
        "ck_batch_carrier_assignments_release_fields_together",
        "batch_carrier_assignments",
        "(released_effective_time IS NULL) = "
        "(released_by_transplant_event_id IS NULL AND released_by_batch_derivation_event_id IS NULL "
        "AND released_by_seedling_disposition_event_id IS NULL)",
    )
    op.drop_constraint(
        "ck_batch_carrier_assignments_at_most_one_releaser", "batch_carrier_assignments", type_="check"
    )
    op.create_check_constraint(
        "ck_batch_carrier_assignments_at_most_one_releaser",
        "batch_carrier_assignments",
        "(CASE WHEN released_by_transplant_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN released_by_batch_derivation_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN released_by_seedling_disposition_event_id IS NOT NULL THEN 1 ELSE 0 END) <= 1",
    )
    op.create_check_constraint(
        "ck_batch_carrier_assignments_only_seedling_source_releasable",
        "batch_carrier_assignments",
        "released_by_seedling_disposition_event_id IS NULL "
        "OR opening_sowing_event_id IS NOT NULL "
        "OR opening_transplant_reversal_event_id IS NOT NULL "
        "OR opening_seedling_disposition_reversal_event_id IS NOT NULL",
    )
    # SEEDLING-DISPOSITION-LIFECYCLE-001 section 32: widen the pre-existing
    # (TRANSPLANT-CORRECTION-001) sowing-origin-releasable CHECK too -- a
    # Disposition-restored assignment is equally eligible for ordinary
    # future Transplant exhaustion, mirroring the closure trigger's own
    # widened branch.
    op.drop_constraint(
        "ck_batch_carrier_assignments_only_sowing_origin_releasable", "batch_carrier_assignments", type_="check"
    )
    op.create_check_constraint(
        "ck_batch_carrier_assignments_only_sowing_origin_releasable",
        "batch_carrier_assignments",
        "released_by_transplant_event_id IS NULL "
        "OR opening_sowing_event_id IS NOT NULL "
        "OR opening_transplant_reversal_event_id IS NOT NULL "
        "OR opening_transplant_event_id IS NOT NULL "
        "OR opening_seedling_disposition_reversal_event_id IS NOT NULL",
    )
    op.drop_constraint(
        "ck_batch_carrier_assignments_restoration_opener_match", "batch_carrier_assignments", type_="check"
    )
    op.create_check_constraint(
        "ck_batch_carrier_assignments_restoration_opener_match",
        "batch_carrier_assignments",
        "(restored_from_batch_carrier_assignment_id IS NOT NULL) = "
        "(opening_transplant_reversal_event_id IS NOT NULL "
        "OR opening_seedling_disposition_reversal_event_id IS NOT NULL)",
    )

    # --- new partial unique indexes ---------------------------------------------------
    op.create_index(
        "ux_batch_carrier_assignments_released_by_disposition_once",
        "batch_carrier_assignments", ["released_by_seedling_disposition_event_id"],
        unique=True, postgresql_where=sa.text("released_by_seedling_disposition_event_id IS NOT NULL"),
    )
    op.create_index(
        "ux_batch_carrier_assignments_opened_by_disposition_once",
        "batch_carrier_assignments", ["opening_seedling_disposition_reversal_event_id"],
        unique=True, postgresql_where=sa.text("opening_seedling_disposition_reversal_event_id IS NOT NULL"),
    )

    # --- trigger function replacements (CREATE OR REPLACE; existing CREATE
    # TRIGGER statements in earlier migrations keep firing against the new
    # bodies unchanged) -----------------------------------------------------------------
    op.execute(_NEW_CLOSURE_ONLY_FUNCTION)
    op.execute(_NEW_ORIGIN_INTEGRITY_FUNCTION)
    op.execute(_NEW_DISPOSITION_COMMAND_INTEGRITY_FUNCTION)
    op.execute(_NEW_DISPOSITION_EVENT_INTEGRITY_FUNCTION)

    # --- new Carrier latest-assignment pointer trigger -------------------------------
    op.execute(_CARRIER_POINTER_TRIGGER_FUNCTION)
    op.execute(
        """
        CREATE TRIGGER batch_carrier_assignments_maintain_carrier_pointer
        AFTER INSERT ON batch_carrier_assignments
        FOR EACH ROW EXECUTE FUNCTION maintain_carrier_latest_assignment_pointer();
        """
    )


def downgrade() -> None:
    bind = op.get_bind()

    unsafe = bind.execute(
        sa.text(
            "SELECT "
            "(SELECT count(*) FROM batch_carrier_assignments "
            " WHERE released_by_seedling_disposition_event_id IS NOT NULL "
            "    OR opening_seedling_disposition_reversal_event_id IS NOT NULL) AS lifecycle_count, "
            "(SELECT count(*) FROM seedling_disposition_commands "
            " WHERE active_batch_stage_run_id IS NOT NULL) AS stage_run_count"
        )
    ).mappings().first()
    if unsafe["lifecycle_count"] > 0 or unsafe["stage_run_count"] > 0:
        raise RuntimeError(
            "Cannot downgrade past SEEDLING-DISPOSITION-LIFECYCLE-001: "
            f"{unsafe['lifecycle_count']} batch_carrier_assignments row(s) carry new Disposition-driven "
            f"release/restoration history and {unsafe['stage_run_count']} seedling_disposition_commands "
            "row(s) carry new stage-run identity. Downgrading would drop the columns/constraints that give "
            "this history its meaning. Move/export the affected data out-of-band before downgrading, or do "
            "not downgrade. (The Carrier latest-assignment pointer backfill alone never blocks downgrade.)"
        )

    op.execute(
        "DROP TRIGGER IF EXISTS batch_carrier_assignments_maintain_carrier_pointer ON batch_carrier_assignments"
    )
    op.execute("DROP FUNCTION IF EXISTS maintain_carrier_latest_assignment_pointer()")

    op.execute(_ORIGINAL_DISPOSITION_EVENT_INTEGRITY_FUNCTION)
    op.execute(_ORIGINAL_DISPOSITION_COMMAND_INTEGRITY_FUNCTION)
    op.execute(_ORIGINAL_ORIGIN_INTEGRITY_FUNCTION)
    op.execute(_ORIGINAL_CLOSURE_ONLY_FUNCTION)

    op.drop_index("ux_batch_carrier_assignments_opened_by_disposition_once", "batch_carrier_assignments")
    op.drop_index("ux_batch_carrier_assignments_released_by_disposition_once", "batch_carrier_assignments")

    op.drop_constraint(
        "ck_batch_carrier_assignments_restoration_opener_match", "batch_carrier_assignments", type_="check"
    )
    op.create_check_constraint(
        "ck_batch_carrier_assignments_restoration_opener_match",
        "batch_carrier_assignments",
        "(restored_from_batch_carrier_assignment_id IS NOT NULL) = (opening_transplant_reversal_event_id IS NOT NULL)",
    )
    op.drop_constraint(
        "ck_batch_carrier_assignments_only_seedling_source_releasable", "batch_carrier_assignments", type_="check"
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
    op.drop_constraint(
        "ck_batch_carrier_assignments_at_most_one_releaser", "batch_carrier_assignments", type_="check"
    )
    op.create_check_constraint(
        "ck_batch_carrier_assignments_at_most_one_releaser",
        "batch_carrier_assignments",
        "NOT (released_by_transplant_event_id IS NOT NULL AND released_by_batch_derivation_event_id IS NOT NULL)",
    )
    op.drop_constraint(
        "ck_batch_carrier_assignments_release_fields_together", "batch_carrier_assignments", type_="check"
    )
    op.create_check_constraint(
        "ck_batch_carrier_assignments_release_fields_together",
        "batch_carrier_assignments",
        "(released_effective_time IS NULL) = "
        "(released_by_transplant_event_id IS NULL AND released_by_batch_derivation_event_id IS NULL)",
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
        "fk_seedling_disposition_commands_active_stage_run", "seedling_disposition_commands", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_batch_carrier_assignments_opening_disposition_reversal_event",
        "batch_carrier_assignments", type_="foreignkey",
    )
    op.drop_constraint(
        "fk_batch_carrier_assignments_released_by_disposition_event",
        "batch_carrier_assignments", type_="foreignkey",
    )
    op.drop_constraint("fk_carriers_latest_assignment", "carriers", type_="foreignkey")

    op.drop_constraint(
        "uq_batch_carrier_assignments_tenant_farm_id_carrier", "batch_carrier_assignments", type_="unique"
    )
    op.drop_constraint(
        "uq_seedling_disposition_events_tenant_farm_id", "seedling_disposition_events", type_="unique"
    )

    op.drop_column("seedling_disposition_commands", "active_batch_stage_run_id")
    op.drop_column("batch_carrier_assignments", "opening_seedling_disposition_reversal_event_id")
    op.drop_column("batch_carrier_assignments", "released_by_seedling_disposition_event_id")
    op.drop_column("carriers", "latest_batch_carrier_assignment_id")
