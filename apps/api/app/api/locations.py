import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.db import get_db, get_engine
from app.core.auth import TenantContext
from app.core.permissions import Permission, require_permission
from app.schemas.location import (
    LocationBulkChildrenCreate,
    LocationCreate,
    LocationDeactivate,
    LocationPathEntry,
    LocationPathRead,
    LocationReactivate,
    LocationRead,
    LocationTreeNode,
    LocationUpdate,
)
from app.schemas.movement import TargetRef
from app.schemas.occupancy import OccupancyRead, TargetOccupantRead, TargetOccupantsRead
from app.schemas.operational_read import SubtreeOccupancyRead
from app.services import location_service, movement_service, operational_read_service
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
from app.services.lineage_traversal import _snapshot_connection

router = APIRouter(tags=["locations"])

# UX-IA-001: a stable, machine-readable identifier for the 3 blocked-action
# 409 subtypes the frontend must branch on to show a friendly, specific
# message rather than raw exception text -- mirrors leafy_harvest.py's own
# `_conflict_detail`/`_CONFLICT_CODES` precedent exactly (SLICE 2
# CORRECTION 1). Every other conflict on these routes (idempotency
# replay-mismatch, plain not-active/not-inactive) keeps its existing plain
# string `detail` -- the shared frontend envelope
# (`lib/errors/adapter.ts`/`lib/api/client.ts`) already parses both shapes.
_CONFLICT_CODES: dict[type[Exception], str] = {
    LocationHasActiveOccupancyError: "LOCATION_HAS_ACTIVE_OCCUPANCY",
    LocationHasActiveChildrenError: "LOCATION_HAS_ACTIVE_CHILDREN",
    LocationParentNotActiveError: "LOCATION_PARENT_NOT_ACTIVE",
}


def _conflict_detail(exc: Exception, message: str) -> dict[str, str] | str:
    code = _CONFLICT_CODES.get(type(exc))
    if code is None:
        return message
    return {"message": message, "code": code}


@router.post(
    "/farms/{farm_id}/locations", response_model=LocationRead, status_code=status.HTTP_201_CREATED
)
def create_location(
    farm_id: uuid.UUID,
    payload: LocationCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.LOCATION_MANAGE)),
) -> LocationRead:
    try:
        location = location_service.create_location(
            db,
            tenant_id=ctx.tenant_id,
            farm_id=farm_id,
            actor_user_id=ctx.user_id,
            location_type_code=payload.location_type_code,
            code=payload.code,
            name=payload.name,
            parent_location_id=payload.parent_location_id,
            greenhouse_classification=payload.greenhouse_classification,
            occupiable=payload.occupiable,
            capacity=payload.capacity,
        )
    except (FarmNotFoundError, LocationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except LocationTypeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown location type") from exc
    except InactiveParentLocationError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Parent location is inactive"
        ) from exc
    except InvalidLocationHierarchyError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This location type is not permitted under this parent",
        ) from exc
    except DuplicateLocationCodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Location code already exists under this parent"
        ) from exc
    return LocationRead.model_validate(location)


@router.post(
    "/farms/{farm_id}/locations/{parent_id}/bulk-children",
    response_model=list[LocationRead],
    status_code=status.HTTP_201_CREATED,
)
def bulk_create_children(
    farm_id: uuid.UUID,
    parent_id: uuid.UUID,
    payload: LocationBulkChildrenCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.LOCATION_MANAGE)),
) -> list[LocationRead]:
    try:
        created = location_service.bulk_generate_children(
            db,
            tenant_id=ctx.tenant_id,
            farm_id=farm_id,
            parent_id=parent_id,
            actor_user_id=ctx.user_id,
            location_type_code=payload.location_type_code,
            code_prefix=payload.code_prefix,
            start=payload.start,
            end=payload.end,
            pad_width=payload.pad_width,
            name_template=payload.name_template,
            capacity=payload.capacity,
        )
    except (FarmNotFoundError, LocationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except LocationTypeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown location type") from exc
    except InactiveParentLocationError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Parent location is inactive"
        ) from exc
    except InvalidLocationHierarchyError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This location type is not permitted under this parent",
        ) from exc
    except DuplicateLocationCodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="One or more generated codes already exist"
        ) from exc
    return [LocationRead.model_validate(location) for location in created]


@router.get("/farms/{farm_id}/locations/tree", response_model=list[LocationTreeNode])
def get_farm_tree(
    farm_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.LOCATION_READ)),
) -> list[LocationTreeNode]:
    try:
        flat = location_service.get_farm_tree(db, tenant_id=ctx.tenant_id, farm_id=farm_id)
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found") from exc

    # STORE-INV-001B: one small, global-table lookup (location_types has
    # ~26 rows total) -- not a new endpoint, just resolves the ids already
    # on each Location to their code for this one response shape.
    type_codes = location_service.get_location_type_code_map(db)

    nodes: dict[uuid.UUID, LocationTreeNode] = {
        loc.id: LocationTreeNode(
            id=loc.id,
            code=loc.code,
            name=loc.name,
            location_type_id=loc.location_type_id,
            location_type_code=type_codes[loc.location_type_id],
            status=loc.status,
            occupiable=loc.occupiable,
            capacity=loc.capacity,
            children=[],
        )
        for loc in flat
    }
    roots: list[LocationTreeNode] = []
    for loc in flat:
        node = nodes[loc.id]
        if loc.parent_location_id is None:
            roots.append(node)
        else:
            parent = nodes.get(loc.parent_location_id)
            if parent is not None:
                parent.children.append(node)
    return roots


@router.get("/farms/{farm_id}/locations/{location_id}", response_model=LocationRead)
def get_location(
    farm_id: uuid.UUID,
    location_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.LOCATION_READ)),
) -> LocationRead:
    try:
        location = location_service.get_location(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, location_id=location_id
        )
    except (FarmNotFoundError, LocationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return LocationRead.model_validate(location)


@router.get("/farms/{farm_id}/locations/{location_id}/children", response_model=list[LocationRead])
def list_children(
    farm_id: uuid.UUID,
    location_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.LOCATION_READ)),
) -> list[LocationRead]:
    try:
        children = location_service.list_children(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, location_id=location_id
        )
    except (FarmNotFoundError, LocationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return [LocationRead.model_validate(child) for child in children]


@router.get("/farms/{farm_id}/locations/{location_id}/path", response_model=LocationPathRead)
def get_path(
    farm_id: uuid.UUID,
    location_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.LOCATION_READ)),
) -> LocationPathRead:
    try:
        rows = location_service.get_path(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, location_id=location_id
        )
    except (FarmNotFoundError, LocationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    entries = [LocationPathEntry(id=row["id"], code=row["code"], name=row["name"]) for row in rows]
    return LocationPathRead(
        location_id=location_id, path=entries, path_string=" / ".join(e.code for e in entries)
    )


@router.get("/farms/{farm_id}/locations/{location_id}/occupant", response_model=TargetOccupantRead)
def get_location_occupant(
    farm_id: uuid.UUID,
    location_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.LOCATION_READ)),
) -> TargetOccupantRead:
    try:
        occupancies = movement_service.list_target_occupants(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, target_kind="location", target_id=location_id
        )
    except (FarmNotFoundError, LocationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return TargetOccupantRead(
        target=TargetRef(kind="location", id=location_id),
        active_occupancy=OccupancyRead.from_model(occupancies[0]) if occupancies else None,
        active_occupancy_count=len(occupancies),
    )


@router.get("/farms/{farm_id}/locations/{location_id}/occupants", response_model=TargetOccupantsRead)
def get_location_occupants(
    farm_id: uuid.UUID,
    location_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.LOCATION_READ)),
) -> TargetOccupantsRead:
    """DOMAIN-FARM-002.1: the truthful, complete-state counterpart to
    `get_location_occupant` -- returns every active occupancy, not just
    one, so a capacity>1 target is never under-reported."""
    try:
        occupancies = movement_service.list_target_occupants(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, target_kind="location", target_id=location_id
        )
    except (FarmNotFoundError, LocationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return TargetOccupantsRead(
        target=TargetRef(kind="location", id=location_id),
        active_occupancies=[OccupancyRead.from_model(o) for o in occupancies],
    )


@router.get(
    "/farms/{farm_id}/locations/{location_id}/subtree-occupancy", response_model=SubtreeOccupancyRead
)
def get_location_subtree_occupancy(
    farm_id: uuid.UUID,
    location_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission(Permission.LOCATION_READ)),
    db_engine: Engine = Depends(get_engine),
) -> SubtreeOccupancyRead:
    """CMP-FE-002A: bounded-by-root occupancy for one location subtree
    (the given root plus all its descendants, never farm-wide). Returns
    aggregate occupiable/occupied counts per structural node plus only the
    currently occupied locations -- never resends the structural tree
    itself (already available from `.../locations/tree`), and never one
    row per empty location."""
    try:
        with _snapshot_connection(db_engine) as conn:
            return operational_read_service.get_location_subtree_occupancy(
                conn, tenant_id=ctx.tenant_id, farm_id=farm_id, root_location_id=location_id
            )
    except (FarmNotFoundError, LocationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.post("/farms/{farm_id}/locations/{location_id}/update", response_model=LocationRead)
def update_location(
    farm_id: uuid.UUID,
    location_id: uuid.UUID,
    payload: LocationUpdate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.LOCATION_MANAGE)),
) -> LocationRead:
    try:
        location = location_service.update_location(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id,
            client_command_id=payload.client_command_id, location_id=location_id, name=payload.name,
        )
    except LocationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except LocationUpdateReusedWithDifferentPayloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="client_command_id already used with a different payload",
        ) from exc
    return LocationRead.model_validate(location)


@router.post("/farms/{farm_id}/locations/{location_id}/deactivate", response_model=LocationRead)
def deactivate_location(
    farm_id: uuid.UUID,
    location_id: uuid.UUID,
    payload: LocationDeactivate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.LOCATION_MANAGE)),
) -> LocationRead:
    try:
        location = location_service.deactivate_location(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id,
            client_command_id=payload.client_command_id, location_id=location_id,
        )
    except LocationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except LocationDeactivationReusedWithDifferentPayloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="client_command_id already used with a different payload",
        ) from exc
    except LocationNotActiveError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Location is not active") from exc
    except LocationHasActiveOccupancyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_conflict_detail(exc, "Location has active occupancy"),
        ) from exc
    except LocationHasActiveChildrenError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_conflict_detail(exc, "Location has active child locations"),
        ) from exc
    return LocationRead.model_validate(location)


@router.post("/farms/{farm_id}/locations/{location_id}/reactivate", response_model=LocationRead)
def reactivate_location(
    farm_id: uuid.UUID,
    location_id: uuid.UUID,
    payload: LocationReactivate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.LOCATION_MANAGE)),
) -> LocationRead:
    try:
        location = location_service.reactivate_location(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id,
            client_command_id=payload.client_command_id, location_id=location_id,
        )
    except LocationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except LocationReactivationReusedWithDifferentPayloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="client_command_id already used with a different payload",
        ) from exc
    except LocationNotInactiveError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Location is not inactive") from exc
    except LocationParentNotActiveError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_conflict_detail(exc, "Parent location is not active"),
        ) from exc
    return LocationRead.model_validate(location)
