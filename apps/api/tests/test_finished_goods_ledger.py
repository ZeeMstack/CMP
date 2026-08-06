"""Unit/integration coverage for CMP-016 beyond the acceptance flow:
deterministic receipt identity, exact field projection, Decimal
canonicalization, BIGINT package-count bounds, and confirmation that
CMP-014's own harvest-receipt behavior is completely unaffected."""
import uuid
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.services import finished_goods_ledger_service, packing_service, produce_lot_ledger_service
from tests._packing_scenario import build_committed_scenario, cleanup_scenario, now

MAX_WHOLE_UNIT_COUNT = 9223372036854775807


def _pack(scenario, *, db, package_count, packed_output="3.000", client_command_id=None):
    return packing_service.record_packing(
        db, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=client_command_id or uuid.uuid4(), effective_time=now(),
        finished_goods_lot_code=f"FG-{uuid.uuid4().hex[:8]}", package_count=package_count,
        packed_output_weight_kg=Decimal(packed_output), process_loss_weight_kg=Decimal("0"),
        rejected_weight_kg=Decimal(str(Decimal(scenario["lot_a_weight"]) - Decimal(packed_output))), note=None,
        input_lines=[
            {
                "harvested_produce_lot_id": scenario["lot_a_id"],
                "consumed_weight_kg": Decimal(scenario["lot_a_weight"]), "consumed_whole_unit_count": None,
                "note": None,
            }
        ],
    )


@pytest.mark.integration
def test_deterministic_receipt_id_equals_finished_goods_lot_id(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        event = _pack(scenario, db=session, package_count=4)
        detail = packing_service.get_packing_event(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], packing_event_id=event.id
        )
        fg_lot_id = detail.finished_goods_lot.id
        ledger = finished_goods_ledger_service.get_ledger(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], finished_goods_lot_id=fg_lot_id
        )
        assert len(ledger) == 1
        assert ledger[0].id == fg_lot_id
        assert ledger[0].finished_goods_lot_id == fg_lot_id
        assert ledger[0].packing_event_id == event.id
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_receipt_weight_and_effective_recorded_time_match_lot_exactly(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        event = _pack(scenario, db=session, package_count=4, packed_output="5.000")
        detail = packing_service.get_packing_event(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], packing_event_id=event.id
        )
        fg_lot = detail.finished_goods_lot
        ledger = finished_goods_ledger_service.get_ledger(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], finished_goods_lot_id=fg_lot.id
        )
        entry = ledger[0]
        assert entry.weight_delta_kg == Decimal("5.000")
        assert entry.package_count_delta == 4
        assert entry.effective_time == detail.effective_time
        assert entry.note is None
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_balance_reflects_receipt_weight_and_count(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        event = _pack(scenario, db=session, package_count=9, packed_output="7.500")
        detail = packing_service.get_packing_event(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], packing_event_id=event.id
        )
        fg_lot_id = detail.finished_goods_lot.id
        balance = finished_goods_ledger_service.get_balance(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], finished_goods_lot_id=fg_lot_id
        )
        assert balance.available_weight_kg == Decimal("7.500")
        assert balance.received_weight_kg == Decimal("7.500")
        assert balance.available_package_count == 9
        assert balance.received_package_count == 9
        assert balance.entry_count == 1
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_package_count_bigint_max_accepted(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        event = _pack(scenario, db=session, package_count=MAX_WHOLE_UNIT_COUNT)
        detail = packing_service.get_packing_event(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], packing_event_id=event.id
        )
        fg_lot_id = detail.finished_goods_lot.id
        ledger = finished_goods_ledger_service.get_ledger(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], finished_goods_lot_id=fg_lot_id
        )
        assert ledger[0].package_count_delta == MAX_WHOLE_UNIT_COUNT
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_cmp014_harvest_receipt_behavior_unaffected(test_engine) -> None:
    """Regression: packing (and its finished-goods receipt) must not
    change lot A's own CMP-014 harvest_receipt row or its balance."""
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        balance_before = produce_lot_ledger_service.get_balance(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], produce_lot_id=scenario["lot_a_id"]
        )
        assert balance_before.available_weight_kg == Decimal("10.000")

        _pack(scenario, db=session, package_count=4, packed_output="10.000")

        produce_ledger = produce_lot_ledger_service.get_ledger(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], produce_lot_id=scenario["lot_a_id"]
        )
        receipt = next(e for e in produce_ledger if e.entry_kind == "harvest_receipt")
        assert receipt.weight_delta_kg == Decimal("10.000")
        assert receipt.note is None
        balance_after = produce_lot_ledger_service.get_balance(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], produce_lot_id=scenario["lot_a_id"]
        )
        assert balance_after.available_weight_kg == Decimal("0.000")
        assert balance_after.received_weight_kg == Decimal("10.000")
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])
