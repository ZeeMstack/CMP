import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class BatchProtocolAssignment(Base):
    """PILOT-AGRO-001 section 6: which `GrowingProtocolVersion` a Batch is
    following, with full history preserved -- mirrors `BatchStageRun`'s own
    "one open-ended current row per Batch, closed by setting its own end
    timestamp when superseded" shape (`ux_batch_stage_runs_active_batch`)
    exactly, via `ux_batch_protocol_assignments_active_batch` below. Never
    rewrites a closed row's `effective_from`/reason/assigner -- only
    `effective_to` on the previously-current row is ever touched, by the
    same `assign_batch_protocol` command that inserts the new current row,
    both in one transaction (see `growing_protocol_service.
    assign_batch_protocol`)."""

    __tablename__ = "batch_protocol_assignments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crop_batches.id"), nullable=False)
    growing_protocol_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("growing_protocol_versions.id"), nullable=False
    )
    assigned_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_batch_protocol_assignments_effective_order",
        ),
        Index(
            "ux_batch_protocol_assignments_active_batch", "batch_id", unique=True,
            postgresql_where=text("effective_to IS NULL"),
        ),
        Index(
            "ux_batch_protocol_assignments_tenant_client_command_id", "tenant_id", "client_command_id", unique=True
        ),
        UniqueConstraint("tenant_id", "id", name="uq_batch_protocol_assignments_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_batch_protocol_assignments_tenant_farm_batch",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "growing_protocol_version_id"],
            ["growing_protocol_versions.tenant_id", "growing_protocol_versions.id"],
            name="fk_batch_protocol_assignments_tenant_version",
        ),
    )
