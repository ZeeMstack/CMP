"""crop catalog and workflow configuration

Revision ID: b2f6c9d3e178
Revises: 8a2c6f1e9d33
Create Date: 2026-08-03 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'b2f6c9d3e178'
down_revision: Union[str, None] = '8a2c6f1e9d33'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STAGE_CATEGORIES = (
    "seeding",
    "germination",
    "nursery",
    "intermediate",
    "production",
    "harvest_ready",
    "completed",
    "rejected",
)


def upgrade() -> None:
    # --- crops --------------------------------------------------------------
    op.create_table(
        "crops",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("common_name", sa.String(), nullable=False),
        sa.Column("scientific_name", sa.String(), nullable=True),
        sa.Column("crop_category", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_crops_status"),
        sa.CheckConstraint(
            "crop_category IN ('leafy_green', 'vine', 'herb', 'other')", name="ck_crops_category_allowed"
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crops_tenant_id_id"),
    )
    op.create_index("ux_crops_tenant_code_lower", "crops", ["tenant_id", sa.text("lower(code)")], unique=True)

    # --- varieties ------------------------------------------------------------
    op.create_table(
        "varieties",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("crop_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("crops.id"), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("supplier_reference", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_varieties_status"),
        sa.UniqueConstraint("tenant_id", "crop_id", "id", name="uq_varieties_tenant_crop_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "crop_id"], ["crops.tenant_id", "crops.id"], name="fk_varieties_tenant_crop"
        ),
    )
    op.create_index(
        "ux_varieties_crop_code_lower", "varieties", ["crop_id", sa.text("lower(code)")], unique=True
    )

    # --- production_systems ---------------------------------------------------
    op.create_table(
        "production_systems",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_production_systems_status"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_production_systems_tenant_id_id"),
    )
    op.create_index(
        "ux_production_systems_tenant_code_lower",
        "production_systems",
        ["tenant_id", sa.text("lower(code)")],
        unique=True,
    )

    # --- workflows --------------------------------------------------------------
    op.create_table(
        "workflows",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("crop_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("crops.id"), nullable=False),
        sa.Column("variety_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("varieties.id"), nullable=True),
        sa.Column(
            "production_system_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("production_systems.id"),
            nullable=False,
        ),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_workflows_status"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_workflows_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "crop_id"], ["crops.tenant_id", "crops.id"], name="fk_workflows_tenant_crop"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "production_system_id"],
            ["production_systems.tenant_id", "production_systems.id"],
            name="fk_workflows_tenant_production_system",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "crop_id", "variety_id"],
            ["varieties.tenant_id", "varieties.crop_id", "varieties.id"],
            name="fk_workflows_tenant_crop_variety",
        ),
    )
    op.create_index(
        "ux_workflows_tenant_code_lower", "workflows", ["tenant_id", sa.text("lower(code)")], unique=True
    )

    # --- workflow_versions --------------------------------------------------------
    op.create_table(
        "workflow_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workflows.id"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("state IN ('draft', 'published', 'retired')", name="ck_workflow_versions_state"),
        sa.CheckConstraint("version_number > 0", name="ck_workflow_versions_number_positive"),
        sa.CheckConstraint(
            "(state = 'draft' AND published_at IS NULL AND retired_at IS NULL) OR "
            "(state = 'published' AND published_at IS NOT NULL AND retired_at IS NULL) OR "
            "(state = 'retired' AND published_at IS NOT NULL AND retired_at IS NOT NULL)",
            name="ck_workflow_versions_state_timestamps",
        ),
        sa.CheckConstraint(
            "retired_at IS NULL OR published_at IS NULL OR retired_at >= published_at",
            name="ck_workflow_versions_retired_after_published",
        ),
        sa.UniqueConstraint("workflow_id", "version_number", name="uq_workflow_versions_workflow_number"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_workflow_versions_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "workflow_id"],
            ["workflows.tenant_id", "workflows.id"],
            name="fk_workflow_versions_tenant_workflow",
        ),
    )
    op.create_index(
        "ux_workflow_versions_one_published",
        "workflow_versions",
        ["workflow_id"],
        unique=True,
        postgresql_where=sa.text("state = 'published'"),
    )

    # --- workflow_stages --------------------------------------------------------
    op.create_table(
        "workflow_stages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "workflow_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflow_versions.id"),
            nullable=False,
        ),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("stage_category", sa.String(), nullable=False),
        sa.Column("expected_duration_minutes", sa.Integer(), nullable=True),
        sa.Column(
            "permitted_location_type_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("location_types.id"),
            nullable=True,
        ),
        sa.Column(
            "required_carrier_type_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("carrier_types.id"),
            nullable=True,
        ),
        sa.Column("is_start", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_terminal", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "stage_category IN ('" + "', '".join(_STAGE_CATEGORIES) + "')",
            name="ck_workflow_stages_category_allowed",
        ),
        sa.CheckConstraint("display_order >= 0", name="ck_workflow_stages_display_order_non_negative"),
        sa.CheckConstraint(
            "expected_duration_minutes IS NULL OR expected_duration_minutes > 0",
            name="ck_workflow_stages_duration_positive",
        ),
        sa.UniqueConstraint(
            "tenant_id", "workflow_version_id", "id", name="uq_workflow_stages_tenant_version_id"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "workflow_version_id"],
            ["workflow_versions.tenant_id", "workflow_versions.id"],
            name="fk_workflow_stages_tenant_version",
        ),
    )
    op.create_index(
        "ux_workflow_stages_version_code_lower",
        "workflow_stages",
        ["workflow_version_id", sa.text("lower(code)")],
        unique=True,
    )

    # --- workflow_transitions --------------------------------------------------------
    op.create_table(
        "workflow_transitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "workflow_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflow_versions.id"),
            nullable=False,
        ),
        sa.Column("from_stage_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workflow_stages.id"), nullable=False),
        sa.Column("to_stage_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workflow_stages.id"), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("from_stage_id <> to_stage_id", name="ck_workflow_transitions_no_self_transition"),
        sa.UniqueConstraint(
            "workflow_version_id", "from_stage_id", "to_stage_id", name="uq_workflow_transitions_pair"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "workflow_version_id"],
            ["workflow_versions.tenant_id", "workflow_versions.id"],
            name="fk_workflow_transitions_tenant_version",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "workflow_version_id", "from_stage_id"],
            ["workflow_stages.tenant_id", "workflow_stages.workflow_version_id", "workflow_stages.id"],
            name="fk_workflow_transitions_from_stage",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "workflow_version_id", "to_stage_id"],
            ["workflow_stages.tenant_id", "workflow_stages.workflow_version_id", "workflow_stages.id"],
            name="fk_workflow_transitions_to_stage",
        ),
    )
    op.create_index(
        "ux_workflow_transitions_version_code_lower",
        "workflow_transitions",
        ["workflow_version_id", sa.text("lower(code)")],
        unique=True,
    )

    # --- workflow_version lifecycle: only draft->published->retired, and the
    # tenant/workflow/version_number/created_at identity fields never change.
    op.execute(
        """
        CREATE FUNCTION enforce_workflow_version_transition() RETURNS trigger AS $$
        BEGIN
            IF NEW.tenant_id <> OLD.tenant_id
               OR NEW.workflow_id <> OLD.workflow_id
               OR NEW.version_number <> OLD.version_number
               OR NEW.created_at <> OLD.created_at
            THEN
                RAISE EXCEPTION 'tenant_id, workflow_id, version_number, and created_at are immutable on workflow_versions';
            END IF;

            IF OLD.state = NEW.state THEN
                RAISE EXCEPTION 'workflow_versions may only be updated to advance lifecycle state';
            END IF;

            IF NOT ((OLD.state = 'draft' AND NEW.state = 'published')
                    OR (OLD.state = 'published' AND NEW.state = 'retired')) THEN
                RAISE EXCEPTION 'invalid workflow_version state transition: % -> %', OLD.state, NEW.state;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER workflow_versions_enforce_transition
        BEFORE UPDATE ON workflow_versions
        FOR EACH ROW EXECUTE FUNCTION enforce_workflow_version_transition();
        """
    )

    # Published/retired versions are immutable history; draft deletion is not
    # exposed through the API in CMP-007 but is not blocked at the DB level.
    op.execute(
        """
        CREATE FUNCTION reject_non_draft_workflow_version_delete() RETURNS trigger AS $$
        BEGIN
            IF OLD.state <> 'draft' THEN
                RAISE EXCEPTION 'published or retired workflow_versions cannot be hard-deleted';
            END IF;
            RETURN OLD;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER workflow_versions_no_delete_when_published
        BEFORE DELETE ON workflow_versions
        FOR EACH ROW EXECUTE FUNCTION reject_non_draft_workflow_version_delete();
        """
    )

    # Stages/transitions may only be created, changed, or removed while their
    # parent workflow version is still draft — covers both the "draft only"
    # creation rule and the published/retired-structure protection rule.
    op.execute(
        """
        CREATE FUNCTION enforce_workflow_stage_draft_only() RETURNS trigger AS $$
        DECLARE
            ver_state TEXT;
            ver_id UUID;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                ver_id := NEW.workflow_version_id;
            ELSE
                ver_id := OLD.workflow_version_id;
            END IF;

            SELECT state INTO ver_state FROM workflow_versions WHERE id = ver_id;
            IF ver_state IS DISTINCT FROM 'draft' THEN
                RAISE EXCEPTION 'workflow_stages can only be created, changed, or removed while their workflow version is draft';
            END IF;

            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER workflow_stages_enforce_draft_only
        BEFORE INSERT OR UPDATE OR DELETE ON workflow_stages
        FOR EACH ROW EXECUTE FUNCTION enforce_workflow_stage_draft_only();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_workflow_transition_draft_only() RETURNS trigger AS $$
        DECLARE
            ver_state TEXT;
            ver_id UUID;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                ver_id := NEW.workflow_version_id;
            ELSE
                ver_id := OLD.workflow_version_id;
            END IF;

            SELECT state INTO ver_state FROM workflow_versions WHERE id = ver_id;
            IF ver_state IS DISTINCT FROM 'draft' THEN
                RAISE EXCEPTION 'workflow_transitions can only be created, changed, or removed while their workflow version is draft';
            END IF;

            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER workflow_transitions_enforce_draft_only
        BEFORE INSERT OR UPDATE OR DELETE ON workflow_transitions
        FOR EACH ROW EXECUTE FUNCTION enforce_workflow_transition_draft_only();
        """
    )

    # A workflow's identity (tenant/crop/variety/production system) cannot
    # change once any of its versions has been published.
    op.execute(
        """
        CREATE FUNCTION enforce_workflow_identity_immutable() RETURNS trigger AS $$
        DECLARE
            has_published INT;
        BEGIN
            IF NEW.tenant_id = OLD.tenant_id
               AND NEW.crop_id = OLD.crop_id
               AND NEW.variety_id IS NOT DISTINCT FROM OLD.variety_id
               AND NEW.production_system_id = OLD.production_system_id
            THEN
                RETURN NEW;
            END IF;

            SELECT 1 INTO has_published FROM workflow_versions
            WHERE workflow_id = OLD.id AND state IN ('published', 'retired')
            LIMIT 1;

            IF has_published IS NOT NULL THEN
                RAISE EXCEPTION 'workflow identity fields cannot change once a version has been published';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER workflows_enforce_identity_immutable
        BEFORE UPDATE ON workflows
        FOR EACH ROW EXECUTE FUNCTION enforce_workflow_identity_immutable();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS workflows_enforce_identity_immutable ON workflows")
    op.execute("DROP FUNCTION IF EXISTS enforce_workflow_identity_immutable()")

    op.execute("DROP TRIGGER IF EXISTS workflow_transitions_enforce_draft_only ON workflow_transitions")
    op.execute("DROP FUNCTION IF EXISTS enforce_workflow_transition_draft_only()")

    op.execute("DROP TRIGGER IF EXISTS workflow_stages_enforce_draft_only ON workflow_stages")
    op.execute("DROP FUNCTION IF EXISTS enforce_workflow_stage_draft_only()")

    op.execute("DROP TRIGGER IF EXISTS workflow_versions_no_delete_when_published ON workflow_versions")
    op.execute("DROP FUNCTION IF EXISTS reject_non_draft_workflow_version_delete()")

    op.execute("DROP TRIGGER IF EXISTS workflow_versions_enforce_transition ON workflow_versions")
    op.execute("DROP FUNCTION IF EXISTS enforce_workflow_version_transition()")

    op.drop_index("ux_workflow_transitions_version_code_lower", table_name="workflow_transitions")
    op.drop_table("workflow_transitions")

    op.drop_index("ux_workflow_stages_version_code_lower", table_name="workflow_stages")
    op.drop_table("workflow_stages")

    op.drop_index("ux_workflow_versions_one_published", table_name="workflow_versions")
    op.drop_table("workflow_versions")

    op.drop_index("ux_workflows_tenant_code_lower", table_name="workflows")
    op.drop_table("workflows")

    op.drop_index("ux_production_systems_tenant_code_lower", table_name="production_systems")
    op.drop_table("production_systems")

    op.drop_index("ux_varieties_crop_code_lower", table_name="varieties")
    op.drop_table("varieties")

    op.drop_index("ux_crops_tenant_code_lower", table_name="crops")
    op.drop_table("crops")
