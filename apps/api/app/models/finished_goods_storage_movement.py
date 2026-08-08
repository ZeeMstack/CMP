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
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class FinishedGoodsStorageMovement(Base):
    """Immutable, insert-only record of one physical storage movement
    (CMP-018) against one finished-goods lot: `place` (unplaced quantity
    -> a cold-store location), `transfer` (cold-store location -> another),
    or `release` (cold-store location -> unplaced/staging). A movement
    never creates, consumes, receives, dispatches, adjusts, or values
    commercial inventory -- the finished-goods ledger remains the sole
    source of truth for quantity; this table only records where an
    already-available quantity currently sits. "Unplaced" quantity is
    always derived (ledger available minus total placed), never a row in
    this table or a location of its own."""

    __tablename__ = "finished_goods_storage_movements"

    MOVEMENT_KINDS = ("place", "transfer", "release")

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    finished_goods_lot_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    movement_kind: Mapped[str] = mapped_column(String, nullable=False)
    source_location_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    destination_location_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    moved_weight_kg: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    moved_package_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    note: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "movement_kind IN ('place', 'transfer', 'release')",
            name="ck_finished_goods_storage_movements_kind_allowed",
        ),
        # place: source NULL, destination populated. transfer: both
        # populated, distinct. release: source populated, destination NULL.
        CheckConstraint(
            "(movement_kind = 'place' AND source_location_id IS NULL AND destination_location_id IS NOT NULL) "
            "OR (movement_kind = 'transfer' AND source_location_id IS NOT NULL "
            "     AND destination_location_id IS NOT NULL AND source_location_id <> destination_location_id) "
            "OR (movement_kind = 'release' AND source_location_id IS NOT NULL AND destination_location_id IS NULL)",
            name="ck_finished_goods_storage_movements_shape",
        ),
        CheckConstraint(
            "moved_weight_kg > 0 AND moved_weight_kg = trunc(moved_weight_kg, 3) "
            "AND moved_weight_kg < 100000000000",
            name="ck_finished_goods_storage_movements_weight_positive",
        ),
        CheckConstraint("moved_package_count > 0", name="ck_finished_goods_storage_movements_count_positive"),
        Index(
            "ux_finished_goods_storage_movements_tenant_client_command_id",
            "tenant_id", "client_command_id", unique=True,
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "finished_goods_lot_id"],
            ["finished_goods_lots.tenant_id", "finished_goods_lots.farm_id", "finished_goods_lots.id"],
            name="fk_finished_goods_storage_movements_tenant_farm_lot",
        ),
        # Composite FKs to locations require CMP-018's own
        # uq_locations_tenant_farm_id (locations had no such constraint
        # before this ticket).
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "source_location_id"],
            ["locations.tenant_id", "locations.farm_id", "locations.id"],
            name="fk_finished_goods_storage_movements_tenant_farm_src_location",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "destination_location_id"],
            ["locations.tenant_id", "locations.farm_id", "locations.id"],
            name="fk_finished_goods_storage_movements_tenant_farm_dest_location",
        ),
    )
