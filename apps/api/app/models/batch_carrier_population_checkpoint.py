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


class BatchCarrierPopulationCheckpoint(Base):
    """NURSERY-OPS-005A: immutable, insert-only boundary marker -- the
    `BatchCarrierAssignment`-anchored sibling of `SeedlingSourceCheckpoint`,
    for a transplant-created biological placement (e.g. a Nursery
    Cultivation Plate) rather than a SeedlingEntry-anchored Seed Tray.
    `SeedlingSourceCheckpoint`/`SeedlingEntry` remain unchanged and
    authoritative for the Seed Tray lifecycle -- this is a genuinely
    separate authority, not a generalization of that one (see
    `docs/domain/TRANSPLANTATION_MODEL.md`).

    One row per `TransplantSourceLine` that consumes this assignment's
    population. A normal (never-restored) assignment needs no row at all
    until first consumed -- its opening population is derived structurally
    from its own `TransplantDestinationLine.assigned_plant_count` (mirrors
    `SeedlingEntry.starting_living_seedling_count`'s identical role). A
    restored assignment (opened by a Transplant REVERSAL) gets its first
    checkpoint written immediately by that REVERSAL, anchored to a
    REVERSAL-synthesized `TransplantSourceLine`, exactly mirroring how
    `SeedlingSourceCheckpoint` restoration already works -- never a second,
    differently-shaped "opening" row or a nullable cause column."""

    __tablename__ = "batch_carrier_population_checkpoints"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crop_batches.id"), nullable=False)
    batch_carrier_assignment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batch_carrier_assignments.id"), nullable=False
    )
    transplant_source_line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transplant_source_lines.id"), nullable=False
    )
    previous_checkpoint_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("batch_carrier_population_checkpoints.id"), nullable=True
    )
    remainder_after: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "remainder_after >= 0", name="ck_batch_carrier_population_checkpoints_remainder_non_negative"
        ),
        # Exactly one checkpoint per consuming TransplantSourceLine.
        UniqueConstraint(
            "transplant_source_line_id", name="ux_batch_carrier_population_checkpoints_source_line"
        ),
        # Structural chain-tip / branch-prevention -- at most one checkpoint
        # ever claims a given predecessor, mirroring
        # ux_seedling_source_checkpoints_previous_once exactly.
        Index(
            "ux_batch_carrier_population_checkpoints_previous_once",
            "previous_checkpoint_id",
            unique=True,
        ),
        Index(
            "ix_batch_carrier_population_checkpoints_assignment_effective",
            "batch_carrier_assignment_id",
            "effective_time",
        ),
        UniqueConstraint(
            "tenant_id", "farm_id", "id", name="uq_batch_carrier_population_checkpoints_tenant_farm_id"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_batch_carrier_population_checkpoints_tenant_farm_batch",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_carrier_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id",
                "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_batch_carrier_population_checkpoints_tenant_farm_assignment",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "transplant_source_line_id"],
            [
                "transplant_source_lines.tenant_id",
                "transplant_source_lines.farm_id",
                "transplant_source_lines.id",
            ],
            name="fk_batch_carrier_population_checkpoints_tenant_farm_source_line",
        ),
    )
