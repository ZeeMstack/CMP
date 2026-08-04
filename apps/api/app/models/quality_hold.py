import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class QualityHold(Base):
    """Immutable, insert-only batch-level quality hold. Every open hold
    (one with no matching `quality_hold_releases` row) blocks stage
    progression. Multiple simultaneous open holds are permitted — no
    severity, no approval level (CMP-010)."""

    __tablename__ = "quality_holds"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crop_batches.id"), nullable=False)
    active_batch_stage_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batch_stage_runs.id"), nullable=False
    )
    source_observation_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("observation_events.id"), nullable=True
    )
    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    reason_code: Mapped[str] = mapped_column(String, nullable=False)
    reason_text: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        Index("ux_quality_holds_tenant_client_command_id", "tenant_id", "client_command_id", unique=True),
        UniqueConstraint("tenant_id", "farm_id", "id", name="uq_quality_holds_tenant_farm_id"),
        UniqueConstraint(
            "tenant_id", "farm_id", "batch_id", "id", name="uq_quality_holds_tenant_farm_batch_id"
        ),
        Index("ix_quality_holds_tenant_farm_batch", "tenant_id", "farm_id", "batch_id"),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_quality_holds_tenant_farm_batch",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id", "active_batch_stage_run_id"],
            [
                "batch_stage_runs.tenant_id",
                "batch_stage_runs.farm_id",
                "batch_stage_runs.batch_id",
                "batch_stage_runs.id",
            ],
            name="fk_quality_holds_stage_run",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id", "source_observation_event_id"],
            [
                "observation_events.tenant_id",
                "observation_events.farm_id",
                "observation_events.batch_id",
                "observation_events.id",
            ],
            name="fk_quality_holds_source_observation",
        ),
    )
