"""platform admin authority

Revision ID: 7473ab25731f
Revises: 2cd787662e3d
Create Date: 2026-08-29 00:00:00.000000

PILOT-SETUP-001B1: the platform-level authorization primitive PILOT-SETUP-
001B's discovery identified as the sole blocker before production Tenant
creation can exist. `platform_admins` is deliberately NOT a
TenantMembership -- no tenant_id, no role_code. A User either currently
holds active platform-admin authority (`revoked_at IS NULL`) or does not;
each grant/revoke cycle is its own permanent historical row (mirrors
`tenant_memberships`' own active-uniqueness idiom via a partial unique
index, rather than a single mutable "current state" row), so re-granting
after a revoke never rewrites or loses the prior cycle's own
granted_at/by and revoked_at/by facts.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "7473ab25731f"
down_revision: Union[str, None] = "2cd787662e3d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "platform_admins",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("granted_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= granted_at", name="ck_platform_admins_revoked_after_granted"
        ),
    )
    op.create_index(
        "ux_platform_admins_active_user",
        "platform_admins",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ux_platform_admins_active_user", table_name="platform_admins")
    op.drop_table("platform_admins")
