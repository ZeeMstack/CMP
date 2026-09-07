"""STORE-INV-002A.1: InventoryLot -- the tenant-wide traceable
manufacturer-lot identity (`docs/domain/STORE_INVENTORY_MODEL.md` §7/§C).
Fully immutable once created; this module only ever resolves-or-creates,
never updates. Canonical identity/matching key is `(tenant_id,
inventory_item_id, lower(trim(manufacturer_name)),
lower(trim(manufacturer_lot_reference)))` ONLY -- `manufacturing_date`/
`expiry_date` are immutable attributes of that identity, compared for
compatibility on a canonical-key match, never folded into the matching key
itself (STORE-INV-002A final domain closure, issue A1)."""

import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.inventory_lot import InventoryLot
from app.services.errors import ConflictingInventoryLotIdentityError


def _find_canonical(
    db: Session, *, tenant_id: uuid.UUID, inventory_item_id: uuid.UUID, manufacturer_name: str,
    manufacturer_lot_reference: str,
) -> InventoryLot | None:
    normalized_name = manufacturer_name.strip().lower()
    normalized_ref = manufacturer_lot_reference.strip().lower()
    return db.execute(
        select(InventoryLot).where(
            InventoryLot.tenant_id == tenant_id,
            InventoryLot.inventory_item_id == inventory_item_id,
            func.lower(func.trim(InventoryLot.manufacturer_name)) == normalized_name,
            func.lower(func.trim(InventoryLot.manufacturer_lot_reference)) == normalized_ref,
        )
    ).scalar_one_or_none()


def _next_code(db: Session, *, tenant_id: uuid.UUID, inventory_item_id: uuid.UUID, item_code: str) -> str:
    # Serializes concurrent lot creation for the same (tenant, item) so two
    # racing receipts never generate the same sequential code -- mirrors
    # NURSERY-OPS-001's own pg_advisory_xact_lock-keyed sequential-code
    # idiom (no new sequence table).
    db.execute(
        select(func.pg_advisory_xact_lock(func.hashtextextended(f"inventory_lot_code:{tenant_id}:{inventory_item_id}", 0)))
    )
    count = db.execute(
        select(func.count()).select_from(InventoryLot).where(
            InventoryLot.tenant_id == tenant_id, InventoryLot.inventory_item_id == inventory_item_id
        )
    ).scalar_one()
    return f"LOT-{item_code}-{count + 1:04d}"


def resolve_or_create_inventory_lot(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    inventory_item_id: uuid.UUID,
    item_code: str,
    manufacturer_name: str | None,
    manufacturer_lot_reference: str | None,
    manufacturing_date: date | None,
    expiry_date: date | None,
) -> InventoryLot:
    """Validate + insert + flush only (no commit, NO internal
    `IntegrityError` catch/rollback) -- a core function composed inside
    `goods_receipt_service`'s own single atomic transaction, following the
    same `_create_batch_core`/`_sow_batch_core` convention: a core function
    never catches `IntegrityError` itself; the caller wraps its own call
    site and handles the possible constraint name (see
    `goods_receipt_service.record_goods_receipt`). Incomplete manufacturer
    identity (either field missing) is never auto-matched -- always creates
    a new, distinct lot."""
    if manufacturer_name is not None and manufacturer_lot_reference is not None:
        existing = _find_canonical(
            db, tenant_id=tenant_id, inventory_item_id=inventory_item_id, manufacturer_name=manufacturer_name,
            manufacturer_lot_reference=manufacturer_lot_reference,
        )
        if existing is not None:
            if existing.manufacturing_date == manufacturing_date and existing.expiry_date == expiry_date:
                return existing
            raise ConflictingInventoryLotIdentityError(
                f"{tenant_id}:{inventory_item_id}:{manufacturer_name}:{manufacturer_lot_reference}"
            )

    code = _next_code(db, tenant_id=tenant_id, inventory_item_id=inventory_item_id, item_code=item_code)
    lot = InventoryLot(
        tenant_id=tenant_id, inventory_item_id=inventory_item_id, code=code,
        manufacturer_name=manufacturer_name, manufacturer_lot_reference=manufacturer_lot_reference,
        manufacturing_date=manufacturing_date, expiry_date=expiry_date, created_by_user_id=actor_user_id,
    )
    db.add(lot)
    db.flush()
    return lot
