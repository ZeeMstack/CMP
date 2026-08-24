"""production biological disposition

LEAFY-OPS-001 -- authoritative living-population management for Leafy
Production after plants have been transplanted onto a Production
Cultivation Plate, before Harvest (out of scope). Mirrors the proven
`SeedlingDisposition`/`SEEDLING-DISPOSITION-LIFECYCLE-001` shape closely,
adapted for a domain with no `SeedlingEntry`-equivalent anchor row: three
new tables (`production_disposition_reasons`,
`production_disposition_commands`, `production_disposition_events`), and a
fourth typed opener/releaser pair on `batch_carrier_assignments`
(`opening_production_disposition_reversal_event_id`/`released_by_
production_disposition_event_id`), following the exact template
`e2a7c9f4b816` already established for adding the third (Seedling
Disposition) pair.

The one genuinely new piece, absent from every prior precedent: a stable
population-lineage identity. `TransplantDestinationLine.assigned_plant_
count` (already the correct, unchanged opening-population authority for the
ORIGINAL transplant-created BCA -- see `BatchCarrierPopulationCheckpoint`'s
own docstring for why NO second opening-population table is introduced
here) only exists for the very first BCA in a lineage; a Production
Disposition correction that restores positive population after a zero-
exhausting event creates a NEW BCA generation (never reactivates the old
one), and that new generation has no `TransplantDestinationLine` of its
own. `batch_carrier_assignments.population_root_batch_carrier_assignment_id`
(new, self-referencing, nullable) solves this: an ordinary transplant-
created destination BCA self-references its own id (it IS the root); a
Production-Disposition-restored BCA copies its predecessor's root forward
unchanged. Every `ProductionDispositionEvent` carries both its actual BCA
generation (`batch_carrier_assignment_id`, audit truth) and that generation's
own root (`population_root_batch_carrier_assignment_id`, denormalized and
trigger-verified against the BCA's own stored value -- never trusted from
the API) -- authoritative living population is then one flat, non-recursive
`TransplantDestinationLine.assigned_plant_count (root) + SUM(quantity_delta
WHERE population_root_batch_carrier_assignment_id = root)`, correct across
any number of restoration generations (A -> B -> C -> ...) with no per-query
lineage walk.

`population_root_batch_carrier_assignment_id` is set at INSERT time by the
CALLER (mirrors every other server-derived-but-caller-supplied field in this
codebase, e.g. `BatchCarrierPopulationCheckpoint.remainder_after`) --
`transplant_service.py`'s existing destination-BCA-creation code now
self-references (one-line, purely additive change, no other 005A/005B
behavior touched); this migration's own trigger widening sets it for a
Production-Disposition restoration. The widened
`enforce_batch_carrier_assignment_origin_insert_integrity_v2` VALIDATES
(never silently computes/overrides) that the supplied value is correct for
each opener branch; the widened `enforce_batch_carrier_assignment_closure_
only_v2` adds `population_root_batch_carrier_assignment_id` to the set of
columns that may NEVER change on UPDATE, alongside its own existing
released-fields-only rule -- immutability enforced at the DB level, not
merely service convention.

Backfill (transactional, in this migration, no fabricated history): every
EXISTING `opening_transplant_event_id`-opened BCA (Nursery AND Production
Cultivation Plate destinations alike -- the root concept is carrier-type
generic) receives `population_root_batch_carrier_assignment_id = id`. This
is safe and unambiguous because no BCA opened by
`opening_production_disposition_reversal_event_id` can possibly exist yet
(brand new column, first migration to ever populate it) -- every existing
transplant destination is, by definition, an unrestored root. No
`production_disposition_events` backfill: none could have pre-existed this
migration.

Explicitly NOT touched: `BatchCarrierPopulationCheckpoint`
(`transplant_source_line_id` stays NOT NULL, no cause column added, no
generalization -- see its own docstring and `docs/domain/
TRANSPLANTATION_MODEL.md`), `SeedlingDispositionEvent`/`SeedlingDisposition
Command`/`SeedlingDispositionReason` (unchanged, separate authority, not
this ticket's table), InterSalads.

Revision ID: a5c9e21f7b64
Revises: 1ffda251c3a8
Create Date: 2026-08-23 15:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a5c9e21f7b64"
down_revision: str | None = "1ffda251c3a8"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_APPROVED_REASONS = [
    ("dead", "Confirmed dead"),
    ("disease_removal", "Disease -- removed"),
    ("pest_damage", "Pest damage -- removed"),
    ("mechanical_damage", "Mechanical/physical damage -- removed"),
    ("quality_removal", "Quality removal"),
    ("other", "Other (note required)"),
]

_CHRONOLOGICAL_BALANCE_MARKER = "CMP-DOMAIN-PRODUCTION-001 chronological balance violated"

# =====================================================================
# production_disposition_commands / events -- own insert-integrity
# triggers, structurally the same three-trigger shape (insert-integrity +
# append-only x2) SeedlingDisposition already established, minus the
# SeedlingEntry-ownership/lineage-walk checks (no separate "entry" identity
# exists for Production population -- the root BCA itself, resolved via
# population_root_batch_carrier_assignment_id, is that identity).
# =====================================================================

_COMMAND_INTEGRITY_FUNCTION = """
    CREATE FUNCTION enforce_production_disposition_command_insert_integrity() RETURNS trigger AS $$
    DECLARE
        v_assignment_tenant_id UUID;
        v_assignment_farm_id UUID;
        v_assignment_batch_id UUID;
        v_assignment_released TIMESTAMPTZ;
        v_target_assignment_id UUID;
        v_target_tenant_id UUID;
        v_target_farm_id UUID;
    BEGIN
        SELECT tenant_id, farm_id, batch_id, released_effective_time
        INTO v_assignment_tenant_id, v_assignment_farm_id, v_assignment_batch_id, v_assignment_released
        FROM batch_carrier_assignments WHERE id = NEW.batch_carrier_assignment_id;
        IF v_assignment_tenant_id IS NULL THEN
            RAISE EXCEPTION 'batch carrier assignment not found';
        END IF;
        IF v_assignment_tenant_id <> NEW.tenant_id OR v_assignment_farm_id <> NEW.farm_id THEN
            RAISE EXCEPTION 'batch carrier assignment does not belong to this tenant/farm';
        END IF;
        IF v_assignment_batch_id <> NEW.batch_id THEN
            RAISE EXCEPTION 'batch carrier assignment does not belong to this batch';
        END IF;

        IF NEW.operation_kind = 'RECORD' THEN
            IF v_assignment_released IS NOT NULL THEN
                RAISE EXCEPTION 'assignment has already been released; no new Production disposition RECORD command may target it';
            END IF;
        ELSE
            SELECT batch_carrier_assignment_id, tenant_id, farm_id
            INTO v_target_assignment_id, v_target_tenant_id, v_target_farm_id
            FROM production_disposition_events WHERE id = NEW.target_event_id;
            IF v_target_assignment_id IS NULL THEN
                RAISE EXCEPTION 'target event not found';
            END IF;
            IF v_target_tenant_id <> NEW.tenant_id OR v_target_farm_id <> NEW.farm_id THEN
                RAISE EXCEPTION 'target event does not belong to this tenant/farm';
            END IF;
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

_EVENT_INTEGRITY_FUNCTION = """
    CREATE FUNCTION enforce_production_disposition_event_insert_integrity() RETURNS trigger AS $$
    DECLARE
        v_cmd_tenant_id UUID;
        v_cmd_farm_id UUID;
        v_cmd_batch_id UUID;
        v_cmd_operation_kind TEXT;
        v_cmd_target_event_id UUID;
        v_assignment_root UUID;
        v_assignment_assigned TIMESTAMPTZ;
        v_assignment_released TIMESTAMPTZ;
        v_root_opening INTEGER;
        v_target_kind TEXT;
        v_target_tenant_id UUID;
        v_target_root UUID;
        v_target_reason TEXT;
        v_target_delta INTEGER;
        v_target_effective TIMESTAMPTZ;
        v_running INTEGER;
        rec RECORD;
    BEGIN
        SELECT tenant_id, farm_id, batch_id, operation_kind, target_event_id
        INTO v_cmd_tenant_id, v_cmd_farm_id, v_cmd_batch_id, v_cmd_operation_kind, v_cmd_target_event_id
        FROM production_disposition_commands WHERE id = NEW.command_id;
        IF v_cmd_tenant_id IS NULL THEN
            RAISE EXCEPTION 'command not found';
        END IF;
        IF v_cmd_tenant_id <> NEW.tenant_id OR v_cmd_farm_id <> NEW.farm_id THEN
            RAISE EXCEPTION 'command does not belong to this tenant/farm';
        END IF;

        -- Lock the population root BCA -- serializes concurrent event
        -- inserts for the same lineage (defense-in-depth behind the
        -- service's own CropBatch-first lock).
        SELECT population_root_batch_carrier_assignment_id, assigned_effective_time, released_effective_time
        INTO v_assignment_root, v_assignment_assigned, v_assignment_released
        FROM batch_carrier_assignments WHERE id = NEW.batch_carrier_assignment_id FOR UPDATE;

        IF NEW.event_kind = 'REDUCTION' THEN
            IF v_assignment_released IS NOT NULL THEN
                RAISE EXCEPTION 'batch carrier assignment is already released; no new REDUCTION may target it';
            END IF;
        END IF;

        IF v_assignment_root IS NULL THEN
            RAISE EXCEPTION 'batch carrier assignment has no population root; not a valid Production population lineage member';
        END IF;
        IF v_assignment_root <> NEW.population_root_batch_carrier_assignment_id THEN
            RAISE EXCEPTION 'event population_root_batch_carrier_assignment_id does not match its own BCA''s stored root';
        END IF;

        IF NEW.event_kind = 'REDUCTION' AND NEW.effective_time < v_assignment_assigned THEN
            RAISE EXCEPTION 'effective_time precedes the assignment''s assigned_effective_time';
        END IF;

        IF NEW.event_kind = 'REVERSAL' THEN
            SELECT event_kind, reason_code, quantity_delta, effective_time, tenant_id,
                   population_root_batch_carrier_assignment_id
            INTO v_target_kind, v_target_reason, v_target_delta, v_target_effective, v_target_tenant_id,
                 v_target_root
            FROM production_disposition_events WHERE id = NEW.reverses_event_id;
            IF v_target_kind IS NULL THEN
                RAISE EXCEPTION 'reversed event not found';
            END IF;
            IF v_target_kind <> 'REDUCTION' THEN
                RAISE EXCEPTION 'a REVERSAL may only reverse a REDUCTION';
            END IF;
            IF v_target_tenant_id <> NEW.tenant_id THEN
                RAISE EXCEPTION 'reversed event does not belong to this tenant';
            END IF;
            IF v_target_root <> NEW.population_root_batch_carrier_assignment_id THEN
                RAISE EXCEPTION 'a REVERSAL must share its target''s own population root';
            END IF;
            IF NEW.reason_code <> v_target_reason THEN
                RAISE EXCEPTION 'REVERSAL reason_code must match the reversed event exactly';
            END IF;
            IF NEW.quantity_delta <> -v_target_delta THEN
                RAISE EXCEPTION 'REVERSAL quantity_delta must be the exact negation of the reversed event';
            END IF;
            IF NEW.effective_time <> v_target_effective THEN
                RAISE EXCEPTION 'REVERSAL effective_time must equal the reversed event''s own effective time';
            END IF;
            IF v_cmd_operation_kind <> 'CORRECT' OR v_cmd_target_event_id <> NEW.reverses_event_id THEN
                RAISE EXCEPTION 'REVERSAL must belong to a CORRECT command targeting exactly the reversed event';
            END IF;
        END IF;

        IF NEW.corrects_event_id IS NOT NULL THEN
            SELECT event_kind, population_root_batch_carrier_assignment_id
            INTO v_target_kind, v_target_root
            FROM production_disposition_events WHERE id = NEW.corrects_event_id;
            IF v_target_kind IS NULL THEN
                RAISE EXCEPTION 'corrected event not found';
            END IF;
            IF v_target_kind <> 'REDUCTION' THEN
                RAISE EXCEPTION 'corrects_event_id must reference a REDUCTION';
            END IF;
            IF v_target_root <> NEW.population_root_batch_carrier_assignment_id THEN
                RAISE EXCEPTION 'a replacement must share its corrected event''s own population root';
            END IF;
            IF v_cmd_operation_kind <> 'CORRECT' OR v_cmd_target_event_id <> NEW.corrects_event_id THEN
                RAISE EXCEPTION 'replacement must belong to a CORRECT command targeting exactly the corrected event';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM production_disposition_events
                WHERE reverses_event_id = NEW.corrects_event_id AND command_id = NEW.command_id
            ) THEN
                RAISE EXCEPTION 'a replacement must be accompanied by a REVERSAL of the same target within the same command';
            END IF;
        END IF;

        -- Root opening quantity -- the one and only TransplantDestinationLine
        -- for this lineage's root BCA.
        SELECT assigned_plant_count INTO v_root_opening
        FROM transplant_destination_lines WHERE destination_batch_carrier_assignment_id = v_assignment_root;
        IF v_root_opening IS NULL THEN
            RAISE EXCEPTION 'population root has no TransplantDestinationLine opening quantity';
        END IF;

        -- CMP-DOMAIN-PRODUCTION-001 chronological balance violated: walk
        -- the ENTIRE population lineage (grouped by the flat,
        -- denormalized root id -- never a per-query recursive walk),
        -- chronologically, including this pending row, and reject if the
        -- running total ever dips below zero or exceeds the root's own
        -- opening quantity at ANY point, not merely in the final
        -- aggregate. GROUPED by effective_time first (mirrors
        -- SeedlingDisposition's own proven "grouped by effective_time,
        -- walked forward" approach exactly) -- a REVERSAL always shares
        -- its target's own effective_time by construction, and summing
        -- same-timestamp deltas together before applying the running
        -- check makes the result independent of any incidental
        -- within-timestamp row ordering, which is otherwise undefined.
        v_running := v_root_opening;
        FOR rec IN
            SELECT effective_time, SUM(quantity_delta) AS quantity_delta FROM (
                SELECT effective_time, quantity_delta FROM production_disposition_events
                WHERE population_root_batch_carrier_assignment_id = NEW.population_root_batch_carrier_assignment_id
                UNION ALL
                SELECT NEW.effective_time, NEW.quantity_delta
            ) combined
            GROUP BY effective_time
            ORDER BY effective_time ASC
        LOOP
            v_running := v_running + rec.quantity_delta;
            IF v_running < 0 THEN
                RAISE EXCEPTION '% (below zero)', '""" + _CHRONOLOGICAL_BALANCE_MARKER + """'
                    USING ERRCODE = '23514';
            END IF;
            IF v_running > v_root_opening THEN
                RAISE EXCEPTION '% (above opening quantity)', '""" + _CHRONOLOGICAL_BALANCE_MARKER + """'
                    USING ERRCODE = '23514';
            END IF;
        END LOOP;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

_NO_UPDATE_FUNCTION_NAME = "reject_append_only_mutation"

# =====================================================================
# enforce_batch_carrier_assignment_closure_only_v2 -- widened with the
# Production Disposition release branch + population_root immutability.
# =====================================================================

_CLOSURE_ONLY_WITH_PRODUCTION = """
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
        v_prod_event_kind TEXT;
        v_prod_event_effective TIMESTAMPTZ;
        v_prod_root UUID;
        v_prod_root_opening INTEGER;
        v_prod_available_after INTEGER;
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
           OR NEW.opening_production_disposition_reversal_event_id IS DISTINCT FROM OLD.opening_production_disposition_reversal_event_id
           OR NEW.restored_from_batch_carrier_assignment_id IS DISTINCT FROM OLD.restored_from_batch_carrier_assignment_id
           OR NEW.population_root_batch_carrier_assignment_id IS DISTINCT FROM OLD.population_root_batch_carrier_assignment_id
           OR NEW.actor_user_id <> OLD.actor_user_id
        THEN
            RAISE EXCEPTION 'only released_effective_time and exactly one typed releaser field may change when releasing a batch_carrier_assignment';
        END IF;

        IF NEW.released_effective_time IS NULL
           OR (NEW.released_by_transplant_event_id IS NULL
               AND NEW.released_by_batch_derivation_event_id IS NULL
               AND NEW.released_by_seedling_disposition_event_id IS NULL
               AND NEW.released_by_production_disposition_event_id IS NULL)
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
        ELSIF NEW.released_by_production_disposition_event_id IS NOT NULL THEN
            -- LEAFY-OPS-001: mirrors the seedling-disposition release
            -- branch below structurally, keyed by population root instead
            -- of a SeedlingEntry id -- proves this release event drives
            -- the lineage's own authoritative living population to
            -- exactly zero as of its own effective_time.
            SELECT event_kind, effective_time, population_root_batch_carrier_assignment_id
            INTO v_prod_event_kind, v_prod_event_effective, v_prod_root
            FROM production_disposition_events WHERE id = NEW.released_by_production_disposition_event_id;
            IF v_prod_event_kind IS NULL THEN
                RAISE EXCEPTION 'releasing production disposition event not found';
            END IF;
            IF v_prod_event_kind <> 'REDUCTION' THEN
                RAISE EXCEPTION 'only a REDUCTION event may release a batch_carrier_assignment';
            END IF;
            IF v_prod_event_effective <> NEW.released_effective_time THEN
                RAISE EXCEPTION 'released_effective_time must match the releasing disposition event''s effective time';
            END IF;
            IF v_prod_root <> NEW.population_root_batch_carrier_assignment_id THEN
                RAISE EXCEPTION 'releasing production disposition event does not share this assignment''s own population root';
            END IF;

            SELECT assigned_plant_count INTO v_prod_root_opening
            FROM transplant_destination_lines WHERE destination_batch_carrier_assignment_id = v_prod_root;

            SELECT v_prod_root_opening + COALESCE(SUM(quantity_delta), 0) INTO v_prod_available_after
            FROM production_disposition_events
            WHERE population_root_batch_carrier_assignment_id = v_prod_root
              AND effective_time <= v_prod_event_effective;

            IF v_prod_available_after <> 0 THEN
                RAISE EXCEPTION 'releasing production disposition event does not leave authoritative living population at zero (got %)', v_prod_available_after;
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
# enforce_batch_carrier_assignment_origin_insert_integrity_v2 -- widened
# with the production-disposition-reversal opener branch (mirrors the
# seedling-disposition-reversal branch exactly) + population_root
# validation on the transplant and production-disposition-reversal
# branches.
# =====================================================================

_ORIGIN_INTEGRITY_WITH_PRODUCTION = """
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
        v_predecessor_released_by_production UUID;
        v_predecessor_root UUID;
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
            IF NEW.population_root_batch_carrier_assignment_id IS NOT NULL THEN
                RAISE EXCEPTION 'a sowing-origin assignment may not carry a population root';
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
            -- LEAFY-OPS-001: every transplant destination is the root of
            -- its own population lineage -- generic across carrier type.
            IF NEW.population_root_batch_carrier_assignment_id IS DISTINCT FROM NEW.id THEN
                RAISE EXCEPTION 'a transplant-created destination assignment must self-reference its own population root';
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
            IF NEW.population_root_batch_carrier_assignment_id IS NOT NULL THEN
                RAISE EXCEPTION 'a transplant-reversal-restored assignment may not carry a population root';
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
            IF NEW.population_root_batch_carrier_assignment_id IS NOT NULL THEN
                RAISE EXCEPTION 'a seedling-disposition-restored assignment may not carry a population root';
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
        ELSIF NEW.opening_production_disposition_reversal_event_id IS NOT NULL THEN
            -- LEAFY-OPS-001: mirrors the seedling-disposition-reversal
            -- branch above exactly, plus the population-root copy-forward
            -- check (the whole reason this ticket needed a new opener
            -- branch rather than reusing the seedling one).
            SELECT c.batch_id, e.effective_time, e.event_kind, e.reverses_event_id
            INTO v_event_batch_id, v_event_effective, v_reversal_kind, v_reverses_id
            FROM production_disposition_events e
            JOIN production_disposition_commands c ON c.id = e.command_id
            WHERE e.id = NEW.opening_production_disposition_reversal_event_id;
            IF v_event_batch_id IS NULL THEN
                RAISE EXCEPTION 'opening production disposition reversal event not found';
            END IF;
            IF v_reversal_kind <> 'REVERSAL' THEN
                RAISE EXCEPTION 'opening_production_disposition_reversal_event_id must reference a REVERSAL-kind production disposition event';
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
            SELECT carrier_id, batch_stage_run_id, released_by_production_disposition_event_id,
                   population_root_batch_carrier_assignment_id
            INTO v_predecessor_carrier_id, v_predecessor_run_id, v_predecessor_released_by_production,
                 v_predecessor_root
            FROM batch_carrier_assignments WHERE id = NEW.restored_from_batch_carrier_assignment_id;
            IF v_predecessor_carrier_id IS DISTINCT FROM NEW.carrier_id THEN
                RAISE EXCEPTION 'restored assignment must be for the same physical Carrier as its predecessor';
            END IF;
            IF v_predecessor_run_id IS DISTINCT FROM NEW.batch_stage_run_id THEN
                RAISE EXCEPTION 'restored assignment must preserve its predecessor''s own stage run';
            END IF;
            IF v_predecessor_released_by_production IS DISTINCT FROM v_reverses_id THEN
                RAISE EXCEPTION 'restored assignment predecessor must have been released by the exact event this reversal reverses';
            END IF;
            IF NEW.population_root_batch_carrier_assignment_id IS DISTINCT FROM v_predecessor_root THEN
                RAISE EXCEPTION 'restored assignment must copy its predecessor''s own population root unchanged';
            END IF;
        ELSE
            SELECT effective_time INTO v_event_effective
            FROM batch_derivation_events WHERE id = NEW.opening_batch_derivation_event_id;
            IF v_event_effective IS NULL THEN
                RAISE EXCEPTION 'opening batch derivation event not found';
            END IF;
            IF NEW.population_root_batch_carrier_assignment_id IS NOT NULL THEN
                RAISE EXCEPTION 'a batch-derivation-origin assignment may not carry a population root';
            END IF;
"""

_ORIGIN_INTEGRITY_TAIL = """
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """


def upgrade() -> None:
    bind = op.get_bind()

    # --- 1. production_disposition_reasons ---------------------------------
    op.create_table(
        "production_disposition_reasons",
        sa.Column("code", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
    )
    for code, name in _APPROVED_REASONS:
        bind.execute(
            sa.text("INSERT INTO production_disposition_reasons (code, name) VALUES (:code, :name)"),
            {"code": code, "name": name},
        )

    # --- 2. batch_carrier_assignments: new columns --------------------------
    op.add_column(
        "batch_carrier_assignments",
        sa.Column("released_by_production_disposition_event_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "batch_carrier_assignments",
        sa.Column("opening_production_disposition_reversal_event_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "batch_carrier_assignments",
        sa.Column("population_root_batch_carrier_assignment_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    # --- 3. backfill: every existing transplant-created destination BCA ----
    # (Nursery AND Production Cultivation Plate alike) self-references its
    # own id as population root. Safe and unambiguous: no BCA opened by
    # opening_production_disposition_reversal_event_id can exist yet.
    bind.execute(
        sa.text(
            "UPDATE batch_carrier_assignments "
            "SET population_root_batch_carrier_assignment_id = id "
            "WHERE opening_transplant_event_id IS NOT NULL "
            "AND population_root_batch_carrier_assignment_id IS NULL"
        )
    )

    # --- 4. production_disposition_commands (target_event_id FK deferred) --
    op.create_table(
        "production_disposition_commands",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("crop_batches.id"), nullable=False),
        sa.Column(
            "batch_carrier_assignment_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("batch_carrier_assignments.id"), nullable=False,
        ),
        sa.Column("operation_kind", sa.String(), nullable=False),
        sa.Column("target_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "operation_kind IN ('RECORD', 'CORRECT')", name="ck_production_disposition_commands_operation_kind"
        ),
        sa.CheckConstraint(
            "(operation_kind = 'RECORD' AND target_event_id IS NULL) OR "
            "(operation_kind = 'CORRECT' AND target_event_id IS NOT NULL)",
            name="ck_production_disposition_commands_target_matches_kind",
        ),
        sa.UniqueConstraint(
            "tenant_id", "client_command_id", name="ux_production_disposition_commands_tenant_client_command_id"
        ),
        sa.UniqueConstraint(
            "tenant_id", "farm_id", "id", name="uq_production_disposition_commands_tenant_farm_id"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_production_disposition_commands_tenant_farm_batch",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_carrier_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id", "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_production_disposition_commands_tenant_farm_assignment",
        ),
    )

    # --- 5. production_disposition_events -----------------------------------
    op.create_table(
        "production_disposition_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column(
            "command_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("production_disposition_commands.id"), nullable=False,
        ),
        sa.Column(
            "batch_carrier_assignment_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("batch_carrier_assignments.id"), nullable=False,
        ),
        sa.Column(
            "population_root_batch_carrier_assignment_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("batch_carrier_assignments.id"), nullable=False,
        ),
        sa.Column("event_kind", sa.String(), nullable=False),
        sa.Column("reason_code", sa.String(), sa.ForeignKey("production_disposition_reasons.code"), nullable=False),
        sa.Column("quantity_delta", sa.Integer(), nullable=False),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("reverses_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("corrects_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("event_kind IN ('REDUCTION', 'REVERSAL')", name="ck_production_disposition_events_kind"),
        sa.CheckConstraint("quantity_delta <> 0", name="ck_production_disposition_events_delta_nonzero"),
        sa.CheckConstraint(
            "(event_kind = 'REDUCTION' AND quantity_delta < 0 AND reverses_event_id IS NULL) OR "
            "(event_kind = 'REVERSAL' AND quantity_delta > 0 AND reverses_event_id IS NOT NULL)",
            name="ck_production_disposition_events_kind_sign_consistency",
        ),
        sa.CheckConstraint(
            "corrects_event_id IS NULL OR event_kind = 'REDUCTION'",
            name="ck_production_disposition_events_corrects_only_on_reduction",
        ),
        sa.CheckConstraint(
            "reason_code <> 'other' OR (note IS NOT NULL AND btrim(note) <> '')",
            name="ck_production_disposition_events_other_requires_note",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "command_id"],
            [
                "production_disposition_commands.tenant_id", "production_disposition_commands.farm_id",
                "production_disposition_commands.id",
            ],
            name="fk_production_disposition_events_tenant_farm_command",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_carrier_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id", "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_production_disposition_events_tenant_farm_assignment",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "population_root_batch_carrier_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id", "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_production_disposition_events_tenant_farm_root",
        ),
        sa.UniqueConstraint("tenant_id", "farm_id", "id", name="uq_production_disposition_events_tenant_farm_id"),
    )
    op.create_index(
        "ux_production_disposition_events_reverses_once",
        "production_disposition_events", ["reverses_event_id"], unique=True,
        postgresql_where=sa.text("reverses_event_id IS NOT NULL"),
    )
    op.create_index(
        "ix_production_disposition_events_root_effective",
        "production_disposition_events", ["population_root_batch_carrier_assignment_id", "effective_time"],
    )
    op.create_index(
        "ix_production_disposition_events_assignment",
        "production_disposition_events", ["batch_carrier_assignment_id"],
    )

    # --- 6. batch_carrier_assignments: new CHECK constraints/indexes/FKs ---
    op.drop_constraint("ck_batch_carrier_assignments_exactly_one_opener", "batch_carrier_assignments", type_="check")
    op.create_check_constraint(
        "ck_batch_carrier_assignments_exactly_one_opener",
        "batch_carrier_assignments",
        "(CASE WHEN opening_sowing_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN opening_transplant_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN opening_batch_derivation_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN opening_transplant_reversal_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN opening_seedling_disposition_reversal_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN opening_production_disposition_reversal_event_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
    )
    op.drop_constraint(
        "ck_batch_carrier_assignments_release_fields_together", "batch_carrier_assignments", type_="check"
    )
    op.create_check_constraint(
        "ck_batch_carrier_assignments_release_fields_together",
        "batch_carrier_assignments",
        "(released_effective_time IS NULL) = "
        "(released_by_transplant_event_id IS NULL AND released_by_batch_derivation_event_id IS NULL "
        "AND released_by_seedling_disposition_event_id IS NULL "
        "AND released_by_production_disposition_event_id IS NULL)",
    )
    op.drop_constraint(
        "ck_batch_carrier_assignments_at_most_one_releaser", "batch_carrier_assignments", type_="check"
    )
    op.create_check_constraint(
        "ck_batch_carrier_assignments_at_most_one_releaser",
        "batch_carrier_assignments",
        "(CASE WHEN released_by_transplant_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN released_by_batch_derivation_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN released_by_seedling_disposition_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN released_by_production_disposition_event_id IS NOT NULL THEN 1 ELSE 0 END) <= 1",
    )
    op.create_check_constraint(
        "ck_batch_carrier_assignments_only_production_source_releasable",
        "batch_carrier_assignments",
        "released_by_production_disposition_event_id IS NULL "
        "OR opening_transplant_event_id IS NOT NULL "
        "OR opening_production_disposition_reversal_event_id IS NOT NULL",
    )
    op.drop_constraint(
        "ck_batch_carrier_assignments_restoration_opener_match", "batch_carrier_assignments", type_="check"
    )
    op.create_check_constraint(
        "ck_batch_carrier_assignments_restoration_opener_match",
        "batch_carrier_assignments",
        "(restored_from_batch_carrier_assignment_id IS NOT NULL) = "
        "(opening_transplant_reversal_event_id IS NOT NULL "
        "OR opening_seedling_disposition_reversal_event_id IS NOT NULL "
        "OR opening_production_disposition_reversal_event_id IS NOT NULL)",
    )
    op.create_index(
        "ux_batch_carrier_assignments_released_by_prod_disposition_once",
        "batch_carrier_assignments", ["released_by_production_disposition_event_id"], unique=True,
        postgresql_where=sa.text("released_by_production_disposition_event_id IS NOT NULL"),
    )
    op.create_index(
        "ux_batch_carrier_assignments_opened_by_prod_disposition_once",
        "batch_carrier_assignments", ["opening_production_disposition_reversal_event_id"], unique=True,
        postgresql_where=sa.text("opening_production_disposition_reversal_event_id IS NOT NULL"),
    )
    op.create_foreign_key(
        "fk_batch_carrier_assignments_released_by_prod_disposition_event",
        "batch_carrier_assignments", "production_disposition_events",
        ["tenant_id", "farm_id", "released_by_production_disposition_event_id"],
        ["tenant_id", "farm_id", "id"],
    )
    op.create_foreign_key(
        "fk_batch_carrier_assignments_opening_prod_disp_reversal_event",
        "batch_carrier_assignments", "production_disposition_events",
        ["tenant_id", "farm_id", "opening_production_disposition_reversal_event_id"],
        ["tenant_id", "farm_id", "id"],
    )
    op.create_foreign_key(
        "fk_batch_carrier_assignments_population_root",
        "batch_carrier_assignments", "batch_carrier_assignments",
        ["tenant_id", "farm_id", "population_root_batch_carrier_assignment_id"],
        ["tenant_id", "farm_id", "id"],
    )

    # --- 7. new command/event insert-integrity + append-only triggers ------
    op.execute(_COMMAND_INTEGRITY_FUNCTION)
    op.execute(
        """
        CREATE TRIGGER production_disposition_commands_enforce_insert_integrity
        BEFORE INSERT ON production_disposition_commands
        FOR EACH ROW EXECUTE FUNCTION enforce_production_disposition_command_insert_integrity();
        """
    )
    op.execute(_EVENT_INTEGRITY_FUNCTION)
    op.execute(
        """
        CREATE TRIGGER production_disposition_events_enforce_insert_integrity
        BEFORE INSERT ON production_disposition_events
        FOR EACH ROW EXECUTE FUNCTION enforce_production_disposition_event_insert_integrity();
        """
    )
    for table in ("production_disposition_commands", "production_disposition_events"):
        op.execute(
            f"""
            CREATE TRIGGER {table}_no_update
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION {_NO_UPDATE_FUNCTION_NAME}();
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER {table}_no_delete
            BEFORE DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION {_NO_UPDATE_FUNCTION_NAME}();
            """
        )

    # --- 8. widen the two existing BatchCarrierAssignment triggers ---------
    op.execute(_CLOSURE_ONLY_WITH_PRODUCTION)
    op.execute(_ORIGIN_INTEGRITY_WITH_PRODUCTION + _ORIGIN_INTEGRITY_TAIL)


def downgrade() -> None:
    bind = op.get_bind()

    # LEAFY-OPS-001: block downgrade if any Production Disposition history
    # exists -- mirrors the repository's own established downgrade-guard
    # convention (b7e2f4a9c1d6 / 1ffda251c3a8 / SEEDLING-DISPOSITION-
    # LIFECYCLE-001's own guard) exactly. Silently dropping this table would
    # discard real biological history, not merely revert a schema shape.
    event_count = bind.execute(sa.text("SELECT count(*) FROM production_disposition_events")).scalar_one()
    if event_count > 0:
        raise RuntimeError(
            f"cannot downgrade past a5c9e21f7b64: {event_count} production_disposition_events row(s) exist -- "
            "downgrading would silently discard real Production Biological Disposition history"
        )

    root_count = bind.execute(
        sa.text(
            "SELECT count(*) FROM batch_carrier_assignments "
            "WHERE opening_production_disposition_reversal_event_id IS NOT NULL"
        )
    ).scalar_one()
    if root_count > 0:
        raise RuntimeError(
            f"cannot downgrade past a5c9e21f7b64: {root_count} restored batch_carrier_assignments row(s) exist"
        )

    op.drop_constraint(
        "fk_batch_carrier_assignments_population_root", "batch_carrier_assignments", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_batch_carrier_assignments_opening_prod_disp_reversal_event",
        "batch_carrier_assignments", type_="foreignkey",
    )
    op.drop_constraint(
        "fk_batch_carrier_assignments_released_by_prod_disposition_event",
        "batch_carrier_assignments", type_="foreignkey",
    )
    op.drop_index("ux_batch_carrier_assignments_opened_by_prod_disposition_once", "batch_carrier_assignments")
    op.drop_index(
        "ux_batch_carrier_assignments_released_by_prod_disposition_once", "batch_carrier_assignments"
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
    op.drop_constraint(
        "ck_batch_carrier_assignments_only_production_source_releasable", "batch_carrier_assignments", type_="check"
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
    op.drop_constraint("ck_batch_carrier_assignments_exactly_one_opener", "batch_carrier_assignments", type_="check")
    op.create_check_constraint(
        "ck_batch_carrier_assignments_exactly_one_opener",
        "batch_carrier_assignments",
        "(CASE WHEN opening_sowing_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN opening_transplant_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN opening_batch_derivation_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN opening_transplant_reversal_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN opening_seedling_disposition_reversal_event_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
    )

    for table in ("production_disposition_events", "production_disposition_commands"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_delete ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_update ON {table}")
    op.execute(
        "DROP TRIGGER IF EXISTS production_disposition_events_enforce_insert_integrity "
        "ON production_disposition_events"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_production_disposition_event_insert_integrity()")
    op.execute(
        "DROP TRIGGER IF EXISTS production_disposition_commands_enforce_insert_integrity "
        "ON production_disposition_commands"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_production_disposition_command_insert_integrity()")

    op.drop_table("production_disposition_events")
    op.drop_table("production_disposition_commands")

    op.drop_column("batch_carrier_assignments", "population_root_batch_carrier_assignment_id")
    op.drop_column("batch_carrier_assignments", "opening_production_disposition_reversal_event_id")
    op.drop_column("batch_carrier_assignments", "released_by_production_disposition_event_id")

    op.drop_table("production_disposition_reasons")

    # Restore the pre-this-migration trigger function bodies (SEEDLING-
    # DISPOSITION-LIFECYCLE-001's own versions, unchanged).
    op.execute(_PRIOR_CLOSURE_ONLY_FUNCTION)
    op.execute(_PRIOR_ORIGIN_INTEGRITY_FUNCTION)


_PRIOR_CLOSURE_ONLY_FUNCTION = """
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

_PRIOR_ORIGIN_INTEGRITY_FUNCTION = """
    CREATE OR REPLACE FUNCTION enforce_batch_carrier_assignment_origin_insert_integrity_v2() RETURNS trigger AS $$
    DECLARE
        v_event_batch_id UUID;
        v_event_run_id UUID;
        v_event_effective TIMESTAMPTZ;
        v_run_stage_id UUID;
        v_required_type UUID;
        v_actual_type UUID;
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
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """
