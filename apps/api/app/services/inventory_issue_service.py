"""STORE-INV-003: Issue -- a CUSTODY TRANSFER, Store Bin custody -> "Issued
to operations" custody (`docs/domain/STORE_INVENTORY_MODEL.md` §10). Never
touches Existence or Quality, never creates a Batch/Work Order. Serves BOTH
"Direct Issue" (operator picks the physical source directly) and "Issue
against Reservation" (one or more lines each optionally pin a
`reservation_line_id`) through the same command -- the business rules
overlap almost entirely (usable cohort, sufficient Bin balance, active Bin),
and the two flows differ only in whether a line ALSO debits a Reservation
line's own remaining claim in the same transaction.

One `InventoryStorageMovement` row (`movement_kind = 'issue'`) per Issue
line -- that row IS the Issue line, so nothing is ever double-counted
between Bin custody / "Not put away" / "Issued to operations"
(`inventory_availability_service`). Mirrors `InventoryQualityCommand`'s own
"header written once, before any child event row" shape: this command
writes the `InventoryIssue` header first (idempotent on
`(tenant_id, client_command_id)`), then fans out to N movement rows (each
composed with `client_command_id = NULL`, mirroring `split_out`/`split_in`),
optionally paired with an `InventoryReservationLineEntry` (`entry_kind =
'issue'`) in the very same transaction."""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.inventory_issue import InventoryIssue
from app.models.inventory_lot import InventoryLot
from app.models.inventory_reservation_line_entry import InventoryReservationLineEntry
from app.models.inventory_storage_movement import InventoryStorageMovement
from app.services import inventory_availability_service, inventory_quality_service
from app.services.audit import append_audit_event
from app.services.errors import (
    InactiveStorageBinError,
    InsufficientAvailableToIssueError,
    InsufficientReservationBalanceError,
    InsufficientStorageBinBalanceError,
    InventoryIssueCommandReusedWithDifferentPayloadError,
    InventoryIssueLineValidationError,
    InventoryIssueNotFoundError,
    InventoryIssueSourceNotUsableError,
    InventoryQuantityCohortNotFoundError,
    InventoryReservationLineNotFoundError,
    InventoryReservationNotFoundError,
    ReservationLineItemMismatchError,
    TooManyInventoryIssueLinesError,
)
from app.services.inventory_existence_ledger_service import _lock_cohort, get_cohort_bin_balance
from app.services.inventory_reservation_service import (
    _get_farm,
    _lock_item_farm_availability_for_many,
    _lock_reservation_line,
    get_reservation,
    get_reservation_line_remaining,
)
from app.services.inventory_storage_service import _lock_bin

MAX_ISSUE_LINES = 50


@dataclass(frozen=True)
class IssueLineInput:
    inventory_item_id: uuid.UUID
    inventory_quantity_cohort_id: uuid.UUID
    source_location_id: uuid.UUID
    quantity: Decimal
    reservation_line_id: uuid.UUID | None = None


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _find_issue_by_command(db: Session, *, tenant_id: uuid.UUID, client_command_id: uuid.UUID) -> InventoryIssue | None:
    return db.execute(
        select(InventoryIssue).where(
            InventoryIssue.tenant_id == tenant_id, InventoryIssue.client_command_id == client_command_id
        )
    ).scalar_one_or_none()


def _compute_issue_fingerprint(
    *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, farm_id: uuid.UUID, purpose: str, effective_time: datetime,
    reservation_id: uuid.UUID | None, lines: list[IssueLineInput],
) -> str:
    parts = [
        str(tenant_id), str(actor_user_id), str(farm_id), purpose, effective_time.isoformat(), str(reservation_id or ""),
    ]
    for line in lines:
        parts.extend([
            str(line.inventory_item_id), str(line.inventory_quantity_cohort_id), str(line.source_location_id),
            str(line.quantity), str(line.reservation_line_id or ""),
        ])
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _next_issue_code(db: Session, *, farm_id: uuid.UUID, farm_code: str) -> str:
    db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(f"inventory_issue_code:{farm_id}", 0))))
    today = datetime.now(timezone.utc).date()
    prefix = f"ISS-{farm_code}-{today:%Y%m%d}"
    count = db.execute(
        select(func.count()).select_from(InventoryIssue).where(
            InventoryIssue.farm_id == farm_id, InventoryIssue.code.like(f"{prefix}-%")
        )
    ).scalar_one()
    return f"{prefix}-{count + 1:03d}"


def _cohort_is_usable(db: Session, *, tenant_id: uuid.UUID, cohort, as_of: date) -> bool:
    state = inventory_quality_service.resolve_current_state(db, tenant_id=tenant_id, cohort_id=cohort.id)
    if state not in inventory_quality_service.USABLE_STATES:
        return False
    if cohort.inventory_lot_id is not None:
        expiry = db.execute(
            select(InventoryLot.expiry_date).where(InventoryLot.id == cohort.inventory_lot_id)
        ).scalar_one_or_none()
        if expiry is not None and expiry < as_of:
            return False
    return True


def record_issue(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_command_id: uuid.UUID,
    purpose: str,
    effective_time: datetime,
    lines: list[IssueLineInput],
    reservation_id: uuid.UUID | None = None,
) -> InventoryIssue:
    if not lines:
        raise InventoryIssueLineValidationError("an issue must have at least one line")
    if len(lines) > MAX_ISSUE_LINES:
        raise TooManyInventoryIssueLinesError(str(len(lines)))
    for line in lines:
        if line.quantity <= 0:
            raise InventoryIssueLineValidationError("every issue line quantity must be positive")

    fingerprint = _compute_issue_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, farm_id=farm_id, purpose=purpose,
        effective_time=effective_time, reservation_id=reservation_id, lines=lines,
    )

    existing = _find_issue_by_command(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise InventoryIssueCommandReusedWithDifferentPayloadError(str(client_command_id))

    farm = _get_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    item_ids = {line.inventory_item_id for line in lines}
    _lock_item_farm_availability_for_many(db, tenant_id=tenant_id, farm_id=farm_id, inventory_item_ids=item_ids)

    existing = _find_issue_by_command(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise InventoryIssueCommandReusedWithDifferentPayloadError(str(client_command_id))

    if reservation_id is not None:
        reservation = get_reservation(db, tenant_id=tenant_id, reservation_id=reservation_id)
        if reservation.farm_id != farm_id:
            raise InventoryReservationNotFoundError(str(reservation_id))

    as_of = effective_time.date() if effective_time.tzinfo is None else effective_time.astimezone().date()

    # Tracks quantity already claimed by an EARLIER line in this same
    # command, per (cohort, bin) and per reservation line -- each
    # `get_cohort_bin_balance`/`get_reservation_line_remaining` read below
    # reflects the pre-transaction balance (nothing from this command has
    # been inserted yet), so two lines racing the SAME source or the SAME
    # reservation line within one multi-line command must be checked
    # cumulatively here, not merely each against the same stale snapshot.
    claimed_from_bin: dict[tuple[uuid.UUID, uuid.UUID], Decimal] = {}
    claimed_from_reservation_line: dict[uuid.UUID, Decimal] = {}

    for line in lines:
        cohort = _lock_cohort(db, tenant_id=tenant_id, cohort_id=line.inventory_quantity_cohort_id)
        if cohort.receiving_farm_id != farm_id or cohort.inventory_item_id != line.inventory_item_id:
            raise InventoryQuantityCohortNotFoundError(str(line.inventory_quantity_cohort_id))

        bin_ = _lock_bin(db, tenant_id=tenant_id, farm_id=farm_id, location_id=line.source_location_id)
        if bin_.status != "active":
            raise InactiveStorageBinError(str(line.source_location_id))

        if not _cohort_is_usable(db, tenant_id=tenant_id, cohort=cohort, as_of=as_of):
            raise InventoryIssueSourceNotUsableError(str(line.inventory_quantity_cohort_id))

        bin_key = (cohort.id, line.source_location_id)
        bin_balance = get_cohort_bin_balance(db, cohort_id=cohort.id, location_id=line.source_location_id)
        already_claimed = claimed_from_bin.get(bin_key, Decimal("0"))
        if already_claimed + line.quantity > bin_balance:
            raise InsufficientStorageBinBalanceError(
                f"requested quantity {line.quantity} exceeds bin balance {bin_balance} for cohort {cohort.id} "
                f"(already {already_claimed} claimed by an earlier line in this same command)"
            )
        claimed_from_bin[bin_key] = already_claimed + line.quantity

        if line.reservation_line_id is not None:
            reservation_line = _lock_reservation_line(db, tenant_id=tenant_id, line_id=line.reservation_line_id)
            if reservation_line.inventory_item_id != line.inventory_item_id:
                raise ReservationLineItemMismatchError(str(line.reservation_line_id))
            source_reservation = get_reservation(db, tenant_id=tenant_id, reservation_id=reservation_line.reservation_id)
            if source_reservation.farm_id != farm_id:
                raise InventoryReservationLineNotFoundError(str(line.reservation_line_id))
            remaining = get_reservation_line_remaining(db, reservation_line_id=reservation_line.id)
            already_claimed_from_reservation = claimed_from_reservation_line.get(reservation_line.id, Decimal("0"))
            if already_claimed_from_reservation + line.quantity > remaining:
                raise InsufficientReservationBalanceError(
                    f"issue quantity {line.quantity} exceeds remaining reservation balance {remaining} for line "
                    f"{reservation_line.id} (already {already_claimed_from_reservation} claimed by an earlier line "
                    "in this same command)"
                )
            claimed_from_reservation_line[reservation_line.id] = already_claimed_from_reservation + line.quantity

    direct_totals: dict[uuid.UUID, Decimal] = {}
    for line in lines:
        if line.reservation_line_id is None:
            direct_totals[line.inventory_item_id] = direct_totals.get(line.inventory_item_id, Decimal("0")) + line.quantity
    for item_id, total_direct in direct_totals.items():
        available = inventory_availability_service.get_item_available_to_issue(
            db, tenant_id=tenant_id, farm_id=farm_id, inventory_item_id=item_id
        )
        if total_direct > available:
            raise InsufficientAvailableToIssueError(
                f"direct issue quantity {total_direct} for item {item_id} exceeds available-to-issue {available} "
                f"at farm {farm_id}"
            )

    code = _next_issue_code(db, farm_id=farm_id, farm_code=farm.code)
    recorded_time = datetime.now(effective_time.tzinfo or timezone.utc)
    issue = InventoryIssue(
        id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, code=code, purpose=purpose,
        issued_by_user_id=actor_user_id, effective_time=effective_time, recorded_time=recorded_time,
        reservation_id=reservation_id, client_command_id=client_command_id, request_fingerprint=fingerprint,
    )
    db.add(issue)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_inventory_issues_tenant_client_command_id":
            replay = _find_issue_by_command(db, tenant_id=tenant_id, client_command_id=client_command_id)
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise InventoryIssueCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    for line in lines:
        movement = InventoryStorageMovement(
            id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id,
            inventory_quantity_cohort_id=line.inventory_quantity_cohort_id, movement_kind="issue",
            source_location_id=line.source_location_id, destination_location_id=None,
            moved_quantity_base=line.quantity, effective_time=effective_time, recorded_time=recorded_time,
            actor_user_id=actor_user_id, client_command_id=None, request_fingerprint=None,
            issue_id=issue.id, reservation_line_id=line.reservation_line_id,
        )
        db.add(movement)
        db.flush()

        if line.reservation_line_id is not None:
            reservation_entry = InventoryReservationLineEntry(
                id=uuid.uuid4(), tenant_id=tenant_id, reservation_line_id=line.reservation_line_id,
                entry_kind="issue", quantity_base=line.quantity, effective_time=effective_time,
                recorded_time=recorded_time, actor_user_id=actor_user_id, reason=None, issue_id=issue.id,
                client_command_id=None, request_fingerprint=None,
            )
            db.add(reservation_entry)
            db.flush()

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="inventory_issue.recorded",
        entity_type="inventory_issue", entity_id=issue.id,
        event_data={
            "farm_id": str(farm_id), "purpose": purpose, "reservation_id": str(reservation_id) if reservation_id else None,
            "lines": [
                {
                    "inventory_item_id": str(line.inventory_item_id),
                    "inventory_quantity_cohort_id": str(line.inventory_quantity_cohort_id),
                    "source_location_id": str(line.source_location_id), "quantity": str(line.quantity),
                    "reservation_line_id": str(line.reservation_line_id) if line.reservation_line_id else None,
                }
                for line in lines
            ],
        },
    )
    db.commit()
    db.refresh(issue)
    return issue


# --- Reads -------------------------------------------------------------------


def get_issue(db: Session, *, tenant_id: uuid.UUID, issue_id: uuid.UUID) -> InventoryIssue:
    issue = db.execute(
        select(InventoryIssue).where(InventoryIssue.id == issue_id, InventoryIssue.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if issue is None:
        raise InventoryIssueNotFoundError(str(issue_id))
    return issue


def list_issue_lines(db: Session, *, tenant_id: uuid.UUID, issue_id: uuid.UUID) -> list[InventoryStorageMovement]:
    return list(
        db.execute(
            select(InventoryStorageMovement).where(
                InventoryStorageMovement.tenant_id == tenant_id, InventoryStorageMovement.issue_id == issue_id
            )
        ).scalars()
    )


def list_issues_for_farm(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> list[InventoryIssue]:
    return list(
        db.execute(
            select(InventoryIssue)
            .where(InventoryIssue.tenant_id == tenant_id, InventoryIssue.farm_id == farm_id)
            .order_by(InventoryIssue.recorded_time.desc())
        ).scalars()
    )
