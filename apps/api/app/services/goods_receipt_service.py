"""STORE-INV-002A.1: `record_goods_receipt` -- one atomic, multi-line
"Record Goods Receipt" command (`docs/domain/STORE_INVENTORY_MODEL.md`
§E/§F/§M). No server-side Draft state. All-or-nothing: any single line
failing rolls back the entire receipt.

Per posted `GoodsReceiptLine`, in the SAME transaction: resolve/create its
`InventoryLot` (tenant-wide, only for lot-tracked items), resolve/create a
Farm-specific `SeedLot` when Seed Details linking is requested, insert the
line itself, its deterministic root `InventoryQuantityCohort`, the
deterministic opening `receipt` ledger entry, and -- when
`qc_release_required` -- the automatic, permanently non-reversible
`RECEIVED_QUARANTINED` opening `QualityDispositionEvent`.

Follows the `_create_batch_core`/`_sow_batch_core` composition convention
throughout: every composed core function (`inventory_lot_service.
resolve_or_create_inventory_lot`, `sowing_service._register_seed_lot_core`)
never catches `IntegrityError` itself -- this module's own single
`except IntegrityError` block, wrapping the whole per-line write sequence,
is the only rollback point, exactly mirroring `nursery_service.
sow_new_batch`.

Losing the canonical-InventoryLot-identity race
(`ux_inventory_lots_tenant_item_manufacturer_identity`) is retried once,
bounded: the loser's whole write sequence was just rolled back (nothing
partial survives), so re-running it lets `resolve_or_create_inventory_lot`'s
own `_find_canonical` check find and transparently reuse the winner's
now-committed row -- exactly the "compatible attributes -> reuse" outcome
`docs/domain/STORE_INVENTORY_MODEL.md` §7 requires, rather than surfacing a
hard conflict for a benign concurrent duplicate. A genuine attribute
conflict still surfaces as `ConflictingInventoryLotIdentityError` raised
directly by `resolve_or_create_inventory_lot` on retry (not an
`IntegrityError`, so it propagates past this module's retry loop
untouched)."""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import ROUND_DOWN, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.goods_receipt import GoodsReceipt
from app.models.goods_receipt_line import GoodsReceiptLine
from app.models.inventory_existence_ledger_entry import InventoryExistenceLedgerEntry
from app.models.inventory_item import InventoryItem
from app.models.inventory_item_packaging import InventoryItemPackaging
from app.models.inventory_quantity_cohort import InventoryQuantityCohort
from app.models.quality_disposition_event import QualityDispositionEvent
from app.services import inventory_item_seed_profile_service, inventory_lot_service, sowing_service
from app.services import unit_of_measure_service
from app.services.audit import append_audit_event
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
from app.services.farm_service import get_farm


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _truncate3(value: Decimal) -> Decimal:
    """Matches the DB's own `trunc(x, 3)` CHECK exactly -- truncation
    toward zero, never rounding."""
    return value.quantize(Decimal("0.001"), rounding=ROUND_DOWN)


@dataclass
class GoodsReceiptLineInput:
    inventory_item_id: uuid.UUID
    entered_quantity: Decimal | None = None
    entered_uom_id: uuid.UUID | None = None
    packaging_id: uuid.UUID | None = None
    package_count: int | None = None
    manufacturer_name: str | None = None
    manufacturer_lot_reference: str | None = None
    manufacturing_date: date | None = None
    expiry_date: date | None = None
    seed_crop_id: uuid.UUID | None = None
    seed_variety_id: uuid.UUID | None = None
    seed_lot_code: str | None = None
    external_line_id: str | None = None


def _require_active_farm(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID):
    farm = get_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    if farm.status != "active":
        raise FarmNotFoundError(str(farm_id))
    return farm


def _compute_fingerprint(
    *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID | None, received_at: datetime,
    supplier_name: str | None, external_system: str | None, external_document_id: str | None,
    notes: str | None, lines: list[GoodsReceiptLineInput],
) -> str:
    parts = [
        str(tenant_id), str(farm_id), str(actor_user_id) if actor_user_id else "",
        received_at.astimezone(timezone.utc).isoformat(), supplier_name or "", external_system or "",
        external_document_id or "", notes or "",
    ]
    for line in lines:
        parts.extend([
            str(line.inventory_item_id), str(line.entered_quantity or ""), str(line.entered_uom_id or ""),
            str(line.packaging_id or ""), str(line.package_count or ""), line.manufacturer_name or "",
            line.manufacturer_lot_reference or "", str(line.manufacturing_date or ""),
            str(line.expiry_date or ""), str(line.seed_crop_id or ""), str(line.seed_variety_id or ""),
            line.seed_lot_code or "", line.external_line_id or "",
        ])
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _resolve_line_quantity(
    db: Session, *, item: InventoryItem, line: GoodsReceiptLineInput
) -> tuple[Decimal, dict]:
    """Returns `(base_quantity, extra_columns)` -- `extra_columns` carries
    exactly the direct-UOM or packaging column set for `GoodsReceiptLine`,
    never both (docs/domain/STORE_INVENTORY_MODEL.md §M)."""
    direct = line.entered_quantity is not None or line.entered_uom_id is not None
    packaged = line.packaging_id is not None or line.package_count is not None
    if direct and packaged:
        raise GoodsReceiptLineValidationError("a line may use direct quantity entry or packaging entry, not both")
    if direct:
        if line.entered_quantity is None or line.entered_uom_id is None or line.entered_quantity <= 0:
            raise GoodsReceiptLineValidationError("entered_quantity and entered_uom_id are both required and positive")
        factor = unit_of_measure_service.resolve_conversion_factor(
            db, from_uom_id=line.entered_uom_id, to_uom_id=item.base_uom_id
        )
        if factor is None:
            raise GoodsReceiptLineValidationError("entered_uom_id is not convertible to this item's base UOM")
        base_quantity = _truncate3(line.entered_quantity * factor)
        return base_quantity, {
            "entered_quantity": line.entered_quantity, "entered_uom_id": line.entered_uom_id,
            "conversion_factor_applied": factor, "packaging_id": None, "package_count": None,
            "package_quantity_snapshot": None,
        }
    if packaged:
        if line.packaging_id is None or line.package_count is None or line.package_count <= 0:
            raise GoodsReceiptLineValidationError("packaging_id and a positive package_count are both required")
        packaging = db.execute(
            select(InventoryItemPackaging).where(
                InventoryItemPackaging.id == line.packaging_id,
                InventoryItemPackaging.tenant_id == item.tenant_id,
            )
        ).scalar_one_or_none()
        if packaging is None:
            raise InventoryItemPackagingNotFoundError(str(line.packaging_id))
        if packaging.inventory_item_id != item.id:
            raise GoodsReceiptLineValidationError("packaging_id does not belong to this line's inventory_item_id")
        if packaging.status != "active":
            raise InventoryItemPackagingNotActiveError(str(line.packaging_id))
        base_quantity = _truncate3(packaging.package_quantity * line.package_count)
        return base_quantity, {
            "entered_quantity": None, "entered_uom_id": None, "conversion_factor_applied": None,
            "packaging_id": packaging.id, "package_count": line.package_count,
            "package_quantity_snapshot": packaging.package_quantity,
        }
    raise GoodsReceiptLineValidationError("a line must use either direct quantity entry or packaging entry")


def _validate_and_prepare_line(db: Session, *, tenant_id: uuid.UUID, line: GoodsReceiptLineInput) -> dict:
    item = db.execute(
        select(InventoryItem).where(InventoryItem.id == line.inventory_item_id, InventoryItem.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if item is None:
        raise InventoryItemNotFoundError(str(line.inventory_item_id))
    if item.status != "active":
        raise GoodsReceiptItemNotActiveError(str(line.inventory_item_id))

    has_manufacturer_fields = (
        line.manufacturer_name is not None or line.manufacturer_lot_reference is not None
        or line.manufacturing_date is not None or line.expiry_date is not None
    )
    if not item.lot_tracking_required and (has_manufacturer_fields or line.seed_crop_id is not None):
        raise GoodsReceiptLineValidationError(
            "this item is not lot-tracked -- manufacturer/lot/expiry/seed-linking fields must not be supplied"
        )
    if item.expiry_tracking_required and line.expiry_date is None:
        raise GoodsReceiptLineValidationError("this item requires expiry_date to be supplied")

    base_quantity, entry_columns = _resolve_line_quantity(db, item=item, line=line)

    seed_profile = None
    if line.seed_crop_id is not None or line.seed_variety_id is not None or line.seed_lot_code is not None:
        seed_profile = inventory_item_seed_profile_service.get_seed_profile_for_item(
            db, tenant_id=tenant_id, inventory_item_id=item.id
        )
        if seed_profile is None:
            raise GoodsReceiptLineValidationError("this item has no Seed Details -- cannot link a Seed Lot")
        if line.seed_crop_id != seed_profile.crop_id or line.seed_variety_id != seed_profile.variety_id:
            raise GoodsReceiptLineValidationError("seed crop/variety must match this item's Seed Details")
        if not line.seed_lot_code:
            raise GoodsReceiptLineValidationError("seed_lot_code is required when linking a Seed Lot")

    return {
        "item": item, "base_quantity": base_quantity, "entry_columns": entry_columns,
        "seed_profile": seed_profile,
    }


def record_goods_receipt(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_command_id: uuid.UUID,
    received_at: datetime,
    supplier_name: str | None,
    external_system: str | None,
    external_document_id: str | None,
    notes: str | None,
    lines: list[GoodsReceiptLineInput],
) -> GoodsReceipt:
    if not lines:
        raise GoodsReceiptLineValidationError("a receipt must have at least one line")

    fingerprint = _compute_fingerprint(
        tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, received_at=received_at,
        supplier_name=supplier_name, external_system=external_system, external_document_id=external_document_id,
        notes=notes, lines=lines,
    )

    existing = db.execute(
        select(GoodsReceipt).where(
            GoodsReceipt.tenant_id == tenant_id, GoodsReceipt.client_command_id == client_command_id
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise GoodsReceiptCommandReusedWithDifferentPayloadError(str(client_command_id))

    farm = _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    recorded_time = datetime.now(timezone.utc)
    local_date = received_at.astimezone(ZoneInfo(farm.timezone)).date()

    # A concurrent receipt can win the race to create the same canonical
    # InventoryLot identity first (`resolve_or_create_inventory_lot`'s own
    # `_find_canonical` check necessarily runs before either racer commits).
    # Losing that race is not itself an error -- the domain model requires
    # transparently reusing the winner's row once its (now-committed,
    # compatible) attributes are visible (docs/domain/
    # STORE_INVENTORY_MODEL.md §7). Since the whole per-line write sequence
    # is rolled back on any IntegrityError, nothing was partially applied,
    # so one bounded retry of the entire sequence is safe: it re-validates
    # cleanly and, on the lot-identity constraint specifically,
    # `resolve_or_create_inventory_lot`'s `_find_canonical` will now find
    # and reuse the winner's committed row -- raising the explicit
    # `ConflictingInventoryLotIdentityError` itself (not an `IntegrityError`,
    # so it is not caught below) if that row's attributes actually conflict.
    # A second collision on the same constraint (a third concurrent racer)
    # is astronomically unlikely and not retried further.
    max_attempts = 2
    for attempt in range(1, max_attempts + 1):
        prepared = [_validate_and_prepare_line(db, tenant_id=tenant_id, line=line) for line in lines]
        try:
            code = _next_receipt_code(db, tenant_id=tenant_id, farm_id=farm_id, farm_code=farm.code)
            receipt = GoodsReceipt(
                tenant_id=tenant_id, farm_id=farm_id, code=code, received_at=received_at,
                received_by_user_id=actor_user_id, supplier_name=supplier_name, external_system=external_system,
                external_document_id=external_document_id, notes=notes, client_command_id=client_command_id,
                request_fingerprint=fingerprint,
            )
            db.add(receipt)
            db.flush()

            line_summaries = []
            for line_input, prep in zip(lines, prepared):
                item: InventoryItem = prep["item"]
                base_quantity: Decimal = prep["base_quantity"]

                inventory_lot_id = None
                if item.lot_tracking_required:
                    lot = inventory_lot_service.resolve_or_create_inventory_lot(
                        db, tenant_id=tenant_id, actor_user_id=actor_user_id, inventory_item_id=item.id,
                        item_code=item.code, manufacturer_name=line_input.manufacturer_name,
                        manufacturer_lot_reference=line_input.manufacturer_lot_reference,
                        manufacturing_date=line_input.manufacturing_date, expiry_date=line_input.expiry_date,
                    )
                    inventory_lot_id = lot.id

                    if prep["seed_profile"] is not None:
                        seed_lot = sowing_service._register_seed_lot_core(
                            db, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id,
                            crop_id=prep["seed_profile"].crop_id, variety_id=prep["seed_profile"].variety_id,
                            code=line_input.seed_lot_code, supplier_name=supplier_name,
                            supplier_lot_reference=line_input.manufacturer_lot_reference,
                            received_date=local_date, expiry_date=line_input.expiry_date,
                            inventory_lot_id=inventory_lot_id,
                        )

                goods_receipt_line = GoodsReceiptLine(
                    tenant_id=tenant_id, farm_id=farm_id, goods_receipt_id=receipt.id, inventory_item_id=item.id,
                    inventory_lot_id=inventory_lot_id, base_quantity=base_quantity,
                    external_line_id=line_input.external_line_id, **prep["entry_columns"],
                )
                db.add(goods_receipt_line)
                db.flush()

                cohort = InventoryQuantityCohort(
                    id=goods_receipt_line.id, tenant_id=tenant_id,
                    source_goods_receipt_line_id=goods_receipt_line.id, inventory_item_id=item.id,
                    inventory_lot_id=inventory_lot_id, receiving_farm_id=farm_id, parent_cohort_id=None,
                    created_by_user_id=actor_user_id,
                )
                db.add(cohort)
                db.flush()

                ledger_entry = InventoryExistenceLedgerEntry(
                    id=goods_receipt_line.id, tenant_id=tenant_id, inventory_quantity_cohort_id=cohort.id,
                    inventory_item_id=item.id, inventory_lot_id=inventory_lot_id, receiving_farm_id=farm_id,
                    entry_kind="receipt", quantity_delta_base=base_quantity, effective_time=received_at,
                    recorded_time=recorded_time, actor_user_id=actor_user_id, reason=None,
                )
                db.add(ledger_entry)
                db.flush()

                if item.qc_release_required:
                    opening_event = QualityDispositionEvent(
                        tenant_id=tenant_id, inventory_quantity_cohort_id=cohort.id,
                        event_kind="RECEIVED_QUARANTINED", effective_time=received_at,
                        recorded_time=recorded_time, actor_user_id=actor_user_id, reason=None,
                    )
                    db.add(opening_event)
                    db.flush()

                line_summaries.append({
                    "goods_receipt_line_id": str(goods_receipt_line.id), "inventory_item_id": str(item.id),
                    "inventory_lot_id": str(inventory_lot_id) if inventory_lot_id else None,
                    "base_quantity": str(base_quantity),
                })
            break
        except IntegrityError as exc:
            db.rollback()
            constraint = _constraint_name(exc)
            if constraint == "ux_goods_receipts_tenant_client_command_id":
                replay = db.execute(
                    select(GoodsReceipt).where(
                        GoodsReceipt.tenant_id == tenant_id, GoodsReceipt.client_command_id == client_command_id
                    )
                ).scalar_one_or_none()
                if replay is not None and replay.request_fingerprint == fingerprint:
                    return replay
                raise GoodsReceiptCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
            if constraint == "ux_inventory_lots_tenant_item_manufacturer_identity":
                if attempt < max_attempts:
                    continue
                raise ConflictingInventoryLotIdentityError(str(exc)) from exc
            if constraint and "seed_lot" in constraint.lower():
                raise DuplicateSeedLotCodeError(str(exc)) from exc
            raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="goods_receipt.posted",
        entity_type="goods_receipt", entity_id=receipt.id,
        event_data={"code": receipt.code, "farm_id": str(farm_id), "lines": line_summaries},
    )
    db.commit()
    db.refresh(receipt)
    return receipt


def _next_receipt_code(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, farm_code: str) -> str:
    from sqlalchemy import func

    db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(f"goods_receipt_code:{farm_id}", 0))))
    today = datetime.now(timezone.utc).date()
    prefix = f"GR-{farm_code}-{today:%Y%m%d}"
    count = db.execute(
        select(func.count()).select_from(GoodsReceipt).where(
            GoodsReceipt.farm_id == farm_id, GoodsReceipt.code.like(f"{prefix}-%")
        )
    ).scalar_one()
    return f"{prefix}-{count + 1:03d}"


def get_goods_receipt(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, receipt_id: uuid.UUID) -> GoodsReceipt:
    receipt = db.execute(
        select(GoodsReceipt).where(
            GoodsReceipt.id == receipt_id, GoodsReceipt.tenant_id == tenant_id, GoodsReceipt.farm_id == farm_id
        )
    ).scalar_one_or_none()
    if receipt is None:
        raise GoodsReceiptNotFoundError(str(receipt_id))
    return receipt


def list_goods_receipts(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> list[GoodsReceipt]:
    return list(
        db.execute(
            select(GoodsReceipt)
            .where(GoodsReceipt.tenant_id == tenant_id, GoodsReceipt.farm_id == farm_id)
            .order_by(GoodsReceipt.received_at.desc())
        ).scalars()
    )
