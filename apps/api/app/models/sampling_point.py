import uuid

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.common import TimestampMixin

SAMPLING_POINT_TYPES = ("source", "reservoir", "circuit_supply", "delivery", "drain_return", "other")


class SamplingPoint(TimestampMixin, Base):
    """PILOT-WATER-001A section 8: where a measurement is physically taken.
    Never free-floating -- exactly one of the five typed anchor columns is
    populated, and it must match `point_type` (mirrors `QrIdentifier`'s own
    "exactly one of N, matching a discriminator" shape). `point_type =
    'other'` anchors to none of the five (an explicitly acknowledged
    residual case, e.g. a farm-wide catch-all point) -- see the CHECK
    constraint below."""

    __tablename__ = "sampling_points"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    point_type: Mapped[str] = mapped_column(String, nullable=False)

    water_source_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    reservoir_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    irrigation_circuit_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    water_delivery_point_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    water_return_point_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('active', 'inactive')", name="ck_sampling_points_status"),
        CheckConstraint(
            "point_type IN " + str(SAMPLING_POINT_TYPES), name="ck_sampling_points_point_type_allowed"
        ),
        CheckConstraint(
            "(CASE WHEN point_type = 'source' THEN water_source_id IS NOT NULL ELSE water_source_id IS NULL END) AND "
            "(CASE WHEN point_type = 'reservoir' THEN reservoir_id IS NOT NULL ELSE reservoir_id IS NULL END) AND "
            "(CASE WHEN point_type = 'circuit_supply' THEN irrigation_circuit_id IS NOT NULL "
            "ELSE irrigation_circuit_id IS NULL END) AND "
            "(CASE WHEN point_type = 'delivery' THEN water_delivery_point_id IS NOT NULL "
            "ELSE water_delivery_point_id IS NULL END) AND "
            "(CASE WHEN point_type = 'drain_return' THEN water_return_point_id IS NOT NULL "
            "ELSE water_return_point_id IS NULL END)",
            name="ck_sampling_points_anchor_matches_type",
        ),
        Index("ux_sampling_points_tenant_code_lower", "tenant_id", func.lower(code), unique=True),
        UniqueConstraint("tenant_id", "farm_id", "id", name="uq_sampling_points_tenant_farm_id"),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "water_source_id"],
            ["water_sources.tenant_id", "water_sources.farm_id", "water_sources.id"],
            name="fk_sampling_points_tenant_farm_source",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "reservoir_id"],
            ["reservoirs.tenant_id", "reservoirs.farm_id", "reservoirs.id"],
            name="fk_sampling_points_tenant_farm_reservoir",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "irrigation_circuit_id"],
            ["irrigation_circuits.tenant_id", "irrigation_circuits.farm_id", "irrigation_circuits.id"],
            name="fk_sampling_points_tenant_farm_circuit",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "water_delivery_point_id"],
            ["water_delivery_points.tenant_id", "water_delivery_points.farm_id", "water_delivery_points.id"],
            name="fk_sampling_points_tenant_farm_delivery_point",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "water_return_point_id"],
            ["water_return_points.tenant_id", "water_return_points.farm_id", "water_return_points.id"],
            name="fk_sampling_points_tenant_farm_return_point",
        ),
    )
