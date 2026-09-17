"""PILOT-WATER-001A section 8: SamplingPoint registration. A SamplingPoint
never floats -- it always anchors to exactly one authoritative water-system
context (source/reservoir/circuit-supply/delivery/drain-return), matching
`point_type`. `point_type = 'other'` is the one acknowledged residual case
with no anchor at all (e.g. a farm-wide catch-all point)."""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.sampling_point import SamplingPoint
from app.services import water_topology_service
from app.services.audit import append_audit_event
from app.services.errors import DuplicateSamplingPointCodeError, SamplingPointNotFoundError, SamplingPointValidationError

_ANCHOR_RESOLVERS = {
    "source": ("water_source_id", lambda db, tenant_id, anchor_id: water_topology_service.get_water_source(
        db, tenant_id=tenant_id, water_source_id=anchor_id
    )),
    "reservoir": ("reservoir_id", lambda db, tenant_id, anchor_id: water_topology_service.get_reservoir(
        db, tenant_id=tenant_id, reservoir_id=anchor_id
    )),
    "circuit_supply": (
        "irrigation_circuit_id",
        lambda db, tenant_id, anchor_id: water_topology_service.get_irrigation_circuit(
            db, tenant_id=tenant_id, irrigation_circuit_id=anchor_id
        ),
    ),
    "delivery": (
        "water_delivery_point_id",
        lambda db, tenant_id, anchor_id: water_topology_service.get_water_delivery_point(
            db, tenant_id=tenant_id, water_delivery_point_id=anchor_id
        ),
    ),
    "drain_return": (
        "water_return_point_id",
        lambda db, tenant_id, anchor_id: water_topology_service.get_water_return_point(
            db, tenant_id=tenant_id, water_return_point_id=anchor_id
        ),
    ),
}


def register_sampling_point(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, code: str, name: str,
    point_type: str, anchor_id: uuid.UUID | None, notes: str | None,
) -> SamplingPoint:
    anchor_columns = {col: None for col, _ in _ANCHOR_RESOLVERS.values()}
    if point_type == "other":
        if anchor_id is not None:
            raise SamplingPointValidationError("point_type 'other' takes no anchor")
    else:
        resolver = _ANCHOR_RESOLVERS.get(point_type)
        if resolver is None:
            raise SamplingPointValidationError(f"unknown point_type {point_type!r}")
        if anchor_id is None:
            raise SamplingPointValidationError(f"point_type {point_type!r} requires an anchor id")
        column, resolve = resolver
        resolve(db, tenant_id, anchor_id)
        anchor_columns[column] = anchor_id

    point = SamplingPoint(
        tenant_id=tenant_id, farm_id=farm_id, code=code, name=name, point_type=point_type, notes=notes,
        **anchor_columns,
    )
    db.add(point)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateSamplingPointCodeError(f"{tenant_id}:{code}") from exc

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="sampling_point.registered",
        entity_type="sampling_point", entity_id=point.id,
        event_data={"code": code, "point_type": point_type, "anchor_id": str(anchor_id) if anchor_id else None},
    )
    db.commit()
    db.refresh(point)
    return point


def get_sampling_point(db: Session, *, tenant_id: uuid.UUID, sampling_point_id: uuid.UUID) -> SamplingPoint:
    point = db.execute(
        select(SamplingPoint).where(SamplingPoint.id == sampling_point_id, SamplingPoint.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if point is None:
        raise SamplingPointNotFoundError(str(sampling_point_id))
    return point


def list_sampling_points(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> list[SamplingPoint]:
    return list(
        db.execute(
            select(SamplingPoint).where(SamplingPoint.tenant_id == tenant_id, SamplingPoint.farm_id == farm_id)
            .order_by(SamplingPoint.code)
        ).scalars()
    )
