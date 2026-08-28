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


class PackingReversalEvent(Base):
    """POSTHARVEST-OPS-001H: immutable, insert-only whole-event reversal of
    one PackingEvent -- never a field-by-field correction. A PackingEvent
    may be reversed at most once, ever
    (`ux_packing_reversal_events_packing_event_id`). The original
    PackingEvent, its PackingInputLines, and its FinishedGoodsLot are never
    modified; reversal restores every source GradedProduceLot's ledger
    balance and neutralizes the FinishedGoodsLot's opening quantity by
    appending new, typed ledger entries (see
    `GradedProduceLotLedgerEntry`/`FinishedGoodsLedgerEntry`'s own
    `packing_reversal` kind) -- `PackingReversalInput` names the exact
    per-input-line restoration amounts. Mirrors `PackingEvent`'s own
    command/idempotency shape exactly (tenant-scoped `client_command_id` +
    SHA-256 fingerprint)."""

    __tablename__ = "packing_reversal_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    packing_event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("packing_events.id"), nullable=False)
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
            "btrim(reason_code) <> ''", name="ck_packing_reversal_events_reason_required",
        ),
        CheckConstraint(
            "note IS NULL OR btrim(note) <> ''", name="ck_packing_reversal_events_note_not_blank",
        ),
        Index(
            "ux_packing_reversal_events_tenant_client_command_id", "tenant_id", "client_command_id", unique=True
        ),
        UniqueConstraint("packing_event_id", name="ux_packing_reversal_events_packing_event_id"),
        UniqueConstraint(
            "tenant_id", "farm_id", "id", name="uq_packing_reversal_events_tenant_farm_id"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "packing_event_id"],
            ["packing_events.tenant_id", "packing_events.farm_id", "packing_events.id"],
            name="fk_packing_reversal_events_tenant_farm_event",
        ),
    )
