"""typed packing consumption and finished goods lot foundation

Revision ID: a91f4c7b2e58
Revises: de82132ef837
Create Date: 2026-08-05 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'a91f4c7b2e58'
down_revision: Union[str, None] = 'de82132ef837'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The exact CMP-014 CHECK bodies, reproduced verbatim so downgrade can
# restore them byte-for-byte under their original constraint names.
_CMP014_KIND_ALLOWED = "entry_kind IN ('harvest_receipt')"
_CMP014_WEIGHT_ENVELOPE = (
    "weight_delta_kg > 0 AND weight_delta_kg = trunc(weight_delta_kg, 3) AND weight_delta_kg < 100000000000"
)
_CMP014_COUNT_POSITIVE = "whole_unit_count_delta IS NULL OR whole_unit_count_delta > 0"


def upgrade() -> None:
    # --- strengthen harvested_produce_lots for composite-FK reference -----------
    # CMP-013/014 never added (tenant_id, farm_id, id) here; CMP-015 needs a
    # DB-enforced composite FK from packing_input_lines rather than
    # trigger-only consistency (contrast with produce_lot_ledger_entries'
    # own, still-single-column-only, produce_lot_id FK).
    op.create_unique_constraint(
        "uq_harvested_produce_lots_tenant_farm_id", "harvested_produce_lots", ["tenant_id", "farm_id", "id"]
    )

    # --- packing_events (immutable) ---------------------------------------------
    op.create_table(
        "packing_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("crop_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("crops.id"), nullable=False),
        sa.Column("variety_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("varieties.id"), nullable=True),
        sa.Column("total_input_weight_kg", sa.Numeric(), nullable=False),
        sa.Column("packed_output_weight_kg", sa.Numeric(), nullable=False),
        sa.Column("process_loss_weight_kg", sa.Numeric(), nullable=False),
        sa.Column("rejected_weight_kg", sa.Numeric(), nullable=False),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.CheckConstraint(
            "total_input_weight_kg > 0 AND total_input_weight_kg = trunc(total_input_weight_kg, 3) "
            "AND total_input_weight_kg < 100000000000",
            name="ck_packing_events_total_input_envelope",
        ),
        sa.CheckConstraint(
            "packed_output_weight_kg > 0 AND packed_output_weight_kg = trunc(packed_output_weight_kg, 3) "
            "AND packed_output_weight_kg < 100000000000",
            name="ck_packing_events_packed_output_positive",
        ),
        sa.CheckConstraint(
            "process_loss_weight_kg >= 0 AND process_loss_weight_kg = trunc(process_loss_weight_kg, 3) "
            "AND process_loss_weight_kg < 100000000000",
            name="ck_packing_events_process_loss_envelope",
        ),
        sa.CheckConstraint(
            "rejected_weight_kg >= 0 AND rejected_weight_kg = trunc(rejected_weight_kg, 3) "
            "AND rejected_weight_kg < 100000000000",
            name="ck_packing_events_rejected_envelope",
        ),
        sa.CheckConstraint(
            "total_input_weight_kg = packed_output_weight_kg + process_loss_weight_kg + rejected_weight_kg",
            name="ck_packing_events_reconciliation",
        ),
        sa.UniqueConstraint("tenant_id", "farm_id", "id", name="uq_packing_events_tenant_farm_id"),
    )
    op.create_index(
        "ux_packing_events_tenant_client_command_id", "packing_events", ["tenant_id", "client_command_id"],
        unique=True,
    )

    # --- packing_input_lines (immutable) ----------------------------------------
    op.create_table(
        "packing_input_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column(
            "packing_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("packing_events.id"), nullable=False
        ),
        sa.Column(
            "harvested_produce_lot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("harvested_produce_lots.id"),
            nullable=False,
        ),
        sa.Column("consumed_weight_kg", sa.Numeric(), nullable=False),
        sa.Column("consumed_whole_unit_count", sa.BigInteger(), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("recorded_time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "consumed_weight_kg > 0 AND consumed_weight_kg = trunc(consumed_weight_kg, 3) "
            "AND consumed_weight_kg < 100000000000",
            name="ck_packing_input_lines_weight_positive",
        ),
        sa.CheckConstraint(
            "consumed_whole_unit_count IS NULL OR consumed_whole_unit_count > 0",
            name="ck_packing_input_lines_count_positive",
        ),
        sa.UniqueConstraint(
            "packing_event_id", "harvested_produce_lot_id", name="ux_packing_input_lines_event_lot"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "packing_event_id"],
            ["packing_events.tenant_id", "packing_events.farm_id", "packing_events.id"],
            name="fk_packing_input_lines_tenant_farm_event",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "harvested_produce_lot_id"],
            ["harvested_produce_lots.tenant_id", "harvested_produce_lots.farm_id", "harvested_produce_lots.id"],
            name="fk_packing_input_lines_tenant_farm_lot",
        ),
    )

    # --- finished_goods_lots (immutable) ----------------------------------------
    op.create_table(
        "finished_goods_lots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column(
            "packing_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("packing_events.id"), nullable=False,
            unique=True,
        ),
        sa.Column("crop_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("crops.id"), nullable=False),
        sa.Column("variety_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("varieties.id"), nullable=True),
        sa.Column("net_packed_weight_kg", sa.Numeric(), nullable=False),
        sa.Column("package_count", sa.BigInteger(), nullable=False),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "net_packed_weight_kg > 0 AND net_packed_weight_kg = trunc(net_packed_weight_kg, 3) "
            "AND net_packed_weight_kg < 100000000000",
            name="ck_finished_goods_lots_weight_envelope",
        ),
        sa.CheckConstraint("package_count > 0", name="ck_finished_goods_lots_package_count_positive"),
        sa.UniqueConstraint("tenant_id", "farm_id", "id", name="uq_finished_goods_lots_tenant_farm_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "packing_event_id"],
            ["packing_events.tenant_id", "packing_events.farm_id", "packing_events.id"],
            name="fk_finished_goods_lots_tenant_farm_event",
        ),
    )
    op.create_index(
        "ux_finished_goods_lots_tenant_code_lower", "finished_goods_lots", ["tenant_id", sa.text("lower(code)")],
        unique=True,
    )

    # --- produce_lot_ledger_entries: widen for the packing_consumption kind ----
    op.add_column(
        "produce_lot_ledger_entries",
        sa.Column("packing_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("packing_events.id"), nullable=True),
    )
    op.alter_column("produce_lot_ledger_entries", "harvest_event_id", nullable=True)

    op.drop_constraint("ck_produce_lot_ledger_entries_kind_allowed", "produce_lot_ledger_entries", type_="check")
    op.create_check_constraint(
        "ck_produce_lot_ledger_entries_kind_allowed", "produce_lot_ledger_entries",
        "entry_kind IN ('harvest_receipt', 'packing_consumption')",
    )

    op.drop_constraint("ck_produce_lot_ledger_entries_weight_envelope", "produce_lot_ledger_entries", type_="check")
    op.create_check_constraint(
        "ck_produce_lot_ledger_entries_weight_envelope", "produce_lot_ledger_entries",
        "(entry_kind = 'harvest_receipt' AND weight_delta_kg > 0 "
        "AND weight_delta_kg = trunc(weight_delta_kg, 3) AND weight_delta_kg < 100000000000) "
        "OR (entry_kind = 'packing_consumption' AND weight_delta_kg < 0 "
        "AND weight_delta_kg = trunc(weight_delta_kg, 3) AND weight_delta_kg > -100000000000)",
    )

    op.drop_constraint("ck_produce_lot_ledger_entries_count_positive", "produce_lot_ledger_entries", type_="check")
    op.create_check_constraint(
        "ck_produce_lot_ledger_entries_count_positive", "produce_lot_ledger_entries",
        "(entry_kind = 'harvest_receipt' AND (whole_unit_count_delta IS NULL OR whole_unit_count_delta > 0)) "
        "OR (entry_kind = 'packing_consumption' AND (whole_unit_count_delta IS NULL OR whole_unit_count_delta < 0))",
    )

    op.create_check_constraint(
        "ck_produce_lot_ledger_entries_typed_source_shape", "produce_lot_ledger_entries",
        "(entry_kind = 'harvest_receipt' AND harvest_event_id IS NOT NULL AND packing_event_id IS NULL) "
        "OR (entry_kind = 'packing_consumption' AND harvest_event_id IS NULL AND packing_event_id IS NOT NULL)",
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

    # --- immediate insert-integrity triggers ------------------------------------
    op.execute(
        """
        CREATE FUNCTION enforce_packing_event_insert_integrity() RETURNS trigger AS $$
        BEGIN
            IF NEW.effective_time > clock_timestamp() THEN
                RAISE EXCEPTION 'packing event effective_time cannot be in the future';
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
        FOR EACH ROW EXECUTE FUNCTION enforce_packing_event_insert_integrity();
        """
    )
    op.execute(
        """
        CREATE TRIGGER packing_events_no_update
        BEFORE UPDATE ON packing_events
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER packing_events_no_delete
        BEFORE DELETE ON packing_events
        FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();
        """
    )

    op.execute(
        """
        CREATE FUNCTION enforce_packing_input_line_insert_integrity() RETURNS trigger AS $$
        DECLARE
            v_lot_tenant_id UUID;
            v_lot_farm_id UUID;
            v_lot_batch_id UUID;
            v_lot_crop_id UUID;
            v_lot_variety_id UUID;
            v_lot_effective_time TIMESTAMPTZ;
            v_lot_count BIGINT;
            v_event_tenant_id UUID;
            v_event_farm_id UUID;
            v_event_crop_id UUID;
            v_event_variety_id UUID;
            v_event_effective_time TIMESTAMPTZ;
            v_open_hold BOOLEAN;
            v_latest_ledger_effective_time TIMESTAMPTZ;
        BEGIN
            SELECT tenant_id, farm_id, batch_id, crop_id, variety_id, effective_time, total_whole_unit_count
            INTO v_lot_tenant_id, v_lot_farm_id, v_lot_batch_id, v_lot_crop_id, v_lot_variety_id,
                 v_lot_effective_time, v_lot_count
            FROM harvested_produce_lots WHERE id = NEW.harvested_produce_lot_id;
            IF v_lot_tenant_id IS NULL THEN
                RAISE EXCEPTION 'harvested produce lot not found for packing input line';
            END IF;
            IF v_lot_tenant_id <> NEW.tenant_id OR v_lot_farm_id <> NEW.farm_id THEN
                RAISE EXCEPTION 'packing input line tenant/farm does not match the source produce lot''s own';
            END IF;

            SELECT tenant_id, farm_id, crop_id, variety_id, effective_time
            INTO v_event_tenant_id, v_event_farm_id, v_event_crop_id, v_event_variety_id, v_event_effective_time
            FROM packing_events WHERE id = NEW.packing_event_id;
            IF v_event_tenant_id IS NULL THEN
                RAISE EXCEPTION 'packing event not found for packing input line';
            END IF;
            IF v_event_tenant_id <> NEW.tenant_id OR v_event_farm_id <> NEW.farm_id THEN
                RAISE EXCEPTION 'packing input line tenant/farm does not match its packing event''s own';
            END IF;
            IF v_event_crop_id <> v_lot_crop_id OR v_event_variety_id IS DISTINCT FROM v_lot_variety_id THEN
                RAISE EXCEPTION 'packing input line source lot crop/variety does not match the packing event''s own';
            END IF;
            IF v_event_effective_time < v_lot_effective_time THEN
                RAISE EXCEPTION 'packing event effective_time cannot precede the source produce lot''s own effective_time';
            END IF;

            -- Non-self-referential by construction: this is a BEFORE INSERT
            -- trigger on packing_input_lines, so the packing_consumption
            -- debit this same line will later produce does not exist in
            -- produce_lot_ledger_entries yet — only genuinely earlier
            -- entries (the opening receipt, and any prior packing debits)
            -- are ever visible to this query.
            SELECT max(effective_time) INTO v_latest_ledger_effective_time
            FROM produce_lot_ledger_entries WHERE produce_lot_id = NEW.harvested_produce_lot_id;
            IF v_latest_ledger_effective_time IS NOT NULL AND v_event_effective_time < v_latest_ledger_effective_time THEN
                RAISE EXCEPTION 'packing event effective_time cannot precede the latest existing ledger entry for source produce lot %', NEW.harvested_produce_lot_id;
            END IF;

            IF v_lot_count IS NULL THEN
                IF NEW.consumed_whole_unit_count IS NOT NULL THEN
                    RAISE EXCEPTION 'source produce lot does not track whole-unit count; packing input count must be null';
                END IF;
            ELSE
                IF NEW.consumed_whole_unit_count IS NULL THEN
                    RAISE EXCEPTION 'source produce lot tracks whole-unit count; packing input count is required';
                END IF;
            END IF;

            -- Lock the source crop batch and reject an open quality hold,
            -- mirroring quality_holds_enforce_insert_integrity's own
            -- self-contained style. Batch lifecycle state is deliberately
            -- not checked here: a harvested produce lot remains usable
            -- after its batch closes or is superseded, unless a hold blocks it.
            PERFORM 1 FROM crop_batches WHERE id = v_lot_batch_id FOR UPDATE;
            SELECT EXISTS (
                SELECT 1 FROM quality_holds h
                WHERE h.batch_id = v_lot_batch_id
                  AND NOT EXISTS (SELECT 1 FROM quality_hold_releases r WHERE r.quality_hold_id = h.id)
            ) INTO v_open_hold;
            IF v_open_hold THEN
                RAISE EXCEPTION 'source produce lot % batch has an open quality hold', NEW.harvested_produce_lot_id;
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
        FOR EACH ROW EXECUTE FUNCTION enforce_packing_input_line_insert_integrity();
        """
    )
    op.execute(
        """
        CREATE TRIGGER packing_input_lines_no_update
        BEFORE UPDATE ON packing_input_lines
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER packing_input_lines_no_delete
        BEFORE DELETE ON packing_input_lines
        FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();
        """
    )

    op.execute(
        """
        CREATE FUNCTION enforce_finished_goods_lot_insert_integrity() RETURNS trigger AS $$
        DECLARE
            v_event_crop_id UUID;
            v_event_variety_id UUID;
            v_event_packed_output_weight_kg NUMERIC;
            v_event_effective_time TIMESTAMPTZ;
        BEGIN
            SELECT crop_id, variety_id, packed_output_weight_kg, effective_time
            INTO v_event_crop_id, v_event_variety_id, v_event_packed_output_weight_kg, v_event_effective_time
            FROM packing_events WHERE id = NEW.packing_event_id;
            IF v_event_crop_id IS NULL THEN
                RAISE EXCEPTION 'packing event not found for finished-goods lot';
            END IF;
            IF NEW.crop_id <> v_event_crop_id OR NEW.variety_id IS DISTINCT FROM v_event_variety_id THEN
                RAISE EXCEPTION 'finished-goods lot crop/variety does not match its packing event''s own';
            END IF;
            IF NEW.net_packed_weight_kg <> v_event_packed_output_weight_kg THEN
                RAISE EXCEPTION 'finished-goods lot net packed weight does not match its packing event''s packed output weight';
            END IF;
            IF NEW.effective_time <> v_event_effective_time THEN
                RAISE EXCEPTION 'finished-goods lot effective_time does not match its packing event''s effective_time';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER finished_goods_lots_enforce_insert_integrity
        BEFORE INSERT ON finished_goods_lots
        FOR EACH ROW EXECUTE FUNCTION enforce_finished_goods_lot_insert_integrity();
        """
    )
    op.execute(
        """
        CREATE TRIGGER finished_goods_lots_no_update
        BEFORE UPDATE ON finished_goods_lots
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER finished_goods_lots_no_delete
        BEFORE DELETE ON finished_goods_lots
        FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();
        """
    )

    # --- produce_lot_ledger_entries: replace only the trigger attachment -------
    # CMP-014's own enforce_produce_lot_ledger_entry_insert_integrity()
    # function body is never modified — only its trigger *attachment* is
    # dropped and replaced with a v2 trigger backed by a new function that
    # validates both entry kinds. On downgrade, the v2 attachment/function
    # are dropped and the original attachment is recreated pointing back at
    # the still-untouched original function — no trigger-name-ordering
    # dependency, exactly one authoritative insert-integrity function live
    # at any time.
    op.execute(
        """
        DROP TRIGGER produce_lot_ledger_entries_enforce_insert_integrity ON produce_lot_ledger_entries
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_produce_lot_ledger_entry_insert_integrity_v2() RETURNS trigger AS $$
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

                -- Lock the source lot row — the serialization point for all
                -- current and future typed consumers — and compute its
                -- balance prior to this insert.
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
        """
    )
    op.execute(
        """
        CREATE TRIGGER produce_lot_ledger_entries_enforce_insert_integrity_v2
        BEFORE INSERT ON produce_lot_ledger_entries
        FOR EACH ROW EXECUTE FUNCTION enforce_produce_lot_ledger_entry_insert_integrity_v2();
        """
    )

    # --- deferred packing reconciliation -----------------------------------------
    op.execute(
        """
        CREATE FUNCTION enforce_packing_reconciliation() RETURNS trigger AS $$
        DECLARE
            v_event_id UUID;
            v_input_count INTEGER;
            v_output_count INTEGER;
            v_debit_count INTEGER;
            v_orphan_debit_count INTEGER;
            v_line_weight_sum NUMERIC;
            v_event RECORD;
        BEGIN
            IF TG_TABLE_NAME = 'packing_events' THEN
                v_event_id := NEW.id;
            ELSIF TG_TABLE_NAME IN ('packing_input_lines', 'finished_goods_lots') THEN
                v_event_id := NEW.packing_event_id;
            ELSIF TG_TABLE_NAME = 'produce_lot_ledger_entries' THEN
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
                SELECT count(DISTINCT harvested_produce_lot_id) FROM packing_input_lines
                WHERE packing_event_id = v_event_id
            ) <> v_input_count THEN
                RAISE EXCEPTION 'packing event % has a source lot referenced more than once', v_event_id;
            END IF;

            IF EXISTS (
                SELECT 1 FROM packing_input_lines pil
                JOIN harvested_produce_lots lot ON lot.id = pil.harvested_produce_lot_id
                WHERE pil.packing_event_id = v_event_id
                  AND (lot.crop_id <> v_event.crop_id OR lot.variety_id IS DISTINCT FROM v_event.variety_id)
            ) THEN
                RAISE EXCEPTION 'packing event % has an input produce lot with mismatched crop/variety', v_event_id;
            END IF;

            SELECT count(*) INTO v_output_count FROM finished_goods_lots WHERE packing_event_id = v_event_id;
            IF v_output_count <> 1 THEN
                RAISE EXCEPTION 'packing event % must have exactly one finished-goods lot', v_event_id;
            END IF;

            SELECT count(*) INTO v_debit_count FROM produce_lot_ledger_entries
            WHERE packing_event_id = v_event_id AND entry_kind = 'packing_consumption';
            IF v_debit_count <> v_input_count THEN
                RAISE EXCEPTION 'packing event % input-line count does not match ledger-debit count', v_event_id;
            END IF;

            IF EXISTS (
                SELECT 1 FROM packing_input_lines pil
                LEFT JOIN produce_lot_ledger_entries r
                  ON r.id = pil.id AND r.entry_kind = 'packing_consumption'
                WHERE pil.packing_event_id = v_event_id
                  AND (
                    r.id IS NULL
                    OR r.produce_lot_id IS DISTINCT FROM pil.harvested_produce_lot_id
                    OR r.packing_event_id IS DISTINCT FROM pil.packing_event_id
                    OR r.harvest_event_id IS NOT NULL
                    OR r.weight_delta_kg IS DISTINCT FROM (-pil.consumed_weight_kg)
                    OR r.whole_unit_count_delta IS DISTINCT FROM
                       (CASE WHEN pil.consumed_whole_unit_count IS NULL THEN NULL ELSE -pil.consumed_whole_unit_count END)
                    OR r.effective_time IS DISTINCT FROM v_event.effective_time
                    OR r.recorded_time IS DISTINCT FROM pil.recorded_time
                    OR r.actor_user_id IS DISTINCT FROM v_event.actor_user_id
                    OR r.note IS DISTINCT FROM pil.note
                  )
            ) THEN
                RAISE EXCEPTION 'packing event % has an input line without an exactly matching ledger debit', v_event_id;
            END IF;

            SELECT count(*) INTO v_orphan_debit_count
            FROM produce_lot_ledger_entries r
            WHERE r.packing_event_id = v_event_id AND r.entry_kind = 'packing_consumption'
              AND NOT EXISTS (SELECT 1 FROM packing_input_lines pil WHERE pil.id = r.id);
            IF v_orphan_debit_count > 0 THEN
                RAISE EXCEPTION 'packing event % has a ledger debit with no matching input line', v_event_id;
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


def downgrade() -> None:
    bind = op.get_bind()

    # --- downgrade guard: packing history is independent operational data ------
    # Every packing_events row (and its input lines, ledger debits, and
    # finished-goods lot, all created atomically with it) is genuinely new
    # information, not a reconstructible projection of CMP-013/014 data —
    # unlike CMP-014's own receipts. Downgrading past CMP-015 while any
    # exists would silently discard it.
    packing_event_count = bind.execute(sa.text("SELECT count(*) FROM packing_events")).scalar_one()
    packing_input_line_count = bind.execute(sa.text("SELECT count(*) FROM packing_input_lines")).scalar_one()
    finished_goods_lot_count = bind.execute(sa.text("SELECT count(*) FROM finished_goods_lots")).scalar_one()
    packing_consumption_count = bind.execute(
        sa.text("SELECT count(*) FROM produce_lot_ledger_entries WHERE entry_kind = 'packing_consumption'")
    ).scalar_one()
    if packing_event_count or packing_input_line_count or finished_goods_lot_count or packing_consumption_count:
        raise RuntimeError(
            "Cannot downgrade past CMP-015: packing history exists (packing events, input lines, "
            "finished-goods lots, or packing_consumption ledger debits). Downgrading would silently "
            "discard it. Remove or migrate the offending data out-of-band first, or do not downgrade."
        )

    # --- deferred packing reconciliation -----------------------------------------
    op.execute(
        "DROP TRIGGER IF EXISTS produce_lot_ledger_entries_enforce_packing_reconciliation "
        "ON produce_lot_ledger_entries"
    )
    op.execute("DROP TRIGGER IF EXISTS finished_goods_lots_enforce_reconciliation ON finished_goods_lots")
    op.execute("DROP TRIGGER IF EXISTS packing_input_lines_enforce_reconciliation ON packing_input_lines")
    op.execute("DROP TRIGGER IF EXISTS packing_events_enforce_reconciliation ON packing_events")
    op.execute("DROP FUNCTION IF EXISTS enforce_packing_reconciliation()")

    # --- restore the exact CMP-014 insert-integrity trigger attachment ---------
    op.execute(
        "DROP TRIGGER IF EXISTS produce_lot_ledger_entries_enforce_insert_integrity_v2 "
        "ON produce_lot_ledger_entries"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_produce_lot_ledger_entry_insert_integrity_v2()")
    op.execute(
        """
        CREATE TRIGGER produce_lot_ledger_entries_enforce_insert_integrity
        BEFORE INSERT ON produce_lot_ledger_entries
        FOR EACH ROW EXECUTE FUNCTION enforce_produce_lot_ledger_entry_insert_integrity();
        """
    )

    # --- restore produce_lot_ledger_entries to the exact CMP-014 shape ---------
    op.drop_constraint(
        "fk_produce_lot_ledger_entries_tenant_farm_packing_event", "produce_lot_ledger_entries", type_="foreignkey"
    )
    op.drop_index("ux_produce_lot_ledger_entries_event_lot_packing_consumption", table_name="produce_lot_ledger_entries")
    op.drop_constraint(
        "ck_produce_lot_ledger_entries_typed_source_shape", "produce_lot_ledger_entries", type_="check"
    )
    op.drop_column("produce_lot_ledger_entries", "packing_event_id")
    op.alter_column("produce_lot_ledger_entries", "harvest_event_id", nullable=False)

    op.drop_constraint("ck_produce_lot_ledger_entries_kind_allowed", "produce_lot_ledger_entries", type_="check")
    op.create_check_constraint(
        "ck_produce_lot_ledger_entries_kind_allowed", "produce_lot_ledger_entries", _CMP014_KIND_ALLOWED
    )
    op.drop_constraint("ck_produce_lot_ledger_entries_weight_envelope", "produce_lot_ledger_entries", type_="check")
    op.create_check_constraint(
        "ck_produce_lot_ledger_entries_weight_envelope", "produce_lot_ledger_entries", _CMP014_WEIGHT_ENVELOPE
    )
    op.drop_constraint("ck_produce_lot_ledger_entries_count_positive", "produce_lot_ledger_entries", type_="check")
    op.create_check_constraint(
        "ck_produce_lot_ledger_entries_count_positive", "produce_lot_ledger_entries", _CMP014_COUNT_POSITIVE
    )

    # --- finished_goods_lots ------------------------------------------------------
    op.execute("DROP TRIGGER IF EXISTS finished_goods_lots_no_delete ON finished_goods_lots")
    op.execute("DROP TRIGGER IF EXISTS finished_goods_lots_no_update ON finished_goods_lots")
    op.execute("DROP TRIGGER IF EXISTS finished_goods_lots_enforce_insert_integrity ON finished_goods_lots")
    op.execute("DROP FUNCTION IF EXISTS enforce_finished_goods_lot_insert_integrity()")
    op.drop_index("ux_finished_goods_lots_tenant_code_lower", table_name="finished_goods_lots")
    op.drop_table("finished_goods_lots")

    # --- packing_input_lines -------------------------------------------------------
    op.execute("DROP TRIGGER IF EXISTS packing_input_lines_no_delete ON packing_input_lines")
    op.execute("DROP TRIGGER IF EXISTS packing_input_lines_no_update ON packing_input_lines")
    op.execute("DROP TRIGGER IF EXISTS packing_input_lines_enforce_insert_integrity ON packing_input_lines")
    op.execute("DROP FUNCTION IF EXISTS enforce_packing_input_line_insert_integrity()")
    op.drop_table("packing_input_lines")

    # --- packing_events --------------------------------------------------------------
    op.execute("DROP TRIGGER IF EXISTS packing_events_no_delete ON packing_events")
    op.execute("DROP TRIGGER IF EXISTS packing_events_no_update ON packing_events")
    op.execute("DROP TRIGGER IF EXISTS packing_events_enforce_insert_integrity ON packing_events")
    op.execute("DROP FUNCTION IF EXISTS enforce_packing_event_insert_integrity()")
    op.drop_index("ux_packing_events_tenant_client_command_id", table_name="packing_events")
    op.drop_table("packing_events")

    # --- restore harvested_produce_lots to its exact CMP-013/014 shape ---------
    op.drop_constraint("uq_harvested_produce_lots_tenant_farm_id", "harvested_produce_lots", type_="unique")
