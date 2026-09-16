import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.common import TimestampMixin

WORK_ITEM_CATEGORIES = (
    "nursery", "production", "crop_care", "harvest", "post_harvest",
    "store", "quality", "dispatch", "cleaning", "maintenance",
)
WORK_ITEM_STATUSES = ("open", "in_progress", "blocked", "completed", "cancelled")
WORK_ITEM_PRIORITIES = ("normal", "high", "critical")
WORK_ITEM_COMPLETION_MODES = ("operational_record", "manual_record")
WORK_ITEM_RESULT_ENTITY_TYPES = ("harvest_event", "observation_event")
# Terminal statuses -- once reached, no further lifecycle command applies
# (no reopen in this ticket; see docs/domain/FARM_WORK_ITEM_MODEL.md).
WORK_ITEM_TERMINAL_STATUSES = ("completed", "cancelled")


class FarmWorkItem(TimestampMixin, Base):
    """PILOT-OPS-001: a small persisted, operator-facing task/assignment,
    distinct from the authoritative GrowCMP transaction it may link to. A
    CURRENT-STATE row (ADR-005): identity/content fields are frozen for
    life by a DB trigger; only the lifecycle fields below may ever change,
    and only through the owning service commands. Full lifecycle history
    (created/assigned/started/blocked/unblocked/completed/cancelled) is
    read from `audit_events` (`entity_type='farm_work_item'`), not
    duplicated on this row."""

    __tablename__ = "farm_work_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    work_type: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="open")
    priority: Mapped[str] = mapped_column(String, nullable=False, default="normal")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assigned_to_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    crop_batch_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    location_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    carrier_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    asset_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    # PILOT-AGRO-001: optional context reference to the CropIssue this Work
    # Item was created FROM (section 12) -- set only at creation, frozen for
    # life by `enforce_farm_work_item_mutable_fields` exactly like the four
    # context columns above. There is no retrofit path onto an existing,
    # already-created Work Item -- a Crop Issue's corrective work is always
    # a NEW Work Item carrying this reference from the start.
    crop_issue_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    quantity_uom_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("unit_of_measures.id"), nullable=True)

    completion_mode: Mapped[str] = mapped_column(String, nullable=False)
    result_entity_type: Mapped[str | None] = mapped_column(String, nullable=True)
    result_entity_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    result_recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completion_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    blocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    blocked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)

    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)

    update_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    update_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)
    start_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    start_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)
    block_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    block_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)
    unblock_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    unblock_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)
    complete_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    complete_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)
    cancel_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    cancel_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)
    link_result_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    link_result_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint("status IN " + str(WORK_ITEM_STATUSES), name="ck_farm_work_items_status"),
        CheckConstraint("priority IN " + str(WORK_ITEM_PRIORITIES), name="ck_farm_work_items_priority"),
        CheckConstraint("category IN " + str(WORK_ITEM_CATEGORIES), name="ck_farm_work_items_category"),
        CheckConstraint(
            "completion_mode IN " + str(WORK_ITEM_COMPLETION_MODES), name="ck_farm_work_items_completion_mode"
        ),
        CheckConstraint(
            "result_entity_type IS NULL OR result_entity_type IN " + str(WORK_ITEM_RESULT_ENTITY_TYPES),
            name="ck_farm_work_items_result_entity_type",
        ),
        CheckConstraint("length(btrim(work_type)) > 0", name="ck_farm_work_items_work_type_not_blank"),
        CheckConstraint("length(btrim(title)) > 0", name="ck_farm_work_items_title_not_blank"),
        CheckConstraint(
            "(quantity IS NULL) = (quantity_uom_id IS NULL)", name="ck_farm_work_items_quantity_uom_pairing"
        ),
        CheckConstraint(
            "("
            "status IN ('open', 'in_progress') AND "
            "blocked_reason IS NULL AND blocked_at IS NULL AND blocked_by_user_id IS NULL AND "
            "completed_at IS NULL AND completed_by_user_id IS NULL AND completion_note IS NULL AND "
            "result_entity_type IS NULL AND result_entity_id IS NULL AND result_recorded_at IS NULL AND "
            "cancelled_at IS NULL AND cancelled_by_user_id IS NULL AND cancel_reason IS NULL"
            ") OR ("
            "status = 'blocked' AND blocked_reason IS NOT NULL AND blocked_at IS NOT NULL AND "
            "completed_at IS NULL AND completed_by_user_id IS NULL AND completion_note IS NULL AND "
            "result_entity_type IS NULL AND result_entity_id IS NULL AND result_recorded_at IS NULL AND "
            "cancelled_at IS NULL AND cancelled_by_user_id IS NULL AND cancel_reason IS NULL"
            ") OR ("
            "status = 'completed' AND completed_at IS NOT NULL AND "
            "blocked_reason IS NULL AND blocked_at IS NULL AND blocked_by_user_id IS NULL AND "
            "cancelled_at IS NULL AND cancelled_by_user_id IS NULL AND cancel_reason IS NULL AND "
            "(("
            "completion_mode = 'manual_record' AND completed_by_user_id IS NOT NULL AND "
            "result_entity_type IS NULL AND result_entity_id IS NULL AND result_recorded_at IS NULL"
            ") OR ("
            "completion_mode = 'operational_record' AND "
            "result_entity_type IS NOT NULL AND result_entity_id IS NOT NULL AND result_recorded_at IS NOT NULL AND "
            "completed_by_user_id IS NULL AND completion_note IS NULL"
            "))"
            ") OR ("
            "status = 'cancelled' AND cancelled_at IS NOT NULL AND cancelled_by_user_id IS NOT NULL AND "
            "blocked_reason IS NULL AND blocked_at IS NULL AND blocked_by_user_id IS NULL AND "
            "completed_at IS NULL AND completed_by_user_id IS NULL AND completion_note IS NULL AND "
            "result_entity_type IS NULL AND result_entity_id IS NULL AND result_recorded_at IS NULL"
            ")",
            name="ck_farm_work_items_status_shape",
        ),
        Index("ux_farm_work_items_tenant_code_lower", "tenant_id", func.lower(code), unique=True),
        Index("ux_farm_work_items_tenant_client_command_id", "tenant_id", "client_command_id", unique=True),
        Index(
            "ux_farm_work_items_tenant_update_command", "tenant_id", "update_client_command_id",
            unique=True, postgresql_where=text("update_client_command_id IS NOT NULL"),
        ),
        Index(
            "ux_farm_work_items_tenant_start_command", "tenant_id", "start_client_command_id",
            unique=True, postgresql_where=text("start_client_command_id IS NOT NULL"),
        ),
        Index(
            "ux_farm_work_items_tenant_block_command", "tenant_id", "block_client_command_id",
            unique=True, postgresql_where=text("block_client_command_id IS NOT NULL"),
        ),
        Index(
            "ux_farm_work_items_tenant_unblock_command", "tenant_id", "unblock_client_command_id",
            unique=True, postgresql_where=text("unblock_client_command_id IS NOT NULL"),
        ),
        Index(
            "ux_farm_work_items_tenant_complete_command", "tenant_id", "complete_client_command_id",
            unique=True, postgresql_where=text("complete_client_command_id IS NOT NULL"),
        ),
        Index(
            "ux_farm_work_items_tenant_cancel_command", "tenant_id", "cancel_client_command_id",
            unique=True, postgresql_where=text("cancel_client_command_id IS NOT NULL"),
        ),
        Index(
            "ux_farm_work_items_tenant_link_result_command", "tenant_id", "link_result_client_command_id",
            unique=True, postgresql_where=text("link_result_client_command_id IS NOT NULL"),
        ),
        Index("ix_farm_work_items_farm_status", "tenant_id", "farm_id", "status"),
        Index("ix_farm_work_items_farm_assignee_status", "tenant_id", "farm_id", "assigned_to_user_id", "status"),
        Index("ix_farm_work_items_farm_due_at", "tenant_id", "farm_id", "due_at"),
        Index("ix_farm_work_items_farm_crop_issue", "tenant_id", "farm_id", "crop_issue_id"),
        UniqueConstraint("tenant_id", "farm_id", "id", name="uq_farm_work_items_tenant_farm_id"),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id"], ["farms.tenant_id", "farms.id"], name="fk_farm_work_items_tenant_farm"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "crop_batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_farm_work_items_tenant_farm_crop_batch",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "location_id"],
            ["locations.tenant_id", "locations.farm_id", "locations.id"],
            name="fk_farm_work_items_tenant_farm_location",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "carrier_id"],
            ["carriers.tenant_id", "carriers.farm_id", "carriers.id"],
            name="fk_farm_work_items_tenant_farm_carrier",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "asset_id"],
            ["assets.tenant_id", "assets.farm_id", "assets.id"],
            name="fk_farm_work_items_tenant_farm_asset",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "crop_issue_id"],
            ["crop_issues.tenant_id", "crop_issues.farm_id", "crop_issues.id"],
            name="fk_farm_work_items_tenant_farm_crop_issue",
        ),
    )
