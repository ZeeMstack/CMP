import uuid

from sqlalchemy import ForeignKey, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.common import TimestampMixin


class InventoryItemSeedProfile(TimestampMixin, Base):
    """STORE-INV-002A.1: "Seed Details" -- the explicit, system-controlled
    seed marker for an `InventoryItem` (`docs/domain/STORE_INVENTORY_MODEL.md`
    §15). Never inferred from `InventoryCategory`; no `inventory_item_kind`
    enum. Deliberately carries NO status field -- its existence alone is the
    signal. Before the item's first posted `GoodsReceiptLine`, the row may be
    created, corrected (`crop_id`/`variety_id`), or hard-deleted -- the one
    narrow, explicitly-scoped exception to this codebase's no-hard-delete
    norm, justified because nothing can reference an unused profile yet.
    After the item's first posted `GoodsReceiptLine`, the row is fully
    immutable (service-layer freeze check, mirroring the same
    first-posted-receipt trigger that freezes `InventoryItem`'s own
    structural fields) -- no update, no removal, and no profile may be newly
    created for a historically non-seed item."""

    __tablename__ = "inventory_item_seed_profiles"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    inventory_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_items.id"), nullable=False)
    crop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crops.id"), nullable=False)
    variety_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("varieties.id"), nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(nullable=False)
    update_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    update_request_fingerprint: Mapped[str | None] = mapped_column(nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "inventory_item_id", name="uq_inventory_item_seed_profiles_item"),
        UniqueConstraint("tenant_id", "id", name="uq_inventory_item_seed_profiles_tenant_id_id"),
        UniqueConstraint(
            "tenant_id", "client_command_id", name="ux_inventory_item_seed_profiles_tenant_command"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "inventory_item_id"],
            ["inventory_items.tenant_id", "inventory_items.id"],
            name="fk_inventory_item_seed_profiles_tenant_item",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "crop_id"], ["crops.tenant_id", "crops.id"],
            name="fk_inventory_item_seed_profiles_tenant_crop",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "crop_id", "variety_id"],
            ["varieties.tenant_id", "varieties.crop_id", "varieties.id"],
            name="fk_inventory_item_seed_profiles_tenant_crop_variety",
        ),
    )
