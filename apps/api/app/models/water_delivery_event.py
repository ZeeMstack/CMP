import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class WaterDeliveryEvent(Base):
    """PILOT-WATER-001A section 17: an actual delivery/operating interval
    from a Reservoir through an IrrigationCircuit -- separate from both
    `NutrientRecipeVersion` (approved) and `NutrientMix` (actually
    prepared): creating a Mix never implies a Delivery happened (ticket
    rule 3/section 18), so `nutrient_mix_id` is optional context, not a
    required parent. `delivered_volume` is optional -- "Delivery occurred
    from X to Y" is a valid, complete fact on its own where a farm cannot
    yet measure volume (ticket section 17); a continuously-circulating DWC
    circuit is represented as one open-or-closed operating interval
    (`effective_start`/`effective_end`) rather than fabricated discrete
    pulses. Immutable, insert-only (`water_domain_reject_update`/
    `water_domain_reject_delete` triggers)."""

    __tablename__ = "water_delivery_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    reservoir_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reservoirs.id"), nullable=False)
    irrigation_circuit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("irrigation_circuits.id"), nullable=False)
    effective_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_volume: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    delivered_volume_uom_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("unit_of_measures.id"), nullable=True
    )
    recorded_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    nutrient_mix_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "effective_end IS NULL OR effective_end >= effective_start",
            name="ck_water_delivery_events_end_after_start",
        ),
        CheckConstraint(
            "(delivered_volume IS NULL) = (delivered_volume_uom_id IS NULL)",
            name="ck_water_delivery_events_volume_uom_pairing",
        ),
        CheckConstraint(
            "delivered_volume IS NULL OR delivered_volume > 0", name="ck_water_delivery_events_volume_positive"
        ),
        Index("ux_water_delivery_events_tenant_client_command_id", "tenant_id", "client_command_id", unique=True),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "reservoir_id"],
            ["reservoirs.tenant_id", "reservoirs.farm_id", "reservoirs.id"],
            name="fk_water_delivery_events_tenant_farm_reservoir",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "irrigation_circuit_id"],
            ["irrigation_circuits.tenant_id", "irrigation_circuits.farm_id", "irrigation_circuits.id"],
            name="fk_water_delivery_events_tenant_farm_circuit",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "nutrient_mix_id"],
            ["nutrient_mixes.tenant_id", "nutrient_mixes.farm_id", "nutrient_mixes.id"],
            name="fk_water_delivery_events_tenant_farm_mix",
        ),
    )
