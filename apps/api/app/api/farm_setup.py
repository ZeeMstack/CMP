import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.db import get_db, get_engine
from app.core.auth import TenantContext
from app.core.permissions import Permission, require_permission
from app.schemas.farm_setup import (
    GreenhouseOverviewItem,
    GreenhouseSetupCreate,
    GreenhouseSetupResult,
    GreenhouseStructureRead,
)
from app.services import farm_setup_service
from app.services.errors import (
    DuplicateAssetCodeError,
    DuplicateLocationCodeError,
    DuplicatePositionCodeError,
    FarmNotFoundError,
    FarmSetupCommandReusedWithDifferentPayloadError,
    InactiveParentLocationError,
    InvalidLocationHierarchyError,
    LocationNotFoundError,
    LocationTypeNotFoundError,
    PositionsNotSupportedError,
)
from app.services.lineage_traversal import _snapshot_connection

router = APIRouter(tags=["farm-setup"])


@router.post(
    "/farms/{farm_id}/farm-setup/greenhouses",
    response_model=GreenhouseSetupResult,
    status_code=status.HTTP_201_CREATED,
)
def create_greenhouse_setup(
    farm_id: uuid.UUID,
    payload: GreenhouseSetupCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.LOCATION_MANAGE)),
    _asset_ctx: TenantContext = Depends(require_permission(Permission.ASSET_MANAGE)),
) -> GreenhouseSetupResult:
    """FARM-SETUP-001: creates a Greenhouse plus its full requested
    classification-specific physical structure in one atomic command.

    FARM-SETUP-001.1: gated on BOTH `location.manage` AND `asset.manage`,
    stacked as two separate dependencies -- this command can register
    Nursery Assets (trolleys, seeding machines), so it must not rely on
    the incidental fact that every role currently holding `location.manage`
    also holds `asset.manage`. A hypothetical membership with only one of
    the two permissions must not be able to create Assets through this
    command."""
    try:
        result = farm_setup_service.create_greenhouse_setup(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, payload=payload,
        )
    except (FarmNotFoundError, LocationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except LocationTypeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown location type") from exc
    except InactiveParentLocationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Parent location is inactive") from exc
    except InvalidLocationHierarchyError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This structure is not valid for this greenhouse classification.",
        ) from exc
    except DuplicateLocationCodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A location with this code already exists under this parent.",
        ) from exc
    except (DuplicateAssetCodeError, DuplicatePositionCodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="An asset with this code already exists.",
        ) from exc
    except PositionsNotSupportedError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="This asset type does not support positions.",
        ) from exc
    except FarmSetupCommandReusedWithDifferentPayloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This setup command id was already used with different setup content.",
        ) from exc
    return result


@router.get(
    "/farms/{farm_id}/farm-setup/greenhouses", response_model=list[GreenhouseOverviewItem]
)
def get_greenhouse_setup_overview(
    farm_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission(Permission.LOCATION_READ)),
    db_engine: Engine = Depends(get_engine),
) -> list[GreenhouseOverviewItem]:
    try:
        with _snapshot_connection(db_engine) as conn:
            return farm_setup_service.get_greenhouse_setup_overview(conn, tenant_id=ctx.tenant_id, farm_id=farm_id)
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get(
    "/farms/{farm_id}/farm-setup/greenhouses/{greenhouse_id}", response_model=GreenhouseStructureRead
)
def get_greenhouse_structure(
    farm_id: uuid.UUID,
    greenhouse_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission(Permission.LOCATION_READ)),
    db_engine: Engine = Depends(get_engine),
) -> GreenhouseStructureRead:
    try:
        with _snapshot_connection(db_engine) as conn:
            return farm_setup_service.get_greenhouse_structure(
                conn, tenant_id=ctx.tenant_id, farm_id=farm_id, greenhouse_id=greenhouse_id
            )
    except (FarmNotFoundError, LocationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
