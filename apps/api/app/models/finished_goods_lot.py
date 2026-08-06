import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class FinishedGoodsLot(Base):
    """Immutable identity created by exactly one packing event (CMP-015),
    carrying the event's packed-output weight and package count. Carries
    no balance, status, location, grade, SKU, customer, or cost — those
    remain deliberately out of scope until a later ticket."""

    __tablename__ = "finished_goods_lots"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    packing_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("packing_events.id"), nullable=False, unique=True
    )
    crop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crops.id"), nullable=False)
    variety_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("varieties.id"), nullable=True)
    net_packed_weight_kg: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    package_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "net_packed_weight_kg > 0 AND net_packed_weight_kg = trunc(net_packed_weight_kg, 3) "
            "AND net_packed_weight_kg < 100000000000",
            name="ck_finished_goods_lots_weight_envelope",
        ),
        CheckConstraint("package_count > 0", name="ck_finished_goods_lots_package_count_positive"),
        Index("ux_finished_goods_lots_tenant_code_lower", "tenant_id", func.lower(code), unique=True),
        UniqueConstraint("tenant_id", "farm_id", "id", name="uq_finished_goods_lots_tenant_farm_id"),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "packing_event_id"],
            ["packing_events.tenant_id", "packing_events.farm_id", "packing_events.id"],
            name="fk_finished_goods_lots_tenant_farm_event",
        ),
    )
