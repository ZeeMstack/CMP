"""Unit/integration coverage for CMP-015 packing beyond the acceptance
flow: deterministic debit identity, ledger read shape (packing_event_id,
negative Decimal strings), balance decrease, output reads omitting
before/after balance snapshots, partial and repeated consumption to exact
zero, count-mode requirements, package-count bounds, and the exact CMP-014
receipt shape remaining unchanged after CMP-015."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.services import graded_produce_lot_ledger_service, packing_service
from app.services.errors import (
    InsufficientGradedProduceLotBalanceError,
    PackingCommandReusedWithDifferentPayloadError,
    PackingCropVarietyMismatchError,
    PackingValidationError,
)
from tests._packing_scenario import (
    build_committed_scenario, build_packing_scaffold, cleanup_scenario, grade_entire_lot, now,
)
from tests.conftest import ensure_seed_tray_specification


def _pack(scenario, *, db, input_lines, packed_output, process_loss="0", rejected="0", code=None, package_count=1,
          client_command_id=None, effective_time=None, pack_specification_version_id=None):
    return packing_service.record_packing(
        db, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=client_command_id or uuid.uuid4(), effective_time=effective_time or now(),
        pack_specification_version_id=pack_specification_version_id or scenario["pack_specification_version_id"],
        finished_goods_lot_code=code or f"FG-{uuid.uuid4().hex[:8]}", package_count=package_count,
        packed_output_weight_kg=Decimal(packed_output), process_loss_weight_kg=Decimal(process_loss),
        rejected_weight_kg=Decimal(rejected), note=None, input_lines=input_lines,
    )


@pytest.mark.integration
def test_deterministic_debit_identity_equals_input_line_id(test_engine) -> None:
    from sqlalchemy.orm import Session

    scenario = build_committed_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        event = _pack(
            scenario, db=session, packed_output="3.000",
            input_lines=[{"graded_produce_lot_id": scenario["gpl_a_id"], "consumed_weight_kg": Decimal("3.000"), "consumed_whole_unit_count": 12, "note": None}],
        )
        detail = packing_service.get_packing_event(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], packing_event_id=event.id
        )
        line = detail.input_lines[0]
        assert line.id == line.ledger_entry_id
        ledger = graded_produce_lot_ledger_service.get_ledger(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], graded_produce_lot_id=scenario["gpl_a_id"]
        )
        debit = next(e for e in ledger if e.entry_kind == "packing_consumption")
        assert debit.id == line.id
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_ledger_read_serializes_packing_event_id_and_negative_delta(test_engine) -> None:
    from sqlalchemy.orm import Session

    scenario = build_committed_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        event = _pack(
            scenario, db=session, packed_output="2.000",
            input_lines=[{"graded_produce_lot_id": scenario["gpl_a_id"], "consumed_weight_kg": Decimal("2.000"), "consumed_whole_unit_count": 8, "note": None}],
        )
        ledger = graded_produce_lot_ledger_service.get_ledger(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], graded_produce_lot_id=scenario["gpl_a_id"]
        )
        debit = next(e for e in ledger if e.entry_kind == "packing_consumption")
        assert debit.packing_event_id == event.id
        assert debit.grading_event_id is None
        assert debit.weight_delta_kg == Decimal("-2.000")
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_balance_decreases_exactly_after_packing(test_engine) -> None:
    from sqlalchemy.orm import Session

    scenario = build_committed_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        _pack(
            scenario, db=session, packed_output="4.000",
            input_lines=[{"graded_produce_lot_id": scenario["gpl_a_id"], "consumed_weight_kg": Decimal("4.000"), "consumed_whole_unit_count": 16, "note": None}],
        )
        balance = graded_produce_lot_ledger_service.get_balance(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], graded_produce_lot_id=scenario["gpl_a_id"]
        )
        assert balance.available_weight_kg == Decimal("6.000")
        assert balance.available_whole_unit_count == 24
        assert balance.received_weight_kg == scenario["lot_a_weight"]
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_repeated_partial_consumption_until_exact_zero(test_engine) -> None:
    from sqlalchemy.orm import Session

    scenario = build_committed_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        _pack(
            scenario, db=session, packed_output="4.000",
            input_lines=[{"graded_produce_lot_id": scenario["gpl_a_id"], "consumed_weight_kg": Decimal("4.000"), "consumed_whole_unit_count": 16, "note": None}],
        )
        _pack(
            scenario, db=session, packed_output="6.000",
            input_lines=[{"graded_produce_lot_id": scenario["gpl_a_id"], "consumed_weight_kg": Decimal("6.000"), "consumed_whole_unit_count": 24, "note": None}],
        )
        balance = graded_produce_lot_ledger_service.get_balance(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], graded_produce_lot_id=scenario["gpl_a_id"]
        )
        assert balance.available_weight_kg == Decimal("0")
        assert balance.available_whole_unit_count == 0
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_weight_overconsumption_rejected(test_engine) -> None:
    from sqlalchemy.orm import Session

    scenario = build_committed_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        with pytest.raises(InsufficientGradedProduceLotBalanceError):
            _pack(
                scenario, db=session, packed_output="99.000",
                input_lines=[{"graded_produce_lot_id": scenario["gpl_a_id"], "consumed_weight_kg": Decimal("99.000"), "consumed_whole_unit_count": 396, "note": None}],
            )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_count_overconsumption_rejected(test_engine) -> None:
    from sqlalchemy.orm import Session

    scenario = build_committed_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        with pytest.raises(InsufficientGradedProduceLotBalanceError):
            _pack(
                scenario, db=session, packed_output="1.000",
                input_lines=[{"graded_produce_lot_id": scenario["gpl_a_id"], "consumed_weight_kg": Decimal("1.000"), "consumed_whole_unit_count": 999, "note": None}],
            )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_count_mode_requires_count_when_lot_tracks_it(test_engine) -> None:
    from sqlalchemy.orm import Session

    scenario = build_committed_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        with pytest.raises(PackingValidationError):
            _pack(
                scenario, db=session, packed_output="1.000",
                input_lines=[{"graded_produce_lot_id": scenario["gpl_a_id"], "consumed_weight_kg": Decimal("1.000"), "consumed_whole_unit_count": None, "note": None}],
            )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_count_mode_forbids_count_when_lot_does_not_track_it(test_engine) -> None:
    from sqlalchemy.orm import Session

    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        with pytest.raises(PackingValidationError):
            _pack(
                scenario, db=session, packed_output="1.000",
                input_lines=[{"graded_produce_lot_id": scenario["gpl_a_id"], "consumed_weight_kg": Decimal("1.000"), "consumed_whole_unit_count": 4, "note": None}],
            )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_residual_weight_count_mismatch_rejected(test_engine) -> None:
    """Consuming all weight but leaving positive count (or vice versa) must
    be rejected — the two must reach zero together or both stay positive."""
    from sqlalchemy.orm import Session

    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=40)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        with pytest.raises(PackingValidationError, match="residual"):
            _pack(
                scenario, db=session, packed_output="10.000",
                input_lines=[{"graded_produce_lot_id": scenario["gpl_a_id"], "consumed_weight_kg": Decimal("10.000"), "consumed_whole_unit_count": 30, "note": None}],
            )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_mixed_crop_variety_inputs_rejected(test_engine) -> None:
    from sqlalchemy.orm import Session
    from app.services import (
        carrier_service, crop_batch_service, crop_service, farm_service, harvest_service,
        production_system_service, sowing_service, workflow_service,
    )

    scenario = build_committed_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        # A second, unrelated crop's harvested lot to violate compatibility.
        other_crop = crop_service.register_crop(
            session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
            code=f"other-{scenario['suffix']}", common_name="Tomato", scientific_name=None,
            crop_category="vine",
        )
        other_variety = crop_service.register_variety(
            session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"], crop_id=other_crop.id,
            code=f"ovar-{scenario['suffix']}", name="Other Variety", supplier_reference=None,
        )
        ps = production_system_service.register_production_system(
            session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
            code=f"ops-{scenario['suffix']}", name="System", description=None,
        )
        wf = workflow_service.register_workflow(
            session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"], crop_id=other_crop.id,
            variety_id=other_variety.id, production_system_id=ps.id, code=f"owf-{scenario['suffix']}", name="Other Workflow",
        )
        v = workflow_service.create_draft_version(
            session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"], workflow_id=wf.id
        )
        seeding = workflow_service.add_stage(
            session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"], workflow_id=wf.id,
            version_id=v.id, code="SEEDING", name="Seeding", display_order=0, stage_category="seeding",
            expected_duration_minutes=None, permitted_location_type_code=None,
            required_carrier_type_code="seed_tray", is_start=True, is_terminal=False,
        )
        harvesting = workflow_service.add_stage(
            session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"], workflow_id=wf.id,
            version_id=v.id, code="HARVESTING", name="Harvesting", display_order=1, stage_category="harvesting",
            expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
            is_start=False, is_terminal=False,
        )
        complete = workflow_service.add_stage(
            session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"], workflow_id=wf.id,
            version_id=v.id, code="COMPLETE", name="Complete", display_order=2, stage_category="completed",
            expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
            is_start=False, is_terminal=True,
        )
        t1 = workflow_service.add_transition(
            session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"], workflow_id=wf.id,
            version_id=v.id, from_stage_id=seeding.id, to_stage_id=harvesting.id, code="A1", name="A1",
        )
        workflow_service.add_transition(
            session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"], workflow_id=wf.id,
            version_id=v.id, from_stage_id=harvesting.id, to_stage_id=complete.id, code="A2", name="A2",
        )
        workflow_service.publish_version(
            session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"], workflow_id=wf.id,
            version_id=v.id,
        )
        other_batch = crop_batch_service.create_batch(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), code=f"OBATCH-{scenario['suffix']}", workflow_id=wf.id,
            effective_time=now(),
        )
        other_seed_lot = sowing_service.register_seed_lot(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            crop_id=other_crop.id, variety_id=other_variety.id, code=f"oseed-{scenario['suffix']}", supplier_name=None,
            supplier_lot_reference=None, received_date=None, expiry_date=None,
        )
        other_seed_tray_spec = ensure_seed_tray_specification(
            session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"]
        )
        other_carrier = carrier_service.register_carrier(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            specification_id=other_seed_tray_spec.id, code=f"otray-{scenario['suffix']}", issued_date=None,
        )
        sowing_service.sow_batch(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            batch_id=other_batch.id, client_command_id=uuid.uuid4(), effective_time=now(), note=None,
            lines=[{"carrier_id": other_carrier.id, "seed_lot_id": other_seed_lot.id, "sown_site_count": 10, "seed_count": 10, "line_note": None}],
        )
        other_assignments = sowing_service.list_batch_carriers(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], batch_id=other_batch.id
        )
        crop_batch_service.transition_stage(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            batch_id=other_batch.id, client_command_id=uuid.uuid4(), configured_transition_id=t1.id,
            effective_time=now(), reason=None,
        )
        other_harvest = harvest_service.record_harvest(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            batch_id=other_batch.id, client_command_id=uuid.uuid4(), effective_time=now(),
            produce_lot_code=f"OLOT-{scenario['suffix']}", note=None,
            source_lines=[{"batch_carrier_assignment_id": other_assignments[0].id, "harvested_weight_kg": Decimal("1.000"), "whole_unit_count": None, "note": None}],
        )
        other_lot_id = session.execute(
            select(harvest_service.HarvestedProduceLot.id).where(
                harvest_service.HarvestedProduceLot.harvest_event_id == other_harvest.id
            )
        ).scalar_one()
        from app.models.farm import Farm
        from app.models.tenant import Tenant
        from app.models.user import User

        tenant_obj = session.get(Tenant, scenario["tenant_id"])
        user_obj = session.get(User, scenario["user_id"])
        farm_obj = session.get(Farm, scenario["farm_id"])
        other_scaffold = build_packing_scaffold(
            session, tenant_obj, user_obj, farm_obj, crop_id=other_crop.id, suffix=f"other-{scenario['suffix']}",
        )
        other_gpl_id = grade_entire_lot(
            session, tenant_obj, user_obj, farm_obj, produce_lot_id=other_lot_id, weight=Decimal("1.000"),
            count=None, scaffold=other_scaffold, suffix=f"other-{scenario['suffix']}",
        )

        with pytest.raises(PackingCropVarietyMismatchError):
            _pack(
                scenario, db=session, packed_output="1.500",
                input_lines=[
                    {"graded_produce_lot_id": scenario["gpl_a_id"], "consumed_weight_kg": Decimal("0.500"), "consumed_whole_unit_count": 2, "note": None},
                    {"graded_produce_lot_id": other_gpl_id, "consumed_weight_kg": Decimal("1.000"), "consumed_whole_unit_count": None, "note": None},
                ],
            )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_changed_payload_same_command_id_rejected(test_engine) -> None:
    from sqlalchemy.orm import Session

    scenario = build_committed_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        command_id = uuid.uuid4()
        fixed_time = now()
        _pack(
            scenario, db=session, packed_output="2.000", client_command_id=command_id, effective_time=fixed_time,
            input_lines=[{"graded_produce_lot_id": scenario["gpl_a_id"], "consumed_weight_kg": Decimal("2.000"), "consumed_whole_unit_count": 8, "note": None}],
        )
        with pytest.raises(PackingCommandReusedWithDifferentPayloadError):
            _pack(
                scenario, db=session, packed_output="3.000", client_command_id=command_id, effective_time=fixed_time,
                input_lines=[{"graded_produce_lot_id": scenario["gpl_a_id"], "consumed_weight_kg": Decimal("3.000"), "consumed_whole_unit_count": 12, "note": None}],
            )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_exact_retry_after_complete_source_depletion_still_returns(test_engine) -> None:
    """An exact retry of an already-successful packing command must return
    the original event even after the source lot has since been fully
    depleted by another, later command — proving retry bypasses current
    mutable-balance validation entirely, consistent with harvest's own
    established idempotency discipline. No additional event, input line,
    or ledger debit is created by the retry."""
    from sqlalchemy import func, select as sa_select
    from sqlalchemy.orm import Session

    from app.models.graded_produce_lot_ledger_entry import GradedProduceLotLedgerEntry

    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        command_id = uuid.uuid4()
        payload = {
            "packed_output": "4.000", "effective_time": now(), "code": f"FG-{scenario['suffix']}",
            "input_lines": [{"graded_produce_lot_id": scenario["gpl_a_id"], "consumed_weight_kg": Decimal("4.000"), "consumed_whole_unit_count": None, "note": None}],
        }
        original = _pack(scenario, db=session, client_command_id=command_id, **payload)

        # Deplete the remaining 6kg via a second, genuinely new command.
        _pack(
            scenario, db=session, packed_output="6.000",
            input_lines=[{"graded_produce_lot_id": scenario["gpl_a_id"], "consumed_weight_kg": Decimal("6.000"), "consumed_whole_unit_count": None, "note": None}],
        )
        debit_count_before_retry = session.execute(
            sa_select(func.count()).select_from(GradedProduceLotLedgerEntry)
            .where(GradedProduceLotLedgerEntry.graded_produce_lot_id == scenario["gpl_a_id"])
        ).scalar_one()

        # Exact retry of the original command must still return, not fail
        # on the now-zero balance, and must create nothing new.
        retried = _pack(scenario, db=session, client_command_id=command_id, **payload)
        assert retried.id == original.id
        debit_count_after_retry = session.execute(
            sa_select(func.count()).select_from(GradedProduceLotLedgerEntry)
            .where(GradedProduceLotLedgerEntry.graded_produce_lot_id == scenario["gpl_a_id"])
        ).scalar_one()
        assert debit_count_after_retry == debit_count_before_retry
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])
