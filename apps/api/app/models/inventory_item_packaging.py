import uuid

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.common import TimestampMixin

INVENTORY_ITEM_PACKAGING_STATUSES = ("active", "inactive")


class InventoryItemPackaging(TimestampMixin, Base):
    """STORE-INV-002A.1: an item-specific display/packaging unit (e.g.
    `BAG-25KG`) naming its quantity in the item's own base UOM -- never a
    `UnitOfMeasure` row (`docs/domain/STORE_INVENTORY_MODEL.md` §5/§L).
    Lifecycle is reversible `active` <-> `inactive`, mirroring
    `CarrierSpecification`'s own reversible lifecycle -- explicitly not
    `PackagingUnit`'s one-way retire. `code` is permanently immutable from
    creation; `package_quantity` becomes structurally frozen the instant any
    `GoodsReceiptLine` references this row (service-layer `_is_referenced`
    check, mirroring `carrier_specification_service` exactly) -- `status`/
    `display_name` remain editable regardless of use."""

    __tablename__ = "inventory_item_packaging"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    inventory_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_items.id"), nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    package_quantity: Mapped[str] = mapped_column(Numeric, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    update_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    update_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)
    deactivation_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    deactivation_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)
    reactivation_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    reactivation_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('active', 'inactive')", name="ck_inventory_item_packaging_status"),
        CheckConstraint("package_quantity > 0", name="ck_inventory_item_packaging_quantity_positive"),
        Index(
            "ux_inventory_item_packaging_item_code_lower", "tenant_id", "inventory_item_id", func.lower(code),
            unique=True,
        ),
        Index(
            "ux_inventory_item_packaging_tenant_client_command_id", "tenant_id", "client_command_id", unique=True
        ),
        Index(
            "ux_inventory_item_packaging_tenant_update_command", "tenant_id", "update_client_command_id",
            unique=True, postgresql_where=text("update_client_command_id IS NOT NULL"),
        ),
        Index(
            "ux_inventory_item_packaging_tenant_deactivation_command", "tenant_id",
            "deactivation_client_command_id", unique=True,
            postgresql_where=text("deactivation_client_command_id IS NOT NULL"),
        ),
        Index(
            "ux_inventory_item_packaging_tenant_reactivation_command", "tenant_id",
            "reactivation_client_command_id", unique=True,
            postgresql_where=text("reactivation_client_command_id IS NOT NULL"),
        ),
        UniqueConstraint("tenant_id", "id", name="uq_inventory_item_packaging_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "inventory_item_id"],
            ["inventory_items.tenant_id", "inventory_items.id"],
            name="fk_inventory_item_packaging_tenant_item",
        ),
    )
