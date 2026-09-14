"""PILOT-SCAN-001: QR label generation, scan resolution, and print/reprint
audit.

Authorization here is deliberately NOT the codebase's usual single static
`Depends(require_permission(SomePermission))` shape (see
`test_authz_read_enforcement_architecture.py`/
`test_authz_mutation_enforcement_architecture.py`'s own `EXEMPT_*`
mechanism, which this module's routes are registered under, each with the
justification repeated inline below): a generic QR resolver's real
authorization requirement is only known once the token has been resolved
to an `entity_type`, which varies request to request. Every route here
still requires `require_tenant_context` (real authentication + an active
tenant membership) and then enforces the exact per-entity-type
`Permission` via `has_permission` before returning or acting on any
content -- CLAUDE.md rule 11 (permissions enforced in the backend) is
never relaxed, only expressed one layer later than the mechanical
per-route check can reach. `test_qr_authz.py` is this module's own
structural + behavioral proof that the dynamic gate actually holds for
every supported entity type.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import TenantContext, require_tenant_context
from app.core.db import get_db
from app.core.permissions import Permission, has_permission
from app.models.qr_identifier import QR_IDENTIFIER_ENTITY_TYPES
from app.schemas.qr import PrintLabelRequest, PrintLabelResponse, QrIdentifierRead, ScanContext
from app.services import qr_service
from app.services.errors import (
    AssetNotFoundError,
    BatchCarrierAssignmentNotFoundError,
    CarrierNotFoundError,
    CropBatchNotFoundError,
    FarmNotFoundError,
    GradedProduceLotNotFoundError,
    HarvestedProduceLotNotFoundError,
    LocationNotFoundError,
    QrEntityNotEligibleError,
    QrIdentifierNotFoundError,
    QrReprintReasonRequiredError,
)

router = APIRouter(tags=["qr"])

_NOT_FOUND_ERRORS = (
    FarmNotFoundError,
    CropBatchNotFoundError,
    LocationNotFoundError,
    CarrierNotFoundError,
    AssetNotFoundError,
    BatchCarrierAssignmentNotFoundError,
    HarvestedProduceLotNotFoundError,
    GradedProduceLotNotFoundError,
)

# entity_type -> (read permission, manage permission). `manage` gates
# generating/(re)printing a label for that entity type; `read` gates
# resolving/scanning it. `batch_carrier_assignment` (the physical
# placement) reuses the parent Batch's own permission tier -- CMP-006
# already treats "what crop batch does this carrier contain right now" as
# part of Crop Batch authority, and no dedicated placement-level
# permission exists in the current catalog (never fabricated here).
ENTITY_PERMISSIONS: dict[str, tuple[Permission, Permission]] = {
    "crop_batch": (Permission.CROP_BATCH_READ, Permission.CROP_BATCH_MANAGE),
    "location": (Permission.LOCATION_READ, Permission.LOCATION_MANAGE),
    "carrier": (Permission.CARRIER_READ, Permission.CARRIER_MANAGE),
    "asset": (Permission.ASSET_READ, Permission.ASSET_MANAGE),
    "batch_carrier_assignment": (Permission.CROP_BATCH_READ, Permission.CROP_BATCH_MANAGE),
    "harvested_produce_lot": (Permission.HARVEST_READ, Permission.HARVEST_MANAGE),
    "graded_produce_lot": (Permission.GRADING_READ, Permission.GRADING_MANAGE),
    "finished_goods_lot": (Permission.FINISHED_GOODS_STORAGE_READ, Permission.FINISHED_GOODS_STORAGE_MANAGE),
}


def _require_read(ctx: TenantContext, entity_type: str) -> None:
    read_permission, _ = ENTITY_PERMISSIONS[entity_type]
    if not has_permission(ctx, read_permission):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You don't have permission to perform this action")


def _require_manage(ctx: TenantContext, entity_type: str) -> None:
    _, manage_permission = ENTITY_PERMISSIONS[entity_type]
    if not has_permission(ctx, manage_permission):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You don't have permission to perform this action")


@router.post("/farms/{farm_id}/qr/{entity_type}/{entity_id}/generate", response_model=QrIdentifierRead)
def generate_qr_identifier(
    farm_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
    ctx: TenantContext = Depends(require_tenant_context),
    db: Session = Depends(get_db),
) -> QrIdentifierRead:
    if entity_type not in QR_IDENTIFIER_ENTITY_TYPES:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    _require_manage(ctx, entity_type)
    try:
        identifier = qr_service.generate_or_get_qr_identifier(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, entity_type=entity_type, entity_id=entity_id,
            actor_user_id=ctx.user_id,
        )
    except _NOT_FOUND_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except QrEntityNotEligibleError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return QrIdentifierRead(
        id=identifier.id, entity_type=identifier.entity_type, token=identifier.token, created_at=identifier.created_at
    )


@router.get("/qr/{token}", response_model=ScanContext)
def resolve_qr(
    token: str,
    ctx: TenantContext = Depends(require_tenant_context),
    db: Session = Depends(get_db),
) -> ScanContext:
    try:
        identifier = qr_service.get_active_qr_identifier_by_token(db, tenant_id=ctx.tenant_id, token=token)
    except QrIdentifierNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc

    _require_read(ctx, identifier.entity_type)

    def may(permission_value: str) -> bool:
        return has_permission(ctx, Permission(permission_value))

    try:
        return qr_service.resolve_scan_context(db, tenant_id=ctx.tenant_id, qr_identifier=identifier, may=may)
    except _NOT_FOUND_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.post("/qr/{token}/print", response_model=PrintLabelResponse)
def print_qr_label(
    token: str,
    payload: PrintLabelRequest,
    ctx: TenantContext = Depends(require_tenant_context),
    db: Session = Depends(get_db),
) -> PrintLabelResponse:
    try:
        identifier = qr_service.get_active_qr_identifier_by_token(db, tenant_id=ctx.tenant_id, token=token)
    except QrIdentifierNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc

    _require_manage(ctx, identifier.entity_type)

    try:
        printed_at, is_reprint = qr_service.record_label_print(
            db, tenant_id=ctx.tenant_id, farm_id=identifier.farm_id, actor_user_id=ctx.user_id,
            qr_identifier=identifier, template=payload.template, template_version=payload.template_version,
            reason=payload.reason,
        )
    except QrReprintReasonRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="A reason is required to reprint this label"
        ) from exc
    return PrintLabelResponse(qr_identifier_id=identifier.id, printed_at=printed_at, is_reprint=is_reprint)
