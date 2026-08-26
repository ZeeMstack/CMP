"""grade definition configuration

Revision ID: c9e3f7a2d5b8
Revises: b8f3c6d1e947
Create Date: 2026-08-25 00:00:00.000000

POSTHARVEST-OPS-001A: configurable, versioned commercial Grade definitions.
Completely separate from the biological workflow/version model (no
change to `workflows`/`workflow_versions`/`workflow_stages`/
`workflow_transitions`). Adds two new, additive tables:

- `grade_definitions` — the stable, tenant-scoped commercial-grade
  identity (crop required, variety optional/null-safe), mirroring
  `workflows`'s own tenant/crop/variety composite-FK shape exactly.
- `grade_definition_versions` — the versioned, immutable-once-created
  criteria, mirroring `workflow_versions`'s own
  draft -> active/published -> retired lifecycle shape
  (`enforce_workflow_version_transition`, `ux_workflow_versions_one_
  published`), widened with per-command idempotency columns
  (`client_command_id`/`request_fingerprint`, and separate
  `activation_*`/`retirement_*` pairs) that `workflow_versions` itself
  does not have — this ticket's own frozen idempotency requirement is
  stricter than that precedent, not a copy of it.

No change to any existing table, trigger, function, or historical
migration.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c9e3f7a2d5b8"
down_revision: Union[str, None] = "b8f3c6d1e947"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- grade_definitions --------------------------------------------------------
    op.create_table(
        "grade_definitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("crop_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("crops.id"), nullable=False),
        sa.Column("variety_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("varieties.id"), nullable=True),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.UniqueConstraint("tenant_id", "id", name="uq_grade_definitions_tenant_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "crop_id"], ["crops.tenant_id", "crops.id"], name="fk_grade_definitions_tenant_crop"
        ),
        # MATCH SIMPLE (Postgres default): only evaluated when variety_id IS
        # NOT NULL — a NULL variety_id ("applies to all varieties of the
        # crop") never engages this FK. Mirrors
        # fk_workflows_tenant_crop_variety exactly.
        sa.ForeignKeyConstraint(
            ["tenant_id", "crop_id", "variety_id"],
            ["varieties.tenant_id", "varieties.crop_id", "varieties.id"],
            name="fk_grade_definitions_tenant_crop_variety",
        ),
    )
    op.create_index(
        "ux_grade_definitions_tenant_code_lower", "grade_definitions",
        ["tenant_id", sa.text("lower(code)")], unique=True,
    )
    op.create_index(
        "ux_grade_definitions_tenant_client_command_id", "grade_definitions",
        ["tenant_id", "client_command_id"], unique=True,
    )

    # --- grade_definition_versions -------------------------------------------------
    op.create_table(
        "grade_definition_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "grade_definition_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("grade_definitions.id"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("spec_notes", sa.String(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.Column("activation_client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("activation_request_fingerprint", sa.String(), nullable=True),
        sa.Column("retirement_client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("retirement_request_fingerprint", sa.String(), nullable=True),
        sa.CheckConstraint("status IN ('draft', 'active', 'retired')", name="ck_grade_definition_versions_status"),
        sa.CheckConstraint("version_number > 0", name="ck_grade_definition_versions_number_positive"),
        sa.CheckConstraint(
            "(status = 'draft' AND effective_from IS NULL AND effective_until IS NULL "
            " AND activation_client_command_id IS NULL AND activation_request_fingerprint IS NULL "
            " AND retirement_client_command_id IS NULL AND retirement_request_fingerprint IS NULL) "
            "OR (status = 'active' AND effective_from IS NOT NULL AND effective_until IS NULL "
            " AND activation_client_command_id IS NOT NULL AND activation_request_fingerprint IS NOT NULL "
            " AND retirement_client_command_id IS NULL AND retirement_request_fingerprint IS NULL) "
            "OR (status = 'retired' AND effective_from IS NOT NULL AND effective_until IS NOT NULL "
            " AND activation_client_command_id IS NOT NULL AND activation_request_fingerprint IS NOT NULL)",
            name="ck_grade_definition_versions_status_shape",
        ),
        sa.CheckConstraint(
            "effective_until IS NULL OR effective_until >= effective_from",
            name="ck_grade_definition_versions_effective_order",
        ),
        sa.UniqueConstraint(
            "grade_definition_id", "version_number", name="uq_grade_definition_versions_definition_number"
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_grade_definition_versions_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id", "grade_definition_id", "id", name="uq_grade_definition_versions_tenant_definition_id"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "grade_definition_id"],
            ["grade_definitions.tenant_id", "grade_definitions.id"],
            name="fk_grade_definition_versions_tenant_definition",
        ),
    )
    # DB-level "at most one ACTIVE version per GradeDefinition" — partial,
    # kind-scoped so many draft/retired rows may coexist freely. Not
    # service-logic-only, mirroring ux_workflow_versions_one_published.
    op.create_index(
        "ux_grade_definition_versions_active_once", "grade_definition_versions", ["grade_definition_id"],
        unique=True, postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "ux_grade_definition_versions_tenant_client_command_id", "grade_definition_versions",
        ["tenant_id", "client_command_id"], unique=True,
    )
    op.create_index(
        "ux_grade_definition_versions_tenant_activation_command", "grade_definition_versions",
        ["tenant_id", "activation_client_command_id"], unique=True,
        postgresql_where=sa.text("activation_client_command_id IS NOT NULL"),
    )
    op.create_index(
        "ux_grade_definition_versions_tenant_retirement_command", "grade_definition_versions",
        ["tenant_id", "retirement_client_command_id"], unique=True,
        postgresql_where=sa.text("retirement_client_command_id IS NOT NULL"),
    )

    # --- lifecycle transition guard: draft -> active -> retired only, and every
    # other field frozen once a version has left draft (mirrors
    # enforce_workflow_version_transition exactly, adapted to this ticket's
    # own column set, including the idempotency-key columns). ------------------
    op.execute(
        """
        CREATE FUNCTION enforce_grade_definition_version_transition() RETURNS trigger AS $$
        BEGIN
            IF NEW.tenant_id <> OLD.tenant_id
               OR NEW.grade_definition_id <> OLD.grade_definition_id
               OR NEW.version_number <> OLD.version_number
               OR NEW.created_at <> OLD.created_at
               OR NEW.spec_notes IS DISTINCT FROM OLD.spec_notes
               OR NEW.created_by IS DISTINCT FROM OLD.created_by
               OR NEW.client_command_id <> OLD.client_command_id
               OR NEW.request_fingerprint <> OLD.request_fingerprint
            THEN
                RAISE EXCEPTION 'tenant_id, grade_definition_id, version_number, created_at, spec_notes, '
                    'created_by, client_command_id, and request_fingerprint are immutable on '
                    'grade_definition_versions';
            END IF;

            IF OLD.status = NEW.status THEN
                RAISE EXCEPTION 'grade_definition_versions may only be updated to advance lifecycle status';
            END IF;

            IF NOT ((OLD.status = 'draft' AND NEW.status = 'active')
                    OR (OLD.status = 'active' AND NEW.status = 'retired')) THEN
                RAISE EXCEPTION 'invalid grade_definition_version status transition: % -> %', OLD.status, NEW.status;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER grade_definition_versions_enforce_transition
        BEFORE UPDATE ON grade_definition_versions
        FOR EACH ROW EXECUTE FUNCTION enforce_grade_definition_version_transition();
        """
    )

    # --- immutability / no hard delete --------------------------------------------
    # Unconditional, unlike workflow_versions' own draft-only-deletable
    # guard: this ticket's frozen scope requires hard delete rejected for
    # every GradeDefinitionVersion regardless of lifecycle status.
    op.execute(
        """
        CREATE FUNCTION reject_grade_definition_version_delete() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'grade_definition_versions cannot be hard-deleted';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER grade_definition_versions_no_delete
        BEFORE DELETE ON grade_definition_versions
        FOR EACH ROW EXECUTE FUNCTION reject_grade_definition_version_delete();
        """
    )

    # GradeDefinition itself has no update endpoint in this ticket and is a
    # stable identity that "must never change from one crop/variety scope
    # to another" — reject both UPDATE and hard DELETE unconditionally.
    op.execute(
        """
        CREATE FUNCTION reject_grade_definition_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'grade_definitions cannot be updated or hard-deleted';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER grade_definitions_no_update
        BEFORE UPDATE ON grade_definitions
        FOR EACH ROW EXECUTE FUNCTION reject_grade_definition_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER grade_definitions_no_delete
        BEFORE DELETE ON grade_definitions
        FOR EACH ROW EXECUTE FUNCTION reject_grade_definition_mutation();
        """
    )


def downgrade() -> None:
    bind = op.get_bind()

    # --- downgrade guard: persisted commercial configuration is not discardable ---
    definition_count = bind.execute(sa.text("SELECT count(*) FROM grade_definitions")).scalar_one()
    version_count = bind.execute(sa.text("SELECT count(*) FROM grade_definition_versions")).scalar_one()
    if definition_count or version_count:
        raise RuntimeError(
            "Cannot downgrade past POSTHARVEST-OPS-001A: persisted GradeDefinition or "
            "GradeDefinitionVersion rows exist. Downgrading would silently discard commercial grade "
            "configuration. Remove or migrate the offending data out-of-band first, or do not downgrade."
        )

    op.execute("DROP TRIGGER IF EXISTS grade_definitions_no_delete ON grade_definitions")
    op.execute("DROP TRIGGER IF EXISTS grade_definitions_no_update ON grade_definitions")
    op.execute("DROP FUNCTION IF EXISTS reject_grade_definition_mutation()")

    op.execute("DROP TRIGGER IF EXISTS grade_definition_versions_no_delete ON grade_definition_versions")
    op.execute("DROP FUNCTION IF EXISTS reject_grade_definition_version_delete()")

    op.execute("DROP TRIGGER IF EXISTS grade_definition_versions_enforce_transition ON grade_definition_versions")
    op.execute("DROP FUNCTION IF EXISTS enforce_grade_definition_version_transition()")

    op.drop_table("grade_definition_versions")
    op.drop_table("grade_definitions")
