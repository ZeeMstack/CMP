import uuid
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, ForeignKeyConstraint, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class DispatchLine(Base):
    """Immutable, insert-only line of one dispatch event (CMP-017), naming
    one finished-goods lot and the weight/package count dispatched from
    it. One finished-goods lot appears at most once per event
    (`UNIQUE(dispatch_event_id, finished_goods_lot_id)`). Each line
    produces exactly one deterministic `dispatch_issue` ledger entry
    sharing this row's own `id` (see `FinishedGoodsLedgerEntry`)."""

    __tablename__ = "dispatch_lines"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    dispatch_event_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    finished_goods_lot_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    dispatched_weight_kg: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    dispatched_package_count: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "dispatched_weight_kg > 0 AND dispatched_weight_kg = trunc(dispatched_weight_kg, 3) "
            "AND dispatched_weight_kg < 100000000000",
            name="ck_dispatch_lines_weight_positive",
        ),
        CheckConstraint("dispatched_package_count > 0", name="ck_dispatch_lines_count_positive"),
        UniqueConstraint(
            "dispatch_event_id", "finished_goods_lot_id", name="ux_dispatch_lines_event_lot"
        ),
        # (tenant_id, farm_id, id) so finished_goods_ledger_entries can use
        # a real composite FK to this table, matching every other typed
        # source in this codebase (packing_events, harvest_events) rather
        # than relying on the UUID primary key alone.
        UniqueConstraint("tenant_id", "farm_id", "id", name="uq_dispatch_lines_tenant_farm_id"),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "dispatch_event_id"],
            ["dispatch_events.tenant_id", "dispatch_events.farm_id", "dispatch_events.id"],
            name="fk_dispatch_lines_tenant_farm_event",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "finished_goods_lot_id"],
            ["finished_goods_lots.tenant_id", "finished_goods_lots.farm_id", "finished_goods_lots.id"],
            name="fk_dispatch_lines_tenant_farm_lot",
        ),
    )
