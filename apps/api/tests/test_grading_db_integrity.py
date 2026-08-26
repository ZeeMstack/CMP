"""POSTHARVEST-OPS-001C: direct-SQL proofs that grading/graded-produce-lot
integrity is enforced at the database layer, not merely by the service.
`SET CONSTRAINTS ALL IMMEDIATE` forces DEFERRABLE INITIALLY DEFERRED
triggers to run inside a `begin_nested()` savepoint without ever
committing the outer transaction, mirroring test_transplant.py's own
established technique for this exact class of proof."""
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.services import grading_service, quality_hold_service, recall_service
from tests._grading_scenario import build_committed_scenario, cleanup_scenario, now
from tests.test_grading import _grade, _output, _session


def _insert_raw_grading_event(session, scenario, **overrides) -> uuid.UUID:
    event_id = overrides.get("id", uuid.uuid4())
    defaults = dict(
        id=event_id, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
        source_harvested_produce_lot_id=scenario["lot_a_id"],
        processing_hall_location_id=scenario["packing_hall_location_id"], effective_time=now(),
        actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(), request_fingerprint="fp",
        input_presented_weight_kg=Decimal("10.000"), rejected_weight_kg=Decimal("0"),
        loss_weight_kg=Decimal("0"), sample_weight_kg=Decimal("0"), remainder_weight_kg=Decimal("2.000"),
        input_presented_whole_unit_count=None, rejected_whole_unit_count=None, loss_whole_unit_count=None,
        sample_whole_unit_count=None, remainder_whole_unit_count=None,
    )
    defaults.update(overrides)
    session.execute(
        text(
            "INSERT INTO grading_events "
            "(id, tenant_id, farm_id, source_harvested_produce_lot_id, processing_hall_location_id, "
            " effective_time, actor_user_id, client_command_id, request_fingerprint, "
            " input_presented_weight_kg, rejected_weight_kg, loss_weight_kg, sample_weight_kg, "
            " remainder_weight_kg, input_presented_whole_unit_count, rejected_whole_unit_count, "
            " loss_whole_unit_count, sample_whole_unit_count, remainder_whole_unit_count) "
            "VALUES (:id, :tenant_id, :farm_id, :source_harvested_produce_lot_id, "
            " :processing_hall_location_id, :effective_time, :actor_user_id, :client_command_id, "
            " :request_fingerprint, :input_presented_weight_kg, :rejected_weight_kg, :loss_weight_kg, "
            " :sample_weight_kg, :remainder_weight_kg, :input_presented_whole_unit_count, "
            " :rejected_whole_unit_count, :loss_whole_unit_count, :sample_whole_unit_count, "
            " :remainder_whole_unit_count)"
        ),
        defaults,
    )
    return event_id


@pytest.mark.integration
def test_direct_sql_wrong_location_type_rejected(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        with pytest.raises(DBAPIError):
            with session.begin_nested():
                _insert_raw_grading_event(
                    session, scenario, processing_hall_location_id=scenario["other_location_id"]
                )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_direct_sql_inactive_hall_rejected(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        with pytest.raises(DBAPIError):
            with session.begin_nested():
                _insert_raw_grading_event(
                    session, scenario, processing_hall_location_id=scenario["inactive_hall_location_id"]
                )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_direct_sql_wrong_grade_crop_rejected(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        from app.services import crop_service, grade_definition_service
        from datetime import timedelta

        other_crop = crop_service.register_crop(
            session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
            code=f"other-{scenario['suffix']}", common_name="Tomato", scientific_name=None, crop_category="vine",
        )
        other_def = grade_definition_service.register_grade_definition(
            session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), code=f"other-grade-{scenario['suffix']}", name="Other",
            crop_id=other_crop.id, variety_id=None, description=None,
        )
        other_version = grade_definition_service.create_draft_version(
            session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), grade_definition_id=other_def.id, spec_notes=None,
        )
        grade_definition_service.activate_version(
            session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), grade_definition_id=other_def.id, version_id=other_version.id,
            effective_time=now() - timedelta(days=5),
        )
        event_id = _insert_raw_grading_event(session, scenario)
        with pytest.raises(DBAPIError):
            with session.begin_nested():
                session.execute(
                    text(
                        "INSERT INTO graded_produce_lots "
                        "(id, tenant_id, farm_id, grading_event_id, crop_id, variety_id, "
                        " grade_definition_version_id, code, original_received_weight_kg, effective_time) "
                        "VALUES (:id, :tenant_id, :farm_id, :event_id, :crop_id, :variety_id, :grade_version_id, "
                        " :code, 8.000, :effective_time)"
                    ),
                    {
                        "id": uuid.uuid4(), "tenant_id": scenario["tenant_id"], "farm_id": scenario["farm_id"],
                        "event_id": event_id, "crop_id": scenario["crop_id"], "variety_id": scenario["variety_id"],
                        "grade_version_id": other_version.id, "code": f"GPL-BAD-{uuid.uuid4().hex[:8]}",
                        "effective_time": now(),
                    },
                )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_direct_sql_grade_effective_window_violation_rejected(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        from app.services import grade_definition_service
        from datetime import timedelta

        draft_def = grade_definition_service.register_grade_definition(
            session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), code=f"draft-grade-{scenario['suffix']}", name="Draft",
            crop_id=scenario["crop_id"], variety_id=None, description=None,
        )
        draft_version = grade_definition_service.create_draft_version(
            session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), grade_definition_id=draft_def.id, spec_notes=None,
        )
        event_id = _insert_raw_grading_event(session, scenario)
        with pytest.raises(DBAPIError):
            with session.begin_nested():
                session.execute(
                    text(
                        "INSERT INTO graded_produce_lots "
                        "(id, tenant_id, farm_id, grading_event_id, crop_id, variety_id, "
                        " grade_definition_version_id, code, original_received_weight_kg, effective_time) "
                        "VALUES (:id, :tenant_id, :farm_id, :event_id, :crop_id, :variety_id, :grade_version_id, "
                        " :code, 8.000, :effective_time)"
                    ),
                    {
                        "id": uuid.uuid4(), "tenant_id": scenario["tenant_id"], "farm_id": scenario["farm_id"],
                        "event_id": event_id, "crop_id": scenario["crop_id"], "variety_id": scenario["variety_id"],
                        "grade_version_id": draft_version.id, "code": f"GPL-BAD-{uuid.uuid4().hex[:8]}",
                        "effective_time": now(),
                    },
                )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_direct_sql_reconciliation_mismatch_rejected(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        # Fully valid same-row shape (remainder < presented, non-negative
        # buckets) but the cross-table 5-way equation is deliberately
        # wrong: 0 (no outputs) + 0 + 0 + 0 + 2 (remainder) != 10 (presented).
        with pytest.raises(DBAPIError):
            with session.begin_nested():
                _insert_raw_grading_event(session, scenario)
                session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_direct_sql_source_consumption_mismatch_rejected(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        event_id = _insert_raw_grading_event(
            session, scenario, input_presented_weight_kg=Decimal("10.000"), remainder_weight_kg=Decimal("2.000")
        )
        # Correct debit would be -8.000 (10 - 2); attempt -5.000 instead.
        with pytest.raises(DBAPIError):
            with session.begin_nested():
                session.execute(
                    text(
                        "INSERT INTO produce_lot_ledger_entries "
                        "(id, tenant_id, farm_id, produce_lot_id, grading_event_id, entry_kind, weight_delta_kg, "
                        " effective_time, recorded_time, actor_user_id) "
                        "VALUES (:id, :tenant_id, :farm_id, :produce_lot_id, :event_id, 'grading_consumption', "
                        " -5.000, :now, :now, :actor_id)"
                    ),
                    {
                        "id": event_id, "tenant_id": scenario["tenant_id"], "farm_id": scenario["farm_id"],
                        "produce_lot_id": scenario["lot_a_id"], "event_id": event_id, "now": now(),
                        "actor_id": scenario["user_id"],
                    },
                )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_direct_sql_graded_receipt_mismatch_rejected(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        event = _grade(
            scenario, db=session, input_presented="8.000", remainder="0",
            outputs=[_output(scenario, weight="8.000")],
        )
        detail = grading_service.get_grading_event(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], grading_event_id=event.id
        )
        graded_lot_id = detail.outputs[0].id
        # A second, forged receipt for the SAME lot with a WRONG amount --
        # blocked by both the deterministic-id-per-lot partial unique index
        # (a second row for the same lot violates it directly) and, were
        # that somehow bypassed, the amount-match check itself.
        with pytest.raises(DBAPIError):
            with session.begin_nested():
                session.execute(
                    text(
                        "INSERT INTO graded_produce_lot_ledger_entries "
                        "(id, tenant_id, farm_id, graded_produce_lot_id, grading_event_id, entry_kind, "
                        " weight_delta_kg, effective_time, recorded_time, actor_user_id) "
                        "VALUES (:id, :tenant_id, :farm_id, :lot_id, :event_id, 'grading_receipt', 99.000, "
                        " :now, :now, :actor_id)"
                    ),
                    {
                        "id": uuid.uuid4(), "tenant_id": scenario["tenant_id"], "farm_id": scenario["farm_id"],
                        "lot_id": graded_lot_id, "event_id": event.id, "now": now(),
                        "actor_id": scenario["user_id"],
                    },
                )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_direct_sql_mutation_rejected(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        event = _grade(
            scenario, db=session, input_presented="8.000", remainder="0",
            outputs=[_output(scenario, weight="8.000")],
        )
        with pytest.raises(DBAPIError):
            with session.begin_nested():
                session.execute(
                    text("UPDATE grading_events SET note = 'changed' WHERE id = :id"), {"id": event.id}
                )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_direct_sql_hard_delete_rejected(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        event = _grade(
            scenario, db=session, input_presented="8.000", remainder="0",
            outputs=[_output(scenario, weight="8.000")],
        )
        with pytest.raises(DBAPIError):
            with session.begin_nested():
                session.execute(text("DELETE FROM grading_events WHERE id = :id"), {"id": event.id})

        detail = grading_service.get_grading_event(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], grading_event_id=event.id
        )
        graded_lot_id = detail.outputs[0].id
        with pytest.raises(DBAPIError):
            with session.begin_nested():
                session.execute(text("DELETE FROM graded_produce_lots WHERE id = :id"), {"id": graded_lot_id})
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


# --- PRE-COMMIT CORRECTION: presented-vs-available integrity (items A-D) ------------


@pytest.mark.integration
def test_direct_sql_presented_exceeds_available_weight_rejected(test_engine) -> None:
    """Item A: available=50, presented=60, remainder=20 (processed=40) --
    the -40kg debit alone would leave the ledger non-negative, but
    presenting 60kg from a 50kg lot is physically impossible and must be
    rejected independently of the ledger-balance arithmetic."""
    scenario = build_committed_scenario(test_engine, lot_a_weight="50.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        with pytest.raises(DBAPIError):
            with session.begin_nested():
                _insert_raw_grading_event(
                    session, scenario, input_presented_weight_kg=Decimal("60.000"),
                    remainder_weight_kg=Decimal("20.000"),
                )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_presented_equals_available_weight_structurally_valid(test_engine) -> None:
    """Item B: available=50, presented=50, remainder=10 (processed=40) --
    presented exactly equals available, which must be accepted once all
    other reconciliation gates pass (proven via the real service, which
    exercises the full 5-way reconciliation + ledger debit end to end)."""
    scenario = build_committed_scenario(test_engine, lot_a_weight="50.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        event = _grade(
            scenario, db=session, input_presented="50.000", remainder="10.000",
            outputs=[_output(scenario, weight="40.000")],
        )
        assert event.id is not None
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_direct_sql_presented_exceeds_available_count_rejected(test_engine) -> None:
    """Item C: available weight=50/count=40. presented weight=30 (well
    within the weight bound) but presented count=50 exceeds the available
    count of 40, even though remainder count=10 would make the PROCESSED
    count (40) exactly equal to what's available. Presented count, not
    processed count, must be compared -- this must still be rejected."""
    scenario = build_committed_scenario(test_engine, lot_a_weight="50.000", lot_a_count=40)
    session, conn = _session(test_engine)
    try:
        with pytest.raises(DBAPIError):
            with session.begin_nested():
                _insert_raw_grading_event(
                    session, scenario, input_presented_weight_kg=Decimal("30.000"),
                    remainder_weight_kg=Decimal("5.000"), input_presented_whole_unit_count=50,
                    rejected_whole_unit_count=0, loss_whole_unit_count=0, sample_whole_unit_count=0,
                    remainder_whole_unit_count=10,
                )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_normal_valid_partial_grading_with_remainder_still_succeeds(test_engine) -> None:
    """Item D: a normal valid partial grading (presented well under
    available, with a remainder) must continue to succeed after the
    presented-vs-available widening -- regression guard alongside
    test_grading.py's own equivalent coverage."""
    scenario = build_committed_scenario(test_engine, lot_a_weight="50.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        event = _grade(
            scenario, db=session, input_presented="30.000", remainder="5.000",
            outputs=[_output(scenario, weight="25.000")],
        )
        assert event.id is not None
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


# --- PRE-COMMIT CORRECTION: Quality Hold / Recall DB containment (items E-H) --------


@pytest.mark.integration
def test_direct_sql_open_quality_hold_rejected(test_engine) -> None:
    """Item E: an open Quality Hold on the source batch must block a
    forged, direct-SQL grading_events insert -- not merely a service call."""
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        quality_hold_service.place_quality_hold(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(), effective_time=now(),
            source_observation_event_id=None, reason_code="QUALITY", reason_text="DB integrity test hold",
        )
        session.commit()
        with pytest.raises(DBAPIError):
            with session.begin_nested():
                _insert_raw_grading_event(session, scenario)
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_direct_sql_open_batch_recall_rejected(test_engine) -> None:
    """Item F: an open Batch Recall must block a forged, direct-SQL
    grading_events insert."""
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        recall_service.open_recall_case(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), effective_time=now(), code=f"RECALL-DB-{scenario['suffix']}",
            crop_batch_id=scenario["batch_id"], harvested_produce_lot_id=None, finished_goods_lot_id=None,
            reason_code="CONTAMINATION", reason_text="DB integrity test recall",
        )
        session.commit()
        with pytest.raises(DBAPIError):
            with session.begin_nested():
                _insert_raw_grading_event(session, scenario)
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_direct_sql_open_produce_lot_recall_rejected(test_engine) -> None:
    """Item G: an open HarvestedProduceLot Recall must block a forged,
    direct-SQL grading_events insert."""
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        recall_service.open_recall_case(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), effective_time=now(), code=f"RECALL-DB-{scenario['suffix']}",
            crop_batch_id=None, harvested_produce_lot_id=scenario["lot_a_id"], finished_goods_lot_id=None,
            reason_code="CONTAMINATION", reason_text="DB integrity test recall",
        )
        session.commit()
        with pytest.raises(DBAPIError):
            with session.begin_nested():
                _insert_raw_grading_event(session, scenario)
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_direct_sql_closed_hold_permits_grading(test_engine) -> None:
    """Item H: a hold that was placed and then released must NOT block a
    direct-SQL grading_events insert -- the containment check is exactly
    "currently open", never "ever existed"."""
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        hold = quality_hold_service.place_quality_hold(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(), effective_time=now(),
            source_observation_event_id=None, reason_code="QUALITY", reason_text="DB integrity test hold",
        )
        quality_hold_service.release_quality_hold(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            batch_id=scenario["batch_id"], hold_id=hold.id, client_command_id=uuid.uuid4(), effective_time=now(),
            release_reason="Resolved",
        )
        session.commit()
        with session.begin_nested():
            event_id = _insert_raw_grading_event(session, scenario)
        assert event_id is not None
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


# --- PRE-COMMIT CORRECTION: GradedProduceLot code uniqueness (item K) ---------------


@pytest.mark.integration
def test_direct_sql_duplicate_graded_lot_code_rejected(test_engine) -> None:
    """Item K: a second GradedProduceLot row, for a DIFFERENT grading
    event (and a different grade_definition_version_id, so the
    (grading_event_id, grade_definition_version_id) unique constraint
    never enters into it), using the SAME code in a different case, must
    be rejected by ux_graded_produce_lots_tenant_code_lower alone."""
    from datetime import timedelta

    from app.services import grade_definition_service

    scenario = build_committed_scenario(test_engine, lot_a_weight="20.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        first_event = _grade(
            scenario, db=session, input_presented="10.000", remainder="0",
            outputs=[_output(scenario, weight="10.000", code="GPL-DUP-K")],
        )
        second_def = grade_definition_service.register_grade_definition(
            session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), code=f"second-{scenario['suffix']}", name="Second",
            crop_id=scenario["crop_id"], variety_id=None, description=None,
        )
        second_version = grade_definition_service.create_draft_version(
            session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), grade_definition_id=second_def.id, spec_notes=None,
        )
        grade_definition_service.activate_version(
            session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), grade_definition_id=second_def.id, version_id=second_version.id,
            effective_time=now() - timedelta(days=1),
        )
        second_event = _grade(
            scenario, db=session, input_presented="10.000", remainder="0",
            outputs=[_output(scenario, weight="10.000", code="GPL-OTHER", grade_version_id=second_version.id)],
        )
        with pytest.raises(DBAPIError):
            with session.begin_nested():
                session.execute(
                    text(
                        "INSERT INTO graded_produce_lots "
                        "(id, tenant_id, farm_id, grading_event_id, crop_id, variety_id, "
                        " grade_definition_version_id, code, original_received_weight_kg, effective_time) "
                        "VALUES (:id, :tenant_id, :farm_id, :event_id, :crop_id, :variety_id, :grade_version_id, "
                        " 'gpl-dup-k', 1.000, :effective_time)"
                    ),
                    {
                        "id": uuid.uuid4(), "tenant_id": scenario["tenant_id"], "farm_id": scenario["farm_id"],
                        "event_id": second_event.id, "crop_id": scenario["crop_id"],
                        "variety_id": scenario["variety_id"], "grade_version_id": second_version.id,
                        "effective_time": second_event.effective_time,
                    },
                )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])
