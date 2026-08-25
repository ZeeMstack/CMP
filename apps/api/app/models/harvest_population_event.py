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

EVENT_KINDS = ("CONSUMPTION", "REVERSAL")


class HarvestPopulationEvent(Base):
    """HARVEST-OPS-001: immutable, insert-only biological fact -- the sibling
    ledger to `ProductionDispositionEvent`, for the one signed-delta channel
    a Leafy Production Harvest contributes to a population lineage's
    authoritative living population. A CONSUMPTION (`quantity_delta < 0`) is
    the biological removal driven by a Harvest fact (either the ORIGINAL
    `HarvestSourceLine.whole_unit_count`, or a correction's own replacement
    count) -- never created for a generic, non-Leafy Harvest source (no
    fabricated roots: see `HarvestSourceLine`'s own docstring for why it
    carries no population-root column itself). A REVERSAL
    (`quantity_delta > 0`) is the exact negation of one specific, named
    prior CONSUMPTION (`reverses_event_id`) -- a correction's own biological
    consequence, never resurrection. `population_root_batch_carrier_
    assignment_id` is server-derived and DB-validated against the
    referenced BCA's own stored root, exactly like `ProductionDispositionEvent`
    -- authoritative living population is one flat, non-recursive SUM across
    BOTH this table and `production_disposition_events`, grouped by shared
    root. See `harvest_service.py` and the migration that introduces this
    table for the full worked A/B/C-style restoration proof and the
    combined chronological-balance invariant."""

    __tablename__ = "harvest_population_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    population_root_batch_carrier_assignment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batch_carrier_assignments.id"), nullable=False
    )
    batch_carrier_assignment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batch_carrier_assignments.id"), nullable=False
    )
    event_kind: Mapped[str] = mapped_column(String, nullable=False)
    quantity_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    reverses_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("harvest_population_events.id"), nullable=True
    )
    # Typed origin -- exactly one populated for a CONSUMPTION (the ORIGINAL
    # HarvestSourceLine's own first-ever biological fact, or a correction's
    # replacement count), both NULL for a REVERSAL (whose identity comes
    # from reverses_event_id alone, mirroring the REVERSAL/REDUCTION shape
    # already proven twice in this codebase).
    original_harvest_source_line_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("harvest_source_lines.id"), nullable=True
    )
    harvest_source_line_correction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("harvest_source_line_corrections.id"), nullable=True
    )

    __table_args__ = (
        CheckConstraint("event_kind IN ('CONSUMPTION', 'REVERSAL')", name="ck_harvest_population_events_kind"),
        CheckConstraint("quantity_delta <> 0", name="ck_harvest_population_events_delta_nonzero"),
        CheckConstraint(
            "(event_kind = 'CONSUMPTION' AND quantity_delta < 0 AND reverses_event_id IS NULL) OR "
            "(event_kind = 'REVERSAL' AND quantity_delta > 0 AND reverses_event_id IS NOT NULL)",
            name="ck_harvest_population_events_kind_sign_consistency",
        ),
        # Exactly one typed origin for a CONSUMPTION; neither for a REVERSAL.
        CheckConstraint(
            "(event_kind = 'CONSUMPTION' AND "
            "(CASE WHEN original_harvest_source_line_id IS NOT NULL THEN 1 ELSE 0 END "
            "+ CASE WHEN harvest_source_line_correction_id IS NOT NULL THEN 1 ELSE 0 END) = 1) "
            "OR (event_kind = 'REVERSAL' AND original_harvest_source_line_id IS NULL "
            "AND harvest_source_line_correction_id IS NULL)",
            name="ck_harvest_population_events_typed_origin_shape",
        ),
        Index(
            "ux_harvest_population_events_reverses_once",
            "reverses_event_id",
            unique=True,
            postgresql_where=text("reverses_event_id IS NOT NULL"),
        ),
        # At most one ORIGINAL CONSUMPTION per original HarvestSourceLine.
        Index(
            "ux_harvest_population_events_original_line_once",
            "original_harvest_source_line_id",
            unique=True,
            postgresql_where=text("original_harvest_source_line_id IS NOT NULL"),
        ),
        # At most one replacement CONSUMPTION per correction.
        Index(
            "ux_harvest_population_events_correction_once",
            "harvest_source_line_correction_id",
            unique=True,
            postgresql_where=text("harvest_source_line_correction_id IS NOT NULL"),
        ),
        Index(
            "ix_harvest_population_events_root_effective",
            "population_root_batch_carrier_assignment_id",
            "effective_time",
        ),
        Index(
            "ix_harvest_population_events_assignment",
            "batch_carrier_assignment_id",
        ),
        UniqueConstraint(
            "tenant_id", "farm_id", "id", name="uq_harvest_population_events_tenant_farm_id"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_carrier_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id", "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_harvest_population_events_tenant_farm_assignment",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "population_root_batch_carrier_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id", "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_harvest_population_events_tenant_farm_root",
        ),
    )
