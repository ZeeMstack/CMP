import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.auth import TenantContext
from app.core.db import get_db
from app.core.permissions import Permission, require_permission
from app.models.farm_work_item import FarmWorkItem
from app.schemas.farm_work_item import (
    FarmWorkItemBlockIn,
    FarmWorkItemCancelIn,
    FarmWorkItemCompleteIn,
    FarmWorkItemCreate,
    FarmWorkItemHistoryEntryRead,
    FarmWorkItemLinkResultIn,
    FarmWorkItemRead,
    FarmWorkItemStartIn,
    FarmWorkItemUnblockIn,
    FarmWorkItemUpdateIn,
)
from app.services import farm_work_item_service
from app.services.errors import (
    AssetNotFoundError,
    CarrierNotFoundError,
    CropBatchNotFoundError,
    FarmNotFoundError,
    FarmWorkItemCommandReusedWithDifferentPayloadError,
    FarmWorkItemInvalidTransitionError,
    FarmWorkItemManualCompletionNotAllowedError,
    FarmWorkItemNotAssignableError,
    FarmWorkItemNotFoundError,
    FarmWorkItemResultConflictError,
    FarmWorkItemWrongCompletionModeError,
    LocationNotFoundError,
    UnitOfMeasureNotFoundError,
    UserNotFoundError,
)

router = APIRouter(tags=["farm-work-items"])

_NOT_FOUND_ERRORS = (
    FarmNotFoundError, CropBatchNotFoundError, LocationNotFoundError, CarrierNotFoundError,
    AssetNotFoundError, UnitOfMeasureNotFoundError, UserNotFoundError, FarmWorkItemNotFoundError,
)


def _to_read(db: Session, *, tenant_id: uuid.UUID, item: FarmWorkItem) -> FarmWorkItemRead:
    context = farm_work_item_service.resolve_read_context(db, tenant_id=tenant_id, items=[item])
    return FarmWorkItemRead(
        id=item.id, tenant_id=item.tenant_id, farm_id=item.farm_id, code=item.code, work_type=item.work_type,
        category=item.category, title=item.title, instructions=item.instructions, status=item.status,
        priority=item.priority, due_at=item.due_at, assigned_to_user_id=item.assigned_to_user_id,
        crop_batch=context["crop_batches"].get(item.crop_batch_id),
        location=context["locations"].get(item.location_id),
        carrier=context["carriers"].get(item.carrier_id),
        asset=context["assets"].get(item.asset_id),
        quantity=item.quantity,
        quantity_uom=context["uoms"].get(item.quantity_uom_id),
        completion_mode=item.completion_mode, result_entity_type=item.result_entity_type,
        result_entity_id=item.result_entity_id, result_recorded_at=item.result_recorded_at,
        completed_by_user_id=item.completed_by_user_id, completed_at=item.completed_at,
        completion_note=item.completion_note, blocked_reason=item.blocked_reason, blocked_at=item.blocked_at,
        blocked_by_user_id=item.blocked_by_user_id, cancelled_at=item.cancelled_at,
        cancelled_by_user_id=item.cancelled_by_user_id, cancel_reason=item.cancel_reason,
        created_by_user_id=item.created_by_user_id, created_at=item.created_at, updated_at=item.updated_at,
    )


def _to_read_many(db: Session, *, tenant_id: uuid.UUID, items: list[FarmWorkItem]) -> list[FarmWorkItemRead]:
    context = farm_work_item_service.resolve_read_context(db, tenant_id=tenant_id, items=items)
    return [
        FarmWorkItemRead(
            id=i.id, tenant_id=i.tenant_id, farm_id=i.farm_id, code=i.code, work_type=i.work_type,
            category=i.category, title=i.title, instructions=i.instructions, status=i.status,
            priority=i.priority, due_at=i.due_at, assigned_to_user_id=i.assigned_to_user_id,
            crop_batch=context["crop_batches"].get(i.crop_batch_id),
            location=context["locations"].get(i.location_id),
            carrier=context["carriers"].get(i.carrier_id),
            asset=context["assets"].get(i.asset_id),
            quantity=i.quantity,
            quantity_uom=context["uoms"].get(i.quantity_uom_id),
            completion_mode=i.completion_mode, result_entity_type=i.result_entity_type,
            result_entity_id=i.result_entity_id, result_recorded_at=i.result_recorded_at,
            completed_by_user_id=i.completed_by_user_id, completed_at=i.completed_at,
            completion_note=i.completion_note, blocked_reason=i.blocked_reason, blocked_at=i.blocked_at,
            blocked_by_user_id=i.blocked_by_user_id, cancelled_at=i.cancelled_at,
            cancelled_by_user_id=i.cancelled_by_user_id, cancel_reason=i.cancel_reason,
            created_by_user_id=i.created_by_user_id, created_at=i.created_at, updated_at=i.updated_at,
        )
        for i in items
    ]


@router.post(
    "/farms/{farm_id}/work-items", response_model=FarmWorkItemRead, status_code=status.HTTP_201_CREATED
)
def create_work_item(
    farm_id: uuid.UUID,
    payload: FarmWorkItemCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.FARM_WORK_ITEM_MANAGE)),
) -> FarmWorkItemRead:
    try:
        item = farm_work_item_service.create_work_item(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id,
            client_command_id=payload.client_command_id, work_type=payload.work_type, category=payload.category,
            title=payload.title, instructions=payload.instructions, priority=payload.priority,
            due_at=payload.due_at, assigned_to_user_id=payload.assigned_to_user_id,
            crop_batch_id=payload.crop_batch_id, location_id=payload.location_id, carrier_id=payload.carrier_id,
            asset_id=payload.asset_id, quantity=payload.quantity, quantity_uom_id=payload.quantity_uom_id,
            completion_mode=payload.completion_mode,
        )
    except _NOT_FOUND_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except FarmWorkItemCommandReusedWithDifferentPayloadError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_read(db, tenant_id=ctx.tenant_id, item=item)


@router.get("/farms/{farm_id}/work-items", response_model=list[FarmWorkItemRead])
def list_work_items(
    farm_id: uuid.UUID,
    status_filter: list[str] | None = Query(default=None, alias="status"),
    assigned_to_me: bool = Query(default=False),
    include_completed: bool = Query(default=False),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.FARM_WORK_ITEM_READ)),
) -> list[FarmWorkItemRead]:
    try:
        items = farm_work_item_service.list_work_items(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, statuses=status_filter,
            assigned_to_user_id=ctx.user_id if assigned_to_me else None, include_completed=include_completed,
        )
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return _to_read_many(db, tenant_id=ctx.tenant_id, items=items)


@router.get("/farms/{farm_id}/work-items/{work_item_id}", response_model=FarmWorkItemRead)
def get_work_item(
    farm_id: uuid.UUID,
    work_item_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.FARM_WORK_ITEM_READ)),
) -> FarmWorkItemRead:
    try:
        item = farm_work_item_service.get_work_item(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, work_item_id=work_item_id
        )
    except FarmWorkItemNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return _to_read(db, tenant_id=ctx.tenant_id, item=item)


@router.get(
    "/farms/{farm_id}/work-items/{work_item_id}/history", response_model=list[FarmWorkItemHistoryEntryRead]
)
def get_work_item_history(
    farm_id: uuid.UUID,
    work_item_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.FARM_WORK_ITEM_READ)),
) -> list[FarmWorkItemHistoryEntryRead]:
    try:
        events = farm_work_item_service.list_history(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, work_item_id=work_item_id
        )
    except FarmWorkItemNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return [
        FarmWorkItemHistoryEntryRead(
            id=e.id, action=e.action, actor_user_id=e.actor_user_id, effective_time=e.effective_time,
            event_data=e.event_data or {},
        )
        for e in events
    ]


@router.post("/farms/{farm_id}/work-items/{work_item_id}/update", response_model=FarmWorkItemRead)
def update_work_item(
    farm_id: uuid.UUID,
    work_item_id: uuid.UUID,
    payload: FarmWorkItemUpdateIn,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.FARM_WORK_ITEM_MANAGE)),
) -> FarmWorkItemRead:
    try:
        item = farm_work_item_service.update_work_item(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, work_item_id=work_item_id,
            client_command_id=payload.client_command_id, assigned_to_user_id=payload.assigned_to_user_id,
            priority=payload.priority, due_at=payload.due_at,
        )
    except _NOT_FOUND_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except (
        FarmWorkItemCommandReusedWithDifferentPayloadError, FarmWorkItemInvalidTransitionError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_read(db, tenant_id=ctx.tenant_id, item=item)


@router.post("/farms/{farm_id}/work-items/{work_item_id}/start", response_model=FarmWorkItemRead)
def start_work_item(
    farm_id: uuid.UUID,
    work_item_id: uuid.UUID,
    payload: FarmWorkItemStartIn,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.FARM_WORK_ITEM_EXECUTE)),
) -> FarmWorkItemRead:
    try:
        item = farm_work_item_service.start_work_item(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, work_item_id=work_item_id,
            client_command_id=payload.client_command_id,
        )
    except FarmWorkItemNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except (
        FarmWorkItemCommandReusedWithDifferentPayloadError, FarmWorkItemInvalidTransitionError,
        FarmWorkItemNotAssignableError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_read(db, tenant_id=ctx.tenant_id, item=item)


@router.post("/farms/{farm_id}/work-items/{work_item_id}/block", response_model=FarmWorkItemRead)
def block_work_item(
    farm_id: uuid.UUID,
    work_item_id: uuid.UUID,
    payload: FarmWorkItemBlockIn,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.FARM_WORK_ITEM_EXECUTE)),
) -> FarmWorkItemRead:
    try:
        item = farm_work_item_service.block_work_item(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, work_item_id=work_item_id,
            client_command_id=payload.client_command_id, reason=payload.reason,
        )
    except FarmWorkItemNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except (
        FarmWorkItemCommandReusedWithDifferentPayloadError, FarmWorkItemInvalidTransitionError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_read(db, tenant_id=ctx.tenant_id, item=item)


@router.post("/farms/{farm_id}/work-items/{work_item_id}/unblock", response_model=FarmWorkItemRead)
def unblock_work_item(
    farm_id: uuid.UUID,
    work_item_id: uuid.UUID,
    payload: FarmWorkItemUnblockIn,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.FARM_WORK_ITEM_EXECUTE)),
) -> FarmWorkItemRead:
    try:
        item = farm_work_item_service.unblock_work_item(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, work_item_id=work_item_id,
            client_command_id=payload.client_command_id,
        )
    except FarmWorkItemNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except (
        FarmWorkItemCommandReusedWithDifferentPayloadError, FarmWorkItemInvalidTransitionError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_read(db, tenant_id=ctx.tenant_id, item=item)


@router.post("/farms/{farm_id}/work-items/{work_item_id}/complete", response_model=FarmWorkItemRead)
def complete_work_item(
    farm_id: uuid.UUID,
    work_item_id: uuid.UUID,
    payload: FarmWorkItemCompleteIn,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.FARM_WORK_ITEM_EXECUTE)),
) -> FarmWorkItemRead:
    try:
        item = farm_work_item_service.complete_work_item(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, work_item_id=work_item_id,
            client_command_id=payload.client_command_id, completion_note=payload.completion_note,
        )
    except FarmWorkItemNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except (
        FarmWorkItemCommandReusedWithDifferentPayloadError, FarmWorkItemInvalidTransitionError,
        FarmWorkItemManualCompletionNotAllowedError, FarmWorkItemNotAssignableError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_read(db, tenant_id=ctx.tenant_id, item=item)


@router.post("/farms/{farm_id}/work-items/{work_item_id}/cancel", response_model=FarmWorkItemRead)
def cancel_work_item(
    farm_id: uuid.UUID,
    work_item_id: uuid.UUID,
    payload: FarmWorkItemCancelIn,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.FARM_WORK_ITEM_MANAGE)),
) -> FarmWorkItemRead:
    try:
        item = farm_work_item_service.cancel_work_item(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, work_item_id=work_item_id,
            client_command_id=payload.client_command_id, reason=payload.reason,
        )
    except FarmWorkItemNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except (
        FarmWorkItemCommandReusedWithDifferentPayloadError, FarmWorkItemInvalidTransitionError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_read(db, tenant_id=ctx.tenant_id, item=item)


@router.post("/farms/{farm_id}/work-items/{work_item_id}/link-result", response_model=FarmWorkItemRead)
def link_work_item_result(
    farm_id: uuid.UUID,
    work_item_id: uuid.UUID,
    payload: FarmWorkItemLinkResultIn,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.FARM_WORK_ITEM_EXECUTE)),
) -> FarmWorkItemRead:
    """Reconciliation endpoint: links an OPERATIONAL_RECORD Work Item to an
    already-committed authoritative record. The same underlying service
    function is called automatically by Harvest/Observation on success
    (best-effort, never blocking); this endpoint exists so a UI can retry a
    failed automatic link without repeating the operation itself."""
    try:
        item = farm_work_item_service.link_operational_result(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, work_item_id=work_item_id,
            client_command_id=payload.client_command_id, result_entity_type=payload.result_entity_type,
            result_entity_id=payload.result_entity_id, effective_time=payload.effective_time,
        )
    except FarmWorkItemNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except (
        FarmWorkItemCommandReusedWithDifferentPayloadError, FarmWorkItemInvalidTransitionError,
        FarmWorkItemWrongCompletionModeError, FarmWorkItemResultConflictError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_read(db, tenant_id=ctx.tenant_id, item=item)
