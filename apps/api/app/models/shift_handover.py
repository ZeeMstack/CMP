import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ShiftHandover(Base):
    """PILOT-OPS-001: a small, immutable, insert-only shift-handover note
    for a Farm. Never clones, closes, or otherwise mutates the Work Items
    it optionally references (see `ShiftHandoverItem`) -- open work stays
    open; the handover is a communication artifact only."""

    __tablename__ = "shift_handovers"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    author_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    note: Mapped[str] = mapped_column(Text, nullable=False)
    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        CheckConstraint("length(btrim(note)) > 0", name="ck_shift_handovers_note_not_blank"),
        Index("ux_shift_handovers_tenant_client_command_id", "tenant_id", "client_command_id", unique=True),
        Index("ix_shift_handovers_farm_effective_time", "tenant_id", "farm_id", "effective_time"),
        UniqueConstraint("tenant_id", "farm_id", "id", name="uq_shift_handovers_tenant_farm_id"),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id"], ["farms.tenant_id", "farms.id"], name="fk_shift_handovers_tenant_farm"
        ),
    )


class ShiftHandoverItem(Base):
    """PILOT-OPS-001: one immutable reference from a `ShiftHandover` to an
    unresolved `FarmWorkItem` the author flagged for the next shift. Purely
    a pointer -- it never changes the Work Item's own state."""

    __tablename__ = "shift_handover_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    handover_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    work_item_id: Mapped[uuid.UUID] = mapped_column(nullable=False)

    __table_args__ = (
        UniqueConstraint("handover_id", "work_item_id", name="uq_shift_handover_items_handover_work_item"),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "handover_id"],
            ["shift_handovers.tenant_id", "shift_handovers.farm_id", "shift_handovers.id"],
            name="fk_shift_handover_items_handover",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "work_item_id"],
            ["farm_work_items.tenant_id", "farm_work_items.farm_id", "farm_work_items.id"],
            name="fk_shift_handover_items_work_item",
        ),
    )
