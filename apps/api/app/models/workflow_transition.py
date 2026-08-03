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


class WorkflowTransition(Base):
    __tablename__ = "workflow_transitions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    workflow_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_versions.id"), nullable=False
    )
    from_stage_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_stages.id"), nullable=False)
    to_stage_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_stages.id"), nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("from_stage_id <> to_stage_id", name="ck_workflow_transitions_no_self_transition"),
        Index(
            "ux_workflow_transitions_version_code_lower",
            "workflow_version_id",
            func.lower(code),
            unique=True,
        ),
        UniqueConstraint(
            "workflow_version_id", "from_stage_id", "to_stage_id", name="uq_workflow_transitions_pair"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "workflow_version_id"],
            ["workflow_versions.tenant_id", "workflow_versions.id"],
            name="fk_workflow_transitions_tenant_version",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "workflow_version_id", "from_stage_id"],
            ["workflow_stages.tenant_id", "workflow_stages.workflow_version_id", "workflow_stages.id"],
            name="fk_workflow_transitions_from_stage",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "workflow_version_id", "to_stage_id"],
            ["workflow_stages.tenant_id", "workflow_stages.workflow_version_id", "workflow_stages.id"],
            name="fk_workflow_transitions_to_stage",
        ),
    )
