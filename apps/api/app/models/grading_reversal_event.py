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


class GradingReversalEvent(Base):
    """POSTHARVEST-OPS-001H: immutable, insert-only whole-event reversal of
    one GradingEvent -- never a field-by-field correction. A GradingEvent
    may be reversed at most once, ever
    (`ux_grading_reversal_events_grading_event_id`). The original
    GradingEvent and its GradedProduceLot outputs are never modified;
    reversal restores the source HarvestedProduceLot's ledger balance and
    zeroes every output GradedProduceLot's balance by appending new,
    typed ledger entries (see `ProduceLotLedgerEntry`/
    `GradedProduceLotLedgerEntry`'s own `grading_reversal` kind) --
    `GradingReversalOutput` names the exact per-output restoration amounts.
    Mirrors `GradingEvent`'s own command/idempotency shape exactly
    (tenant-scoped `client_command_id` + SHA-256 fingerprint)."""

    __tablename__ = "grading_reversal_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    grading_event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("grading_events.id"), nullable=False)
    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    reason_code: Mapped[str] = mapped_column(String, nullable=False)
    # PRE-COMMIT AUDIT: nullable -- reason_code is mandatory, note is
    # optional (mirrors SeedlingDispositionEvent's own REVERSAL shape, not
    # HarvestSourceLineCorrection's stricter both-mandatory field-correction
    # shape).
    note: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "btrim(reason_code) <> ''", name="ck_grading_reversal_events_reason_required",
        ),
        CheckConstraint(
            "note IS NULL OR btrim(note) <> ''", name="ck_grading_reversal_events_note_not_blank",
        ),
        Index(
            "ux_grading_reversal_events_tenant_client_command_id", "tenant_id", "client_command_id", unique=True
        ),
        UniqueConstraint("grading_event_id", name="ux_grading_reversal_events_grading_event_id"),
        UniqueConstraint(
            "tenant_id", "farm_id", "id", name="uq_grading_reversal_events_tenant_farm_id"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "grading_event_id"],
            ["grading_events.tenant_id", "grading_events.farm_id", "grading_events.id"],
            name="fk_grading_reversal_events_tenant_farm_event",
        ),
    )
