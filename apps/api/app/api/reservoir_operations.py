import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import TenantContext
from app.core.db import get_db
from app.core.permissions import Permission, require_permission
from app.schemas.reservoir_operations import (
    ReservoirEventCreate,
    ReservoirEventRead,
    WaterDeliveryEventCreate,
    WaterDeliveryEventRead,
)
from app.services import reservoir_operations_service
from app.services.errors import (
    InventoryItemNotFoundError,
    IrrigationCircuitNotFoundError,
    NutrientMixNotFoundError,
    ReservoirEventValidationError,
    ReservoirNotFoundError,
    UnitOfMeasureKindMismatchError,
    UnitOfMeasureNotFoundError,
    WaterDeliveryEventValidationError,
)

router = APIRouter(tags=["reservoir-operations"])


@router.post(
    "/farms/{farm_id}/reservoirs/{reservoir_id}/events", response_model=ReservoirEventRead,
    status_code=status.HTTP_201_CREATED,
)
def record_reservoir_event(
    farm_id: uuid.UUID,
    reservoir_id: uuid.UUID,
    payload: ReservoirEventCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.NUTRIENT_OPERATIONS_MANAGE)),
) -> ReservoirEventRead:
    try:
        return reservoir_operations_service.record_reservoir_event(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, reservoir_id=reservoir_id,
            event_type=payload.event_type, effective_at=payload.effective_at, quantity=payload.quantity,
            quantity_uom_id=payload.quantity_uom_id, inventory_item_id=payload.inventory_item_id,
            notes=payload.notes, client_command_id=payload.client_command_id,
        )
    except ReservoirNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservoir not found") from exc
    except InventoryItemNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Inventory item not found") from exc
    except UnitOfMeasureNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except ReservoirEventValidationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/reservoirs/{reservoir_id}/events", response_model=list[ReservoirEventRead])
def list_reservoir_events(
    reservoir_id: uuid.UUID, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.NUTRIENT_OPERATIONS_READ)),
) -> list[ReservoirEventRead]:
    return reservoir_operations_service.list_reservoir_events(db, tenant_id=ctx.tenant_id, reservoir_id=reservoir_id)


@router.post(
    "/farms/{farm_id}/water-delivery-events", response_model=WaterDeliveryEventRead,
    status_code=status.HTTP_201_CREATED,
)
def record_delivery_event(
    farm_id: uuid.UUID,
    payload: WaterDeliveryEventCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.NUTRIENT_OPERATIONS_MANAGE)),
) -> WaterDeliveryEventRead:
    try:
        return reservoir_operations_service.record_delivery_event(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id,
            reservoir_id=payload.reservoir_id, irrigation_circuit_id=payload.irrigation_circuit_id,
            effective_start=payload.effective_start, effective_end=payload.effective_end,
            delivered_volume=payload.delivered_volume, delivered_volume_uom_id=payload.delivered_volume_uom_id,
            nutrient_mix_id=payload.nutrient_mix_id, notes=payload.notes,
            client_command_id=payload.client_command_id,
        )
    except (ReservoirNotFoundError, IrrigationCircuitNotFoundError, NutrientMixNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (UnitOfMeasureNotFoundError, UnitOfMeasureKindMismatchError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except WaterDeliveryEventValidationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/irrigation-circuits/{irrigation_circuit_id}/water-delivery-events", response_model=list[WaterDeliveryEventRead])
def list_delivery_events(
    irrigation_circuit_id: uuid.UUID, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.NUTRIENT_OPERATIONS_READ)),
) -> list[WaterDeliveryEventRead]:
    return reservoir_operations_service.list_delivery_events_for_circuit(
        db, tenant_id=ctx.tenant_id, irrigation_circuit_id=irrigation_circuit_id
    )


@router.get("/farms/{farm_id}/reservoir-events", response_model=list[ReservoirEventRead])
def list_reservoir_events_for_farm(
    farm_id: uuid.UUID, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.NUTRIENT_OPERATIONS_READ)),
) -> list[ReservoirEventRead]:
    return reservoir_operations_service.list_reservoir_events_for_farm(db, tenant_id=ctx.tenant_id, farm_id=farm_id)


@router.get("/farms/{farm_id}/water-delivery-events", response_model=list[WaterDeliveryEventRead])
def list_delivery_events_for_farm(
    farm_id: uuid.UUID, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.NUTRIENT_OPERATIONS_READ)),
) -> list[WaterDeliveryEventRead]:
    return reservoir_operations_service.list_delivery_events_for_farm(db, tenant_id=ctx.tenant_id, farm_id=farm_id)
