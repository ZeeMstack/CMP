import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ObservationValue(Base):
    """Immutable, insert-only typed value within one observation event —
    exactly one carrier, one definition, one typed column populated
    (CMP-010)."""

    __tablename__ = "observation_values"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    observation_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("observation_events.id"), nullable=False
    )
    observation_definition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("observation_definitions.id"), nullable=False
    )
    batch_carrier_assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("batch_carrier_assignments.id"), nullable=True
    )
    value_integer: Mapped[int | None] = mapped_column(Integer, nullable=True)
    value_decimal: Mapped[object | None] = mapped_column(Numeric, nullable=True)
    value_boolean: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    value_text: Mapped[str | None] = mapped_column(String, nullable=True)
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "(value_integer IS NOT NULL)::int + (value_decimal IS NOT NULL)::int + "
            "(value_boolean IS NOT NULL)::int + (value_text IS NOT NULL)::int = 1",
            name="ck_observation_values_exactly_one_typed_value",
        ),
        CheckConstraint(
            "value_text IS NULL OR length(value_text) > 0", name="ck_observation_values_text_not_blank"
        ),
        Index(
            "ux_observation_values_batch_target",
            "observation_event_id",
            "observation_definition_id",
            unique=True,
            postgresql_where=text("batch_carrier_assignment_id IS NULL"),
        ),
        Index(
            "ux_observation_values_assignment_target",
            "observation_event_id",
            "observation_definition_id",
            "batch_carrier_assignment_id",
            unique=True,
            postgresql_where=text("batch_carrier_assignment_id IS NOT NULL"),
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "observation_event_id"],
            ["observation_events.tenant_id", "observation_events.farm_id", "observation_events.id"],
            name="fk_observation_values_tenant_farm_event",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "observation_definition_id"],
            ["observation_definitions.tenant_id", "observation_definitions.id"],
            name="fk_observation_values_tenant_definition",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_carrier_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id",
                "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_observation_values_tenant_farm_assignment",
        ),
    )
