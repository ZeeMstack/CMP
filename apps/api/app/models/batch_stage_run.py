import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class BatchStageRun(Base):
    """Immutable-history record of one batch occupying one workflow stage.
    Current stage is the single row per batch with `exited_effective_time`
    NULL — there is no separate mutable pointer (CMP-008)."""

    __tablename__ = "batch_stage_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crop_batches.id"), nullable=False)
    workflow_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_versions.id"), nullable=False
    )
    workflow_stage_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_stages.id"), nullable=False)
    entered_effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exited_effective_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    opened_by_transition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batch_stage_transitions.id"), nullable=False
    )
    closed_by_transition_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("batch_stage_transitions.id"), nullable=True
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "(exited_effective_time IS NULL) = (closed_by_transition_id IS NULL)",
            name="ck_batch_stage_runs_closure_fields_together",
        ),
        CheckConstraint(
            "exited_effective_time IS NULL OR exited_effective_time >= entered_effective_time",
            name="ck_batch_stage_runs_exited_after_entered",
        ),
        Index(
            "ux_batch_stage_runs_active_batch",
            "batch_id",
            unique=True,
            postgresql_where=text("exited_effective_time IS NULL"),
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_batch_stage_runs_tenant_farm_batch",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "workflow_version_id", "workflow_stage_id"],
            ["workflow_stages.tenant_id", "workflow_stages.workflow_version_id", "workflow_stages.id"],
            name="fk_batch_stage_runs_stage",
        ),
    )
