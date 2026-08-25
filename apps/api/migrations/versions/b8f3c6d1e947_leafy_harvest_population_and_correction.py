"""leafy harvest population and correction

HARVEST-OPS-001 BUILD SLICE 1 -- backend foundation for Leafy Production
Harvest, reusing the existing CMP-013 Harvest primitives
(`harvest_events`/`harvest_source_lines`/`harvested_produce_lots`/
`produce_lot_ledger_entries`) unchanged and untouched in shape, adding only
what a biologically-population-aware, correctable Leafy Harvest needs on
top of them.

Three new pieces:

1. `harvest_population_events` -- the sibling biological ledger to
   `production_disposition_events` (LEAFY-OPS-001), never a parallel
   population authority. A CONSUMPTION (`quantity_delta < 0`) is the
   biological removal driven by a Leafy HarvestSourceLine's own
   `whole_unit_count` (weight NEVER reduces population); a REVERSAL
   (`quantity_delta > 0`) is the exact negation of one specific prior
   CONSUMPTION, a correction's own biological consequence. Authoritative
   living population becomes:

       opening (root's own TransplantDestinationLine.assigned_plant_count)
       + SUM(production_disposition_events.quantity_delta)
       + SUM(harvest_population_events.quantity_delta)

   one flat, non-recursive SUM across BOTH event tables, grouped by shared
   root -- `enforce_production_disposition_event_insert_integrity` is
   widened (CREATE OR REPLACE) to call a new shared helper function,
   `enforce_shared_leafy_population_chronological_balance`, which walks
   BOTH tables together (grouped by `effective_time` first, then walked
   ascending -- never dependent on row insertion order or UNION ordering);
   a new, structurally identical trigger on `harvest_population_events`
   calls the exact same shared helper. Generic, non-Leafy Harvest sources
   (whose BCA has no `population_root_batch_carrier_assignment_id`) never
   get a row here -- no fabricated roots (see `harvest_source_lines`'
   own docstring, unmodified: no population-root column was added there).

2. `harvest_source_line_corrections` -- the immutable, non-branching
   commercial/audit correction chain for one ORIGINAL `HarvestSourceLine`.
   `supersedes_correction_id` links each correction to whichever node (a
   prior correction, or NULL meaning the original line itself) it
   replaces -- structurally identical to `BatchCarrierAssignment.
   restored_from_batch_carrier_assignment_id`'s own restoration lineage.
   Two partial unique indexes make it a strict, non-branching linked list
   (`ux_..._root_once`: at most one first correction per line;
   `ux_..._successor_once`: at most one direct successor per correction --
   this second index doubles as the optimistic-concurrency primitive: two
   concurrent corrections targeting the same predecessor race on INSERT,
   exactly one wins). Every non-void correction is a COMPLETE state
   snapshot (both `corrected_harvested_weight_kg` and `corrected_whole_
   unit_count` always populated); a void correction carries NULL/NULL for
   both ("currently nothing harvested from this line") and is NOT
   terminal -- a later correction may supersede a void node exactly like
   any other.

3. `produce_lot_ledger_entries` gains a third `entry_kind`,
   `harvest_adjustment` -- a signed (either-direction) delta, `id` equal
   to its own `HarvestSourceLineCorrection`'s id, additive into the SAME
   `available_weight_kg = SUM(weight_delta_kg)` balance `packing_
   consumption` already established, with the SAME negative-balance guard
   (lock the lot, compute the prior balance, reject if the adjustment
   would drive it negative -- "some quantity already consumed downstream
   in Packing"). `harvested_produce_lots.total_*` remain untouched,
   immutable ORIGINAL receipt snapshots forever (CMP-013's own contract,
   never reinterpreted).

`BatchCarrierAssignment` gains a fifth typed releaser/opener pair,
`released_by_harvest_population_event_id`/`opening_harvest_population_
reversal_event_id`, mirroring `released_by_production_disposition_event_id`/
`opening_production_disposition_reversal_event_id` exactly -- deliberately
source-LINE-specific (a multi-Plate HarvestEvent may zero-exhaust one Plate
while leaving another active; the releaser names the exact
HarvestPopulationEvent, never the shared HarvestEvent header). A Harvest
correction that restores positive population after a zero-Harvest released
a BCA creates a NEW generation (never reactivates the old one), exactly
like every other restoration in this codebase.

Worked proof -- repeated correction (ticket's own required example):

    Original line: 5 heads / 2.5 kg (opening 10, living after harvest: 5)
    Correction 1 -> 4 / 2.0: REVERSAL +5 of the original CONSUMPTION,
        REPLACEMENT CONSUMPTION -4. living = 10 - 4 = 6.
        Ledger: harvest_receipt +2.5/+5, harvest_adjustment -0.5/-1.
        available = 2.5 - 0.5 = 2.0kg / 5 - 1 = 4.
    Correction 2 -> 6 / 3.0 (relative to correction 1's OWN 4/2.0, never
        the original 5/2.5): REVERSAL +4 of correction 1's replacement
        CONSUMPTION, REPLACEMENT CONSUMPTION -6. living = 10 - 6 = 4.
        Ledger delta = (3.0-2.0, 6-4) = (+1.0, +2), NOT (+0.5, +1).
        available = 2.0 + 1.0 = 3.0kg / 4 + 2 = 6 -- matches the corrected
        tuple exactly. Full-history cross-check:
        2.5 + (-0.5) + (+1.0) = 3.0kg; 5 + (-1) + (+2) = 6.

Worked proof -- zero-release -> restore -> re-zero (ticket's own required
example), opening 5:

    Original harvest -5. living = 0. BCA A released
        (released_by_harvest_population_event_id = original CONSUMPTION).
    Correction 1 (5 -> 4): REVERSAL +5 against A (running 0+5=5) -- A is
        released, so this restores positive population -> NEW BCA
        generation B is opened
        (opening_harvest_population_reversal_event_id = this REVERSAL),
        restored_from_batch_carrier_assignment_id = A, root copied
        forward, no fabricated TransplantDestinationLine. REPLACEMENT
        CONSUMPTION -4 against B (running 5-4=1). living = 1, B active.
    Correction 2 (4 -> 5): REVERSAL +4 against B (running 1+4=5) -- B is
        STILL active (not released), so no restoration (CASE A).
        REPLACEMENT CONSUMPTION -5 against the SAME B (running 5-5=0) ->
        B now hits exactly zero -> B released
        (released_by_harvest_population_event_id = correction 2's own
        replacement CONSUMPTION). living = 0.
    A stays historically released forever, B is the generation Correction
    2 releases, never A reactivated, no unnecessary C generation.

Defensive historical safety: this migration does NOT assume no historical
CMP-013 `harvest_source_lines` row exists against a `production_
cultivation_plate`-typed BatchCarrierAssignment -- it asserts this
explicitly and raises loudly rather than silently inventing population
history for pre-existing rows this ticket never designed for.

Revision ID: b8f3c6d1e947
Revises: a5c9e21f7b64
Create Date: 2026-08-24 09:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b8f3c6d1e947"
down_revision: str | None = "a5c9e21f7b64"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_CHRONOLOGICAL_BALANCE_MARKER = "CMP-DOMAIN-PRODUCTION-001 chronological balance violated"
_NO_UPDATE_FUNCTION_NAME = "reject_append_only_mutation"

# =====================================================================
# Shared chronological-balance helper -- called by BOTH the widened
# production_disposition_events trigger and the new
# harvest_population_events trigger, so the "walk both tables together,
# grouped by effective_time, walked ascending" algorithm exists in exactly
# one place.
# =====================================================================

_SHARED_BALANCE_FUNCTION = """
    CREATE FUNCTION enforce_shared_leafy_population_chronological_balance(
        p_root UUID, p_new_effective_time TIMESTAMPTZ, p_new_delta INTEGER
    ) RETURNS void AS $$
    DECLARE
        v_root_opening INTEGER;
        v_running INTEGER;
        rec RECORD;
    BEGIN
        SELECT assigned_plant_count INTO v_root_opening
        FROM transplant_destination_lines WHERE destination_batch_carrier_assignment_id = p_root;
        IF v_root_opening IS NULL THEN
            RAISE EXCEPTION 'population root has no TransplantDestinationLine opening quantity';
        END IF;

        v_running := v_root_opening;
        FOR rec IN
            SELECT effective_time, SUM(quantity_delta) AS quantity_delta FROM (
                SELECT effective_time, quantity_delta FROM production_disposition_events
                WHERE population_root_batch_carrier_assignment_id = p_root
                UNION ALL
                SELECT effective_time, quantity_delta FROM harvest_population_events
                WHERE population_root_batch_carrier_assignment_id = p_root
                UNION ALL
                SELECT p_new_effective_time, p_new_delta
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
    END;
    $$ LANGUAGE plpgsql;
    """

_DROP_SHARED_BALANCE_FUNCTION = (
    "DROP FUNCTION IF EXISTS enforce_shared_leafy_population_chronological_balance(UUID, TIMESTAMPTZ, INTEGER)"
)

# =====================================================================
# enforce_production_disposition_event_insert_integrity -- widened
# (CREATE OR REPLACE) to call the shared balance helper instead of its own
# inline walk. Every other check is byte-for-byte unchanged from
# a5c9e21f7b64's own version.
# =====================================================================

_PRODUCTION_DISPOSITION_EVENT_INTEGRITY_WIDENED = """
    CREATE OR REPLACE FUNCTION enforce_production_disposition_event_insert_integrity() RETURNS trigger AS $$
    DECLARE
        v_cmd_tenant_id UUID;
        v_cmd_farm_id UUID;
        v_cmd_batch_id UUID;
        v_cmd_operation_kind TEXT;
        v_cmd_target_event_id UUID;
        v_assignment_root UUID;
        v_assignment_assigned TIMESTAMPTZ;
        v_assignment_released TIMESTAMPTZ;
        v_target_kind TEXT;
        v_target_tenant_id UUID;
        v_target_root UUID;
        v_target_reason TEXT;
        v_target_delta INTEGER;
        v_target_effective TIMESTAMPTZ;
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

        -- HARVEST-OPS-001: the balance walk now lives in one shared
        -- function, unioning BOTH production_disposition_events and
        -- harvest_population_events, so a Harvest and a Plant Loss on the
        -- same root are validated together, never independently.
        PERFORM enforce_shared_leafy_population_chronological_balance(
            NEW.population_root_batch_carrier_assignment_id, NEW.effective_time, NEW.quantity_delta
        );

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

# =====================================================================
# harvest_population_events -- own insert-integrity trigger.
# =====================================================================

_HARVEST_POPULATION_EVENT_INTEGRITY_FUNCTION = """
    CREATE FUNCTION enforce_harvest_population_event_insert_integrity() RETURNS trigger AS $$
    DECLARE
        v_assignment_root UUID;
        v_assignment_released TIMESTAMPTZ;
        v_line_tenant_id UUID;
        v_line_farm_id UUID;
        v_line_assignment_id UUID;
        v_line_whole_unit_count BIGINT;
        v_line_event_effective TIMESTAMPTZ;
        v_correction_tenant_id UUID;
        v_correction_farm_id UUID;
        v_correction_is_void BOOLEAN;
        v_correction_count BIGINT;
        v_correction_event_effective TIMESTAMPTZ;
        v_target_kind TEXT;
        v_target_tenant_id UUID;
        v_target_root UUID;
        v_target_delta INTEGER;
        v_target_effective TIMESTAMPTZ;
        v_target_assignment UUID;
    BEGIN
        -- Lock the BCA row -- serializes concurrent event inserts for the
        -- same lineage (defense-in-depth behind the service's own
        -- CropBatch-first and population-root locks).
        SELECT population_root_batch_carrier_assignment_id, released_effective_time
        INTO v_assignment_root, v_assignment_released
        FROM batch_carrier_assignments WHERE id = NEW.batch_carrier_assignment_id FOR UPDATE;

        IF v_assignment_root IS NULL THEN
            RAISE EXCEPTION 'batch carrier assignment has no population root; not a valid Leafy population lineage member';
        END IF;
        IF v_assignment_root <> NEW.population_root_batch_carrier_assignment_id THEN
            RAISE EXCEPTION 'event population_root_batch_carrier_assignment_id does not match its own BCA''s stored root';
        END IF;

        IF NEW.event_kind = 'CONSUMPTION' THEN
            IF v_assignment_released IS NOT NULL THEN
                RAISE EXCEPTION 'batch carrier assignment is already released; no new CONSUMPTION may target it';
            END IF;

            IF NEW.original_harvest_source_line_id IS NOT NULL THEN
                SELECT tenant_id, farm_id, batch_carrier_assignment_id, whole_unit_count
                INTO v_line_tenant_id, v_line_farm_id, v_line_assignment_id, v_line_whole_unit_count
                FROM harvest_source_lines WHERE id = NEW.original_harvest_source_line_id;
                IF v_line_tenant_id IS NULL THEN
                    RAISE EXCEPTION 'original harvest source line not found';
                END IF;
                IF v_line_tenant_id <> NEW.tenant_id OR v_line_farm_id <> NEW.farm_id THEN
                    RAISE EXCEPTION 'original harvest source line does not belong to this tenant/farm';
                END IF;
                IF v_line_assignment_id <> NEW.batch_carrier_assignment_id THEN
                    RAISE EXCEPTION 'an original CONSUMPTION must target the exact BCA its own HarvestSourceLine was recorded against';
                END IF;
                -- CTO CORRECTION 1 / Finding 2.A: the ORIGINAL CONSUMPTION's
                -- own magnitude must be the exact negation of its source
                -- line's own whole_unit_count -- never trusted from the
                -- caller, always cross-checked against the one authoritative
                -- column.
                IF v_line_whole_unit_count IS NULL THEN
                    RAISE EXCEPTION 'original harvest source line has no whole_unit_count; not a valid Leafy population fact';
                END IF;
                IF NEW.quantity_delta <> -v_line_whole_unit_count THEN
                    RAISE EXCEPTION 'original CONSUMPTION quantity_delta must be the exact negation of its own HarvestSourceLine''s whole_unit_count';
                END IF;

                SELECT e.effective_time INTO v_line_event_effective
                FROM harvest_source_lines l JOIN harvest_events e ON e.id = l.harvest_event_id
                WHERE l.id = NEW.original_harvest_source_line_id;
                IF NEW.effective_time <> v_line_event_effective THEN
                    RAISE EXCEPTION 'CONSUMPTION effective_time must match its own HarvestEvent''s effective time';
                END IF;
            ELSE
                SELECT tenant_id, farm_id, is_void, corrected_whole_unit_count
                INTO v_correction_tenant_id, v_correction_farm_id, v_correction_is_void, v_correction_count
                FROM harvest_source_line_corrections WHERE id = NEW.harvest_source_line_correction_id;
                IF v_correction_tenant_id IS NULL THEN
                    RAISE EXCEPTION 'harvest source line correction not found';
                END IF;
                IF v_correction_tenant_id <> NEW.tenant_id OR v_correction_farm_id <> NEW.farm_id THEN
                    RAISE EXCEPTION 'harvest source line correction does not belong to this tenant/farm';
                END IF;
                IF v_correction_is_void THEN
                    RAISE EXCEPTION 'a void correction may never carry a replacement CONSUMPTION';
                END IF;
                IF NEW.quantity_delta <> -v_correction_count THEN
                    RAISE EXCEPTION 'replacement CONSUMPTION quantity_delta must be the exact negation of its correction''s own corrected_whole_unit_count';
                END IF;

                SELECT e.effective_time INTO v_correction_event_effective
                FROM harvest_source_line_corrections c
                JOIN harvest_source_lines l ON l.id = c.harvest_source_line_id
                JOIN harvest_events e ON e.id = l.harvest_event_id
                WHERE c.id = NEW.harvest_source_line_correction_id;
                IF NEW.effective_time <> v_correction_event_effective THEN
                    RAISE EXCEPTION 'replacement CONSUMPTION effective_time must match the ORIGINAL HarvestEvent''s effective time';
                END IF;
            END IF;
        END IF;

        IF NEW.event_kind = 'REVERSAL' THEN
            SELECT event_kind, tenant_id, population_root_batch_carrier_assignment_id, quantity_delta,
                   effective_time, batch_carrier_assignment_id
            INTO v_target_kind, v_target_tenant_id, v_target_root, v_target_delta, v_target_effective,
                 v_target_assignment
            FROM harvest_population_events WHERE id = NEW.reverses_event_id;
            IF v_target_kind IS NULL THEN
                RAISE EXCEPTION 'reversed event not found';
            END IF;
            IF v_target_kind <> 'CONSUMPTION' THEN
                RAISE EXCEPTION 'a REVERSAL may only reverse a CONSUMPTION';
            END IF;
            IF v_target_tenant_id <> NEW.tenant_id THEN
                RAISE EXCEPTION 'reversed event does not belong to this tenant';
            END IF;
            IF v_target_root <> NEW.population_root_batch_carrier_assignment_id THEN
                RAISE EXCEPTION 'a REVERSAL must share its target''s own population root';
            END IF;
            IF NEW.quantity_delta <> -v_target_delta THEN
                RAISE EXCEPTION 'REVERSAL quantity_delta must be the exact negation of the reversed event';
            END IF;
            IF NEW.effective_time <> v_target_effective THEN
                RAISE EXCEPTION 'REVERSAL effective_time must equal the reversed event''s own effective time';
            END IF;
            IF NEW.batch_carrier_assignment_id <> v_target_assignment THEN
                RAISE EXCEPTION 'REVERSAL must target the exact same BCA generation as the CONSUMPTION it reverses';
            END IF;
        END IF;

        PERFORM enforce_shared_leafy_population_chronological_balance(
            NEW.population_root_batch_carrier_assignment_id, NEW.effective_time, NEW.quantity_delta
        );

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

# =====================================================================
# CTO CORRECTION 1 / Finding 1: enforce_leafy_harvest_stage_bypass_integrity
# -- a DEFERRED constraint trigger on harvest_events, firing at REAL commit.
# `SET LOCAL cmp.leafy_harvest = 'true'` (set only by record_leafy_harvest)
# is what lets the IMMEDIATE enforce_harvest_event_insert_integrity trigger
# skip the stage_category = 'harvesting' gate at INSERT time -- but the GUC
# is never trusted as the final authority. This trigger independently
# re-examines the COMPLETE persisted state of every event whose own stage
# is NOT 'harvesting' and rejects the whole transaction unless it
# genuinely proves Leafy Harvest shape for every one of its source lines --
# carrier type, positive whole_unit_count, exactly one original
# CONSUMPTION referencing the same BCA and that BCA's own stored population
# root, with the exact matching quantity. An event whose stage IS
# 'harvesting' returns immediately (CMP-013's own path, already fully
# proven by the immediate trigger, untouched). A direct-SQL insert that
# merely sets the GUC without also persisting genuine Leafy facts is
# rejected here regardless.
# =====================================================================

_STAGE_BYPASS_INTEGRITY_FUNCTION = """
    CREATE FUNCTION enforce_leafy_harvest_stage_bypass_integrity() RETURNS trigger AS $$
    DECLARE
        v_stage_category TEXT;
        v_line RECORD;
        v_bca RECORD;
        v_consumption_count INTEGER;
        v_consumption RECORD;
    BEGIN
        SELECT s.stage_category INTO v_stage_category
        FROM batch_stage_runs r JOIN workflow_stages s ON s.id = r.workflow_stage_id
        WHERE r.id = NEW.active_batch_stage_run_id;

        IF v_stage_category = 'harvesting' THEN
            RETURN NEW;
        END IF;

        FOR v_line IN
            SELECT id, batch_carrier_assignment_id, whole_unit_count
            FROM harvest_source_lines WHERE harvest_event_id = NEW.id
        LOOP
            SELECT bca.batch_id, bca.tenant_id, bca.farm_id,
                   bca.population_root_batch_carrier_assignment_id, ct.code AS carrier_type_code
            INTO v_bca
            FROM batch_carrier_assignments bca
            JOIN carriers c ON c.id = bca.carrier_id
            JOIN carrier_types ct ON ct.id = c.carrier_type_id
            WHERE bca.id = v_line.batch_carrier_assignment_id;

            IF v_bca.batch_id IS DISTINCT FROM NEW.batch_id
               OR v_bca.tenant_id IS DISTINCT FROM NEW.tenant_id
               OR v_bca.farm_id IS DISTINCT FROM NEW.farm_id
            THEN
                RAISE EXCEPTION 'harvest event % is outside the harvesting stage and source line %''s BCA does not belong to this event''s own tenant/farm/batch -- not a valid Leafy Harvest',
                    NEW.id, v_line.id;
            END IF;
            IF v_bca.carrier_type_code IS DISTINCT FROM 'production_cultivation_plate' THEN
                RAISE EXCEPTION 'harvest event % is outside the harvesting stage and source line % is not a production_cultivation_plate BCA -- not a valid Leafy Harvest',
                    NEW.id, v_line.id;
            END IF;
            IF v_line.whole_unit_count IS NULL OR v_line.whole_unit_count <= 0 THEN
                RAISE EXCEPTION 'harvest event % is outside the harvesting stage and source line % has no positive whole_unit_count -- not a valid Leafy Harvest',
                    NEW.id, v_line.id;
            END IF;

            SELECT count(*) INTO v_consumption_count FROM harvest_population_events
            WHERE original_harvest_source_line_id = v_line.id AND event_kind = 'CONSUMPTION';
            IF v_consumption_count <> 1 THEN
                RAISE EXCEPTION 'harvest event % is outside the harvesting stage and source line % does not have exactly one original CONSUMPTION -- not a valid Leafy Harvest',
                    NEW.id, v_line.id;
            END IF;

            SELECT batch_carrier_assignment_id, population_root_batch_carrier_assignment_id, quantity_delta
            INTO v_consumption
            FROM harvest_population_events WHERE original_harvest_source_line_id = v_line.id AND event_kind = 'CONSUMPTION';

            IF v_consumption.batch_carrier_assignment_id <> v_line.batch_carrier_assignment_id THEN
                RAISE EXCEPTION 'harvest event % is outside the harvesting stage and source line %''s CONSUMPTION does not reference the exact same BCA -- not a valid Leafy Harvest',
                    NEW.id, v_line.id;
            END IF;
            IF v_consumption.population_root_batch_carrier_assignment_id IS DISTINCT FROM v_bca.population_root_batch_carrier_assignment_id THEN
                RAISE EXCEPTION 'harvest event % is outside the harvesting stage and source line %''s CONSUMPTION does not reference its own BCA''s stored population root -- not a valid Leafy Harvest',
                    NEW.id, v_line.id;
            END IF;
            IF v_consumption.quantity_delta <> -v_line.whole_unit_count THEN
                RAISE EXCEPTION 'harvest event % is outside the harvesting stage and source line %''s CONSUMPTION quantity does not match its own whole_unit_count -- not a valid Leafy Harvest',
                    NEW.id, v_line.id;
            END IF;
        END LOOP;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

# =====================================================================
# CTO CORRECTION 1: enforce_harvest_source_line_correction_insert_integrity
# -- own insert-integrity trigger for harvest_source_line_corrections,
# proving two cross-row facts the partial unique indexes alone cannot:
# (1) a correction may only supersede another correction belonging to the
# SAME original HarvestSourceLine -- never a different line's chain; (2) a
# correction must actually change the effective tuple from its own
# immediate predecessor -- no useless no-op chain nodes, ever.
# =====================================================================

_SOURCE_LINE_CORRECTION_INTEGRITY_FUNCTION = """
    CREATE FUNCTION enforce_harvest_source_line_correction_insert_integrity() RETURNS trigger AS $$
    DECLARE
        v_line_tenant_id UUID;
        v_line_farm_id UUID;
        v_predecessor_line_id UUID;
        v_predecessor_is_void BOOLEAN;
        v_predecessor_weight NUMERIC;
        v_predecessor_count BIGINT;
        v_new_weight NUMERIC;
        v_new_count BIGINT;
    BEGIN
        SELECT tenant_id, farm_id INTO v_line_tenant_id, v_line_farm_id
        FROM harvest_source_lines WHERE id = NEW.harvest_source_line_id;
        IF v_line_tenant_id IS NULL THEN
            RAISE EXCEPTION 'harvest source line not found for correction';
        END IF;
        IF v_line_tenant_id <> NEW.tenant_id OR v_line_farm_id <> NEW.farm_id THEN
            RAISE EXCEPTION 'correction tenant/farm does not match its own harvest source line';
        END IF;

        IF NEW.supersedes_correction_id IS NOT NULL THEN
            SELECT harvest_source_line_id, is_void, corrected_harvested_weight_kg, corrected_whole_unit_count
            INTO v_predecessor_line_id, v_predecessor_is_void, v_predecessor_weight, v_predecessor_count
            FROM harvest_source_line_corrections WHERE id = NEW.supersedes_correction_id;
            IF v_predecessor_line_id IS NULL THEN
                RAISE EXCEPTION 'superseded correction not found';
            END IF;
            IF v_predecessor_line_id <> NEW.harvest_source_line_id THEN
                RAISE EXCEPTION 'a correction may only supersede another correction belonging to the SAME original HarvestSourceLine';
            END IF;
            IF v_predecessor_is_void THEN
                v_predecessor_weight := 0;
                v_predecessor_count := 0;
            END IF;
        ELSE
            SELECT harvested_weight_kg, whole_unit_count INTO v_predecessor_weight, v_predecessor_count
            FROM harvest_source_lines WHERE id = NEW.harvest_source_line_id;
        END IF;
        v_predecessor_count := COALESCE(v_predecessor_count, 0);

        IF NEW.is_void THEN
            v_new_weight := 0;
            v_new_count := 0;
        ELSE
            v_new_weight := NEW.corrected_harvested_weight_kg;
            v_new_count := COALESCE(NEW.corrected_whole_unit_count, 0);
        END IF;

        IF v_new_weight = v_predecessor_weight AND v_new_count = v_predecessor_count THEN
            RAISE EXCEPTION 'correction does not change the effective tuple from its own immediate predecessor -- no-op corrections are rejected';
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

# =====================================================================
# enforce_harvest_correction_reconciliation -- deferred, proves current-
# effective per-line quantities (walked via each line's own correction-
# chain tip) reconcile with harvest_receipt + harvest_adjustment ledger
# entries for the lot. Never touches CMP-013's own
# enforce_harvest_reconciliation (unchanged, separate function/triggers).
# =====================================================================

_CORRECTION_RECONCILIATION_FUNCTION = """
    CREATE FUNCTION enforce_harvest_correction_reconciliation() RETURNS trigger AS $$
    DECLARE
        v_lot_id UUID;
        v_event_id UUID;
        v_ledger_weight NUMERIC;
        v_ledger_count BIGINT;
        v_effective_sum_weight NUMERIC := 0;
        v_effective_sum_count BIGINT := 0;
        v_any_count_null BOOLEAN := FALSE;
        v_lot_tracks_count BOOLEAN;
        rec RECORD;
        v_tip RECORD;
    BEGIN
        IF TG_TABLE_NAME = 'harvest_source_line_corrections' THEN
            SELECT lot.id, lot.harvest_event_id INTO v_lot_id, v_event_id
            FROM harvest_source_lines l
            JOIN harvested_produce_lots lot ON lot.harvest_event_id = l.harvest_event_id
            WHERE l.id = NEW.harvest_source_line_id;
        ELSIF TG_TABLE_NAME = 'produce_lot_ledger_entries' THEN
            IF NEW.entry_kind <> 'harvest_adjustment' THEN
                RETURN NEW;
            END IF;
            SELECT id, harvest_event_id INTO v_lot_id, v_event_id
            FROM harvested_produce_lots WHERE id = NEW.produce_lot_id;
        END IF;

        IF v_lot_id IS NULL THEN
            RETURN NEW;
        END IF;

        SELECT total_whole_unit_count IS NOT NULL INTO v_lot_tracks_count
        FROM harvested_produce_lots WHERE id = v_lot_id;

        FOR rec IN SELECT id, harvested_weight_kg, whole_unit_count FROM harvest_source_lines WHERE harvest_event_id = v_event_id LOOP
            SELECT c.is_void, c.corrected_harvested_weight_kg, c.corrected_whole_unit_count
            INTO v_tip
            FROM harvest_source_line_corrections c
            WHERE c.harvest_source_line_id = rec.id
              AND NOT EXISTS (SELECT 1 FROM harvest_source_line_corrections s WHERE s.supersedes_correction_id = c.id);

            IF v_tip.is_void IS NULL THEN
                v_effective_sum_weight := v_effective_sum_weight + rec.harvested_weight_kg;
                IF rec.whole_unit_count IS NULL THEN
                    v_any_count_null := TRUE;
                ELSE
                    v_effective_sum_count := v_effective_sum_count + rec.whole_unit_count;
                END IF;
            ELSIF v_tip.is_void THEN
                NULL;
            ELSE
                v_effective_sum_weight := v_effective_sum_weight + v_tip.corrected_harvested_weight_kg;
                v_effective_sum_count := v_effective_sum_count + v_tip.corrected_whole_unit_count;
            END IF;
        END LOOP;

        SELECT COALESCE(SUM(weight_delta_kg), 0), COALESCE(SUM(whole_unit_count_delta), 0)
        INTO v_ledger_weight, v_ledger_count
        FROM produce_lot_ledger_entries
        WHERE produce_lot_id = v_lot_id AND entry_kind IN ('harvest_receipt', 'harvest_adjustment');

        IF v_ledger_weight <> v_effective_sum_weight THEN
            RAISE EXCEPTION 'harvest correction reconciliation failed for produce lot %: ledger weight % <> effective source-line sum %',
                v_lot_id, v_ledger_weight, v_effective_sum_weight;
        END IF;

        IF v_lot_tracks_count AND NOT v_any_count_null THEN
            IF v_ledger_count <> v_effective_sum_count THEN
                RAISE EXCEPTION 'harvest correction reconciliation failed for produce lot %: ledger count % <> effective source-line sum %',
                    v_lot_id, v_ledger_count, v_effective_sum_count;
            END IF;
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

# =====================================================================
# enforce_batch_carrier_assignment_closure_only_v2 -- widened again with
# the Harvest release branch + the two new columns joining the immutable-
# on-release column set.
# =====================================================================

_CLOSURE_ONLY_WITH_HARVEST = """
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
        v_harvest_event_kind TEXT;
        v_harvest_event_effective TIMESTAMPTZ;
        v_harvest_root UUID;
        v_harvest_root_opening INTEGER;
        v_harvest_available_after INTEGER;
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
           OR NEW.opening_harvest_population_reversal_event_id IS DISTINCT FROM OLD.opening_harvest_population_reversal_event_id
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
               AND NEW.released_by_production_disposition_event_id IS NULL
               AND NEW.released_by_harvest_population_event_id IS NULL)
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

            SELECT v_prod_root_opening
                + COALESCE((SELECT SUM(quantity_delta) FROM production_disposition_events
                            WHERE population_root_batch_carrier_assignment_id = v_prod_root
                              AND effective_time <= v_prod_event_effective), 0)
                + COALESCE((SELECT SUM(quantity_delta) FROM harvest_population_events
                            WHERE population_root_batch_carrier_assignment_id = v_prod_root
                              AND effective_time <= v_prod_event_effective), 0)
            INTO v_prod_available_after;

            IF v_prod_available_after <> 0 THEN
                RAISE EXCEPTION 'releasing production disposition event does not leave authoritative living population at zero (got %)', v_prod_available_after;
            END IF;
        ELSIF NEW.released_by_harvest_population_event_id IS NOT NULL THEN
            -- HARVEST-OPS-001: mirrors the production-disposition release
            -- branch above exactly, keyed by the SAME combined (disposition
            -- + harvest) population formula -- a Harvest CONSUMPTION and a
            -- Plant Loss REDUCTION are equally valid releasers of the same
            -- shared lineage.
            SELECT event_kind, effective_time, population_root_batch_carrier_assignment_id
            INTO v_harvest_event_kind, v_harvest_event_effective, v_harvest_root
            FROM harvest_population_events WHERE id = NEW.released_by_harvest_population_event_id;
            IF v_harvest_event_kind IS NULL THEN
                RAISE EXCEPTION 'releasing harvest population event not found';
            END IF;
            IF v_harvest_event_kind <> 'CONSUMPTION' THEN
                RAISE EXCEPTION 'only a CONSUMPTION event may release a batch_carrier_assignment';
            END IF;
            IF v_harvest_event_effective <> NEW.released_effective_time THEN
                RAISE EXCEPTION 'released_effective_time must match the releasing harvest population event''s effective time';
            END IF;
            IF v_harvest_root <> NEW.population_root_batch_carrier_assignment_id THEN
                RAISE EXCEPTION 'releasing harvest population event does not share this assignment''s own population root';
            END IF;

            SELECT assigned_plant_count INTO v_harvest_root_opening
            FROM transplant_destination_lines WHERE destination_batch_carrier_assignment_id = v_harvest_root;

            SELECT v_harvest_root_opening
                + COALESCE((SELECT SUM(quantity_delta) FROM production_disposition_events
                            WHERE population_root_batch_carrier_assignment_id = v_harvest_root
                              AND effective_time <= v_harvest_event_effective), 0)
                + COALESCE((SELECT SUM(quantity_delta) FROM harvest_population_events
                            WHERE population_root_batch_carrier_assignment_id = v_harvest_root
                              AND effective_time <= v_harvest_event_effective), 0)
            INTO v_harvest_available_after;

            IF v_harvest_available_after <> 0 THEN
                RAISE EXCEPTION 'releasing harvest population event does not leave authoritative living population at zero (got %)', v_harvest_available_after;
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
# again with the harvest-population-reversal opener branch (mirrors the
# production-disposition-reversal branch exactly).
# =====================================================================

_ORIGIN_INTEGRITY_WITH_HARVEST_HEAD = """
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
        v_predecessor_released_by_harvest UUID;
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
        ELSIF NEW.opening_harvest_population_reversal_event_id IS NOT NULL THEN
            -- HARVEST-OPS-001: mirrors the production-disposition-reversal
            -- branch above exactly. A REVERSAL row's own typed-origin
            -- columns are both NULL by design (its identity comes from
            -- reverses_event_id, not from harvest_source_line_correction_id)
            -- -- resolve batch_id by walking through the TARGET CONSUMPTION
            -- being reversed (which always has exactly one typed origin
            -- populated) instead.
            SELECT he.batch_id, e.effective_time, e.event_kind, e.reverses_event_id
            INTO v_event_batch_id, v_event_effective, v_reversal_kind, v_reverses_id
            FROM harvest_population_events e
            JOIN harvest_population_events target ON target.id = e.reverses_event_id
            LEFT JOIN harvest_source_line_corrections c ON c.id = target.harvest_source_line_correction_id
            JOIN harvest_source_lines l ON l.id = COALESCE(target.original_harvest_source_line_id, c.harvest_source_line_id)
            JOIN harvest_events he ON he.id = l.harvest_event_id
            WHERE e.id = NEW.opening_harvest_population_reversal_event_id;
            IF v_event_batch_id IS NULL THEN
                RAISE EXCEPTION 'opening harvest population reversal event not found';
            END IF;
            IF v_reversal_kind <> 'REVERSAL' THEN
                RAISE EXCEPTION 'opening_harvest_population_reversal_event_id must reference a REVERSAL-kind harvest population event';
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
            SELECT carrier_id, batch_stage_run_id, released_by_harvest_population_event_id,
                   population_root_batch_carrier_assignment_id
            INTO v_predecessor_carrier_id, v_predecessor_run_id, v_predecessor_released_by_harvest,
                 v_predecessor_root
            FROM batch_carrier_assignments WHERE id = NEW.restored_from_batch_carrier_assignment_id;
            IF v_predecessor_carrier_id IS DISTINCT FROM NEW.carrier_id THEN
                RAISE EXCEPTION 'restored assignment must be for the same physical Carrier as its predecessor';
            END IF;
            IF v_predecessor_run_id IS DISTINCT FROM NEW.batch_stage_run_id THEN
                RAISE EXCEPTION 'restored assignment must preserve its predecessor''s own stage run';
            END IF;
            IF v_predecessor_released_by_harvest IS DISTINCT FROM v_reverses_id THEN
                RAISE EXCEPTION 'restored assignment predecessor must have been released by the exact event this reversal reverses';
            END IF;
            IF NEW.population_root_batch_carrier_assignment_id IS DISTINCT FROM v_predecessor_root THEN
                RAISE EXCEPTION 'restored assignment must copy its predecessor''s own population root unchanged';
            END IF;
"""

_ORIGIN_INTEGRITY_TAIL = """
        ELSE
            SELECT effective_time INTO v_event_effective
            FROM batch_derivation_events WHERE id = NEW.opening_batch_derivation_event_id;
            IF v_event_effective IS NULL THEN
                RAISE EXCEPTION 'opening batch derivation event not found';
            END IF;
            IF NEW.population_root_batch_carrier_assignment_id IS NOT NULL THEN
                RAISE EXCEPTION 'a batch-derivation-origin assignment may not carry a population root';
            END IF;
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

# =====================================================================
# enforce_produce_lot_ledger_entry_insert_integrity_v2 -- widened again
# with the harvest_adjustment branch: structural cross-checks against its
# own typed source (HarvestSourceLineCorrection), plus the same
# lock-the-lot / negative-balance guard packing_consumption already
# established, generalized to allow EITHER sign.
# =====================================================================

_LEDGER_ENTRY_INTEGRITY_WITH_HARVEST_ADJUSTMENT = """
    CREATE OR REPLACE FUNCTION enforce_produce_lot_ledger_entry_insert_integrity_v2() RETURNS trigger AS $$
    DECLARE
        v_lot_tenant_id UUID;
        v_lot_farm_id UUID;
        v_lot_event_id UUID;
        v_lot_weight NUMERIC;
        v_lot_count BIGINT;
        v_lot_effective TIMESTAMPTZ;
        v_lot_recorded TIMESTAMPTZ;
        v_event_actor UUID;
        v_line RECORD;
        v_packing_event RECORD;
        v_prior_weight NUMERIC;
        v_prior_count BIGINT;
        v_remaining_weight NUMERIC;
        v_remaining_count BIGINT;
        v_correction RECORD;
        v_correction_lot_id UUID;
        v_correction_lot_tracks_count BOOLEAN;
        v_original_event_effective TIMESTAMPTZ;
        v_predecessor_is_void BOOLEAN;
        v_predecessor_weight NUMERIC;
        v_predecessor_count BIGINT;
        v_new_weight NUMERIC;
        v_new_count BIGINT;
        v_expected_count_delta BIGINT;
    BEGIN
        IF NEW.entry_kind = 'harvest_receipt' THEN
            SELECT tenant_id, farm_id, harvest_event_id, total_harvested_weight_kg, total_whole_unit_count,
                   effective_time, recorded_at
            INTO v_lot_tenant_id, v_lot_farm_id, v_lot_event_id, v_lot_weight, v_lot_count, v_lot_effective,
                 v_lot_recorded
            FROM harvested_produce_lots WHERE id = NEW.produce_lot_id;
            IF v_lot_tenant_id IS NULL THEN
                RAISE EXCEPTION 'produce lot not found for ledger entry';
            END IF;
            IF v_lot_tenant_id <> NEW.tenant_id OR v_lot_farm_id <> NEW.farm_id THEN
                RAISE EXCEPTION 'ledger entry tenant/farm does not match the produce lot''s own';
            END IF;
            IF v_lot_event_id <> NEW.harvest_event_id THEN
                RAISE EXCEPTION 'ledger entry harvest event does not match the produce lot''s own event';
            END IF;

            SELECT actor_user_id INTO v_event_actor FROM harvest_events WHERE id = NEW.harvest_event_id;
            IF v_event_actor IS NULL THEN
                RAISE EXCEPTION 'harvest event not found for ledger entry';
            END IF;

            IF NEW.id <> NEW.produce_lot_id THEN
                RAISE EXCEPTION 'harvest receipt id must equal its produce lot id';
            END IF;
            IF NEW.weight_delta_kg <> v_lot_weight THEN
                RAISE EXCEPTION 'harvest receipt weight does not match the produce lot''s total weight';
            END IF;
            IF NEW.whole_unit_count_delta IS DISTINCT FROM v_lot_count THEN
                RAISE EXCEPTION 'harvest receipt count does not match the produce lot''s total count';
            END IF;
            IF NEW.actor_user_id <> v_event_actor THEN
                RAISE EXCEPTION 'harvest receipt actor does not match the harvest event''s actor';
            END IF;
            IF NEW.effective_time <> v_lot_effective THEN
                RAISE EXCEPTION 'harvest receipt effective time does not match the produce lot''s effective time';
            END IF;
            IF NEW.recorded_time <> v_lot_recorded THEN
                RAISE EXCEPTION 'harvest receipt recorded time does not match the produce lot''s recorded time';
            END IF;
            IF NEW.note IS NOT NULL THEN
                RAISE EXCEPTION 'harvest receipt note must be null';
            END IF;

        ELSIF NEW.entry_kind = 'packing_consumption' THEN
            SELECT * INTO v_line FROM packing_input_lines WHERE id = NEW.id;
            IF v_line.id IS NULL THEN
                RAISE EXCEPTION 'packing input line not found for ledger debit';
            END IF;
            IF v_line.packing_event_id <> NEW.packing_event_id THEN
                RAISE EXCEPTION 'ledger debit packing event does not match its input line''s own';
            END IF;
            IF v_line.harvested_produce_lot_id <> NEW.produce_lot_id THEN
                RAISE EXCEPTION 'ledger debit produce lot does not match its input line''s own';
            END IF;
            IF v_line.tenant_id <> NEW.tenant_id OR v_line.farm_id <> NEW.farm_id THEN
                RAISE EXCEPTION 'ledger debit tenant/farm does not match its input line''s own';
            END IF;

            SELECT * INTO v_packing_event FROM packing_events WHERE id = NEW.packing_event_id;
            IF v_packing_event.id IS NULL THEN
                RAISE EXCEPTION 'packing event not found for ledger debit';
            END IF;

            IF NEW.weight_delta_kg <> -v_line.consumed_weight_kg THEN
                RAISE EXCEPTION 'ledger debit weight does not match the negative of its input line''s consumed weight';
            END IF;
            IF NEW.whole_unit_count_delta IS DISTINCT FROM
               (CASE WHEN v_line.consumed_whole_unit_count IS NULL THEN NULL ELSE -v_line.consumed_whole_unit_count END)
            THEN
                RAISE EXCEPTION 'ledger debit count does not match the negative of its input line''s consumed count';
            END IF;
            IF NEW.effective_time <> v_packing_event.effective_time THEN
                RAISE EXCEPTION 'ledger debit effective time does not match its packing event''s effective time';
            END IF;
            IF NEW.recorded_time <> v_line.recorded_time THEN
                RAISE EXCEPTION 'ledger debit recorded time does not match its input line''s recorded time';
            END IF;
            IF NEW.actor_user_id <> v_packing_event.actor_user_id THEN
                RAISE EXCEPTION 'ledger debit actor does not match its packing event''s actor';
            END IF;
            IF NEW.note IS DISTINCT FROM v_line.note THEN
                RAISE EXCEPTION 'ledger debit note does not match its input line''s note';
            END IF;

            SELECT total_whole_unit_count INTO v_lot_count
            FROM harvested_produce_lots WHERE id = NEW.produce_lot_id FOR UPDATE;

            SELECT COALESCE(sum(weight_delta_kg), 0), SUM(whole_unit_count_delta)
            INTO v_prior_weight, v_prior_count
            FROM produce_lot_ledger_entries WHERE produce_lot_id = NEW.produce_lot_id;

            v_remaining_weight := v_prior_weight + NEW.weight_delta_kg;
            IF v_remaining_weight < 0 THEN
                RAISE EXCEPTION 'packing consumption would leave produce lot % with negative available weight', NEW.produce_lot_id;
            END IF;

            IF v_lot_count IS NULL THEN
                IF NEW.whole_unit_count_delta IS NOT NULL THEN
                    RAISE EXCEPTION 'produce lot % does not track whole-unit count; ledger debit count must be null', NEW.produce_lot_id;
                END IF;
            ELSE
                IF NEW.whole_unit_count_delta IS NULL THEN
                    RAISE EXCEPTION 'produce lot % tracks whole-unit count; ledger debit count is required', NEW.produce_lot_id;
                END IF;
                v_remaining_count := COALESCE(v_prior_count, 0) + NEW.whole_unit_count_delta;
                IF v_remaining_count < 0 THEN
                    RAISE EXCEPTION 'packing consumption would leave produce lot % with negative available count', NEW.produce_lot_id;
                END IF;
                IF (v_remaining_weight = 0 AND v_remaining_count > 0)
                   OR (v_remaining_weight > 0 AND v_remaining_count = 0) THEN
                    RAISE EXCEPTION 'packing consumption would leave produce lot % with mismatched residual weight/count', NEW.produce_lot_id;
                END IF;
            END IF;

        ELSIF NEW.entry_kind = 'harvest_adjustment' THEN
            SELECT * INTO v_correction FROM harvest_source_line_corrections WHERE id = NEW.harvest_source_line_correction_id;
            IF v_correction.id IS NULL THEN
                RAISE EXCEPTION 'harvest source line correction not found for ledger adjustment';
            END IF;
            IF v_correction.tenant_id <> NEW.tenant_id OR v_correction.farm_id <> NEW.farm_id THEN
                RAISE EXCEPTION 'ledger adjustment tenant/farm does not match its correction''s own';
            END IF;
            IF NEW.id <> v_correction.id THEN
                RAISE EXCEPTION 'harvest adjustment id must equal its correction''s own id';
            END IF;
            IF NEW.actor_user_id <> v_correction.actor_user_id THEN
                RAISE EXCEPTION 'ledger adjustment actor does not match its correction''s own actor';
            END IF;
            IF NEW.recorded_time <> v_correction.recorded_at THEN
                RAISE EXCEPTION 'ledger adjustment recorded time does not match its correction''s own recorded time';
            END IF;
            IF NEW.note IS DISTINCT FROM v_correction.note THEN
                RAISE EXCEPTION 'ledger adjustment note does not match its correction''s own note';
            END IF;

            SELECT lot.id, lot.total_whole_unit_count IS NOT NULL, he.effective_time
            INTO v_correction_lot_id, v_correction_lot_tracks_count, v_original_event_effective
            FROM harvest_source_lines l
            JOIN harvest_events he ON he.id = l.harvest_event_id
            JOIN harvested_produce_lots lot ON lot.harvest_event_id = l.harvest_event_id
            WHERE l.id = v_correction.harvest_source_line_id;
            IF v_correction_lot_id <> NEW.produce_lot_id THEN
                RAISE EXCEPTION 'ledger adjustment produce lot does not match its correction''s own line/lot chain';
            END IF;
            IF NEW.effective_time <> v_original_event_effective THEN
                RAISE EXCEPTION 'ledger adjustment effective time must match the ORIGINAL harvest event''s effective time';
            END IF;

            -- CTO CORRECTION 1 / Finding 2.D: deterministic per-fact
            -- arithmetic proof -- the adjustment must equal exactly (this
            -- correction's own new effective tuple) minus (its IMMEDIATE
            -- PREDECESSOR's own effective tuple), never the original once a
            -- prior correction exists. The predecessor is the original
            -- HarvestSourceLine's own values when supersedes_correction_id
            -- IS NULL, or the superseded correction's own complete tuple
            -- (0/0 if that predecessor was itself void) otherwise -- exactly
            -- the same resolution the service layer performs, now proven
            -- independently at the DB level.
            IF v_correction.supersedes_correction_id IS NULL THEN
                SELECT harvested_weight_kg, whole_unit_count INTO v_predecessor_weight, v_predecessor_count
                FROM harvest_source_lines WHERE id = v_correction.harvest_source_line_id;
            ELSE
                SELECT is_void, corrected_harvested_weight_kg, corrected_whole_unit_count
                INTO v_predecessor_is_void, v_predecessor_weight, v_predecessor_count
                FROM harvest_source_line_corrections WHERE id = v_correction.supersedes_correction_id;
                IF v_predecessor_is_void THEN
                    v_predecessor_weight := 0;
                    v_predecessor_count := 0;
                END IF;
            END IF;
            v_predecessor_count := COALESCE(v_predecessor_count, 0);

            IF v_correction.is_void THEN
                v_new_weight := 0;
                v_new_count := 0;
            ELSE
                v_new_weight := v_correction.corrected_harvested_weight_kg;
                v_new_count := COALESCE(v_correction.corrected_whole_unit_count, 0);
            END IF;

            IF NEW.weight_delta_kg <> (v_new_weight - v_predecessor_weight) THEN
                RAISE EXCEPTION 'harvest adjustment weight_delta_kg (%) does not equal the new effective tuple minus the immediate predecessor''s own (expected %)',
                    NEW.weight_delta_kg, (v_new_weight - v_predecessor_weight);
            END IF;

            v_expected_count_delta := v_new_count - v_predecessor_count;
            IF v_expected_count_delta = 0 THEN
                IF NEW.whole_unit_count_delta IS NOT NULL THEN
                    RAISE EXCEPTION 'harvest adjustment whole_unit_count_delta must be NULL when the effective count is unchanged (got %)', NEW.whole_unit_count_delta;
                END IF;
            ELSIF NEW.whole_unit_count_delta IS DISTINCT FROM v_expected_count_delta THEN
                RAISE EXCEPTION 'harvest adjustment whole_unit_count_delta (%) does not equal the new effective tuple minus the immediate predecessor''s own (expected %)',
                    NEW.whole_unit_count_delta, v_expected_count_delta;
            END IF;

            -- Lock the source lot row -- the serialization point for every
            -- current and future typed consumer -- and compute its balance
            -- prior to this insert. A harvest_adjustment may be EITHER
            -- sign; only the negative-balance floor is enforced, never a
            -- positive ceiling (an increasing correction can never harm
            -- the balance).
            PERFORM 1 FROM harvested_produce_lots WHERE id = NEW.produce_lot_id FOR UPDATE;

            SELECT COALESCE(sum(weight_delta_kg), 0), SUM(whole_unit_count_delta)
            INTO v_prior_weight, v_prior_count
            FROM produce_lot_ledger_entries WHERE produce_lot_id = NEW.produce_lot_id;

            v_remaining_weight := v_prior_weight + NEW.weight_delta_kg;
            IF v_remaining_weight < 0 THEN
                RAISE EXCEPTION 'harvest correction would leave produce lot % with negative available weight', NEW.produce_lot_id;
            END IF;

            IF v_correction_lot_tracks_count AND NEW.whole_unit_count_delta IS NOT NULL THEN
                v_remaining_count := COALESCE(v_prior_count, 0) + NEW.whole_unit_count_delta;
                IF v_remaining_count < 0 THEN
                    RAISE EXCEPTION 'harvest correction would leave produce lot % with negative available count', NEW.produce_lot_id;
                END IF;
            END IF;

        ELSE
            RAISE EXCEPTION 'unknown ledger entry kind %', NEW.entry_kind;
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

# =====================================================================
# enforce_harvest_event_insert_integrity -- CMP-013's own trigger (from
# c7f14b8e29a3) independently re-enforces `stage_category = 'harvesting'`
# at the DB level, not merely in the generic service's own Python check.
# Widened (CREATE OR REPLACE) with a transaction-local escape hatch for
# Leafy Harvest ONLY, set via `SET LOCAL cmp.leafy_harvest = 'true'` by
# `record_leafy_harvest` (never by the generic path) immediately before
# its own insert -- resets automatically at transaction end, never leaks
# across connections/transactions. Every other check is byte-for-byte
# unchanged from c7f14b8e29a3's own version (decision 2: never weaken the
# generic gate).
# =====================================================================

_HARVEST_EVENT_INTEGRITY_WITH_LEAFY_BYPASS = """
    CREATE OR REPLACE FUNCTION enforce_harvest_event_insert_integrity() RETURNS trigger AS $$
    DECLARE
        v_batch_tenant_id UUID;
        v_batch_farm_id UUID;
        v_batch_state TEXT;
        v_batch_created TIMESTAMPTZ;
        v_run_batch_id UUID;
        v_run_exited TIMESTAMPTZ;
        v_run_entered TIMESTAMPTZ;
        v_stage_category TEXT;
        v_open_hold_count INTEGER;
    BEGIN
        SELECT tenant_id, farm_id, state, created_effective_time
        INTO v_batch_tenant_id, v_batch_farm_id, v_batch_state, v_batch_created
        FROM crop_batches WHERE id = NEW.batch_id FOR UPDATE;
        IF v_batch_state IS NULL THEN
            RAISE EXCEPTION 'crop batch not found for harvest event';
        END IF;
        IF v_batch_tenant_id <> NEW.tenant_id OR v_batch_farm_id <> NEW.farm_id THEN
            RAISE EXCEPTION 'harvest event tenant/farm does not match the crop batch''s own';
        END IF;
        IF v_batch_state <> 'active' THEN
            RAISE EXCEPTION 'crop batch is not active';
        END IF;
        IF NEW.effective_time > clock_timestamp() THEN
            RAISE EXCEPTION 'harvest event effective time cannot be in the future';
        END IF;
        IF NEW.effective_time < v_batch_created THEN
            RAISE EXCEPTION 'harvest event effective time precedes the batch''s creation effective time';
        END IF;

        SELECT batch_id, exited_effective_time, entered_effective_time
        INTO v_run_batch_id, v_run_exited, v_run_entered
        FROM batch_stage_runs WHERE id = NEW.active_batch_stage_run_id;
        IF v_run_batch_id IS NULL THEN
            RAISE EXCEPTION 'active stage run not found';
        END IF;
        IF v_run_batch_id <> NEW.batch_id THEN
            RAISE EXCEPTION 'stage run does not belong to this batch';
        END IF;
        IF v_run_exited IS NOT NULL THEN
            RAISE EXCEPTION 'harvest requires the batch''s currently active stage run';
        END IF;
        IF NEW.effective_time < v_run_entered THEN
            RAISE EXCEPTION 'harvest event effective time precedes the current stage run''s entry time';
        END IF;

        SELECT s.stage_category INTO v_stage_category
        FROM batch_stage_runs r JOIN workflow_stages s ON s.id = r.workflow_stage_id
        WHERE r.id = NEW.active_batch_stage_run_id;
        -- HARVEST-OPS-001: Leafy Harvest is exempt from this gate (decision
        -- 3) -- proven by the transaction-local marker the Leafy service
        -- path alone sets, never by inspecting the row itself (HarvestEvent
        -- carries no "kind" column of its own, by design -- one shared
        -- table, decision 1).
        IF v_stage_category IS DISTINCT FROM 'harvesting'
           AND COALESCE(current_setting('cmp.leafy_harvest', true), 'false') <> 'true'
        THEN
            RAISE EXCEPTION 'current stage is not a harvesting stage';
        END IF;

        SELECT count(*) INTO v_open_hold_count
        FROM quality_holds h
        WHERE h.batch_id = NEW.batch_id
          AND NOT EXISTS (SELECT 1 FROM quality_hold_releases r WHERE r.quality_hold_id = h.id);
        IF v_open_hold_count > 0 THEN
            RAISE EXCEPTION 'crop batch has an open quality hold';
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

_PRIOR_HARVEST_EVENT_INTEGRITY_FUNCTION = """
    CREATE OR REPLACE FUNCTION enforce_harvest_event_insert_integrity() RETURNS trigger AS $$
    DECLARE
        v_batch_tenant_id UUID;
        v_batch_farm_id UUID;
        v_batch_state TEXT;
        v_batch_created TIMESTAMPTZ;
        v_run_batch_id UUID;
        v_run_exited TIMESTAMPTZ;
        v_run_entered TIMESTAMPTZ;
        v_stage_category TEXT;
        v_open_hold_count INTEGER;
    BEGIN
        SELECT tenant_id, farm_id, state, created_effective_time
        INTO v_batch_tenant_id, v_batch_farm_id, v_batch_state, v_batch_created
        FROM crop_batches WHERE id = NEW.batch_id FOR UPDATE;
        IF v_batch_state IS NULL THEN
            RAISE EXCEPTION 'crop batch not found for harvest event';
        END IF;
        IF v_batch_tenant_id <> NEW.tenant_id OR v_batch_farm_id <> NEW.farm_id THEN
            RAISE EXCEPTION 'harvest event tenant/farm does not match the crop batch''s own';
        END IF;
        IF v_batch_state <> 'active' THEN
            RAISE EXCEPTION 'crop batch is not active';
        END IF;
        IF NEW.effective_time > clock_timestamp() THEN
            RAISE EXCEPTION 'harvest event effective time cannot be in the future';
        END IF;
        IF NEW.effective_time < v_batch_created THEN
            RAISE EXCEPTION 'harvest event effective time precedes the batch''s creation effective time';
        END IF;

        SELECT batch_id, exited_effective_time, entered_effective_time
        INTO v_run_batch_id, v_run_exited, v_run_entered
        FROM batch_stage_runs WHERE id = NEW.active_batch_stage_run_id;
        IF v_run_batch_id IS NULL THEN
            RAISE EXCEPTION 'active stage run not found';
        END IF;
        IF v_run_batch_id <> NEW.batch_id THEN
            RAISE EXCEPTION 'stage run does not belong to this batch';
        END IF;
        IF v_run_exited IS NOT NULL THEN
            RAISE EXCEPTION 'harvest requires the batch''s currently active stage run';
        END IF;
        IF NEW.effective_time < v_run_entered THEN
            RAISE EXCEPTION 'harvest event effective time precedes the current stage run''s entry time';
        END IF;

        SELECT s.stage_category INTO v_stage_category
        FROM batch_stage_runs r JOIN workflow_stages s ON s.id = r.workflow_stage_id
        WHERE r.id = NEW.active_batch_stage_run_id;
        IF v_stage_category IS DISTINCT FROM 'harvesting' THEN
            RAISE EXCEPTION 'current stage is not a harvesting stage';
        END IF;

        SELECT count(*) INTO v_open_hold_count
        FROM quality_holds h
        WHERE h.batch_id = NEW.batch_id
          AND NOT EXISTS (SELECT 1 FROM quality_hold_releases r WHERE r.quality_hold_id = h.id);
        IF v_open_hold_count > 0 THEN
            RAISE EXCEPTION 'crop batch has an open quality hold';
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """


def upgrade() -> None:
    bind = op.get_bind()

    # --- 0. Defensive historical safety -------------------------------------
    # This ticket does NOT assume no historical CMP-013 harvest_source_lines
    # row exists against a production_cultivation_plate-typed BCA merely
    # because current QA history never used one -- assert it explicitly and
    # raise loudly rather than silently inventing population history.
    stray_count = bind.execute(
        sa.text(
            "SELECT count(*) FROM harvest_source_lines hsl "
            "JOIN batch_carrier_assignments bca ON bca.id = hsl.batch_carrier_assignment_id "
            "JOIN carriers c ON c.id = bca.carrier_id "
            "JOIN carrier_types ct ON ct.id = c.carrier_type_id "
            "WHERE ct.code = 'production_cultivation_plate'"
        )
    ).scalar_one()
    if stray_count > 0:
        raise RuntimeError(
            f"cannot apply b8f3c6d1e947: {stray_count} pre-existing harvest_source_lines row(s) already reference "
            "a production_cultivation_plate BCA with no population tracking -- this migration cannot safely "
            "backfill population history for them without inventing facts. Resolve manually before upgrading."
        )

    # --- 1. batch_carrier_assignments: new columns --------------------------
    op.add_column(
        "batch_carrier_assignments",
        sa.Column("released_by_harvest_population_event_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "batch_carrier_assignments",
        sa.Column("opening_harvest_population_reversal_event_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    # --- 2. harvest_source_line_corrections ---------------------------------
    op.create_table(
        "harvest_source_line_corrections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column(
            "harvest_source_line_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("harvest_source_lines.id"), nullable=False,
        ),
        sa.Column(
            "supersedes_correction_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("harvest_source_line_corrections.id"), nullable=True,
        ),
        sa.Column("is_void", sa.Boolean(), nullable=False),
        sa.Column("corrected_harvested_weight_kg", sa.Numeric(), nullable=True),
        sa.Column("corrected_whole_unit_count", sa.BigInteger(), nullable=True),
        sa.Column("reason_code", sa.String(), nullable=False),
        sa.Column("note", sa.String(), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "is_void = (corrected_harvested_weight_kg IS NULL AND corrected_whole_unit_count IS NULL)",
            name="ck_harvest_source_line_corrections_void_shape",
        ),
        sa.CheckConstraint(
            "is_void OR (corrected_harvested_weight_kg > 0 "
            "AND corrected_harvested_weight_kg = trunc(corrected_harvested_weight_kg, 3) "
            "AND corrected_harvested_weight_kg < 100000000000)",
            name="ck_harvest_source_line_corrections_weight_envelope",
        ),
        sa.CheckConstraint(
            "is_void OR corrected_whole_unit_count > 0",
            name="ck_harvest_source_line_corrections_count_positive",
        ),
        sa.CheckConstraint(
            "supersedes_correction_id IS NULL OR supersedes_correction_id <> id",
            name="ck_harvest_source_line_corrections_not_self",
        ),
        sa.CheckConstraint(
            "btrim(reason_code) <> '' AND btrim(note) <> ''",
            name="ck_harvest_source_line_corrections_reason_note_required",
        ),
        sa.UniqueConstraint(
            "tenant_id", "client_command_id", name="ux_harvest_source_line_corrections_tenant_client_command_id"
        ),
        sa.UniqueConstraint(
            "tenant_id", "farm_id", "id", name="uq_harvest_source_line_corrections_tenant_farm_id"
        ),
    )
    op.create_index(
        "ux_harvest_source_line_corrections_root_once",
        "harvest_source_line_corrections", ["harvest_source_line_id"], unique=True,
        postgresql_where=sa.text("supersedes_correction_id IS NULL"),
    )
    op.create_index(
        "ux_harvest_source_line_corrections_successor_once",
        "harvest_source_line_corrections", ["supersedes_correction_id"], unique=True,
        postgresql_where=sa.text("supersedes_correction_id IS NOT NULL"),
    )

    # --- 3. harvest_population_events ---------------------------------------
    op.create_table(
        "harvest_population_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column(
            "population_root_batch_carrier_assignment_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("batch_carrier_assignments.id"), nullable=False,
        ),
        sa.Column(
            "batch_carrier_assignment_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("batch_carrier_assignments.id"), nullable=False,
        ),
        sa.Column("event_kind", sa.String(), nullable=False),
        sa.Column("quantity_delta", sa.Integer(), nullable=False),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("reverses_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "original_harvest_source_line_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("harvest_source_lines.id"), nullable=True,
        ),
        sa.Column(
            "harvest_source_line_correction_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("harvest_source_line_corrections.id"), nullable=True,
        ),
        sa.CheckConstraint("event_kind IN ('CONSUMPTION', 'REVERSAL')", name="ck_harvest_population_events_kind"),
        sa.CheckConstraint("quantity_delta <> 0", name="ck_harvest_population_events_delta_nonzero"),
        sa.CheckConstraint(
            "(event_kind = 'CONSUMPTION' AND quantity_delta < 0 AND reverses_event_id IS NULL) OR "
            "(event_kind = 'REVERSAL' AND quantity_delta > 0 AND reverses_event_id IS NOT NULL)",
            name="ck_harvest_population_events_kind_sign_consistency",
        ),
        sa.CheckConstraint(
            "(event_kind = 'CONSUMPTION' AND "
            "(CASE WHEN original_harvest_source_line_id IS NOT NULL THEN 1 ELSE 0 END "
            "+ CASE WHEN harvest_source_line_correction_id IS NOT NULL THEN 1 ELSE 0 END) = 1) "
            "OR (event_kind = 'REVERSAL' AND original_harvest_source_line_id IS NULL "
            "AND harvest_source_line_correction_id IS NULL)",
            name="ck_harvest_population_events_typed_origin_shape",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_carrier_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id", "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_harvest_population_events_tenant_farm_assignment",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "population_root_batch_carrier_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id", "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_harvest_population_events_tenant_farm_root",
        ),
        sa.UniqueConstraint("tenant_id", "farm_id", "id", name="uq_harvest_population_events_tenant_farm_id"),
    )
    # Self-referencing FK added separately, after the table exists.
    op.create_foreign_key(
        "fk_harvest_population_events_reverses_event",
        "harvest_population_events", "harvest_population_events", ["reverses_event_id"], ["id"],
    )
    op.create_index(
        "ux_harvest_population_events_reverses_once",
        "harvest_population_events", ["reverses_event_id"], unique=True,
        postgresql_where=sa.text("reverses_event_id IS NOT NULL"),
    )
    op.create_index(
        "ux_harvest_population_events_original_line_once",
        "harvest_population_events", ["original_harvest_source_line_id"], unique=True,
        postgresql_where=sa.text("original_harvest_source_line_id IS NOT NULL"),
    )
    op.create_index(
        "ux_harvest_population_events_correction_once",
        "harvest_population_events", ["harvest_source_line_correction_id"], unique=True,
        postgresql_where=sa.text("harvest_source_line_correction_id IS NOT NULL"),
    )
    op.create_index(
        "ix_harvest_population_events_root_effective",
        "harvest_population_events", ["population_root_batch_carrier_assignment_id", "effective_time"],
    )
    op.create_index(
        "ix_harvest_population_events_assignment", "harvest_population_events", ["batch_carrier_assignment_id"],
    )

    # --- 4. produce_lot_ledger_entries: harvest_adjustment widening ---------
    op.add_column(
        "produce_lot_ledger_entries",
        sa.Column(
            "harvest_source_line_correction_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("harvest_source_line_corrections.id"), nullable=True,
        ),
    )
    op.drop_constraint("ck_produce_lot_ledger_entries_kind_allowed", "produce_lot_ledger_entries", type_="check")
    op.create_check_constraint(
        "ck_produce_lot_ledger_entries_kind_allowed", "produce_lot_ledger_entries",
        "entry_kind IN ('harvest_receipt', 'packing_consumption', 'harvest_adjustment')",
    )
    op.drop_constraint("ck_produce_lot_ledger_entries_weight_envelope", "produce_lot_ledger_entries", type_="check")
    op.create_check_constraint(
        "ck_produce_lot_ledger_entries_weight_envelope", "produce_lot_ledger_entries",
        "(entry_kind = 'harvest_receipt' AND weight_delta_kg > 0 "
        "AND weight_delta_kg = trunc(weight_delta_kg, 3) AND weight_delta_kg < 100000000000) "
        "OR (entry_kind = 'packing_consumption' AND weight_delta_kg < 0 "
        "AND weight_delta_kg = trunc(weight_delta_kg, 3) AND weight_delta_kg > -100000000000) "
        "OR (entry_kind = 'harvest_adjustment' "
        "AND weight_delta_kg = trunc(weight_delta_kg, 3) "
        "AND weight_delta_kg > -100000000000 AND weight_delta_kg < 100000000000)",
    )
    op.drop_constraint("ck_produce_lot_ledger_entries_count_positive", "produce_lot_ledger_entries", type_="check")
    op.create_check_constraint(
        "ck_produce_lot_ledger_entries_count_positive", "produce_lot_ledger_entries",
        "(entry_kind = 'harvest_receipt' AND (whole_unit_count_delta IS NULL OR whole_unit_count_delta > 0)) "
        "OR (entry_kind = 'packing_consumption' AND (whole_unit_count_delta IS NULL OR whole_unit_count_delta < 0)) "
        "OR (entry_kind = 'harvest_adjustment' AND (whole_unit_count_delta IS NULL OR whole_unit_count_delta <> 0))",
    )
    op.create_check_constraint(
        "ck_produce_lot_ledger_entries_harvest_adjustment_nonzero", "produce_lot_ledger_entries",
        "entry_kind <> 'harvest_adjustment' OR weight_delta_kg <> 0 OR whole_unit_count_delta IS NOT NULL",
    )
    op.drop_constraint(
        "ck_produce_lot_ledger_entries_typed_source_shape", "produce_lot_ledger_entries", type_="check"
    )
    op.create_check_constraint(
        "ck_produce_lot_ledger_entries_typed_source_shape", "produce_lot_ledger_entries",
        "(entry_kind = 'harvest_receipt' AND harvest_event_id IS NOT NULL AND packing_event_id IS NULL "
        "AND harvest_source_line_correction_id IS NULL) "
        "OR (entry_kind = 'packing_consumption' AND harvest_event_id IS NULL AND packing_event_id IS NOT NULL "
        "AND harvest_source_line_correction_id IS NULL) "
        "OR (entry_kind = 'harvest_adjustment' AND harvest_event_id IS NULL AND packing_event_id IS NULL "
        "AND harvest_source_line_correction_id IS NOT NULL)",
    )
    op.create_index(
        "ux_produce_lot_ledger_entries_correction_harvest_adjustment",
        "produce_lot_ledger_entries", ["harvest_source_line_correction_id"], unique=True,
        postgresql_where=sa.text("entry_kind = 'harvest_adjustment'"),
    )
    op.create_foreign_key(
        "fk_produce_lot_ledger_entries_tenant_farm_correction",
        "produce_lot_ledger_entries", "harvest_source_line_corrections",
        ["tenant_id", "farm_id", "harvest_source_line_correction_id"],
        ["tenant_id", "farm_id", "id"],
    )

    # --- 5. batch_carrier_assignments: widened CHECK constraints ------------
    op.drop_constraint("ck_batch_carrier_assignments_exactly_one_opener", "batch_carrier_assignments", type_="check")
    op.create_check_constraint(
        "ck_batch_carrier_assignments_exactly_one_opener", "batch_carrier_assignments",
        "(CASE WHEN opening_sowing_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN opening_transplant_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN opening_batch_derivation_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN opening_transplant_reversal_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN opening_seedling_disposition_reversal_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN opening_production_disposition_reversal_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN opening_harvest_population_reversal_event_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
    )
    op.drop_constraint(
        "ck_batch_carrier_assignments_release_fields_together", "batch_carrier_assignments", type_="check"
    )
    op.create_check_constraint(
        "ck_batch_carrier_assignments_release_fields_together", "batch_carrier_assignments",
        "(released_effective_time IS NULL) = "
        "(released_by_transplant_event_id IS NULL AND released_by_batch_derivation_event_id IS NULL "
        "AND released_by_seedling_disposition_event_id IS NULL "
        "AND released_by_production_disposition_event_id IS NULL "
        "AND released_by_harvest_population_event_id IS NULL)",
    )
    op.drop_constraint(
        "ck_batch_carrier_assignments_at_most_one_releaser", "batch_carrier_assignments", type_="check"
    )
    op.create_check_constraint(
        "ck_batch_carrier_assignments_at_most_one_releaser", "batch_carrier_assignments",
        "(CASE WHEN released_by_transplant_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN released_by_batch_derivation_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN released_by_seedling_disposition_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN released_by_production_disposition_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN released_by_harvest_population_event_id IS NOT NULL THEN 1 ELSE 0 END) <= 1",
    )
    op.drop_constraint(
        "ck_batch_carrier_assignments_only_production_source_releasable", "batch_carrier_assignments", type_="check"
    )
    op.create_check_constraint(
        "ck_batch_carrier_assignments_only_production_source_releasable", "batch_carrier_assignments",
        "released_by_production_disposition_event_id IS NULL "
        "OR opening_transplant_event_id IS NOT NULL "
        "OR opening_production_disposition_reversal_event_id IS NOT NULL "
        "OR opening_harvest_population_reversal_event_id IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_batch_carrier_assignments_only_harvest_source_releasable", "batch_carrier_assignments",
        "released_by_harvest_population_event_id IS NULL "
        "OR opening_transplant_event_id IS NOT NULL "
        "OR opening_production_disposition_reversal_event_id IS NOT NULL "
        "OR opening_harvest_population_reversal_event_id IS NOT NULL",
    )
    op.drop_constraint(
        "ck_batch_carrier_assignments_restoration_opener_match", "batch_carrier_assignments", type_="check"
    )
    op.create_check_constraint(
        "ck_batch_carrier_assignments_restoration_opener_match", "batch_carrier_assignments",
        "(restored_from_batch_carrier_assignment_id IS NOT NULL) = "
        "(opening_transplant_reversal_event_id IS NOT NULL "
        "OR opening_seedling_disposition_reversal_event_id IS NOT NULL "
        "OR opening_production_disposition_reversal_event_id IS NOT NULL "
        "OR opening_harvest_population_reversal_event_id IS NOT NULL)",
    )
    op.create_index(
        "ux_batch_carrier_assignments_released_by_harvest_pop_once",
        "batch_carrier_assignments", ["released_by_harvest_population_event_id"], unique=True,
        postgresql_where=sa.text("released_by_harvest_population_event_id IS NOT NULL"),
    )
    op.create_index(
        "ux_batch_carrier_assignments_opened_by_harvest_pop_once",
        "batch_carrier_assignments", ["opening_harvest_population_reversal_event_id"], unique=True,
        postgresql_where=sa.text("opening_harvest_population_reversal_event_id IS NOT NULL"),
    )
    op.create_foreign_key(
        "fk_batch_carrier_assignments_released_by_harvest_pop_event",
        "batch_carrier_assignments", "harvest_population_events",
        ["tenant_id", "farm_id", "released_by_harvest_population_event_id"],
        ["tenant_id", "farm_id", "id"],
    )
    op.create_foreign_key(
        "fk_batch_carrier_assignments_opening_harvest_pop_reversal_event",
        "batch_carrier_assignments", "harvest_population_events",
        ["tenant_id", "farm_id", "opening_harvest_population_reversal_event_id"],
        ["tenant_id", "farm_id", "id"],
    )

    # --- 6. triggers ----------------------------------------------------------
    op.execute(_SHARED_BALANCE_FUNCTION)
    op.execute(_PRODUCTION_DISPOSITION_EVENT_INTEGRITY_WIDENED)
    op.execute(_HARVEST_POPULATION_EVENT_INTEGRITY_FUNCTION)
    op.execute(
        """
        CREATE TRIGGER harvest_population_events_enforce_insert_integrity
        BEFORE INSERT ON harvest_population_events
        FOR EACH ROW EXECUTE FUNCTION enforce_harvest_population_event_insert_integrity();
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER harvest_population_events_no_update
        BEFORE UPDATE ON harvest_population_events
        FOR EACH ROW EXECUTE FUNCTION {_NO_UPDATE_FUNCTION_NAME}();
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER harvest_population_events_no_delete
        BEFORE DELETE ON harvest_population_events
        FOR EACH ROW EXECUTE FUNCTION {_NO_UPDATE_FUNCTION_NAME}();
        """
    )
    op.execute(_SOURCE_LINE_CORRECTION_INTEGRITY_FUNCTION)
    op.execute(
        """
        CREATE TRIGGER harvest_source_line_corrections_enforce_insert_integrity
        BEFORE INSERT ON harvest_source_line_corrections
        FOR EACH ROW EXECUTE FUNCTION enforce_harvest_source_line_correction_insert_integrity();
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER harvest_source_line_corrections_no_update
        BEFORE UPDATE ON harvest_source_line_corrections
        FOR EACH ROW EXECUTE FUNCTION {_NO_UPDATE_FUNCTION_NAME}();
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER harvest_source_line_corrections_no_delete
        BEFORE DELETE ON harvest_source_line_corrections
        FOR EACH ROW EXECUTE FUNCTION {_NO_UPDATE_FUNCTION_NAME}();
        """
    )
    op.execute(_CORRECTION_RECONCILIATION_FUNCTION)
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER harvest_source_line_corrections_enforce_reconciliation
        AFTER INSERT ON harvest_source_line_corrections
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_harvest_correction_reconciliation();
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER produce_lot_ledger_entries_enforce_harvest_correction_reconciliation
        AFTER INSERT ON produce_lot_ledger_entries
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_harvest_correction_reconciliation();
        """
    )
    op.execute(_CLOSURE_ONLY_WITH_HARVEST)
    op.execute(_ORIGIN_INTEGRITY_WITH_HARVEST_HEAD + _ORIGIN_INTEGRITY_TAIL)
    op.execute(_LEDGER_ENTRY_INTEGRITY_WITH_HARVEST_ADJUSTMENT)
    op.execute(_HARVEST_EVENT_INTEGRITY_WITH_LEAFY_BYPASS)
    op.execute(_STAGE_BYPASS_INTEGRITY_FUNCTION)
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER harvest_events_enforce_leafy_stage_bypass_integrity
        AFTER INSERT ON harvest_events
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_leafy_harvest_stage_bypass_integrity();
        """
    )


def downgrade() -> None:
    bind = op.get_bind()

    event_count = bind.execute(sa.text("SELECT count(*) FROM harvest_population_events")).scalar_one()
    if event_count > 0:
        raise RuntimeError(
            f"cannot downgrade past b8f3c6d1e947: {event_count} harvest_population_events row(s) exist -- "
            "downgrading would silently discard real Leafy Harvest biological history"
        )
    correction_count = bind.execute(sa.text("SELECT count(*) FROM harvest_source_line_corrections")).scalar_one()
    if correction_count > 0:
        raise RuntimeError(
            f"cannot downgrade past b8f3c6d1e947: {correction_count} harvest_source_line_corrections row(s) exist "
            "-- downgrading would silently discard real Harvest correction history"
        )
    adjustment_count = bind.execute(
        sa.text("SELECT count(*) FROM produce_lot_ledger_entries WHERE entry_kind = 'harvest_adjustment'")
    ).scalar_one()
    if adjustment_count > 0:
        raise RuntimeError(
            f"cannot downgrade past b8f3c6d1e947: {adjustment_count} harvest_adjustment ledger row(s) exist"
        )
    root_count = bind.execute(
        sa.text(
            "SELECT count(*) FROM batch_carrier_assignments "
            "WHERE opening_harvest_population_reversal_event_id IS NOT NULL"
        )
    ).scalar_one()
    if root_count > 0:
        raise RuntimeError(
            f"cannot downgrade past b8f3c6d1e947: {root_count} restored batch_carrier_assignments row(s) exist"
        )

    op.execute(_LEDGER_ENTRY_INTEGRITY_PRIOR := """
        CREATE OR REPLACE FUNCTION enforce_produce_lot_ledger_entry_insert_integrity_v2() RETURNS trigger AS $$
        DECLARE
            v_lot_tenant_id UUID;
            v_lot_farm_id UUID;
            v_lot_event_id UUID;
            v_lot_weight NUMERIC;
            v_lot_count BIGINT;
            v_lot_effective TIMESTAMPTZ;
            v_lot_recorded TIMESTAMPTZ;
            v_event_actor UUID;
            v_line RECORD;
            v_packing_event RECORD;
            v_prior_weight NUMERIC;
            v_prior_count BIGINT;
            v_remaining_weight NUMERIC;
            v_remaining_count BIGINT;
        BEGIN
            IF NEW.entry_kind = 'harvest_receipt' THEN
                SELECT tenant_id, farm_id, harvest_event_id, total_harvested_weight_kg, total_whole_unit_count,
                       effective_time, recorded_at
                INTO v_lot_tenant_id, v_lot_farm_id, v_lot_event_id, v_lot_weight, v_lot_count, v_lot_effective,
                     v_lot_recorded
                FROM harvested_produce_lots WHERE id = NEW.produce_lot_id;
                IF v_lot_tenant_id IS NULL THEN
                    RAISE EXCEPTION 'produce lot not found for ledger entry';
                END IF;
                IF v_lot_tenant_id <> NEW.tenant_id OR v_lot_farm_id <> NEW.farm_id THEN
                    RAISE EXCEPTION 'ledger entry tenant/farm does not match the produce lot''s own';
                END IF;
                IF v_lot_event_id <> NEW.harvest_event_id THEN
                    RAISE EXCEPTION 'ledger entry harvest event does not match the produce lot''s own event';
                END IF;

                SELECT actor_user_id INTO v_event_actor FROM harvest_events WHERE id = NEW.harvest_event_id;
                IF v_event_actor IS NULL THEN
                    RAISE EXCEPTION 'harvest event not found for ledger entry';
                END IF;

                IF NEW.id <> NEW.produce_lot_id THEN
                    RAISE EXCEPTION 'harvest receipt id must equal its produce lot id';
                END IF;
                IF NEW.weight_delta_kg <> v_lot_weight THEN
                    RAISE EXCEPTION 'harvest receipt weight does not match the produce lot''s total weight';
                END IF;
                IF NEW.whole_unit_count_delta IS DISTINCT FROM v_lot_count THEN
                    RAISE EXCEPTION 'harvest receipt count does not match the produce lot''s total count';
                END IF;
                IF NEW.actor_user_id <> v_event_actor THEN
                    RAISE EXCEPTION 'harvest receipt actor does not match the harvest event''s actor';
                END IF;
                IF NEW.effective_time <> v_lot_effective THEN
                    RAISE EXCEPTION 'harvest receipt effective time does not match the produce lot''s effective time';
                END IF;
                IF NEW.recorded_time <> v_lot_recorded THEN
                    RAISE EXCEPTION 'harvest receipt recorded time does not match the produce lot''s recorded time';
                END IF;
                IF NEW.note IS NOT NULL THEN
                    RAISE EXCEPTION 'harvest receipt note must be null';
                END IF;

            ELSIF NEW.entry_kind = 'packing_consumption' THEN
                SELECT * INTO v_line FROM packing_input_lines WHERE id = NEW.id;
                IF v_line.id IS NULL THEN
                    RAISE EXCEPTION 'packing input line not found for ledger debit';
                END IF;
                IF v_line.packing_event_id <> NEW.packing_event_id THEN
                    RAISE EXCEPTION 'ledger debit packing event does not match its input line''s own';
                END IF;
                IF v_line.harvested_produce_lot_id <> NEW.produce_lot_id THEN
                    RAISE EXCEPTION 'ledger debit produce lot does not match its input line''s own';
                END IF;
                IF v_line.tenant_id <> NEW.tenant_id OR v_line.farm_id <> NEW.farm_id THEN
                    RAISE EXCEPTION 'ledger debit tenant/farm does not match its input line''s own';
                END IF;

                SELECT * INTO v_packing_event FROM packing_events WHERE id = NEW.packing_event_id;
                IF v_packing_event.id IS NULL THEN
                    RAISE EXCEPTION 'packing event not found for ledger debit';
                END IF;

                IF NEW.weight_delta_kg <> -v_line.consumed_weight_kg THEN
                    RAISE EXCEPTION 'ledger debit weight does not match the negative of its input line''s consumed weight';
                END IF;
                IF NEW.whole_unit_count_delta IS DISTINCT FROM
                   (CASE WHEN v_line.consumed_whole_unit_count IS NULL THEN NULL ELSE -v_line.consumed_whole_unit_count END)
                THEN
                    RAISE EXCEPTION 'ledger debit count does not match the negative of its input line''s consumed count';
                END IF;
                IF NEW.effective_time <> v_packing_event.effective_time THEN
                    RAISE EXCEPTION 'ledger debit effective time does not match its packing event''s effective time';
                END IF;
                IF NEW.recorded_time <> v_line.recorded_time THEN
                    RAISE EXCEPTION 'ledger debit recorded time does not match its input line''s recorded time';
                END IF;
                IF NEW.actor_user_id <> v_packing_event.actor_user_id THEN
                    RAISE EXCEPTION 'ledger debit actor does not match its packing event''s actor';
                END IF;
                IF NEW.note IS DISTINCT FROM v_line.note THEN
                    RAISE EXCEPTION 'ledger debit note does not match its input line''s note';
                END IF;

                SELECT total_whole_unit_count INTO v_lot_count
                FROM harvested_produce_lots WHERE id = NEW.produce_lot_id FOR UPDATE;

                SELECT COALESCE(sum(weight_delta_kg), 0), SUM(whole_unit_count_delta)
                INTO v_prior_weight, v_prior_count
                FROM produce_lot_ledger_entries WHERE produce_lot_id = NEW.produce_lot_id;

                v_remaining_weight := v_prior_weight + NEW.weight_delta_kg;
                IF v_remaining_weight < 0 THEN
                    RAISE EXCEPTION 'packing consumption would leave produce lot % with negative available weight', NEW.produce_lot_id;
                END IF;

                IF v_lot_count IS NULL THEN
                    IF NEW.whole_unit_count_delta IS NOT NULL THEN
                        RAISE EXCEPTION 'produce lot % does not track whole-unit count; ledger debit count must be null', NEW.produce_lot_id;
                    END IF;
                ELSE
                    IF NEW.whole_unit_count_delta IS NULL THEN
                        RAISE EXCEPTION 'produce lot % tracks whole-unit count; ledger debit count is required', NEW.produce_lot_id;
                    END IF;
                    v_remaining_count := COALESCE(v_prior_count, 0) + NEW.whole_unit_count_delta;
                    IF v_remaining_count < 0 THEN
                        RAISE EXCEPTION 'packing consumption would leave produce lot % with negative available count', NEW.produce_lot_id;
                    END IF;
                    IF (v_remaining_weight = 0 AND v_remaining_count > 0)
                       OR (v_remaining_weight > 0 AND v_remaining_count = 0) THEN
                        RAISE EXCEPTION 'packing consumption would leave produce lot % with mismatched residual weight/count', NEW.produce_lot_id;
                    END IF;
                END IF;

            ELSE
                RAISE EXCEPTION 'unknown ledger entry kind %', NEW.entry_kind;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """)

    op.execute(
        "DROP TRIGGER IF EXISTS produce_lot_ledger_entries_enforce_harvest_correction_reconciliation "
        "ON produce_lot_ledger_entries"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS harvest_source_line_corrections_enforce_reconciliation "
        "ON harvest_source_line_corrections"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_harvest_correction_reconciliation()")

    op.execute("DROP TRIGGER IF EXISTS harvest_source_line_corrections_no_delete ON harvest_source_line_corrections")
    op.execute("DROP TRIGGER IF EXISTS harvest_source_line_corrections_no_update ON harvest_source_line_corrections")
    op.execute(
        "DROP TRIGGER IF EXISTS harvest_source_line_corrections_enforce_insert_integrity "
        "ON harvest_source_line_corrections"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_harvest_source_line_correction_insert_integrity()")
    op.execute("DROP TRIGGER IF EXISTS harvest_population_events_no_delete ON harvest_population_events")
    op.execute("DROP TRIGGER IF EXISTS harvest_population_events_no_update ON harvest_population_events")
    op.execute(
        "DROP TRIGGER IF EXISTS harvest_population_events_enforce_insert_integrity ON harvest_population_events"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_harvest_population_event_insert_integrity()")

    op.drop_constraint(
        "fk_batch_carrier_assignments_opening_harvest_pop_reversal_event", "batch_carrier_assignments",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_batch_carrier_assignments_released_by_harvest_pop_event", "batch_carrier_assignments", type_="foreignkey"
    )
    op.drop_index("ux_batch_carrier_assignments_opened_by_harvest_pop_once", "batch_carrier_assignments")
    op.drop_index("ux_batch_carrier_assignments_released_by_harvest_pop_once", "batch_carrier_assignments")

    op.drop_constraint(
        "ck_batch_carrier_assignments_restoration_opener_match", "batch_carrier_assignments", type_="check"
    )
    op.create_check_constraint(
        "ck_batch_carrier_assignments_restoration_opener_match", "batch_carrier_assignments",
        "(restored_from_batch_carrier_assignment_id IS NOT NULL) = "
        "(opening_transplant_reversal_event_id IS NOT NULL "
        "OR opening_seedling_disposition_reversal_event_id IS NOT NULL "
        "OR opening_production_disposition_reversal_event_id IS NOT NULL)",
    )
    op.drop_constraint(
        "ck_batch_carrier_assignments_only_harvest_source_releasable", "batch_carrier_assignments", type_="check"
    )
    op.drop_constraint(
        "ck_batch_carrier_assignments_only_production_source_releasable", "batch_carrier_assignments", type_="check"
    )
    op.create_check_constraint(
        "ck_batch_carrier_assignments_only_production_source_releasable", "batch_carrier_assignments",
        "released_by_production_disposition_event_id IS NULL "
        "OR opening_transplant_event_id IS NOT NULL "
        "OR opening_production_disposition_reversal_event_id IS NOT NULL",
    )
    op.drop_constraint(
        "ck_batch_carrier_assignments_at_most_one_releaser", "batch_carrier_assignments", type_="check"
    )
    op.create_check_constraint(
        "ck_batch_carrier_assignments_at_most_one_releaser", "batch_carrier_assignments",
        "(CASE WHEN released_by_transplant_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN released_by_batch_derivation_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN released_by_seedling_disposition_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN released_by_production_disposition_event_id IS NOT NULL THEN 1 ELSE 0 END) <= 1",
    )
    op.drop_constraint(
        "ck_batch_carrier_assignments_release_fields_together", "batch_carrier_assignments", type_="check"
    )
    op.create_check_constraint(
        "ck_batch_carrier_assignments_release_fields_together", "batch_carrier_assignments",
        "(released_effective_time IS NULL) = "
        "(released_by_transplant_event_id IS NULL AND released_by_batch_derivation_event_id IS NULL "
        "AND released_by_seedling_disposition_event_id IS NULL "
        "AND released_by_production_disposition_event_id IS NULL)",
    )
    op.drop_constraint("ck_batch_carrier_assignments_exactly_one_opener", "batch_carrier_assignments", type_="check")
    op.create_check_constraint(
        "ck_batch_carrier_assignments_exactly_one_opener", "batch_carrier_assignments",
        "(CASE WHEN opening_sowing_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN opening_transplant_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN opening_batch_derivation_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN opening_transplant_reversal_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN opening_seedling_disposition_reversal_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN opening_production_disposition_reversal_event_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
    )

    op.drop_constraint(
        "fk_produce_lot_ledger_entries_tenant_farm_correction", "produce_lot_ledger_entries", type_="foreignkey"
    )
    op.drop_index("ux_produce_lot_ledger_entries_correction_harvest_adjustment", "produce_lot_ledger_entries")
    op.drop_constraint(
        "ck_produce_lot_ledger_entries_harvest_adjustment_nonzero", "produce_lot_ledger_entries", type_="check"
    )
    op.drop_constraint(
        "ck_produce_lot_ledger_entries_typed_source_shape", "produce_lot_ledger_entries", type_="check"
    )
    op.create_check_constraint(
        "ck_produce_lot_ledger_entries_typed_source_shape", "produce_lot_ledger_entries",
        "(entry_kind = 'harvest_receipt' AND harvest_event_id IS NOT NULL AND packing_event_id IS NULL) "
        "OR (entry_kind = 'packing_consumption' AND harvest_event_id IS NULL AND packing_event_id IS NOT NULL)",
    )
    op.drop_constraint("ck_produce_lot_ledger_entries_count_positive", "produce_lot_ledger_entries", type_="check")
    op.create_check_constraint(
        "ck_produce_lot_ledger_entries_count_positive", "produce_lot_ledger_entries",
        "(entry_kind = 'harvest_receipt' AND (whole_unit_count_delta IS NULL OR whole_unit_count_delta > 0)) "
        "OR (entry_kind = 'packing_consumption' AND (whole_unit_count_delta IS NULL OR whole_unit_count_delta < 0))",
    )
    op.drop_constraint("ck_produce_lot_ledger_entries_weight_envelope", "produce_lot_ledger_entries", type_="check")
    op.create_check_constraint(
        "ck_produce_lot_ledger_entries_weight_envelope", "produce_lot_ledger_entries",
        "(entry_kind = 'harvest_receipt' AND weight_delta_kg > 0 "
        "AND weight_delta_kg = trunc(weight_delta_kg, 3) AND weight_delta_kg < 100000000000) "
        "OR (entry_kind = 'packing_consumption' AND weight_delta_kg < 0 "
        "AND weight_delta_kg = trunc(weight_delta_kg, 3) AND weight_delta_kg > -100000000000)",
    )
    op.drop_constraint("ck_produce_lot_ledger_entries_kind_allowed", "produce_lot_ledger_entries", type_="check")
    op.create_check_constraint(
        "ck_produce_lot_ledger_entries_kind_allowed", "produce_lot_ledger_entries",
        "entry_kind IN ('harvest_receipt', 'packing_consumption')",
    )
    op.drop_column("produce_lot_ledger_entries", "harvest_source_line_correction_id")

    op.drop_index("ux_harvest_population_events_correction_once", "harvest_population_events")
    op.drop_index("ux_harvest_population_events_original_line_once", "harvest_population_events")
    op.drop_index("ux_harvest_population_events_reverses_once", "harvest_population_events")
    op.drop_table("harvest_population_events")
    op.drop_table("harvest_source_line_corrections")

    op.drop_column("batch_carrier_assignments", "opening_harvest_population_reversal_event_id")
    op.drop_column("batch_carrier_assignments", "released_by_harvest_population_event_id")

    op.execute(
        "DROP TRIGGER IF EXISTS harvest_events_enforce_leafy_stage_bypass_integrity ON harvest_events"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_leafy_harvest_stage_bypass_integrity()")

    op.execute("DROP FUNCTION IF EXISTS enforce_shared_leafy_population_chronological_balance(UUID, TIMESTAMPTZ, INTEGER)")

    # Restore the pre-this-migration production_disposition_events trigger
    # (its own inline balance walk, LEAFY-OPS-001's own version, unchanged)
    # and the pre-this-migration closure/origin-integrity trigger bodies
    # (a5c9e21f7b64's own versions, unchanged).
    op.execute(_PRIOR_PRODUCTION_DISPOSITION_EVENT_INTEGRITY)
    op.execute(_PRIOR_CLOSURE_ONLY_FUNCTION)
    op.execute(_PRIOR_ORIGIN_INTEGRITY_FUNCTION)
    op.execute(_PRIOR_HARVEST_EVENT_INTEGRITY_FUNCTION)


_PRIOR_PRODUCTION_DISPOSITION_EVENT_INTEGRITY = """
    CREATE OR REPLACE FUNCTION enforce_production_disposition_event_insert_integrity() RETURNS trigger AS $$
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

        SELECT assigned_plant_count INTO v_root_opening
        FROM transplant_destination_lines WHERE destination_batch_carrier_assignment_id = v_assignment_root;
        IF v_root_opening IS NULL THEN
            RAISE EXCEPTION 'population root has no TransplantDestinationLine opening quantity';
        END IF;

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

_PRIOR_ORIGIN_INTEGRITY_FUNCTION = """
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
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """
