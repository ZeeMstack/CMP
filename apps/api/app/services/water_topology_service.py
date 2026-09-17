"""PILOT-WATER-001A: water TOPOLOGY -- WaterSource/Reservoir/
IrrigationCircuit/WaterDeliveryPoint/WaterReturnPoint identity, and the
four effective-dated topology connections between them. Deliberately
separate from `location_service` (ticket rule 1: water topology != the
physical Location hierarchy) -- a Reservoir/DeliveryPoint/ReturnPoint may
optionally reference a Location, but this module never writes to
`locations` and never treats a topology entity as a Location.

Topology identity registration (this module's five `register_*`
functions) carries no `client_command_id`/idempotency pair, mirroring
`Asset`/`Carrier`'s own precedent -- infrequent, admin/grower-driven farm
setup, not a repeated offline floor-scan action. Every operational,
field-recorded command elsewhere in this ticket's domain (measurements,
calibration, mixes, reservoir events, delivery events) does carry one; see
docs/domain/WATER_NUTRIENT_SYSTEM_MODEL.md "Known gaps" for the exact
line drawn here.

Closing an effective-dated link is the ONLY update this module ever
performs against a link row -- superseding one always closes the old row
and inserts a new one in the same transaction, per the ticket's own
"never overwrite FKs and lose topology history" rule. The DB itself
backstops this (`enforce_water_topology_link_closure_only`, this ticket's
migration): even a bug here could not silently rewrite history.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.irrigation_circuit import IrrigationCircuit
from app.models.location import Location
from app.models.reservoir import Reservoir
from app.models.unit_of_measure import UnitOfMeasure
from app.models.water_delivery_point import WaterDeliveryPoint
from app.models.water_return_point import WaterReturnPoint
from app.models.water_source import WaterSource
from app.models.water_topology_link import (
    CircuitDeliveryPointLink,
    ReservoirCircuitLink,
    ReturnPointReservoirLink,
    WaterSourceReservoirLink,
)
from app.services import farm_service
from app.services.audit import append_audit_event
from app.services.errors import (
    DuplicateIrrigationCircuitCodeError,
    DuplicateReservoirCodeError,
    DuplicateWaterDeliveryPointCodeError,
    DuplicateWaterReturnPointCodeError,
    DuplicateWaterSourceCodeError,
    FarmNotFoundError,
    IrrigationCircuitNotFoundError,
    LocationNotFoundError,
    ReservoirNotFoundError,
    UnitOfMeasureKindMismatchError,
    UnitOfMeasureNotFoundError,
    WaterDeliveryPointNotFoundError,
    WaterReturnPointNotFoundError,
    WaterSourceNotFoundError,
    WaterTopologyLinkAlreadyClosedError,
    WaterTopologyLinkNotFoundError,
)


def _require_active_farm(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID):
    farm = farm_service.get_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    if farm.status != "active":
        raise FarmNotFoundError(str(farm_id))
    return farm


def _require_location(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, location_id: uuid.UUID) -> Location:
    location = db.execute(
        select(Location).where(
            Location.id == location_id, Location.tenant_id == tenant_id, Location.farm_id == farm_id
        )
    ).scalar_one_or_none()
    if location is None:
        raise LocationNotFoundError(str(location_id))
    return location


def _require_volume_uom(db: Session, *, uom_id: uuid.UUID) -> UnitOfMeasure:
    uom = db.execute(select(UnitOfMeasure).where(UnitOfMeasure.id == uom_id)).scalar_one_or_none()
    if uom is None:
        raise UnitOfMeasureNotFoundError(str(uom_id))
    if uom.quantity_kind != "volume":
        raise UnitOfMeasureKindMismatchError(f"{uom.code} is not a volume unit")
    return uom


# --- WaterSource ---------------------------------------------------------------------


def register_water_source(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, code: str, name: str,
    source_type: str, notes: str | None,
) -> WaterSource:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    source = WaterSource(
        tenant_id=tenant_id, farm_id=farm_id, code=code, name=name, source_type=source_type, notes=notes,
    )
    db.add(source)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateWaterSourceCodeError(f"{tenant_id}:{code}") from exc
    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="water_source.registered",
        entity_type="water_source", entity_id=source.id, event_data={"code": code, "source_type": source_type},
    )
    db.commit()
    db.refresh(source)
    return source


def get_water_source(db: Session, *, tenant_id: uuid.UUID, water_source_id: uuid.UUID) -> WaterSource:
    source = db.execute(
        select(WaterSource).where(WaterSource.id == water_source_id, WaterSource.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if source is None:
        raise WaterSourceNotFoundError(str(water_source_id))
    return source


def list_water_sources(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> list[WaterSource]:
    return list(
        db.execute(
            select(WaterSource).where(WaterSource.tenant_id == tenant_id, WaterSource.farm_id == farm_id)
            .order_by(WaterSource.code)
        ).scalars()
    )


def set_water_source_status(
    db: Session, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, water_source_id: uuid.UUID, status: str,
) -> WaterSource:
    source = get_water_source(db, tenant_id=tenant_id, water_source_id=water_source_id)
    source.status = status
    db.flush()
    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action=f"water_source.{status}",
        entity_type="water_source", entity_id=source.id, event_data={"code": source.code},
    )
    db.commit()
    db.refresh(source)
    return source


# --- Reservoir -------------------------------------------------------------------------


def register_reservoir(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, code: str, name: str,
    reservoir_type: str, nominal_capacity, nominal_capacity_uom_id: uuid.UUID | None,
    linked_asset_id: uuid.UUID | None, location_id: uuid.UUID | None, notes: str | None,
) -> Reservoir:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    if nominal_capacity_uom_id is not None:
        _require_volume_uom(db, uom_id=nominal_capacity_uom_id)
    if location_id is not None:
        _require_location(db, tenant_id=tenant_id, farm_id=farm_id, location_id=location_id)

    reservoir = Reservoir(
        tenant_id=tenant_id, farm_id=farm_id, code=code, name=name, reservoir_type=reservoir_type,
        nominal_capacity=nominal_capacity, nominal_capacity_uom_id=nominal_capacity_uom_id,
        linked_asset_id=linked_asset_id, location_id=location_id, notes=notes,
    )
    db.add(reservoir)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateReservoirCodeError(f"{tenant_id}:{code}") from exc
    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="reservoir.registered",
        entity_type="reservoir", entity_id=reservoir.id, event_data={"code": code, "reservoir_type": reservoir_type},
    )
    db.commit()
    db.refresh(reservoir)
    return reservoir


def get_reservoir(db: Session, *, tenant_id: uuid.UUID, reservoir_id: uuid.UUID) -> Reservoir:
    reservoir = db.execute(
        select(Reservoir).where(Reservoir.id == reservoir_id, Reservoir.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if reservoir is None:
        raise ReservoirNotFoundError(str(reservoir_id))
    return reservoir


def list_reservoirs(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> list[Reservoir]:
    return list(
        db.execute(
            select(Reservoir).where(Reservoir.tenant_id == tenant_id, Reservoir.farm_id == farm_id)
            .order_by(Reservoir.code)
        ).scalars()
    )


def set_reservoir_status(
    db: Session, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, reservoir_id: uuid.UUID, status: str,
) -> Reservoir:
    reservoir = get_reservoir(db, tenant_id=tenant_id, reservoir_id=reservoir_id)
    reservoir.status = status
    db.flush()
    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action=f"reservoir.{status}",
        entity_type="reservoir", entity_id=reservoir.id, event_data={"code": reservoir.code},
    )
    db.commit()
    db.refresh(reservoir)
    return reservoir


# --- IrrigationCircuit -----------------------------------------------------------------


def register_irrigation_circuit(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, code: str, name: str,
    system_type: str | None, notes: str | None,
) -> IrrigationCircuit:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    circuit = IrrigationCircuit(
        tenant_id=tenant_id, farm_id=farm_id, code=code, name=name, system_type=system_type, notes=notes,
    )
    db.add(circuit)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateIrrigationCircuitCodeError(f"{tenant_id}:{code}") from exc
    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="irrigation_circuit.registered",
        entity_type="irrigation_circuit", entity_id=circuit.id, event_data={"code": code},
    )
    db.commit()
    db.refresh(circuit)
    return circuit


def get_irrigation_circuit(db: Session, *, tenant_id: uuid.UUID, irrigation_circuit_id: uuid.UUID) -> IrrigationCircuit:
    circuit = db.execute(
        select(IrrigationCircuit).where(
            IrrigationCircuit.id == irrigation_circuit_id, IrrigationCircuit.tenant_id == tenant_id
        )
    ).scalar_one_or_none()
    if circuit is None:
        raise IrrigationCircuitNotFoundError(str(irrigation_circuit_id))
    return circuit


def list_irrigation_circuits(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> list[IrrigationCircuit]:
    return list(
        db.execute(
            select(IrrigationCircuit).where(
                IrrigationCircuit.tenant_id == tenant_id, IrrigationCircuit.farm_id == farm_id
            ).order_by(IrrigationCircuit.code)
        ).scalars()
    )


def set_irrigation_circuit_status(
    db: Session, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, irrigation_circuit_id: uuid.UUID, status: str,
) -> IrrigationCircuit:
    circuit = get_irrigation_circuit(db, tenant_id=tenant_id, irrigation_circuit_id=irrigation_circuit_id)
    circuit.status = status
    db.flush()
    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action=f"irrigation_circuit.{status}",
        entity_type="irrigation_circuit", entity_id=circuit.id, event_data={"code": circuit.code},
    )
    db.commit()
    db.refresh(circuit)
    return circuit


# --- WaterDeliveryPoint -----------------------------------------------------------------


def register_water_delivery_point(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, code: str, name: str,
    location_id: uuid.UUID, notes: str | None,
) -> WaterDeliveryPoint:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    _require_location(db, tenant_id=tenant_id, farm_id=farm_id, location_id=location_id)
    point = WaterDeliveryPoint(
        tenant_id=tenant_id, farm_id=farm_id, code=code, name=name, location_id=location_id, notes=notes,
    )
    db.add(point)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateWaterDeliveryPointCodeError(f"{tenant_id}:{code}") from exc
    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="water_delivery_point.registered",
        entity_type="water_delivery_point", entity_id=point.id,
        event_data={"code": code, "location_id": str(location_id)},
    )
    db.commit()
    db.refresh(point)
    return point


def get_water_delivery_point(db: Session, *, tenant_id: uuid.UUID, water_delivery_point_id: uuid.UUID) -> WaterDeliveryPoint:
    point = db.execute(
        select(WaterDeliveryPoint).where(
            WaterDeliveryPoint.id == water_delivery_point_id, WaterDeliveryPoint.tenant_id == tenant_id
        )
    ).scalar_one_or_none()
    if point is None:
        raise WaterDeliveryPointNotFoundError(str(water_delivery_point_id))
    return point


def list_water_delivery_points(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> list[WaterDeliveryPoint]:
    return list(
        db.execute(
            select(WaterDeliveryPoint).where(
                WaterDeliveryPoint.tenant_id == tenant_id, WaterDeliveryPoint.farm_id == farm_id
            ).order_by(WaterDeliveryPoint.code)
        ).scalars()
    )


# --- WaterReturnPoint -------------------------------------------------------------------


def register_water_return_point(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, code: str, name: str,
    location_id: uuid.UUID | None, notes: str | None,
) -> WaterReturnPoint:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    if location_id is not None:
        _require_location(db, tenant_id=tenant_id, farm_id=farm_id, location_id=location_id)
    point = WaterReturnPoint(
        tenant_id=tenant_id, farm_id=farm_id, code=code, name=name, location_id=location_id, notes=notes,
    )
    db.add(point)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateWaterReturnPointCodeError(f"{tenant_id}:{code}") from exc
    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="water_return_point.registered",
        entity_type="water_return_point", entity_id=point.id, event_data={"code": code},
    )
    db.commit()
    db.refresh(point)
    return point


def get_water_return_point(db: Session, *, tenant_id: uuid.UUID, water_return_point_id: uuid.UUID) -> WaterReturnPoint:
    point = db.execute(
        select(WaterReturnPoint).where(
            WaterReturnPoint.id == water_return_point_id, WaterReturnPoint.tenant_id == tenant_id
        )
    ).scalar_one_or_none()
    if point is None:
        raise WaterReturnPointNotFoundError(str(water_return_point_id))
    return point


def list_water_return_points(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> list[WaterReturnPoint]:
    return list(
        db.execute(
            select(WaterReturnPoint).where(
                WaterReturnPoint.tenant_id == tenant_id, WaterReturnPoint.farm_id == farm_id
            ).order_by(WaterReturnPoint.code)
        ).scalars()
    )


# --- Effective-dated topology links ------------------------------------------------------
#
# One generic open/close pair per link table -- each table differs only in
# its two endpoint FK columns and which side is uniquely-active, so the
# logic is factored once and parameterized by model + column names rather
# than duplicated four times.


def _open_link(
    db: Session, *, model, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID,
    endpoint_columns: dict, effective_from: datetime, reason: str | None, action: str, entity_type: str,
    active_unique_constraint: str,
):
    link = model(
        tenant_id=tenant_id, farm_id=farm_id, effective_from=effective_from, created_by_user_id=actor_user_id,
        reason=reason, **endpoint_columns,
    )
    db.add(link)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise WaterTopologyLinkAlreadyClosedError(
            f"an active link already exists for this endpoint (constraint {active_unique_constraint})"
        ) from exc
    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action=action, entity_type=entity_type,
        entity_id=link.id, event_data={**{k: str(v) for k, v in endpoint_columns.items()}, "reason": reason},
    )
    db.commit()
    db.refresh(link)
    return link


def _close_link(
    db: Session, *, model, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, link_id: uuid.UUID,
    effective_to: datetime, action: str, entity_type: str,
):
    link = db.execute(select(model).where(model.id == link_id, model.tenant_id == tenant_id)).scalar_one_or_none()
    if link is None:
        raise WaterTopologyLinkNotFoundError(str(link_id))
    if link.effective_to is not None:
        raise WaterTopologyLinkAlreadyClosedError(str(link_id))
    link.effective_to = effective_to
    db.flush()
    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action=action, entity_type=entity_type,
        entity_id=link.id, event_data={"effective_to": effective_to.isoformat()},
    )
    db.commit()
    db.refresh(link)
    return link


def open_water_source_reservoir_link(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, water_source_id: uuid.UUID,
    reservoir_id: uuid.UUID, effective_from: datetime, reason: str | None,
) -> WaterSourceReservoirLink:
    get_water_source(db, tenant_id=tenant_id, water_source_id=water_source_id)
    get_reservoir(db, tenant_id=tenant_id, reservoir_id=reservoir_id)
    return _open_link(
        db, model=WaterSourceReservoirLink, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id,
        endpoint_columns={"water_source_id": water_source_id, "reservoir_id": reservoir_id},
        effective_from=effective_from, reason=reason, action="water_source_reservoir_link.opened",
        entity_type="water_source_reservoir_link",
        active_unique_constraint="ux_water_source_reservoir_links_active_reservoir",
    )


def close_water_source_reservoir_link(
    db: Session, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, link_id: uuid.UUID, effective_to: datetime,
) -> WaterSourceReservoirLink:
    return _close_link(
        db, model=WaterSourceReservoirLink, tenant_id=tenant_id, actor_user_id=actor_user_id, link_id=link_id,
        effective_to=effective_to, action="water_source_reservoir_link.closed",
        entity_type="water_source_reservoir_link",
    )


def open_reservoir_circuit_link(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, reservoir_id: uuid.UUID,
    irrigation_circuit_id: uuid.UUID, effective_from: datetime, reason: str | None,
) -> ReservoirCircuitLink:
    get_reservoir(db, tenant_id=tenant_id, reservoir_id=reservoir_id)
    get_irrigation_circuit(db, tenant_id=tenant_id, irrigation_circuit_id=irrigation_circuit_id)
    return _open_link(
        db, model=ReservoirCircuitLink, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id,
        endpoint_columns={"reservoir_id": reservoir_id, "irrigation_circuit_id": irrigation_circuit_id},
        effective_from=effective_from, reason=reason, action="reservoir_circuit_link.opened",
        entity_type="reservoir_circuit_link", active_unique_constraint="ux_reservoir_circuit_links_active_circuit",
    )


def close_reservoir_circuit_link(
    db: Session, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, link_id: uuid.UUID, effective_to: datetime,
) -> ReservoirCircuitLink:
    return _close_link(
        db, model=ReservoirCircuitLink, tenant_id=tenant_id, actor_user_id=actor_user_id, link_id=link_id,
        effective_to=effective_to, action="reservoir_circuit_link.closed", entity_type="reservoir_circuit_link",
    )


def open_circuit_delivery_point_link(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID,
    irrigation_circuit_id: uuid.UUID, water_delivery_point_id: uuid.UUID, effective_from: datetime,
    reason: str | None,
) -> CircuitDeliveryPointLink:
    get_irrigation_circuit(db, tenant_id=tenant_id, irrigation_circuit_id=irrigation_circuit_id)
    get_water_delivery_point(db, tenant_id=tenant_id, water_delivery_point_id=water_delivery_point_id)
    return _open_link(
        db, model=CircuitDeliveryPointLink, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id,
        endpoint_columns={
            "irrigation_circuit_id": irrigation_circuit_id, "water_delivery_point_id": water_delivery_point_id,
        },
        effective_from=effective_from, reason=reason, action="circuit_delivery_point_link.opened",
        entity_type="circuit_delivery_point_link",
        active_unique_constraint="ux_circuit_delivery_point_links_active_delivery_point",
    )


def close_circuit_delivery_point_link(
    db: Session, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, link_id: uuid.UUID, effective_to: datetime,
) -> CircuitDeliveryPointLink:
    return _close_link(
        db, model=CircuitDeliveryPointLink, tenant_id=tenant_id, actor_user_id=actor_user_id, link_id=link_id,
        effective_to=effective_to, action="circuit_delivery_point_link.closed",
        entity_type="circuit_delivery_point_link",
    )


def open_return_point_reservoir_link(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID,
    water_return_point_id: uuid.UUID, return_reservoir_id: uuid.UUID, effective_from: datetime, reason: str | None,
) -> ReturnPointReservoirLink:
    get_water_return_point(db, tenant_id=tenant_id, water_return_point_id=water_return_point_id)
    get_reservoir(db, tenant_id=tenant_id, reservoir_id=return_reservoir_id)
    return _open_link(
        db, model=ReturnPointReservoirLink, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id,
        endpoint_columns={
            "water_return_point_id": water_return_point_id, "return_reservoir_id": return_reservoir_id,
        },
        effective_from=effective_from, reason=reason, action="return_point_reservoir_link.opened",
        entity_type="return_point_reservoir_link",
        active_unique_constraint="ux_return_point_reservoir_links_active_return_point",
    )


def close_return_point_reservoir_link(
    db: Session, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, link_id: uuid.UUID, effective_to: datetime,
) -> ReturnPointReservoirLink:
    return _close_link(
        db, model=ReturnPointReservoirLink, tenant_id=tenant_id, actor_user_id=actor_user_id, link_id=link_id,
        effective_to=effective_to, action="return_point_reservoir_link.closed",
        entity_type="return_point_reservoir_link",
    )
