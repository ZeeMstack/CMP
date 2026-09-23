import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class WaterDeliveryEndEvent(Base):
    """UX-OPS-001D0 (N07): the append-only closure record that ends an
    ongoing `WaterDeliveryEvent` (one created with `effective_end = NULL`)
    without ever updating or deleting the original delivery row. Records
    only the operator-approved closure facts -- `effective_end` and an
    optional `note` -- never a final volume, UOM, mix, reservoir, circuit,
    or start time.

    Exactly one end event may close a delivery
    (`ux_water_delivery_end_events_delivery`). The composite FK pins the
    end event to its delivery's own tenant and farm. A BEFORE INSERT
    trigger (`enforce_water_delivery_end_event_parent`) rejects ending a
    delivery that was created with an end, and an end before the
    delivery's start. Immutable, insert-only (`reject_append_only_mutation`
    UPDATE/DELETE triggers). Reads resolve a delivery's domain end as
    `original effective_end ?? end-event effective_end ?? NULL`
    (`reservoir_operations_service.ResolvedWaterDeliveryEvent`)."""

    __tablename__ = "water_delivery_end_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    water_delivery_event_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    effective_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        Index("ux_water_delivery_end_events_delivery", "water_delivery_event_id", unique=True),
        Index(
            "ux_water_delivery_end_events_tenant_client_command_id", "tenant_id", "client_command_id", unique=True
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "water_delivery_event_id"],
            ["water_delivery_events.tenant_id", "water_delivery_events.farm_id", "water_delivery_events.id"],
            name="fk_water_delivery_end_events_tenant_farm_delivery",
        ),
    )
