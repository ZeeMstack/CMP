"""PILOT-WATER-001A sections 9-11: WaterInstrument identity (referencing an
existing Asset -- never a second physical-object catalog), immutable
Calibration history, and immutable pH/EC/temperature/DO Measurements.

Rule 7 (ticket): calibration status is never inferred from a Measurement
merely existing -- `instrument_calibration_status` below is the one read
that answers "is this instrument currently calibrated", and it looks only
at `InstrumentCalibrationEvent` history, never at `WaterMeasurement`.
"""

import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.instrument_calibration_event import InstrumentCalibrationEvent
from app.models.sampling_point import SamplingPoint
from app.models.water_instrument import WaterInstrument
from app.models.water_measurement import CANONICAL_UNIT_BY_METRIC
from app.services import water_command_identity
from app.services.audit import append_audit_event
from app.services.errors import (
    AssetNotFoundError,
    DuplicateWaterInstrumentAssetError,
    InstrumentCalibrationValidationError,
    SamplingPointNotFoundError,
    WaterInstrumentNotFoundError,
    WaterInstrumentValidationError,
    WaterMeasurementValidationError,
)


def _fingerprint(*parts: object) -> str:
    return hashlib.sha256("|".join("" if p is None else str(p) for p in parts).encode("utf-8")).hexdigest()


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


# --- WaterInstrument -------------------------------------------------------------------


def register_water_instrument(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, asset_id: uuid.UUID,
    supports_ph: bool, supports_ec: bool, supports_solution_temperature: bool, supports_dissolved_oxygen: bool,
) -> WaterInstrument:
    asset = db.execute(
        select(Asset).where(Asset.id == asset_id, Asset.tenant_id == tenant_id, Asset.farm_id == farm_id)
    ).scalar_one_or_none()
    if asset is None:
        raise AssetNotFoundError(str(asset_id))
    if not any((supports_ph, supports_ec, supports_solution_temperature, supports_dissolved_oxygen)):
        raise WaterInstrumentValidationError("an instrument must support at least one measurement metric")

    instrument = WaterInstrument(
        tenant_id=tenant_id, farm_id=farm_id, asset_id=asset_id, supports_ph=supports_ph, supports_ec=supports_ec,
        supports_solution_temperature=supports_solution_temperature,
        supports_dissolved_oxygen=supports_dissolved_oxygen,
    )
    db.add(instrument)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateWaterInstrumentAssetError(f"{tenant_id}:{asset_id}") from exc

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="water_instrument.registered",
        entity_type="water_instrument", entity_id=instrument.id, event_data={"asset_id": str(asset_id)},
    )
    db.commit()
    db.refresh(instrument)
    return instrument


def get_water_instrument(db: Session, *, tenant_id: uuid.UUID, water_instrument_id: uuid.UUID) -> WaterInstrument:
    instrument = db.execute(
        select(WaterInstrument).where(
            WaterInstrument.id == water_instrument_id, WaterInstrument.tenant_id == tenant_id
        )
    ).scalar_one_or_none()
    if instrument is None:
        raise WaterInstrumentNotFoundError(str(water_instrument_id))
    return instrument


def list_water_instruments(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> list[WaterInstrument]:
    return list(
        db.execute(
            select(WaterInstrument).where(
                WaterInstrument.tenant_id == tenant_id, WaterInstrument.farm_id == farm_id
            )
        ).scalars()
    )


# --- InstrumentCalibrationEvent ---------------------------------------------------------


def record_calibration(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID,
    water_instrument_id: uuid.UUID, metric: str, effective_at: datetime | None, result: str,
    standard_reference: str | None, notes: str | None, client_command_id: uuid.UUID,
) -> InstrumentCalibrationEvent:
    """PILOT-WATER-001B: `effective_at=None` is "record now" -- see
    `record_measurement`'s own identical HOTFIX-TIME-002 note."""
    get_water_instrument(db, tenant_id=tenant_id, water_instrument_id=water_instrument_id)
    fingerprint = _fingerprint(tenant_id, water_instrument_id, metric, effective_at, result, standard_reference)

    existing = db.execute(
        select(InstrumentCalibrationEvent).where(
            InstrumentCalibrationEvent.tenant_id == tenant_id,
            InstrumentCalibrationEvent.client_command_id == client_command_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise InstrumentCalibrationValidationError(f"client_command_id {client_command_id} reused with a different payload")

    if effective_at is None:
        effective_at = datetime.now(timezone.utc)
    elif effective_at > datetime.now(timezone.utc):
        raise InstrumentCalibrationValidationError("effective_at cannot be in the future")

    event = InstrumentCalibrationEvent(
        tenant_id=tenant_id, farm_id=farm_id, water_instrument_id=water_instrument_id, metric=metric,
        effective_at=effective_at, recorded_by_user_id=actor_user_id, result=result,
        standard_reference=standard_reference, notes=notes, client_command_id=client_command_id,
        request_fingerprint=fingerprint,
    )
    db.add(event)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_instrument_calibration_events_tenant_client_command_id":
            replay = db.execute(
                select(InstrumentCalibrationEvent).where(
                    InstrumentCalibrationEvent.tenant_id == tenant_id,
                    InstrumentCalibrationEvent.client_command_id == client_command_id,
                )
            ).scalar_one_or_none()
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="instrument_calibration_event.recorded",
        entity_type="instrument_calibration_event", entity_id=event.id,
        event_data={"water_instrument_id": str(water_instrument_id), "metric": metric, "result": result},
    )
    db.commit()
    db.refresh(event)
    return event


def list_calibration_events(
    db: Session, *, tenant_id: uuid.UUID, water_instrument_id: uuid.UUID
) -> list[InstrumentCalibrationEvent]:
    get_water_instrument(db, tenant_id=tenant_id, water_instrument_id=water_instrument_id)
    return list(
        db.execute(
            select(InstrumentCalibrationEvent)
            .where(
                InstrumentCalibrationEvent.tenant_id == tenant_id,
                InstrumentCalibrationEvent.water_instrument_id == water_instrument_id,
            )
            .order_by(InstrumentCalibrationEvent.effective_at.desc())
        ).scalars()
    )


def instrument_calibration_status(db: Session, *, tenant_id: uuid.UUID, water_instrument_id: uuid.UUID) -> dict:
    """Read-only: the latest calibration event per metric, if any. Never
    states "calibrated" from a Measurement's mere existence (ticket rule
    7) -- only from this table."""
    events = list_calibration_events(db, tenant_id=tenant_id, water_instrument_id=water_instrument_id)
    latest_by_metric: dict[str, InstrumentCalibrationEvent] = {}
    for event in events:
        if event.metric not in latest_by_metric:
            latest_by_metric[event.metric] = event
    return {
        "water_instrument_id": water_instrument_id,
        "latest_by_metric": {
            metric: {
                "effective_at": event.effective_at, "result": event.result,
                "standard_reference": event.standard_reference,
            }
            for metric, event in latest_by_metric.items()
        },
    }


# --- WaterMeasurement --------------------------------------------------------------------


def record_measurement(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, sampling_point_id: uuid.UUID,
    metric: str, value, unit: str, effective_at: datetime | None, water_instrument_id: uuid.UUID | None,
    notes: str | None, client_command_id: uuid.UUID,
):
    """PILOT-WATER-001B (HOTFIX-TIME-002 pattern): `effective_at=None` is
    "record now" -- resolved to the server's own authoritative
    `datetime.now(timezone.utc)` only after the idempotency check below
    confirms this is a genuinely new command (never part of the
    fingerprint itself), so a retry of the same NOW command always replays
    the original measurement rather than being rejected as "reused with a
    different payload" or creating a second row."""
    sampling_point = db.execute(
        select(SamplingPoint).where(SamplingPoint.id == sampling_point_id, SamplingPoint.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if sampling_point is None:
        raise SamplingPointNotFoundError(str(sampling_point_id))

    expected_unit = CANONICAL_UNIT_BY_METRIC.get(metric)
    if expected_unit is None:
        raise WaterMeasurementValidationError(f"unknown metric {metric!r}")
    if unit != expected_unit:
        raise WaterMeasurementValidationError(f"metric {metric!r} requires unit {expected_unit!r}, got {unit!r}")

    if water_instrument_id is not None:
        get_water_instrument(db, tenant_id=tenant_id, water_instrument_id=water_instrument_id)

    from app.models.water_measurement import WaterMeasurement

    # UX-OPS-001D (N03): every material fact, farm scope included.
    fingerprint = water_command_identity.complete_fingerprint(
        "water_measurement.record",
        {
            "farm_id": water_command_identity.canonical_uuid(farm_id),
            "sampling_point_id": water_command_identity.canonical_uuid(sampling_point_id),
            "metric": metric,
            "value": water_command_identity.canonical_decimal(value),
            "unit": unit,
            "effective_at": water_command_identity.canonical_instant(effective_at),
            "water_instrument_id": water_command_identity.canonical_uuid(water_instrument_id),
            "notes": notes,
        },
    )
    legacy = water_command_identity.legacy_fingerprint(
        tenant_id, sampling_point_id, metric, value, unit, effective_at, water_instrument_id
    )

    def is_replay(row: WaterMeasurement) -> bool:
        return water_command_identity.is_replay(
            stored_fingerprint=row.request_fingerprint, complete=fingerprint, legacy=legacy,
            persisted_facts_match=lambda: (
                row.farm_id == farm_id
                and row.sampling_point_id == sampling_point_id
                and row.metric == metric
                and water_command_identity.decimals_equal(row.value, value)
                and row.unit == unit
                and water_command_identity.effective_time_matches(row.effective_at, effective_at)
                and row.water_instrument_id == water_instrument_id
                and row.notes == notes
            ),
        )

    existing = db.execute(
        select(WaterMeasurement).where(
            WaterMeasurement.tenant_id == tenant_id, WaterMeasurement.client_command_id == client_command_id
        )
    ).scalar_one_or_none()
    if existing is not None:
        if is_replay(existing):
            return existing
        raise WaterMeasurementValidationError(f"client_command_id {client_command_id} reused with a different payload")

    if effective_at is None:
        effective_at = datetime.now(timezone.utc)
    elif effective_at > datetime.now(timezone.utc):
        raise WaterMeasurementValidationError("effective_at cannot be in the future")

    measurement = WaterMeasurement(
        tenant_id=tenant_id, farm_id=farm_id, sampling_point_id=sampling_point_id, metric=metric, value=value,
        unit=unit, effective_at=effective_at, recorded_by_user_id=actor_user_id,
        water_instrument_id=water_instrument_id, notes=notes, client_command_id=client_command_id,
        request_fingerprint=fingerprint,
    )
    db.add(measurement)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_water_measurements_tenant_client_command_id":
            replay = db.execute(
                select(WaterMeasurement).where(
                    WaterMeasurement.tenant_id == tenant_id, WaterMeasurement.client_command_id == client_command_id
                )
            ).scalar_one_or_none()
            if replay is not None:
                if is_replay(replay):
                    return replay
                raise WaterMeasurementValidationError(
                    f"client_command_id {client_command_id} reused with a different payload"
                ) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="water_measurement.recorded",
        entity_type="water_measurement", entity_id=measurement.id,
        event_data={
            "sampling_point_id": str(sampling_point_id), "metric": metric, "value": str(value), "unit": unit,
        },
    )
    db.commit()
    db.refresh(measurement)
    return measurement


def list_measurements(
    db: Session, *, tenant_id: uuid.UUID, sampling_point_id: uuid.UUID, limit: int = 100
):
    from app.models.water_measurement import WaterMeasurement

    return list(
        db.execute(
            select(WaterMeasurement)
            .where(WaterMeasurement.tenant_id == tenant_id, WaterMeasurement.sampling_point_id == sampling_point_id)
            .order_by(WaterMeasurement.effective_at.desc())
            .limit(limit)
        ).scalars()
    )


def list_measurements_for_farm(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, metric: str | None = None,
    reservoir_id: uuid.UUID | None = None, window_start=None, window_end=None, limit: int = 200,
):
    """PILOT-WATER-001B: farm-wide, optionally filtered -- powers both the
    Overview workspace's "latest key measurements" and the dedicated
    Measurement History page's Sampling Point/Reservoir/metric/time-window
    filters (section 12), rather than two separate reads. `reservoir_id`
    filters through `SamplingPoint.reservoir_id` (only meaningful for
    reservoir-anchored Sampling Points; a source/circuit/delivery/drain
    -anchored point is simply excluded when this filter is set, never
    silently misattributed to a Reservoir it isn't anchored to)."""
    from app.models.water_measurement import WaterMeasurement

    query = select(WaterMeasurement).where(WaterMeasurement.tenant_id == tenant_id, WaterMeasurement.farm_id == farm_id)
    if metric is not None:
        query = query.where(WaterMeasurement.metric == metric)
    if window_start is not None:
        query = query.where(WaterMeasurement.effective_at >= window_start)
    if window_end is not None:
        query = query.where(WaterMeasurement.effective_at <= window_end)
    if reservoir_id is not None:
        query = query.join(SamplingPoint, SamplingPoint.id == WaterMeasurement.sampling_point_id).where(
            SamplingPoint.reservoir_id == reservoir_id
        )
    return list(db.execute(query.order_by(WaterMeasurement.effective_at.desc()).limit(limit)).scalars())
