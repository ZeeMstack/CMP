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
from app.models.inspection_finding import FINDING_CATEGORIES, FINDING_SEVERITIES

CROP_ISSUE_STATUSES = ("open", "resolved", "closed")


class CropIssue(Base):
    """PILOT-AGRO-001 section 10: a persistent crop problem raised from a
    significant `InspectionFinding`. A CURRENT-STATE row (ADR-005), not a
    fully immutable event -- identity/content fields are frozen for life by
    `enforce_crop_issue_mutable_fields` (mirrors `enforce_farm_work_item_
    mutable_fields` exactly); only the small lifecycle/current-state fields
    below may ever change, and only through `crop_issue_service`'s owning
    commands.

    Persisted lifecycle is deliberately just OPEN -> RESOLVED -> CLOSED
    (never reopened) -- section 10's suggested `ACTION_IN_PROGRESS`/
    `FOLLOW_UP_DUE` states are READ-MODEL overlays instead (derived from
    "has an open linked FarmWorkItem" / "follow_up_due_at has passed"),
    per section 14's own "these may be read-model items" guidance and the
    ticket's explicit "keep simple" instruction -- see
    docs/domain/GROWING_PROTOCOL_INSPECTION_MODEL.md. `suspected_cause`
    (copied from the originating Finding at open time, further editable by
    a grower/supervisor) and `confirmed_diagnosis` remain two distinct
    columns forever (section 11) -- no command ever copies one into the
    other. RESOLVED and CLOSED are two separate, deliberate, authorized
    commands (`resolve_crop_issue`/`close_crop_issue`) -- nothing
    (including a FarmWorkItem completing, or a follow-up Inspection
    recording a RESOLVED outcome) ever transitions this row automatically
    (section WORK ITEM COMPLETE != ISSUE RESOLVED)."""

    __tablename__ = "crop_issues"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crop_batches.id"), nullable=False)
    batch_carrier_assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("batch_carrier_assignments.id"), nullable=True
    )
    location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id"), nullable=True)
    originating_grower_inspection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("grower_inspections.id"), nullable=False
    )
    originating_finding_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("inspection_findings.id"), nullable=True
    )
    category: Mapped[str] = mapped_column(String, nullable=False)
    severity: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    suspected_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_diagnosis: Mapped[str | None] = mapped_column(Text, nullable=True)
    diagnosis_confirmed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    diagnosis_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    status: Mapped[str] = mapped_column(String, nullable=False, default="open")
    opened_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    assigned_owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    follow_up_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    closed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    close_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    update_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    update_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)
    diagnosis_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    diagnosis_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)
    resolve_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    resolve_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)
    close_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    close_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('" + "', '".join(CROP_ISSUE_STATUSES) + "')", name="ck_crop_issues_status"),
        CheckConstraint(
            "category IN ('" + "', '".join(FINDING_CATEGORIES) + "')", name="ck_crop_issues_category"
        ),
        CheckConstraint(
            "severity IN ('" + "', '".join(FINDING_SEVERITIES) + "')", name="ck_crop_issues_severity"
        ),
        CheckConstraint("length(btrim(description)) > 0", name="ck_crop_issues_description_not_blank"),
        CheckConstraint(
            "(confirmed_diagnosis IS NULL) = (diagnosis_confirmed_by_user_id IS NULL) AND "
            "(confirmed_diagnosis IS NULL) = (diagnosis_confirmed_at IS NULL)",
            name="ck_crop_issues_diagnosis_fields_together",
        ),
        CheckConstraint(
            "("
            "status = 'open' AND resolved_at IS NULL AND resolved_by_user_id IS NULL AND resolution_note IS NULL "
            "AND closed_at IS NULL AND closed_by_user_id IS NULL AND close_note IS NULL"
            ") OR ("
            "status = 'resolved' AND resolved_at IS NOT NULL AND resolved_by_user_id IS NOT NULL "
            "AND closed_at IS NULL AND closed_by_user_id IS NULL AND close_note IS NULL"
            ") OR ("
            "status = 'closed' AND resolved_at IS NOT NULL AND resolved_by_user_id IS NOT NULL "
            "AND closed_at IS NOT NULL AND closed_by_user_id IS NOT NULL"
            ")",
            name="ck_crop_issues_status_shape",
        ),
        Index("ux_crop_issues_tenant_code_lower", "tenant_id", func.lower(code), unique=True),
        Index("ux_crop_issues_tenant_client_command_id", "tenant_id", "client_command_id", unique=True),
        Index(
            "ux_crop_issues_tenant_update_command", "tenant_id", "update_client_command_id",
            unique=True, postgresql_where=text("update_client_command_id IS NOT NULL"),
        ),
        Index(
            "ux_crop_issues_tenant_diagnosis_command", "tenant_id", "diagnosis_client_command_id",
            unique=True, postgresql_where=text("diagnosis_client_command_id IS NOT NULL"),
        ),
        Index(
            "ux_crop_issues_tenant_resolve_command", "tenant_id", "resolve_client_command_id",
            unique=True, postgresql_where=text("resolve_client_command_id IS NOT NULL"),
        ),
        Index(
            "ux_crop_issues_tenant_close_command", "tenant_id", "close_client_command_id",
            unique=True, postgresql_where=text("close_client_command_id IS NOT NULL"),
        ),
        Index("ix_crop_issues_farm_status", "tenant_id", "farm_id", "status"),
        Index("ix_crop_issues_farm_batch", "tenant_id", "farm_id", "batch_id"),
        UniqueConstraint("tenant_id", "id", name="uq_crop_issues_tenant_id"),
        UniqueConstraint("tenant_id", "farm_id", "id", name="uq_crop_issues_tenant_farm_id"),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id"], ["farms.tenant_id", "farms.id"], name="fk_crop_issues_tenant_farm"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_crop_issues_tenant_farm_batch",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_carrier_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id",
                "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_crop_issues_tenant_farm_assignment",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "location_id"],
            ["locations.tenant_id", "locations.farm_id", "locations.id"],
            name="fk_crop_issues_tenant_farm_location",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "originating_grower_inspection_id"],
            ["grower_inspections.tenant_id", "grower_inspections.farm_id", "grower_inspections.id"],
            name="fk_crop_issues_tenant_farm_originating_inspection",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "originating_finding_id"],
            ["inspection_findings.tenant_id", "inspection_findings.farm_id", "inspection_findings.id"],
            name="fk_crop_issues_tenant_farm_originating_finding",
        ),
    )
