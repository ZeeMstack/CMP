import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.auth import TenantContext
from app.core.permissions import Permission, require_permission
from app.schemas.seed_lot import SeedLotCreate, SeedLotRead
from app.schemas.sowing_event import SeedLotBatchSummary
from app.services import sowing_service
from app.services.errors import (
    CropNotFoundError,
    DuplicateSeedLotCodeError,
    FarmNotFoundError,
    SeedLotNotFoundError,
    SeedLotValidationError,
    VarietyNotFoundError,
)

router = APIRouter(tags=["seed-lots"])


@router.post("/farms/{farm_id}/seed-lots", response_model=SeedLotRead, status_code=status.HTTP_201_CREATED)
def register_seed_lot(
    farm_id: uuid.UUID,
    payload: SeedLotCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.SEED_LOT_MANAGE)),
) -> SeedLotRead:
    try:
        seed_lot = sowing_service.register_seed_lot(
            db,
            tenant_id=ctx.tenant_id,
            farm_id=farm_id,
            actor_user_id=ctx.user_id,
            crop_id=payload.crop_id,
            variety_id=payload.variety_id,
            code=payload.code,
            supplier_name=payload.supplier_name,
            supplier_lot_reference=payload.supplier_lot_reference,
            received_date=payload.received_date,
            expiry_date=payload.expiry_date,
        )
    except (FarmNotFoundError, CropNotFoundError, VarietyNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except DuplicateSeedLotCodeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except SeedLotValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return sowing_service.get_seed_lot(db, tenant_id=ctx.tenant_id, farm_id=farm_id, seed_lot_id=seed_lot.id)


@router.get("/farms/{farm_id}/seed-lots", response_model=list[SeedLotRead])
def list_seed_lots(
    farm_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.SEED_LOT_READ)),
) -> list[SeedLotRead]:
    try:
        return sowing_service.list_seed_lots(db, tenant_id=ctx.tenant_id, farm_id=farm_id)
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found") from exc


@router.get("/farms/{farm_id}/seed-lots/{seed_lot_id}", response_model=SeedLotRead)
def get_seed_lot(
    farm_id: uuid.UUID,
    seed_lot_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.SEED_LOT_READ)),
) -> SeedLotRead:
    try:
        return sowing_service.get_seed_lot(db, tenant_id=ctx.tenant_id, farm_id=farm_id, seed_lot_id=seed_lot_id)
    except (FarmNotFoundError, SeedLotNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get(
    "/farms/{farm_id}/seed-lots/{seed_lot_id}/crop-batches", response_model=list[SeedLotBatchSummary]
)
def list_batches_for_seed_lot(
    farm_id: uuid.UUID,
    seed_lot_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.SEED_LOT_READ)),
) -> list[SeedLotBatchSummary]:
    """Section 49: "which Crop Batches were sown from this Seed Lot" --
    gated on `seed_lot.read` (the resource being read), matching
    `get_seed_lot` above."""
    try:
        return sowing_service.list_batches_for_seed_lot(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, seed_lot_id=seed_lot_id
        )
    except (FarmNotFoundError, SeedLotNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
