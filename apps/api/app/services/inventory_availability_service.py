"""STORE-INV-003: read-only derivations answering "how much usable Store
stock is committed?" / "what can still be issued?" / "what has physically
left the Store for farm operations?" -- never a stored aggregate, always
computed live from the existing STORE-INV-002A/002B ledgers plus this
ticket's own Reservation tables (`docs/domain/STORE_INVENTORY_MODEL.md`
§9/§10/§11).

Every quantity here is Farm + Item scoped (Reservation's own frozen
granularity) -- never lot/cohort/Bin. `get_cohort_total_custody`
(STORE-INV-002B, unchanged) deliberately excludes `issue` movements from its
own formula, so "Not put away" (`existence - total_custody`) stays provably
unaffected by Issue; "in Store Bin" quantity is instead `total_custody -
issued` here, and never double-counted against "Issued to operations"."""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.inventory_lot import InventoryLot
from app.models.inventory_material_event import InventoryMaterialEvent
from app.models.inventory_quantity_cohort import InventoryQuantityCohort
from app.models.inventory_reservation import InventoryReservation
from app.models.inventory_reservation_line import InventoryReservationLine
from app.models.inventory_reservation_line_entry import InventoryReservationLineEntry
from app.models.inventory_storage_movement import InventoryStorageMovement
from app.models.location import Location
from app.services import inventory_existence_ledger_service, inventory_quality_service


def _farm_scoped_cohort_ids(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, inventory_item_id: uuid.UUID
) -> list[uuid.UUID]:
    return list(
        db.execute(
            select(InventoryQuantityCohort.id).where(
                InventoryQuantityCohort.tenant_id == tenant_id,
                InventoryQuantityCohort.inventory_item_id == inventory_item_id,
                InventoryQuantityCohort.receiving_farm_id == farm_id,
            )
        ).scalars()
    )


def get_cohort_issued_quantity(db: Session, *, cohort_id: uuid.UUID) -> Decimal:
    """Total quantity of this cohort EVER issued out of Store Bin custody --
    gross, never reduced by a later Return/Consume/Scrap (that reduction is
    `get_cohort_issued_to_operations_quantity`'s own job, STORE-INV-004)."""
    return db.execute(
        select(func.coalesce(func.sum(InventoryStorageMovement.moved_quantity_base), 0)).where(
            InventoryStorageMovement.inventory_quantity_cohort_id == cohort_id,
            InventoryStorageMovement.movement_kind == "issue",
        )
    ).scalar_one()


def get_cohort_returned_quantity(db: Session, *, cohort_id: uuid.UUID) -> Decimal:
    """STORE-INV-004: total quantity of this cohort ever returned from
    "Issued to operations" custody back into a Store Bin."""
    return db.execute(
        select(func.coalesce(func.sum(InventoryStorageMovement.moved_quantity_base), 0)).where(
            InventoryStorageMovement.inventory_quantity_cohort_id == cohort_id,
            InventoryStorageMovement.movement_kind == "return",
        )
    ).scalar_one()


def get_cohort_settled_from_issued_quantity(db: Session, *, cohort_id: uuid.UUID) -> Decimal:
    """STORE-INV-004: total quantity of this cohort's own outstanding
    Issued-to-operations balance ever consumed or scrapped (never Return --
    Return is tracked separately via the physical `return` movement, since
    it also affects "in Store")."""
    return db.execute(
        select(func.coalesce(func.sum(InventoryMaterialEvent.quantity_base), 0)).where(
            InventoryMaterialEvent.inventory_quantity_cohort_id == cohort_id,
            InventoryMaterialEvent.source_kind == "issued",
            InventoryMaterialEvent.event_kind.in_(("consumption", "scrap")),
        )
    ).scalar_one()


def get_cohort_issued_to_operations_quantity(db: Session, *, cohort_id: uuid.UUID) -> Decimal:
    """STORE-INV-004: `issued - returned - consumed - scrapped-from-issued`
    -- the cohort's CURRENT outstanding Issued-to-operations custody, never
    below zero in a healthy system (every settlement is bounded against its
    own Issue line's own outstanding balance, service-layer + trigger)."""
    issued = get_cohort_issued_quantity(db, cohort_id=cohort_id)
    returned = get_cohort_returned_quantity(db, cohort_id=cohort_id)
    settled = get_cohort_settled_from_issued_quantity(db, cohort_id=cohort_id)
    return issued - returned - settled


def get_cohort_in_store_quantity(db: Session, *, cohort_id: uuid.UUID) -> Decimal:
    """This cohort's quantity currently sitting in a Store Bin -- total
    custody (STORE-INV-002B's own formula, STORE-INV-004 additionally
    debiting `scrap_bin`) minus whatever of that has since been issued out,
    plus whatever has since been returned. Consumption and Scrap-from-issued
    never appear here -- neither ever puts material back in a Bin. Never
    negative in a healthy system (Issue/Return's own service-layer +
    trigger checks bound each against its own source balance before
    insert)."""
    total_custody = inventory_existence_ledger_service.get_cohort_total_custody(db, cohort_id=cohort_id)
    issued = get_cohort_issued_quantity(db, cohort_id=cohort_id)
    returned = get_cohort_returned_quantity(db, cohort_id=cohort_id)
    return total_custody - issued + returned


def get_item_usable_in_store_quantity(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, inventory_item_id: uuid.UUID, as_of: date | None = None
) -> Decimal:
    """`SUM`, across every one of this Item's cohorts AT THIS FARM, of
    `min(existence balance, in-Store-Bin quantity)` for whichever cohorts
    are currently usable (RELEASED/HOLD_RELEASED, not expired) --
    deliberately excludes "Not put away" (usability is cohort-level, but
    Reservation/Issue only ever claims quantity that is ALSO already
    physically in a Bin) and excludes already-issued quantity. Mirrors
    `inventory_quality_service.get_item_usable_existence`'s own shape,
    narrowed to one Farm and further narrowed to in-Bin quantity."""
    as_of = as_of or date.today()
    rows = db.execute(
        select(InventoryQuantityCohort.id, InventoryLot.expiry_date)
        .select_from(InventoryQuantityCohort)
        .outerjoin(InventoryLot, InventoryLot.id == InventoryQuantityCohort.inventory_lot_id)
        .where(
            InventoryQuantityCohort.tenant_id == tenant_id,
            InventoryQuantityCohort.inventory_item_id == inventory_item_id,
            InventoryQuantityCohort.receiving_farm_id == farm_id,
        )
    ).all()

    total = Decimal("0")
    for cohort_id, expiry_date in rows:
        if expiry_date is not None and expiry_date < as_of:
            continue
        state = inventory_quality_service.resolve_current_state(db, tenant_id=tenant_id, cohort_id=cohort_id)
        if state not in inventory_quality_service.USABLE_STATES:
            continue
        balance = inventory_existence_ledger_service.get_cohort_balance(db, cohort_id=cohort_id)
        if balance <= 0:
            continue
        in_store = get_cohort_in_store_quantity(db, cohort_id=cohort_id)
        if in_store <= 0:
            continue
        total += min(in_store, balance)
    return total


def get_item_reserved_quantity(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, inventory_item_id: uuid.UUID
) -> Decimal:
    """`SUM` of every active Reservation line's own remaining balance
    (`requested_quantity_base - SUM(entries)`) for this Item at this Farm --
    never a stored aggregate, and never scoped to one Reservation (multiple
    Reservations for the same Item/Farm are fungible against the same pool,
    docs §9)."""
    debits_subq = (
        select(
            InventoryReservationLineEntry.reservation_line_id.label("line_id"),
            func.coalesce(func.sum(InventoryReservationLineEntry.quantity_base), 0).label("debited"),
        )
        .group_by(InventoryReservationLineEntry.reservation_line_id)
        .subquery()
    )
    query = (
        select(
            func.coalesce(
                func.sum(
                    InventoryReservationLine.requested_quantity_base - func.coalesce(debits_subq.c.debited, 0)
                ),
                0,
            )
        )
        .select_from(InventoryReservationLine)
        .join(InventoryReservation, InventoryReservation.id == InventoryReservationLine.reservation_id)
        .outerjoin(debits_subq, debits_subq.c.line_id == InventoryReservationLine.id)
        .where(
            InventoryReservation.tenant_id == tenant_id,
            InventoryReservation.farm_id == farm_id,
            InventoryReservationLine.inventory_item_id == inventory_item_id,
        )
    )
    return db.execute(query).scalar_one()


def get_item_available_to_issue(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, inventory_item_id: uuid.UUID, as_of: date | None = None
) -> Decimal:
    """"Available to issue" (docs §"Available to issue"): usable quantity
    physically held in Store Bins, minus active Reservation quantity, for
    this Item at this Farm. May legitimately be negative -- never clamped
    here -- when a later Quality action removes usability out from under an
    already-committed Reservation (docs §"Quality x Reservation": the
    Reservation itself is never silently reduced); callers presenting this
    to an operator as a headline figure should floor it at zero and rely on
    the per-Reservation "Blocked by quality" signal for the true story."""
    usable_in_store = get_item_usable_in_store_quantity(
        db, tenant_id=tenant_id, farm_id=farm_id, inventory_item_id=inventory_item_id, as_of=as_of
    )
    reserved = get_item_reserved_quantity(db, tenant_id=tenant_id, farm_id=farm_id, inventory_item_id=inventory_item_id)
    return usable_in_store - reserved


def get_item_issued_to_operations_quantity(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, inventory_item_id: uuid.UUID
) -> Decimal:
    """STORE-INV-004: `issued - returned - consumed - scrapped-from-issued`,
    summed across every one of this Item's cohorts at this Farm -- the
    CURRENT outstanding Issued-to-operations custody, never the gross
    ever-issued figure."""
    cohort_ids = _farm_scoped_cohort_ids(db, tenant_id=tenant_id, farm_id=farm_id, inventory_item_id=inventory_item_id)
    if not cohort_ids:
        return Decimal("0")
    total = Decimal("0")
    for cohort_id in cohort_ids:
        total += get_cohort_issued_to_operations_quantity(db, cohort_id=cohort_id)
    return total


def get_item_in_store_quantity(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, inventory_item_id: uuid.UUID
) -> Decimal:
    cohort_ids = _farm_scoped_cohort_ids(db, tenant_id=tenant_id, farm_id=farm_id, inventory_item_id=inventory_item_id)
    total = Decimal("0")
    for cohort_id in cohort_ids:
        total += get_cohort_in_store_quantity(db, cohort_id=cohort_id)
    return total


def get_item_farm_availability_summary(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, inventory_item_id: uuid.UUID, as_of: date | None = None
) -> dict:
    """One compact bundle for the Inventory screen's per-Item, per-(current)
    Farm expanded detail: In Store / Reserved / Issued to operations /
    Available to issue -- "Not put away" is deliberately NOT included here
    (it is tenant-wide, not Farm-scoped, and already served by
    `inventory_storage_service.get_item_storage_breakdown`)."""
    in_store = get_item_in_store_quantity(db, tenant_id=tenant_id, farm_id=farm_id, inventory_item_id=inventory_item_id)
    reserved = get_item_reserved_quantity(db, tenant_id=tenant_id, farm_id=farm_id, inventory_item_id=inventory_item_id)
    issued = get_item_issued_to_operations_quantity(
        db, tenant_id=tenant_id, farm_id=farm_id, inventory_item_id=inventory_item_id
    )
    usable_in_store = get_item_usable_in_store_quantity(
        db, tenant_id=tenant_id, farm_id=farm_id, inventory_item_id=inventory_item_id, as_of=as_of
    )
    available_to_issue = usable_in_store - reserved
    return {
        "in_store_quantity": in_store,
        "reserved_quantity": reserved,
        "issued_to_operations_quantity": issued,
        "available_to_issue_quantity": max(Decimal("0"), available_to_issue),
    }


def list_item_farm_issuable_sources(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, inventory_item_id: uuid.UUID, as_of: date | None = None
) -> list[dict]:
    """Every (Cohort, Bin) pair an operator may actually pick as an Issue
    line's physical source for this Item at this Farm -- usable, not
    expired, positive Bin balance. Feeds the "Issue now" compact row
    picker (Item | Lot | Bin | Qty | UOM): when this list has exactly one
    entry, the frontend defaults it -- no forced extra tap."""
    as_of = as_of or date.today()
    rows = db.execute(
        select(InventoryQuantityCohort.id, InventoryQuantityCohort.inventory_lot_id, InventoryLot.expiry_date, InventoryLot.manufacturer_lot_reference)
        .select_from(InventoryQuantityCohort)
        .outerjoin(InventoryLot, InventoryLot.id == InventoryQuantityCohort.inventory_lot_id)
        .where(
            InventoryQuantityCohort.tenant_id == tenant_id,
            InventoryQuantityCohort.inventory_item_id == inventory_item_id,
            InventoryQuantityCohort.receiving_farm_id == farm_id,
        )
    ).all()

    sources: list[dict] = []
    for cohort_id, lot_id, expiry_date, lot_reference in rows:
        if expiry_date is not None and expiry_date < as_of:
            continue
        state = inventory_quality_service.resolve_current_state(db, tenant_id=tenant_id, cohort_id=cohort_id)
        if state not in inventory_quality_service.USABLE_STATES:
            continue
        movement_rows = db.execute(
            select(
                InventoryStorageMovement.source_location_id, InventoryStorageMovement.destination_location_id,
                InventoryStorageMovement.moved_quantity_base, InventoryStorageMovement.movement_kind,
            ).where(InventoryStorageMovement.inventory_quantity_cohort_id == cohort_id)
        ).all()
        per_bin: dict[uuid.UUID, Decimal] = {}
        for src, dest, qty, kind in movement_rows:
            if dest is not None:
                per_bin[dest] = per_bin.get(dest, Decimal(0)) + qty
            if src is not None:
                per_bin[src] = per_bin.get(src, Decimal(0)) - qty
        bin_ids = [loc_id for loc_id, bal in per_bin.items() if bal > 0]
        if not bin_ids:
            continue
        locations = {loc.id: loc for loc in db.execute(select(Location).where(Location.id.in_(bin_ids))).scalars()}
        for loc_id in bin_ids:
            loc = locations.get(loc_id)
            sources.append({
                "inventory_quantity_cohort_id": cohort_id, "inventory_lot_id": lot_id,
                "lot_label": lot_reference, "source_location_id": loc_id,
                "bin_label": loc.name if loc is not None else str(loc_id), "balance": per_bin[loc_id],
            })
    return sources
