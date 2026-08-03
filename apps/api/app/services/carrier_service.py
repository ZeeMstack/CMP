import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.carrier import Carrier
from app.models.carrier_type import CarrierType
from app.services import farm_service
from app.services.audit import append_audit_event
from app.services.errors import (
    CarrierNotFoundError,
    CarrierTypeNotFoundError,
    DuplicateCarrierCodeError,
    FarmNotFoundError,
)


def _require_active_farm(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> None:
    farm = farm_service.get_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    if farm.status != "active":
        raise FarmNotFoundError(str(farm_id))


def _get_carrier_type_by_code(db: Session, code: str) -> CarrierType:
    carrier_type = db.execute(select(CarrierType).where(CarrierType.code == code)).scalar_one_or_none()
    if carrier_type is None:
        raise CarrierTypeNotFoundError(code)
    return carrier_type


def register_carrier(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    carrier_type_code: str,
    code: str,
    issued_date: date | None,
) -> Carrier:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    carrier_type = _get_carrier_type_by_code(db, carrier_type_code)

    carrier = Carrier(
        tenant_id=tenant_id,
        farm_id=farm_id,
        carrier_type_id=carrier_type.id,
        code=code,
        issued_date=issued_date,
    )
    db.add(carrier)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateCarrierCodeError(f"{tenant_id}:{code}") from exc

    append_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="carrier.registered",
        entity_type="carrier",
        entity_id=carrier.id,
        event_data={"code": carrier.code, "carrier_type_code": carrier_type_code},
    )
    db.commit()
    db.refresh(carrier)
    return carrier


def bulk_register_carriers(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    carrier_type_code: str,
    code_prefix: str,
    start: int,
    end: int,
    pad_width: int,
) -> list[Carrier]:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    carrier_type = _get_carrier_type_by_code(db, carrier_type_code)

    numbers = range(start, end + 1)
    codes = [f"{code_prefix}{str(n).zfill(pad_width)}" for n in numbers]

    existing = db.execute(
        select(Carrier.code).where(
            Carrier.tenant_id == tenant_id,
            func.lower(Carrier.code).in_([c.lower() for c in codes]),
        )
    ).scalars().all()
    if existing:
        raise DuplicateCarrierCodeError(f"{tenant_id}:{','.join(existing)}")

    created: list[Carrier] = []
    for code in codes:
        carrier = Carrier(
            tenant_id=tenant_id,
            farm_id=farm_id,
            carrier_type_id=carrier_type.id,
            code=code,
        )
        db.add(carrier)
        created.append(carrier)

    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateCarrierCodeError(f"{tenant_id}:{code_prefix}") from exc

    append_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="carrier.bulk_registered",
        entity_type="carrier",
        entity_id=None,
        event_data={
            "carrier_type_code": carrier_type_code,
            "code_prefix": code_prefix,
            "start": start,
            "end": end,
            "pad_width": pad_width,
            "count": len(created),
        },
    )
    db.commit()
    for carrier in created:
        db.refresh(carrier)
    return created


def get_carrier(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, carrier_id: uuid.UUID) -> Carrier:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    carrier = db.execute(
        select(Carrier).where(
            Carrier.id == carrier_id, Carrier.tenant_id == tenant_id, Carrier.farm_id == farm_id
        )
    ).scalar_one_or_none()
    if carrier is None:
        raise CarrierNotFoundError(str(carrier_id))
    return carrier


def list_carriers(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, carrier_type_code: str | None
) -> list[Carrier]:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    query = select(Carrier).where(Carrier.tenant_id == tenant_id, Carrier.farm_id == farm_id)
    if carrier_type_code is not None:
        carrier_type = _get_carrier_type_by_code(db, carrier_type_code)
        query = query.where(Carrier.carrier_type_id == carrier_type.id)
    return list(db.execute(query.order_by(func.lower(Carrier.code))).scalars())
