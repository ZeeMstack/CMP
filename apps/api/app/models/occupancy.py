import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Occupancy(Base):
    """Active + historical occupancy of an asset/carrier at a location/asset
    position. Rows are inserted active-only and may be updated exactly once
    (to close). Cross-row integrity (occupant/target validity, compatibility,
    opening/closing movement matching) is enforced by PostgreSQL triggers in
    the migration — a CHECK constraint cannot join to other tables."""

    __tablename__ = "occupancies"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)

    occupant_asset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("assets.id"), nullable=True)
    occupant_carrier_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("carriers.id"), nullable=True)

    target_location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id"), nullable=True)
    target_asset_position_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("asset_positions.id"), nullable=True
    )

    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    opened_by_movement_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("movements.id"), nullable=False)
    closed_by_movement_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("movements.id"), nullable=True
    )

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "(occupant_asset_id IS NOT NULL)::int + (occupant_carrier_id IS NOT NULL)::int = 1",
            name="ck_occupancies_occupant_xor",
        ),
        CheckConstraint(
            "(target_location_id IS NOT NULL)::int + (target_asset_position_id IS NOT NULL)::int = 1",
            name="ck_occupancies_target_xor",
        ),
        CheckConstraint(
            "end_time IS NULL OR end_time >= effective_time", name="ck_occupancies_end_after_effective"
        ),
        CheckConstraint(
            "(end_time IS NULL) = (closed_by_movement_id IS NULL)",
            name="ck_occupancies_closure_fields_together",
        ),
        Index(
            "ux_occupancies_active_occupant_asset",
            "occupant_asset_id",
            unique=True,
            postgresql_where=text("end_time IS NULL AND occupant_asset_id IS NOT NULL"),
        ),
        Index(
            "ux_occupancies_active_occupant_carrier",
            "occupant_carrier_id",
            unique=True,
            postgresql_where=text("end_time IS NULL AND occupant_carrier_id IS NOT NULL"),
        ),
        Index(
            "ux_occupancies_active_target_location",
            "target_location_id",
            unique=True,
            postgresql_where=text("end_time IS NULL AND target_location_id IS NOT NULL"),
        ),
        Index(
            "ux_occupancies_active_target_position",
            "target_asset_position_id",
            unique=True,
            postgresql_where=text("end_time IS NULL AND target_asset_position_id IS NOT NULL"),
        ),
    )
