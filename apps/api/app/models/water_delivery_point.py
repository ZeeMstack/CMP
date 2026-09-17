import uuid

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.common import TimestampMixin


class WaterDeliveryPoint(TimestampMixin, Base):
    """PILOT-WATER-001A section 6: links the water network to a real farm
    physical context. `location_id` is mandatory and always a real,
    existing Location id (never a display path string) -- it may be a
    Table/Gutter leaf or a larger ancestor (e.g. a whole Zone) when that is
    how the actual plumbing serves it (ticket section 6: "a circuit may
    serve ... a larger Location ancestor where that is how the actual
    plumbing works"). Which IrrigationCircuit currently serves this point
    is tracked separately, effective-dated, in
    `CircuitDeliveryPointLink`."""

    __tablename__ = "water_delivery_points"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    location_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('active', 'inactive')", name="ck_water_delivery_points_status"),
        Index("ux_water_delivery_points_tenant_code_lower", "tenant_id", func.lower(code), unique=True),
        UniqueConstraint("tenant_id", "farm_id", "id", name="uq_water_delivery_points_tenant_farm_id"),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "location_id"],
            ["locations.tenant_id", "locations.farm_id", "locations.id"],
            name="fk_water_delivery_points_tenant_farm_location",
        ),
    )
