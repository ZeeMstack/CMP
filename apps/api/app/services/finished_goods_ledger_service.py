import uuid

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.finished_goods_ledger_entry import FinishedGoodsLedgerEntry
from app.models.finished_goods_lot import FinishedGoodsLot
from app.schemas.finished_goods_ledger import FinishedGoodsBalanceRead, FinishedGoodsLedgerEntryRead
from app.services import farm_service
from app.services.errors import FarmNotFoundError, FinishedGoodsLotNotFoundError


def _require_active_farm(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID):
    farm = farm_service.get_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    if farm.status != "active":
        raise FarmNotFoundError(str(farm_id))
    return farm


def _get_lot(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, finished_goods_lot_id: uuid.UUID
) -> FinishedGoodsLot:
    lot = db.execute(
        select(FinishedGoodsLot).where(
            FinishedGoodsLot.id == finished_goods_lot_id, FinishedGoodsLot.tenant_id == tenant_id,
            FinishedGoodsLot.farm_id == farm_id,
        )
    ).scalar_one_or_none()
    if lot is None:
        raise FinishedGoodsLotNotFoundError(str(finished_goods_lot_id))
    return lot


def get_ledger(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, finished_goods_lot_id: uuid.UUID
) -> list[FinishedGoodsLedgerEntryRead]:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    lot = _get_lot(db, tenant_id=tenant_id, farm_id=farm_id, finished_goods_lot_id=finished_goods_lot_id)
    rows = db.execute(
        select(FinishedGoodsLedgerEntry)
        .where(FinishedGoodsLedgerEntry.finished_goods_lot_id == lot.id)
        .order_by(
            FinishedGoodsLedgerEntry.effective_time, FinishedGoodsLedgerEntry.recorded_time,
            FinishedGoodsLedgerEntry.id,
        )
    ).scalars()
    return [
        FinishedGoodsLedgerEntryRead(
            id=e.id, entry_kind=e.entry_kind, finished_goods_lot_id=e.finished_goods_lot_id,
            finished_goods_lot_code=lot.code, packing_event_id=e.packing_event_id, actor_user_id=e.actor_user_id,
            weight_delta_kg=e.weight_delta_kg, package_count_delta=e.package_count_delta,
            effective_time=e.effective_time, recorded_time=e.recorded_time, note=e.note,
        )
        for e in rows
    ]


def get_balance(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, finished_goods_lot_id: uuid.UUID
) -> FinishedGoodsBalanceRead:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    lot = _get_lot(db, tenant_id=tenant_id, farm_id=farm_id, finished_goods_lot_id=finished_goods_lot_id)

    # `available_*` sums every ledger entry ever posted against this lot —
    # a future negative dispatch-issue delta will correctly reduce it, with
    # no query change needed here. `received_*` sums only `packing_receipt`
    # entries — the lot's original inflow, which never shrinks regardless
    # of later consumption.
    row = db.execute(
        select(
            func.sum(FinishedGoodsLedgerEntry.weight_delta_kg).label("available_weight"),
            func.sum(
                case(
                    (FinishedGoodsLedgerEntry.entry_kind == "packing_receipt", FinishedGoodsLedgerEntry.weight_delta_kg)
                )
            ).label("received_weight"),
            func.sum(FinishedGoodsLedgerEntry.package_count_delta).label("available_count"),
            func.sum(
                case(
                    (
                        FinishedGoodsLedgerEntry.entry_kind == "packing_receipt",
                        FinishedGoodsLedgerEntry.package_count_delta,
                    )
                )
            ).label("received_count"),
            func.count().label("entry_count"),
            func.max(FinishedGoodsLedgerEntry.effective_time).label("last_effective_time"),
        ).where(FinishedGoodsLedgerEntry.finished_goods_lot_id == lot.id)
    ).one()

    return FinishedGoodsBalanceRead(
        finished_goods_lot_id=lot.id, finished_goods_lot_code=lot.code, received_weight_kg=row.received_weight,
        available_weight_kg=row.available_weight, received_package_count=row.received_count,
        available_package_count=row.available_count, entry_count=row.entry_count,
        last_effective_time=row.last_effective_time,
    )
