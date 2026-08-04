"""crop batch split and merge lineage foundation

Revision ID: a4d92f7c1e6b
Revises: f3a8c2e1b975
Create Date: 2026-08-04 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'a4d92f7c1e6b'
down_revision: Union[str, None] = 'f3a8c2e1b975'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- batch_derivation_events (immutable) --------------------------------------
    op.create_table(
        "batch_derivation_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("derivation_kind", sa.String(), nullable=False),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workflows.id"), nullable=False),
        sa.Column(
            "workflow_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workflow_versions.id"),
            nullable=False,
        ),
        sa.Column(
            "inherited_workflow_stage_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workflow_stages.id"),
            nullable=False,
        ),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.CheckConstraint("derivation_kind IN ('split', 'merge')", name="ck_batch_derivation_events_kind"),
        sa.UniqueConstraint(
            "tenant_id", "farm_id", "id", name="uq_batch_derivation_events_tenant_farm_id"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id"], ["farms.tenant_id", "farms.id"], name="fk_batch_derivation_events_tenant_farm"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "workflow_id", "workflow_version_id"],
            ["workflow_versions.tenant_id", "workflow_versions.workflow_id", "workflow_versions.id"],
            name="fk_batch_derivation_events_tenant_workflow_version",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "workflow_version_id", "inherited_workflow_stage_id"],
            ["workflow_stages.tenant_id", "workflow_stages.workflow_version_id", "workflow_stages.id"],
            name="fk_batch_derivation_events_inherited_stage",
        ),
    )
    op.create_index(
        "ux_batch_derivation_events_tenant_client_command_id",
        "batch_derivation_events",
        ["tenant_id", "client_command_id"],
        unique=True,
    )

    # --- crop_batches: derivation origin, supersession, conditional command ownership
    op.add_column(
        "crop_batches", sa.Column("superseded_effective_time", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "crop_batches",
        sa.Column("superseded_by_batch_derivation_event_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "crop_batches",
        sa.Column("created_by_batch_derivation_event_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.alter_column("crop_batches", "client_command_id", nullable=True)
    op.alter_column("crop_batches", "request_fingerprint", nullable=True)

    op.drop_constraint("ck_crop_batches_closed_time_matches_state", "crop_batches", type_="check")
    op.drop_constraint("ck_crop_batches_state", "crop_batches", type_="check")
    op.create_check_constraint(
        "ck_crop_batches_state", "crop_batches", "state IN ('active', 'closed', 'superseded')"
    )
    op.create_check_constraint(
        "ck_crop_batches_lifecycle_shape",
        "crop_batches",
        "(state = 'active' AND closed_effective_time IS NULL "
        "AND superseded_effective_time IS NULL AND superseded_by_batch_derivation_event_id IS NULL) OR "
        "(state = 'closed' AND closed_effective_time IS NOT NULL "
        "AND superseded_effective_time IS NULL AND superseded_by_batch_derivation_event_id IS NULL) OR "
        "(state = 'superseded' AND closed_effective_time IS NULL "
        "AND superseded_effective_time IS NOT NULL AND superseded_by_batch_derivation_event_id IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_crop_batches_superseded_after_created",
        "crop_batches",
        "superseded_effective_time IS NULL OR superseded_effective_time >= created_effective_time",
    )
    op.create_check_constraint(
        "ck_crop_batches_command_ownership_shape",
        "crop_batches",
        "(created_by_batch_derivation_event_id IS NULL) = (client_command_id IS NOT NULL) AND "
        "(created_by_batch_derivation_event_id IS NULL) = (request_fingerprint IS NOT NULL)",
    )
    op.create_foreign_key(
        "fk_crop_batches_created_by_derivation_event",
        "crop_batches",
        "batch_derivation_events",
        ["tenant_id", "farm_id", "created_by_batch_derivation_event_id"],
        ["tenant_id", "farm_id", "id"],
    )
    op.create_foreign_key(
        "fk_crop_batches_superseded_by_derivation_event",
        "crop_batches",
        "batch_derivation_events",
        ["tenant_id", "farm_id", "superseded_by_batch_derivation_event_id"],
        ["tenant_id", "farm_id", "id"],
    )

    # Replace the CMP-008 lifecycle trigger with a CMP-012 one that also
    # allows active -> superseded. The original CMP-008 function
    # (enforce_crop_batch_lifecycle) is left entirely untouched — only its
    # trigger attachment is dropped — so downgrade can restore it exactly.
    op.execute("DROP TRIGGER IF EXISTS crop_batches_enforce_lifecycle ON crop_batches")
    op.execute(
        """
        CREATE FUNCTION enforce_crop_batch_lifecycle_v2() RETURNS trigger AS $$
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
               OR NEW.created_by_batch_derivation_event_id IS DISTINCT FROM OLD.created_by_batch_derivation_event_id
               OR NEW.client_command_id IS DISTINCT FROM OLD.client_command_id
               OR NEW.request_fingerprint IS DISTINCT FROM OLD.request_fingerprint
            THEN
                RAISE EXCEPTION 'crop_batch identity and creation fields are immutable';
            END IF;

            IF OLD.state <> 'active' THEN
                RAISE EXCEPTION 'crop_batches may only be updated from the active state';
            END IF;

            IF NEW.state = 'closed' THEN
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
            ELSIF NEW.state = 'superseded' THEN
                IF NEW.superseded_effective_time IS NULL OR NEW.superseded_by_batch_derivation_event_id IS NULL THEN
                    RAISE EXCEPTION 'superseding a crop_batch requires both superseded_effective_time and superseded_by_batch_derivation_event_id';
                END IF;
            ELSE
                RAISE EXCEPTION 'invalid crop_batch state transition: % -> %', OLD.state, NEW.state;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER crop_batches_enforce_lifecycle_v2
        BEFORE UPDATE ON crop_batches
        FOR EACH ROW EXECUTE FUNCTION enforce_crop_batch_lifecycle_v2();
        """
    )

    # --- batch_stage_transitions: derivation_entry command kind --------------------
    op.add_column(
        "batch_stage_transitions",
        sa.Column("batch_derivation_event_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.alter_column("batch_stage_transitions", "client_command_id", nullable=True)
    op.alter_column("batch_stage_transitions", "request_fingerprint", nullable=True)

    op.drop_constraint("ck_batch_stage_transitions_shape", "batch_stage_transitions", type_="check")
    op.drop_constraint("ck_batch_stage_transitions_command_kind", "batch_stage_transitions", type_="check")
    op.create_check_constraint(
        "ck_batch_stage_transitions_command_kind",
        "batch_stage_transitions",
        "command_kind IN ('initial_entry', 'stage_transition', 'derivation_entry')",
    )
    op.create_check_constraint(
        "ck_batch_stage_transitions_shape",
        "batch_stage_transitions",
        "(command_kind = 'initial_entry' AND source_stage_id IS NULL AND configured_transition_id IS NULL "
        "AND batch_derivation_event_id IS NULL AND client_command_id IS NOT NULL "
        "AND request_fingerprint IS NOT NULL) OR "
        "(command_kind = 'stage_transition' AND source_stage_id IS NOT NULL "
        "AND configured_transition_id IS NOT NULL AND batch_derivation_event_id IS NULL "
        "AND client_command_id IS NOT NULL AND request_fingerprint IS NOT NULL) OR "
        "(command_kind = 'derivation_entry' AND source_stage_id IS NULL AND configured_transition_id IS NULL "
        "AND batch_derivation_event_id IS NOT NULL AND client_command_id IS NULL "
        "AND request_fingerprint IS NULL)",
    )
    op.create_index(
        "ux_batch_stage_transitions_one_derivation_entry",
        "batch_stage_transitions",
        ["batch_id"],
        unique=True,
        postgresql_where=sa.text("command_kind = 'derivation_entry'"),
    )
    op.create_foreign_key(
        "fk_batch_stage_transitions_derivation_event",
        "batch_stage_transitions",
        "batch_derivation_events",
        ["tenant_id", "farm_id", "batch_derivation_event_id"],
        ["tenant_id", "farm_id", "id"],
    )

    # --- batch_carrier_assignments: third opener, second releaser -------------------
    op.add_column(
        "batch_carrier_assignments",
        sa.Column("opening_batch_derivation_event_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "batch_carrier_assignments",
        sa.Column("released_by_batch_derivation_event_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.drop_constraint(
        "ck_batch_carrier_assignments_exactly_one_opener", "batch_carrier_assignments", type_="check"
    )
    op.drop_constraint(
        "ck_batch_carrier_assignments_release_fields_together", "batch_carrier_assignments", type_="check"
    )
    op.create_check_constraint(
        "ck_batch_carrier_assignments_exactly_one_opener",
        "batch_carrier_assignments",
        "(CASE WHEN opening_sowing_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN opening_transplant_event_id IS NOT NULL THEN 1 ELSE 0 END "
        "+ CASE WHEN opening_batch_derivation_event_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
    )
    op.create_check_constraint(
        "ck_batch_carrier_assignments_release_fields_together",
        "batch_carrier_assignments",
        "(released_effective_time IS NULL) = "
        "(released_by_transplant_event_id IS NULL AND released_by_batch_derivation_event_id IS NULL)",
    )
    op.create_check_constraint(
        "ck_batch_carrier_assignments_at_most_one_releaser",
        "batch_carrier_assignments",
        "NOT (released_by_transplant_event_id IS NOT NULL AND released_by_batch_derivation_event_id IS NOT NULL)",
    )
    op.create_foreign_key(
        "fk_batch_carrier_assignments_opening_derivation_event",
        "batch_carrier_assignments",
        "batch_derivation_events",
        ["tenant_id", "farm_id", "opening_batch_derivation_event_id"],
        ["tenant_id", "farm_id", "id"],
    )
    op.create_foreign_key(
        "fk_batch_carrier_assignments_released_by_derivation_event",
        "batch_carrier_assignments",
        "batch_derivation_events",
        ["tenant_id", "farm_id", "released_by_batch_derivation_event_id"],
        ["tenant_id", "farm_id", "id"],
    )

    # Replace the CMP-011 origin-insert-integrity trigger with a CMP-012 one
    # that also accepts a batch-derivation opener. The CMP-011 function
    # (enforce_batch_carrier_assignment_origin_insert_integrity) is left
    # entirely untouched — only its trigger attachment is dropped.
    op.execute(
        "DROP TRIGGER IF EXISTS batch_carrier_assignments_enforce_origin_insert_integrity "
        "ON batch_carrier_assignments"
    )
    op.execute(
        """
        CREATE FUNCTION enforce_batch_carrier_assignment_origin_insert_integrity_v2() RETURNS trigger AS $$
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
            ELSE
                SELECT effective_time INTO v_event_effective
                FROM batch_derivation_events WHERE id = NEW.opening_batch_derivation_event_id;
                IF v_event_effective IS NULL THEN
                    RAISE EXCEPTION 'opening batch derivation event not found';
                END IF;
                IF v_event_effective <> NEW.assigned_effective_time THEN
                    RAISE EXCEPTION 'assigned_effective_time must match the opening derivation event''s effective time';
                END IF;

                SELECT created_by_batch_derivation_event_id INTO v_batch_created_by
                FROM crop_batches WHERE id = NEW.batch_id;
                IF v_batch_created_by IS DISTINCT FROM NEW.opening_batch_derivation_event_id THEN
                    RAISE EXCEPTION 'destination batch was not created by this derivation event';
                END IF;

                SELECT t.command_kind, t.batch_derivation_event_id INTO v_run_kind, v_run_event
                FROM batch_stage_runs r JOIN batch_stage_transitions t ON t.id = r.opened_by_transition_id
                WHERE r.id = NEW.batch_stage_run_id;
                IF v_run_kind IS DISTINCT FROM 'derivation_entry'
                   OR v_run_event IS DISTINCT FROM NEW.opening_batch_derivation_event_id THEN
                    RAISE EXCEPTION 'destination stage run was not opened by this derivation event''s entry transition';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER batch_carrier_assignments_enforce_origin_insert_integrity_v2
        BEFORE INSERT ON batch_carrier_assignments
        FOR EACH ROW EXECUTE FUNCTION enforce_batch_carrier_assignment_origin_insert_integrity_v2();
        """
    )

    # Replace the CMP-011 closure-only trigger with a CMP-012 one that also
    # accepts a batch-derivation releaser (any origin, unlike transplant
    # release which remains sowing-origin-only). The CMP-011 function
    # (enforce_batch_carrier_assignment_closure_only) is left untouched.
    op.execute(
        "DROP TRIGGER IF EXISTS batch_carrier_assignments_enforce_closure_only ON batch_carrier_assignments"
    )
    op.execute(
        """
        CREATE FUNCTION enforce_batch_carrier_assignment_closure_only_v2() RETURNS trigger AS $$
        DECLARE
            v_source_line_event UUID;
            v_source_line_carrier UUID;
            v_transplant_batch_id UUID;
            v_transplant_effective TIMESTAMPTZ;
            v_derivation_effective TIMESTAMPTZ;
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
               OR NEW.actor_user_id <> OLD.actor_user_id
            THEN
                RAISE EXCEPTION 'only released_effective_time, released_by_transplant_event_id, and released_by_batch_derivation_event_id may change when releasing a batch_carrier_assignment';
            END IF;

            IF NEW.released_effective_time IS NULL
               OR (NEW.released_by_transplant_event_id IS NULL AND NEW.released_by_batch_derivation_event_id IS NULL)
            THEN
                RAISE EXCEPTION 'releasing a batch_carrier_assignment requires released_effective_time and exactly one typed releaser';
            END IF;

            IF NEW.released_by_transplant_event_id IS NOT NULL THEN
                IF NEW.opening_sowing_event_id IS NULL THEN
                    RAISE EXCEPTION 'only sowing-origin assignments may be released by transplantation';
                END IF;

                SELECT batch_id, effective_time INTO v_transplant_batch_id, v_transplant_effective
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

                SELECT transplant_event_id, source_carrier_id INTO v_source_line_event, v_source_line_carrier
                FROM transplant_source_lines WHERE source_batch_carrier_assignment_id = NEW.id;
                IF v_source_line_event IS NULL THEN
                    RAISE EXCEPTION 'no transplant source line found for this assignment';
                END IF;
                IF v_source_line_event <> NEW.released_by_transplant_event_id THEN
                    RAISE EXCEPTION 'source line event does not match released_by_transplant_event_id';
                END IF;
                IF v_source_line_carrier <> NEW.carrier_id THEN
                    RAISE EXCEPTION 'source line carrier does not match assignment carrier';
                END IF;
            ELSE
                -- Unlike the transplant-release branch above, the matching
                -- batch_assignment_transfers row cannot be required to exist
                -- yet: the destination assignment (and therefore the
                -- transfer row, which references it) can only be inserted
                -- for this carrier *after* this same release frees the
                -- carrier's "one active assignment" slot. Full cross-table
                -- linkage (transfer exists, carrier/batch match, quantities
                -- reconcile) is proven by the deferred reconciliation
                -- trigger at commit instead.
                SELECT effective_time INTO v_derivation_effective
                FROM batch_derivation_events WHERE id = NEW.released_by_batch_derivation_event_id;
                IF v_derivation_effective IS NULL THEN
                    RAISE EXCEPTION 'releasing batch derivation event not found';
                END IF;
                IF v_derivation_effective <> NEW.released_effective_time THEN
                    RAISE EXCEPTION 'released_effective_time must match the releasing derivation event''s effective time';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER batch_carrier_assignments_enforce_closure_only_v2
        BEFORE UPDATE ON batch_carrier_assignments
        FOR EACH ROW EXECUTE FUNCTION enforce_batch_carrier_assignment_closure_only_v2();
        """
    )

    # --- batch_derivation_sources / outputs / batch_assignment_transfers -----------
    op.create_table(
        "batch_derivation_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column(
            "derivation_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("batch_derivation_events.id"),
            nullable=False,
        ),
        sa.Column("source_batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("crop_batches.id"), nullable=False),
        sa.Column(
            "source_batch_stage_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("batch_stage_runs.id"),
            nullable=False,
        ),
        sa.Column("recorded_plant_quantity_total", sa.Integer(), nullable=False),
        sa.Column("recorded_carrier_assignment_count", sa.Integer(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "recorded_plant_quantity_total >= 0", name="ck_batch_derivation_sources_quantity_non_negative"
        ),
        sa.CheckConstraint(
            "recorded_carrier_assignment_count >= 0",
            name="ck_batch_derivation_sources_assignment_count_non_negative",
        ),
        sa.UniqueConstraint("source_batch_id", name="ux_batch_derivation_sources_source_batch"),
        sa.UniqueConstraint(
            "derivation_event_id", "source_batch_id", name="ux_batch_derivation_sources_event_source_batch"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "derivation_event_id"],
            [
                "batch_derivation_events.tenant_id", "batch_derivation_events.farm_id",
                "batch_derivation_events.id",
            ],
            name="fk_batch_derivation_sources_tenant_farm_event",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "source_batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_batch_derivation_sources_tenant_farm_batch",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "source_batch_id", "source_batch_stage_run_id"],
            [
                "batch_stage_runs.tenant_id", "batch_stage_runs.farm_id", "batch_stage_runs.batch_id",
                "batch_stage_runs.id",
            ],
            name="fk_batch_derivation_sources_stage_run",
        ),
    )
    op.execute(
        """
        CREATE TRIGGER batch_derivation_sources_no_update
        BEFORE UPDATE ON batch_derivation_sources
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER batch_derivation_sources_no_delete
        BEFORE DELETE ON batch_derivation_sources
        FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();
        """
    )

    op.create_table(
        "batch_derivation_outputs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column(
            "derivation_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("batch_derivation_events.id"),
            nullable=False,
        ),
        sa.Column("output_batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("crop_batches.id"), nullable=False),
        sa.Column("recorded_plant_quantity_total", sa.Integer(), nullable=False),
        sa.Column("recorded_carrier_assignment_count", sa.Integer(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "recorded_plant_quantity_total > 0", name="ck_batch_derivation_outputs_quantity_positive"
        ),
        sa.CheckConstraint(
            "recorded_carrier_assignment_count > 0",
            name="ck_batch_derivation_outputs_assignment_count_positive",
        ),
        sa.UniqueConstraint("output_batch_id", name="ux_batch_derivation_outputs_output_batch"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "derivation_event_id"],
            [
                "batch_derivation_events.tenant_id", "batch_derivation_events.farm_id",
                "batch_derivation_events.id",
            ],
            name="fk_batch_derivation_outputs_tenant_farm_event",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "output_batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_batch_derivation_outputs_tenant_farm_batch",
        ),
    )
    op.execute(
        """
        CREATE TRIGGER batch_derivation_outputs_no_update
        BEFORE UPDATE ON batch_derivation_outputs
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER batch_derivation_outputs_no_delete
        BEFORE DELETE ON batch_derivation_outputs
        FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();
        """
    )

    op.create_table(
        "batch_assignment_transfers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column(
            "derivation_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("batch_derivation_events.id"),
            nullable=False,
        ),
        sa.Column("source_batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("crop_batches.id"), nullable=False),
        sa.Column("output_batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("crop_batches.id"), nullable=False),
        sa.Column("carrier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("carriers.id"), nullable=False),
        sa.Column(
            "released_source_assignment_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("batch_carrier_assignments.id"), nullable=False,
        ),
        sa.Column(
            "opened_destination_assignment_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("batch_carrier_assignments.id"), nullable=False,
        ),
        sa.Column("transferred_plant_count", sa.Integer(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("transferred_plant_count > 0", name="ck_batch_assignment_transfers_count_positive"),
        sa.UniqueConstraint(
            "released_source_assignment_id", name="ux_batch_assignment_transfers_source_assignment"
        ),
        sa.UniqueConstraint(
            "opened_destination_assignment_id", name="ux_batch_assignment_transfers_destination_assignment"
        ),
        sa.UniqueConstraint(
            "derivation_event_id", "carrier_id", name="ux_batch_assignment_transfers_event_carrier"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "derivation_event_id"],
            [
                "batch_derivation_events.tenant_id", "batch_derivation_events.farm_id",
                "batch_derivation_events.id",
            ],
            name="fk_batch_assignment_transfers_tenant_farm_event",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "source_batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_batch_assignment_transfers_tenant_farm_source_batch",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "output_batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_batch_assignment_transfers_tenant_farm_output_batch",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "carrier_id"],
            ["carriers.tenant_id", "carriers.farm_id", "carriers.id"],
            name="fk_batch_assignment_transfers_tenant_farm_carrier",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "released_source_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id", "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_batch_assignment_transfers_source_assignment",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "opened_destination_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id", "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_batch_assignment_transfers_destination_assignment",
        ),
    )

    op.execute(
        """
        CREATE FUNCTION enforce_batch_assignment_transfer_insert_integrity() RETURNS trigger AS $$
        DECLARE
            v_source_opening_sowing UUID;
            v_source_opening_transplant UUID;
            v_source_carrier UUID;
            v_source_released_by_derivation UUID;
            v_source_released_effective TIMESTAMPTZ;
            v_origin_quantity INTEGER;
            v_dest_opening_derivation UUID;
            v_dest_carrier UUID;
            v_dest_assigned_effective TIMESTAMPTZ;
            v_event_effective TIMESTAMPTZ;
        BEGIN
            SELECT effective_time INTO v_event_effective FROM batch_derivation_events WHERE id = NEW.derivation_event_id;
            IF v_event_effective IS NULL THEN
                RAISE EXCEPTION 'derivation event not found';
            END IF;

            -- The source assignment must already be released by this event
            -- (release happens before the transfer row is inserted — the
            -- reverse of CMP-011's transplant_source_lines ordering — because
            -- the destination assignment reuses the same physical carrier,
            -- and the "one active assignment per carrier" partial unique
            -- index is not deferrable, so the old row must already be
            -- released before the new one can be inserted).
            SELECT opening_sowing_event_id, opening_transplant_event_id, carrier_id,
                   released_by_batch_derivation_event_id, released_effective_time
            INTO v_source_opening_sowing, v_source_opening_transplant, v_source_carrier,
                 v_source_released_by_derivation, v_source_released_effective
            FROM batch_carrier_assignments WHERE id = NEW.released_source_assignment_id;
            IF v_source_carrier IS NULL THEN
                RAISE EXCEPTION 'released source assignment not found';
            END IF;
            IF v_source_carrier <> NEW.carrier_id THEN
                RAISE EXCEPTION 'transfer carrier does not match source assignment carrier';
            END IF;
            IF v_source_released_by_derivation IS DISTINCT FROM NEW.derivation_event_id
               OR v_source_released_effective IS DISTINCT FROM v_event_effective THEN
                RAISE EXCEPTION 'source assignment was not released by this derivation event';
            END IF;

            IF v_source_opening_sowing IS NOT NULL THEN
                SELECT sown_site_count INTO v_origin_quantity FROM sowing_event_lines
                WHERE batch_carrier_assignment_id = NEW.released_source_assignment_id;
            ELSIF v_source_opening_transplant IS NOT NULL THEN
                SELECT assigned_plant_count INTO v_origin_quantity FROM transplant_destination_lines
                WHERE destination_batch_carrier_assignment_id = NEW.released_source_assignment_id;
            ELSE
                SELECT transferred_plant_count INTO v_origin_quantity FROM batch_assignment_transfers
                WHERE opened_destination_assignment_id = NEW.released_source_assignment_id;
            END IF;
            IF v_origin_quantity IS NULL THEN
                RAISE EXCEPTION 'no resolvable origin quantity for source assignment';
            END IF;
            IF NEW.transferred_plant_count <> v_origin_quantity THEN
                RAISE EXCEPTION 'transferred_plant_count must equal the source assignment''s immutable origin quantity';
            END IF;

            SELECT opening_batch_derivation_event_id, carrier_id, assigned_effective_time
            INTO v_dest_opening_derivation, v_dest_carrier, v_dest_assigned_effective
            FROM batch_carrier_assignments WHERE id = NEW.opened_destination_assignment_id;
            IF v_dest_carrier IS NULL THEN
                RAISE EXCEPTION 'opened destination assignment not found';
            END IF;
            IF v_dest_opening_derivation IS DISTINCT FROM NEW.derivation_event_id THEN
                RAISE EXCEPTION 'destination assignment was not opened by this derivation event';
            END IF;
            IF v_dest_carrier <> NEW.carrier_id THEN
                RAISE EXCEPTION 'transfer carrier does not match destination assignment carrier';
            END IF;
            IF v_dest_assigned_effective IS DISTINCT FROM v_event_effective THEN
                RAISE EXCEPTION 'destination assignment effective time mismatch';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER batch_assignment_transfers_enforce_insert_integrity
        BEFORE INSERT ON batch_assignment_transfers
        FOR EACH ROW EXECUTE FUNCTION enforce_batch_assignment_transfer_insert_integrity();
        """
    )
    op.execute(
        """
        CREATE TRIGGER batch_assignment_transfers_no_update
        BEFORE UPDATE ON batch_assignment_transfers
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER batch_assignment_transfers_no_delete
        BEFORE DELETE ON batch_assignment_transfers
        FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();
        """
    )
    op.execute(
        """
        CREATE TRIGGER batch_derivation_events_no_update
        BEFORE UPDATE ON batch_derivation_events
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER batch_derivation_events_no_delete
        BEFORE DELETE ON batch_derivation_events
        FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();
        """
    )

    # --- deferred reconciliation ----------------------------------------------------
    # One shared function, resolved per firing table/operation, attached via
    # ten DEFERRABLE INITIALLY DEFERRED constraint triggers so that ANY
    # insert or update touching a derivation event's lineage — even direct
    # SQL against an already-committed event, in a later transaction —
    # re-validates that event's complete reconciled state at commit time.
    op.execute(
        """
        CREATE FUNCTION enforce_batch_derivation_reconciliation() RETURNS trigger AS $$
        DECLARE
            v_event_id UUID;
            v_kind TEXT;
            v_workflow_version_id UUID;
            v_inherited_stage_id UUID;
            v_source_count INTEGER;
            v_output_count INTEGER;
            v_transfer_count INTEGER;
            v_bad_count INTEGER;
        BEGIN
            IF TG_TABLE_NAME = 'batch_derivation_events' THEN
                v_event_id := NEW.id;
            ELSIF TG_TABLE_NAME = 'batch_derivation_sources' THEN
                v_event_id := NEW.derivation_event_id;
            ELSIF TG_TABLE_NAME = 'batch_derivation_outputs' THEN
                v_event_id := NEW.derivation_event_id;
            ELSIF TG_TABLE_NAME = 'batch_assignment_transfers' THEN
                v_event_id := NEW.derivation_event_id;
            ELSIF TG_TABLE_NAME = 'crop_batches' THEN
                IF TG_OP = 'INSERT' THEN
                    v_event_id := NEW.created_by_batch_derivation_event_id;
                ELSE
                    v_event_id := NEW.superseded_by_batch_derivation_event_id;
                END IF;
            ELSIF TG_TABLE_NAME = 'batch_stage_transitions' THEN
                v_event_id := NEW.batch_derivation_event_id;
            ELSIF TG_TABLE_NAME = 'batch_stage_runs' THEN
                SELECT batch_derivation_event_id INTO v_event_id
                FROM batch_stage_transitions WHERE id = NEW.opened_by_transition_id;
            ELSIF TG_TABLE_NAME = 'batch_carrier_assignments' THEN
                IF TG_OP = 'INSERT' THEN
                    v_event_id := NEW.opening_batch_derivation_event_id;
                ELSE
                    v_event_id := NEW.released_by_batch_derivation_event_id;
                END IF;
            END IF;

            IF v_event_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT derivation_kind, workflow_version_id, inherited_workflow_stage_id
            INTO v_kind, v_workflow_version_id, v_inherited_stage_id
            FROM batch_derivation_events WHERE id = v_event_id;

            SELECT count(*) INTO v_source_count FROM batch_derivation_sources WHERE derivation_event_id = v_event_id;
            SELECT count(*) INTO v_output_count FROM batch_derivation_outputs WHERE derivation_event_id = v_event_id;
            SELECT count(*) INTO v_transfer_count FROM batch_assignment_transfers WHERE derivation_event_id = v_event_id;

            IF v_kind = 'split' THEN
                IF v_source_count <> 1 THEN
                    RAISE EXCEPTION 'derivation event % (split) must have exactly one source', v_event_id;
                END IF;
                IF v_output_count < 2 THEN
                    RAISE EXCEPTION 'derivation event % (split) must have at least two outputs', v_event_id;
                END IF;
            ELSE
                IF v_source_count < 2 THEN
                    RAISE EXCEPTION 'derivation event % (merge) must have at least two sources', v_event_id;
                END IF;
                IF v_output_count <> 1 THEN
                    RAISE EXCEPTION 'derivation event % (merge) must have exactly one output', v_event_id;
                END IF;
            END IF;

            IF v_transfer_count = 0 THEN
                RAISE EXCEPTION 'derivation event % has no assignment transfers', v_event_id;
            END IF;

            SELECT count(*) INTO v_bad_count
            FROM batch_derivation_sources s
            JOIN crop_batches b ON b.id = s.source_batch_id
            WHERE s.derivation_event_id = v_event_id
              AND (b.state <> 'superseded' OR b.superseded_by_batch_derivation_event_id <> v_event_id);
            IF v_bad_count > 0 THEN
                RAISE EXCEPTION 'derivation event % has a source batch not superseded by this event', v_event_id;
            END IF;

            SELECT count(*) INTO v_bad_count
            FROM batch_derivation_sources s
            WHERE s.derivation_event_id = v_event_id
              AND EXISTS (
                  SELECT 1 FROM batch_carrier_assignments a
                  WHERE a.batch_id = s.source_batch_id AND a.released_effective_time IS NULL
              );
            IF v_bad_count > 0 THEN
                RAISE EXCEPTION 'derivation event % left an active assignment under a superseded source batch', v_event_id;
            END IF;

            SELECT count(*) INTO v_bad_count
            FROM batch_derivation_outputs o
            JOIN crop_batches b ON b.id = o.output_batch_id
            WHERE o.derivation_event_id = v_event_id
              AND (
                  b.created_by_batch_derivation_event_id <> v_event_id
                  OR b.workflow_version_id <> v_workflow_version_id
                  OR b.state <> 'active'
              );
            IF v_bad_count > 0 THEN
                RAISE EXCEPTION 'derivation event % has an output batch with mismatched origin or workflow version', v_event_id;
            END IF;

            SELECT count(*) INTO v_bad_count
            FROM batch_derivation_outputs o
            WHERE o.derivation_event_id = v_event_id
              AND (SELECT count(*) FROM batch_stage_transitions t
                   WHERE t.batch_id = o.output_batch_id AND t.command_kind = 'derivation_entry') <> 1;
            IF v_bad_count > 0 THEN
                RAISE EXCEPTION 'derivation event % has an output batch without exactly one derivation-entry transition', v_event_id;
            END IF;

            SELECT count(*) INTO v_bad_count
            FROM batch_derivation_outputs o
            WHERE o.derivation_event_id = v_event_id
              AND NOT EXISTS (
                  SELECT 1 FROM batch_stage_runs r
                  JOIN batch_stage_transitions t ON t.id = r.opened_by_transition_id
                  WHERE r.batch_id = o.output_batch_id AND r.exited_effective_time IS NULL
                    AND t.command_kind = 'derivation_entry' AND t.batch_derivation_event_id = v_event_id
                    AND r.workflow_stage_id = v_inherited_stage_id
              );
            IF v_bad_count > 0 THEN
                RAISE EXCEPTION 'derivation event % has an output batch without a correctly opened active stage run', v_event_id;
            END IF;

            SELECT count(*) INTO v_bad_count
            FROM batch_derivation_outputs o
            WHERE o.derivation_event_id = v_event_id
              AND NOT EXISTS (
                  SELECT 1 FROM batch_carrier_assignments a
                  WHERE a.batch_id = o.output_batch_id AND a.released_effective_time IS NULL
              );
            IF v_bad_count > 0 THEN
                RAISE EXCEPTION 'derivation event % has an output batch with no active destination assignment', v_event_id;
            END IF;

            SELECT count(*) INTO v_bad_count
            FROM batch_derivation_sources s
            WHERE s.derivation_event_id = v_event_id
              AND (
                  s.recorded_plant_quantity_total <> COALESCE(
                      (SELECT sum(t.transferred_plant_count) FROM batch_assignment_transfers t
                       WHERE t.derivation_event_id = v_event_id AND t.source_batch_id = s.source_batch_id), 0)
                  OR s.recorded_carrier_assignment_count <> COALESCE(
                      (SELECT count(*) FROM batch_assignment_transfers t
                       WHERE t.derivation_event_id = v_event_id AND t.source_batch_id = s.source_batch_id), 0)
              );
            IF v_bad_count > 0 THEN
                RAISE EXCEPTION 'derivation event % has an unreconciled source total', v_event_id;
            END IF;

            SELECT count(*) INTO v_bad_count
            FROM batch_derivation_outputs o
            WHERE o.derivation_event_id = v_event_id
              AND (
                  o.recorded_plant_quantity_total <> COALESCE(
                      (SELECT sum(t.transferred_plant_count) FROM batch_assignment_transfers t
                       WHERE t.derivation_event_id = v_event_id AND t.output_batch_id = o.output_batch_id), 0)
                  OR o.recorded_carrier_assignment_count <> COALESCE(
                      (SELECT count(*) FROM batch_assignment_transfers t
                       WHERE t.derivation_event_id = v_event_id AND t.output_batch_id = o.output_batch_id), 0)
              );
            IF v_bad_count > 0 THEN
                RAISE EXCEPTION 'derivation event % has an unreconciled output total', v_event_id;
            END IF;

            IF (SELECT COALESCE(sum(recorded_plant_quantity_total), 0) FROM batch_derivation_sources WHERE derivation_event_id = v_event_id)
               <> (SELECT COALESCE(sum(recorded_plant_quantity_total), 0) FROM batch_derivation_outputs WHERE derivation_event_id = v_event_id)
            THEN
                RAISE EXCEPTION 'derivation event % source and output plant totals do not reconcile', v_event_id;
            END IF;

            -- Reverse direction: every FK-side reference to this event must
            -- have a matching lineage row — proves no extra batch,
            -- transition, run, or assignment references the event via
            -- direct SQL without the corresponding batch_derivation_sources/
            -- outputs/transfers row that would make it legitimate.
            SELECT count(*) INTO v_bad_count
            FROM crop_batches WHERE created_by_batch_derivation_event_id = v_event_id;
            IF v_bad_count <> v_output_count THEN
                RAISE EXCEPTION 'derivation event % has an extra crop batch created without a matching output line', v_event_id;
            END IF;

            SELECT count(*) INTO v_bad_count
            FROM crop_batches WHERE superseded_by_batch_derivation_event_id = v_event_id;
            IF v_bad_count <> v_source_count THEN
                RAISE EXCEPTION 'derivation event % has an extra superseded crop batch without a matching source line', v_event_id;
            END IF;

            SELECT count(*) INTO v_bad_count
            FROM batch_stage_transitions WHERE batch_derivation_event_id = v_event_id;
            IF v_bad_count <> v_output_count THEN
                RAISE EXCEPTION 'derivation event % has an extra derivation-entry transition without a matching output line', v_event_id;
            END IF;

            SELECT count(*) INTO v_bad_count
            FROM batch_stage_runs r
            JOIN batch_stage_transitions t ON t.id = r.opened_by_transition_id
            WHERE t.batch_derivation_event_id = v_event_id;
            IF v_bad_count <> v_output_count THEN
                RAISE EXCEPTION 'derivation event % has an extra stage run opened by one of its derivation-entry transitions', v_event_id;
            END IF;

            SELECT count(*) INTO v_bad_count
            FROM batch_carrier_assignments WHERE opening_batch_derivation_event_id = v_event_id;
            IF v_bad_count <> v_transfer_count THEN
                RAISE EXCEPTION 'derivation event % has an extra opened assignment without a matching transfer', v_event_id;
            END IF;

            SELECT count(*) INTO v_bad_count
            FROM batch_carrier_assignments WHERE released_by_batch_derivation_event_id = v_event_id;
            IF v_bad_count <> v_transfer_count THEN
                RAISE EXCEPTION 'derivation event % has an extra released assignment without a matching transfer', v_event_id;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER batch_derivation_events_enforce_reconciliation
        AFTER INSERT ON batch_derivation_events
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_batch_derivation_reconciliation();
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER batch_derivation_sources_enforce_reconciliation
        AFTER INSERT ON batch_derivation_sources
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_batch_derivation_reconciliation();
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER batch_derivation_outputs_enforce_reconciliation
        AFTER INSERT ON batch_derivation_outputs
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_batch_derivation_reconciliation();
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER batch_assignment_transfers_enforce_reconciliation
        AFTER INSERT ON batch_assignment_transfers
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_batch_derivation_reconciliation();
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER crop_batches_enforce_derivation_reconciliation_on_create
        AFTER INSERT ON crop_batches
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW WHEN (NEW.created_by_batch_derivation_event_id IS NOT NULL)
        EXECUTE FUNCTION enforce_batch_derivation_reconciliation();
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER crop_batches_enforce_derivation_reconciliation_on_supersede
        AFTER UPDATE ON crop_batches
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW WHEN (
            OLD.superseded_by_batch_derivation_event_id IS NULL
            AND NEW.superseded_by_batch_derivation_event_id IS NOT NULL
        )
        EXECUTE FUNCTION enforce_batch_derivation_reconciliation();
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER batch_stage_transitions_enforce_derivation_reconciliation
        AFTER INSERT ON batch_stage_transitions
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW WHEN (NEW.command_kind = 'derivation_entry')
        EXECUTE FUNCTION enforce_batch_derivation_reconciliation();
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER batch_stage_runs_enforce_derivation_reconciliation
        AFTER INSERT ON batch_stage_runs
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_batch_derivation_reconciliation();
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER batch_carrier_assignments_enforce_reconcile_bde_on_open
        AFTER INSERT ON batch_carrier_assignments
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW WHEN (NEW.opening_batch_derivation_event_id IS NOT NULL)
        EXECUTE FUNCTION enforce_batch_derivation_reconciliation();
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER batch_carrier_assignments_enforce_reconcile_bde_on_release
        AFTER UPDATE ON batch_carrier_assignments
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW WHEN (
            OLD.released_by_batch_derivation_event_id IS NULL
            AND NEW.released_by_batch_derivation_event_id IS NOT NULL
        )
        EXECUTE FUNCTION enforce_batch_derivation_reconciliation();
        """
    )


def downgrade() -> None:
    bind = op.get_bind()

    # --- downgrade guard: never corrupt or silently discard CMP-012 history ------
    unsafe = bind.execute(
        sa.text(
            "SELECT "
            "(SELECT count(*) FROM batch_derivation_events) AS event_count, "
            "(SELECT count(*) FROM crop_batches WHERE created_by_batch_derivation_event_id IS NOT NULL) "
            "AS created_count, "
            "(SELECT count(*) FROM crop_batches WHERE superseded_by_batch_derivation_event_id IS NOT NULL) "
            "AS superseded_count, "
            "(SELECT count(*) FROM batch_stage_transitions WHERE command_kind = 'derivation_entry') "
            "AS derivation_entry_count, "
            "(SELECT count(*) FROM batch_carrier_assignments WHERE opening_batch_derivation_event_id IS NOT NULL) "
            "AS opened_count, "
            "(SELECT count(*) FROM batch_carrier_assignments WHERE released_by_batch_derivation_event_id IS NOT NULL) "
            "AS released_count"
        )
    ).mappings().first()
    if (
        unsafe["event_count"] > 0
        or unsafe["created_count"] > 0
        or unsafe["superseded_count"] > 0
        or unsafe["derivation_entry_count"] > 0
        or unsafe["opened_count"] > 0
        or unsafe["released_count"] > 0
    ):
        raise RuntimeError(
            "Cannot downgrade past CMP-012: batch derivation events, derivation-created or "
            "superseded crop batches, derivation-entry stage transitions, or derivation-opened/"
            "released carrier assignments exist. Downgrading would corrupt or silently discard "
            "this production history. Remove or migrate the offending data out-of-band before "
            "downgrading, or do not downgrade."
        )

    op.execute(
        "DROP TRIGGER IF EXISTS batch_carrier_assignments_enforce_reconcile_bde_on_release "
        "ON batch_carrier_assignments"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS batch_carrier_assignments_enforce_reconcile_bde_on_open "
        "ON batch_carrier_assignments"
    )
    op.execute("DROP TRIGGER IF EXISTS batch_stage_runs_enforce_derivation_reconciliation ON batch_stage_runs")
    op.execute(
        "DROP TRIGGER IF EXISTS batch_stage_transitions_enforce_derivation_reconciliation "
        "ON batch_stage_transitions"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS crop_batches_enforce_derivation_reconciliation_on_supersede ON crop_batches"
    )
    op.execute("DROP TRIGGER IF EXISTS crop_batches_enforce_derivation_reconciliation_on_create ON crop_batches")
    op.execute(
        "DROP TRIGGER IF EXISTS batch_assignment_transfers_enforce_reconciliation ON batch_assignment_transfers"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS batch_derivation_outputs_enforce_reconciliation ON batch_derivation_outputs"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS batch_derivation_sources_enforce_reconciliation ON batch_derivation_sources"
    )
    op.execute("DROP TRIGGER IF EXISTS batch_derivation_events_enforce_reconciliation ON batch_derivation_events")
    op.execute("DROP FUNCTION IF EXISTS enforce_batch_derivation_reconciliation()")

    op.execute("DROP TRIGGER IF EXISTS batch_derivation_events_no_delete ON batch_derivation_events")
    op.execute("DROP TRIGGER IF EXISTS batch_derivation_events_no_update ON batch_derivation_events")

    op.execute("DROP TRIGGER IF EXISTS batch_assignment_transfers_no_delete ON batch_assignment_transfers")
    op.execute("DROP TRIGGER IF EXISTS batch_assignment_transfers_no_update ON batch_assignment_transfers")
    op.execute(
        "DROP TRIGGER IF EXISTS batch_assignment_transfers_enforce_insert_integrity ON batch_assignment_transfers"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_batch_assignment_transfer_insert_integrity()")
    op.drop_table("batch_assignment_transfers")

    op.execute("DROP TRIGGER IF EXISTS batch_derivation_outputs_no_delete ON batch_derivation_outputs")
    op.execute("DROP TRIGGER IF EXISTS batch_derivation_outputs_no_update ON batch_derivation_outputs")
    op.drop_table("batch_derivation_outputs")

    op.execute("DROP TRIGGER IF EXISTS batch_derivation_sources_no_delete ON batch_derivation_sources")
    op.execute("DROP TRIGGER IF EXISTS batch_derivation_sources_no_update ON batch_derivation_sources")
    op.drop_table("batch_derivation_sources")

    # Restore the CMP-011 closure/origin-insert-integrity triggers pointing
    # at their original, never-modified functions.
    op.execute(
        "DROP TRIGGER IF EXISTS batch_carrier_assignments_enforce_closure_only_v2 ON batch_carrier_assignments"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_batch_carrier_assignment_closure_only_v2()")
    op.execute(
        """
        CREATE TRIGGER batch_carrier_assignments_enforce_closure_only
        BEFORE UPDATE ON batch_carrier_assignments
        FOR EACH ROW EXECUTE FUNCTION enforce_batch_carrier_assignment_closure_only();
        """
    )

    op.execute(
        "DROP TRIGGER IF EXISTS batch_carrier_assignments_enforce_origin_insert_integrity_v2 "
        "ON batch_carrier_assignments"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_batch_carrier_assignment_origin_insert_integrity_v2()")
    op.execute(
        """
        CREATE TRIGGER batch_carrier_assignments_enforce_origin_insert_integrity
        BEFORE INSERT ON batch_carrier_assignments
        FOR EACH ROW EXECUTE FUNCTION enforce_batch_carrier_assignment_origin_insert_integrity();
        """
    )

    op.drop_constraint(
        "fk_batch_carrier_assignments_released_by_derivation_event", "batch_carrier_assignments", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_batch_carrier_assignments_opening_derivation_event", "batch_carrier_assignments", type_="foreignkey"
    )
    op.drop_constraint(
        "ck_batch_carrier_assignments_at_most_one_releaser", "batch_carrier_assignments", type_="check"
    )
    op.drop_constraint(
        "ck_batch_carrier_assignments_release_fields_together", "batch_carrier_assignments", type_="check"
    )
    op.drop_constraint(
        "ck_batch_carrier_assignments_exactly_one_opener", "batch_carrier_assignments", type_="check"
    )
    op.create_check_constraint(
        "ck_batch_carrier_assignments_release_fields_together",
        "batch_carrier_assignments",
        "(released_effective_time IS NULL) = (released_by_transplant_event_id IS NULL)",
    )
    op.create_check_constraint(
        "ck_batch_carrier_assignments_exactly_one_opener",
        "batch_carrier_assignments",
        "(opening_sowing_event_id IS NOT NULL) <> (opening_transplant_event_id IS NOT NULL)",
    )
    op.drop_column("batch_carrier_assignments", "released_by_batch_derivation_event_id")
    op.drop_column("batch_carrier_assignments", "opening_batch_derivation_event_id")

    op.drop_constraint(
        "fk_batch_stage_transitions_derivation_event", "batch_stage_transitions", type_="foreignkey"
    )
    op.drop_index("ux_batch_stage_transitions_one_derivation_entry", table_name="batch_stage_transitions")
    op.drop_constraint("ck_batch_stage_transitions_shape", "batch_stage_transitions", type_="check")
    op.drop_constraint("ck_batch_stage_transitions_command_kind", "batch_stage_transitions", type_="check")
    op.create_check_constraint(
        "ck_batch_stage_transitions_command_kind",
        "batch_stage_transitions",
        "command_kind IN ('initial_entry', 'stage_transition')",
    )
    op.create_check_constraint(
        "ck_batch_stage_transitions_shape",
        "batch_stage_transitions",
        "(command_kind = 'initial_entry' AND source_stage_id IS NULL AND configured_transition_id IS NULL) OR "
        "(command_kind = 'stage_transition' AND source_stage_id IS NOT NULL AND configured_transition_id IS NOT NULL)",
    )
    op.alter_column("batch_stage_transitions", "request_fingerprint", nullable=False)
    op.alter_column("batch_stage_transitions", "client_command_id", nullable=False)
    op.drop_column("batch_stage_transitions", "batch_derivation_event_id")

    op.execute("DROP TRIGGER IF EXISTS crop_batches_enforce_lifecycle_v2 ON crop_batches")
    op.execute("DROP FUNCTION IF EXISTS enforce_crop_batch_lifecycle_v2()")
    op.execute(
        """
        CREATE TRIGGER crop_batches_enforce_lifecycle
        BEFORE UPDATE ON crop_batches
        FOR EACH ROW EXECUTE FUNCTION enforce_crop_batch_lifecycle();
        """
    )

    op.drop_constraint("fk_crop_batches_superseded_by_derivation_event", "crop_batches", type_="foreignkey")
    op.drop_constraint("fk_crop_batches_created_by_derivation_event", "crop_batches", type_="foreignkey")
    op.drop_constraint("ck_crop_batches_command_ownership_shape", "crop_batches", type_="check")
    op.drop_constraint("ck_crop_batches_superseded_after_created", "crop_batches", type_="check")
    op.drop_constraint("ck_crop_batches_lifecycle_shape", "crop_batches", type_="check")
    op.drop_constraint("ck_crop_batches_state", "crop_batches", type_="check")
    op.create_check_constraint("ck_crop_batches_state", "crop_batches", "state IN ('active', 'closed')")
    op.create_check_constraint(
        "ck_crop_batches_closed_time_matches_state",
        "crop_batches",
        "(state = 'active' AND closed_effective_time IS NULL) OR "
        "(state = 'closed' AND closed_effective_time IS NOT NULL)",
    )
    op.alter_column("crop_batches", "request_fingerprint", nullable=False)
    op.alter_column("crop_batches", "client_command_id", nullable=False)
    op.drop_column("crop_batches", "created_by_batch_derivation_event_id")
    op.drop_column("crop_batches", "superseded_by_batch_derivation_event_id")
    op.drop_column("crop_batches", "superseded_effective_time")

    op.drop_index("ux_batch_derivation_events_tenant_client_command_id", table_name="batch_derivation_events")
    op.drop_table("batch_derivation_events")
