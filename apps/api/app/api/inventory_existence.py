import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import TenantContext
from app.core.db import get_db
from app.core.permissions import Permission, require_permission
from app.schemas.inventory_existence import (
    InventoryAdjustmentCreate,
    InventoryExistenceLedgerEntryRead,
    InventoryExistenceReversalCreate,
    InventoryItemCohortProvenanceRead,
    InventoryItemExistenceRead,
    InventoryLotExistenceRead,
)
from app.services import inventory_existence_ledger_service, inventory_existence_read_service
from app.services.errors import (
    InsufficientCohortBalanceError,
    InventoryAdjustmentCommandReusedWithDifferentPayloadError,
    InventoryExistenceLedgerEntryNotFoundError,
    InventoryExistenceReversalCommandReusedWithDifferentPayloadError,
    InventoryExistenceReversalOfReversalError,
    InventoryExistenceReversalTargetAlreadyReversedError,
    InventoryQuantityCohortNotFoundError,
)

router = APIRouter(tags=["inventory-existence"])


@router.post(
    "/inventory-adjustments", response_model=InventoryExistenceLedgerEntryRead, status_code=status.HTTP_201_CREATED
)
def record_adjustment(
    payload: InventoryAdjustmentCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_ADJUSTMENT_MANAGE)),
) -> InventoryExistenceLedgerEntryRead:
    try:
        entry = inventory_existence_ledger_service.record_adjustment(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, client_command_id=payload.client_command_id,
            cohort_id=payload.inventory_quantity_cohort_id, quantity_delta=payload.quantity_delta,
            effective_time=payload.effective_time, reason=payload.reason,
        )
    except InventoryQuantityCohortNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cohort not found") from exc
    except InventoryAdjustmentCommandReusedWithDifferentPayloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="client_command_id already used with a different payload",
        ) from exc
    except InsufficientCohortBalanceError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return InventoryExistenceLedgerEntryRead.model_validate(entry)


@router.post(
    "/inventory-existence-reversals", response_model=InventoryExistenceLedgerEntryRead,
    status_code=status.HTTP_201_CREATED,
)
def record_existence_reversal(
    payload: InventoryExistenceReversalCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_ADJUSTMENT_MANAGE)),
) -> InventoryExistenceLedgerEntryRead:
    try:
        entry = inventory_existence_ledger_service.reverse_ledger_entry(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, client_command_id=payload.client_command_id,
            target_entry_id=payload.target_entry_id, reason=payload.reason,
        )
    except InventoryExistenceLedgerEntryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ledger entry not found") from exc
    except InventoryExistenceReversalCommandReusedWithDifferentPayloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="client_command_id already used with a different payload",
        ) from exc
    except (
        InventoryExistenceReversalOfReversalError, InventoryExistenceReversalTargetAlreadyReversedError,
        InsufficientCohortBalanceError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return InventoryExistenceLedgerEntryRead.model_validate(entry)


@router.get(
    "/inventory-quantity-cohorts/{cohort_id}/ledger", response_model=list[InventoryExistenceLedgerEntryRead]
)
def list_cohort_ledger(
    cohort_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_READ)),
) -> list[InventoryExistenceLedgerEntryRead]:
    rows = inventory_existence_ledger_service.list_ledger_entries(db, tenant_id=ctx.tenant_id, cohort_id=cohort_id)
    return [InventoryExistenceLedgerEntryRead.model_validate(r) for r in rows]


@router.get("/inventory-items/{item_id}/existence", response_model=InventoryItemExistenceRead)
def get_item_existence(
    item_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_READ)),
) -> InventoryItemExistenceRead:
    total = inventory_existence_read_service.get_item_existence(db, tenant_id=ctx.tenant_id, inventory_item_id=item_id)
    return InventoryItemExistenceRead(inventory_item_id=item_id, existing_quantity=total)


@router.get("/inventory-items/{item_id}/existence/provenance", response_model=list[InventoryItemCohortProvenanceRead])
def get_item_existence_provenance(
    item_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_READ)),
) -> list[InventoryItemCohortProvenanceRead]:
    rows = inventory_existence_read_service.list_item_cohort_provenance(
        db, tenant_id=ctx.tenant_id, inventory_item_id=item_id
    )
    return [InventoryItemCohortProvenanceRead(**row) for row in rows]


@router.get("/inventory-lots/{lot_id}/existence", response_model=InventoryLotExistenceRead)
def get_lot_existence(
    lot_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_READ)),
) -> InventoryLotExistenceRead:
    total = inventory_existence_read_service.get_lot_existence(db, tenant_id=ctx.tenant_id, inventory_lot_id=lot_id)
    return InventoryLotExistenceRead(inventory_lot_id=lot_id, existing_quantity=total)
