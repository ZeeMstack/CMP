import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class SowingEventLine(Base):
    """Immutable, insert-only per-carrier line of one sowing event: exactly
    one carrier, one seed lot, and its recorded sown-site/seed quantities.
    Exactly one line per batch-carrier assignment (CMP-009)."""

    __tablename__ = "sowing_event_lines"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    sowing_event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sowing_events.id"), nullable=False)
    batch_carrier_assignment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batch_carrier_assignments.id"), nullable=False
    )
    carrier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("carriers.id"), nullable=False)
    seed_lot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("seed_lots.id"), nullable=False)
    # NURSERY-OPS-001.1: nullable -- "sown site/cell count" is a genuinely
    # separate, optionally-observed fact from "seeds sown" (see
    # SEED_SOWING_MODEL.md). CMP-009 originally required both and the
    # NURSERY-OPS-001 operator command silently set
    # sown_site_count = seed_count, fabricating an unobserved
    # one-seed-per-site assumption. NULL now honestly means "not recorded"
    # -- the CHECK constraints below both pass automatically on NULL
    # (Postgres CHECK is satisfied unless it evaluates to FALSE).
    sown_site_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    line_note: Mapped[str | None] = mapped_column(String, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("sown_site_count > 0", name="ck_sowing_event_lines_site_count_positive"),
        CheckConstraint("seed_count > 0", name="ck_sowing_event_lines_seed_count_positive"),
        CheckConstraint(
            "seed_count >= sown_site_count", name="ck_sowing_event_lines_seed_count_ge_site_count"
        ),
        UniqueConstraint(
            "sowing_event_id", "carrier_id", name="ux_sowing_event_lines_event_carrier"
        ),
        UniqueConstraint(
            "batch_carrier_assignment_id", name="ux_sowing_event_lines_assignment"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "sowing_event_id"],
            ["sowing_events.tenant_id", "sowing_events.farm_id", "sowing_events.id"],
            name="fk_sowing_event_lines_tenant_farm_event",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_carrier_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id",
                "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_sowing_event_lines_tenant_farm_assignment",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "carrier_id"],
            ["carriers.tenant_id", "carriers.farm_id", "carriers.id"],
            name="fk_sowing_event_lines_tenant_farm_carrier",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "seed_lot_id"],
            ["seed_lots.tenant_id", "seed_lots.farm_id", "seed_lots.id"],
            name="fk_sowing_event_lines_tenant_farm_seed_lot",
        ),
    )
