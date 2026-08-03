"""crop batch and stage execution

Revision ID: c48f21a6b3d9
Revises: b2f6c9d3e178
Create Date: 2026-08-03 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'c48f21a6b3d9'
down_revision: Union[str, None] = 'b2f6c9d3e178'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- additive constraints on existing tables, needed as composite-FK
    # targets below. No column changes, no data migration.
    op.create_unique_constraint("uq_farms_tenant_id_id", "farms", ["tenant_id", "id"])
    op.create_unique_constraint(
        "uq_workflow_versions_tenant_workflow_id", "workflow_versions", ["tenant_id", "workflow_id", "id"]
    )
    op.create_unique_constraint(
        "uq_workflow_transitions_tenant_version_id",
        "workflow_transitions",
        ["tenant_id", "workflow_version_id", "id"],
    )

    # --- crop_batches ------------------------------------------------------
    op.create_table(
        "crop_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workflows.id"), nullable=False),
        sa.Column(
            "workflow_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflow_versions.id"),
            nullable=False,
        ),
        sa.Column("state", sa.String(), nullable=False, server_default="active"),
        sa.Column("created_effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("closed_effective_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.CheckConstraint("state IN ('active', 'closed')", name="ck_crop_batches_state"),
        sa.CheckConstraint(
            "(state = 'active' AND closed_effective_time IS NULL) OR "
            "(state = 'closed' AND closed_effective_time IS NOT NULL)",
            name="ck_crop_batches_closed_time_matches_state",
        ),
        sa.CheckConstraint(
            "closed_effective_time IS NULL OR closed_effective_time >= created_effective_time",
            name="ck_crop_batches_closed_after_created",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crop_batches_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "farm_id", "id", name="uq_crop_batches_tenant_farm_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id"], ["farms.tenant_id", "farms.id"], name="fk_crop_batches_tenant_farm"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "workflow_id"],
            ["workflows.tenant_id", "workflows.id"],
            name="fk_crop_batches_tenant_workflow",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "workflow_id", "workflow_version_id"],
            ["workflow_versions.tenant_id", "workflow_versions.workflow_id", "workflow_versions.id"],
            name="fk_crop_batches_tenant_workflow_version",
        ),
    )
    op.create_index(
        "ux_crop_batches_tenant_code_lower", "crop_batches", ["tenant_id", sa.text("lower(code)")], unique=True
    )
    op.create_index(
        "ux_crop_batches_tenant_client_command_id",
        "crop_batches",
        ["tenant_id", "client_command_id"],
        unique=True,
    )

    # --- batch_stage_transitions (immutable) --------------------------------
    op.create_table(
        "batch_stage_transitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("crop_batches.id"), nullable=False),
        sa.Column(
            "workflow_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflow_versions.id"),
            nullable=False,
        ),
        sa.Column("command_kind", sa.String(), nullable=False),
        sa.Column(
            "source_stage_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workflow_stages.id"), nullable=True
        ),
        sa.Column(
            "destination_stage_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflow_stages.id"),
            nullable=False,
        ),
        sa.Column(
            "configured_transition_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflow_transitions.id"),
            nullable=True,
        ),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.CheckConstraint(
            "command_kind IN ('initial_entry', 'stage_transition')",
            name="ck_batch_stage_transitions_command_kind",
        ),
        sa.CheckConstraint(
            "(command_kind = 'initial_entry' AND source_stage_id IS NULL AND configured_transition_id IS NULL) OR "
            "(command_kind = 'stage_transition' AND source_stage_id IS NOT NULL AND configured_transition_id IS NOT NULL)",
            name="ck_batch_stage_transitions_shape",
        ),
        sa.CheckConstraint(
            "source_stage_id IS NULL OR source_stage_id <> destination_stage_id",
            name="ck_batch_stage_transitions_no_self_transition",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_batch_stage_transitions_tenant_farm_batch",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "workflow_version_id", "destination_stage_id"],
            ["workflow_stages.tenant_id", "workflow_stages.workflow_version_id", "workflow_stages.id"],
            name="fk_batch_stage_transitions_destination_stage",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "workflow_version_id", "source_stage_id"],
            ["workflow_stages.tenant_id", "workflow_stages.workflow_version_id", "workflow_stages.id"],
            name="fk_batch_stage_transitions_source_stage",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "workflow_version_id", "configured_transition_id"],
            [
                "workflow_transitions.tenant_id",
                "workflow_transitions.workflow_version_id",
                "workflow_transitions.id",
            ],
            name="fk_batch_stage_transitions_configured_transition",
        ),
    )
    op.create_index(
        "ux_batch_stage_transitions_tenant_kind_client_id",
        "batch_stage_transitions",
        ["tenant_id", "command_kind", "client_command_id"],
        unique=True,
    )
    op.create_index(
        "ux_batch_stage_transitions_one_initial_entry",
        "batch_stage_transitions",
        ["batch_id"],
        unique=True,
        postgresql_where=sa.text("command_kind = 'initial_entry'"),
    )

    # --- batch_stage_runs ----------------------------------------------------
    op.create_table(
        "batch_stage_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("crop_batches.id"), nullable=False),
        sa.Column(
            "workflow_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflow_versions.id"),
            nullable=False,
        ),
        sa.Column(
            "workflow_stage_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workflow_stages.id"), nullable=False
        ),
        sa.Column("entered_effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exited_effective_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "opened_by_transition_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("batch_stage_transitions.id"),
            nullable=False,
        ),
        sa.Column(
            "closed_by_transition_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("batch_stage_transitions.id"),
            nullable=True,
        ),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(exited_effective_time IS NULL) = (closed_by_transition_id IS NULL)",
            name="ck_batch_stage_runs_closure_fields_together",
        ),
        sa.CheckConstraint(
            "exited_effective_time IS NULL OR exited_effective_time >= entered_effective_time",
            name="ck_batch_stage_runs_exited_after_entered",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_batch_stage_runs_tenant_farm_batch",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "workflow_version_id", "workflow_stage_id"],
            ["workflow_stages.tenant_id", "workflow_stages.workflow_version_id", "workflow_stages.id"],
            name="fk_batch_stage_runs_stage",
        ),
    )
    op.create_index(
        "ux_batch_stage_runs_active_batch",
        "batch_stage_runs",
        ["batch_id"],
        unique=True,
        postgresql_where=sa.text("exited_effective_time IS NULL"),
    )

    # --- triggers ------------------------------------------------------------

    # batch_stage_transitions: workflow_version_id must match the batch's own
    # bound version — a cross-table check no CHECK constraint can express.
    op.execute(
        """
        CREATE FUNCTION enforce_batch_stage_transition_version_match() RETURNS trigger AS $$
        DECLARE
            batch_version_id UUID;
        BEGIN
            SELECT workflow_version_id INTO batch_version_id FROM crop_batches WHERE id = NEW.batch_id;
            IF batch_version_id IS NULL THEN
                RAISE EXCEPTION 'batch not found for stage transition';
            END IF;
            IF batch_version_id <> NEW.workflow_version_id THEN
                RAISE EXCEPTION 'stage transition workflow_version_id must match the batch''s bound version';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER batch_stage_transitions_enforce_version_match
        BEFORE INSERT ON batch_stage_transitions
        FOR EACH ROW EXECUTE FUNCTION enforce_batch_stage_transition_version_match();
        """
    )

    # batch_stage_transitions are fully immutable, insert-only history.
    op.execute(
        """
        CREATE FUNCTION reject_append_only_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only: % not permitted', TG_TABLE_NAME, TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER batch_stage_transitions_no_update
        BEFORE UPDATE ON batch_stage_transitions
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER batch_stage_transitions_no_delete
        BEFORE DELETE ON batch_stage_transitions
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )

    # batch_stage_runs: cross-row integrity a CHECK cannot express — must be
    # inserted active, workflow_version_id matches the batch, and the opening
    # transition's destination/batch match this run's own stage/batch.
    op.execute(
        """
        CREATE FUNCTION enforce_batch_stage_run_insert_integrity() RETURNS trigger AS $$
        DECLARE
            batch_version_id UUID;
            opening_dest_stage UUID;
            opening_batch UUID;
        BEGIN
            IF NEW.exited_effective_time IS NOT NULL OR NEW.closed_by_transition_id IS NOT NULL THEN
                RAISE EXCEPTION 'batch_stage_runs must be inserted as active';
            END IF;

            SELECT workflow_version_id INTO batch_version_id FROM crop_batches WHERE id = NEW.batch_id;
            IF batch_version_id IS NULL THEN
                RAISE EXCEPTION 'batch not found for stage run';
            END IF;
            IF batch_version_id <> NEW.workflow_version_id THEN
                RAISE EXCEPTION 'stage run workflow_version_id must match the batch''s bound version';
            END IF;

            SELECT destination_stage_id, batch_id INTO opening_dest_stage, opening_batch
            FROM batch_stage_transitions WHERE id = NEW.opened_by_transition_id;
            IF opening_dest_stage IS NULL THEN
                RAISE EXCEPTION 'opening transition not found';
            END IF;
            IF opening_batch <> NEW.batch_id THEN
                RAISE EXCEPTION 'opening transition batch mismatch';
            END IF;
            IF opening_dest_stage <> NEW.workflow_stage_id THEN
                RAISE EXCEPTION 'opening transition destination stage mismatch';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER batch_stage_runs_enforce_insert_integrity
        BEFORE INSERT ON batch_stage_runs
        FOR EACH ROW EXECUTE FUNCTION enforce_batch_stage_run_insert_integrity();
        """
    )

    # batch_stage_runs: the only permitted update is closing (both fields
    # together, from NULL, matching the closing transition's own source
    # stage/batch), and a closed run cannot be touched again.
    op.execute(
        """
        CREATE FUNCTION enforce_batch_stage_run_closure_only() RETURNS trigger AS $$
        DECLARE
            closing_src_stage UUID;
            closing_batch UUID;
        BEGIN
            IF OLD.exited_effective_time IS NOT NULL THEN
                RAISE EXCEPTION 'batch_stage_run is already closed and cannot be modified';
            END IF;

            IF NEW.tenant_id <> OLD.tenant_id
               OR NEW.farm_id <> OLD.farm_id
               OR NEW.batch_id <> OLD.batch_id
               OR NEW.workflow_version_id <> OLD.workflow_version_id
               OR NEW.workflow_stage_id <> OLD.workflow_stage_id
               OR NEW.entered_effective_time <> OLD.entered_effective_time
               OR NEW.opened_by_transition_id <> OLD.opened_by_transition_id
               OR NEW.actor_user_id <> OLD.actor_user_id
            THEN
                RAISE EXCEPTION 'only exited_effective_time and closed_by_transition_id may change when closing a batch_stage_run';
            END IF;

            IF NEW.exited_effective_time IS NULL OR NEW.closed_by_transition_id IS NULL THEN
                RAISE EXCEPTION 'closing a batch_stage_run requires both exited_effective_time and closed_by_transition_id';
            END IF;
            IF NEW.exited_effective_time < NEW.entered_effective_time THEN
                RAISE EXCEPTION 'exited_effective_time cannot precede entered_effective_time';
            END IF;

            SELECT source_stage_id, batch_id INTO closing_src_stage, closing_batch
            FROM batch_stage_transitions WHERE id = NEW.closed_by_transition_id;
            IF closing_src_stage IS NULL THEN
                RAISE EXCEPTION 'closing transition not found or has no source stage';
            END IF;
            IF closing_batch <> NEW.batch_id THEN
                RAISE EXCEPTION 'closing transition batch mismatch';
            END IF;
            IF closing_src_stage <> NEW.workflow_stage_id THEN
                RAISE EXCEPTION 'closing transition source stage mismatch';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER batch_stage_runs_enforce_closure_only
        BEFORE UPDATE ON batch_stage_runs
        FOR EACH ROW EXECUTE FUNCTION enforce_batch_stage_run_closure_only();
        """
    )

    # Hard-delete protection reusing the shared function from CMP-005.
    op.execute(
        """
        CREATE TRIGGER crop_batches_no_delete
        BEFORE DELETE ON crop_batches
        FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();
        """
    )
    op.execute(
        """
        CREATE TRIGGER batch_stage_runs_no_delete
        BEFORE DELETE ON batch_stage_runs
        FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();
        """
    )

    # crop_batches: identity/creation fields immutable; state moves only
    # active -> closed, and only while the batch's active stage run is
    # terminal, with closed_effective_time matching that run's entry time.
    op.execute(
        """
        CREATE FUNCTION enforce_crop_batch_lifecycle() RETURNS trigger AS $$
        DECLARE
            terminal_run_entered TIMESTAMPTZ;
        BEGIN
            IF NEW.tenant_id <> OLD.tenant_id
               OR NEW.farm_id <> OLD.farm_id
               OR NEW.code <> OLD.code
               OR NEW.workflow_id <> OLD.workflow_id
               OR NEW.workflow_version_id <> OLD.workflow_version_id
               OR NEW.created_by_user_id <> OLD.created_by_user_id
               OR NEW.created_effective_time <> OLD.created_effective_time
               OR NEW.client_command_id <> OLD.client_command_id
               OR NEW.request_fingerprint <> OLD.request_fingerprint
            THEN
                RAISE EXCEPTION 'crop_batch identity and creation fields are immutable';
            END IF;

            IF OLD.state = NEW.state THEN
                RAISE EXCEPTION 'crop_batches may only be updated to close the batch';
            END IF;

            IF NOT (OLD.state = 'active' AND NEW.state = 'closed') THEN
                RAISE EXCEPTION 'invalid crop_batch state transition: % -> %', OLD.state, NEW.state;
            END IF;

            SELECT r.entered_effective_time INTO terminal_run_entered
            FROM batch_stage_runs r
            JOIN workflow_stages s ON s.id = r.workflow_stage_id
            WHERE r.batch_id = NEW.id AND r.exited_effective_time IS NULL AND s.is_terminal = true;

            IF terminal_run_entered IS NULL THEN
                RAISE EXCEPTION 'crop_batch can only close while its active stage run is terminal';
            END IF;
            IF NEW.closed_effective_time <> terminal_run_entered THEN
                RAISE EXCEPTION 'closed_effective_time must match the terminal stage run entry time';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER crop_batches_enforce_lifecycle
        BEFORE UPDATE ON crop_batches
        FOR EACH ROW EXECUTE FUNCTION enforce_crop_batch_lifecycle();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS crop_batches_enforce_lifecycle ON crop_batches")
    op.execute("DROP FUNCTION IF EXISTS enforce_crop_batch_lifecycle()")

    op.execute("DROP TRIGGER IF EXISTS batch_stage_runs_no_delete ON batch_stage_runs")
    op.execute("DROP TRIGGER IF EXISTS crop_batches_no_delete ON crop_batches")

    op.execute("DROP TRIGGER IF EXISTS batch_stage_runs_enforce_closure_only ON batch_stage_runs")
    op.execute("DROP FUNCTION IF EXISTS enforce_batch_stage_run_closure_only()")

    op.execute("DROP TRIGGER IF EXISTS batch_stage_runs_enforce_insert_integrity ON batch_stage_runs")
    op.execute("DROP FUNCTION IF EXISTS enforce_batch_stage_run_insert_integrity()")

    op.execute("DROP TRIGGER IF EXISTS batch_stage_transitions_no_delete ON batch_stage_transitions")
    op.execute("DROP TRIGGER IF EXISTS batch_stage_transitions_no_update ON batch_stage_transitions")
    op.execute("DROP FUNCTION IF EXISTS reject_append_only_mutation()")

    op.execute(
        "DROP TRIGGER IF EXISTS batch_stage_transitions_enforce_version_match ON batch_stage_transitions"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_batch_stage_transition_version_match()")

    op.drop_index("ux_batch_stage_runs_active_batch", table_name="batch_stage_runs")
    op.drop_table("batch_stage_runs")

    op.drop_index("ux_batch_stage_transitions_one_initial_entry", table_name="batch_stage_transitions")
    op.drop_index("ux_batch_stage_transitions_tenant_kind_client_id", table_name="batch_stage_transitions")
    op.drop_table("batch_stage_transitions")

    op.drop_index("ux_crop_batches_tenant_client_command_id", table_name="crop_batches")
    op.drop_index("ux_crop_batches_tenant_code_lower", table_name="crop_batches")
    op.drop_table("crop_batches")

    op.drop_constraint(
        "uq_workflow_transitions_tenant_version_id", "workflow_transitions", type_="unique"
    )
    op.drop_constraint("uq_workflow_versions_tenant_workflow_id", "workflow_versions", type_="unique")
    op.drop_constraint("uq_farms_tenant_id_id", "farms", type_="unique")
