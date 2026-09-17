import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

RESERVOIR_EVENT_TYPES = (
    "NUTRIENT_ADDITION",
    "WATER_TOP_UP",
    "PH_ADJUSTMENT",
    "SOLUTION_REPLACEMENT",
    "FLUSH",
    "DRAIN",
    "OTHER",
)


class ReservoirEvent(Base):
    """PILOT-WATER-001A section 16: an actual operating event against a
    Reservoir. Records what was done (and, where applicable, how much of
    what) -- it never records or infers the resulting EC/pH (ticket rule 4/
    section 16: "A Measurement must record the observed result"); a
    `WaterMeasurement` taken afterward is a separate, independent fact.
    Never recommends a dosage -- this table has no target/recommended
    quantity column at all, only an ACTUAL one. Immutable, insert-only
    (`water_domain_reject_update`/`water_domain_reject_delete` triggers)."""

    __tablename__ = "reservoir_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    reservoir_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reservoirs.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    operator_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    quantity_uom_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("unit_of_measures.id"), nullable=True)
    inventory_item_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        CheckConstraint("event_type IN " + str(RESERVOIR_EVENT_TYPES), name="ck_reservoir_events_event_type_allowed"),
        CheckConstraint(
            "(quantity IS NULL) = (quantity_uom_id IS NULL)", name="ck_reservoir_events_quantity_uom_pairing"
        ),
        CheckConstraint("quantity IS NULL OR quantity > 0", name="ck_reservoir_events_quantity_positive"),
        Index("ux_reservoir_events_tenant_client_command_id", "tenant_id", "client_command_id", unique=True),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "reservoir_id"],
            ["reservoirs.tenant_id", "reservoirs.farm_id", "reservoirs.id"],
            name="fk_reservoir_events_tenant_farm_reservoir",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "inventory_item_id"],
            ["inventory_items.tenant_id", "inventory_items.id"],
            name="fk_reservoir_events_tenant_inventory_item",
        ),
    )
