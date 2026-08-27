"""convert packing to graded produce lots and pack specification

Revision ID: d8f4a1c92b57
Revises: c3f7a29d5e64
Create Date: 2026-08-27 09:00:00.000000

POSTHARVEST-OPS-001E: breaking conversion of Packing's source contract
from `HarvestedProduceLot` directly to `GradedProduceLot`:

    HarvestedProduceLot -> GradingEvent -> GradedProduceLot
        -> PackingInputLine -> PackingEvent -> FinishedGoodsLot

`PackingEvent` gains a required `pack_specification_version_id` (tenant-
scoped composite FK -- `PackSpecification`/`PackSpecificationVersion` are
tenant-only, never farm-scoped). `PackingInputLine.harvested_produce_lot_id`
is replaced by `graded_produce_lot_id`. `produce_lot_ledger_entries` loses
`packing_consumption` support (HarvestedProduceLot balance is affected by
Grading only, from POSTHARVEST-OPS-001C onward).
`graded_produce_lot_ledger_entries` gains `packing_consumption`, mirroring
`produce_lot_ledger_entries`'s own historical `packing_consumption` shape
one layer up.

This is a genuinely breaking schema conversion with no honest HPL-to-GPL
backfill mapping. The upgrade pre-flight guard aborts unconditionally if
any legacy Packing operational history exists -- no row is ever
reinterpreted, merged, or guessed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d8f4a1c92b57"
down_revision: Union[str, None] = "c3f7a29d5e64"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# =====================================================================
# The exact CURRENT (POSTHARVEST-OPS-001C) body of
# enforce_produce_lot_ledger_entry_insert_integrity_v2 -- reproduced
# byte-for-byte from f2c8a5d1e793 so downgrade can restore it exactly via
# CREATE OR REPLACE. Never edit this string to "improve" it.
# =====================================================================
_LEDGER_V2_CURRENT_BODY = """
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

# The packing_consumption branch, excised verbatim for the narrowed
# (POSTHARVEST-OPS-001E) body -- HarvestedProduceLot balance is no longer
# affected by Packing at all after this ticket.
_PACKING_CONSUMPTION_BRANCH = """
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

"""


def _narrowed_ledger_v2_body() -> str:
    """The POSTHARVEST-OPS-001E body: the exact current body with the
    `packing_consumption` branch removed (Packing no longer touches
    `produce_lot_ledger_entries` at all). DECLARE variables used only by
    that branch (`v_line`, `v_packing_event`) are left in place, unused --
    harmless in plpgsql, and keeps this a pure excision, not a rewrite."""
    body = _LEDGER_V2_CURRENT_BODY
    assert _PACKING_CONSUMPTION_BRANCH in body, "packing_consumption branch text must match byte-for-byte"
    return body.replace(_PACKING_CONSUMPTION_BRANCH, "\n")


# =====================================================================
# The exact CURRENT (POSTHARVEST-OPS-001C) body of
# enforce_graded_produce_lot_ledger_entry_insert_integrity -- reproduced
# byte-for-byte from f2c8a5d1e793 so downgrade can restore it exactly via
# CREATE OR REPLACE. Never edit this string to "improve" it.
# =====================================================================
_GRADED_LEDGER_ORIGINAL_BODY = """
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
        IF v_lot_event_id <> NEW.grading_event_id THEN
            RAISE EXCEPTION 'ledger entry grading event does not match the graded produce lot''s own event';
        END IF;

        SELECT actor_user_id INTO v_event_actor FROM grading_events WHERE id = NEW.grading_event_id;
        IF v_event_actor IS NULL THEN
            RAISE EXCEPTION 'grading event not found for ledger entry';
        END IF;

        IF NEW.entry_kind = 'grading_receipt' THEN
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
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

# The POSTHARVEST-OPS-001E widened body: the tenant/farm and
# grading-event-identity checks that used to run unconditionally now run
# only for `grading_receipt` (a `packing_consumption` row legitimately has
# `grading_event_id IS NULL`), and a new `packing_consumption` branch
# validates identity against `packing_input_lines`/`packing_events` and
# re-derives GPL balance sufficiency independently of
# `enforce_packing_input_line_insert_integrity_v3`, mirroring the same
# defense-in-depth redundancy `enforce_produce_lot_ledger_entry_insert_integrity_v2`
# already applies to its own `packing_consumption` branch.
_GRADED_LEDGER_WIDENED_BODY = """
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


def upgrade() -> None:
    bind = op.get_bind()

    # --- 1. legacy operational history guard (frozen policy: never map/guess) --------
    counts = bind.execute(
        sa.text(
            "SELECT "
            "(SELECT count(*) FROM packing_events) AS event_count, "
            "(SELECT count(*) FROM packing_input_lines) AS line_count, "
            "(SELECT count(*) FROM finished_goods_lots) AS fg_count, "
            "(SELECT count(*) FROM finished_goods_ledger_entries WHERE entry_kind = 'packing_receipt') AS fg_receipt_count, "
            "(SELECT count(*) FROM produce_lot_ledger_entries WHERE entry_kind = 'packing_consumption') AS legacy_consumption_count"
        )
    ).mappings().first()
    if any(counts[k] > 0 for k in counts.keys()):
        raise RuntimeError(
            "POSTHARVEST-OPS-001E cannot upgrade: legacy Packing operational history exists "
            f"({dict(counts)}). There is no honest HarvestedProduceLot-to-GradedProduceLot mapping for "
            "existing packing_input_lines -- refusing to guess, merge, or fabricate lineage. Remove or "
            "migrate the offending data out-of-band first, or do not upgrade."
        )

    # --- 2. narrow produce_lot_ledger_entries: remove packing_consumption support ----
    # Order matters: `ck_produce_lot_ledger_entries_typed_source_shape`'s
    # condition references `packing_event_id` -- PostgreSQL auto-drops a
    # CHECK constraint when the column it references is dropped, so every
    # CHECK must be dropped/recreated (narrowed, no longer referencing that
    # column) BEFORE the column itself is dropped, never after.
    op.drop_index("ux_produce_lot_ledger_entries_event_lot_packing_consumption", table_name="produce_lot_ledger_entries")
    op.drop_constraint(
        "fk_produce_lot_ledger_entries_tenant_farm_packing_event", "produce_lot_ledger_entries", type_="foreignkey"
    )

    op.drop_constraint("ck_produce_lot_ledger_entries_kind_allowed", "produce_lot_ledger_entries", type_="check")
    op.create_check_constraint(
        "ck_produce_lot_ledger_entries_kind_allowed",
        "produce_lot_ledger_entries",
        "entry_kind IN ('harvest_receipt', 'harvest_adjustment', 'grading_consumption')",
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
        "AND weight_delta_kg = trunc(weight_delta_kg, 3) AND weight_delta_kg > -100000000000)",
    )
    op.drop_constraint("ck_produce_lot_ledger_entries_count_positive", "produce_lot_ledger_entries", type_="check")
    op.create_check_constraint(
        "ck_produce_lot_ledger_entries_count_positive",
        "produce_lot_ledger_entries",
        "(entry_kind = 'harvest_receipt' AND (whole_unit_count_delta IS NULL OR whole_unit_count_delta > 0)) "
        "OR (entry_kind = 'harvest_adjustment' AND (whole_unit_count_delta IS NULL OR whole_unit_count_delta <> 0)) "
        "OR (entry_kind = 'grading_consumption' AND (whole_unit_count_delta IS NULL OR whole_unit_count_delta < 0))",
    )
    op.drop_constraint(
        "ck_produce_lot_ledger_entries_typed_source_shape", "produce_lot_ledger_entries", type_="check"
    )
    op.create_check_constraint(
        "ck_produce_lot_ledger_entries_typed_source_shape",
        "produce_lot_ledger_entries",
        "(entry_kind = 'harvest_receipt' AND harvest_event_id IS NOT NULL "
        "AND harvest_source_line_correction_id IS NULL AND grading_event_id IS NULL) "
        "OR (entry_kind = 'harvest_adjustment' AND harvest_event_id IS NULL "
        "AND harvest_source_line_correction_id IS NOT NULL AND grading_event_id IS NULL) "
        "OR (entry_kind = 'grading_consumption' AND harvest_event_id IS NULL "
        "AND harvest_source_line_correction_id IS NULL AND grading_event_id IS NOT NULL)",
    )
    op.drop_column("produce_lot_ledger_entries", "packing_event_id")
    op.execute(_narrowed_ledger_v2_body())

    # --- 3. widen graded_produce_lot_ledger_entries: add packing_consumption --------
    op.alter_column(
        "graded_produce_lot_ledger_entries", "grading_event_id",
        existing_type=postgresql.UUID(as_uuid=True), nullable=True,
    )
    op.add_column(
        "graded_produce_lot_ledger_entries",
        sa.Column("packing_event_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_graded_produce_lot_ledger_entries_tenant_farm_packing_event",
        "graded_produce_lot_ledger_entries", "packing_events",
        ["tenant_id", "farm_id", "packing_event_id"], ["tenant_id", "farm_id", "id"],
    )
    op.drop_constraint(
        "ck_graded_produce_lot_ledger_entries_kind_allowed", "graded_produce_lot_ledger_entries", type_="check"
    )
    op.create_check_constraint(
        "ck_graded_produce_lot_ledger_entries_kind_allowed",
        "graded_produce_lot_ledger_entries",
        "entry_kind IN ('grading_receipt', 'packing_consumption')",
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
        ")",
    )
    op.drop_constraint(
        "ck_graded_produce_lot_ledger_entries_count_positive", "graded_produce_lot_ledger_entries", type_="check"
    )
    op.create_check_constraint(
        "ck_graded_produce_lot_ledger_entries_count_positive",
        "graded_produce_lot_ledger_entries",
        "(entry_kind = 'grading_receipt' AND (whole_unit_count_delta IS NULL OR whole_unit_count_delta > 0)) "
        "OR (entry_kind = 'packing_consumption' AND (whole_unit_count_delta IS NULL OR whole_unit_count_delta < 0))",
    )
    op.create_check_constraint(
        "ck_graded_produce_lot_ledger_entries_typed_source_shape",
        "graded_produce_lot_ledger_entries",
        "(entry_kind = 'grading_receipt' AND grading_event_id IS NOT NULL AND packing_event_id IS NULL) "
        "OR (entry_kind = 'packing_consumption' AND grading_event_id IS NULL AND packing_event_id IS NOT NULL)",
    )
    op.create_index(
        "ux_graded_produce_lot_ledger_entries_packing_consumption",
        "graded_produce_lot_ledger_entries", ["packing_event_id", "graded_produce_lot_id"], unique=True,
        postgresql_where=sa.text("entry_kind = 'packing_consumption'"),
    )

    # --- 3b. widen enforce_graded_produce_lot_ledger_entry_insert_integrity ---------
    # Pre-existing (POSTHARVEST-OPS-001C) trigger on graded_produce_lot_ledger_entries
    # itself -- widened IN PLACE (same function name, trigger attachment never
    # touched) exactly like enforce_produce_lot_ledger_entry_insert_integrity_v2's
    # own convention for adding a new entry_kind branch.
    op.execute(_GRADED_LEDGER_WIDENED_BODY)

    # --- 4. PackingInputLine: HPL source -> GPL source -------------------------------
    # 677fcd22cb3c's own "traceability indexes" migration created a plain
    # (non-unique) index on (tenant_id, farm_id, harvested_produce_lot_id)
    # for lineage-lookup performance -- dropped explicitly here (rather than
    # relying on the implicit cascade `DROP COLUMN` performs on it) and
    # replaced with the equivalent index on the new source column, so
    # traceability's own GPL-keyed joins get the same benefit.
    op.drop_index("ix_packing_input_lines_tenant_farm_produce_lot", table_name="packing_input_lines")
    op.drop_constraint("ux_packing_input_lines_event_lot", "packing_input_lines", type_="unique")
    op.drop_constraint("fk_packing_input_lines_tenant_farm_lot", "packing_input_lines", type_="foreignkey")
    op.drop_column("packing_input_lines", "harvested_produce_lot_id")
    op.add_column(
        "packing_input_lines",
        sa.Column("graded_produce_lot_id", postgresql.UUID(as_uuid=True), nullable=False),
    )
    op.create_foreign_key(
        "fk_packing_input_lines_tenant_farm_gpl", "packing_input_lines", "graded_produce_lots",
        ["tenant_id", "farm_id", "graded_produce_lot_id"], ["tenant_id", "farm_id", "id"],
    )
    op.create_unique_constraint(
        "ux_packing_input_lines_event_gpl", "packing_input_lines", ["packing_event_id", "graded_produce_lot_id"]
    )
    op.create_index(
        "ix_packing_input_lines_tenant_farm_graded_produce_lot",
        "packing_input_lines", ["tenant_id", "farm_id", "graded_produce_lot_id"],
    )

    # --- 5. PackingEvent: pin an exact PackSpecificationVersion ----------------------
    # PackSpecification/PackSpecificationVersion are tenant-scoped only (no
    # farm_id) -- the composite FK is deliberately (tenant_id, id), never
    # the usual (tenant_id, farm_id, id) triple this codebase uses
    # everywhere else, matching PackSpecificationVersion's own actual shape.
    op.add_column(
        "packing_events",
        sa.Column("pack_specification_version_id", postgresql.UUID(as_uuid=True), nullable=False),
    )
    op.create_foreign_key(
        "fk_packing_events_tenant_pack_spec_version", "packing_events", "pack_specification_versions",
        ["tenant_id", "pack_specification_version_id"], ["tenant_id", "id"],
    )

    # --- 6. packing_events insert-integrity: v1 -> v2 (add PackSpecVersion checks) --
    # CMP-015's own enforce_packing_event_insert_integrity() function
    # (created in a91f4c7b2e58 -- effective_time-not-in-the-future only)
    # is never modified -- only the trigger attachment is dropped and
    # replaced, the same idiom this codebase always uses. v2 reproduces
    # the v1 check byte-for-byte and adds PackSpecificationVersion
    # tenant/status/effective-window/crop/variety-pin validation -- mirrors
    # enforce_grading_event_insert_integrity's own "validate a referenced
    # spec/config row, once, immediately" shape one layer over. Only checks
    # what is resolvable from the PackSpecificationVersion row alone;
    # cross-input-line grade-pin compatibility is necessarily deferred (see
    # enforce_packing_reconciliation_v2) since input lines do not exist yet
    # when packing_events is inserted.
    op.execute("DROP TRIGGER packing_events_enforce_insert_integrity ON packing_events")
    op.execute(
        """
        CREATE FUNCTION enforce_packing_event_insert_integrity_v2() RETURNS trigger AS $$
        DECLARE
            v_spec_version RECORD;
            v_spec RECORD;
        BEGIN
            IF NEW.effective_time > clock_timestamp() THEN
                RAISE EXCEPTION 'packing event effective_time cannot be in the future';
            END IF;

            SELECT * INTO v_spec_version FROM pack_specification_versions
            WHERE id = NEW.pack_specification_version_id;
            IF v_spec_version.id IS NULL THEN
                RAISE EXCEPTION 'pack specification version not found for packing event';
            END IF;
            IF v_spec_version.tenant_id <> NEW.tenant_id THEN
                RAISE EXCEPTION 'packing event tenant does not match the pack specification version''s own';
            END IF;
            IF v_spec_version.status = 'draft' THEN
                RAISE EXCEPTION 'pack specification version % is draft and cannot be referenced', NEW.pack_specification_version_id;
            END IF;
            IF NEW.effective_time < v_spec_version.effective_from THEN
                RAISE EXCEPTION 'pack specification version % is not yet effective at this event''s effective_time', NEW.pack_specification_version_id;
            END IF;
            IF v_spec_version.effective_until IS NOT NULL AND NEW.effective_time >= v_spec_version.effective_until THEN
                RAISE EXCEPTION 'pack specification version % is no longer effective at this event''s effective_time', NEW.pack_specification_version_id;
            END IF;

            SELECT * INTO v_spec FROM pack_specifications WHERE id = v_spec_version.pack_specification_id;
            IF v_spec.crop_id <> NEW.crop_id THEN
                RAISE EXCEPTION 'pack specification % crop does not match the packing event''s own crop', v_spec.id;
            END IF;
            IF v_spec.variety_id IS NOT NULL AND v_spec.variety_id IS DISTINCT FROM NEW.variety_id THEN
                RAISE EXCEPTION 'pack specification % variety is incompatible with the packing event''s own variety', v_spec.id;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER packing_events_enforce_insert_integrity
        BEFORE INSERT ON packing_events
        FOR EACH ROW EXECUTE FUNCTION enforce_packing_event_insert_integrity_v2();
        """
    )

    # --- 7. packing_input_lines insert-integrity: v2 (HPL) -> v3 (GPL) --------------
    # CMP-015/CMP-020's own enforce_packing_input_line_insert_integrity_v2()
    # function is never modified -- only the trigger attachment is dropped
    # and replaced, the same idiom this codebase always uses. v3 checks the
    # exact same class of things (tenant/farm, count-mode, chronology,
    # balance, recall containment) against the new GPL source and its
    # inherited upstream HPL/CropBatch/QualityHold chain (POSTHARVEST-OPS-
    # 001E requirement) -- it does not re-validate the GPL's own
    # GradeDefinitionVersion effective window (already proven at Grading
    # time; a since-retired grade version does not retroactively block
    # Packing). Lock order strictly ascending: CropBatch -> HarvestedProduceLot
    # -> GradedProduceLot, matching the codebase's global order and never
    # walking GPL -> HPL -> Batch after acquiring the GPL lock.
    op.execute("DROP TRIGGER packing_input_lines_enforce_insert_integrity ON packing_input_lines")
    op.execute(
        """
        CREATE FUNCTION enforce_packing_input_line_insert_integrity_v3() RETURNS trigger AS $$
        DECLARE
            v_gpl RECORD;
            v_grading_event RECORD;
            v_event RECORD;
            v_available_weight NUMERIC;
            v_available_count BIGINT;
            v_remaining_weight NUMERIC;
            v_remaining_count BIGINT;
            v_latest_ledger_effective_time TIMESTAMPTZ;
            v_open_hold BOOLEAN;
            v_open_batch_recall BOOLEAN;
            v_open_lot_recall BOOLEAN;
            v_open_gpl_recall BOOLEAN;
        BEGIN
            SELECT * INTO v_gpl FROM graded_produce_lots WHERE id = NEW.graded_produce_lot_id;
            IF v_gpl.id IS NULL THEN
                RAISE EXCEPTION 'graded produce lot not found for packing input line';
            END IF;
            IF v_gpl.tenant_id <> NEW.tenant_id OR v_gpl.farm_id <> NEW.farm_id THEN
                RAISE EXCEPTION 'packing input line tenant/farm does not match the source graded produce lot''s own';
            END IF;

            SELECT * INTO v_event FROM packing_events WHERE id = NEW.packing_event_id;
            IF v_event.id IS NULL THEN
                RAISE EXCEPTION 'packing event not found for packing input line';
            END IF;
            IF v_event.tenant_id <> NEW.tenant_id OR v_event.farm_id <> NEW.farm_id THEN
                RAISE EXCEPTION 'packing input line tenant/farm does not match its packing event''s own';
            END IF;

            SELECT * INTO v_grading_event FROM grading_events WHERE id = v_gpl.grading_event_id;
            IF v_grading_event.id IS NULL THEN
                RAISE EXCEPTION 'grading event not found for source graded produce lot';
            END IF;

            -- Lock order: CropBatch -> HarvestedProduceLot -> GradedProduceLot,
            -- strictly ascending, never inverted -- the exact rows a
            -- batch-source / harvested-produce-lot-source / graded-produce-
            -- lot-source recall each lock for their own containment freeze.
            PERFORM 1 FROM crop_batches cb
            JOIN harvested_produce_lots hpl ON hpl.batch_id = cb.id
            WHERE hpl.id = v_grading_event.source_harvested_produce_lot_id
            FOR UPDATE;

            SELECT EXISTS (
                SELECT 1 FROM quality_holds h
                JOIN harvested_produce_lots hpl ON hpl.batch_id = h.batch_id
                WHERE hpl.id = v_grading_event.source_harvested_produce_lot_id
                  AND NOT EXISTS (SELECT 1 FROM quality_hold_releases r WHERE r.quality_hold_id = h.id)
            ) INTO v_open_hold;
            IF v_open_hold THEN
                RAISE EXCEPTION 'source graded produce lot % upstream crop batch has an open quality hold', NEW.graded_produce_lot_id;
            END IF;

            SELECT EXISTS (
                SELECT 1 FROM recall_scope_batches rsb
                JOIN harvested_produce_lots hpl ON hpl.batch_id = rsb.crop_batch_id
                WHERE hpl.id = v_grading_event.source_harvested_produce_lot_id
                  AND NOT EXISTS (SELECT 1 FROM recall_case_closures rcc WHERE rcc.recall_case_id = rsb.recall_case_id)
            ) INTO v_open_batch_recall;
            IF v_open_batch_recall THEN
                RAISE EXCEPTION 'source graded produce lot % upstream crop batch is contained by an open recall case', NEW.graded_produce_lot_id;
            END IF;

            PERFORM 1 FROM harvested_produce_lots WHERE id = v_grading_event.source_harvested_produce_lot_id FOR UPDATE;

            SELECT EXISTS (
                SELECT 1 FROM recall_scope_produce_lots rspl
                WHERE rspl.harvested_produce_lot_id = v_grading_event.source_harvested_produce_lot_id
                  AND NOT EXISTS (SELECT 1 FROM recall_case_closures rcc WHERE rcc.recall_case_id = rspl.recall_case_id)
            ) INTO v_open_lot_recall;
            IF v_open_lot_recall THEN
                RAISE EXCEPTION 'source graded produce lot % upstream harvested produce lot is contained by an open recall case', NEW.graded_produce_lot_id;
            END IF;

            PERFORM 1 FROM graded_produce_lots WHERE id = NEW.graded_produce_lot_id FOR UPDATE;

            SELECT EXISTS (
                SELECT 1 FROM recall_scope_graded_produce_lots rsg
                WHERE rsg.graded_produce_lot_id = NEW.graded_produce_lot_id
                  AND NOT EXISTS (SELECT 1 FROM recall_case_closures rcc WHERE rcc.recall_case_id = rsg.recall_case_id)
            ) INTO v_open_gpl_recall;
            IF v_open_gpl_recall THEN
                RAISE EXCEPTION 'graded produce lot % is contained by an open recall case', NEW.graded_produce_lot_id;
            END IF;

            IF v_event.effective_time < v_gpl.effective_time THEN
                RAISE EXCEPTION 'packing event effective_time precedes source graded produce lot %''s own effective_time', NEW.graded_produce_lot_id;
            END IF;
            SELECT max(effective_time) INTO v_latest_ledger_effective_time
            FROM graded_produce_lot_ledger_entries WHERE graded_produce_lot_id = NEW.graded_produce_lot_id;
            IF v_latest_ledger_effective_time IS NOT NULL AND v_event.effective_time < v_latest_ledger_effective_time THEN
                RAISE EXCEPTION 'packing event effective_time precedes the latest existing ledger entry for source graded produce lot %', NEW.graded_produce_lot_id;
            END IF;

            IF v_gpl.original_received_whole_unit_count IS NULL THEN
                IF NEW.consumed_whole_unit_count IS NOT NULL THEN
                    RAISE EXCEPTION 'source graded produce lot does not track whole-unit count; packing input count must be null';
                END IF;
            ELSE
                IF NEW.consumed_whole_unit_count IS NULL THEN
                    RAISE EXCEPTION 'source graded produce lot tracks whole-unit count; packing input count is required';
                END IF;
            END IF;

            SELECT COALESCE(sum(weight_delta_kg), 0), sum(whole_unit_count_delta)
            INTO v_available_weight, v_available_count
            FROM graded_produce_lot_ledger_entries WHERE graded_produce_lot_id = NEW.graded_produce_lot_id;

            v_remaining_weight := v_available_weight - NEW.consumed_weight_kg;
            IF v_remaining_weight < 0 THEN
                RAISE EXCEPTION 'consumed_weight_kg exceeds source graded produce lot % available balance', NEW.graded_produce_lot_id;
            END IF;
            IF NEW.consumed_whole_unit_count IS NOT NULL THEN
                IF v_available_count IS NULL OR NEW.consumed_whole_unit_count > v_available_count THEN
                    RAISE EXCEPTION 'consumed_whole_unit_count exceeds source graded produce lot % available balance', NEW.graded_produce_lot_id;
                END IF;
                v_remaining_count := v_available_count - NEW.consumed_whole_unit_count;
                IF (v_remaining_weight = 0 AND v_remaining_count > 0)
                   OR (v_remaining_weight > 0 AND v_remaining_count = 0) THEN
                    RAISE EXCEPTION 'packing would leave source graded produce lot % with mismatched residual weight/count', NEW.graded_produce_lot_id;
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER packing_input_lines_enforce_insert_integrity
        BEFORE INSERT ON packing_input_lines
        FOR EACH ROW EXECUTE FUNCTION enforce_packing_input_line_insert_integrity_v3();
        """
    )

    # --- 8. deferred packing reconciliation: v1 -> v2 (GPL-keyed) --------------------
    op.execute("DROP TRIGGER packing_events_enforce_reconciliation ON packing_events")
    op.execute("DROP TRIGGER packing_input_lines_enforce_reconciliation ON packing_input_lines")
    op.execute("DROP TRIGGER finished_goods_lots_enforce_reconciliation ON finished_goods_lots")
    op.execute(
        "DROP TRIGGER produce_lot_ledger_entries_enforce_packing_reconciliation ON produce_lot_ledger_entries"
    )
    op.execute(
        """
        CREATE FUNCTION enforce_packing_reconciliation_v2() RETURNS trigger AS $$
        DECLARE
            v_event_id UUID;
            v_input_count INTEGER;
            v_output_count INTEGER;
            v_debit_count INTEGER;
            v_orphan_debit_count INTEGER;
            v_line_weight_sum NUMERIC;
            v_event RECORD;
            v_spec_version RECORD;
            v_distinct_grade_count INTEGER;
        BEGIN
            IF TG_TABLE_NAME = 'packing_events' THEN
                v_event_id := NEW.id;
            ELSIF TG_TABLE_NAME IN ('packing_input_lines', 'finished_goods_lots') THEN
                v_event_id := NEW.packing_event_id;
            ELSIF TG_TABLE_NAME = 'graded_produce_lot_ledger_entries' THEN
                IF NEW.entry_kind <> 'packing_consumption' THEN
                    RETURN NEW;
                END IF;
                v_event_id := NEW.packing_event_id;
            END IF;

            IF v_event_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT * INTO v_event FROM packing_events WHERE id = v_event_id;
            IF v_event.id IS NULL THEN
                RAISE EXCEPTION 'packing event % not found during reconciliation', v_event_id;
            END IF;

            SELECT count(*) INTO v_input_count FROM packing_input_lines WHERE packing_event_id = v_event_id;
            IF v_input_count < 1 THEN
                RAISE EXCEPTION 'packing event % must have at least one input line', v_event_id;
            END IF;

            IF (
                SELECT count(DISTINCT graded_produce_lot_id) FROM packing_input_lines
                WHERE packing_event_id = v_event_id
            ) <> v_input_count THEN
                RAISE EXCEPTION 'packing event % has a source graded produce lot referenced more than once', v_event_id;
            END IF;

            IF EXISTS (
                SELECT 1 FROM packing_input_lines pil
                JOIN graded_produce_lots gpl ON gpl.id = pil.graded_produce_lot_id
                WHERE pil.packing_event_id = v_event_id
                  AND (gpl.crop_id <> v_event.crop_id OR gpl.variety_id IS DISTINCT FROM v_event.variety_id)
            ) THEN
                RAISE EXCEPTION 'packing event % has an input graded produce lot with mismatched crop/variety', v_event_id;
            END IF;

            SELECT count(DISTINCT gpl.grade_definition_version_id) INTO v_distinct_grade_count
            FROM packing_input_lines pil JOIN graded_produce_lots gpl ON gpl.id = pil.graded_produce_lot_id
            WHERE pil.packing_event_id = v_event_id;
            IF v_distinct_grade_count <> 1 THEN
                RAISE EXCEPTION 'packing event % input graded produce lots do not share one exact grade definition version', v_event_id;
            END IF;

            SELECT * INTO v_spec_version FROM pack_specification_versions WHERE id = v_event.pack_specification_version_id;
            IF v_spec_version.grade_definition_version_id IS NOT NULL AND EXISTS (
                SELECT 1 FROM packing_input_lines pil
                JOIN graded_produce_lots gpl ON gpl.id = pil.graded_produce_lot_id
                WHERE pil.packing_event_id = v_event_id
                  AND gpl.grade_definition_version_id <> v_spec_version.grade_definition_version_id
            ) THEN
                RAISE EXCEPTION 'packing event % has an input graded produce lot that does not match its pack specification version''s pinned grade', v_event_id;
            END IF;

            SELECT count(*) INTO v_output_count FROM finished_goods_lots WHERE packing_event_id = v_event_id;
            IF v_output_count <> 1 THEN
                RAISE EXCEPTION 'packing event % must have exactly one finished-goods lot', v_event_id;
            END IF;

            SELECT count(*) INTO v_debit_count FROM graded_produce_lot_ledger_entries
            WHERE packing_event_id = v_event_id AND entry_kind = 'packing_consumption';
            IF v_debit_count <> v_input_count THEN
                RAISE EXCEPTION 'packing event % input-line count does not match graded ledger-debit count', v_event_id;
            END IF;

            IF EXISTS (
                SELECT 1 FROM packing_input_lines pil
                LEFT JOIN graded_produce_lot_ledger_entries r
                  ON r.id = pil.id AND r.entry_kind = 'packing_consumption'
                WHERE pil.packing_event_id = v_event_id
                  AND (
                    r.id IS NULL
                    OR r.graded_produce_lot_id IS DISTINCT FROM pil.graded_produce_lot_id
                    OR r.packing_event_id IS DISTINCT FROM pil.packing_event_id
                    OR r.grading_event_id IS NOT NULL
                    OR r.weight_delta_kg IS DISTINCT FROM (-pil.consumed_weight_kg)
                    OR r.whole_unit_count_delta IS DISTINCT FROM
                       (CASE WHEN pil.consumed_whole_unit_count IS NULL THEN NULL ELSE -pil.consumed_whole_unit_count END)
                    OR r.effective_time IS DISTINCT FROM v_event.effective_time
                    OR r.recorded_time IS DISTINCT FROM pil.recorded_time
                    OR r.actor_user_id IS DISTINCT FROM v_event.actor_user_id
                    OR r.note IS DISTINCT FROM pil.note
                  )
            ) THEN
                RAISE EXCEPTION 'packing event % has an input line without an exactly matching graded ledger debit', v_event_id;
            END IF;

            SELECT count(*) INTO v_orphan_debit_count
            FROM graded_produce_lot_ledger_entries r
            WHERE r.packing_event_id = v_event_id AND r.entry_kind = 'packing_consumption'
              AND NOT EXISTS (SELECT 1 FROM packing_input_lines pil WHERE pil.id = r.id);
            IF v_orphan_debit_count > 0 THEN
                RAISE EXCEPTION 'packing event % has a graded ledger debit with no matching input line', v_event_id;
            END IF;

            SELECT COALESCE(sum(consumed_weight_kg), 0) INTO v_line_weight_sum
            FROM packing_input_lines WHERE packing_event_id = v_event_id;
            IF v_line_weight_sum <> v_event.total_input_weight_kg THEN
                RAISE EXCEPTION 'packing event % total input weight does not equal the sum of its input lines', v_event_id;
            END IF;
            IF v_event.total_input_weight_kg <>
               (v_event.packed_output_weight_kg + v_event.process_loss_weight_kg + v_event.rejected_weight_kg)
            THEN
                RAISE EXCEPTION 'packing event % does not reconcile: input <> output + loss + rejection', v_event_id;
            END IF;

            IF EXISTS (
                SELECT 1 FROM finished_goods_lots fg
                WHERE fg.packing_event_id = v_event_id
                  AND (
                    fg.crop_id <> v_event.crop_id
                    OR fg.variety_id IS DISTINCT FROM v_event.variety_id
                    OR fg.net_packed_weight_kg <> v_event.packed_output_weight_kg
                    OR fg.effective_time <> v_event.effective_time
                  )
            ) THEN
                RAISE EXCEPTION 'packing event % finished-goods lot does not match the event', v_event_id;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER packing_events_enforce_reconciliation
        AFTER INSERT ON packing_events
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_packing_reconciliation_v2();
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER packing_input_lines_enforce_reconciliation
        AFTER INSERT ON packing_input_lines
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_packing_reconciliation_v2();
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER finished_goods_lots_enforce_reconciliation
        AFTER INSERT ON finished_goods_lots
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_packing_reconciliation_v2();
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER graded_produce_lot_ledger_enforce_packing_reconciliation
        AFTER INSERT ON graded_produce_lot_ledger_entries
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_packing_reconciliation_v2();
        """
    )


def downgrade() -> None:
    bind = op.get_bind()

    # --- downgrade guard: new graded-input Packing history is independent data ------
    unsafe = bind.execute(
        sa.text(
            "SELECT "
            "(SELECT count(*) FROM packing_events) AS event_count, "
            "(SELECT count(*) FROM packing_input_lines) AS line_count, "
            "(SELECT count(*) FROM graded_produce_lot_ledger_entries WHERE entry_kind = 'packing_consumption') AS graded_consumption_count"
        )
    ).mappings().first()
    if any(unsafe[k] > 0 for k in unsafe.keys()):
        raise RuntimeError(
            "Cannot downgrade past POSTHARVEST-OPS-001E: graded-produce-lot-input Packing history exists. "
            "This is new commercial operational history, never reconstructible from any other table. "
            "Do not downgrade."
        )

    # --- restore deferred reconciliation to the exact CMP-015 (v1) shape ------------
    op.execute("DROP TRIGGER graded_produce_lot_ledger_enforce_packing_reconciliation ON graded_produce_lot_ledger_entries")
    op.execute("DROP TRIGGER finished_goods_lots_enforce_reconciliation ON finished_goods_lots")
    op.execute("DROP TRIGGER packing_input_lines_enforce_reconciliation ON packing_input_lines")
    op.execute("DROP TRIGGER packing_events_enforce_reconciliation ON packing_events")
    op.execute("DROP FUNCTION IF EXISTS enforce_packing_reconciliation_v2()")
    # enforce_packing_reconciliation() (v1) was never dropped -- only its
    # trigger attachments were -- so CREATE OR REPLACE is unnecessary; just
    # re-attach the still-existing original function.
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER packing_events_enforce_reconciliation
        AFTER INSERT ON packing_events
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_packing_reconciliation();
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER packing_input_lines_enforce_reconciliation
        AFTER INSERT ON packing_input_lines
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_packing_reconciliation();
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER finished_goods_lots_enforce_reconciliation
        AFTER INSERT ON finished_goods_lots
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_packing_reconciliation();
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER produce_lot_ledger_entries_enforce_packing_reconciliation
        AFTER INSERT ON produce_lot_ledger_entries
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_packing_reconciliation();
        """
    )

    # --- restore packing_input_lines to the exact CMP-020 (v2, HPL) attachment ------
    op.execute("DROP TRIGGER packing_input_lines_enforce_insert_integrity ON packing_input_lines")
    op.execute("DROP FUNCTION IF EXISTS enforce_packing_input_line_insert_integrity_v3()")
    op.execute(
        """
        CREATE TRIGGER packing_input_lines_enforce_insert_integrity
        BEFORE INSERT ON packing_input_lines
        FOR EACH ROW EXECUTE FUNCTION enforce_packing_input_line_insert_integrity_v2();
        """
    )

    # --- restore packing_events to the exact CMP-015 (v1) attachment ---------------
    op.execute("DROP TRIGGER packing_events_enforce_insert_integrity ON packing_events")
    op.execute("DROP FUNCTION IF EXISTS enforce_packing_event_insert_integrity_v2()")
    op.execute(
        """
        CREATE TRIGGER packing_events_enforce_insert_integrity
        BEFORE INSERT ON packing_events
        FOR EACH ROW EXECUTE FUNCTION enforce_packing_event_insert_integrity();
        """
    )

    # --- PackingEvent: drop pack_specification_version_id ---------------------------
    op.drop_constraint("fk_packing_events_tenant_pack_spec_version", "packing_events", type_="foreignkey")
    op.drop_column("packing_events", "pack_specification_version_id")

    # --- PackingInputLine: GPL source -> HPL source (restore exact CMP-015 shape) ---
    op.drop_index("ix_packing_input_lines_tenant_farm_graded_produce_lot", table_name="packing_input_lines")
    op.drop_constraint("ux_packing_input_lines_event_gpl", "packing_input_lines", type_="unique")
    op.drop_constraint("fk_packing_input_lines_tenant_farm_gpl", "packing_input_lines", type_="foreignkey")
    op.drop_column("packing_input_lines", "graded_produce_lot_id")
    op.add_column(
        "packing_input_lines",
        sa.Column("harvested_produce_lot_id", postgresql.UUID(as_uuid=True), nullable=False),
    )
    op.create_foreign_key(
        "fk_packing_input_lines_tenant_farm_lot", "packing_input_lines", "harvested_produce_lots",
        ["tenant_id", "farm_id", "harvested_produce_lot_id"], ["tenant_id", "farm_id", "id"],
    )
    op.create_unique_constraint(
        "ux_packing_input_lines_event_lot", "packing_input_lines", ["packing_event_id", "harvested_produce_lot_id"]
    )
    # Restore 677fcd22cb3c's own original traceability index exactly, so
    # its own downgrade (further down this same cascade) can find and drop
    # it, and a clean re-upgrade recreates it identically via this same step.
    op.create_index(
        "ix_packing_input_lines_tenant_farm_produce_lot",
        "packing_input_lines", ["tenant_id", "farm_id", "harvested_produce_lot_id"],
    )

    # --- restore enforce_graded_produce_lot_ledger_entry_insert_integrity to the ----
    # --- exact CMP-020 (001D-era, grading_receipt-only) body ------------------------
    op.execute(_GRADED_LEDGER_ORIGINAL_BODY)

    # --- narrow graded_produce_lot_ledger_entries back to the exact CMP-020(001D-era) shape --
    op.execute(
        "DROP INDEX IF EXISTS ux_graded_produce_lot_ledger_entries_packing_consumption"
    )
    op.drop_constraint(
        "ck_graded_produce_lot_ledger_entries_typed_source_shape", "graded_produce_lot_ledger_entries", type_="check"
    )
    op.drop_constraint(
        "ck_graded_produce_lot_ledger_entries_count_positive", "graded_produce_lot_ledger_entries", type_="check"
    )
    op.create_check_constraint(
        "ck_graded_produce_lot_ledger_entries_count_positive",
        "graded_produce_lot_ledger_entries",
        "whole_unit_count_delta IS NULL OR whole_unit_count_delta > 0",
    )
    op.drop_constraint(
        "ck_graded_produce_lot_ledger_entries_weight_envelope", "graded_produce_lot_ledger_entries", type_="check"
    )
    op.create_check_constraint(
        "ck_graded_produce_lot_ledger_entries_weight_envelope",
        "graded_produce_lot_ledger_entries",
        "weight_delta_kg > 0 AND weight_delta_kg = trunc(weight_delta_kg, 3) "
        "AND weight_delta_kg < 100000000000",
    )
    op.drop_constraint(
        "ck_graded_produce_lot_ledger_entries_kind_allowed", "graded_produce_lot_ledger_entries", type_="check"
    )
    op.create_check_constraint(
        "ck_graded_produce_lot_ledger_entries_kind_allowed",
        "graded_produce_lot_ledger_entries",
        "entry_kind IN ('grading_receipt')",
    )
    op.drop_constraint(
        "fk_graded_produce_lot_ledger_entries_tenant_farm_packing_event",
        "graded_produce_lot_ledger_entries", type_="foreignkey",
    )
    op.drop_column("graded_produce_lot_ledger_entries", "packing_event_id")
    op.alter_column(
        "graded_produce_lot_ledger_entries", "grading_event_id",
        existing_type=postgresql.UUID(as_uuid=True), nullable=False,
    )

    # --- restore produce_lot_ledger_entries to the exact CMP-015/001C (4-kind) shape --
    # Order matters (mirror image of the upgrade path): the widened
    # `ck_produce_lot_ledger_entries_typed_source_shape` condition
    # references `packing_event_id`, so the column must be restored BEFORE
    # that CHECK is recreated, never after.
    op.execute(_LEDGER_V2_CURRENT_BODY)
    op.add_column(
        "produce_lot_ledger_entries",
        sa.Column("packing_event_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.drop_constraint(
        "ck_produce_lot_ledger_entries_typed_source_shape", "produce_lot_ledger_entries", type_="check"
    )
    op.create_check_constraint(
        "ck_produce_lot_ledger_entries_typed_source_shape",
        "produce_lot_ledger_entries",
        "(entry_kind = 'harvest_receipt' AND harvest_event_id IS NOT NULL AND packing_event_id IS NULL "
        "AND harvest_source_line_correction_id IS NULL AND grading_event_id IS NULL) "
        "OR (entry_kind = 'packing_consumption' AND harvest_event_id IS NULL AND packing_event_id IS NOT NULL "
        "AND harvest_source_line_correction_id IS NULL AND grading_event_id IS NULL) "
        "OR (entry_kind = 'harvest_adjustment' AND harvest_event_id IS NULL AND packing_event_id IS NULL "
        "AND harvest_source_line_correction_id IS NOT NULL AND grading_event_id IS NULL) "
        "OR (entry_kind = 'grading_consumption' AND harvest_event_id IS NULL AND packing_event_id IS NULL "
        "AND harvest_source_line_correction_id IS NULL AND grading_event_id IS NOT NULL)",
    )
    op.drop_constraint("ck_produce_lot_ledger_entries_count_positive", "produce_lot_ledger_entries", type_="check")
    op.create_check_constraint(
        "ck_produce_lot_ledger_entries_count_positive",
        "produce_lot_ledger_entries",
        "(entry_kind = 'harvest_receipt' AND (whole_unit_count_delta IS NULL OR whole_unit_count_delta > 0)) "
        "OR (entry_kind = 'packing_consumption' AND (whole_unit_count_delta IS NULL OR whole_unit_count_delta < 0)) "
        "OR (entry_kind = 'harvest_adjustment' AND (whole_unit_count_delta IS NULL OR whole_unit_count_delta <> 0)) "
        "OR (entry_kind = 'grading_consumption' AND (whole_unit_count_delta IS NULL OR whole_unit_count_delta < 0))",
    )
    op.drop_constraint("ck_produce_lot_ledger_entries_weight_envelope", "produce_lot_ledger_entries", type_="check")
    op.create_check_constraint(
        "ck_produce_lot_ledger_entries_weight_envelope",
        "produce_lot_ledger_entries",
        "(entry_kind = 'harvest_receipt' AND weight_delta_kg > 0 "
        "AND weight_delta_kg = trunc(weight_delta_kg, 3) AND weight_delta_kg < 100000000000) "
        "OR (entry_kind = 'packing_consumption' AND weight_delta_kg < 0 "
        "AND weight_delta_kg = trunc(weight_delta_kg, 3) AND weight_delta_kg > -100000000000) "
        "OR (entry_kind = 'harvest_adjustment' "
        "AND weight_delta_kg = trunc(weight_delta_kg, 3) "
        "AND weight_delta_kg > -100000000000 AND weight_delta_kg < 100000000000) "
        "OR (entry_kind = 'grading_consumption' AND weight_delta_kg < 0 "
        "AND weight_delta_kg = trunc(weight_delta_kg, 3) AND weight_delta_kg > -100000000000)",
    )
    op.drop_constraint("ck_produce_lot_ledger_entries_kind_allowed", "produce_lot_ledger_entries", type_="check")
    op.create_check_constraint(
        "ck_produce_lot_ledger_entries_kind_allowed",
        "produce_lot_ledger_entries",
        "entry_kind IN ('harvest_receipt', 'packing_consumption', 'harvest_adjustment', 'grading_consumption')",
    )
    op.create_foreign_key(
        "fk_produce_lot_ledger_entries_tenant_farm_packing_event", "produce_lot_ledger_entries", "packing_events",
        ["tenant_id", "farm_id", "packing_event_id"], ["tenant_id", "farm_id", "id"],
    )
    op.create_index(
        "ux_produce_lot_ledger_entries_event_lot_packing_consumption", "produce_lot_ledger_entries",
        ["packing_event_id", "produce_lot_id"], unique=True,
        postgresql_where=sa.text("entry_kind = 'packing_consumption'"),
    )
