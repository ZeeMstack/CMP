import uuid

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.location import Location
from app.models.location_type import LocationType
from app.models.location_type_hierarchy_rule import LocationTypeHierarchyRule
from app.services import farm_service
from app.services.audit import append_audit_event
from app.services.errors import (
    DuplicateLocationCodeError,
    FarmNotFoundError,
    InactiveParentLocationError,
    InvalidLocationHierarchyError,
    LocationNotFoundError,
    LocationTypeNotFoundError,
)


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


def _get_active_location_in_scope(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, location_id: uuid.UUID
) -> Location:
    location = db.execute(
        select(Location).where(
            Location.id == location_id,
            Location.tenant_id == tenant_id,
            Location.farm_id == farm_id,
        )
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
) -> Location:
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
    )
    db.add(location)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateLocationCodeError(f"{parent_location_id}:{code}") from exc

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
) -> list[Location]:
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
            occupiable=location_type.default_occupiable,
        )
        db.add(location)
        created.append(location)

    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateLocationCodeError(f"{parent_id}:{code_prefix}") from exc

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
