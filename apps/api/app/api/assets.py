import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.auth import TenantContext, require_tenant_context
from app.schemas.asset import AssetCreate, AssetRead
from app.schemas.asset_position import AssetPositionRead, AssetPositionsGenerate, AssetPositionTreeNode
from app.schemas.movement import MovementRead, TargetRef
from app.schemas.occupancy import OccupancyRead, ResolvedLocationRead, TargetOccupantRead
from app.services import asset_service, movement_service
from app.services.errors import (
    AssetNotFoundError,
    AssetPositionNotFoundError,
    AssetTypeNotFoundError,
    DuplicateAssetCodeError,
    DuplicatePositionCodeError,
    FarmNotFoundError,
    PositionsNotSupportedError,
)

router = APIRouter(tags=["assets"])


@router.post("/farms/{farm_id}/assets", response_model=AssetRead, status_code=status.HTTP_201_CREATED)
def register_asset(
    farm_id: uuid.UUID,
    payload: AssetCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_tenant_context),
) -> AssetRead:
    try:
        asset = asset_service.register_asset(
            db,
            tenant_id=ctx.tenant_id,
            farm_id=farm_id,
            actor_user_id=ctx.user_id,
            asset_type_code=payload.asset_type_code,
            code=payload.code,
            name=payload.name,
            commissioned_date=payload.commissioned_date,
        )
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found") from exc
    except AssetTypeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown asset type") from exc
    except DuplicateAssetCodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Asset code already exists in this tenant"
        ) from exc
    return AssetRead.model_validate(asset)


@router.get("/farms/{farm_id}/assets/{asset_id}", response_model=AssetRead)
def get_asset(
    farm_id: uuid.UUID,
    asset_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_tenant_context),
) -> AssetRead:
    try:
        asset = asset_service.get_asset(db, tenant_id=ctx.tenant_id, farm_id=farm_id, asset_id=asset_id)
    except (FarmNotFoundError, AssetNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return AssetRead.model_validate(asset)


@router.get("/farms/{farm_id}/assets", response_model=list[AssetRead])
def list_assets(
    farm_id: uuid.UUID,
    asset_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_tenant_context),
) -> list[AssetRead]:
    try:
        assets = asset_service.list_assets(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, asset_type_code=asset_type
        )
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found") from exc
    except AssetTypeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown asset type") from exc
    return [AssetRead.model_validate(asset) for asset in assets]


@router.post(
    "/farms/{farm_id}/assets/{asset_id}/positions/generate",
    response_model=list[AssetPositionRead],
    status_code=status.HTTP_201_CREATED,
)
def generate_positions(
    farm_id: uuid.UUID,
    asset_id: uuid.UUID,
    payload: AssetPositionsGenerate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_tenant_context),
) -> list[AssetPositionRead]:
    try:
        created = asset_service.generate_positions(
            db,
            tenant_id=ctx.tenant_id,
            farm_id=farm_id,
            actor_user_id=ctx.user_id,
            asset_id=asset_id,
            shelf_count=payload.shelf_count,
            slots_per_shelf=payload.slots_per_shelf,
            shelf_prefix=payload.shelf_prefix,
            slot_prefix=payload.slot_prefix,
            shelf_pad_width=payload.shelf_pad_width,
            slot_pad_width=payload.slot_pad_width,
        )
    except (FarmNotFoundError, AssetNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except PositionsNotSupportedError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This asset type does not support relative positions",
        ) from exc
    except DuplicatePositionCodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="One or more generated position codes already exist"
        ) from exc
    return [AssetPositionRead.model_validate(p) for p in created]


@router.get(
    "/farms/{farm_id}/assets/{asset_id}/positions/tree", response_model=list[AssetPositionTreeNode]
)
def get_positions_tree(
    farm_id: uuid.UUID,
    asset_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_tenant_context),
) -> list[AssetPositionTreeNode]:
    try:
        flat = asset_service.get_positions_tree(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, asset_id=asset_id
        )
    except (FarmNotFoundError, AssetNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc

    nodes: dict[uuid.UUID, AssetPositionTreeNode] = {
        p.id: AssetPositionTreeNode(id=p.id, position_kind=p.position_kind, code=p.code, name=p.name, children=[])
        for p in flat
    }
    roots: list[AssetPositionTreeNode] = []
    for p in flat:
        node = nodes[p.id]
        if p.parent_position_id is None:
            roots.append(node)
        else:
            parent = nodes.get(p.parent_position_id)
            if parent is not None:
                parent.children.append(node)
    return roots


@router.get("/farms/{farm_id}/assets/{asset_id}/occupancy", response_model=OccupancyRead | None)
def get_asset_occupancy(
    farm_id: uuid.UUID,
    asset_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_tenant_context),
) -> OccupancyRead | None:
    try:
        occupancy = movement_service.get_occupancy(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, occupant_kind="asset", occupant_id=asset_id
        )
    except (FarmNotFoundError, AssetNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return OccupancyRead.from_model(occupancy) if occupancy is not None else None


@router.get("/farms/{farm_id}/assets/{asset_id}/movement-history", response_model=list[MovementRead])
def get_asset_movement_history(
    farm_id: uuid.UUID,
    asset_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_tenant_context),
) -> list[MovementRead]:
    try:
        movements = movement_service.get_movement_history(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, occupant_kind="asset", occupant_id=asset_id
        )
    except (FarmNotFoundError, AssetNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return [MovementRead.from_model(m) for m in movements]


@router.get("/farms/{farm_id}/assets/{asset_id}/resolved-location", response_model=ResolvedLocationRead)
def get_asset_resolved_location(
    farm_id: uuid.UUID,
    asset_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_tenant_context),
) -> ResolvedLocationRead:
    try:
        resolved = movement_service.get_resolved_location(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, occupant_kind="asset", occupant_id=asset_id
        )
    except (FarmNotFoundError, AssetNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return ResolvedLocationRead(**resolved)


@router.get(
    "/farms/{farm_id}/assets/{asset_id}/positions/{position_id}/occupant", response_model=TargetOccupantRead
)
def get_position_occupant(
    farm_id: uuid.UUID,
    asset_id: uuid.UUID,
    position_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_tenant_context),
) -> TargetOccupantRead:
    try:
        occupancy = movement_service.get_target_occupant(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, target_kind="asset_position", target_id=position_id
        )
    except (FarmNotFoundError, AssetPositionNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return TargetOccupantRead(
        target=TargetRef(kind="asset_position", id=position_id),
        active_occupancy=OccupancyRead.from_model(occupancy) if occupancy is not None else None,
    )
