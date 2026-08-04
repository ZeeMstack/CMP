import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class BatchAssignmentTransfer(Base):
    """Immutable, insert-only record of one carrier's complete active
    assignment moving from a source batch to an output batch during a split
    or merge (CMP-012). One source assignment and one destination assignment
    each appear in exactly one transfer, ever — full carrier-content
    transfer only, never a partial split of one carrier's contents."""

    __tablename__ = "batch_assignment_transfers"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    derivation_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batch_derivation_events.id"), nullable=False
    )
    source_batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crop_batches.id"), nullable=False)
    output_batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crop_batches.id"), nullable=False)
    carrier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("carriers.id"), nullable=False)
    released_source_assignment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batch_carrier_assignments.id"), nullable=False
    )
    opened_destination_assignment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batch_carrier_assignments.id"), nullable=False
    )
    transferred_plant_count: Mapped[int] = mapped_column(Integer, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "transferred_plant_count > 0", name="ck_batch_assignment_transfers_count_positive"
        ),
        UniqueConstraint(
            "released_source_assignment_id", name="ux_batch_assignment_transfers_source_assignment"
        ),
        UniqueConstraint(
            "opened_destination_assignment_id", name="ux_batch_assignment_transfers_destination_assignment"
        ),
        UniqueConstraint(
            "derivation_event_id", "carrier_id", name="ux_batch_assignment_transfers_event_carrier"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "derivation_event_id"],
            [
                "batch_derivation_events.tenant_id",
                "batch_derivation_events.farm_id",
                "batch_derivation_events.id",
            ],
            name="fk_batch_assignment_transfers_tenant_farm_event",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "source_batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_batch_assignment_transfers_tenant_farm_source_batch",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "output_batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_batch_assignment_transfers_tenant_farm_output_batch",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "carrier_id"],
            ["carriers.tenant_id", "carriers.farm_id", "carriers.id"],
            name="fk_batch_assignment_transfers_tenant_farm_carrier",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "released_source_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id",
                "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_batch_assignment_transfers_source_assignment",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "opened_destination_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id",
                "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_batch_assignment_transfers_destination_assignment",
        ),
    )
