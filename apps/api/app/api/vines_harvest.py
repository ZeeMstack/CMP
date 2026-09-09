import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.auth import TenantContext
from app.core.permissions import Permission, require_permission
from app.schemas.vines_harvest import (
    CorrectVinesHarvestSourceLineCreate,
    RecordVinesHarvestCreate,
    VinesHarvestableSourceRead,
    VinesHarvestEventRead,
)
from app.services import harvest_service
from app.services.errors import (
    CropBatchClosedError,
    CropBatchNotFoundError,
    DuplicateProduceLotCodeError,
    FarmNotFoundError,
    HarvestCommandReusedWithDifferentPayloadError,
    HarvestCorrectionAlreadySupersededError,
    HarvestCorrectionCommandReusedWithDifferentPayloadError,
    HarvestCorrectionValidationError,
    HarvestEventNotFoundError,
    HarvestLedgerBalanceError,
    HarvestSourceLineNotFoundError,
    HarvestValidationError,
    InvalidHarvestEffectiveTimeError,
    LocationNotFoundError,
    QualityHoldOpenError,
    TooManyHarvestLinesError,
)

router = APIRouter(tags=["vines-harvest"])

_NOT_FOUND = (
    FarmNotFoundError,
    CropBatchNotFoundError,
    LocationNotFoundError,
    HarvestEventNotFoundError,
    HarvestSourceLineNotFoundError,
)
_INVALID = (
    HarvestValidationError,
    InvalidHarvestEffectiveTimeError,
    TooManyHarvestLinesError,
    HarvestCorrectionValidationError,
)
_CONFLICT_CODES: dict[type[Exception], str] = {
    HarvestCorrectionAlreadySupersededError: "HARVEST_CORRECTION_STALE",
    HarvestLedgerBalanceError: "HARVEST_NEGATIVE_LOT_BALANCE",
    QualityHoldOpenError: "HARVEST_QUALITY_HOLD",
}
_CONFLICT = (
    CropBatchClosedError,
    QualityHoldOpenError,
    HarvestCommandReusedWithDifferentPayloadError,
    DuplicateProduceLotCodeError,
    HarvestCorrectionCommandReusedWithDifferentPayloadError,
    HarvestCorrectionAlreadySupersededError,
    HarvestLedgerBalanceError,
)


def _conflict_detail(exc: Exception) -> dict[str, str] | str:
    code = _CONFLICT_CODES.get(type(exc))
    if code is None:
        return str(exc)
    return {"message": str(exc), "code": code}


@router.get(
    "/farms/{farm_id}/vines-production/harvestable-sources",
    response_model=list[VinesHarvestableSourceRead],
)
def list_vines_harvestable_sources(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.HARVEST_READ)),
) -> list[VinesHarvestableSourceRead]:
    try:
        return harvest_service.list_vines_harvestable_sources(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id
        )
    except _NOT_FOUND as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.post(
    "/farms/{farm_id}/vines-production/harvests",
    response_model=VinesHarvestEventRead,
    status_code=status.HTTP_201_CREATED,
)
def record_vines_harvest(
    farm_id: uuid.UUID,
    payload: RecordVinesHarvestCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.HARVEST_MANAGE)),
) -> VinesHarvestEventRead:
    source_lines = [
        {
            "source_location_id": line.gutter_id, "harvested_weight_kg": line.harvested_weight_kg,
            "whole_unit_count": None, "note": line.note,
        }
        for line in payload.source_lines
    ]
    try:
        event = harvest_service.record_vines_harvest(
            db,
            tenant_id=ctx.tenant_id,
            farm_id=farm_id,
            actor_user_id=ctx.user_id,
            batch_id=payload.batch_id,
            client_command_id=payload.client_command_id,
            effective_time=payload.effective_time,
            produce_lot_code=payload.produce_lot_code,
            note=payload.note,
            source_lines=source_lines,
        )
    except _NOT_FOUND as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except _CONFLICT as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_conflict_detail(exc)) from exc
    except _INVALID as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return harvest_service.get_vines_harvest_event(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, harvest_event_id=event.id
    )


@router.get(
    "/farms/{farm_id}/vines-production/harvests",
    response_model=list[VinesHarvestEventRead],
)
def list_vines_harvests(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.HARVEST_READ)),
) -> list[VinesHarvestEventRead]:
    try:
        return harvest_service.list_vines_harvest_events(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id
        )
    except _NOT_FOUND as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get(
    "/farms/{farm_id}/vines-production/harvests/{harvest_event_id}",
    response_model=VinesHarvestEventRead,
)
def get_vines_harvest(
    farm_id: uuid.UUID,
    harvest_event_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.HARVEST_READ)),
) -> VinesHarvestEventRead:
    try:
        return harvest_service.get_vines_harvest_event(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, harvest_event_id=harvest_event_id
        )
    except _NOT_FOUND as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.post(
    "/farms/{farm_id}/vines-production/harvests/{harvest_event_id}/source-lines/{harvest_source_line_id}/correct",
    response_model=VinesHarvestEventRead,
    status_code=status.HTTP_201_CREATED,
)
def correct_vines_harvest_source_line(
    farm_id: uuid.UUID,
    harvest_event_id: uuid.UUID,
    harvest_source_line_id: uuid.UUID,
    payload: CorrectVinesHarvestSourceLineCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.HARVEST_MANAGE)),
) -> VinesHarvestEventRead:
    try:
        harvest_service.correct_vines_harvest_source_line(
            db,
            tenant_id=ctx.tenant_id,
            farm_id=farm_id,
            harvest_event_id=harvest_event_id,
            harvest_source_line_id=harvest_source_line_id,
            actor_user_id=ctx.user_id,
            client_command_id=payload.client_command_id,
            supersedes_correction_id=payload.supersedes_correction_id,
            is_void=payload.is_void,
            corrected_harvested_weight_kg=payload.corrected_harvested_weight_kg,
            reason_code=payload.reason_code,
            note=payload.note,
        )
    except _NOT_FOUND as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except _CONFLICT as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_conflict_detail(exc)) from exc
    except _INVALID as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return harvest_service.get_vines_harvest_event(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, harvest_event_id=harvest_event_id
    )
