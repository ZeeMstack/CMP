import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import TenantContext
from app.core.db import get_db
from app.core.permissions import Permission, require_permission
from app.models.inventory_issue import InventoryIssue
from app.models.inventory_quantity_cohort import InventoryQuantityCohort
from app.models.inventory_storage_movement import InventoryStorageMovement
from app.schemas.inventory_issue import (
    InventoryIssueCreate,
    InventoryIssueLineRead,
    InventoryIssueRead,
    IssuableSourceRead,
    ItemFarmAvailabilityRead,
)
from app.services import inventory_availability_service, inventory_issue_service
from app.services.errors import (
    FarmNotFoundError,
    InactiveStorageBinError,
    InsufficientAvailableToIssueError,
    InsufficientReservationBalanceError,
    InsufficientStorageBinBalanceError,
    InventoryIssueCommandReusedWithDifferentPayloadError,
    InventoryIssueLineValidationError,
    InventoryIssueNotFoundError,
    InventoryIssueSourceNotUsableError,
    InventoryQuantityCohortNotFoundError,
    InventoryReservationLineNotFoundError,
    InventoryReservationNotFoundError,
    ReservationLineItemMismatchError,
    StorageBinNotFoundError,
    TooManyInventoryIssueLinesError,
)
from app.services.inventory_issue_service import IssueLineInput

router = APIRouter(tags=["inventory-issues"])


def _build_issue_read(db: Session, *, tenant_id: uuid.UUID, issue: InventoryIssue) -> InventoryIssueRead:
    lines = inventory_issue_service.list_issue_lines(db, tenant_id=tenant_id, issue_id=issue.id)
    cohort_ids = {line.inventory_quantity_cohort_id for line in lines}
    item_by_cohort = dict(
        db.execute(
            select(InventoryQuantityCohort.id, InventoryQuantityCohort.inventory_item_id).where(
                InventoryQuantityCohort.id.in_(cohort_ids)
            )
        ).all()
    ) if cohort_ids else {}
    return InventoryIssueRead(
        id=issue.id, tenant_id=issue.tenant_id, farm_id=issue.farm_id, code=issue.code, purpose=issue.purpose,
        issued_by_user_id=issue.issued_by_user_id, effective_time=issue.effective_time,
        recorded_time=issue.recorded_time, reservation_id=issue.reservation_id,
        lines=[
            InventoryIssueLineRead(
                id=line.id, inventory_item_id=item_by_cohort.get(line.inventory_quantity_cohort_id),
                inventory_quantity_cohort_id=line.inventory_quantity_cohort_id,
                source_location_id=line.source_location_id, moved_quantity_base=line.moved_quantity_base,
                reservation_line_id=line.reservation_line_id,
            )
            for line in lines
        ],
    )


@router.post(
    "/farms/{farm_id}/inventory-issues", response_model=InventoryIssueRead, status_code=status.HTTP_201_CREATED
)
def record_issue(
    farm_id: uuid.UUID,
    payload: InventoryIssueCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_ISSUE_MANAGE)),
) -> InventoryIssueRead:
    try:
        issue = inventory_issue_service.record_issue(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id,
            client_command_id=payload.client_command_id, purpose=payload.purpose,
            effective_time=payload.effective_time, reservation_id=payload.reservation_id,
            lines=[
                IssueLineInput(
                    inventory_item_id=line.inventory_item_id,
                    inventory_quantity_cohort_id=line.inventory_quantity_cohort_id,
                    source_location_id=line.source_location_id, quantity=line.quantity,
                    reservation_line_id=line.reservation_line_id,
                )
                for line in payload.lines
            ],
        )
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found") from exc
    except (InventoryQuantityCohortNotFoundError, StorageBinNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found") from exc
    except (InventoryReservationNotFoundError, InventoryReservationLineNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found") from exc
    except InventoryIssueCommandReusedWithDifferentPayloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="client_command_id already used with a different payload"
        ) from exc
    except (InventoryIssueLineValidationError, TooManyInventoryIssueLinesError, ReservationLineItemMismatchError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except InactiveStorageBinError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InventoryIssueSourceNotUsableError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Source is not currently usable") from exc
    except InsufficientStorageBinBalanceError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InsufficientReservationBalanceError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InsufficientAvailableToIssueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _build_issue_read(db, tenant_id=ctx.tenant_id, issue=issue)


@router.get("/farms/{farm_id}/inventory-issues", response_model=list[InventoryIssueRead])
def list_issues(
    farm_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_READ)),
) -> list[InventoryIssueRead]:
    issues = inventory_issue_service.list_issues_for_farm(db, tenant_id=ctx.tenant_id, farm_id=farm_id)
    return [_build_issue_read(db, tenant_id=ctx.tenant_id, issue=i) for i in issues]


@router.get("/inventory-issues/{issue_id}", response_model=InventoryIssueRead)
def get_issue(
    issue_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_READ)),
) -> InventoryIssueRead:
    try:
        issue = inventory_issue_service.get_issue(db, tenant_id=ctx.tenant_id, issue_id=issue_id)
    except InventoryIssueNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Issue not found") from exc
    return _build_issue_read(db, tenant_id=ctx.tenant_id, issue=issue)


@router.get(
    "/farms/{farm_id}/inventory-items/{item_id}/availability", response_model=ItemFarmAvailabilityRead
)
def get_item_farm_availability(
    farm_id: uuid.UUID,
    item_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_READ)),
) -> ItemFarmAvailabilityRead:
    summary = inventory_availability_service.get_item_farm_availability_summary(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, inventory_item_id=item_id
    )
    return ItemFarmAvailabilityRead(
        inventory_item_id=item_id, farm_id=farm_id, in_store_quantity=summary["in_store_quantity"],
        reserved_quantity=summary["reserved_quantity"],
        issued_to_operations_quantity=summary["issued_to_operations_quantity"],
        available_to_issue_quantity=summary["available_to_issue_quantity"],
    )


@router.get(
    "/farms/{farm_id}/inventory-items/{item_id}/issuable-sources", response_model=list[IssuableSourceRead]
)
def list_issuable_sources(
    farm_id: uuid.UUID,
    item_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_READ)),
) -> list[IssuableSourceRead]:
    sources = inventory_availability_service.list_item_farm_issuable_sources(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, inventory_item_id=item_id
    )
    return [IssuableSourceRead(**s) for s in sources]
