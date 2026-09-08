import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class InventoryReservation(Base):
    """STORE-INV-003: the immutable header of a Reservation -- a fungible
    CLAIM against usable in-Store quantity of one or more `InventoryItem`s
    at one Farm (`docs/domain/STORE_INVENTORY_MODEL.md` §9). Frozen at
    FARM + ITEM (never `InventoryLot`/cohort/Bin) via its own
    `InventoryReservationLine` rows -- never touches Existence, Quality, or
    physical custody. `code` is farm-scoped and immutable, mirroring
    `GoodsReceipt`'s own precedent exactly. Every field is immutable from
    creation; there is no update path."""

    __tablename__ = "inventory_reservations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    purpose: Mapped[str] = mapped_column(String, nullable=False)
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_inventory_reservations_tenant_id_id"),
        UniqueConstraint("tenant_id", "farm_id", "id", name="uq_inventory_reservations_tenant_farm_id"),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id"], ["farms.tenant_id", "farms.id"], name="fk_inventory_reservations_tenant_farm"
        ),
        Index("ux_inventory_reservations_farm_code_lower", "farm_id", func.lower(code), unique=True),
        Index(
            "ux_inventory_reservations_tenant_client_command_id", "tenant_id", "client_command_id", unique=True
        ),
    )
