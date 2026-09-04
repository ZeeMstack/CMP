"""STORE-INV-001B: InventoryCategory -- tenant-scoped classification/
reporting metadata only, never a business-behavior switch
(`docs/domain/STORE_INVENTORY_MODEL.md` §5). Follows `packaging_unit_
service.py`'s idempotency idiom (tenant-scoped `client_command_id` + SHA-256
fingerprint, pre/post-lock replay checks, IntegrityError fallback), widened
to a reversible `active <-> inactive` lifecycle (mirroring
`carrier_specification_service.py`'s own deactivate/reactivate shape) with
its own independent idempotency pair per direction rather than
`PackagingUnit`'s single one-way `retirement_*` pair."""

import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.inventory_category import InventoryCategory
from app.services.audit import append_audit_event
from app.services.errors import (
    DuplicateInventoryCategoryCodeError,
    InventoryCategoryCommandReusedWithDifferentPayloadError,
    InventoryCategoryDeactivationReusedWithDifferentPayloadError,
    InventoryCategoryNotActiveError,
    InventoryCategoryNotFoundError,
    InventoryCategoryNotInactiveError,
    InventoryCategoryReactivationReusedWithDifferentPayloadError,
)


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _compute_create_fingerprint(
    *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID | None, code: str, name: str
) -> str:
    parts = [str(tenant_id), str(actor_user_id) if actor_user_id else "", code, name]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _compute_update_fingerprint(
    *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID | None, category_id: uuid.UUID, name: str
) -> str:
    parts = [str(tenant_id), str(actor_user_id) if actor_user_id else "", str(category_id), name]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _compute_status_fingerprint(
    *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID | None, category_id: uuid.UUID
) -> str:
    parts = [str(tenant_id), str(actor_user_id) if actor_user_id else "", str(category_id)]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def register_inventory_category(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    client_command_id: uuid.UUID,
    code: str,
    name: str,
) -> InventoryCategory:
    fingerprint = _compute_create_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, code=code, name=name
    )

    existing = db.execute(
        select(InventoryCategory).where(
            InventoryCategory.tenant_id == tenant_id, InventoryCategory.client_command_id == client_command_id
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise InventoryCategoryCommandReusedWithDifferentPayloadError(str(client_command_id))

    category = InventoryCategory(
        tenant_id=tenant_id, code=code, name=name, status="active", client_command_id=client_command_id,
        request_fingerprint=fingerprint,
    )
    db.add(category)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_inventory_categories_tenant_client_command_id":
            replay = db.execute(
                select(InventoryCategory).where(
                    InventoryCategory.tenant_id == tenant_id,
                    InventoryCategory.client_command_id == client_command_id,
                )
            ).scalar_one_or_none()
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise InventoryCategoryCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        if constraint == "ux_inventory_categories_tenant_code_lower":
            raise DuplicateInventoryCategoryCodeError(f"{tenant_id}:{code}") from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="inventory_category.created",
        entity_type="inventory_category", entity_id=category.id,
        event_data={"code": category.code, "name": category.name},
    )
    db.commit()
    db.refresh(category)
    return category


def get_inventory_category(
    db: Session, *, tenant_id: uuid.UUID, category_id: uuid.UUID
) -> InventoryCategory:
    category = db.execute(
        select(InventoryCategory).where(
            InventoryCategory.id == category_id, InventoryCategory.tenant_id == tenant_id
        )
    ).scalar_one_or_none()
    if category is None:
        raise InventoryCategoryNotFoundError(str(category_id))
    return category


def list_inventory_categories(
    db: Session, *, tenant_id: uuid.UUID, status: str | None = None
) -> list[InventoryCategory]:
    query = select(InventoryCategory).where(InventoryCategory.tenant_id == tenant_id)
    if status is not None:
        query = query.where(InventoryCategory.status == status)
    return list(db.execute(query.order_by(InventoryCategory.code)).scalars())


def _lock_category(db: Session, *, tenant_id: uuid.UUID, category_id: uuid.UUID) -> InventoryCategory:
    category = db.execute(
        select(InventoryCategory)
        .where(InventoryCategory.id == category_id, InventoryCategory.tenant_id == tenant_id)
        .with_for_update()
    ).scalar_one_or_none()
    if category is None:
        raise InventoryCategoryNotFoundError(str(category_id))
    return category


def update_inventory_category(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    client_command_id: uuid.UUID,
    category_id: uuid.UUID,
    name: str,
) -> InventoryCategory:
    fingerprint = _compute_update_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, category_id=category_id, name=name
    )

    def _find_by_update_command() -> InventoryCategory | None:
        return db.execute(
            select(InventoryCategory).where(
                InventoryCategory.tenant_id == tenant_id,
                InventoryCategory.update_client_command_id == client_command_id,
            )
        ).scalar_one_or_none()

    existing = _find_by_update_command()
    if existing is not None:
        if existing.update_request_fingerprint == fingerprint:
            return existing
        raise InventoryCategoryCommandReusedWithDifferentPayloadError(str(client_command_id))

    category = _lock_category(db, tenant_id=tenant_id, category_id=category_id)

    existing = _find_by_update_command()
    if existing is not None:
        if existing.update_request_fingerprint == fingerprint:
            return existing
        raise InventoryCategoryCommandReusedWithDifferentPayloadError(str(client_command_id))

    category.name = name
    category.update_client_command_id = client_command_id
    category.update_request_fingerprint = fingerprint
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_inventory_categories_tenant_update_command":
            replay = _find_by_update_command()
            if replay is not None and replay.update_request_fingerprint == fingerprint:
                return replay
            raise InventoryCategoryCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="inventory_category.updated",
        entity_type="inventory_category", entity_id=category.id, event_data={"name": category.name},
    )
    db.commit()
    db.refresh(category)
    return category


def deactivate_inventory_category(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    client_command_id: uuid.UUID,
    category_id: uuid.UUID,
) -> InventoryCategory:
    fingerprint = _compute_status_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, category_id=category_id
    )

    def _find_by_command() -> InventoryCategory | None:
        return db.execute(
            select(InventoryCategory).where(
                InventoryCategory.tenant_id == tenant_id,
                InventoryCategory.deactivation_client_command_id == client_command_id,
            )
        ).scalar_one_or_none()

    existing = _find_by_command()
    if existing is not None:
        if existing.deactivation_request_fingerprint == fingerprint:
            return existing
        raise InventoryCategoryDeactivationReusedWithDifferentPayloadError(str(client_command_id))

    category = _lock_category(db, tenant_id=tenant_id, category_id=category_id)

    existing = _find_by_command()
    if existing is not None:
        if existing.deactivation_request_fingerprint == fingerprint:
            return existing
        raise InventoryCategoryDeactivationReusedWithDifferentPayloadError(str(client_command_id))

    if category.status != "active":
        raise InventoryCategoryNotActiveError(str(category_id))

    category.status = "inactive"
    category.deactivation_client_command_id = client_command_id
    category.deactivation_request_fingerprint = fingerprint
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_inventory_categories_tenant_deactivation_command":
            replay = _find_by_command()
            if replay is not None and replay.deactivation_request_fingerprint == fingerprint:
                return replay
            raise InventoryCategoryDeactivationReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="inventory_category.deactivated",
        entity_type="inventory_category", entity_id=category.id, event_data={"code": category.code},
    )
    db.commit()
    db.refresh(category)
    return category


def reactivate_inventory_category(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    client_command_id: uuid.UUID,
    category_id: uuid.UUID,
) -> InventoryCategory:
    fingerprint = _compute_status_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, category_id=category_id
    )

    def _find_by_command() -> InventoryCategory | None:
        return db.execute(
            select(InventoryCategory).where(
                InventoryCategory.tenant_id == tenant_id,
                InventoryCategory.reactivation_client_command_id == client_command_id,
            )
        ).scalar_one_or_none()

    existing = _find_by_command()
    if existing is not None:
        if existing.reactivation_request_fingerprint == fingerprint:
            return existing
        raise InventoryCategoryReactivationReusedWithDifferentPayloadError(str(client_command_id))

    category = _lock_category(db, tenant_id=tenant_id, category_id=category_id)

    existing = _find_by_command()
    if existing is not None:
        if existing.reactivation_request_fingerprint == fingerprint:
            return existing
        raise InventoryCategoryReactivationReusedWithDifferentPayloadError(str(client_command_id))

    if category.status != "inactive":
        raise InventoryCategoryNotInactiveError(str(category_id))

    category.status = "active"
    category.reactivation_client_command_id = client_command_id
    category.reactivation_request_fingerprint = fingerprint
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_inventory_categories_tenant_reactivation_command":
            replay = _find_by_command()
            if replay is not None and replay.reactivation_request_fingerprint == fingerprint:
                return replay
            raise InventoryCategoryReactivationReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="inventory_category.reactivated",
        entity_type="inventory_category", entity_id=category.id, event_data={"code": category.code},
    )
    db.commit()
    db.refresh(category)
    return category
