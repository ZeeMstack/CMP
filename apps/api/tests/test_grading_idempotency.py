"""POSTHARVEST-OPS-001C: exact idempotent replay coverage."""
import uuid

import pytest
from sqlalchemy import func, select

from app.models.audit_event import AuditEvent
from app.models.graded_produce_lot_ledger_entry import GradedProduceLotLedgerEntry
from app.models.produce_lot_ledger_entry import ProduceLotLedgerEntry
from app.services import grading_service
from app.services.errors import GradingCommandReusedWithDifferentPayloadError
from tests._grading_scenario import build_committed_scenario, cleanup_scenario, now
from tests.test_grading import _grade, _output, _session


@pytest.mark.integration
def test_exact_replay_returns_same_event_and_lots(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        command_id = uuid.uuid4()
        fixed_output = _output(scenario, weight="10.000", code="GPL-FIXED")
        effective_time = now()
        first = _grade(
            scenario, db=session, input_presented="10.000", remainder="0", outputs=[fixed_output],
            client_command_id=command_id, effective_time=effective_time,
        )
        second = _grade(
            scenario, db=session, input_presented="10.000", remainder="0", outputs=[fixed_output],
            client_command_id=command_id, effective_time=effective_time,
        )
        assert first.id == second.id

        first_detail = grading_service.get_grading_event(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], grading_event_id=first.id
        )
        second_detail = grading_service.get_grading_event(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], grading_event_id=second.id
        )
        assert [o.id for o in first_detail.outputs] == [o.id for o in second_detail.outputs]
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_replay_creates_no_duplicate_source_debit(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        command_id = uuid.uuid4()
        fixed_output = _output(scenario, weight="10.000", code="GPL-FIXED")
        effective_time = now()
        _grade(
            scenario, db=session, input_presented="10.000", remainder="0", outputs=[fixed_output],
            client_command_id=command_id, effective_time=effective_time,
        )
        _grade(
            scenario, db=session, input_presented="10.000", remainder="0", outputs=[fixed_output],
            client_command_id=command_id, effective_time=effective_time,
        )
        debit_count = session.execute(
            select(func.count()).select_from(ProduceLotLedgerEntry).where(
                ProduceLotLedgerEntry.produce_lot_id == scenario["lot_a_id"],
                ProduceLotLedgerEntry.entry_kind == "grading_consumption",
            )
        ).scalar_one()
        assert debit_count == 1
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_replay_creates_no_duplicate_graded_receipts(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        command_id = uuid.uuid4()
        fixed_output = _output(scenario, weight="10.000", code="GPL-FIXED")
        effective_time = now()
        first = _grade(
            scenario, db=session, input_presented="10.000", remainder="0", outputs=[fixed_output],
            client_command_id=command_id, effective_time=effective_time,
        )
        _grade(
            scenario, db=session, input_presented="10.000", remainder="0", outputs=[fixed_output],
            client_command_id=command_id, effective_time=effective_time,
        )
        detail = grading_service.get_grading_event(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], grading_event_id=first.id
        )
        receipt_count = session.execute(
            select(func.count()).select_from(GradedProduceLotLedgerEntry).where(
                GradedProduceLotLedgerEntry.graded_produce_lot_id == detail.outputs[0].id,
                GradedProduceLotLedgerEntry.entry_kind == "grading_receipt",
            )
        ).scalar_one()
        assert receipt_count == 1
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_replay_creates_no_duplicate_audit(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        command_id = uuid.uuid4()
        fixed_output = _output(scenario, weight="10.000", code="GPL-FIXED")
        effective_time = now()
        first = _grade(
            scenario, db=session, input_presented="10.000", remainder="0", outputs=[fixed_output],
            client_command_id=command_id, effective_time=effective_time,
        )
        _grade(
            scenario, db=session, input_presented="10.000", remainder="0", outputs=[fixed_output],
            client_command_id=command_id, effective_time=effective_time,
        )
        audit_count = session.execute(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action == "grading_event.created", AuditEvent.entity_id == first.id
            )
        ).scalar_one()
        assert audit_count == 1
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_changed_payload_same_command_id_conflicts(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        command_id = uuid.uuid4()
        _grade(
            scenario, db=session, input_presented="10.000", remainder="0",
            outputs=[_output(scenario, weight="10.000", code="A")], client_command_id=command_id,
        )
        with pytest.raises(GradingCommandReusedWithDifferentPayloadError):
            _grade(
                scenario, db=session, input_presented="10.000", remainder="0",
                outputs=[_output(scenario, weight="10.000", code="B")], client_command_id=command_id,
            )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])
