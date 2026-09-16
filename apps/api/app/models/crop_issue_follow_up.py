import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

FOLLOW_UP_OUTCOMES = ("improved", "unchanged", "worsened", "resolved")


class CropIssueFollowUp(Base):
    """PILOT-AGRO-001 section 13: one follow-up observation against an
    open `CropIssue`. Recording an outcome of RESOLVED here is descriptive
    only -- it never transitions the parent `CropIssue.status` by itself;
    an authorized user must still call `crop_issue_service.
    resolve_crop_issue` deliberately (section WORK ITEM COMPLETE != ISSUE
    RESOLVED's sibling rule for follow-up outcomes). Fully insert-only,
    like `GrowerInspection`."""

    __tablename__ = "crop_issue_follow_ups"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    crop_issue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crop_issues.id"), nullable=False)
    follow_up_grower_inspection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("grower_inspections.id"), nullable=True
    )
    affected_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome: Mapped[str] = mapped_column(String, nullable=False)
    recorded_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "outcome IN ('" + "', '".join(FOLLOW_UP_OUTCOMES) + "')", name="ck_crop_issue_follow_ups_outcome"
        ),
        CheckConstraint("affected_count IS NULL OR affected_count >= 0", name="ck_crop_issue_follow_ups_affected_count_non_negative"),
        Index("ux_crop_issue_follow_ups_tenant_client_command_id", "tenant_id", "client_command_id", unique=True),
        Index("ix_crop_issue_follow_ups_issue", "tenant_id", "farm_id", "crop_issue_id"),
        UniqueConstraint("tenant_id", "id", name="uq_crop_issue_follow_ups_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "crop_issue_id"],
            ["crop_issues.tenant_id", "crop_issues.farm_id", "crop_issues.id"],
            name="fk_crop_issue_follow_ups_tenant_farm_issue",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "follow_up_grower_inspection_id"],
            ["grower_inspections.tenant_id", "grower_inspections.farm_id", "grower_inspections.id"],
            name="fk_crop_issue_follow_ups_tenant_farm_inspection",
        ),
    )
