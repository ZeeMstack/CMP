import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.common import TimestampMixin

INVENTORY_CATEGORY_STATUSES = ("active", "inactive")


class InventoryCategory(TimestampMixin, Base):
    """STORE-INV-001B: tenant-scoped classification/reporting metadata for
    `InventoryItem` only -- never a business-behavior switch
    (`docs/domain/STORE_INVENTORY_MODEL.md` §5). No `farm_id` (reusable
    across every Farm in the tenant, matching `Crop`/`ProductionSystem`).
    Flat -- no parent/child hierarchy; no catalog in this codebase has one,
    and none is justified here. `code` is permanently immutable from
    creation (no update path at all). Lifecycle is reversible `active` <->
    `inactive` (mirrors `CarrierSpecification`'s own reversible lifecycle,
    not `PackagingUnit`'s one-way retire) -- never hard-deleted.

    Deactivation and reactivation each carry their own idempotency pair
    (never one shared column) -- a category may cycle through both
    transitions repeatedly, and each direction's replay/conflict check must
    only ever compare against its own most recent command, never the
    other direction's."""

    __tablename__ = "inventory_categories"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
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
        CheckConstraint("status IN ('active', 'inactive')", name="ck_inventory_categories_status"),
        Index("ux_inventory_categories_tenant_code_lower", "tenant_id", func.lower(code), unique=True),
        Index(
            "ux_inventory_categories_tenant_client_command_id", "tenant_id", "client_command_id", unique=True
        ),
        Index(
            "ux_inventory_categories_tenant_update_command", "tenant_id", "update_client_command_id",
            unique=True, postgresql_where=text("update_client_command_id IS NOT NULL"),
        ),
        Index(
            "ux_inventory_categories_tenant_deactivation_command", "tenant_id", "deactivation_client_command_id",
            unique=True, postgresql_where=text("deactivation_client_command_id IS NOT NULL"),
        ),
        Index(
            "ux_inventory_categories_tenant_reactivation_command", "tenant_id", "reactivation_client_command_id",
            unique=True, postgresql_where=text("reactivation_client_command_id IS NOT NULL"),
        ),
        UniqueConstraint("tenant_id", "id", name="uq_inventory_categories_tenant_id_id"),
    )
