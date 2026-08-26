"""POSTHARVEST-OPS-001C: whole-unit-count semantics -- reconciliation,
mode consistency, and source-availability coverage."""
from decimal import Decimal

import pytest

from app.services import grading_service, produce_lot_ledger_service
from app.services.errors import GradingValidationError, InsufficientHarvestedProduceLotBalanceError
from tests._grading_scenario import build_committed_scenario, cleanup_scenario
from tests.test_grading import _grade, _output, _session


@pytest.mark.integration
def test_count_bearing_source_requires_counts(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=40)
    session, conn = _session(test_engine)
    try:
        with pytest.raises(GradingValidationError):
            _grade(
                scenario, db=session, input_presented="10.000", remainder="0",
                outputs=[_output(scenario, weight="10.000")],
                input_count=None,
            )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_count_reconciliation_exact(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=40)
    session, conn = _session(test_engine)
    try:
        event = _grade(
            scenario, db=session, input_presented="10.000", rejected="1.000", loss="1.000", sample="0",
            remainder="2.000", outputs=[_output(scenario, weight="6.000", count=24)],
            input_count=40, rejected_count=4, loss_count=4, sample_count=0, remainder_count=8,
        )
        detail = grading_service.get_grading_event(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], grading_event_id=event.id
        )
        assert detail.processed_whole_unit_count == 32
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_count_under_reconciliation_rejected(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=40)
    session, conn = _session(test_engine)
    try:
        with pytest.raises(GradingValidationError):
            _grade(
                scenario, db=session, input_presented="10.000", remainder="2.000",
                outputs=[_output(scenario, weight="8.000", count=30)],
                input_count=40, rejected_count=0, loss_count=0, sample_count=0, remainder_count=8,
            )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_count_over_reconciliation_rejected(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=40)
    session, conn = _session(test_engine)
    try:
        with pytest.raises(GradingValidationError):
            _grade(
                scenario, db=session, input_presented="10.000", remainder="2.000",
                outputs=[_output(scenario, weight="8.000", count=35)],
                input_count=40, rejected_count=0, loss_count=0, sample_count=0, remainder_count=8,
            )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_presented_count_cannot_exceed_available_count(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="50.000", lot_a_count=40)
    session, conn = _session(test_engine)
    try:
        with pytest.raises(InsufficientHarvestedProduceLotBalanceError):
            _grade(
                scenario, db=session, input_presented="50.000", remainder="10.000",
                outputs=[_output(scenario, weight="40.000", count=40)],
                input_count=50, rejected_count=0, loss_count=0, sample_count=0, remainder_count=10,
            )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_weight_only_source_requires_all_grading_counts_null(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        with pytest.raises(GradingValidationError):
            _grade(
                scenario, db=session, input_presented="10.000", remainder="0",
                outputs=[_output(scenario, weight="10.000")], input_count=10,
            )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_output_graded_lot_count_receipt_exact(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=40)
    session, conn = _session(test_engine)
    try:
        event = _grade(
            scenario, db=session, input_presented="10.000", remainder="0",
            outputs=[_output(scenario, weight="10.000", count=40)],
            input_count=40, rejected_count=0, loss_count=0, sample_count=0, remainder_count=0,
        )
        detail = grading_service.get_grading_event(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], grading_event_id=event.id
        )
        assert detail.outputs[0].original_received_whole_unit_count == 40
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_remainder_count_remains_available(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=40)
    session, conn = _session(test_engine)
    try:
        _grade(
            scenario, db=session, input_presented="10.000", remainder="4.000",
            outputs=[_output(scenario, weight="6.000", count=24)],
            input_count=40, rejected_count=0, loss_count=0, sample_count=0, remainder_count=16,
        )
        balance = produce_lot_ledger_service.get_balance(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
            produce_lot_id=scenario["lot_a_id"],
        )
        assert balance.available_weight_kg == Decimal("4.000")
        assert balance.available_whole_unit_count == 16
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])
