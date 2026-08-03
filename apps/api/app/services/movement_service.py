import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.asset_position import AssetPosition
from app.models.carrier import Carrier
from app.models.location import Location
from app.models.movement import Movement
from app.models.occupancy import Occupancy
from app.models.occupancy_compatibility_rule import OccupancyCompatibilityRule
from app.services import farm_service
from app.services.audit import append_audit_event
from app.services.errors import (
    AssetCannotOccupyOwnPositionError,
    AssetNotFoundError,
    AssetPositionNotFoundError,
    CarrierNotFoundError,
    FarmNotFoundError,
    InactiveOccupantError,
    InactiveTargetError,
    IncompatibleOccupantTargetError,
    InvalidEffectiveTimeError,
    LocationNotFoundError,
    MovementCommandReusedWithDifferentPayloadError,
    NoOpMovementError,
    NothingToRemoveError,
    OccupantAlreadyActiveError,
    TargetNotOccupiableError,
    TargetOccupiedError,
)

COMMAND_TYPE = "movement"


def _require_active_farm(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> None:
    farm = farm_service.get_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    if farm.status != "active":
        raise FarmNotFoundError(str(farm_id))


def _resolve_occupant(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, occupant_kind: str, occupant_id: uuid.UUID,
    lock: bool = False,
):
    if occupant_kind == "asset":
        query = select(Asset).where(Asset.id == occupant_id, Asset.tenant_id == tenant_id, Asset.farm_id == farm_id)
        if lock:
            query = query.with_for_update()
        asset = db.execute(query).scalar_one_or_none()
        if asset is None:
            raise AssetNotFoundError(str(occupant_id))
        if asset.status != "active":
            raise InactiveOccupantError(str(occupant_id))
        return asset, asset.asset_type_id
    query = select(Carrier).where(
        Carrier.id == occupant_id, Carrier.tenant_id == tenant_id, Carrier.farm_id == farm_id
    )
    if lock:
        query = query.with_for_update()
    carrier = db.execute(query).scalar_one_or_none()
    if carrier is None:
        raise CarrierNotFoundError(str(occupant_id))
    if carrier.status != "active":
        raise InactiveOccupantError(str(occupant_id))
    return carrier, carrier.carrier_type_id


def _resolve_target(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, target_kind: str, target_id: uuid.UUID,
    lock: bool = False,
):
    if target_kind == "location":
        query = select(Location).where(
            Location.id == target_id, Location.tenant_id == tenant_id, Location.farm_id == farm_id
        )
        if lock:
            query = query.with_for_update()
        location = db.execute(query).scalar_one_or_none()
        if location is None:
            raise LocationNotFoundError(str(target_id))
        if location.status != "active":
            raise InactiveTargetError(str(target_id))
        if not location.occupiable:
            raise TargetNotOccupiableError(str(target_id))
        return location, location.location_type_id

    query = select(AssetPosition).where(AssetPosition.id == target_id)
    if lock:
        query = query.with_for_update()
    position = db.execute(query).scalar_one_or_none()
    if position is None:
        raise AssetPositionNotFoundError(str(target_id))
    containing_asset = db.execute(
        select(Asset).where(Asset.id == position.asset_id, Asset.tenant_id == tenant_id, Asset.farm_id == farm_id)
    ).scalar_one_or_none()
    if containing_asset is None:
        raise AssetPositionNotFoundError(str(target_id))
    if containing_asset.status != "active":
        raise InactiveTargetError(str(target_id))
    return position, position.position_kind


def _get_active_occupancy_for_occupant(
    db: Session, *, occupant_kind: str, occupant_id: uuid.UUID, lock: bool = False
) -> Occupancy | None:
    if occupant_kind == "asset":
        condition = Occupancy.occupant_asset_id == occupant_id
    else:
        condition = Occupancy.occupant_carrier_id == occupant_id
    query = select(Occupancy).where(condition, Occupancy.end_time.is_(None))
    if lock:
        query = query.with_for_update()
    return db.execute(query).scalar_one_or_none()


def _get_active_occupancy_for_target(
    db: Session, *, target_kind: str, target_id: uuid.UUID, lock: bool = False
) -> Occupancy | None:
    if target_kind == "location":
        condition = Occupancy.target_location_id == target_id
    else:
        condition = Occupancy.target_asset_position_id == target_id
    query = select(Occupancy).where(condition, Occupancy.end_time.is_(None))
    if lock:
        query = query.with_for_update()
    return db.execute(query).scalar_one_or_none()


def _target_kind_id(occupancy: Occupancy) -> tuple[str, uuid.UUID]:
    if occupancy.target_location_id is not None:
        return "location", occupancy.target_location_id
    return "asset_position", occupancy.target_asset_position_id


def _check_compatibility(
    db: Session, *, occupant_kind: str, occupant_type_id, destination_kind: str, destination_type_or_kind
) -> None:
    conditions = []
    if occupant_kind == "asset":
        conditions.append(OccupancyCompatibilityRule.occupant_asset_type_id == occupant_type_id)
    else:
        conditions.append(OccupancyCompatibilityRule.occupant_carrier_type_id == occupant_type_id)
    if destination_kind == "location":
        conditions.append(OccupancyCompatibilityRule.target_location_type_id == destination_type_or_kind)
    else:
        conditions.append(OccupancyCompatibilityRule.target_position_kind == destination_type_or_kind)
    found = db.execute(select(OccupancyCompatibilityRule.id).where(*conditions)).scalar_one_or_none()
    if found is None:
        raise IncompatibleOccupantTargetError(f"{occupant_kind}:{destination_kind}")


def _compute_fingerprint(
    *, tenant_id, farm_id, actor_user_id, occupant_kind, occupant_id, destination_kind, destination_id,
    effective_time: datetime, reason: str | None,
) -> str:
    parts = [
        str(tenant_id),
        str(farm_id),
        str(actor_user_id) if actor_user_id else "",
        occupant_kind,
        str(occupant_id),
        destination_kind or "",
        str(destination_id) if destination_id else "",
        effective_time.astimezone(timezone.utc).isoformat(),
        reason or "",
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _find_existing_movement(db: Session, *, tenant_id: uuid.UUID, client_command_id: uuid.UUID) -> Movement | None:
    return db.execute(
        select(Movement).where(
            Movement.tenant_id == tenant_id,
            Movement.command_type == COMMAND_TYPE,
            Movement.client_command_id == client_command_id,
        )
    ).scalar_one_or_none()


def execute_movement(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    client_command_id: uuid.UUID,
    effective_time: datetime,
    occupant_kind: str,
    occupant_id: uuid.UUID,
    destination_kind: str | None,
    destination_id: uuid.UUID | None,
    reason: str | None,
) -> Movement:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    fingerprint = _compute_fingerprint(
        tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id,
        occupant_kind=occupant_kind, occupant_id=occupant_id,
        destination_kind=destination_kind, destination_id=destination_id,
        effective_time=effective_time, reason=reason,
    )

    existing = _find_existing_movement(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise MovementCommandReusedWithDifferentPayloadError(str(client_command_id))

    if effective_time > datetime.now(timezone.utc):
        raise InvalidEffectiveTimeError("effective_time cannot be in the future")

    # Lock occupant, then destination, in a consistent order to reduce deadlock risk.
    occupant_row, occupant_type_id = _resolve_occupant(
        db, tenant_id=tenant_id, farm_id=farm_id, occupant_kind=occupant_kind, occupant_id=occupant_id, lock=True
    )

    # Re-check idempotency now that the occupant row lock has serialized us
    # behind any concurrent submission of the same command id: a losing
    # concurrent duplicate must resolve as a replay here, before business
    # rules (no-op / target-occupied) evaluate state a concurrent winner may
    # have just committed.
    existing = _find_existing_movement(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise MovementCommandReusedWithDifferentPayloadError(str(client_command_id))

    destination_row = None
    destination_type_or_kind = None
    if destination_kind is not None:
        destination_row, destination_type_or_kind = _resolve_target(
            db, tenant_id=tenant_id, farm_id=farm_id, target_kind=destination_kind, target_id=destination_id,
            lock=True,
        )

    current_occupancy = _get_active_occupancy_for_occupant(
        db, occupant_kind=occupant_kind, occupant_id=occupant_id, lock=True
    )
    if current_occupancy is not None and effective_time < current_occupancy.effective_time:
        raise InvalidEffectiveTimeError("effective_time precedes the occupant's current active occupancy")

    source_kind: str | None
    source_id: uuid.UUID | None
    if destination_kind is None:
        if current_occupancy is None:
            raise NothingToRemoveError(str(occupant_id))
        source_kind, source_id = _target_kind_id(current_occupancy)
    else:
        if current_occupancy is not None:
            source_kind, source_id = _target_kind_id(current_occupancy)
            if source_kind == destination_kind and source_id == destination_id:
                raise NoOpMovementError(str(destination_id))
        else:
            source_kind, source_id = None, None

        if destination_kind == "asset_position" and occupant_kind == "asset" and destination_row.asset_id == occupant_id:
            raise AssetCannotOccupyOwnPositionError(str(occupant_id))

        target_occupancy = _get_active_occupancy_for_target(
            db, target_kind=destination_kind, target_id=destination_id, lock=True
        )
        if target_occupancy is not None:
            raise TargetOccupiedError(str(destination_id))

        _check_compatibility(
            db, occupant_kind=occupant_kind, occupant_type_id=occupant_type_id,
            destination_kind=destination_kind, destination_type_or_kind=destination_type_or_kind,
        )

    movement = Movement(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        farm_id=farm_id,
        occupant_asset_id=occupant_id if occupant_kind == "asset" else None,
        occupant_carrier_id=occupant_id if occupant_kind == "carrier" else None,
        source_location_id=source_id if source_kind == "location" else None,
        source_asset_position_id=source_id if source_kind == "asset_position" else None,
        destination_location_id=destination_id if destination_kind == "location" else None,
        destination_asset_position_id=destination_id if destination_kind == "asset_position" else None,
        command_type=COMMAND_TYPE,
        client_command_id=client_command_id,
        request_fingerprint=fingerprint,
        effective_time=effective_time,
        actor_user_id=actor_user_id,
        reason=reason,
    )
    db.add(movement)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_movements_tenant_command_client_id":
            replay = _find_existing_movement(db, tenant_id=tenant_id, client_command_id=client_command_id)
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise MovementCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    if current_occupancy is not None:
        current_occupancy.end_time = effective_time
        current_occupancy.closed_by_movement_id = movement.id
        db.flush()

    if destination_kind is not None:
        new_occupancy = Occupancy(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            farm_id=farm_id,
            occupant_asset_id=occupant_id if occupant_kind == "asset" else None,
            occupant_carrier_id=occupant_id if occupant_kind == "carrier" else None,
            target_location_id=destination_id if destination_kind == "location" else None,
            target_asset_position_id=destination_id if destination_kind == "asset_position" else None,
            effective_time=effective_time,
            opened_by_movement_id=movement.id,
            actor_user_id=actor_user_id,
        )
        db.add(new_occupancy)
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            constraint = _constraint_name(exc)
            if constraint in ("ux_occupancies_active_target_location", "ux_occupancies_active_target_position"):
                raise TargetOccupiedError(str(destination_id)) from exc
            if constraint in ("ux_occupancies_active_occupant_asset", "ux_occupancies_active_occupant_carrier"):
                raise OccupantAlreadyActiveError(str(occupant_id)) from exc
            raise

    kind = "removal" if destination_kind is None else ("placement" if source_kind is None else "move")
    append_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="movement.executed",
        entity_type="movement",
        entity_id=movement.id,
        event_data={
            "movement_id": str(movement.id),
            "client_command_id": str(client_command_id),
            "kind": kind,
            "occupant_type": occupant_kind,
            "occupant_id": str(occupant_id),
            "source": {"kind": source_kind, "id": str(source_id)} if source_kind else None,
            "destination": {"kind": destination_kind, "id": str(destination_id)} if destination_kind else None,
            "effective_time": effective_time.isoformat(),
            "reason": reason,
        },
    )
    db.commit()
    db.refresh(movement)
    return movement


# --- Read queries -----------------------------------------------------------


def get_occupancy(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, occupant_kind: str, occupant_id: uuid.UUID
) -> Occupancy | None:
    _resolve_occupant(db, tenant_id=tenant_id, farm_id=farm_id, occupant_kind=occupant_kind, occupant_id=occupant_id)
    return _get_active_occupancy_for_occupant(db, occupant_kind=occupant_kind, occupant_id=occupant_id)


def get_movement_history(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, occupant_kind: str, occupant_id: uuid.UUID
) -> list[Movement]:
    _resolve_occupant(db, tenant_id=tenant_id, farm_id=farm_id, occupant_kind=occupant_kind, occupant_id=occupant_id)
    condition = (
        Movement.occupant_asset_id == occupant_id
        if occupant_kind == "asset"
        else Movement.occupant_carrier_id == occupant_id
    )
    return list(
        db.execute(
            select(Movement)
            .where(Movement.tenant_id == tenant_id, Movement.farm_id == farm_id, condition)
            .order_by(Movement.effective_time.desc(), Movement.recorded_time.desc())
        ).scalars()
    )


def get_target_occupant(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, target_kind: str, target_id: uuid.UUID
) -> Occupancy | None:
    _resolve_target(db, tenant_id=tenant_id, farm_id=farm_id, target_kind=target_kind, target_id=target_id)
    return _get_active_occupancy_for_target(db, target_kind=target_kind, target_id=target_id)


def _location_path(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, location_id: uuid.UUID) -> list[dict]:
    result = db.execute(
        text(
            """
            WITH RECURSIVE ancestry AS (
                SELECT id, parent_location_id, code, name, 0 AS depth
                FROM locations
                WHERE id = :location_id AND tenant_id = :tenant_id AND farm_id = :farm_id
                UNION ALL
                SELECT l.id, l.parent_location_id, l.code, l.name, a.depth + 1
                FROM locations l
                JOIN ancestry a ON l.id = a.parent_location_id
            )
            SELECT id, code, name FROM ancestry ORDER BY depth DESC
            """
        ),
        {"location_id": location_id, "tenant_id": tenant_id, "farm_id": farm_id},
    )
    return [dict(row) for row in result.mappings().all()]


def _position_path(db: Session, *, asset_id: uuid.UUID, position_id: uuid.UUID) -> list[dict]:
    result = db.execute(
        text(
            """
            WITH RECURSIVE ancestry AS (
                SELECT id, parent_position_id, code, name, 0 AS depth
                FROM asset_positions
                WHERE id = :position_id AND asset_id = :asset_id
                UNION ALL
                SELECT p.id, p.parent_position_id, p.code, p.name, a.depth + 1
                FROM asset_positions p
                JOIN ancestry a ON p.id = a.parent_position_id
            )
            SELECT id, code, name FROM ancestry ORDER BY depth DESC
            """
        ),
        {"position_id": position_id, "asset_id": asset_id},
    )
    return [dict(row) for row in result.mappings().all()]


def get_resolved_location(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, occupant_kind: str, occupant_id: uuid.UUID
) -> dict:
    _resolve_occupant(db, tenant_id=tenant_id, farm_id=farm_id, occupant_kind=occupant_kind, occupant_id=occupant_id)
    active = _get_active_occupancy_for_occupant(db, occupant_kind=occupant_kind, occupant_id=occupant_id)

    base = {
        "occupant": {"kind": occupant_kind, "id": occupant_id},
        "direct_target": None,
        "position_path": None,
        "containing_asset": None,
        "fixed_location_path": None,
        "path_string": None,
        "unresolved_reason": None,
    }
    if active is None:
        base["unresolved_reason"] = "occupant has no active occupancy"
        return base

    target_kind, target_id = _target_kind_id(active)
    base["direct_target"] = {"kind": target_kind, "id": target_id}

    if target_kind == "location":
        path = _location_path(db, tenant_id=tenant_id, farm_id=farm_id, location_id=target_id)
        base["fixed_location_path"] = path
        base["path_string"] = " / ".join(entry["code"] for entry in path)
        return base

    # Carrier in an asset position: resolve the position's relative path,
    # then the containing asset's own active fixed-location occupancy.
    position = db.get(AssetPosition, target_id)
    containing_asset = db.get(Asset, position.asset_id)
    base["containing_asset"] = {"id": containing_asset.id, "code": containing_asset.code, "name": containing_asset.name}
    position_path = _position_path(db, asset_id=containing_asset.id, position_id=target_id)
    base["position_path"] = position_path

    asset_occupancy = _get_active_occupancy_for_occupant(db, occupant_kind="asset", occupant_id=containing_asset.id)
    if asset_occupancy is None or asset_occupancy.target_location_id is None:
        base["unresolved_reason"] = "containing asset has no active fixed-location occupancy"
        return base

    location_path = _location_path(
        db, tenant_id=tenant_id, farm_id=farm_id, location_id=asset_occupancy.target_location_id
    )
    base["fixed_location_path"] = location_path
    parts = (
        [entry["code"] for entry in location_path]
        + [containing_asset.code]
        + [entry["code"] for entry in position_path]
    )
    base["path_string"] = " / ".join(parts)
    return base
