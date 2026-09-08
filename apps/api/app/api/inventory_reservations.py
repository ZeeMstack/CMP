import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import TenantContext
from app.core.db import get_db
from app.core.permissions import Permission, require_permission
from app.models.inventory_reservation import InventoryReservation
from app.models.inventory_reservation_line import InventoryReservationLine
from app.schemas.inventory_reservation import (
    InventoryReservationCreate,
    InventoryReservationLineRead,
    InventoryReservationRead,
    InventoryReservationReleaseCreate,
)
from app.services import inventory_reservation_service
from app.services.errors import (
    FarmNotFoundError,
    InsufficientAvailableToIssueError,
    InsufficientReservationBalanceError,
    InventoryReservationCommandReusedWithDifferentPayloadError,
    InventoryReservationLineNotFoundError,
    InventoryReservationNotFoundError,
    InventoryReservationReleaseCommandReusedWithDifferentPayloadError,
)
from app.services.inventory_reservation_service import ReservationLineInput

router = APIRouter(tags=["inventory-reservations"])


def _build_line_read(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, line: InventoryReservationLine
) -> InventoryReservationLineRead:
    remaining = inventory_reservation_service.get_reservation_line_remaining(db, reservation_line_id=line.id)
    blocked = inventory_reservation_service.is_line_blocked_by_quality(
        db, tenant_id=tenant_id, farm_id=farm_id, inventory_item_id=line.inventory_item_id, remaining=remaining
    )
    return InventoryReservationLineRead(
        id=line.id, inventory_item_id=line.inventory_item_id, requested_quantity_base=line.requested_quantity_base,
        remaining_quantity_base=remaining, blocked_by_quality=blocked,
    )


def _build_reservation_read(db: Session, *, tenant_id: uuid.UUID, reservation: InventoryReservation) -> InventoryReservationRead:
    lines = inventory_reservation_service.list_reservation_lines(db, tenant_id=tenant_id, reservation_id=reservation.id)
    return InventoryReservationRead(
        id=reservation.id, tenant_id=reservation.tenant_id, farm_id=reservation.farm_id, code=reservation.code,
        purpose=reservation.purpose, requested_by_user_id=reservation.requested_by_user_id,
        effective_time=reservation.effective_time, recorded_time=reservation.recorded_time,
        lines=[_build_line_read(db, tenant_id=tenant_id, farm_id=reservation.farm_id, line=line) for line in lines],
    )


@router.post(
    "/farms/{farm_id}/inventory-reservations", response_model=InventoryReservationRead,
    status_code=status.HTTP_201_CREATED,
)
def create_reservation(
    farm_id: uuid.UUID,
    payload: InventoryReservationCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_RESERVATION_MANAGE)),
) -> InventoryReservationRead:
    try:
        reservation = inventory_reservation_service.create_reservation(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id,
            client_command_id=payload.client_command_id, purpose=payload.purpose,
            effective_time=payload.effective_time,
            lines=[ReservationLineInput(inventory_item_id=line.inventory_item_id, quantity=line.quantity) for line in payload.lines],
        )
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found") from exc
    except InventoryReservationCommandReusedWithDifferentPayloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="client_command_id already used with a different payload"
        ) from exc
    except InsufficientAvailableToIssueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InsufficientReservationBalanceError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _build_reservation_read(db, tenant_id=ctx.tenant_id, reservation=reservation)


@router.get("/farms/{farm_id}/inventory-reservations", response_model=list[InventoryReservationRead])
def list_reservations(
    farm_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_READ)),
) -> list[InventoryReservationRead]:
    reservations = inventory_reservation_service.list_reservations_for_farm(db, tenant_id=ctx.tenant_id, farm_id=farm_id)
    return [_build_reservation_read(db, tenant_id=ctx.tenant_id, reservation=r) for r in reservations]


@router.get("/inventory-reservations/{reservation_id}", response_model=InventoryReservationRead)
def get_reservation(
    reservation_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_READ)),
) -> InventoryReservationRead:
    try:
        reservation = inventory_reservation_service.get_reservation(db, tenant_id=ctx.tenant_id, reservation_id=reservation_id)
    except InventoryReservationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found") from exc
    return _build_reservation_read(db, tenant_id=ctx.tenant_id, reservation=reservation)


@router.post(
    "/inventory-reservation-lines/{line_id}/releases", response_model=InventoryReservationLineRead,
    status_code=status.HTTP_201_CREATED,
)
def release_reservation_line(
    line_id: uuid.UUID,
    payload: InventoryReservationReleaseCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_RESERVATION_MANAGE)),
) -> InventoryReservationLineRead:
    try:
        entry = inventory_reservation_service.release_reservation_line(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, client_command_id=payload.client_command_id,
            reservation_line_id=line_id, quantity=payload.quantity, effective_time=payload.effective_time,
            reason=payload.reason,
        )
    except InventoryReservationLineNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation line not found") from exc
    except InventoryReservationReleaseCommandReusedWithDifferentPayloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="client_command_id already used with a different payload"
        ) from exc
    except InsufficientReservationBalanceError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    line = db.get(InventoryReservationLine, entry.reservation_line_id)
    assert line is not None
    reservation = inventory_reservation_service.get_reservation(db, tenant_id=ctx.tenant_id, reservation_id=line.reservation_id)
    return _build_line_read(db, tenant_id=ctx.tenant_id, farm_id=reservation.farm_id, line=line)
