import uuid
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.common import TimestampMixin


class GoodsReceiptLine(TimestampMixin, Base):
    """STORE-INV-002A.1: receiving provenance ONLY -- immutable from
    posting, no ledger entries and no quality disposition attached directly
    (those attach to this line's own `InventoryQuantityCohort`
    (`docs/domain/STORE_INVENTORY_MODEL.md` §7/§D)). `farm_id` is
    denormalized from the parent `GoodsReceipt` (the receiving Farm --
    provenance, never current custody). Exactly one of the direct-UOM or
    packaging entry shapes is populated, never both, never neither."""

    __tablename__ = "goods_receipt_lines"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    goods_receipt_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("goods_receipts.id"), nullable=False)
    inventory_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_items.id"), nullable=False)
    inventory_lot_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("inventory_lots.id"), nullable=True)

    # Direct-UOM entry shape (XOR with the packaging shape below).
    entered_quantity: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    entered_uom_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("unit_of_measures.id"), nullable=True)
    conversion_factor_applied: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)

    # Packaging entry shape (XOR with the direct-UOM shape above).
    packaging_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("inventory_item_packaging.id"), nullable=True
    )
    package_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    package_quantity_snapshot: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)

    base_quantity: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    external_line_id: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "base_quantity > 0 AND base_quantity = trunc(base_quantity, 3) "
            "AND base_quantity < 100000000000",
            name="ck_goods_receipt_lines_base_quantity_envelope",
        ),
        CheckConstraint("package_count IS NULL OR package_count > 0", name="ck_goods_receipt_lines_package_count_positive"),
        CheckConstraint(
            "package_quantity_snapshot IS NULL OR package_quantity_snapshot > 0",
            name="ck_goods_receipt_lines_package_quantity_snapshot_positive",
        ),
        # Direct-UOM XOR packaging -- exactly one shape populated.
        CheckConstraint(
            "(entered_quantity IS NOT NULL AND entered_uom_id IS NOT NULL "
            " AND packaging_id IS NULL AND package_count IS NULL AND package_quantity_snapshot IS NULL) "
            "OR (entered_quantity IS NULL AND entered_uom_id IS NULL "
            " AND packaging_id IS NOT NULL AND package_count IS NOT NULL "
            " AND package_quantity_snapshot IS NOT NULL)",
            name="ck_goods_receipt_lines_entry_shape_xor",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_goods_receipt_lines_tenant_id_id"),
        UniqueConstraint("tenant_id", "farm_id", "id", name="uq_goods_receipt_lines_tenant_farm_id"),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "goods_receipt_id"],
            ["goods_receipts.tenant_id", "goods_receipts.farm_id", "goods_receipts.id"],
            name="fk_goods_receipt_lines_tenant_farm_receipt",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "inventory_item_id"],
            ["inventory_items.tenant_id", "inventory_items.id"],
            name="fk_goods_receipt_lines_tenant_item",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "inventory_lot_id"],
            ["inventory_lots.tenant_id", "inventory_lots.id"],
            name="fk_goods_receipt_lines_tenant_lot",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "packaging_id"],
            ["inventory_item_packaging.tenant_id", "inventory_item_packaging.id"],
            name="fk_goods_receipt_lines_tenant_packaging",
        ),
    )
