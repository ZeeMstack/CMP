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


class FinishedGoodsLedgerEntry(Base):
    """Immutable, insert-only ledger entry against one finished-goods lot
    (CMP-016), mirroring CMP-014's produce-lot ledger exactly one level up
    the chain. CMP-016 permits exactly one `entry_kind`, `packing_receipt`
    — the lot's original packed quantity, created automatically inside the
    same transaction as the packing command. A `packing_receipt` row is a
    deterministic, reconstructible projection of its lot and packing
    event: `id`/`finished_goods_lot_id` both equal the lot's own id, and
    every other field is copied exactly from the lot/event, including
    `recorded_time` (from the lot's own `recorded_time`, not a fresh
    server default) and `note` (always NULL). Since only one entry kind
    exists today, the deterministic-ID, kind, and note-null rules are
    unconditional same-row CHECK constraints rather than kind-guarded —
    a future ticket introducing a second kind (e.g. dispatch) must widen
    these CHECKs the same way CMP-015 widened CMP-014's own, and must not
    assume every row obeys today's unconditional shape."""

    __tablename__ = "finished_goods_ledger_entries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    finished_goods_lot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("finished_goods_lots.id"), nullable=False
    )
    packing_event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("packing_events.id"), nullable=False)
    entry_kind: Mapped[str] = mapped_column(String, nullable=False)
    weight_delta_kg: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    package_count_delta: Mapped[int] = mapped_column(BigInteger, nullable=False)
    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    note: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint("entry_kind IN ('packing_receipt')", name="ck_finished_goods_ledger_entries_kind_allowed"),
        # Deterministic-identity CHECK: unconditional today (only one kind
        # exists), same-row, no join needed.
        CheckConstraint("id = finished_goods_lot_id", name="ck_finished_goods_ledger_entries_deterministic_id"),
        # NUMERIC deliberately unscoped, matching CMP-013/014/015's shared envelope.
        CheckConstraint(
            "weight_delta_kg > 0 AND weight_delta_kg = trunc(weight_delta_kg, 3) "
            "AND weight_delta_kg < 100000000000",
            name="ck_finished_goods_ledger_entries_weight_envelope",
        ),
        CheckConstraint("package_count_delta > 0", name="ck_finished_goods_ledger_entries_count_positive"),
        CheckConstraint("note IS NULL", name="ck_finished_goods_ledger_entries_note_null"),
        UniqueConstraint(
            "tenant_id", "farm_id", "id", name="uq_finished_goods_ledger_entries_tenant_farm_id"
        ),
        # Partial (kind-scoped), not table-wide: a future entry kind must
        # be able to reference the same lot/event without being blocked
        # by this ticket's one-receipt-per-lot rule.
        Index(
            "ux_finished_goods_ledger_entries_lot_packing_receipt", "finished_goods_lot_id", unique=True,
            postgresql_where=text("entry_kind = 'packing_receipt'"),
        ),
        Index(
            "ux_finished_goods_ledger_entries_event_packing_receipt", "packing_event_id", unique=True,
            postgresql_where=text("entry_kind = 'packing_receipt'"),
        ),
        # Both composite FKs are usable directly: unlike CMP-014's
        # situation with harvested_produce_lots, both finished_goods_lots
        # and packing_events already carry a (tenant_id, farm_id, id)
        # unique constraint (uq_finished_goods_lots_tenant_farm_id,
        # uq_packing_events_tenant_farm_id) — no new constraint needed.
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "finished_goods_lot_id"],
            ["finished_goods_lots.tenant_id", "finished_goods_lots.farm_id", "finished_goods_lots.id"],
            name="fk_finished_goods_ledger_entries_tenant_farm_lot",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "packing_event_id"],
            ["packing_events.tenant_id", "packing_events.farm_id", "packing_events.id"],
            name="fk_finished_goods_ledger_entries_tenant_farm_event",
        ),
    )
