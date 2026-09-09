import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ProductionDispositionEventGrowCube(Base):
    """VINES-OPS-002: names exactly which specific Grow Cube(s) -- one living
    plant each -- a Production Disposition REDUCTION event actually removed
    from a `grow_bag` population root. `ProductionDispositionEvent.
    quantity_delta` alone (an anonymous count) is sufficient for Leafy's
    Production Cultivation Plate, but never for Vines: "one Grow Cube = one
    plant" requires truthful, unambiguous plant-level identity, never a bare
    count subtracted from a Gutter/Bag.

    Insert-only, one row per Grow Cube named by one RECORD command's own
    REDUCTION event -- never attached to a REVERSAL event directly. A
    REVERSAL restores every one of its target REDUCTION's named Grow Cube(s)
    to disposal eligibility automatically: every "already disposed" lookup
    walks REDUCTION -> its own REVERSAL (via `ProductionDispositionEvent.
    reverses_event_id`), never a static per-row status column, so correcting
    a mistaken loss (`production_disposition_service.correct_disposition`,
    already carrier-type-agnostic) transparently frees the Grow Cube for a
    later, truthful disposition with zero changes needed here."""

    __tablename__ = "production_disposition_event_grow_cubes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    production_disposition_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("production_disposition_events.id"), nullable=False
    )
    grow_cube_carrier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("carriers.id"), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "production_disposition_event_id", "grow_cube_carrier_id",
            name="ux_production_disposition_event_grow_cubes_event_carrier",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "production_disposition_event_id"],
            [
                "production_disposition_events.tenant_id", "production_disposition_events.farm_id",
                "production_disposition_events.id",
            ],
            name="fk_production_disposition_event_grow_cubes_tenant_farm_event",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "grow_cube_carrier_id"],
            ["carriers.tenant_id", "carriers.farm_id", "carriers.id"],
            name="fk_production_disposition_event_grow_cubes_tenant_farm_carrier",
        ),
    )
