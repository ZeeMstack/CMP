import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

PROTOCOL_VERSION_STATES = ("draft", "active", "retired")


class GrowingProtocolVersion(Base):
    """PILOT-AGRO-001: the versioned, agronomically-immutable-once-ACTIVE
    content of one `GrowingProtocol`. Lifecycle is `draft -> active ->
    retired` -- mirrors `WorkflowVersion`'s own `draft -> published ->
    retired` shape and `GradeDefinitionVersion`'s own per-command
    idempotency-column convention (a separate client_command_id/
    fingerprint pair per lifecycle transition, never a shared one). To
    change ACTIVE agronomic content, a caller must create a NEXT version
    (`create_draft_version`) -- there is no in-place edit path for a
    version once it leaves DRAFT (enforced in `growing_protocol_service`,
    matching `add_stage`'s `WorkflowVersionNotDraftError` precedent for
    `WorkflowStage`). `reason` is required, non-blank text: PILOT-AGRO-001
    section 2 calls it out as required version metadata (why this version
    exists), never inferred."""

    __tablename__ = "growing_protocol_versions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    growing_protocol_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("growing_protocols.id"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False, default="draft")
    author_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    activation_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    activation_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)
    retirement_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    retirement_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "state IN ('" + "', '".join(PROTOCOL_VERSION_STATES) + "')", name="ck_growing_protocol_versions_state"
        ),
        CheckConstraint("version_number > 0", name="ck_growing_protocol_versions_number_positive"),
        CheckConstraint("length(btrim(reason)) > 0", name="ck_growing_protocol_versions_reason_not_blank"),
        CheckConstraint(
            "(state = 'draft' AND activated_at IS NULL AND retired_at IS NULL "
            " AND activation_client_command_id IS NULL AND activation_request_fingerprint IS NULL "
            " AND retirement_client_command_id IS NULL AND retirement_request_fingerprint IS NULL) OR "
            "(state = 'active' AND activated_at IS NOT NULL AND retired_at IS NULL "
            " AND activation_client_command_id IS NOT NULL AND activation_request_fingerprint IS NOT NULL "
            " AND retirement_client_command_id IS NULL AND retirement_request_fingerprint IS NULL) OR "
            "(state = 'retired' AND activated_at IS NOT NULL AND retired_at IS NOT NULL "
            " AND activation_client_command_id IS NOT NULL AND activation_request_fingerprint IS NOT NULL)",
            name="ck_growing_protocol_versions_state_shape",
        ),
        CheckConstraint(
            "retired_at IS NULL OR retired_at >= activated_at", name="ck_growing_protocol_versions_retired_after_activated"
        ),
        UniqueConstraint(
            "growing_protocol_id", "version_number", name="uq_growing_protocol_versions_protocol_number"
        ),
        UniqueConstraint("tenant_id", "id", name="uq_growing_protocol_versions_tenant_id"),
        UniqueConstraint(
            "tenant_id", "growing_protocol_id", "id", name="uq_growing_protocol_versions_tenant_protocol_id"
        ),
        # DB-level "at most one ACTIVE version per protocol" -- mirrors
        # `ux_grade_definition_versions_active_once` / `ux_workflow_
        # versions_one_published` exactly.
        Index(
            "ux_growing_protocol_versions_active_once", "growing_protocol_id", unique=True,
            postgresql_where=text("state = 'active'"),
        ),
        Index(
            "ux_growing_protocol_versions_tenant_client_command_id", "tenant_id", "client_command_id", unique=True
        ),
        Index(
            "ux_growing_protocol_versions_tenant_activation_command", "tenant_id", "activation_client_command_id",
            unique=True, postgresql_where=text("activation_client_command_id IS NOT NULL"),
        ),
        Index(
            "ux_growing_protocol_versions_tenant_retirement_command", "tenant_id", "retirement_client_command_id",
            unique=True, postgresql_where=text("retirement_client_command_id IS NOT NULL"),
        ),
        ForeignKeyConstraint(
            ["tenant_id", "growing_protocol_id"],
            ["growing_protocols.tenant_id", "growing_protocols.id"],
            name="fk_growing_protocol_versions_tenant_protocol",
        ),
    )
