import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.auth import TenantContext
from app.core.permissions import Permission, require_permission
from app.schemas.carrier import CarrierBulkCreate, CarrierCreate, CarrierRead
from app.schemas.movement import MovementRead
from app.schemas.occupancy import OccupancyRead, ResolvedLocationRead
from app.services import carrier_service, movement_service
from app.services.errors import (
    CarrierNotFoundError,
    CarrierTypeNotFoundError,
    DuplicateCarrierCodeError,
    FarmNotFoundError,
)

router = APIRouter(tags=["carriers"])


@router.post("/farms/{farm_id}/carriers", response_model=CarrierRead, status_code=status.HTTP_201_CREATED)
def register_carrier(
    farm_id: uuid.UUID,
    payload: CarrierCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.CARRIER_MANAGE)),
) -> CarrierRead:
    try:
        carrier = carrier_service.register_carrier(
            db,
            tenant_id=ctx.tenant_id,
            farm_id=farm_id,
            actor_user_id=ctx.user_id,
            carrier_type_code=payload.carrier_type_code,
            code=payload.code,
            issued_date=payload.issued_date,
        )
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found") from exc
    except CarrierTypeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown carrier type") from exc
    except DuplicateCarrierCodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Carrier code already exists in this tenant"
        ) from exc
    return CarrierRead.model_validate(carrier)


@router.post(
    "/farms/{farm_id}/carriers/bulk", response_model=list[CarrierRead], status_code=status.HTTP_201_CREATED
)
def bulk_register_carriers(
    farm_id: uuid.UUID,
    payload: CarrierBulkCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.CARRIER_MANAGE)),
) -> list[CarrierRead]:
    try:
        created = carrier_service.bulk_register_carriers(
            db,
            tenant_id=ctx.tenant_id,
            farm_id=farm_id,
            actor_user_id=ctx.user_id,
            carrier_type_code=payload.carrier_type_code,
            code_prefix=payload.code_prefix,
            start=payload.start,
            end=payload.end,
            pad_width=payload.pad_width,
        )
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found") from exc
    except CarrierTypeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown carrier type") from exc
    except DuplicateCarrierCodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="One or more generated carrier codes already exist"
        ) from exc
    return [CarrierRead.model_validate(carrier) for carrier in created]


@router.get("/farms/{farm_id}/carriers/{carrier_id}", response_model=CarrierRead)
def get_carrier(
    farm_id: uuid.UUID,
    carrier_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.CARRIER_READ)),
) -> CarrierRead:
    try:
        carrier = carrier_service.get_carrier(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, carrier_id=carrier_id
        )
    except (FarmNotFoundError, CarrierNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return CarrierRead.model_validate(carrier)


@router.get("/farms/{farm_id}/carriers", response_model=list[CarrierRead])
def list_carriers(
    farm_id: uuid.UUID,
    carrier_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.CARRIER_READ)),
) -> list[CarrierRead]:
    try:
        carriers = carrier_service.list_carriers(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, carrier_type_code=carrier_type
        )
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found") from exc
    except CarrierTypeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown carrier type") from exc
    return [CarrierRead.model_validate(carrier) for carrier in carriers]


@router.get("/farms/{farm_id}/carriers/{carrier_id}/occupancy", response_model=OccupancyRead | None)
def get_carrier_occupancy(
    farm_id: uuid.UUID,
    carrier_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.CARRIER_READ)),
) -> OccupancyRead | None:
    try:
        occupancy = movement_service.get_occupancy(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, occupant_kind="carrier", occupant_id=carrier_id
        )
    except (FarmNotFoundError, CarrierNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return OccupancyRead.from_model(occupancy) if occupancy is not None else None


@router.get("/farms/{farm_id}/carriers/{carrier_id}/movement-history", response_model=list[MovementRead])
def get_carrier_movement_history(
    farm_id: uuid.UUID,
    carrier_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.CARRIER_READ)),
) -> list[MovementRead]:
    try:
        movements = movement_service.get_movement_history(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, occupant_kind="carrier", occupant_id=carrier_id
        )
    except (FarmNotFoundError, CarrierNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return [MovementRead.from_model(m) for m in movements]


@router.get("/farms/{farm_id}/carriers/{carrier_id}/resolved-location", response_model=ResolvedLocationRead)
def get_carrier_resolved_location(
    farm_id: uuid.UUID,
    carrier_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.CARRIER_READ)),
) -> ResolvedLocationRead:
    try:
        resolved = movement_service.get_resolved_location(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, occupant_kind="carrier", occupant_id=carrier_id
        )
    except (FarmNotFoundError, CarrierNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return ResolvedLocationRead(**resolved)
