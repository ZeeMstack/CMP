import hashlib
import uuid

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.location import Location
from app.models.location_type import LocationType
from app.models.location_type_hierarchy_rule import LocationTypeHierarchyRule
from app.services import farm_service, movement_service
from app.services.audit import append_audit_event
from app.services.errors import (
    DuplicateLocationCodeError,
    FarmNotFoundError,
    InactiveParentLocationError,
    InvalidLocationHierarchyError,
    LocationDeactivationReusedWithDifferentPayloadError,
    LocationHasActiveChildrenError,
    LocationHasActiveOccupancyError,
    LocationNotActiveError,
    LocationNotFoundError,
    LocationNotInactiveError,
    LocationParentNotActiveError,
    LocationReactivationReusedWithDifferentPayloadError,
    LocationTypeNotFoundError,
    LocationUpdateReusedWithDifferentPayloadError,
)


_CODE_UNIQUENESS_CONSTRAINTS = ("ux_locations_sibling_code_lower", "ux_locations_root_code_lower")


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _require_active_farm(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> None:
    farm = farm_service.get_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    if farm.status != "active":
        raise FarmNotFoundError(str(farm_id))


def _get_location_type_by_code(db: Session, code: str) -> LocationType:
    location_type = db.execute(
        select(LocationType).where(LocationType.code == code)
    ).scalar_one_or_none()
    if location_type is None:
        raise LocationTypeNotFoundError(code)
    return location_type


def get_location_type_code_map(db: Session) -> dict[uuid.UUID, str]:
    """STORE-INV-001B: `location_types` is small (~26 rows), global, and
    unchanged mid-request -- one full-table read, not a new public
    endpoint (none exists for this catalog, deliberately)."""
    return {row.id: row.code for row in db.execute(select(LocationType)).scalars()}


def _get_active_location_in_scope(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, location_id: uuid.UUID
) -> Location:
    """UX-IA-001: row-locks the parent FOR UPDATE -- a plain unlocked read
    here would let a concurrent `deactivate_location(parent)` commit between
    this check and the child insert that follows, producing an inactive
    parent with an active child (the one invariant this whole feature
    exists to protect). Locking the same row `deactivate_location` already
    locks via `_lock_location` means the two commands correctly serialize:
    whichever transaction commits first is the one the other observes.
    Every existing caller of this helper (`_create_location_core`,
    `_bulk_generate_children_core`) is already a write path inside an open
    transaction, so holding this lock through to that transaction's own
    commit is always correct here, never a read-endpoint concern."""
    location = db.execute(
        select(Location)
        .where(
            Location.id == location_id,
            Location.tenant_id == tenant_id,
            Location.farm_id == farm_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if location is None:
        raise LocationNotFoundError(str(location_id))
    if location.status != "active":
        raise InactiveParentLocationError(str(location_id))
    return location


def _resolve_governing_greenhouse_classification(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, parent: Location | None
) -> str | None:
    """DOMAIN-FARM-001: walks the parent's ancestor chain (inclusive of the
    parent itself) for the nearest `greenhouse`-typed location, returning its
    (immutable) `greenhouse_classification`. Returns `None` when there is no
    parent (farm-root creation) or no greenhouse ancestor exists (e.g. a
    `store`/`cold_store`/`packing_hall`/`dispatch_area` tree) — in either
    case the generic, classification-agnostic hierarchy rules govern,
    exactly as before this ticket. A greenhouse can never itself have a
    greenhouse ancestor (no hierarchy rule permits nesting one), so "nearest"
    is unambiguous."""
    if parent is None:
        return None
    return db.execute(
        text(
            """
            WITH RECURSIVE ancestry AS (
                SELECT l.id, l.parent_location_id, l.greenhouse_classification, lt.code AS type_code, 0 AS depth
                FROM locations l
                JOIN location_types lt ON lt.id = l.location_type_id
                WHERE l.id = :start_id AND l.tenant_id = :tenant_id AND l.farm_id = :farm_id
                UNION ALL
                SELECT l.id, l.parent_location_id, l.greenhouse_classification, lt.code AS type_code, a.depth + 1
                FROM locations l
                JOIN location_types lt ON lt.id = l.location_type_id
                JOIN ancestry a ON l.id = a.parent_location_id
            )
            SELECT greenhouse_classification FROM ancestry WHERE type_code = 'greenhouse'
            ORDER BY depth ASC LIMIT 1
            """
        ),
        {"start_id": parent.id, "tenant_id": tenant_id, "farm_id": farm_id},
    ).scalar_one_or_none()


def _validate_hierarchy(
    db: Session,
    *,
    parent_type_id: uuid.UUID | None,
    child_type_id: uuid.UUID,
    governing_classification: str | None,
) -> None:
    """DOMAIN-FARM-001: when `governing_classification` is set (the
    candidate location is being created inside a classified greenhouse
    tree), ONLY classification-matching rules are consulted — never the
    generic (`greenhouse_classification IS NULL`) rule set, so a
    classification-specific topology restriction can never be bypassed by an
    otherwise-permitted generic parent/child pair. When `governing_
    classification` is `None` (farm-root creation, or a non-greenhouse tree
    such as store/cold_store/packing_hall/dispatch_area), ONLY the generic
    rule set is consulted — exactly the pre-existing, unchanged behavior."""
    if parent_type_id is None:
        parent_condition = LocationTypeHierarchyRule.parent_type_id.is_(None)
    else:
        parent_condition = LocationTypeHierarchyRule.parent_type_id == parent_type_id
    if governing_classification is None:
        classification_condition = LocationTypeHierarchyRule.greenhouse_classification.is_(None)
    else:
        classification_condition = LocationTypeHierarchyRule.greenhouse_classification == governing_classification
    exists = db.execute(
        select(LocationTypeHierarchyRule.id).where(
            parent_condition,
            classification_condition,
            LocationTypeHierarchyRule.child_type_id == child_type_id,
        )
    ).scalar_one_or_none()
    if exists is None:
        raise InvalidLocationHierarchyError(f"{parent_type_id}:{child_type_id}:{governing_classification}")


def _create_location_core(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    location_type_code: str,
    code: str,
    name: str,
    parent_location_id: uuid.UUID | None,
    greenhouse_classification: str | None,
    occupiable: bool | None,
    capacity: int | None = None,
) -> Location:
    """The validate+insert+flush core of `create_location`, with no commit
    and no audit event -- reused directly by FARM-SETUP-001's orchestration
    service so a multi-location setup command can create many locations in
    one transaction with one commit at the end, instead of each call
    committing (and thus becoming unrollback-able) independently. Public
    `create_location` below is a thin wrapper: same behavior as before this
    ticket, just with its core extracted."""
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    location_type = _get_location_type_by_code(db, location_type_code)

    parent_type_id: uuid.UUID | None = None
    parent: Location | None = None
    if parent_location_id is not None:
        parent = _get_active_location_in_scope(
            db, tenant_id=tenant_id, farm_id=farm_id, location_id=parent_location_id
        )
        parent_type_id = parent.location_type_id
    governing_classification = _resolve_governing_greenhouse_classification(
        db, tenant_id=tenant_id, farm_id=farm_id, parent=parent
    )
    _validate_hierarchy(
        db,
        parent_type_id=parent_type_id,
        child_type_id=location_type.id,
        governing_classification=governing_classification,
    )

    location = Location(
        tenant_id=tenant_id,
        farm_id=farm_id,
        parent_location_id=parent_location_id,
        location_type_id=location_type.id,
        code=code,
        name=name,
        greenhouse_classification=greenhouse_classification,
        occupiable=location_type.default_occupiable if occupiable is None else occupiable,
        capacity=capacity,
    )
    db.add(location)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) not in _CODE_UNIQUENESS_CONSTRAINTS:
            raise
        raise DuplicateLocationCodeError(f"{parent_location_id}:{code}") from exc
    return location


def create_location(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    location_type_code: str,
    code: str,
    name: str,
    parent_location_id: uuid.UUID | None,
    greenhouse_classification: str | None,
    occupiable: bool | None,
    capacity: int | None = None,
) -> Location:
    location = _create_location_core(
        db,
        tenant_id=tenant_id,
        farm_id=farm_id,
        location_type_code=location_type_code,
        code=code,
        name=name,
        parent_location_id=parent_location_id,
        greenhouse_classification=greenhouse_classification,
        occupiable=occupiable,
        capacity=capacity,
    )

    append_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="location.created",
        entity_type="location",
        entity_id=location.id,
        event_data={
            "code": location.code,
            "location_type_code": location_type_code,
            "parent_location_id": str(parent_location_id) if parent_location_id else None,
        },
    )
    db.commit()
    db.refresh(location)
    return location


def _bulk_generate_children_core(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    parent_id: uuid.UUID,
    location_type_code: str,
    code_prefix: str,
    start: int,
    end: int,
    pad_width: int,
    name_template: str | None,
    capacity: int | None = None,
    occupiable: bool | None = None,
) -> list[Location]:
    """The validate+insert+flush core of `bulk_generate_children`, with no
    commit and no audit event -- see `_create_location_core`'s docstring
    for why FARM-SETUP-001 needs this split.

    `occupiable=None` (the pre-existing, unchanged default for every
    caller before FARM-SETUP-001) uses the location type's own default,
    exactly as before. FARM-SETUP-001 needs an explicit per-instance
    override here for the same reason `create_location` already has one:
    `grow_table.default_occupiable` is `False` (grow_table is a purely
    structural node until a real instance is deliberately made the
    occupiable Leafy leaf -- DOMAIN-FARM-001's own documented design),
    so Farm Setup must be able to pass `occupiable=True` when it
    bulk-generates real Leafy Tables."""
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    parent = _get_active_location_in_scope(
        db, tenant_id=tenant_id, farm_id=farm_id, location_id=parent_id
    )
    location_type = _get_location_type_by_code(db, location_type_code)
    governing_classification = _resolve_governing_greenhouse_classification(
        db, tenant_id=tenant_id, farm_id=farm_id, parent=parent
    )
    _validate_hierarchy(
        db,
        parent_type_id=parent.location_type_id,
        child_type_id=location_type.id,
        governing_classification=governing_classification,
    )

    numbers = range(start, end + 1)
    codes = [f"{code_prefix}{str(n).zfill(pad_width)}" for n in numbers]

    existing = db.execute(
        select(Location.code).where(
            Location.parent_location_id == parent_id,
            func.lower(Location.code).in_([c.lower() for c in codes]),
        )
    ).scalars().all()
    if existing:
        raise DuplicateLocationCodeError(f"{parent_id}:{','.join(existing)}")

    created: list[Location] = []
    for n, code in zip(numbers, codes):
        name = name_template.format(n=n) if name_template else f"{location_type.name} {code}"
        location = Location(
            tenant_id=tenant_id,
            farm_id=farm_id,
            parent_location_id=parent_id,
            location_type_id=location_type.id,
            code=code,
            name=name,
            occupiable=location_type.default_occupiable if occupiable is None else occupiable,
            capacity=capacity,
        )
        db.add(location)
        created.append(location)

    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) not in _CODE_UNIQUENESS_CONSTRAINTS:
            raise
        raise DuplicateLocationCodeError(f"{parent_id}:{code_prefix}") from exc
    return created


def bulk_generate_children(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    parent_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    location_type_code: str,
    code_prefix: str,
    start: int,
    end: int,
    pad_width: int,
    name_template: str | None,
    capacity: int | None = None,
) -> list[Location]:
    created = _bulk_generate_children_core(
        db,
        tenant_id=tenant_id,
        farm_id=farm_id,
        parent_id=parent_id,
        location_type_code=location_type_code,
        code_prefix=code_prefix,
        start=start,
        end=end,
        pad_width=pad_width,
        name_template=name_template,
        capacity=capacity,
    )

    append_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="location.bulk_generated",
        entity_type="location",
        entity_id=parent_id,
        event_data={
            "parent_id": str(parent_id),
            "location_type_code": location_type_code,
            "code_prefix": code_prefix,
            "start": start,
            "end": end,
            "pad_width": pad_width,
            "count": len(created),
        },
    )
    db.commit()
    for location in created:
        db.refresh(location)
    return created


def get_location(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, location_id: uuid.UUID) -> Location:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    location = db.execute(
        select(Location).where(
            Location.id == location_id, Location.tenant_id == tenant_id, Location.farm_id == farm_id
        )
    ).scalar_one_or_none()
    if location is None:
        raise LocationNotFoundError(str(location_id))
    return location


def list_children(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, location_id: uuid.UUID
) -> list[Location]:
    get_location(db, tenant_id=tenant_id, farm_id=farm_id, location_id=location_id)
    return list(
        db.execute(
            select(Location)
            .where(
                Location.parent_location_id == location_id,
                Location.tenant_id == tenant_id,
                Location.farm_id == farm_id,
            )
            .order_by(func.lower(Location.code))
        ).scalars()
    )


def get_farm_tree(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> list[Location]:
    """One tenant-and-farm-scoped query; nested assembly happens in the router."""
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    return list(
        db.execute(
            select(Location)
            .where(Location.tenant_id == tenant_id, Location.farm_id == farm_id)
            .order_by(func.lower(Location.code))
        ).scalars()
    )


def get_path(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, location_id: uuid.UUID
) -> list[dict]:
    get_location(db, tenant_id=tenant_id, farm_id=farm_id, location_id=location_id)
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


def _lock_location(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, location_id: uuid.UUID
) -> Location:
    location = db.execute(
        select(Location)
        .where(Location.id == location_id, Location.tenant_id == tenant_id, Location.farm_id == farm_id)
        .with_for_update()
    ).scalar_one_or_none()
    if location is None:
        raise LocationNotFoundError(str(location_id))
    return location


def _compute_location_update_fingerprint(
    *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID | None, location_id: uuid.UUID, name: str
) -> str:
    parts = [str(tenant_id), str(actor_user_id) if actor_user_id else "", str(location_id), name]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _compute_location_status_fingerprint(
    *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID | None, location_id: uuid.UUID
) -> str:
    parts = [str(tenant_id), str(actor_user_id) if actor_user_id else "", str(location_id)]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def update_location(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    client_command_id: uuid.UUID,
    location_id: uuid.UUID,
    name: str,
) -> Location:
    """UX-IA-001: renames a Location -- the only mutable field. Mirrors
    `inventory_item_service.update_inventory_item`'s idempotency shape
    exactly (pre-lock replay check, row lock, post-lock replay check,
    IntegrityError-fallback replay). `code`/`parent_location_id`/
    `location_type_id`/`farm_id` have no update path at all -- see
    `docs/domain/LOCATION_MODEL.md`, "Location maintenance lifecycle".
    Works whether the Location is currently active or inactive -- name
    correction is not a lifecycle action."""
    fingerprint = _compute_location_update_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, location_id=location_id, name=name
    )

    def _find_by_update_command() -> Location | None:
        return db.execute(
            select(Location).where(
                Location.tenant_id == tenant_id, Location.update_client_command_id == client_command_id
            )
        ).scalar_one_or_none()

    existing = _find_by_update_command()
    if existing is not None:
        if existing.update_request_fingerprint == fingerprint:
            return existing
        raise LocationUpdateReusedWithDifferentPayloadError(str(client_command_id))

    location = _lock_location(db, tenant_id=tenant_id, farm_id=farm_id, location_id=location_id)

    existing = _find_by_update_command()
    if existing is not None:
        if existing.update_request_fingerprint == fingerprint:
            return existing
        raise LocationUpdateReusedWithDifferentPayloadError(str(client_command_id))

    name_before = location.name
    location.name = name
    location.update_client_command_id = client_command_id
    location.update_request_fingerprint = fingerprint
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_locations_tenant_update_command":
            replay = _find_by_update_command()
            if replay is not None and replay.update_request_fingerprint == fingerprint:
                return replay
            raise LocationUpdateReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="location.updated",
        entity_type="location", entity_id=location.id,
        event_data={"code": location.code, "name_before": name_before, "name_after": location.name},
    )
    db.commit()
    db.refresh(location)
    return location


def deactivate_location(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    client_command_id: uuid.UUID,
    location_id: uuid.UUID,
) -> Location:
    """UX-IA-001: explicit, non-cascading deactivation
    (docs/domain/LOCATION_MODEL.md, "Location maintenance lifecycle").
    Blocked by active occupancy at this exact Location or by any directly
    active child Location; closed/historical occupancy and movement never
    block. Deactivating a parent never cascades to its descendants -- the
    operator retires a hierarchy bottom-up, one explicit command per node.
    Both invariant checks run AFTER the row lock is acquired, so a
    concurrent `execute_movement` into this same Location (which also locks
    the destination Location row, see `movement_service._resolve_target`)
    is correctly serialized rather than racing a stale pre-lock read."""
    fingerprint = _compute_location_status_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, location_id=location_id
    )

    def _find_by_command() -> Location | None:
        return db.execute(
            select(Location).where(
                Location.tenant_id == tenant_id, Location.deactivation_client_command_id == client_command_id
            )
        ).scalar_one_or_none()

    existing = _find_by_command()
    if existing is not None:
        if existing.deactivation_request_fingerprint == fingerprint:
            return existing
        raise LocationDeactivationReusedWithDifferentPayloadError(str(client_command_id))

    location = _lock_location(db, tenant_id=tenant_id, farm_id=farm_id, location_id=location_id)

    existing = _find_by_command()
    if existing is not None:
        if existing.deactivation_request_fingerprint == fingerprint:
            return existing
        raise LocationDeactivationReusedWithDifferentPayloadError(str(client_command_id))

    if location.status != "active":
        raise LocationNotActiveError(str(location_id))

    # A non-occupiable Location can never have any Occupancy at all --
    # occupancy creation itself requires occupiable=True at movement time
    # (movement_service._resolve_target), and occupiable is immutable after
    # creation (no update path touches it). list_target_occupants() itself
    # raises TargetNotOccupiableError for a non-occupiable target (it is
    # built for the "read this occupiable target's occupants" case, e.g.
    # the /occupants endpoint) -- calling it here for every Location type,
    # including plain structural ones like store_area/store_rack, would be
    # a misuse of that guard, not a real invariant violation.
    if location.occupiable:
        active_occupancies = movement_service.list_target_occupants(
            db, tenant_id=tenant_id, farm_id=farm_id, target_kind="location", target_id=location_id
        )
        if active_occupancies:
            raise LocationHasActiveOccupancyError(str(location_id))

    active_child_count = db.execute(
        select(func.count()).select_from(Location).where(
            Location.parent_location_id == location_id,
            Location.tenant_id == tenant_id,
            Location.farm_id == farm_id,
            Location.status == "active",
        )
    ).scalar_one()
    if active_child_count > 0:
        raise LocationHasActiveChildrenError(str(location_id))

    location.status = "inactive"
    location.deactivation_client_command_id = client_command_id
    location.deactivation_request_fingerprint = fingerprint
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_locations_tenant_deactivation_command":
            replay = _find_by_command()
            if replay is not None and replay.deactivation_request_fingerprint == fingerprint:
                return replay
            raise LocationDeactivationReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="location.deactivated",
        entity_type="location", entity_id=location.id,
        event_data={"code": location.code, "status_before": "active", "status_after": "inactive"},
    )
    db.commit()
    db.refresh(location)
    return location


def reactivate_location(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    client_command_id: uuid.UUID,
    location_id: uuid.UUID,
) -> Location:
    """UX-IA-001: reactivation requires the Location itself to be inactive
    and, if it has a parent, that parent to be currently active -- mirrors
    the same invariant `create_location` already enforces at creation time
    via `_get_active_location_in_scope`. No occupancy/child check applies
    to reactivation -- it only ever adds future eligibility."""
    fingerprint = _compute_location_status_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, location_id=location_id
    )

    def _find_by_command() -> Location | None:
        return db.execute(
            select(Location).where(
                Location.tenant_id == tenant_id, Location.reactivation_client_command_id == client_command_id
            )
        ).scalar_one_or_none()

    existing = _find_by_command()
    if existing is not None:
        if existing.reactivation_request_fingerprint == fingerprint:
            return existing
        raise LocationReactivationReusedWithDifferentPayloadError(str(client_command_id))

    location = _lock_location(db, tenant_id=tenant_id, farm_id=farm_id, location_id=location_id)

    existing = _find_by_command()
    if existing is not None:
        if existing.reactivation_request_fingerprint == fingerprint:
            return existing
        raise LocationReactivationReusedWithDifferentPayloadError(str(client_command_id))

    if location.status != "inactive":
        raise LocationNotInactiveError(str(location_id))

    if location.parent_location_id is not None:
        # UX-IA-001: row-locks the parent FOR UPDATE, same reasoning as
        # `_get_active_location_in_scope` -- without this lock, a
        # concurrent `deactivate_location(parent)` could commit between
        # this check and this command's own status flip below, again
        # producing an inactive parent with an active (reactivated) child.
        # Deadlock-safe: this transaction already holds a lock on `location`
        # itself (`_lock_location` above) before requesting the parent's
        # lock, but `deactivate_location` never locks a child row -- its own
        # active-child check is a plain, unlocked read -- so the two
        # commands can only ever contend on the parent row, never form a
        # lock cycle.
        parent = db.execute(
            select(Location)
            .where(
                Location.id == location.parent_location_id,
                Location.tenant_id == tenant_id,
                Location.farm_id == farm_id,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if parent is None or parent.status != "active":
            raise LocationParentNotActiveError(str(location_id))

    location.status = "active"
    location.reactivation_client_command_id = client_command_id
    location.reactivation_request_fingerprint = fingerprint
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_locations_tenant_reactivation_command":
            replay = _find_by_command()
            if replay is not None and replay.reactivation_request_fingerprint == fingerprint:
                return replay
            raise LocationReactivationReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="location.reactivated",
        entity_type="location", entity_id=location.id,
        event_data={"code": location.code, "status_before": "inactive", "status_after": "active"},
    )
    db.commit()
    db.refresh(location)
    return location
