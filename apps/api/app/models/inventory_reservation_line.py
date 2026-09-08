import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Numeric, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class InventoryReservationLine(Base):
    """STORE-INV-003: one immutable line within a Reservation -- the
    ORIGINAL requested quantity for one `InventoryItem`, frozen at
    creation. Remaining balance is never stored here -- always
    `requested_quantity_base - SUM(InventoryReservationLineEntry.quantity_base)`
    for this line, mirroring every other balance in this codebase
    (`docs/domain/STORE_INVENTORY_MODEL.md` §9)."""

    __tablename__ = "inventory_reservation_lines"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    reservation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_reservations.id"), nullable=False)
    inventory_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_items.id"), nullable=False)
    requested_quantity_base: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    recorded_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "requested_quantity_base > 0 AND requested_quantity_base = trunc(requested_quantity_base, 3) "
            "AND requested_quantity_base < 100000000000",
            name="ck_inventory_reservation_lines_quantity_positive",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_inventory_reservation_lines_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "reservation_id"], ["inventory_reservations.tenant_id", "inventory_reservations.id"],
            name="fk_inventory_reservation_lines_tenant_reservation",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "inventory_item_id"], ["inventory_items.tenant_id", "inventory_items.id"],
            name="fk_inventory_reservation_lines_tenant_item",
        ),
    )
