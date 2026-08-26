import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class PackagingUnit(Base):
    """POSTHARVEST-OPS-001B: a simple, tenant-scoped, stable commercial
    packaging-unit identity (e.g. what a tenant would eventually name
    "carton", "clamshell" ... never seeded or hard-coded here). No
    versioning -- unlike GradeDefinition/PackSpecification, a packaging
    unit carries no separate criteria payload to version; its own
    `code`/`name` ARE its stable identity, frozen after creation exactly
    like GradeDefinition's own crop/variety scope. Lifecycle is the
    simplest possible two-state machine, `active -> retired`, enforced
    the same way GradeDefinitionVersion's own richer lifecycle is:
    unconditional hard-delete rejection, and a DB trigger that only
    permits the one legal transition. Retirement never rewrites or
    invalidates a PackSpecificationVersion that already references this
    unit -- only NEW references are blocked (see
    `pack_specification_versions_enforce_insert_integrity`)."""

    __tablename__ = "packaging_units"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    retirement_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    retirement_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('active', 'retired')", name="ck_packaging_units_status"),
        CheckConstraint(
            "(status = 'active' AND retirement_client_command_id IS NULL "
            " AND retirement_request_fingerprint IS NULL) "
            "OR (status = 'retired' AND retirement_client_command_id IS NOT NULL "
            " AND retirement_request_fingerprint IS NOT NULL)",
            name="ck_packaging_units_status_shape",
        ),
        Index("ux_packaging_units_tenant_code_lower", "tenant_id", func.lower(code), unique=True),
        Index(
            "ux_packaging_units_tenant_client_command_id", "tenant_id", "client_command_id", unique=True
        ),
        Index(
            "ux_packaging_units_tenant_retirement_command", "tenant_id", "retirement_client_command_id",
            unique=True, postgresql_where=text("retirement_client_command_id IS NOT NULL"),
        ),
        UniqueConstraint("tenant_id", "id", name="uq_packaging_units_tenant_id"),
    )
