import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class InventoryLot(Base):
    """STORE-INV-002A.1: the tenant-wide traceable manufacturer-lot identity
    (`docs/domain/STORE_INVENTORY_MODEL.md` §7/§C) -- NEVER Farm-scoped.
    Fully immutable from creation (no update path anywhere); a wrong value
    is corrected by creating a fresh, correctly-identified lot and reversing
    the mistaken receipt, never by editing this row.

    `manufacturer_name`/`manufacturer_lot_reference` are GrowCMP's own
    free-text facts -- what is physically printed on the package -- never a
    Supplier Master row. The canonical, tenant-wide identity/matching key is
    `(tenant_id, inventory_item_id, lower(trim(manufacturer_name)),
    lower(trim(manufacturer_lot_reference)))` ONLY -- `manufacturing_date`/
    `expiry_date` are immutable ATTRIBUTES of that identity, never
    uniqueness dimensions (STORE-INV-002A final domain closure, issue A1).
    A lot with either manufacturer field missing is never auto-matched to
    any other lot -- each such receipt creates a brand-new row."""

    __tablename__ = "inventory_lots"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    inventory_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_items.id"), nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    manufacturer_name: Mapped[str | None] = mapped_column(String, nullable=True)
    manufacturer_lot_reference: Mapped[str | None] = mapped_column(String, nullable=True)
    manufacturing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "manufacturer_lot_reference IS NULL OR manufacturer_name IS NOT NULL",
            name="ck_inventory_lots_manufacturer_reference_requires_name",
        ),
        Index("ux_inventory_lots_tenant_code_lower", "tenant_id", func.lower(code), unique=True),
        # Canonical identity -- manufacturer name + manufacturer lot
        # reference ONLY. manufacturing_date/expiry_date are deliberately
        # NOT part of this index (they are compared for compatibility by
        # the service, not folded into uniqueness) -- STORE-INV-002A final
        # domain closure, issue A1.
        Index(
            "ux_inventory_lots_tenant_item_manufacturer_identity",
            "tenant_id", "inventory_item_id", func.lower(func.trim(manufacturer_name)),
            func.lower(func.trim(manufacturer_lot_reference)),
            unique=True,
            postgresql_where=text("manufacturer_name IS NOT NULL AND manufacturer_lot_reference IS NOT NULL"),
        ),
        UniqueConstraint("tenant_id", "id", name="uq_inventory_lots_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "inventory_item_id"],
            ["inventory_items.tenant_id", "inventory_items.id"],
            name="fk_inventory_lots_tenant_item",
        ),
    )
