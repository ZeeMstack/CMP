import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
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

INVENTORY_RESERVATION_LINE_ENTRY_KINDS = ("release", "issue")


class InventoryReservationLineEntry(Base):
    """STORE-INV-003: the append-only DEBIT ledger against one
    `InventoryReservationLine`. `release` is an operator freeing unused
    claim -- its own idempotent top-level command (`client_command_id`
    required). `issue` is composed internally, in the SAME transaction, by
    an Issue command that fulfills part of this line -- mirrors
    `InventoryStorageMovement.split_out`/`split_in`'s own "internally
    composed, no separate client_command_id" convention exactly
    (`client_command_id` forbidden, `issue_id` required instead). A line's
    remaining balance is always `requested_quantity_base - SUM(entries)`,
    never a stored aggregate."""

    __tablename__ = "inventory_reservation_line_entries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    reservation_line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inventory_reservation_lines.id"), nullable=False
    )
    entry_kind: Mapped[str] = mapped_column(String, nullable=False)
    quantity_base: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    issue_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "entry_kind IN ('release', 'issue')", name="ck_inventory_reservation_line_entries_kind_allowed"
        ),
        CheckConstraint(
            "quantity_base > 0 AND quantity_base = trunc(quantity_base, 3) AND quantity_base < 100000000000",
            name="ck_inventory_reservation_line_entries_quantity_positive",
        ),
        CheckConstraint(
            "(entry_kind = 'release' AND client_command_id IS NOT NULL AND request_fingerprint IS NOT NULL "
            "  AND issue_id IS NULL) "
            "OR (entry_kind = 'issue' AND client_command_id IS NULL AND request_fingerprint IS NULL "
            "     AND issue_id IS NOT NULL)",
            name="ck_inventory_reservation_line_entries_evidence_matches_kind",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_inventory_reservation_line_entries_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "reservation_line_id"],
            ["inventory_reservation_lines.tenant_id", "inventory_reservation_lines.id"],
            name="fk_inventory_reservation_line_entries_tenant_line",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "issue_id"], ["inventory_issues.tenant_id", "inventory_issues.id"],
            name="fk_inventory_reservation_line_entries_tenant_issue",
        ),
        Index(
            "ux_inventory_reservation_line_entries_tenant_client_command_id", "tenant_id", "client_command_id",
            unique=True, postgresql_where=text("client_command_id IS NOT NULL"),
        ),
    )
