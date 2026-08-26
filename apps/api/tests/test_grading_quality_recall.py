"""POSTHARVEST-OPS-001C: Quality Hold / Recall source-material gate
coverage -- mirrors packing_service's own established gate semantics."""
import uuid

import pytest

from app.services import quality_hold_service, recall_service
from app.services.errors import QualityHoldOpenError, RecallContainmentOpenError
from tests._grading_scenario import build_committed_scenario, cleanup_scenario, now
from tests.test_grading import _grade, _output, _session


@pytest.mark.integration
def test_open_quality_hold_blocks_grading(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        quality_hold_service.place_quality_hold(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(), effective_time=now(),
            source_observation_event_id=None, reason_code="QUALITY", reason_text="Test hold",
        )
        with pytest.raises(QualityHoldOpenError):
            _grade(
                scenario, db=session, input_presented="10.000", remainder="0",
                outputs=[_output(scenario, weight="10.000")],
            )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_closed_hold_permits_grading(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        hold = quality_hold_service.place_quality_hold(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(), effective_time=now(),
            source_observation_event_id=None, reason_code="QUALITY", reason_text="Test hold",
        )
        quality_hold_service.release_quality_hold(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            batch_id=scenario["batch_id"], hold_id=hold.id, client_command_id=uuid.uuid4(), effective_time=now(),
            release_reason="Resolved",
        )
        event = _grade(
            scenario, db=session, input_presented="10.000", remainder="0",
            outputs=[_output(scenario, weight="10.000")],
        )
        assert event.id is not None
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_open_batch_recall_blocks_grading(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        recall_service.open_recall_case(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), effective_time=now(), code=f"RECALL-{scenario['suffix']}",
            crop_batch_id=scenario["batch_id"], harvested_produce_lot_id=None, finished_goods_lot_id=None,
            reason_code="CONTAMINATION", reason_text="Test recall",
        )
        with pytest.raises(RecallContainmentOpenError):
            _grade(
                scenario, db=session, input_presented="10.000", remainder="0",
                outputs=[_output(scenario, weight="10.000")],
            )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_open_produce_lot_recall_blocks_grading(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        recall_service.open_recall_case(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), effective_time=now(), code=f"RECALL-{scenario['suffix']}",
            crop_batch_id=None, harvested_produce_lot_id=scenario["lot_a_id"], finished_goods_lot_id=None,
            reason_code="CONTAMINATION", reason_text="Test recall",
        )
        with pytest.raises(RecallContainmentOpenError):
            _grade(
                scenario, db=session, input_presented="10.000", remainder="0",
                outputs=[_output(scenario, weight="10.000")],
            )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_exact_replay_returns_original_even_after_later_hold(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        command_id = uuid.uuid4()
        fixed_output = _output(scenario, weight="10.000", code="GPL-FIXED")
        fixed_effective_time = now()
        first = _grade(
            scenario, db=session, input_presented="10.000", remainder="0",
            outputs=[fixed_output], client_command_id=command_id, effective_time=fixed_effective_time,
        )
        quality_hold_service.place_quality_hold(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(), effective_time=now(),
            source_observation_event_id=None, reason_code="QUALITY", reason_text="Opened after success",
        )
        second = _grade(
            scenario, db=session, input_presented="10.000", remainder="0",
            outputs=[fixed_output], client_command_id=command_id, effective_time=fixed_effective_time,
        )
        assert first.id == second.id
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])
