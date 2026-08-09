"""recall case containment foundation

Revision ID: 68215f964ca9
Revises: 677fcd22cb3c
Create Date: 2026-08-22 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '68215f964ca9'
down_revision: Union[str, None] = '677fcd22cb3c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # --- 1. validate the exact expected CMP-015/018 pre-state -------------------
    packing_v1_attached = bind.execute(
        sa.text(
            "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'packing_input_lines'::regclass "
            "AND tgname = 'packing_input_lines_enforce_insert_integrity' "
            "AND tgfoid = to_regproc('enforce_packing_input_line_insert_integrity')"
        )
    ).scalar_one()
    if packing_v1_attached != 1:
        raise RuntimeError(
            "CMP-020 cannot upgrade: the expected CMP-015 packing_input_lines insert-integrity "
            "trigger attachment was not found. Refusing to version an unexpected pre-state."
        )
    storage_v1_attached = bind.execute(
        sa.text(
            "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'finished_goods_storage_movements'::regclass "
            "AND tgname = 'finished_goods_storage_movements_enforce_insert_integrity' "
            "AND tgfoid = to_regproc('enforce_finished_goods_storage_movement_insert_integrity')"
        )
    ).scalar_one()
    if storage_v1_attached != 1:
        raise RuntimeError(
            "CMP-020 cannot upgrade: the expected CMP-018 finished_goods_storage_movements "
            "insert-integrity trigger attachment was not found. Refusing to version an unexpected "
            "pre-state."
        )
    ledger_v3_attached = bind.execute(
        sa.text(
            "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'finished_goods_ledger_entries'::regclass "
            "AND tgname = 'finished_goods_ledger_entries_enforce_insert_integrity' "
            "AND tgfoid = to_regproc('enforce_finished_goods_ledger_entry_insert_integrity_v3')"
        )
    ).scalar_one()
    if ledger_v3_attached != 1:
        raise RuntimeError(
            "CMP-020 cannot upgrade: the expected CMP-018 v3 finished_goods_ledger_entries "
            "insert-integrity trigger attachment was not found. Refusing to version an unexpected "
            "pre-state."
        )

    # --- 2. recall_cases -----------------------------------------------------------
    op.create_table(
        "recall_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("crop_batch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("harvested_produce_lot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("finished_goods_lot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reason_code", sa.String(), nullable=False),
        sa.Column("reason_text", sa.String(), nullable=False),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.CheckConstraint(
            "(CASE WHEN crop_batch_id IS NOT NULL THEN 1 ELSE 0 END) + "
            "(CASE WHEN harvested_produce_lot_id IS NOT NULL THEN 1 ELSE 0 END) + "
            "(CASE WHEN finished_goods_lot_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="ck_recall_cases_typed_source_shape",
        ),
        sa.UniqueConstraint("tenant_id", "farm_id", "id", name="uq_recall_cases_tenant_farm_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id"], ["farms.tenant_id", "farms.id"], name="fk_recall_cases_tenant_farm"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "crop_batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_recall_cases_tenant_farm_batch",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "harvested_produce_lot_id"],
            [
                "harvested_produce_lots.tenant_id",
                "harvested_produce_lots.farm_id",
                "harvested_produce_lots.id",
            ],
            name="fk_recall_cases_tenant_farm_produce_lot",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "finished_goods_lot_id"],
            ["finished_goods_lots.tenant_id", "finished_goods_lots.farm_id", "finished_goods_lots.id"],
            name="fk_recall_cases_tenant_farm_fg_lot",
        ),
    )
    op.create_index(
        "ux_recall_cases_tenant_client_command_id", "recall_cases", ["tenant_id", "client_command_id"], unique=True
    )
    op.create_index(
        "ux_recall_cases_farm_code_lower", "recall_cases", ["farm_id", sa.text("lower(code)")], unique=True
    )
    op.execute(
        "CREATE TRIGGER recall_cases_no_update BEFORE UPDATE ON recall_cases "
        "FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();"
    )
    op.execute(
        "CREATE TRIGGER recall_cases_no_delete BEFORE DELETE ON recall_cases "
        "FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();"
    )

    # --- 3. recall_case_closures -----------------------------------------------------
    op.create_table(
        "recall_case_closures",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("recall_case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("recall_cases.id"), nullable=False),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.Column("close_reason", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "recall_case_id"],
            ["recall_cases.tenant_id", "recall_cases.farm_id", "recall_cases.id"],
            name="fk_recall_case_closures_tenant_farm_case",
        ),
    )
    op.create_index(
        "ux_recall_case_closures_tenant_client_command_id", "recall_case_closures",
        ["tenant_id", "client_command_id"], unique=True,
    )
    op.create_index("ux_recall_case_closures_case", "recall_case_closures", ["recall_case_id"], unique=True)
    op.execute(
        "CREATE TRIGGER recall_case_closures_no_update BEFORE UPDATE ON recall_case_closures "
        "FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();"
    )
    op.execute(
        "CREATE TRIGGER recall_case_closures_no_delete BEFORE DELETE ON recall_case_closures "
        "FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();"
    )

    # --- 4. recall scope tables ------------------------------------------------------
    op.create_table(
        "recall_scope_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("recall_case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("recall_cases.id"), nullable=False),
        sa.Column("crop_batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("crop_batches.id"), nullable=False),
        sa.Column("recorded_time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("recall_case_id", "crop_batch_id", name="ux_recall_scope_batches_case_batch"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "recall_case_id"],
            ["recall_cases.tenant_id", "recall_cases.farm_id", "recall_cases.id"],
            name="fk_recall_scope_batches_tenant_farm_case",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "crop_batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_recall_scope_batches_tenant_farm_batch",
        ),
    )
    op.create_index(
        "ix_recall_scope_batches_tenant_farm_batch", "recall_scope_batches", ["tenant_id", "farm_id", "crop_batch_id"]
    )
    op.execute(
        "CREATE TRIGGER recall_scope_batches_no_update BEFORE UPDATE ON recall_scope_batches "
        "FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();"
    )
    op.execute(
        "CREATE TRIGGER recall_scope_batches_no_delete BEFORE DELETE ON recall_scope_batches "
        "FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();"
    )

    op.create_table(
        "recall_scope_produce_lots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("recall_case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("recall_cases.id"), nullable=False),
        sa.Column(
            "harvested_produce_lot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("harvested_produce_lots.id"),
            nullable=False,
        ),
        sa.Column("recorded_time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint(
            "recall_case_id", "harvested_produce_lot_id", name="ux_recall_scope_produce_lots_case_lot"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "recall_case_id"],
            ["recall_cases.tenant_id", "recall_cases.farm_id", "recall_cases.id"],
            name="fk_recall_scope_produce_lots_tenant_farm_case",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "harvested_produce_lot_id"],
            [
                "harvested_produce_lots.tenant_id",
                "harvested_produce_lots.farm_id",
                "harvested_produce_lots.id",
            ],
            name="fk_recall_scope_produce_lots_tenant_farm_lot",
        ),
    )
    op.create_index(
        "ix_recall_scope_produce_lots_tenant_farm_lot", "recall_scope_produce_lots",
        ["tenant_id", "farm_id", "harvested_produce_lot_id"],
    )
    op.execute(
        "CREATE TRIGGER recall_scope_produce_lots_no_update BEFORE UPDATE ON recall_scope_produce_lots "
        "FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();"
    )
    op.execute(
        "CREATE TRIGGER recall_scope_produce_lots_no_delete BEFORE DELETE ON recall_scope_produce_lots "
        "FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();"
    )

    op.create_table(
        "recall_scope_finished_goods_lots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("recall_case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("recall_cases.id"), nullable=False),
        sa.Column(
            "finished_goods_lot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("finished_goods_lots.id"),
            nullable=False,
        ),
        sa.Column("recorded_time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("recall_case_id", "finished_goods_lot_id", name="ux_recall_scope_fg_lots_case_lot"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "recall_case_id"],
            ["recall_cases.tenant_id", "recall_cases.farm_id", "recall_cases.id"],
            name="fk_recall_scope_fg_lots_tenant_farm_case",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "finished_goods_lot_id"],
            ["finished_goods_lots.tenant_id", "finished_goods_lots.farm_id", "finished_goods_lots.id"],
            name="fk_recall_scope_fg_lots_tenant_farm_lot",
        ),
    )
    op.create_index(
        "ix_recall_scope_fg_lots_tenant_farm_lot", "recall_scope_finished_goods_lots",
        ["tenant_id", "farm_id", "finished_goods_lot_id"],
    )
    op.execute(
        "CREATE TRIGGER recall_scope_fg_lots_no_update BEFORE UPDATE ON recall_scope_finished_goods_lots "
        "FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();"
    )
    op.execute(
        "CREATE TRIGGER recall_scope_fg_lots_no_delete BEFORE DELETE ON recall_scope_finished_goods_lots "
        "FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();"
    )

    # --- 5. structural reconciliation (deferred) --------------------------------------
    # Proves only what a same-row CHECK/FK cannot: that the case's own
    # selected typed source is itself represented in the matching scope
    # table. This is deliberately narrow -- it never re-derives the full
    # recursive lineage closure (that would duplicate CMP-019's own
    # traversal and add real complexity for no additional safety, since
    # the closure's *semantic* correctness is already guaranteed by
    # recall_service's own lock-protected freeze algorithm at write time).
    # The DB proves structural well-formedness of what was persisted; the
    # service proves the persisted set is the semantically-complete one.
    op.execute(
        """
        CREATE FUNCTION enforce_recall_case_reconciliation() RETURNS trigger AS $$
        DECLARE
            v_case RECORD;
        BEGIN
            IF TG_TABLE_NAME = 'recall_cases' THEN
                SELECT * INTO v_case FROM recall_cases WHERE id = NEW.id;
            ELSE
                SELECT * INTO v_case FROM recall_cases WHERE id = NEW.recall_case_id;
            END IF;
            IF v_case.id IS NULL THEN
                RAISE EXCEPTION 'recall scope row references a recall case that does not resolve';
            END IF;

            IF v_case.crop_batch_id IS NOT NULL THEN
                IF NOT EXISTS (
                    SELECT 1 FROM recall_scope_batches
                    WHERE recall_case_id = v_case.id AND crop_batch_id = v_case.crop_batch_id
                ) THEN
                    RAISE EXCEPTION 'recall case % has a crop_batch_id source with no matching recall_scope_batches row', v_case.id;
                END IF;
            ELSIF v_case.harvested_produce_lot_id IS NOT NULL THEN
                IF NOT EXISTS (
                    SELECT 1 FROM recall_scope_produce_lots
                    WHERE recall_case_id = v_case.id AND harvested_produce_lot_id = v_case.harvested_produce_lot_id
                ) THEN
                    RAISE EXCEPTION 'recall case % has a harvested_produce_lot_id source with no matching recall_scope_produce_lots row', v_case.id;
                END IF;
            ELSIF v_case.finished_goods_lot_id IS NOT NULL THEN
                IF NOT EXISTS (
                    SELECT 1 FROM recall_scope_finished_goods_lots
                    WHERE recall_case_id = v_case.id AND finished_goods_lot_id = v_case.finished_goods_lot_id
                ) THEN
                    RAISE EXCEPTION 'recall case % has a finished_goods_lot_id source with no matching recall_scope_finished_goods_lots row', v_case.id;
                END IF;
            END IF;

            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table in (
        "recall_cases", "recall_scope_batches", "recall_scope_produce_lots", "recall_scope_finished_goods_lots",
    ):
        op.execute(
            f"""
            CREATE CONSTRAINT TRIGGER {table}_enforce_recall_reconciliation
            AFTER INSERT ON {table}
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION enforce_recall_case_reconciliation();
            """
        )

    # --- 6. batch-derivation containment gate -----------------------------------------
    # New trigger (no prior attachment exists on batch_derivation_sources
    # to version) at the authoritative source-row insertion point: a
    # source batch cannot be consumed by a new split/merge while it is
    # contained by an open CMP-020 recall case.
    op.execute(
        """
        CREATE FUNCTION enforce_batch_derivation_source_containment() RETURNS trigger AS $$
        DECLARE
            v_open_recall BOOLEAN;
        BEGIN
            -- Lock the source batch row FIRST, before evaluating
            -- containment. batch_derivation_service already locks this
            -- same row earlier in the same transaction, so this is a
            -- no-op re-lock for the ordinary service path -- but it is
            -- the sole serialization point for a direct-SQL writer that
            -- does not pre-lock the batch itself, closing the same
            -- check-before-lock race this trigger would otherwise have.
            PERFORM 1 FROM crop_batches WHERE id = NEW.source_batch_id FOR UPDATE;
            SELECT EXISTS (
                SELECT 1 FROM recall_scope_batches rsb
                WHERE rsb.tenant_id = NEW.tenant_id AND rsb.farm_id = NEW.farm_id
                  AND rsb.crop_batch_id = NEW.source_batch_id
                  AND NOT EXISTS (
                      SELECT 1 FROM recall_case_closures c WHERE c.recall_case_id = rsb.recall_case_id
                  )
            ) INTO v_open_recall;
            IF v_open_recall THEN
                RAISE EXCEPTION 'source crop batch % is contained by an open recall case', NEW.source_batch_id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER batch_derivation_sources_enforce_containment
        BEFORE INSERT ON batch_derivation_sources
        FOR EACH ROW EXECUTE FUNCTION enforce_batch_derivation_source_containment();
        """
    )

    # --- 7. packing containment gate (v1 -> v2) -----------------------------------------
    # CMP-015's own enforce_packing_input_line_insert_integrity() function
    # is never modified -- only its trigger attachment is swapped, exactly
    # the idiom this codebase already uses three times (produce-lot ledger,
    # finished-goods ledger, dispatch-ledger). v2 reproduces every v1 rule
    # byte-for-byte and adds, at the end: the source produce lot and its
    # source crop batch must not be contained by an open recall case.
    op.execute("DROP TRIGGER packing_input_lines_enforce_insert_integrity ON packing_input_lines")
    op.execute(
        """
        CREATE FUNCTION enforce_packing_input_line_insert_integrity_v2() RETURNS trigger AS $$
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
            v_open_recall BOOLEAN;
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

            PERFORM 1 FROM crop_batches WHERE id = v_lot_batch_id FOR UPDATE;
            SELECT EXISTS (
                SELECT 1 FROM quality_holds h
                WHERE h.batch_id = v_lot_batch_id
                  AND NOT EXISTS (SELECT 1 FROM quality_hold_releases r WHERE r.quality_hold_id = h.id)
            ) INTO v_open_hold;
            IF v_open_hold THEN
                RAISE EXCEPTION 'source produce lot % batch has an open quality hold', NEW.harvested_produce_lot_id;
            END IF;

            -- CMP-020: direct SQL must not create packing consumption from
            -- a contained produce lot, or from a produce lot whose crop
            -- batch is contained -- the same DB boundary already
            -- responsible for the quality-hold check above. Lock the
            -- produce lot row FIRST, before evaluating its own
            -- containment -- the same row a harvested-produce-lot-source
            -- recall locks (`_freeze_produce_lot_source_scope`); the crop
            -- batch is already locked above for the quality-hold check,
            -- which is also the row a crop-batch-source recall locks, so
            -- both containment checks below are correctly ordered after
            -- their respective lock.
            PERFORM 1 FROM harvested_produce_lots WHERE id = NEW.harvested_produce_lot_id FOR UPDATE;
            SELECT EXISTS (
                SELECT 1 FROM recall_scope_produce_lots rsl
                WHERE rsl.tenant_id = NEW.tenant_id AND rsl.farm_id = NEW.farm_id
                  AND rsl.harvested_produce_lot_id = NEW.harvested_produce_lot_id
                  AND NOT EXISTS (SELECT 1 FROM recall_case_closures c WHERE c.recall_case_id = rsl.recall_case_id)
            ) INTO v_open_recall;
            IF v_open_recall THEN
                RAISE EXCEPTION 'source produce lot % is contained by an open recall case', NEW.harvested_produce_lot_id;
            END IF;
            SELECT EXISTS (
                SELECT 1 FROM recall_scope_batches rsb
                WHERE rsb.tenant_id = NEW.tenant_id AND rsb.farm_id = NEW.farm_id
                  AND rsb.crop_batch_id = v_lot_batch_id
                  AND NOT EXISTS (SELECT 1 FROM recall_case_closures c WHERE c.recall_case_id = rsb.recall_case_id)
            ) INTO v_open_recall;
            IF v_open_recall THEN
                RAISE EXCEPTION 'source produce lot % crop batch is contained by an open recall case', NEW.harvested_produce_lot_id;
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
        FOR EACH ROW EXECUTE FUNCTION enforce_packing_input_line_insert_integrity_v2();
        """
    )

    # --- 8. storage-release containment gate (v1 -> v2) -----------------------------------
    # CMP-018's own enforce_finished_goods_storage_movement_insert_integrity()
    # function is never modified -- only its trigger attachment is
    # swapped. v2 reproduces every v1 rule byte-for-byte and adds,
    # only in the 'release' branch: the lot must not be contained by an
    # open recall case. 'place'/'transfer' are untouched -- an operator
    # may still physically segregate recalled stock.
    op.execute(
        "DROP TRIGGER finished_goods_storage_movements_enforce_insert_integrity "
        "ON finished_goods_storage_movements"
    )
    op.execute(
        """
        CREATE FUNCTION enforce_finished_goods_storage_movement_insert_integrity_v2() RETURNS trigger AS $$
        DECLARE
            v_lot_tenant_id UUID;
            v_lot_farm_id UUID;
            v_lot_effective TIMESTAMPTZ;
            v_first_location UUID;
            v_second_location UUID;
            v_src_tenant_id UUID;
            v_src_farm_id UUID;
            v_src_type_code VARCHAR;
            v_dest_tenant_id UUID;
            v_dest_farm_id UUID;
            v_dest_type_code VARCHAR;
            v_dest_status VARCHAR;
            v_available_weight NUMERIC;
            v_available_count BIGINT;
            v_placed_weight NUMERIC;
            v_placed_count BIGINT;
            v_source_balance_weight NUMERIC;
            v_source_balance_count BIGINT;
            v_latest_movement_effective TIMESTAMPTZ;
            v_latest_ledger_effective TIMESTAMPTZ;
            v_open_recall BOOLEAN;
        BEGIN
            IF NEW.movement_kind NOT IN ('place', 'transfer', 'release') THEN
                RAISE EXCEPTION 'unrecognized storage movement kind %', NEW.movement_kind;
            END IF;

            SELECT tenant_id, farm_id, effective_time INTO v_lot_tenant_id, v_lot_farm_id, v_lot_effective
            FROM finished_goods_lots WHERE id = NEW.finished_goods_lot_id FOR UPDATE;
            IF v_lot_tenant_id IS NULL THEN
                RAISE EXCEPTION 'finished-goods lot not found for storage movement';
            END IF;
            IF v_lot_tenant_id <> NEW.tenant_id OR v_lot_farm_id <> NEW.farm_id THEN
                RAISE EXCEPTION 'storage movement tenant/farm does not match the finished-goods lot''s own';
            END IF;

            IF NEW.movement_kind = 'release' THEN
                SELECT EXISTS (
                    SELECT 1 FROM recall_scope_finished_goods_lots rsf
                    WHERE rsf.tenant_id = NEW.tenant_id AND rsf.farm_id = NEW.farm_id
                      AND rsf.finished_goods_lot_id = NEW.finished_goods_lot_id
                      AND NOT EXISTS (SELECT 1 FROM recall_case_closures c WHERE c.recall_case_id = rsf.recall_case_id)
                ) INTO v_open_recall;
                IF v_open_recall THEN
                    RAISE EXCEPTION 'finished-goods lot % is contained by an open recall case; release is blocked (place/transfer remain allowed)', NEW.finished_goods_lot_id;
                END IF;
            END IF;

            IF NEW.source_location_id IS NOT NULL AND NEW.destination_location_id IS NOT NULL THEN
                IF NEW.source_location_id < NEW.destination_location_id THEN
                    v_first_location := NEW.source_location_id;
                    v_second_location := NEW.destination_location_id;
                ELSE
                    v_first_location := NEW.destination_location_id;
                    v_second_location := NEW.source_location_id;
                END IF;
                PERFORM 1 FROM locations WHERE id = v_first_location FOR UPDATE;
                PERFORM 1 FROM locations WHERE id = v_second_location FOR UPDATE;
            ELSIF NEW.source_location_id IS NOT NULL THEN
                PERFORM 1 FROM locations WHERE id = NEW.source_location_id FOR UPDATE;
            ELSIF NEW.destination_location_id IS NOT NULL THEN
                PERFORM 1 FROM locations WHERE id = NEW.destination_location_id FOR UPDATE;
            END IF;

            IF NEW.source_location_id IS NOT NULL THEN
                SELECT l.tenant_id, l.farm_id, lt.code INTO v_src_tenant_id, v_src_farm_id, v_src_type_code
                FROM locations l JOIN location_types lt ON lt.id = l.location_type_id
                WHERE l.id = NEW.source_location_id;
                IF v_src_tenant_id IS NULL THEN
                    RAISE EXCEPTION 'source location not found for storage movement';
                END IF;
                IF v_src_tenant_id <> NEW.tenant_id OR v_src_farm_id <> NEW.farm_id THEN
                    RAISE EXCEPTION 'storage movement tenant/farm does not match the source location''s own';
                END IF;
                IF v_src_type_code <> 'cold_store_position' THEN
                    RAISE EXCEPTION 'source location is not a storage-eligible cold-store position';
                END IF;
            END IF;

            IF NEW.destination_location_id IS NOT NULL THEN
                SELECT l.tenant_id, l.farm_id, lt.code, l.status
                INTO v_dest_tenant_id, v_dest_farm_id, v_dest_type_code, v_dest_status
                FROM locations l JOIN location_types lt ON lt.id = l.location_type_id
                WHERE l.id = NEW.destination_location_id;
                IF v_dest_tenant_id IS NULL THEN
                    RAISE EXCEPTION 'destination location not found for storage movement';
                END IF;
                IF v_dest_tenant_id <> NEW.tenant_id OR v_dest_farm_id <> NEW.farm_id THEN
                    RAISE EXCEPTION 'storage movement tenant/farm does not match the destination location''s own';
                END IF;
                IF v_dest_type_code <> 'cold_store_position' THEN
                    RAISE EXCEPTION 'destination location is not a storage-eligible cold-store position';
                END IF;
                IF v_dest_status <> 'active' THEN
                    RAISE EXCEPTION 'destination location is not active';
                END IF;
            END IF;

            IF NEW.effective_time < v_lot_effective THEN
                RAISE EXCEPTION 'storage movement effective time precedes the finished-goods lot''s own effective time';
            END IF;

            SELECT MAX(effective_time) INTO v_latest_movement_effective
            FROM finished_goods_storage_movements WHERE finished_goods_lot_id = NEW.finished_goods_lot_id;
            IF v_latest_movement_effective IS NOT NULL AND NEW.effective_time < v_latest_movement_effective THEN
                RAISE EXCEPTION 'storage movement effective time precedes the finished-goods lot''s latest existing storage movement';
            END IF;

            SELECT MAX(effective_time) INTO v_latest_ledger_effective
            FROM finished_goods_ledger_entries WHERE finished_goods_lot_id = NEW.finished_goods_lot_id;
            IF v_latest_ledger_effective IS NOT NULL AND NEW.effective_time < v_latest_ledger_effective THEN
                RAISE EXCEPTION 'storage movement effective time precedes the finished-goods lot''s latest ledger entry';
            END IF;

            SELECT COALESCE(SUM(weight_delta_kg), 0), COALESCE(SUM(package_count_delta), 0)
            INTO v_available_weight, v_available_count
            FROM finished_goods_ledger_entries WHERE finished_goods_lot_id = NEW.finished_goods_lot_id;

            SELECT
                COALESCE(SUM(CASE WHEN movement_kind = 'place' THEN moved_weight_kg
                                   WHEN movement_kind = 'release' THEN -moved_weight_kg ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN movement_kind = 'place' THEN moved_package_count
                                   WHEN movement_kind = 'release' THEN -moved_package_count ELSE 0 END), 0)
            INTO v_placed_weight, v_placed_count
            FROM finished_goods_storage_movements WHERE finished_goods_lot_id = NEW.finished_goods_lot_id;

            IF NEW.movement_kind = 'place' THEN
                IF NEW.moved_weight_kg > (v_available_weight - v_placed_weight) THEN
                    RAISE EXCEPTION 'placement would exceed unplaced weight for finished-goods lot %', NEW.finished_goods_lot_id;
                END IF;
                IF NEW.moved_package_count > (v_available_count - v_placed_count) THEN
                    RAISE EXCEPTION 'placement would exceed unplaced package count for finished-goods lot %', NEW.finished_goods_lot_id;
                END IF;
            ELSE
                SELECT
                    COALESCE(SUM(CASE WHEN destination_location_id = NEW.source_location_id THEN moved_weight_kg ELSE 0 END), 0)
                    - COALESCE(SUM(CASE WHEN source_location_id = NEW.source_location_id THEN moved_weight_kg ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN destination_location_id = NEW.source_location_id THEN moved_package_count ELSE 0 END), 0)
                    - COALESCE(SUM(CASE WHEN source_location_id = NEW.source_location_id THEN moved_package_count ELSE 0 END), 0)
                INTO v_source_balance_weight, v_source_balance_count
                FROM finished_goods_storage_movements
                WHERE finished_goods_lot_id = NEW.finished_goods_lot_id
                  AND (source_location_id = NEW.source_location_id OR destination_location_id = NEW.source_location_id);

                IF NEW.moved_weight_kg > v_source_balance_weight THEN
                    RAISE EXCEPTION 'storage movement would leave source location with negative weight for finished-goods lot %', NEW.finished_goods_lot_id;
                END IF;
                IF NEW.moved_package_count > v_source_balance_count THEN
                    RAISE EXCEPTION 'storage movement would leave source location with negative package count for finished-goods lot %', NEW.finished_goods_lot_id;
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        "CREATE TRIGGER finished_goods_storage_movements_enforce_insert_integrity "
        "BEFORE INSERT ON finished_goods_storage_movements "
        "FOR EACH ROW EXECUTE FUNCTION enforce_finished_goods_storage_movement_insert_integrity_v2();"
    )

    # --- 9. dispatch containment gate (v3 -> v4) -----------------------------------------
    # CMP-018's own enforce_finished_goods_ledger_entry_insert_integrity_v3()
    # function is never modified -- only its trigger attachment is
    # swapped. v4 reproduces every v3 rule byte-for-byte (packing_receipt
    # branch untouched) and adds, only in the dispatch_issue branch: the
    # lot must not be contained by an open recall case, independent of
    # every existing balance/chronology/placement check.
    op.execute(
        "DROP TRIGGER finished_goods_ledger_entries_enforce_insert_integrity ON finished_goods_ledger_entries"
    )
    op.execute(
        """
        CREATE FUNCTION enforce_finished_goods_ledger_entry_insert_integrity_v4() RETURNS trigger AS $$
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
            v_prior_count BIGINT;
            v_prior_max_effective TIMESTAMPTZ;
            v_latest_movement_effective TIMESTAMPTZ;
            v_placed_weight NUMERIC;
            v_placed_count BIGINT;
            v_open_recall BOOLEAN;
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

                -- Lock the finished-goods lot row FIRST, before evaluating
                -- containment -- this is the same row `open_recall_case`
                -- locks for a finished-goods-lot-source recall
                -- (`_freeze_finished_goods_lot_source_scope`), so whichever
                -- transaction (this dispatch, or a concurrent recall open)
                -- acquires it first determines one strict serial order:
                -- either this dispatch commits first and the recall opens
                -- against the resulting state, or the recall commits first
                -- and this check (re-evaluated only after the lock is
                -- actually held) correctly sees the now-open containment.
                -- Checking containment before locking would let a
                -- concurrent recall commit in the gap between the read and
                -- the lock, so this order is deliberate and must not be
                -- reversed.
                PERFORM 1 FROM finished_goods_lots WHERE id = NEW.finished_goods_lot_id FOR UPDATE;

                -- CMP-020: dispatch of a finished-goods lot contained by an
                -- open recall case is rejected -- independent of, and in
                -- addition to, every balance/chronology/placement check
                -- below.
                SELECT EXISTS (
                    SELECT 1 FROM recall_scope_finished_goods_lots rsf
                    WHERE rsf.tenant_id = NEW.tenant_id AND rsf.farm_id = NEW.farm_id
                      AND rsf.finished_goods_lot_id = NEW.finished_goods_lot_id
                      AND NOT EXISTS (SELECT 1 FROM recall_case_closures c WHERE c.recall_case_id = rsf.recall_case_id)
                ) INTO v_open_recall;
                IF v_open_recall THEN
                    RAISE EXCEPTION 'finished-goods lot % is contained by an open recall case', NEW.finished_goods_lot_id;
                END IF;

                SELECT COALESCE(SUM(weight_delta_kg), 0), COALESCE(SUM(package_count_delta), 0), MAX(effective_time)
                INTO v_prior_weight, v_prior_count, v_prior_max_effective
                FROM finished_goods_ledger_entries WHERE finished_goods_lot_id = NEW.finished_goods_lot_id;

                IF v_prior_max_effective IS NOT NULL AND NEW.effective_time < v_prior_max_effective THEN
                    RAISE EXCEPTION 'dispatch issue effective time precedes the finished-goods lot''s latest existing ledger entry';
                END IF;

                SELECT MAX(effective_time) INTO v_latest_movement_effective
                FROM finished_goods_storage_movements WHERE finished_goods_lot_id = NEW.finished_goods_lot_id;
                IF v_latest_movement_effective IS NOT NULL AND NEW.effective_time < v_latest_movement_effective THEN
                    RAISE EXCEPTION 'dispatch issue effective time precedes the finished-goods lot''s latest storage movement';
                END IF;

                IF v_prior_weight + NEW.weight_delta_kg < 0 THEN
                    RAISE EXCEPTION 'dispatch issue would leave finished-goods lot % with negative available weight', NEW.finished_goods_lot_id;
                END IF;
                IF v_prior_count + NEW.package_count_delta < 0 THEN
                    RAISE EXCEPTION 'dispatch issue would leave finished-goods lot % with negative available package count', NEW.finished_goods_lot_id;
                END IF;

                SELECT
                    COALESCE(SUM(CASE WHEN movement_kind = 'place' THEN moved_weight_kg
                                       WHEN movement_kind = 'release' THEN -moved_weight_kg ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN movement_kind = 'place' THEN moved_package_count
                                       WHEN movement_kind = 'release' THEN -moved_package_count ELSE 0 END), 0)
                INTO v_placed_weight, v_placed_count
                FROM finished_goods_storage_movements WHERE finished_goods_lot_id = NEW.finished_goods_lot_id;

                IF (v_prior_weight + NEW.weight_delta_kg) < v_placed_weight THEN
                    RAISE EXCEPTION 'dispatch issue would leave finished-goods lot % with available weight below physically placed quantity', NEW.finished_goods_lot_id;
                END IF;
                IF (v_prior_count + NEW.package_count_delta) < v_placed_count THEN
                    RAISE EXCEPTION 'dispatch issue would leave finished-goods lot % with available package count below physically placed quantity', NEW.finished_goods_lot_id;
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER finished_goods_ledger_entries_enforce_insert_integrity
        BEFORE INSERT ON finished_goods_ledger_entries
        FOR EACH ROW EXECUTE FUNCTION enforce_finished_goods_ledger_entry_insert_integrity_v4();
        """
    )


def downgrade() -> None:
    bind = op.get_bind()

    # --- downgrade guard: recall history is independent compliance data --------
    # never reconstructible -- the same unconditional-block model CMP-015/
    # 017/018 already use for their own genuinely-new operational history.
    unsafe = bind.execute(
        sa.text(
            "SELECT "
            "(SELECT count(*) FROM recall_cases) AS case_count, "
            "(SELECT count(*) FROM recall_case_closures) AS closure_count, "
            "(SELECT count(*) FROM recall_scope_batches) AS scope_batch_count, "
            "(SELECT count(*) FROM recall_scope_produce_lots) AS scope_produce_lot_count, "
            "(SELECT count(*) FROM recall_scope_finished_goods_lots) AS scope_fg_lot_count"
        )
    ).mappings().first()
    if any(unsafe[k] > 0 for k in unsafe.keys()):
        raise RuntimeError(
            "Cannot downgrade past CMP-020: recall case, closure, or scope history exists. Recall "
            "history is independent compliance data, never reconstructible from any other table. "
            "Do not downgrade."
        )

    # --- restore the exact CMP-018 (v3) finished-goods ledger trigger attachment -----
    op.execute(
        "DROP TRIGGER finished_goods_ledger_entries_enforce_insert_integrity ON finished_goods_ledger_entries"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_finished_goods_ledger_entry_insert_integrity_v4()")
    op.execute(
        """
        CREATE TRIGGER finished_goods_ledger_entries_enforce_insert_integrity
        BEFORE INSERT ON finished_goods_ledger_entries
        FOR EACH ROW EXECUTE FUNCTION enforce_finished_goods_ledger_entry_insert_integrity_v3();
        """
    )

    # --- restore the exact CMP-018 (v1) storage-movement trigger attachment ----------
    op.execute(
        "DROP TRIGGER finished_goods_storage_movements_enforce_insert_integrity "
        "ON finished_goods_storage_movements"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_finished_goods_storage_movement_insert_integrity_v2()")
    op.execute(
        """
        CREATE TRIGGER finished_goods_storage_movements_enforce_insert_integrity
        BEFORE INSERT ON finished_goods_storage_movements
        FOR EACH ROW EXECUTE FUNCTION enforce_finished_goods_storage_movement_insert_integrity();
        """
    )

    # --- restore the exact CMP-015 (v1) packing_input_lines trigger attachment -------
    op.execute("DROP TRIGGER packing_input_lines_enforce_insert_integrity ON packing_input_lines")
    op.execute("DROP FUNCTION IF EXISTS enforce_packing_input_line_insert_integrity_v2()")
    op.execute(
        """
        CREATE TRIGGER packing_input_lines_enforce_insert_integrity
        BEFORE INSERT ON packing_input_lines
        FOR EACH ROW EXECUTE FUNCTION enforce_packing_input_line_insert_integrity();
        """
    )

    # --- drop the batch-derivation containment gate -----------------------------------
    op.execute("DROP TRIGGER IF EXISTS batch_derivation_sources_enforce_containment ON batch_derivation_sources")
    op.execute("DROP FUNCTION IF EXISTS enforce_batch_derivation_source_containment()")

    # --- drop recall reconciliation attachments/function -------------------------------
    for table in (
        "recall_cases", "recall_scope_batches", "recall_scope_produce_lots", "recall_scope_finished_goods_lots",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_enforce_recall_reconciliation ON {table}")
    op.execute("DROP FUNCTION IF EXISTS enforce_recall_case_reconciliation()")

    # --- drop recall tables (cascades their own indexes/constraints/triggers) --------
    op.drop_table("recall_scope_finished_goods_lots")
    op.drop_table("recall_scope_produce_lots")
    op.drop_table("recall_scope_batches")
    op.drop_table("recall_case_closures")
    op.drop_table("recall_cases")
