"""STORE-INV-002B: physical custody / putaway for quantity-bearing
consumable Inventory (`docs/domain/STORE_INVENTORY_MODEL.md` §8B). NOT the
identity-based Asset/Carrier Occupancy/Movement engine -- Assets and
reusable Carriers continue using that engine unchanged; this is a separate
quantity-bearing custody model scoped to `InventoryQuantityCohort`.

Mirrors `finished_goods_storage_service.py`'s own proven shape: one
immutable, insert-only movement table (`InventoryStorageMovement`);
balance always `SUM`-derived; the cohort row is the lock target (reusing
`.1`'s own `_lock_cohort`/`get_cohort_balance`, never `InventoryLot`).

Putaway/transfer never change `InventoryExistenceLedgerEntry` balances or
Quality disposition -- existence, custody, and usability remain three
separate questions, never collapsed."""

import hashlib
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.goods_receipt import GoodsReceipt
from app.models.goods_receipt_line import GoodsReceiptLine
from app.models.inventory_item import InventoryItem
from app.models.inventory_lot import InventoryLot
from app.models.inventory_material_event import InventoryMaterialEvent
from app.models.inventory_quantity_cohort import InventoryQuantityCohort
from app.models.inventory_storage_movement import InventoryStorageMovement
from app.models.location import Location
from app.models.location_type import LocationType
from app.services.audit import append_audit_event
from app.services.errors import (
    IneligibleStorageBinError,
    InactiveStorageBinError,
    InsufficientNotPutAwayQuantityError,
    InsufficientStorageBinBalanceError,
    InventoryStorageCommandReusedWithDifferentPayloadError,
    StorageBinNotFoundError,
    StorageBinsMustDifferError,
)
from app.services.inventory_existence_ledger_service import (
    _lock_cohort,
    get_cohort,
    get_cohort_balance,
    get_cohort_bin_balance,
    get_cohort_total_custody,
)

STORE_BIN_LOCATION_TYPE_CODE = "store_bin"


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _lock_bin(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, location_id: uuid.UUID) -> Location:
    row = db.execute(
        select(Location, LocationType.code)
        .join(LocationType, LocationType.id == Location.location_type_id)
        .where(Location.id == location_id, Location.tenant_id == tenant_id, Location.farm_id == farm_id)
        .with_for_update(of=Location)
    ).first()
    if row is None:
        raise StorageBinNotFoundError(str(location_id))
    location, type_code = row
    if type_code != STORE_BIN_LOCATION_TYPE_CODE:
        raise IneligibleStorageBinError(str(location_id))
    return location


def _find_by_command(db: Session, *, tenant_id: uuid.UUID, client_command_id: uuid.UUID) -> InventoryStorageMovement | None:
    return db.execute(
        select(InventoryStorageMovement).where(
            InventoryStorageMovement.tenant_id == tenant_id,
            InventoryStorageMovement.client_command_id == client_command_id,
        )
    ).scalar_one_or_none()


def _compute_fingerprint(
    *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, cohort_id: uuid.UUID, movement_kind: str,
    source_location_id: uuid.UUID | None, destination_location_id: uuid.UUID | None, quantity: Decimal,
    effective_time: datetime, note: str | None,
) -> str:
    parts = [
        str(tenant_id), str(actor_user_id), str(cohort_id), movement_kind, str(source_location_id or ""),
        str(destination_location_id or ""), str(quantity), effective_time.isoformat(), note or "",
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


# --- Commands ------------------------------------------------------------------


def record_putaway(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_command_id: uuid.UUID,
    cohort_id: uuid.UUID,
    destination_location_id: uuid.UUID,
    quantity: Decimal,
    effective_time: datetime,
    note: str | None = None,
) -> InventoryStorageMovement:
    """"Not put away" quantity -> a Store Bin. Existence-neutral,
    Quality-neutral -- quarantined/held/rejected material may be freely
    put away."""
    if quantity <= 0:
        raise InsufficientNotPutAwayQuantityError("quantity must be positive")

    fingerprint = _compute_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, cohort_id=cohort_id, movement_kind="putaway",
        source_location_id=None, destination_location_id=destination_location_id, quantity=quantity,
        effective_time=effective_time, note=note,
    )

    existing = _find_by_command(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise InventoryStorageCommandReusedWithDifferentPayloadError(str(client_command_id))

    cohort = _lock_cohort(db, tenant_id=tenant_id, cohort_id=cohort_id)
    if cohort.receiving_farm_id != farm_id:
        raise StorageBinNotFoundError(str(destination_location_id))
    bin_ = _lock_bin(db, tenant_id=tenant_id, farm_id=farm_id, location_id=destination_location_id)
    if bin_.status != "active":
        raise InactiveStorageBinError(str(destination_location_id))

    existing = _find_by_command(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise InventoryStorageCommandReusedWithDifferentPayloadError(str(client_command_id))

    balance = get_cohort_balance(db, cohort_id=cohort.id)
    total_custody = get_cohort_total_custody(db, cohort_id=cohort.id)
    not_put_away = balance - total_custody
    if quantity > not_put_away:
        raise InsufficientNotPutAwayQuantityError(
            f"requested quantity {quantity} exceeds not-put-away quantity {not_put_away} for cohort {cohort_id}"
        )

    movement = InventoryStorageMovement(
        id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, inventory_quantity_cohort_id=cohort.id,
        movement_kind="putaway", source_location_id=None, destination_location_id=destination_location_id,
        moved_quantity_base=quantity, effective_time=effective_time, actor_user_id=actor_user_id,
        client_command_id=client_command_id, request_fingerprint=fingerprint, note=note,
    )
    return _commit_movement(db, movement, fingerprint=fingerprint, client_command_id=client_command_id, audit_action="inventory_custody.putaway")


def record_transfer(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_command_id: uuid.UUID,
    cohort_id: uuid.UUID,
    source_location_id: uuid.UUID,
    destination_location_id: uuid.UUID,
    quantity: Decimal,
    effective_time: datetime,
    note: str | None = None,
) -> InventoryStorageMovement:
    """Store Bin A -> Store Bin B, within the SAME Farm. Existence-neutral,
    Quality-neutral. Cross-Farm transfer is out of scope -- both Bins are
    resolved against this exact `farm_id`, so a cross-Farm request simply
    cannot resolve a location and fails as not-found."""
    if source_location_id == destination_location_id:
        raise StorageBinsMustDifferError("source and destination bins must differ")
    if quantity <= 0:
        raise InsufficientStorageBinBalanceError("quantity must be positive")

    fingerprint = _compute_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, cohort_id=cohort_id, movement_kind="transfer",
        source_location_id=source_location_id, destination_location_id=destination_location_id, quantity=quantity,
        effective_time=effective_time, note=note,
    )

    existing = _find_by_command(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise InventoryStorageCommandReusedWithDifferentPayloadError(str(client_command_id))

    cohort = _lock_cohort(db, tenant_id=tenant_id, cohort_id=cohort_id)
    if cohort.receiving_farm_id != farm_id:
        raise StorageBinNotFoundError(str(source_location_id))

    # Deterministic sorted-UUID lock order -- matches the DB trigger's own
    # ordering exactly, avoiding a transfer-vs-transfer deadlock.
    first_id, second_id = sorted((source_location_id, destination_location_id))
    bins_by_id = {
        first_id: _lock_bin(db, tenant_id=tenant_id, farm_id=farm_id, location_id=first_id),
        second_id: _lock_bin(db, tenant_id=tenant_id, farm_id=farm_id, location_id=second_id),
    }
    dest_bin = bins_by_id[destination_location_id]
    if dest_bin.status != "active":
        raise InactiveStorageBinError(str(destination_location_id))

    existing = _find_by_command(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise InventoryStorageCommandReusedWithDifferentPayloadError(str(client_command_id))

    source_balance = get_cohort_bin_balance(db, cohort_id=cohort.id, location_id=source_location_id)
    if quantity > source_balance:
        raise InsufficientStorageBinBalanceError(
            f"requested quantity {quantity} exceeds bin balance {source_balance} for cohort {cohort_id}"
        )

    movement = InventoryStorageMovement(
        id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, inventory_quantity_cohort_id=cohort.id,
        movement_kind="transfer", source_location_id=source_location_id,
        destination_location_id=destination_location_id, moved_quantity_base=quantity, effective_time=effective_time,
        actor_user_id=actor_user_id, client_command_id=client_command_id, request_fingerprint=fingerprint, note=note,
    )
    return _commit_movement(db, movement, fingerprint=fingerprint, client_command_id=client_command_id, audit_action="inventory_custody.transferred")


def _commit_movement(
    db: Session, movement: InventoryStorageMovement, *, fingerprint: str, client_command_id: uuid.UUID,
    audit_action: str,
) -> InventoryStorageMovement:
    db.add(movement)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_inventory_storage_movements_tenant_client_command_id":
            replay = _find_by_command(db, tenant_id=movement.tenant_id, client_command_id=client_command_id)
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise InventoryStorageCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=movement.tenant_id, actor_user_id=movement.actor_user_id, action=audit_action,
        entity_type="inventory_storage_movement", entity_id=movement.id,
        event_data={
            "cohort_id": str(movement.inventory_quantity_cohort_id),
            "source_location_id": str(movement.source_location_id) if movement.source_location_id else None,
            "destination_location_id": str(movement.destination_location_id) if movement.destination_location_id else None,
            "quantity": str(movement.moved_quantity_base),
        },
    )
    db.commit()
    db.refresh(movement)
    return movement


def split_custody_core(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    farm_id: uuid.UUID,
    source_cohort_id: uuid.UUID,
    child_cohort_id: uuid.UUID,
    location_id: uuid.UUID,
    quantity: Decimal,
    effective_time: datetime,
) -> None:
    """Composable internal primitive (no commit, no audit) called by
    `inventory_quality_service` in the SAME transaction as a partial
    Quality command that acts against a specific Bin bucket -- a logical
    custody reclassification, never a physical move: the Bin's own total
    is unchanged (one `split_out` debiting the parent, one `split_in`
    crediting the child, both in this exact Bin). The caller is
    responsible for validating the requested quantity against the
    parent's own balance in this Bin BEFORE calling this -- this function
    still re-validates via the DB trigger as defense-in-depth."""
    recorded_time = datetime.now(effective_time.tzinfo or timezone.utc)
    split_out = InventoryStorageMovement(
        id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, inventory_quantity_cohort_id=source_cohort_id,
        movement_kind="split_out", source_location_id=location_id, destination_location_id=None,
        moved_quantity_base=quantity, effective_time=effective_time, recorded_time=recorded_time,
        actor_user_id=actor_user_id, client_command_id=None, request_fingerprint=None,
    )
    db.add(split_out)
    db.flush()

    split_in = InventoryStorageMovement(
        id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, inventory_quantity_cohort_id=child_cohort_id,
        movement_kind="split_in", source_location_id=None, destination_location_id=location_id,
        moved_quantity_base=quantity, effective_time=effective_time, recorded_time=recorded_time,
        actor_user_id=actor_user_id, client_command_id=None, request_fingerprint=None,
    )
    db.add(split_in)
    db.flush()


# --- Reads -----------------------------------------------------------------


def _cohort_settled_from_issued(db: Session, *, cohort_id: uuid.UUID) -> Decimal:
    """STORE-INV-004: total Consumption + Scrap-from-issued ever settled
    against this cohort's own Issue lines -- reduces Existence without
    touching `get_cohort_total_custody`'s own formula, so it must be added
    back explicitly wherever "Not put away" is derived from those two
    (see `get_cohort_not_put_away`)."""
    return db.execute(
        select(func.coalesce(func.sum(InventoryMaterialEvent.quantity_base), 0)).where(
            InventoryMaterialEvent.inventory_quantity_cohort_id == cohort_id,
            InventoryMaterialEvent.source_kind == "issued",
            InventoryMaterialEvent.event_kind.in_(("consumption", "scrap")),
        )
    ).scalar_one()


def get_cohort_not_put_away(db: Session, *, tenant_id: uuid.UUID, cohort_id: uuid.UUID) -> Decimal:
    """`existence - in-Store - issued-to-operations` (docs' own formula),
    computed here as `(existence - total_custody) + settled-from-issued` --
    algebraically identical (STORE-INV-004 keeps `total_custody` and
    `issued`/`returned` movement-only, so Consumption/Scrap-from-issued,
    which touch existence but no movement row, must be added back to
    avoid double-subtracting them)."""
    balance = get_cohort_balance(db, cohort_id=cohort_id)
    total_custody = get_cohort_total_custody(db, cohort_id=cohort_id)
    settled_from_issued = _cohort_settled_from_issued(db, cohort_id=cohort_id)
    return balance - total_custody + settled_from_issued


def get_cohort_bucket_breakdown(db: Session, *, tenant_id: uuid.UUID, cohort_id: uuid.UUID) -> list[dict]:
    """Every eligible physical bucket for this cohort -- "Not put away"
    (if positive) plus one row per Bin with a positive balance. Feeds the
    Quality partial-action "Affected location" selector: auto-selected
    when there is exactly one eligible bucket, shown as a compact dropdown
    otherwise (docs §11's partial-quality/custody integration seam).

    Tenant ownership of `cohort_id` is established FIRST via the shared
    `get_cohort` accessor (read-only -- no lock taken for this GET); every
    balance/bucket computation below only ever runs against a cohort
    already proven to belong to `tenant_id`."""
    cohort = get_cohort(db, tenant_id=tenant_id, cohort_id=cohort_id)

    buckets: list[dict] = []
    not_put_away = get_cohort_not_put_away(db, tenant_id=tenant_id, cohort_id=cohort.id)
    if not_put_away > 0:
        buckets.append({"location_id": None, "label": "Not put away", "balance": not_put_away})

    rows = db.execute(
        select(
            InventoryStorageMovement.source_location_id, InventoryStorageMovement.destination_location_id,
            InventoryStorageMovement.moved_quantity_base,
        ).where(
            InventoryStorageMovement.tenant_id == tenant_id,
            InventoryStorageMovement.inventory_quantity_cohort_id == cohort.id,
        )
    ).all()
    per_bin: dict[uuid.UUID, Decimal] = {}
    for src, dest, qty in rows:
        if dest is not None:
            per_bin[dest] = per_bin.get(dest, Decimal(0)) + qty
        if src is not None:
            per_bin[src] = per_bin.get(src, Decimal(0)) - qty
    bin_ids = [loc_id for loc_id, bal in per_bin.items() if bal > 0]
    if bin_ids:
        locations = {
            loc.id: loc
            for loc in db.execute(select(Location).where(Location.id.in_(bin_ids))).scalars()
        }
        for loc_id in bin_ids:
            loc = locations.get(loc_id)
            label = loc.name if loc is not None else str(loc_id)
            buckets.append({"location_id": loc_id, "label": label, "balance": per_bin[loc_id]})
    return buckets


def list_not_put_away_queue(db: Session, *, tenant_id: uuid.UUID) -> list[dict]:
    """Every cohort with a positive not-put-away quantity, company-wide,
    with enough denormalized context for the Putaway screen -- mirrors
    `inventory_quality_service.list_quality_work_queue`'s own shape."""
    rows = db.execute(
        select(
            InventoryQuantityCohort.id,
            InventoryQuantityCohort.inventory_item_id,
            InventoryItem.name.label("item_name"),
            InventoryItem.base_uom_id,
            InventoryQuantityCohort.inventory_lot_id,
            InventoryLot.manufacturer_lot_reference,
            InventoryQuantityCohort.receiving_farm_id,
            GoodsReceipt.code.label("receipt_code"),
            GoodsReceipt.received_at.label("receipt_received_at"),
        )
        .select_from(InventoryQuantityCohort)
        .join(InventoryItem, InventoryItem.id == InventoryQuantityCohort.inventory_item_id)
        .outerjoin(InventoryLot, InventoryLot.id == InventoryQuantityCohort.inventory_lot_id)
        .join(GoodsReceiptLine, GoodsReceiptLine.id == InventoryQuantityCohort.source_goods_receipt_line_id)
        .join(GoodsReceipt, GoodsReceipt.id == GoodsReceiptLine.goods_receipt_id)
        .where(InventoryQuantityCohort.tenant_id == tenant_id)
        .order_by(GoodsReceipt.received_at.desc())
    ).all()

    queue: list[dict] = []
    for row in rows:
        not_put_away = get_cohort_not_put_away(db, tenant_id=tenant_id, cohort_id=row.id)
        if not_put_away <= 0:
            continue
        queue.append({
            "inventory_quantity_cohort_id": row.id, "inventory_item_id": row.inventory_item_id,
            "item_name": row.item_name, "base_uom_id": row.base_uom_id, "inventory_lot_id": row.inventory_lot_id,
            "manufacturer_lot_reference": row.manufacturer_lot_reference,
            "received_at_farm_id": row.receiving_farm_id, "receipt_code": row.receipt_code,
            "receipt_received_at": row.receipt_received_at, "not_put_away_quantity": not_put_away,
        })
    return queue


def get_item_storage_breakdown(db: Session, *, tenant_id: uuid.UUID, inventory_item_id: uuid.UUID) -> dict:
    """Company-wide "Not put away" total plus a per-Bin breakdown,
    aggregated across every cohort of this item -- feeds the Inventory
    screen's compact custody section."""
    cohort_ids = list(
        db.execute(
            select(InventoryQuantityCohort.id).where(
                InventoryQuantityCohort.tenant_id == tenant_id,
                InventoryQuantityCohort.inventory_item_id == inventory_item_id,
            )
        ).scalars()
    )
    if not cohort_ids:
        return {"not_put_away_quantity": Decimal("0"), "bins": []}

    total_existence = Decimal("0")
    total_custody = Decimal("0")
    total_settled_from_issued = Decimal("0")
    per_bin: dict[uuid.UUID, Decimal] = {}
    for cohort_id in cohort_ids:
        total_existence += get_cohort_balance(db, cohort_id=cohort_id)
        total_custody += get_cohort_total_custody(db, cohort_id=cohort_id)
        total_settled_from_issued += _cohort_settled_from_issued(db, cohort_id=cohort_id)
        rows = db.execute(
            select(
                InventoryStorageMovement.source_location_id, InventoryStorageMovement.destination_location_id,
                InventoryStorageMovement.moved_quantity_base,
            ).where(InventoryStorageMovement.inventory_quantity_cohort_id == cohort_id)
        ).all()
        for src, dest, qty in rows:
            if dest is not None:
                per_bin[dest] = per_bin.get(dest, Decimal(0)) + qty
            if src is not None:
                per_bin[src] = per_bin.get(src, Decimal(0)) - qty

    bin_ids = [loc_id for loc_id, bal in per_bin.items() if bal > 0]
    locations = (
        {loc.id: loc for loc in db.execute(select(Location).where(Location.id.in_(bin_ids))).scalars()}
        if bin_ids else {}
    )
    bins = [
        {"location_id": loc_id, "label": (locations[loc_id].name if loc_id in locations else str(loc_id)), "balance": per_bin[loc_id]}
        for loc_id in bin_ids
    ]
    return {"not_put_away_quantity": total_existence - total_custody + total_settled_from_issued, "bins": bins}
