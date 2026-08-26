import uuid
from datetime import datetime

from sqlalchemy import (
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


class GradeDefinition(Base):
    """POSTHARVEST-OPS-001A: the stable, tenant-scoped commercial-grade
    identity — completely separate from the biological workflow/version
    model (never placed on `WorkflowVersion`). `crop_id` (required) and
    `variety_id` (nullable — NULL means "applies to all varieties of that
    crop") are part of this identity's own scope and never change once
    created; a change in commercial-grading criteria is expressed as a new
    `GradeDefinitionVersion`, never as a mutation here. No `farm_id` —
    grade configuration is tenant-scoped, not farm-scoped, mirroring
    `Crop`/`Workflow`'s own tenant-only shape. Reuses the exact composite-FK
    idiom `Workflow` already established for its own `crop_id`/`variety_id`
    pair (`fk_workflows_tenant_crop`/`fk_workflows_tenant_crop_variety`) so
    a cross-tenant or wrong-crop variety reference is structurally
    impossible, not merely service-validated. `client_command_id`/
    `request_fingerprint` back this ticket's own create-command idempotency
    (the closest existing configuration precedent, `workflow_service.
    register_workflow`, does not use this pattern — see
    `grade_definition_service.py`'s module docstring for why this ticket
    deliberately diverges from it)."""

    __tablename__ = "grade_definitions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    crop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crops.id"), nullable=False)
    variety_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("varieties.id"), nullable=True)
    code: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        Index("ux_grade_definitions_tenant_code_lower", "tenant_id", func.lower(code), unique=True),
        Index(
            "ux_grade_definitions_tenant_client_command_id", "tenant_id", "client_command_id", unique=True
        ),
        UniqueConstraint("tenant_id", "id", name="uq_grade_definitions_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "crop_id"],
            ["crops.tenant_id", "crops.id"],
            name="fk_grade_definitions_tenant_crop",
        ),
        # MATCH SIMPLE (Postgres default): this composite FK is only
        # evaluated when variety_id IS NOT NULL, so a NULL
        # variety_id ("applies to all varieties") never engages it —
        # exactly mirroring fk_workflows_tenant_crop_variety.
        ForeignKeyConstraint(
            ["tenant_id", "crop_id", "variety_id"],
            ["varieties.tenant_id", "varieties.crop_id", "varieties.id"],
            name="fk_grade_definitions_tenant_crop_variety",
        ),
    )
