import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.auth import TenantContext
from app.core.permissions import Permission, require_permission
from app.schemas.leafy_harvest import (
    CorrectLeafyHarvestSourceLineCreate,
    HarvestablePlateRead,
    LeafyHarvestEventRead,
    RecordLeafyHarvestCreate,
)
from app.services import harvest_service
from app.services.errors import (
    CarrierNotFoundError,
    CropBatchClosedError,
    CropBatchNotFoundError,
    DuplicateProduceLotCodeError,
    FarmNotFoundError,
    HarvestCarrierReusedError,
    HarvestCommandReusedWithDifferentPayloadError,
    HarvestCorrectionAlreadySupersededError,
    HarvestCorrectionCommandReusedWithDifferentPayloadError,
    HarvestCorrectionValidationError,
    HarvestEventNotFoundError,
    HarvestLedgerBalanceError,
    HarvestPopulationInsufficientError,
    HarvestSourceAssignmentNotFoundError,
    HarvestSourceLineNotFoundError,
    HarvestValidationError,
    InvalidHarvestEffectiveTimeError,
    NoPopulationRootError,
    QualityHoldOpenError,
    TooManyHarvestLinesError,
    UnsupportedHarvestSourceCarrierTypeError,
)

router = APIRouter(tags=["leafy-harvest"])

_NOT_FOUND = (
    FarmNotFoundError,
    CropBatchNotFoundError,
    HarvestSourceAssignmentNotFoundError,
    CarrierNotFoundError,
    HarvestEventNotFoundError,
    HarvestSourceLineNotFoundError,
)
_INVALID = (
    HarvestValidationError,
    InvalidHarvestEffectiveTimeError,
    TooManyHarvestLinesError,
    UnsupportedHarvestSourceCarrierTypeError,
    NoPopulationRootError,
    HarvestCorrectionValidationError,
)
_CONFLICT = (
    CropBatchClosedError,
    QualityHoldOpenError,
    HarvestCommandReusedWithDifferentPayloadError,
    DuplicateProduceLotCodeError,
    HarvestPopulationInsufficientError,
    HarvestCorrectionCommandReusedWithDifferentPayloadError,
    HarvestCorrectionAlreadySupersededError,
    HarvestCarrierReusedError,
    HarvestLedgerBalanceError,
)

# SLICE 2 CORRECTION 1: a stable, machine-readable identifier for the 409
# subtypes the Leafy Harvest frontend must branch on -- human-readable
# `detail` text is never a machine contract. Narrow and additive: every
# OTHER conflict here (idempotency replay-mismatches, CropBatchClosedError,
# DuplicateProduceLotCodeError) keeps its existing plain-string `detail`
# exactly as before; only the 5 conflict types the ticket names carry a
# `code` alongside their unchanged `message` text. The shared frontend
# envelope (`lib/errors/adapter.ts`/`lib/api/client.ts`) parses both a
# bare string and this `{message, code}` shape, so no other route's
# response shape changes.
_CONFLICT_CODES: dict[type[Exception], str] = {
    HarvestCorrectionAlreadySupersededError: "HARVEST_CORRECTION_STALE",
    HarvestLedgerBalanceError: "HARVEST_NEGATIVE_LOT_BALANCE",
    QualityHoldOpenError: "HARVEST_QUALITY_HOLD",
    HarvestPopulationInsufficientError: "HARVEST_POPULATION_CONFLICT",
    HarvestCarrierReusedError: "HARVEST_CARRIER_REUSED",
}


def _conflict_detail(exc: Exception) -> dict[str, str] | str:
    code = _CONFLICT_CODES.get(type(exc))
    if code is None:
        return str(exc)
    return {"message": str(exc), "code": code}


@router.get(
    "/farms/{farm_id}/leafy-production/harvestable-plates",
    response_model=list[HarvestablePlateRead],
)
def list_harvestable_plates(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.HARVEST_READ)),
) -> list[HarvestablePlateRead]:
    try:
        return harvest_service.list_harvestable_production_plates(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id
        )
    except _NOT_FOUND as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.post(
    "/farms/{farm_id}/leafy-production/harvests",
    response_model=LeafyHarvestEventRead,
    status_code=status.HTTP_201_CREATED,
)
def record_leafy_harvest(
    farm_id: uuid.UUID,
    payload: RecordLeafyHarvestCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.HARVEST_MANAGE)),
) -> LeafyHarvestEventRead:
    source_lines = [
        {
            "batch_carrier_assignment_id": line.batch_carrier_assignment_id,
            "harvested_weight_kg": line.harvested_weight_kg,
            "whole_unit_count": line.whole_unit_count,
            "note": line.note,
        }
        for line in payload.source_lines
    ]
    try:
        event = harvest_service.record_leafy_harvest(
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
    return harvest_service.get_leafy_harvest_event(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, harvest_event_id=event.id
    )


@router.get(
    "/farms/{farm_id}/leafy-production/harvests",
    response_model=list[LeafyHarvestEventRead],
)
def list_leafy_harvests(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.HARVEST_READ)),
) -> list[LeafyHarvestEventRead]:
    try:
        return harvest_service.list_leafy_harvest_events(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id
        )
    except _NOT_FOUND as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get(
    "/farms/{farm_id}/leafy-production/harvests/{harvest_event_id}",
    response_model=LeafyHarvestEventRead,
)
def get_leafy_harvest(
    farm_id: uuid.UUID,
    harvest_event_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.HARVEST_READ)),
) -> LeafyHarvestEventRead:
    try:
        return harvest_service.get_leafy_harvest_event(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, harvest_event_id=harvest_event_id
        )
    except _NOT_FOUND as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.post(
    "/farms/{farm_id}/leafy-production/harvests/{harvest_event_id}/source-lines/{harvest_source_line_id}/correct",
    response_model=LeafyHarvestEventRead,
    status_code=status.HTTP_201_CREATED,
)
def correct_leafy_harvest_source_line(
    farm_id: uuid.UUID,
    harvest_event_id: uuid.UUID,
    harvest_source_line_id: uuid.UUID,
    payload: CorrectLeafyHarvestSourceLineCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.HARVEST_MANAGE)),
) -> LeafyHarvestEventRead:
    try:
        harvest_service.correct_leafy_harvest_source_line(
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
            corrected_whole_unit_count=payload.corrected_whole_unit_count,
            reason_code=payload.reason_code,
            note=payload.note,
        )
    except _NOT_FOUND as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except _CONFLICT as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_conflict_detail(exc)) from exc
    except _INVALID as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return harvest_service.get_leafy_harvest_event(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, harvest_event_id=harvest_event_id
    )
