import hashlib
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.finished_goods_ledger_entry import FinishedGoodsLedgerEntry
from app.models.finished_goods_lot import FinishedGoodsLot
from app.models.finished_goods_storage_movement import FinishedGoodsStorageMovement
from app.models.location import Location
from app.models.location_type import LocationType
from app.schemas.finished_goods_storage import (
    FinishedGoodsPlacementRead,
    FinishedGoodsStorageMovementRead,
    LocationBalanceRead,
    LocationInventoryRead,
    LotBalanceRead,
)
from app.schemas.harvest import canonical_decimal_str
from app.services import farm_service
from app.services.audit import append_audit_event
from app.services.errors import (
    FarmNotFoundError,
    FinishedGoodsLotNotFoundError,
    InactiveDestinationLocationError,
    IneligibleStorageLocationError,
    InsufficientStorageLocationBalanceError,
    InsufficientUnplacedQuantityError,
    InvalidStorageMovementEffectiveTimeError,
    StorageCommandReusedWithDifferentPayloadError,
    StorageLocationNotFoundError,
    StorageMovementValidationError,
)

STORAGE_ELIGIBLE_LOCATION_TYPE_CODE = "cold_store_position"


def _require_active_farm(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID):
    farm = farm_service.get_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    if farm.status != "active":
        raise FarmNotFoundError(str(farm_id))
    return farm


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _validate_shape(
    *, movement_kind: str, source_location_id: uuid.UUID | None, destination_location_id: uuid.UUID | None
) -> None:
    if movement_kind not in FinishedGoodsStorageMovement.MOVEMENT_KINDS:
        raise StorageMovementValidationError(f"unrecognized movement_kind {movement_kind!r}")
    if movement_kind == "place":
        if source_location_id is not None or destination_location_id is None:
            raise StorageMovementValidationError("place requires destination_location_id and no source_location_id")
    elif movement_kind == "transfer":
        if source_location_id is None or destination_location_id is None:
            raise StorageMovementValidationError("transfer requires both source_location_id and destination_location_id")
        if source_location_id == destination_location_id:
            raise StorageMovementValidationError("transfer source and destination locations must differ")
    elif movement_kind == "release":
        if source_location_id is None or destination_location_id is not None:
            raise StorageMovementValidationError("release requires source_location_id and no destination_location_id")


def _compute_movement_fingerprint(
    *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, effective_time: datetime,
    finished_goods_lot_id: uuid.UUID, movement_kind: str, source_location_id: uuid.UUID | None,
    destination_location_id: uuid.UUID | None, moved_weight_kg: Decimal, moved_package_count: int,
    note: str | None,
) -> str:
    parts = [
        str(tenant_id), str(farm_id), str(actor_user_id), effective_time.astimezone(timezone.utc).isoformat(),
        str(finished_goods_lot_id), movement_kind, str(source_location_id or ""), str(destination_location_id or ""),
        canonical_decimal_str(moved_weight_kg), str(moved_package_count), note or "",
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _find_existing_movement(
    db: Session, *, tenant_id: uuid.UUID, client_command_id: uuid.UUID
) -> FinishedGoodsStorageMovement | None:
    return db.execute(
        select(FinishedGoodsStorageMovement).where(
            FinishedGoodsStorageMovement.tenant_id == tenant_id,
            FinishedGoodsStorageMovement.client_command_id == client_command_id,
        )
    ).scalar_one_or_none()


# --- Command ------------------------------------------------------------------------


def record_movement(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_command_id: uuid.UUID,
    effective_time: datetime,
    finished_goods_lot_id: uuid.UUID,
    movement_kind: str,
    source_location_id: uuid.UUID | None,
    destination_location_id: uuid.UUID | None,
    moved_weight_kg: Decimal,
    moved_package_count: int,
    note: str | None,
) -> FinishedGoodsStorageMovement:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    if effective_time > datetime.now(timezone.utc):
        raise InvalidStorageMovementEffectiveTimeError("effective_time cannot be in the future")

    _validate_shape(
        movement_kind=movement_kind, source_location_id=source_location_id,
        destination_location_id=destination_location_id,
    )

    fingerprint = _compute_movement_fingerprint(
        tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, effective_time=effective_time,
        finished_goods_lot_id=finished_goods_lot_id, movement_kind=movement_kind,
        source_location_id=source_location_id, destination_location_id=destination_location_id,
        moved_weight_kg=moved_weight_kg, moved_package_count=moved_package_count, note=note,
    )

    existing = _find_existing_movement(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise StorageCommandReusedWithDifferentPayloadError(str(client_command_id))

    # Lock the finished-goods lot first -- the single global serialization
    # point shared with dispatch_service (CMP-017) and the amended ledger
    # insert-integrity trigger (v3): every writer that can change a lot's
    # available/placed quantity locks this row before anything else.
    lot = db.execute(
        select(FinishedGoodsLot).where(
            FinishedGoodsLot.id == finished_goods_lot_id, FinishedGoodsLot.tenant_id == tenant_id,
            FinishedGoodsLot.farm_id == farm_id,
        ).with_for_update()
    ).scalar_one_or_none()
    if lot is None:
        raise FinishedGoodsLotNotFoundError(str(finished_goods_lot_id))

    # Referenced location rows, locked in sorted-UUID order (at most two:
    # source and destination) -- deterministic regardless of which role a
    # given location plays, matching the app-level/trigger-level ordering
    # exactly and avoiding a transfer-vs-transfer deadlock between two
    # movements that reference the same pair of locations in reversed roles.
    location_ids = sorted({loc_id for loc_id in (source_location_id, destination_location_id) if loc_id is not None})
    locked_locations = list(
        db.execute(
            select(Location, LocationType.code)
            .join(LocationType, LocationType.id == Location.location_type_id)
            .where(Location.id.in_(location_ids))
            .order_by(Location.id)
            .with_for_update(of=Location)
        ).all()
    )
    locations_by_id = {loc.id: (loc, type_code) for loc, type_code in locked_locations}

    def _validate_location(location_id: uuid.UUID, *, require_active: bool) -> None:
        found = locations_by_id.get(location_id)
        if found is None:
            raise StorageLocationNotFoundError(str(location_id))
        location, type_code = found
        if location.tenant_id != tenant_id or location.farm_id != farm_id:
            raise StorageLocationNotFoundError(str(location_id))
        if type_code != STORAGE_ELIGIBLE_LOCATION_TYPE_CODE:
            raise IneligibleStorageLocationError(str(location_id))
        if require_active and location.status != "active":
            raise InactiveDestinationLocationError(str(location_id))

    if source_location_id is not None:
        # A source location may be inactive -- CMP-018 adds no
        # location-deactivation guard, so requiring an active source would
        # permanently trap any stock already recorded there.
        _validate_location(source_location_id, require_active=False)
    if destination_location_id is not None:
        _validate_location(destination_location_id, require_active=True)

    existing = _find_existing_movement(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise StorageCommandReusedWithDifferentPayloadError(str(client_command_id))

    # Combined ledger/storage chronology must stay monotonic for this lot:
    # not before the lot's own effective_time, not before the latest prior
    # storage movement, not before the latest prior ledger entry.
    if effective_time < lot.effective_time:
        raise InvalidStorageMovementEffectiveTimeError(
            f"effective_time precedes finished-goods lot {finished_goods_lot_id}'s own effective_time"
        )
    latest_movement_effective = db.execute(
        select(func.max(FinishedGoodsStorageMovement.effective_time)).where(
            FinishedGoodsStorageMovement.finished_goods_lot_id == finished_goods_lot_id
        )
    ).scalar_one_or_none()
    if latest_movement_effective is not None and effective_time < latest_movement_effective:
        raise InvalidStorageMovementEffectiveTimeError(
            f"effective_time precedes the latest existing storage movement for finished-goods lot {finished_goods_lot_id}"
        )
    latest_ledger_effective = db.execute(
        select(func.max(FinishedGoodsLedgerEntry.effective_time)).where(
            FinishedGoodsLedgerEntry.finished_goods_lot_id == finished_goods_lot_id
        )
    ).scalar_one_or_none()
    if latest_ledger_effective is not None and effective_time < latest_ledger_effective:
        raise InvalidStorageMovementEffectiveTimeError(
            f"effective_time precedes the latest ledger entry for finished-goods lot {finished_goods_lot_id}"
        )

    available_row = db.execute(
        select(
            func.coalesce(func.sum(FinishedGoodsLedgerEntry.weight_delta_kg), 0),
            func.coalesce(func.sum(FinishedGoodsLedgerEntry.package_count_delta), 0),
        ).where(FinishedGoodsLedgerEntry.finished_goods_lot_id == finished_goods_lot_id)
    ).one()
    available_weight, available_count = available_row

    placed_row = db.execute(
        text(
            "SELECT "
            "COALESCE(SUM(CASE WHEN movement_kind = 'place' THEN moved_weight_kg "
            "  WHEN movement_kind = 'release' THEN -moved_weight_kg ELSE 0 END), 0) AS weight, "
            "COALESCE(SUM(CASE WHEN movement_kind = 'place' THEN moved_package_count "
            "  WHEN movement_kind = 'release' THEN -moved_package_count ELSE 0 END), 0) AS count "
            "FROM finished_goods_storage_movements WHERE finished_goods_lot_id = :lot"
        ),
        {"lot": finished_goods_lot_id},
    ).mappings().one()
    total_placed_weight, total_placed_count = placed_row["weight"], placed_row["count"]

    if movement_kind == "place":
        unplaced_weight = available_weight - total_placed_weight
        unplaced_count = available_count - total_placed_count
        if moved_weight_kg > unplaced_weight:
            raise InsufficientUnplacedQuantityError(str(finished_goods_lot_id))
        if moved_package_count > unplaced_count:
            raise InsufficientUnplacedQuantityError(str(finished_goods_lot_id))
    else:
        source_balance_row = db.execute(
            text(
                "SELECT "
                "COALESCE(SUM(CASE WHEN destination_location_id = :loc THEN moved_weight_kg ELSE 0 END), 0) "
                "- COALESCE(SUM(CASE WHEN source_location_id = :loc THEN moved_weight_kg ELSE 0 END), 0) AS weight, "
                "COALESCE(SUM(CASE WHEN destination_location_id = :loc THEN moved_package_count ELSE 0 END), 0) "
                "- COALESCE(SUM(CASE WHEN source_location_id = :loc THEN moved_package_count ELSE 0 END), 0) AS count "
                "FROM finished_goods_storage_movements "
                "WHERE finished_goods_lot_id = :lot AND (source_location_id = :loc OR destination_location_id = :loc)"
            ),
            {"loc": source_location_id, "lot": finished_goods_lot_id},
        ).mappings().one()
        source_balance_weight = source_balance_row["weight"]
        source_balance_count = source_balance_row["count"]
        if moved_weight_kg > source_balance_weight:
            raise InsufficientStorageLocationBalanceError(str(source_location_id))
        if moved_package_count > source_balance_count:
            raise InsufficientStorageLocationBalanceError(str(source_location_id))

    movement_id = uuid.uuid4()
    try:
        movement = FinishedGoodsStorageMovement(
            id=movement_id, tenant_id=tenant_id, farm_id=farm_id, finished_goods_lot_id=finished_goods_lot_id,
            movement_kind=movement_kind, source_location_id=source_location_id,
            destination_location_id=destination_location_id, moved_weight_kg=moved_weight_kg,
            moved_package_count=moved_package_count, effective_time=effective_time, actor_user_id=actor_user_id,
            client_command_id=client_command_id, request_fingerprint=fingerprint, note=note,
        )
        db.add(movement)
        db.flush()

        append_audit_event(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="finished_goods.storage_moved",
            entity_type="finished_goods_storage_movement", entity_id=movement.id,
            event_data={
                "movement_id": str(movement.id), "finished_goods_lot_id": str(finished_goods_lot_id),
                "movement_kind": movement_kind,
                "source_location_id": str(source_location_id) if source_location_id else None,
                "destination_location_id": str(destination_location_id) if destination_location_id else None,
                "moved_weight_kg": canonical_decimal_str(moved_weight_kg),
                "moved_package_count": moved_package_count, "effective_time": effective_time.isoformat(),
            },
        )
        db.flush()
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_finished_goods_storage_movements_tenant_client_command_id":
            replay = _find_existing_movement(db, tenant_id=tenant_id, client_command_id=client_command_id)
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise StorageCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise
    except Exception:
        db.rollback()
        raise
    db.refresh(movement)
    return movement


# --- Reads ------------------------------------------------------------------------


def get_movement_history(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, finished_goods_lot_id: uuid.UUID
) -> list[FinishedGoodsStorageMovementRead]:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    lot = db.execute(
        select(FinishedGoodsLot).where(
            FinishedGoodsLot.id == finished_goods_lot_id, FinishedGoodsLot.tenant_id == tenant_id,
            FinishedGoodsLot.farm_id == farm_id,
        )
    ).scalar_one_or_none()
    if lot is None:
        raise FinishedGoodsLotNotFoundError(str(finished_goods_lot_id))
    movements = db.execute(
        select(FinishedGoodsStorageMovement)
        .where(FinishedGoodsStorageMovement.finished_goods_lot_id == finished_goods_lot_id)
        .order_by(
            FinishedGoodsStorageMovement.effective_time, FinishedGoodsStorageMovement.recorded_time,
            FinishedGoodsStorageMovement.id,
        )
    ).scalars().all()
    return [FinishedGoodsStorageMovementRead.model_validate(m, from_attributes=True) for m in movements]


def get_placement(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, finished_goods_lot_id: uuid.UUID
) -> FinishedGoodsPlacementRead:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    lot = db.execute(
        select(FinishedGoodsLot).where(
            FinishedGoodsLot.id == finished_goods_lot_id, FinishedGoodsLot.tenant_id == tenant_id,
            FinishedGoodsLot.farm_id == farm_id,
        )
    ).scalar_one_or_none()
    if lot is None:
        raise FinishedGoodsLotNotFoundError(str(finished_goods_lot_id))

    available_row = db.execute(
        select(
            func.coalesce(func.sum(FinishedGoodsLedgerEntry.weight_delta_kg), 0),
            func.coalesce(func.sum(FinishedGoodsLedgerEntry.package_count_delta), 0),
        ).where(FinishedGoodsLedgerEntry.finished_goods_lot_id == finished_goods_lot_id)
    ).one()
    available_weight, available_count = available_row

    location_rows = db.execute(
        text(
            "SELECT loc_id, SUM(weight_in) - SUM(weight_out) AS weight, "
            "SUM(count_in) - SUM(count_out) AS count FROM ("
            "  SELECT destination_location_id AS loc_id, moved_weight_kg AS weight_in, 0 AS weight_out, "
            "         moved_package_count AS count_in, 0 AS count_out "
            "  FROM finished_goods_storage_movements "
            "  WHERE finished_goods_lot_id = :lot AND destination_location_id IS NOT NULL "
            "  UNION ALL "
            "  SELECT source_location_id AS loc_id, 0, moved_weight_kg, 0, moved_package_count "
            "  FROM finished_goods_storage_movements "
            "  WHERE finished_goods_lot_id = :lot AND source_location_id IS NOT NULL "
            ") x GROUP BY loc_id HAVING SUM(weight_in) - SUM(weight_out) > 0 "
            "ORDER BY loc_id"
        ),
        {"lot": finished_goods_lot_id},
    ).mappings().all()
    locations = [
        LocationBalanceRead(location_id=row["loc_id"], weight_kg=row["weight"], package_count=row["count"])
        for row in location_rows
    ]
    total_placed_weight = sum((loc.weight_kg for loc in locations), Decimal("0"))
    total_placed_count = sum((loc.package_count for loc in locations), 0)

    return FinishedGoodsPlacementRead(
        finished_goods_lot_id=finished_goods_lot_id, finished_goods_lot_code=lot.code,
        available_weight_kg=available_weight, available_package_count=available_count,
        total_placed_weight_kg=total_placed_weight, total_placed_package_count=total_placed_count,
        unplaced_weight_kg=available_weight - total_placed_weight,
        unplaced_package_count=available_count - total_placed_count, locations=locations,
    )


def get_location_inventory(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, location_id: uuid.UUID
) -> LocationInventoryRead:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    location_row = db.execute(
        select(Location, LocationType.code)
        .join(LocationType, LocationType.id == Location.location_type_id)
        .where(Location.id == location_id, Location.tenant_id == tenant_id, Location.farm_id == farm_id)
    ).first()
    if location_row is None:
        raise StorageLocationNotFoundError(str(location_id))
    _location, type_code = location_row
    if type_code != STORAGE_ELIGIBLE_LOCATION_TYPE_CODE:
        raise IneligibleStorageLocationError(str(location_id))

    lot_rows = db.execute(
        text(
            "SELECT fg.id AS lot_id, fg.code AS lot_code, "
            "SUM(weight_in) - SUM(weight_out) AS weight, SUM(count_in) - SUM(count_out) AS count FROM ("
            "  SELECT finished_goods_lot_id, moved_weight_kg AS weight_in, 0 AS weight_out, "
            "         moved_package_count AS count_in, 0 AS count_out "
            "  FROM finished_goods_storage_movements WHERE destination_location_id = :loc "
            "  UNION ALL "
            "  SELECT finished_goods_lot_id, 0, moved_weight_kg, 0, moved_package_count "
            "  FROM finished_goods_storage_movements WHERE source_location_id = :loc "
            ") x JOIN finished_goods_lots fg ON fg.id = x.finished_goods_lot_id "
            "GROUP BY fg.id, fg.code HAVING SUM(weight_in) - SUM(weight_out) > 0 "
            "ORDER BY fg.code"
        ),
        {"loc": location_id},
    ).mappings().all()
    lots = [
        LotBalanceRead(
            finished_goods_lot_id=row["lot_id"], finished_goods_lot_code=row["lot_code"],
            weight_kg=row["weight"], package_count=row["count"],
        )
        for row in lot_rows
    ]
    return LocationInventoryRead(location_id=location_id, lots=lots)
