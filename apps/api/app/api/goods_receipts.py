import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import TenantContext
from app.core.db import get_db
from app.core.permissions import Permission, require_permission
from app.schemas.goods_receipt import GoodsReceiptCreate, GoodsReceiptRead
from app.services import goods_receipt_service
from app.services.errors import (
    ConflictingInventoryLotIdentityError,
    DuplicateSeedLotCodeError,
    FarmNotFoundError,
    GoodsReceiptCommandReusedWithDifferentPayloadError,
    GoodsReceiptItemNotActiveError,
    GoodsReceiptLineValidationError,
    GoodsReceiptNotFoundError,
    InventoryItemNotFoundError,
    InventoryItemPackagingNotActiveError,
    InventoryItemPackagingNotFoundError,
)
from app.services.goods_receipt_service import GoodsReceiptLineInput

router = APIRouter(tags=["goods-receipts"])


@router.post(
    "/farms/{farm_id}/goods-receipts", response_model=GoodsReceiptRead, status_code=status.HTTP_201_CREATED
)
def record_goods_receipt(
    farm_id: uuid.UUID,
    payload: GoodsReceiptCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_RECEIPT_MANAGE)),
) -> GoodsReceiptRead:
    lines = [
        GoodsReceiptLineInput(
            inventory_item_id=line.inventory_item_id, entered_quantity=line.entered_quantity,
            entered_uom_id=line.entered_uom_id, packaging_id=line.packaging_id, package_count=line.package_count,
            manufacturer_name=line.manufacturer_name, manufacturer_lot_reference=line.manufacturer_lot_reference,
            manufacturing_date=line.manufacturing_date, expiry_date=line.expiry_date,
            seed_crop_id=line.seed_crop_id, seed_variety_id=line.seed_variety_id,
            seed_lot_code=line.seed_lot_code, external_line_id=line.external_line_id,
        )
        for line in payload.lines
    ]
    try:
        receipt = goods_receipt_service.record_goods_receipt(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id,
            client_command_id=payload.client_command_id, received_at=payload.received_at,
            supplier_name=payload.supplier_name, external_system=payload.external_system,
            external_document_id=payload.external_document_id, notes=payload.notes, lines=lines,
        )
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found") from exc
    except (InventoryItemNotFoundError, InventoryItemPackagingNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown reference") from exc
    except (
        GoodsReceiptLineValidationError, GoodsReceiptItemNotActiveError, InventoryItemPackagingNotActiveError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except GoodsReceiptCommandReusedWithDifferentPayloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="client_command_id already used with a different payload",
        ) from exc
    except ConflictingInventoryLotIdentityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "this manufacturer name + lot reference already identifies a different InventoryLot "
                "(conflicting manufacturing_date/expiry_date) -- verify and correct, or confirm this is "
                "genuinely a different lot"
            ),
        ) from exc
    except DuplicateSeedLotCodeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Seed lot code already exists") from exc
    return GoodsReceiptRead.model_validate(receipt)


@router.get("/farms/{farm_id}/goods-receipts", response_model=list[GoodsReceiptRead])
def list_goods_receipts(
    farm_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_READ)),
) -> list[GoodsReceiptRead]:
    rows = goods_receipt_service.list_goods_receipts(db, tenant_id=ctx.tenant_id, farm_id=farm_id)
    return [GoodsReceiptRead.model_validate(r) for r in rows]


@router.get("/farms/{farm_id}/goods-receipts/{receipt_id}", response_model=GoodsReceiptRead)
def get_goods_receipt(
    farm_id: uuid.UUID,
    receipt_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_READ)),
) -> GoodsReceiptRead:
    try:
        receipt = goods_receipt_service.get_goods_receipt(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, receipt_id=receipt_id
        )
    except GoodsReceiptNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goods receipt not found") from exc
    return GoodsReceiptRead.model_validate(receipt)
