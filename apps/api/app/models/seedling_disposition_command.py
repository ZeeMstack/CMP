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


class SeedlingDispositionCommand(Base):
    """NURSERY-OPS-003B: the logical operator command header -- a RECORD
    command always produces exactly one `SeedlingDispositionEvent`
    (REDUCTION); a CORRECT command always produces exactly one REVERSAL and,
    optionally, one replacement REDUCTION. This header exists specifically
    because one command may create a variable number of immutable domain
    event rows (unlike `SeedlingEntry`/`Movement`, which are each exactly
    one row per command) -- the same header-plus-variable-child-lines shape
    already established by `SowingEvent`+`SowingEventLine`,
    `TransplantEvent`+`TransplantSourceLine`/`TransplantDestinationLine`,
    and the modern Germination outcome's own `ObservationEvent`+
    `GerminationOutcomeSnapshot` pair. Deliberately NOT built on
    `ObservationEvent` -- `SeedlingEntry` itself already established the
    precedent of a dedicated, narrow typed header for this domain."""

    __tablename__ = "seedling_disposition_commands"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crop_batches.id"), nullable=False)
    seedling_entry_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("seedling_entries.id"), nullable=False)
    operation_kind: Mapped[str] = mapped_column(String, nullable=False)
    target_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("seedling_disposition_events.id"), nullable=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "operation_kind IN ('RECORD', 'CORRECT')", name="ck_seedling_disposition_commands_operation_kind"
        ),
        # Section 16: target_event_id is required for CORRECT, forbidden for
        # RECORD -- same-row, no cross-table lookup needed.
        CheckConstraint(
            "(operation_kind = 'RECORD' AND target_event_id IS NULL) OR "
            "(operation_kind = 'CORRECT' AND target_event_id IS NOT NULL)",
            name="ck_seedling_disposition_commands_target_matches_kind",
        ),
        UniqueConstraint(
            "tenant_id", "client_command_id", name="ux_seedling_disposition_commands_tenant_client_command_id"
        ),
        UniqueConstraint(
            "tenant_id", "farm_id", "id", name="uq_seedling_disposition_commands_tenant_farm_id"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_seedling_disposition_commands_tenant_farm_batch",
        ),
    )
