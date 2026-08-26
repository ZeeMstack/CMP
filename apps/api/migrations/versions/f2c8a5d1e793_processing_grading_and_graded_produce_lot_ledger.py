"""processing/grading and graded produce lot ledger

Revision ID: f2c8a5d1e793
Revises: e8d5f3a2b6c1
Create Date: 2026-08-26 00:00:00.000000

POSTHARVEST-OPS-001C: the first real post-harvest transformation between
`HarvestedProduceLot` and (future) Packing —
HarvestedProduceLot -> GradingEvent -> 0..N GradedProduceLot -> its own
ledger. Adds three new, additive tables (`grading_events`,
`graded_produce_lots`, `graded_produce_lot_ledger_entries`) and widens
`produce_lot_ledger_entries` with a fourth `entry_kind`,
`grading_consumption`, using the exact `CREATE OR REPLACE FUNCTION`
in-place-widening idiom HARVEST-OPS-001 already established when it added
`harvest_adjustment` to the same function
(`enforce_produce_lot_ledger_entry_insert_integrity_v2`) — the trigger
ATTACHMENT (created once at CMP-015) is never re-created, only the
function body it points to. No historical migration is edited.

Current direct Harvest -> Packing continues to work completely unchanged;
`packing_consumption` behavior is untouched. POSTHARVEST-OPS-001E will
perform the breaking Packing-to-GradedProduceLot conversion.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "f2c8a5d1e793"
down_revision: Union[str, None] = "e8d5f3a2b6c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# =====================================================================
# The exact CURRENT (HARVEST-OPS-001) body of
# enforce_produce_lot_ledger_entry_insert_integrity_v2 — reproduced
# byte-for-byte so downgrade can restore it exactly via CREATE OR REPLACE.
# Never edit this string to "improve" it; it must remain an exact copy of
# what b8f3c6d1e947 left behind.
# =====================================================================
_LEDGER_INTEGRITY_V2_PRIOR_BODY = """
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

        ELSE
            RAISE EXCEPTION 'unknown ledger entry kind %', NEW.entry_kind;
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """


# =====================================================================
# The same function, widened in place with a fourth branch,
# grading_consumption -- mirrors the packing_consumption branch's own
# lock-then-balance shape exactly, generalized to reference
# grading_events instead of packing_events/packing_input_lines (a
# GradingEvent owns its debit directly; there is no per-line child table).
# =====================================================================
_GRADING_CONSUMPTION_BRANCH = """
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

    """


def _widened_ledger_integrity_v2_body() -> str:
    """Splices the new grading_consumption branch into the exact prior
    body, immediately before the final `ELSE RAISE EXCEPTION 'unknown
    ledger entry kind'` catch-all, and adds the two new DECLARE variables
    the branch needs. The prior body's own harvest_receipt/
    packing_consumption/harvest_adjustment branches are byte-for-byte
    untouched."""
    body = _LEDGER_INTEGRITY_V2_PRIOR_BODY
    body = body.replace(
        "        v_expected_count_delta BIGINT;\n    BEGIN",
        "        v_expected_count_delta BIGINT;\n"
        "        v_grading_event RECORD;\n"
        "        v_expected_weight_delta NUMERIC;\n"
        "    BEGIN",
    )
    body = body.replace(
        "        ELSE\n            RAISE EXCEPTION 'unknown ledger entry kind %', NEW.entry_kind;\n        END IF;",
        _GRADING_CONSUMPTION_BRANCH
        + "        ELSE\n            RAISE EXCEPTION 'unknown ledger entry kind %', NEW.entry_kind;\n        END IF;",
    )
    return body


def upgrade() -> None:
    # --- grading_events -------------------------------------------------------------
    op.create_table(
        "grading_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column(
            "source_harvested_produce_lot_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("harvested_produce_lots.id"), nullable=False,
        ),
        sa.Column(
            "processing_hall_location_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("locations.id"),
            nullable=False,
        ),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("input_presented_weight_kg", sa.Numeric(), nullable=False),
        sa.Column("input_presented_whole_unit_count", sa.BigInteger(), nullable=True),
        sa.Column("rejected_weight_kg", sa.Numeric(), nullable=False),
        sa.Column("rejected_whole_unit_count", sa.BigInteger(), nullable=True),
        sa.Column("loss_weight_kg", sa.Numeric(), nullable=False),
        sa.Column("loss_whole_unit_count", sa.BigInteger(), nullable=True),
        sa.Column("sample_weight_kg", sa.Numeric(), nullable=False),
        sa.Column("sample_whole_unit_count", sa.BigInteger(), nullable=True),
        sa.Column("remainder_weight_kg", sa.Numeric(), nullable=False),
        sa.Column("remainder_whole_unit_count", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            "input_presented_weight_kg > 0 AND input_presented_weight_kg = trunc(input_presented_weight_kg, 3) "
            "AND input_presented_weight_kg < 100000000000",
            name="ck_grading_events_input_presented_envelope",
        ),
        sa.CheckConstraint(
            "rejected_weight_kg >= 0 AND rejected_weight_kg = trunc(rejected_weight_kg, 3) "
            "AND rejected_weight_kg < 100000000000",
            name="ck_grading_events_rejected_envelope",
        ),
        sa.CheckConstraint(
            "loss_weight_kg >= 0 AND loss_weight_kg = trunc(loss_weight_kg, 3) AND loss_weight_kg < 100000000000",
            name="ck_grading_events_loss_envelope",
        ),
        sa.CheckConstraint(
            "sample_weight_kg >= 0 AND sample_weight_kg = trunc(sample_weight_kg, 3) "
            "AND sample_weight_kg < 100000000000",
            name="ck_grading_events_sample_envelope",
        ),
        sa.CheckConstraint(
            "remainder_weight_kg >= 0 AND remainder_weight_kg = trunc(remainder_weight_kg, 3) "
            "AND remainder_weight_kg < 100000000000",
            name="ck_grading_events_remainder_envelope",
        ),
        sa.CheckConstraint(
            "remainder_weight_kg < input_presented_weight_kg",
            name="ck_grading_events_remainder_less_than_presented",
        ),
        sa.CheckConstraint(
            "rejected_weight_kg + loss_weight_kg + sample_weight_kg + remainder_weight_kg "
            "<= input_presented_weight_kg",
            name="ck_grading_events_weight_bounds",
        ),
        sa.CheckConstraint(
            "(input_presented_whole_unit_count IS NULL AND rejected_whole_unit_count IS NULL "
            " AND loss_whole_unit_count IS NULL AND sample_whole_unit_count IS NULL "
            " AND remainder_whole_unit_count IS NULL) "
            "OR (input_presented_whole_unit_count IS NOT NULL AND rejected_whole_unit_count IS NOT NULL "
            " AND loss_whole_unit_count IS NOT NULL AND sample_whole_unit_count IS NOT NULL "
            " AND remainder_whole_unit_count IS NOT NULL "
            " AND input_presented_whole_unit_count > 0 AND rejected_whole_unit_count >= 0 "
            " AND loss_whole_unit_count >= 0 AND sample_whole_unit_count >= 0 "
            " AND remainder_whole_unit_count >= 0 "
            " AND remainder_whole_unit_count < input_presented_whole_unit_count "
            " AND rejected_whole_unit_count + loss_whole_unit_count + sample_whole_unit_count "
            "     + remainder_whole_unit_count <= input_presented_whole_unit_count)",
            name="ck_grading_events_count_mode_shape",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_grading_events_tenant_id"),
        sa.UniqueConstraint("tenant_id", "farm_id", "id", name="uq_grading_events_tenant_farm_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "source_harvested_produce_lot_id"],
            [
                "harvested_produce_lots.tenant_id", "harvested_produce_lots.farm_id",
                "harvested_produce_lots.id",
            ],
            name="fk_grading_events_tenant_farm_lot",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "processing_hall_location_id"],
            ["locations.tenant_id", "locations.farm_id", "locations.id"],
            name="fk_grading_events_tenant_farm_hall",
        ),
    )
    op.create_index(
        "ux_grading_events_tenant_client_command_id", "grading_events", ["tenant_id", "client_command_id"],
        unique=True,
    )
    op.create_index(
        "ix_grading_events_tenant_farm_source_lot", "grading_events",
        ["tenant_id", "farm_id", "source_harvested_produce_lot_id"],
    )

    # --- graded_produce_lots ---------------------------------------------------------
    op.create_table(
        "graded_produce_lots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column(
            "grading_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("grading_events.id"), nullable=False
        ),
        sa.Column("crop_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("crops.id"), nullable=False),
        sa.Column("variety_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("varieties.id"), nullable=True),
        sa.Column(
            "grade_definition_version_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("grade_definition_versions.id"), nullable=False,
        ),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("original_received_weight_kg", sa.Numeric(), nullable=False),
        sa.Column("original_received_whole_unit_count", sa.BigInteger(), nullable=True),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "original_received_weight_kg > 0 AND original_received_weight_kg = trunc(original_received_weight_kg, 3) "
            "AND original_received_weight_kg < 100000000000",
            name="ck_graded_produce_lots_weight_envelope",
        ),
        sa.CheckConstraint(
            "original_received_whole_unit_count IS NULL OR original_received_whole_unit_count > 0",
            name="ck_graded_produce_lots_count_positive",
        ),
        sa.UniqueConstraint(
            "grading_event_id", "grade_definition_version_id", name="uq_graded_produce_lots_event_grade_version"
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_graded_produce_lots_tenant_id"),
        sa.UniqueConstraint("tenant_id", "farm_id", "id", name="uq_graded_produce_lots_tenant_farm_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "grading_event_id"],
            ["grading_events.tenant_id", "grading_events.farm_id", "grading_events.id"],
            name="fk_graded_produce_lots_tenant_farm_event",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "crop_id"], ["crops.tenant_id", "crops.id"], name="fk_graded_produce_lots_tenant_crop"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "crop_id", "variety_id"],
            ["varieties.tenant_id", "varieties.crop_id", "varieties.id"],
            name="fk_graded_produce_lots_tenant_crop_variety",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "grade_definition_version_id"],
            ["grade_definition_versions.tenant_id", "grade_definition_versions.id"],
            name="fk_graded_produce_lots_tenant_grade_version",
        ),
    )
    op.create_index(
        "ux_graded_produce_lots_tenant_code_lower", "graded_produce_lots", ["tenant_id", sa.text("lower(code)")],
        unique=True,
    )

    # --- graded_produce_lot_ledger_entries --------------------------------------------
    op.create_table(
        "graded_produce_lot_ledger_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column(
            "graded_produce_lot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("graded_produce_lots.id"),
            nullable=False,
        ),
        sa.Column(
            "grading_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("grading_events.id"), nullable=False
        ),
        sa.Column("entry_kind", sa.String(), nullable=False),
        sa.Column("weight_delta_kg", sa.Numeric(), nullable=False),
        sa.Column("whole_unit_count_delta", sa.BigInteger(), nullable=True),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.CheckConstraint(
            "entry_kind IN ('grading_receipt')", name="ck_graded_produce_lot_ledger_entries_kind_allowed"
        ),
        sa.CheckConstraint(
            "weight_delta_kg > 0 AND weight_delta_kg = trunc(weight_delta_kg, 3) "
            "AND weight_delta_kg < 100000000000",
            name="ck_graded_produce_lot_ledger_entries_weight_envelope",
        ),
        sa.CheckConstraint(
            "whole_unit_count_delta IS NULL OR whole_unit_count_delta > 0",
            name="ck_graded_produce_lot_ledger_entries_count_positive",
        ),
        sa.CheckConstraint(
            "entry_kind <> 'grading_receipt' OR note IS NULL",
            name="ck_graded_produce_lot_ledger_entries_receipt_note_null",
        ),
        sa.UniqueConstraint(
            "tenant_id", "farm_id", "id", name="uq_graded_produce_lot_ledger_entries_tenant_farm_id"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "graded_produce_lot_id"],
            ["graded_produce_lots.tenant_id", "graded_produce_lots.farm_id", "graded_produce_lots.id"],
            name="fk_graded_produce_lot_ledger_entries_tenant_farm_lot",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "grading_event_id"],
            ["grading_events.tenant_id", "grading_events.farm_id", "grading_events.id"],
            name="fk_graded_produce_lot_ledger_entries_tenant_farm_event",
        ),
    )
    op.create_index(
        "ux_graded_produce_lot_ledger_entries_lot_receipt", "graded_produce_lot_ledger_entries",
        ["graded_produce_lot_id"], unique=True, postgresql_where=sa.text("entry_kind = 'grading_receipt'"),
    )

    # --- append-only guards (reused generic functions, never redefined) --------------
    for table in ("grading_events", "graded_produce_lots", "graded_produce_lot_ledger_entries"):
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

    # --- grading_events: mandatory active packing_hall check, Quality Hold/
    # Recall containment, and source-availability integrity ---------------------------
    # A plain FK proves tenant/farm/location existence; it cannot prove the
    # location's TYPE or current status, since Location stores
    # location_type_id, not a code, and status is mutable. Mirrors the
    # established location-classification-integrity idiom.
    #
    # PRE-COMMIT CORRECTION (POSTHARVEST-OPS-001C verification pass): the
    # service already enforces Quality Hold / Recall containment and
    # presented-vs-available-balance BEFORE ever reaching this INSERT, but
    # none of that was independently DB-enforced -- direct SQL could bypass
    # all three. This widens the function (the migration is still
    # uncommitted local work, not a historical revision) to make each an
    # unconditional DB-level guarantee, mirroring
    # enforce_packing_input_line_insert_integrity's own self-contained
    # quality-hold-lock style one level up (Packing itself does not yet
    # DB-enforce recall containment -- this is a new, not merely copied,
    # pattern for that half). Lock order is CropBatch, then
    # HarvestedProduceLot -- the same global convention the service
    # already follows, never inverted; re-acquiring a lock the calling
    # transaction already holds (the normal path, via the service) is a
    # safe no-op in Postgres, so this adds no extra deadlock risk on top
    # of the service's own locking.
    op.execute(
        """
        CREATE FUNCTION enforce_grading_event_insert_integrity() RETURNS trigger AS $$
        DECLARE
            v_hall_type_code TEXT;
            v_hall_status TEXT;
            v_batch_id UUID;
            v_open_hold BOOLEAN;
            v_open_batch_recall BOOLEAN;
            v_open_lot_recall BOOLEAN;
            v_available_weight NUMERIC;
            v_available_count BIGINT;
        BEGIN
            SELECT lt.code, l.status INTO v_hall_type_code, v_hall_status
            FROM locations l JOIN location_types lt ON lt.id = l.location_type_id
            WHERE l.id = NEW.processing_hall_location_id;
            IF v_hall_type_code IS NULL THEN
                RAISE EXCEPTION 'processing hall location not found';
            END IF;
            IF v_hall_type_code <> 'packing_hall' THEN
                RAISE EXCEPTION 'processing_hall_location_id % is not a packing_hall location', NEW.processing_hall_location_id;
            END IF;
            IF v_hall_status <> 'active' THEN
                RAISE EXCEPTION 'processing_hall_location_id % is not active', NEW.processing_hall_location_id;
            END IF;

            SELECT batch_id INTO v_batch_id FROM harvested_produce_lots WHERE id = NEW.source_harvested_produce_lot_id;
            IF v_batch_id IS NULL THEN
                RAISE EXCEPTION 'source harvested produce lot % not found for grading event', NEW.source_harvested_produce_lot_id;
            END IF;

            PERFORM 1 FROM crop_batches WHERE id = v_batch_id FOR UPDATE;

            SELECT EXISTS (
                SELECT 1 FROM quality_holds h
                WHERE h.batch_id = v_batch_id
                  AND NOT EXISTS (SELECT 1 FROM quality_hold_releases r WHERE r.quality_hold_id = h.id)
            ) INTO v_open_hold;
            IF v_open_hold THEN
                RAISE EXCEPTION 'source produce lot % batch has an open quality hold', NEW.source_harvested_produce_lot_id;
            END IF;

            SELECT EXISTS (
                SELECT 1 FROM recall_scope_batches rsb
                WHERE rsb.crop_batch_id = v_batch_id
                  AND NOT EXISTS (SELECT 1 FROM recall_case_closures rcc WHERE rcc.recall_case_id = rsb.recall_case_id)
            ) INTO v_open_batch_recall;
            IF v_open_batch_recall THEN
                RAISE EXCEPTION 'source produce lot % batch has an open recall', NEW.source_harvested_produce_lot_id;
            END IF;

            PERFORM 1 FROM harvested_produce_lots WHERE id = NEW.source_harvested_produce_lot_id FOR UPDATE;

            SELECT EXISTS (
                SELECT 1 FROM recall_scope_produce_lots rspl
                WHERE rspl.harvested_produce_lot_id = NEW.source_harvested_produce_lot_id
                  AND NOT EXISTS (SELECT 1 FROM recall_case_closures rcc WHERE rcc.recall_case_id = rspl.recall_case_id)
            ) INTO v_open_lot_recall;
            IF v_open_lot_recall THEN
                RAISE EXCEPTION 'source produce lot % has an open recall', NEW.source_harvested_produce_lot_id;
            END IF;

            SELECT COALESCE(sum(weight_delta_kg), 0), sum(whole_unit_count_delta)
            INTO v_available_weight, v_available_count
            FROM produce_lot_ledger_entries WHERE produce_lot_id = NEW.source_harvested_produce_lot_id;

            IF NEW.input_presented_weight_kg > v_available_weight THEN
                RAISE EXCEPTION 'input_presented_weight_kg % exceeds source produce lot % available balance %', NEW.input_presented_weight_kg, NEW.source_harvested_produce_lot_id, v_available_weight;
            END IF;
            IF NEW.input_presented_whole_unit_count IS NOT NULL THEN
                IF v_available_count IS NULL OR NEW.input_presented_whole_unit_count > v_available_count THEN
                    RAISE EXCEPTION 'input_presented_whole_unit_count % exceeds source produce lot % available count', NEW.input_presented_whole_unit_count, NEW.source_harvested_produce_lot_id;
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER grading_events_enforce_insert_integrity
        BEFORE INSERT ON grading_events
        FOR EACH ROW EXECUTE FUNCTION enforce_grading_event_insert_integrity();
        """
    )

    # --- graded_produce_lots: crop/variety snapshot + grade compatibility ------------
    op.execute(
        """
        CREATE FUNCTION enforce_graded_produce_lot_insert_integrity() RETURNS trigger AS $$
        DECLARE
            v_event RECORD;
            v_lot_crop_id UUID;
            v_lot_variety_id UUID;
            v_lot_tracks_count BOOLEAN;
            v_grade_version RECORD;
            v_grade_def RECORD;
        BEGIN
            SELECT tenant_id, farm_id, source_harvested_produce_lot_id, effective_time
            INTO v_event
            FROM grading_events WHERE id = NEW.grading_event_id;
            IF v_event.tenant_id IS NULL THEN
                RAISE EXCEPTION 'grading event not found for graded produce lot';
            END IF;
            IF v_event.tenant_id <> NEW.tenant_id OR v_event.farm_id <> NEW.farm_id THEN
                RAISE EXCEPTION 'graded produce lot tenant/farm does not match its grading event''s own';
            END IF;
            IF NEW.effective_time <> v_event.effective_time THEN
                RAISE EXCEPTION 'graded produce lot effective_time must match its grading event''s own';
            END IF;

            SELECT crop_id, variety_id, total_whole_unit_count IS NOT NULL
            INTO v_lot_crop_id, v_lot_variety_id, v_lot_tracks_count
            FROM harvested_produce_lots WHERE id = v_event.source_harvested_produce_lot_id;

            IF NEW.crop_id <> v_lot_crop_id THEN
                RAISE EXCEPTION 'graded produce lot crop must match the source harvested produce lot''s crop';
            END IF;
            IF NEW.variety_id IS DISTINCT FROM v_lot_variety_id THEN
                RAISE EXCEPTION 'graded produce lot variety must match the source harvested produce lot''s variety';
            END IF;
            IF v_lot_tracks_count AND NEW.original_received_whole_unit_count IS NULL THEN
                RAISE EXCEPTION 'source produce lot tracks whole-unit count; graded output count is required';
            END IF;
            IF NOT v_lot_tracks_count AND NEW.original_received_whole_unit_count IS NOT NULL THEN
                RAISE EXCEPTION 'source produce lot does not track whole-unit count; graded output count must be null';
            END IF;

            SELECT status, effective_from, effective_until, grade_definition_id
            INTO v_grade_version
            FROM grade_definition_versions WHERE id = NEW.grade_definition_version_id;
            IF v_grade_version.grade_definition_id IS NULL THEN
                RAISE EXCEPTION 'grade definition version not found for graded produce lot';
            END IF;
            IF v_grade_version.status = 'draft' THEN
                RAISE EXCEPTION 'grade_definition_version % is draft and cannot be referenced', NEW.grade_definition_version_id;
            END IF;
            IF v_event.effective_time < v_grade_version.effective_from THEN
                RAISE EXCEPTION 'grade_definition_version % is not yet effective at the grading event''s effective_time', NEW.grade_definition_version_id;
            END IF;
            IF v_grade_version.effective_until IS NOT NULL AND v_event.effective_time >= v_grade_version.effective_until THEN
                RAISE EXCEPTION 'grade_definition_version % is no longer effective at the grading event''s effective_time', NEW.grade_definition_version_id;
            END IF;

            SELECT crop_id, variety_id INTO v_grade_def
            FROM grade_definitions WHERE id = v_grade_version.grade_definition_id;
            IF v_grade_def.crop_id <> v_lot_crop_id THEN
                RAISE EXCEPTION 'grade_definition_version % crop does not match the source produce lot''s crop', NEW.grade_definition_version_id;
            END IF;
            IF v_grade_def.variety_id IS NOT NULL AND v_grade_def.variety_id <> v_lot_variety_id THEN
                RAISE EXCEPTION 'grade_definition_version % variety is incompatible with the source produce lot''s variety', NEW.grade_definition_version_id;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER graded_produce_lots_enforce_insert_integrity
        BEFORE INSERT ON graded_produce_lots
        FOR EACH ROW EXECUTE FUNCTION enforce_graded_produce_lot_insert_integrity();
        """
    )

    # --- graded_produce_lot_ledger_entries: immediate insert-integrity ---------------
    # Mirrors CMP-014's own enforce_produce_lot_ledger_entry_insert_integrity
    # exactly, one level down the chain (single entry_kind, deterministic
    # id = lot id).
    op.execute(
        """
        CREATE FUNCTION enforce_graded_produce_lot_ledger_entry_insert_integrity() RETURNS trigger AS $$
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
    )
    op.execute(
        """
        CREATE TRIGGER graded_produce_lot_ledger_entries_enforce_insert_integrity
        BEFORE INSERT ON graded_produce_lot_ledger_entries
        FOR EACH ROW EXECUTE FUNCTION enforce_graded_produce_lot_ledger_entry_insert_integrity();
        """
    )

    # --- deferred reconciliation: graded ledger (mirrors CMP-014 exactly, one level down) ---
    op.execute(
        """
        CREATE FUNCTION enforce_graded_produce_lot_ledger_reconciliation() RETURNS trigger AS $$
        DECLARE
            v_lot_id UUID;
            v_receipt_count INTEGER;
        BEGIN
            IF TG_TABLE_NAME = 'graded_produce_lots' THEN
                v_lot_id := NEW.id;
            ELSIF TG_TABLE_NAME = 'graded_produce_lot_ledger_entries' THEN
                v_lot_id := NEW.graded_produce_lot_id;
            END IF;

            IF v_lot_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT count(*) INTO v_receipt_count
            FROM graded_produce_lot_ledger_entries
            WHERE graded_produce_lot_id = v_lot_id AND entry_kind = 'grading_receipt';
            IF v_receipt_count <> 1 THEN
                RAISE EXCEPTION 'graded produce lot % must have exactly one grading receipt', v_lot_id;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER graded_produce_lots_enforce_ledger_reconciliation
        AFTER INSERT ON graded_produce_lots
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_graded_produce_lot_ledger_reconciliation();
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER graded_produce_lot_ledger_entries_enforce_reconciliation
        AFTER INSERT ON graded_produce_lot_ledger_entries
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_graded_produce_lot_ledger_reconciliation();
        """
    )

    # --- deferred reconciliation: the full grading 5-way equation --------------------
    # input_presented = SUM(graded outputs) + rejected + loss + sample + remainder,
    # plus the count equivalent when count-mode, plus exactly-one-debit
    # existence. Attached on all three tables the equation spans, mirroring
    # CMP-015's own enforce_packing_reconciliation 4-attachment shape.
    op.execute(
        """
        CREATE FUNCTION enforce_grading_reconciliation() RETURNS trigger AS $$
        DECLARE
            v_event_id UUID;
            v_event RECORD;
            v_output_weight_total NUMERIC;
            v_output_count_total BIGINT;
            v_debit_count INTEGER;
        BEGIN
            IF TG_TABLE_NAME = 'grading_events' THEN
                v_event_id := NEW.id;
            ELSIF TG_TABLE_NAME = 'graded_produce_lots' THEN
                v_event_id := NEW.grading_event_id;
            ELSIF TG_TABLE_NAME = 'produce_lot_ledger_entries' THEN
                IF NEW.entry_kind <> 'grading_consumption' THEN
                    RETURN NEW;
                END IF;
                v_event_id := NEW.grading_event_id;
            END IF;

            IF v_event_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT * INTO v_event FROM grading_events WHERE id = v_event_id;
            IF v_event.id IS NULL THEN
                RAISE EXCEPTION 'grading event % not found during reconciliation', v_event_id;
            END IF;

            SELECT COALESCE(sum(original_received_weight_kg), 0), SUM(original_received_whole_unit_count)
            INTO v_output_weight_total, v_output_count_total
            FROM graded_produce_lots WHERE grading_event_id = v_event_id;

            IF v_event.input_presented_weight_kg <>
               (v_output_weight_total + v_event.rejected_weight_kg + v_event.loss_weight_kg
                + v_event.sample_weight_kg + v_event.remainder_weight_kg)
            THEN
                RAISE EXCEPTION 'grading event % does not reconcile: input_presented_weight_kg must equal SUM(graded outputs) + rejected + loss + sample + remainder', v_event_id;
            END IF;

            IF v_event.input_presented_whole_unit_count IS NOT NULL THEN
                IF v_event.input_presented_whole_unit_count <>
                   (COALESCE(v_output_count_total, 0) + v_event.rejected_whole_unit_count
                    + v_event.loss_whole_unit_count + v_event.sample_whole_unit_count
                    + v_event.remainder_whole_unit_count)
                THEN
                    RAISE EXCEPTION 'grading event % does not reconcile: input_presented_whole_unit_count must equal SUM(graded output counts) + rejected + loss + sample + remainder counts', v_event_id;
                END IF;
            END IF;

            SELECT count(*) INTO v_debit_count
            FROM produce_lot_ledger_entries
            WHERE grading_event_id = v_event_id AND entry_kind = 'grading_consumption';
            IF v_debit_count <> 1 THEN
                RAISE EXCEPTION 'grading event % must have exactly one grading_consumption ledger debit', v_event_id;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER grading_events_enforce_reconciliation
        AFTER INSERT ON grading_events
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_grading_reconciliation();
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER graded_produce_lots_enforce_grading_reconciliation
        AFTER INSERT ON graded_produce_lots
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_grading_reconciliation();
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER produce_lot_ledger_entries_enforce_grading_reconciliation
        AFTER INSERT ON produce_lot_ledger_entries
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_grading_reconciliation();
        """
    )

    # --- produce_lot_ledger_entries: grading_consumption widening --------------------
    op.add_column(
        "produce_lot_ledger_entries",
        sa.Column(
            "grading_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("grading_events.id"), nullable=True
        ),
    )
    op.drop_constraint("ck_produce_lot_ledger_entries_kind_allowed", "produce_lot_ledger_entries", type_="check")
    op.create_check_constraint(
        "ck_produce_lot_ledger_entries_kind_allowed", "produce_lot_ledger_entries",
        "entry_kind IN ('harvest_receipt', 'packing_consumption', 'harvest_adjustment', 'grading_consumption')",
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
        "AND weight_delta_kg > -100000000000 AND weight_delta_kg < 100000000000) "
        "OR (entry_kind = 'grading_consumption' AND weight_delta_kg < 0 "
        "AND weight_delta_kg = trunc(weight_delta_kg, 3) AND weight_delta_kg > -100000000000)",
    )
    op.drop_constraint("ck_produce_lot_ledger_entries_count_positive", "produce_lot_ledger_entries", type_="check")
    op.create_check_constraint(
        "ck_produce_lot_ledger_entries_count_positive", "produce_lot_ledger_entries",
        "(entry_kind = 'harvest_receipt' AND (whole_unit_count_delta IS NULL OR whole_unit_count_delta > 0)) "
        "OR (entry_kind = 'packing_consumption' AND (whole_unit_count_delta IS NULL OR whole_unit_count_delta < 0)) "
        "OR (entry_kind = 'harvest_adjustment' AND (whole_unit_count_delta IS NULL OR whole_unit_count_delta <> 0)) "
        "OR (entry_kind = 'grading_consumption' AND (whole_unit_count_delta IS NULL OR whole_unit_count_delta < 0))",
    )
    op.drop_constraint(
        "ck_produce_lot_ledger_entries_typed_source_shape", "produce_lot_ledger_entries", type_="check"
    )
    op.create_check_constraint(
        "ck_produce_lot_ledger_entries_typed_source_shape", "produce_lot_ledger_entries",
        "(entry_kind = 'harvest_receipt' AND harvest_event_id IS NOT NULL AND packing_event_id IS NULL "
        "AND harvest_source_line_correction_id IS NULL AND grading_event_id IS NULL) "
        "OR (entry_kind = 'packing_consumption' AND harvest_event_id IS NULL AND packing_event_id IS NOT NULL "
        "AND harvest_source_line_correction_id IS NULL AND grading_event_id IS NULL) "
        "OR (entry_kind = 'harvest_adjustment' AND harvest_event_id IS NULL AND packing_event_id IS NULL "
        "AND harvest_source_line_correction_id IS NOT NULL AND grading_event_id IS NULL) "
        "OR (entry_kind = 'grading_consumption' AND harvest_event_id IS NULL AND packing_event_id IS NULL "
        "AND harvest_source_line_correction_id IS NULL AND grading_event_id IS NOT NULL)",
    )
    op.create_index(
        "ux_produce_lot_ledger_entries_event_grading_consumption", "produce_lot_ledger_entries",
        ["grading_event_id"], unique=True, postgresql_where=sa.text("entry_kind = 'grading_consumption'"),
    )
    op.create_foreign_key(
        "fk_produce_lot_ledger_entries_tenant_farm_grading_event", "produce_lot_ledger_entries", "grading_events",
        ["tenant_id", "farm_id", "grading_event_id"], ["tenant_id", "farm_id", "id"],
    )

    # Widen the insert-integrity function IN PLACE via CREATE OR REPLACE —
    # never versioned to _v3. The trigger attachment
    # (produce_lot_ledger_entries_enforce_insert_integrity_v2), created
    # once at CMP-015, is completely untouched.
    op.execute(_widened_ledger_integrity_v2_body())


def downgrade() -> None:
    bind = op.get_bind()

    # --- downgrade guard: 001C operational history is not discardable ---------------
    grading_event_count = bind.execute(sa.text("SELECT count(*) FROM grading_events")).scalar_one()
    graded_lot_count = bind.execute(sa.text("SELECT count(*) FROM graded_produce_lots")).scalar_one()
    graded_ledger_count = bind.execute(
        sa.text("SELECT count(*) FROM graded_produce_lot_ledger_entries")
    ).scalar_one()
    grading_consumption_count = bind.execute(
        sa.text("SELECT count(*) FROM produce_lot_ledger_entries WHERE entry_kind = 'grading_consumption'")
    ).scalar_one()
    if grading_event_count or graded_lot_count or graded_ledger_count or grading_consumption_count:
        raise RuntimeError(
            "Cannot downgrade past POSTHARVEST-OPS-001C: persisted GradingEvent, GradedProduceLot, graded "
            "produce lot ledger, or grading_consumption history exists. Downgrading would silently discard "
            "commercial processing/grading history and misrepresent the produce-lot ledger. Remove or migrate "
            "the offending data out-of-band first, or do not downgrade."
        )

    # --- restore produce_lot_ledger_entries to the exact prior (HARVEST-OPS-001) shape ---
    op.execute(_LEDGER_INTEGRITY_V2_PRIOR_BODY)

    op.drop_constraint(
        "fk_produce_lot_ledger_entries_tenant_farm_grading_event", "produce_lot_ledger_entries", type_="foreignkey"
    )
    op.drop_index("ux_produce_lot_ledger_entries_event_grading_consumption", table_name="produce_lot_ledger_entries")

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
    op.drop_constraint("ck_produce_lot_ledger_entries_count_positive", "produce_lot_ledger_entries", type_="check")
    op.create_check_constraint(
        "ck_produce_lot_ledger_entries_count_positive", "produce_lot_ledger_entries",
        "(entry_kind = 'harvest_receipt' AND (whole_unit_count_delta IS NULL OR whole_unit_count_delta > 0)) "
        "OR (entry_kind = 'packing_consumption' AND (whole_unit_count_delta IS NULL OR whole_unit_count_delta < 0)) "
        "OR (entry_kind = 'harvest_adjustment' AND (whole_unit_count_delta IS NULL OR whole_unit_count_delta <> 0))",
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
    op.drop_constraint("ck_produce_lot_ledger_entries_kind_allowed", "produce_lot_ledger_entries", type_="check")
    op.create_check_constraint(
        "ck_produce_lot_ledger_entries_kind_allowed", "produce_lot_ledger_entries",
        "entry_kind IN ('harvest_receipt', 'packing_consumption', 'harvest_adjustment')",
    )
    op.drop_column("produce_lot_ledger_entries", "grading_event_id")

    # --- drop deferred reconciliation (grading 5-way + graded ledger) ---------------
    op.execute(
        "DROP TRIGGER IF EXISTS produce_lot_ledger_entries_enforce_grading_reconciliation "
        "ON produce_lot_ledger_entries"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS graded_produce_lots_enforce_grading_reconciliation ON graded_produce_lots"
    )
    op.execute("DROP TRIGGER IF EXISTS grading_events_enforce_reconciliation ON grading_events")
    op.execute("DROP FUNCTION IF EXISTS enforce_grading_reconciliation()")

    op.execute(
        "DROP TRIGGER IF EXISTS graded_produce_lot_ledger_entries_enforce_reconciliation "
        "ON graded_produce_lot_ledger_entries"
    )
    op.execute("DROP TRIGGER IF EXISTS graded_produce_lots_enforce_ledger_reconciliation ON graded_produce_lots")
    op.execute("DROP FUNCTION IF EXISTS enforce_graded_produce_lot_ledger_reconciliation()")

    # --- drop immediate insert-integrity triggers/functions --------------------------
    op.execute(
        "DROP TRIGGER IF EXISTS graded_produce_lot_ledger_entries_enforce_insert_integrity "
        "ON graded_produce_lot_ledger_entries"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_graded_produce_lot_ledger_entry_insert_integrity()")

    op.execute("DROP TRIGGER IF EXISTS graded_produce_lots_enforce_insert_integrity ON graded_produce_lots")
    op.execute("DROP FUNCTION IF EXISTS enforce_graded_produce_lot_insert_integrity()")

    op.execute("DROP TRIGGER IF EXISTS grading_events_enforce_insert_integrity ON grading_events")
    op.execute("DROP FUNCTION IF EXISTS enforce_grading_event_insert_integrity()")

    # --- drop append-only guards + tables ---------------------------------------------
    for table in ("graded_produce_lot_ledger_entries", "graded_produce_lots", "grading_events"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_delete ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_update ON {table}")

    op.drop_table("graded_produce_lot_ledger_entries")
    op.drop_table("graded_produce_lots")
    op.drop_table("grading_events")
