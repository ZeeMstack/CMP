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
    """Immutable, insert-only line of one packing event (CMP-015,
    converted by POSTHARVEST-OPS-001E), naming one source `GradedProduceLot`
    and the weight/optional whole-unit count consumed from it. One graded
    produce lot appears at most once per event
    (`UniqueConstraint(packing_event_id, graded_produce_lot_id)`). Each
    line produces exactly one deterministic `packing_consumption` ledger
    debit sharing this row's own `id` (see `GradedProduceLotLedgerEntry`).
    There is no supported direct `HarvestedProduceLot -> Packing` path --
    the lineage is always `HarvestedProduceLot -> GradingEvent ->
    GradedProduceLot -> PackingInputLine`."""

    __tablename__ = "packing_input_lines"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    packing_event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("packing_events.id"), nullable=False)
    graded_produce_lot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("graded_produce_lots.id"), nullable=False
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
            "packing_event_id", "graded_produce_lot_id", name="ux_packing_input_lines_event_gpl"
        ),
        # POSTHARVEST-OPS-001H: added so packing_reversal_inputs can use a
        # real composite FK to this table -- mirrors CMP-018's own
        # uq_locations_tenant_farm_id (locations had no such constraint
        # before that ticket either).
        UniqueConstraint(
            "tenant_id", "farm_id", "id", name="uq_packing_input_lines_tenant_farm_id"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "packing_event_id"],
            ["packing_events.tenant_id", "packing_events.farm_id", "packing_events.id"],
            name="fk_packing_input_lines_tenant_farm_event",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "graded_produce_lot_id"],
            ["graded_produce_lots.tenant_id", "graded_produce_lots.farm_id", "graded_produce_lots.id"],
            name="fk_packing_input_lines_tenant_farm_gpl",
        ),
    )
