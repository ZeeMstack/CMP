"""STORE-INV-001B: InventoryItem -- tenant-scoped consumable-material
master. Same idempotency idiom as `inventory_category_service.py`
(itself following `packaging_unit_service.py`), widened with an extra
`update_*` idempotency pair since, unlike `PackagingUnit`, several fields
besides `name` are mutable here (`docs/domain/STORE_INVENTORY_MODEL.md`
§5). `base_uom_id` freeze is deliberately NOT implemented -- no
`InventoryLot` exists yet in this ticket to check a reference against; see
the model's own docstring and STORE-INV-002A's future scope."""

import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.inventory_category import InventoryCategory
from app.models.inventory_item import InventoryItem
from app.services import unit_of_measure_service
from app.services.audit import append_audit_event
from app.services.errors import (
    DuplicateInventoryItemCodeError,
    InventoryCategoryInactiveForAssignmentError,
    InventoryCategoryNotInTenantError,
    InventoryItemCommandReusedWithDifferentPayloadError,
    InventoryItemDeactivationReusedWithDifferentPayloadError,
    InventoryItemNotActiveError,
    InventoryItemNotFoundError,
    InventoryItemNotInactiveError,
    InventoryItemReactivationReusedWithDifferentPayloadError,
    InventoryItemTrackingPolicyInvalidError,
    InventoryItemUpdateReusedWithDifferentPayloadError,
)


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _validate_tracking_policy(
    *, lot_tracking_required: bool, expiry_tracking_required: bool, qc_release_required: bool
) -> None:
    if expiry_tracking_required and not lot_tracking_required:
        raise InventoryItemTrackingPolicyInvalidError("expiry_tracking_required requires lot_tracking_required")
    if qc_release_required and not lot_tracking_required:
        raise InventoryItemTrackingPolicyInvalidError("qc_release_required requires lot_tracking_required")


def _require_active_category_in_tenant(db: Session, *, tenant_id: uuid.UUID, category_id: uuid.UUID) -> None:
    """A new assignment (create, or reassigning an existing InventoryItem
    to a different category) requires an active InventoryCategory. An
    InventoryItem already assigned to a category that later becomes
    inactive is untouched -- this check only ever gates a NEW assignment,
    never revisits an existing one (docs/domain/STORE_INVENTORY_MODEL.md
    §5). Category deactivation itself is never blocked by this check --
    it lives entirely on the InventoryItem write path, not on
    `deactivate_inventory_category`."""
    category = db.execute(
        select(InventoryCategory).where(
            InventoryCategory.id == category_id, InventoryCategory.tenant_id == tenant_id
        )
    ).scalar_one_or_none()
    if category is None:
        raise InventoryCategoryNotInTenantError(str(category_id))
    if category.status != "active":
        raise InventoryCategoryInactiveForAssignmentError(str(category_id))


def _compute_create_fingerprint(
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    code: str,
    name: str,
    category_id: uuid.UUID,
    base_uom_id: uuid.UUID,
    lot_tracking_required: bool,
    expiry_tracking_required: bool,
    qc_release_required: bool,
) -> str:
    parts = [
        str(tenant_id), str(actor_user_id) if actor_user_id else "", code, name, str(category_id),
        str(base_uom_id), str(lot_tracking_required), str(expiry_tracking_required), str(qc_release_required),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _compute_update_fingerprint(
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    item_id: uuid.UUID,
    name: str,
    category_id: uuid.UUID,
    base_uom_id: uuid.UUID,
    lot_tracking_required: bool,
    expiry_tracking_required: bool,
    qc_release_required: bool,
) -> str:
    parts = [
        str(tenant_id), str(actor_user_id) if actor_user_id else "", str(item_id), name, str(category_id),
        str(base_uom_id), str(lot_tracking_required), str(expiry_tracking_required), str(qc_release_required),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _compute_status_fingerprint(
    *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID | None, item_id: uuid.UUID
) -> str:
    parts = [str(tenant_id), str(actor_user_id) if actor_user_id else "", str(item_id)]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def register_inventory_item(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    client_command_id: uuid.UUID,
    code: str,
    name: str,
    category_id: uuid.UUID,
    base_uom_id: uuid.UUID,
    lot_tracking_required: bool,
    expiry_tracking_required: bool,
    qc_release_required: bool,
) -> InventoryItem:
    _validate_tracking_policy(
        lot_tracking_required=lot_tracking_required, expiry_tracking_required=expiry_tracking_required,
        qc_release_required=qc_release_required,
    )
    fingerprint = _compute_create_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, code=code, name=name, category_id=category_id,
        base_uom_id=base_uom_id, lot_tracking_required=lot_tracking_required,
        expiry_tracking_required=expiry_tracking_required, qc_release_required=qc_release_required,
    )

    existing = db.execute(
        select(InventoryItem).where(
            InventoryItem.tenant_id == tenant_id, InventoryItem.client_command_id == client_command_id
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise InventoryItemCommandReusedWithDifferentPayloadError(str(client_command_id))

    _require_active_category_in_tenant(db, tenant_id=tenant_id, category_id=category_id)
    unit_of_measure_service.get_uom(db, uom_id=base_uom_id)

    item = InventoryItem(
        tenant_id=tenant_id, code=code, name=name, inventory_category_id=category_id, base_uom_id=base_uom_id,
        lot_tracking_required=lot_tracking_required, expiry_tracking_required=expiry_tracking_required,
        qc_release_required=qc_release_required, status="active", client_command_id=client_command_id,
        request_fingerprint=fingerprint,
    )
    db.add(item)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_inventory_items_tenant_client_command_id":
            replay = db.execute(
                select(InventoryItem).where(
                    InventoryItem.tenant_id == tenant_id, InventoryItem.client_command_id == client_command_id
                )
            ).scalar_one_or_none()
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise InventoryItemCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        if constraint == "ux_inventory_items_tenant_code_lower":
            raise DuplicateInventoryItemCodeError(f"{tenant_id}:{code}") from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="inventory_item.created",
        entity_type="inventory_item", entity_id=item.id,
        event_data={
            "code": item.code, "name": item.name, "category_id": str(category_id), "base_uom_id": str(base_uom_id),
            "lot_tracking_required": lot_tracking_required, "expiry_tracking_required": expiry_tracking_required,
            "qc_release_required": qc_release_required,
        },
    )
    db.commit()
    db.refresh(item)
    return item


def get_inventory_item(db: Session, *, tenant_id: uuid.UUID, item_id: uuid.UUID) -> InventoryItem:
    item = db.execute(
        select(InventoryItem).where(InventoryItem.id == item_id, InventoryItem.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if item is None:
        raise InventoryItemNotFoundError(str(item_id))
    return item


def list_inventory_items(
    db: Session, *, tenant_id: uuid.UUID, status: str | None = None, category_id: uuid.UUID | None = None
) -> list[InventoryItem]:
    query = select(InventoryItem).where(InventoryItem.tenant_id == tenant_id)
    if status is not None:
        query = query.where(InventoryItem.status == status)
    if category_id is not None:
        query = query.where(InventoryItem.inventory_category_id == category_id)
    return list(db.execute(query.order_by(InventoryItem.code)).scalars())


def _lock_item(db: Session, *, tenant_id: uuid.UUID, item_id: uuid.UUID) -> InventoryItem:
    item = db.execute(
        select(InventoryItem)
        .where(InventoryItem.id == item_id, InventoryItem.tenant_id == tenant_id)
        .with_for_update()
    ).scalar_one_or_none()
    if item is None:
        raise InventoryItemNotFoundError(str(item_id))
    return item


def update_inventory_item(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    client_command_id: uuid.UUID,
    item_id: uuid.UUID,
    name: str,
    category_id: uuid.UUID,
    base_uom_id: uuid.UUID,
    lot_tracking_required: bool,
    expiry_tracking_required: bool,
    qc_release_required: bool,
) -> InventoryItem:
    _validate_tracking_policy(
        lot_tracking_required=lot_tracking_required, expiry_tracking_required=expiry_tracking_required,
        qc_release_required=qc_release_required,
    )
    fingerprint = _compute_update_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, item_id=item_id, name=name, category_id=category_id,
        base_uom_id=base_uom_id, lot_tracking_required=lot_tracking_required,
        expiry_tracking_required=expiry_tracking_required, qc_release_required=qc_release_required,
    )

    def _find_by_update_command() -> InventoryItem | None:
        return db.execute(
            select(InventoryItem).where(
                InventoryItem.tenant_id == tenant_id, InventoryItem.update_client_command_id == client_command_id
            )
        ).scalar_one_or_none()

    existing = _find_by_update_command()
    if existing is not None:
        if existing.update_request_fingerprint == fingerprint:
            return existing
        raise InventoryItemUpdateReusedWithDifferentPayloadError(str(client_command_id))

    item = _lock_item(db, tenant_id=tenant_id, item_id=item_id)

    existing = _find_by_update_command()
    if existing is not None:
        if existing.update_request_fingerprint == fingerprint:
            return existing
        raise InventoryItemUpdateReusedWithDifferentPayloadError(str(client_command_id))

    # Only an actual reassignment (a different category_id than the item
    # already carries) is gated on the target category being active --
    # resubmitting the item's own current category unchanged (e.g. while
    # only renaming it) must keep working even after that category has
    # since gone inactive, or the item would become permanently uneditable
    # (docs/domain/STORE_INVENTORY_MODEL.md §5: an existing reference to a
    # since-deactivated category remains valid).
    if category_id != item.inventory_category_id:
        _require_active_category_in_tenant(db, tenant_id=tenant_id, category_id=category_id)
    unit_of_measure_service.get_uom(db, uom_id=base_uom_id)

    item.name = name
    item.inventory_category_id = category_id
    item.base_uom_id = base_uom_id
    item.lot_tracking_required = lot_tracking_required
    item.expiry_tracking_required = expiry_tracking_required
    item.qc_release_required = qc_release_required
    item.update_client_command_id = client_command_id
    item.update_request_fingerprint = fingerprint
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_inventory_items_tenant_update_command":
            replay = _find_by_update_command()
            if replay is not None and replay.update_request_fingerprint == fingerprint:
                return replay
            raise InventoryItemUpdateReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="inventory_item.updated",
        entity_type="inventory_item", entity_id=item.id,
        event_data={
            "name": item.name, "category_id": str(category_id), "base_uom_id": str(base_uom_id),
            "lot_tracking_required": lot_tracking_required, "expiry_tracking_required": expiry_tracking_required,
            "qc_release_required": qc_release_required,
        },
    )
    db.commit()
    db.refresh(item)
    return item


def deactivate_inventory_item(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    client_command_id: uuid.UUID,
    item_id: uuid.UUID,
) -> InventoryItem:
    fingerprint = _compute_status_fingerprint(tenant_id=tenant_id, actor_user_id=actor_user_id, item_id=item_id)

    def _find_by_command() -> InventoryItem | None:
        return db.execute(
            select(InventoryItem).where(
                InventoryItem.tenant_id == tenant_id,
                InventoryItem.deactivation_client_command_id == client_command_id,
            )
        ).scalar_one_or_none()

    existing = _find_by_command()
    if existing is not None:
        if existing.deactivation_request_fingerprint == fingerprint:
            return existing
        raise InventoryItemDeactivationReusedWithDifferentPayloadError(str(client_command_id))

    item = _lock_item(db, tenant_id=tenant_id, item_id=item_id)

    existing = _find_by_command()
    if existing is not None:
        if existing.deactivation_request_fingerprint == fingerprint:
            return existing
        raise InventoryItemDeactivationReusedWithDifferentPayloadError(str(client_command_id))

    if item.status != "active":
        raise InventoryItemNotActiveError(str(item_id))

    item.status = "inactive"
    item.deactivation_client_command_id = client_command_id
    item.deactivation_request_fingerprint = fingerprint
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_inventory_items_tenant_deactivation_command":
            replay = _find_by_command()
            if replay is not None and replay.deactivation_request_fingerprint == fingerprint:
                return replay
            raise InventoryItemDeactivationReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="inventory_item.deactivated",
        entity_type="inventory_item", entity_id=item.id, event_data={"code": item.code},
    )
    db.commit()
    db.refresh(item)
    return item


def reactivate_inventory_item(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    client_command_id: uuid.UUID,
    item_id: uuid.UUID,
) -> InventoryItem:
    fingerprint = _compute_status_fingerprint(tenant_id=tenant_id, actor_user_id=actor_user_id, item_id=item_id)

    def _find_by_command() -> InventoryItem | None:
        return db.execute(
            select(InventoryItem).where(
                InventoryItem.tenant_id == tenant_id,
                InventoryItem.reactivation_client_command_id == client_command_id,
            )
        ).scalar_one_or_none()

    existing = _find_by_command()
    if existing is not None:
        if existing.reactivation_request_fingerprint == fingerprint:
            return existing
        raise InventoryItemReactivationReusedWithDifferentPayloadError(str(client_command_id))

    item = _lock_item(db, tenant_id=tenant_id, item_id=item_id)

    existing = _find_by_command()
    if existing is not None:
        if existing.reactivation_request_fingerprint == fingerprint:
            return existing
        raise InventoryItemReactivationReusedWithDifferentPayloadError(str(client_command_id))

    if item.status != "inactive":
        raise InventoryItemNotInactiveError(str(item_id))

    item.status = "active"
    item.reactivation_client_command_id = client_command_id
    item.reactivation_request_fingerprint = fingerprint
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_inventory_items_tenant_reactivation_command":
            replay = _find_by_command()
            if replay is not None and replay.reactivation_request_fingerprint == fingerprint:
                return replay
            raise InventoryItemReactivationReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="inventory_item.reactivated",
        entity_type="inventory_item", entity_id=item.id, event_data={"code": item.code},
    )
    db.commit()
    db.refresh(item)
    return item
