import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class HarvestedProduceLot(Base):
    """Immutable, insert-only harvested-produce-lot identity. Exactly one
    per harvest event — `UNIQUE(harvest_event_id)` is the typed one-to-one
    relationship; a lot cannot exist without its event, and an event cannot
    commit without exactly one lot (proven by deferred reconciliation).
    `workflow_id`/`workflow_version_id`/`crop_id`/`variety_id` are snapshot
    copies of the batch's own immutable values — zero drift risk, kept for
    durable external traceability (CMP-013)."""

    __tablename__ = "harvested_produce_lots"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    harvest_event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("harvest_events.id"), nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crop_batches.id"), nullable=False)
    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflows.id"), nullable=False)
    workflow_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_versions.id"), nullable=False
    )
    crop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crops.id"), nullable=False)
    variety_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("varieties.id"), nullable=True)
    total_harvested_weight_kg: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    total_whole_unit_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "total_harvested_weight_kg > 0 AND total_harvested_weight_kg = trunc(total_harvested_weight_kg, 3) "
            "AND total_harvested_weight_kg < 100000000000",
            name="ck_harvested_produce_lots_weight_envelope",
        ),
        CheckConstraint(
            "total_whole_unit_count IS NULL OR total_whole_unit_count > 0",
            name="ck_harvested_produce_lots_count_positive",
        ),
        Index("ux_harvested_produce_lots_tenant_code_lower", "tenant_id", func.lower(code), unique=True),
        UniqueConstraint("harvest_event_id", name="ux_harvested_produce_lots_event"),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "harvest_event_id"],
            ["harvest_events.tenant_id", "harvest_events.farm_id", "harvest_events.id"],
            name="fk_harvested_produce_lots_tenant_farm_event",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_harvested_produce_lots_tenant_farm_batch",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "workflow_id", "workflow_version_id"],
            ["workflow_versions.tenant_id", "workflow_versions.workflow_id", "workflow_versions.id"],
            name="fk_harvested_produce_lots_tenant_workflow_version",
        ),
    )
