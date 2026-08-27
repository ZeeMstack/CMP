import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class GradedProduceLotLedgerEntry(Base):
    """POSTHARVEST-OPS-001C: immutable, insert-only ledger entry against
    one `GradedProduceLot` — a new PEER ledger (not a widened dimension of
    `produce_lot_ledger_entries`), since `GradedProduceLot` is a genuinely
    new lot identity, mirroring this codebase's established "one ledger
    per lot identity" convention (produce-lot ledger for
    `HarvestedProduceLot`, finished-goods ledger for `FinishedGoodsLot`).

    001C introduced exactly one `entry_kind`, `grading_receipt` — the
    deterministic, reconstructible opening receipt for its lot
    (`id = graded_produce_lot_id`), created automatically inside the same
    transaction as the `GradingEvent` that created the lot, exactly
    mirroring CMP-014's own `harvest_receipt` convention one level down
    the chain.

    POSTHARVEST-OPS-001E adds a second kind, `packing_consumption` — a
    typed negative debit, `id` equal to its own `PackingInputLine`'s own
    id (one debit per input line, since a packing event may combine many
    graded produce lots — mirrors CMP-015's own historical
    `packing_consumption` shape on `ProduceLotLedgerEntry`, moved down one
    level: Packing no longer debits `HarvestedProduceLot` balance at all
    after this ticket). The two kinds are mutually exclusive typed sources
    (`ck_graded_produce_lot_ledger_entries_typed_source_shape`):
    `grading_receipt` populates `grading_event_id` (NULL `packing_event_id`);
    `packing_consumption` populates `packing_event_id` (NULL
    `grading_event_id`)."""

    __tablename__ = "graded_produce_lot_ledger_entries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    graded_produce_lot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("graded_produce_lots.id"), nullable=False
    )
    # Nullable since POSTHARVEST-OPS-001E: populated for grading_receipt,
    # NULL for packing_consumption.
    grading_event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("grading_events.id"), nullable=True)
    # New in POSTHARVEST-OPS-001E: populated for packing_consumption, NULL
    # for grading_receipt.
    packing_event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("packing_events.id"), nullable=True)
    entry_kind: Mapped[str] = mapped_column(String, nullable=False)
    weight_delta_kg: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    whole_unit_count_delta: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    note: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "entry_kind IN ('grading_receipt', 'packing_consumption')",
            name="ck_graded_produce_lot_ledger_entries_kind_allowed",
        ),
        CheckConstraint(
            "weight_delta_kg = trunc(weight_delta_kg, 3) AND ("
            "  (entry_kind = 'grading_receipt' AND weight_delta_kg > 0 AND weight_delta_kg < 100000000000)"
            "  OR (entry_kind = 'packing_consumption' AND weight_delta_kg < 0 AND weight_delta_kg > -100000000000)"
            ")",
            name="ck_graded_produce_lot_ledger_entries_weight_envelope",
        ),
        CheckConstraint(
            "(entry_kind = 'grading_receipt' AND (whole_unit_count_delta IS NULL OR whole_unit_count_delta > 0)) "
            "OR (entry_kind = 'packing_consumption' AND (whole_unit_count_delta IS NULL OR whole_unit_count_delta < 0))",
            name="ck_graded_produce_lot_ledger_entries_count_positive",
        ),
        CheckConstraint(
            "entry_kind <> 'grading_receipt' OR note IS NULL",
            name="ck_graded_produce_lot_ledger_entries_receipt_note_null",
        ),
        CheckConstraint(
            "(entry_kind = 'grading_receipt' AND grading_event_id IS NOT NULL AND packing_event_id IS NULL) "
            "OR (entry_kind = 'packing_consumption' AND grading_event_id IS NULL AND packing_event_id IS NOT NULL)",
            name="ck_graded_produce_lot_ledger_entries_typed_source_shape",
        ),
        UniqueConstraint(
            "tenant_id", "farm_id", "id", name="uq_graded_produce_lot_ledger_entries_tenant_farm_id"
        ),
        # Partial (kind-scoped, not table-wide): a graded produce lot may
        # be packed repeatedly (multiple packing events over time,
        # partial-balance consumption), so only the one-receipt-per-lot
        # rule is scoped to that kind.
        Index(
            "ux_graded_produce_lot_ledger_entries_lot_receipt", "graded_produce_lot_id", unique=True,
            postgresql_where=text("entry_kind = 'grading_receipt'"),
        ),
        # POSTHARVEST-OPS-001E: one graded produce lot appears at most
        # once per packing event (defense in depth alongside
        # PackingInputLine's own identical uniqueness and the
        # deterministic id = packing_input_line.id convention).
        Index(
            "ux_graded_produce_lot_ledger_entries_packing_consumption", "packing_event_id", "graded_produce_lot_id",
            unique=True, postgresql_where=text("entry_kind = 'packing_consumption'"),
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "graded_produce_lot_id"],
            ["graded_produce_lots.tenant_id", "graded_produce_lots.farm_id", "graded_produce_lots.id"],
            name="fk_graded_produce_lot_ledger_entries_tenant_farm_lot",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "grading_event_id"],
            ["grading_events.tenant_id", "grading_events.farm_id", "grading_events.id"],
            name="fk_graded_produce_lot_ledger_entries_tenant_farm_event",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "packing_event_id"],
            ["packing_events.tenant_id", "packing_events.farm_id", "packing_events.id"],
            name="fk_graded_produce_lot_ledger_entries_tenant_farm_packing_event",
        ),
    )
