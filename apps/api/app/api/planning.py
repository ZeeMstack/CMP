import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import TenantContext
from app.core.db import get_db
from app.core.permissions import Permission, require_permission
from app.schemas.planning import (
    ProductionRequirementCreate,
    ProductionRequirementRead,
    ProductionRequirementStatusCommand,
    ProductionRequirementUpdate,
    SeedingProgramLineCreate,
    SeedingProgramLineDetailRead,
    SeedingProgramLineRead,
    SeedingProgramLineStatusCommand,
    SeedingProgramLineUpdate,
)
from app.services import planning_service
from app.services.errors import (
    CropNotFoundError,
    FarmNotFoundError,
    ProductionRequirementCommandReusedWithDifferentPayloadError,
    ProductionRequirementNotEditableError,
    ProductionRequirementNotFoundError,
    ProductionRequirementValidationError,
    SeedingProgramLineCommandReusedWithDifferentPayloadError,
    SeedingProgramLineNotEditableError,
    SeedingProgramLineNotFoundError,
    SeedingProgramLineValidationError,
    UnitOfMeasureNotFoundError,
    VarietyNotFoundError,
)

router = APIRouter(tags=["planning"])


# --- Production Requirements --------------------------------------------------------


@router.post(
    "/farms/{farm_id}/production-requirements",
    response_model=ProductionRequirementRead,
    status_code=status.HTTP_201_CREATED,
)
def create_production_requirement(
    farm_id: uuid.UUID,
    payload: ProductionRequirementCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PLANNING_MANAGE)),
) -> ProductionRequirementRead:
    try:
        requirement = planning_service.create_production_requirement(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id,
            client_command_id=payload.client_command_id, crop_id=payload.crop_id, variety_id=payload.variety_id,
            required_by_date=payload.required_by_date, required_quantity=payload.required_quantity,
            quantity_uom_id=payload.quantity_uom_id, reference=payload.reference, notes=payload.notes,
        )
    except (FarmNotFoundError, CropNotFoundError, VarietyNotFoundError, UnitOfMeasureNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except ProductionRequirementCommandReusedWithDifferentPayloadError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return planning_service.get_production_requirement(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, requirement_id=requirement.id
    )


@router.get("/farms/{farm_id}/production-requirements", response_model=list[ProductionRequirementRead])
def list_production_requirements(
    farm_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PLANNING_READ)),
) -> list[ProductionRequirementRead]:
    try:
        return planning_service.list_production_requirements(db, tenant_id=ctx.tenant_id, farm_id=farm_id)
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get(
    "/farms/{farm_id}/production-requirements/{requirement_id}", response_model=ProductionRequirementRead
)
def get_production_requirement(
    farm_id: uuid.UUID,
    requirement_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PLANNING_READ)),
) -> ProductionRequirementRead:
    try:
        return planning_service.get_production_requirement(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, requirement_id=requirement_id
        )
    except (FarmNotFoundError, ProductionRequirementNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.post(
    "/farms/{farm_id}/production-requirements/{requirement_id}/update", response_model=ProductionRequirementRead
)
def update_production_requirement(
    farm_id: uuid.UUID,
    requirement_id: uuid.UUID,
    payload: ProductionRequirementUpdate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PLANNING_MANAGE)),
) -> ProductionRequirementRead:
    try:
        planning_service.update_production_requirement(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, requirement_id=requirement_id,
            client_command_id=payload.client_command_id, required_by_date=payload.required_by_date,
            required_quantity=payload.required_quantity, reference=payload.reference, notes=payload.notes,
        )
    except (FarmNotFoundError, ProductionRequirementNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except (
        ProductionRequirementCommandReusedWithDifferentPayloadError,
        ProductionRequirementNotEditableError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return planning_service.get_production_requirement(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, requirement_id=requirement_id
    )


@router.post(
    "/farms/{farm_id}/production-requirements/{requirement_id}/close", response_model=ProductionRequirementRead
)
def close_production_requirement(
    farm_id: uuid.UUID,
    requirement_id: uuid.UUID,
    payload: ProductionRequirementStatusCommand,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PLANNING_MANAGE)),
) -> ProductionRequirementRead:
    try:
        planning_service.close_production_requirement(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, requirement_id=requirement_id,
            client_command_id=payload.client_command_id,
        )
    except (FarmNotFoundError, ProductionRequirementNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except ProductionRequirementCommandReusedWithDifferentPayloadError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ProductionRequirementValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return planning_service.get_production_requirement(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, requirement_id=requirement_id
    )


@router.post(
    "/farms/{farm_id}/production-requirements/{requirement_id}/cancel", response_model=ProductionRequirementRead
)
def cancel_production_requirement(
    farm_id: uuid.UUID,
    requirement_id: uuid.UUID,
    payload: ProductionRequirementStatusCommand,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PLANNING_MANAGE)),
) -> ProductionRequirementRead:
    try:
        planning_service.cancel_production_requirement(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, requirement_id=requirement_id,
            client_command_id=payload.client_command_id,
        )
    except (FarmNotFoundError, ProductionRequirementNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except ProductionRequirementCommandReusedWithDifferentPayloadError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return planning_service.get_production_requirement(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, requirement_id=requirement_id
    )


# --- Seeding Program Lines -----------------------------------------------------------


@router.post(
    "/farms/{farm_id}/production-requirements/{requirement_id}/seeding-program-lines",
    response_model=SeedingProgramLineDetailRead,
    status_code=status.HTTP_201_CREATED,
)
def create_seeding_program_line(
    farm_id: uuid.UUID,
    requirement_id: uuid.UUID,
    payload: SeedingProgramLineCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PLANNING_MANAGE)),
) -> SeedingProgramLineDetailRead:
    try:
        line = planning_service.create_seeding_program_line(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id,
            production_requirement_id=requirement_id, client_command_id=payload.client_command_id,
            planned_sow_date=payload.planned_sow_date, crop_id=payload.crop_id, variety_id=payload.variety_id,
            planned_quantity=payload.planned_quantity, planned_quantity_uom_id=payload.planned_quantity_uom_id,
            expected_coverage_quantity=payload.expected_coverage_quantity,
            expected_coverage_uom_id=payload.expected_coverage_uom_id, notes=payload.notes,
        )
    except (
        FarmNotFoundError,
        ProductionRequirementNotFoundError,
        CropNotFoundError,
        VarietyNotFoundError,
        UnitOfMeasureNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except SeedingProgramLineCommandReusedWithDifferentPayloadError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except SeedingProgramLineValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return planning_service.get_seeding_program_line(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, line_id=line.id
    )


@router.get(
    "/farms/{farm_id}/production-requirements/{requirement_id}/seeding-program-lines",
    response_model=list[SeedingProgramLineRead],
)
def list_seeding_program_lines_for_requirement(
    farm_id: uuid.UUID,
    requirement_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PLANNING_READ)),
) -> list[SeedingProgramLineRead]:
    try:
        planning_service.get_production_requirement(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, requirement_id=requirement_id
        )
        return planning_service.list_seeding_program_lines(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, production_requirement_id=requirement_id
        )
    except (FarmNotFoundError, ProductionRequirementNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get("/farms/{farm_id}/seeding-program-lines", response_model=list[SeedingProgramLineRead])
def list_seeding_program_lines(
    farm_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PLANNING_READ)),
) -> list[SeedingProgramLineRead]:
    try:
        return planning_service.list_seeding_program_lines(db, tenant_id=ctx.tenant_id, farm_id=farm_id)
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get("/farms/{farm_id}/seeding-program-lines/{line_id}", response_model=SeedingProgramLineDetailRead)
def get_seeding_program_line(
    farm_id: uuid.UUID,
    line_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PLANNING_READ)),
) -> SeedingProgramLineDetailRead:
    try:
        return planning_service.get_seeding_program_line(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, line_id=line_id
        )
    except (FarmNotFoundError, SeedingProgramLineNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.post(
    "/farms/{farm_id}/seeding-program-lines/{line_id}/update", response_model=SeedingProgramLineDetailRead
)
def update_seeding_program_line(
    farm_id: uuid.UUID,
    line_id: uuid.UUID,
    payload: SeedingProgramLineUpdate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PLANNING_MANAGE)),
) -> SeedingProgramLineDetailRead:
    try:
        planning_service.update_seeding_program_line(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, line_id=line_id,
            client_command_id=payload.client_command_id, planned_sow_date=payload.planned_sow_date,
            planned_quantity=payload.planned_quantity, expected_coverage_quantity=payload.expected_coverage_quantity,
            notes=payload.notes,
        )
    except (FarmNotFoundError, SeedingProgramLineNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except (
        SeedingProgramLineCommandReusedWithDifferentPayloadError,
        SeedingProgramLineNotEditableError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return planning_service.get_seeding_program_line(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, line_id=line_id
    )


@router.post(
    "/farms/{farm_id}/seeding-program-lines/{line_id}/cancel", response_model=SeedingProgramLineDetailRead
)
def cancel_seeding_program_line(
    farm_id: uuid.UUID,
    line_id: uuid.UUID,
    payload: SeedingProgramLineStatusCommand,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PLANNING_MANAGE)),
) -> SeedingProgramLineDetailRead:
    try:
        planning_service.cancel_seeding_program_line(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, line_id=line_id,
            client_command_id=payload.client_command_id,
        )
    except (FarmNotFoundError, SeedingProgramLineNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except SeedingProgramLineCommandReusedWithDifferentPayloadError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return planning_service.get_seeding_program_line(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, line_id=line_id
    )
