import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import TenantContext
from app.core.db import get_db
from app.core.permissions import Permission, require_permission
from app.schemas.inventory_material_event import (
    InventoryConsumptionCreate,
    InventoryMaterialEventRead,
    InventoryReturnCreate,
    InventoryScrapCreate,
    IssueLineReconciliationRead,
    OutstandingIssuedMaterialRowRead,
)
from app.services import inventory_material_event_service
from app.services.errors import (
    InactiveStorageBinError,
    InsufficientIssueLineOutstandingError,
    InsufficientNotPutAwayQuantityError,
    InsufficientStorageBinBalanceError,
    InventoryConsumptionSourceNotUsableError,
    InventoryIssueLineNotFoundError,
    InventoryMaterialEventCommandReusedWithDifferentPayloadError,
    InventoryMaterialEventValidationError,
    InventoryQuantityCohortNotFoundError,
    StorageBinNotFoundError,
)

router = APIRouter(tags=["inventory-material-events"])


def _build_event_read(event) -> InventoryMaterialEventRead:
    return InventoryMaterialEventRead(
        id=event.id, event_kind=event.event_kind, source_kind=event.source_kind, issue_line_id=event.issue_line_id,
        inventory_quantity_cohort_id=event.inventory_quantity_cohort_id,
        source_location_id=event.source_location_id, destination_location_id=event.destination_location_id,
        quantity_base=event.quantity_base, reason=event.reason, effective_time=event.effective_time,
        recorded_time=event.recorded_time, actor_user_id=event.actor_user_id,
    )


@router.post(
    "/inventory-consumptions", response_model=InventoryMaterialEventRead, status_code=status.HTTP_201_CREATED
)
def record_consumption(
    payload: InventoryConsumptionCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_CONSUMPTION_MANAGE)),
) -> InventoryMaterialEventRead:
    try:
        event = inventory_material_event_service.record_consumption(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, client_command_id=payload.client_command_id,
            issue_line_id=payload.issue_line_id, quantity=payload.quantity, effective_time=payload.effective_time,
        )
    except InventoryIssueLineNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Issue line not found") from exc
    except InventoryMaterialEventCommandReusedWithDifferentPayloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="client_command_id already used with a different payload"
        ) from exc
    except InventoryMaterialEventValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except InventoryConsumptionSourceNotUsableError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Source is not currently usable") from exc
    except InsufficientIssueLineOutstandingError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _build_event_read(event)


@router.post("/inventory-returns", response_model=InventoryMaterialEventRead, status_code=status.HTTP_201_CREATED)
def record_return(
    payload: InventoryReturnCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_RETURN_MANAGE)),
) -> InventoryMaterialEventRead:
    try:
        event = inventory_material_event_service.record_return(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, client_command_id=payload.client_command_id,
            issue_line_id=payload.issue_line_id, destination_location_id=payload.destination_location_id,
            quantity=payload.quantity, effective_time=payload.effective_time,
        )
    except InventoryIssueLineNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Issue line not found") from exc
    except StorageBinNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store bin not found") from exc
    except InventoryMaterialEventCommandReusedWithDifferentPayloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="client_command_id already used with a different payload"
        ) from exc
    except InventoryMaterialEventValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except InactiveStorageBinError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InsufficientIssueLineOutstandingError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _build_event_read(event)


@router.post("/inventory-scraps", response_model=InventoryMaterialEventRead, status_code=status.HTTP_201_CREATED)
def record_scrap(
    payload: InventoryScrapCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_SCRAP_MANAGE)),
) -> InventoryMaterialEventRead:
    try:
        event = inventory_material_event_service.record_scrap(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, client_command_id=payload.client_command_id,
            source_kind=payload.source_kind, quantity=payload.quantity, reason=payload.reason,
            effective_time=payload.effective_time, issue_line_id=payload.issue_line_id,
            inventory_quantity_cohort_id=payload.inventory_quantity_cohort_id,
            source_location_id=payload.source_location_id,
        )
    except InventoryIssueLineNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Issue line not found") from exc
    except InventoryQuantityCohortNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cohort not found") from exc
    except StorageBinNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store bin not found") from exc
    except InventoryMaterialEventCommandReusedWithDifferentPayloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="client_command_id already used with a different payload"
        ) from exc
    except InventoryMaterialEventValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except (
        InsufficientIssueLineOutstandingError, InsufficientStorageBinBalanceError,
        InsufficientNotPutAwayQuantityError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _build_event_read(event)


@router.get(
    "/inventory-issue-lines/{issue_line_id}/reconciliation", response_model=IssueLineReconciliationRead
)
def get_issue_line_reconciliation(
    issue_line_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_READ)),
) -> IssueLineReconciliationRead:
    try:
        summary = inventory_material_event_service.get_issue_line_reconciliation(
            db, tenant_id=ctx.tenant_id, issue_line_id=issue_line_id
        )
    except InventoryIssueLineNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Issue line not found") from exc
    return IssueLineReconciliationRead(**summary)


@router.get(
    "/farms/{farm_id}/outstanding-issued-material", response_model=list[OutstandingIssuedMaterialRowRead]
)
def list_outstanding_issued_material(
    farm_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_READ)),
) -> list[OutstandingIssuedMaterialRowRead]:
    rows = inventory_material_event_service.list_outstanding_issued_material(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id
    )
    return [OutstandingIssuedMaterialRowRead(**row) for row in rows]
