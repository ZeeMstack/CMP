"""CARRIER-CONFIG-001: tenant-configurable reusable physical Carrier
Specifications (`CarrierType` [platform role] -> `CarrierSpecification`
[tenant-defined physical design] -> `Carrier` [individually traceable
physical object]). Physical equipment configuration only -- never a
crop/variety/planting-density fact; see the model's own docstring."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.carrier import Carrier
from app.models.carrier_specification import CarrierSpecification
from app.models.carrier_type import CarrierType
from app.schemas.carrier_specification import CarrierSpecificationRead
from app.services import carrier_service
from app.services.audit import append_audit_event
from app.services.errors import (
    CarrierSpecificationNotFoundError,
    CarrierSpecificationStructurallyLockedError,
    CarrierSpecificationValidationError,
    DuplicateCarrierSpecificationCodeError,
)


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _require_minimum_fields_if_specification_required(
    carrier_type: CarrierType, *, length_mm: int | None, width_mm: int | None,
    biological_position_count: int | None,
) -> None:
    """Section 10: for a CarrierType that requires a specification, a real
    specification must carry at least length/width/biological_position_count
    -- height stays optional even then. For a CarrierType that does not
    require one, these all stay fully optional (a tenant may still choose to
    record partial physical facts about e.g. a Grow Bag design)."""
    if not carrier_type.requires_specification:
        return
    missing = [
        field_name
        for field_name, value in (
            ("length_mm", length_mm), ("width_mm", width_mm),
            ("biological_position_count", biological_position_count),
        )
        if value is None
    ]
    if missing:
        raise CarrierSpecificationValidationError(
            f"carrier type {carrier_type.code!r} requires a specification; missing: {', '.join(missing)}"
        )


def _specification_read_query():
    return (
        select(
            CarrierSpecification,
            CarrierType.code.label("carrier_type_code"),
            CarrierType.biological_position_label,
            select(Carrier.id)
            .where(Carrier.specification_id == CarrierSpecification.id)
            .exists()
            .label("is_structurally_locked"),
        )
        .join(CarrierType, CarrierType.id == CarrierSpecification.carrier_type_id)
    )


def _row_to_read(row) -> CarrierSpecificationRead:
    spec: CarrierSpecification = row[0]
    m = row._mapping
    return CarrierSpecificationRead(
        id=spec.id, tenant_id=spec.tenant_id, carrier_type_id=spec.carrier_type_id,
        carrier_type_code=m["carrier_type_code"], biological_position_label=m["biological_position_label"],
        code=spec.code, name=spec.name, length_mm=spec.length_mm, width_mm=spec.width_mm,
        height_mm=spec.height_mm, biological_position_count=spec.biological_position_count,
        status=spec.status, is_structurally_locked=bool(m["is_structurally_locked"]),
    )


def _get_specification_row(
    db: Session, *, tenant_id: uuid.UUID, specification_id: uuid.UUID, lock: bool = False
) -> CarrierSpecification:
    query = select(CarrierSpecification).where(
        CarrierSpecification.id == specification_id, CarrierSpecification.tenant_id == tenant_id
    )
    if lock:
        query = query.with_for_update()
    specification = db.execute(query).scalar_one_or_none()
    if specification is None:
        raise CarrierSpecificationNotFoundError(str(specification_id))
    return specification


def _is_referenced(db: Session, *, specification_id: uuid.UUID) -> bool:
    return (
        db.execute(
            select(func.count()).select_from(Carrier).where(Carrier.specification_id == specification_id)
        ).scalar_one()
        > 0
    )


def register_carrier_specification(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    carrier_type_code: str,
    code: str,
    name: str,
    length_mm: int | None,
    width_mm: int | None,
    height_mm: int | None,
    biological_position_count: int | None,
) -> CarrierSpecificationRead:
    carrier_type = carrier_service._get_carrier_type_by_code(db, carrier_type_code)
    _require_minimum_fields_if_specification_required(
        carrier_type, length_mm=length_mm, width_mm=width_mm,
        biological_position_count=biological_position_count,
    )

    specification = CarrierSpecification(
        tenant_id=tenant_id, carrier_type_id=carrier_type.id, code=code, name=name,
        length_mm=length_mm, width_mm=width_mm, height_mm=height_mm,
        biological_position_count=biological_position_count,
    )
    db.add(specification)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateCarrierSpecificationCodeError(f"{tenant_id}:{code}") from exc

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="carrier_specification.registered",
        entity_type="carrier_specification", entity_id=specification.id,
        event_data={
            "code": specification.code, "name": specification.name, "carrier_type_code": carrier_type.code,
            "length_mm": length_mm, "width_mm": width_mm, "height_mm": height_mm,
            "biological_position_count": biological_position_count,
        },
    )
    db.commit()
    return get_carrier_specification(db, tenant_id=tenant_id, specification_id=specification.id)


def get_carrier_specification(
    db: Session, *, tenant_id: uuid.UUID, specification_id: uuid.UUID
) -> CarrierSpecificationRead:
    row = db.execute(
        _specification_read_query().where(
            CarrierSpecification.id == specification_id, CarrierSpecification.tenant_id == tenant_id
        )
    ).first()
    if row is None:
        raise CarrierSpecificationNotFoundError(str(specification_id))
    return _row_to_read(row)


def list_carrier_specifications(
    db: Session, *, tenant_id: uuid.UUID, carrier_type_code: str | None, status: str | None
) -> list[CarrierSpecificationRead]:
    query = _specification_read_query().where(CarrierSpecification.tenant_id == tenant_id)
    if carrier_type_code is not None:
        carrier_type = carrier_service._get_carrier_type_by_code(db, carrier_type_code)
        query = query.where(CarrierSpecification.carrier_type_id == carrier_type.id)
    if status is not None:
        query = query.where(CarrierSpecification.status == status)
    rows = db.execute(query.order_by(func.lower(CarrierSpecification.code))).all()
    return [_row_to_read(row) for row in rows]


def update_carrier_specification(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    specification_id: uuid.UUID,
    carrier_type_code: str,
    code: str,
    name: str,
    length_mm: int | None,
    width_mm: int | None,
    height_mm: int | None,
    biological_position_count: int | None,
) -> CarrierSpecificationRead:
    # Section 14: lock the specification row FIRST, before checking
    # is-referenced -- a concurrent Carrier registration that references
    # this specification must take a FOR KEY SHARE lock on this exact row
    # as part of its own FK constraint check, which blocks behind this
    # FOR UPDATE until this transaction commits/rolls back. This makes the
    # "is it referenced" check below genuinely race-safe, not just a
    # point-in-time snapshot that a concurrent registration could race past.
    specification = _get_specification_row(db, tenant_id=tenant_id, specification_id=specification_id, lock=True)
    carrier_type = carrier_service._get_carrier_type_by_code(db, carrier_type_code)

    structural_changed = (
        specification.carrier_type_id != carrier_type.id
        or specification.code.lower() != code.lower()
        or specification.length_mm != length_mm
        or specification.width_mm != width_mm
        or specification.height_mm != height_mm
        or specification.biological_position_count != biological_position_count
    )
    if structural_changed and _is_referenced(db, specification_id=specification.id):
        raise CarrierSpecificationStructurallyLockedError(str(specification_id))

    if structural_changed:
        _require_minimum_fields_if_specification_required(
            carrier_type, length_mm=length_mm, width_mm=width_mm,
            biological_position_count=biological_position_count,
        )
        specification.carrier_type_id = carrier_type.id
        specification.code = code
        specification.length_mm = length_mm
        specification.width_mm = width_mm
        specification.height_mm = height_mm
        specification.biological_position_count = biological_position_count
    # name is never structural -- always applied, matching section 15.
    specification.name = name

    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateCarrierSpecificationCodeError(f"{tenant_id}:{code}") from exc

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="carrier_specification.updated",
        entity_type="carrier_specification", entity_id=specification.id,
        event_data={
            "code": specification.code, "name": specification.name, "structural_changed": structural_changed,
        },
    )
    db.commit()
    return get_carrier_specification(db, tenant_id=tenant_id, specification_id=specification.id)


def deactivate_carrier_specification(
    db: Session, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID | None, specification_id: uuid.UUID
) -> CarrierSpecificationRead:
    specification = _get_specification_row(db, tenant_id=tenant_id, specification_id=specification_id, lock=True)
    specification.status = "inactive"
    db.flush()
    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="carrier_specification.deactivated",
        entity_type="carrier_specification", entity_id=specification.id,
        event_data={"code": specification.code},
    )
    db.commit()
    return get_carrier_specification(db, tenant_id=tenant_id, specification_id=specification.id)


def reactivate_carrier_specification(
    db: Session, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID | None, specification_id: uuid.UUID
) -> CarrierSpecificationRead:
    specification = _get_specification_row(db, tenant_id=tenant_id, specification_id=specification_id, lock=True)
    specification.status = "active"
    db.flush()
    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="carrier_specification.reactivated",
        entity_type="carrier_specification", entity_id=specification.id,
        event_data={"code": specification.code},
    )
    db.commit()
    return get_carrier_specification(db, tenant_id=tenant_id, specification_id=specification.id)
