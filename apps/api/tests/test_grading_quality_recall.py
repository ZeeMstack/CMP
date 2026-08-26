"""POSTHARVEST-OPS-001C: Quality Hold / Recall source-material gate
coverage -- mirrors packing_service's own established gate semantics."""
import uuid

import pytest
from sqlalchemy import text

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


@pytest.mark.integration
def test_grading_scenario_cleanup_leaves_no_recall_rows_behind(test_engine) -> None:
    """PRE-COMMIT CORRECTION (POSTHARVEST-OPS-001D verification pass):
    `cleanup_scenario` previously never deleted the RecallCase/scope rows
    this file's own tests create (see `_grading_scenario.cleanup_scenario`'s
    docstring) -- orphaning them once the tenant was deleted underneath
    them, and blocking every full-chain migration downgrade test until
    manually cleaned. Proves the fix directly: open a RecallCase through
    the exact same path `test_open_batch_recall_blocks_grading` uses, run
    the normal scenario cleanup, and confirm zero RecallCase/scope/closure
    rows remain for that tenant."""
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    tenant_id = scenario["tenant_id"]
    session, conn = _session(test_engine)
    try:
        recall_service.open_recall_case(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
            actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(), effective_time=now(),
            code=f"RECALL-CLEANUP-{scenario['suffix']}", crop_batch_id=scenario["batch_id"],
            harvested_produce_lot_id=None, finished_goods_lot_id=None,
            reason_code="CONTAMINATION", reason_text="Cleanup hermeticity proof.",
        )
        session.commit()
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, tenant_id)

    with test_engine.connect() as check_conn:
        remaining_cases = check_conn.execute(
            text("SELECT count(*) FROM recall_cases WHERE tenant_id = :tid"), {"tid": tenant_id}
        ).scalar_one()
        remaining_batch_scope = check_conn.execute(
            text("SELECT count(*) FROM recall_scope_batches WHERE tenant_id = :tid"), {"tid": tenant_id}
        ).scalar_one()
        remaining_produce_lot_scope = check_conn.execute(
            text("SELECT count(*) FROM recall_scope_produce_lots WHERE tenant_id = :tid"), {"tid": tenant_id}
        ).scalar_one()
        remaining_closures = check_conn.execute(
            text("SELECT count(*) FROM recall_case_closures WHERE tenant_id = :tid"), {"tid": tenant_id}
        ).scalar_one()
    assert remaining_cases == 0
    assert remaining_batch_scope == 0
    assert remaining_produce_lot_scope == 0
    assert remaining_closures == 0
