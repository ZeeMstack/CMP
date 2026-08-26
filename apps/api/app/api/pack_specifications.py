import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.auth import TenantContext
from app.core.db import get_db
from app.core.permissions import Permission, require_permission
from app.schemas.pack_specification import (
    PackSpecificationCreate,
    PackSpecificationRead,
    PackSpecificationVersionActivate,
    PackSpecificationVersionCreate,
    PackSpecificationVersionRead,
    PackSpecificationVersionRetire,
)
from app.services import pack_specification_service
from app.services.errors import (
    CropNotFoundError,
    DuplicatePackSpecificationCodeError,
    GradeDefinitionVersionNotFoundError,
    InvalidPackSpecificationVersionEffectiveTimeError,
    PackagingUnitNotActiveError,
    PackagingUnitNotFoundError,
    PackSpecificationCommandReusedWithDifferentPayloadError,
    PackSpecificationNotFoundError,
    PackSpecificationVersionActivationReusedWithDifferentPayloadError,
    PackSpecificationVersionCommandReusedWithDifferentPayloadError,
    PackSpecificationVersionNotActiveError,
    PackSpecificationVersionNotDraftError,
    PackSpecificationVersionNotFoundError,
    PackSpecificationVersionRetirementReusedWithDifferentPayloadError,
    PackSpecificationVersionValidationError,
    VarietyCropMismatchError,
)

router = APIRouter(tags=["pack-specifications"])


@router.post("/pack-specifications", response_model=PackSpecificationRead, status_code=status.HTTP_201_CREATED)
def create_pack_specification(
    payload: PackSpecificationCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PACKING_MANAGE)),
) -> PackSpecificationRead:
    try:
        spec = pack_specification_service.register_pack_specification(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, client_command_id=payload.client_command_id,
            code=payload.code, name=payload.name, crop_id=payload.crop_id, variety_id=payload.variety_id,
            customer_reference=payload.customer_reference,
        )
    except CropNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crop not found") from exc
    except VarietyCropMismatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Variety not found for this crop"
        ) from exc
    except DuplicatePackSpecificationCodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Pack specification code already exists in this tenant"
        ) from exc
    except PackSpecificationCommandReusedWithDifferentPayloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="client_command_id already used with a different payload",
        ) from exc
    return PackSpecificationRead.model_validate(spec)


@router.get("/pack-specifications", response_model=list[PackSpecificationRead])
def list_pack_specifications(
    crop_id: uuid.UUID | None = Query(default=None),
    variety_id: uuid.UUID | None = Query(default=None),
    customer_reference: str | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PACKING_READ)),
) -> list[PackSpecificationRead]:
    specs = pack_specification_service.list_pack_specifications(
        db, tenant_id=ctx.tenant_id, crop_id=crop_id, variety_id=variety_id, customer_reference=customer_reference,
    )
    return [PackSpecificationRead.model_validate(s) for s in specs]


@router.get("/pack-specifications/{pack_specification_id}", response_model=PackSpecificationRead)
def get_pack_specification(
    pack_specification_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PACKING_READ)),
) -> PackSpecificationRead:
    try:
        spec = pack_specification_service.get_pack_specification(
            db, tenant_id=ctx.tenant_id, pack_specification_id=pack_specification_id
        )
    except PackSpecificationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pack specification not found") from exc
    return PackSpecificationRead.model_validate(spec)


@router.post(
    "/pack-specifications/{pack_specification_id}/versions",
    response_model=PackSpecificationVersionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_pack_specification_version(
    pack_specification_id: uuid.UUID,
    payload: PackSpecificationVersionCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PACKING_MANAGE)),
) -> PackSpecificationVersionRead:
    try:
        version = pack_specification_service.create_draft_version(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, client_command_id=payload.client_command_id,
            pack_specification_id=pack_specification_id,
            grade_definition_version_id=payload.grade_definition_version_id,
            packaging_unit_id=payload.packaging_unit_id, nominal_net_weight_kg=payload.nominal_net_weight_kg,
            whole_units_per_pack=payload.whole_units_per_pack, spec_notes=payload.spec_notes,
        )
    except (
        PackSpecificationNotFoundError,
        PackagingUnitNotFoundError,
        GradeDefinitionVersionNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except (
        PackSpecificationVersionCommandReusedWithDifferentPayloadError,
        PackagingUnitNotActiveError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except PackSpecificationVersionValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.reason) from exc
    return PackSpecificationVersionRead.model_validate(version)


@router.get(
    "/pack-specifications/{pack_specification_id}/versions", response_model=list[PackSpecificationVersionRead]
)
def list_pack_specification_versions(
    pack_specification_id: uuid.UUID,
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PACKING_READ)),
) -> list[PackSpecificationVersionRead]:
    try:
        versions = pack_specification_service.list_versions(
            db, tenant_id=ctx.tenant_id, pack_specification_id=pack_specification_id, status=status_filter
        )
    except PackSpecificationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pack specification not found") from exc
    return [PackSpecificationVersionRead.model_validate(v) for v in versions]


@router.get(
    "/pack-specifications/{pack_specification_id}/versions/{version_id}",
    response_model=PackSpecificationVersionRead,
)
def get_pack_specification_version(
    pack_specification_id: uuid.UUID,
    version_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PACKING_READ)),
) -> PackSpecificationVersionRead:
    try:
        version = pack_specification_service.get_version(
            db, tenant_id=ctx.tenant_id, pack_specification_id=pack_specification_id, version_id=version_id
        )
    except (PackSpecificationNotFoundError, PackSpecificationVersionNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return PackSpecificationVersionRead.model_validate(version)


@router.post(
    "/pack-specifications/{pack_specification_id}/versions/{version_id}/activate",
    response_model=PackSpecificationVersionRead,
)
def activate_pack_specification_version(
    pack_specification_id: uuid.UUID,
    version_id: uuid.UUID,
    payload: PackSpecificationVersionActivate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PACKING_MANAGE)),
) -> PackSpecificationVersionRead:
    try:
        version = pack_specification_service.activate_version(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, client_command_id=payload.client_command_id,
            pack_specification_id=pack_specification_id, version_id=version_id,
            effective_time=payload.effective_time,
        )
    except (PackSpecificationNotFoundError, PackSpecificationVersionNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except (
        PackSpecificationVersionNotDraftError,
        PackSpecificationVersionActivationReusedWithDifferentPayloadError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InvalidPackSpecificationVersionEffectiveTimeError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return PackSpecificationVersionRead.model_validate(version)


@router.post(
    "/pack-specifications/{pack_specification_id}/versions/{version_id}/retire",
    response_model=PackSpecificationVersionRead,
)
def retire_pack_specification_version(
    pack_specification_id: uuid.UUID,
    version_id: uuid.UUID,
    payload: PackSpecificationVersionRetire,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PACKING_MANAGE)),
) -> PackSpecificationVersionRead:
    try:
        version = pack_specification_service.retire_version(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, client_command_id=payload.client_command_id,
            pack_specification_id=pack_specification_id, version_id=version_id,
            effective_time=payload.effective_time,
        )
    except (PackSpecificationNotFoundError, PackSpecificationVersionNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except (
        PackSpecificationVersionNotActiveError,
        PackSpecificationVersionRetirementReusedWithDifferentPayloadError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InvalidPackSpecificationVersionEffectiveTimeError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return PackSpecificationVersionRead.model_validate(version)
