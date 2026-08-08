import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class DispatchEvent(Base):
    """Immutable, insert-only record of one dispatch command (CMP-017):
    the first typed negative finished-goods ledger operation. A
    successfully inserted row represents a completed dispatch — there is
    no status or editable completion flag. Carries no customer,
    destination, money, or derived-total column; every total is summed
    from `dispatch_lines` at read time."""

    __tablename__ = "dispatch_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    external_reference: Mapped[str | None] = mapped_column(String, nullable=True)
    note: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        # Farm-scoped (not tenant-scoped, unlike every other *_code index in
        # this codebase) — a deliberate CMP-017 choice: a dispatch code is a
        # facility-local document number, not a tenant-wide identity like a
        # produce/finished-goods lot code.
        Index("ux_dispatch_events_farm_code_lower", "farm_id", func.lower(code), unique=True),
        UniqueConstraint("tenant_id", "farm_id", "id", name="uq_dispatch_events_tenant_farm_id"),
        Index("ux_dispatch_events_tenant_client_command_id", "tenant_id", "client_command_id", unique=True),
    )
