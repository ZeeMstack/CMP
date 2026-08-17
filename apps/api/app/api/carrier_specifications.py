import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.auth import TenantContext
from app.core.permissions import Permission, require_permission
from app.schemas.carrier_specification import (
    CarrierSpecificationCreate,
    CarrierSpecificationRead,
    CarrierSpecificationUpdate,
)
from app.services import carrier_specification_service
from app.services.errors import (
    CarrierSpecificationNotFoundError,
    CarrierSpecificationStructurallyLockedError,
    CarrierSpecificationValidationError,
    CarrierTypeNotFoundError,
    DuplicateCarrierSpecificationCodeError,
)

router = APIRouter(tags=["carrier-specifications"])


@router.post(
    "/carrier-specifications", response_model=CarrierSpecificationRead, status_code=status.HTTP_201_CREATED
)
def create_carrier_specification(
    payload: CarrierSpecificationCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.CARRIER_SPECIFICATION_MANAGE)),
) -> CarrierSpecificationRead:
    try:
        return carrier_specification_service.register_carrier_specification(
            db,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            carrier_type_code=payload.carrier_type_code,
            code=payload.code,
            name=payload.name,
            length_mm=payload.length_mm,
            width_mm=payload.width_mm,
            height_mm=payload.height_mm,
            biological_position_count=payload.biological_position_count,
        )
    except CarrierTypeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown carrier type") from exc
    except DuplicateCarrierSpecificationCodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Specification code already exists in this tenant"
        ) from exc
    except CarrierSpecificationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.get("/carrier-specifications", response_model=list[CarrierSpecificationRead])
def list_carrier_specifications(
    carrier_type: str | None = Query(default=None),
    specification_status: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.CARRIER_SPECIFICATION_READ)),
) -> list[CarrierSpecificationRead]:
    try:
        return carrier_specification_service.list_carrier_specifications(
            db, tenant_id=ctx.tenant_id, carrier_type_code=carrier_type, status=specification_status,
        )
    except CarrierTypeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown carrier type") from exc


@router.get("/carrier-specifications/{specification_id}", response_model=CarrierSpecificationRead)
def get_carrier_specification(
    specification_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.CARRIER_SPECIFICATION_READ)),
) -> CarrierSpecificationRead:
    try:
        return carrier_specification_service.get_carrier_specification(
            db, tenant_id=ctx.tenant_id, specification_id=specification_id
        )
    except CarrierSpecificationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Specification not found") from exc


@router.post("/carrier-specifications/{specification_id}/update", response_model=CarrierSpecificationRead)
def update_carrier_specification(
    specification_id: uuid.UUID,
    payload: CarrierSpecificationUpdate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.CARRIER_SPECIFICATION_MANAGE)),
) -> CarrierSpecificationRead:
    try:
        return carrier_specification_service.update_carrier_specification(
            db,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            specification_id=specification_id,
            carrier_type_code=payload.carrier_type_code,
            code=payload.code,
            name=payload.name,
            length_mm=payload.length_mm,
            width_mm=payload.width_mm,
            height_mm=payload.height_mm,
            biological_position_count=payload.biological_position_count,
        )
    except CarrierSpecificationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Specification not found") from exc
    except CarrierTypeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown carrier type") from exc
    except DuplicateCarrierSpecificationCodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Specification code already exists in this tenant"
        ) from exc
    except CarrierSpecificationStructurallyLockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Structural fields cannot change once a Carrier references this specification",
        ) from exc
    except CarrierSpecificationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post(
    "/carrier-specifications/{specification_id}/deactivate", response_model=CarrierSpecificationRead
)
def deactivate_carrier_specification(
    specification_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.CARRIER_SPECIFICATION_MANAGE)),
) -> CarrierSpecificationRead:
    try:
        return carrier_specification_service.deactivate_carrier_specification(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, specification_id=specification_id
        )
    except CarrierSpecificationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Specification not found") from exc


@router.post(
    "/carrier-specifications/{specification_id}/reactivate", response_model=CarrierSpecificationRead
)
def reactivate_carrier_specification(
    specification_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.CARRIER_SPECIFICATION_MANAGE)),
) -> CarrierSpecificationRead:
    try:
        return carrier_specification_service.reactivate_carrier_specification(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, specification_id=specification_id
        )
    except CarrierSpecificationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Specification not found") from exc
