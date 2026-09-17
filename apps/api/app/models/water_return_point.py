import uuid

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.common import TimestampMixin


class WaterReturnPoint(TimestampMixin, Base):
    """PILOT-WATER-001A section 7: drainage/return point for a
    recirculating OR a drain-to-waste system. `location_id` is optional --
    a drain-to-waste point may be a simple identity with no Return
    Reservoir link at all (ticket: "drain-to-waste ... return reservoir may
    be null / absent"); whether it recirculates is a fact of whether an
    active `ReturnPointReservoirLink` row exists for it, never a stored
    flag on this row (avoids two sources of truth)."""

    __tablename__ = "water_return_points"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    location_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('active', 'inactive')", name="ck_water_return_points_status"),
        Index("ux_water_return_points_tenant_code_lower", "tenant_id", func.lower(code), unique=True),
        UniqueConstraint("tenant_id", "farm_id", "id", name="uq_water_return_points_tenant_farm_id"),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "location_id"],
            ["locations.tenant_id", "locations.farm_id", "locations.id"],
            name="fk_water_return_points_tenant_farm_location",
        ),
    )
