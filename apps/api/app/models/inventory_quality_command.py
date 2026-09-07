import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

INVENTORY_QUALITY_COMMAND_OPERATION_KINDS = ("RECORD", "CORRECT", "PARTIAL", "PARTIAL_CORRECT")


class InventoryQualityCommand(Base):
    """STORE-INV-002A.2 CTO closure pass: the logical command header every
    Quality command writes exactly once, before any `QualityDispositionEvent`
    row -- the actual fix for command-level idempotency (`docs/domain/
    STORE_INVENTORY_MODEL.md` §11). Mirrors `SeedlingDispositionCommand`'s
    own "one header, idempotent on `(tenant_id, client_command_id)`, fans
    out to a variable number of child event rows" shape.

    `operation_kind`: `RECORD` (ordinary whole-cohort disposition, one
    event) | `CORRECT` (whole-cohort correction: one REVERSAL, optionally
    one replacement) | `PARTIAL` (ordinary partial-quantity disposition,
    one child event) | `PARTIAL_CORRECT` ("Correct decision for part of
    quantity" -- one child event, bypassing the ordinary transition table).
    `target_event_id` is required for `CORRECT`/`PARTIAL_CORRECT` (the
    specific event the operator observed and is now acting on -- the
    request-supplied target, never silently resolved to "whatever is
    current"), forbidden for `RECORD`/`PARTIAL`.

    The `(tenant_id, client_command_id)` unique constraint is the actual
    fix: two concurrent requests sharing one `client_command_id`, even
    against different cohorts (which acquire different `FOR UPDATE`
    locks and so cannot serialize against each other), can never both
    insert a command row here."""

    __tablename__ = "inventory_quality_commands"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    inventory_quantity_cohort_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inventory_quantity_cohorts.id"), nullable=False
    )
    operation_kind: Mapped[str] = mapped_column(String, nullable=False)
    target_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("quality_disposition_events.id"), nullable=True
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "operation_kind IN ('RECORD', 'CORRECT', 'PARTIAL', 'PARTIAL_CORRECT')",
            name="ck_inventory_quality_commands_operation_kind",
        ),
        CheckConstraint(
            "(operation_kind IN ('RECORD', 'PARTIAL') AND target_event_id IS NULL) OR "
            "(operation_kind IN ('CORRECT', 'PARTIAL_CORRECT') AND target_event_id IS NOT NULL)",
            name="ck_inventory_quality_commands_target_matches_kind",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_inventory_quality_commands_tenant_id_id"),
        UniqueConstraint(
            "tenant_id", "client_command_id", name="ux_inventory_quality_commands_tenant_client_command_id"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "inventory_quantity_cohort_id"],
            ["inventory_quantity_cohorts.tenant_id", "inventory_quantity_cohorts.id"],
            name="fk_inventory_quality_commands_tenant_cohort",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "target_event_id"],
            ["quality_disposition_events.tenant_id", "quality_disposition_events.id"],
            name="fk_inventory_quality_commands_tenant_target_event",
        ),
    )
