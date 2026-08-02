import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.common import TimestampMixin

# CMP is crop-agnostic but not role-agnostic: these are platform-operational
# roles (who does what on the farm), not a permission engine — no role-based
# authorization is implemented yet (CMP-003 scope).
APPROVED_ROLE_CODES = frozenset(
    {
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
    }
)

_ROLE_CODES_SQL_LIST = ", ".join(f"'{code}'" for code in sorted(APPROVED_ROLE_CODES))


class TenantMembership(TimestampMixin, Base):
    __tablename__ = "tenant_memberships"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    role_code: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('active', 'removed')", name="ck_tenant_memberships_status"),
        CheckConstraint(
            f"role_code IS NULL OR role_code IN ({_ROLE_CODES_SQL_LIST})",
            name="ck_tenant_memberships_role_code_allowed",
        ),
        CheckConstraint(
            "status <> 'active' OR role_code IS NOT NULL",
            name="ck_tenant_memberships_active_requires_role",
        ),
        Index(
            "ux_tenant_memberships_active_tenant_user",
            "tenant_id",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )
