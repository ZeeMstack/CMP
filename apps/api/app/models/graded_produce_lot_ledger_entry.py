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

    For 001C exactly one `entry_kind`, `grading_receipt`, exists — the
    deterministic, reconstructible opening receipt for its lot
    (`id = graded_produce_lot_id`), created automatically inside the same
    transaction as the `GradingEvent` that created the lot, exactly
    mirroring CMP-014's own `harvest_receipt` convention one level down
    the chain. No `packing_consumption`-equivalent kind exists yet — a
    later ticket (POSTHARVEST-OPS-001E) will widen this table's CHECK/
    trigger the same way CMP-015 widened CMP-014's own, using the
    identical drop/recreate-check + `CREATE OR REPLACE FUNCTION` idiom."""

    __tablename__ = "graded_produce_lot_ledger_entries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    graded_produce_lot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("graded_produce_lots.id"), nullable=False
    )
    grading_event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("grading_events.id"), nullable=False)
    entry_kind: Mapped[str] = mapped_column(String, nullable=False)
    weight_delta_kg: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    whole_unit_count_delta: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    note: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "entry_kind IN ('grading_receipt')", name="ck_graded_produce_lot_ledger_entries_kind_allowed"
        ),
        CheckConstraint(
            "weight_delta_kg > 0 AND weight_delta_kg = trunc(weight_delta_kg, 3) "
            "AND weight_delta_kg < 100000000000",
            name="ck_graded_produce_lot_ledger_entries_weight_envelope",
        ),
        CheckConstraint(
            "whole_unit_count_delta IS NULL OR whole_unit_count_delta > 0",
            name="ck_graded_produce_lot_ledger_entries_count_positive",
        ),
        CheckConstraint(
            "entry_kind <> 'grading_receipt' OR note IS NULL",
            name="ck_graded_produce_lot_ledger_entries_receipt_note_null",
        ),
        UniqueConstraint(
            "tenant_id", "farm_id", "id", name="uq_graded_produce_lot_ledger_entries_tenant_farm_id"
        ),
        # Partial (kind-scoped, not table-wide) so a future consumption
        # kind (POSTHARVEST-OPS-001E) can reference the same lot
        # repeatedly without being blocked by this ticket's
        # one-receipt-per-lot rule.
        Index(
            "ux_graded_produce_lot_ledger_entries_lot_receipt", "graded_produce_lot_id", unique=True,
            postgresql_where=text("entry_kind = 'grading_receipt'"),
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
    )
