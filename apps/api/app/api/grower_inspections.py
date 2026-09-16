import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import TenantContext
from app.core.db import get_db
from app.core.permissions import Permission, require_permission
from app.schemas.grower_inspection import (
    GrowerInspectionCreate,
    GrowerInspectionRead,
    InspectionFindingRead,
)
from app.services import grower_inspection_service
from app.services.errors import (
    BatchCarrierAssignmentNotFoundError,
    CropBatchClosedError,
    CropBatchNotFoundError,
    FarmNotFoundError,
    GrowerInspectionCommandReusedWithDifferentPayloadError,
    GrowerInspectionNotFoundError,
    GrowerInspectionValidationError,
    ObservationDefinitionNotFoundError,
)

router = APIRouter(tags=["grower-inspections"])

_NOT_FOUND_ERRORS = (
    FarmNotFoundError, CropBatchNotFoundError, BatchCarrierAssignmentNotFoundError,
    ObservationDefinitionNotFoundError, GrowerInspectionNotFoundError,
)


def _to_read(db, *, tenant_id: uuid.UUID, inspection) -> GrowerInspectionRead:
    findings = grower_inspection_service.list_findings(db, tenant_id=tenant_id, inspection_id=inspection.id)
    return GrowerInspectionRead(
        id=inspection.id, tenant_id=inspection.tenant_id, farm_id=inspection.farm_id, batch_id=inspection.batch_id,
        batch_carrier_assignment_id=inspection.batch_carrier_assignment_id, location_id=inspection.location_id,
        growing_protocol_version_id=inspection.growing_protocol_version_id,
        inspected_by_user_id=inspection.inspected_by_user_id, effective_time=inspection.effective_time,
        recorded_time=inspection.recorded_time, inspected_count=inspection.inspected_count,
        overall_assessment=inspection.overall_assessment, notes=inspection.notes,
        observation_event_id=inspection.observation_event_id,
        findings=[InspectionFindingRead.model_validate(f) for f in findings],
    )


@router.post(
    "/farms/{farm_id}/crop-batches/{batch_id}/grower-inspections", response_model=GrowerInspectionRead,
    status_code=status.HTTP_201_CREATED,
)
def record_inspection(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    payload: GrowerInspectionCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.CROP_INSPECTION_MANAGE)),
) -> GrowerInspectionRead:
    if payload.batch_id != batch_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="batch_id mismatch")
    findings = [f.model_dump() for f in payload.findings]
    observation_values = [v.model_dump() for v in payload.observation_values]
    try:
        inspection = grower_inspection_service.record_inspection(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id,
            client_command_id=payload.client_command_id, batch_id=batch_id,
            batch_carrier_assignment_id=payload.batch_carrier_assignment_id, effective_time=payload.effective_time,
            inspected_count=payload.inspected_count, overall_assessment=payload.overall_assessment,
            notes=payload.notes, findings=findings, observation_values=observation_values,
        )
    except _NOT_FOUND_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except (CropBatchClosedError, GrowerInspectionCommandReusedWithDifferentPayloadError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except GrowerInspectionValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _to_read(db, tenant_id=ctx.tenant_id, inspection=inspection)


@router.get(
    "/farms/{farm_id}/crop-batches/{batch_id}/grower-inspections", response_model=list[GrowerInspectionRead]
)
def list_inspections(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.CROP_INSPECTION_READ)),
) -> list[GrowerInspectionRead]:
    try:
        inspections = grower_inspection_service.list_inspections_for_batch(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id
        )
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return [_to_read(db, tenant_id=ctx.tenant_id, inspection=i) for i in inspections]


@router.get(
    "/farms/{farm_id}/crop-batches/{batch_id}/grower-inspections/{inspection_id}",
    response_model=GrowerInspectionRead,
)
def get_inspection(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    inspection_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.CROP_INSPECTION_READ)),
) -> GrowerInspectionRead:
    try:
        inspection = grower_inspection_service.get_inspection(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, inspection_id=inspection_id
        )
    except GrowerInspectionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    if inspection.batch_id != batch_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return _to_read(db, tenant_id=ctx.tenant_id, inspection=inspection)
