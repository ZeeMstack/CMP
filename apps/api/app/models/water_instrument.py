import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.common import TimestampMixin


class WaterInstrument(TimestampMixin, Base):
    """PILOT-WATER-001A section 10: permanent instrument identity for a
    pH/EC/temperature/DO (or combination) meter. Deliberately references an
    existing `Asset` rather than duplicating a second physical-object
    catalog (CLAUDE.md: no second Asset catalog) -- code, name, serial/
    model metadata, and active/inactive status all already live on that
    Asset row; this table only adds the measurement-specific fact an Asset
    cannot safely hold: which metrics this instrument is capable of
    measuring. One `WaterInstrument` row per Asset (an Asset used as a
    water instrument has exactly one such role)."""

    __tablename__ = "water_instruments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    asset_id: Mapped[uuid.UUID] = mapped_column(nullable=False)

    supports_ph: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    supports_ec: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    supports_solution_temperature: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    supports_dissolved_oxygen: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    status: Mapped[str] = mapped_column(String, nullable=False, default="active")

    __table_args__ = (
        CheckConstraint("status IN ('active', 'inactive')", name="ck_water_instruments_status"),
        CheckConstraint(
            "supports_ph OR supports_ec OR supports_solution_temperature OR supports_dissolved_oxygen",
            name="ck_water_instruments_at_least_one_capability",
        ),
        UniqueConstraint("tenant_id", "asset_id", name="ux_water_instruments_tenant_asset"),
        UniqueConstraint("tenant_id", "farm_id", "id", name="uq_water_instruments_tenant_farm_id"),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "asset_id"],
            ["assets.tenant_id", "assets.farm_id", "assets.id"],
            name="fk_water_instruments_tenant_farm_asset",
        ),
    )
