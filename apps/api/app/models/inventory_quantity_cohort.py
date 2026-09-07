import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class InventoryQuantityCohort(Base):
    """STORE-INV-002A.1: the existence-ledger and quality-disposition
    aggregate root (`docs/domain/STORE_INVENTORY_MODEL.md` §7/§B) -- NOT
    `GoodsReceiptLine` and NOT `InventoryLot`. Every posted
    `GoodsReceiptLine` automatically creates exactly one deterministic root
    cohort (`id = goods_receipt_line_id`, mirroring the
    `harvest_receipt.id = produce_lot_id` idiom). A cohort may later be
    split (`STORE-INV-002A.2`, using this ticket's own internal primitive)
    into lineage-preserving child cohorts, each with its own independent
    quality disposition, without ever creating or destroying existence.

    No stored quantity or status column -- current balance is always
    `SUM()` over `InventoryExistenceLedgerEntry` rows targeting this cohort.
    Every field is immutable from creation; there is no update path."""

    __tablename__ = "inventory_quantity_cohorts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    source_goods_receipt_line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("goods_receipt_lines.id"), nullable=False
    )
    inventory_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_items.id"), nullable=False)
    inventory_lot_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("inventory_lots.id"), nullable=True)
    receiving_farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    parent_cohort_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("inventory_quantity_cohorts.id"), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_inventory_quantity_cohorts_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "receiving_farm_id", "source_goods_receipt_line_id"],
            [
                "goods_receipt_lines.tenant_id", "goods_receipt_lines.farm_id",
                "goods_receipt_lines.id",
            ],
            name="fk_inventory_quantity_cohorts_tenant_farm_line",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "inventory_item_id"],
            ["inventory_items.tenant_id", "inventory_items.id"],
            name="fk_inventory_quantity_cohorts_tenant_item",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "inventory_lot_id"],
            ["inventory_lots.tenant_id", "inventory_lots.id"],
            name="fk_inventory_quantity_cohorts_tenant_lot",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "parent_cohort_id"],
            ["inventory_quantity_cohorts.tenant_id", "inventory_quantity_cohorts.id"],
            name="fk_inventory_quantity_cohorts_tenant_parent",
        ),
    )
