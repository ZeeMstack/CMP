"""harvest event and harvested produce lot foundation

Revision ID: c7f14b8e29a3
Revises: a4d92f7c1e6b
Create Date: 2026-08-05 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'c7f14b8e29a3'
down_revision: Union[str, None] = 'a4d92f7c1e6b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PRIOR_STAGE_CATEGORIES = (
    "seeding", "germination", "nursery", "transplanting", "intermediate", "production", "harvest_ready",
    "completed", "rejected",
)
_NEW_STAGE_CATEGORIES = (
    "seeding", "germination", "nursery", "transplanting", "intermediate", "production", "harvest_ready",
    "harvesting", "completed", "rejected",
)


def upgrade() -> None:
    # --- workflow_stages: widen the category CHECK additively --------------------
    op.drop_constraint("ck_workflow_stages_category_allowed", "workflow_stages", type_="check")
    op.create_check_constraint(
        "ck_workflow_stages_category_allowed",
        "workflow_stages",
        "stage_category IN ('" + "', '".join(_NEW_STAGE_CATEGORIES) + "')",
    )

    # --- harvest_events (immutable) --------------------------------------------
    op.create_table(
        "harvest_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("crop_batches.id"), nullable=False),
        sa.Column(
            "active_batch_stage_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("batch_stage_runs.id"),
            nullable=False,
        ),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.UniqueConstraint("tenant_id", "farm_id", "id", name="uq_harvest_events_tenant_farm_id"),
        sa.UniqueConstraint(
            "tenant_id", "farm_id", "batch_id", "id", name="uq_harvest_events_tenant_farm_batch_id"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_harvest_events_tenant_farm_batch",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id", "active_batch_stage_run_id"],
            [
                "batch_stage_runs.tenant_id", "batch_stage_runs.farm_id", "batch_stage_runs.batch_id",
                "batch_stage_runs.id",
            ],
            name="fk_harvest_events_stage_run",
        ),
    )
    op.create_index(
        "ux_harvest_events_tenant_client_command_id", "harvest_events", ["tenant_id", "client_command_id"],
        unique=True,
    )

    # --- harvested_produce_lots (immutable) -------------------------------------
    op.create_table(
        "harvested_produce_lots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column(
            "harvest_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("harvest_events.id"), nullable=False
        ),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("crop_batches.id"), nullable=False),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workflows.id"), nullable=False),
        sa.Column(
            "workflow_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workflow_versions.id"),
            nullable=False,
        ),
        sa.Column("crop_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("crops.id"), nullable=False),
        sa.Column("variety_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("varieties.id"), nullable=True),
        sa.Column("total_harvested_weight_kg", sa.Numeric(), nullable=False),
        sa.Column("total_whole_unit_count", sa.BigInteger(), nullable=True),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "total_harvested_weight_kg > 0 AND total_harvested_weight_kg = trunc(total_harvested_weight_kg, 3) "
            "AND total_harvested_weight_kg < 100000000000",
            name="ck_harvested_produce_lots_weight_envelope",
        ),
        sa.CheckConstraint(
            "total_whole_unit_count IS NULL OR total_whole_unit_count > 0",
            name="ck_harvested_produce_lots_count_positive",
        ),
        sa.UniqueConstraint("harvest_event_id", name="ux_harvested_produce_lots_event"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "harvest_event_id"],
            ["harvest_events.tenant_id", "harvest_events.farm_id", "harvest_events.id"],
            name="fk_harvested_produce_lots_tenant_farm_event",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_harvested_produce_lots_tenant_farm_batch",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "workflow_id", "workflow_version_id"],
            ["workflow_versions.tenant_id", "workflow_versions.workflow_id", "workflow_versions.id"],
            name="fk_harvested_produce_lots_tenant_workflow_version",
        ),
    )
    op.create_index(
        "ux_harvested_produce_lots_tenant_code_lower", "harvested_produce_lots",
        ["tenant_id", sa.text("lower(code)")], unique=True,
    )

    # --- harvest_source_lines (immutable) ---------------------------------------
    op.create_table(
        "harvest_source_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column(
            "harvest_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("harvest_events.id"), nullable=False
        ),
        sa.Column(
            "batch_carrier_assignment_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("batch_carrier_assignments.id"), nullable=False,
        ),
        sa.Column("carrier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("carriers.id"), nullable=False),
        sa.Column("harvested_weight_kg", sa.Numeric(), nullable=False),
        sa.Column("whole_unit_count", sa.BigInteger(), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "harvested_weight_kg > 0 AND harvested_weight_kg = trunc(harvested_weight_kg, 3) "
            "AND harvested_weight_kg < 100000000000",
            name="ck_harvest_source_lines_weight_envelope",
        ),
        sa.CheckConstraint(
            "whole_unit_count IS NULL OR whole_unit_count > 0", name="ck_harvest_source_lines_count_positive"
        ),
        sa.UniqueConstraint(
            "harvest_event_id", "batch_carrier_assignment_id", name="ux_harvest_source_lines_event_assignment"
        ),
        sa.UniqueConstraint(
            "tenant_id", "farm_id", "harvest_event_id", "id",
            name="uq_harvest_source_lines_tenant_farm_event_id",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "harvest_event_id"],
            ["harvest_events.tenant_id", "harvest_events.farm_id", "harvest_events.id"],
            name="fk_harvest_source_lines_tenant_farm_event",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_carrier_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id", "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_harvest_source_lines_tenant_farm_assignment",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "carrier_id"],
            ["carriers.tenant_id", "carriers.farm_id", "carriers.id"],
            name="fk_harvest_source_lines_tenant_farm_carrier",
        ),
    )

    # --- immediate insert-integrity triggers ------------------------------------

    op.execute(
        """
        CREATE FUNCTION enforce_harvest_event_insert_integrity() RETURNS trigger AS $$
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
            -- Lock the crop batch row so a direct-SQL insert genuinely
            -- serializes against every other command that already locks
            -- the batch (stage progression, transplantation, split/merge,
            -- hold placement, another harvest) — not just an unlocked read.
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
            -- clock_timestamp() is this trigger's one selected clock
            -- function for "future" — deliberately NOT now()/
            -- transaction_timestamp(), which freeze at the transaction's
            -- start: a command whose transaction has been open for any
            -- real elapsed time (e.g. earlier reads/locks in the same
            -- request) would otherwise see its own genuinely-current
            -- effective_time misclassified as "future" purely because the
            -- transaction began before that instant. clock_timestamp()
            -- always reflects the true current instant, matching what
            -- "in the future" actually means.
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
    )
    op.execute(
        """
        CREATE TRIGGER harvest_events_enforce_insert_integrity
        BEFORE INSERT ON harvest_events
        FOR EACH ROW EXECUTE FUNCTION enforce_harvest_event_insert_integrity();
        """
    )
    op.execute(
        """
        CREATE TRIGGER harvest_events_no_update
        BEFORE UPDATE ON harvest_events
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER harvest_events_no_delete
        BEFORE DELETE ON harvest_events
        FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();
        """
    )

    op.execute(
        """
        CREATE FUNCTION enforce_harvest_source_line_insert_integrity() RETURNS trigger AS $$
        DECLARE
            v_event_batch_id UUID;
            v_event_effective TIMESTAMPTZ;
            v_assignment_batch_id UUID;
            v_assignment_carrier UUID;
            v_assignment_released TIMESTAMPTZ;
            v_assignment_effective TIMESTAMPTZ;
            v_carrier_status TEXT;
        BEGIN
            SELECT batch_id, effective_time INTO v_event_batch_id, v_event_effective
            FROM harvest_events WHERE id = NEW.harvest_event_id;
            IF v_event_batch_id IS NULL THEN
                RAISE EXCEPTION 'harvest event not found';
            END IF;

            SELECT batch_id, carrier_id, released_effective_time, assigned_effective_time
            INTO v_assignment_batch_id, v_assignment_carrier, v_assignment_released, v_assignment_effective
            FROM batch_carrier_assignments WHERE id = NEW.batch_carrier_assignment_id;
            IF v_assignment_batch_id IS NULL THEN
                RAISE EXCEPTION 'source assignment not found';
            END IF;
            IF v_assignment_batch_id <> v_event_batch_id THEN
                RAISE EXCEPTION 'source assignment does not belong to this harvest event''s batch';
            END IF;
            IF v_assignment_released IS NOT NULL THEN
                RAISE EXCEPTION 'source assignment is not active';
            END IF;
            IF v_assignment_carrier <> NEW.carrier_id THEN
                RAISE EXCEPTION 'carrier does not match source assignment carrier';
            END IF;
            IF v_event_effective < v_assignment_effective THEN
                RAISE EXCEPTION 'harvest event effective time precedes source assignment''s assigned effective time';
            END IF;

            SELECT status INTO v_carrier_status FROM carriers WHERE id = NEW.carrier_id;
            IF v_carrier_status IS DISTINCT FROM 'active' THEN
                RAISE EXCEPTION 'carrier is not active';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER harvest_source_lines_enforce_insert_integrity
        BEFORE INSERT ON harvest_source_lines
        FOR EACH ROW EXECUTE FUNCTION enforce_harvest_source_line_insert_integrity();
        """
    )
    op.execute(
        """
        CREATE TRIGGER harvest_source_lines_no_update
        BEFORE UPDATE ON harvest_source_lines
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER harvest_source_lines_no_delete
        BEFORE DELETE ON harvest_source_lines
        FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();
        """
    )

    op.execute(
        """
        CREATE FUNCTION enforce_harvested_produce_lot_insert_integrity() RETURNS trigger AS $$
        DECLARE
            v_event_batch_id UUID;
            v_event_effective TIMESTAMPTZ;
            v_batch_workflow_id UUID;
            v_batch_workflow_version_id UUID;
            v_workflow_crop_id UUID;
            v_workflow_variety_id UUID;
        BEGIN
            SELECT batch_id, effective_time INTO v_event_batch_id, v_event_effective
            FROM harvest_events WHERE id = NEW.harvest_event_id;
            IF v_event_batch_id IS NULL THEN
                RAISE EXCEPTION 'harvest event not found';
            END IF;
            IF v_event_batch_id <> NEW.batch_id THEN
                RAISE EXCEPTION 'produce lot batch does not match harvest event batch';
            END IF;
            IF v_event_effective <> NEW.effective_time THEN
                RAISE EXCEPTION 'produce lot effective time must equal the harvest event''s effective time';
            END IF;

            SELECT workflow_id, workflow_version_id INTO v_batch_workflow_id, v_batch_workflow_version_id
            FROM crop_batches WHERE id = NEW.batch_id;
            IF v_batch_workflow_id <> NEW.workflow_id OR v_batch_workflow_version_id <> NEW.workflow_version_id THEN
                RAISE EXCEPTION 'produce lot workflow/version does not match the batch''s own';
            END IF;

            SELECT crop_id, variety_id INTO v_workflow_crop_id, v_workflow_variety_id
            FROM workflows WHERE id = v_batch_workflow_id;
            IF v_workflow_crop_id <> NEW.crop_id OR v_workflow_variety_id IS DISTINCT FROM NEW.variety_id THEN
                RAISE EXCEPTION 'produce lot crop/variety does not match the batch''s workflow';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER harvested_produce_lots_enforce_insert_integrity
        BEFORE INSERT ON harvested_produce_lots
        FOR EACH ROW EXECUTE FUNCTION enforce_harvested_produce_lot_insert_integrity();
        """
    )
    op.execute(
        """
        CREATE TRIGGER harvested_produce_lots_no_update
        BEFORE UPDATE ON harvested_produce_lots
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER harvested_produce_lots_no_delete
        BEFORE DELETE ON harvested_produce_lots
        FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();
        """
    )

    # --- deferred reconciliation --------------------------------------------------
    # One shared function, resolved per firing table, attached via three
    # DEFERRABLE INITIALLY DEFERRED constraint triggers so any insert — even
    # direct SQL against an already-committed event, in a later transaction —
    # re-validates that event's complete reconciled state at commit time.
    # harvest_source_lines/harvested_produce_lots always reference their
    # event directly via harvest_event_id, so counting "by event" already is
    # the complete set — no separate reverse-reference check is needed here
    # (unlike CMP-012, which had an intermediate source/output header table).
    op.execute(
        """
        CREATE FUNCTION enforce_harvest_reconciliation() RETURNS trigger AS $$
        DECLARE
            v_event_id UUID;
            v_line_count INTEGER;
            v_lot_count INTEGER;
            v_total_weight NUMERIC;
            v_total_count NUMERIC;
            v_lot_weight NUMERIC;
            v_lot_count_col BIGINT;
            v_null_count_lines INTEGER;
            v_nonnull_count_lines INTEGER;
        BEGIN
            IF TG_TABLE_NAME = 'harvest_events' THEN
                v_event_id := NEW.id;
            ELSIF TG_TABLE_NAME = 'harvest_source_lines' THEN
                v_event_id := NEW.harvest_event_id;
            ELSIF TG_TABLE_NAME = 'harvested_produce_lots' THEN
                v_event_id := NEW.harvest_event_id;
            END IF;

            IF v_event_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT count(*) INTO v_line_count FROM harvest_source_lines WHERE harvest_event_id = v_event_id;
            IF v_line_count = 0 THEN
                RAISE EXCEPTION 'harvest event % has no source lines', v_event_id;
            END IF;

            SELECT count(*) INTO v_lot_count FROM harvested_produce_lots WHERE harvest_event_id = v_event_id;
            IF v_lot_count <> 1 THEN
                RAISE EXCEPTION 'harvest event % must have exactly one produce lot', v_event_id;
            END IF;

            SELECT
                count(*) FILTER (WHERE whole_unit_count IS NULL),
                count(*) FILTER (WHERE whole_unit_count IS NOT NULL),
                sum(harvested_weight_kg), sum(whole_unit_count)
            INTO v_null_count_lines, v_nonnull_count_lines, v_total_weight, v_total_count
            FROM harvest_source_lines WHERE harvest_event_id = v_event_id;

            IF v_null_count_lines > 0 AND v_nonnull_count_lines > 0 THEN
                RAISE EXCEPTION 'harvest event % has mixed whole_unit_count presence across source lines', v_event_id;
            END IF;
            IF v_nonnull_count_lines = 0 THEN
                v_total_count := NULL;
            END IF;

            SELECT total_harvested_weight_kg, total_whole_unit_count INTO v_lot_weight, v_lot_count_col
            FROM harvested_produce_lots WHERE harvest_event_id = v_event_id;

            IF v_lot_weight <> v_total_weight THEN
                RAISE EXCEPTION 'harvest event % produce-lot weight does not reconcile with source lines', v_event_id;
            END IF;
            IF v_lot_count_col IS DISTINCT FROM v_total_count THEN
                RAISE EXCEPTION 'harvest event % produce-lot count does not reconcile with source lines', v_event_id;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER harvest_events_enforce_reconciliation
        AFTER INSERT ON harvest_events
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_harvest_reconciliation();
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER harvest_source_lines_enforce_reconciliation
        AFTER INSERT ON harvest_source_lines
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_harvest_reconciliation();
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER harvested_produce_lots_enforce_reconciliation
        AFTER INSERT ON harvested_produce_lots
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_harvest_reconciliation();
        """
    )


def downgrade() -> None:
    bind = op.get_bind()

    # --- downgrade guard: never corrupt or silently discard CMP-013 history ------
    unsafe = bind.execute(
        sa.text(
            "SELECT "
            "(SELECT count(*) FROM harvest_events) AS event_count, "
            "(SELECT count(*) FROM harvest_source_lines) AS line_count, "
            "(SELECT count(*) FROM harvested_produce_lots) AS lot_count, "
            "(SELECT count(*) FROM workflow_stages WHERE stage_category = 'harvesting') AS stage_count"
        )
    ).mappings().first()
    if (
        unsafe["event_count"] > 0
        or unsafe["line_count"] > 0
        or unsafe["lot_count"] > 0
        or unsafe["stage_count"] > 0
    ):
        raise RuntimeError(
            "Cannot downgrade past CMP-013: harvest events, harvest source lines, harvested produce "
            "lots, or harvesting-category workflow stages exist. Downgrading would corrupt or silently "
            "discard this production history. Remove or migrate the offending data out-of-band before "
            "downgrading, or do not downgrade."
        )

    op.execute(
        "DROP TRIGGER IF EXISTS harvested_produce_lots_enforce_reconciliation ON harvested_produce_lots"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS harvest_source_lines_enforce_reconciliation ON harvest_source_lines"
    )
    op.execute("DROP TRIGGER IF EXISTS harvest_events_enforce_reconciliation ON harvest_events")
    op.execute("DROP FUNCTION IF EXISTS enforce_harvest_reconciliation()")

    op.execute("DROP TRIGGER IF EXISTS harvested_produce_lots_no_delete ON harvested_produce_lots")
    op.execute("DROP TRIGGER IF EXISTS harvested_produce_lots_no_update ON harvested_produce_lots")
    op.execute(
        "DROP TRIGGER IF EXISTS harvested_produce_lots_enforce_insert_integrity ON harvested_produce_lots"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_harvested_produce_lot_insert_integrity()")

    op.execute("DROP TRIGGER IF EXISTS harvest_source_lines_no_delete ON harvest_source_lines")
    op.execute("DROP TRIGGER IF EXISTS harvest_source_lines_no_update ON harvest_source_lines")
    op.execute(
        "DROP TRIGGER IF EXISTS harvest_source_lines_enforce_insert_integrity ON harvest_source_lines"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_harvest_source_line_insert_integrity()")

    op.execute("DROP TRIGGER IF EXISTS harvest_events_no_delete ON harvest_events")
    op.execute("DROP TRIGGER IF EXISTS harvest_events_no_update ON harvest_events")
    op.execute("DROP TRIGGER IF EXISTS harvest_events_enforce_insert_integrity ON harvest_events")
    op.execute("DROP FUNCTION IF EXISTS enforce_harvest_event_insert_integrity()")

    op.drop_table("harvest_source_lines")

    op.drop_index("ux_harvested_produce_lots_tenant_code_lower", table_name="harvested_produce_lots")
    op.drop_table("harvested_produce_lots")

    op.drop_index("ux_harvest_events_tenant_client_command_id", table_name="harvest_events")
    op.drop_table("harvest_events")

    op.drop_constraint("ck_workflow_stages_category_allowed", "workflow_stages", type_="check")
    op.create_check_constraint(
        "ck_workflow_stages_category_allowed",
        "workflow_stages",
        "stage_category IN ('" + "', '".join(_PRIOR_STAGE_CATEGORIES) + "')",
    )
