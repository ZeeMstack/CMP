import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class NutrientMix(Base):
    """PILOT-WATER-001A section 14: immutable, insert-only record of what
    was ACTUALLY prepared in a Reservoir. `nutrient_recipe_version_id` is
    optional reference/guidance only (ticket rule 3/section 18) -- a Mix
    may exist with no recipe at all, and creating one never implies a
    Delivery happened (`WaterDeliveryEvent` is a separate fact). No hard
    delete, no update (`water_domain_reject_update`/
    `water_domain_reject_delete` triggers, this ticket's migration);
    correcting a mis-recorded Mix means recording a new one, not editing
    this row (see docs/domain/WATER_NUTRIENT_SYSTEM_MODEL.md)."""

    __tablename__ = "nutrient_mixes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    reservoir_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reservoirs.id"), nullable=False)
    nutrient_recipe_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("nutrient_recipe_versions.id"), nullable=True
    )
    prepared_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    target_volume: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    target_volume_uom_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("unit_of_measures.id"), nullable=True)
    actual_volume: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    actual_volume_uom_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("unit_of_measures.id"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "(target_volume IS NULL) = (target_volume_uom_id IS NULL)",
            name="ck_nutrient_mixes_target_volume_uom_pairing",
        ),
        CheckConstraint(
            "(actual_volume IS NULL) = (actual_volume_uom_id IS NULL)",
            name="ck_nutrient_mixes_actual_volume_uom_pairing",
        ),
        CheckConstraint("target_volume IS NULL OR target_volume > 0", name="ck_nutrient_mixes_target_volume_positive"),
        CheckConstraint("actual_volume IS NULL OR actual_volume > 0", name="ck_nutrient_mixes_actual_volume_positive"),
        Index("ux_nutrient_mixes_tenant_client_command_id", "tenant_id", "client_command_id", unique=True),
        UniqueConstraint("tenant_id", "farm_id", "id", name="uq_nutrient_mixes_tenant_farm_id"),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "reservoir_id"],
            ["reservoirs.tenant_id", "reservoirs.farm_id", "reservoirs.id"],
            name="fk_nutrient_mixes_tenant_farm_reservoir",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "nutrient_recipe_version_id"],
            ["nutrient_recipe_versions.tenant_id", "nutrient_recipe_versions.id"],
            name="fk_nutrient_mixes_tenant_recipe_version",
        ),
    )
