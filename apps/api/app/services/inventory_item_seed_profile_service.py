"""STORE-INV-002A.1: InventoryItemSeedProfile ("Seed Details") -- the
explicit, system-controlled seed marker for an `InventoryItem`
(`docs/domain/STORE_INVENTORY_MODEL.md` §15/§F). Deliberately carries NO
status field -- its existence alone is the signal. Before the item's first
posted `GoodsReceiptLine`, the row may be created, corrected, or hard-deleted
(the one narrow, explicitly-scoped exception to this codebase's no-hard-
delete norm -- nothing can reference an unused profile yet). After that
point, the row is fully immutable (service-layer check here, DB trigger in
the migration as defense in depth)."""

import hashlib
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.goods_receipt_line import GoodsReceiptLine
from app.models.inventory_item import InventoryItem
from app.models.inventory_item_seed_profile import InventoryItemSeedProfile
from app.services.audit import append_audit_event
from app.services.errors import (
    CropNotFoundError,
    InventoryItemNotFoundError,
    InventoryItemSeedProfileAlreadyExistsError,
    InventoryItemSeedProfileCommandReusedWithDifferentPayloadError,
    InventoryItemSeedProfileCreationBlockedError,
    InventoryItemSeedProfileNotFoundError,
    InventoryItemSeedProfileStructurallyLockedError,
    InventoryItemSeedProfileUpdateReusedWithDifferentPayloadError,
    VarietyNotFoundError,
)


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _has_posted_receipts(db: Session, *, inventory_item_id: uuid.UUID) -> bool:
    """The uniform first-posted-receipt freeze trigger this domain family
    uses everywhere (docs/domain/STORE_INVENTORY_MODEL.md §O/§T) -- checked
    against `GoodsReceiptLine` existence directly, never `InventoryLot`
    (which may not exist at all for a non-lot-tracked item)."""
    return (
        db.execute(
            select(func.count()).select_from(GoodsReceiptLine).where(
                GoodsReceiptLine.inventory_item_id == inventory_item_id
            )
        ).scalar_one()
        > 0
    )


def _require_item(db: Session, *, tenant_id: uuid.UUID, inventory_item_id: uuid.UUID) -> None:
    item = db.execute(
        select(InventoryItem.id).where(
            InventoryItem.id == inventory_item_id, InventoryItem.tenant_id == tenant_id
        )
    ).scalar_one_or_none()
    if item is None:
        raise InventoryItemNotFoundError(str(inventory_item_id))


def _require_crop_and_variety(
    db: Session, *, tenant_id: uuid.UUID, crop_id: uuid.UUID, variety_id: uuid.UUID
) -> None:
    from app.models.crop import Crop
    from app.models.variety import Variety

    crop = db.execute(select(Crop.id).where(Crop.id == crop_id, Crop.tenant_id == tenant_id)).scalar_one_or_none()
    if crop is None:
        raise CropNotFoundError(str(crop_id))
    variety = db.execute(
        select(Variety.id).where(
            Variety.id == variety_id, Variety.tenant_id == tenant_id, Variety.crop_id == crop_id
        )
    ).scalar_one_or_none()
    if variety is None:
        raise VarietyNotFoundError(str(variety_id))


def _compute_create_fingerprint(
    *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID | None, inventory_item_id: uuid.UUID, crop_id: uuid.UUID,
    variety_id: uuid.UUID,
) -> str:
    parts = [
        str(tenant_id), str(actor_user_id) if actor_user_id else "", str(inventory_item_id), str(crop_id),
        str(variety_id),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _compute_update_fingerprint(
    *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID | None, profile_id: uuid.UUID, crop_id: uuid.UUID,
    variety_id: uuid.UUID,
) -> str:
    parts = [
        str(tenant_id), str(actor_user_id) if actor_user_id else "", str(profile_id), str(crop_id),
        str(variety_id),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def register_seed_profile(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    client_command_id: uuid.UUID,
    inventory_item_id: uuid.UUID,
    crop_id: uuid.UUID,
    variety_id: uuid.UUID,
) -> InventoryItemSeedProfile:
    fingerprint = _compute_create_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, inventory_item_id=inventory_item_id, crop_id=crop_id,
        variety_id=variety_id,
    )

    existing = db.execute(
        select(InventoryItemSeedProfile).where(
            InventoryItemSeedProfile.tenant_id == tenant_id,
            InventoryItemSeedProfile.client_command_id == client_command_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise InventoryItemSeedProfileCommandReusedWithDifferentPayloadError(str(client_command_id))

    _require_item(db, tenant_id=tenant_id, inventory_item_id=inventory_item_id)
    _require_crop_and_variety(db, tenant_id=tenant_id, crop_id=crop_id, variety_id=variety_id)

    # A historically non-seed item (posted receipts, never had Seed Details)
    # can never retroactively become one.
    if _has_posted_receipts(db, inventory_item_id=inventory_item_id):
        raise InventoryItemSeedProfileCreationBlockedError(str(inventory_item_id))

    already = db.execute(
        select(InventoryItemSeedProfile.id).where(
            InventoryItemSeedProfile.tenant_id == tenant_id,
            InventoryItemSeedProfile.inventory_item_id == inventory_item_id,
        )
    ).scalar_one_or_none()
    if already is not None:
        raise InventoryItemSeedProfileAlreadyExistsError(str(inventory_item_id))

    profile = InventoryItemSeedProfile(
        tenant_id=tenant_id, inventory_item_id=inventory_item_id, crop_id=crop_id, variety_id=variety_id,
        created_by_user_id=actor_user_id, client_command_id=client_command_id, request_fingerprint=fingerprint,
    )
    db.add(profile)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_inventory_item_seed_profiles_tenant_command":
            replay = db.execute(
                select(InventoryItemSeedProfile).where(
                    InventoryItemSeedProfile.tenant_id == tenant_id,
                    InventoryItemSeedProfile.client_command_id == client_command_id,
                )
            ).scalar_one_or_none()
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise InventoryItemSeedProfileCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        if constraint == "uq_inventory_item_seed_profiles_item":
            raise InventoryItemSeedProfileAlreadyExistsError(str(inventory_item_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="inventory_item_seed_profile.created",
        entity_type="inventory_item_seed_profile", entity_id=profile.id,
        event_data={"inventory_item_id": str(inventory_item_id), "crop_id": str(crop_id), "variety_id": str(variety_id)},
    )
    db.commit()
    db.refresh(profile)
    return profile


def get_seed_profile(db: Session, *, tenant_id: uuid.UUID, profile_id: uuid.UUID) -> InventoryItemSeedProfile:
    profile = db.execute(
        select(InventoryItemSeedProfile).where(
            InventoryItemSeedProfile.id == profile_id, InventoryItemSeedProfile.tenant_id == tenant_id
        )
    ).scalar_one_or_none()
    if profile is None:
        raise InventoryItemSeedProfileNotFoundError(str(profile_id))
    return profile


def get_seed_profile_for_item(
    db: Session, *, tenant_id: uuid.UUID, inventory_item_id: uuid.UUID
) -> InventoryItemSeedProfile | None:
    return db.execute(
        select(InventoryItemSeedProfile).where(
            InventoryItemSeedProfile.tenant_id == tenant_id,
            InventoryItemSeedProfile.inventory_item_id == inventory_item_id,
        )
    ).scalar_one_or_none()


def _lock_profile(db: Session, *, tenant_id: uuid.UUID, profile_id: uuid.UUID) -> InventoryItemSeedProfile | None:
    return db.execute(
        select(InventoryItemSeedProfile)
        .where(InventoryItemSeedProfile.id == profile_id, InventoryItemSeedProfile.tenant_id == tenant_id)
        .with_for_update()
    ).scalar_one_or_none()


def update_seed_profile(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    client_command_id: uuid.UUID,
    profile_id: uuid.UUID,
    crop_id: uuid.UUID,
    variety_id: uuid.UUID,
) -> InventoryItemSeedProfile:
    fingerprint = _compute_update_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, profile_id=profile_id, crop_id=crop_id,
        variety_id=variety_id,
    )

    def _find_by_update_command() -> InventoryItemSeedProfile | None:
        return db.execute(
            select(InventoryItemSeedProfile).where(
                InventoryItemSeedProfile.tenant_id == tenant_id,
                InventoryItemSeedProfile.update_client_command_id == client_command_id,
            )
        ).scalar_one_or_none()

    existing = _find_by_update_command()
    if existing is not None:
        if existing.update_request_fingerprint == fingerprint:
            return existing
        raise InventoryItemSeedProfileUpdateReusedWithDifferentPayloadError(str(client_command_id))

    profile = _lock_profile(db, tenant_id=tenant_id, profile_id=profile_id)
    if profile is None:
        raise InventoryItemSeedProfileNotFoundError(str(profile_id))

    existing = _find_by_update_command()
    if existing is not None:
        if existing.update_request_fingerprint == fingerprint:
            return existing
        raise InventoryItemSeedProfileUpdateReusedWithDifferentPayloadError(str(client_command_id))

    if _has_posted_receipts(db, inventory_item_id=profile.inventory_item_id):
        raise InventoryItemSeedProfileStructurallyLockedError(str(profile_id))

    _require_crop_and_variety(db, tenant_id=tenant_id, crop_id=crop_id, variety_id=variety_id)

    profile.crop_id = crop_id
    profile.variety_id = variety_id
    profile.update_client_command_id = client_command_id
    profile.update_request_fingerprint = fingerprint
    db.flush()

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="inventory_item_seed_profile.updated",
        entity_type="inventory_item_seed_profile", entity_id=profile.id,
        event_data={"crop_id": str(crop_id), "variety_id": str(variety_id)},
    )
    db.commit()
    db.refresh(profile)
    return profile


def remove_seed_profile(
    db: Session, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID | None, client_command_id: uuid.UUID,
    profile_id: uuid.UUID,
) -> None:
    """A genuine hard DELETE -- the one narrow exception in this domain
    family, permitted only pre-use. Unlike CREATE/UPDATE, a DELETE command
    is naturally idempotent in end-state (the row is gone either way), so
    there is no stored `client_command_id` on the (now-deleted) row to
    replay against -- `client_command_id` is accepted here purely for audit
    correlation, not for replay-conflict detection. Calling this a second
    time on an already-removed profile is a silent, successful no-op."""
    profile = _lock_profile(db, tenant_id=tenant_id, profile_id=profile_id)
    if profile is None:
        return

    if _has_posted_receipts(db, inventory_item_id=profile.inventory_item_id):
        raise InventoryItemSeedProfileStructurallyLockedError(str(profile_id))

    inventory_item_id = profile.inventory_item_id
    db.delete(profile)
    db.flush()

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="inventory_item_seed_profile.removed",
        entity_type="inventory_item_seed_profile", entity_id=profile_id,
        event_data={"inventory_item_id": str(inventory_item_id), "client_command_id": str(client_command_id)},
    )
    db.commit()
