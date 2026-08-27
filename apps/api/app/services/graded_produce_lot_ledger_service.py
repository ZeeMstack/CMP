import uuid

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.graded_produce_lot import GradedProduceLot
from app.models.graded_produce_lot_ledger_entry import GradedProduceLotLedgerEntry
from app.schemas.graded_produce_lot_ledger import GradedProduceLotBalanceRead, GradedProduceLotLedgerEntryRead
from app.services import farm_service
from app.services.errors import FarmNotFoundError, GradedProduceLotNotFoundError


def _require_active_farm(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID):
    farm = farm_service.get_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    if farm.status != "active":
        raise FarmNotFoundError(str(farm_id))
    return farm


def _get_lot(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, graded_produce_lot_id: uuid.UUID
) -> GradedProduceLot:
    lot = db.execute(
        select(GradedProduceLot).where(
            GradedProduceLot.id == graded_produce_lot_id, GradedProduceLot.tenant_id == tenant_id,
            GradedProduceLot.farm_id == farm_id,
        )
    ).scalar_one_or_none()
    if lot is None:
        raise GradedProduceLotNotFoundError(str(graded_produce_lot_id))
    return lot


def get_ledger(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, graded_produce_lot_id: uuid.UUID
) -> list[GradedProduceLotLedgerEntryRead]:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    lot = _get_lot(db, tenant_id=tenant_id, farm_id=farm_id, graded_produce_lot_id=graded_produce_lot_id)
    rows = db.execute(
        select(GradedProduceLotLedgerEntry)
        .where(GradedProduceLotLedgerEntry.graded_produce_lot_id == lot.id)
        .order_by(
            GradedProduceLotLedgerEntry.effective_time, GradedProduceLotLedgerEntry.recorded_time,
            GradedProduceLotLedgerEntry.id,
        )
    ).scalars()
    return [
        GradedProduceLotLedgerEntryRead(
            id=e.id, entry_kind=e.entry_kind, graded_produce_lot_id=e.graded_produce_lot_id,
            graded_produce_lot_code=lot.code, grading_event_id=e.grading_event_id,
            packing_event_id=e.packing_event_id, actor_user_id=e.actor_user_id,
            weight_delta_kg=e.weight_delta_kg, whole_unit_count_delta=e.whole_unit_count_delta,
            effective_time=e.effective_time, recorded_time=e.recorded_time, note=e.note,
        )
        for e in rows
    ]


def get_balance(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, graded_produce_lot_id: uuid.UUID
) -> GradedProduceLotBalanceRead:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    lot = _get_lot(db, tenant_id=tenant_id, farm_id=farm_id, graded_produce_lot_id=graded_produce_lot_id)

    # `available_*` sums every ledger entry ever posted against this lot —
    # a future `packing_consumption`-equivalent negative delta (001E) will
    # correctly reduce it with no query-shape change. `received_*` sums
    # only `grading_receipt` entries — the lot's original inflow.
    row = db.execute(
        select(
            func.sum(GradedProduceLotLedgerEntry.weight_delta_kg).label("available_weight"),
            func.sum(
                case(
                    (
                        GradedProduceLotLedgerEntry.entry_kind == "grading_receipt",
                        GradedProduceLotLedgerEntry.weight_delta_kg,
                    )
                )
            ).label("received_weight"),
            func.sum(GradedProduceLotLedgerEntry.whole_unit_count_delta).label("available_count"),
            func.sum(
                case(
                    (
                        GradedProduceLotLedgerEntry.entry_kind == "grading_receipt",
                        GradedProduceLotLedgerEntry.whole_unit_count_delta,
                    )
                )
            ).label("received_count"),
            func.count().label("entry_count"),
            func.max(GradedProduceLotLedgerEntry.effective_time).label("last_effective_time"),
        ).where(GradedProduceLotLedgerEntry.graded_produce_lot_id == lot.id)
    ).one()

    return GradedProduceLotBalanceRead(
        graded_produce_lot_id=lot.id, graded_produce_lot_code=lot.code, received_weight_kg=row.received_weight,
        available_weight_kg=row.available_weight, received_whole_unit_count=row.received_count,
        available_whole_unit_count=row.available_count, entry_count=row.entry_count,
        last_effective_time=row.last_effective_time,
    )
