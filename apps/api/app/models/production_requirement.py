import uuid
from datetime import date

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.common import TimestampMixin


class ProductionRequirement(TimestampMixin, Base):
    """PLANNING-OPS-001: a planner's statement of desired FARM OUTPUT for a
    crop (optionally variety) by a required-by date -- a plan, never
    biological truth. Mutable (safe audited updates while `status = 'open'`,
    see `planning_service`) rather than the immutable-event shape used
    elsewhere in CMP: a Production Requirement is planning intent with no
    physical-world side effect of its own, so there is nothing here that
    reversal-plus-new-transaction semantics would meaningfully protect.
    `code` is server-generated and immutable once assigned."""

    __tablename__ = "production_requirements"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    crop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crops.id"), nullable=False)
    variety_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("varieties.id"), nullable=True)
    required_by_date: Mapped[date] = mapped_column(Date, nullable=False)
    required_quantity: Mapped[Numeric] = mapped_column(Numeric(18, 3), nullable=False)
    quantity_uom_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("unit_of_measures.id"), nullable=False)
    reference: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="open")
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)

    # PLANNING-OPS-001: per-command idempotency column pairs for the three
    # mutation commands (update/close/cancel), mirroring UX-IA-001's
    # Location update/deactivate/reactivate convention exactly.
    update_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    update_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)
    close_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    close_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)
    cancel_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    cancel_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('open', 'closed', 'cancelled')", name="ck_production_requirements_status"),
        CheckConstraint("required_quantity > 0", name="ck_production_requirements_quantity_positive"),
        Index("ux_production_requirements_tenant_code_lower", "tenant_id", func.lower(code), unique=True),
        Index(
            "ux_production_requirements_tenant_client_command_id",
            "tenant_id",
            "client_command_id",
            unique=True,
        ),
        Index(
            "ux_production_requirements_tenant_update_command", "tenant_id", "update_client_command_id",
            unique=True, postgresql_where=text("update_client_command_id IS NOT NULL"),
        ),
        Index(
            "ux_production_requirements_tenant_close_command", "tenant_id", "close_client_command_id",
            unique=True, postgresql_where=text("close_client_command_id IS NOT NULL"),
        ),
        Index(
            "ux_production_requirements_tenant_cancel_command", "tenant_id", "cancel_client_command_id",
            unique=True, postgresql_where=text("cancel_client_command_id IS NOT NULL"),
        ),
        UniqueConstraint("tenant_id", "id", name="uq_production_requirements_tenant_id_id"),
        UniqueConstraint("tenant_id", "farm_id", "id", name="uq_production_requirements_tenant_farm_id"),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id"], ["farms.tenant_id", "farms.id"], name="fk_production_requirements_tenant_farm"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "crop_id"], ["crops.tenant_id", "crops.id"], name="fk_production_requirements_tenant_crop"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "crop_id", "variety_id"],
            ["varieties.tenant_id", "varieties.crop_id", "varieties.id"],
            name="fk_production_requirements_tenant_crop_variety",
        ),
    )
