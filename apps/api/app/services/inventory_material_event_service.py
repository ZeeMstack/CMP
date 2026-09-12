"""STORE-INV-004: Consumption, Return, and Scrap -- completes the
consumable Inventory lifecycle (Receipt -> Putaway -> Reservation -> Issue
-> Consumption/Return/Scrap, `docs/domain/STORE_INVENTORY_MODEL.md`). Never
collapses Existence, physical custody, Reservation, or Issue-line
reconciliation.

**Consumption**: material actually used by farm operations. Acts only on an
Issue line's own outstanding balance, reduces Existence (a `consumption`
`InventoryExistenceLedgerEntry`), never touches physical custody. Blocked
when the source cohort is not currently usable (Quality/expiry) -- Return
and Scrap of the same material remain allowed regardless.

**Return**: unused issued material physically comes back to a Store Bin in
the SAME Farm. Reduces the Issue line's own outstanding balance, increases
Bin custody (a new `return` `InventoryStorageMovement`), never touches
Existence or Quality -- returned held/rejected/expired stock remains
held/rejected/expired.

**Scrap**: material physically ceases to exist, from exactly one of three
truthful source buckets (`source_kind`): an Issue line's own outstanding
balance, a specific Store Bin, or "Not put away". Always reduces Existence
(a `scrap` `InventoryExistenceLedgerEntry`), always carries a mandatory
human-readable reason, and may occur regardless of Quality disposition.

Every command here is its OWN top-level idempotent operator command
(unlike `split_out`/`split_in`/`issue`, none are internally composed by a
larger one), written as a single `InventoryMaterialEvent` row alongside
whichever paired existence-ledger/storage-movement fact it produced, all in
one transaction ending in one commit -- mirrors `inventory_issue_service`'s
own "lock, re-derive, validate, insert" shape throughout."""

import hashlib
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.inventory_existence_ledger_entry import InventoryExistenceLedgerEntry
from app.models.inventory_material_event import InventoryMaterialEvent
from app.models.inventory_storage_movement import InventoryStorageMovement
from app.services import inventory_cohort_accounting_service, inventory_issue_service
from app.services.audit import append_audit_event
from app.services.errors import (
    InactiveStorageBinError,
    InsufficientIssueLineOutstandingError,
    InsufficientNotPutAwayQuantityError,
    InsufficientStorageBinBalanceError,
    InventoryConsumptionSourceNotUsableError,
    InventoryIssueLineNotFoundError,
    InventoryMaterialEventCommandReusedWithDifferentPayloadError,
    InventoryMaterialEventValidationError,
)
from app.services.inventory_existence_ledger_service import (
    _lock_cohort,
    get_cohort_bin_balance,
)
from app.services.inventory_storage_service import _lock_bin

SOURCE_KINDS = ("issued", "store_bin", "not_put_away")


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _find_by_command(db: Session, *, tenant_id: uuid.UUID, client_command_id: uuid.UUID) -> InventoryMaterialEvent | None:
    return db.execute(
        select(InventoryMaterialEvent).where(
            InventoryMaterialEvent.tenant_id == tenant_id, InventoryMaterialEvent.client_command_id == client_command_id
        )
    ).scalar_one_or_none()


def _compute_fingerprint(
    *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, event_kind: str, source_kind: str,
    issue_line_id: uuid.UUID | None, inventory_quantity_cohort_id: uuid.UUID | None,
    source_location_id: uuid.UUID | None, destination_location_id: uuid.UUID | None, quantity: Decimal,
    reason: str | None, effective_time: datetime,
) -> str:
    parts = [
        str(tenant_id), str(actor_user_id), event_kind, source_kind, str(issue_line_id or ""),
        str(inventory_quantity_cohort_id or ""), str(source_location_id or ""), str(destination_location_id or ""),
        str(quantity), reason or "", effective_time.isoformat(),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _lock_issue_line(db: Session, *, tenant_id: uuid.UUID, issue_line_id: uuid.UUID) -> InventoryStorageMovement:
    line = db.execute(
        select(InventoryStorageMovement)
        .where(InventoryStorageMovement.id == issue_line_id, InventoryStorageMovement.tenant_id == tenant_id)
        .with_for_update()
    ).scalar_one_or_none()
    if line is None or line.movement_kind != "issue":
        raise InventoryIssueLineNotFoundError(str(issue_line_id))
    return line


def _issue_line_settled(db: Session, *, issue_line_id: uuid.UUID) -> Decimal:
    return db.execute(
        select(func.coalesce(func.sum(InventoryMaterialEvent.quantity_base), 0)).where(
            InventoryMaterialEvent.issue_line_id == issue_line_id
        )
    ).scalar_one()


def get_issue_line_outstanding(db: Session, *, issue_line: InventoryStorageMovement) -> Decimal:
    return issue_line.moved_quantity_base - _issue_line_settled(db, issue_line_id=issue_line.id)


def _as_of_date(effective_time: datetime) -> date:
    return effective_time.date() if effective_time.tzinfo is None else effective_time.astimezone().date()


# --- Consumption --------------------------------------------------------------


def record_consumption(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_command_id: uuid.UUID,
    issue_line_id: uuid.UUID,
    quantity: Decimal,
    effective_time: datetime,
) -> InventoryMaterialEvent:
    if quantity <= 0:
        raise InventoryMaterialEventValidationError("consumption quantity must be positive")

    fingerprint = _compute_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, event_kind="consumption", source_kind="issued",
        issue_line_id=issue_line_id, inventory_quantity_cohort_id=None, source_location_id=None,
        destination_location_id=None, quantity=quantity, reason=None, effective_time=effective_time,
    )

    def _replay() -> InventoryMaterialEvent | None:
        existing = _find_by_command(db, tenant_id=tenant_id, client_command_id=client_command_id)
        if existing is None:
            return None
        if existing.request_fingerprint == fingerprint:
            return existing
        raise InventoryMaterialEventCommandReusedWithDifferentPayloadError(str(client_command_id))

    replay = _replay()
    if replay is not None:
        return replay

    issue_line = _lock_issue_line(db, tenant_id=tenant_id, issue_line_id=issue_line_id)

    replay = _replay()
    if replay is not None:
        return replay

    cohort = _lock_cohort(db, tenant_id=tenant_id, cohort_id=issue_line.inventory_quantity_cohort_id)

    if not inventory_issue_service._cohort_is_usable(
        db, tenant_id=tenant_id, cohort=cohort, as_of=_as_of_date(effective_time)
    ):
        raise InventoryConsumptionSourceNotUsableError(str(issue_line_id))

    outstanding = get_issue_line_outstanding(db, issue_line=issue_line)
    if quantity > outstanding:
        raise InsufficientIssueLineOutstandingError(
            f"consumption quantity {quantity} exceeds outstanding issued balance {outstanding} for issue line "
            f"{issue_line_id}"
        )

    recorded_time = datetime.now(effective_time.tzinfo or timezone.utc)
    ledger_entry = InventoryExistenceLedgerEntry(
        tenant_id=tenant_id, inventory_quantity_cohort_id=cohort.id, inventory_item_id=cohort.inventory_item_id,
        inventory_lot_id=cohort.inventory_lot_id, receiving_farm_id=cohort.receiving_farm_id,
        entry_kind="consumption", quantity_delta_base=-quantity, effective_time=effective_time,
        recorded_time=recorded_time, actor_user_id=actor_user_id, reason=None,
    )
    db.add(ledger_entry)
    db.flush()

    event = InventoryMaterialEvent(
        id=uuid.uuid4(), tenant_id=tenant_id, farm_id=cohort.receiving_farm_id,
        inventory_quantity_cohort_id=cohort.id, event_kind="consumption", source_kind="issued",
        issue_line_id=issue_line.id, quantity_base=quantity, reason=None, effective_time=effective_time,
        recorded_time=recorded_time, actor_user_id=actor_user_id, existence_ledger_entry_id=ledger_entry.id,
        storage_movement_id=None, client_command_id=client_command_id, request_fingerprint=fingerprint,
    )
    event = _commit_event(db, event, fingerprint=fingerprint, audit_action="inventory_consumption.recorded")
    return event


# --- Return --------------------------------------------------------------------


def record_return(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_command_id: uuid.UUID,
    issue_line_id: uuid.UUID,
    destination_location_id: uuid.UUID,
    quantity: Decimal,
    effective_time: datetime,
) -> InventoryMaterialEvent:
    if quantity <= 0:
        raise InventoryMaterialEventValidationError("return quantity must be positive")

    fingerprint = _compute_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, event_kind="return", source_kind="issued",
        issue_line_id=issue_line_id, inventory_quantity_cohort_id=None, source_location_id=None,
        destination_location_id=destination_location_id, quantity=quantity, reason=None,
        effective_time=effective_time,
    )

    def _replay() -> InventoryMaterialEvent | None:
        existing = _find_by_command(db, tenant_id=tenant_id, client_command_id=client_command_id)
        if existing is None:
            return None
        if existing.request_fingerprint == fingerprint:
            return existing
        raise InventoryMaterialEventCommandReusedWithDifferentPayloadError(str(client_command_id))

    replay = _replay()
    if replay is not None:
        return replay

    issue_line = _lock_issue_line(db, tenant_id=tenant_id, issue_line_id=issue_line_id)

    replay = _replay()
    if replay is not None:
        return replay

    cohort = _lock_cohort(db, tenant_id=tenant_id, cohort_id=issue_line.inventory_quantity_cohort_id)
    bin_ = _lock_bin(db, tenant_id=tenant_id, farm_id=issue_line.farm_id, location_id=destination_location_id)
    if bin_.status != "active":
        raise InactiveStorageBinError(str(destination_location_id))

    outstanding = get_issue_line_outstanding(db, issue_line=issue_line)
    if quantity > outstanding:
        raise InsufficientIssueLineOutstandingError(
            f"return quantity {quantity} exceeds outstanding issued balance {outstanding} for issue line "
            f"{issue_line_id}"
        )

    recorded_time = datetime.now(effective_time.tzinfo or timezone.utc)
    movement = InventoryStorageMovement(
        id=uuid.uuid4(), tenant_id=tenant_id, farm_id=issue_line.farm_id,
        inventory_quantity_cohort_id=cohort.id, movement_kind="return", source_location_id=None,
        destination_location_id=destination_location_id, moved_quantity_base=quantity,
        effective_time=effective_time, recorded_time=recorded_time, actor_user_id=actor_user_id,
        client_command_id=None, request_fingerprint=None, issue_id=None, reservation_line_id=None,
    )
    db.add(movement)
    db.flush()

    event = InventoryMaterialEvent(
        id=uuid.uuid4(), tenant_id=tenant_id, farm_id=cohort.receiving_farm_id,
        inventory_quantity_cohort_id=cohort.id, event_kind="return", source_kind="issued",
        issue_line_id=issue_line.id, destination_location_id=destination_location_id, quantity_base=quantity,
        reason=None, effective_time=effective_time, recorded_time=recorded_time, actor_user_id=actor_user_id,
        existence_ledger_entry_id=None, storage_movement_id=movement.id, client_command_id=client_command_id,
        request_fingerprint=fingerprint,
    )
    event = _commit_event(db, event, fingerprint=fingerprint, audit_action="inventory_return.recorded")
    return event


# --- Scrap -----------------------------------------------------------------------


def record_scrap(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_command_id: uuid.UUID,
    source_kind: str,
    quantity: Decimal,
    reason: str,
    effective_time: datetime,
    issue_line_id: uuid.UUID | None = None,
    inventory_quantity_cohort_id: uuid.UUID | None = None,
    source_location_id: uuid.UUID | None = None,
) -> InventoryMaterialEvent:
    if quantity <= 0:
        raise InventoryMaterialEventValidationError("scrap quantity must be positive")
    if not reason or not reason.strip():
        raise InventoryMaterialEventValidationError("scrap requires a human-readable reason")
    if source_kind not in SOURCE_KINDS:
        raise InventoryMaterialEventValidationError(f"{source_kind!r} is not a valid scrap source")

    if source_kind == "issued":
        if issue_line_id is None or inventory_quantity_cohort_id is not None or source_location_id is not None:
            raise InventoryMaterialEventValidationError("scrap from issued material requires only issue_line_id")
    elif source_kind == "store_bin":
        if inventory_quantity_cohort_id is None or source_location_id is None or issue_line_id is not None:
            raise InventoryMaterialEventValidationError(
                "scrap from a Store Bin requires inventory_quantity_cohort_id and source_location_id"
            )
    else:  # not_put_away
        if inventory_quantity_cohort_id is None or issue_line_id is not None or source_location_id is not None:
            raise InventoryMaterialEventValidationError(
                "scrap from Not put away requires only inventory_quantity_cohort_id"
            )

    fingerprint = _compute_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, event_kind="scrap", source_kind=source_kind,
        issue_line_id=issue_line_id, inventory_quantity_cohort_id=inventory_quantity_cohort_id,
        source_location_id=source_location_id, destination_location_id=None, quantity=quantity, reason=reason,
        effective_time=effective_time,
    )

    def _replay() -> InventoryMaterialEvent | None:
        existing = _find_by_command(db, tenant_id=tenant_id, client_command_id=client_command_id)
        if existing is None:
            return None
        if existing.request_fingerprint == fingerprint:
            return existing
        raise InventoryMaterialEventCommandReusedWithDifferentPayloadError(str(client_command_id))

    replay = _replay()
    if replay is not None:
        return replay

    issue_line: InventoryStorageMovement | None = None
    if source_kind == "issued":
        issue_line = _lock_issue_line(db, tenant_id=tenant_id, issue_line_id=issue_line_id)
        cohort = _lock_cohort(db, tenant_id=tenant_id, cohort_id=issue_line.inventory_quantity_cohort_id)
    else:
        cohort = _lock_cohort(db, tenant_id=tenant_id, cohort_id=inventory_quantity_cohort_id)

    replay = _replay()
    if replay is not None:
        return replay

    recorded_time = datetime.now(effective_time.tzinfo or timezone.utc)
    movement: InventoryStorageMovement | None = None

    if source_kind == "issued":
        outstanding = get_issue_line_outstanding(db, issue_line=issue_line)
        if quantity > outstanding:
            raise InsufficientIssueLineOutstandingError(
                f"scrap quantity {quantity} exceeds outstanding issued balance {outstanding} for issue line "
                f"{issue_line_id}"
            )
    elif source_kind == "store_bin":
        bin_ = _lock_bin(db, tenant_id=tenant_id, farm_id=cohort.receiving_farm_id, location_id=source_location_id)
        bin_balance = get_cohort_bin_balance(db, cohort_id=cohort.id, location_id=source_location_id)
        if quantity > bin_balance:
            raise InsufficientStorageBinBalanceError(
                f"scrap quantity {quantity} exceeds bin balance {bin_balance} for cohort {cohort.id}"
            )
        movement = InventoryStorageMovement(
            id=uuid.uuid4(), tenant_id=tenant_id, farm_id=cohort.receiving_farm_id,
            inventory_quantity_cohort_id=cohort.id, movement_kind="scrap_bin", source_location_id=source_location_id,
            destination_location_id=None, moved_quantity_base=quantity, effective_time=effective_time,
            recorded_time=recorded_time, actor_user_id=actor_user_id, client_command_id=None,
            request_fingerprint=None, issue_id=None, reservation_line_id=None,
        )
        db.add(movement)
        db.flush()
        _ = bin_
    else:  # not_put_away
        # PILOT-BLOCKER-004 F02: `existence - custody`, missing the
        # issued-settlement term, goes stale (over-restrictive) once any
        # issued material has since been consumed/scrapped -- see
        # `inventory_cohort_accounting_service` for the canonical formula.
        not_put_away = inventory_cohort_accounting_service.get_cohort_accounting_snapshot(
            db, cohort_id=cohort.id
        ).not_put_away
        if quantity > not_put_away:
            raise InsufficientNotPutAwayQuantityError(
                f"scrap quantity {quantity} exceeds not-put-away quantity {not_put_away} for cohort {cohort.id}"
            )

    ledger_entry = InventoryExistenceLedgerEntry(
        tenant_id=tenant_id, inventory_quantity_cohort_id=cohort.id, inventory_item_id=cohort.inventory_item_id,
        inventory_lot_id=cohort.inventory_lot_id, receiving_farm_id=cohort.receiving_farm_id, entry_kind="scrap",
        quantity_delta_base=-quantity, effective_time=effective_time, recorded_time=recorded_time,
        actor_user_id=actor_user_id, reason=reason,
    )
    db.add(ledger_entry)
    db.flush()

    event = InventoryMaterialEvent(
        id=uuid.uuid4(), tenant_id=tenant_id, farm_id=cohort.receiving_farm_id,
        inventory_quantity_cohort_id=cohort.id, event_kind="scrap", source_kind=source_kind,
        issue_line_id=issue_line.id if issue_line is not None else None,
        source_location_id=source_location_id if source_kind == "store_bin" else None,
        destination_location_id=None, quantity_base=quantity, reason=reason, effective_time=effective_time,
        recorded_time=recorded_time, actor_user_id=actor_user_id, existence_ledger_entry_id=ledger_entry.id,
        storage_movement_id=movement.id if movement is not None else None, client_command_id=client_command_id,
        request_fingerprint=fingerprint,
    )
    event = _commit_event(db, event, fingerprint=fingerprint, audit_action="inventory_scrap.recorded")
    return event


def _commit_event(
    db: Session, event: InventoryMaterialEvent, *, fingerprint: str, audit_action: str
) -> InventoryMaterialEvent:
    db.add(event)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_inventory_material_events_tenant_client_command_id":
            replay = _find_by_command(db, tenant_id=event.tenant_id, client_command_id=event.client_command_id)
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise InventoryMaterialEventCommandReusedWithDifferentPayloadError(str(event.client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=event.tenant_id, actor_user_id=event.actor_user_id, action=audit_action,
        entity_type="inventory_material_event", entity_id=event.id,
        event_data={
            "source_kind": event.source_kind, "issue_line_id": str(event.issue_line_id) if event.issue_line_id else None,
            "inventory_quantity_cohort_id": str(event.inventory_quantity_cohort_id),
            "source_location_id": str(event.source_location_id) if event.source_location_id else None,
            "destination_location_id": str(event.destination_location_id) if event.destination_location_id else None,
            "quantity": str(event.quantity_base), "reason": event.reason,
        },
    )
    db.commit()
    db.refresh(event)
    return event


# --- Reads -------------------------------------------------------------------


def get_issue_line(db: Session, *, tenant_id: uuid.UUID, issue_line_id: uuid.UUID) -> InventoryStorageMovement:
    line = db.execute(
        select(InventoryStorageMovement).where(
            InventoryStorageMovement.id == issue_line_id, InventoryStorageMovement.tenant_id == tenant_id,
            InventoryStorageMovement.movement_kind == "issue",
        )
    ).scalar_one_or_none()
    if line is None:
        raise InventoryIssueLineNotFoundError(str(issue_line_id))
    return line


def get_issue_line_reconciliation(db: Session, *, tenant_id: uuid.UUID, issue_line_id: uuid.UUID) -> dict:
    """issued / consumed / returned / scrapped / outstanding for one Issue
    line -- always `SUM()` over `InventoryMaterialEvent`, grouped by
    `event_kind`, never a stored aggregate."""
    line = get_issue_line(db, tenant_id=tenant_id, issue_line_id=issue_line_id)
    rows = db.execute(
        select(InventoryMaterialEvent.event_kind, func.coalesce(func.sum(InventoryMaterialEvent.quantity_base), 0))
        .where(InventoryMaterialEvent.issue_line_id == issue_line_id)
        .group_by(InventoryMaterialEvent.event_kind)
    ).all()
    by_kind = {kind: total for kind, total in rows}
    consumed = by_kind.get("consumption", Decimal("0"))
    returned = by_kind.get("return", Decimal("0"))
    scrapped = by_kind.get("scrap", Decimal("0"))
    return {
        "issue_line_id": issue_line_id,
        "issued_quantity": line.moved_quantity_base,
        "consumed_quantity": consumed,
        "returned_quantity": returned,
        "scrapped_quantity": scrapped,
        "outstanding_quantity": line.moved_quantity_base - consumed - returned - scrapped,
    }


def list_material_events_for_issue_line(
    db: Session, *, tenant_id: uuid.UUID, issue_line_id: uuid.UUID
) -> list[InventoryMaterialEvent]:
    return list(
        db.execute(
            select(InventoryMaterialEvent).where(
                InventoryMaterialEvent.tenant_id == tenant_id, InventoryMaterialEvent.issue_line_id == issue_line_id
            ).order_by(InventoryMaterialEvent.recorded_time)
        ).scalars()
    )


def list_outstanding_issued_material(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> list[dict]:
    """Every Issue line at this Farm with a positive outstanding balance --
    feeds the "Issued material" tab. Denormalized with enough context for a
    single compact table row (Issue code / purpose / Item / Lot / Issued /
    Outstanding), mirroring `list_not_put_away_queue`'s own shape."""
    from app.models.inventory_issue import InventoryIssue
    from app.models.inventory_item import InventoryItem
    from app.models.inventory_lot import InventoryLot
    from app.models.inventory_quantity_cohort import InventoryQuantityCohort

    rows = db.execute(
        select(
            InventoryStorageMovement.id, InventoryStorageMovement.moved_quantity_base,
            InventoryStorageMovement.source_location_id, InventoryIssue.id.label("issue_id"),
            InventoryIssue.code.label("issue_code"), InventoryIssue.purpose,
            InventoryQuantityCohort.inventory_item_id, InventoryItem.name.label("item_name"),
            InventoryItem.base_uom_id, InventoryQuantityCohort.inventory_lot_id,
            InventoryLot.manufacturer_lot_reference,
        )
        .select_from(InventoryStorageMovement)
        .join(InventoryIssue, InventoryIssue.id == InventoryStorageMovement.issue_id)
        .join(
            InventoryQuantityCohort,
            InventoryQuantityCohort.id == InventoryStorageMovement.inventory_quantity_cohort_id,
        )
        .join(InventoryItem, InventoryItem.id == InventoryQuantityCohort.inventory_item_id)
        .outerjoin(InventoryLot, InventoryLot.id == InventoryQuantityCohort.inventory_lot_id)
        .where(
            InventoryStorageMovement.tenant_id == tenant_id, InventoryStorageMovement.farm_id == farm_id,
            InventoryStorageMovement.movement_kind == "issue",
        )
        .order_by(InventoryIssue.recorded_time.desc())
    ).all()
    if not rows:
        return []

    line_ids = [row.id for row in rows]
    settled_rows = db.execute(
        select(InventoryMaterialEvent.issue_line_id, func.coalesce(func.sum(InventoryMaterialEvent.quantity_base), 0))
        .where(InventoryMaterialEvent.issue_line_id.in_(line_ids))
        .group_by(InventoryMaterialEvent.issue_line_id)
    ).all()
    settled_by_line = {line_id: total for line_id, total in settled_rows}

    result: list[dict] = []
    for row in rows:
        outstanding = row.moved_quantity_base - settled_by_line.get(row.id, Decimal("0"))
        if outstanding <= 0:
            continue
        result.append({
            "issue_line_id": row.id, "issue_id": row.issue_id, "issue_code": row.issue_code, "purpose": row.purpose,
            "inventory_item_id": row.inventory_item_id, "item_name": row.item_name, "base_uom_id": row.base_uom_id,
            "inventory_lot_id": row.inventory_lot_id, "manufacturer_lot_reference": row.manufacturer_lot_reference,
            "source_location_id": row.source_location_id, "issued_quantity": row.moved_quantity_base,
            "outstanding_quantity": outstanding,
        })
    return result
