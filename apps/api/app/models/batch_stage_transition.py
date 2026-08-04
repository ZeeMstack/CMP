import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

COMMAND_KINDS = ("initial_entry", "stage_transition", "derivation_entry")


class BatchStageTransition(Base):
    """Immutable, insert-only record of one stage-progression command —
    either a batch's initial entry into its start stage, or a normal
    configured-transition move. Never updated or deleted (CMP-008)."""

    __tablename__ = "batch_stage_transitions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crop_batches.id"), nullable=False)
    workflow_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_versions.id"), nullable=False
    )
    command_kind: Mapped[str] = mapped_column(String, nullable=False)
    source_stage_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workflow_stages.id"), nullable=True
    )
    destination_stage_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_stages.id"), nullable=False
    )
    configured_transition_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workflow_transitions.id"), nullable=True
    )
    batch_derivation_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("batch_derivation_events.id"), nullable=True
    )
    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "command_kind IN ('initial_entry', 'stage_transition', 'derivation_entry')",
            name="ck_batch_stage_transitions_command_kind",
        ),
        CheckConstraint(
            "(command_kind = 'initial_entry' AND source_stage_id IS NULL AND configured_transition_id IS NULL "
            "AND batch_derivation_event_id IS NULL AND client_command_id IS NOT NULL "
            "AND request_fingerprint IS NOT NULL) OR "
            "(command_kind = 'stage_transition' AND source_stage_id IS NOT NULL "
            "AND configured_transition_id IS NOT NULL AND batch_derivation_event_id IS NULL "
            "AND client_command_id IS NOT NULL AND request_fingerprint IS NOT NULL) OR "
            "(command_kind = 'derivation_entry' AND source_stage_id IS NULL AND configured_transition_id IS NULL "
            "AND batch_derivation_event_id IS NOT NULL AND client_command_id IS NULL "
            "AND request_fingerprint IS NULL)",
            name="ck_batch_stage_transitions_shape",
        ),
        CheckConstraint(
            "source_stage_id IS NULL OR source_stage_id <> destination_stage_id",
            name="ck_batch_stage_transitions_no_self_transition",
        ),
        Index(
            "ux_batch_stage_transitions_tenant_kind_client_id",
            "tenant_id",
            "command_kind",
            "client_command_id",
            unique=True,
        ),
        Index(
            "ux_batch_stage_transitions_one_initial_entry",
            "batch_id",
            unique=True,
            postgresql_where=text("command_kind = 'initial_entry'"),
        ),
        Index(
            "ux_batch_stage_transitions_one_derivation_entry",
            "batch_id",
            unique=True,
            postgresql_where=text("command_kind = 'derivation_entry'"),
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_batch_stage_transitions_tenant_farm_batch",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_derivation_event_id"],
            [
                "batch_derivation_events.tenant_id",
                "batch_derivation_events.farm_id",
                "batch_derivation_events.id",
            ],
            name="fk_batch_stage_transitions_derivation_event",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "workflow_version_id", "destination_stage_id"],
            ["workflow_stages.tenant_id", "workflow_stages.workflow_version_id", "workflow_stages.id"],
            name="fk_batch_stage_transitions_destination_stage",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "workflow_version_id", "source_stage_id"],
            ["workflow_stages.tenant_id", "workflow_stages.workflow_version_id", "workflow_stages.id"],
            name="fk_batch_stage_transitions_source_stage",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "workflow_version_id", "configured_transition_id"],
            [
                "workflow_transitions.tenant_id",
                "workflow_transitions.workflow_version_id",
                "workflow_transitions.id",
            ],
            name="fk_batch_stage_transitions_configured_transition",
        ),
    )
