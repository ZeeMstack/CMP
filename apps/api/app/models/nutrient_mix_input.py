import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class NutrientMixInput(Base):
    """PILOT-WATER-001A section 14: one ACTUAL ingredient actually added to
    a `NutrientMix` -- a fact, never copied automatically from the
    recipe version's target components (ticket rule 3/section 14: "Do not
    auto-copy target quantities as actual. User must record actual
    quantities."). Deliberately carries no Store-inventory-consumption
    column: recording this row NEVER decrements `InventoryExistenceLedger`
    or any other Store accounting table (ticket section 15) -- if a farm
    later wants to also record a real Store consumption transaction for the
    same physical usage, that is a separate, explicit command against the
    Inventory domain, never implied by this table. Immutable, insert-only
    (`water_domain_reject_update`/`water_domain_reject_delete` triggers)."""

    __tablename__ = "nutrient_mix_inputs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    nutrient_mix_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("nutrient_mixes.id"), nullable=False)
    inventory_item_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    component_label: Mapped[str] = mapped_column(String, nullable=False)
    actual_quantity: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    actual_quantity_uom_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("unit_of_measures.id"), nullable=False)
    sequence_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("length(btrim(component_label)) > 0", name="ck_nutrient_mix_inputs_label_not_blank"),
        CheckConstraint("actual_quantity > 0", name="ck_nutrient_mix_inputs_quantity_positive"),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "nutrient_mix_id"],
            ["nutrient_mixes.tenant_id", "nutrient_mixes.farm_id", "nutrient_mixes.id"],
            name="fk_nutrient_mix_inputs_tenant_farm_mix",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "inventory_item_id"],
            ["inventory_items.tenant_id", "inventory_items.id"],
            name="fk_nutrient_mix_inputs_tenant_inventory_item",
        ),
    )
