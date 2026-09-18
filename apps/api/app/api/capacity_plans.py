import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.auth import TenantContext
from app.core.db import get_db
from app.core.permissions import Permission, require_permission
from app.schemas.capacity_plan import (
    CapacityAllocationStatusCommand,
    CreateProductionCapacityAllocation,
    LocationCapacitySummaryRead,
    ProductionCapacityAllocationRead,
    UpdateProductionCapacityAllocation,
)
from app.services import capacity_plan_service
from app.services.errors import (
    CapacityAllocationExceedsAuthoritativeCapacityError,
    CropBatchNotFoundError,
    FarmNotFoundError,
    LocationNotFoundError,
    ProductionCapacityAllocationCommandReusedWithDifferentPayloadError,
    ProductionCapacityAllocationNotEditableError,
    ProductionCapacityAllocationNotFoundError,
    ProductionSystemNotFoundError,
    SeedingProgramLineNotFoundError,
)

router = APIRouter(tags=["capacity-plans"])


@router.post(
    "/farms/{farm_id}/capacity-allocations",
    response_model=ProductionCapacityAllocationRead,
    status_code=status.HTTP_201_CREATED,
)
def create_capacity_allocation(
    farm_id: uuid.UUID,
    payload: CreateProductionCapacityAllocation,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.CAPACITY_PLAN_MANAGE)),
) -> ProductionCapacityAllocationRead:
    try:
        allocation = capacity_plan_service.create_capacity_allocation(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id,
            client_command_id=payload.client_command_id, location_id=payload.location_id,
            production_system_id=payload.production_system_id, planned_start_date=payload.planned_start_date,
            planned_end_date=payload.planned_end_date, planned_capacity_amount=payload.planned_capacity_amount,
            source_seeding_program_line_id=payload.source_seeding_program_line_id,
            source_crop_batch_id=payload.source_crop_batch_id, notes=payload.notes,
        )
    except (
        FarmNotFoundError, LocationNotFoundError, ProductionSystemNotFoundError,
        SeedingProgramLineNotFoundError, CropBatchNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except ProductionCapacityAllocationCommandReusedWithDifferentPayloadError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except CapacityAllocationExceedsAuthoritativeCapacityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return capacity_plan_service.get_capacity_allocation(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, allocation_id=allocation.id
    )


@router.post(
    "/farms/{farm_id}/capacity-allocations/{allocation_id}/update",
    response_model=ProductionCapacityAllocationRead,
)
def update_capacity_allocation(
    farm_id: uuid.UUID,
    allocation_id: uuid.UUID,
    payload: UpdateProductionCapacityAllocation,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.CAPACITY_PLAN_MANAGE)),
) -> ProductionCapacityAllocationRead:
    try:
        capacity_plan_service.update_capacity_allocation(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, allocation_id=allocation_id,
            client_command_id=payload.client_command_id, planned_start_date=payload.planned_start_date,
            planned_end_date=payload.planned_end_date, planned_capacity_amount=payload.planned_capacity_amount,
            production_system_id=payload.production_system_id, notes=payload.notes,
        )
    except (FarmNotFoundError, ProductionCapacityAllocationNotFoundError, ProductionSystemNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except (
        ProductionCapacityAllocationCommandReusedWithDifferentPayloadError,
        ProductionCapacityAllocationNotEditableError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except CapacityAllocationExceedsAuthoritativeCapacityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return capacity_plan_service.get_capacity_allocation(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, allocation_id=allocation_id
    )


@router.post(
    "/farms/{farm_id}/capacity-allocations/{allocation_id}/cancel",
    response_model=ProductionCapacityAllocationRead,
)
def cancel_capacity_allocation(
    farm_id: uuid.UUID,
    allocation_id: uuid.UUID,
    payload: CapacityAllocationStatusCommand,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.CAPACITY_PLAN_MANAGE)),
) -> ProductionCapacityAllocationRead:
    try:
        capacity_plan_service.cancel_capacity_allocation(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, allocation_id=allocation_id,
            client_command_id=payload.client_command_id,
        )
    except (FarmNotFoundError, ProductionCapacityAllocationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return capacity_plan_service.get_capacity_allocation(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, allocation_id=allocation_id
    )


@router.get("/farms/{farm_id}/capacity-allocations", response_model=list[ProductionCapacityAllocationRead])
def list_capacity_allocations(
    farm_id: uuid.UUID,
    location_id: uuid.UUID | None = Query(None),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.CAPACITY_PLAN_READ)),
) -> list[ProductionCapacityAllocationRead]:
    try:
        return capacity_plan_service.list_capacity_allocations(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, location_id=location_id
        )
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get(
    "/farms/{farm_id}/capacity-allocations/{allocation_id}", response_model=ProductionCapacityAllocationRead
)
def get_capacity_allocation(
    farm_id: uuid.UUID,
    allocation_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.CAPACITY_PLAN_READ)),
) -> ProductionCapacityAllocationRead:
    try:
        return capacity_plan_service.get_capacity_allocation(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, allocation_id=allocation_id
        )
    except (FarmNotFoundError, ProductionCapacityAllocationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get(
    "/farms/{farm_id}/locations/{location_id}/capacity-summary", response_model=LocationCapacitySummaryRead
)
def get_location_capacity_summary(
    farm_id: uuid.UUID,
    location_id: uuid.UUID,
    window_start_date: date = Query(...),
    window_end_date: date = Query(...),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.CAPACITY_PLAN_READ)),
) -> LocationCapacitySummaryRead:
    try:
        return capacity_plan_service.get_location_capacity_summary(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, location_id=location_id,
            window_start_date=window_start_date, window_end_date=window_end_date,
        )
    except (FarmNotFoundError, LocationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
