import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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

INVENTORY_ITEM_STATUSES = ("active", "inactive")


class InventoryItem(TimestampMixin, Base):
    """STORE-INV-001B: tenant-scoped consumable-material master, reusable
    across every Farm in the tenant (no `farm_id`). Carries no price, cost,
    supplier, reorder metadata, purchase/issue UOM, or packaging field --
    all explicitly deferred to `STORE-INV-002A`
    (`docs/domain/STORE_INVENTORY_MODEL.md` §5). `code` is permanently
    immutable from creation. `base_uom_id` IS editable in this ticket --
    no operational table exists yet that could reference an `InventoryItem`
    (no `InventoryLot`), so there is nothing to freeze against; the actual
    structural-freeze check (mirroring `CarrierSpecification`'s own
    lock-row + is-referenced pattern) is `STORE-INV-002A` scope, not built
    here. Lifecycle is reversible `active` <-> `inactive`, never hard
    deleted.

    Two same-row tracking-policy invariants are frozen from this ticket
    onward regardless of any future operational-use state: expiry tracking
    requires lot tracking, and QC release requires lot tracking -- both
    are `InventoryLot`-level concepts and meaningless on non-lot-tracked
    material."""

    __tablename__ = "inventory_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    inventory_category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inventory_categories.id"), nullable=False
    )
    base_uom_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("unit_of_measures.id"), nullable=False)
    lot_tracking_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    expiry_tracking_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    qc_release_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
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
        CheckConstraint("status IN ('active', 'inactive')", name="ck_inventory_items_status"),
        CheckConstraint(
            "NOT expiry_tracking_required OR lot_tracking_required",
            name="ck_inventory_items_expiry_requires_lot_tracking",
        ),
        CheckConstraint(
            "NOT qc_release_required OR lot_tracking_required",
            name="ck_inventory_items_qc_release_requires_lot_tracking",
        ),
        Index("ux_inventory_items_tenant_code_lower", "tenant_id", func.lower(code), unique=True),
        Index("ux_inventory_items_tenant_client_command_id", "tenant_id", "client_command_id", unique=True),
        Index(
            "ux_inventory_items_tenant_update_command", "tenant_id", "update_client_command_id",
            unique=True, postgresql_where=text("update_client_command_id IS NOT NULL"),
        ),
        Index(
            "ux_inventory_items_tenant_deactivation_command", "tenant_id", "deactivation_client_command_id",
            unique=True, postgresql_where=text("deactivation_client_command_id IS NOT NULL"),
        ),
        Index(
            "ux_inventory_items_tenant_reactivation_command", "tenant_id", "reactivation_client_command_id",
            unique=True, postgresql_where=text("reactivation_client_command_id IS NOT NULL"),
        ),
        UniqueConstraint("tenant_id", "id", name="uq_inventory_items_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "inventory_category_id"],
            ["inventory_categories.tenant_id", "inventory_categories.id"],
            name="fk_inventory_items_tenant_category",
        ),
    )
