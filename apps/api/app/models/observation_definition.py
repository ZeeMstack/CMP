import uuid

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.common import TimestampMixin

VALUE_TYPES = ("integer", "decimal", "percentage", "boolean", "text")
TARGET_SCOPES = ("crop_batch", "carrier_assignment", "either")
DEFINITION_STATUSES = ("active", "inactive")


class ObservationDefinition(TimestampMixin, Base):
    """Tenant-owned, reusable structured observation metric. Semantic fields
    (everything but `status`) are immutable once created — enforced by a DB
    trigger — so production observation history never rests on a
    retroactively redefined metric (CMP-010)."""

    __tablename__ = "observation_definitions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    value_type: Mapped[str] = mapped_column(String, nullable=False)
    unit: Mapped[str | None] = mapped_column(String, nullable=True)
    target_scope: Mapped[str] = mapped_column(String, nullable=False)
    min_value: Mapped[object | None] = mapped_column(Numeric, nullable=True)
    max_value: Mapped[object | None] = mapped_column(Numeric, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "value_type IN ('" + "', '".join(VALUE_TYPES) + "')", name="ck_observation_definitions_value_type"
        ),
        CheckConstraint(
            "target_scope IN ('" + "', '".join(TARGET_SCOPES) + "')",
            name="ck_observation_definitions_target_scope",
        ),
        CheckConstraint("status IN ('active', 'inactive')", name="ck_observation_definitions_status"),
        CheckConstraint(
            "min_value IS NULL OR max_value IS NULL OR min_value <= max_value",
            name="ck_observation_definitions_min_le_max",
        ),
        CheckConstraint(
            "value_type NOT IN ('boolean', 'text') OR (min_value IS NULL AND max_value IS NULL)",
            name="ck_observation_definitions_bool_text_no_bounds",
        ),
        CheckConstraint(
            "value_type <> 'percentage' OR "
            "((min_value IS NULL OR min_value >= 0) AND (max_value IS NULL OR max_value <= 100))",
            name="ck_observation_definitions_percentage_bounds",
        ),
        CheckConstraint(
            "value_type <> 'integer' OR "
            "((min_value IS NULL OR min_value = floor(min_value)) AND "
            "(max_value IS NULL OR max_value = floor(max_value)))",
            name="ck_observation_definitions_integer_bounds_integral",
        ),
        Index("ux_observation_definitions_tenant_code_lower", "tenant_id", func.lower(code), unique=True),
        UniqueConstraint("tenant_id", "id", name="uq_observation_definitions_tenant_id_id"),
    )
