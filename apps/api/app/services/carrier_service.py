import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.carrier import Carrier
from app.models.carrier_specification import CarrierSpecification
from app.models.carrier_type import CarrierType
from app.schemas.carrier import CarrierRead
from app.schemas.carrier_specification import CarrierSpecificationSummary
from app.services import farm_service
from app.services.audit import append_audit_event
from app.services.errors import (
    CarrierNotFoundError,
    CarrierSpecificationInactiveError,
    CarrierSpecificationNotFoundError,
    CarrierSpecificationRequiredError,
    CarrierSpecificationTypeMismatchError,
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


def _resolve_carrier_type_and_specification(
    db: Session, *, tenant_id: uuid.UUID, carrier_type_code: str | None, specification_id: uuid.UUID | None,
) -> tuple[CarrierType, CarrierSpecification | None]:
    """Section 18/19: the modern path supplies `specification_id` alone
    (CarrierType is then derived from it, never asked for redundantly);
    the legacy path supplies `carrier_type_code` alone, valid only for a
    CarrierType that does not require a specification; supplying both is
    accepted only if they agree on the same CarrierType."""
    specification: CarrierSpecification | None = None
    if specification_id is not None:
        specification = db.execute(
            select(CarrierSpecification).where(
                CarrierSpecification.id == specification_id, CarrierSpecification.tenant_id == tenant_id
            )
        ).scalar_one_or_none()
        if specification is None:
            raise CarrierSpecificationNotFoundError(str(specification_id))
        if specification.status != "active":
            raise CarrierSpecificationInactiveError(str(specification_id))
        carrier_type = db.get(CarrierType, specification.carrier_type_id)
        if carrier_type_code is not None and carrier_type.code != carrier_type_code:
            raise CarrierSpecificationTypeMismatchError(
                f"specification's carrier type {carrier_type.code!r} does not match "
                f"carrier_type_code {carrier_type_code!r}"
            )
    else:
        if carrier_type_code is None:
            raise CarrierSpecificationRequiredError("carrier_type_code or specification_id is required")
        carrier_type = _get_carrier_type_by_code(db, carrier_type_code)
        if carrier_type.requires_specification:
            raise CarrierSpecificationRequiredError(carrier_type.code)

    return carrier_type, specification


def _hydrate_carrier_reads(db: Session, carriers: list[Carrier]) -> list[CarrierRead]:
    """One batched query for every distinct `specification_id` present in
    `carriers` -- never a query per carrier (section 24: avoid N+1)."""
    specification_ids = {c.specification_id for c in carriers if c.specification_id is not None}
    specifications_by_id: dict[uuid.UUID, CarrierSpecification] = {}
    if specification_ids:
        specifications_by_id = {
            s.id: s
            for s in db.execute(
                select(CarrierSpecification).where(CarrierSpecification.id.in_(specification_ids))
            ).scalars()
        }
    reads: list[CarrierRead] = []
    for carrier in carriers:
        specification = (
            specifications_by_id.get(carrier.specification_id) if carrier.specification_id else None
        )
        reads.append(
            CarrierRead(
                id=carrier.id, tenant_id=carrier.tenant_id, farm_id=carrier.farm_id,
                carrier_type_id=carrier.carrier_type_id, code=carrier.code, status=carrier.status,
                issued_date=carrier.issued_date, retired_date=carrier.retired_date,
                specification_id=carrier.specification_id,
                specification=(
                    CarrierSpecificationSummary(
                        id=specification.id, code=specification.code, name=specification.name,
                        biological_position_count=specification.biological_position_count,
                    )
                    if specification is not None
                    else None
                ),
            )
        )
    return reads


def register_carrier(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    carrier_type_code: str | None = None,
    specification_id: uuid.UUID | None = None,
    code: str,
    issued_date: date | None,
) -> Carrier:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    carrier_type, specification = _resolve_carrier_type_and_specification(
        db, tenant_id=tenant_id, carrier_type_code=carrier_type_code, specification_id=specification_id,
    )

    carrier = Carrier(
        tenant_id=tenant_id,
        farm_id=farm_id,
        carrier_type_id=carrier_type.id,
        specification_id=specification.id if specification is not None else None,
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
        event_data={
            "code": carrier.code, "carrier_type_code": carrier_type.code,
            "specification_id": str(specification.id) if specification is not None else None,
        },
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
    carrier_type_code: str | None = None,
    specification_id: uuid.UUID | None = None,
    code_prefix: str,
    start: int,
    end: int,
    pad_width: int,
) -> list[Carrier]:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    carrier_type, specification = _resolve_carrier_type_and_specification(
        db, tenant_id=tenant_id, carrier_type_code=carrier_type_code, specification_id=specification_id,
    )

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
            specification_id=specification.id if specification is not None else None,
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
            "carrier_type_code": carrier_type.code,
            "specification_id": str(specification.id) if specification is not None else None,
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


def list_carrier_types(db: Session) -> list[CarrierType]:
    return list(db.execute(select(CarrierType).order_by(CarrierType.code)).scalars())
