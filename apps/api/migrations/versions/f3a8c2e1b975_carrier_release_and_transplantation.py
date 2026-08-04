"""carrier release and transplantation transformation foundation

Revision ID: f3a8c2e1b975
Revises: e29b5c1a7d43
Create Date: 2026-08-04 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'f3a8c2e1b975'
down_revision: Union[str, None] = 'e29b5c1a7d43'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PRIOR_STAGE_CATEGORIES = (
    "seeding", "germination", "nursery", "intermediate", "production", "harvest_ready", "completed", "rejected",
)
_NEW_STAGE_CATEGORIES = (
    "seeding", "germination", "nursery", "transplanting", "intermediate", "production", "harvest_ready",
    "completed", "rejected",
)


def upgrade() -> None:
    # --- workflow_stages: widen the category CHECK additively --------------------
    op.drop_constraint("ck_workflow_stages_category_allowed", "workflow_stages", type_="check")
    op.create_check_constraint(
        "ck_workflow_stages_category_allowed",
        "workflow_stages",
        "stage_category IN ('" + "', '".join(_NEW_STAGE_CATEGORIES) + "')",
    )

    # --- transplant_events (immutable) --------------------------------------------
    op.create_table(
        "transplant_events",
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
        sa.UniqueConstraint("tenant_id", "farm_id", "id", name="uq_transplant_events_tenant_farm_id"),
        sa.UniqueConstraint(
            "tenant_id", "farm_id", "batch_id", "id", name="uq_transplant_events_tenant_farm_batch_id"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_transplant_events_tenant_farm_batch",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id", "active_batch_stage_run_id"],
            [
                "batch_stage_runs.tenant_id", "batch_stage_runs.farm_id", "batch_stage_runs.batch_id",
                "batch_stage_runs.id",
            ],
            name="fk_transplant_events_stage_run",
        ),
    )
    op.create_index(
        "ux_transplant_events_tenant_client_command_id",
        "transplant_events",
        ["tenant_id", "client_command_id"],
        unique=True,
    )

    # --- batch_carrier_assignments: additive amendment ----------------------------
    op.alter_column("batch_carrier_assignments", "opening_sowing_event_id", nullable=True)
    op.add_column(
        "batch_carrier_assignments",
        sa.Column("opening_transplant_event_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "batch_carrier_assignments",
        sa.Column("released_by_transplant_event_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_batch_carrier_assignments_exactly_one_opener",
        "batch_carrier_assignments",
        "(opening_sowing_event_id IS NOT NULL) <> (opening_transplant_event_id IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_batch_carrier_assignments_release_fields_together",
        "batch_carrier_assignments",
        "(released_effective_time IS NULL) = (released_by_transplant_event_id IS NULL)",
    )
    op.create_check_constraint(
        "ck_batch_carrier_assignments_only_sowing_origin_releasable",
        "batch_carrier_assignments",
        "released_by_transplant_event_id IS NULL OR opening_sowing_event_id IS NOT NULL",
    )
    op.create_foreign_key(
        "fk_batch_carrier_assignments_opening_transplant_event",
        "batch_carrier_assignments",
        "transplant_events",
        ["tenant_id", "farm_id", "batch_id", "opening_transplant_event_id"],
        ["tenant_id", "farm_id", "batch_id", "id"],
    )
    op.create_foreign_key(
        "fk_batch_carrier_assignments_released_by_transplant_event",
        "batch_carrier_assignments",
        "transplant_events",
        ["tenant_id", "farm_id", "batch_id", "released_by_transplant_event_id"],
        ["tenant_id", "farm_id", "batch_id", "id"],
    )

    # Replace the CMP-009 insert-integrity trigger with a CMP-011 one that
    # branches on whichever opener is set. The original CMP-009 function
    # (enforce_batch_carrier_assignment_insert_integrity) is left entirely
    # untouched — only its trigger attachment is dropped — so downgrade can
    # restore it exactly with zero risk of divergence.
    op.execute(
        "DROP TRIGGER IF EXISTS batch_carrier_assignments_enforce_insert_integrity ON batch_carrier_assignments"
    )
    op.execute(
        """
        CREATE FUNCTION enforce_batch_carrier_assignment_origin_insert_integrity() RETURNS trigger AS $$
        DECLARE
            v_event_batch_id UUID;
            v_event_run_id UUID;
            v_event_effective TIMESTAMPTZ;
            v_run_stage_id UUID;
            v_required_type UUID;
            v_actual_type UUID;
        BEGIN
            IF NEW.opening_sowing_event_id IS NOT NULL THEN
                SELECT batch_id, active_batch_stage_run_id, effective_time
                INTO v_event_batch_id, v_event_run_id, v_event_effective
                FROM sowing_events WHERE id = NEW.opening_sowing_event_id;
                IF v_event_batch_id IS NULL THEN
                    RAISE EXCEPTION 'opening sowing event not found';
                END IF;
            ELSE
                SELECT batch_id, active_batch_stage_run_id, effective_time
                INTO v_event_batch_id, v_event_run_id, v_event_effective
                FROM transplant_events WHERE id = NEW.opening_transplant_event_id;
                IF v_event_batch_id IS NULL THEN
                    RAISE EXCEPTION 'opening transplant event not found';
                END IF;
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

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER batch_carrier_assignments_enforce_origin_insert_integrity
        BEFORE INSERT ON batch_carrier_assignments
        FOR EACH ROW EXECUTE FUNCTION enforce_batch_carrier_assignment_origin_insert_integrity();
        """
    )

    # Replace the CMP-009 blanket no-update trigger with a CMP-011
    # closure-only trigger. reject_append_only_mutation (shared with other
    # tables) is left untouched — only this table's trigger is dropped.
    op.execute("DROP TRIGGER IF EXISTS batch_carrier_assignments_no_update ON batch_carrier_assignments")
    op.execute(
        """
        CREATE FUNCTION enforce_batch_carrier_assignment_closure_only() RETURNS trigger AS $$
        DECLARE
            v_source_line_event UUID;
            v_source_line_carrier UUID;
            v_transplant_batch_id UUID;
            v_transplant_effective TIMESTAMPTZ;
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
               OR NEW.actor_user_id <> OLD.actor_user_id
            THEN
                RAISE EXCEPTION 'only released_effective_time and released_by_transplant_event_id may change when releasing a batch_carrier_assignment';
            END IF;

            IF NEW.released_effective_time IS NULL OR NEW.released_by_transplant_event_id IS NULL THEN
                RAISE EXCEPTION 'releasing a batch_carrier_assignment requires both released_effective_time and released_by_transplant_event_id';
            END IF;

            IF NEW.opening_sowing_event_id IS NULL THEN
                RAISE EXCEPTION 'only sowing-origin assignments may be released';
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

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER batch_carrier_assignments_enforce_closure_only
        BEFORE UPDATE ON batch_carrier_assignments
        FOR EACH ROW EXECUTE FUNCTION enforce_batch_carrier_assignment_closure_only();
        """
    )

    # --- transplant_source_lines (immutable) --------------------------------------
    op.create_table(
        "transplant_source_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column(
            "transplant_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("transplant_events.id"),
            nullable=False,
        ),
        sa.Column(
            "source_batch_carrier_assignment_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("batch_carrier_assignments.id"), nullable=False,
        ),
        sa.Column("source_carrier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("carriers.id"), nullable=False),
        sa.Column("source_plant_count", sa.Integer(), nullable=False),
        sa.Column("discarded_plant_count", sa.Integer(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("source_plant_count > 0", name="ck_transplant_source_lines_count_positive"),
        sa.CheckConstraint(
            "discarded_plant_count >= 0", name="ck_transplant_source_lines_discarded_non_negative"
        ),
        sa.CheckConstraint(
            "discarded_plant_count <= source_plant_count",
            name="ck_transplant_source_lines_discarded_within_count",
        ),
        sa.UniqueConstraint(
            "source_batch_carrier_assignment_id", name="ux_transplant_source_lines_assignment"
        ),
        sa.UniqueConstraint(
            "tenant_id", "farm_id", "transplant_event_id", "id",
            name="uq_transplant_source_lines_tenant_farm_event_id",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "transplant_event_id"],
            ["transplant_events.tenant_id", "transplant_events.farm_id", "transplant_events.id"],
            name="fk_transplant_source_lines_tenant_farm_event",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "source_batch_carrier_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id", "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_transplant_source_lines_tenant_farm_assignment",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "source_carrier_id"],
            ["carriers.tenant_id", "carriers.farm_id", "carriers.id"],
            name="fk_transplant_source_lines_tenant_farm_carrier",
        ),
    )

    # --- transplant_destination_lines (immutable) ----------------------------------
    op.create_table(
        "transplant_destination_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column(
            "transplant_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("transplant_events.id"),
            nullable=False,
        ),
        sa.Column(
            "destination_batch_carrier_assignment_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("batch_carrier_assignments.id"), nullable=False,
        ),
        sa.Column(
            "destination_carrier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("carriers.id"), nullable=False
        ),
        sa.Column("assigned_plant_count", sa.Integer(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("assigned_plant_count > 0", name="ck_transplant_destination_lines_count_positive"),
        sa.UniqueConstraint(
            "transplant_event_id", "destination_carrier_id", name="ux_transplant_destination_lines_event_carrier"
        ),
        sa.UniqueConstraint(
            "destination_batch_carrier_assignment_id", name="ux_transplant_destination_lines_assignment"
        ),
        sa.UniqueConstraint(
            "tenant_id", "farm_id", "transplant_event_id", "id",
            name="uq_transplant_destination_lines_tenant_farm_event_id",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "transplant_event_id"],
            ["transplant_events.tenant_id", "transplant_events.farm_id", "transplant_events.id"],
            name="fk_transplant_destination_lines_tenant_farm_event",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "destination_batch_carrier_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id", "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_transplant_destination_lines_tenant_farm_assignment",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "destination_carrier_id"],
            ["carriers.tenant_id", "carriers.farm_id", "carriers.id"],
            name="fk_transplant_destination_lines_tenant_farm_carrier",
        ),
    )

    # --- transplant_allocations (immutable) -----------------------------------------
    op.create_table(
        "transplant_allocations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column(
            "transplant_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("transplant_events.id"),
            nullable=False,
        ),
        sa.Column(
            "source_line_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("transplant_source_lines.id"),
            nullable=False,
        ),
        sa.Column(
            "destination_line_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("transplant_destination_lines.id"), nullable=False,
        ),
        sa.Column("allocated_plant_count", sa.Integer(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("allocated_plant_count > 0", name="ck_transplant_allocations_count_positive"),
        sa.UniqueConstraint("source_line_id", "destination_line_id", name="ux_transplant_allocations_pair"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "transplant_event_id"],
            ["transplant_events.tenant_id", "transplant_events.farm_id", "transplant_events.id"],
            name="fk_transplant_allocations_tenant_farm_event",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "transplant_event_id", "source_line_id"],
            [
                "transplant_source_lines.tenant_id", "transplant_source_lines.farm_id",
                "transplant_source_lines.transplant_event_id", "transplant_source_lines.id",
            ],
            name="fk_transplant_allocations_source_line",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "transplant_event_id", "destination_line_id"],
            [
                "transplant_destination_lines.tenant_id", "transplant_destination_lines.farm_id",
                "transplant_destination_lines.transplant_event_id", "transplant_destination_lines.id",
            ],
            name="fk_transplant_allocations_destination_line",
        ),
    )

    # --- insert-integrity triggers on the new tables --------------------------------

    op.execute(
        """
        CREATE FUNCTION enforce_transplant_event_insert_integrity() RETURNS trigger AS $$
        DECLARE
            v_run_batch_id UUID;
            v_run_exited TIMESTAMPTZ;
            v_batch_state TEXT;
            v_stage_category TEXT;
            v_required_type UUID;
        BEGIN
            SELECT batch_id, exited_effective_time INTO v_run_batch_id, v_run_exited
            FROM batch_stage_runs WHERE id = NEW.active_batch_stage_run_id;
            IF v_run_batch_id IS NULL THEN
                RAISE EXCEPTION 'active stage run not found';
            END IF;
            IF v_run_batch_id <> NEW.batch_id THEN
                RAISE EXCEPTION 'stage run does not belong to this batch';
            END IF;
            IF v_run_exited IS NOT NULL THEN
                RAISE EXCEPTION 'transplant requires the batch''s currently active stage run';
            END IF;

            SELECT state INTO v_batch_state FROM crop_batches WHERE id = NEW.batch_id;
            IF v_batch_state IS DISTINCT FROM 'active' THEN
                RAISE EXCEPTION 'crop batch is not active';
            END IF;

            SELECT s.stage_category, s.required_carrier_type_id INTO v_stage_category, v_required_type
            FROM batch_stage_runs r JOIN workflow_stages s ON s.id = r.workflow_stage_id
            WHERE r.id = NEW.active_batch_stage_run_id;
            IF v_stage_category IS DISTINCT FROM 'transplanting' THEN
                RAISE EXCEPTION 'current stage is not a transplanting stage';
            END IF;
            IF v_required_type IS NULL THEN
                RAISE EXCEPTION 'current stage has no required destination carrier type configured';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER transplant_events_enforce_insert_integrity
        BEFORE INSERT ON transplant_events
        FOR EACH ROW EXECUTE FUNCTION enforce_transplant_event_insert_integrity();
        """
    )
    op.execute(
        """
        CREATE TRIGGER transplant_events_no_update
        BEFORE UPDATE ON transplant_events
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER transplant_events_no_delete
        BEFORE DELETE ON transplant_events
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )

    op.execute(
        """
        CREATE FUNCTION enforce_transplant_source_line_insert_integrity() RETURNS trigger AS $$
        DECLARE
            v_event_batch_id UUID;
            v_assignment_batch_id UUID;
            v_assignment_carrier UUID;
            v_assignment_released TIMESTAMPTZ;
            v_assignment_sowing_event UUID;
            v_sown_count INTEGER;
        BEGIN
            SELECT batch_id INTO v_event_batch_id FROM transplant_events WHERE id = NEW.transplant_event_id;

            SELECT batch_id, carrier_id, released_effective_time, opening_sowing_event_id
            INTO v_assignment_batch_id, v_assignment_carrier, v_assignment_released, v_assignment_sowing_event
            FROM batch_carrier_assignments WHERE id = NEW.source_batch_carrier_assignment_id;
            IF v_assignment_batch_id IS NULL THEN
                RAISE EXCEPTION 'source assignment not found';
            END IF;
            IF v_assignment_batch_id <> v_event_batch_id THEN
                RAISE EXCEPTION 'source assignment does not belong to this transplant event''s batch';
            END IF;
            IF v_assignment_carrier <> NEW.source_carrier_id THEN
                RAISE EXCEPTION 'source carrier does not match assignment carrier';
            END IF;
            IF v_assignment_released IS NOT NULL THEN
                RAISE EXCEPTION 'source assignment is already released';
            END IF;
            IF v_assignment_sowing_event IS NULL THEN
                RAISE EXCEPTION 'source assignment did not originate from sowing';
            END IF;

            SELECT sown_site_count INTO v_sown_count FROM sowing_event_lines
            WHERE batch_carrier_assignment_id = NEW.source_batch_carrier_assignment_id;
            IF v_sown_count IS NULL THEN
                RAISE EXCEPTION 'no sowing line found for source assignment';
            END IF;
            IF NEW.source_plant_count > v_sown_count THEN
                RAISE EXCEPTION 'source_plant_count cannot exceed the assignment''s original sown_site_count';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER transplant_source_lines_enforce_insert_integrity
        BEFORE INSERT ON transplant_source_lines
        FOR EACH ROW EXECUTE FUNCTION enforce_transplant_source_line_insert_integrity();
        """
    )
    op.execute(
        """
        CREATE TRIGGER transplant_source_lines_no_update
        BEFORE UPDATE ON transplant_source_lines
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER transplant_source_lines_no_delete
        BEFORE DELETE ON transplant_source_lines
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )

    op.execute(
        """
        CREATE FUNCTION enforce_transplant_destination_line_insert_integrity() RETURNS trigger AS $$
        DECLARE
            v_assignment_event UUID;
            v_assignment_batch UUID;
            v_assignment_run UUID;
            v_assignment_carrier UUID;
            v_assignment_effective TIMESTAMPTZ;
            v_event_batch UUID;
            v_event_run UUID;
            v_event_effective TIMESTAMPTZ;
        BEGIN
            SELECT batch_id, active_batch_stage_run_id, effective_time
            INTO v_event_batch, v_event_run, v_event_effective
            FROM transplant_events WHERE id = NEW.transplant_event_id;

            SELECT opening_transplant_event_id, batch_id, batch_stage_run_id, carrier_id, assigned_effective_time
            INTO v_assignment_event, v_assignment_batch, v_assignment_run, v_assignment_carrier, v_assignment_effective
            FROM batch_carrier_assignments WHERE id = NEW.destination_batch_carrier_assignment_id;
            IF v_assignment_batch IS NULL THEN
                RAISE EXCEPTION 'destination assignment not found';
            END IF;
            IF v_assignment_event IS DISTINCT FROM NEW.transplant_event_id THEN
                RAISE EXCEPTION 'destination assignment was not opened by this transplant event';
            END IF;
            IF v_assignment_batch <> v_event_batch THEN
                RAISE EXCEPTION 'destination assignment batch mismatch';
            END IF;
            IF v_assignment_run <> v_event_run THEN
                RAISE EXCEPTION 'destination assignment stage-run mismatch';
            END IF;
            IF v_assignment_effective <> v_event_effective THEN
                RAISE EXCEPTION 'destination assignment effective time mismatch';
            END IF;
            IF v_assignment_carrier <> NEW.destination_carrier_id THEN
                RAISE EXCEPTION 'destination carrier does not match assignment carrier';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER transplant_destination_lines_enforce_insert_integrity
        BEFORE INSERT ON transplant_destination_lines
        FOR EACH ROW EXECUTE FUNCTION enforce_transplant_destination_line_insert_integrity();
        """
    )
    op.execute(
        """
        CREATE TRIGGER transplant_destination_lines_no_update
        BEFORE UPDATE ON transplant_destination_lines
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER transplant_destination_lines_no_delete
        BEFORE DELETE ON transplant_destination_lines
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )

    op.execute(
        """
        CREATE TRIGGER transplant_allocations_no_update
        BEFORE UPDATE ON transplant_allocations
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER transplant_allocations_no_delete
        BEFORE DELETE ON transplant_allocations
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )

    # --- deferred reconciliation --------------------------------------------------
    # One shared function, resolved per firing table/operation, attached via
    # six DEFERRABLE INITIALLY DEFERRED constraint triggers so that ANY insert
    # (even direct SQL against an already-committed event, in a later
    # transaction) re-validates that event's complete reconciled state at
    # commit time.
    op.execute(
        """
        CREATE FUNCTION enforce_transplant_reconciliation() RETURNS trigger AS $$
        DECLARE
            v_event_id UUID;
            v_source_line_count INTEGER;
            v_destination_line_count INTEGER;
            v_allocation_count INTEGER;
            v_bad_source_count INTEGER;
            v_bad_destination_count INTEGER;
            v_total_source INTEGER;
            v_total_destination INTEGER;
            v_total_discarded INTEGER;
            v_unreleased_source_count INTEGER;
            v_unopened_destination_count INTEGER;
            v_extra_release_count INTEGER;
            v_extra_open_count INTEGER;
            v_event_effective TIMESTAMPTZ;
        BEGIN
            IF TG_TABLE_NAME = 'transplant_events' THEN
                v_event_id := NEW.id;
            ELSIF TG_TABLE_NAME = 'transplant_source_lines' THEN
                v_event_id := NEW.transplant_event_id;
            ELSIF TG_TABLE_NAME = 'transplant_destination_lines' THEN
                v_event_id := NEW.transplant_event_id;
            ELSIF TG_TABLE_NAME = 'transplant_allocations' THEN
                v_event_id := NEW.transplant_event_id;
            ELSIF TG_TABLE_NAME = 'batch_carrier_assignments' THEN
                IF TG_OP = 'INSERT' THEN
                    v_event_id := NEW.opening_transplant_event_id;
                ELSE
                    v_event_id := NEW.released_by_transplant_event_id;
                END IF;
            END IF;

            IF v_event_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT effective_time INTO v_event_effective FROM transplant_events WHERE id = v_event_id;

            SELECT count(*) INTO v_source_line_count FROM transplant_source_lines WHERE transplant_event_id = v_event_id;
            SELECT count(*) INTO v_destination_line_count FROM transplant_destination_lines WHERE transplant_event_id = v_event_id;
            SELECT count(*) INTO v_allocation_count FROM transplant_allocations WHERE transplant_event_id = v_event_id;

            IF v_source_line_count = 0 THEN
                RAISE EXCEPTION 'transplant event % has no source lines', v_event_id;
            END IF;
            IF v_destination_line_count = 0 THEN
                RAISE EXCEPTION 'transplant event % has no destination lines', v_event_id;
            END IF;
            IF v_allocation_count = 0 THEN
                RAISE EXCEPTION 'transplant event % has no allocations', v_event_id;
            END IF;

            SELECT count(*) INTO v_bad_source_count
            FROM transplant_source_lines sl
            WHERE sl.transplant_event_id = v_event_id
              AND sl.discarded_plant_count + COALESCE(
                  (SELECT sum(a.allocated_plant_count) FROM transplant_allocations a WHERE a.source_line_id = sl.id), 0
              ) <> sl.source_plant_count;
            IF v_bad_source_count > 0 THEN
                RAISE EXCEPTION 'transplant event % has unreconciled source lines', v_event_id;
            END IF;

            SELECT count(*) INTO v_bad_destination_count
            FROM transplant_destination_lines dl
            WHERE dl.transplant_event_id = v_event_id
              AND COALESCE(
                  (SELECT sum(a.allocated_plant_count) FROM transplant_allocations a WHERE a.destination_line_id = dl.id), 0
              ) <> dl.assigned_plant_count;
            IF v_bad_destination_count > 0 THEN
                RAISE EXCEPTION 'transplant event % has unreconciled destination lines', v_event_id;
            END IF;

            SELECT sum(source_plant_count), sum(discarded_plant_count) INTO v_total_source, v_total_discarded
            FROM transplant_source_lines WHERE transplant_event_id = v_event_id;
            SELECT sum(assigned_plant_count) INTO v_total_destination
            FROM transplant_destination_lines WHERE transplant_event_id = v_event_id;
            IF v_total_source IS DISTINCT FROM (COALESCE(v_total_destination, 0) + COALESCE(v_total_discarded, 0)) THEN
                RAISE EXCEPTION 'transplant event % totals do not reconcile', v_event_id;
            END IF;

            SELECT count(*) INTO v_unreleased_source_count
            FROM transplant_source_lines sl
            JOIN batch_carrier_assignments a ON a.id = sl.source_batch_carrier_assignment_id
            WHERE sl.transplant_event_id = v_event_id
              AND (a.released_by_transplant_event_id IS DISTINCT FROM v_event_id
                   OR a.released_effective_time IS DISTINCT FROM v_event_effective);
            IF v_unreleased_source_count > 0 THEN
                RAISE EXCEPTION 'transplant event % has a source line whose assignment was not released by this event', v_event_id;
            END IF;

            SELECT count(*) INTO v_unopened_destination_count
            FROM transplant_destination_lines dl
            JOIN batch_carrier_assignments a ON a.id = dl.destination_batch_carrier_assignment_id
            WHERE dl.transplant_event_id = v_event_id
              AND (a.opening_transplant_event_id IS DISTINCT FROM v_event_id
                   OR a.assigned_effective_time IS DISTINCT FROM v_event_effective);
            IF v_unopened_destination_count > 0 THEN
                RAISE EXCEPTION 'transplant event % has a destination line whose assignment was not opened by this event', v_event_id;
            END IF;

            SELECT count(*) INTO v_extra_release_count
            FROM batch_carrier_assignments a
            WHERE a.released_by_transplant_event_id = v_event_id
              AND NOT EXISTS (
                  SELECT 1 FROM transplant_source_lines sl
                  WHERE sl.source_batch_carrier_assignment_id = a.id AND sl.transplant_event_id = v_event_id
              );
            IF v_extra_release_count > 0 THEN
                RAISE EXCEPTION 'transplant event % released an assignment without a matching source line', v_event_id;
            END IF;

            SELECT count(*) INTO v_extra_open_count
            FROM batch_carrier_assignments a
            WHERE a.opening_transplant_event_id = v_event_id
              AND NOT EXISTS (
                  SELECT 1 FROM transplant_destination_lines dl
                  WHERE dl.destination_batch_carrier_assignment_id = a.id AND dl.transplant_event_id = v_event_id
              );
            IF v_extra_open_count > 0 THEN
                RAISE EXCEPTION 'transplant event % opened an assignment without a matching destination line', v_event_id;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER transplant_events_enforce_reconciliation
        AFTER INSERT ON transplant_events
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_transplant_reconciliation();
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER transplant_source_lines_enforce_reconciliation
        AFTER INSERT ON transplant_source_lines
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_transplant_reconciliation();
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER transplant_destination_lines_enforce_reconciliation
        AFTER INSERT ON transplant_destination_lines
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_transplant_reconciliation();
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER transplant_allocations_enforce_reconciliation
        AFTER INSERT ON transplant_allocations
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_transplant_reconciliation();
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER batch_carrier_assignments_enforce_reconciliation_on_open
        AFTER INSERT ON batch_carrier_assignments
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW WHEN (NEW.opening_transplant_event_id IS NOT NULL)
        EXECUTE FUNCTION enforce_transplant_reconciliation();
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER batch_carrier_assignments_enforce_reconciliation_on_release
        AFTER UPDATE ON batch_carrier_assignments
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW WHEN (
            OLD.released_by_transplant_event_id IS NULL AND NEW.released_by_transplant_event_id IS NOT NULL
        )
        EXECUTE FUNCTION enforce_transplant_reconciliation();
        """
    )


def downgrade() -> None:
    bind = op.get_bind()

    # --- downgrade guard: never corrupt or silently discard CMP-011 history ------
    unsafe = bind.execute(
        sa.text(
            "SELECT "
            "(SELECT count(*) FROM transplant_events) AS event_count, "
            "(SELECT count(*) FROM batch_carrier_assignments WHERE opening_transplant_event_id IS NOT NULL) "
            "AS opened_count, "
            "(SELECT count(*) FROM batch_carrier_assignments WHERE released_by_transplant_event_id IS NOT NULL) "
            "AS released_count, "
            "(SELECT count(*) FROM workflow_stages WHERE stage_category = 'transplanting') AS stage_count"
        )
    ).mappings().first()
    if (
        unsafe["event_count"] > 0
        or unsafe["opened_count"] > 0
        or unsafe["released_count"] > 0
        or unsafe["stage_count"] > 0
    ):
        raise RuntimeError(
            "Cannot downgrade past CMP-011: transplant events, transplant-created assignments, "
            "released source assignments, or transplanting-category workflow stages exist. "
            "Downgrading would corrupt or silently discard this production history. "
            "Remove or migrate the offending data out-of-band before downgrading, or do not downgrade."
        )

    op.execute(
        "DROP TRIGGER IF EXISTS batch_carrier_assignments_enforce_reconciliation_on_release "
        "ON batch_carrier_assignments"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS batch_carrier_assignments_enforce_reconciliation_on_open "
        "ON batch_carrier_assignments"
    )
    op.execute("DROP TRIGGER IF EXISTS transplant_allocations_enforce_reconciliation ON transplant_allocations")
    op.execute(
        "DROP TRIGGER IF EXISTS transplant_destination_lines_enforce_reconciliation ON transplant_destination_lines"
    )
    op.execute("DROP TRIGGER IF EXISTS transplant_source_lines_enforce_reconciliation ON transplant_source_lines")
    op.execute("DROP TRIGGER IF EXISTS transplant_events_enforce_reconciliation ON transplant_events")
    op.execute("DROP FUNCTION IF EXISTS enforce_transplant_reconciliation()")

    op.execute("DROP TRIGGER IF EXISTS transplant_allocations_no_delete ON transplant_allocations")
    op.execute("DROP TRIGGER IF EXISTS transplant_allocations_no_update ON transplant_allocations")

    op.execute("DROP TRIGGER IF EXISTS transplant_destination_lines_no_delete ON transplant_destination_lines")
    op.execute("DROP TRIGGER IF EXISTS transplant_destination_lines_no_update ON transplant_destination_lines")
    op.execute(
        "DROP TRIGGER IF EXISTS transplant_destination_lines_enforce_insert_integrity "
        "ON transplant_destination_lines"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_transplant_destination_line_insert_integrity()")

    op.execute("DROP TRIGGER IF EXISTS transplant_source_lines_no_delete ON transplant_source_lines")
    op.execute("DROP TRIGGER IF EXISTS transplant_source_lines_no_update ON transplant_source_lines")
    op.execute(
        "DROP TRIGGER IF EXISTS transplant_source_lines_enforce_insert_integrity ON transplant_source_lines"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_transplant_source_line_insert_integrity()")

    op.execute("DROP TRIGGER IF EXISTS transplant_events_no_delete ON transplant_events")
    op.execute("DROP TRIGGER IF EXISTS transplant_events_no_update ON transplant_events")
    op.execute("DROP TRIGGER IF EXISTS transplant_events_enforce_insert_integrity ON transplant_events")
    op.execute("DROP FUNCTION IF EXISTS enforce_transplant_event_insert_integrity()")

    op.drop_table("transplant_allocations")
    op.drop_table("transplant_destination_lines")
    op.drop_table("transplant_source_lines")

    # Restore the CMP-009 closure/insert-integrity triggers pointing at their
    # original, never-modified functions.
    op.execute(
        "DROP TRIGGER IF EXISTS batch_carrier_assignments_enforce_closure_only ON batch_carrier_assignments"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_batch_carrier_assignment_closure_only()")
    op.execute(
        """
        CREATE TRIGGER batch_carrier_assignments_no_update
        BEFORE UPDATE ON batch_carrier_assignments
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )

    op.execute(
        "DROP TRIGGER IF EXISTS batch_carrier_assignments_enforce_origin_insert_integrity "
        "ON batch_carrier_assignments"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_batch_carrier_assignment_origin_insert_integrity()")
    op.execute(
        """
        CREATE TRIGGER batch_carrier_assignments_enforce_insert_integrity
        BEFORE INSERT ON batch_carrier_assignments
        FOR EACH ROW EXECUTE FUNCTION enforce_batch_carrier_assignment_insert_integrity();
        """
    )

    op.drop_constraint(
        "fk_batch_carrier_assignments_released_by_transplant_event", "batch_carrier_assignments", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_batch_carrier_assignments_opening_transplant_event", "batch_carrier_assignments", type_="foreignkey"
    )
    op.drop_constraint(
        "ck_batch_carrier_assignments_only_sowing_origin_releasable", "batch_carrier_assignments", type_="check"
    )
    op.drop_constraint(
        "ck_batch_carrier_assignments_release_fields_together", "batch_carrier_assignments", type_="check"
    )
    op.drop_constraint(
        "ck_batch_carrier_assignments_exactly_one_opener", "batch_carrier_assignments", type_="check"
    )
    op.drop_column("batch_carrier_assignments", "released_by_transplant_event_id")
    op.drop_column("batch_carrier_assignments", "opening_transplant_event_id")
    op.alter_column("batch_carrier_assignments", "opening_sowing_event_id", nullable=False)

    op.drop_index("ux_transplant_events_tenant_client_command_id", table_name="transplant_events")
    op.drop_table("transplant_events")

    op.drop_constraint("ck_workflow_stages_category_allowed", "workflow_stages", type_="check")
    op.create_check_constraint(
        "ck_workflow_stages_category_allowed",
        "workflow_stages",
        "stage_category IN ('" + "', '".join(_PRIOR_STAGE_CATEGORIES) + "')",
    )
