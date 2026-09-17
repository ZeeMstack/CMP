import uuid

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.common import TimestampMixin


class NutrientRecipe(TimestampMixin, Base):
    """PILOT-WATER-001A section 12: the versioned identity of one approved
    nutrient program (e.g. "Leafy Greens Standard EC 1.8"), scoped by the
    existing Crop/Variety/ProductionSystem catalogs -- never a new crop
    catalog (CLAUDE.md rule 1). Unlike `GrowingProtocol`, applicability is
    fully optional: a recipe is frequently crop-agnostic (a baseline RO/
    source-water program used across many crops), so `crop_id` is nullable
    here even though `GrowingProtocol.crop_id` is not. All approved
    agronomic CONTENT (target EC/pH, components) lives on
    `NutrientRecipeVersion`; this row is only the versioned identity plus
    optional applicability."""

    __tablename__ = "nutrient_recipes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    crop_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("crops.id"), nullable=True)
    variety_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("varieties.id"), nullable=True)
    production_system_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("production_systems.id"), nullable=True
    )
    code: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)

    __table_args__ = (
        CheckConstraint("status IN ('active', 'inactive')", name="ck_nutrient_recipes_status"),
        CheckConstraint(
            "crop_id IS NOT NULL OR variety_id IS NULL", name="ck_nutrient_recipes_variety_requires_crop"
        ),
        Index("ux_nutrient_recipes_tenant_code_lower", "tenant_id", func.lower(code), unique=True),
        UniqueConstraint("tenant_id", "id", name="uq_nutrient_recipes_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "crop_id"], ["crops.tenant_id", "crops.id"], name="fk_nutrient_recipes_tenant_crop"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "crop_id", "variety_id"],
            ["varieties.tenant_id", "varieties.crop_id", "varieties.id"],
            name="fk_nutrient_recipes_tenant_crop_variety",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "production_system_id"],
            ["production_systems.tenant_id", "production_systems.id"],
            name="fk_nutrient_recipes_tenant_production_system",
        ),
    )
