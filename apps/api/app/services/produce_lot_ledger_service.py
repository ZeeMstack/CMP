import uuid

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.harvested_produce_lot import HarvestedProduceLot
from app.models.produce_lot_ledger_entry import ProduceLotLedgerEntry
from app.schemas.produce_lot_ledger import ProduceLotBalanceRead, ProduceLotLedgerEntryRead
from app.services import farm_service
from app.services.errors import FarmNotFoundError, HarvestedProduceLotNotFoundError


def _require_active_farm(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID):
    farm = farm_service.get_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    if farm.status != "active":
        raise FarmNotFoundError(str(farm_id))
    return farm


def _get_lot(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, produce_lot_id: uuid.UUID) -> HarvestedProduceLot:
    lot = db.execute(
        select(HarvestedProduceLot).where(
            HarvestedProduceLot.id == produce_lot_id, HarvestedProduceLot.tenant_id == tenant_id,
            HarvestedProduceLot.farm_id == farm_id,
        )
    ).scalar_one_or_none()
    if lot is None:
        raise HarvestedProduceLotNotFoundError(str(produce_lot_id))
    return lot


def get_ledger(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, produce_lot_id: uuid.UUID
) -> list[ProduceLotLedgerEntryRead]:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    lot = _get_lot(db, tenant_id=tenant_id, farm_id=farm_id, produce_lot_id=produce_lot_id)
    rows = db.execute(
        select(ProduceLotLedgerEntry)
        .where(ProduceLotLedgerEntry.produce_lot_id == lot.id)
        .order_by(ProduceLotLedgerEntry.effective_time, ProduceLotLedgerEntry.recorded_time, ProduceLotLedgerEntry.id)
    ).scalars()
    return [
        ProduceLotLedgerEntryRead(
            id=e.id, entry_kind=e.entry_kind, produce_lot_id=e.produce_lot_id, produce_lot_code=lot.code,
            harvest_event_id=e.harvest_event_id,
            actor_user_id=e.actor_user_id, weight_delta_kg=e.weight_delta_kg,
            whole_unit_count_delta=e.whole_unit_count_delta, effective_time=e.effective_time,
            recorded_time=e.recorded_time, note=e.note,
        )
        for e in rows
    ]


def get_balance(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, produce_lot_id: uuid.UUID
) -> ProduceLotBalanceRead:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    lot = _get_lot(db, tenant_id=tenant_id, farm_id=farm_id, produce_lot_id=produce_lot_id)

    # `available_*` sums every ledger entry ever posted against this lot —
    # CMP-015's negative `packing_consumption` deltas correctly reduce it,
    # with no query change needed here (the shape already anticipated
    # this). `received_*` sums only `harvest_receipt` entries — the lot's
    # original inflow, which never shrinks regardless of later consumption.
    row = db.execute(
        select(
            func.sum(ProduceLotLedgerEntry.weight_delta_kg).label("available_weight"),
            func.sum(
                case((ProduceLotLedgerEntry.entry_kind == "harvest_receipt", ProduceLotLedgerEntry.weight_delta_kg))
            ).label("received_weight"),
            func.sum(ProduceLotLedgerEntry.whole_unit_count_delta).label("available_count"),
            func.sum(
                case(
                    (ProduceLotLedgerEntry.entry_kind == "harvest_receipt", ProduceLotLedgerEntry.whole_unit_count_delta)
                )
            ).label("received_count"),
            func.count().label("entry_count"),
            func.max(ProduceLotLedgerEntry.effective_time).label("last_effective_time"),
        ).where(ProduceLotLedgerEntry.produce_lot_id == lot.id)
    ).one()

    return ProduceLotBalanceRead(
        produce_lot_id=lot.id, produce_lot_code=lot.code, received_weight_kg=row.received_weight,
        available_weight_kg=row.available_weight, received_whole_unit_count=row.received_count,
        available_whole_unit_count=row.available_count, entry_count=row.entry_count,
        last_effective_time=row.last_effective_time,
    )
