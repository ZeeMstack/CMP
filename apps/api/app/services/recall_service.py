"""CMP-020 recall case and containment foundation.

A recall case is a formal food-safety containment decision. Opening one
freezes an immutable evidence/scope snapshot -- computed from the exact
same set-based lineage primitives CMP-019 uses (`app.services.lineage_
traversal`) -- and then makes that scope authoritative for four write-path
containment gates (batch derivation, packing, finished-goods storage
release, dispatch), enforced independently in both this service and in
versioned database triggers.

This is NOT customer notification, regulatory reporting, delivery recall,
return processing, destruction/disposal, financial credit, CAPA, or an
investigation workflow -- CMP does not yet model customers/destinations,
and none of those concerns are addressed here.

Containment is never a mutable boolean column. `RecallCase` IS the opened
fact (mirroring `QualityHold`'s own immutable-fact shape); `RecallCase
Closure` is the one optional immutable fact that ends it. Open/closed
state is always derived from closure-row absence/presence, never stored.
"""
import hashlib
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import exists, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.crop_batch import CropBatch
from app.models.finished_goods_lot import FinishedGoodsLot
from app.models.harvested_produce_lot import HarvestedProduceLot
from app.models.recall import (
    RecallCase,
    RecallCaseClosure,
    RecallScopeBatch,
    RecallScopeFinishedGoodsLot,
    RecallScopeProduceLot,
)
from app.services import farm_service, lineage_traversal
from app.services.audit import append_audit_event
from app.services.errors import (
    CropBatchNotFoundError,
    DuplicateRecallCaseCodeError,
    FarmNotFoundError,
    FinishedGoodsLotNotFoundError,
    HarvestedProduceLotNotFoundError,
    InvalidRecallCaseEffectiveTimeError,
    RecallCaseAlreadyClosedError,
    RecallCaseCommandReusedWithDifferentPayloadError,
    RecallCaseNotFoundError,
    RecallCaseValidationError,
    RecallScopeStabilizationError,
)

# Defensive corruption/pathological-concurrency guard only -- never a
# normal business limit. A genuine recall scope is expected to stabilize
# in one or two rounds; this bound exists solely so a runaway concurrent
# split storm (or corrupted lineage data) fails loud instead of looping
# forever. Deliberately the same order of magnitude as CMP-019's own
# `lineage_traversal._MAX_LINEAGE_DEPTH`.
_MAX_SCOPE_STABILIZATION_ROUNDS = 500


def _require_active_farm(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID):
    farm = farm_service.get_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    if farm.status != "active":
        raise FarmNotFoundError(str(farm_id))
    return farm


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


# --- Containment predicates (used by the four write-path gates) ------------


def has_open_batch_recall(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID) -> bool:
    row = db.execute(
        select(RecallScopeBatch.id).where(
            RecallScopeBatch.tenant_id == tenant_id, RecallScopeBatch.farm_id == farm_id,
            RecallScopeBatch.crop_batch_id == batch_id,
            ~exists().where(RecallCaseClosure.recall_case_id == RecallScopeBatch.recall_case_id),
        )
    ).first()
    return row is not None


def has_open_produce_lot_recall(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, produce_lot_id: uuid.UUID
) -> bool:
    row = db.execute(
        select(RecallScopeProduceLot.id).where(
            RecallScopeProduceLot.tenant_id == tenant_id, RecallScopeProduceLot.farm_id == farm_id,
            RecallScopeProduceLot.harvested_produce_lot_id == produce_lot_id,
            ~exists().where(RecallCaseClosure.recall_case_id == RecallScopeProduceLot.recall_case_id),
        )
    ).first()
    return row is not None


def has_open_finished_goods_recall(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, finished_goods_lot_id: uuid.UUID
) -> bool:
    row = db.execute(
        select(RecallScopeFinishedGoodsLot.id).where(
            RecallScopeFinishedGoodsLot.tenant_id == tenant_id, RecallScopeFinishedGoodsLot.farm_id == farm_id,
            RecallScopeFinishedGoodsLot.finished_goods_lot_id == finished_goods_lot_id,
            ~exists().where(RecallCaseClosure.recall_case_id == RecallScopeFinishedGoodsLot.recall_case_id),
        )
    ).first()
    return row is not None


# --- Locking helpers (sorted-UUID, matching batch_derivation_service's own idiom) --


def _lock_crop_batches(db: Session, *, tenant_id, farm_id, ids) -> list[CropBatch]:
    if not ids:
        return []
    return list(
        db.execute(
            select(CropBatch)
            .where(CropBatch.id.in_(list(ids)), CropBatch.tenant_id == tenant_id, CropBatch.farm_id == farm_id)
            .order_by(CropBatch.id).with_for_update()
        ).scalars()
    )


def _lock_produce_lots(db: Session, *, tenant_id, farm_id, ids) -> list[HarvestedProduceLot]:
    if not ids:
        return []
    return list(
        db.execute(
            select(HarvestedProduceLot)
            .where(
                HarvestedProduceLot.id.in_(list(ids)), HarvestedProduceLot.tenant_id == tenant_id,
                HarvestedProduceLot.farm_id == farm_id,
            )
            .order_by(HarvestedProduceLot.id).with_for_update()
        ).scalars()
    )


def _lock_finished_goods_lots(db: Session, *, tenant_id, farm_id, ids) -> list[FinishedGoodsLot]:
    if not ids:
        return []
    return list(
        db.execute(
            select(FinishedGoodsLot)
            .where(
                FinishedGoodsLot.id.in_(list(ids)), FinishedGoodsLot.tenant_id == tenant_id,
                FinishedGoodsLot.farm_id == farm_id,
            )
            .order_by(FinishedGoodsLot.id).with_for_update()
        ).scalars()
    )


# --- Stable scope-freeze algorithms ------------------------------------------


def _derive_and_lock_fg_lots(db: Session, conn, *, tenant_id, farm_id, produce_lot_ids: set[uuid.UUID]) -> set[uuid.UUID]:
    """Derives the finished-goods lots reachable from `produce_lot_ids` via
    packing, locks them, then re-derives and locks any delta -- a defensive
    lock-then-recheck pass (this codebase's universal idempotency
    discipline applied to scope discovery), on top of the fact that every
    produce lot in `produce_lot_ids` is already locked by the caller, which
    already prevents any *new* packing_input_line from being inserted
    against it (packing_service locks batches then produce lots, in that
    order, before creating a finished-goods lot)."""
    packing_inputs = lineage_traversal._packing_input_lines_for_produce_lots(
        conn, tenant_id=tenant_id, farm_id=farm_id, produce_lot_ids=sorted(produce_lot_ids)
    )
    packing_event_ids = sorted({r["packing_event_id"] for r in packing_inputs})
    fg_rows = lineage_traversal._finished_goods_lots_for_packing_events(
        conn, tenant_id=tenant_id, farm_id=farm_id, packing_event_ids=packing_event_ids
    )
    fg_lot_ids = {r["finished_goods_lot_id"] for r in fg_rows}

    _lock_finished_goods_lots(db, tenant_id=tenant_id, farm_id=farm_id, ids=sorted(fg_lot_ids))

    packing_inputs_2 = lineage_traversal._packing_input_lines_for_produce_lots(
        conn, tenant_id=tenant_id, farm_id=farm_id, produce_lot_ids=sorted(produce_lot_ids)
    )
    packing_event_ids_2 = sorted({r["packing_event_id"] for r in packing_inputs_2})
    fg_rows_2 = lineage_traversal._finished_goods_lots_for_packing_events(
        conn, tenant_id=tenant_id, farm_id=farm_id, packing_event_ids=packing_event_ids_2
    )
    fg_lot_ids_2 = {r["finished_goods_lot_id"] for r in fg_rows_2}
    delta = fg_lot_ids_2 - fg_lot_ids
    if delta:
        _lock_finished_goods_lots(db, tenant_id=tenant_id, farm_id=farm_id, ids=sorted(delta))
    return fg_lot_ids | fg_lot_ids_2


def _freeze_batch_source_scope(db: Session, conn, *, tenant_id, farm_id, source_batch_id: uuid.UUID):
    """Crop-batch source: selected batch + full descendant closure, their
    harvested produce lots, and every finished-goods lot reachable through
    packing. See `docs/domain/RECALL_CONTAINMENT_MODEL.md` for the full
    step-by-step rationale."""
    locked = _lock_crop_batches(db, tenant_id=tenant_id, farm_id=farm_id, ids=[source_batch_id])
    if not locked:
        raise CropBatchNotFoundError(str(source_batch_id))
    source_batch = locked[0]
    locked_batch_ids = {source_batch.id}

    closure = lineage_traversal._batch_lineage_closure(
        conn, tenant_id=tenant_id, farm_id=farm_id, start_batch_ids=[source_batch_id], direction="descendants"
    )
    rounds = 0
    while not closure <= locked_batch_ids:
        rounds += 1
        if rounds > _MAX_SCOPE_STABILIZATION_ROUNDS:
            raise RecallScopeStabilizationError(
                f"Crop-batch descendant closure for {source_batch_id} did not stabilize within "
                f"{_MAX_SCOPE_STABILIZATION_ROUNDS} rounds. This indicates pathological concurrent "
                "derivation activity or corrupted lineage data, not a normal recall scope -- refusing "
                "to freeze a partial scope."
            )
        new_ids = closure - locked_batch_ids
        _lock_crop_batches(db, tenant_id=tenant_id, farm_id=farm_id, ids=sorted(new_ids))
        locked_batch_ids |= new_ids
        closure = lineage_traversal._batch_lineage_closure(
            conn, tenant_id=tenant_id, farm_id=farm_id, start_batch_ids=[source_batch_id], direction="descendants"
        )
    batch_ids = closure

    def _derive_produce_lots() -> set[uuid.UUID]:
        harvest_events = lineage_traversal._harvest_events_for_batches(
            conn, tenant_id=tenant_id, farm_id=farm_id, batch_ids=batch_ids
        )
        harvest_event_ids = [h["harvest_event_id"] for h in harvest_events]
        produce_lots = lineage_traversal._produce_lots_for_harvest_events(
            conn, tenant_id=tenant_id, farm_id=farm_id, harvest_event_ids=harvest_event_ids
        )
        return {p["harvested_produce_lot_id"] for p in produce_lots}

    produce_lot_ids = _derive_produce_lots()
    _lock_produce_lots(db, tenant_id=tenant_id, farm_id=farm_id, ids=sorted(produce_lot_ids))
    produce_lot_ids_2 = _derive_produce_lots()
    delta = produce_lot_ids_2 - produce_lot_ids
    if delta:
        _lock_produce_lots(db, tenant_id=tenant_id, farm_id=farm_id, ids=sorted(delta))
    produce_lot_ids = produce_lot_ids | produce_lot_ids_2

    fg_lot_ids = _derive_and_lock_fg_lots(
        db, conn, tenant_id=tenant_id, farm_id=farm_id, produce_lot_ids=produce_lot_ids
    )
    return batch_ids, produce_lot_ids, fg_lot_ids, source_batch.created_effective_time


def _freeze_produce_lot_source_scope(db: Session, conn, *, tenant_id, farm_id, source_produce_lot_id: uuid.UUID):
    """Harvested-produce-lot source: selected lot + finished-goods lots
    that already contain material from it. The lot's own crop batch is
    deliberately never promoted into batch scope."""
    locked = _lock_produce_lots(db, tenant_id=tenant_id, farm_id=farm_id, ids=[source_produce_lot_id])
    if not locked:
        raise HarvestedProduceLotNotFoundError(str(source_produce_lot_id))
    source_lot = locked[0]
    produce_lot_ids = {source_lot.id}
    fg_lot_ids = _derive_and_lock_fg_lots(
        db, conn, tenant_id=tenant_id, farm_id=farm_id, produce_lot_ids=produce_lot_ids
    )
    return produce_lot_ids, fg_lot_ids, source_lot.effective_time


def _freeze_finished_goods_lot_source_scope(db: Session, *, tenant_id, farm_id, source_fg_lot_id: uuid.UUID):
    """Finished-goods-lot source: the selected lot only. Upstream co-input
    batches/produce lots are never promoted into scope -- backward
    provenance remains available informationally via CMP-019, never
    persisted as containment."""
    locked = _lock_finished_goods_lots(db, tenant_id=tenant_id, farm_id=farm_id, ids=[source_fg_lot_id])
    if not locked:
        raise FinishedGoodsLotNotFoundError(str(source_fg_lot_id))
    source_lot = locked[0]
    return {source_lot.id}, source_lot.effective_time


# --- Open ---------------------------------------------------------------------


def _compute_open_fingerprint(
    *, tenant_id, farm_id, actor_user_id, code, crop_batch_id, harvested_produce_lot_id,
    finished_goods_lot_id, effective_time, reason_code, reason_text,
) -> str:
    if crop_batch_id is not None:
        source_kind, source_id = "crop_batch", crop_batch_id
    elif harvested_produce_lot_id is not None:
        source_kind, source_id = "harvested_produce_lot", harvested_produce_lot_id
    else:
        source_kind, source_id = "finished_goods_lot", finished_goods_lot_id
    parts = [
        str(tenant_id), str(farm_id), str(actor_user_id), code.strip().lower(), source_kind, str(source_id),
        effective_time.astimezone(timezone.utc).isoformat(), reason_code, reason_text,
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _find_existing_case(db: Session, *, tenant_id: uuid.UUID, client_command_id: uuid.UUID) -> RecallCase | None:
    return db.execute(
        select(RecallCase).where(RecallCase.tenant_id == tenant_id, RecallCase.client_command_id == client_command_id)
    ).scalar_one_or_none()


def open_recall_case(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_command_id: uuid.UUID,
    effective_time: datetime,
    code: str,
    crop_batch_id: uuid.UUID | None,
    harvested_produce_lot_id: uuid.UUID | None,
    finished_goods_lot_id: uuid.UUID | None,
    reason_code: str,
    reason_text: str,
) -> RecallCase:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    source_count = sum(x is not None for x in (crop_batch_id, harvested_produce_lot_id, finished_goods_lot_id))
    if source_count != 1:
        raise RecallCaseValidationError(
            "exactly one of crop_batch_id, harvested_produce_lot_id, finished_goods_lot_id must be provided"
        )

    if effective_time > datetime.now(timezone.utc):
        raise InvalidRecallCaseEffectiveTimeError("effective_time cannot be in the future")

    fingerprint = _compute_open_fingerprint(
        tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, code=code,
        crop_batch_id=crop_batch_id, harvested_produce_lot_id=harvested_produce_lot_id,
        finished_goods_lot_id=finished_goods_lot_id, effective_time=effective_time,
        reason_code=reason_code, reason_text=reason_text,
    )

    existing = _find_existing_case(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise RecallCaseCommandReusedWithDifferentPayloadError(str(client_command_id))

    # `db.connection()` returns the same Core `Connection`/transaction the
    # ORM Session is already using -- `lineage_traversal`'s pure-SQL
    # helpers run inside this one write transaction, seeing every row lock
    # taken via the Session above them.
    conn = db.connection()

    batch_ids: set[uuid.UUID] = set()
    produce_lot_ids: set[uuid.UUID] = set()
    if crop_batch_id is not None:
        batch_ids, produce_lot_ids, fg_lot_ids, source_effective_time = _freeze_batch_source_scope(
            db, conn, tenant_id=tenant_id, farm_id=farm_id, source_batch_id=crop_batch_id
        )
    elif harvested_produce_lot_id is not None:
        produce_lot_ids, fg_lot_ids, source_effective_time = _freeze_produce_lot_source_scope(
            db, conn, tenant_id=tenant_id, farm_id=farm_id, source_produce_lot_id=harvested_produce_lot_id
        )
    else:
        fg_lot_ids, source_effective_time = _freeze_finished_goods_lot_source_scope(
            db, tenant_id=tenant_id, farm_id=farm_id, source_fg_lot_id=finished_goods_lot_id
        )

    if effective_time < source_effective_time:
        raise InvalidRecallCaseEffectiveTimeError(
            "effective_time cannot precede the recall source's own creation/effective time"
        )

    # Post-lock idempotency recheck -- a concurrent replay of this exact
    # command could have committed while the scope above was being frozen.
    existing = _find_existing_case(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise RecallCaseCommandReusedWithDifferentPayloadError(str(client_command_id))

    case = RecallCase(
        id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, code=code,
        crop_batch_id=crop_batch_id, harvested_produce_lot_id=harvested_produce_lot_id,
        finished_goods_lot_id=finished_goods_lot_id, reason_code=reason_code, reason_text=reason_text,
        effective_time=effective_time, actor_user_id=actor_user_id, client_command_id=client_command_id,
        request_fingerprint=fingerprint,
    )
    db.add(case)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_recall_cases_tenant_client_command_id":
            replay = _find_existing_case(db, tenant_id=tenant_id, client_command_id=client_command_id)
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise RecallCaseCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        if constraint == "ux_recall_cases_farm_code_lower":
            raise DuplicateRecallCaseCodeError(code) from exc
        raise

    for bid in sorted(batch_ids):
        db.add(RecallScopeBatch(id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, recall_case_id=case.id, crop_batch_id=bid))
    for pid in sorted(produce_lot_ids):
        db.add(
            RecallScopeProduceLot(
                id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, recall_case_id=case.id,
                harvested_produce_lot_id=pid,
            )
        )
    for fid in sorted(fg_lot_ids):
        db.add(
            RecallScopeFinishedGoodsLot(
                id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, recall_case_id=case.id,
                finished_goods_lot_id=fid,
            )
        )
    db.flush()

    try:
        append_audit_event(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="recall_case.opened",
            entity_type="recall_case", entity_id=case.id,
            event_data={
                "recall_case_id": str(case.id), "code": code,
                "crop_batch_id": str(crop_batch_id) if crop_batch_id else None,
                "harvested_produce_lot_id": str(harvested_produce_lot_id) if harvested_produce_lot_id else None,
                "finished_goods_lot_id": str(finished_goods_lot_id) if finished_goods_lot_id else None,
                "reason_code": reason_code, "effective_time": effective_time.isoformat(),
                "client_command_id": str(client_command_id),
                "scope_batch_count": len(batch_ids), "scope_produce_lot_count": len(produce_lot_ids),
                "scope_finished_goods_lot_count": len(fg_lot_ids),
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(case)
    return case


# --- Close ----------------------------------------------------------------


def _compute_close_fingerprint(
    *, tenant_id, farm_id, actor_user_id, recall_case_id, effective_time, close_reason
) -> str:
    parts = [
        str(tenant_id), str(farm_id), str(actor_user_id), str(recall_case_id),
        effective_time.astimezone(timezone.utc).isoformat(), close_reason,
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _find_existing_closure(db: Session, *, tenant_id: uuid.UUID, client_command_id: uuid.UUID) -> RecallCaseClosure | None:
    return db.execute(
        select(RecallCaseClosure).where(
            RecallCaseClosure.tenant_id == tenant_id, RecallCaseClosure.client_command_id == client_command_id
        )
    ).scalar_one_or_none()


def close_recall_case(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    recall_case_id: uuid.UUID,
    client_command_id: uuid.UUID,
    effective_time: datetime,
    close_reason: str,
) -> RecallCaseClosure:
    """Ends CMP's own containment for this case only -- never product
    recovery, customer notification, or a claim that the underlying
    food-safety event is resolved. The case and its frozen scope remain
    immutable and readable forever; no row is deleted."""
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    if effective_time > datetime.now(timezone.utc):
        raise InvalidRecallCaseEffectiveTimeError("effective_time cannot be in the future")

    fingerprint = _compute_close_fingerprint(
        tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, recall_case_id=recall_case_id,
        effective_time=effective_time, close_reason=close_reason,
    )

    existing = _find_existing_closure(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise RecallCaseCommandReusedWithDifferentPayloadError(str(client_command_id))

    case = db.execute(
        select(RecallCase)
        .where(RecallCase.id == recall_case_id, RecallCase.tenant_id == tenant_id, RecallCase.farm_id == farm_id)
        .with_for_update()
    ).scalar_one_or_none()
    if case is None:
        raise RecallCaseNotFoundError(str(recall_case_id))

    existing = _find_existing_closure(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise RecallCaseCommandReusedWithDifferentPayloadError(str(client_command_id))

    already_closed = db.execute(
        select(RecallCaseClosure.id).where(RecallCaseClosure.recall_case_id == case.id)
    ).scalar_one_or_none()
    if already_closed is not None:
        raise RecallCaseAlreadyClosedError(str(recall_case_id))

    if effective_time < case.effective_time:
        raise InvalidRecallCaseEffectiveTimeError(
            "close effective_time cannot precede the case's own opening effective_time"
        )

    closure = RecallCaseClosure(
        id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, recall_case_id=case.id,
        effective_time=effective_time, actor_user_id=actor_user_id, client_command_id=client_command_id,
        request_fingerprint=fingerprint, close_reason=close_reason,
    )
    db.add(closure)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_recall_case_closures_tenant_client_command_id":
            replay = _find_existing_closure(db, tenant_id=tenant_id, client_command_id=client_command_id)
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise RecallCaseCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        if constraint == "ux_recall_case_closures_case":
            raise RecallCaseAlreadyClosedError(str(recall_case_id)) from exc
        raise

    try:
        append_audit_event(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="recall_case.closed",
            entity_type="recall_case", entity_id=case.id,
            event_data={
                "recall_case_id": str(case.id), "effective_time": effective_time.isoformat(),
                "close_reason": close_reason, "client_command_id": str(client_command_id),
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(closure)
    return closure


# --- Reads ------------------------------------------------------------------


def list_recall_cases(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> list[dict]:
    """Deterministic, set-based list read -- no per-case live-balance
    summary (that belongs only to case detail)."""
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    rows = db.execute(
        select(RecallCase)
        .where(RecallCase.tenant_id == tenant_id, RecallCase.farm_id == farm_id)
        .order_by(RecallCase.effective_time, RecallCase.recorded_time, RecallCase.id)
    ).scalars().all()
    case_ids = [c.id for c in rows]
    closed_ids: set[uuid.UUID] = set()
    if case_ids:
        closed_ids = set(
            db.execute(
                select(RecallCaseClosure.recall_case_id).where(RecallCaseClosure.recall_case_id.in_(case_ids))
            ).scalars()
        )
    return [
        {
            "recall_case_id": c.id, "code": c.code,
            "crop_batch_id": c.crop_batch_id, "harvested_produce_lot_id": c.harvested_produce_lot_id,
            "finished_goods_lot_id": c.finished_goods_lot_id, "reason_code": c.reason_code,
            "reason_text": c.reason_text, "effective_time": c.effective_time, "recorded_time": c.recorded_time,
            "actor_user_id": c.actor_user_id, "is_open": c.id not in closed_ids,
        }
        for c in rows
    ]


def get_recall_case(
    *, tenant_id: uuid.UUID, farm_id: uuid.UUID, recall_case_id: uuid.UUID, engine=None
) -> dict:
    """Case detail: identity/source, derived lifecycle state, the frozen
    scope (immutable ID lists), and -- for scoped finished-goods lots --
    live available/placed/unplaced/dispatch reads. Every query in this
    function runs on one dedicated REPEATABLE READ / READ ONLY snapshot
    (`lineage_traversal._snapshot_connection`), so `frozen_scope` and
    `live_state` are never assembled from two different points in time."""
    with lineage_traversal._snapshot_connection(engine) as conn:
        farm_row = conn.execute(
            text(
                "SELECT 1 FROM farms WHERE id = :fid AND tenant_id = :tid AND status = 'active'"
            ),
            {"fid": farm_id, "tid": tenant_id},
        ).first()
        if farm_row is None:
            raise FarmNotFoundError(str(farm_id))

        case_row = conn.execute(
            text(
                "SELECT id, code, crop_batch_id, harvested_produce_lot_id, finished_goods_lot_id, "
                "reason_code, reason_text, effective_time, recorded_time, actor_user_id "
                "FROM recall_cases WHERE id = :id AND tenant_id = :tid AND farm_id = :fid"
            ),
            {"id": recall_case_id, "tid": tenant_id, "fid": farm_id},
        ).mappings().first()
        if case_row is None:
            raise RecallCaseNotFoundError(str(recall_case_id))

        closure_row = conn.execute(
            text(
                "SELECT id, effective_time, recorded_time, actor_user_id, close_reason "
                "FROM recall_case_closures WHERE recall_case_id = :cid"
            ),
            {"cid": recall_case_id},
        ).mappings().first()

        batch_ids = sorted(
            conn.execute(
                text(
                    "SELECT crop_batch_id FROM recall_scope_batches WHERE recall_case_id = :cid ORDER BY crop_batch_id"
                ),
                {"cid": recall_case_id},
            ).scalars()
        )
        produce_lot_ids = sorted(
            conn.execute(
                text(
                    "SELECT harvested_produce_lot_id FROM recall_scope_produce_lots "
                    "WHERE recall_case_id = :cid ORDER BY harvested_produce_lot_id"
                ),
                {"cid": recall_case_id},
            ).scalars()
        )
        fg_lot_ids = sorted(
            conn.execute(
                text(
                    "SELECT finished_goods_lot_id FROM recall_scope_finished_goods_lots "
                    "WHERE recall_case_id = :cid ORDER BY finished_goods_lot_id"
                ),
                {"cid": recall_case_id},
            ).scalars()
        )

        fg_rows = []
        if fg_lot_ids:
            fg_rows = conn.execute(
                text(
                    "SELECT id AS finished_goods_lot_id, code, packing_event_id, net_packed_weight_kg, "
                    "package_count, effective_time FROM finished_goods_lots "
                    "WHERE tenant_id = :tid AND farm_id = :fid AND id = ANY(:ids) ORDER BY effective_time, id"
                ),
                {"tid": tenant_id, "fid": farm_id, "ids": fg_lot_ids},
            ).mappings().all()
        available = lineage_traversal._bulk_available(conn, tenant_id=tenant_id, farm_id=farm_id, fg_lot_ids=fg_lot_ids)
        placed = lineage_traversal._bulk_placed(conn, tenant_id=tenant_id, farm_id=farm_id, fg_lot_ids=fg_lot_ids)
        dispatches = lineage_traversal._bulk_dispatch_lines(conn, tenant_id=tenant_id, farm_id=farm_id, fg_lot_ids=fg_lot_ids)
        storage = lineage_traversal._bulk_location_balances(conn, tenant_id=tenant_id, farm_id=farm_id, fg_lot_ids=fg_lot_ids)

        finished_goods_live = []
        for r in fg_rows:
            lot_id = r["finished_goods_lot_id"]
            av_w, av_c = available.get(lot_id, (Decimal("0"), 0))
            pl_w, pl_c = placed.get(lot_id, (Decimal("0"), 0))
            finished_goods_live.append(
                {
                    "finished_goods_lot_id": lot_id, "code": r["code"], "packing_event_id": r["packing_event_id"],
                    "net_packed_weight_kg": r["net_packed_weight_kg"], "package_count": r["package_count"],
                    "effective_time": r["effective_time"],
                    "available_weight_kg": av_w, "available_package_count": av_c,
                    "placed_weight_kg": pl_w, "placed_package_count": pl_c,
                    "unplaced_weight_kg": av_w - pl_w, "unplaced_package_count": av_c - pl_c,
                }
            )

        return {
            "recall_case_id": case_row["id"], "code": case_row["code"],
            "crop_batch_id": case_row["crop_batch_id"],
            "harvested_produce_lot_id": case_row["harvested_produce_lot_id"],
            "finished_goods_lot_id": case_row["finished_goods_lot_id"],
            "reason_code": case_row["reason_code"], "reason_text": case_row["reason_text"],
            "effective_time": case_row["effective_time"], "recorded_time": case_row["recorded_time"],
            "actor_user_id": case_row["actor_user_id"],
            "is_open": closure_row is None,
            "closure": dict(closure_row) if closure_row is not None else None,
            "frozen_scope": {
                "crop_batch_ids": batch_ids, "harvested_produce_lot_ids": produce_lot_ids,
                "finished_goods_lot_ids": fg_lot_ids,
            },
            "live_state": {
                "finished_goods_lots": finished_goods_live, "storage": storage, "dispatches": dispatches,
            },
        }
