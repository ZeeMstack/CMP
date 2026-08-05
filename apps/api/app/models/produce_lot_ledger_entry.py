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


class ProduceLotLedgerEntry(Base):
    """Immutable, insert-only ledger entry against one harvested produce
    lot. CMP-014 permits exactly one `entry_kind`, `harvest_receipt` — the
    lot's original harvested quantity, created automatically inside the
    same transaction as the harvest command. A `harvest_receipt` row is a
    deterministic, reconstructible projection of its lot and harvest event:
    `id`/`produce_lot_id` both equal the lot's own id, and every other
    field is copied exactly from the lot/event, including `recorded_time`
    (from the lot's own `recorded_at`, not a fresh server default) and
    `note` (always NULL — the harvest event already owns the user-provided
    note). Future tickets may widen `entry_kind` for typed consumption;
    CMP-014 introduces no such kind and no negative delta (CMP-014)."""

    __tablename__ = "produce_lot_ledger_entries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    produce_lot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("harvested_produce_lots.id"), nullable=False
    )
    harvest_event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("harvest_events.id"), nullable=False)
    entry_kind: Mapped[str] = mapped_column(String, nullable=False)
    weight_delta_kg: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    whole_unit_count_delta: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    note: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint("entry_kind IN ('harvest_receipt')", name="ck_produce_lot_ledger_entries_kind_allowed"),
        # NUMERIC is deliberately unscoped, not NUMERIC(14,3) — see CMP-013's
        # own harvest_source_lines/harvested_produce_lots CHECKs, reproduced
        # identically here so the two tables share one envelope definition.
        CheckConstraint(
            "weight_delta_kg > 0 AND weight_delta_kg = trunc(weight_delta_kg, 3) "
            "AND weight_delta_kg < 100000000000",
            name="ck_produce_lot_ledger_entries_weight_envelope",
        ),
        CheckConstraint(
            "whole_unit_count_delta IS NULL OR whole_unit_count_delta > 0",
            name="ck_produce_lot_ledger_entries_count_positive",
        ),
        # A harvest_receipt's note is always NULL — the harvest event
        # already owns the user-provided note. Scoped to this one kind so a
        # future typed entry kind may use a note without altering this rule.
        CheckConstraint(
            "entry_kind <> 'harvest_receipt' OR note IS NULL",
            name="ck_produce_lot_ledger_entries_receipt_note_null",
        ),
        UniqueConstraint("tenant_id", "farm_id", "id", name="uq_produce_lot_ledger_entries_tenant_farm_id"),
        # Partial (kind-scoped), not table-wide: a future consumption kind
        # must be able to reference the same lot/event repeatedly without
        # being blocked by this ticket's one-receipt-per-lot rule.
        Index(
            "ux_produce_lot_ledger_entries_lot_harvest_receipt", "produce_lot_id", unique=True,
            postgresql_where=text("entry_kind = 'harvest_receipt'"),
        ),
        Index(
            "ux_produce_lot_ledger_entries_event_harvest_receipt", "harvest_event_id", unique=True,
            postgresql_where=text("entry_kind = 'harvest_receipt'"),
        ),
        # No composite (tenant_id, farm_id, produce_lot_id) FK here:
        # harvested_produce_lots (CMP-013) has no (tenant_id, farm_id, id)
        # unique constraint to reference (unlike harvest_events, below), and
        # the CMP-013 migration must not be modified to add one. The plain
        # single-column FK on produce_lot_id (declared above) proves the
        # lot exists; tenant/farm consistency against the lot is instead
        # proven by the DB insert-integrity trigger.
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "harvest_event_id"],
            ["harvest_events.tenant_id", "harvest_events.farm_id", "harvest_events.id"],
            name="fk_produce_lot_ledger_entries_tenant_farm_event",
        ),
    )
