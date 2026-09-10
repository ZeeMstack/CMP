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


class SeedingProgramLine(TimestampMixin, Base):
    """PLANNING-OPS-001: one planned sowing intended to cover part of a
    Production Requirement's demand -- a plan line, never biological truth.
    A Crop Batch/Sowing Event is never created by this row; it is only
    optionally REFERENCED by an actual `SowingEvent` once real sowing
    happens (`sowing_events.seeding_program_line_id`). Mutable while
    `status = 'planned'` and not yet referenced by any actual Sowing, mirroring
    `ProductionRequirement`'s own planning-intent shape."""

    __tablename__ = "seeding_program_lines"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    production_requirement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("production_requirements.id"), nullable=False
    )
    planned_sow_date: Mapped[date] = mapped_column(Date, nullable=False)
    crop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crops.id"), nullable=False)
    variety_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("varieties.id"), nullable=True)
    planned_quantity: Mapped[Numeric] = mapped_column(Numeric(18, 3), nullable=False)
    planned_quantity_uom_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("unit_of_measures.id"), nullable=False)
    expected_coverage_quantity: Mapped[Numeric] = mapped_column(Numeric(18, 3), nullable=False)
    expected_coverage_uom_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("unit_of_measures.id"), nullable=False)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="planned")
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)

    # PLANNING-OPS-001: per-command idempotency column pairs for the two
    # mutation commands (update/cancel), mirroring UX-IA-001's Location
    # update/deactivate/reactivate convention exactly.
    update_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    update_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)
    cancel_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    cancel_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('planned', 'cancelled')", name="ck_seeding_program_lines_status"),
        CheckConstraint("planned_quantity > 0", name="ck_seeding_program_lines_planned_quantity_positive"),
        CheckConstraint(
            "expected_coverage_quantity > 0", name="ck_seeding_program_lines_coverage_quantity_positive"
        ),
        Index(
            "ux_seeding_program_lines_tenant_client_command_id",
            "tenant_id",
            "client_command_id",
            unique=True,
        ),
        Index(
            "ux_seeding_program_lines_tenant_update_command", "tenant_id", "update_client_command_id",
            unique=True, postgresql_where=text("update_client_command_id IS NOT NULL"),
        ),
        Index(
            "ux_seeding_program_lines_tenant_cancel_command", "tenant_id", "cancel_client_command_id",
            unique=True, postgresql_where=text("cancel_client_command_id IS NOT NULL"),
        ),
        Index("ix_seeding_program_lines_tenant_farm_sow_date", "tenant_id", "farm_id", "planned_sow_date"),
        UniqueConstraint("tenant_id", "id", name="uq_seeding_program_lines_tenant_id_id"),
        UniqueConstraint("tenant_id", "farm_id", "id", name="uq_seeding_program_lines_tenant_farm_id"),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id"], ["farms.tenant_id", "farms.id"], name="fk_seeding_program_lines_tenant_farm"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "production_requirement_id"],
            [
                "production_requirements.tenant_id",
                "production_requirements.farm_id",
                "production_requirements.id",
            ],
            name="fk_seeding_program_lines_tenant_farm_requirement",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "crop_id"], ["crops.tenant_id", "crops.id"], name="fk_seeding_program_lines_tenant_crop"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "crop_id", "variety_id"],
            ["varieties.tenant_id", "varieties.crop_id", "varieties.id"],
            name="fk_seeding_program_lines_tenant_crop_variety",
        ),
    )
