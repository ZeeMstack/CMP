"""packaging unit and pack specification configuration

Revision ID: e8d5f3a2b6c1
Revises: c9e3f7a2d5b8
Create Date: 2026-08-25 00:00:00.000000

POSTHARVEST-OPS-001B: configuration-only commercial Packaging Unit and
Pack Specification (+ version) domain, consumed by a later Packing-
contract ticket. Adds three new, additive tables:

- `packaging_units` — simple tenant-scoped stable identity, no versioning,
  a two-state `active -> retired` lifecycle mirroring GradeDefinitionVersion's
  own hard-delete-rejection/transition-guard idiom at the smallest possible
  scale.
- `pack_specifications` — the stable commercial pack/product identity,
  reusing GradeDefinition's exact tenant/crop/variety composite-FK shape.
- `pack_specification_versions` — the versioned, immutable-once-created
  exact commercial packing standard, reusing GradeDefinitionVersion's
  exact `draft -> active -> retired` lifecycle/idempotency-column shape,
  widened with a narrow INSERT-only integrity trigger that a same-row
  CHECK/plain FK cannot express: the referenced PackagingUnit must be
  ACTIVE at creation time, and an optional referenced GradeDefinitionVersion
  must be non-DRAFT and crop/variety-compatible with this version's own
  parent PackSpecification.

No change to any existing table, trigger, function, or historical
migration (including c9e3f7a2d5b8 and b8f3c6d1e947, neither of which is
edited).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "e8d5f3a2b6c1"
down_revision: Union[str, None] = "c9e3f7a2d5b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- packaging_units -----------------------------------------------------------
    op.create_table(
        "packaging_units",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.Column("retirement_client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("retirement_request_fingerprint", sa.String(), nullable=True),
        sa.CheckConstraint("status IN ('active', 'retired')", name="ck_packaging_units_status"),
        sa.CheckConstraint(
            "(status = 'active' AND retirement_client_command_id IS NULL "
            " AND retirement_request_fingerprint IS NULL) "
            "OR (status = 'retired' AND retirement_client_command_id IS NOT NULL "
            " AND retirement_request_fingerprint IS NOT NULL)",
            name="ck_packaging_units_status_shape",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_packaging_units_tenant_id"),
    )
    op.create_index(
        "ux_packaging_units_tenant_code_lower", "packaging_units", ["tenant_id", sa.text("lower(code)")],
        unique=True,
    )
    op.create_index(
        "ux_packaging_units_tenant_client_command_id", "packaging_units", ["tenant_id", "client_command_id"],
        unique=True,
    )
    op.create_index(
        "ux_packaging_units_tenant_retirement_command", "packaging_units",
        ["tenant_id", "retirement_client_command_id"], unique=True,
        postgresql_where=sa.text("retirement_client_command_id IS NOT NULL"),
    )

    # Two-state lifecycle guard: active -> retired only, identity fields frozen.
    op.execute(
        """
        CREATE FUNCTION enforce_packaging_unit_transition() RETURNS trigger AS $$
        BEGIN
            IF NEW.tenant_id <> OLD.tenant_id
               OR NEW.code <> OLD.code
               OR NEW.name <> OLD.name
               OR NEW.created_at <> OLD.created_at
               OR NEW.client_command_id <> OLD.client_command_id
               OR NEW.request_fingerprint <> OLD.request_fingerprint
            THEN
                RAISE EXCEPTION 'tenant_id, code, name, created_at, client_command_id, and '
                    'request_fingerprint are immutable on packaging_units';
            END IF;

            IF OLD.status = NEW.status THEN
                RAISE EXCEPTION 'packaging_units may only be updated to advance lifecycle status';
            END IF;

            IF NOT (OLD.status = 'active' AND NEW.status = 'retired') THEN
                RAISE EXCEPTION 'invalid packaging_unit status transition: % -> %', OLD.status, NEW.status;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER packaging_units_enforce_transition
        BEFORE UPDATE ON packaging_units
        FOR EACH ROW EXECUTE FUNCTION enforce_packaging_unit_transition();
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_packaging_unit_delete() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'packaging_units cannot be hard-deleted';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER packaging_units_no_delete
        BEFORE DELETE ON packaging_units
        FOR EACH ROW EXECUTE FUNCTION reject_packaging_unit_delete();
        """
    )

    # --- pack_specifications --------------------------------------------------------
    op.create_table(
        "pack_specifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("crop_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("crops.id"), nullable=False),
        sa.Column("variety_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("varieties.id"), nullable=True),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("customer_reference", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.UniqueConstraint("tenant_id", "id", name="uq_pack_specifications_tenant_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "crop_id"], ["crops.tenant_id", "crops.id"], name="fk_pack_specifications_tenant_crop"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "crop_id", "variety_id"],
            ["varieties.tenant_id", "varieties.crop_id", "varieties.id"],
            name="fk_pack_specifications_tenant_crop_variety",
        ),
    )
    op.create_index(
        "ux_pack_specifications_tenant_code_lower", "pack_specifications", ["tenant_id", sa.text("lower(code)")],
        unique=True,
    )
    op.create_index(
        "ux_pack_specifications_tenant_client_command_id", "pack_specifications",
        ["tenant_id", "client_command_id"], unique=True,
    )

    # Stable identity: no update endpoint, must never silently drift; hard
    # delete unconditionally rejected -- mirrors reject_grade_definition_mutation.
    op.execute(
        """
        CREATE FUNCTION reject_pack_specification_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'pack_specifications cannot be updated or hard-deleted';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER pack_specifications_no_update
        BEFORE UPDATE ON pack_specifications
        FOR EACH ROW EXECUTE FUNCTION reject_pack_specification_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER pack_specifications_no_delete
        BEFORE DELETE ON pack_specifications
        FOR EACH ROW EXECUTE FUNCTION reject_pack_specification_mutation();
        """
    )

    # --- pack_specification_versions -------------------------------------------------
    op.create_table(
        "pack_specification_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "pack_specification_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("pack_specifications.id"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column(
            "grade_definition_version_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("grade_definition_versions.id"), nullable=True,
        ),
        sa.Column(
            "packaging_unit_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("packaging_units.id"),
            nullable=False,
        ),
        sa.Column("nominal_net_weight_kg", sa.Numeric(), nullable=True),
        sa.Column("whole_units_per_pack", sa.BigInteger(), nullable=True),
        sa.Column("spec_notes", sa.String(), nullable=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.Column("activation_client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("activation_request_fingerprint", sa.String(), nullable=True),
        sa.Column("retirement_client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("retirement_request_fingerprint", sa.String(), nullable=True),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'retired')", name="ck_pack_specification_versions_status"
        ),
        sa.CheckConstraint("version_number > 0", name="ck_pack_specification_versions_number_positive"),
        sa.CheckConstraint(
            "(status = 'draft' AND effective_from IS NULL AND effective_until IS NULL "
            " AND activation_client_command_id IS NULL AND activation_request_fingerprint IS NULL "
            " AND retirement_client_command_id IS NULL AND retirement_request_fingerprint IS NULL) "
            "OR (status = 'active' AND effective_from IS NOT NULL AND effective_until IS NULL "
            " AND activation_client_command_id IS NOT NULL AND activation_request_fingerprint IS NOT NULL "
            " AND retirement_client_command_id IS NULL AND retirement_request_fingerprint IS NULL) "
            "OR (status = 'retired' AND effective_from IS NOT NULL AND effective_until IS NOT NULL "
            " AND activation_client_command_id IS NOT NULL AND activation_request_fingerprint IS NOT NULL)",
            name="ck_pack_specification_versions_status_shape",
        ),
        sa.CheckConstraint(
            "effective_until IS NULL OR effective_until >= effective_from",
            name="ck_pack_specification_versions_effective_order",
        ),
        sa.CheckConstraint(
            "nominal_net_weight_kg IS NOT NULL OR whole_units_per_pack IS NOT NULL",
            name="ck_pack_specification_versions_measure_present",
        ),
        sa.CheckConstraint(
            "nominal_net_weight_kg IS NULL OR (nominal_net_weight_kg > 0 "
            "AND nominal_net_weight_kg = trunc(nominal_net_weight_kg, 3) "
            "AND nominal_net_weight_kg < 100000000000)",
            name="ck_pack_specification_versions_weight_envelope",
        ),
        sa.CheckConstraint(
            "whole_units_per_pack IS NULL OR whole_units_per_pack > 0",
            name="ck_pack_specification_versions_units_positive",
        ),
        sa.UniqueConstraint(
            "pack_specification_id", "version_number", name="uq_pack_specification_versions_spec_number"
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_pack_specification_versions_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id", "pack_specification_id", "id", name="uq_pack_specification_versions_tenant_spec_id"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "pack_specification_id"],
            ["pack_specifications.tenant_id", "pack_specifications.id"],
            name="fk_pack_specification_versions_tenant_spec",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "packaging_unit_id"],
            ["packaging_units.tenant_id", "packaging_units.id"],
            name="fk_pack_specification_versions_tenant_unit",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "grade_definition_version_id"],
            ["grade_definition_versions.tenant_id", "grade_definition_versions.id"],
            name="fk_pack_specification_versions_tenant_grade_version",
        ),
    )
    op.create_index(
        "ux_pack_specification_versions_active_once", "pack_specification_versions", ["pack_specification_id"],
        unique=True, postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "ux_pack_specification_versions_tenant_client_command_id", "pack_specification_versions",
        ["tenant_id", "client_command_id"], unique=True,
    )
    op.create_index(
        "ux_pack_specification_versions_tenant_activation_command", "pack_specification_versions",
        ["tenant_id", "activation_client_command_id"], unique=True,
        postgresql_where=sa.text("activation_client_command_id IS NOT NULL"),
    )
    op.create_index(
        "ux_pack_specification_versions_tenant_retirement_command", "pack_specification_versions",
        ["tenant_id", "retirement_client_command_id"], unique=True,
        postgresql_where=sa.text("retirement_client_command_id IS NOT NULL"),
    )

    # --- lifecycle transition guard (mirrors enforce_grade_definition_version_transition) ---
    op.execute(
        """
        CREATE FUNCTION enforce_pack_specification_version_transition() RETURNS trigger AS $$
        BEGIN
            IF NEW.tenant_id <> OLD.tenant_id
               OR NEW.pack_specification_id <> OLD.pack_specification_id
               OR NEW.version_number <> OLD.version_number
               OR NEW.created_at <> OLD.created_at
               OR NEW.grade_definition_version_id IS DISTINCT FROM OLD.grade_definition_version_id
               OR NEW.packaging_unit_id <> OLD.packaging_unit_id
               OR NEW.nominal_net_weight_kg IS DISTINCT FROM OLD.nominal_net_weight_kg
               OR NEW.whole_units_per_pack IS DISTINCT FROM OLD.whole_units_per_pack
               OR NEW.spec_notes IS DISTINCT FROM OLD.spec_notes
               OR NEW.created_by IS DISTINCT FROM OLD.created_by
               OR NEW.client_command_id <> OLD.client_command_id
               OR NEW.request_fingerprint <> OLD.request_fingerprint
            THEN
                RAISE EXCEPTION 'semantic and identity fields are immutable on pack_specification_versions';
            END IF;

            IF OLD.status = NEW.status THEN
                RAISE EXCEPTION 'pack_specification_versions may only be updated to advance lifecycle status';
            END IF;

            IF NOT ((OLD.status = 'draft' AND NEW.status = 'active')
                    OR (OLD.status = 'active' AND NEW.status = 'retired')) THEN
                RAISE EXCEPTION 'invalid pack_specification_version status transition: % -> %', OLD.status, NEW.status;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER pack_specification_versions_enforce_transition
        BEFORE UPDATE ON pack_specification_versions
        FOR EACH ROW EXECUTE FUNCTION enforce_pack_specification_version_transition();
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_pack_specification_version_delete() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'pack_specification_versions cannot be hard-deleted';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER pack_specification_versions_no_delete
        BEFORE DELETE ON pack_specification_versions
        FOR EACH ROW EXECUTE FUNCTION reject_pack_specification_version_delete();
        """
    )

    # --- cross-table insert integrity: PackagingUnit ACTIVE-at-creation, and
    # optional GradeDefinitionVersion non-DRAFT + crop/variety compatibility --
    # neither a same-row CHECK nor a plain FK can express a cross-table STATUS
    # comparison or a two-hop crop/variety join. -------------------------------
    op.execute(
        """
        CREATE FUNCTION enforce_pack_specification_version_insert_integrity() RETURNS trigger AS $$
        DECLARE
            spec_crop_id UUID;
            spec_variety_id UUID;
            unit_status TEXT;
            grade_status TEXT;
            grade_def_id UUID;
            grade_crop_id UUID;
            grade_variety_id UUID;
        BEGIN
            SELECT crop_id, variety_id INTO spec_crop_id, spec_variety_id
            FROM pack_specifications WHERE id = NEW.pack_specification_id;

            SELECT status INTO unit_status FROM packaging_units WHERE id = NEW.packaging_unit_id;
            IF unit_status IS DISTINCT FROM 'active' THEN
                RAISE EXCEPTION 'packaging_unit % is not active', NEW.packaging_unit_id;
            END IF;

            IF NEW.grade_definition_version_id IS NOT NULL THEN
                SELECT status, grade_definition_id INTO grade_status, grade_def_id
                FROM grade_definition_versions WHERE id = NEW.grade_definition_version_id;

                IF grade_status = 'draft' THEN
                    RAISE EXCEPTION 'grade_definition_version % is draft and cannot be referenced',
                        NEW.grade_definition_version_id;
                END IF;

                SELECT crop_id, variety_id INTO grade_crop_id, grade_variety_id
                FROM grade_definitions WHERE id = grade_def_id;

                IF grade_crop_id IS DISTINCT FROM spec_crop_id THEN
                    RAISE EXCEPTION 'grade_definition_version % crop does not match the pack '
                        'specification''s crop', NEW.grade_definition_version_id;
                END IF;

                IF spec_variety_id IS NOT NULL AND grade_variety_id IS NOT NULL
                   AND grade_variety_id <> spec_variety_id THEN
                    RAISE EXCEPTION 'grade_definition_version % variety is incompatible with the pack '
                        'specification''s variety', NEW.grade_definition_version_id;
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER pack_specification_versions_enforce_insert_integrity
        BEFORE INSERT ON pack_specification_versions
        FOR EACH ROW EXECUTE FUNCTION enforce_pack_specification_version_insert_integrity();
        """
    )


def downgrade() -> None:
    bind = op.get_bind()

    # --- downgrade guard: persisted commercial configuration is not discardable ---
    version_count = bind.execute(sa.text("SELECT count(*) FROM pack_specification_versions")).scalar_one()
    spec_count = bind.execute(sa.text("SELECT count(*) FROM pack_specifications")).scalar_one()
    unit_count = bind.execute(sa.text("SELECT count(*) FROM packaging_units")).scalar_one()
    if version_count or spec_count or unit_count:
        raise RuntimeError(
            "Cannot downgrade past POSTHARVEST-OPS-001B: persisted PackagingUnit, PackSpecification, or "
            "PackSpecificationVersion rows exist. Downgrading would silently discard commercial packaging "
            "configuration. Remove or migrate the offending data out-of-band first, or do not downgrade."
        )

    op.execute(
        "DROP TRIGGER IF EXISTS pack_specification_versions_enforce_insert_integrity "
        "ON pack_specification_versions"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_pack_specification_version_insert_integrity()")

    op.execute("DROP TRIGGER IF EXISTS pack_specification_versions_no_delete ON pack_specification_versions")
    op.execute("DROP FUNCTION IF EXISTS reject_pack_specification_version_delete()")

    op.execute(
        "DROP TRIGGER IF EXISTS pack_specification_versions_enforce_transition ON pack_specification_versions"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_pack_specification_version_transition()")

    op.drop_table("pack_specification_versions")

    op.execute("DROP TRIGGER IF EXISTS pack_specifications_no_delete ON pack_specifications")
    op.execute("DROP TRIGGER IF EXISTS pack_specifications_no_update ON pack_specifications")
    op.execute("DROP FUNCTION IF EXISTS reject_pack_specification_mutation()")

    op.drop_table("pack_specifications")

    op.execute("DROP TRIGGER IF EXISTS packaging_units_no_delete ON packaging_units")
    op.execute("DROP FUNCTION IF EXISTS reject_packaging_unit_delete()")

    op.execute("DROP TRIGGER IF EXISTS packaging_units_enforce_transition ON packaging_units")
    op.execute("DROP FUNCTION IF EXISTS enforce_packaging_unit_transition()")

    op.drop_table("packaging_units")
