"""PILOT-WATER-001A sections 16-17: ReservoirEvent (actual top-up/
addition/adjustment/flush/drain) and WaterDeliveryEvent (actual delivery
interval from a Reservoir through an IrrigationCircuit). Neither table nor
this module ever computes or recommends a dosage, and neither infers a
resulting EC/pH -- an operator records the observed result afterward as a
`WaterMeasurement` (a separate, independent fact -- rule 4/section 16)."""

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.inventory_item import InventoryItem
from app.models.reservoir_event import ReservoirEvent
from app.models.unit_of_measure import UnitOfMeasure
from app.models.water_delivery_end_event import WaterDeliveryEndEvent
from app.models.water_delivery_event import WaterDeliveryEvent
from app.services import nutrient_mix_service, water_command_identity, water_topology_service
from app.services.audit import append_audit_event
from app.services.errors import (
    InventoryItemNotFoundError,
    ReservoirEventValidationError,
    UnitOfMeasureKindMismatchError,
    UnitOfMeasureNotFoundError,
    WaterDeliveryEndCommandConflictError,
    WaterDeliveryEndValidationError,
    WaterDeliveryEventAlreadyEndedError,
    WaterDeliveryEventNotFoundError,
    WaterDeliveryEventValidationError,
)


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
    event_type: str, effective_at: datetime | None, quantity, quantity_uom_id: uuid.UUID | None,
    inventory_item_id: uuid.UUID | None, notes: str | None, client_command_id: uuid.UUID,
) -> ReservoirEvent:
    """PILOT-WATER-001B: `effective_at=None` is "record now" -- see
    `water_instrument_service.record_measurement`'s own identical
    HOTFIX-TIME-002 note."""
    water_topology_service.get_reservoir(db, tenant_id=tenant_id, reservoir_id=reservoir_id)
    if quantity_uom_id is not None:
        _require_uom(db, uom_id=quantity_uom_id)
    if inventory_item_id is not None:
        item = db.execute(
            select(InventoryItem).where(InventoryItem.id == inventory_item_id, InventoryItem.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if item is None:
            raise InventoryItemNotFoundError(str(inventory_item_id))

    # UX-OPS-001D (N03): every material fact, farm scope included.
    ident = water_command_identity
    fingerprint = ident.complete_fingerprint(
        "reservoir_event.record",
        {
            "farm_id": ident.canonical_uuid(farm_id),
            "reservoir_id": ident.canonical_uuid(reservoir_id),
            "event_type": event_type,
            "effective_at": ident.canonical_instant(effective_at),
            "quantity": ident.canonical_decimal(quantity),
            "quantity_uom_id": ident.canonical_uuid(quantity_uom_id),
            "inventory_item_id": ident.canonical_uuid(inventory_item_id),
            "notes": notes,
        },
    )
    legacy = ident.legacy_fingerprint(
        tenant_id, reservoir_id, event_type, effective_at, quantity, quantity_uom_id, inventory_item_id
    )

    def is_replay(row: ReservoirEvent) -> bool:
        return ident.is_replay(
            stored_fingerprint=row.request_fingerprint, complete=fingerprint, legacy=legacy,
            persisted_facts_match=lambda: (
                row.farm_id == farm_id
                and row.reservoir_id == reservoir_id
                and row.event_type == event_type
                and ident.effective_time_matches(row.effective_at, effective_at)
                and ident.decimals_equal(row.quantity, quantity)
                and row.quantity_uom_id == quantity_uom_id
                and row.inventory_item_id == inventory_item_id
                and row.notes == notes
            ),
        )

    existing = db.execute(
        select(ReservoirEvent).where(ReservoirEvent.tenant_id == tenant_id, ReservoirEvent.client_command_id == client_command_id)
    ).scalar_one_or_none()
    if existing is not None:
        if is_replay(existing):
            return existing
        raise ReservoirEventValidationError(f"client_command_id {client_command_id} reused with a different payload")

    if effective_at is None:
        effective_at = datetime.now(timezone.utc)
    elif effective_at > datetime.now(timezone.utc):
        raise ReservoirEventValidationError("effective_at cannot be in the future")

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
            if replay is not None:
                if is_replay(replay):
                    return replay
                raise ReservoirEventValidationError(
                    f"client_command_id {client_command_id} reused with a different payload"
                ) from exc
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
    irrigation_circuit_id: uuid.UUID, effective_start: datetime | None, effective_end: datetime | None,
    delivered_volume, delivered_volume_uom_id: uuid.UUID | None, nutrient_mix_id: uuid.UUID | None,
    notes: str | None, client_command_id: uuid.UUID,
) -> WaterDeliveryEvent:
    """PILOT-WATER-001B: `effective_start=None` is "starting now" -- see
    `water_instrument_service.record_measurement`'s own identical
    HOTFIX-TIME-002 note. `effective_end=None` remains its own, separate
    fact (section 21/17 of WATER-001A/001B): an ongoing/continuous
    delivery that has not (yet) ended -- never conflated with "starting
    now"."""
    water_topology_service.get_reservoir(db, tenant_id=tenant_id, reservoir_id=reservoir_id)
    water_topology_service.get_irrigation_circuit(db, tenant_id=tenant_id, irrigation_circuit_id=irrigation_circuit_id)
    if delivered_volume_uom_id is not None:
        _require_volume_uom(db, uom_id=delivered_volume_uom_id)
    if nutrient_mix_id is not None:
        nutrient_mix_service.get_mix(db, tenant_id=tenant_id, nutrient_mix_id=nutrient_mix_id)

    # UX-OPS-001D (N03): every material fact, farm scope included. The
    # original row's own `effective_end` (never the resolved End Delivery
    # end) is the fact this command recorded.
    ident = water_command_identity
    fingerprint = ident.complete_fingerprint(
        "water_delivery_event.record",
        {
            "farm_id": ident.canonical_uuid(farm_id),
            "reservoir_id": ident.canonical_uuid(reservoir_id),
            "irrigation_circuit_id": ident.canonical_uuid(irrigation_circuit_id),
            "effective_start": ident.canonical_instant(effective_start),
            "effective_end": ident.canonical_instant(effective_end),
            "delivered_volume": ident.canonical_decimal(delivered_volume),
            "delivered_volume_uom_id": ident.canonical_uuid(delivered_volume_uom_id),
            "nutrient_mix_id": ident.canonical_uuid(nutrient_mix_id),
            "notes": notes,
        },
    )
    legacy = ident.legacy_fingerprint(
        tenant_id, reservoir_id, irrigation_circuit_id, effective_start, effective_end, delivered_volume,
        nutrient_mix_id,
    )

    def is_replay(row: WaterDeliveryEvent) -> bool:
        return ident.is_replay(
            stored_fingerprint=row.request_fingerprint, complete=fingerprint, legacy=legacy,
            persisted_facts_match=lambda: (
                row.farm_id == farm_id
                and row.reservoir_id == reservoir_id
                and row.irrigation_circuit_id == irrigation_circuit_id
                and ident.effective_time_matches(row.effective_start, effective_start)
                and ident.instants_equal(row.effective_end, effective_end)
                and ident.decimals_equal(row.delivered_volume, delivered_volume)
                and row.delivered_volume_uom_id == delivered_volume_uom_id
                and row.nutrient_mix_id == nutrient_mix_id
                and row.notes == notes
            ),
        )

    existing = db.execute(
        select(WaterDeliveryEvent).where(
            WaterDeliveryEvent.tenant_id == tenant_id, WaterDeliveryEvent.client_command_id == client_command_id
        )
    ).scalar_one_or_none()
    if existing is not None:
        if is_replay(existing):
            return existing
        raise WaterDeliveryEventValidationError(f"client_command_id {client_command_id} reused with a different payload")

    now = datetime.now(timezone.utc)
    if effective_start is None:
        effective_start = now
    elif effective_start > now:
        raise WaterDeliveryEventValidationError("effective_start cannot be in the future")
    if effective_end is not None and effective_end > now:
        raise WaterDeliveryEventValidationError("effective_end cannot be in the future")

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
            if replay is not None:
                if is_replay(replay):
                    return replay
                raise WaterDeliveryEventValidationError(
                    f"client_command_id {client_command_id} reused with a different payload"
                ) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="water_delivery_event.recorded",
        entity_type="water_delivery_event", entity_id=event.id,
        event_data={"reservoir_id": str(reservoir_id), "irrigation_circuit_id": str(irrigation_circuit_id)},
    )
    db.commit()
    db.refresh(event)
    return event


# --- Resolved delivery read (UX-OPS-001D0) -------------------------------------------

END_SOURCE_RECORDED_AT_CREATION = "RECORDED_AT_CREATION"
END_SOURCE_END_EVENT = "END_EVENT"


@dataclass(frozen=True)
class ResolvedWaterDeliveryEvent:
    """Read projection of a `WaterDeliveryEvent` with its DOMAIN end
    resolved as `original effective_end ?? end-event effective_end ?? NULL`
    -- never a mutation of the insert-only ORM row. `effective_end` keeps
    its existing public meaning (NULL = still ongoing); `end_source` says
    which fact supplied it."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    reservoir_id: uuid.UUID
    irrigation_circuit_id: uuid.UUID
    effective_start: datetime
    effective_end: datetime | None
    delivered_volume: Decimal | None
    delivered_volume_uom_id: uuid.UUID | None
    nutrient_mix_id: uuid.UUID | None
    notes: str | None
    end_source: str | None
    water_delivery_end_event_id: uuid.UUID | None
    end_note: str | None


def _resolved_delivery_select():
    return select(WaterDeliveryEvent, WaterDeliveryEndEvent).outerjoin(
        WaterDeliveryEndEvent,
        and_(
            WaterDeliveryEndEvent.water_delivery_event_id == WaterDeliveryEvent.id,
            WaterDeliveryEndEvent.tenant_id == WaterDeliveryEvent.tenant_id,
            WaterDeliveryEndEvent.farm_id == WaterDeliveryEvent.farm_id,
        ),
    )


def _resolve(event: WaterDeliveryEvent, end_event: WaterDeliveryEndEvent | None) -> ResolvedWaterDeliveryEvent:
    if event.effective_end is not None:
        effective_end, end_source = event.effective_end, END_SOURCE_RECORDED_AT_CREATION
    elif end_event is not None:
        effective_end, end_source = end_event.effective_end, END_SOURCE_END_EVENT
    else:
        effective_end, end_source = None, None
    return ResolvedWaterDeliveryEvent(
        id=event.id, tenant_id=event.tenant_id, farm_id=event.farm_id, reservoir_id=event.reservoir_id,
        irrigation_circuit_id=event.irrigation_circuit_id, effective_start=event.effective_start,
        effective_end=effective_end, delivered_volume=event.delivered_volume,
        delivered_volume_uom_id=event.delivered_volume_uom_id, nutrient_mix_id=event.nutrient_mix_id,
        notes=event.notes, end_source=end_source,
        water_delivery_end_event_id=end_event.id if end_event is not None else None,
        end_note=end_event.note if end_event is not None else None,
    )


def resolve_delivery_event(db: Session, *, tenant_id: uuid.UUID, event: WaterDeliveryEvent) -> ResolvedWaterDeliveryEvent:
    end_event = db.execute(
        select(WaterDeliveryEndEvent).where(
            WaterDeliveryEndEvent.tenant_id == tenant_id, WaterDeliveryEndEvent.water_delivery_event_id == event.id
        )
    ).scalar_one_or_none()
    return _resolve(event, end_event)


def get_delivery_event(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, water_delivery_event_id: uuid.UUID
) -> ResolvedWaterDeliveryEvent:
    """Missing, cross-tenant, and cross-farm ids all raise the same
    `WaterDeliveryEventNotFoundError` -- existence never leaks."""
    row = db.execute(
        _resolved_delivery_select().where(
            WaterDeliveryEvent.id == water_delivery_event_id,
            WaterDeliveryEvent.tenant_id == tenant_id,
            WaterDeliveryEvent.farm_id == farm_id,
        )
    ).one_or_none()
    if row is None:
        raise WaterDeliveryEventNotFoundError(str(water_delivery_event_id))
    return _resolve(row[0], row[1])


# --- End Delivery command (UX-OPS-001D0, N07) ----------------------------------------


def _end_fingerprint(
    *, farm_id: uuid.UUID, water_delivery_event_id: uuid.UUID, effective_end: datetime, note: str | None
) -> str:
    """Every material request field, canonically serialized: the same
    instant in a different UTC offset fingerprints identically, and a
    `None` note never collides with an empty-string note."""
    payload = {
        "command": "water_delivery_event.end",
        "farm_id": str(farm_id),
        "water_delivery_event_id": str(water_delivery_event_id),
        "effective_end": effective_end.astimezone(timezone.utc).isoformat(),
        "note": note,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _replay_end_command(
    db: Session, *, tenant_id: uuid.UUID, client_command_id: uuid.UUID, fingerprint: str
) -> ResolvedWaterDeliveryEvent | None:
    existing = db.execute(
        select(WaterDeliveryEndEvent).where(
            WaterDeliveryEndEvent.tenant_id == tenant_id, WaterDeliveryEndEvent.client_command_id == client_command_id
        )
    ).scalar_one_or_none()
    if existing is None:
        return None
    if existing.request_fingerprint != fingerprint:
        raise WaterDeliveryEndCommandConflictError(
            f"client_command_id {client_command_id} reused with a different payload"
        )
    event = db.execute(
        select(WaterDeliveryEvent).where(
            WaterDeliveryEvent.id == existing.water_delivery_event_id, WaterDeliveryEvent.tenant_id == tenant_id
        )
    ).scalar_one()
    return _resolve(event, existing)


def end_delivery_event(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID,
    water_delivery_event_id: uuid.UUID, effective_end: datetime, note: str | None, client_command_id: uuid.UUID,
) -> ResolvedWaterDeliveryEvent:
    """Ends an ONGOING delivery (created with `effective_end = NULL`) by
    appending one immutable `WaterDeliveryEndEvent` plus a
    `water_delivery_event.ended` audit event in a single commit. The
    original `water_delivery_events` row is never updated.

    Records only `effective_end` and an optional `note` (operator-approved
    scope) -- never a final volume, UOM, mix, reservoir, circuit, or start.

    Idempotent: the same `client_command_id` + same payload replays the
    original success (no second row, no second audit); a different payload
    conflicts. The target row is locked (`FOR UPDATE`) so concurrent close
    attempts serialize; `ux_water_delivery_end_events_delivery` is the
    final, database-level guarantee that at most one end event exists."""
    fingerprint = _end_fingerprint(
        farm_id=farm_id, water_delivery_event_id=water_delivery_event_id, effective_end=effective_end, note=note
    )
    replay = _replay_end_command(db, tenant_id=tenant_id, client_command_id=client_command_id, fingerprint=fingerprint)
    if replay is not None:
        return replay

    event = db.execute(
        select(WaterDeliveryEvent)
        .where(
            WaterDeliveryEvent.id == water_delivery_event_id,
            WaterDeliveryEvent.tenant_id == tenant_id,
            WaterDeliveryEvent.farm_id == farm_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if event is None:
        raise WaterDeliveryEventNotFoundError(str(water_delivery_event_id))

    # Re-check under the lock: a concurrent same-command request that
    # committed while this one waited must replay, not report "already
    # ended".
    replay = _replay_end_command(db, tenant_id=tenant_id, client_command_id=client_command_id, fingerprint=fingerprint)
    if replay is not None:
        return replay

    if event.effective_end is not None:
        raise WaterDeliveryEventAlreadyEndedError(
            f"water delivery event {water_delivery_event_id} was recorded with an end and cannot be ended again"
        )
    already_ended = db.execute(
        select(WaterDeliveryEndEvent.id).where(
            WaterDeliveryEndEvent.tenant_id == tenant_id,
            WaterDeliveryEndEvent.water_delivery_event_id == water_delivery_event_id,
        )
    ).scalar_one_or_none()
    if already_ended is not None:
        raise WaterDeliveryEventAlreadyEndedError(f"water delivery event {water_delivery_event_id} is already ended")

    if effective_end < event.effective_start:
        raise WaterDeliveryEndValidationError("effective_end cannot be before the delivery's effective_start")
    if effective_end > datetime.now(timezone.utc):
        raise WaterDeliveryEndValidationError("effective_end cannot be in the future")

    end_event = WaterDeliveryEndEvent(
        tenant_id=tenant_id, farm_id=farm_id, water_delivery_event_id=water_delivery_event_id,
        effective_end=effective_end, note=note, recorded_by_user_id=actor_user_id,
        client_command_id=client_command_id, request_fingerprint=fingerprint,
    )
    db.add(end_event)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_water_delivery_end_events_tenant_client_command_id":
            replay = _replay_end_command(
                db, tenant_id=tenant_id, client_command_id=client_command_id, fingerprint=fingerprint
            )
            if replay is not None:
                return replay
        if constraint == "ux_water_delivery_end_events_delivery":
            raise WaterDeliveryEventAlreadyEndedError(
                f"water delivery event {water_delivery_event_id} is already ended"
            ) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="water_delivery_event.ended",
        entity_type="water_delivery_event", entity_id=water_delivery_event_id,
        event_data={
            "water_delivery_end_event_id": str(end_event.id),
            "effective_end": effective_end.astimezone(timezone.utc).isoformat(),
            "note": note,
            "client_command_id": str(client_command_id),
        },
    )
    db.commit()
    db.refresh(end_event)
    return _resolve(event, end_event)


def list_delivery_events_for_circuit(
    db: Session, *, tenant_id: uuid.UUID, irrigation_circuit_id: uuid.UUID
) -> list[ResolvedWaterDeliveryEvent]:
    rows = db.execute(
        _resolved_delivery_select()
        .where(
            WaterDeliveryEvent.tenant_id == tenant_id,
            WaterDeliveryEvent.irrigation_circuit_id == irrigation_circuit_id,
        )
        .order_by(WaterDeliveryEvent.effective_start.desc())
    ).all()
    return [_resolve(event, end_event) for event, end_event in rows]


def list_reservoir_events_for_farm(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, limit: int = 50
) -> list[ReservoirEvent]:
    """PILOT-WATER-001B: farm-wide -- the Overview workspace's "recent
    activity" needs this across every Reservoir, which WATER-001A had no
    read for (only per-Reservoir)."""
    return list(
        db.execute(
            select(ReservoirEvent)
            .where(ReservoirEvent.tenant_id == tenant_id, ReservoirEvent.farm_id == farm_id)
            .order_by(ReservoirEvent.effective_at.desc())
            .limit(limit)
        ).scalars()
    )


def list_delivery_events_for_farm(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, limit: int = 50
) -> list[ResolvedWaterDeliveryEvent]:
    """PILOT-WATER-001B: farm-wide -- same reasoning as
    `list_reservoir_events_for_farm` above, for Delivery Events."""
    rows = db.execute(
        _resolved_delivery_select()
        .where(WaterDeliveryEvent.tenant_id == tenant_id, WaterDeliveryEvent.farm_id == farm_id)
        .order_by(WaterDeliveryEvent.effective_start.desc())
        .limit(limit)
    ).all()
    return [_resolve(event, end_event) for event, end_event in rows]
