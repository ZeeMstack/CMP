import hashlib
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.batch_harvest_forecast import BatchHarvestForecast
from app.models.crop_issue import CropIssue
from app.models.harvested_produce_lot import HarvestedProduceLot
from app.models.location import Location
from app.models.occupancy import Occupancy
from app.models.unit_of_measure import UnitOfMeasure
from app.schemas.harvest_forecast import (
    BatchHarvestActualSummary,
    BatchHarvestForecastRead,
    BatchHarvestForecastStatusRead,
)
from app.schemas.planning import UomSummary
from app.services import crop_batch_service, farm_service, unit_of_measure_service
from app.services.audit import append_audit_event
from app.services.errors import (
    BatchHarvestForecastCommandReusedWithDifferentPayloadError,
    BatchHarvestForecastNotFoundError,
    BatchHarvestForecastValidationError,
    FarmNotFoundError,
)


def _require_active_farm(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID):
    farm = farm_service.get_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    if farm.status != "active":
        raise FarmNotFoundError(str(farm_id))
    return farm


def _uom_summary(uom: UnitOfMeasure) -> UomSummary:
    return UomSummary(id=uom.id, code=uom.code, name=uom.name, quantity_kind=uom.quantity_kind)


def _compute_fingerprint(
    *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID, actor_user_id: uuid.UUID,
    window_start_date: date, window_end_date: date, low_quantity: Decimal, expected_quantity: Decimal,
    high_quantity: Decimal, quantity_uom_id: uuid.UUID, basis: str, effective_time: datetime,
    notes: str | None, revision_reason: str | None,
) -> str:
    parts = [
        str(tenant_id), str(farm_id), str(batch_id), str(actor_user_id), window_start_date.isoformat(),
        window_end_date.isoformat(), str(low_quantity), str(expected_quantity), str(high_quantity),
        str(quantity_uom_id), basis, effective_time.isoformat(), notes or "", revision_reason or "",
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _row_to_read(forecast: BatchHarvestForecast, uom: UnitOfMeasure) -> BatchHarvestForecastRead:
    return BatchHarvestForecastRead(
        id=forecast.id, tenant_id=forecast.tenant_id, farm_id=forecast.farm_id, batch_id=forecast.batch_id,
        revision_number=forecast.revision_number, is_current=forecast.superseded_at is None,
        superseded_at=forecast.superseded_at, superseded_by_forecast_id=forecast.superseded_by_forecast_id,
        window_start_date=forecast.window_start_date, window_end_date=forecast.window_end_date,
        low_quantity=Decimal(forecast.low_quantity), expected_quantity=Decimal(forecast.expected_quantity),
        high_quantity=Decimal(forecast.high_quantity), uom=_uom_summary(uom), basis=forecast.basis,
        notes=forecast.notes, revision_reason=forecast.revision_reason,
        recorded_by_user_id=forecast.recorded_by_user_id, effective_time=forecast.effective_time,
        recorded_time=forecast.recorded_time,
    )


def _find_current(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID) -> BatchHarvestForecast | None:
    return db.execute(
        select(BatchHarvestForecast).where(
            BatchHarvestForecast.tenant_id == tenant_id, BatchHarvestForecast.farm_id == farm_id,
            BatchHarvestForecast.batch_id == batch_id, BatchHarvestForecast.superseded_at.is_(None),
        )
    ).scalar_one_or_none()


def record_batch_harvest_forecast(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    batch_id: uuid.UUID,
    client_command_id: uuid.UUID,
    window_start_date: date,
    window_end_date: date,
    low_quantity: Decimal,
    expected_quantity: Decimal,
    high_quantity: Decimal,
    quantity_uom_id: uuid.UUID,
    basis: str,
    effective_time: datetime,
    notes: str | None,
    revision_reason: str | None,
) -> BatchHarvestForecast:
    """PILOT-PLAN-001A: records the Batch's first forecast, or revises its
    current one -- never a mutable update in place. This command never
    touches `crop_batches`/`batch_stage_runs`/`occupancies` (CLAUDE.md rule
    "no automatic decisions": forecasting a Batch's harvest must never
    change its stage, create a Harvest, or move it)."""
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    crop_batch_service.get_batch(db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id)
    unit_of_measure_service.get_uom(db, uom_id=quantity_uom_id)

    fingerprint = _compute_fingerprint(
        tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id, actor_user_id=actor_user_id,
        window_start_date=window_start_date, window_end_date=window_end_date, low_quantity=low_quantity,
        expected_quantity=expected_quantity, high_quantity=high_quantity, quantity_uom_id=quantity_uom_id,
        basis=basis, effective_time=effective_time, notes=notes, revision_reason=revision_reason,
    )

    def _find_replay() -> BatchHarvestForecast | None:
        return db.execute(
            select(BatchHarvestForecast).where(
                BatchHarvestForecast.tenant_id == tenant_id,
                BatchHarvestForecast.client_command_id == client_command_id,
            )
        ).scalar_one_or_none()

    existing = _find_replay()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise BatchHarvestForecastCommandReusedWithDifferentPayloadError(str(client_command_id))

    # Tenant-scoped advisory lock serializes concurrent forecast revisions
    # for the same Batch, so "supersede the prior current row, insert the
    # next revision_number" can never race -- mirrors `planning_service`'s
    # own code-generation lock shape.
    db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(f"batch_harvest_forecast:{batch_id}", 0))))

    existing = _find_replay()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise BatchHarvestForecastCommandReusedWithDifferentPayloadError(str(client_command_id))

    prior_current = _find_current(db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id)
    next_revision = (prior_current.revision_number + 1) if prior_current is not None else 1
    new_id = uuid.uuid4()

    forecast = BatchHarvestForecast(
        id=new_id, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id, revision_number=next_revision,
        window_start_date=window_start_date, window_end_date=window_end_date, low_quantity=low_quantity,
        expected_quantity=expected_quantity, high_quantity=high_quantity, quantity_uom_id=quantity_uom_id,
        basis=basis, notes=notes, revision_reason=revision_reason, recorded_by_user_id=actor_user_id,
        effective_time=effective_time, client_command_id=client_command_id, request_fingerprint=fingerprint,
    )
    try:
        if prior_current is not None:
            # Close the prior CURRENT row (and flush it) BEFORE inserting
            # the new one -- `ux_batch_harvest_forecasts_current_batch`
            # (superseded_at IS NULL) is a synchronous partial unique
            # index, so both rows must never simultaneously read as
            # "current" mid-transaction.
            prior_current.superseded_at = datetime.now(timezone.utc)
            prior_current.superseded_by_forecast_id = new_id
            db.flush()
        db.add(forecast)
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        replay = _find_replay()
        if replay is not None and replay.request_fingerprint == fingerprint:
            return replay
        raise BatchHarvestForecastCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="batch_harvest_forecast.recorded",
        entity_type="batch_harvest_forecast", entity_id=forecast.id,
        event_data={
            "batch_id": str(batch_id), "revision_number": next_revision,
            "previous_forecast_id": str(prior_current.id) if prior_current is not None else None,
            "window_start_date": window_start_date.isoformat(), "window_end_date": window_end_date.isoformat(),
            "low_quantity": str(low_quantity), "expected_quantity": str(expected_quantity),
            "high_quantity": str(high_quantity), "quantity_uom_id": str(quantity_uom_id), "basis": basis,
            "revision_reason": revision_reason,
        },
    )
    db.commit()
    db.refresh(forecast)
    return forecast


def get_current_forecast(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID
) -> BatchHarvestForecastRead:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    crop_batch_service.get_batch(db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id)
    forecast = _find_current(db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id)
    if forecast is None:
        raise BatchHarvestForecastNotFoundError(str(batch_id))
    uom = unit_of_measure_service.get_uom(db, uom_id=forecast.quantity_uom_id)
    return _row_to_read(forecast, uom)


def list_forecast_history(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID
) -> list[BatchHarvestForecastRead]:
    """Every revision, oldest first -- the earlier estimate always remains
    inspectable (CLAUDE.md rule 7, 9)."""
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    crop_batch_service.get_batch(db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id)
    rows = db.execute(
        select(BatchHarvestForecast)
        .where(
            BatchHarvestForecast.tenant_id == tenant_id, BatchHarvestForecast.farm_id == farm_id,
            BatchHarvestForecast.batch_id == batch_id,
        )
        .order_by(BatchHarvestForecast.revision_number)
    ).scalars().all()
    uom_cache: dict[uuid.UUID, UnitOfMeasure] = {}
    result = []
    for row in rows:
        if row.quantity_uom_id not in uom_cache:
            uom_cache[row.quantity_uom_id] = unit_of_measure_service.get_uom(db, uom_id=row.quantity_uom_id)
        result.append(_row_to_read(row, uom_cache[row.quantity_uom_id]))
    return result


def _kg_uom(db: Session) -> UnitOfMeasure:
    uom = db.execute(select(UnitOfMeasure).where(UnitOfMeasure.code == "kg")).scalar_one_or_none()
    if uom is None:  # pragma: no cover -- seeded platform-wide, never absent
        raise BatchHarvestForecastValidationError("kg unit of measure is not seeded")
    return uom


def _active_location_codes(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID) -> list[str]:
    carrier_ids = db.execute(
        select(BatchCarrierAssignment.carrier_id).where(
            BatchCarrierAssignment.tenant_id == tenant_id, BatchCarrierAssignment.farm_id == farm_id,
            BatchCarrierAssignment.batch_id == batch_id, BatchCarrierAssignment.released_effective_time.is_(None),
        )
    ).scalars().all()
    if not carrier_ids:
        return []
    codes = db.execute(
        select(Location.code)
        .join(Occupancy, Occupancy.target_location_id == Location.id)
        .where(
            Occupancy.tenant_id == tenant_id, Occupancy.occupant_carrier_id.in_(carrier_ids),
            Occupancy.end_time.is_(None),
        )
        .distinct()
        .order_by(Location.code)
    ).scalars().all()
    return list(codes)


def get_forecast_status(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID
) -> BatchHarvestForecastStatusRead:
    """PILOT-PLAN-001A Part 2/8: forecast vs actual, plus a Crop Issue risk
    signal -- a pure computed read, never a stored comparison, and never a
    write to the forecast row."""
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    batch = crop_batch_service.get_batch(db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id)

    current = _find_current(db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id)
    current_read = None
    if current is not None:
        uom = unit_of_measure_service.get_uom(db, uom_id=current.quantity_uom_id)
        current_read = _row_to_read(current, uom)

    total_weight, first_date, last_date = db.execute(
        select(
            func.coalesce(func.sum(HarvestedProduceLot.total_harvested_weight_kg), 0),
            func.min(HarvestedProduceLot.effective_time),
            func.max(HarvestedProduceLot.effective_time),
        ).where(
            HarvestedProduceLot.tenant_id == tenant_id, HarvestedProduceLot.farm_id == farm_id,
            HarvestedProduceLot.batch_id == batch_id,
        )
    ).one()
    total_weight = Decimal(total_weight)

    comparable = False
    actual_in_forecast_uom: Decimal | None = None
    remaining: Decimal | None = None
    if current is not None:
        kg_uom = _kg_uom(db)
        factor = unit_of_measure_service.resolve_conversion_factor(
            db, from_uom_id=kg_uom.id, to_uom_id=current.quantity_uom_id
        )
        if factor is not None:
            comparable = True
            actual_in_forecast_uom = total_weight * factor
            remaining = Decimal(current.expected_quantity) - actual_in_forecast_uom

    open_issue_count = db.execute(
        select(func.count()).select_from(CropIssue).where(
            CropIssue.tenant_id == tenant_id, CropIssue.farm_id == farm_id, CropIssue.batch_id == batch_id,
            CropIssue.status == "open",
        )
    ).scalar_one()

    return BatchHarvestForecastStatusRead(
        batch_id=batch_id, batch_code=batch.code, crop=batch.crop, variety=batch.variety,
        current_stage=batch.current_stage, current_forecast=current_read,
        actual=BatchHarvestActualSummary(
            total_harvested_weight_kg=total_weight, first_harvest_date=first_date.date() if first_date else None,
            latest_harvest_date=last_date.date() if last_date else None, comparable_to_forecast_uom=comparable,
            actual_quantity_in_forecast_uom=actual_in_forecast_uom,
            remaining_forecast_quantity_in_forecast_uom=remaining,
        ),
        open_crop_issue_count=open_issue_count,
        active_location_codes=_active_location_codes(db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id),
    )


def list_farm_forecast_summary(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, window_start_date: date, window_end_date: date,
) -> list[BatchHarvestForecastStatusRead]:
    """Part 10 COVERAGE: every Batch whose CURRENT forecast window overlaps
    `[window_start_date, window_end_date]` (both inclusive -- forecast
    windows are a human date range, not the half-open interval Capacity
    Allocation uses)."""
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    batch_ids = db.execute(
        select(BatchHarvestForecast.batch_id).where(
            BatchHarvestForecast.tenant_id == tenant_id, BatchHarvestForecast.farm_id == farm_id,
            BatchHarvestForecast.superseded_at.is_(None),
            BatchHarvestForecast.window_start_date <= window_end_date,
            BatchHarvestForecast.window_end_date >= window_start_date,
        )
    ).scalars().all()
    return [
        get_forecast_status(db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id) for batch_id in batch_ids
    ]
