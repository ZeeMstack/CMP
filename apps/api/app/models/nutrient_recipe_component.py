import uuid
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class NutrientRecipeComponent(Base):
    """PILOT-WATER-001A section 13: one target ingredient line on a DRAFT
    `NutrientRecipeVersion`. `component_label` is always populated (a
    display name -- "Stock A", "Calcium Nitrate", "Source Water") even when
    `inventory_item_id` is set, so a component that has no InventoryItem
    counterpart (e.g. "source water" itself, which is never a Store
    material) is still nameable; `inventory_item_id` is the preferred,
    optional link to the existing InventoryItem catalog (CLAUDE.md: no
    second fertilizer catalog).

    `target_quantity` is a TARGET only (ticket rule 13/18) -- recording a
    component here never touches Store existence; only the service layer's
    guard against inserting/editing a component once the owning version has
    left `draft` protects this table's content, mirroring how
    `growing_protocol_service` enforces "no in-place edit once published"
    at the service layer rather than by FK/trigger."""

    __tablename__ = "nutrient_recipe_components"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    nutrient_recipe_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("nutrient_recipe_versions.id"), nullable=False
    )
    inventory_item_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    component_label: Mapped[str] = mapped_column(String, nullable=False)
    target_quantity: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    target_quantity_uom_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("unit_of_measures.id"), nullable=False)
    basis_volume: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    basis_volume_uom_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("unit_of_measures.id"), nullable=True)
    sequence_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("length(btrim(component_label)) > 0", name="ck_nutrient_recipe_components_label_not_blank"),
        CheckConstraint("target_quantity > 0", name="ck_nutrient_recipe_components_quantity_positive"),
        CheckConstraint(
            "(basis_volume IS NULL) = (basis_volume_uom_id IS NULL)",
            name="ck_nutrient_recipe_components_basis_pairing",
        ),
        CheckConstraint(
            "basis_volume IS NULL OR basis_volume > 0", name="ck_nutrient_recipe_components_basis_positive"
        ),
        UniqueConstraint("tenant_id", "id", name="uq_nutrient_recipe_components_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "nutrient_recipe_version_id"],
            ["nutrient_recipe_versions.tenant_id", "nutrient_recipe_versions.id"],
            name="fk_nutrient_recipe_components_tenant_version",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "inventory_item_id"],
            ["inventory_items.tenant_id", "inventory_items.id"],
            name="fk_nutrient_recipe_components_tenant_inventory_item",
        ),
    )
