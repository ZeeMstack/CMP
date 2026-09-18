import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

CAPACITY_ALLOCATION_STATUSES = ("active", "cancelled")


class ProductionCapacityAllocation(Base):
    """PILOT-PLAN-001A: a PLANNING reservation of future occupant-slot
    capacity at one Location, over a date window -- never Occupancy, never
    a Carrier reservation, never a Batch. See `docs/domain/
    HARVEST_FORECAST_CAPACITY_MODEL.md` for the chosen capacity grain
    (`locations.capacity`, DOMAIN-FARM-002's occupant-count semantics) and
    the `[start, end)` overlap convention `planned_start_date`/
    `planned_end_date` follow.

    Current-state row (mirrors `ProductionRequirement`): create/update
    while `status = 'active'`, cancel to stop it consuming planned
    capacity -- never hard-deleted, never silently deleted, and no
    row here ever creates or mutates an `Occupancy`, moves a Batch, or
    changes Location truth."""

    __tablename__ = "production_capacity_allocations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)

    location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("locations.id"), nullable=False)
    production_system_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("production_systems.id"), nullable=True
    )

    planned_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    planned_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    planned_capacity_amount: Mapped[int] = mapped_column(Integer, nullable=False)

    source_seeding_program_line_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("seeding_program_lines.id"), nullable=True
    )
    source_crop_batch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("crop_batches.id"), nullable=True)

    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    notes: Mapped[str | None] = mapped_column(String, nullable=True)

    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    cancelled_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    update_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    update_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)
    cancel_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    cancel_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('" + "', '".join(CAPACITY_ALLOCATION_STATUSES) + "')",
            name="ck_production_capacity_allocations_status",
        ),
        CheckConstraint("planned_capacity_amount > 0", name="ck_production_capacity_allocations_amount_positive"),
        CheckConstraint("planned_end_date > planned_start_date", name="ck_production_capacity_allocations_window_shape"),
        CheckConstraint(
            "(status = 'active' AND cancelled_at IS NULL AND cancelled_by_user_id IS NULL) OR "
            "(status = 'cancelled' AND cancelled_at IS NOT NULL AND cancelled_by_user_id IS NOT NULL)",
            name="ck_production_capacity_allocations_status_shape",
        ),
        Index("ux_production_capacity_allocations_tenant_code_lower", "tenant_id", func.lower(code), unique=True),
        Index(
            "ux_production_capacity_allocations_tenant_client_command_id",
            "tenant_id", "client_command_id", unique=True,
        ),
        Index(
            "ux_production_capacity_allocations_tenant_update_command", "tenant_id", "update_client_command_id",
            unique=True, postgresql_where=text("update_client_command_id IS NOT NULL"),
        ),
        Index(
            "ux_production_capacity_allocations_tenant_cancel_command", "tenant_id", "cancel_client_command_id",
            unique=True, postgresql_where=text("cancel_client_command_id IS NOT NULL"),
        ),
        # Overlap-sum query filter: active allocations for one Location,
        # ordered by window -- see capacity_plan_service's overlap check.
        Index(
            "ix_production_capacity_allocations_location_window",
            "tenant_id", "farm_id", "location_id", "planned_start_date", "planned_end_date",
            postgresql_where=text("status = 'active'"),
        ),
        Index("ix_production_capacity_allocations_farm_status", "tenant_id", "farm_id", "status"),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id"], ["farms.tenant_id", "farms.id"],
            name="fk_production_capacity_allocations_tenant_farm",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "location_id"],
            ["locations.tenant_id", "locations.farm_id", "locations.id"],
            name="fk_production_capacity_allocations_tenant_farm_location",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "production_system_id"],
            ["production_systems.tenant_id", "production_systems.id"],
            name="fk_production_capacity_allocations_tenant_production_system",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "source_seeding_program_line_id"],
            ["seeding_program_lines.tenant_id", "seeding_program_lines.farm_id", "seeding_program_lines.id"],
            name="fk_production_capacity_allocations_tenant_farm_seeding_line",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "source_crop_batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_production_capacity_allocations_tenant_farm_batch",
        ),
    )
