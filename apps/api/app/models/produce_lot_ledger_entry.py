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
    lot. CMP-014 introduced one `entry_kind`, `harvest_receipt` — the
    lot's original harvested quantity, created automatically inside the
    same transaction as the harvest command. CMP-015 adds a second kind,
    `packing_consumption` — a typed negative debit created automatically
    inside the packing transaction. HARVEST-OPS-001 adds a third kind,
    `harvest_adjustment` — a signed (either-direction) correction delta,
    `id` equal to its own `HarvestSourceLineCorrection`'s id, computed as
    `corrected_effective_tuple - predecessor_effective_tuple` (never
    relative to the ORIGINAL receipt once a prior correction exists — see
    `harvest_service.py`'s own correction algorithm). Each kind is a
    deterministic, reconstructible projection of exactly one source row: a
    `harvest_receipt`'s `id`/`produce_lot_id` equal the lot's own id and
    `harvest_event_id` is populated; a `packing_consumption`'s `id` equals
    its `PackingInputLine`'s own id and `packing_event_id` is populated; a
    `harvest_adjustment`'s `id` equals its `HarvestSourceLineCorrection`'s
    own id and `harvest_source_line_correction_id` is populated. The three
    source references are mutually exclusive
    (`ck_produce_lot_ledger_entries_typed_source_shape`) and the weight/
    count sign is tied to the kind (positive receipts, negative
    consumption, either sign for an adjustment) —
    `available_weight_kg = SUM(weight_delta_kg)` therefore reflects
    receipts, consumption, and corrections alike with no separate
    balance/status column. `received_weight_kg`/`received_whole_unit_count`
    (see `produce_lot_ledger_service.get_balance`) sum `harvest_receipt`
    ORIGINAL inflow only, unaffected by corrections;
    `current_corrected_received_*` widens that sum to also include
    `harvest_adjustment` (excluding `packing_consumption`) — the "current
    corrected Harvest total" distinct from both the frozen original
    receipt and the post-packing available balance."""

    __tablename__ = "produce_lot_ledger_entries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    produce_lot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("harvested_produce_lots.id"), nullable=False
    )
    # Nullable since CMP-015: populated for harvest_receipt, NULL for
    # packing_consumption (see ck_produce_lot_ledger_entries_typed_source_shape).
    harvest_event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("harvest_events.id"), nullable=True)
    # New in CMP-015: populated for packing_consumption, NULL for harvest_receipt.
    packing_event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("packing_events.id"), nullable=True)
    # New in HARVEST-OPS-001: populated for harvest_adjustment, NULL for the
    # other two kinds.
    harvest_source_line_correction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("harvest_source_line_corrections.id"), nullable=True
    )
    entry_kind: Mapped[str] = mapped_column(String, nullable=False)
    weight_delta_kg: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    whole_unit_count_delta: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    note: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "entry_kind IN ('harvest_receipt', 'packing_consumption', 'harvest_adjustment')",
            name="ck_produce_lot_ledger_entries_kind_allowed",
        ),
        # NUMERIC is deliberately unscoped, not NUMERIC(14,3) — see CMP-013's
        # own harvest_source_lines/harvested_produce_lots CHECKs, reproduced
        # identically here so the two tables share one envelope definition.
        # Widened in CMP-015 (same constraint name, replaced body — the
        # same drop/recreate idiom CMP-013 used to widen
        # ck_workflow_stages_category_allowed) to sign the delta by kind:
        # receipts stay strictly positive, consumption strictly negative.
        # Widened again in HARVEST-OPS-001: a harvest_adjustment may be
        # EITHER sign (a correction may increase or decrease the effective
        # quantity) -- and, critically, its OWN weight_delta_kg may be
        # exactly zero (a count-only correction changes nothing about
        # weight) as long as the sibling count check proves the row isn't
        # a true no-op overall (ck_produce_lot_ledger_entries_harvest_
        # adjustment_nonzero, below) -- never a per-column-only "nonzero"
        # rule the way receipts/consumption enforce.
        CheckConstraint(
            "(entry_kind = 'harvest_receipt' AND weight_delta_kg > 0 "
            "AND weight_delta_kg = trunc(weight_delta_kg, 3) AND weight_delta_kg < 100000000000) "
            "OR (entry_kind = 'packing_consumption' AND weight_delta_kg < 0 "
            "AND weight_delta_kg = trunc(weight_delta_kg, 3) AND weight_delta_kg > -100000000000) "
            "OR (entry_kind = 'harvest_adjustment' "
            "AND weight_delta_kg = trunc(weight_delta_kg, 3) "
            "AND weight_delta_kg > -100000000000 AND weight_delta_kg < 100000000000)",
            name="ck_produce_lot_ledger_entries_weight_envelope",
        ),
        CheckConstraint(
            "(entry_kind = 'harvest_receipt' AND (whole_unit_count_delta IS NULL OR whole_unit_count_delta > 0)) "
            "OR (entry_kind = 'packing_consumption' AND (whole_unit_count_delta IS NULL OR whole_unit_count_delta < 0)) "
            "OR (entry_kind = 'harvest_adjustment' AND (whole_unit_count_delta IS NULL OR whole_unit_count_delta <> 0))",
            name="ck_produce_lot_ledger_entries_count_positive",
        ),
        # A count-only correction has weight_delta_kg = 0; a weight-only
        # correction has whole_unit_count_delta IS NULL -- but never BOTH
        # at once (that would be a true no-op, which the service never
        # inserts a row for at all).
        CheckConstraint(
            "entry_kind <> 'harvest_adjustment' OR weight_delta_kg <> 0 OR whole_unit_count_delta IS NOT NULL",
            name="ck_produce_lot_ledger_entries_harvest_adjustment_nonzero",
        ),
        # A harvest_receipt's note is always NULL — the harvest event
        # already owns the user-provided note. Scoped to this one kind so a
        # future typed entry kind may use a note without altering this rule.
        # harvest_adjustment DOES use note (the correction's own reason
        # text, denormalized for ledger-only readers).
        CheckConstraint(
            "entry_kind <> 'harvest_receipt' OR note IS NULL",
            name="ck_produce_lot_ledger_entries_receipt_note_null",
        ),
        # New in CMP-015, widened in HARVEST-OPS-001: ties entry_kind to
        # exactly one populated source reference — the DB-level typed-source
        # XOR across all three kinds.
        CheckConstraint(
            "(entry_kind = 'harvest_receipt' AND harvest_event_id IS NOT NULL AND packing_event_id IS NULL "
            "AND harvest_source_line_correction_id IS NULL) "
            "OR (entry_kind = 'packing_consumption' AND harvest_event_id IS NULL AND packing_event_id IS NOT NULL "
            "AND harvest_source_line_correction_id IS NULL) "
            "OR (entry_kind = 'harvest_adjustment' AND harvest_event_id IS NULL AND packing_event_id IS NULL "
            "AND harvest_source_line_correction_id IS NOT NULL)",
            name="ck_produce_lot_ledger_entries_typed_source_shape",
        ),
        UniqueConstraint("tenant_id", "farm_id", "id", name="uq_produce_lot_ledger_entries_tenant_farm_id"),
        # Partial (kind-scoped), not table-wide: consumption may reference
        # the same lot repeatedly (multiple packing events over time), so
        # only the one-receipt-per-lot/-event rule is scoped to that kind.
        Index(
            "ux_produce_lot_ledger_entries_lot_harvest_receipt", "produce_lot_id", unique=True,
            postgresql_where=text("entry_kind = 'harvest_receipt'"),
        ),
        Index(
            "ux_produce_lot_ledger_entries_event_harvest_receipt", "harvest_event_id", unique=True,
            postgresql_where=text("entry_kind = 'harvest_receipt'"),
        ),
        # New in CMP-015: one lot appears once per packing event (defense
        # in depth alongside PackingInputLine's own identical uniqueness
        # and the deterministic id = packing_input_line.id convention).
        Index(
            "ux_produce_lot_ledger_entries_event_lot_packing_consumption", "packing_event_id", "produce_lot_id",
            unique=True, postgresql_where=text("entry_kind = 'packing_consumption'"),
        ),
        # HARVEST-OPS-001: one correction produces exactly one
        # harvest_adjustment ledger entry, ever -- DB-level, unreachable via
        # direct SQL (mirrors the harvest_receipt-per-event index above).
        Index(
            "ux_produce_lot_ledger_entries_correction_harvest_adjustment",
            "harvest_source_line_correction_id", unique=True,
            postgresql_where=text("entry_kind = 'harvest_adjustment'"),
        ),
        # No composite (tenant_id, farm_id, produce_lot_id) FK here:
        # harvested_produce_lots (CMP-013) has no (tenant_id, farm_id, id)
        # unique constraint to reference (unlike harvest_events/
        # packing_events, below), and the CMP-013 migration must not be
        # modified to add one. The plain single-column FK on produce_lot_id
        # (declared above) proves the lot exists; tenant/farm consistency
        # against the lot is instead proven by the DB insert-integrity
        # trigger.
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "harvest_event_id"],
            ["harvest_events.tenant_id", "harvest_events.farm_id", "harvest_events.id"],
            name="fk_produce_lot_ledger_entries_tenant_farm_event",
        ),
        # New in CMP-015. Both this and the harvest_event composite FK use
        # Postgres's default MATCH SIMPLE: a FK is not checked for a row
        # where any of its own columns is NULL, so each kind's row only
        # activates the composite FK for the source table it actually
        # references.
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "packing_event_id"],
            ["packing_events.tenant_id", "packing_events.farm_id", "packing_events.id"],
            name="fk_produce_lot_ledger_entries_tenant_farm_packing_event",
        ),
        # New in HARVEST-OPS-001, same MATCH SIMPLE reasoning as above.
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "harvest_source_line_correction_id"],
            [
                "harvest_source_line_corrections.tenant_id", "harvest_source_line_corrections.farm_id",
                "harvest_source_line_corrections.id",
            ],
            name="fk_produce_lot_ledger_entries_tenant_farm_correction",
        ),
    )
