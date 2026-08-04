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

DERIVATION_KINDS = ("split", "merge")


class BatchDerivationEvent(Base):
    """Immutable, insert-only record of one crop-batch split or merge
    command (CMP-012). Owns idempotency for the whole command, including
    every output batch and derivation-entry transition it creates — outputs
    never carry their own client_command_id/request_fingerprint."""

    __tablename__ = "batch_derivation_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    derivation_kind: Mapped[str] = mapped_column(String, nullable=False)
    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflows.id"), nullable=False)
    workflow_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_versions.id"), nullable=False
    )
    inherited_workflow_stage_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_stages.id"), nullable=False
    )
    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    note: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "derivation_kind IN ('split', 'merge')", name="ck_batch_derivation_events_kind"
        ),
        Index(
            "ux_batch_derivation_events_tenant_client_command_id",
            "tenant_id",
            "client_command_id",
            unique=True,
        ),
        UniqueConstraint(
            "tenant_id", "farm_id", "id", name="uq_batch_derivation_events_tenant_farm_id"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id"], ["farms.tenant_id", "farms.id"], name="fk_batch_derivation_events_tenant_farm"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "workflow_id", "workflow_version_id"],
            ["workflow_versions.tenant_id", "workflow_versions.workflow_id", "workflow_versions.id"],
            name="fk_batch_derivation_events_tenant_workflow_version",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "workflow_version_id", "inherited_workflow_stage_id"],
            ["workflow_stages.tenant_id", "workflow_stages.workflow_version_id", "workflow_stages.id"],
            name="fk_batch_derivation_events_inherited_stage",
        ),
    )
