import uuid
from datetime import datetime

from sqlalchemy import (
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


class TransplantSourceLine(Base):
    """Immutable, insert-only record of one source carrier assignment
    released within one transplant event. An assignment may appear as a
    source in at most one transplant event ever — enforced by a global
    (not per-event) unique constraint (CMP-011)."""

    __tablename__ = "transplant_source_lines"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    transplant_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transplant_events.id"), nullable=False
    )
    source_batch_carrier_assignment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batch_carrier_assignments.id"), nullable=False
    )
    source_carrier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("carriers.id"), nullable=False)
    source_plant_count: Mapped[int] = mapped_column(Integer, nullable=False)
    discarded_plant_count: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("source_plant_count > 0", name="ck_transplant_source_lines_count_positive"),
        CheckConstraint(
            "discarded_plant_count >= 0", name="ck_transplant_source_lines_discarded_non_negative"
        ),
        CheckConstraint(
            "discarded_plant_count <= source_plant_count",
            name="ck_transplant_source_lines_discarded_within_count",
        ),
        UniqueConstraint(
            "source_batch_carrier_assignment_id", name="ux_transplant_source_lines_assignment"
        ),
        UniqueConstraint(
            "tenant_id", "farm_id", "transplant_event_id", "id",
            name="uq_transplant_source_lines_tenant_farm_event_id",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "transplant_event_id"],
            ["transplant_events.tenant_id", "transplant_events.farm_id", "transplant_events.id"],
            name="fk_transplant_source_lines_tenant_farm_event",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "source_batch_carrier_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id",
                "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_transplant_source_lines_tenant_farm_assignment",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "source_carrier_id"],
            ["carriers.tenant_id", "carriers.farm_id", "carriers.id"],
            name="fk_transplant_source_lines_tenant_farm_carrier",
        ),
    )
