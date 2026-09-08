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
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

EVENT_KINDS = ("consumption", "return", "scrap")
SOURCE_KINDS = ("issued", "store_bin", "not_put_away")


class InventoryMaterialEvent(Base):
    """STORE-INV-004: the single append-only settlement/event model for
    Consumption, Return, and Scrap of consumable Inventory (`docs/domain/
    STORE_INVENTORY_MODEL.md`) -- completes the lifecycle Receipt -> Putaway
    -> Reservation -> Issue -> Consumption/Return/Scrap. Never collapses
    Existence, physical custody, Reservation, or Issue-line reconciliation;
    each row is its OWN top-level idempotent operator command (unlike
    `split_out`/`split_in`/`issue`, none of these three are internally
    composed by a larger command).

    `event_kind`: `consumption` (material actually used by farm operations
    -- reduces Existence, reduces Issue-line outstanding, never touches
    custody), `return` (unused issued material physically comes back to a
    Store Bin -- reduces Issue-line outstanding, increases Bin custody,
    Existence unchanged), `scrap` (material physically ceases to exist --
    reduces Existence, from exactly one of the three source buckets, always
    a mandatory human-readable `reason`).

    `source_kind` names which bucket this event acts against: `issued`
    (Consumption, Return, and Scrap-from-issued alike -- `issue_line_id`
    is the specific `InventoryStorageMovement` row, `movement_kind =
    'issue'`, being settled), `store_bin` (Scrap only -- `source_location_id`
    is the specific Bin), or `not_put_away` (Scrap only -- no location at
    all, mirrors how a partial Quality action against "Not put away" writes
    no storage-movement row either).

    `existence_ledger_entry_id` is set exactly for Consumption and every
    Scrap flavor (the paired negative `InventoryExistenceLedgerEntry`);
    `storage_movement_id` is set exactly for Return (the paired `return`
    movement into the destination Bin) and Scrap-from-Bin (the paired
    `scrap_bin` movement out of the source Bin) -- Consumption,
    Scrap-from-issued, and Scrap-from-not-put-away write no storage-movement
    row at all, since none of them touch physical Bin custody."""

    __tablename__ = "inventory_material_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    inventory_quantity_cohort_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inventory_quantity_cohorts.id"), nullable=False
    )
    event_kind: Mapped[str] = mapped_column(String, nullable=False)
    source_kind: Mapped[str] = mapped_column(String, nullable=False)
    issue_line_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    source_location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id"), nullable=True)
    destination_location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id"), nullable=True)
    quantity_base: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    existence_ledger_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("inventory_existence_ledger_entries.id"), nullable=True
    )
    storage_movement_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("inventory_storage_movements.id"), nullable=True
    )
    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "event_kind IN ('consumption', 'return', 'scrap')", name="ck_inventory_material_events_kind_allowed"
        ),
        CheckConstraint(
            "source_kind IN ('issued', 'store_bin', 'not_put_away')",
            name="ck_inventory_material_events_source_kind_allowed",
        ),
        CheckConstraint(
            "quantity_base > 0 AND quantity_base = trunc(quantity_base, 3) AND quantity_base < 100000000000",
            name="ck_inventory_material_events_quantity_positive",
        ),
        CheckConstraint(
            "event_kind <> 'scrap' OR reason IS NOT NULL", name="ck_inventory_material_events_scrap_reason_required"
        ),
        # Exhaustive shape per (event_kind, source_kind) combination -- the
        # only five combinations this table ever accepts.
        CheckConstraint(
            "(event_kind = 'consumption' AND source_kind = 'issued' AND issue_line_id IS NOT NULL "
            "  AND source_location_id IS NULL AND destination_location_id IS NULL "
            "  AND existence_ledger_entry_id IS NOT NULL AND storage_movement_id IS NULL) "
            "OR (event_kind = 'return' AND source_kind = 'issued' AND issue_line_id IS NOT NULL "
            "  AND source_location_id IS NULL AND destination_location_id IS NOT NULL "
            "  AND existence_ledger_entry_id IS NULL AND storage_movement_id IS NOT NULL) "
            "OR (event_kind = 'scrap' AND source_kind = 'issued' AND issue_line_id IS NOT NULL "
            "  AND source_location_id IS NULL AND destination_location_id IS NULL "
            "  AND existence_ledger_entry_id IS NOT NULL AND storage_movement_id IS NULL) "
            "OR (event_kind = 'scrap' AND source_kind = 'store_bin' AND issue_line_id IS NULL "
            "  AND source_location_id IS NOT NULL AND destination_location_id IS NULL "
            "  AND existence_ledger_entry_id IS NOT NULL AND storage_movement_id IS NOT NULL) "
            "OR (event_kind = 'scrap' AND source_kind = 'not_put_away' AND issue_line_id IS NULL "
            "  AND source_location_id IS NULL AND destination_location_id IS NULL "
            "  AND existence_ledger_entry_id IS NOT NULL AND storage_movement_id IS NULL)",
            name="ck_inventory_material_events_shape_matches_kind",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_inventory_material_events_tenant_id_id"),
        Index(
            "ux_inventory_material_events_tenant_client_command_id", "tenant_id", "client_command_id", unique=True
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id"], ["farms.tenant_id", "farms.id"], name="fk_inventory_material_events_tenant_farm"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "inventory_quantity_cohort_id"],
            ["inventory_quantity_cohorts.tenant_id", "inventory_quantity_cohorts.id"],
            name="fk_inventory_material_events_tenant_cohort",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "issue_line_id"], ["inventory_storage_movements.tenant_id", "inventory_storage_movements.id"],
            name="fk_inventory_material_events_tenant_issue_line",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "source_location_id"],
            ["locations.tenant_id", "locations.farm_id", "locations.id"],
            name="fk_inventory_material_events_tenant_farm_src_location",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "destination_location_id"],
            ["locations.tenant_id", "locations.farm_id", "locations.id"],
            name="fk_inventory_material_events_tenant_farm_dest_location",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "existence_ledger_entry_id"],
            ["inventory_existence_ledger_entries.tenant_id", "inventory_existence_ledger_entries.id"],
            name="fk_inventory_material_events_tenant_ledger_entry",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "storage_movement_id"],
            ["inventory_storage_movements.tenant_id", "inventory_storage_movements.id"],
            name="fk_inventory_material_events_tenant_storage_movement",
        ),
    )
