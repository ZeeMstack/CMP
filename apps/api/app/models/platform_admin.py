import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.common import TimestampMixin


class PlatformAdmin(TimestampMixin, Base):
    """PILOT-SETUP-001B1: platform-level authority, structurally separate
    from CMP's tenant-scoped model -- no `tenant_id`, no `role_code`, never
    a `TenantMembership`. A User either currently holds active platform-
    admin authority (`revoked_at IS NULL`) or does not; each grant/revoke
    cycle is its own permanent row (mirrors `tenant_memberships`' own
    active-uniqueness idiom via a partial unique index, rather than a
    single mutable "current state" row), so re-granting after a revoke
    never rewrites or loses the prior cycle's own facts. Holding this
    authority implies no tenant data access whatsoever -- see
    `app.core.platform_auth.require_platform_admin`."""

    __tablename__ = "platform_admins"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    granted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        # revoked_by_user_id is deliberately allowed to be NULL even when
        # revoked_at is set -- an unattributed revoke (e.g. via the CLI
        # bootstrap path with no --revoked-by-* identity supplied) is
        # legitimate, mirroring granted_by_user_id's identical allowance.
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= granted_at", name="ck_platform_admins_revoked_after_granted"
        ),
        Index(
            "ux_platform_admins_active_user",
            "user_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )
