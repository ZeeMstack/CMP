import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class WorkflowVersion(Base):
    __tablename__ = "workflow_versions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflows.id"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("state IN ('draft', 'published', 'retired')", name="ck_workflow_versions_state"),
        CheckConstraint("version_number > 0", name="ck_workflow_versions_number_positive"),
        CheckConstraint(
            "(state = 'draft' AND published_at IS NULL AND retired_at IS NULL) OR "
            "(state = 'published' AND published_at IS NOT NULL AND retired_at IS NULL) OR "
            "(state = 'retired' AND published_at IS NOT NULL AND retired_at IS NOT NULL)",
            name="ck_workflow_versions_state_timestamps",
        ),
        CheckConstraint(
            "retired_at IS NULL OR published_at IS NULL OR retired_at >= published_at",
            name="ck_workflow_versions_retired_after_published",
        ),
        UniqueConstraint("workflow_id", "version_number", name="uq_workflow_versions_workflow_number"),
        UniqueConstraint("tenant_id", "id", name="uq_workflow_versions_tenant_id_id"),
        UniqueConstraint(
            "tenant_id", "workflow_id", "id", name="uq_workflow_versions_tenant_workflow_id"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "workflow_id"],
            ["workflows.tenant_id", "workflows.id"],
            name="fk_workflow_versions_tenant_workflow",
        ),
    )
