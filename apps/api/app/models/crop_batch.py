import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
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


class CropBatch(Base):
    """Tenant- and farm-owned production batch, permanently bound to the
    workflow version that was published at creation time (CMP-008). Current
    stage is never stored here — it is derived from the one active
    `BatchStageRun` row for this batch."""

    __tablename__ = "crop_batches"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflows.id"), nullable=False)
    workflow_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_versions.id"), nullable=False
    )
    state: Mapped[str] = mapped_column(String, nullable=False, default="active")
    created_effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    closed_effective_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_effective_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_by_batch_derivation_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("batch_derivation_events.id"), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_by_batch_derivation_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("batch_derivation_events.id"), nullable=True
    )
    client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint("state IN ('active', 'closed', 'superseded')", name="ck_crop_batches_state"),
        CheckConstraint(
            "(state = 'active' AND closed_effective_time IS NULL "
            "AND superseded_effective_time IS NULL AND superseded_by_batch_derivation_event_id IS NULL) OR "
            "(state = 'closed' AND closed_effective_time IS NOT NULL "
            "AND superseded_effective_time IS NULL AND superseded_by_batch_derivation_event_id IS NULL) OR "
            "(state = 'superseded' AND closed_effective_time IS NULL "
            "AND superseded_effective_time IS NOT NULL AND superseded_by_batch_derivation_event_id IS NOT NULL)",
            name="ck_crop_batches_lifecycle_shape",
        ),
        CheckConstraint(
            "closed_effective_time IS NULL OR closed_effective_time >= created_effective_time",
            name="ck_crop_batches_closed_after_created",
        ),
        CheckConstraint(
            "superseded_effective_time IS NULL OR superseded_effective_time >= created_effective_time",
            name="ck_crop_batches_superseded_after_created",
        ),
        CheckConstraint(
            "(created_by_batch_derivation_event_id IS NULL) = (client_command_id IS NOT NULL) AND "
            "(created_by_batch_derivation_event_id IS NULL) = (request_fingerprint IS NOT NULL)",
            name="ck_crop_batches_command_ownership_shape",
        ),
        Index("ux_crop_batches_tenant_code_lower", "tenant_id", func.lower(code), unique=True),
        Index(
            "ux_crop_batches_tenant_client_command_id", "tenant_id", "client_command_id", unique=True
        ),
        UniqueConstraint("tenant_id", "id", name="uq_crop_batches_tenant_id_id"),
        UniqueConstraint("tenant_id", "farm_id", "id", name="uq_crop_batches_tenant_farm_id"),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id"], ["farms.tenant_id", "farms.id"], name="fk_crop_batches_tenant_farm"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "workflow_id"],
            ["workflows.tenant_id", "workflows.id"],
            name="fk_crop_batches_tenant_workflow",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "workflow_id", "workflow_version_id"],
            ["workflow_versions.tenant_id", "workflow_versions.workflow_id", "workflow_versions.id"],
            name="fk_crop_batches_tenant_workflow_version",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "created_by_batch_derivation_event_id"],
            [
                "batch_derivation_events.tenant_id",
                "batch_derivation_events.farm_id",
                "batch_derivation_events.id",
            ],
            name="fk_crop_batches_created_by_derivation_event",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "superseded_by_batch_derivation_event_id"],
            [
                "batch_derivation_events.tenant_id",
                "batch_derivation_events.farm_id",
                "batch_derivation_events.id",
            ],
            name="fk_crop_batches_superseded_by_derivation_event",
        ),
    )
