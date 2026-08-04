import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class TransplantAllocation(Base):
    """Immutable, insert-only many-to-many lineage row: exactly how many
    plants moved from one source line into one destination line within one
    transplant event (CMP-011)."""

    __tablename__ = "transplant_allocations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    transplant_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transplant_events.id"), nullable=False
    )
    source_line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transplant_source_lines.id"), nullable=False
    )
    destination_line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transplant_destination_lines.id"), nullable=False
    )
    allocated_plant_count: Mapped[int] = mapped_column(Integer, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("allocated_plant_count > 0", name="ck_transplant_allocations_count_positive"),
        UniqueConstraint("source_line_id", "destination_line_id", name="ux_transplant_allocations_pair"),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "transplant_event_id"],
            ["transplant_events.tenant_id", "transplant_events.farm_id", "transplant_events.id"],
            name="fk_transplant_allocations_tenant_farm_event",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "transplant_event_id", "source_line_id"],
            [
                "transplant_source_lines.tenant_id",
                "transplant_source_lines.farm_id",
                "transplant_source_lines.transplant_event_id",
                "transplant_source_lines.id",
            ],
            name="fk_transplant_allocations_source_line",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "transplant_event_id", "destination_line_id"],
            [
                "transplant_destination_lines.tenant_id",
                "transplant_destination_lines.farm_id",
                "transplant_destination_lines.transplant_event_id",
                "transplant_destination_lines.id",
            ],
            name="fk_transplant_allocations_destination_line",
        ),
    )
