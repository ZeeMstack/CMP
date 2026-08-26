import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.auth import TenantContext
from app.core.db import get_db
from app.core.permissions import Permission, require_permission
from app.schemas.packaging_unit import PackagingUnitCreate, PackagingUnitRead, PackagingUnitRetire
from app.services import packaging_unit_service
from app.services.errors import (
    DuplicatePackagingUnitCodeError,
    PackagingUnitCommandReusedWithDifferentPayloadError,
    PackagingUnitNotActiveError,
    PackagingUnitNotFoundError,
    PackagingUnitRetirementReusedWithDifferentPayloadError,
)

router = APIRouter(tags=["packaging-units"])


@router.post("/packaging-units", response_model=PackagingUnitRead, status_code=status.HTTP_201_CREATED)
def create_packaging_unit(
    payload: PackagingUnitCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PACKING_MANAGE)),
) -> PackagingUnitRead:
    try:
        unit = packaging_unit_service.register_packaging_unit(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, client_command_id=payload.client_command_id,
            code=payload.code, name=payload.name,
        )
    except DuplicatePackagingUnitCodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Packaging unit code already exists in this tenant"
        ) from exc
    except PackagingUnitCommandReusedWithDifferentPayloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="client_command_id already used with a different payload",
        ) from exc
    return PackagingUnitRead.model_validate(unit)


@router.get("/packaging-units", response_model=list[PackagingUnitRead])
def list_packaging_units(
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PACKING_READ)),
) -> list[PackagingUnitRead]:
    units = packaging_unit_service.list_packaging_units(db, tenant_id=ctx.tenant_id, status=status_filter)
    return [PackagingUnitRead.model_validate(u) for u in units]


@router.get("/packaging-units/{packaging_unit_id}", response_model=PackagingUnitRead)
def get_packaging_unit(
    packaging_unit_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PACKING_READ)),
) -> PackagingUnitRead:
    try:
        unit = packaging_unit_service.get_packaging_unit(
            db, tenant_id=ctx.tenant_id, packaging_unit_id=packaging_unit_id
        )
    except PackagingUnitNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Packaging unit not found") from exc
    return PackagingUnitRead.model_validate(unit)


@router.post("/packaging-units/{packaging_unit_id}/retire", response_model=PackagingUnitRead)
def retire_packaging_unit(
    packaging_unit_id: uuid.UUID,
    payload: PackagingUnitRetire,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PACKING_MANAGE)),
) -> PackagingUnitRead:
    try:
        unit = packaging_unit_service.retire_packaging_unit(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, client_command_id=payload.client_command_id,
            packaging_unit_id=packaging_unit_id,
        )
    except PackagingUnitNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Packaging unit not found") from exc
    except (PackagingUnitNotActiveError, PackagingUnitRetirementReusedWithDifferentPayloadError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return PackagingUnitRead.model_validate(unit)
