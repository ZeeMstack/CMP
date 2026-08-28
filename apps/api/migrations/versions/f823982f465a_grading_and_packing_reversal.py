"""grading and packing whole-event reversal

Revision ID: f823982f465a
Revises: d8f4a1c92b57
Create Date: 2026-08-27 12:00:00.000000

POSTHARVEST-OPS-001H: minimum safe pilot correction capability for
Processing/Grading and Packing -- whole-event reversal only, never a
field-by-field correction. Original GradingEvent/GradedProduceLot and
PackingEvent/PackingInputLine/FinishedGoodsLot rows are never rewritten;
correction is always reverse-then-re-record through the normal workflow.

New tables:

- `grading_reversal_events` -- one row per GradingEvent reversal (at most
  one, ever, per GradingEvent).
- `grading_reversal_outputs` -- one row per output GradedProduceLot being
  zeroed by one grading reversal (child of the above, mirrors
  `PackingInputLine`'s own "child row whose id becomes its ledger entry's
  id" shape).
- `packing_reversal_events` -- one row per PackingEvent reversal (at most
  one, ever, per PackingEvent).
- `packing_reversal_inputs` -- one row per original PackingInputLine being
  restored by one packing reversal (child of the above, same shape).

Ledger widening (new typed entry kinds, each following this codebase's
established "deterministic id, exactly one typed source populated" idiom):

- `produce_lot_ledger_entries` gains `grading_reversal` (positive credit,
  `id = grading_reversal_event_id`, restoring exactly the quantity the
  original `grading_consumption` debited).
- `graded_produce_lot_ledger_entries` gains `grading_reversal` (negative
  debit, `id = grading_reversal_outputs.id`, zeroing the lot) and
  `packing_reversal` (positive credit, `id = packing_reversal_inputs.id`,
  restoring exactly the quantity the original `packing_consumption`
  debited).
- `finished_goods_ledger_entries` gains `packing_reversal` (negative
  debit, `id = packing_reversal_event_id`, neutralizing the lot's opening
  `packing_receipt` quantity).

Every ledger insert-integrity trigger function already established for
these three tables is widened IN PLACE via `CREATE OR REPLACE` (same
function name, same trigger attachment, exactly this codebase's own
convention for adding a new entry_kind branch) with a new branch per new
kind, reproducing the identity/actor/effective-time/balance checks the
existing branches already establish for their own kinds.

Grading reversal is blocked at the service layer (not by a DB trigger --
recall-style commercial containment gates in this codebase live in the
service layer only) while any output GradedProduceLot is still consumed
by an ACTIVE (non-reversed) PackingEvent. Packing reversal is blocked at
the service layer while its FinishedGoodsLot has any dispatch activity or
a nonzero net placed quantity in cold storage -- neither dispatch nor
storage placement has a reversal mechanism in this ticket's scope.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f823982f465a"
down_revision: Union[str, None] = "d8f4a1c92b57"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# =====================================================================
# PRE-UPGRADE bodies -- reproduced byte-for-byte from d8f4a1c92b57/
# 63d4d7e184e2 so downgrade can restore them exactly via CREATE OR
# REPLACE. Never edit these strings to "improve" them.
# =====================================================================

_LEDGER_V2_PRE_UPGRADE_BODY = """
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
        v_grading_event RECORD;
        v_expected_weight_delta NUMERIC;
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

        ELSIF NEW.entry_kind = 'grading_consumption' THEN
            SELECT * INTO v_grading_event FROM grading_events WHERE id = NEW.grading_event_id;
            IF v_grading_event.id IS NULL THEN
                RAISE EXCEPTION 'grading event not found for ledger debit';
            END IF;
            IF NEW.id <> v_grading_event.id THEN
                RAISE EXCEPTION 'grading consumption id must equal its grading event''s own id';
            END IF;
            IF v_grading_event.source_harvested_produce_lot_id <> NEW.produce_lot_id THEN
                RAISE EXCEPTION 'ledger debit produce lot does not match its grading event''s own source lot';
            END IF;
            IF v_grading_event.tenant_id <> NEW.tenant_id OR v_grading_event.farm_id <> NEW.farm_id THEN
                RAISE EXCEPTION 'ledger debit tenant/farm does not match its grading event''s own';
            END IF;
            IF NEW.effective_time <> v_grading_event.effective_time THEN
                RAISE EXCEPTION 'ledger debit effective time does not match its grading event''s effective time';
            END IF;
            IF NEW.recorded_time <> v_grading_event.recorded_time THEN
                RAISE EXCEPTION 'ledger debit recorded time does not match its grading event''s recorded time';
            END IF;
            IF NEW.actor_user_id <> v_grading_event.actor_user_id THEN
                RAISE EXCEPTION 'ledger debit actor does not match its grading event''s actor';
            END IF;
            IF NEW.note IS NOT NULL THEN
                RAISE EXCEPTION 'grading consumption note must be null';
            END IF;

            v_expected_weight_delta := -(v_grading_event.input_presented_weight_kg - v_grading_event.remainder_weight_kg);
            IF NEW.weight_delta_kg <> v_expected_weight_delta THEN
                RAISE EXCEPTION 'grading consumption weight_delta_kg (%) does not equal -(presented - remainder) (expected %)',
                    NEW.weight_delta_kg, v_expected_weight_delta;
            END IF;

            SELECT total_whole_unit_count INTO v_lot_count
            FROM harvested_produce_lots WHERE id = NEW.produce_lot_id FOR UPDATE;

            SELECT COALESCE(sum(weight_delta_kg), 0), SUM(whole_unit_count_delta)
            INTO v_prior_weight, v_prior_count
            FROM produce_lot_ledger_entries WHERE produce_lot_id = NEW.produce_lot_id;

            v_remaining_weight := v_prior_weight + NEW.weight_delta_kg;
            IF v_remaining_weight < 0 THEN
                RAISE EXCEPTION 'grading consumption would leave produce lot % with negative available weight', NEW.produce_lot_id;
            END IF;

            IF v_lot_count IS NULL THEN
                IF NEW.whole_unit_count_delta IS NOT NULL THEN
                    RAISE EXCEPTION 'produce lot % does not track whole-unit count; ledger debit count must be null', NEW.produce_lot_id;
                END IF;
                IF v_grading_event.input_presented_whole_unit_count IS NOT NULL THEN
                    RAISE EXCEPTION 'grading event references a non-count-tracking produce lot but carries presented count';
                END IF;
            ELSE
                IF NEW.whole_unit_count_delta IS NULL THEN
                    RAISE EXCEPTION 'produce lot % tracks whole-unit count; ledger debit count is required', NEW.produce_lot_id;
                END IF;
                v_expected_count_delta := -(v_grading_event.input_presented_whole_unit_count - v_grading_event.remainder_whole_unit_count);
                IF NEW.whole_unit_count_delta <> v_expected_count_delta THEN
                    RAISE EXCEPTION 'grading consumption whole_unit_count_delta (%) does not equal -(presented - remainder) count (expected %)',
                        NEW.whole_unit_count_delta, v_expected_count_delta;
                END IF;
                v_remaining_count := COALESCE(v_prior_count, 0) + NEW.whole_unit_count_delta;
                IF v_remaining_count < 0 THEN
                    RAISE EXCEPTION 'grading consumption would leave produce lot % with negative available count', NEW.produce_lot_id;
                END IF;
                IF (v_remaining_weight = 0 AND v_remaining_count > 0)
                   OR (v_remaining_weight > 0 AND v_remaining_count = 0) THEN
                    RAISE EXCEPTION 'grading consumption would leave produce lot % with mismatched residual weight/count', NEW.produce_lot_id;
                END IF;
            END IF;

        ELSE
            RAISE EXCEPTION 'unknown ledger entry kind %', NEW.entry_kind;
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

# The POSTHARVEST-OPS-001H widened body: adds one new ELSIF branch,
# `grading_reversal`, immediately before the final ELSE/unknown-kind
# guard. Every other branch is byte-for-byte identical to
# `_LEDGER_V2_PRE_UPGRADE_BODY` above.
_LEDGER_V2_WIDENED_BODY = _LEDGER_V2_PRE_UPGRADE_BODY.replace(
    "        ELSE\n            RAISE EXCEPTION 'unknown ledger entry kind %', NEW.entry_kind;\n        END IF;",
    """        ELSIF NEW.entry_kind = 'grading_reversal' THEN
            SELECT * INTO v_grading_event FROM grading_reversal_events WHERE id = NEW.grading_reversal_event_id;
            IF v_grading_event.id IS NULL THEN
                RAISE EXCEPTION 'grading reversal event not found for ledger credit';
            END IF;
            IF NEW.id <> v_grading_event.id THEN
                RAISE EXCEPTION 'grading reversal id must equal its grading reversal event''s own id';
            END IF;
            IF v_grading_event.tenant_id <> NEW.tenant_id OR v_grading_event.farm_id <> NEW.farm_id THEN
                RAISE EXCEPTION 'ledger credit tenant/farm does not match its grading reversal event''s own';
            END IF;
            IF NEW.actor_user_id <> v_grading_event.actor_user_id THEN
                RAISE EXCEPTION 'ledger credit actor does not match its grading reversal event''s actor';
            END IF;
            IF NEW.recorded_time <> v_grading_event.recorded_time THEN
                RAISE EXCEPTION 'ledger credit recorded time does not match its grading reversal event''s recorded time';
            END IF;
            IF NEW.note IS DISTINCT FROM v_grading_event.note THEN
                RAISE EXCEPTION 'ledger credit note does not match its grading reversal event''s own note';
            END IF;

            SELECT ge.source_harvested_produce_lot_id, ge.input_presented_weight_kg - ge.remainder_weight_kg,
                   CASE WHEN ge.input_presented_whole_unit_count IS NULL THEN NULL
                        ELSE ge.input_presented_whole_unit_count - ge.remainder_whole_unit_count END
            INTO v_correction_lot_id, v_expected_weight_delta, v_expected_count_delta
            FROM grading_events ge WHERE ge.id = v_grading_event.grading_event_id;
            IF v_correction_lot_id <> NEW.produce_lot_id THEN
                RAISE EXCEPTION 'ledger credit produce lot does not match its grading reversal event''s own target event source lot';
            END IF;
            IF NEW.weight_delta_kg <> v_expected_weight_delta THEN
                RAISE EXCEPTION 'grading reversal weight_delta_kg (%) does not equal (presented - remainder) of the target grading event (expected %)',
                    NEW.weight_delta_kg, v_expected_weight_delta;
            END IF;
            IF NEW.whole_unit_count_delta IS DISTINCT FROM v_expected_count_delta THEN
                RAISE EXCEPTION 'grading reversal whole_unit_count_delta does not equal (presented - remainder) count of the target grading event';
            END IF;

            PERFORM 1 FROM harvested_produce_lots WHERE id = NEW.produce_lot_id FOR UPDATE;

            SELECT COALESCE(sum(weight_delta_kg), 0), SUM(whole_unit_count_delta)
            INTO v_prior_weight, v_prior_count
            FROM produce_lot_ledger_entries WHERE produce_lot_id = NEW.produce_lot_id;

            v_remaining_weight := v_prior_weight + NEW.weight_delta_kg;
            IF v_remaining_weight < 0 THEN
                RAISE EXCEPTION 'grading reversal would leave produce lot % with negative available weight', NEW.produce_lot_id;
            END IF;

        ELSE
            RAISE EXCEPTION 'unknown ledger entry kind %', NEW.entry_kind;
        END IF;""",
)
assert _LEDGER_V2_WIDENED_BODY != _LEDGER_V2_PRE_UPGRADE_BODY, "grading_reversal branch splice must apply"


_GRADED_LEDGER_PRE_UPGRADE_BODY = """
    CREATE OR REPLACE FUNCTION enforce_graded_produce_lot_ledger_entry_insert_integrity() RETURNS trigger AS $$
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
        SELECT tenant_id, farm_id, grading_event_id, original_received_weight_kg,
               original_received_whole_unit_count, effective_time, recorded_at
        INTO v_lot_tenant_id, v_lot_farm_id, v_lot_event_id, v_lot_weight, v_lot_count, v_lot_effective,
             v_lot_recorded
        FROM graded_produce_lots WHERE id = NEW.graded_produce_lot_id;
        IF v_lot_tenant_id IS NULL THEN
            RAISE EXCEPTION 'graded produce lot not found for ledger entry';
        END IF;
        IF v_lot_tenant_id <> NEW.tenant_id OR v_lot_farm_id <> NEW.farm_id THEN
            RAISE EXCEPTION 'ledger entry tenant/farm does not match the graded produce lot''s own';
        END IF;

        IF NEW.entry_kind = 'grading_receipt' THEN
            IF v_lot_event_id <> NEW.grading_event_id THEN
                RAISE EXCEPTION 'ledger entry grading event does not match the graded produce lot''s own event';
            END IF;

            SELECT actor_user_id INTO v_event_actor FROM grading_events WHERE id = NEW.grading_event_id;
            IF v_event_actor IS NULL THEN
                RAISE EXCEPTION 'grading event not found for ledger entry';
            END IF;

            IF NEW.id <> NEW.graded_produce_lot_id THEN
                RAISE EXCEPTION 'grading receipt id must equal its graded produce lot id';
            END IF;
            IF NEW.weight_delta_kg <> v_lot_weight THEN
                RAISE EXCEPTION 'grading receipt weight does not match the graded produce lot''s original weight';
            END IF;
            IF NEW.whole_unit_count_delta IS DISTINCT FROM v_lot_count THEN
                RAISE EXCEPTION 'grading receipt count does not match the graded produce lot''s original count';
            END IF;
            IF NEW.actor_user_id <> v_event_actor THEN
                RAISE EXCEPTION 'grading receipt actor does not match the grading event''s actor';
            END IF;
            IF NEW.effective_time <> v_lot_effective THEN
                RAISE EXCEPTION 'grading receipt effective time does not match the graded produce lot''s effective time';
            END IF;
            IF NEW.recorded_time <> v_lot_recorded THEN
                RAISE EXCEPTION 'grading receipt recorded time does not match the graded produce lot''s recorded time';
            END IF;
            IF NEW.note IS NOT NULL THEN
                RAISE EXCEPTION 'grading receipt note must be null';
            END IF;

        ELSIF NEW.entry_kind = 'packing_consumption' THEN
            SELECT * INTO v_line FROM packing_input_lines WHERE id = NEW.id;
            IF v_line.id IS NULL THEN
                RAISE EXCEPTION 'packing input line not found for ledger debit';
            END IF;
            IF v_line.packing_event_id <> NEW.packing_event_id THEN
                RAISE EXCEPTION 'ledger debit packing event does not match its input line''s own';
            END IF;
            IF v_line.graded_produce_lot_id <> NEW.graded_produce_lot_id THEN
                RAISE EXCEPTION 'ledger debit graded produce lot does not match its input line''s own';
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

            SELECT original_received_whole_unit_count INTO v_lot_count
            FROM graded_produce_lots WHERE id = NEW.graded_produce_lot_id FOR UPDATE;

            SELECT COALESCE(sum(weight_delta_kg), 0), SUM(whole_unit_count_delta)
            INTO v_prior_weight, v_prior_count
            FROM graded_produce_lot_ledger_entries WHERE graded_produce_lot_id = NEW.graded_produce_lot_id;

            v_remaining_weight := v_prior_weight + NEW.weight_delta_kg;
            IF v_remaining_weight < 0 THEN
                RAISE EXCEPTION 'packing consumption would leave graded produce lot % with negative available weight', NEW.graded_produce_lot_id;
            END IF;

            IF v_lot_count IS NULL THEN
                IF NEW.whole_unit_count_delta IS NOT NULL THEN
                    RAISE EXCEPTION 'graded produce lot % does not track whole-unit count; ledger debit count must be null', NEW.graded_produce_lot_id;
                END IF;
            ELSE
                IF NEW.whole_unit_count_delta IS NULL THEN
                    RAISE EXCEPTION 'graded produce lot % tracks whole-unit count; ledger debit count is required', NEW.graded_produce_lot_id;
                END IF;
                v_remaining_count := COALESCE(v_prior_count, 0) + NEW.whole_unit_count_delta;
                IF v_remaining_count < 0 THEN
                    RAISE EXCEPTION 'packing consumption would leave graded produce lot % with negative available count', NEW.graded_produce_lot_id;
                END IF;
                IF (v_remaining_weight = 0 AND v_remaining_count > 0)
                   OR (v_remaining_weight > 0 AND v_remaining_count = 0) THEN
                    RAISE EXCEPTION 'packing consumption would leave graded produce lot % with mismatched residual weight/count', NEW.graded_produce_lot_id;
                END IF;
            END IF;

        ELSE
            RAISE EXCEPTION 'unknown ledger entry kind %', NEW.entry_kind;
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

# The POSTHARVEST-OPS-001H widened body: adds two new ELSIF branches,
# `grading_reversal` and `packing_reversal`, immediately before the final
# ELSE/unknown-kind guard. Every other branch is byte-for-byte identical
# to `_GRADED_LEDGER_PRE_UPGRADE_BODY` above.
_GRADED_LEDGER_WIDENED_BODY = _GRADED_LEDGER_PRE_UPGRADE_BODY.replace(
    "        ELSE\n            RAISE EXCEPTION 'unknown ledger entry kind %', NEW.entry_kind;\n        END IF;",
    """        ELSIF NEW.entry_kind = 'grading_reversal' THEN
            SELECT * INTO v_line FROM grading_reversal_outputs WHERE id = NEW.id;
            IF v_line.id IS NULL THEN
                RAISE EXCEPTION 'grading reversal output not found for ledger debit';
            END IF;
            IF v_line.grading_reversal_event_id <> NEW.grading_reversal_event_id THEN
                RAISE EXCEPTION 'ledger debit grading reversal event does not match its output row''s own';
            END IF;
            IF v_line.graded_produce_lot_id <> NEW.graded_produce_lot_id THEN
                RAISE EXCEPTION 'ledger debit graded produce lot does not match its output row''s own';
            END IF;
            IF v_line.tenant_id <> NEW.tenant_id OR v_line.farm_id <> NEW.farm_id THEN
                RAISE EXCEPTION 'ledger debit tenant/farm does not match its output row''s own';
            END IF;

            SELECT * INTO v_packing_event FROM grading_reversal_events WHERE id = NEW.grading_reversal_event_id;
            IF v_packing_event.id IS NULL THEN
                RAISE EXCEPTION 'grading reversal event not found for ledger debit';
            END IF;

            IF NEW.weight_delta_kg <> -v_line.reversed_weight_kg THEN
                RAISE EXCEPTION 'ledger debit weight does not match the negative of its output row''s reversed weight';
            END IF;
            IF NEW.whole_unit_count_delta IS DISTINCT FROM
               (CASE WHEN v_line.reversed_whole_unit_count IS NULL THEN NULL ELSE -v_line.reversed_whole_unit_count END)
            THEN
                RAISE EXCEPTION 'ledger debit count does not match the negative of its output row''s reversed count';
            END IF;
            IF NEW.actor_user_id <> v_packing_event.actor_user_id THEN
                RAISE EXCEPTION 'ledger debit actor does not match its grading reversal event''s actor';
            END IF;
            IF NEW.note IS DISTINCT FROM v_packing_event.note THEN
                RAISE EXCEPTION 'ledger debit note does not match its grading reversal event''s own note';
            END IF;

            SELECT COALESCE(sum(weight_delta_kg), 0), SUM(whole_unit_count_delta)
            INTO v_prior_weight, v_prior_count
            FROM graded_produce_lot_ledger_entries WHERE graded_produce_lot_id = NEW.graded_produce_lot_id;

            v_remaining_weight := v_prior_weight + NEW.weight_delta_kg;
            IF v_remaining_weight < 0 THEN
                RAISE EXCEPTION 'grading reversal would leave graded produce lot % with negative available weight', NEW.graded_produce_lot_id;
            END IF;

        ELSIF NEW.entry_kind = 'packing_reversal' THEN
            SELECT * INTO v_line FROM packing_reversal_inputs WHERE id = NEW.id;
            IF v_line.id IS NULL THEN
                RAISE EXCEPTION 'packing reversal input not found for ledger credit';
            END IF;
            IF v_line.packing_reversal_event_id <> NEW.packing_reversal_event_id THEN
                RAISE EXCEPTION 'ledger credit packing reversal event does not match its input row''s own';
            END IF;
            IF v_line.graded_produce_lot_id <> NEW.graded_produce_lot_id THEN
                RAISE EXCEPTION 'ledger credit graded produce lot does not match its input row''s own';
            END IF;
            IF v_line.tenant_id <> NEW.tenant_id OR v_line.farm_id <> NEW.farm_id THEN
                RAISE EXCEPTION 'ledger credit tenant/farm does not match its input row''s own';
            END IF;

            SELECT * INTO v_packing_event FROM packing_reversal_events WHERE id = NEW.packing_reversal_event_id;
            IF v_packing_event.id IS NULL THEN
                RAISE EXCEPTION 'packing reversal event not found for ledger credit';
            END IF;

            IF NEW.weight_delta_kg <> v_line.restored_weight_kg THEN
                RAISE EXCEPTION 'ledger credit weight does not match its input row''s restored weight';
            END IF;
            IF NEW.whole_unit_count_delta IS DISTINCT FROM v_line.restored_whole_unit_count THEN
                RAISE EXCEPTION 'ledger credit count does not match its input row''s restored count';
            END IF;
            IF NEW.actor_user_id <> v_packing_event.actor_user_id THEN
                RAISE EXCEPTION 'ledger credit actor does not match its packing reversal event''s actor';
            END IF;
            IF NEW.note IS DISTINCT FROM v_packing_event.note THEN
                RAISE EXCEPTION 'ledger credit note does not match its packing reversal event''s own note';
            END IF;

        ELSE
            RAISE EXCEPTION 'unknown ledger entry kind %', NEW.entry_kind;
        END IF;""",
)
assert _GRADED_LEDGER_WIDENED_BODY != _GRADED_LEDGER_PRE_UPGRADE_BODY, "reversal branches splice must apply"


_FG_LEDGER_V2_PRE_UPGRADE_BODY = """
    CREATE OR REPLACE FUNCTION enforce_finished_goods_ledger_entry_insert_integrity_v2() RETURNS trigger AS $$
    DECLARE
        v_lot_tenant_id UUID;
        v_lot_farm_id UUID;
        v_lot_event_id UUID;
        v_lot_weight NUMERIC;
        v_lot_count BIGINT;
        v_lot_effective TIMESTAMPTZ;
        v_lot_recorded TIMESTAMPTZ;
        v_event_actor UUID;
        v_event_effective TIMESTAMPTZ;
        v_line_tenant_id UUID;
        v_line_farm_id UUID;
        v_line_event_id UUID;
        v_line_lot_id UUID;
        v_line_weight NUMERIC;
        v_line_count BIGINT;
        v_dispatch_tenant_id UUID;
        v_dispatch_farm_id UUID;
        v_dispatch_actor UUID;
        v_dispatch_effective TIMESTAMPTZ;
        v_dispatch_recorded TIMESTAMPTZ;
        v_prior_weight NUMERIC;
        v_prior_count NUMERIC;
        v_prior_max_effective TIMESTAMPTZ;
    BEGIN
        SELECT tenant_id, farm_id, packing_event_id, net_packed_weight_kg, package_count,
               effective_time, recorded_time
        INTO v_lot_tenant_id, v_lot_farm_id, v_lot_event_id, v_lot_weight, v_lot_count, v_lot_effective,
             v_lot_recorded
        FROM finished_goods_lots WHERE id = NEW.finished_goods_lot_id;
        IF v_lot_tenant_id IS NULL THEN
            RAISE EXCEPTION 'finished-goods lot not found for ledger entry';
        END IF;
        IF v_lot_tenant_id <> NEW.tenant_id OR v_lot_farm_id <> NEW.farm_id THEN
            RAISE EXCEPTION 'ledger entry tenant/farm does not match the finished-goods lot''s own';
        END IF;

        IF NEW.entry_kind = 'packing_receipt' THEN
            IF v_lot_event_id <> NEW.packing_event_id THEN
                RAISE EXCEPTION 'ledger entry packing event does not match the finished-goods lot''s own event';
            END IF;
            SELECT actor_user_id, effective_time INTO v_event_actor, v_event_effective
            FROM packing_events WHERE id = NEW.packing_event_id;
            IF v_event_actor IS NULL THEN
                RAISE EXCEPTION 'packing event not found for ledger entry';
            END IF;
            IF NEW.weight_delta_kg <> v_lot_weight THEN
                RAISE EXCEPTION 'packing receipt weight does not match the finished-goods lot''s net packed weight';
            END IF;
            IF NEW.package_count_delta <> v_lot_count THEN
                RAISE EXCEPTION 'packing receipt package count does not match the finished-goods lot''s package count';
            END IF;
            IF NEW.actor_user_id <> v_event_actor THEN
                RAISE EXCEPTION 'packing receipt actor does not match the packing event''s actor';
            END IF;
            IF NEW.effective_time <> v_lot_effective THEN
                RAISE EXCEPTION 'packing receipt effective time does not match the finished-goods lot''s effective time';
            END IF;
            IF NEW.effective_time <> v_event_effective THEN
                RAISE EXCEPTION 'packing receipt effective time does not match the packing event''s effective time';
            END IF;
            IF NEW.recorded_time <> v_lot_recorded THEN
                RAISE EXCEPTION 'packing receipt recorded time does not match the finished-goods lot''s recorded time';
            END IF;

        ELSIF NEW.entry_kind = 'dispatch_issue' THEN
            SELECT tenant_id, farm_id, dispatch_event_id, finished_goods_lot_id, dispatched_weight_kg,
                   dispatched_package_count
            INTO v_line_tenant_id, v_line_farm_id, v_line_event_id, v_line_lot_id, v_line_weight, v_line_count
            FROM dispatch_lines WHERE id = NEW.dispatch_line_id;
            IF v_line_tenant_id IS NULL THEN
                RAISE EXCEPTION 'dispatch line not found for ledger entry';
            END IF;
            IF v_line_tenant_id <> NEW.tenant_id OR v_line_farm_id <> NEW.farm_id THEN
                RAISE EXCEPTION 'ledger entry tenant/farm does not match the dispatch line''s own';
            END IF;
            IF v_line_lot_id <> NEW.finished_goods_lot_id THEN
                RAISE EXCEPTION 'ledger entry finished-goods lot does not match the dispatch line''s own lot';
            END IF;

            SELECT tenant_id, farm_id, actor_user_id, effective_time, recorded_time
            INTO v_dispatch_tenant_id, v_dispatch_farm_id, v_dispatch_actor, v_dispatch_effective,
                 v_dispatch_recorded
            FROM dispatch_events WHERE id = v_line_event_id;
            IF v_dispatch_tenant_id IS NULL THEN
                RAISE EXCEPTION 'dispatch event not found for ledger entry';
            END IF;
            IF v_dispatch_tenant_id <> NEW.tenant_id OR v_dispatch_farm_id <> NEW.farm_id THEN
                RAISE EXCEPTION 'ledger entry tenant/farm does not match the dispatch event''s own';
            END IF;

            IF NEW.weight_delta_kg <> -v_line_weight THEN
                RAISE EXCEPTION 'dispatch issue weight does not match the negative dispatch line weight';
            END IF;
            IF NEW.package_count_delta <> -v_line_count THEN
                RAISE EXCEPTION 'dispatch issue package count does not match the negative dispatch line package count';
            END IF;
            IF NEW.actor_user_id <> v_dispatch_actor THEN
                RAISE EXCEPTION 'dispatch issue actor does not match the dispatch event''s actor';
            END IF;
            IF NEW.effective_time <> v_dispatch_effective THEN
                RAISE EXCEPTION 'dispatch issue effective time does not match the dispatch event''s effective time';
            END IF;
            IF NEW.effective_time < v_lot_effective THEN
                RAISE EXCEPTION 'dispatch issue effective time precedes the finished-goods lot''s own effective time';
            END IF;
            IF NEW.recorded_time <> v_dispatch_recorded THEN
                RAISE EXCEPTION 'dispatch issue recorded time does not match the dispatch event''s recorded time';
            END IF;

            PERFORM 1 FROM finished_goods_lots WHERE id = NEW.finished_goods_lot_id FOR UPDATE;

            SELECT COALESCE(SUM(weight_delta_kg), 0), COALESCE(SUM(package_count_delta), 0), MAX(effective_time)
            INTO v_prior_weight, v_prior_count, v_prior_max_effective
            FROM finished_goods_ledger_entries WHERE finished_goods_lot_id = NEW.finished_goods_lot_id;

            IF v_prior_max_effective IS NOT NULL AND NEW.effective_time < v_prior_max_effective THEN
                RAISE EXCEPTION 'dispatch issue effective time precedes the finished-goods lot''s latest existing ledger entry';
            END IF;
            IF v_prior_weight + NEW.weight_delta_kg < 0 THEN
                RAISE EXCEPTION 'dispatch issue would leave finished-goods lot % with negative available weight', NEW.finished_goods_lot_id;
            END IF;
            IF v_prior_count + NEW.package_count_delta < 0 THEN
                RAISE EXCEPTION 'dispatch issue would leave finished-goods lot % with negative available package count', NEW.finished_goods_lot_id;
            END IF;
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

# The POSTHARVEST-OPS-001H widened body: adds one new ELSIF branch,
# `packing_reversal`, before the closing `END IF;` of the (deliberately
# non-exhaustive -- the original never RAISEs on an unknown kind) IF
# chain. Every other branch is byte-for-byte identical to
# `_FG_LEDGER_V2_PRE_UPGRADE_BODY` above.
_FG_LEDGER_V2_WIDENED_BODY = _FG_LEDGER_V2_PRE_UPGRADE_BODY.replace(
    "        v_prior_max_effective TIMESTAMPTZ;\n    BEGIN",
    "        v_prior_max_effective TIMESTAMPTZ;\n        v_reversal_note VARCHAR;\n    BEGIN",
).replace(
    "            IF v_prior_count + NEW.package_count_delta < 0 THEN\n"
    "                RAISE EXCEPTION 'dispatch issue would leave finished-goods lot % with negative available package count', NEW.finished_goods_lot_id;\n"
    "            END IF;\n"
    "        END IF;",
    """            IF v_prior_count + NEW.package_count_delta < 0 THEN
                RAISE EXCEPTION 'dispatch issue would leave finished-goods lot % with negative available package count', NEW.finished_goods_lot_id;
            END IF;

        ELSIF NEW.entry_kind = 'packing_reversal' THEN
            SELECT actor_user_id, effective_time, recorded_time, note
            INTO v_dispatch_actor, v_dispatch_effective, v_dispatch_recorded, v_reversal_note
            FROM packing_reversal_events WHERE id = NEW.packing_reversal_event_id;
            IF v_dispatch_actor IS NULL THEN
                RAISE EXCEPTION 'packing reversal event not found for ledger debit';
            END IF;
            IF NEW.weight_delta_kg <> -v_lot_weight THEN
                RAISE EXCEPTION 'packing reversal weight does not match the negative of the finished-goods lot''s own net packed weight';
            END IF;
            IF NEW.package_count_delta <> -v_lot_count THEN
                RAISE EXCEPTION 'packing reversal package count does not match the negative of the finished-goods lot''s own package count';
            END IF;
            IF NEW.actor_user_id <> v_dispatch_actor THEN
                RAISE EXCEPTION 'packing reversal actor does not match its packing reversal event''s actor';
            END IF;
            IF NEW.recorded_time <> v_dispatch_recorded THEN
                RAISE EXCEPTION 'packing reversal recorded time does not match its packing reversal event''s recorded time';
            END IF;
            IF NEW.note IS NOT NULL THEN
                RAISE EXCEPTION 'packing reversal note must be null';
            END IF;

            SELECT COALESCE(SUM(weight_delta_kg), 0), COALESCE(SUM(package_count_delta), 0)
            INTO v_prior_weight, v_prior_count
            FROM finished_goods_ledger_entries WHERE finished_goods_lot_id = NEW.finished_goods_lot_id;

            IF v_prior_weight + NEW.weight_delta_kg < 0 THEN
                RAISE EXCEPTION 'packing reversal would leave finished-goods lot % with negative available weight', NEW.finished_goods_lot_id;
            END IF;
            IF v_prior_count + NEW.package_count_delta < 0 THEN
                RAISE EXCEPTION 'packing reversal would leave finished-goods lot % with negative available package count', NEW.finished_goods_lot_id;
            END IF;
        END IF;""",
)
assert _FG_LEDGER_V2_WIDENED_BODY != _FG_LEDGER_V2_PRE_UPGRADE_BODY, "packing_reversal branch splice must apply"


def _drop_check_if_exists(table: str, name: str) -> None:
    """FINAL AFFECTED-AREA VERIFICATION fix: several pre-existing downgrade-
    guard tests (e.g. `test_finished_goods_ledger_downgrade_guard.py`,
    `test_dispatch_downgrade_guard.py`) manually drop one or more of these
    exact CHECK constraints via raw SQL, on top of an already-committed
    scenario, to inject data that could never pass through the normal
    insert path -- proving that a LOWER migration's own downgrade guard
    (e.g. d8f4a1c92b57's "Cannot downgrade past POSTHARVEST-OPS-001E" row-
    count check) still fires reliably no matter how this table's own rows
    are corrupted. Those tests predate this ticket and were written when
    the migration owning these constraint names was head; now that this
    migration sits on top and reuses the same names (widening, then
    narrowing back), a plain `op.drop_constraint` would raise
    `UndefinedObject` when the constraint is already gone -- never reaching
    the lower guard those tests actually exercise. `DROP CONSTRAINT IF
    EXISTS` makes this narrowing step a true no-op in that bypassed state,
    exactly matching this table's real state without asserting anything
    about how it got there."""
    op.execute(f'ALTER TABLE {table} DROP CONSTRAINT IF EXISTS "{name}"')


def _add_check_validating_when_safe(table: str, name: str, expression: str) -> None:
    """FINAL SCHEMA VALIDATION CHECK fix: companion to
    `_drop_check_if_exists`. A CLEAN downgrade must restore the exact
    effective parent (pre-001H) schema -- including `convalidated = true`
    on every restored CHECK, identical to what `op.create_check_constraint`
    always produces -- never a permanently-unvalidated parent constraint
    just to make a deliberately-corrupted test scenario reach a deeper
    guard. This checks, with the identical `WHERE NOT (...)` three-valued
    logic Postgres itself uses to validate a CHECK (a NULL result is never
    a violation), whether ANY row already violates the narrower shape
    BEFORE deciding how to add it:

    - No violating row -- every genuine downgrade, since this migration's
      own reversal-history guard (immediately below) already refuses to
      downgrade at all while any Grading/Packing reversal exists, and no
      other code path can ever create a `grading_reversal`/
      `packing_reversal`-kind row; narrowing a kind list or widened
      envelope never invalidates a row that only ever used the OTHER,
      untouched branches -- adds and validates the constraint immediately,
      exactly like `op.create_check_constraint`. `convalidated = true`
      afterward.
    - A violating row exists -- reachable only by a downgrade-guard test's
      own deliberate raw-SQL bypass of an UNRELATED older constraint (e.g.
      `test_finished_goods_ledger_downgrade_guard.py`,
      `test_dispatch_downgrade_guard.py`), never by normal operation --
      adds it `NOT VALID`, skipping validation so this migration's own
      narrowing step is not itself the reason the downgrade fails, letting
      execution reach whichever OLDER migration's own guard exists for
      that exact corrupted state (inside the same transaction Alembic
      wraps the whole multi-step downgrade in, which then rolls the entire
      thing back once that guard fires -- this branch's `NOT VALID` output
      is never left observable after a downgrade that actually succeeds).
    Never used in `upgrade()` -- widening onto live, already-conforming
    data always validates immediately there, same as every other migration
    in this codebase."""
    bind = op.get_bind()
    has_violation = bind.execute(
        sa.text(f"SELECT EXISTS (SELECT 1 FROM {table} WHERE NOT ({expression}))")
    ).scalar()
    if has_violation:
        op.execute(f'ALTER TABLE {table} ADD CONSTRAINT "{name}" CHECK ({expression}) NOT VALID')
    else:
        op.execute(f'ALTER TABLE {table} ADD CONSTRAINT "{name}" CHECK ({expression})')


def _create_append_only_triggers(table: str) -> None:
    op.execute(
        f"""
        CREATE TRIGGER {table}_no_update
        BEFORE UPDATE ON {table}
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {table}_no_delete
        BEFORE DELETE ON {table}
        FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();
        """
    )


def upgrade() -> None:
    # --- 1. grading_reversal_events --------------------------------------------------
    op.create_table(
        "grading_reversal_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("grading_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("grading_events.id"), nullable=False),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.Column("reason_code", sa.String(), nullable=False),
        # PRE-COMMIT AUDIT: nullable -- reason_code is mandatory, note is
        # optional (mirrors SeedlingDispositionEvent's own REVERSAL shape).
        sa.Column("note", sa.String(), nullable=True),
        sa.CheckConstraint("btrim(reason_code) <> ''", name="ck_grading_reversal_events_reason_required"),
        sa.CheckConstraint("note IS NULL OR btrim(note) <> ''", name="ck_grading_reversal_events_note_not_blank"),
        sa.UniqueConstraint("grading_event_id", name="ux_grading_reversal_events_grading_event_id"),
        sa.UniqueConstraint("tenant_id", "farm_id", "id", name="uq_grading_reversal_events_tenant_farm_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "grading_event_id"],
            ["grading_events.tenant_id", "grading_events.farm_id", "grading_events.id"],
            name="fk_grading_reversal_events_tenant_farm_event",
        ),
    )
    op.create_index(
        "ux_grading_reversal_events_tenant_client_command_id", "grading_reversal_events",
        ["tenant_id", "client_command_id"], unique=True,
    )
    _create_append_only_triggers("grading_reversal_events")

    # --- 2. grading_reversal_outputs ---------------------------------------------------
    op.create_table(
        "grading_reversal_outputs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column(
            "grading_reversal_event_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("grading_reversal_events.id"), nullable=False,
        ),
        sa.Column(
            "graded_produce_lot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("graded_produce_lots.id"),
            nullable=False,
        ),
        sa.Column("reversed_weight_kg", sa.Numeric(), nullable=False),
        sa.Column("reversed_whole_unit_count", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            "reversed_weight_kg > 0 AND reversed_weight_kg = trunc(reversed_weight_kg, 3) "
            "AND reversed_weight_kg < 100000000000",
            name="ck_grading_reversal_outputs_weight_positive",
        ),
        sa.CheckConstraint(
            "reversed_whole_unit_count IS NULL OR reversed_whole_unit_count > 0",
            name="ck_grading_reversal_outputs_count_positive",
        ),
        sa.UniqueConstraint("graded_produce_lot_id", name="ux_grading_reversal_outputs_graded_produce_lot"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "grading_reversal_event_id"],
            ["grading_reversal_events.tenant_id", "grading_reversal_events.farm_id", "grading_reversal_events.id"],
            name="fk_grading_reversal_outputs_tenant_farm_event",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "graded_produce_lot_id"],
            ["graded_produce_lots.tenant_id", "graded_produce_lots.farm_id", "graded_produce_lots.id"],
            name="fk_grading_reversal_outputs_tenant_farm_gpl",
        ),
    )
    _create_append_only_triggers("grading_reversal_outputs")

    # --- 3. packing_reversal_events -----------------------------------------------------
    op.create_table(
        "packing_reversal_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("packing_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("packing_events.id"), nullable=False),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.Column("reason_code", sa.String(), nullable=False),
        # PRE-COMMIT AUDIT: nullable -- reason_code is mandatory, note is
        # optional (mirrors SeedlingDispositionEvent's own REVERSAL shape).
        sa.Column("note", sa.String(), nullable=True),
        sa.CheckConstraint("btrim(reason_code) <> ''", name="ck_packing_reversal_events_reason_required"),
        sa.CheckConstraint("note IS NULL OR btrim(note) <> ''", name="ck_packing_reversal_events_note_not_blank"),
        sa.UniqueConstraint("packing_event_id", name="ux_packing_reversal_events_packing_event_id"),
        sa.UniqueConstraint("tenant_id", "farm_id", "id", name="uq_packing_reversal_events_tenant_farm_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "packing_event_id"],
            ["packing_events.tenant_id", "packing_events.farm_id", "packing_events.id"],
            name="fk_packing_reversal_events_tenant_farm_event",
        ),
    )
    op.create_index(
        "ux_packing_reversal_events_tenant_client_command_id", "packing_reversal_events",
        ["tenant_id", "client_command_id"], unique=True,
    )
    _create_append_only_triggers("packing_reversal_events")

    # --- 3b. packing_input_lines: add missing (tenant_id, farm_id, id) unique -------
    # Needed so packing_reversal_inputs (below) can use a real composite FK
    # to this table, matching every other typed source in this codebase --
    # mirrors CMP-018's own uq_locations_tenant_farm_id precedent exactly
    # (locations had no such constraint before that ticket either).
    op.create_unique_constraint(
        "uq_packing_input_lines_tenant_farm_id", "packing_input_lines", ["tenant_id", "farm_id", "id"]
    )

    # --- 4. packing_reversal_inputs -------------------------------------------------
    op.create_table(
        "packing_reversal_inputs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column(
            "packing_reversal_event_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("packing_reversal_events.id"), nullable=False,
        ),
        sa.Column(
            "packing_input_line_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("packing_input_lines.id"),
            nullable=False,
        ),
        sa.Column(
            "graded_produce_lot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("graded_produce_lots.id"),
            nullable=False,
        ),
        sa.Column("restored_weight_kg", sa.Numeric(), nullable=False),
        sa.Column("restored_whole_unit_count", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            "restored_weight_kg > 0 AND restored_weight_kg = trunc(restored_weight_kg, 3) "
            "AND restored_weight_kg < 100000000000",
            name="ck_packing_reversal_inputs_weight_positive",
        ),
        sa.CheckConstraint(
            "restored_whole_unit_count IS NULL OR restored_whole_unit_count > 0",
            name="ck_packing_reversal_inputs_count_positive",
        ),
        sa.UniqueConstraint("packing_input_line_id", name="ux_packing_reversal_inputs_packing_input_line"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "packing_reversal_event_id"],
            ["packing_reversal_events.tenant_id", "packing_reversal_events.farm_id", "packing_reversal_events.id"],
            name="fk_packing_reversal_inputs_tenant_farm_event",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "packing_input_line_id"],
            ["packing_input_lines.tenant_id", "packing_input_lines.farm_id", "packing_input_lines.id"],
            name="fk_packing_reversal_inputs_tenant_farm_line",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "graded_produce_lot_id"],
            ["graded_produce_lots.tenant_id", "graded_produce_lots.farm_id", "graded_produce_lots.id"],
            name="fk_packing_reversal_inputs_tenant_farm_gpl",
        ),
    )
    _create_append_only_triggers("packing_reversal_inputs")

    # --- 5. widen produce_lot_ledger_entries: add grading_reversal -------------------
    op.add_column(
        "produce_lot_ledger_entries",
        sa.Column("grading_reversal_event_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_produce_lot_ledger_entries_tenant_farm_grading_reversal", "produce_lot_ledger_entries",
        "grading_reversal_events", ["tenant_id", "farm_id", "grading_reversal_event_id"],
        ["tenant_id", "farm_id", "id"],
    )
    op.create_index(
        "ux_produce_lot_ledger_entries_event_grading_reversal", "produce_lot_ledger_entries",
        ["grading_reversal_event_id"], unique=True, postgresql_where=sa.text("entry_kind = 'grading_reversal'"),
    )

    op.drop_constraint("ck_produce_lot_ledger_entries_kind_allowed", "produce_lot_ledger_entries", type_="check")
    op.create_check_constraint(
        "ck_produce_lot_ledger_entries_kind_allowed",
        "produce_lot_ledger_entries",
        "entry_kind IN ('harvest_receipt', 'harvest_adjustment', 'grading_consumption', 'grading_reversal')",
    )
    op.drop_constraint("ck_produce_lot_ledger_entries_weight_envelope", "produce_lot_ledger_entries", type_="check")
    op.create_check_constraint(
        "ck_produce_lot_ledger_entries_weight_envelope",
        "produce_lot_ledger_entries",
        "(entry_kind = 'harvest_receipt' AND weight_delta_kg > 0 "
        "AND weight_delta_kg = trunc(weight_delta_kg, 3) AND weight_delta_kg < 100000000000) "
        "OR (entry_kind = 'harvest_adjustment' "
        "AND weight_delta_kg = trunc(weight_delta_kg, 3) "
        "AND weight_delta_kg > -100000000000 AND weight_delta_kg < 100000000000) "
        "OR (entry_kind = 'grading_consumption' AND weight_delta_kg < 0 "
        "AND weight_delta_kg = trunc(weight_delta_kg, 3) AND weight_delta_kg > -100000000000) "
        "OR (entry_kind = 'grading_reversal' AND weight_delta_kg > 0 "
        "AND weight_delta_kg = trunc(weight_delta_kg, 3) AND weight_delta_kg < 100000000000)",
    )
    op.drop_constraint("ck_produce_lot_ledger_entries_count_positive", "produce_lot_ledger_entries", type_="check")
    op.create_check_constraint(
        "ck_produce_lot_ledger_entries_count_positive",
        "produce_lot_ledger_entries",
        "(entry_kind = 'harvest_receipt' AND (whole_unit_count_delta IS NULL OR whole_unit_count_delta > 0)) "
        "OR (entry_kind = 'harvest_adjustment' AND (whole_unit_count_delta IS NULL OR whole_unit_count_delta <> 0)) "
        "OR (entry_kind = 'grading_consumption' AND (whole_unit_count_delta IS NULL OR whole_unit_count_delta < 0)) "
        "OR (entry_kind = 'grading_reversal' AND (whole_unit_count_delta IS NULL OR whole_unit_count_delta > 0))",
    )
    op.drop_constraint(
        "ck_produce_lot_ledger_entries_typed_source_shape", "produce_lot_ledger_entries", type_="check"
    )
    op.create_check_constraint(
        "ck_produce_lot_ledger_entries_typed_source_shape",
        "produce_lot_ledger_entries",
        "(entry_kind = 'harvest_receipt' AND harvest_event_id IS NOT NULL "
        "AND harvest_source_line_correction_id IS NULL AND grading_event_id IS NULL "
        "AND grading_reversal_event_id IS NULL) "
        "OR (entry_kind = 'harvest_adjustment' AND harvest_event_id IS NULL "
        "AND harvest_source_line_correction_id IS NOT NULL AND grading_event_id IS NULL "
        "AND grading_reversal_event_id IS NULL) "
        "OR (entry_kind = 'grading_consumption' AND harvest_event_id IS NULL "
        "AND harvest_source_line_correction_id IS NULL AND grading_event_id IS NOT NULL "
        "AND grading_reversal_event_id IS NULL) "
        "OR (entry_kind = 'grading_reversal' AND harvest_event_id IS NULL "
        "AND harvest_source_line_correction_id IS NULL AND grading_event_id IS NULL "
        "AND grading_reversal_event_id IS NOT NULL)",
    )
    op.execute(_LEDGER_V2_WIDENED_BODY)

    # --- 6. widen graded_produce_lot_ledger_entries: add grading_reversal/packing_reversal --
    op.add_column(
        "graded_produce_lot_ledger_entries",
        sa.Column("grading_reversal_event_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "graded_produce_lot_ledger_entries",
        sa.Column("packing_reversal_event_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_gpl_ledger_entries_tenant_farm_grading_reversal", "graded_produce_lot_ledger_entries",
        "grading_reversal_events", ["tenant_id", "farm_id", "grading_reversal_event_id"],
        ["tenant_id", "farm_id", "id"],
    )
    op.create_foreign_key(
        "fk_gpl_ledger_entries_tenant_farm_packing_reversal", "graded_produce_lot_ledger_entries",
        "packing_reversal_events", ["tenant_id", "farm_id", "packing_reversal_event_id"],
        ["tenant_id", "farm_id", "id"],
    )
    op.create_index(
        "ux_graded_produce_lot_ledger_entries_grading_reversal", "graded_produce_lot_ledger_entries",
        ["graded_produce_lot_id"], unique=True, postgresql_where=sa.text("entry_kind = 'grading_reversal'"),
    )
    op.create_index(
        "ux_graded_produce_lot_ledger_entries_packing_reversal", "graded_produce_lot_ledger_entries",
        ["packing_reversal_event_id", "graded_produce_lot_id"], unique=True,
        postgresql_where=sa.text("entry_kind = 'packing_reversal'"),
    )

    op.drop_constraint(
        "ck_graded_produce_lot_ledger_entries_kind_allowed", "graded_produce_lot_ledger_entries", type_="check"
    )
    op.create_check_constraint(
        "ck_graded_produce_lot_ledger_entries_kind_allowed",
        "graded_produce_lot_ledger_entries",
        "entry_kind IN ('grading_receipt', 'packing_consumption', 'grading_reversal', 'packing_reversal')",
    )
    op.drop_constraint(
        "ck_graded_produce_lot_ledger_entries_weight_envelope", "graded_produce_lot_ledger_entries", type_="check"
    )
    op.create_check_constraint(
        "ck_graded_produce_lot_ledger_entries_weight_envelope",
        "graded_produce_lot_ledger_entries",
        "weight_delta_kg = trunc(weight_delta_kg, 3) AND ("
        "  (entry_kind = 'grading_receipt' AND weight_delta_kg > 0 AND weight_delta_kg < 100000000000)"
        "  OR (entry_kind = 'packing_consumption' AND weight_delta_kg < 0 AND weight_delta_kg > -100000000000)"
        "  OR (entry_kind = 'grading_reversal' AND weight_delta_kg < 0 AND weight_delta_kg > -100000000000)"
        "  OR (entry_kind = 'packing_reversal' AND weight_delta_kg > 0 AND weight_delta_kg < 100000000000)"
        ")",
    )
    op.drop_constraint(
        "ck_graded_produce_lot_ledger_entries_count_positive", "graded_produce_lot_ledger_entries", type_="check"
    )
    op.create_check_constraint(
        "ck_graded_produce_lot_ledger_entries_count_positive",
        "graded_produce_lot_ledger_entries",
        "(entry_kind = 'grading_receipt' AND (whole_unit_count_delta IS NULL OR whole_unit_count_delta > 0)) "
        "OR (entry_kind = 'packing_consumption' AND (whole_unit_count_delta IS NULL OR whole_unit_count_delta < 0)) "
        "OR (entry_kind = 'grading_reversal' AND (whole_unit_count_delta IS NULL OR whole_unit_count_delta < 0)) "
        "OR (entry_kind = 'packing_reversal' AND (whole_unit_count_delta IS NULL OR whole_unit_count_delta > 0))",
    )
    op.drop_constraint(
        "ck_graded_produce_lot_ledger_entries_typed_source_shape", "graded_produce_lot_ledger_entries", type_="check"
    )
    op.create_check_constraint(
        "ck_graded_produce_lot_ledger_entries_typed_source_shape",
        "graded_produce_lot_ledger_entries",
        "(entry_kind = 'grading_receipt' AND grading_event_id IS NOT NULL AND packing_event_id IS NULL "
        "  AND grading_reversal_event_id IS NULL AND packing_reversal_event_id IS NULL) "
        "OR (entry_kind = 'packing_consumption' AND grading_event_id IS NULL AND packing_event_id IS NOT NULL "
        "  AND grading_reversal_event_id IS NULL AND packing_reversal_event_id IS NULL) "
        "OR (entry_kind = 'grading_reversal' AND grading_event_id IS NULL AND packing_event_id IS NULL "
        "  AND grading_reversal_event_id IS NOT NULL AND packing_reversal_event_id IS NULL) "
        "OR (entry_kind = 'packing_reversal' AND grading_event_id IS NULL AND packing_event_id IS NULL "
        "  AND grading_reversal_event_id IS NULL AND packing_reversal_event_id IS NOT NULL)",
    )
    op.execute(_GRADED_LEDGER_WIDENED_BODY)

    # --- 7. widen finished_goods_ledger_entries: add packing_reversal ----------------
    op.add_column(
        "finished_goods_ledger_entries",
        sa.Column("packing_reversal_event_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_finished_goods_ledger_entries_tenant_farm_packing_reversal", "finished_goods_ledger_entries",
        "packing_reversal_events", ["tenant_id", "farm_id", "packing_reversal_event_id"],
        ["tenant_id", "farm_id", "id"],
    )
    op.create_index(
        "ux_finished_goods_ledger_entries_event_packing_reversal", "finished_goods_ledger_entries",
        ["packing_reversal_event_id"], unique=True, postgresql_where=sa.text("entry_kind = 'packing_reversal'"),
    )

    op.drop_constraint("ck_finished_goods_ledger_entries_kind_allowed", "finished_goods_ledger_entries", type_="check")
    op.create_check_constraint(
        "ck_finished_goods_ledger_entries_kind_allowed",
        "finished_goods_ledger_entries",
        "entry_kind IN ('packing_receipt', 'dispatch_issue', 'packing_reversal')",
    )
    op.drop_constraint(
        "ck_finished_goods_ledger_entries_deterministic_id", "finished_goods_ledger_entries", type_="check"
    )
    op.create_check_constraint(
        "ck_finished_goods_ledger_entries_deterministic_id",
        "finished_goods_ledger_entries",
        "(entry_kind = 'packing_receipt' AND id = finished_goods_lot_id) "
        "OR (entry_kind = 'dispatch_issue' AND id = dispatch_line_id) "
        "OR (entry_kind = 'packing_reversal' AND id = packing_reversal_event_id)",
    )
    op.drop_constraint(
        "ck_finished_goods_ledger_entries_typed_source_shape", "finished_goods_ledger_entries", type_="check"
    )
    op.create_check_constraint(
        "ck_finished_goods_ledger_entries_typed_source_shape",
        "finished_goods_ledger_entries",
        "(entry_kind = 'packing_receipt' AND packing_event_id IS NOT NULL AND dispatch_line_id IS NULL "
        "  AND packing_reversal_event_id IS NULL) "
        "OR (entry_kind = 'dispatch_issue' AND packing_event_id IS NULL AND dispatch_line_id IS NOT NULL "
        "  AND packing_reversal_event_id IS NULL) "
        "OR (entry_kind = 'packing_reversal' AND packing_event_id IS NULL AND dispatch_line_id IS NULL "
        "  AND packing_reversal_event_id IS NOT NULL)",
    )
    op.drop_constraint(
        "ck_finished_goods_ledger_entries_weight_envelope", "finished_goods_ledger_entries", type_="check"
    )
    op.create_check_constraint(
        "ck_finished_goods_ledger_entries_weight_envelope",
        "finished_goods_ledger_entries",
        "weight_delta_kg = trunc(weight_delta_kg, 3) AND ("
        "  (entry_kind = 'packing_receipt' AND weight_delta_kg > 0 AND weight_delta_kg < 100000000000)"
        "  OR (entry_kind = 'dispatch_issue' AND weight_delta_kg < 0 AND weight_delta_kg > -100000000000)"
        "  OR (entry_kind = 'packing_reversal' AND weight_delta_kg < 0 AND weight_delta_kg > -100000000000)"
        ")",
    )
    op.drop_constraint("ck_finished_goods_ledger_entries_count_signed", "finished_goods_ledger_entries", type_="check")
    op.create_check_constraint(
        "ck_finished_goods_ledger_entries_count_signed",
        "finished_goods_ledger_entries",
        "(entry_kind = 'packing_receipt' AND package_count_delta > 0 "
        "  AND package_count_delta <= 9223372036854775807)"
        "OR (entry_kind = 'dispatch_issue' AND package_count_delta < 0 "
        "  AND package_count_delta >= -9223372036854775807)"
        "OR (entry_kind = 'packing_reversal' AND package_count_delta < 0 "
        "  AND package_count_delta >= -9223372036854775807)",
    )
    op.execute(_FG_LEDGER_V2_WIDENED_BODY)


def downgrade() -> None:
    # --- 0. downgrade guard: Grading/Packing reversal history is independent data ---
    # Mirrors d8f4a1c92b57's own "Cannot downgrade past POSTHARVEST-OPS-001E"
    # idiom exactly. Runs FIRST, before any schema DDL below, so a real
    # reversal fact is never silently destroyed by dropping these tables --
    # the whole point of 001H is that reversal IS the audit trail (rule 7:
    # immutable history), never reconstructible from any other table.
    bind = op.get_bind()
    unsafe = bind.execute(
        sa.text(
            "SELECT "
            "(SELECT count(*) FROM grading_reversal_events) AS grading_reversal_count, "
            "(SELECT count(*) FROM packing_reversal_events) AS packing_reversal_count"
        )
    ).mappings().first()
    if any(unsafe[k] > 0 for k in unsafe.keys()):
        raise RuntimeError(
            "Cannot downgrade past POSTHARVEST-OPS-001H: Grading/Packing reversal history exists. "
            "This is new commercial/audit correction history, never reconstructible from any other "
            "table. Do not downgrade."
        )

    # --- 7. narrow finished_goods_ledger_entries back -------------------------------
    op.execute(_FG_LEDGER_V2_PRE_UPGRADE_BODY)

    _drop_check_if_exists("finished_goods_ledger_entries", "ck_finished_goods_ledger_entries_count_signed")
    _add_check_validating_when_safe(
        "finished_goods_ledger_entries",
        "ck_finished_goods_ledger_entries_count_signed",
        "(entry_kind = 'packing_receipt' AND package_count_delta > 0 "
        "  AND package_count_delta <= 9223372036854775807)"
        "OR (entry_kind = 'dispatch_issue' AND package_count_delta < 0 "
        "  AND package_count_delta >= -9223372036854775807)",
    )
    _drop_check_if_exists("finished_goods_ledger_entries", "ck_finished_goods_ledger_entries_weight_envelope")
    _add_check_validating_when_safe(
        "finished_goods_ledger_entries",
        "ck_finished_goods_ledger_entries_weight_envelope",
        "weight_delta_kg = trunc(weight_delta_kg, 3) AND ("
        "  (entry_kind = 'packing_receipt' AND weight_delta_kg > 0 AND weight_delta_kg < 100000000000)"
        "  OR (entry_kind = 'dispatch_issue' AND weight_delta_kg < 0 AND weight_delta_kg > -100000000000)"
        ")",
    )
    _drop_check_if_exists("finished_goods_ledger_entries", "ck_finished_goods_ledger_entries_typed_source_shape")
    _add_check_validating_when_safe(
        "finished_goods_ledger_entries",
        "ck_finished_goods_ledger_entries_typed_source_shape",
        "(entry_kind = 'packing_receipt' AND packing_event_id IS NOT NULL AND dispatch_line_id IS NULL) "
        "OR (entry_kind = 'dispatch_issue' AND packing_event_id IS NULL AND dispatch_line_id IS NOT NULL)",
    )
    _drop_check_if_exists("finished_goods_ledger_entries", "ck_finished_goods_ledger_entries_deterministic_id")
    _add_check_validating_when_safe(
        "finished_goods_ledger_entries",
        "ck_finished_goods_ledger_entries_deterministic_id",
        "(entry_kind = 'packing_receipt' AND id = finished_goods_lot_id) "
        "OR (entry_kind = 'dispatch_issue' AND id = dispatch_line_id)",
    )
    _drop_check_if_exists("finished_goods_ledger_entries", "ck_finished_goods_ledger_entries_kind_allowed")
    _add_check_validating_when_safe(
        "finished_goods_ledger_entries",
        "ck_finished_goods_ledger_entries_kind_allowed",
        "entry_kind IN ('packing_receipt', 'dispatch_issue')",
    )
    op.drop_index("ux_finished_goods_ledger_entries_event_packing_reversal", table_name="finished_goods_ledger_entries")
    op.drop_constraint(
        "fk_finished_goods_ledger_entries_tenant_farm_packing_reversal", "finished_goods_ledger_entries",
        type_="foreignkey",
    )
    op.drop_column("finished_goods_ledger_entries", "packing_reversal_event_id")

    # --- 6. narrow graded_produce_lot_ledger_entries back ----------------------------
    op.execute(_GRADED_LEDGER_PRE_UPGRADE_BODY)

    _drop_check_if_exists(
        "graded_produce_lot_ledger_entries", "ck_graded_produce_lot_ledger_entries_typed_source_shape"
    )
    _add_check_validating_when_safe(
        "graded_produce_lot_ledger_entries",
        "ck_graded_produce_lot_ledger_entries_typed_source_shape",
        "(entry_kind = 'grading_receipt' AND grading_event_id IS NOT NULL AND packing_event_id IS NULL) "
        "OR (entry_kind = 'packing_consumption' AND grading_event_id IS NULL AND packing_event_id IS NOT NULL)",
    )
    _drop_check_if_exists("graded_produce_lot_ledger_entries", "ck_graded_produce_lot_ledger_entries_count_positive")
    _add_check_validating_when_safe(
        "graded_produce_lot_ledger_entries",
        "ck_graded_produce_lot_ledger_entries_count_positive",
        "(entry_kind = 'grading_receipt' AND (whole_unit_count_delta IS NULL OR whole_unit_count_delta > 0)) "
        "OR (entry_kind = 'packing_consumption' AND (whole_unit_count_delta IS NULL OR whole_unit_count_delta < 0))",
    )
    _drop_check_if_exists("graded_produce_lot_ledger_entries", "ck_graded_produce_lot_ledger_entries_weight_envelope")
    _add_check_validating_when_safe(
        "graded_produce_lot_ledger_entries",
        "ck_graded_produce_lot_ledger_entries_weight_envelope",
        "weight_delta_kg = trunc(weight_delta_kg, 3) AND ("
        "  (entry_kind = 'grading_receipt' AND weight_delta_kg > 0 AND weight_delta_kg < 100000000000)"
        "  OR (entry_kind = 'packing_consumption' AND weight_delta_kg < 0 AND weight_delta_kg > -100000000000)"
        ")",
    )
    _drop_check_if_exists("graded_produce_lot_ledger_entries", "ck_graded_produce_lot_ledger_entries_kind_allowed")
    _add_check_validating_when_safe(
        "graded_produce_lot_ledger_entries",
        "ck_graded_produce_lot_ledger_entries_kind_allowed",
        "entry_kind IN ('grading_receipt', 'packing_consumption')",
    )
    op.drop_index(
        "ux_graded_produce_lot_ledger_entries_packing_reversal", table_name="graded_produce_lot_ledger_entries"
    )
    op.drop_index(
        "ux_graded_produce_lot_ledger_entries_grading_reversal", table_name="graded_produce_lot_ledger_entries"
    )
    op.drop_constraint(
        "fk_gpl_ledger_entries_tenant_farm_packing_reversal", "graded_produce_lot_ledger_entries",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_gpl_ledger_entries_tenant_farm_grading_reversal", "graded_produce_lot_ledger_entries",
        type_="foreignkey",
    )
    op.drop_column("graded_produce_lot_ledger_entries", "packing_reversal_event_id")
    op.drop_column("graded_produce_lot_ledger_entries", "grading_reversal_event_id")

    # --- 5. narrow produce_lot_ledger_entries back -----------------------------------
    op.execute(_LEDGER_V2_PRE_UPGRADE_BODY)

    _drop_check_if_exists("produce_lot_ledger_entries", "ck_produce_lot_ledger_entries_typed_source_shape")
    _add_check_validating_when_safe(
        "produce_lot_ledger_entries",
        "ck_produce_lot_ledger_entries_typed_source_shape",
        "(entry_kind = 'harvest_receipt' AND harvest_event_id IS NOT NULL "
        "AND harvest_source_line_correction_id IS NULL AND grading_event_id IS NULL) "
        "OR (entry_kind = 'harvest_adjustment' AND harvest_event_id IS NULL "
        "AND harvest_source_line_correction_id IS NOT NULL AND grading_event_id IS NULL) "
        "OR (entry_kind = 'grading_consumption' AND harvest_event_id IS NULL "
        "AND harvest_source_line_correction_id IS NULL AND grading_event_id IS NOT NULL)",
    )
    _drop_check_if_exists("produce_lot_ledger_entries", "ck_produce_lot_ledger_entries_count_positive")
    _add_check_validating_when_safe(
        "produce_lot_ledger_entries",
        "ck_produce_lot_ledger_entries_count_positive",
        "(entry_kind = 'harvest_receipt' AND (whole_unit_count_delta IS NULL OR whole_unit_count_delta > 0)) "
        "OR (entry_kind = 'harvest_adjustment' AND (whole_unit_count_delta IS NULL OR whole_unit_count_delta <> 0)) "
        "OR (entry_kind = 'grading_consumption' AND (whole_unit_count_delta IS NULL OR whole_unit_count_delta < 0))",
    )
    _drop_check_if_exists("produce_lot_ledger_entries", "ck_produce_lot_ledger_entries_weight_envelope")
    _add_check_validating_when_safe(
        "produce_lot_ledger_entries",
        "ck_produce_lot_ledger_entries_weight_envelope",
        "(entry_kind = 'harvest_receipt' AND weight_delta_kg > 0 "
        "AND weight_delta_kg = trunc(weight_delta_kg, 3) AND weight_delta_kg < 100000000000) "
        "OR (entry_kind = 'harvest_adjustment' "
        "AND weight_delta_kg = trunc(weight_delta_kg, 3) "
        "AND weight_delta_kg > -100000000000 AND weight_delta_kg < 100000000000) "
        "OR (entry_kind = 'grading_consumption' AND weight_delta_kg < 0 "
        "AND weight_delta_kg = trunc(weight_delta_kg, 3) AND weight_delta_kg > -100000000000)",
    )
    _drop_check_if_exists("produce_lot_ledger_entries", "ck_produce_lot_ledger_entries_kind_allowed")
    _add_check_validating_when_safe(
        "produce_lot_ledger_entries",
        "ck_produce_lot_ledger_entries_kind_allowed",
        "entry_kind IN ('harvest_receipt', 'harvest_adjustment', 'grading_consumption')",
    )
    op.drop_index("ux_produce_lot_ledger_entries_event_grading_reversal", table_name="produce_lot_ledger_entries")
    op.drop_constraint(
        "fk_produce_lot_ledger_entries_tenant_farm_grading_reversal", "produce_lot_ledger_entries",
        type_="foreignkey",
    )
    op.drop_column("produce_lot_ledger_entries", "grading_reversal_event_id")

    # --- 4-1. drop the four new tables (append-only triggers dropped with them) -----
    op.drop_table("packing_reversal_inputs")
    op.drop_table("packing_reversal_events")
    op.drop_table("grading_reversal_outputs")
    op.drop_table("grading_reversal_events")

    # --- 3b. drop packing_input_lines' composite unique added by this ticket --------
    op.drop_constraint("uq_packing_input_lines_tenant_farm_id", "packing_input_lines", type_="unique")
