import hashlib
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.crop_batch import CropBatch
from app.models.dispatch_event import DispatchEvent
from app.models.dispatch_line import DispatchLine
from app.models.finished_goods_ledger_entry import FinishedGoodsLedgerEntry
from app.models.finished_goods_lot import FinishedGoodsLot
from app.models.finished_goods_storage_movement import FinishedGoodsStorageMovement
from app.models.harvested_produce_lot import HarvestedProduceLot
from app.models.packing_input_line import PackingInputLine
from app.schemas.dispatch import DispatchEventRead, DispatchLineRead
from app.schemas.harvest import canonical_decimal_str
from app.services import farm_service, quality_hold_service
from app.services.audit import append_audit_event
from app.services.errors import (
    DispatchCommandReusedWithDifferentPayloadError,
    DispatchEventNotFoundError,
    DispatchFinishedGoodsLotNotFoundError,
    DispatchValidationError,
    DuplicateDispatchCodeError,
    FarmNotFoundError,
    InsufficientFinishedGoodsBalanceError,
    InsufficientUnplacedQuantityError,
    InvalidDispatchEffectiveTimeError,
    QualityHoldOpenError,
)


def _require_active_farm(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID):
    farm = farm_service.get_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    if farm.status != "active":
        raise FarmNotFoundError(str(farm_id))
    return farm


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _compute_dispatch_fingerprint(
    *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, effective_time: datetime,
    code: str, external_reference: str | None, note: str | None, lines: list[dict],
) -> str:
    sorted_lines = sorted(lines, key=lambda line: str(line["finished_goods_lot_id"]))
    parts = [
        str(tenant_id), str(farm_id), str(actor_user_id), effective_time.astimezone(timezone.utc).isoformat(),
        code, external_reference or "", note or "",
    ]
    for line in sorted_lines:
        parts.extend(
            [
                str(line["finished_goods_lot_id"]), canonical_decimal_str(line["dispatched_weight_kg"]),
                str(line["dispatched_package_count"]),
            ]
        )
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _find_existing_dispatch_event(
    db: Session, *, tenant_id: uuid.UUID, client_command_id: uuid.UUID
) -> DispatchEvent | None:
    return db.execute(
        select(DispatchEvent).where(
            DispatchEvent.tenant_id == tenant_id, DispatchEvent.client_command_id == client_command_id
        )
    ).scalar_one_or_none()


# --- Command ------------------------------------------------------------------------


def record_dispatch(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_command_id: uuid.UUID,
    effective_time: datetime,
    code: str,
    external_reference: str | None,
    note: str | None,
    lines: list[dict],
) -> DispatchEvent:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    if effective_time > datetime.now(timezone.utc):
        raise InvalidDispatchEffectiveTimeError("effective_time cannot be in the future")

    lot_ids_in_order = [line["finished_goods_lot_id"] for line in lines]
    if len(lot_ids_in_order) != len(set(lot_ids_in_order)):
        raise DispatchValidationError("duplicate finished_goods_lot_id within one dispatch command")

    fingerprint = _compute_dispatch_fingerprint(
        tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, effective_time=effective_time,
        code=code, external_reference=external_reference, note=note, lines=lines,
    )

    existing = _find_existing_dispatch_event(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise DispatchCommandReusedWithDifferentPayloadError(str(client_command_id))

    lot_ids = sorted(set(lot_ids_in_order))

    # Derive the complete, deterministic lineage from each requested
    # finished-goods lot back to the crop batch(es) that contributed to it
    # — finished_goods_lot -> packing_event -> packing_input_lines ->
    # harvested_produce_lot -> batch. A lot with no resolvable lineage
    # (nonexistent, wrong tenant/farm, or — structurally unreachable given
    # CMP-015's own reconciliation, but never assumed — no input lines) is
    # rejected outright rather than silently dispatched.
    lineage_rows = db.execute(
        select(FinishedGoodsLot.id, HarvestedProduceLot.batch_id)
        .join(PackingInputLine, PackingInputLine.packing_event_id == FinishedGoodsLot.packing_event_id)
        .join(HarvestedProduceLot, HarvestedProduceLot.id == PackingInputLine.harvested_produce_lot_id)
        .where(
            FinishedGoodsLot.id.in_(lot_ids), FinishedGoodsLot.tenant_id == tenant_id,
            FinishedGoodsLot.farm_id == farm_id,
        )
    ).all()
    lots_with_lineage = {row[0] for row in lineage_rows}
    missing_lineage = [lid for lid in lot_ids if lid not in lots_with_lineage]
    if missing_lineage:
        raise DispatchFinishedGoodsLotNotFoundError(str(missing_lineage[0]))
    batch_ids = sorted({row[1] for row in lineage_rows})

    batches = list(
        db.execute(
            select(CropBatch)
            .where(CropBatch.id.in_(batch_ids), CropBatch.tenant_id == tenant_id, CropBatch.farm_id == farm_id)
            .order_by(CropBatch.id).with_for_update()
        ).scalars()
    )
    if len(batches) != len(batch_ids):
        found = {b.id for b in batches}
        missing = [bid for bid in batch_ids if bid not in found]
        raise DispatchFinishedGoodsLotNotFoundError(str(missing[0]))

    # A genuinely new dispatch command is blocked while any contributing
    # source batch has an open quality hold — same lineage-derived net
    # CMP-013/015 already extend for harvest/packing.
    for batch in batches:
        if quality_hold_service.has_open_quality_hold(db, batch_id=batch.id):
            raise QualityHoldOpenError(str(batch.id))

    locked_lots = list(
        db.execute(
            select(FinishedGoodsLot).where(FinishedGoodsLot.id.in_(lot_ids))
            .order_by(FinishedGoodsLot.id).with_for_update()
        ).scalars()
    )
    locked_lots_by_id = {lot.id: lot for lot in locked_lots}

    existing = _find_existing_dispatch_event(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise DispatchCommandReusedWithDifferentPayloadError(str(client_command_id))

    for lid in lot_ids:
        lot = locked_lots_by_id.get(lid)
        if lot is None or lot.tenant_id != tenant_id or lot.farm_id != farm_id:
            raise DispatchFinishedGoodsLotNotFoundError(str(lid))

    balance_rows = db.execute(
        select(
            FinishedGoodsLedgerEntry.finished_goods_lot_id,
            func.sum(FinishedGoodsLedgerEntry.weight_delta_kg).label("weight"),
            func.sum(FinishedGoodsLedgerEntry.package_count_delta).label("count"),
            func.max(FinishedGoodsLedgerEntry.effective_time).label("last_effective_time"),
        )
        .where(FinishedGoodsLedgerEntry.finished_goods_lot_id.in_(lot_ids))
        .group_by(FinishedGoodsLedgerEntry.finished_goods_lot_id)
    ).all()
    balances_by_lot = {r.finished_goods_lot_id: r for r in balance_rows}

    # CMP-018: a lot's own physical-placement history is a second,
    # independent chronology that must stay monotonic against dispatch
    # too -- computed in the same batched shape as the ledger balance
    # above. total_placed = SUM(place) - SUM(release); transfers cancel
    # out across the total by construction.
    storage_rows = db.execute(
        select(
            FinishedGoodsStorageMovement.finished_goods_lot_id,
            func.sum(
                case(
                    (FinishedGoodsStorageMovement.movement_kind == "place", FinishedGoodsStorageMovement.moved_weight_kg),
                    (FinishedGoodsStorageMovement.movement_kind == "release", -FinishedGoodsStorageMovement.moved_weight_kg),
                    else_=0,
                )
            ).label("placed_weight"),
            func.sum(
                case(
                    (FinishedGoodsStorageMovement.movement_kind == "place", FinishedGoodsStorageMovement.moved_package_count),
                    (FinishedGoodsStorageMovement.movement_kind == "release", -FinishedGoodsStorageMovement.moved_package_count),
                    else_=0,
                )
            ).label("placed_count"),
            func.max(FinishedGoodsStorageMovement.effective_time).label("last_movement_effective_time"),
        )
        .where(FinishedGoodsStorageMovement.finished_goods_lot_id.in_(lot_ids))
        .group_by(FinishedGoodsStorageMovement.finished_goods_lot_id)
    ).all()
    storage_by_lot = {r.finished_goods_lot_id: r for r in storage_rows}

    for lid in lot_ids:
        lot = locked_lots_by_id[lid]
        if effective_time < lot.effective_time:
            raise InvalidDispatchEffectiveTimeError(
                f"effective_time precedes finished-goods lot {lid}'s own effective_time"
            )
        bal = balances_by_lot.get(lid)
        if bal is not None and bal.last_effective_time is not None and effective_time < bal.last_effective_time:
            raise InvalidDispatchEffectiveTimeError(
                f"effective_time precedes the latest existing ledger entry for finished-goods lot {lid}"
            )
        storage_row = storage_by_lot.get(lid)
        if (
            storage_row is not None and storage_row.last_movement_effective_time is not None
            and effective_time < storage_row.last_movement_effective_time
        ):
            raise InvalidDispatchEffectiveTimeError(
                f"effective_time precedes the latest storage movement for finished-goods lot {lid}"
            )

    for line in lines:
        lid = line["finished_goods_lot_id"]
        bal = balances_by_lot.get(lid)
        available_weight = bal.weight if bal is not None else Decimal("0")
        available_count = bal.count if bal is not None else 0
        dispatched_weight = line["dispatched_weight_kg"]
        dispatched_count = line["dispatched_package_count"]

        if dispatched_weight > available_weight:
            raise InsufficientFinishedGoodsBalanceError(str(lid))
        if dispatched_count > available_count:
            raise InsufficientFinishedGoodsBalanceError(str(lid))

        # CMP-018: dispatch may only consume currently unplaced quantity --
        # release-before-dispatch. Checked independently of, and in
        # addition to, the plain commercial-balance check above.
        storage_row = storage_by_lot.get(lid)
        placed_weight = storage_row.placed_weight if storage_row is not None and storage_row.placed_weight is not None else Decimal("0")
        placed_count = storage_row.placed_count if storage_row is not None and storage_row.placed_count is not None else 0
        unplaced_weight = available_weight - placed_weight
        unplaced_count = available_count - placed_count
        if dispatched_weight > unplaced_weight:
            raise InsufficientUnplacedQuantityError(str(lid))
        if dispatched_count > unplaced_count:
            raise InsufficientUnplacedQuantityError(str(lid))

    event_id = uuid.uuid4()
    line_ids = {lid: uuid.uuid4() for lid in lot_ids}

    try:
        event = DispatchEvent(
            id=event_id, tenant_id=tenant_id, farm_id=farm_id, code=code, effective_time=effective_time,
            actor_user_id=actor_user_id, client_command_id=client_command_id, request_fingerprint=fingerprint,
            external_reference=external_reference, note=note,
        )
        db.add(event)
        db.flush()

        line_objs: dict[uuid.UUID, DispatchLine] = {}
        for lid in lot_ids:
            line = next(l for l in lines if l["finished_goods_lot_id"] == lid)
            obj = DispatchLine(
                id=line_ids[lid], tenant_id=tenant_id, farm_id=farm_id, dispatch_event_id=event.id,
                finished_goods_lot_id=lid, dispatched_weight_kg=line["dispatched_weight_kg"],
                dispatched_package_count=line["dispatched_package_count"],
            )
            db.add(obj)
            line_objs[lid] = obj
        db.flush()

        # Deterministic dispatch_issue identity, one level up the chain
        # from CMP-015's own packing_consumption debit convention: each
        # issue's id equals its own dispatch line's id.
        for lid in lot_ids:
            obj = line_objs[lid]
            db.add(
                FinishedGoodsLedgerEntry(
                    id=obj.id, tenant_id=tenant_id, farm_id=farm_id, finished_goods_lot_id=lid,
                    packing_event_id=None, dispatch_line_id=obj.id, entry_kind="dispatch_issue",
                    weight_delta_kg=-obj.dispatched_weight_kg, package_count_delta=-obj.dispatched_package_count,
                    effective_time=effective_time, recorded_time=event.recorded_time, actor_user_id=actor_user_id,
                    note=None,
                )
            )
        db.flush()

        append_audit_event(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="finished_goods.dispatched",
            entity_type="dispatch_event", entity_id=event.id,
            event_data={
                "dispatch_event_id": str(event.id), "code": event.code,
                "effective_time": effective_time.isoformat(), "client_command_id": str(client_command_id),
                "lines": [
                    {
                        "finished_goods_lot_id": str(lid),
                        "dispatched_weight_kg": canonical_decimal_str(line_objs[lid].dispatched_weight_kg),
                        "dispatched_package_count": line_objs[lid].dispatched_package_count,
                    }
                    for lid in lot_ids
                ],
                "total_dispatched_weight_kg": canonical_decimal_str(
                    sum((line_objs[lid].dispatched_weight_kg for lid in lot_ids), Decimal("0"))
                ),
                "total_dispatched_package_count": sum(line_objs[lid].dispatched_package_count for lid in lot_ids),
                "external_reference": external_reference,
            },
        )
        db.flush()
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_dispatch_events_tenant_client_command_id":
            replay = _find_existing_dispatch_event(db, tenant_id=tenant_id, client_command_id=client_command_id)
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise DispatchCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        if constraint == "ux_dispatch_events_farm_code_lower":
            raise DuplicateDispatchCodeError(f"{farm_id}:{code}") from exc
        raise
    except Exception:
        db.rollback()
        raise
    db.refresh(event)
    return event


# --- Reads ------------------------------------------------------------------------


def _load_lines(db: Session, *, event_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[DispatchLineRead]]:
    grouped: dict[uuid.UUID, list[DispatchLineRead]] = {eid: [] for eid in event_ids}
    if not event_ids:
        return grouped
    rows = db.execute(
        select(DispatchLine, FinishedGoodsLot.code)
        .join(FinishedGoodsLot, FinishedGoodsLot.id == DispatchLine.finished_goods_lot_id)
        .where(DispatchLine.dispatch_event_id.in_(event_ids))
        .order_by(FinishedGoodsLot.code, FinishedGoodsLot.id)
    ).all()
    for line, lot_code in rows:
        grouped[line.dispatch_event_id].append(
            DispatchLineRead(
                id=line.id, finished_goods_lot_id=line.finished_goods_lot_id, finished_goods_lot_code=lot_code,
                dispatched_weight_kg=line.dispatched_weight_kg,
                dispatched_package_count=line.dispatched_package_count, ledger_entry_id=line.id,
            )
        )
    return grouped


def _row_to_dispatch_event_read(event: DispatchEvent, lines: list[DispatchLineRead]) -> DispatchEventRead:
    return DispatchEventRead(
        id=event.id, tenant_id=event.tenant_id, farm_id=event.farm_id, code=event.code, lines=lines,
        total_dispatched_weight_kg=sum((l.dispatched_weight_kg for l in lines), Decimal("0")),
        total_dispatched_package_count=sum(l.dispatched_package_count for l in lines),
        effective_time=event.effective_time, recorded_time=event.recorded_time, actor_user_id=event.actor_user_id,
        client_command_id=event.client_command_id, external_reference=event.external_reference, note=event.note,
    )


def get_dispatch_event(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, dispatch_event_id: uuid.UUID
) -> DispatchEventRead:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    event = db.execute(
        select(DispatchEvent).where(
            DispatchEvent.id == dispatch_event_id, DispatchEvent.tenant_id == tenant_id,
            DispatchEvent.farm_id == farm_id,
        )
    ).scalar_one_or_none()
    if event is None:
        raise DispatchEventNotFoundError(str(dispatch_event_id))
    lines = _load_lines(db, event_ids=[dispatch_event_id])[dispatch_event_id]
    return _row_to_dispatch_event_read(event, lines)


def list_dispatch_events(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> list[DispatchEventRead]:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    events = list(
        db.execute(
            select(DispatchEvent)
            .where(DispatchEvent.tenant_id == tenant_id, DispatchEvent.farm_id == farm_id)
            .order_by(DispatchEvent.effective_time, DispatchEvent.recorded_time, DispatchEvent.id)
        ).scalars()
    )
    event_ids = [e.id for e in events]
    lines_by_event = _load_lines(db, event_ids=event_ids)
    return [_row_to_dispatch_event_read(e, lines_by_event[e.id]) for e in events]
