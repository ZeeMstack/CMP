import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, or_, select, text
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
    """Returns one active occupancy for the target, if any exist.

    DOMAIN-FARM-002: a target with capacity > 1 may have several
    simultaneous active occupancies -- this no longer assumes at most one
    (that guarantee was removed along with the target-side unique indexes).
    Returns an arbitrary one (the earliest by effective_time) rather than
    raising on multiple rows. Existing single-occupant callers
    (`get_target_occupant`) keep working for the still-common capacity=1
    case; they degrade to reporting only one of several occupants for a
    capacity>1 target rather than crashing. A full multi-occupant read is
    deliberately out of this ticket's scope -- see
    `_count_active_occupancies_for_target` for the capacity-enforcement path,
    which counts rather than fetches a single row."""
    if target_kind == "location":
        condition = Occupancy.target_location_id == target_id
    else:
        condition = Occupancy.target_asset_position_id == target_id
    query = select(Occupancy).where(condition, Occupancy.end_time.is_(None)).order_by(Occupancy.effective_time)
    if lock:
        query = query.with_for_update()
    return db.execute(query.limit(1)).scalars().first()


def _count_active_occupancies_for_target(db: Session, *, target_kind: str, target_id: uuid.UUID) -> int:
    if target_kind == "location":
        condition = Occupancy.target_location_id == target_id
    else:
        condition = Occupancy.target_asset_position_id == target_id
    return db.execute(
        select(func.count()).select_from(Occupancy).where(condition, Occupancy.end_time.is_(None))
    ).scalar_one()


def _list_active_occupancies_for_target(db: Session, *, target_kind: str, target_id: uuid.UUID) -> list[Occupancy]:
    """DOMAIN-FARM-002.1: the truthful complement to
    `_get_active_occupancy_for_target` -- returns every active occupancy for
    the target, not just one, so a capacity>1 target's actual state is never
    silently under-reported as if it held a single occupant. Deterministic
    ordering (earliest effective_time first, id as tiebreaker) matches
    `_get_active_occupancy_for_target`'s own choice of "the" occupant, so
    `list(...)[0]` and the singular read agree for the same target."""
    if target_kind == "location":
        condition = Occupancy.target_location_id == target_id
    else:
        condition = Occupancy.target_asset_position_id == target_id
    query = select(Occupancy).where(condition, Occupancy.end_time.is_(None)).order_by(Occupancy.effective_time, Occupancy.id)
    return list(db.execute(query).scalars())


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


_CAPACITY_EXCEEDED_MARKER = "CMP-DOMAIN-FARM-002 target capacity exceeded"


def _is_capacity_exceeded_error(exc: IntegrityError) -> bool:
    """DOMAIN-FARM-002: the DB-layer capacity backstop
    (`enforce_occupancy_insert_integrity`, migration f91c366cfe57) raises
    its trigger exception with SQLSTATE 23514 (check_violation) so it
    surfaces as `IntegrityError` like any other constraint failure here,
    even though capacity is no longer a unique index -- identified by its
    fixed message marker rather than a constraint name, since a trigger
    RAISE has no constraint to name. In the normal application path this is
    unreachable (the service already checks capacity under the same target
    row lock before ever attempting the insert); this exists purely so a
    direct-SQL/ORM write bypassing movement_service still surfaces as a
    clean domain error, not a raw trigger message, if it somehow reaches
    this code path."""
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    message = getattr(diag, "message_primary", None) or str(orig or exc)
    return _CAPACITY_EXCEEDED_MARKER in message


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
    """Public entry point: runs `_execute_movement_core` then owns the
    transaction boundary (commit + refresh) itself, exactly as before this
    function was split -- every existing caller's behavior is unchanged."""
    movement = _execute_movement_core(
        db,
        tenant_id=tenant_id,
        farm_id=farm_id,
        actor_user_id=actor_user_id,
        client_command_id=client_command_id,
        effective_time=effective_time,
        occupant_kind=occupant_kind,
        occupant_id=occupant_id,
        destination_kind=destination_kind,
        destination_id=destination_id,
        reason=reason,
    )
    db.commit()
    db.refresh(movement)
    return movement


def _execute_movement_core(
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
    """NURSERY-OPS-003A: the validate+insert+flush core of `execute_movement`,
    with no commit and no refresh -- reused directly by
    `seedling_entry_service` so a Seedling-entry command can perform the
    physical Movement and insert its own `SeedlingEntry` row inside ONE
    transaction/commit (section 15/16 of the ticket), exactly the same
    extraction pattern `location_service._create_location_core` and
    `_bulk_generate_children_core` already established for FARM-SETUP-001.
    Every check, lock, and IntegrityError-recovery path below is unchanged
    from before the split; only the trailing `db.commit()`/`db.refresh()`
    moved to the public wrapper above. A flush-time IntegrityError still
    triggers this function's own `db.rollback()` -- safe for a caller
    composing a larger transaction only if nothing that caller needs to
    survive was written before this call (true for `seedling_entry_service`,
    whose own reads before this call are all plain SELECTs); Postgres would
    force that rollback on any aborted statement regardless, so this is not
    an added constraint, merely the existing one made explicit."""
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

        # DOMAIN-FARM-002: destination_row was already locked (FOR UPDATE)
        # by _resolve_target above -- capacity is decided under that same
        # lock, so a concurrent mover targeting the same destination blocks
        # here rather than racing. NULL capacity means an effective
        # capacity of 1 (exclusive, backward-compatible with pre-capacity
        # behavior).
        effective_capacity = destination_row.capacity or 1
        active_target_count = _count_active_occupancies_for_target(
            db, target_kind=destination_kind, target_id=destination_id
        )
        if active_target_count >= effective_capacity:
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
            if constraint in ("ux_occupancies_active_occupant_asset", "ux_occupancies_active_occupant_carrier"):
                raise OccupantAlreadyActiveError(str(occupant_id)) from exc
            # DOMAIN-FARM-002: capacity is enforced by a trigger (row-locked
            # COUNT check), not a unique index -- see
            # _is_capacity_exceeded_error. Unreachable via this normal
            # application path (the service's own pre-check above already
            # holds the same target row lock), kept as a defensive backstop.
            if _is_capacity_exceeded_error(exc):
                raise TargetOccupiedError(str(destination_id)) from exc
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
    return movement


# --- Read queries -----------------------------------------------------------


def get_occupancy(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, occupant_kind: str, occupant_id: uuid.UUID
) -> Occupancy | None:
    _resolve_occupant(db, tenant_id=tenant_id, farm_id=farm_id, occupant_kind=occupant_kind, occupant_id=occupant_id)
    return _get_active_occupancy_for_occupant(db, occupant_kind=occupant_kind, occupant_id=occupant_id)


def get_carrier_location_as_of(db: Session, *, carrier_id: uuid.UUID, as_of: datetime) -> uuid.UUID | None:
    """HARVEST-OPS-001 SLICE 2 CORRECTION 1: the Carrier's physical
    `target_location_id` as of a historical timestamp -- NOT its current
    occupancy. Interval semantics mirror `observation_service.record_
    observation`'s own historical `BatchStageRun` resolution exactly
    (open-bound inclusive, close-bound exclusive-with-null-escape):
    `effective_time <= as_of AND (end_time IS NULL OR end_time > as_of)`.
    Only ever meaningful for a Carrier occupying a fixed Location directly
    (Harvest's own callers never need the Asset-position/relative-path
    resolution `get_resolved_location` provides) -- returns `None`,
    never a fallback to current location, if no Occupancy interval
    legitimately contains `as_of` (e.g. the Carrier had no Occupancy row
    yet at that instant)."""
    return db.execute(
        select(Occupancy.target_location_id)
        .where(
            Occupancy.occupant_carrier_id == carrier_id,
            Occupancy.target_location_id.is_not(None),
            Occupancy.effective_time <= as_of,
            or_(Occupancy.end_time.is_(None), Occupancy.end_time > as_of),
        )
        .order_by(Occupancy.effective_time.desc())
        .limit(1)
    ).scalar_one_or_none()


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
    """Legacy singular read -- for a capacity>1 target with several active
    occupancies, returns only one of them (the earliest). Kept for backward
    compatibility; callers that need the true, complete state must use
    `list_target_occupants` instead (its API-facing response also carries
    an explicit count, see `TargetOccupantRead.active_occupancy_count`, so
    this endpoint's output is never silently presented as complete)."""
    _resolve_target(db, tenant_id=tenant_id, farm_id=farm_id, target_kind=target_kind, target_id=target_id)
    return _get_active_occupancy_for_target(db, target_kind=target_kind, target_id=target_id)


def list_target_occupants(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, target_kind: str, target_id: uuid.UUID
) -> list[Occupancy]:
    """DOMAIN-FARM-002.1: the truthful, complete read -- every active
    occupancy for the target, in deterministic order. For a truly exclusive
    (capacity<=1) target this returns 0 or 1 rows, identical in substance to
    `get_target_occupant`; for capacity>1 it returns all of them."""
    _resolve_target(db, tenant_id=tenant_id, farm_id=farm_id, target_kind=target_kind, target_id=target_id)
    return _list_active_occupancies_for_target(db, target_kind=target_kind, target_id=target_id)


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
