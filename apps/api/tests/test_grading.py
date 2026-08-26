"""POSTHARVEST-OPS-001C: basic grading, mandatory Processing Hall,
weight reconciliation, and remainder/partial-processing coverage."""
import uuid
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.services import grading_service, produce_lot_ledger_service
from app.services.errors import (
    GradingSourceProduceLotNotFoundError,
    GradingValidationError,
    InsufficientHarvestedProduceLotBalanceError,
    ProcessingHallLocationInvalidError,
)
from tests._grading_scenario import build_committed_scenario, cleanup_scenario, now


def _grade(scenario, *, db, input_presented="10.000", rejected="0", loss="0", sample="0", remainder="0",
           outputs=None, hall_id=None, source_lot_id=None, effective_time=None, client_command_id=None,
           input_count=None, rejected_count=None, loss_count=None, sample_count=None, remainder_count=None):
    return grading_service.record_grading(
        db, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=client_command_id or uuid.uuid4(),
        source_harvested_produce_lot_id=source_lot_id or scenario["lot_a_id"],
        processing_hall_location_id=hall_id or scenario["packing_hall_location_id"],
        effective_time=effective_time or now(), note=None,
        input_presented_weight_kg=Decimal(input_presented), input_presented_whole_unit_count=input_count,
        rejected_weight_kg=Decimal(rejected), rejected_whole_unit_count=rejected_count,
        loss_weight_kg=Decimal(loss), loss_whole_unit_count=loss_count,
        sample_weight_kg=Decimal(sample), sample_whole_unit_count=sample_count,
        remainder_weight_kg=Decimal(remainder), remainder_whole_unit_count=remainder_count,
        outputs=outputs or [],
    )


def _output(scenario, *, weight, code=None, grade_version_id=None, count=None):
    return {
        "grade_definition_version_id": grade_version_id or scenario["grade_definition_version_id"],
        "code": code or f"GPL-{uuid.uuid4().hex[:8]}", "output_weight_kg": Decimal(weight),
        "output_whole_unit_count": count,
    }


def _session(test_engine):
    conn = test_engine.connect()
    return Session(bind=conn), conn


# --- Basic grading (1-10) -----------------------------------------------------------


@pytest.mark.integration
def test_grade_valid_harvested_produce_lot(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        event = _grade(
            scenario, db=session, input_presented="10.000", remainder="2.000",
            outputs=[_output(scenario, weight="8.000")],
        )
        assert event.id is not None
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_non_packing_hall_location_rejected(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        with pytest.raises(ProcessingHallLocationInvalidError):
            _grade(
                scenario, db=session, input_presented="10.000", remainder="2.000",
                outputs=[_output(scenario, weight="8.000")], hall_id=scenario["other_location_id"],
            )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_inactive_hall_rejected(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        with pytest.raises(ProcessingHallLocationInvalidError):
            _grade(
                scenario, db=session, input_presented="10.000", remainder="2.000",
                outputs=[_output(scenario, weight="8.000")], hall_id=scenario["inactive_hall_location_id"],
            )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_cross_farm_hall_rejected(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        from app.services import farm_service, location_service

        other_farm = farm_service.create_farm(
            session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
            code=f"farm2-{scenario['suffix']}", name="Other Farm", country_code="AE", city_region=None,
            timezone="Asia/Dubai",
        )
        other_hall = location_service.create_location(
            session, tenant_id=scenario["tenant_id"], farm_id=other_farm.id, actor_user_id=scenario["user_id"],
            location_type_code="packing_hall", code=f"hall2-{scenario['suffix']}", name="Other Farm Hall",
            parent_location_id=None, greenhouse_classification=None, occupiable=False,
        )
        session.commit()
        with pytest.raises(ProcessingHallLocationInvalidError):
            _grade(
                scenario, db=session, input_presented="10.000", remainder="2.000",
                outputs=[_output(scenario, weight="8.000")], hall_id=other_hall.id,
            )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_cross_tenant_hall_rejected(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    other_scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        with pytest.raises(ProcessingHallLocationInvalidError):
            _grade(
                scenario, db=session, input_presented="10.000", remainder="2.000",
                outputs=[_output(scenario, weight="8.000")],
                hall_id=other_scenario["packing_hall_location_id"],
            )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])
        cleanup_scenario(test_engine, other_scenario["tenant_id"])


@pytest.mark.integration
def test_cross_farm_source_lot_rejected(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        from app.services import farm_service

        other_farm = farm_service.create_farm(
            session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
            code=f"farm3-{scenario['suffix']}", name="Other Farm 2", country_code="AE", city_region=None,
            timezone="Asia/Dubai",
        )
        session.commit()
        with pytest.raises(GradingSourceProduceLotNotFoundError):
            grading_service.record_grading(
                session, tenant_id=scenario["tenant_id"], farm_id=other_farm.id,
                actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(),
                source_harvested_produce_lot_id=scenario["lot_a_id"],
                processing_hall_location_id=scenario["packing_hall_location_id"], effective_time=now(),
                note=None, input_presented_weight_kg=Decimal("10.000"), input_presented_whole_unit_count=None,
                rejected_weight_kg=Decimal("0"), rejected_whole_unit_count=None,
                loss_weight_kg=Decimal("0"), loss_whole_unit_count=None,
                sample_weight_kg=Decimal("0"), sample_whole_unit_count=None,
                remainder_weight_kg=Decimal("2.000"), remainder_whole_unit_count=None,
                outputs=[_output(scenario, weight="8.000")],
            )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_cross_tenant_source_lot_rejected(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    other_scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        with pytest.raises(GradingSourceProduceLotNotFoundError):
            _grade(
                scenario, db=session, input_presented="10.000", remainder="2.000",
                outputs=[_output(scenario, weight="8.000")], source_lot_id=other_scenario["lot_a_id"],
            )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])
        cleanup_scenario(test_engine, other_scenario["tenant_id"])


@pytest.mark.integration
def test_multiple_grading_events_against_one_source_lot(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        _grade(
            scenario, db=session, input_presented="4.000", remainder="0",
            outputs=[_output(scenario, weight="4.000")],
        )
        _grade(
            scenario, db=session, input_presented="6.000", remainder="0",
            outputs=[_output(scenario, weight="6.000")],
        )
        events = grading_service.list_grading_events(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
            source_harvested_produce_lot_id=scenario["lot_a_id"],
        )
        assert len(events) == 2
        balance = produce_lot_ledger_service.get_balance(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
            produce_lot_id=scenario["lot_a_id"],
        )
        assert balance.available_weight_kg == Decimal("0.000") or balance.available_weight_kg == Decimal("0")
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


# --- Reconciliation (11-19) ----------------------------------------------------------


@pytest.mark.integration
def test_exact_worked_example_reconciliation(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="100.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        from app.services import grade_definition_service

        grade_b_def = grade_definition_service.register_grade_definition(
            session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), code=f"gradeb-{scenario['suffix']}", name="Standard",
            crop_id=scenario["crop_id"], variety_id=None, description=None,
        )
        grade_b_version = grade_definition_service.create_draft_version(
            session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), grade_definition_id=grade_b_def.id, spec_notes=None,
        )
        from datetime import timedelta

        grade_definition_service.activate_version(
            session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), grade_definition_id=grade_b_def.id, version_id=grade_b_version.id,
            effective_time=now() - timedelta(days=10),
        )

        event = _grade(
            scenario, db=session, input_presented="100.000", rejected="5.000", loss="3.000", sample="2.000",
            remainder="10.000",
            outputs=[
                _output(scenario, weight="65.000", code="PREMIUM"),
                _output(scenario, weight="15.000", code="STANDARD", grade_version_id=grade_b_version.id),
            ],
        )
        detail = grading_service.get_grading_event(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], grading_event_id=event.id
        )
        assert detail.processed_weight_kg == Decimal("90.000")

        ledger = produce_lot_ledger_service.get_ledger(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
            produce_lot_id=scenario["lot_a_id"],
        )
        debit = next(e for e in ledger if e.entry_kind == "grading_consumption")
        assert debit.weight_delta_kg == Decimal("-90.000")

        balance = produce_lot_ledger_service.get_balance(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
            produce_lot_id=scenario["lot_a_id"],
        )
        assert balance.available_weight_kg == Decimal("10.000")
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_all_processed_remainder_zero(test_engine) -> None:
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
        assert detail.processed_weight_kg == Decimal("10.000")
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_zero_saleable_output_all_reject_loss_sample_valid(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        event = _grade(
            scenario, db=session, input_presented="10.000", rejected="5.000", loss="3.000", sample="2.000",
            remainder="0", outputs=[],
        )
        detail = grading_service.get_grading_event(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], grading_event_id=event.id
        )
        assert detail.outputs == []
        assert detail.processed_weight_kg == Decimal("10.000")
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_input_equals_remainder_rejected(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        with pytest.raises(GradingValidationError):
            _grade(scenario, db=session, input_presented="10.000", remainder="10.000", outputs=[])
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_weight_under_reconciliation_rejected(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        # 8 (output) + 1 (remainder) = 9, short of the 10 presented.
        with pytest.raises(GradingValidationError):
            _grade(
                scenario, db=session, input_presented="10.000", remainder="1.000",
                outputs=[_output(scenario, weight="8.000")],
            )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_weight_over_reconciliation_rejected(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        # 9 (output) + 2 (remainder) = 11, over the 10 presented.
        with pytest.raises(GradingValidationError):
            _grade(
                scenario, db=session, input_presented="10.000", remainder="2.000",
                outputs=[_output(scenario, weight="9.000")],
            )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_negative_bucket_rejected(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        with pytest.raises(Exception):
            _grade(
                scenario, db=session, input_presented="10.000", rejected="-1.000", remainder="2.000",
                outputs=[_output(scenario, weight="9.000")],
            )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_output_weight_non_positive_rejected(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        with pytest.raises(Exception):
            _grade(
                scenario, db=session, input_presented="10.000", remainder="2.000",
                outputs=[_output(scenario, weight="0")],
            )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_duplicate_exact_grade_version_outputs_rejected(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        with pytest.raises(Exception):
            _grade(
                scenario, db=session, input_presented="10.000", remainder="0",
                outputs=[_output(scenario, weight="6.000"), _output(scenario, weight="4.000")],
            )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


# --- Remainder / partial processing (20-24) ------------------------------------------


@pytest.mark.integration
def test_first_event_leaves_remainder(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        _grade(
            scenario, db=session, input_presented="10.000", remainder="4.000",
            outputs=[_output(scenario, weight="6.000")],
        )
        balance = produce_lot_ledger_service.get_balance(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
            produce_lot_id=scenario["lot_a_id"],
        )
        assert balance.available_weight_kg == Decimal("4.000")
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_second_event_consumes_remainder(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        _grade(
            scenario, db=session, input_presented="10.000", remainder="4.000",
            outputs=[_output(scenario, weight="6.000")],
        )
        _grade(
            scenario, db=session, input_presented="4.000", remainder="0",
            outputs=[_output(scenario, weight="4.000", code="SECOND")],
        )
        balance = produce_lot_ledger_service.get_balance(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
            produce_lot_id=scenario["lot_a_id"],
        )
        assert balance.available_weight_kg == Decimal("0.000") or balance.available_weight_kg == Decimal("0")
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_source_presented_cannot_exceed_available_balance(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="50.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        with pytest.raises(InsufficientHarvestedProduceLotBalanceError):
            _grade(
                scenario, db=session, input_presented="60.000", remainder="20.000",
                outputs=[_output(scenario, weight="40.000")],
            )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_processed_may_be_less_than_presented(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        event = _grade(
            scenario, db=session, input_presented="10.000", remainder="3.000",
            outputs=[_output(scenario, weight="7.000")],
        )
        detail = grading_service.get_grading_event(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], grading_event_id=event.id
        )
        assert detail.processed_weight_kg == Decimal("7.000")
        assert detail.processed_weight_kg < detail.input_presented_weight_kg
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])
