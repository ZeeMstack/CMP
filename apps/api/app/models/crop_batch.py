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
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        CheckConstraint("state IN ('active', 'closed')", name="ck_crop_batches_state"),
        CheckConstraint(
            "(state = 'active' AND closed_effective_time IS NULL) OR "
            "(state = 'closed' AND closed_effective_time IS NOT NULL)",
            name="ck_crop_batches_closed_time_matches_state",
        ),
        CheckConstraint(
            "closed_effective_time IS NULL OR closed_effective_time >= created_effective_time",
            name="ck_crop_batches_closed_after_created",
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
    )
