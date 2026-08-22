import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.auth import TenantContext
from app.core.permissions import Permission, require_permission
from app.schemas.seedling_disposition import (
    CorrectSeedlingDispositionCreate,
    RecordSeedlingDispositionCreate,
    SeedlingBiologicalTrayRead,
    SeedlingDispositionCorrectResult,
    SeedlingDispositionHistoryRead,
    SeedlingDispositionReasonRead,
    SeedlingDispositionRecordResult,
)
from app.schemas.seedling_entry import (
    AvailableSeedlingTableRead,
    SeedlingCandidateTrayRead,
    SeedlingEntryCreate,
    SeedlingEntryRead,
)
from app.services import seedling_disposition_service, seedling_entry_service
from app.services.errors import (
    BatchCarrierAssignmentNotFoundError,
    CropBatchClosedError,
    FarmNotFoundError,
    InvalidSeedlingDispositionEffectiveTimeError,
    InvalidSeedlingDispositionReasonError,
    InvalidSeedlingEntryEffectiveTimeError,
    LocationNotFoundError,
    NoCompletedGerminationHandoffError,
    NoSeedlingEntryError,
    SeedlingDispositionAlreadyCorrectedError,
    SeedlingDispositionAssignmentReleasedError,
    SeedlingDispositionBalanceError,
    SeedlingDispositionCarrierReusedError,
    SeedlingDispositionCommandReusedWithDifferentPayloadError,
    SeedlingDispositionCorrectionStageContextUnavailableError,
    SeedlingDispositionCorrectionStageMismatchError,
    SeedlingDispositionEventNotFoundError,
    SeedlingDispositionNotReductionError,
    SeedlingDispositionValidationError,
    SeedlingEntryAlreadyExistsError,
    SeedlingEntryCommandReusedWithDifferentPayloadError,
    SeedlingEntryPhysicalChronologyError,
    SeedlingEntryValidationError,
    SeedlingTableInvalidError,
)
from app.services.errors import (
    AssetPositionNotFoundError,
    CarrierNotFoundError,
    InactiveOccupantError,
    InactiveTargetError,
    IncompatibleOccupantTargetError,
    MovementCommandReusedWithDifferentPayloadError,
    NoOpMovementError,
    OccupantAlreadyActiveError,
    TargetNotOccupiableError,
    TargetOccupiedError,
)

router = APIRouter(tags=["seedling"])

_DISPOSITION_NOT_FOUND = (FarmNotFoundError, BatchCarrierAssignmentNotFoundError, NoSeedlingEntryError, SeedlingDispositionEventNotFoundError)
_DISPOSITION_INVALID = (
    SeedlingDispositionValidationError,
    InvalidSeedlingDispositionReasonError,
    InvalidSeedlingDispositionEffectiveTimeError,
    SeedlingDispositionNotReductionError,
)
_DISPOSITION_CONFLICT = (
    SeedlingDispositionCommandReusedWithDifferentPayloadError,
    SeedlingDispositionAssignmentReleasedError,
    SeedlingDispositionAlreadyCorrectedError,
    SeedlingDispositionBalanceError,
    CropBatchClosedError,
    SeedlingDispositionCorrectionStageContextUnavailableError,
    SeedlingDispositionCorrectionStageMismatchError,
    SeedlingDispositionCarrierReusedError,
)

_NOT_FOUND = (
    FarmNotFoundError,
    BatchCarrierAssignmentNotFoundError,
    LocationNotFoundError,
    CarrierNotFoundError,
    AssetPositionNotFoundError,
)
_INVALID = (
    SeedlingTableInvalidError,
    SeedlingEntryValidationError,
    NoCompletedGerminationHandoffError,
    InvalidSeedlingEntryEffectiveTimeError,
    SeedlingEntryPhysicalChronologyError,
    TargetNotOccupiableError,
    IncompatibleOccupantTargetError,
)
_CONFLICT = (
    SeedlingEntryAlreadyExistsError,
    SeedlingEntryCommandReusedWithDifferentPayloadError,
    InactiveOccupantError,
    InactiveTargetError,
    TargetOccupiedError,
    OccupantAlreadyActiveError,
    NoOpMovementError,
    MovementCommandReusedWithDifferentPayloadError,
)


@router.post(
    "/farms/{farm_id}/nursery/seedling/entries",
    response_model=SeedlingEntryRead,
    status_code=status.HTTP_201_CREATED,
)
def record_seedling_entry(
    farm_id: uuid.UUID,
    payload: SeedlingEntryCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.MOVEMENT_MANAGE)),
) -> SeedlingEntryRead:
    try:
        entry = seedling_entry_service.record_seedling_entry(
            db,
            tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id,
            client_command_id=payload.client_command_id,
            batch_carrier_assignment_id=payload.batch_carrier_assignment_id,
            destination_seedling_table_id=payload.destination_seedling_table_id,
            effective_time=payload.effective_time, reason=payload.reason,
        )
    except _NOT_FOUND as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except _CONFLICT as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except _INVALID as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return seedling_entry_service.describe_seedling_entry(db, entry=entry)


@router.get(
    "/farms/{farm_id}/nursery/seedling/tables/available", response_model=list[AvailableSeedlingTableRead]
)
def list_available_seedling_tables(
    farm_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.LOCATION_READ)),
) -> list[AvailableSeedlingTableRead]:
    try:
        return seedling_entry_service.list_available_seedling_tables(db, tenant_id=ctx.tenant_id, farm_id=farm_id)
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get("/farms/{farm_id}/nursery/seedling/trays", response_model=list[SeedlingCandidateTrayRead])
def list_seedling_candidate_trays(
    farm_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.SOWING_READ)),
) -> list[SeedlingCandidateTrayRead]:
    try:
        return seedling_entry_service.list_seedling_candidate_trays(db, tenant_id=ctx.tenant_id, farm_id=farm_id)
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


# --- NURSERY-OPS-003B --------------------------------------------------------------
# Seedling Biological Dispositions -- quantity-reducing facts recorded AFTER
# SeedlingEntry. Read permission reuses SOWING_READ (matching the Tray-list
# precedent above); mutation requires the dedicated BIOLOGICAL_DISPOSITION_MANAGE
# permission (distinct from OBSERVATION_ENTRY_MANAGE -- section 0.6).


@router.post(
    "/farms/{farm_id}/nursery/seedling/dispositions",
    response_model=SeedlingDispositionRecordResult,
    status_code=status.HTTP_201_CREATED,
)
def record_seedling_disposition(
    farm_id: uuid.UUID,
    payload: RecordSeedlingDispositionCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.BIOLOGICAL_DISPOSITION_MANAGE)),
) -> SeedlingDispositionRecordResult:
    try:
        command = seedling_disposition_service.record_disposition(
            db,
            tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id,
            client_command_id=payload.client_command_id,
            batch_carrier_assignment_id=payload.batch_carrier_assignment_id,
            quantity=payload.quantity, reason_code=payload.reason_code,
            effective_time=payload.effective_time, note=payload.note,
        )
    except _DISPOSITION_NOT_FOUND as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except _DISPOSITION_CONFLICT as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except _DISPOSITION_INVALID as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return seedling_disposition_service.describe_record_result(db, command=command)


@router.post(
    "/farms/{farm_id}/nursery/seedling/dispositions/{event_id}/correct",
    response_model=SeedlingDispositionCorrectResult,
    status_code=status.HTTP_201_CREATED,
)
def correct_seedling_disposition(
    farm_id: uuid.UUID,
    event_id: uuid.UUID,
    payload: CorrectSeedlingDispositionCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.BIOLOGICAL_DISPOSITION_MANAGE)),
) -> SeedlingDispositionCorrectResult:
    corrected = (
        {
            "quantity": payload.corrected.quantity, "reason_code": payload.corrected.reason_code,
            "effective_time": payload.corrected.effective_time, "note": payload.corrected.note,
        }
        if payload.corrected is not None
        else None
    )
    try:
        command = seedling_disposition_service.correct_disposition(
            db,
            tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id,
            client_command_id=payload.client_command_id, target_event_id=event_id, corrected=corrected,
        )
    except _DISPOSITION_NOT_FOUND as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except _DISPOSITION_CONFLICT as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except _DISPOSITION_INVALID as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return seedling_disposition_service.describe_correct_result(db, command=command)


@router.get(
    "/farms/{farm_id}/nursery/seedling/disposition-reasons", response_model=list[SeedlingDispositionReasonRead]
)
def list_seedling_disposition_reasons(
    farm_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.SOWING_READ)),
) -> list[SeedlingDispositionReasonRead]:
    return seedling_disposition_service.list_seedling_disposition_reasons(db)


@router.get(
    "/farms/{farm_id}/nursery/seedling/biological-trays", response_model=list[SeedlingBiologicalTrayRead]
)
def list_seedling_biological_trays(
    farm_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.SOWING_READ)),
) -> list[SeedlingBiologicalTrayRead]:
    try:
        return seedling_disposition_service.list_seedling_biological_trays(db, tenant_id=ctx.tenant_id, farm_id=farm_id)
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get(
    "/farms/{farm_id}/nursery/seedling/dispositions", response_model=SeedlingDispositionHistoryRead
)
def get_seedling_disposition_history(
    farm_id: uuid.UUID,
    seedling_entry_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.SOWING_READ)),
) -> SeedlingDispositionHistoryRead:
    try:
        return seedling_disposition_service.get_seedling_disposition_history(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, seedling_entry_id=seedling_entry_id
        )
    except NoSeedlingEntryError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
