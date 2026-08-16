import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class GerminationOutcomeSnapshot(Base):
    """NURSERY-OPS-002B: immutable, insert-only, INDIVIDUAL-SEEDLING-based
    Germination outcome for one carrier assignment within one observation
    event. Distinct from the legacy site/cell-based `GerminationCheck`
    (CMP-010) -- neither table redefines the other. `normal_seedling_count`
    and `abnormal_seedling_count` are both LIVING counts (abnormal is never
    a loss here); their sum need not equal the assignment's authoritative
    `seed_count` -- the gap is deliberately left uncategorized. Repeated
    rows for one assignment are point-in-time snapshots, never additive;
    `assessment_complete` marks whether a given snapshot establishes the
    authoritative downstream handoff quantity for that Tray."""

    __tablename__ = "germination_outcome_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    observation_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("observation_events.id"), nullable=False
    )
    batch_carrier_assignment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batch_carrier_assignments.id"), nullable=False
    )
    normal_seedling_count: Mapped[int] = mapped_column(Integer, nullable=False)
    abnormal_seedling_count: Mapped[int] = mapped_column(Integer, nullable=False)
    assessment_complete: Mapped[bool] = mapped_column(Boolean, nullable=False)
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "normal_seedling_count >= 0", name="ck_germination_outcome_snapshots_normal_non_negative"
        ),
        CheckConstraint(
            "abnormal_seedling_count >= 0", name="ck_germination_outcome_snapshots_abnormal_non_negative"
        ),
        UniqueConstraint(
            "observation_event_id", "batch_carrier_assignment_id",
            name="ux_germination_outcome_snapshots_event_assignment",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "observation_event_id"],
            ["observation_events.tenant_id", "observation_events.farm_id", "observation_events.id"],
            name="fk_germination_outcome_snapshots_tenant_farm_event",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_carrier_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id",
                "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_germination_outcome_snapshots_tenant_farm_assignment",
        ),
    )
