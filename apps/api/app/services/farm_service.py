import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.farm import Farm
from app.services.audit import append_audit_event
from app.services.errors import DuplicateFarmCodeError, FarmNotFoundError


def create_farm(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    code: str,
    name: str,
    country_code: str,
    city_region: str | None,
    timezone: str,
) -> Farm:
    farm = Farm(
        tenant_id=tenant_id,
        code=code,
        name=name,
        country_code=country_code,
        city_region=city_region,
        timezone=timezone,
    )
    db.add(farm)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateFarmCodeError(f"{tenant_id}:{code}") from exc

    append_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="farm.created",
        entity_type="farm",
        entity_id=farm.id,
        event_data={"code": farm.code, "name": farm.name},
    )

    db.commit()
    db.refresh(farm)
    return farm


def get_farm(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> Farm:
    farm = db.execute(
        select(Farm).where(Farm.id == farm_id, Farm.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if farm is None:
        raise FarmNotFoundError(str(farm_id))
    return farm


def list_farms(db: Session, *, tenant_id: uuid.UUID) -> list[Farm]:
    return list(
        db.execute(select(Farm).where(Farm.tenant_id == tenant_id).order_by(Farm.code)).scalars()
    )
