import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class HarvestSourceLineGrowBag(Base):
    """VINES-OPS-003: names exactly which Grow Bag(s) were currently living
    (at least one living Grow Cube) under a Vines-harvested Grow Gutter at
    the moment of harvest -- a point-in-time lineage snapshot only, never a
    weight split. The Gutter-level `HarvestSourceLine.harvested_weight_kg`
    is never attributable to one specific Bag (the ticket is explicit: do
    not fabricate per-bag harvested weights); this table instead answers
    "which Bags/Cubes were physically present and living here when this
    harvest was recorded" for backward traceability (Harvested Produce Lot
    -> Harvest Event -> Grow Gutter -> Grow Bag -> Grow Cube -> ... -> Seed
    Lot), independent of the aggregate weight. Insert-only, one row per Bag
    -- disposed/lost Grow Cubes (VINES-OPS-002) contribute no Bag here
    unless that same Bag still has at least one OTHER living Grow Cube."""

    __tablename__ = "harvest_source_line_grow_bags"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    harvest_source_line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("harvest_source_lines.id"), nullable=False
    )
    grow_bag_carrier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("carriers.id"), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "harvest_source_line_id", "grow_bag_carrier_id",
            name="ux_harvest_source_line_grow_bags_line_carrier",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "harvest_source_line_id"],
            [
                "harvest_source_lines.tenant_id", "harvest_source_lines.farm_id",
                "harvest_source_lines.id",
            ],
            name="fk_harvest_source_line_grow_bags_tenant_farm_line",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "grow_bag_carrier_id"],
            ["carriers.tenant_id", "carriers.farm_id", "carriers.id"],
            name="fk_harvest_source_line_grow_bags_tenant_farm_carrier",
        ),
    )
