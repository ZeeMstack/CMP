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


class PackingReversalInput(Base):
    """POSTHARVEST-OPS-001H: one row per original `PackingInputLine` being
    restored by one `PackingReversalEvent` -- mirrors `PackingInputLine`'s
    own shape exactly, one layer over (a child row of the reversal whose
    own `id` becomes its deterministic
    `GradedProduceLotLedgerEntry(packing_reversal)` credit's id).
    `restored_weight_kg`/`restored_whole_unit_count` always equal the
    original line's own `consumed_weight_kg`/`consumed_whole_unit_count`
    -- an exact negation of the original `packing_consumption` debit,
    never a live balance read. `graded_produce_lot_id` is denormalized from
    the original line for read/query convenience only (the authoritative
    reference is `packing_input_line_id`)."""

    __tablename__ = "packing_reversal_inputs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    packing_reversal_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("packing_reversal_events.id"), nullable=False
    )
    packing_input_line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("packing_input_lines.id"), nullable=False
    )
    graded_produce_lot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("graded_produce_lots.id"), nullable=False
    )
    restored_weight_kg: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    restored_whole_unit_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "restored_weight_kg > 0 AND restored_weight_kg = trunc(restored_weight_kg, 3) "
            "AND restored_weight_kg < 100000000000",
            name="ck_packing_reversal_inputs_weight_positive",
        ),
        CheckConstraint(
            "restored_whole_unit_count IS NULL OR restored_whole_unit_count > 0",
            name="ck_packing_reversal_inputs_count_positive",
        ),
        # A PackingInputLine belongs to exactly one PackingEvent, which can
        # be reversed at most once -- so a given line may appear in this
        # table at most once, ever.
        UniqueConstraint(
            "packing_input_line_id", name="ux_packing_reversal_inputs_packing_input_line"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "packing_reversal_event_id"],
            [
                "packing_reversal_events.tenant_id", "packing_reversal_events.farm_id",
                "packing_reversal_events.id",
            ],
            name="fk_packing_reversal_inputs_tenant_farm_event",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "packing_input_line_id"],
            ["packing_input_lines.tenant_id", "packing_input_lines.farm_id", "packing_input_lines.id"],
            name="fk_packing_reversal_inputs_tenant_farm_line",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "graded_produce_lot_id"],
            ["graded_produce_lots.tenant_id", "graded_produce_lots.farm_id", "graded_produce_lots.id"],
            name="fk_packing_reversal_inputs_tenant_farm_gpl",
        ),
    )
