import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class HarvestSourceLine(Base):
    """Immutable, insert-only per-assignment line of a harvest event.
    `batch_carrier_assignment_id` is deliberately **not** globally unique —
    the same active carrier assignment may be harvested again in a later,
    separate event; only one appearance per event is enforced (CMP-013)."""

    __tablename__ = "harvest_source_lines"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    harvest_event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("harvest_events.id"), nullable=False)
    batch_carrier_assignment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batch_carrier_assignments.id"), nullable=False
    )
    carrier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("carriers.id"), nullable=False)
    harvested_weight_kg: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    whole_unit_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # NUMERIC is deliberately unscoped, not NUMERIC(14,3): PostgreSQL
        # silently rounds excess scale to a declared scale on insert, which
        # would defeat "reject rather than round". This CHECK reproduces the
        # intended NUMERIC(14,3) envelope explicitly instead.
        CheckConstraint(
            "harvested_weight_kg > 0 AND harvested_weight_kg = trunc(harvested_weight_kg, 3) "
            "AND harvested_weight_kg < 100000000000",
            name="ck_harvest_source_lines_weight_envelope",
        ),
        CheckConstraint(
            "whole_unit_count IS NULL OR whole_unit_count > 0",
            name="ck_harvest_source_lines_count_positive",
        ),
        UniqueConstraint(
            "harvest_event_id", "batch_carrier_assignment_id",
            name="ux_harvest_source_lines_event_assignment",
        ),
        UniqueConstraint(
            "tenant_id", "farm_id", "harvest_event_id", "id",
            name="uq_harvest_source_lines_tenant_farm_event_id",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "harvest_event_id"],
            ["harvest_events.tenant_id", "harvest_events.farm_id", "harvest_events.id"],
            name="fk_harvest_source_lines_tenant_farm_event",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_carrier_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id", "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_harvest_source_lines_tenant_farm_assignment",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "carrier_id"],
            ["carriers.tenant_id", "carriers.farm_id", "carriers.id"],
            name="fk_harvest_source_lines_tenant_farm_carrier",
        ),
    )
