import hashlib
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.crop import Crop
from app.models.crop_batch import CropBatch
from app.models.finished_goods_lot import FinishedGoodsLot
from app.models.harvested_produce_lot import HarvestedProduceLot
from app.models.packing_event import PackingEvent
from app.models.packing_input_line import PackingInputLine
from app.models.produce_lot_ledger_entry import ProduceLotLedgerEntry
from app.models.variety import Variety
from app.schemas.crop_batch import CropSummary, VarietySummary
from app.schemas.harvest import MAX_WEIGHT_KG, canonical_decimal_str
from app.schemas.packing import (
    FinishedGoodsLotRead,
    FinishedGoodsLotSummary,
    PackingEventRead,
    PackingInputLineRead,
)
from app.services import farm_service, quality_hold_service
from app.services.audit import append_audit_event
from app.services.errors import (
    DuplicateFinishedGoodsLotCodeError,
    FarmNotFoundError,
    FinishedGoodsLotNotFoundError,
    InsufficientProduceLotBalanceError,
    InvalidPackingEffectiveTimeError,
    PackingCommandReusedWithDifferentPayloadError,
    PackingCropVarietyMismatchError,
    PackingEventNotFoundError,
    PackingInputProduceLotNotFoundError,
    PackingValidationError,
    QualityHoldOpenError,
    TooManyPackingInputLinesError,
)

MAX_PACKING_INPUT_LINES = 50


def _require_active_farm(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID):
    farm = farm_service.get_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    if farm.status != "active":
        raise FarmNotFoundError(str(farm_id))
    return farm


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _compute_packing_fingerprint(
    *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, effective_time: datetime,
    note: str | None, finished_goods_lot_code: str, packed_output_weight_kg: Decimal, package_count: int,
    process_loss_weight_kg: Decimal, rejected_weight_kg: Decimal, input_lines: list[dict],
) -> str:
    sorted_lines = sorted(input_lines, key=lambda line: str(line["harvested_produce_lot_id"]))
    parts = [
        str(tenant_id), str(farm_id), str(actor_user_id), effective_time.astimezone(timezone.utc).isoformat(),
        note or "", finished_goods_lot_code, canonical_decimal_str(packed_output_weight_kg), str(package_count),
        canonical_decimal_str(process_loss_weight_kg), canonical_decimal_str(rejected_weight_kg),
    ]
    for line in sorted_lines:
        parts.extend(
            [
                str(line["harvested_produce_lot_id"]), canonical_decimal_str(line["consumed_weight_kg"]),
                str(line["consumed_whole_unit_count"]) if line["consumed_whole_unit_count"] is not None else "",
                line.get("note") or "",
            ]
        )
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _find_existing_packing_event(
    db: Session, *, tenant_id: uuid.UUID, client_command_id: uuid.UUID
) -> PackingEvent | None:
    return db.execute(
        select(PackingEvent).where(
            PackingEvent.tenant_id == tenant_id, PackingEvent.client_command_id == client_command_id
        )
    ).scalar_one_or_none()


# --- Command ------------------------------------------------------------------------


def record_packing(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_command_id: uuid.UUID,
    effective_time: datetime,
    finished_goods_lot_code: str,
    package_count: int,
    packed_output_weight_kg: Decimal,
    process_loss_weight_kg: Decimal,
    rejected_weight_kg: Decimal,
    note: str | None,
    input_lines: list[dict],
) -> PackingEvent:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    if effective_time > datetime.now(timezone.utc):
        raise InvalidPackingEffectiveTimeError("effective_time cannot be in the future")
    if len(input_lines) > MAX_PACKING_INPUT_LINES:
        raise TooManyPackingInputLinesError(
            f"a packing command may include at most {MAX_PACKING_INPUT_LINES} input lines"
        )

    total_input_weight_kg: Decimal = sum(
        (line["consumed_weight_kg"] for line in input_lines), Decimal("0")
    )

    fingerprint = _compute_packing_fingerprint(
        tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, effective_time=effective_time,
        note=note, finished_goods_lot_code=finished_goods_lot_code, packed_output_weight_kg=packed_output_weight_kg,
        package_count=package_count, process_loss_weight_kg=process_loss_weight_kg,
        rejected_weight_kg=rejected_weight_kg, input_lines=input_lines,
    )

    existing = _find_existing_packing_event(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise PackingCommandReusedWithDifferentPayloadError(str(client_command_id))

    # Resolve source lots and their batch ids first, without trusting any
    # mutable balance — the authoritative balance is only read once the
    # batch and lot rows below are locked.
    lot_ids = sorted({line["harvested_produce_lot_id"] for line in input_lines})
    lots = list(
        db.execute(select(HarvestedProduceLot).where(HarvestedProduceLot.id.in_(lot_ids))).scalars()
    )
    lots_by_id = {lot.id: lot for lot in lots}
    for lid in lot_ids:
        lot = lots_by_id.get(lid)
        if lot is None or lot.tenant_id != tenant_id or lot.farm_id != farm_id:
            raise PackingInputProduceLotNotFoundError(str(lid))
    batch_ids = sorted({lot.batch_id for lot in lots})

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
        raise PackingInputProduceLotNotFoundError(str(missing[0]))

    existing = _find_existing_packing_event(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise PackingCommandReusedWithDifferentPayloadError(str(client_command_id))

    # A genuinely new packing command is blocked while any source batch has
    # an open CMP-010 quality hold. Closed/superseded batch state does not
    # block — a harvested produce lot remains usable after its batch
    # closes or is superseded, unless a hold blocks it.
    for batch in batches:
        if quality_hold_service.has_open_quality_hold(db, batch_id=batch.id):
            raise QualityHoldOpenError(str(batch.id))

    locked_lots = list(
        db.execute(
            select(HarvestedProduceLot).where(HarvestedProduceLot.id.in_(lot_ids))
            .order_by(HarvestedProduceLot.id).with_for_update()
        ).scalars()
    )
    locked_lots_by_id = {lot.id: lot for lot in locked_lots}

    balance_rows = db.execute(
        select(
            ProduceLotLedgerEntry.produce_lot_id,
            func.sum(ProduceLotLedgerEntry.weight_delta_kg).label("weight"),
            func.sum(ProduceLotLedgerEntry.whole_unit_count_delta).label("count"),
            func.max(ProduceLotLedgerEntry.effective_time).label("last_effective_time"),
        )
        .where(ProduceLotLedgerEntry.produce_lot_id.in_(lot_ids))
        .group_by(ProduceLotLedgerEntry.produce_lot_id)
    ).all()
    balances_by_lot = {r.produce_lot_id: r for r in balance_rows}

    crop_ids = {lot.crop_id for lot in locked_lots}
    variety_ids = {lot.variety_id for lot in locked_lots}
    if len(crop_ids) != 1 or len(variety_ids) != 1:
        raise PackingCropVarietyMismatchError(
            "all input produce lots in one packing command must share the same crop and variety"
        )
    crop_id = next(iter(crop_ids))
    variety_id = next(iter(variety_ids))

    for lot in locked_lots:
        if effective_time < lot.effective_time:
            raise InvalidPackingEffectiveTimeError(
                f"effective_time precedes source produce lot {lot.id}'s own effective_time"
            )
        bal = balances_by_lot.get(lot.id)
        if bal is not None and bal.last_effective_time is not None and effective_time < bal.last_effective_time:
            raise InvalidPackingEffectiveTimeError(
                f"effective_time precedes the latest existing ledger entry for source produce lot {lot.id}"
            )

    if total_input_weight_kg >= MAX_WEIGHT_KG:
        raise PackingValidationError("the sum of input-line weights exceeds the supported total weight range")
    if total_input_weight_kg != packed_output_weight_kg + process_loss_weight_kg + rejected_weight_kg:
        raise PackingValidationError(
            "total input weight does not reconcile into packed output, process loss, and rejected weight"
        )

    for line in input_lines:
        lid = line["harvested_produce_lot_id"]
        lot = locked_lots_by_id[lid]
        bal = balances_by_lot.get(lid)
        available_weight = bal.weight if bal is not None else Decimal("0")
        available_count = bal.count if bal is not None else None
        consumed_weight = line["consumed_weight_kg"]
        consumed_count = line["consumed_whole_unit_count"]

        if lot.total_whole_unit_count is None:
            if consumed_count is not None:
                raise PackingValidationError(
                    f"source produce lot {lid} does not track whole-unit count; consumed count must be null"
                )
        elif consumed_count is None:
            raise PackingValidationError(
                f"source produce lot {lid} tracks whole-unit count; consumed count is required"
            )

        if consumed_weight > available_weight:
            raise InsufficientProduceLotBalanceError(str(lid))
        remaining_weight = available_weight - consumed_weight
        remaining_count = None
        if consumed_count is not None:
            if available_count is None or consumed_count > available_count:
                raise InsufficientProduceLotBalanceError(str(lid))
            remaining_count = available_count - consumed_count
            if (remaining_weight == 0 and remaining_count > 0) or (remaining_weight > 0 and remaining_count == 0):
                raise PackingValidationError(
                    f"packing would leave source produce lot {lid} with mismatched residual weight/count"
                )

    event_id = uuid.uuid4()
    line_ids = {lid: uuid.uuid4() for lid in lot_ids}

    try:
        event = PackingEvent(
            id=event_id, tenant_id=tenant_id, farm_id=farm_id, crop_id=crop_id, variety_id=variety_id,
            total_input_weight_kg=total_input_weight_kg, packed_output_weight_kg=packed_output_weight_kg,
            process_loss_weight_kg=process_loss_weight_kg, rejected_weight_kg=rejected_weight_kg,
            effective_time=effective_time, actor_user_id=actor_user_id, client_command_id=client_command_id,
            request_fingerprint=fingerprint, note=note,
        )
        db.add(event)
        db.flush()

        fg_lot = FinishedGoodsLot(
            id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, code=finished_goods_lot_code,
            packing_event_id=event.id, crop_id=crop_id, variety_id=variety_id,
            net_packed_weight_kg=packed_output_weight_kg, package_count=package_count,
            effective_time=effective_time,
        )
        db.add(fg_lot)
        db.flush()

        # Deterministic packing_consumption debit identity (CMP-015, mirrors
        # CMP-014's harvest_receipt convention): each ledger debit's id
        # equals its own PackingInputLine's id — one exact debit per line,
        # trivially reconstructible, no independent client command id.
        input_line_objs: dict[uuid.UUID, PackingInputLine] = {}
        for line in input_lines:
            lid = line["harvested_produce_lot_id"]
            obj = PackingInputLine(
                id=line_ids[lid], tenant_id=tenant_id, farm_id=farm_id, packing_event_id=event.id,
                harvested_produce_lot_id=lid, consumed_weight_kg=line["consumed_weight_kg"],
                consumed_whole_unit_count=line["consumed_whole_unit_count"], note=line.get("note"),
            )
            db.add(obj)
            input_line_objs[lid] = obj
        db.flush()

        for lid, obj in input_line_objs.items():
            count_delta = -obj.consumed_whole_unit_count if obj.consumed_whole_unit_count is not None else None
            db.add(
                ProduceLotLedgerEntry(
                    id=obj.id, tenant_id=tenant_id, farm_id=farm_id, produce_lot_id=lid, harvest_event_id=None,
                    packing_event_id=event.id, entry_kind="packing_consumption",
                    weight_delta_kg=-obj.consumed_weight_kg, whole_unit_count_delta=count_delta,
                    effective_time=effective_time, recorded_time=obj.recorded_time, actor_user_id=actor_user_id,
                    note=obj.note,
                )
            )
        db.flush()

        append_audit_event(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="produce_lot.packed",
            entity_type="packing_event", entity_id=event.id,
            event_data={
                "packing_event_id": str(event.id), "finished_goods_lot_id": str(fg_lot.id),
                "finished_goods_lot_code": fg_lot.code, "source_produce_lot_ids": [str(lid) for lid in lot_ids],
                "packing_input_line_ids": [str(line_ids[lid]) for lid in lot_ids],
                "ledger_entry_ids": [str(line_ids[lid]) for lid in lot_ids],
                "effective_time": effective_time.isoformat(), "client_command_id": str(client_command_id),
                "source_count": len(lot_ids), "total_input_weight_kg": canonical_decimal_str(total_input_weight_kg),
                "packed_output_weight_kg": canonical_decimal_str(packed_output_weight_kg),
                "process_loss_weight_kg": canonical_decimal_str(process_loss_weight_kg),
                "rejected_weight_kg": canonical_decimal_str(rejected_weight_kg), "package_count": package_count,
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_packing_events_tenant_client_command_id":
            replay = _find_existing_packing_event(db, tenant_id=tenant_id, client_command_id=client_command_id)
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise PackingCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        if constraint == "ux_finished_goods_lots_tenant_code_lower":
            raise DuplicateFinishedGoodsLotCodeError(f"{tenant_id}:{finished_goods_lot_code}") from exc
        raise
    except Exception:
        db.rollback()
        raise
    db.refresh(event)
    return event


# --- Reads ------------------------------------------------------------------------


def _packing_event_header_query():
    return (
        select(PackingEvent, Crop, Variety, FinishedGoodsLot)
        .join(Crop, Crop.id == PackingEvent.crop_id)
        .outerjoin(Variety, Variety.id == PackingEvent.variety_id)
        .join(FinishedGoodsLot, FinishedGoodsLot.packing_event_id == PackingEvent.id)
    )


def _load_input_lines(db: Session, *, event_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[PackingInputLineRead]]:
    grouped: dict[uuid.UUID, list[PackingInputLineRead]] = {eid: [] for eid in event_ids}
    if not event_ids:
        return grouped
    rows = db.execute(
        select(PackingInputLine, HarvestedProduceLot.code, HarvestedProduceLot.harvest_event_id)
        .join(HarvestedProduceLot, HarvestedProduceLot.id == PackingInputLine.harvested_produce_lot_id)
        .where(PackingInputLine.packing_event_id.in_(event_ids))
        .order_by(HarvestedProduceLot.code, HarvestedProduceLot.id)
    ).all()
    for line, lot_code, harvest_event_id in rows:
        grouped[line.packing_event_id].append(
            PackingInputLineRead(
                id=line.id, harvested_produce_lot_id=line.harvested_produce_lot_id, produce_lot_code=lot_code,
                harvest_event_id=harvest_event_id, consumed_weight_kg=line.consumed_weight_kg,
                consumed_whole_unit_count=line.consumed_whole_unit_count, ledger_entry_id=line.id,
                note=line.note, recorded_time=line.recorded_time,
            )
        )
    return grouped


def _row_to_packing_event_read(row, input_lines: list[PackingInputLineRead]) -> PackingEventRead:
    event: PackingEvent = row[0]
    crop: Crop = row[1]
    variety: Variety | None = row[2]
    fg_lot: FinishedGoodsLot = row[3]
    return PackingEventRead(
        id=event.id, tenant_id=event.tenant_id, farm_id=event.farm_id,
        crop=CropSummary(id=crop.id, code=crop.code, common_name=crop.common_name),
        variety=(
            VarietySummary(id=variety.id, code=variety.code, name=variety.name) if variety is not None else None
        ),
        finished_goods_lot=FinishedGoodsLotSummary(
            id=fg_lot.id, code=fg_lot.code, net_packed_weight_kg=fg_lot.net_packed_weight_kg,
            package_count=fg_lot.package_count,
        ),
        input_lines=input_lines, total_input_weight_kg=event.total_input_weight_kg,
        packed_output_weight_kg=event.packed_output_weight_kg, process_loss_weight_kg=event.process_loss_weight_kg,
        rejected_weight_kg=event.rejected_weight_kg, effective_time=event.effective_time,
        recorded_time=event.recorded_time, actor_user_id=event.actor_user_id,
        client_command_id=event.client_command_id, note=event.note,
    )


def get_packing_event(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, packing_event_id: uuid.UUID
) -> PackingEventRead:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    row = db.execute(
        _packing_event_header_query().where(
            PackingEvent.id == packing_event_id, PackingEvent.tenant_id == tenant_id,
            PackingEvent.farm_id == farm_id,
        )
    ).first()
    if row is None:
        raise PackingEventNotFoundError(str(packing_event_id))
    input_lines = _load_input_lines(db, event_ids=[packing_event_id])[packing_event_id]
    return _row_to_packing_event_read(row, input_lines)


def list_packing_events(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> list[PackingEventRead]:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    rows = db.execute(
        _packing_event_header_query()
        .where(PackingEvent.tenant_id == tenant_id, PackingEvent.farm_id == farm_id)
        .order_by(PackingEvent.effective_time, PackingEvent.recorded_time)
    ).all()
    event_ids = [r[0].id for r in rows]
    lines_by_event = _load_input_lines(db, event_ids=event_ids)
    return [_row_to_packing_event_read(r, lines_by_event[r[0].id]) for r in rows]


def _finished_goods_lot_header_query():
    return (
        select(FinishedGoodsLot, Crop, Variety)
        .join(Crop, Crop.id == FinishedGoodsLot.crop_id)
        .outerjoin(Variety, Variety.id == FinishedGoodsLot.variety_id)
    )


def _load_source_lot_ids(db: Session, *, event_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[uuid.UUID]]:
    grouped: dict[uuid.UUID, list[uuid.UUID]] = {eid: [] for eid in event_ids}
    if not event_ids:
        return grouped
    rows = db.execute(
        select(PackingInputLine.packing_event_id, PackingInputLine.harvested_produce_lot_id)
        .join(HarvestedProduceLot, HarvestedProduceLot.id == PackingInputLine.harvested_produce_lot_id)
        .where(PackingInputLine.packing_event_id.in_(event_ids))
        .order_by(HarvestedProduceLot.code, HarvestedProduceLot.id)
    ).all()
    for eid, lot_id in rows:
        grouped[eid].append(lot_id)
    return grouped


def _row_to_finished_goods_lot_read(row, source_lot_ids: list[uuid.UUID]) -> FinishedGoodsLotRead:
    lot: FinishedGoodsLot = row[0]
    crop: Crop = row[1]
    variety: Variety | None = row[2]
    return FinishedGoodsLotRead(
        id=lot.id, tenant_id=lot.tenant_id, farm_id=lot.farm_id, code=lot.code,
        packing_event_id=lot.packing_event_id,
        crop=CropSummary(id=crop.id, code=crop.code, common_name=crop.common_name),
        variety=(
            VarietySummary(id=variety.id, code=variety.code, name=variety.name) if variety is not None else None
        ),
        net_packed_weight_kg=lot.net_packed_weight_kg, package_count=lot.package_count,
        source_produce_lot_ids=source_lot_ids, effective_time=lot.effective_time, recorded_time=lot.recorded_time,
    )


def get_finished_goods_lot(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, finished_goods_lot_id: uuid.UUID
) -> FinishedGoodsLotRead:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    row = db.execute(
        _finished_goods_lot_header_query().where(
            FinishedGoodsLot.id == finished_goods_lot_id, FinishedGoodsLot.tenant_id == tenant_id,
            FinishedGoodsLot.farm_id == farm_id,
        )
    ).first()
    if row is None:
        raise FinishedGoodsLotNotFoundError(str(finished_goods_lot_id))
    lot: FinishedGoodsLot = row[0]
    source_lot_ids = _load_source_lot_ids(db, event_ids=[lot.packing_event_id])[lot.packing_event_id]
    return _row_to_finished_goods_lot_read(row, source_lot_ids)


def list_finished_goods_lots(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> list[FinishedGoodsLotRead]:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    rows = db.execute(
        _finished_goods_lot_header_query()
        .where(FinishedGoodsLot.tenant_id == tenant_id, FinishedGoodsLot.farm_id == farm_id)
        .order_by(FinishedGoodsLot.code)
    ).all()
    event_ids = [r[0].packing_event_id for r in rows]
    lines_by_event = _load_source_lot_ids(db, event_ids=event_ids)
    return [_row_to_finished_goods_lot_read(r, lines_by_event[r[0].packing_event_id]) for r in rows]
