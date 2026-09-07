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

INVENTORY_STORAGE_MOVEMENT_KINDS = ("putaway", "transfer", "split_out", "split_in")


class InventoryStorageMovement(Base):
    """STORE-INV-002B: the physical custody model for quantity-bearing
    consumable Inventory (`docs/domain/STORE_INVENTORY_MODEL.md` §8B) --
    NOT the identity-based Asset/Carrier Occupancy/Movement engine, and
    NEVER touches `InventoryExistenceLedgerEntry` balances. Mirrors
    `FinishedGoodsStorageMovement`'s own proven shape exactly: immutable,
    insert-only, one row per physical/logical custody fact, balance always
    derived via `SUM`, never a stored `current_bin_id`/`current_quantity`.

    `putaway` (source NULL, destination a `store_bin`): "Not put away" ->
    a Bin -- the operator's first physical placement of received quantity.
    `transfer` (source and destination both `store_bin`, distinct, SAME
    Farm): Bin -> Bin, an ordinary physical move.
    `split_out`/`split_in`: NOT an operator command -- the custody-side
    half of a Quality partial split/correction that acts against a
    specific Bin bucket (docs §11's own partial-quality integration).
    `split_out` (source populated, destination NULL) debits the PARENT
    cohort's custody in that Bin; `split_in` (destination populated,
    source NULL) credits the CHILD cohort's custody in the SAME Bin --
    together a logical custody reclassification, never a physical move
    (the Bin's own total is unchanged). When a partial Quality action
    instead acts against the "Not put away" bucket, no row is written at
    all -- the child simply stays not put away (derived, never a
    fabricated custody fact).

    Every cohort's own current per-Bin balance and total custody are
    always `SUM(quantity_delta)` over this table (destination = +, source
    = -), grouped by `inventory_quantity_cohort_id` and/or
    `location_id` -- never a stored aggregate anywhere on this table or
    on `InventoryQuantityCohort`."""

    __tablename__ = "inventory_storage_movements"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    inventory_quantity_cohort_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inventory_quantity_cohorts.id"), nullable=False
    )
    movement_kind: Mapped[str] = mapped_column(String, nullable=False)
    source_location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id"), nullable=True)
    destination_location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id"), nullable=True)
    moved_quantity_base: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)
    note: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "movement_kind IN ('putaway', 'transfer', 'split_out', 'split_in')",
            name="ck_inventory_storage_movements_kind_allowed",
        ),
        # putaway/split_in: source NULL, destination populated.
        # transfer: both populated, distinct. split_out: source
        # populated, destination NULL.
        CheckConstraint(
            "(movement_kind IN ('putaway', 'split_in') AND source_location_id IS NULL "
            "  AND destination_location_id IS NOT NULL) "
            "OR (movement_kind = 'transfer' AND source_location_id IS NOT NULL "
            "     AND destination_location_id IS NOT NULL AND source_location_id <> destination_location_id) "
            "OR (movement_kind = 'split_out' AND source_location_id IS NOT NULL AND destination_location_id IS NULL)",
            name="ck_inventory_storage_movements_shape",
        ),
        CheckConstraint(
            "moved_quantity_base > 0 AND moved_quantity_base = trunc(moved_quantity_base, 3) "
            "AND moved_quantity_base < 100000000000",
            name="ck_inventory_storage_movements_quantity_positive",
        ),
        # putaway/transfer are real operator commands and always carry
        # idempotency evidence; split_out/split_in are the internal
        # custody-side half of a Quality command (already idempotent at
        # the InventoryQualityCommand layer) and never carry their own.
        CheckConstraint(
            "(movement_kind IN ('putaway', 'transfer') AND client_command_id IS NOT NULL "
            "  AND request_fingerprint IS NOT NULL) "
            "OR (movement_kind IN ('split_out', 'split_in') AND client_command_id IS NULL "
            "  AND request_fingerprint IS NULL)",
            name="ck_inventory_storage_movements_command_evidence_matches_kind",
        ),
        Index(
            "ux_inventory_storage_movements_tenant_client_command_id", "tenant_id", "client_command_id",
            unique=True, postgresql_where=text("client_command_id IS NOT NULL"),
        ),
        ForeignKeyConstraint(
            ["tenant_id", "inventory_quantity_cohort_id"],
            ["inventory_quantity_cohorts.tenant_id", "inventory_quantity_cohorts.id"],
            name="fk_inventory_storage_movements_tenant_cohort",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "source_location_id"],
            ["locations.tenant_id", "locations.farm_id", "locations.id"],
            name="fk_inventory_storage_movements_tenant_farm_src_location",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "destination_location_id"],
            ["locations.tenant_id", "locations.farm_id", "locations.id"],
            name="fk_inventory_storage_movements_tenant_farm_dest_location",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_inventory_storage_movements_tenant_id_id"),
    )
