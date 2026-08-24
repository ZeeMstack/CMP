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

EVENT_KINDS = ("REDUCTION", "REVERSAL")


class ProductionDispositionEvent(Base):
    """LEAFY-OPS-001: immutable, insert-only biological fact -- a REDUCTION
    (`quantity_delta < 0`) records living plants that stopped continuing in
    a Production Cultivation Plate's authoritative population (death,
    disease/pest/mechanical removal, quality removal, or another explicit
    biological removal -- never merely "weak" or "off-spec", which remain
    living until actually removed); a REVERSAL (`quantity_delta > 0`) is the
    exact negation of one specific, named prior REDUCTION
    (`reverses_event_id`) -- accounting correction, never biological
    resurrection. Mirrors `SeedlingDispositionEvent`'s proven shape, with
    two identity fields instead of one: `batch_carrier_assignment_id` is the
    actual BCA generation the event was recorded against (audit truth --
    which physical Plate placement); `population_root_batch_carrier_
    assignment_id` is the stable lineage anchor every event across every
    restoration generation (A/B/C/...) shares, letting authoritative living
    population be computed as one flat, non-recursive SUM regardless of how
    many times the Plate's biological assignment has been exhausted and
    restored. Server-derived only -- an insert-integrity trigger verifies
    the root matches the referenced BCA's own stored root; never trusted
    from the API payload. `current` population is never persisted -- always
    `TransplantDestinationLine.assigned_plant_count` (for the root BCA) +
    `SUM(quantity_delta)` across every event sharing the same root,
    chronologically validated to never go negative or exceed the root's
    opening quantity at any point in history, not merely in the final
    aggregate."""

    __tablename__ = "production_disposition_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    command_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("production_disposition_commands.id"), nullable=False
    )
    batch_carrier_assignment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batch_carrier_assignments.id"), nullable=False
    )
    population_root_batch_carrier_assignment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batch_carrier_assignments.id"), nullable=False
    )
    event_kind: Mapped[str] = mapped_column(String, nullable=False)
    reason_code: Mapped[str] = mapped_column(
        String, ForeignKey("production_disposition_reasons.code"), nullable=False
    )
    quantity_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    reverses_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("production_disposition_events.id"), nullable=True
    )
    corrects_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("production_disposition_events.id"), nullable=True
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "event_kind IN ('REDUCTION', 'REVERSAL')", name="ck_production_disposition_events_kind"
        ),
        CheckConstraint("quantity_delta <> 0", name="ck_production_disposition_events_delta_nonzero"),
        CheckConstraint(
            "(event_kind = 'REDUCTION' AND quantity_delta < 0 AND reverses_event_id IS NULL) OR "
            "(event_kind = 'REVERSAL' AND quantity_delta > 0 AND reverses_event_id IS NOT NULL)",
            name="ck_production_disposition_events_kind_sign_consistency",
        ),
        CheckConstraint(
            "corrects_event_id IS NULL OR event_kind = 'REDUCTION'",
            name="ck_production_disposition_events_corrects_only_on_reduction",
        ),
        CheckConstraint(
            "reason_code <> 'other' OR (note IS NOT NULL AND btrim(note) <> '')",
            name="ck_production_disposition_events_other_requires_note",
        ),
        Index(
            "ux_production_disposition_events_reverses_once",
            "reverses_event_id",
            unique=True,
            postgresql_where=text("reverses_event_id IS NOT NULL"),
        ),
        Index(
            "ix_production_disposition_events_root_effective",
            "population_root_batch_carrier_assignment_id",
            "effective_time",
        ),
        Index(
            "ix_production_disposition_events_assignment",
            "batch_carrier_assignment_id",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "command_id"],
            [
                "production_disposition_commands.tenant_id", "production_disposition_commands.farm_id",
                "production_disposition_commands.id",
            ],
            name="fk_production_disposition_events_tenant_farm_command",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_carrier_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id", "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_production_disposition_events_tenant_farm_assignment",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "population_root_batch_carrier_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id", "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_production_disposition_events_tenant_farm_root",
        ),
        UniqueConstraint(
            "tenant_id", "farm_id", "id", name="uq_production_disposition_events_tenant_farm_id"
        ),
    )
