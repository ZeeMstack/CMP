import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

OPERATION_KINDS = ("RECORD", "CORRECT")


class ProductionDispositionCommand(Base):
    """LEAFY-OPS-001: the logical operator command header for a Production
    Biological Disposition -- a RECORD command always produces exactly one
    `ProductionDispositionEvent` (REDUCTION); a CORRECT command always
    produces exactly one REVERSAL and, optionally, one replacement
    REDUCTION. Mirrors `SeedlingDispositionCommand`'s header-plus-variable-
    child-events shape exactly, anchored to `batch_carrier_assignment_id`
    (the actual generation the command was issued against) rather than a
    SeedlingEntry-style separate row, since Production population has no
    such entry concept -- see `BatchCarrierAssignment.population_root_
    batch_carrier_assignment_id` for the stable lineage identity this
    command's events resolve balance against."""

    __tablename__ = "production_disposition_commands"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crop_batches.id"), nullable=False)
    batch_carrier_assignment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batch_carrier_assignments.id"), nullable=False
    )
    operation_kind: Mapped[str] = mapped_column(String, nullable=False)
    target_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("production_disposition_events.id"), nullable=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "operation_kind IN ('RECORD', 'CORRECT')", name="ck_production_disposition_commands_operation_kind"
        ),
        CheckConstraint(
            "(operation_kind = 'RECORD' AND target_event_id IS NULL) OR "
            "(operation_kind = 'CORRECT' AND target_event_id IS NOT NULL)",
            name="ck_production_disposition_commands_target_matches_kind",
        ),
        UniqueConstraint(
            "tenant_id", "client_command_id", name="ux_production_disposition_commands_tenant_client_command_id"
        ),
        UniqueConstraint(
            "tenant_id", "farm_id", "id", name="uq_production_disposition_commands_tenant_farm_id"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_production_disposition_commands_tenant_farm_batch",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_carrier_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id", "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_production_disposition_commands_tenant_farm_assignment",
        ),
    )
