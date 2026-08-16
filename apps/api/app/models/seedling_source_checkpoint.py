import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class SeedlingSourceCheckpoint(Base):
    """NURSERY-OPS-004A: immutable, insert-only boundary marker -- one row
    per `TransplantSourceLine` that consumes a modern (SeedlingEntry-
    anchored) Seed Tray. Each checkpoint closes the currently-open
    biological balance window and opens a new one: `remainder_after`
    becomes the new anchor value, `effective_time` the new anchor time,
    for every `SeedlingDispositionEvent` recorded from this point forward
    against the same `seedling_entry_id` (see
    `seedling_disposition_service._latest_checkpoint_anchor`). Deliberately
    minimal -- actor/note remain owned by `TransplantEvent`; successful-
    transfer/loss facts remain owned by `TransplantSourceLine`/
    `TransplantAllocation`; this row exists only to anchor the next
    balance window and chain to the previous one."""

    __tablename__ = "seedling_source_checkpoints"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crop_batches.id"), nullable=False)
    seedling_entry_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("seedling_entries.id"), nullable=False)
    source_batch_carrier_assignment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batch_carrier_assignments.id"), nullable=False
    )
    transplant_source_line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transplant_source_lines.id"), nullable=False
    )
    previous_checkpoint_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("seedling_source_checkpoints.id"), nullable=True
    )
    remainder_after: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("remainder_after >= 0", name="ck_seedling_source_checkpoints_remainder_non_negative"),
        # Exactly one checkpoint per modern TransplantSourceLine (section 11).
        UniqueConstraint(
            "transplant_source_line_id", name="ux_seedling_source_checkpoints_source_line"
        ),
        # Section 22: the chain must be traceable id-by-id; a partial unique
        # index proves at most one checkpoint ever claims a given
        # predecessor, structurally preventing branching.
        Index(
            "ux_seedling_source_checkpoints_previous_once",
            "previous_checkpoint_id",
            unique=True,
        ),
        Index(
            "ix_seedling_source_checkpoints_entry_effective", "seedling_entry_id", "effective_time"
        ),
        UniqueConstraint(
            "tenant_id", "farm_id", "id", name="uq_seedling_source_checkpoints_tenant_farm_id"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_seedling_source_checkpoints_tenant_farm_batch",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "seedling_entry_id"],
            ["seedling_entries.tenant_id", "seedling_entries.farm_id", "seedling_entries.id"],
            name="fk_seedling_source_checkpoints_tenant_farm_entry",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "transplant_source_line_id"],
            [
                "transplant_source_lines.tenant_id",
                "transplant_source_lines.farm_id",
                "transplant_source_lines.id",
            ],
            name="fk_seedling_source_checkpoints_tenant_farm_source_line",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "source_batch_carrier_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id",
                "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_seedling_source_checkpoints_tenant_farm_assignment",
        ),
    )
