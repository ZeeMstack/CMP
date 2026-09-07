"""STORE-INV-002A.1: InventoryItemPackaging -- tenant-scoped, item-specific
packaging/display units (e.g. `BAG-25KG`), never a `UnitOfMeasure` row
(`docs/domain/STORE_INVENTORY_MODEL.md` §5/§L). Follows
`inventory_category_service.py`'s idempotency idiom exactly (reversible
`active <-> inactive`, one independent idempotency pair per command
direction), widened with a structural freeze on `package_quantity` once any
`GoodsReceiptLine` references the row -- mirroring
`carrier_specification_service._is_referenced` precisely."""

import hashlib
import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.goods_receipt_line import GoodsReceiptLine
from app.models.inventory_item import InventoryItem
from app.models.inventory_item_packaging import InventoryItemPackaging
from app.services.audit import append_audit_event
from app.services.errors import (
    DuplicateInventoryItemPackagingCodeError,
    InventoryItemNotFoundError,
    InventoryItemPackagingCommandReusedWithDifferentPayloadError,
    InventoryItemPackagingDeactivationReusedWithDifferentPayloadError,
    InventoryItemPackagingNotActiveError,
    InventoryItemPackagingNotFoundError,
    InventoryItemPackagingNotInactiveError,
    InventoryItemPackagingReactivationReusedWithDifferentPayloadError,
    InventoryItemPackagingStructurallyLockedError,
    InventoryItemPackagingUpdateReusedWithDifferentPayloadError,
)


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _require_item(db: Session, *, tenant_id: uuid.UUID, inventory_item_id: uuid.UUID) -> None:
    item = db.execute(
        select(InventoryItem.id).where(InventoryItem.id == inventory_item_id, InventoryItem.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if item is None:
        raise InventoryItemNotFoundError(str(inventory_item_id))


def _is_referenced(db: Session, *, packaging_id: uuid.UUID) -> bool:
    return (
        db.execute(
            select(func.count()).select_from(GoodsReceiptLine).where(GoodsReceiptLine.packaging_id == packaging_id)
        ).scalar_one()
        > 0
    )


def _compute_create_fingerprint(
    *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID | None, inventory_item_id: uuid.UUID, code: str,
    display_name: str, package_quantity: Decimal,
) -> str:
    parts = [
        str(tenant_id), str(actor_user_id) if actor_user_id else "", str(inventory_item_id), code, display_name,
        str(package_quantity),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _compute_update_fingerprint(
    *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID | None, packaging_id: uuid.UUID, display_name: str,
    package_quantity: Decimal,
) -> str:
    parts = [
        str(tenant_id), str(actor_user_id) if actor_user_id else "", str(packaging_id), display_name,
        str(package_quantity),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _compute_status_fingerprint(
    *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID | None, packaging_id: uuid.UUID
) -> str:
    parts = [str(tenant_id), str(actor_user_id) if actor_user_id else "", str(packaging_id)]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def register_inventory_item_packaging(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    client_command_id: uuid.UUID,
    inventory_item_id: uuid.UUID,
    code: str,
    display_name: str,
    package_quantity: Decimal,
) -> InventoryItemPackaging:
    fingerprint = _compute_create_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, inventory_item_id=inventory_item_id, code=code,
        display_name=display_name, package_quantity=package_quantity,
    )

    existing = db.execute(
        select(InventoryItemPackaging).where(
            InventoryItemPackaging.tenant_id == tenant_id,
            InventoryItemPackaging.client_command_id == client_command_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise InventoryItemPackagingCommandReusedWithDifferentPayloadError(str(client_command_id))

    _require_item(db, tenant_id=tenant_id, inventory_item_id=inventory_item_id)

    packaging = InventoryItemPackaging(
        tenant_id=tenant_id, inventory_item_id=inventory_item_id, code=code, display_name=display_name,
        package_quantity=package_quantity, status="active", client_command_id=client_command_id,
        request_fingerprint=fingerprint,
    )
    db.add(packaging)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_inventory_item_packaging_tenant_client_command_id":
            replay = db.execute(
                select(InventoryItemPackaging).where(
                    InventoryItemPackaging.tenant_id == tenant_id,
                    InventoryItemPackaging.client_command_id == client_command_id,
                )
            ).scalar_one_or_none()
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise InventoryItemPackagingCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        if constraint == "ux_inventory_item_packaging_item_code_lower":
            raise DuplicateInventoryItemPackagingCodeError(f"{tenant_id}:{inventory_item_id}:{code}") from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="inventory_item_packaging.created",
        entity_type="inventory_item_packaging", entity_id=packaging.id,
        event_data={
            "inventory_item_id": str(inventory_item_id), "code": packaging.code,
            "display_name": packaging.display_name, "package_quantity": str(package_quantity),
        },
    )
    db.commit()
    db.refresh(packaging)
    return packaging


def get_inventory_item_packaging(
    db: Session, *, tenant_id: uuid.UUID, packaging_id: uuid.UUID
) -> InventoryItemPackaging:
    packaging = db.execute(
        select(InventoryItemPackaging).where(
            InventoryItemPackaging.id == packaging_id, InventoryItemPackaging.tenant_id == tenant_id
        )
    ).scalar_one_or_none()
    if packaging is None:
        raise InventoryItemPackagingNotFoundError(str(packaging_id))
    return packaging


def list_inventory_item_packaging(
    db: Session, *, tenant_id: uuid.UUID, inventory_item_id: uuid.UUID | None = None,
    status: str | None = None,
) -> list[InventoryItemPackaging]:
    query = select(InventoryItemPackaging).where(InventoryItemPackaging.tenant_id == tenant_id)
    if inventory_item_id is not None:
        query = query.where(InventoryItemPackaging.inventory_item_id == inventory_item_id)
    if status is not None:
        query = query.where(InventoryItemPackaging.status == status)
    return list(db.execute(query.order_by(InventoryItemPackaging.code)).scalars())


def _lock_packaging(db: Session, *, tenant_id: uuid.UUID, packaging_id: uuid.UUID) -> InventoryItemPackaging:
    packaging = db.execute(
        select(InventoryItemPackaging)
        .where(InventoryItemPackaging.id == packaging_id, InventoryItemPackaging.tenant_id == tenant_id)
        .with_for_update()
    ).scalar_one_or_none()
    if packaging is None:
        raise InventoryItemPackagingNotFoundError(str(packaging_id))
    return packaging


def update_inventory_item_packaging(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    client_command_id: uuid.UUID,
    packaging_id: uuid.UUID,
    display_name: str,
    package_quantity: Decimal,
) -> InventoryItemPackaging:
    fingerprint = _compute_update_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, packaging_id=packaging_id, display_name=display_name,
        package_quantity=package_quantity,
    )

    def _find_by_update_command() -> InventoryItemPackaging | None:
        return db.execute(
            select(InventoryItemPackaging).where(
                InventoryItemPackaging.tenant_id == tenant_id,
                InventoryItemPackaging.update_client_command_id == client_command_id,
            )
        ).scalar_one_or_none()

    existing = _find_by_update_command()
    if existing is not None:
        if existing.update_request_fingerprint == fingerprint:
            return existing
        raise InventoryItemPackagingUpdateReusedWithDifferentPayloadError(str(client_command_id))

    packaging = _lock_packaging(db, tenant_id=tenant_id, packaging_id=packaging_id)

    existing = _find_by_update_command()
    if existing is not None:
        if existing.update_request_fingerprint == fingerprint:
            return existing
        raise InventoryItemPackagingUpdateReusedWithDifferentPayloadError(str(client_command_id))

    # Structural freeze: package_quantity locks the instant any
    # GoodsReceiptLine references this row -- display_name stays editable
    # regardless (mirrors CarrierSpecification's own structural-field-only
    # freeze).
    if packaging.package_quantity != package_quantity and _is_referenced(db, packaging_id=packaging.id):
        raise InventoryItemPackagingStructurallyLockedError(str(packaging_id))

    packaging.display_name = display_name
    packaging.package_quantity = package_quantity
    packaging.update_client_command_id = client_command_id
    packaging.update_request_fingerprint = fingerprint
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_inventory_item_packaging_tenant_update_command":
            replay = _find_by_update_command()
            if replay is not None and replay.update_request_fingerprint == fingerprint:
                return replay
            raise InventoryItemPackagingUpdateReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="inventory_item_packaging.updated",
        entity_type="inventory_item_packaging", entity_id=packaging.id,
        event_data={"display_name": packaging.display_name, "package_quantity": str(package_quantity)},
    )
    db.commit()
    db.refresh(packaging)
    return packaging


def deactivate_inventory_item_packaging(
    db: Session, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID | None, client_command_id: uuid.UUID,
    packaging_id: uuid.UUID,
) -> InventoryItemPackaging:
    fingerprint = _compute_status_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, packaging_id=packaging_id
    )

    def _find_by_command() -> InventoryItemPackaging | None:
        return db.execute(
            select(InventoryItemPackaging).where(
                InventoryItemPackaging.tenant_id == tenant_id,
                InventoryItemPackaging.deactivation_client_command_id == client_command_id,
            )
        ).scalar_one_or_none()

    existing = _find_by_command()
    if existing is not None:
        if existing.deactivation_request_fingerprint == fingerprint:
            return existing
        raise InventoryItemPackagingDeactivationReusedWithDifferentPayloadError(str(client_command_id))

    packaging = _lock_packaging(db, tenant_id=tenant_id, packaging_id=packaging_id)

    existing = _find_by_command()
    if existing is not None:
        if existing.deactivation_request_fingerprint == fingerprint:
            return existing
        raise InventoryItemPackagingDeactivationReusedWithDifferentPayloadError(str(client_command_id))

    if packaging.status != "active":
        raise InventoryItemPackagingNotActiveError(str(packaging_id))

    packaging.status = "inactive"
    packaging.deactivation_client_command_id = client_command_id
    packaging.deactivation_request_fingerprint = fingerprint
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_inventory_item_packaging_tenant_deactivation_command":
            replay = _find_by_command()
            if replay is not None and replay.deactivation_request_fingerprint == fingerprint:
                return replay
            raise InventoryItemPackagingDeactivationReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="inventory_item_packaging.deactivated",
        entity_type="inventory_item_packaging", entity_id=packaging.id, event_data={"code": packaging.code},
    )
    db.commit()
    db.refresh(packaging)
    return packaging


def reactivate_inventory_item_packaging(
    db: Session, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID | None, client_command_id: uuid.UUID,
    packaging_id: uuid.UUID,
) -> InventoryItemPackaging:
    fingerprint = _compute_status_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, packaging_id=packaging_id
    )

    def _find_by_command() -> InventoryItemPackaging | None:
        return db.execute(
            select(InventoryItemPackaging).where(
                InventoryItemPackaging.tenant_id == tenant_id,
                InventoryItemPackaging.reactivation_client_command_id == client_command_id,
            )
        ).scalar_one_or_none()

    existing = _find_by_command()
    if existing is not None:
        if existing.reactivation_request_fingerprint == fingerprint:
            return existing
        raise InventoryItemPackagingReactivationReusedWithDifferentPayloadError(str(client_command_id))

    packaging = _lock_packaging(db, tenant_id=tenant_id, packaging_id=packaging_id)

    existing = _find_by_command()
    if existing is not None:
        if existing.reactivation_request_fingerprint == fingerprint:
            return existing
        raise InventoryItemPackagingReactivationReusedWithDifferentPayloadError(str(client_command_id))

    if packaging.status != "inactive":
        raise InventoryItemPackagingNotInactiveError(str(packaging_id))

    packaging.status = "active"
    packaging.reactivation_client_command_id = client_command_id
    packaging.reactivation_request_fingerprint = fingerprint
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_inventory_item_packaging_tenant_reactivation_command":
            replay = _find_by_command()
            if replay is not None and replay.reactivation_request_fingerprint == fingerprint:
                return replay
            raise InventoryItemPackagingReactivationReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="inventory_item_packaging.reactivated",
        entity_type="inventory_item_packaging", entity_id=packaging.id, event_data={"code": packaging.code},
    )
    db.commit()
    db.refresh(packaging)
    return packaging
