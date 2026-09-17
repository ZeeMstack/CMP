"""PILOT-WATER-001A sections 16-17: ReservoirEvent (actual top-up/
addition/adjustment/flush/drain) and WaterDeliveryEvent (actual delivery
interval from a Reservoir through an IrrigationCircuit). Neither table nor
this module ever computes or recommends a dosage, and neither infers a
resulting EC/pH -- an operator records the observed result afterward as a
`WaterMeasurement` (a separate, independent fact -- rule 4/section 16)."""

import hashlib
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.inventory_item import InventoryItem
from app.models.reservoir_event import ReservoirEvent
from app.models.unit_of_measure import UnitOfMeasure
from app.models.water_delivery_event import WaterDeliveryEvent
from app.services import nutrient_mix_service, water_topology_service
from app.services.audit import append_audit_event
from app.services.errors import (
    InventoryItemNotFoundError,
    ReservoirEventValidationError,
    UnitOfMeasureKindMismatchError,
    UnitOfMeasureNotFoundError,
    WaterDeliveryEventValidationError,
)


def _fingerprint(*parts: object) -> str:
    return hashlib.sha256("|".join("" if p is None else str(p) for p in parts).encode("utf-8")).hexdigest()


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _require_uom(db: Session, *, uom_id: uuid.UUID) -> UnitOfMeasure:
    uom = db.execute(select(UnitOfMeasure).where(UnitOfMeasure.id == uom_id)).scalar_one_or_none()
    if uom is None:
        raise UnitOfMeasureNotFoundError(str(uom_id))
    return uom


def _require_volume_uom(db: Session, *, uom_id: uuid.UUID) -> UnitOfMeasure:
    uom = _require_uom(db, uom_id=uom_id)
    if uom.quantity_kind != "volume":
        raise UnitOfMeasureKindMismatchError(f"{uom.code} is not a volume unit")
    return uom


# --- ReservoirEvent ---------------------------------------------------------------------


def record_reservoir_event(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, reservoir_id: uuid.UUID,
    event_type: str, effective_at: datetime, quantity, quantity_uom_id: uuid.UUID | None,
    inventory_item_id: uuid.UUID | None, notes: str | None, client_command_id: uuid.UUID,
) -> ReservoirEvent:
    water_topology_service.get_reservoir(db, tenant_id=tenant_id, reservoir_id=reservoir_id)
    if quantity_uom_id is not None:
        _require_uom(db, uom_id=quantity_uom_id)
    if inventory_item_id is not None:
        item = db.execute(
            select(InventoryItem).where(InventoryItem.id == inventory_item_id, InventoryItem.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if item is None:
            raise InventoryItemNotFoundError(str(inventory_item_id))

    fingerprint = _fingerprint(tenant_id, reservoir_id, event_type, effective_at, quantity, quantity_uom_id, inventory_item_id)
    existing = db.execute(
        select(ReservoirEvent).where(ReservoirEvent.tenant_id == tenant_id, ReservoirEvent.client_command_id == client_command_id)
    ).scalar_one_or_none()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise ReservoirEventValidationError(f"client_command_id {client_command_id} reused with a different payload")

    event = ReservoirEvent(
        tenant_id=tenant_id, farm_id=farm_id, reservoir_id=reservoir_id, event_type=event_type,
        effective_at=effective_at, operator_user_id=actor_user_id, quantity=quantity,
        quantity_uom_id=quantity_uom_id, inventory_item_id=inventory_item_id, notes=notes,
        client_command_id=client_command_id, request_fingerprint=fingerprint,
    )
    db.add(event)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_reservoir_events_tenant_client_command_id":
            replay = db.execute(
                select(ReservoirEvent).where(
                    ReservoirEvent.tenant_id == tenant_id, ReservoirEvent.client_command_id == client_command_id
                )
            ).scalar_one_or_none()
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="reservoir_event.recorded",
        entity_type="reservoir_event", entity_id=event.id,
        event_data={"reservoir_id": str(reservoir_id), "event_type": event_type},
    )
    db.commit()
    db.refresh(event)
    return event


def list_reservoir_events(db: Session, *, tenant_id: uuid.UUID, reservoir_id: uuid.UUID) -> list[ReservoirEvent]:
    return list(
        db.execute(
            select(ReservoirEvent)
            .where(ReservoirEvent.tenant_id == tenant_id, ReservoirEvent.reservoir_id == reservoir_id)
            .order_by(ReservoirEvent.effective_at.desc())
        ).scalars()
    )


# --- WaterDeliveryEvent -----------------------------------------------------------------


def record_delivery_event(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, reservoir_id: uuid.UUID,
    irrigation_circuit_id: uuid.UUID, effective_start: datetime, effective_end: datetime | None, delivered_volume,
    delivered_volume_uom_id: uuid.UUID | None, nutrient_mix_id: uuid.UUID | None, notes: str | None,
    client_command_id: uuid.UUID,
) -> WaterDeliveryEvent:
    water_topology_service.get_reservoir(db, tenant_id=tenant_id, reservoir_id=reservoir_id)
    water_topology_service.get_irrigation_circuit(db, tenant_id=tenant_id, irrigation_circuit_id=irrigation_circuit_id)
    if delivered_volume_uom_id is not None:
        _require_volume_uom(db, uom_id=delivered_volume_uom_id)
    if nutrient_mix_id is not None:
        nutrient_mix_service.get_mix(db, tenant_id=tenant_id, nutrient_mix_id=nutrient_mix_id)

    fingerprint = _fingerprint(
        tenant_id, reservoir_id, irrigation_circuit_id, effective_start, effective_end, delivered_volume,
        nutrient_mix_id,
    )
    existing = db.execute(
        select(WaterDeliveryEvent).where(
            WaterDeliveryEvent.tenant_id == tenant_id, WaterDeliveryEvent.client_command_id == client_command_id
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise WaterDeliveryEventValidationError(f"client_command_id {client_command_id} reused with a different payload")

    event = WaterDeliveryEvent(
        tenant_id=tenant_id, farm_id=farm_id, reservoir_id=reservoir_id,
        irrigation_circuit_id=irrigation_circuit_id, effective_start=effective_start, effective_end=effective_end,
        delivered_volume=delivered_volume, delivered_volume_uom_id=delivered_volume_uom_id,
        recorded_by_user_id=actor_user_id, nutrient_mix_id=nutrient_mix_id, notes=notes,
        client_command_id=client_command_id, request_fingerprint=fingerprint,
    )
    db.add(event)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_water_delivery_events_tenant_client_command_id":
            replay = db.execute(
                select(WaterDeliveryEvent).where(
                    WaterDeliveryEvent.tenant_id == tenant_id,
                    WaterDeliveryEvent.client_command_id == client_command_id,
                )
            ).scalar_one_or_none()
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="water_delivery_event.recorded",
        entity_type="water_delivery_event", entity_id=event.id,
        event_data={"reservoir_id": str(reservoir_id), "irrigation_circuit_id": str(irrigation_circuit_id)},
    )
    db.commit()
    db.refresh(event)
    return event


def list_delivery_events_for_circuit(
    db: Session, *, tenant_id: uuid.UUID, irrigation_circuit_id: uuid.UUID
) -> list[WaterDeliveryEvent]:
    return list(
        db.execute(
            select(WaterDeliveryEvent)
            .where(
                WaterDeliveryEvent.tenant_id == tenant_id,
                WaterDeliveryEvent.irrigation_circuit_id == irrigation_circuit_id,
            )
            .order_by(WaterDeliveryEvent.effective_start.desc())
        ).scalars()
    )
