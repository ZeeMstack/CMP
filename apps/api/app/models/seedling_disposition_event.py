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
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

EVENT_KINDS = ("REDUCTION", "REVERSAL")


class SeedlingDispositionEvent(Base):
    """NURSERY-OPS-003B: immutable, insert-only biological fact -- a
    REDUCTION (`quantity_delta < 0`) records seedlings that stopped
    continuing in the living population; a REVERSAL (`quantity_delta > 0`)
    is the exact negation of one specific, named prior REDUCTION
    (`reverses_event_id`), never a free-floating positive entry -- this is
    accounting correction, never biological resurrection. A replacement
    REDUCTION created by the same correction command references the
    original it replaces via `corrects_event_id` (provenance only, not
    used in the balance arithmetic -- every event, of either kind,
    contributes its own signed `quantity_delta` at its own `effective_time`
    identically). `current_living_seedling_count` is never persisted --
    always `SeedlingEntry.starting_living_seedling_count +
    SUM(quantity_delta)`, chronologically validated (see the
    `enforce_seedling_disposition_event_insert_integrity` trigger) to never
    go negative or exceed the frozen starting quantity at any
    effective-time point, not merely in the final aggregate."""

    __tablename__ = "seedling_disposition_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    command_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("seedling_disposition_commands.id"), nullable=False
    )
    seedling_entry_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("seedling_entries.id"), nullable=False)
    event_kind: Mapped[str] = mapped_column(String, nullable=False)
    reason_code: Mapped[str] = mapped_column(
        String, ForeignKey("seedling_disposition_reasons.code"), nullable=False
    )
    quantity_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    reverses_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("seedling_disposition_events.id"), nullable=True
    )
    corrects_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("seedling_disposition_events.id"), nullable=True
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "event_kind IN ('REDUCTION', 'REVERSAL')", name="ck_seedling_disposition_events_kind"
        ),
        CheckConstraint("quantity_delta <> 0", name="ck_seedling_disposition_events_delta_nonzero"),
        # Section 7: REDUCTION is always negative and never itself a
        # reversal of anything; REVERSAL is always positive and always
        # names what it reverses. Same-row, no trigger needed.
        CheckConstraint(
            "(event_kind = 'REDUCTION' AND quantity_delta < 0 AND reverses_event_id IS NULL) OR "
            "(event_kind = 'REVERSAL' AND quantity_delta > 0 AND reverses_event_id IS NOT NULL)",
            name="ck_seedling_disposition_events_kind_sign_consistency",
        ),
        # Section 21/23: only a REDUCTION may ever be a correction
        # replacement; a REVERSAL is never itself "corrected".
        CheckConstraint(
            "corrects_event_id IS NULL OR event_kind = 'REDUCTION'",
            name="ck_seedling_disposition_events_corrects_only_on_reduction",
        ),
        # Section 12: OTHER requires a genuinely non-blank note -- a
        # same-row CHECK, enabled by reason_code being a natural-key FK
        # (see SeedlingDispositionReason's own docstring).
        CheckConstraint(
            "reason_code <> 'OTHER' OR (note IS NOT NULL AND btrim(note) <> '')",
            name="ck_seedling_disposition_events_other_requires_note",
        ),
        # Section 21: at most one REVERSAL may ever reference a given
        # REDUCTION -- a partial unique index, the DB-level backstop for
        # "may be reversed/corrected at most once".
        Index(
            "ux_seedling_disposition_events_reverses_once",
            "reverses_event_id",
            unique=True,
            postgresql_where=text("reverses_event_id IS NOT NULL"),
        ),
        Index("ix_seedling_disposition_events_entry_effective", "seedling_entry_id", "effective_time"),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "command_id"],
            ["seedling_disposition_commands.tenant_id", "seedling_disposition_commands.farm_id", "seedling_disposition_commands.id"],
            name="fk_seedling_disposition_events_tenant_farm_command",
        ),
    )
