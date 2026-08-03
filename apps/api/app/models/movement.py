import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

COMMAND_TYPES = ("movement",)


class Movement(Base):
    """Immutable movement record. Source is server-derived from the
    occupant's current active occupancy at execution time — never accepted
    from the API. Immutability (no UPDATE/DELETE) is enforced by a
    PostgreSQL trigger, since CLAUDE.md rule 7 forbids rewriting history."""

    __tablename__ = "movements"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)

    occupant_asset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("assets.id"), nullable=True)
    occupant_carrier_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("carriers.id"), nullable=True)

    source_location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id"), nullable=True)
    source_asset_position_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("asset_positions.id"), nullable=True
    )
    destination_location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("locations.id"), nullable=True
    )
    destination_asset_position_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("asset_positions.id"), nullable=True
    )

    command_type: Mapped[str] = mapped_column(String, nullable=False, default="movement")
    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)

    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "(occupant_asset_id IS NOT NULL)::int + (occupant_carrier_id IS NOT NULL)::int = 1",
            name="ck_movements_occupant_xor",
        ),
        CheckConstraint(
            "NOT (source_location_id IS NOT NULL AND source_asset_position_id IS NOT NULL)",
            name="ck_movements_source_at_most_one",
        ),
        CheckConstraint(
            "NOT (destination_location_id IS NOT NULL AND destination_asset_position_id IS NOT NULL)",
            name="ck_movements_destination_at_most_one",
        ),
        CheckConstraint(
            "source_location_id IS NOT NULL OR source_asset_position_id IS NOT NULL "
            "OR destination_location_id IS NOT NULL OR destination_asset_position_id IS NOT NULL",
            name="ck_movements_source_or_destination_present",
        ),
        CheckConstraint(
            "NOT (source_location_id IS NOT NULL AND source_location_id = destination_location_id)",
            name="ck_movements_source_destination_location_distinct",
        ),
        CheckConstraint(
            "NOT (source_asset_position_id IS NOT NULL AND source_asset_position_id = destination_asset_position_id)",
            name="ck_movements_source_destination_position_distinct",
        ),
        CheckConstraint("command_type IN ('movement')", name="ck_movements_command_type_allowed"),
        Index(
            "ux_movements_tenant_command_client_id",
            "tenant_id",
            "command_type",
            "client_command_id",
            unique=True,
        ),
    )
