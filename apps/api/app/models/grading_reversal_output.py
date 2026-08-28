import uuid
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class GradingReversalOutput(Base):
    """POSTHARVEST-OPS-001H: one row per `GradedProduceLot` output being
    neutralized by one `GradingReversalEvent` -- mirrors `PackingInputLine`'s
    own shape (a child row of a reversal/event whose own `id` becomes its
    deterministic `GradedProduceLotLedgerEntry(grading_reversal)` debit's
    id). `reversed_weight_kg`/`reversed_whole_unit_count` always equal the
    output's own `GradedProduceLot.original_received_weight_kg`/
    `original_received_whole_unit_count` -- the Grading downstream gate
    (`grading_service.reverse_grading_event`) only ever allows a reversal
    while every output's current available balance already equals its own
    original receipt (never packed, or packed by PackingEvents that have
    themselves all been reversed), so the exact-negation amount is always
    the lot's own frozen original quantity, never a live balance read."""

    __tablename__ = "grading_reversal_outputs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    grading_reversal_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("grading_reversal_events.id"), nullable=False
    )
    graded_produce_lot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("graded_produce_lots.id"), nullable=False
    )
    reversed_weight_kg: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    reversed_whole_unit_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "reversed_weight_kg > 0 AND reversed_weight_kg = trunc(reversed_weight_kg, 3) "
            "AND reversed_weight_kg < 100000000000",
            name="ck_grading_reversal_outputs_weight_positive",
        ),
        CheckConstraint(
            "reversed_whole_unit_count IS NULL OR reversed_whole_unit_count > 0",
            name="ck_grading_reversal_outputs_count_positive",
        ),
        # A GPL is the output of exactly one GradingEvent, which can be
        # reversed at most once -- so a GPL may appear in this table at
        # most once, ever (never scoped to grading_reversal_event_id).
        UniqueConstraint("graded_produce_lot_id", name="ux_grading_reversal_outputs_graded_produce_lot"),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "grading_reversal_event_id"],
            [
                "grading_reversal_events.tenant_id", "grading_reversal_events.farm_id",
                "grading_reversal_events.id",
            ],
            name="fk_grading_reversal_outputs_tenant_farm_event",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "graded_produce_lot_id"],
            ["graded_produce_lots.tenant_id", "graded_produce_lots.farm_id", "graded_produce_lots.id"],
            name="fk_grading_reversal_outputs_tenant_farm_gpl",
        ),
    )
