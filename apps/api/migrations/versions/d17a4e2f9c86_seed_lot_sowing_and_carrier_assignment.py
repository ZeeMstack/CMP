"""seed lot, sowing, and initial carrier assignment

Revision ID: d17a4e2f9c86
Revises: c48f21a6b3d9
Create Date: 2026-08-03 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'd17a4e2f9c86'
down_revision: Union[str, None] = 'c48f21a6b3d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- additive constraints on existing tables, needed as composite-FK
    # targets below. No column changes, no data migration.
    op.create_unique_constraint("uq_carriers_tenant_farm_id", "carriers", ["tenant_id", "farm_id", "id"])
    op.create_unique_constraint(
        "uq_batch_stage_runs_tenant_farm_batch_id",
        "batch_stage_runs",
        ["tenant_id", "farm_id", "batch_id", "id"],
    )

    # --- seed_lots ------------------------------------------------------------
    op.create_table(
        "seed_lots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("crop_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("crops.id"), nullable=False),
        sa.Column("variety_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("varieties.id"), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("supplier_name", sa.String(), nullable=True),
        sa.Column("supplier_lot_reference", sa.String(), nullable=True),
        sa.Column("received_date", sa.Date(), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column(
            "created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_seed_lots_status"),
        sa.CheckConstraint(
            "expiry_date IS NULL OR received_date IS NULL OR expiry_date >= received_date",
            name="ck_seed_lots_expiry_after_received",
        ),
        sa.UniqueConstraint("tenant_id", "farm_id", "id", name="uq_seed_lots_tenant_farm_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id"], ["farms.tenant_id", "farms.id"], name="fk_seed_lots_tenant_farm"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "crop_id"], ["crops.tenant_id", "crops.id"], name="fk_seed_lots_tenant_crop"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "crop_id", "variety_id"],
            ["varieties.tenant_id", "varieties.crop_id", "varieties.id"],
            name="fk_seed_lots_tenant_crop_variety",
        ),
    )
    op.create_index(
        "ux_seed_lots_tenant_code_lower", "seed_lots", ["tenant_id", sa.text("lower(code)")], unique=True
    )

    # --- sowing_events (immutable) ----------------------------------------------
    op.create_table(
        "sowing_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("crop_batches.id"), nullable=False),
        sa.Column(
            "active_batch_stage_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("batch_stage_runs.id"),
            nullable=False,
        ),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.UniqueConstraint("tenant_id", "farm_id", "id", name="uq_sowing_events_tenant_farm_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_sowing_events_tenant_farm_batch",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id", "active_batch_stage_run_id"],
            [
                "batch_stage_runs.tenant_id",
                "batch_stage_runs.farm_id",
                "batch_stage_runs.batch_id",
                "batch_stage_runs.id",
            ],
            name="fk_sowing_events_stage_run",
        ),
    )
    op.create_index(
        "ux_sowing_events_tenant_client_command_id",
        "sowing_events",
        ["tenant_id", "client_command_id"],
        unique=True,
    )

    # --- batch_carrier_assignments -----------------------------------------------
    op.create_table(
        "batch_carrier_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("crop_batches.id"), nullable=False),
        sa.Column("carrier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("carriers.id"), nullable=False),
        sa.Column(
            "batch_stage_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("batch_stage_runs.id"), nullable=False
        ),
        sa.Column("assigned_effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_effective_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "opening_sowing_event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sowing_events.id"),
            nullable=False,
        ),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "farm_id", "id", name="uq_batch_carrier_assignments_tenant_farm_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_batch_carrier_assignments_tenant_farm_batch",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "carrier_id"],
            ["carriers.tenant_id", "carriers.farm_id", "carriers.id"],
            name="fk_batch_carrier_assignments_tenant_farm_carrier",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id", "batch_stage_run_id"],
            [
                "batch_stage_runs.tenant_id",
                "batch_stage_runs.farm_id",
                "batch_stage_runs.batch_id",
                "batch_stage_runs.id",
            ],
            name="fk_batch_carrier_assignments_stage_run",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "opening_sowing_event_id"],
            ["sowing_events.tenant_id", "sowing_events.farm_id", "sowing_events.id"],
            name="fk_batch_carrier_assignments_opening_event",
        ),
    )
    op.create_index(
        "ux_batch_carrier_assignments_active_carrier",
        "batch_carrier_assignments",
        ["tenant_id", "carrier_id"],
        unique=True,
        postgresql_where=sa.text("released_effective_time IS NULL"),
    )

    # --- sowing_event_lines (immutable) -------------------------------------------
    op.create_table(
        "sowing_event_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column(
            "sowing_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sowing_events.id"), nullable=False
        ),
        sa.Column(
            "batch_carrier_assignment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("batch_carrier_assignments.id"),
            nullable=False,
        ),
        sa.Column("carrier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("carriers.id"), nullable=False),
        sa.Column("seed_lot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("seed_lots.id"), nullable=False),
        sa.Column("sown_site_count", sa.Integer(), nullable=False),
        sa.Column("seed_count", sa.Integer(), nullable=False),
        sa.Column("line_note", sa.String(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("sown_site_count > 0", name="ck_sowing_event_lines_site_count_positive"),
        sa.CheckConstraint("seed_count > 0", name="ck_sowing_event_lines_seed_count_positive"),
        sa.CheckConstraint(
            "seed_count >= sown_site_count", name="ck_sowing_event_lines_seed_count_ge_site_count"
        ),
        sa.UniqueConstraint("sowing_event_id", "carrier_id", name="ux_sowing_event_lines_event_carrier"),
        sa.UniqueConstraint("batch_carrier_assignment_id", name="ux_sowing_event_lines_assignment"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "sowing_event_id"],
            ["sowing_events.tenant_id", "sowing_events.farm_id", "sowing_events.id"],
            name="fk_sowing_event_lines_tenant_farm_event",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_carrier_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id",
                "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_sowing_event_lines_tenant_farm_assignment",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "carrier_id"],
            ["carriers.tenant_id", "carriers.farm_id", "carriers.id"],
            name="fk_sowing_event_lines_tenant_farm_carrier",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "seed_lot_id"],
            ["seed_lots.tenant_id", "seed_lots.farm_id", "seed_lots.id"],
            name="fk_sowing_event_lines_tenant_farm_seed_lot",
        ),
    )

    # --- triggers ------------------------------------------------------------

    # sowing_events: the active stage run must actually be this batch's own,
    # currently-open run, on a seeding-category stage that has a configured
    # required carrier type — cross-table checks a CHECK cannot express.
    op.execute(
        """
        CREATE FUNCTION enforce_sowing_event_insert_integrity() RETURNS trigger AS $$
        DECLARE
            v_run_batch_id UUID;
            v_run_exited TIMESTAMPTZ;
            v_run_stage_id UUID;
            v_batch_state TEXT;
            v_stage_category TEXT;
            v_required_carrier_type UUID;
        BEGIN
            SELECT batch_id, exited_effective_time, workflow_stage_id
            INTO v_run_batch_id, v_run_exited, v_run_stage_id
            FROM batch_stage_runs WHERE id = NEW.active_batch_stage_run_id;

            IF v_run_batch_id IS NULL THEN
                RAISE EXCEPTION 'active stage run not found';
            END IF;
            IF v_run_batch_id <> NEW.batch_id THEN
                RAISE EXCEPTION 'stage run does not belong to this batch';
            END IF;
            IF v_run_exited IS NOT NULL THEN
                RAISE EXCEPTION 'sowing requires the batch''s currently active stage run';
            END IF;

            SELECT state INTO v_batch_state FROM crop_batches WHERE id = NEW.batch_id;
            IF v_batch_state IS DISTINCT FROM 'active' THEN
                RAISE EXCEPTION 'crop batch is not active';
            END IF;

            SELECT stage_category, required_carrier_type_id INTO v_stage_category, v_required_carrier_type
            FROM workflow_stages WHERE id = v_run_stage_id;
            IF v_stage_category IS DISTINCT FROM 'seeding' THEN
                RAISE EXCEPTION 'current stage is not a seeding stage';
            END IF;
            IF v_required_carrier_type IS NULL THEN
                RAISE EXCEPTION 'current stage has no required carrier type configured';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER sowing_events_enforce_insert_integrity
        BEFORE INSERT ON sowing_events
        FOR EACH ROW EXECUTE FUNCTION enforce_sowing_event_insert_integrity();
        """
    )
    op.execute(
        """
        CREATE TRIGGER sowing_events_no_update
        BEFORE UPDATE ON sowing_events
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER sowing_events_no_delete
        BEFORE DELETE ON sowing_events
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )

    # batch_carrier_assignments: must be inserted active; must match the
    # opening sowing event's batch/stage-run/effective-time; carrier type
    # must match the stage's configured required carrier type. No CMP-009
    # command populates released_effective_time, so every UPDATE/DELETE is
    # rejected outright (a future release ticket replaces this pair).
    op.execute(
        """
        CREATE FUNCTION enforce_batch_carrier_assignment_insert_integrity() RETURNS trigger AS $$
        DECLARE
            event_batch_id UUID;
            event_run_id UUID;
            event_effective TIMESTAMPTZ;
            run_stage_id UUID;
            required_type UUID;
            actual_type UUID;
        BEGIN
            IF NEW.released_effective_time IS NOT NULL THEN
                RAISE EXCEPTION 'batch_carrier_assignments must be inserted active';
            END IF;

            SELECT batch_id, active_batch_stage_run_id, effective_time
            INTO event_batch_id, event_run_id, event_effective
            FROM sowing_events WHERE id = NEW.opening_sowing_event_id;

            IF event_batch_id IS NULL THEN
                RAISE EXCEPTION 'opening sowing event not found';
            END IF;
            IF event_batch_id <> NEW.batch_id THEN
                RAISE EXCEPTION 'opening sowing event batch mismatch';
            END IF;
            IF event_run_id <> NEW.batch_stage_run_id THEN
                RAISE EXCEPTION 'opening sowing event stage-run mismatch';
            END IF;
            IF event_effective <> NEW.assigned_effective_time THEN
                RAISE EXCEPTION 'assigned_effective_time must match the opening sowing event''s effective time';
            END IF;

            SELECT workflow_stage_id INTO run_stage_id FROM batch_stage_runs WHERE id = NEW.batch_stage_run_id;
            SELECT required_carrier_type_id INTO required_type FROM workflow_stages WHERE id = run_stage_id;
            SELECT carrier_type_id INTO actual_type FROM carriers WHERE id = NEW.carrier_id;
            IF required_type IS NULL OR actual_type IS DISTINCT FROM required_type THEN
                RAISE EXCEPTION 'carrier type does not match the stage''s required carrier type';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER batch_carrier_assignments_enforce_insert_integrity
        BEFORE INSERT ON batch_carrier_assignments
        FOR EACH ROW EXECUTE FUNCTION enforce_batch_carrier_assignment_insert_integrity();
        """
    )
    op.execute(
        """
        CREATE TRIGGER batch_carrier_assignments_no_update
        BEFORE UPDATE ON batch_carrier_assignments
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER batch_carrier_assignments_no_delete
        BEFORE DELETE ON batch_carrier_assignments
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )

    # sowing_event_lines: the referenced assignment must actually belong to
    # this sowing event and carrier, and the seed lot's crop/variety must
    # match the batch's immutable workflow-derived crop/variety.
    op.execute(
        """
        CREATE FUNCTION enforce_sowing_event_line_insert_integrity() RETURNS trigger AS $$
        DECLARE
            assignment_event_id UUID;
            assignment_carrier_id UUID;
            event_batch_id UUID;
            wf_crop_id UUID;
            wf_variety_id UUID;
            lot_crop_id UUID;
            lot_variety_id UUID;
        BEGIN
            SELECT opening_sowing_event_id, carrier_id INTO assignment_event_id, assignment_carrier_id
            FROM batch_carrier_assignments WHERE id = NEW.batch_carrier_assignment_id;

            IF assignment_event_id IS NULL THEN
                RAISE EXCEPTION 'batch carrier assignment not found';
            END IF;
            IF assignment_event_id <> NEW.sowing_event_id THEN
                RAISE EXCEPTION 'assignment does not belong to this sowing event';
            END IF;
            IF assignment_carrier_id <> NEW.carrier_id THEN
                RAISE EXCEPTION 'assignment carrier does not match this line''s carrier';
            END IF;

            SELECT batch_id INTO event_batch_id FROM sowing_events WHERE id = NEW.sowing_event_id;

            SELECT w.crop_id, w.variety_id INTO wf_crop_id, wf_variety_id
            FROM crop_batches cb
            JOIN workflow_versions wv ON wv.id = cb.workflow_version_id
            JOIN workflows w ON w.id = wv.workflow_id
            WHERE cb.id = event_batch_id;

            SELECT crop_id, variety_id INTO lot_crop_id, lot_variety_id
            FROM seed_lots WHERE id = NEW.seed_lot_id;

            IF lot_crop_id IS DISTINCT FROM wf_crop_id THEN
                RAISE EXCEPTION 'seed lot crop does not match the batch''s workflow crop';
            END IF;
            IF wf_variety_id IS NULL OR lot_variety_id IS DISTINCT FROM wf_variety_id THEN
                RAISE EXCEPTION 'seed lot variety does not match the batch''s workflow variety';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER sowing_event_lines_enforce_insert_integrity
        BEFORE INSERT ON sowing_event_lines
        FOR EACH ROW EXECUTE FUNCTION enforce_sowing_event_line_insert_integrity();
        """
    )
    op.execute(
        """
        CREATE TRIGGER sowing_event_lines_no_update
        BEFORE UPDATE ON sowing_event_lines
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER sowing_event_lines_no_delete
        BEFORE DELETE ON sowing_event_lines
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )

    # Hard-delete protection reusing the shared function from CMP-005.
    op.execute(
        """
        CREATE TRIGGER seed_lots_no_delete
        BEFORE DELETE ON seed_lots
        FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS seed_lots_no_delete ON seed_lots")

    op.execute("DROP TRIGGER IF EXISTS sowing_event_lines_no_delete ON sowing_event_lines")
    op.execute("DROP TRIGGER IF EXISTS sowing_event_lines_no_update ON sowing_event_lines")
    op.execute(
        "DROP TRIGGER IF EXISTS sowing_event_lines_enforce_insert_integrity ON sowing_event_lines"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_sowing_event_line_insert_integrity()")

    op.execute("DROP TRIGGER IF EXISTS batch_carrier_assignments_no_delete ON batch_carrier_assignments")
    op.execute("DROP TRIGGER IF EXISTS batch_carrier_assignments_no_update ON batch_carrier_assignments")
    op.execute(
        "DROP TRIGGER IF EXISTS batch_carrier_assignments_enforce_insert_integrity "
        "ON batch_carrier_assignments"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_batch_carrier_assignment_insert_integrity()")

    op.execute("DROP TRIGGER IF EXISTS sowing_events_no_delete ON sowing_events")
    op.execute("DROP TRIGGER IF EXISTS sowing_events_no_update ON sowing_events")
    op.execute("DROP TRIGGER IF EXISTS sowing_events_enforce_insert_integrity ON sowing_events")
    op.execute("DROP FUNCTION IF EXISTS enforce_sowing_event_insert_integrity()")

    op.drop_table("sowing_event_lines")

    op.drop_index("ux_batch_carrier_assignments_active_carrier", table_name="batch_carrier_assignments")
    op.drop_table("batch_carrier_assignments")

    op.drop_index("ux_sowing_events_tenant_client_command_id", table_name="sowing_events")
    op.drop_table("sowing_events")

    op.drop_index("ux_seed_lots_tenant_code_lower", table_name="seed_lots")
    op.drop_table("seed_lots")

    op.drop_constraint(
        "uq_batch_stage_runs_tenant_farm_batch_id", "batch_stage_runs", type_="unique"
    )
    op.drop_constraint("uq_carriers_tenant_farm_id", "carriers", type_="unique")
