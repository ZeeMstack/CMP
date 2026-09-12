import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import TenantContext
from app.core.db import get_db
from app.core.permissions import Permission, require_permission
from app.schemas.inventory_quality import (
    InventoryItemUsableExistenceRead,
    InventoryLotUsableExistenceRead,
    QualityDispositionCorrectionCreate,
    QualityDispositionCorrectionRead,
    QualityDispositionCreate,
    QualityDispositionEventRead,
    QualityPartialCorrectionCreate,
    QualityPartialCorrectionRead,
    QualityPartialDispositionCreate,
    QualityPartialDispositionRead,
    QualityWorkQueueRowRead,
)
from app.services import inventory_quality_service
from app.services.errors import (
    IneligibleStorageBinError,
    InvalidQualityDispositionTransitionError,
    InvalidQualityEffectiveTimeError,
    InventoryQuantityCohortNotFoundError,
    InventoryQuantityCohortSplitAllocationExceedsBalanceError,
    QualityCorrectionCommandReusedWithDifferentPayloadError,
    QualityCorrectionTargetNotCurrentError,
    QualityDispositionCommandReusedWithDifferentPayloadError,
    QualityDispositionEventNotFoundError,
    QualityDispositionNoCurrentHumanDecisionError,
    QualityPartialCorrectionCommandReusedWithDifferentPayloadError,
    QualityPartialDispositionCommandReusedWithDifferentPayloadError,
    QualitySegregationOfDutiesError,
    StorageBinNotFoundError,
)

router = APIRouter(tags=["inventory-quality"])

# PILOT-BLOCKER-005 F06/F05: a stable, machine-readable discriminator for
# the two "your captured correction target is no longer actionable" 409s --
# mirrors the existing `HARVEST_CORRECTION_STALE` convention
# (app/api/vines_harvest.py). Every OTHER Quality 409 (segregation-of-duty,
# command-reused-with-different-payload, over-allocation) carries no `code`
# and must never be treated as a stale-target conflict by the frontend --
# those are definitive domain rejections of a different kind, not "the
# state moved since you opened this action".
_STALE_TARGET_CODES: dict[type[Exception], str] = {
    QualityCorrectionTargetNotCurrentError: "QUALITY_CORRECTION_TARGET_STALE",
    QualityDispositionNoCurrentHumanDecisionError: "QUALITY_CORRECTION_NO_CURRENT_DECISION",
}


def _stale_target_conflict_detail(exc: Exception) -> dict[str, str]:
    return {"message": str(exc), "code": _STALE_TARGET_CODES[type(exc)]}


@router.post(
    "/quality-dispositions", response_model=QualityDispositionEventRead, status_code=status.HTTP_201_CREATED
)
def record_quality_disposition(
    payload: QualityDispositionCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_QUALITY_MANAGE)),
) -> QualityDispositionEventRead:
    try:
        event = inventory_quality_service.record_quality_disposition(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, client_command_id=payload.client_command_id,
            cohort_id=payload.inventory_quantity_cohort_id, disposition=payload.disposition,
            effective_time=payload.effective_time, reason=payload.reason,
        )
    except InventoryQuantityCohortNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cohort not found") from exc
    except QualityDispositionCommandReusedWithDifferentPayloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="client_command_id already used with a different payload",
        ) from exc
    except InvalidQualityDispositionTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except InvalidQualityEffectiveTimeError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except QualitySegregationOfDutiesError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return QualityDispositionEventRead.model_validate(event)


@router.post(
    "/quality-disposition-corrections", response_model=QualityDispositionCorrectionRead,
    status_code=status.HTTP_201_CREATED,
)
def correct_quality_disposition(
    payload: QualityDispositionCorrectionCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_QUALITY_MANAGE)),
) -> QualityDispositionCorrectionRead:
    try:
        reversal, replacement = inventory_quality_service.correct_quality_disposition(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, client_command_id=payload.client_command_id,
            cohort_id=payload.inventory_quantity_cohort_id, target_event_id=payload.target_event_id,
            reason=payload.reason, replacement_disposition=payload.replacement_disposition,
            effective_time=payload.effective_time,
        )
    except (InventoryQuantityCohortNotFoundError, QualityDispositionEventNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except QualityCorrectionCommandReusedWithDifferentPayloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="client_command_id already used with a different payload",
        ) from exc
    except (QualityDispositionNoCurrentHumanDecisionError, QualityCorrectionTargetNotCurrentError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=_stale_target_conflict_detail(exc)
        ) from exc
    except InvalidQualityDispositionTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except InvalidQualityEffectiveTimeError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except QualitySegregationOfDutiesError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return QualityDispositionCorrectionRead(
        reversal=QualityDispositionEventRead.model_validate(reversal),
        replacement=QualityDispositionEventRead.model_validate(replacement) if replacement is not None else None,
    )


@router.post(
    "/quality-partial-dispositions", response_model=QualityPartialDispositionRead,
    status_code=status.HTTP_201_CREATED,
)
def apply_quality_disposition_to_partial_quantity(
    payload: QualityPartialDispositionCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_QUALITY_MANAGE)),
) -> QualityPartialDispositionRead:
    try:
        child = inventory_quality_service.apply_quality_disposition_to_partial_quantity(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, client_command_id=payload.client_command_id,
            source_cohort_id=payload.inventory_quantity_cohort_id, quantity=payload.quantity,
            disposition=payload.disposition, effective_time=payload.effective_time, reason=payload.reason,
            custody_location_id=payload.custody_location_id,
        )
    except InventoryQuantityCohortNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cohort not found") from exc
    except StorageBinNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store bin not found") from exc
    except QualityPartialDispositionCommandReusedWithDifferentPayloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="client_command_id already used with a different payload",
        ) from exc
    except InvalidQualityDispositionTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except InvalidQualityEffectiveTimeError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except IneligibleStorageBinError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except QualitySegregationOfDutiesError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InventoryQuantityCohortSplitAllocationExceedsBalanceError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return QualityPartialDispositionRead(
        child_cohort_id=child.id, source_cohort_id=payload.inventory_quantity_cohort_id,
        quantity=payload.quantity, disposition=payload.disposition,
        custody_location_id=payload.custody_location_id,
    )


@router.post(
    "/quality-partial-corrections", response_model=QualityPartialCorrectionRead,
    status_code=status.HTTP_201_CREATED,
)
def correct_quality_disposition_for_partial_quantity(
    payload: QualityPartialCorrectionCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_QUALITY_MANAGE)),
) -> QualityPartialCorrectionRead:
    try:
        child = inventory_quality_service.correct_quality_disposition_for_partial_quantity(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, client_command_id=payload.client_command_id,
            source_cohort_id=payload.inventory_quantity_cohort_id, target_event_id=payload.target_event_id,
            quantity=payload.quantity, corrected_disposition=payload.corrected_disposition,
            reason=payload.reason, effective_time=payload.effective_time,
            custody_location_id=payload.custody_location_id,
        )
    except (InventoryQuantityCohortNotFoundError, QualityDispositionEventNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except StorageBinNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store bin not found") from exc
    except QualityPartialCorrectionCommandReusedWithDifferentPayloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="client_command_id already used with a different payload",
        ) from exc
    except (QualityDispositionNoCurrentHumanDecisionError, QualityCorrectionTargetNotCurrentError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=_stale_target_conflict_detail(exc)
        ) from exc
    except InvalidQualityDispositionTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except InvalidQualityEffectiveTimeError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except IneligibleStorageBinError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except QualitySegregationOfDutiesError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InventoryQuantityCohortSplitAllocationExceedsBalanceError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return QualityPartialCorrectionRead(
        child_cohort_id=child.id, source_cohort_id=payload.inventory_quantity_cohort_id,
        target_event_id=payload.target_event_id, quantity=payload.quantity,
        corrected_disposition=payload.corrected_disposition,
        custody_location_id=payload.custody_location_id,
    )


@router.get("/quality-work-queue", response_model=list[QualityWorkQueueRowRead])
def get_quality_work_queue(
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_READ)),
) -> list[QualityWorkQueueRowRead]:
    rows = inventory_quality_service.list_quality_work_queue(db, tenant_id=ctx.tenant_id)
    return [QualityWorkQueueRowRead(**row) for row in rows]


@router.get("/inventory-items/{item_id}/usable-existence", response_model=InventoryItemUsableExistenceRead)
def get_item_usable_existence(
    item_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_READ)),
) -> InventoryItemUsableExistenceRead:
    usable = inventory_quality_service.get_item_usable_existence(db, tenant_id=ctx.tenant_id, inventory_item_id=item_id)
    return InventoryItemUsableExistenceRead(inventory_item_id=item_id, usable_quantity=usable)


@router.get("/inventory-lots/{lot_id}/usable-existence", response_model=InventoryLotUsableExistenceRead)
def get_lot_usable_existence(
    lot_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_READ)),
) -> InventoryLotUsableExistenceRead:
    usable = inventory_quality_service.get_lot_usable_existence(db, tenant_id=ctx.tenant_id, inventory_lot_id=lot_id)
    return InventoryLotUsableExistenceRead(inventory_lot_id=lot_id, usable_quantity=usable)
