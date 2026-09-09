import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class HarvestSourceLine(Base):
    """Immutable, insert-only per-source line of a harvest event.
    `batch_carrier_assignment_id` is deliberately **not** globally unique —
    the same active carrier assignment may be harvested again in a later,
    separate event; only one appearance per event is enforced (CMP-013).

    VINES-OPS-003: a source line now has exactly ONE of two anchor shapes --
    the original (`batch_carrier_assignment_id` + `carrier_id`, a single
    biological source Carrier, e.g. a Leafy Production Cultivation Plate)
    OR the new `source_location_id` (a Location -- e.g. a Vines Grow
    Gutter, whose harvested weight is never attributable to one single
    Carrier since it aggregates several Grow Bags at once). Never both,
    never neither -- `ck_harvest_source_lines_exactly_one_anchor`. A
    location-anchored line's underlying Grow Bag lineage (never a weight
    split -- see the ticket's own "do not fabricate per-bag weights") is
    recorded separately in `HarvestSourceLineGrowBag`."""

    __tablename__ = "harvest_source_lines"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    harvest_event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("harvest_events.id"), nullable=False)
    batch_carrier_assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("batch_carrier_assignments.id"), nullable=True
    )
    carrier_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("carriers.id"), nullable=True)
    # VINES-OPS-003
    source_location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id"), nullable=True)
    harvested_weight_kg: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    whole_unit_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # NUMERIC is deliberately unscoped, not NUMERIC(14,3): PostgreSQL
        # silently rounds excess scale to a declared scale on insert, which
        # would defeat "reject rather than round". This CHECK reproduces the
        # intended NUMERIC(14,3) envelope explicitly instead.
        CheckConstraint(
            "harvested_weight_kg > 0 AND harvested_weight_kg = trunc(harvested_weight_kg, 3) "
            "AND harvested_weight_kg < 100000000000",
            name="ck_harvest_source_lines_weight_envelope",
        ),
        CheckConstraint(
            "whole_unit_count IS NULL OR whole_unit_count > 0",
            name="ck_harvest_source_lines_count_positive",
        ),
        # VINES-OPS-003: exactly one anchor shape -- the original
        # (assignment + carrier, always together) XOR the new
        # (source_location_id alone).
        CheckConstraint(
            "(batch_carrier_assignment_id IS NOT NULL AND carrier_id IS NOT NULL AND source_location_id IS NULL) "
            "OR (batch_carrier_assignment_id IS NULL AND carrier_id IS NULL AND source_location_id IS NOT NULL)",
            name="ck_harvest_source_lines_exactly_one_anchor",
        ),
        UniqueConstraint(
            "harvest_event_id", "batch_carrier_assignment_id",
            name="ux_harvest_source_lines_event_assignment",
        ),
        UniqueConstraint(
            "harvest_event_id", "source_location_id",
            name="ux_harvest_source_lines_event_location",
        ),
        # VINES-OPS-003: the new `harvest_source_line_grow_bags` child table
        # needs a plain (tenant_id, farm_id, id) unique target for its own
        # composite FK -- the existing 4-column one below includes
        # harvest_event_id, which that child table doesn't carry.
        UniqueConstraint(
            "tenant_id", "farm_id", "id", name="uq_harvest_source_lines_tenant_farm_id",
        ),
        UniqueConstraint(
            "tenant_id", "farm_id", "harvest_event_id", "id",
            name="uq_harvest_source_lines_tenant_farm_event_id",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "harvest_event_id"],
            ["harvest_events.tenant_id", "harvest_events.farm_id", "harvest_events.id"],
            name="fk_harvest_source_lines_tenant_farm_event",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_carrier_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id", "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_harvest_source_lines_tenant_farm_assignment",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "carrier_id"],
            ["carriers.tenant_id", "carriers.farm_id", "carriers.id"],
            name="fk_harvest_source_lines_tenant_farm_carrier",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "source_location_id"],
            ["locations.tenant_id", "locations.farm_id", "locations.id"],
            name="fk_harvest_source_lines_tenant_farm_location",
        ),
    )
