import uuid
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.common import TimestampMixin

RESERVOIR_TYPES = ("source_tank", "nutrient_reservoir", "return_reservoir", "mixing_reservoir", "other")


class Reservoir(Base, TimestampMixin):
    """PILOT-WATER-001A: a physical body/container of solution -- water
    TOPOLOGY, never a Location. `location_id` is optional (ticket section
    3): a Reservoir's place in the water network is proven by its
    topology links, not by where it physically sits, so a farm that has no
    reason to record that placement is not forced to invent one.
    `linked_asset_id` is likewise optional -- it never duplicates identity
    fields an existing Asset already owns (CLAUDE.md: no second Asset
    catalog); it only cross-references one when a real physical Asset
    already represents the tank."""

    __tablename__ = "reservoirs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    reservoir_type: Mapped[str] = mapped_column(String, nullable=False)
    nominal_capacity: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    nominal_capacity_uom_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("unit_of_measures.id"), nullable=True
    )
    linked_asset_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    location_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('active', 'inactive')", name="ck_reservoirs_status"),
        CheckConstraint(
            "reservoir_type IN " + str(RESERVOIR_TYPES), name="ck_reservoirs_reservoir_type_allowed"
        ),
        CheckConstraint(
            "(nominal_capacity IS NULL) = (nominal_capacity_uom_id IS NULL)",
            name="ck_reservoirs_capacity_uom_pairing",
        ),
        CheckConstraint(
            "nominal_capacity IS NULL OR nominal_capacity > 0", name="ck_reservoirs_capacity_positive"
        ),
        Index("ux_reservoirs_tenant_code_lower", "tenant_id", func.lower(code), unique=True),
        UniqueConstraint("tenant_id", "farm_id", "id", name="uq_reservoirs_tenant_farm_id"),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "linked_asset_id"],
            ["assets.tenant_id", "assets.farm_id", "assets.id"],
            name="fk_reservoirs_tenant_farm_linked_asset",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "location_id"],
            ["locations.tenant_id", "locations.farm_id", "locations.id"],
            name="fk_reservoirs_tenant_farm_location",
        ),
    )
