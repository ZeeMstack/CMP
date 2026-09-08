import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class InventoryIssue(Base):
    """STORE-INV-003: the immutable header of an Issue -- a CUSTODY
    TRANSFER, Store Bin custody -> "Issued to operations" custody
    (`docs/domain/STORE_INVENTORY_MODEL.md` §10). Never touches Existence
    or Quality, and never creates a Batch/Work Order. A single Issue may
    contain multiple lines (one `InventoryStorageMovement` row per line,
    `movement_kind = 'issue'`, linked back via `issue_id`); the OPTIONAL
    `reservation_id` marks the whole Issue as being against one
    Reservation (individual lines may still each optionally pin their own
    `reservation_line_id` on the movement row). `code` is farm-scoped and
    immutable, mirroring `GoodsReceipt`'s own precedent exactly."""

    __tablename__ = "inventory_issues"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    purpose: Mapped[str] = mapped_column(String, nullable=False)
    issued_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_inventory_issues_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id"], ["farms.tenant_id", "farms.id"], name="fk_inventory_issues_tenant_farm"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "reservation_id"], ["inventory_reservations.tenant_id", "inventory_reservations.id"],
            name="fk_inventory_issues_tenant_reservation",
        ),
        Index("ux_inventory_issues_farm_code_lower", "farm_id", func.lower(code), unique=True),
        Index("ux_inventory_issues_tenant_client_command_id", "tenant_id", "client_command_id", unique=True),
    )
