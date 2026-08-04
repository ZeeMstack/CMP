"""observation, germination check, and quality hold foundation

Revision ID: e29b5c1a7d43
Revises: d17a4e2f9c86
Create Date: 2026-08-03 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'e29b5c1a7d43'
down_revision: Union[str, None] = 'd17a4e2f9c86'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # No additive constraints on existing tables are required: CMP-009 already
    # added uq_carriers_tenant_farm_id, uq_batch_stage_runs_tenant_farm_batch_id,
    # uq_batch_carrier_assignments_tenant_farm_id, and uq_sowing_events_tenant_farm_id;
    # crop_batches already carries uq_crop_batches_tenant_farm_id from CMP-008 —
    # all of these already provide every composite-FK target CMP-010 needs.
    # (Verified directly against the live schema before writing this migration.)

    # --- observation_definitions -----------------------------------------------
    op.create_table(
        "observation_definitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("value_type", sa.String(), nullable=False),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("target_scope", sa.String(), nullable=False),
        sa.Column("min_value", sa.Numeric(), nullable=True),
        sa.Column("max_value", sa.Numeric(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column(
            "created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "value_type IN ('integer', 'decimal', 'percentage', 'boolean', 'text')",
            name="ck_observation_definitions_value_type",
        ),
        sa.CheckConstraint(
            "target_scope IN ('crop_batch', 'carrier_assignment', 'either')",
            name="ck_observation_definitions_target_scope",
        ),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_observation_definitions_status"),
        sa.CheckConstraint(
            "min_value IS NULL OR max_value IS NULL OR min_value <= max_value",
            name="ck_observation_definitions_min_le_max",
        ),
        sa.CheckConstraint(
            "value_type NOT IN ('boolean', 'text') OR (min_value IS NULL AND max_value IS NULL)",
            name="ck_observation_definitions_bool_text_no_bounds",
        ),
        sa.CheckConstraint(
            "value_type <> 'percentage' OR "
            "((min_value IS NULL OR min_value >= 0) AND (max_value IS NULL OR max_value <= 100))",
            name="ck_observation_definitions_percentage_bounds",
        ),
        sa.CheckConstraint(
            "value_type <> 'integer' OR "
            "((min_value IS NULL OR min_value = floor(min_value)) AND "
            "(max_value IS NULL OR max_value = floor(max_value)))",
            name="ck_observation_definitions_integer_bounds_integral",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_observation_definitions_tenant_id_id"),
    )
    op.create_index(
        "ux_observation_definitions_tenant_code_lower",
        "observation_definitions",
        ["tenant_id", sa.text("lower(code)")],
        unique=True,
    )

    # --- observation_events (immutable) ------------------------------------------
    op.create_table(
        "observation_events",
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
        sa.UniqueConstraint("tenant_id", "farm_id", "id", name="uq_observation_events_tenant_farm_id"),
        sa.UniqueConstraint(
            "tenant_id", "farm_id", "batch_id", "id", name="uq_observation_events_tenant_farm_batch_id"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_observation_events_tenant_farm_batch",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id", "active_batch_stage_run_id"],
            [
                "batch_stage_runs.tenant_id",
                "batch_stage_runs.farm_id",
                "batch_stage_runs.batch_id",
                "batch_stage_runs.id",
            ],
            name="fk_observation_events_stage_run",
        ),
    )
    op.create_index(
        "ux_observation_events_tenant_client_command_id",
        "observation_events",
        ["tenant_id", "client_command_id"],
        unique=True,
    )

    # --- observation_values (immutable) -------------------------------------------
    op.create_table(
        "observation_values",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column(
            "observation_event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("observation_events.id"),
            nullable=False,
        ),
        sa.Column(
            "observation_definition_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("observation_definitions.id"),
            nullable=False,
        ),
        sa.Column(
            "batch_carrier_assignment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("batch_carrier_assignments.id"),
            nullable=True,
        ),
        sa.Column("value_integer", sa.Integer(), nullable=True),
        sa.Column("value_decimal", sa.Numeric(), nullable=True),
        sa.Column("value_boolean", sa.Boolean(), nullable=True),
        sa.Column("value_text", sa.String(), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(value_integer IS NOT NULL)::int + (value_decimal IS NOT NULL)::int + "
            "(value_boolean IS NOT NULL)::int + (value_text IS NOT NULL)::int = 1",
            name="ck_observation_values_exactly_one_typed_value",
        ),
        sa.CheckConstraint(
            "value_text IS NULL OR length(value_text) > 0", name="ck_observation_values_text_not_blank"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "observation_event_id"],
            ["observation_events.tenant_id", "observation_events.farm_id", "observation_events.id"],
            name="fk_observation_values_tenant_farm_event",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "observation_definition_id"],
            ["observation_definitions.tenant_id", "observation_definitions.id"],
            name="fk_observation_values_tenant_definition",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_carrier_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id",
                "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_observation_values_tenant_farm_assignment",
        ),
    )
    op.create_index(
        "ux_observation_values_batch_target",
        "observation_values",
        ["observation_event_id", "observation_definition_id"],
        unique=True,
        postgresql_where=sa.text("batch_carrier_assignment_id IS NULL"),
    )
    op.create_index(
        "ux_observation_values_assignment_target",
        "observation_values",
        ["observation_event_id", "observation_definition_id", "batch_carrier_assignment_id"],
        unique=True,
        postgresql_where=sa.text("batch_carrier_assignment_id IS NOT NULL"),
    )

    # --- germination_checks (immutable) -------------------------------------------
    op.create_table(
        "germination_checks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column(
            "observation_event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("observation_events.id"),
            nullable=False,
        ),
        sa.Column(
            "batch_carrier_assignment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("batch_carrier_assignments.id"),
            nullable=False,
        ),
        sa.Column("inspected_site_count", sa.Integer(), nullable=False),
        sa.Column("normal_germinated_site_count", sa.Integer(), nullable=False),
        sa.Column("abnormal_germinated_site_count", sa.Integer(), nullable=False),
        sa.Column("failed_site_count", sa.Integer(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("inspected_site_count > 0", name="ck_germination_checks_inspected_positive"),
        sa.CheckConstraint(
            "normal_germinated_site_count >= 0", name="ck_germination_checks_normal_non_negative"
        ),
        sa.CheckConstraint(
            "abnormal_germinated_site_count >= 0", name="ck_germination_checks_abnormal_non_negative"
        ),
        sa.CheckConstraint("failed_site_count >= 0", name="ck_germination_checks_failed_non_negative"),
        sa.CheckConstraint(
            "normal_germinated_site_count + abnormal_germinated_site_count + failed_site_count "
            "<= inspected_site_count",
            name="ck_germination_checks_categories_within_inspected",
        ),
        sa.UniqueConstraint(
            "observation_event_id", "batch_carrier_assignment_id", name="ux_germination_checks_event_assignment"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "observation_event_id"],
            ["observation_events.tenant_id", "observation_events.farm_id", "observation_events.id"],
            name="fk_germination_checks_tenant_farm_event",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_carrier_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id",
                "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_germination_checks_tenant_farm_assignment",
        ),
    )

    # --- quality_holds (immutable) -------------------------------------------------
    op.create_table(
        "quality_holds",
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
        sa.Column(
            "source_observation_event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("observation_events.id"),
            nullable=True,
        ),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.Column("reason_code", sa.String(), nullable=False),
        sa.Column("reason_text", sa.String(), nullable=False),
        sa.UniqueConstraint("tenant_id", "farm_id", "id", name="uq_quality_holds_tenant_farm_id"),
        sa.UniqueConstraint(
            "tenant_id", "farm_id", "batch_id", "id", name="uq_quality_holds_tenant_farm_batch_id"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_quality_holds_tenant_farm_batch",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id", "active_batch_stage_run_id"],
            [
                "batch_stage_runs.tenant_id",
                "batch_stage_runs.farm_id",
                "batch_stage_runs.batch_id",
                "batch_stage_runs.id",
            ],
            name="fk_quality_holds_stage_run",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id", "source_observation_event_id"],
            [
                "observation_events.tenant_id",
                "observation_events.farm_id",
                "observation_events.batch_id",
                "observation_events.id",
            ],
            name="fk_quality_holds_source_observation",
        ),
    )
    op.create_index(
        "ux_quality_holds_tenant_client_command_id", "quality_holds", ["tenant_id", "client_command_id"],
        unique=True,
    )
    op.create_index(
        "ix_quality_holds_tenant_farm_batch", "quality_holds", ["tenant_id", "farm_id", "batch_id"]
    )

    # --- quality_hold_releases (immutable) ------------------------------------------
    op.create_table(
        "quality_hold_releases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column(
            "quality_hold_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("quality_holds.id"), nullable=False
        ),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("crop_batches.id"), nullable=False),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.Column("release_reason", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id", "quality_hold_id"],
            [
                "quality_holds.tenant_id",
                "quality_holds.farm_id",
                "quality_holds.batch_id",
                "quality_holds.id",
            ],
            name="fk_quality_hold_releases_hold",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_quality_hold_releases_tenant_farm_batch",
        ),
    )
    op.create_index(
        "ux_quality_hold_releases_tenant_client_command_id",
        "quality_hold_releases",
        ["tenant_id", "client_command_id"],
        unique=True,
    )
    op.create_index(
        "ux_quality_hold_releases_hold", "quality_hold_releases", ["tenant_id", "quality_hold_id"], unique=True
    )

    # --- triggers ------------------------------------------------------------

    # observation_definitions: only `status` (+ updated_at) may change after
    # creation; every other semantic field is immutable.
    op.execute(
        """
        CREATE FUNCTION enforce_observation_definition_status_only_update() RETURNS trigger AS $$
        BEGIN
            IF NEW.tenant_id <> OLD.tenant_id OR NEW.code <> OLD.code OR NEW.name <> OLD.name
               OR NEW.description IS DISTINCT FROM OLD.description OR NEW.value_type <> OLD.value_type
               OR NEW.unit IS DISTINCT FROM OLD.unit OR NEW.target_scope <> OLD.target_scope
               OR NEW.min_value IS DISTINCT FROM OLD.min_value OR NEW.max_value IS DISTINCT FROM OLD.max_value
               OR NEW.created_by_user_id <> OLD.created_by_user_id OR NEW.created_at <> OLD.created_at
            THEN
                RAISE EXCEPTION 'observation_definition semantic fields are immutable; only status may change';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER observation_definitions_enforce_status_only_update
        BEFORE UPDATE ON observation_definitions
        FOR EACH ROW EXECUTE FUNCTION enforce_observation_definition_status_only_update();
        """
    )
    op.execute(
        """
        CREATE TRIGGER observation_definitions_no_delete
        BEFORE DELETE ON observation_definitions
        FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();
        """
    )

    # observation_events: active stage run must belong to this batch, be
    # currently open, and the batch must be active.
    op.execute(
        """
        CREATE FUNCTION enforce_observation_event_insert_integrity() RETURNS trigger AS $$
        DECLARE
            v_run_batch_id UUID;
            v_run_exited TIMESTAMPTZ;
            v_batch_state TEXT;
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
                RAISE EXCEPTION 'observation requires the batch''s currently active stage run';
            END IF;

            SELECT state INTO v_batch_state FROM crop_batches WHERE id = NEW.batch_id;
            IF v_batch_state IS DISTINCT FROM 'active' THEN
                RAISE EXCEPTION 'crop batch is not active';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER observation_events_enforce_insert_integrity
        BEFORE INSERT ON observation_events
        FOR EACH ROW EXECUTE FUNCTION enforce_observation_event_insert_integrity();
        """
    )
    op.execute(
        """
        CREATE TRIGGER observation_events_no_update
        BEFORE UPDATE ON observation_events
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER observation_events_no_delete
        BEFORE DELETE ON observation_events
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )

    # observation_values: definition must be active, target scope must match
    # assignment presence, the typed column must match the definition's
    # value_type, numeric/percentage bounds must hold, and any referenced
    # assignment must belong to the event's batch with a compatible
    # effective time.
    op.execute(
        """
        CREATE FUNCTION enforce_observation_value_insert_integrity() RETURNS trigger AS $$
        DECLARE
            v_def_status TEXT;
            v_def_type TEXT;
            v_def_scope TEXT;
            v_def_min NUMERIC;
            v_def_max NUMERIC;
            v_event_batch_id UUID;
            v_event_effective TIMESTAMPTZ;
            v_assignment_batch_id UUID;
            v_assignment_assigned TIMESTAMPTZ;
        BEGIN
            SELECT status, value_type, target_scope, min_value, max_value
            INTO v_def_status, v_def_type, v_def_scope, v_def_min, v_def_max
            FROM observation_definitions WHERE id = NEW.observation_definition_id;
            IF v_def_type IS NULL THEN
                RAISE EXCEPTION 'observation definition not found';
            END IF;
            IF v_def_status <> 'active' THEN
                RAISE EXCEPTION 'observation definition is not active';
            END IF;

            IF v_def_scope = 'crop_batch' AND NEW.batch_carrier_assignment_id IS NOT NULL THEN
                RAISE EXCEPTION 'definition target scope crop_batch does not accept an assignment target';
            END IF;
            IF v_def_scope = 'carrier_assignment' AND NEW.batch_carrier_assignment_id IS NULL THEN
                RAISE EXCEPTION 'definition target scope carrier_assignment requires an assignment target';
            END IF;

            IF v_def_type = 'integer' AND NEW.value_integer IS NULL THEN
                RAISE EXCEPTION 'definition value_type integer requires value_integer';
            END IF;
            IF v_def_type IN ('decimal', 'percentage') AND NEW.value_decimal IS NULL THEN
                RAISE EXCEPTION 'definition value_type % requires value_decimal', v_def_type;
            END IF;
            IF v_def_type = 'boolean' AND NEW.value_boolean IS NULL THEN
                RAISE EXCEPTION 'definition value_type boolean requires value_boolean';
            END IF;
            IF v_def_type = 'text' AND NEW.value_text IS NULL THEN
                RAISE EXCEPTION 'definition value_type text requires value_text';
            END IF;

            IF v_def_type = 'integer' AND NEW.value_integer IS NOT NULL THEN
                IF v_def_min IS NOT NULL AND NEW.value_integer < v_def_min THEN
                    RAISE EXCEPTION 'value below definition minimum';
                END IF;
                IF v_def_max IS NOT NULL AND NEW.value_integer > v_def_max THEN
                    RAISE EXCEPTION 'value above definition maximum';
                END IF;
            END IF;
            IF v_def_type IN ('decimal', 'percentage') AND NEW.value_decimal IS NOT NULL THEN
                IF v_def_type = 'percentage' AND (NEW.value_decimal < 0 OR NEW.value_decimal > 100) THEN
                    RAISE EXCEPTION 'percentage value must be within 0 and 100';
                END IF;
                IF v_def_min IS NOT NULL AND NEW.value_decimal < v_def_min THEN
                    RAISE EXCEPTION 'value below definition minimum';
                END IF;
                IF v_def_max IS NOT NULL AND NEW.value_decimal > v_def_max THEN
                    RAISE EXCEPTION 'value above definition maximum';
                END IF;
            END IF;

            SELECT batch_id, effective_time INTO v_event_batch_id, v_event_effective
            FROM observation_events WHERE id = NEW.observation_event_id;

            IF NEW.batch_carrier_assignment_id IS NOT NULL THEN
                SELECT batch_id, assigned_effective_time INTO v_assignment_batch_id, v_assignment_assigned
                FROM batch_carrier_assignments WHERE id = NEW.batch_carrier_assignment_id;
                IF v_assignment_batch_id IS NULL THEN
                    RAISE EXCEPTION 'assignment not found';
                END IF;
                IF v_assignment_batch_id <> v_event_batch_id THEN
                    RAISE EXCEPTION 'assignment does not belong to this observation event''s batch';
                END IF;
                IF v_event_effective < v_assignment_assigned THEN
                    RAISE EXCEPTION 'observation effective time precedes assignment assigned_effective_time';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER observation_values_enforce_insert_integrity
        BEFORE INSERT ON observation_values
        FOR EACH ROW EXECUTE FUNCTION enforce_observation_value_insert_integrity();
        """
    )
    op.execute(
        """
        CREATE TRIGGER observation_values_no_update
        BEFORE UPDATE ON observation_values
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER observation_values_no_delete
        BEFORE DELETE ON observation_values
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )

    # germination_checks: assignment must belong to the event's batch with a
    # compatible effective time, and inspected_site_count cannot exceed the
    # assignment's original CMP-009 sown_site_count.
    op.execute(
        """
        CREATE FUNCTION enforce_germination_check_insert_integrity() RETURNS trigger AS $$
        DECLARE
            v_event_batch_id UUID;
            v_event_effective TIMESTAMPTZ;
            v_assignment_batch_id UUID;
            v_assignment_assigned TIMESTAMPTZ;
            v_sown_site_count INTEGER;
        BEGIN
            SELECT batch_id, effective_time INTO v_event_batch_id, v_event_effective
            FROM observation_events WHERE id = NEW.observation_event_id;

            SELECT batch_id, assigned_effective_time INTO v_assignment_batch_id, v_assignment_assigned
            FROM batch_carrier_assignments WHERE id = NEW.batch_carrier_assignment_id;
            IF v_assignment_batch_id IS NULL THEN
                RAISE EXCEPTION 'assignment not found';
            END IF;
            IF v_assignment_batch_id <> v_event_batch_id THEN
                RAISE EXCEPTION 'assignment does not belong to this observation event''s batch';
            END IF;
            IF v_event_effective < v_assignment_assigned THEN
                RAISE EXCEPTION 'observation effective time precedes assignment assigned_effective_time';
            END IF;

            SELECT sown_site_count INTO v_sown_site_count
            FROM sowing_event_lines WHERE batch_carrier_assignment_id = NEW.batch_carrier_assignment_id;
            IF v_sown_site_count IS NULL THEN
                RAISE EXCEPTION 'no sowing line found for this assignment';
            END IF;
            IF NEW.inspected_site_count > v_sown_site_count THEN
                RAISE EXCEPTION 'inspected_site_count cannot exceed the assignment''s original sown_site_count';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER germination_checks_enforce_insert_integrity
        BEFORE INSERT ON germination_checks
        FOR EACH ROW EXECUTE FUNCTION enforce_germination_check_insert_integrity();
        """
    )
    op.execute(
        """
        CREATE TRIGGER germination_checks_no_update
        BEFORE UPDATE ON germination_checks
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER germination_checks_no_delete
        BEFORE DELETE ON germination_checks
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )

    # quality_holds: active stage run must belong to the batch and be open,
    # batch must be active, and an optional source observation must belong
    # to the same batch with an effective time no later than the hold's.
    op.execute(
        """
        CREATE FUNCTION enforce_quality_hold_insert_integrity() RETURNS trigger AS $$
        DECLARE
            v_run_batch_id UUID;
            v_run_exited TIMESTAMPTZ;
            v_batch_state TEXT;
            v_source_batch_id UUID;
            v_source_effective TIMESTAMPTZ;
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
                RAISE EXCEPTION 'hold requires the batch''s currently active stage run';
            END IF;

            SELECT state INTO v_batch_state FROM crop_batches WHERE id = NEW.batch_id;
            IF v_batch_state IS DISTINCT FROM 'active' THEN
                RAISE EXCEPTION 'crop batch is not active';
            END IF;

            IF NEW.source_observation_event_id IS NOT NULL THEN
                SELECT batch_id, effective_time INTO v_source_batch_id, v_source_effective
                FROM observation_events WHERE id = NEW.source_observation_event_id;
                IF v_source_batch_id IS NULL THEN
                    RAISE EXCEPTION 'source observation event not found';
                END IF;
                IF v_source_batch_id <> NEW.batch_id THEN
                    RAISE EXCEPTION 'source observation event does not belong to this batch';
                END IF;
                IF v_source_effective > NEW.effective_time THEN
                    RAISE EXCEPTION 'source observation effective time cannot be after the hold effective time';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER quality_holds_enforce_insert_integrity
        BEFORE INSERT ON quality_holds
        FOR EACH ROW EXECUTE FUNCTION enforce_quality_hold_insert_integrity();
        """
    )
    op.execute(
        """
        CREATE TRIGGER quality_holds_no_update
        BEFORE UPDATE ON quality_holds
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER quality_holds_no_delete
        BEFORE DELETE ON quality_holds
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )

    # quality_hold_releases: release batch must match the hold's batch, and
    # release effective time cannot precede the hold's effective time. "One
    # release per hold" and "hold still open" are both already enforced by
    # ux_quality_hold_releases_hold.
    op.execute(
        """
        CREATE FUNCTION enforce_quality_hold_release_insert_integrity() RETURNS trigger AS $$
        DECLARE
            v_hold_batch_id UUID;
            v_hold_effective TIMESTAMPTZ;
        BEGIN
            SELECT batch_id, effective_time INTO v_hold_batch_id, v_hold_effective
            FROM quality_holds WHERE id = NEW.quality_hold_id;
            IF v_hold_batch_id IS NULL THEN
                RAISE EXCEPTION 'quality hold not found';
            END IF;
            IF v_hold_batch_id <> NEW.batch_id THEN
                RAISE EXCEPTION 'release batch does not match hold batch';
            END IF;
            IF NEW.effective_time < v_hold_effective THEN
                RAISE EXCEPTION 'release effective time cannot precede the hold effective time';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER quality_hold_releases_enforce_insert_integrity
        BEFORE INSERT ON quality_hold_releases
        FOR EACH ROW EXECUTE FUNCTION enforce_quality_hold_release_insert_integrity();
        """
    )
    op.execute(
        """
        CREATE TRIGGER quality_hold_releases_no_update
        BEFORE UPDATE ON quality_hold_releases
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER quality_hold_releases_no_delete
        BEFORE DELETE ON quality_hold_releases
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )

    # Defense in depth on the EXISTING CMP-008 batch_stage_transitions table:
    # a genuinely new stage_transition insert is rejected outright while any
    # unreleased quality hold exists for that transition's batch. Never
    # fires for command_kind = 'initial_entry'. No column or data change to
    # the existing table — only an additional trigger.
    op.execute(
        """
        CREATE FUNCTION enforce_no_open_quality_hold() RETURNS trigger AS $$
        DECLARE
            v_open_hold_exists BOOLEAN;
        BEGIN
            SELECT EXISTS (
                SELECT 1 FROM quality_holds h
                WHERE h.tenant_id = NEW.tenant_id AND h.farm_id = NEW.farm_id AND h.batch_id = NEW.batch_id
                AND NOT EXISTS (
                    SELECT 1 FROM quality_hold_releases r WHERE r.quality_hold_id = h.id
                )
            ) INTO v_open_hold_exists;
            IF v_open_hold_exists THEN
                RAISE EXCEPTION 'crop batch has an open quality hold; stage progression is blocked';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER batch_stage_transitions_enforce_no_open_hold
        BEFORE INSERT ON batch_stage_transitions
        FOR EACH ROW WHEN (NEW.command_kind = 'stage_transition')
        EXECUTE FUNCTION enforce_no_open_quality_hold();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS batch_stage_transitions_enforce_no_open_hold ON batch_stage_transitions"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_no_open_quality_hold()")

    op.execute("DROP TRIGGER IF EXISTS quality_hold_releases_no_delete ON quality_hold_releases")
    op.execute("DROP TRIGGER IF EXISTS quality_hold_releases_no_update ON quality_hold_releases")
    op.execute(
        "DROP TRIGGER IF EXISTS quality_hold_releases_enforce_insert_integrity ON quality_hold_releases"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_quality_hold_release_insert_integrity()")

    op.execute("DROP TRIGGER IF EXISTS quality_holds_no_delete ON quality_holds")
    op.execute("DROP TRIGGER IF EXISTS quality_holds_no_update ON quality_holds")
    op.execute("DROP TRIGGER IF EXISTS quality_holds_enforce_insert_integrity ON quality_holds")
    op.execute("DROP FUNCTION IF EXISTS enforce_quality_hold_insert_integrity()")

    op.execute("DROP TRIGGER IF EXISTS germination_checks_no_delete ON germination_checks")
    op.execute("DROP TRIGGER IF EXISTS germination_checks_no_update ON germination_checks")
    op.execute("DROP TRIGGER IF EXISTS germination_checks_enforce_insert_integrity ON germination_checks")
    op.execute("DROP FUNCTION IF EXISTS enforce_germination_check_insert_integrity()")

    op.execute("DROP TRIGGER IF EXISTS observation_values_no_delete ON observation_values")
    op.execute("DROP TRIGGER IF EXISTS observation_values_no_update ON observation_values")
    op.execute("DROP TRIGGER IF EXISTS observation_values_enforce_insert_integrity ON observation_values")
    op.execute("DROP FUNCTION IF EXISTS enforce_observation_value_insert_integrity()")

    op.execute("DROP TRIGGER IF EXISTS observation_events_no_delete ON observation_events")
    op.execute("DROP TRIGGER IF EXISTS observation_events_no_update ON observation_events")
    op.execute("DROP TRIGGER IF EXISTS observation_events_enforce_insert_integrity ON observation_events")
    op.execute("DROP FUNCTION IF EXISTS enforce_observation_event_insert_integrity()")

    op.execute("DROP TRIGGER IF EXISTS observation_definitions_no_delete ON observation_definitions")
    op.execute(
        "DROP TRIGGER IF EXISTS observation_definitions_enforce_status_only_update ON observation_definitions"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_observation_definition_status_only_update()")

    op.drop_index("ux_quality_hold_releases_hold", table_name="quality_hold_releases")
    op.drop_index("ux_quality_hold_releases_tenant_client_command_id", table_name="quality_hold_releases")
    op.drop_table("quality_hold_releases")

    op.drop_index("ix_quality_holds_tenant_farm_batch", table_name="quality_holds")
    op.drop_index("ux_quality_holds_tenant_client_command_id", table_name="quality_holds")
    op.drop_table("quality_holds")

    op.drop_table("germination_checks")

    op.drop_index("ux_observation_values_assignment_target", table_name="observation_values")
    op.drop_index("ux_observation_values_batch_target", table_name="observation_values")
    op.drop_table("observation_values")

    op.drop_index("ux_observation_events_tenant_client_command_id", table_name="observation_events")
    op.drop_table("observation_events")

    op.drop_index("ux_observation_definitions_tenant_code_lower", table_name="observation_definitions")
    op.drop_table("observation_definitions")
