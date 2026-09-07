import uuid
from datetime import date

from sqlalchemy import (
    CheckConstraint,
    Date,
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
from app.models.common import TimestampMixin

SEED_LOT_STATUSES = ("active", "inactive")


class SeedLot(TimestampMixin, Base):
    """Tenant- and farm-owned identity of a supplier seed lot. Carries no
    quantity-on-hand, cost, or germination-test data — those belong to a
    later input-store ledger ticket (CMP-009 covers traceability only)."""

    __tablename__ = "seed_lots"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    crop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crops.id"), nullable=False)
    variety_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("varieties.id"), nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    supplier_name: Mapped[str | None] = mapped_column(String, nullable=True)
    supplier_lot_reference: Mapped[str | None] = mapped_column(String, nullable=True)
    received_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    # STORE-INV-002A.1: nullable link to the tenant-wide InventoryLot this
    # SeedLot represents the Farm-specific sowing-lineage half of (see
    # docs/domain/STORE_INVENTORY_MODEL.md §15/§I -- one InventoryLot may
    # link to many Farm-scoped SeedLots, at most one per Farm). Never
    # backfilled for historical rows, which keep this NULL and remain fully
    # valid. When set, a DB trigger enforces this row's own
    # supplier_lot_reference/expiry_date exactly equal the linked
    # InventoryLot's manufacturer_lot_reference/expiry_date at INSERT time
    # (both sides are frozen at creation, so equality can never drift) --
    # existing sowing farm-local-date validation keeps reading this row's
    # own columns directly, unchanged.
    inventory_lot_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("inventory_lots.id"), nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('active', 'inactive')", name="ck_seed_lots_status"),
        CheckConstraint(
            "expiry_date IS NULL OR received_date IS NULL OR expiry_date >= received_date",
            name="ck_seed_lots_expiry_after_received",
        ),
        Index("ux_seed_lots_tenant_code_lower", "tenant_id", func.lower(code), unique=True),
        UniqueConstraint("tenant_id", "farm_id", "id", name="uq_seed_lots_tenant_farm_id"),
        Index(
            "ux_seed_lots_inventory_lot_farm", "inventory_lot_id", "farm_id", unique=True,
            postgresql_where=text("inventory_lot_id IS NOT NULL"),
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id"], ["farms.tenant_id", "farms.id"], name="fk_seed_lots_tenant_farm"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "crop_id"], ["crops.tenant_id", "crops.id"], name="fk_seed_lots_tenant_crop"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "crop_id", "variety_id"],
            ["varieties.tenant_id", "varieties.crop_id", "varieties.id"],
            name="fk_seed_lots_tenant_crop_variety",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "inventory_lot_id"],
            ["inventory_lots.tenant_id", "inventory_lots.id"],
            name="fk_seed_lots_tenant_inventory_lot",
        ),
    )
