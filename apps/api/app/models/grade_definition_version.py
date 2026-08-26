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
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class GradeDefinitionVersion(Base):
    """POSTHARVEST-OPS-001A: the versioned, immutable-once-created
    commercial-grading criteria for one `GradeDefinition`. Lifecycle is
    `draft -> active -> retired` (never `draft -> retired` directly, never
    reactivated) — mirrors `WorkflowVersion`'s own `draft -> published ->
    retired` shape (`enforce_workflow_version_transition`,
    `ux_workflow_versions_one_published`) with two deliberate departures
    the ticket requires: (1) activation/retirement take an explicit
    caller-supplied business `effective_time`, never a bare `now()`
    reused for both business and recorded time; (2) every mutating command
    (create, activate, retire) carries its own `client_command_id` +
    fingerprint pair for idempotent replay — `WorkflowVersion` has no such
    columns at all. `activation_client_command_id`/`retirement_client_
    command_id` are separate, independently-nullable columns rather than a
    second table, since each names a specific lifecycle transition applied
    to this same row over time, not a new entity: `activation_*` is set
    once, at `draft -> active`; `retirement_*` is set only by an explicit
    RETIRE command (`active -> retired`) and stays NULL when a version is
    instead retired as the side effect of a later version's replacement
    activation — that distinction is what lets a reader tell "explicitly
    retired" apart from "superseded by a newer version" without a second
    audit lookup."""

    __tablename__ = "grade_definition_versions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    grade_definition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("grade_definitions.id"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft")
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    spec_notes: Mapped[str | None] = mapped_column(String, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # CREATE-command idempotency.
    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    # ACTIVATE-command idempotency — populated exactly once, at draft -> active.
    activation_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    activation_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)
    # RETIRE-command idempotency — populated only by an explicit retirement
    # command; stays NULL when retirement instead happens as the side
    # effect of a replacement activation (see class docstring).
    retirement_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    retirement_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'active', 'retired')", name="ck_grade_definition_versions_status"
        ),
        CheckConstraint("version_number > 0", name="ck_grade_definition_versions_number_positive"),
        CheckConstraint(
            "(status = 'draft' AND effective_from IS NULL AND effective_until IS NULL "
            " AND activation_client_command_id IS NULL AND activation_request_fingerprint IS NULL "
            " AND retirement_client_command_id IS NULL AND retirement_request_fingerprint IS NULL) "
            "OR (status = 'active' AND effective_from IS NOT NULL AND effective_until IS NULL "
            " AND activation_client_command_id IS NOT NULL AND activation_request_fingerprint IS NOT NULL "
            " AND retirement_client_command_id IS NULL AND retirement_request_fingerprint IS NULL) "
            "OR (status = 'retired' AND effective_from IS NOT NULL AND effective_until IS NOT NULL "
            " AND activation_client_command_id IS NOT NULL AND activation_request_fingerprint IS NOT NULL)",
            name="ck_grade_definition_versions_status_shape",
        ),
        CheckConstraint(
            "effective_until IS NULL OR effective_until >= effective_from",
            name="ck_grade_definition_versions_effective_order",
        ),
        UniqueConstraint(
            "grade_definition_id", "version_number", name="uq_grade_definition_versions_definition_number"
        ),
        UniqueConstraint("tenant_id", "id", name="uq_grade_definition_versions_tenant_id"),
        UniqueConstraint(
            "tenant_id", "grade_definition_id", "id",
            name="uq_grade_definition_versions_tenant_definition_id",
        ),
        # DB-level "at most one ACTIVE version per GradeDefinition" —
        # partial/kind-scoped, so many draft/retired rows may coexist
        # freely. Not service-logic-only, per the ticket's explicit
        # requirement (WorkflowVersion's own equivalent,
        # ux_workflow_versions_one_published, is the direct precedent).
        Index(
            "ux_grade_definition_versions_active_once", "grade_definition_id", unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index(
            "ux_grade_definition_versions_tenant_client_command_id", "tenant_id", "client_command_id",
            unique=True,
        ),
        Index(
            "ux_grade_definition_versions_tenant_activation_command", "tenant_id",
            "activation_client_command_id", unique=True,
            postgresql_where=text("activation_client_command_id IS NOT NULL"),
        ),
        Index(
            "ux_grade_definition_versions_tenant_retirement_command", "tenant_id",
            "retirement_client_command_id", unique=True,
            postgresql_where=text("retirement_client_command_id IS NOT NULL"),
        ),
        ForeignKeyConstraint(
            ["tenant_id", "grade_definition_id"],
            ["grade_definitions.tenant_id", "grade_definitions.id"],
            name="fk_grade_definition_versions_tenant_definition",
        ),
    )
