import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.common import TimestampMixin

STAGE_CATEGORIES = (
    "seeding",
    "germination",
    "nursery",
    "transplanting",
    "intermediate",
    "production",
    "harvest_ready",
    "harvesting",
    "completed",
    "rejected",
)


class WorkflowStage(TimestampMixin, Base):
    __tablename__ = "workflow_stages"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    workflow_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_versions.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    stage_category: Mapped[str] = mapped_column(String, nullable=False)
    expected_duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    permitted_location_type_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("location_types.id"), nullable=True
    )
    required_carrier_type_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("carrier_types.id"), nullable=True
    )
    is_start: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_terminal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        CheckConstraint(
            "stage_category IN ('" + "', '".join(STAGE_CATEGORIES) + "')",
            name="ck_workflow_stages_category_allowed",
        ),
        CheckConstraint("display_order >= 0", name="ck_workflow_stages_display_order_non_negative"),
        CheckConstraint(
            "expected_duration_minutes IS NULL OR expected_duration_minutes > 0",
            name="ck_workflow_stages_duration_positive",
        ),
        Index("ux_workflow_stages_version_code_lower", "workflow_version_id", func.lower(code), unique=True),
        UniqueConstraint("tenant_id", "workflow_version_id", "id", name="uq_workflow_stages_tenant_version_id"),
        ForeignKeyConstraint(
            ["tenant_id", "workflow_version_id"],
            ["workflow_versions.tenant_id", "workflow_versions.id"],
            name="fk_workflow_stages_tenant_version",
        ),
    )
