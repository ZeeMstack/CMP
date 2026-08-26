import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.auth import TenantContext
from app.core.db import get_db
from app.core.permissions import Permission, require_permission
from app.schemas.grade_definition import (
    GradeDefinitionCreate,
    GradeDefinitionRead,
    GradeDefinitionVersionActivate,
    GradeDefinitionVersionCreate,
    GradeDefinitionVersionRead,
    GradeDefinitionVersionRetire,
)
from app.services import grade_definition_service
from app.services.errors import (
    CropNotFoundError,
    DuplicateGradeDefinitionCodeError,
    GradeDefinitionCommandReusedWithDifferentPayloadError,
    GradeDefinitionNotFoundError,
    GradeDefinitionVersionActivationReusedWithDifferentPayloadError,
    GradeDefinitionVersionCommandReusedWithDifferentPayloadError,
    GradeDefinitionVersionNotActiveError,
    GradeDefinitionVersionNotDraftError,
    GradeDefinitionVersionNotFoundError,
    GradeDefinitionVersionRetirementReusedWithDifferentPayloadError,
    InvalidGradeDefinitionVersionEffectiveTimeError,
    VarietyCropMismatchError,
)

router = APIRouter(tags=["grade-definitions"])


@router.post("/grade-definitions", response_model=GradeDefinitionRead, status_code=status.HTTP_201_CREATED)
def create_grade_definition(
    payload: GradeDefinitionCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PACKING_MANAGE)),
) -> GradeDefinitionRead:
    try:
        definition = grade_definition_service.register_grade_definition(
            db,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            client_command_id=payload.client_command_id,
            code=payload.code,
            name=payload.name,
            crop_id=payload.crop_id,
            variety_id=payload.variety_id,
            description=payload.description,
        )
    except CropNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crop not found") from exc
    except VarietyCropMismatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Variety not found for this crop"
        ) from exc
    except DuplicateGradeDefinitionCodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Grade definition code already exists in this tenant"
        ) from exc
    except GradeDefinitionCommandReusedWithDifferentPayloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="client_command_id already used with a different payload",
        ) from exc
    return GradeDefinitionRead.model_validate(definition)


@router.get("/grade-definitions", response_model=list[GradeDefinitionRead])
def list_grade_definitions(
    crop_id: uuid.UUID | None = Query(default=None),
    variety_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PACKING_READ)),
) -> list[GradeDefinitionRead]:
    definitions = grade_definition_service.list_grade_definitions(
        db, tenant_id=ctx.tenant_id, crop_id=crop_id, variety_id=variety_id
    )
    return [GradeDefinitionRead.model_validate(d) for d in definitions]


@router.get("/grade-definitions/{grade_definition_id}", response_model=GradeDefinitionRead)
def get_grade_definition(
    grade_definition_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PACKING_READ)),
) -> GradeDefinitionRead:
    try:
        definition = grade_definition_service.get_grade_definition(
            db, tenant_id=ctx.tenant_id, grade_definition_id=grade_definition_id
        )
    except GradeDefinitionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Grade definition not found") from exc
    return GradeDefinitionRead.model_validate(definition)


@router.post(
    "/grade-definitions/{grade_definition_id}/versions",
    response_model=GradeDefinitionVersionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_grade_definition_version(
    grade_definition_id: uuid.UUID,
    payload: GradeDefinitionVersionCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PACKING_MANAGE)),
) -> GradeDefinitionVersionRead:
    try:
        version = grade_definition_service.create_draft_version(
            db,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            client_command_id=payload.client_command_id,
            grade_definition_id=grade_definition_id,
            spec_notes=payload.spec_notes,
        )
    except GradeDefinitionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Grade definition not found") from exc
    except GradeDefinitionVersionCommandReusedWithDifferentPayloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="client_command_id already used with a different payload",
        ) from exc
    return GradeDefinitionVersionRead.model_validate(version)


@router.get(
    "/grade-definitions/{grade_definition_id}/versions", response_model=list[GradeDefinitionVersionRead]
)
def list_grade_definition_versions(
    grade_definition_id: uuid.UUID,
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PACKING_READ)),
) -> list[GradeDefinitionVersionRead]:
    try:
        versions = grade_definition_service.list_versions(
            db, tenant_id=ctx.tenant_id, grade_definition_id=grade_definition_id, status=status_filter
        )
    except GradeDefinitionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Grade definition not found") from exc
    return [GradeDefinitionVersionRead.model_validate(v) for v in versions]


@router.get(
    "/grade-definitions/{grade_definition_id}/versions/{version_id}",
    response_model=GradeDefinitionVersionRead,
)
def get_grade_definition_version(
    grade_definition_id: uuid.UUID,
    version_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PACKING_READ)),
) -> GradeDefinitionVersionRead:
    try:
        version = grade_definition_service.get_version(
            db, tenant_id=ctx.tenant_id, grade_definition_id=grade_definition_id, version_id=version_id
        )
    except (GradeDefinitionNotFoundError, GradeDefinitionVersionNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return GradeDefinitionVersionRead.model_validate(version)


@router.post(
    "/grade-definitions/{grade_definition_id}/versions/{version_id}/activate",
    response_model=GradeDefinitionVersionRead,
)
def activate_grade_definition_version(
    grade_definition_id: uuid.UUID,
    version_id: uuid.UUID,
    payload: GradeDefinitionVersionActivate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PACKING_MANAGE)),
) -> GradeDefinitionVersionRead:
    try:
        version = grade_definition_service.activate_version(
            db,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            client_command_id=payload.client_command_id,
            grade_definition_id=grade_definition_id,
            version_id=version_id,
            effective_time=payload.effective_time,
        )
    except (GradeDefinitionNotFoundError, GradeDefinitionVersionNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except (
        GradeDefinitionVersionNotDraftError,
        GradeDefinitionVersionActivationReusedWithDifferentPayloadError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InvalidGradeDefinitionVersionEffectiveTimeError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return GradeDefinitionVersionRead.model_validate(version)


@router.post(
    "/grade-definitions/{grade_definition_id}/versions/{version_id}/retire",
    response_model=GradeDefinitionVersionRead,
)
def retire_grade_definition_version(
    grade_definition_id: uuid.UUID,
    version_id: uuid.UUID,
    payload: GradeDefinitionVersionRetire,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PACKING_MANAGE)),
) -> GradeDefinitionVersionRead:
    try:
        version = grade_definition_service.retire_version(
            db,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            client_command_id=payload.client_command_id,
            grade_definition_id=grade_definition_id,
            version_id=version_id,
            effective_time=payload.effective_time,
        )
    except (GradeDefinitionNotFoundError, GradeDefinitionVersionNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except (
        GradeDefinitionVersionNotActiveError,
        GradeDefinitionVersionRetirementReusedWithDifferentPayloadError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InvalidGradeDefinitionVersionEffectiveTimeError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return GradeDefinitionVersionRead.model_validate(version)
