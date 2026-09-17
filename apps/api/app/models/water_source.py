import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.common import TimestampMixin

WATER_SOURCE_TYPES = ("bore", "municipal", "ro_treated", "storage_tank_feed", "other")


class WaterSource(TimestampMixin, Base):
    """PILOT-WATER-001A: the origin of a water/nutrient solution before it
    ever reaches a Reservoir -- water TOPOLOGY, deliberately never inserted
    into the physical Location hierarchy (Farm -> Greenhouse -> Zone ->
    Span -> Table/Gutter). A WaterSource may optionally be linked to a
    Reservoir via an effective-dated `WaterSourceReservoirLink` row; this
    table only carries the source's own identity."""

    __tablename__ = "water_sources"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('active', 'inactive')", name="ck_water_sources_status"),
        CheckConstraint(
            "source_type IN " + str(WATER_SOURCE_TYPES), name="ck_water_sources_source_type_allowed"
        ),
        Index("ux_water_sources_tenant_code_lower", "tenant_id", func.lower(code), unique=True),
        UniqueConstraint("tenant_id", "farm_id", "id", name="uq_water_sources_tenant_farm_id"),
    )
