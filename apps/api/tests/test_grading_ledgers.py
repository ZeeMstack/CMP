"""POSTHARVEST-OPS-001C: HarvestedProduceLot grading-consumption debit and
GradedProduceLot grading-receipt ledger coverage."""
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.services import graded_produce_lot_ledger_service, grading_service, produce_lot_ledger_service
from app.services.errors import DuplicateGradedProduceLotCodeError
from tests._grading_scenario import build_committed_scenario, cleanup_scenario, now
from tests.test_grading import _grade, _output, _session


@pytest.mark.integration
def test_exactly_one_source_grading_consumption(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        _grade(
            scenario, db=session, input_presented="6.000", remainder="0",
            outputs=[_output(scenario, weight="6.000")],
        )
        ledger = produce_lot_ledger_service.get_ledger(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
            produce_lot_id=scenario["lot_a_id"],
        )
        debits = [e for e in ledger if e.entry_kind == "grading_consumption"]
        assert len(debits) == 1
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_source_debit_equals_processed_not_presented(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        _grade(
            scenario, db=session, input_presented="10.000", remainder="4.000",
            outputs=[_output(scenario, weight="6.000")],
        )
        ledger = produce_lot_ledger_service.get_ledger(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
            produce_lot_id=scenario["lot_a_id"],
        )
        debit = next(e for e in ledger if e.entry_kind == "grading_consumption")
        assert debit.weight_delta_kg == Decimal("-6.000")
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_remainder_creates_no_source_credit(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        _grade(
            scenario, db=session, input_presented="10.000", remainder="4.000",
            outputs=[_output(scenario, weight="6.000")],
        )
        ledger = produce_lot_ledger_service.get_ledger(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
            produce_lot_id=scenario["lot_a_id"],
        )
        positive_entries = [e for e in ledger if e.weight_delta_kg > 0]
        # Only the original harvest_receipt should ever be positive -- no
        # separate "remainder credit" entry is ever created.
        assert len(positive_entries) == 1
        assert positive_entries[0].entry_kind == "harvest_receipt"
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_one_grading_receipt_per_graded_produce_lot(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        event = _grade(
            scenario, db=session, input_presented="10.000", remainder="0",
            outputs=[_output(scenario, weight="10.000")],
        )
        detail = grading_service.get_grading_event(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], grading_event_id=event.id
        )
        graded_lot_id = detail.outputs[0].id
        ledger = graded_produce_lot_ledger_service.get_ledger(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], graded_produce_lot_id=graded_lot_id
        )
        receipts = [e for e in ledger if e.entry_kind == "grading_receipt"]
        assert len(receipts) == 1
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_graded_receipt_equals_original_output(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        event = _grade(
            scenario, db=session, input_presented="7.500", remainder="0",
            outputs=[_output(scenario, weight="7.500")],
        )
        detail = grading_service.get_grading_event(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], grading_event_id=event.id
        )
        graded_lot_id = detail.outputs[0].id
        ledger = graded_produce_lot_ledger_service.get_ledger(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], graded_produce_lot_id=graded_lot_id
        )
        receipt = next(e for e in ledger if e.entry_kind == "grading_receipt")
        assert receipt.weight_delta_kg == Decimal("7.500")
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_graded_balance_read_exact(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        event = _grade(
            scenario, db=session, input_presented="7.500", remainder="0",
            outputs=[_output(scenario, weight="7.500")],
        )
        detail = grading_service.get_grading_event(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], grading_event_id=event.id
        )
        graded_lot_id = detail.outputs[0].id
        balance = graded_produce_lot_ledger_service.get_balance(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], graded_produce_lot_id=graded_lot_id
        )
        assert balance.available_weight_kg == Decimal("7.500")
        assert balance.received_weight_kg == Decimal("7.500")
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_produce_lot_balance_cannot_go_negative_direct_sql(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        _grade(
            scenario, db=session, input_presented="10.000", remainder="0",
            outputs=[_output(scenario, weight="10.000")],
        )
        # Attempt a second, direct-SQL grading_consumption debit that would
        # drive the already-exhausted lot negative.
        with pytest.raises(DBAPIError):
            with session.begin_nested():
                session.execute(
                    text(
                        "INSERT INTO produce_lot_ledger_entries "
                        "(id, tenant_id, farm_id, produce_lot_id, grading_event_id, entry_kind, weight_delta_kg, "
                        " effective_time, recorded_time, actor_user_id) "
                        "VALUES (:id, :tenant_id, :farm_id, :produce_lot_id, :grading_event_id, "
                        " 'grading_consumption', -1.000, :now, :now, :actor_id)"
                    ),
                    {
                        "id": uuid.uuid4(), "tenant_id": scenario["tenant_id"], "farm_id": scenario["farm_id"],
                        "produce_lot_id": scenario["lot_a_id"], "grading_event_id": uuid.uuid4(), "now": now(),
                        "actor_id": scenario["user_id"],
                    },
                )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_direct_sql_forged_grading_consumption_rejected(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        # No matching grading_events row exists for this fabricated debit.
        with pytest.raises(DBAPIError):
            with session.begin_nested():
                session.execute(
                    text(
                        "INSERT INTO produce_lot_ledger_entries "
                        "(id, tenant_id, farm_id, produce_lot_id, grading_event_id, entry_kind, weight_delta_kg, "
                        " effective_time, recorded_time, actor_user_id) "
                        "VALUES (:id, :tenant_id, :farm_id, :produce_lot_id, :id, "
                        " 'grading_consumption', -1.000, :now, :now, :actor_id)"
                    ),
                    {
                        "id": uuid.uuid4(), "tenant_id": scenario["tenant_id"], "farm_id": scenario["farm_id"],
                        "produce_lot_id": scenario["lot_a_id"], "now": now(), "actor_id": scenario["user_id"],
                    },
                )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_direct_sql_forged_grading_receipt_rejected(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        with pytest.raises(DBAPIError):
            with session.begin_nested():
                session.execute(
                    text(
                        "INSERT INTO graded_produce_lot_ledger_entries "
                        "(id, tenant_id, farm_id, graded_produce_lot_id, grading_event_id, entry_kind, "
                        " weight_delta_kg, effective_time, recorded_time, actor_user_id) "
                        "VALUES (:id, :tenant_id, :farm_id, :id, :id, 'grading_receipt', 99.000, :now, :now, "
                        " :actor_id)"
                    ),
                    {
                        "id": uuid.uuid4(), "tenant_id": scenario["tenant_id"], "farm_id": scenario["farm_id"],
                        "now": now(), "actor_id": scenario["user_id"],
                    },
                )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


# --- PRE-COMMIT CORRECTION: GradedProduceLot code identity (items I, J) ------------


@pytest.mark.integration
def test_duplicate_graded_lot_code_same_tenant_rejected(test_engine) -> None:
    """Item I: reusing a GradedProduceLot code across two DIFFERENT
    GradingEvents in the SAME tenant must be rejected via the service's
    own IntegrityError-to-DuplicateGradedProduceLotCodeError mapping,
    mirroring HarvestedProduceLot/FinishedGoodsLot's own tenant-scoped,
    case-insensitive code uniqueness convention exactly."""
    scenario = build_committed_scenario(test_engine, lot_a_weight="20.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        _grade(
            scenario, db=session, input_presented="10.000", remainder="0",
            outputs=[_output(scenario, weight="10.000", code="GPL-SAME-CODE")],
        )
        with pytest.raises(DuplicateGradedProduceLotCodeError):
            _grade(
                scenario, db=session, input_presented="10.000", remainder="0",
                outputs=[_output(scenario, weight="10.000", code="gpl-same-code")],
            )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_same_graded_lot_code_different_tenant_accepted(test_engine) -> None:
    """Item J: the uniqueness scope is tenant-only (`ux_graded_produce_
    lots_tenant_code_lower` carries no farm_id column), exactly matching
    HarvestedProduceLot's `ux_harvested_produce_lots_tenant_code_lower`
    and FinishedGoodsLot's `ux_finished_goods_lots_tenant_code_lower` --
    the SAME code string in a DIFFERENT tenant (a genuinely different
    scope under this convention) must be accepted in both."""
    scenario_a = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    scenario_b = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session_a, conn_a = _session(test_engine)
    session_b, conn_b = _session(test_engine)
    try:
        event_a = _grade(
            scenario_a, db=session_a, input_presented="10.000", remainder="0",
            outputs=[_output(scenario_a, weight="10.000", code="GPL-CROSS-TENANT")],
        )
        event_b = _grade(
            scenario_b, db=session_b, input_presented="10.000", remainder="0",
            outputs=[_output(scenario_b, weight="10.000", code="GPL-CROSS-TENANT")],
        )
        assert event_a.id is not None
        assert event_b.id is not None
    finally:
        session_a.close()
        conn_a.close()
        session_b.close()
        conn_b.close()
        cleanup_scenario(test_engine, scenario_a["tenant_id"])
        cleanup_scenario(test_engine, scenario_b["tenant_id"])
