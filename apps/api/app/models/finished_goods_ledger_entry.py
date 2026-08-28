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
    """Immutable, insert-only ledger entry against one finished-goods lot.
    CMP-016 permitted exactly one `entry_kind`, `packing_receipt`. CMP-017
    adds the first typed negative kind, `dispatch_issue`, widening the
    same-row CHECKs to be kind-guarded exactly as anticipated in CMP-016's
    own model doc. Exactly one typed source is ever populated
    (`packing_event_id` XOR `dispatch_line_id`) — never a generic source
    type/UUID pair. Both kinds keep the same deterministic-projection
    convention, one level removed: a `packing_receipt` row's `id` equals
    its `finished_goods_lot_id`; a `dispatch_issue` row's `id` equals its
    own `dispatch_line_id`.

    POSTHARVEST-OPS-001H adds a third kind, `packing_reversal` — a typed
    negative debit neutralizing the lot's own opening `packing_receipt`
    quantity (whole-event reversal, never a field-by-field correction),
    `id` equal to its own `PackingReversalEvent`'s id (exactly one FG lot
    per PackingEvent, so exactly one debit per reversal). Reversal is only
    ever permitted while the lot has no downstream dispatch/storage
    activity (see `packing_service.reverse_packing_event`), so this debit
    always exactly zeroes the lot's balance."""

    __tablename__ = "finished_goods_ledger_entries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    finished_goods_lot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("finished_goods_lots.id"), nullable=False
    )
    packing_event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("packing_events.id"), nullable=True)
    dispatch_line_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("dispatch_lines.id"), nullable=True)
    # New in POSTHARVEST-OPS-001H: populated for packing_reversal, NULL for
    # every other kind.
    packing_reversal_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("packing_reversal_events.id"), nullable=True
    )
    entry_kind: Mapped[str] = mapped_column(String, nullable=False)
    weight_delta_kg: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    package_count_delta: Mapped[int] = mapped_column(BigInteger, nullable=False)
    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    note: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "entry_kind IN ('packing_receipt', 'dispatch_issue', 'packing_reversal')",
            name="ck_finished_goods_ledger_entries_kind_allowed",
        ),
        # Deterministic-identity CHECK, now kind-guarded: a packing_receipt
        # row's id equals its own lot id; a dispatch_issue row's id equals
        # its own dispatch line id; a packing_reversal row's id equals its
        # own PackingReversalEvent id.
        CheckConstraint(
            "(entry_kind = 'packing_receipt' AND id = finished_goods_lot_id) "
            "OR (entry_kind = 'dispatch_issue' AND id = dispatch_line_id) "
            "OR (entry_kind = 'packing_reversal' AND id = packing_reversal_event_id)",
            name="ck_finished_goods_ledger_entries_deterministic_id",
        ),
        # Typed-source XOR, mirroring CMP-015's own
        # ck_produce_lot_ledger_entries_typed_source_shape idiom exactly:
        # no generic source-type/UUID pair.
        CheckConstraint(
            "(entry_kind = 'packing_receipt' AND packing_event_id IS NOT NULL AND dispatch_line_id IS NULL "
            "  AND packing_reversal_event_id IS NULL) "
            "OR (entry_kind = 'dispatch_issue' AND packing_event_id IS NULL AND dispatch_line_id IS NOT NULL "
            "  AND packing_reversal_event_id IS NULL) "
            "OR (entry_kind = 'packing_reversal' AND packing_event_id IS NULL AND dispatch_line_id IS NULL "
            "  AND packing_reversal_event_id IS NOT NULL)",
            name="ck_finished_goods_ledger_entries_typed_source_shape",
        ),
        # Kind-signed envelope: receipts stay strictly positive, issues
        # strictly negative -- zero is never valid for either. Uses
        # explicit range comparisons rather than ABS() so the BIGINT
        # minimum (-9223372036854775808) never needs to be negated; the
        # issue lower bound is deliberately -9223372036854775807, one
        # above the true BIGINT minimum.
        CheckConstraint(
            "weight_delta_kg = trunc(weight_delta_kg, 3) AND ("
            "  (entry_kind = 'packing_receipt' AND weight_delta_kg > 0 AND weight_delta_kg < 100000000000)"
            "  OR (entry_kind = 'dispatch_issue' AND weight_delta_kg < 0 AND weight_delta_kg > -100000000000)"
            "  OR (entry_kind = 'packing_reversal' AND weight_delta_kg < 0 AND weight_delta_kg > -100000000000)"
            ")",
            name="ck_finished_goods_ledger_entries_weight_envelope",
        ),
        CheckConstraint(
            "(entry_kind = 'packing_receipt' AND package_count_delta > 0 "
            "  AND package_count_delta <= 9223372036854775807)"
            "OR (entry_kind = 'dispatch_issue' AND package_count_delta < 0 "
            "  AND package_count_delta >= -9223372036854775807)"
            "OR (entry_kind = 'packing_reversal' AND package_count_delta < 0 "
            "  AND package_count_delta >= -9223372036854775807)",
            name="ck_finished_goods_ledger_entries_count_signed",
        ),
        CheckConstraint("note IS NULL", name="ck_finished_goods_ledger_entries_note_null"),
        UniqueConstraint(
            "tenant_id", "farm_id", "id", name="uq_finished_goods_ledger_entries_tenant_farm_id"
        ),
        # Partial (kind-scoped), not table-wide: each kind gets its own
        # one-per-parent rule without blocking the other kind.
        Index(
            "ux_finished_goods_ledger_entries_lot_packing_receipt", "finished_goods_lot_id", unique=True,
            postgresql_where=text("entry_kind = 'packing_receipt'"),
        ),
        Index(
            "ux_finished_goods_ledger_entries_event_packing_receipt", "packing_event_id", unique=True,
            postgresql_where=text("entry_kind = 'packing_receipt'"),
        ),
        Index(
            "ux_finished_goods_ledger_entries_line_dispatch_issue", "dispatch_line_id", unique=True,
            postgresql_where=text("entry_kind = 'dispatch_issue'"),
        ),
        Index(
            "ux_finished_goods_ledger_entries_event_packing_reversal", "packing_reversal_event_id", unique=True,
            postgresql_where=text("entry_kind = 'packing_reversal'"),
        ),
        # All three composite FKs are usable directly: finished_goods_lots,
        # packing_events, and dispatch_lines each already carry their own
        # (tenant_id, farm_id, id) unique constraint.
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
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "dispatch_line_id"],
            ["dispatch_lines.tenant_id", "dispatch_lines.farm_id", "dispatch_lines.id"],
            name="fk_finished_goods_ledger_entries_tenant_farm_line",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "packing_reversal_event_id"],
            [
                "packing_reversal_events.tenant_id", "packing_reversal_events.farm_id",
                "packing_reversal_events.id",
            ],
            name="fk_finished_goods_ledger_entries_tenant_farm_packing_reversal",
        ),
    )
