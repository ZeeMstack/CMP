import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.crop import Crop
from app.models.variety import Variety
from app.services.audit import append_audit_event
from app.services.errors import (
    CropNotFoundError,
    DuplicateCropCodeError,
    DuplicateVarietyCodeError,
    VarietyNotFoundError,
)


def register_crop(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    code: str,
    common_name: str,
    scientific_name: str | None,
    crop_category: str,
) -> Crop:
    crop = Crop(
        tenant_id=tenant_id,
        code=code,
        common_name=common_name,
        scientific_name=scientific_name,
        crop_category=crop_category,
    )
    db.add(crop)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateCropCodeError(f"{tenant_id}:{code}") from exc

    append_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="crop.registered",
        entity_type="crop",
        entity_id=crop.id,
        event_data={"code": crop.code, "common_name": crop.common_name, "crop_category": crop.crop_category},
    )
    db.commit()
    db.refresh(crop)
    return crop


def get_crop(db: Session, *, tenant_id: uuid.UUID, crop_id: uuid.UUID) -> Crop:
    crop = db.execute(select(Crop).where(Crop.id == crop_id, Crop.tenant_id == tenant_id)).scalar_one_or_none()
    if crop is None:
        raise CropNotFoundError(str(crop_id))
    return crop


def list_crops(db: Session, *, tenant_id: uuid.UUID) -> list[Crop]:
    return list(db.execute(select(Crop).where(Crop.tenant_id == tenant_id).order_by(Crop.code)).scalars())


def register_variety(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    crop_id: uuid.UUID,
    code: str,
    name: str,
    supplier_reference: str | None,
) -> Variety:
    crop = get_crop(db, tenant_id=tenant_id, crop_id=crop_id)

    variety = Variety(
        tenant_id=tenant_id,
        crop_id=crop.id,
        code=code,
        name=name,
        supplier_reference=supplier_reference,
    )
    db.add(variety)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateVarietyCodeError(f"{crop_id}:{code}") from exc

    append_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="variety.registered",
        entity_type="variety",
        entity_id=variety.id,
        event_data={"crop_id": str(crop_id), "code": variety.code, "name": variety.name},
    )
    db.commit()
    db.refresh(variety)
    return variety


def get_variety(db: Session, *, tenant_id: uuid.UUID, crop_id: uuid.UUID, variety_id: uuid.UUID) -> Variety:
    get_crop(db, tenant_id=tenant_id, crop_id=crop_id)
    variety = db.execute(
        select(Variety).where(
            Variety.id == variety_id, Variety.tenant_id == tenant_id, Variety.crop_id == crop_id
        )
    ).scalar_one_or_none()
    if variety is None:
        raise VarietyNotFoundError(str(variety_id))
    return variety


def list_varieties(db: Session, *, tenant_id: uuid.UUID, crop_id: uuid.UUID) -> list[Variety]:
    get_crop(db, tenant_id=tenant_id, crop_id=crop_id)
    return list(
        db.execute(
            select(Variety)
            .where(Variety.tenant_id == tenant_id, Variety.crop_id == crop_id)
            .order_by(Variety.code)
        ).scalars()
    )
