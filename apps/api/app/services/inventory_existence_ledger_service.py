"""STORE-INV-002A.1: the existence ledger (`docs/domain/
STORE_INVENTORY_MODEL.md` §7/§F) -- Adjustment, Reversal, and the internal
cohort-split primitive. Every writer locks the `InventoryQuantityCohort`
row (`FOR UPDATE`), never `InventoryLot` -- narrower, higher-concurrency
than locking the whole lot, and correct once a lot can span cohorts with
independent lifecycles. Balance is always `SUM(quantity_delta_base)`,
never a stored column."""

import hashlib
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.inventory_existence_ledger_entry import InventoryExistenceLedgerEntry
from app.models.inventory_quantity_cohort import InventoryQuantityCohort
from app.models.inventory_storage_movement import InventoryStorageMovement
from app.services.audit import append_audit_event
from app.services.errors import (
    ExistenceBelowCustodyError,
    InsufficientCohortBalanceError,
    InventoryAdjustmentCommandReusedWithDifferentPayloadError,
    InventoryExistenceLedgerEntryNotFoundError,
    InventoryExistenceReversalCommandReusedWithDifferentPayloadError,
    InventoryExistenceReversalOfReversalError,
    InventoryExistenceReversalTargetAlreadyReversedError,
    InventoryQuantityCohortNotFoundError,
    InventoryQuantityCohortSplitAllocationExceedsBalanceError,
)


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def get_cohort_balance(db: Session, *, cohort_id: uuid.UUID) -> Decimal:
    return db.execute(
        select(func.coalesce(func.sum(InventoryExistenceLedgerEntry.quantity_delta_base), 0)).where(
            InventoryExistenceLedgerEntry.inventory_quantity_cohort_id == cohort_id
        )
    ).scalar_one()


# --- STORE-INV-002B: physical custody -----------------------------------
# Co-located here (not in inventory_storage_service.py) purely to avoid a
# circular import: inventory_storage_service imports `_lock_cohort`/
# `get_cohort_balance` from this module, so this module must never import
# back from it -- these two helpers only need the `InventoryStorageMovement`
# MODEL, never the storage service itself.


def get_cohort_total_custody(db: Session, *, cohort_id: uuid.UUID) -> Decimal:
    """Total physical custody currently recorded for this cohort, across
    every Bin -- `putaway`/`split_in` credit, `split_out` debits,
    `transfer` nets to zero for the cohort as a whole (it only
    redistributes between Bins). Never exceeds `get_cohort_balance`
    (STORE-INV-002B's own existence/custody safety invariant)."""
    return db.execute(
        select(
            func.coalesce(
                func.sum(
                    case(
                        (InventoryStorageMovement.movement_kind.in_(("putaway", "split_in")), InventoryStorageMovement.moved_quantity_base),
                        (InventoryStorageMovement.movement_kind == "split_out", -InventoryStorageMovement.moved_quantity_base),
                        else_=0,
                    )
                ),
                0,
            )
        ).where(InventoryStorageMovement.inventory_quantity_cohort_id == cohort_id)
    ).scalar_one()


def get_cohort_bin_balance(db: Session, *, cohort_id: uuid.UUID, location_id: uuid.UUID) -> Decimal:
    """This cohort's current custody balance in one specific Bin --
    destination credits, source debits, regardless of movement_kind."""
    return db.execute(
        select(
            func.coalesce(
                func.sum(
                    case((InventoryStorageMovement.destination_location_id == location_id, InventoryStorageMovement.moved_quantity_base), else_=0)
                ),
                0,
            )
            - func.coalesce(
                func.sum(
                    case((InventoryStorageMovement.source_location_id == location_id, InventoryStorageMovement.moved_quantity_base), else_=0)
                ),
                0,
            )
        ).where(
            InventoryStorageMovement.inventory_quantity_cohort_id == cohort_id,
            (InventoryStorageMovement.source_location_id == location_id)
            | (InventoryStorageMovement.destination_location_id == location_id),
        )
    ).scalar_one()


def _lock_cohort(db: Session, *, tenant_id: uuid.UUID, cohort_id: uuid.UUID) -> InventoryQuantityCohort:
    cohort = db.execute(
        select(InventoryQuantityCohort)
        .where(InventoryQuantityCohort.id == cohort_id, InventoryQuantityCohort.tenant_id == tenant_id)
        .with_for_update()
    ).scalar_one_or_none()
    if cohort is None:
        raise InventoryQuantityCohortNotFoundError(str(cohort_id))
    return cohort


def get_cohort(db: Session, *, tenant_id: uuid.UUID, cohort_id: uuid.UUID) -> InventoryQuantityCohort:
    cohort = db.execute(
        select(InventoryQuantityCohort).where(
            InventoryQuantityCohort.id == cohort_id, InventoryQuantityCohort.tenant_id == tenant_id
        )
    ).scalar_one_or_none()
    if cohort is None:
        raise InventoryQuantityCohortNotFoundError(str(cohort_id))
    return cohort


def list_ledger_entries(
    db: Session, *, tenant_id: uuid.UUID, cohort_id: uuid.UUID
) -> list[InventoryExistenceLedgerEntry]:
    return list(
        db.execute(
            select(InventoryExistenceLedgerEntry)
            .where(
                InventoryExistenceLedgerEntry.tenant_id == tenant_id,
                InventoryExistenceLedgerEntry.inventory_quantity_cohort_id == cohort_id,
            )
            .order_by(InventoryExistenceLedgerEntry.effective_time, InventoryExistenceLedgerEntry.recorded_time)
        ).scalars()
    )


def _compute_adjustment_fingerprint(
    *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID | None, cohort_id: uuid.UUID, quantity_delta: Decimal,
    effective_time: datetime, reason: str,
) -> str:
    parts = [
        str(tenant_id), str(actor_user_id) if actor_user_id else "", str(cohort_id), str(quantity_delta),
        effective_time.isoformat(), reason,
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def record_adjustment(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_command_id: uuid.UUID,
    cohort_id: uuid.UUID,
    quantity_delta: Decimal,
    effective_time: datetime,
    reason: str,
) -> InventoryExistenceLedgerEntry:
    """Always targets one existing cohort explicitly -- never an item- or
    lot-level generic adjustment. If physical quantity exists with no
    corresponding cohort at all, the answer is a corrective Goods Receipt
    (`goods_receipt_service.record_goods_receipt`), never a fabricated
    target here (docs/domain/STORE_INVENTORY_MODEL.md §G)."""
    fingerprint = _compute_adjustment_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, cohort_id=cohort_id, quantity_delta=quantity_delta,
        effective_time=effective_time, reason=reason,
    )

    existing = db.execute(
        select(InventoryExistenceLedgerEntry).where(
            InventoryExistenceLedgerEntry.tenant_id == tenant_id,
            InventoryExistenceLedgerEntry.client_command_id == client_command_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise InventoryAdjustmentCommandReusedWithDifferentPayloadError(str(client_command_id))

    cohort = _lock_cohort(db, tenant_id=tenant_id, cohort_id=cohort_id)

    existing = db.execute(
        select(InventoryExistenceLedgerEntry).where(
            InventoryExistenceLedgerEntry.tenant_id == tenant_id,
            InventoryExistenceLedgerEntry.client_command_id == client_command_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise InventoryAdjustmentCommandReusedWithDifferentPayloadError(str(client_command_id))

    balance = get_cohort_balance(db, cohort_id=cohort.id)
    if balance + quantity_delta < 0:
        raise InsufficientCohortBalanceError(
            f"adjustment would drive cohort {cohort_id} balance negative (balance={balance}, delta={quantity_delta})"
        )
    if quantity_delta < 0:
        # STORE-INV-002B: physical custody can never exceed existence.
        total_custody = get_cohort_total_custody(db, cohort_id=cohort.id)
        if balance + quantity_delta < total_custody:
            raise ExistenceBelowCustodyError(
                f"adjustment would leave cohort {cohort_id} existence ({balance + quantity_delta}) below its "
                f"current physical custody ({total_custody})"
            )

    entry = InventoryExistenceLedgerEntry(
        tenant_id=tenant_id, inventory_quantity_cohort_id=cohort.id, inventory_item_id=cohort.inventory_item_id,
        inventory_lot_id=cohort.inventory_lot_id, receiving_farm_id=cohort.receiving_farm_id,
        entry_kind="adjustment", quantity_delta_base=quantity_delta, effective_time=effective_time,
        recorded_time=datetime.now(effective_time.tzinfo), actor_user_id=actor_user_id, reason=reason,
        client_command_id=client_command_id, request_fingerprint=fingerprint,
    )
    db.add(entry)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_inventory_existence_ledger_entries_tenant_client_command_id":
            replay = db.execute(
                select(InventoryExistenceLedgerEntry).where(
                    InventoryExistenceLedgerEntry.tenant_id == tenant_id,
                    InventoryExistenceLedgerEntry.client_command_id == client_command_id,
                )
            ).scalar_one_or_none()
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise InventoryAdjustmentCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="inventory_adjustment.recorded",
        entity_type="inventory_existence_ledger_entry", entity_id=entry.id,
        event_data={"cohort_id": str(cohort_id), "quantity_delta": str(quantity_delta), "reason": reason},
    )
    db.commit()
    db.refresh(entry)
    return entry


def reverse_ledger_entry(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_command_id: uuid.UUID,
    target_entry_id: uuid.UUID,
    reason: str,
) -> InventoryExistenceLedgerEntry:
    """Append-only: exact negation of `target_entry_id`, on the SAME
    cohort, at most one reversal per target, no reversal-of-reversal. A
    reversal of the original `receipt` entry is only permitted if doing so
    would not drive the cohort negative -- an operator wanting to fully
    cancel a cohort that already has a later adjustment reverses in
    reverse-chronological order; the general non-negative check already
    enforces this correctly with no special-casing
    (docs/domain/STORE_INVENTORY_MODEL.md §R)."""
    fingerprint = hashlib.sha256(
        "|".join([
            str(tenant_id), str(actor_user_id), str(target_entry_id), reason,
        ]).encode("utf-8")
    ).hexdigest()

    existing = db.execute(
        select(InventoryExistenceLedgerEntry).where(
            InventoryExistenceLedgerEntry.tenant_id == tenant_id,
            InventoryExistenceLedgerEntry.client_command_id == client_command_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise InventoryExistenceReversalCommandReusedWithDifferentPayloadError(str(client_command_id))

    target = db.execute(
        select(InventoryExistenceLedgerEntry).where(
            InventoryExistenceLedgerEntry.id == target_entry_id, InventoryExistenceLedgerEntry.tenant_id == tenant_id
        )
    ).scalar_one_or_none()
    if target is None:
        raise InventoryExistenceLedgerEntryNotFoundError(str(target_entry_id))
    if target.entry_kind == "reversal":
        raise InventoryExistenceReversalOfReversalError(str(target_entry_id))

    cohort = _lock_cohort(db, tenant_id=tenant_id, cohort_id=target.inventory_quantity_cohort_id)

    existing = db.execute(
        select(InventoryExistenceLedgerEntry).where(
            InventoryExistenceLedgerEntry.tenant_id == tenant_id,
            InventoryExistenceLedgerEntry.client_command_id == client_command_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise InventoryExistenceReversalCommandReusedWithDifferentPayloadError(str(client_command_id))

    already_reversed = db.execute(
        select(InventoryExistenceLedgerEntry.id).where(
            InventoryExistenceLedgerEntry.reversal_of_entry_id == target.id
        )
    ).scalar_one_or_none()
    if already_reversed is not None:
        raise InventoryExistenceReversalTargetAlreadyReversedError(str(target_entry_id))

    negated = -target.quantity_delta_base
    balance = get_cohort_balance(db, cohort_id=cohort.id)
    if balance + negated < 0:
        raise InsufficientCohortBalanceError(
            f"reversal would drive cohort {cohort.id} balance negative (balance={balance}, delta={negated})"
        )
    if negated < 0:
        # STORE-INV-002B: physical custody can never exceed existence.
        total_custody = get_cohort_total_custody(db, cohort_id=cohort.id)
        if balance + negated < total_custody:
            raise ExistenceBelowCustodyError(
                f"reversal would leave cohort {cohort.id} existence ({balance + negated}) below its current "
                f"physical custody ({total_custody})"
            )

    entry = InventoryExistenceLedgerEntry(
        tenant_id=tenant_id, inventory_quantity_cohort_id=cohort.id, inventory_item_id=cohort.inventory_item_id,
        inventory_lot_id=cohort.inventory_lot_id, receiving_farm_id=cohort.receiving_farm_id,
        entry_kind="reversal", quantity_delta_base=negated, effective_time=target.effective_time,
        recorded_time=datetime.now(target.effective_time.tzinfo), actor_user_id=actor_user_id, reason=reason,
        reversal_of_entry_id=target.id, client_command_id=client_command_id, request_fingerprint=fingerprint,
    )
    db.add(entry)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_inventory_existence_ledger_entries_tenant_client_command_id":
            replay = db.execute(
                select(InventoryExistenceLedgerEntry).where(
                    InventoryExistenceLedgerEntry.tenant_id == tenant_id,
                    InventoryExistenceLedgerEntry.client_command_id == client_command_id,
                )
            ).scalar_one_or_none()
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise InventoryExistenceReversalCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        if constraint == "ux_inventory_existence_ledger_entries_reversal_target":
            raise InventoryExistenceReversalTargetAlreadyReversedError(str(target_entry_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="inventory_existence.reversed",
        entity_type="inventory_existence_ledger_entry", entity_id=entry.id,
        event_data={"target_entry_id": str(target_entry_id), "reason": reason},
    )
    db.commit()
    db.refresh(entry)
    return entry


def _split_cohort_core(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    source_cohort_id: uuid.UUID,
    allocations: list[Decimal],
    reason: str,
    effective_time: datetime,
) -> list[InventoryQuantityCohort]:
    """The ONE composable internal split primitive: validate + insert +
    flush only, no commit, no audit -- composable inside a larger atomic
    transaction, mirroring the `_create_batch_core`/`_sow_batch_core`/
    `_register_seed_lot_core` convention. `STORE-INV-002A.2`'s real quality
    command ("Apply disposition to part of quantity") is what `.2` must
    call directly: it composes this core with inserting each resulting
    child cohort's own opening `QualityDispositionEvent` and its own
    command-level audit event, all in the SAME transaction, ending in its
    own single `db.commit()` -- exactly the shape every other `_*_core`
    function in this codebase already requires of its caller. There is
    deliberately no committing sibling of this function anywhere in
    production code (a committing wrapper here would be a generic public
    split command in all but name, and `.1` has none -- no route, no
    `Permission`, no operator-facing "Split Cohort" concept anywhere,
    docs/domain/STORE_INVENTORY_MODEL.md §C). Tests that need a
    committed split call this core directly and commit it themselves
    (`tests/_store_inv_scenario.py::split_cohort_for_test`).

    A split may be partial (source keeps a nonzero remainder, its own
    disposition chain untouched) or full (source balance fully allocated
    away). Never creates a new `InventoryLot` identity. Reconciliation
    (`source_balance_before = SUM(allocations) + source_balance_after`) is
    enforced by both this function and a DB trigger."""
    if not allocations or any(a <= 0 for a in allocations):
        raise InventoryQuantityCohortSplitAllocationExceedsBalanceError("every split allocation must be positive")

    source = _lock_cohort(db, tenant_id=tenant_id, cohort_id=source_cohort_id)
    balance = get_cohort_balance(db, cohort_id=source.id)
    total = sum(allocations)
    if total > balance:
        raise InventoryQuantityCohortSplitAllocationExceedsBalanceError(
            f"requested split total {total} exceeds cohort {source_cohort_id} balance {balance}"
        )

    recorded_time = datetime.now(effective_time.tzinfo)
    children: list[InventoryQuantityCohort] = []
    for allocation in allocations:
        split_out = InventoryExistenceLedgerEntry(
            tenant_id=tenant_id, inventory_quantity_cohort_id=source.id, inventory_item_id=source.inventory_item_id,
            inventory_lot_id=source.inventory_lot_id, receiving_farm_id=source.receiving_farm_id,
            entry_kind="split_out", quantity_delta_base=-allocation, effective_time=effective_time,
            recorded_time=recorded_time, actor_user_id=actor_user_id, reason=reason,
        )
        db.add(split_out)
        db.flush()

        child = InventoryQuantityCohort(
            id=uuid.uuid4(), tenant_id=tenant_id, source_goods_receipt_line_id=source.source_goods_receipt_line_id,
            inventory_item_id=source.inventory_item_id, inventory_lot_id=source.inventory_lot_id,
            receiving_farm_id=source.receiving_farm_id, parent_cohort_id=source.id,
            created_by_user_id=actor_user_id,
        )
        db.add(child)
        db.flush()

        split_in = InventoryExistenceLedgerEntry(
            tenant_id=tenant_id, inventory_quantity_cohort_id=child.id, inventory_item_id=child.inventory_item_id,
            inventory_lot_id=child.inventory_lot_id, receiving_farm_id=child.receiving_farm_id,
            entry_kind="split_in", quantity_delta_base=allocation, effective_time=effective_time,
            recorded_time=recorded_time, actor_user_id=actor_user_id, reason=reason,
            source_split_out_entry_id=split_out.id,
        )
        db.add(split_in)
        db.flush()
        children.append(child)

    return children
