"""STORE-INV-002A.1: company-wide existence read model
(`docs/domain/STORE_INVENTORY_MODEL.md` §13/§U). Always derived from the
existence ledger, always company-wide (never claiming current Farm/Store/
Bin/available/reserved -- those don't exist until STORE-INV-002B/003).
`receiving_farm_id` on a cohort/line is historical provenance -- "Received
at <Farm>" -- never a current-location claim."""

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.inventory_existence_ledger_entry import InventoryExistenceLedgerEntry
from app.models.inventory_quantity_cohort import InventoryQuantityCohort


def get_item_existence(db: Session, *, tenant_id: uuid.UUID, inventory_item_id: uuid.UUID) -> Decimal:
    return db.execute(
        select(func.coalesce(func.sum(InventoryExistenceLedgerEntry.quantity_delta_base), 0)).where(
            InventoryExistenceLedgerEntry.tenant_id == tenant_id,
            InventoryExistenceLedgerEntry.inventory_item_id == inventory_item_id,
        )
    ).scalar_one()


def get_lot_existence(db: Session, *, tenant_id: uuid.UUID, inventory_lot_id: uuid.UUID) -> Decimal:
    return db.execute(
        select(func.coalesce(func.sum(InventoryExistenceLedgerEntry.quantity_delta_base), 0)).where(
            InventoryExistenceLedgerEntry.tenant_id == tenant_id,
            InventoryExistenceLedgerEntry.inventory_lot_id == inventory_lot_id,
        )
    ).scalar_one()


def list_item_cohort_provenance(
    db: Session, *, tenant_id: uuid.UUID, inventory_item_id: uuid.UUID
) -> list[dict]:
    """Drill-down rows: one per cohort contributing to this item's
    company-wide existence, with its current balance and receiving-Farm
    provenance -- never labeled as current location."""
    rows = db.execute(
        select(
            InventoryQuantityCohort.id,
            InventoryQuantityCohort.inventory_lot_id,
            InventoryQuantityCohort.source_goods_receipt_line_id,
            InventoryQuantityCohort.receiving_farm_id,
            func.coalesce(func.sum(InventoryExistenceLedgerEntry.quantity_delta_base), 0).label("balance"),
        )
        .join(
            InventoryExistenceLedgerEntry,
            InventoryExistenceLedgerEntry.inventory_quantity_cohort_id == InventoryQuantityCohort.id,
        )
        .where(
            InventoryQuantityCohort.tenant_id == tenant_id,
            InventoryQuantityCohort.inventory_item_id == inventory_item_id,
        )
        .group_by(
            InventoryQuantityCohort.id, InventoryQuantityCohort.inventory_lot_id,
            InventoryQuantityCohort.source_goods_receipt_line_id, InventoryQuantityCohort.receiving_farm_id,
        )
    ).all()
    return [
        {
            "inventory_quantity_cohort_id": row.id, "inventory_lot_id": row.inventory_lot_id,
            "source_goods_receipt_line_id": row.source_goods_receipt_line_id,
            "received_at_farm_id": row.receiving_farm_id, "balance": row.balance,
        }
        for row in rows
    ]
