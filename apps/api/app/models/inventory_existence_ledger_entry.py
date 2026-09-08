import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
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

ENTRY_KINDS = ("receipt", "adjustment", "reversal", "split_out", "split_in", "consumption", "scrap")


class InventoryExistenceLedgerEntry(Base):
    """STORE-INV-002A.1: the authoritative, append-only existence ledger,
    targeting `InventoryQuantityCohort` (`docs/domain/
    STORE_INVENTORY_MODEL.md` §7/§F) -- never `GoodsReceiptLine` or
    `InventoryLot` directly. Balance is always `SUM(quantity_delta_base)`
    for a cohort; there is no stored current-quantity column anywhere.

    `receipt`: exactly one deterministic opening entry per root cohort
    (`id = inventory_quantity_cohort_id`, mirroring `harvest_receipt.id =
    produce_lot_id`). `adjustment`: signed, non-zero, mandatory reason,
    always targets one existing cohort explicitly. `reversal`: exact
    negation of another entry on the SAME cohort, mandatory reason, at most
    one reversal per target, no reversal-of-reversal. `split_out`/
    `split_in`: existence-neutral cohort-split pair (STORE-INV-002A.1
    schema foundation; the operator-facing partial-disposition command is
    STORE-INV-002A.2 scope).

    STORE-INV-004: `consumption` (material actually used by farm
    operations) and `scrap` (material disposed of/lost, from any of the
    three physical buckets) are both negative, non-zero existence facts,
    shaped exactly like `adjustment` (no reversal/split-source references)
    but semantically distinct and never reversible through the generic
    `reversal` path (`inventory_material_event_service` blocks it --
    reversing either would restore existence without restoring the
    matching custody/Issue-line state)."""

    __tablename__ = "inventory_existence_ledger_entries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    inventory_quantity_cohort_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inventory_quantity_cohorts.id"), nullable=False
    )
    inventory_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_items.id"), nullable=False)
    inventory_lot_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("inventory_lots.id"), nullable=True)
    receiving_farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    entry_kind: Mapped[str] = mapped_column(String, nullable=False)
    quantity_delta_base: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    reversal_of_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("inventory_existence_ledger_entries.id"), nullable=True
    )
    source_split_out_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("inventory_existence_ledger_entries.id"), nullable=True
    )
    client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "entry_kind IN ('receipt', 'adjustment', 'reversal', 'split_out', 'split_in', 'consumption', 'scrap')",
            name="ck_inventory_existence_ledger_entries_kind_allowed",
        ),
        CheckConstraint(
            "quantity_delta_base = trunc(quantity_delta_base, 3) AND ("
            "  (entry_kind = 'receipt' AND quantity_delta_base > 0 AND quantity_delta_base < 100000000000)"
            "  OR (entry_kind = 'adjustment' AND quantity_delta_base <> 0 "
            "      AND quantity_delta_base > -100000000000 AND quantity_delta_base < 100000000000)"
            "  OR (entry_kind = 'reversal' AND quantity_delta_base <> 0 "
            "      AND quantity_delta_base > -100000000000 AND quantity_delta_base < 100000000000)"
            "  OR (entry_kind = 'split_out' AND quantity_delta_base < 0 AND quantity_delta_base > -100000000000)"
            "  OR (entry_kind = 'split_in' AND quantity_delta_base > 0 AND quantity_delta_base < 100000000000)"
            "  OR (entry_kind = 'consumption' AND quantity_delta_base < 0 AND quantity_delta_base > -100000000000)"
            "  OR (entry_kind = 'scrap' AND quantity_delta_base < 0 AND quantity_delta_base > -100000000000)"
            ")",
            name="ck_inventory_existence_ledger_entries_envelope",
        ),
        CheckConstraint(
            "entry_kind NOT IN ('adjustment', 'reversal') OR reason IS NOT NULL",
            name="ck_inventory_existence_ledger_entries_reason_required",
        ),
        # Typed-source shape, exhaustive per kind (mirrors
        # finished_goods_ledger_entries' own typed-source XOR idiom): only
        # 'reversal' ever populates reversal_of_entry_id; only 'split_in'
        # ever populates source_split_out_entry_id. 'consumption'/'scrap'
        # are shaped like 'adjustment'/'split_out' -- neither reference.
        CheckConstraint(
            "(entry_kind IN ('receipt', 'adjustment', 'split_out', 'consumption', 'scrap') "
            "  AND reversal_of_entry_id IS NULL AND source_split_out_entry_id IS NULL) "
            "OR (entry_kind = 'reversal' "
            "  AND reversal_of_entry_id IS NOT NULL AND source_split_out_entry_id IS NULL) "
            "OR (entry_kind = 'split_in' "
            "  AND reversal_of_entry_id IS NULL AND source_split_out_entry_id IS NOT NULL)",
            name="ck_inventory_existence_ledger_entries_typed_source_shape",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_inventory_existence_ledger_entries_tenant_id_id"),
        # Exactly one receipt entry per root cohort.
        Index(
            "ux_inventory_existence_ledger_entries_cohort_receipt", "inventory_quantity_cohort_id",
            unique=True, postgresql_where=text("entry_kind = 'receipt'"),
        ),
        # At most one reversal per target entry.
        Index(
            "ux_inventory_existence_ledger_entries_reversal_target", "reversal_of_entry_id", unique=True,
            postgresql_where=text("entry_kind = 'reversal'"),
        ),
        # Exactly one split_in per split_out.
        Index(
            "ux_inventory_existence_ledger_entries_split_out_target", "source_split_out_entry_id", unique=True,
            postgresql_where=text("entry_kind = 'split_in'"),
        ),
        ForeignKeyConstraint(
            ["tenant_id", "inventory_quantity_cohort_id"],
            ["inventory_quantity_cohorts.tenant_id", "inventory_quantity_cohorts.id"],
            name="fk_inventory_existence_ledger_entries_tenant_cohort",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "inventory_item_id"],
            ["inventory_items.tenant_id", "inventory_items.id"],
            name="fk_inventory_existence_ledger_entries_tenant_item",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "inventory_lot_id"],
            ["inventory_lots.tenant_id", "inventory_lots.id"],
            name="fk_inventory_existence_ledger_entries_tenant_lot",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "reversal_of_entry_id"],
            ["inventory_existence_ledger_entries.tenant_id", "inventory_existence_ledger_entries.id"],
            name="fk_inventory_existence_ledger_entries_tenant_reversal_target",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "source_split_out_entry_id"],
            ["inventory_existence_ledger_entries.tenant_id", "inventory_existence_ledger_entries.id"],
            name="fk_inventory_existence_ledger_entries_tenant_split_out",
        ),
        Index(
            "ux_inventory_existence_ledger_entries_tenant_client_command_id", "tenant_id", "client_command_id",
            unique=True, postgresql_where=text("client_command_id IS NOT NULL"),
        ),
    )
