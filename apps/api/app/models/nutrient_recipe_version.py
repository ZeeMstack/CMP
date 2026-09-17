import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

RECIPE_VERSION_STATES = ("draft", "active", "retired")


class NutrientRecipeVersion(Base):
    """PILOT-WATER-001A section 12: the versioned, immutable-once-ACTIVE
    approved content of one `NutrientRecipe`. Lifecycle is `draft -> active
    -> retired`, mirroring `GrowingProtocolVersion`'s own identical shape
    (including its per-command idempotency-column convention: a separate
    client_command_id/fingerprint pair per lifecycle transition). To change
    ACTIVE content, a caller creates a NEXT version -- there is no in-place
    edit path once a version leaves DRAFT. `target_ec`/`target_ph` are
    APPROVED TARGETS only (ticket rule 4 / section 18): never overwritten
    by, and never inferred from, an actual `WaterMeasurement` or
    `NutrientMix`. `reason` is required, non-blank text, matching
    `GrowingProtocolVersion.reason`."""

    __tablename__ = "nutrient_recipe_versions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    nutrient_recipe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("nutrient_recipes.id"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False, default="draft")
    author_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    target_ec: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    target_ph: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    activation_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    activation_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)
    retirement_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    retirement_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "state IN ('" + "', '".join(RECIPE_VERSION_STATES) + "')", name="ck_nutrient_recipe_versions_state"
        ),
        CheckConstraint("version_number > 0", name="ck_nutrient_recipe_versions_number_positive"),
        CheckConstraint("length(btrim(reason)) > 0", name="ck_nutrient_recipe_versions_reason_not_blank"),
        CheckConstraint("target_ec IS NULL OR target_ec > 0", name="ck_nutrient_recipe_versions_target_ec_positive"),
        CheckConstraint(
            "target_ph IS NULL OR (target_ph >= 0 AND target_ph <= 14)",
            name="ck_nutrient_recipe_versions_target_ph_range",
        ),
        CheckConstraint(
            "(state = 'draft' AND activated_at IS NULL AND retired_at IS NULL "
            " AND activation_client_command_id IS NULL AND activation_request_fingerprint IS NULL "
            " AND retirement_client_command_id IS NULL AND retirement_request_fingerprint IS NULL) OR "
            "(state = 'active' AND activated_at IS NOT NULL AND retired_at IS NULL "
            " AND activation_client_command_id IS NOT NULL AND activation_request_fingerprint IS NOT NULL "
            " AND retirement_client_command_id IS NULL AND retirement_request_fingerprint IS NULL) OR "
            "(state = 'retired' AND activated_at IS NOT NULL AND retired_at IS NOT NULL "
            " AND activation_client_command_id IS NOT NULL AND activation_request_fingerprint IS NOT NULL)",
            name="ck_nutrient_recipe_versions_state_shape",
        ),
        CheckConstraint(
            "retired_at IS NULL OR retired_at >= activated_at",
            name="ck_nutrient_recipe_versions_retired_after_activated",
        ),
        UniqueConstraint(
            "nutrient_recipe_id", "version_number", name="uq_nutrient_recipe_versions_recipe_number"
        ),
        UniqueConstraint("tenant_id", "id", name="uq_nutrient_recipe_versions_tenant_id"),
        UniqueConstraint(
            "tenant_id", "nutrient_recipe_id", "id", name="uq_nutrient_recipe_versions_tenant_recipe_id"
        ),
        Index(
            "ux_nutrient_recipe_versions_active_once", "nutrient_recipe_id", unique=True,
            postgresql_where=text("state = 'active'"),
        ),
        Index(
            "ux_nutrient_recipe_versions_tenant_client_command_id", "tenant_id", "client_command_id", unique=True
        ),
        Index(
            "ux_nutrient_recipe_versions_tenant_activation_command", "tenant_id", "activation_client_command_id",
            unique=True, postgresql_where=text("activation_client_command_id IS NOT NULL"),
        ),
        Index(
            "ux_nutrient_recipe_versions_tenant_retirement_command", "tenant_id", "retirement_client_command_id",
            unique=True, postgresql_where=text("retirement_client_command_id IS NOT NULL"),
        ),
        ForeignKeyConstraint(
            ["tenant_id", "nutrient_recipe_id"],
            ["nutrient_recipes.tenant_id", "nutrient_recipes.id"],
            name="fk_nutrient_recipe_versions_tenant_recipe",
        ),
    )
