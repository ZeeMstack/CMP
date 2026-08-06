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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class PackingInputLine(Base):
    """Immutable, insert-only line of one packing event (CMP-015), naming
    one source harvested produce lot and the weight/optional whole-unit
    count consumed from it. One produce lot appears at most once per
    event (`UniqueConstraint(packing_event_id, harvested_produce_lot_id)`).
    Each line produces exactly one deterministic `packing_consumption`
    ledger debit sharing this row's own `id` (see
    `ProduceLotLedgerEntry`)."""

    __tablename__ = "packing_input_lines"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    packing_event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("packing_events.id"), nullable=False)
    harvested_produce_lot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("harvested_produce_lots.id"), nullable=False
    )
    consumed_weight_kg: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    consumed_whole_unit_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    recorded_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "consumed_weight_kg > 0 AND consumed_weight_kg = trunc(consumed_weight_kg, 3) "
            "AND consumed_weight_kg < 100000000000",
            name="ck_packing_input_lines_weight_positive",
        ),
        CheckConstraint(
            "consumed_whole_unit_count IS NULL OR consumed_whole_unit_count > 0",
            name="ck_packing_input_lines_count_positive",
        ),
        UniqueConstraint(
            "packing_event_id", "harvested_produce_lot_id", name="ux_packing_input_lines_event_lot"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "packing_event_id"],
            ["packing_events.tenant_id", "packing_events.farm_id", "packing_events.id"],
            name="fk_packing_input_lines_tenant_farm_event",
        ),
        # Composite FK against the (tenant_id, farm_id, id) unique constraint
        # CMP-015 adds to harvested_produce_lots (CMP-013/014 never added
        # one — see the CMP-015 migration). Prefer this DB-enforced
        # consistency over trigger-only consistency, unlike
        # produce_lot_ledger_entries' own single-column-only FK.
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "harvested_produce_lot_id"],
            ["harvested_produce_lots.tenant_id", "harvested_produce_lots.farm_id", "harvested_produce_lots.id"],
            name="fk_packing_input_lines_tenant_farm_lot",
        ),
    )
