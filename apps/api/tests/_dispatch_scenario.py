"""Shared, non-collected scenario helpers for CMP-017 dispatch tests.
Builds on `tests._packing_scenario`'s own `build_committed_scenario` (a
committed tenant/farm/crop/variety/workflow/batch with two independent
harvested produce lots), adding a `pack_one`/`pack_two` convenience wrapper
that packs a lot into a finished-goods lot, and a `dispatch_one` wrapper
that dispatches from it. Not a test file itself (pytest's default
`test_*.py` discovery glob does not match this name)."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.services import dispatch_service, packing_service


def now():
    return datetime.now(timezone.utc)


def pack_one(
    scenario, db: Session, *, lot_key: str = "lot_a_id", package_count: int = 10,
    packed_output_weight_kg: Decimal = Decimal("8.000"), code_suffix: str = "",
):
    """Packs the scenario's given source produce lot into a new
    finished-goods lot. Returns (finished_goods_lot_id, packing_event_id).

    POSTHARVEST-OPS-001E: Packing no longer accepts a HarvestedProduceLot
    directly -- `lot_key` (e.g. "lot_a_id"/"lot_b_id") is mapped to its
    corresponding GradedProduceLot key ("gpl_a_id"/"gpl_b_id"), which
    `tests._packing_scenario.build_committed_scenario` already grades in
    full ahead of time."""
    gpl_key = "gpl_" + lot_key.removeprefix("lot_")
    event = packing_service.record_packing(
        db, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), pack_specification_version_id=scenario["pack_specification_version_id"],
        effective_time=now(),
        finished_goods_lot_code=f"FG-{scenario['suffix']}{code_suffix}", package_count=package_count,
        packed_output_weight_kg=packed_output_weight_kg, process_loss_weight_kg=Decimal("0"),
        rejected_weight_kg=Decimal("0"), note=None,
        input_lines=[
            {
                "graded_produce_lot_id": scenario[gpl_key], "consumed_weight_kg": packed_output_weight_kg,
                "consumed_whole_unit_count": None, "note": None,
            }
        ],
    )
    detail = packing_service.get_packing_event(
        db, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], packing_event_id=event.id
    )
    return detail.finished_goods_lot.id, event.id


def dispatch_one(
    scenario, db: Session, *, finished_goods_lot_id, dispatched_weight_kg: Decimal = Decimal("3.000"),
    dispatched_package_count: int = 4, code_suffix: str = "", client_command_id=None, effective_time=None,
    external_reference: str | None = None, note: str | None = None,
):
    """Dispatches one line for the given finished-goods lot. Returns the
    DispatchEvent ORM object."""
    return dispatch_service.record_dispatch(
        db, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=client_command_id or uuid.uuid4(), effective_time=effective_time or now(),
        code=f"DISP-{scenario['suffix']}{code_suffix}", external_reference=external_reference, note=note,
        lines=[
            {
                "finished_goods_lot_id": finished_goods_lot_id, "dispatched_weight_kg": dispatched_weight_kg,
                "dispatched_package_count": dispatched_package_count,
            }
        ],
    )
