"""STORE-INV-003: Reservation -- a fungible CLAIM against usable in-Store
quantity of one `InventoryItem` at one Farm, frozen at FARM + ITEM (never
`InventoryLot`/cohort/Bin, `docs/domain/STORE_INVENTORY_MODEL.md` §9).
Never touches Existence, Quality, or physical custody. Mirrors
`goods_receipt_service`'s own "header + N lines, one command, one atomic
transaction" shape, and `inventory_storage_service`'s own idempotency/
locking conventions.

Concurrency: every command that could change what "Available to issue"
means for a given (tenant, farm, item) -- Reservation create, and (in
`inventory_issue_service`) direct/against-reservation Issue -- first
acquires a `pg_advisory_xact_lock` keyed on exactly that triple, for every
DISTINCT item touched, in deterministic sorted-item-id order. This
serializes the read-check-write race described in docs' concurrency proofs
A/B/D without needing a physical "Item x Farm balance" row to lock."""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.farm import Farm
from app.models.inventory_reservation import InventoryReservation
from app.models.inventory_reservation_line import InventoryReservationLine
from app.models.inventory_reservation_line_entry import InventoryReservationLineEntry
from app.services import inventory_availability_service
from app.services.audit import append_audit_event
from app.services.errors import (
    FarmNotFoundError,
    InsufficientAvailableToIssueError,
    InsufficientReservationBalanceError,
    InventoryReservationCommandReusedWithDifferentPayloadError,
    InventoryReservationLineNotFoundError,
    InventoryReservationNotFoundError,
    InventoryReservationReleaseCommandReusedWithDifferentPayloadError,
)


@dataclass(frozen=True)
class ReservationLineInput:
    inventory_item_id: uuid.UUID
    quantity: Decimal


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _lock_item_farm_availability(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, inventory_item_id: uuid.UUID) -> None:
    db.execute(
        select(
            func.pg_advisory_xact_lock(
                func.hashtextextended(f"inv_reservation_availability:{tenant_id}:{farm_id}:{inventory_item_id}", 0)
            )
        )
    )


def _lock_item_farm_availability_for_many(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, inventory_item_ids: set[uuid.UUID]
) -> None:
    """Deterministic sorted-item-id lock order -- avoids a deadlock between
    two multi-item commands touching overlapping item sets in different
    orders, mirroring `inventory_storage_service.record_transfer`'s own
    sorted-bin-lock idiom."""
    for item_id in sorted(inventory_item_ids, key=str):
        _lock_item_farm_availability(db, tenant_id=tenant_id, farm_id=farm_id, inventory_item_id=item_id)


def _find_reservation_by_command(
    db: Session, *, tenant_id: uuid.UUID, client_command_id: uuid.UUID
) -> InventoryReservation | None:
    return db.execute(
        select(InventoryReservation).where(
            InventoryReservation.tenant_id == tenant_id, InventoryReservation.client_command_id == client_command_id
        )
    ).scalar_one_or_none()


def _compute_reservation_fingerprint(
    *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, farm_id: uuid.UUID, purpose: str, effective_time: datetime,
    lines: list[ReservationLineInput],
) -> str:
    parts = [str(tenant_id), str(actor_user_id), str(farm_id), purpose, effective_time.isoformat()]
    for line in lines:
        parts.extend([str(line.inventory_item_id), str(line.quantity)])
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _next_reservation_code(db: Session, *, farm_id: uuid.UUID, farm_code: str) -> str:
    db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(f"inventory_reservation_code:{farm_id}", 0))))
    today = datetime.now(timezone.utc).date()
    prefix = f"RES-{farm_code}-{today:%Y%m%d}"
    count = db.execute(
        select(func.count()).select_from(InventoryReservation).where(
            InventoryReservation.farm_id == farm_id, InventoryReservation.code.like(f"{prefix}-%")
        )
    ).scalar_one()
    return f"{prefix}-{count + 1:03d}"


def _get_farm(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> Farm:
    farm = db.execute(select(Farm).where(Farm.id == farm_id, Farm.tenant_id == tenant_id)).scalar_one_or_none()
    if farm is None:
        raise FarmNotFoundError(str(farm_id))
    return farm


def create_reservation(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_command_id: uuid.UUID,
    purpose: str,
    effective_time: datetime,
    lines: list[ReservationLineInput],
) -> InventoryReservation:
    if not lines:
        raise InsufficientReservationBalanceError("a reservation must have at least one line")
    for line in lines:
        if line.quantity <= 0:
            raise InsufficientReservationBalanceError("every reservation line quantity must be positive")

    fingerprint = _compute_reservation_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, farm_id=farm_id, purpose=purpose,
        effective_time=effective_time, lines=lines,
    )

    existing = _find_reservation_by_command(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise InventoryReservationCommandReusedWithDifferentPayloadError(str(client_command_id))

    farm = _get_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    requested_by_item: dict[uuid.UUID, Decimal] = {}
    for line in lines:
        requested_by_item[line.inventory_item_id] = requested_by_item.get(line.inventory_item_id, Decimal("0")) + line.quantity
    _lock_item_farm_availability_for_many(db, tenant_id=tenant_id, farm_id=farm_id, inventory_item_ids=set(requested_by_item))

    existing = _find_reservation_by_command(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise InventoryReservationCommandReusedWithDifferentPayloadError(str(client_command_id))

    for item_id, total_requested in requested_by_item.items():
        available = inventory_availability_service.get_item_available_to_issue(
            db, tenant_id=tenant_id, farm_id=farm_id, inventory_item_id=item_id
        )
        if total_requested > available:
            raise InsufficientAvailableToIssueError(
                f"requested quantity {total_requested} for item {item_id} exceeds available-to-issue {available} "
                f"at farm {farm_id}"
            )

    code = _next_reservation_code(db, farm_id=farm_id, farm_code=farm.code)
    recorded_time = datetime.now(effective_time.tzinfo or timezone.utc)
    reservation = InventoryReservation(
        id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, code=code, purpose=purpose,
        requested_by_user_id=actor_user_id, effective_time=effective_time, recorded_time=recorded_time,
        client_command_id=client_command_id, request_fingerprint=fingerprint,
    )
    db.add(reservation)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_inventory_reservations_tenant_client_command_id":
            replay = _find_reservation_by_command(db, tenant_id=tenant_id, client_command_id=client_command_id)
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise InventoryReservationCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    for line in lines:
        db.add(
            InventoryReservationLine(
                id=uuid.uuid4(), tenant_id=tenant_id, reservation_id=reservation.id,
                inventory_item_id=line.inventory_item_id, requested_quantity_base=line.quantity,
            )
        )
    db.flush()

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="inventory_reservation.created",
        entity_type="inventory_reservation", entity_id=reservation.id,
        event_data={
            "farm_id": str(farm_id), "purpose": purpose,
            "lines": [{"inventory_item_id": str(line.inventory_item_id), "quantity": str(line.quantity)} for line in lines],
        },
    )
    db.commit()
    db.refresh(reservation)
    return reservation


def _lock_reservation_line(db: Session, *, tenant_id: uuid.UUID, line_id: uuid.UUID) -> InventoryReservationLine:
    line = db.execute(
        select(InventoryReservationLine)
        .where(InventoryReservationLine.id == line_id, InventoryReservationLine.tenant_id == tenant_id)
        .with_for_update()
    ).scalar_one_or_none()
    if line is None:
        raise InventoryReservationLineNotFoundError(str(line_id))
    return line


def get_reservation_line_remaining(db: Session, *, reservation_line_id: uuid.UUID) -> Decimal:
    debited = db.execute(
        select(func.coalesce(func.sum(InventoryReservationLineEntry.quantity_base), 0)).where(
            InventoryReservationLineEntry.reservation_line_id == reservation_line_id
        )
    ).scalar_one()
    line = db.execute(
        select(InventoryReservationLine.requested_quantity_base).where(InventoryReservationLine.id == reservation_line_id)
    ).scalar_one()
    return line - debited


def _find_release_by_command(
    db: Session, *, tenant_id: uuid.UUID, client_command_id: uuid.UUID
) -> InventoryReservationLineEntry | None:
    return db.execute(
        select(InventoryReservationLineEntry).where(
            InventoryReservationLineEntry.tenant_id == tenant_id,
            InventoryReservationLineEntry.client_command_id == client_command_id,
        )
    ).scalar_one_or_none()


def release_reservation_line(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_command_id: uuid.UUID,
    reservation_line_id: uuid.UUID,
    quantity: Decimal,
    effective_time: datetime,
    reason: str | None = None,
) -> InventoryReservationLineEntry:
    """Releases (part of) the unused CLAIM on one reservation line -- never
    moves stock, never alters Existence/Quality (docs "Reservation
    release"). Full release is simply `quantity == current remaining`."""
    if quantity <= 0:
        raise InsufficientReservationBalanceError("release quantity must be positive")

    fingerprint = hashlib.sha256(
        "|".join([
            str(tenant_id), str(actor_user_id), str(reservation_line_id), str(quantity), effective_time.isoformat(),
            reason or "",
        ]).encode("utf-8")
    ).hexdigest()

    existing = _find_release_by_command(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise InventoryReservationReleaseCommandReusedWithDifferentPayloadError(str(client_command_id))

    line = _lock_reservation_line(db, tenant_id=tenant_id, line_id=reservation_line_id)

    existing = _find_release_by_command(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise InventoryReservationReleaseCommandReusedWithDifferentPayloadError(str(client_command_id))

    remaining = get_reservation_line_remaining(db, reservation_line_id=line.id)
    if quantity > remaining:
        raise InsufficientReservationBalanceError(
            f"release quantity {quantity} exceeds remaining reservation balance {remaining} for line {line.id}"
        )

    entry = InventoryReservationLineEntry(
        id=uuid.uuid4(), tenant_id=tenant_id, reservation_line_id=line.id, entry_kind="release",
        quantity_base=quantity, effective_time=effective_time,
        recorded_time=datetime.now(effective_time.tzinfo or timezone.utc), actor_user_id=actor_user_id, reason=reason,
        client_command_id=client_command_id, request_fingerprint=fingerprint,
    )
    db.add(entry)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_inventory_reservation_line_entries_tenant_client_command_id":
            replay = _find_release_by_command(db, tenant_id=tenant_id, client_command_id=client_command_id)
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise InventoryReservationReleaseCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="inventory_reservation.released",
        entity_type="inventory_reservation_line_entry", entity_id=entry.id,
        event_data={"reservation_line_id": str(line.id), "quantity": str(quantity), "reason": reason},
    )
    db.commit()
    db.refresh(entry)
    return entry


# --- Reads -------------------------------------------------------------------


def get_reservation(db: Session, *, tenant_id: uuid.UUID, reservation_id: uuid.UUID) -> InventoryReservation:
    reservation = db.execute(
        select(InventoryReservation).where(
            InventoryReservation.id == reservation_id, InventoryReservation.tenant_id == tenant_id
        )
    ).scalar_one_or_none()
    if reservation is None:
        raise InventoryReservationNotFoundError(str(reservation_id))
    return reservation


def list_reservation_lines(db: Session, *, tenant_id: uuid.UUID, reservation_id: uuid.UUID) -> list[InventoryReservationLine]:
    return list(
        db.execute(
            select(InventoryReservationLine).where(
                InventoryReservationLine.tenant_id == tenant_id,
                InventoryReservationLine.reservation_id == reservation_id,
            )
        ).scalars()
    )


def list_reservations_for_farm(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> list[InventoryReservation]:
    return list(
        db.execute(
            select(InventoryReservation)
            .where(InventoryReservation.tenant_id == tenant_id, InventoryReservation.farm_id == farm_id)
            .order_by(InventoryReservation.recorded_time.desc())
        ).scalars()
    )


def is_line_blocked_by_quality(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, inventory_item_id: uuid.UUID, remaining: Decimal,
    as_of: date | None = None,
) -> bool:
    """Cheap, deliberately non-priority-aware operator signal (docs "Quality
    x Reservation"): true whenever this line's own remaining claim exceeds
    the Item/Farm's CURRENT usable-in-Store quantity, regardless of what any
    other Reservation for the same Item/Farm currently claims -- never a
    fair-share/priority allocation engine (out of scope, "no automatic lot
    allocation")."""
    if remaining <= 0:
        return False
    usable_in_store = inventory_availability_service.get_item_usable_in_store_quantity(
        db, tenant_id=tenant_id, farm_id=farm_id, inventory_item_id=inventory_item_id, as_of=as_of
    )
    return remaining > usable_in_store
