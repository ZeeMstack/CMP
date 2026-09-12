"""PILOT-BLOCKER-004 F02: the single authoritative cohort accounting
projection (`docs/domain/STORE_INVENTORY_MODEL.md`). Computes existence,
physical custody, and issued-settlement quantities directly from the three
source-of-truth tables (`InventoryExistenceLedgerEntry`,
`InventoryStorageMovement`, `InventoryMaterialEvent`) -- always `SUM`-derived,
never a stored aggregate.

Deliberately dependency-free: imports models only, never another
`inventory_*_service` module. Every write validator that needs this same
projection sits at a different point in the existing service import graph
(`inventory_storage_service` already imports from `inventory_existence_
ledger_service`; `inventory_material_event_service` and `inventory_quality_
service` import from both) -- `inventory_existence_ledger_service` is the
innermost of those and itself needs this projection (STORE-INV-002B's
generic Adjustment/Reversal existence floor), so this module cannot import
from ANY of them without creating a cycle. Being a leaf lets all four import
it safely.

Canonical accounting identity (frozen, PILOT-BLOCKER-004 F02):

    existence (E) = not_put_away (N) + in_bins (B) + outstanding_issued (O)

Reservations, Quality, and expiry never reduce E -- only Consumption and
Scrap (from any of the three source buckets) do. Derivation:

    custody_total   (C) = putaway/split_in credits - split_out/scrap_bin
                           debits (issue/return deliberately excluded --
                           neither changes whether material is "put away")
    settled_from_issued (D) = consumption + scrap ever settled against this
                           cohort's own Issue lines (existence-reducing, but
                           writes no storage-movement row, so it never
                           touches C)
    issued (I) / returned (R) = gross issue / return storage-movement totals

    not_put_away         N = E - C + D
    in_bins               B = C - I + R
    outstanding_issued    O = I - R - D

Algebraic proof N + B + O == E: (E-C+D) + (C-I+R) + (I-R-D) = E. The floor
below which Existence can never validly drop (generic Adjustment/Reversal,
STORE-INV-002B/004) is `in_bins + outstanding_issued` (= C - D), never the
stale `custody_total` (C) alone -- C never falls when issued material is
later consumed/scrapped, so using C as the floor after any issued-settlement
activity over-restricts valid reductions (PILOT-BLOCKER-004 F02's confirmed
defect)."""

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.inventory_existence_ledger_entry import InventoryExistenceLedgerEntry
from app.models.inventory_material_event import InventoryMaterialEvent
from app.models.inventory_storage_movement import InventoryStorageMovement


@dataclass(frozen=True)
class CohortAccountingSnapshot:
    existence: Decimal
    custody_total: Decimal
    settled_from_issued: Decimal
    not_put_away: Decimal
    in_bins: Decimal
    outstanding_issued: Decimal

    @property
    def existence_floor(self) -> Decimal:
        """The minimum Existence a generic Adjustment/Reversal may ever
        leave this cohort at -- `in_bins + outstanding_issued`, algebraically
        `custody_total - settled_from_issued`. Below this, physical/issued
        custody the system still believes exists would exceed Existence."""
        return self.in_bins + self.outstanding_issued


def get_cohort_existence(db: Session, *, cohort_id: uuid.UUID) -> Decimal:
    return db.execute(
        select(func.coalesce(func.sum(InventoryExistenceLedgerEntry.quantity_delta_base), 0)).where(
            InventoryExistenceLedgerEntry.inventory_quantity_cohort_id == cohort_id
        )
    ).scalar_one()


def get_cohort_custody_total(db: Session, *, cohort_id: uuid.UUID) -> Decimal:
    """Must stay algebraically identical to `inventory_existence_ledger_
    service.get_cohort_total_custody` -- duplicated here (not imported) so
    this module stays a dependency-free leaf (see module docstring)."""
    return db.execute(
        select(
            func.coalesce(
                func.sum(
                    case(
                        (
                            InventoryStorageMovement.movement_kind.in_(("putaway", "split_in")),
                            InventoryStorageMovement.moved_quantity_base,
                        ),
                        (
                            InventoryStorageMovement.movement_kind.in_(("split_out", "scrap_bin")),
                            -InventoryStorageMovement.moved_quantity_base,
                        ),
                        else_=0,
                    )
                ),
                0,
            )
        ).where(InventoryStorageMovement.inventory_quantity_cohort_id == cohort_id)
    ).scalar_one()


def get_cohort_settled_from_issued(db: Session, *, cohort_id: uuid.UUID) -> Decimal:
    """`D`: total Consumption + Scrap ever settled against this cohort's own
    Issue lines -- reduces Existence without touching `custody_total`."""
    return db.execute(
        select(func.coalesce(func.sum(InventoryMaterialEvent.quantity_base), 0)).where(
            InventoryMaterialEvent.inventory_quantity_cohort_id == cohort_id,
            InventoryMaterialEvent.source_kind == "issued",
            InventoryMaterialEvent.event_kind.in_(("consumption", "scrap")),
        )
    ).scalar_one()


def _get_cohort_issued_and_returned(db: Session, *, cohort_id: uuid.UUID) -> tuple[Decimal, Decimal]:
    row = db.execute(
        select(
            func.coalesce(
                func.sum(
                    case((InventoryStorageMovement.movement_kind == "issue", InventoryStorageMovement.moved_quantity_base), else_=0)
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case((InventoryStorageMovement.movement_kind == "return", InventoryStorageMovement.moved_quantity_base), else_=0)
                ),
                0,
            ),
        ).where(InventoryStorageMovement.inventory_quantity_cohort_id == cohort_id)
    ).one()
    return row[0], row[1]


def get_cohort_accounting_snapshot(db: Session, *, cohort_id: uuid.UUID) -> CohortAccountingSnapshot:
    """The one place every write validator that needs Existence/custody/
    issued-settlement state should call -- never re-derive any of these
    quantities inline (that duplication is exactly what caused
    PILOT-BLOCKER-004 F02)."""
    existence = get_cohort_existence(db, cohort_id=cohort_id)
    custody_total = get_cohort_custody_total(db, cohort_id=cohort_id)
    settled_from_issued = get_cohort_settled_from_issued(db, cohort_id=cohort_id)
    issued, returned = _get_cohort_issued_and_returned(db, cohort_id=cohort_id)
    not_put_away = existence - custody_total + settled_from_issued
    in_bins = custody_total - issued + returned
    outstanding_issued = issued - returned - settled_from_issued
    return CohortAccountingSnapshot(
        existence=existence,
        custody_total=custody_total,
        settled_from_issued=settled_from_issued,
        not_put_away=not_put_away,
        in_bins=in_bins,
        outstanding_issued=outstanding_issued,
    )
