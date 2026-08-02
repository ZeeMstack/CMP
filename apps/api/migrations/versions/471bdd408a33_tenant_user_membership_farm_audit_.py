"""tenant user membership farm audit foundation

Revision ID: 471bdd408a33
Revises: aa985cd43fbb
Create Date: 2026-08-02 11:40:24.507631

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '471bdd408a33'
down_revision: Union[str, None] = 'aa985cd43fbb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Platform-operational roles, not a permission engine (CMP-003 scope).
_APPROVED_ROLE_CODES = (
    "tenant_admin",
    "farm_manager",
    "head_grower",
    "production_supervisor",
    "operator",
    "storekeeper",
    "qc_officer",
    "auditor",
    "packing_supervisor",
    "cold_store_supervisor",
    "dispatch_officer",
    "read_only",
)
_ROLE_CODES_SQL_LIST = ", ".join(f"'{code}'" for code in _APPROVED_ROLE_CODES)


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_tenants_status"),
    )
    op.create_index("ux_tenants_code_lower", "tenants", [sa.text("lower(code)")], unique=True)

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("oidc_issuer", sa.String(), nullable=False),
        sa.Column("oidc_subject", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_users_status"),
        sa.UniqueConstraint("oidc_issuer", "oidc_subject", name="ux_users_issuer_subject"),
    )

    op.create_table(
        "tenant_memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("role_code", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('active', 'removed')", name="ck_tenant_memberships_status"),
        sa.CheckConstraint(
            f"role_code IS NULL OR role_code IN ({_ROLE_CODES_SQL_LIST})",
            name="ck_tenant_memberships_role_code_allowed",
        ),
        sa.CheckConstraint(
            "status <> 'active' OR role_code IS NOT NULL",
            name="ck_tenant_memberships_active_requires_role",
        ),
    )
    op.create_index(
        "ux_tenant_memberships_active_tenant_user",
        "tenant_memberships",
        ["tenant_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "farms",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("city_region", sa.String(), nullable=True),
        sa.Column("timezone", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_farms_status"),
        sa.CheckConstraint("country_code ~ '^[A-Z]{2}$'", name="ck_farms_country_code_format"),
    )
    op.create_index(
        "ux_farms_tenant_code_lower", "farms", ["tenant_id", sa.text("lower(code)")], unique=True
    )

    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("request_id", sa.String(), nullable=True),
        sa.Column("event_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    )
    op.create_index("ix_audit_events_tenant_id", "audit_events", ["tenant_id"])
    op.create_index("ix_audit_events_entity", "audit_events", ["entity_type", "entity_id"])

    # Append-only enforcement: reject UPDATE/DELETE at the database level,
    # independent of application code paths.
    op.execute(
        """
        CREATE FUNCTION reject_audit_event_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only: % not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_no_update
        BEFORE UPDATE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION reject_audit_event_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_no_delete
        BEFORE DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION reject_audit_event_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_events_no_delete ON audit_events")
    op.execute("DROP TRIGGER IF EXISTS audit_events_no_update ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS reject_audit_event_mutation()")

    op.drop_table("audit_events")
    op.drop_index("ux_farms_tenant_code_lower", table_name="farms")
    op.drop_table("farms")
    op.drop_index("ux_tenant_memberships_active_tenant_user", table_name="tenant_memberships")
    op.drop_table("tenant_memberships")
    op.drop_table("users")
    op.drop_index("ux_tenants_code_lower", table_name="tenants")
    op.drop_table("tenants")
