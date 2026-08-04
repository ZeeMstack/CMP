import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class BatchDerivationSource(Base):
    """Immutable, insert-only record of one source batch consumed by a
    split or merge (CMP-012). `source_batch_id` is globally unique — a
    crop batch may be superseded by at most one successful derivation event,
    ever."""

    __tablename__ = "batch_derivation_sources"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    derivation_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batch_derivation_events.id"), nullable=False
    )
    source_batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crop_batches.id"), nullable=False)
    source_batch_stage_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batch_stage_runs.id"), nullable=False
    )
    recorded_plant_quantity_total: Mapped[int] = mapped_column(Integer, nullable=False)
    recorded_carrier_assignment_count: Mapped[int] = mapped_column(Integer, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "recorded_plant_quantity_total >= 0", name="ck_batch_derivation_sources_quantity_non_negative"
        ),
        CheckConstraint(
            "recorded_carrier_assignment_count >= 0",
            name="ck_batch_derivation_sources_assignment_count_non_negative",
        ),
        UniqueConstraint("source_batch_id", name="ux_batch_derivation_sources_source_batch"),
        UniqueConstraint(
            "derivation_event_id", "source_batch_id", name="ux_batch_derivation_sources_event_source_batch"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "derivation_event_id"],
            [
                "batch_derivation_events.tenant_id",
                "batch_derivation_events.farm_id",
                "batch_derivation_events.id",
            ],
            name="fk_batch_derivation_sources_tenant_farm_event",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "source_batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_batch_derivation_sources_tenant_farm_batch",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "source_batch_id", "source_batch_stage_run_id"],
            [
                "batch_stage_runs.tenant_id",
                "batch_stage_runs.farm_id",
                "batch_stage_runs.batch_id",
                "batch_stage_runs.id",
            ],
            name="fk_batch_derivation_sources_stage_run",
        ),
    )
