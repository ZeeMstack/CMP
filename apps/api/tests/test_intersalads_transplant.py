"""NURSERY-OPS-004B.1: InterSalads Transplant + atomic physical placement.

Domain/service, API, atomicity, capacity, authorization, and traceability
coverage for the composite command. Concurrency lives in its own file
(`test_intersalads_transplant_concurrency.py`); migration/downgrade-guard
coverage lives in `test_intersalads_transplant_downgrade_guard.py`. Does not
duplicate existing `test_transplant.py`/`test_movement*.py` coverage for
behavior the composite reuses unchanged (source reconciliation math, Movement
occupancy-compatibility/capacity enforcement) -- only what the composite
itself adds or could plausibly regress."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select, text

from app.models.audit_event import AuditEvent
from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.movement import Movement
from app.models.occupancy import Occupancy
from app.models.seedling_source_checkpoint import SeedlingSourceCheckpoint
from app.models.transplant_allocation import TransplantAllocation
from app.models.transplant_destination_line import TransplantDestinationLine
from app.models.transplant_event import TransplantEvent
from app.services import carrier_specification_service, intersalads_transplant_service, tenant_service
from app.services.errors import (
    DestinationCarrierAlreadyAssignedError,
    IncompatibleOccupantTargetError,
    IntersaladsTransplantReplayStateConflictError,
    TargetOccupiedError,
    TransplantCapacityExceededError,
    TransplantCommandReusedWithDifferentPayloadError,
    TransplantValidationError,
)
from tests._transplant_scenario import build_transplant_ready_scenario, now as _now

DESTINATION_TYPE = "nursery_cultivation_plate"


def _register_destination_spec(db_session, tenant, user, *, biological_position_count=200, suffix=None):
    suffix = suffix or uuid.uuid4().hex[:8]
    return carrier_specification_service.register_carrier_specification(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, carrier_type_code=DESTINATION_TYPE,
        code=f"NCP-{suffix}", name="200 Hole Nursery Plate", length_mm=500, width_mm=300, height_mm=60,
        biological_position_count=biological_position_count,
    )


def _build_scenario(db_session, tenant, user, farm, *, biological_position_count=200, tray_count=4, **overrides):
    spec = _register_destination_spec(db_session, tenant, user, biological_position_count=biological_position_count)
    return build_transplant_ready_scenario(
        db_session, tenant, user, farm, tray_count=tray_count, transplanting_required_type=DESTINATION_TYPE,
        destination_specification_id=spec.id, intersalads_table_count=2, intersalads_table_capacity=4, **overrides,
    ), spec


def _simple_source(assignment_id, **overrides):
    defaults = dict(
        source_assignment_id=assignment_id, transplant_damage_count=0, qc_rejection_count=0, sample_count=0,
        other_loss_count=0, other_loss_note=None, note=None,
    )
    defaults.update(overrides)
    return defaults


def _simple_destination(carrier_id, location_id, count=200, **overrides):
    defaults = dict(
        destination_carrier_id=carrier_id, assigned_plant_count=count, destination_location_id=location_id,
        note=None,
    )
    defaults.update(overrides)
    return defaults


def _simple_allocation(source_id, dest_id, count=200):
    return {"source_assignment_id": source_id, "destination_carrier_id": dest_id, "allocated_plant_count": count}


def _record(db_session, tenant, farm, user, batch, source_lines, destination_lines, allocations, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
    )
    defaults.update(overrides)
    return intersalads_transplant_service.record_intersalads_transplant(
        db_session, source_lines=source_lines, destination_lines=destination_lines, allocations=allocations,
        **defaults,
    )


# =====================================================================
# Happy path
# =====================================================================


@pytest.mark.integration
def test_partial_transplant_to_one_plate_with_placement(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, _spec = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    aid = s["source_assignment_ids"][0]
    plate = s["destination_carriers"][0]
    table_id = s["intersalads_table_ids"][0]

    result = _record(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(plate.id, table_id, count=150)],
        [_simple_allocation(aid, plate.id, 150)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )

    assert result.total_destination_plant_count == 150
    assert result.total_remainder_after == 50
    assert len(result.destination_lines) == 1
    dline = result.destination_lines[0]
    assert dline.destination_location_id == table_id
    assert dline.assigned_plant_count == 150

    movement = db_session.get(Movement, dline.movement_id)
    assert movement.occupant_carrier_id == plate.id
    assert movement.destination_location_id == table_id

    active_occupancy = db_session.execute(
        select(Occupancy).where(Occupancy.occupant_carrier_id == plate.id, Occupancy.end_time.is_(None))
    ).scalar_one()
    assert active_occupancy.target_location_id == table_id


@pytest.mark.integration
def test_full_transplant_exhausting_source_with_placement(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, _spec = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    aid = s["source_assignment_ids"][0]
    plate = s["destination_carriers"][0]
    table_id = s["intersalads_table_ids"][0]

    result = _record(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(plate.id, table_id, count=200)],
        [_simple_allocation(aid, plate.id, 200)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    assert result.total_remainder_after == 0
    assignment = db_session.get(BatchCarrierAssignment, aid)
    assert assignment.released_effective_time is not None


@pytest.mark.integration
def test_one_source_to_multiple_plates(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, _spec = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    aid = s["source_assignment_ids"][0]
    plate_a, plate_b = s["destination_carriers"][0], s["destination_carriers"][1]
    table_a, table_b = s["intersalads_table_ids"][0], s["intersalads_table_ids"][1]

    result = _record(
        db_session, tenant, farm, user, s["batch"], [_simple_source(aid)],
        [
            _simple_destination(plate_a.id, table_a, count=120),
            _simple_destination(plate_b.id, table_b, count=80),
        ],
        [_simple_allocation(aid, plate_a.id, 120), _simple_allocation(aid, plate_b.id, 80)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    assert result.total_destination_plant_count == 200
    assert len(result.destination_lines) == 2
    locations = {line.destination_location_id for line in result.destination_lines}
    assert locations == {table_a, table_b}


@pytest.mark.integration
def test_multiple_same_batch_sources_to_one_plate(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, _spec = _build_scenario(db_session, tenant, user, farm, tray_count=2, biological_position_count=400)
    aid_a, aid_b = s["source_assignment_ids"]
    plate = s["destination_carriers"][0]
    table_id = s["intersalads_table_ids"][0]

    result = _record(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid_a), _simple_source(aid_b)],
        [_simple_destination(plate.id, table_id, count=400)],
        [_simple_allocation(aid_a, plate.id, 200), _simple_allocation(aid_b, plate.id, 200)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    assert result.total_destination_plant_count == 400
    assert len(result.destination_lines) == 1
    assert len(result.allocations) == 2


# =====================================================================
# Capacity
# =====================================================================


@pytest.mark.integration
def test_capacity_below_boundary_succeeds(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, _spec = _build_scenario(db_session, tenant, user, farm, tray_count=1, biological_position_count=200)
    aid = s["source_assignment_ids"][0]
    plate = s["destination_carriers"][0]
    table_id = s["intersalads_table_ids"][0]
    result = _record(
        db_session, tenant, farm, user, s["batch"], [_simple_source(aid)],
        [_simple_destination(plate.id, table_id, count=199)], [_simple_allocation(aid, plate.id, 199)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    assert result.total_destination_plant_count == 199


@pytest.mark.integration
def test_capacity_exact_boundary_succeeds(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, _spec = _build_scenario(db_session, tenant, user, farm, tray_count=1, biological_position_count=200)
    aid = s["source_assignment_ids"][0]
    plate = s["destination_carriers"][0]
    table_id = s["intersalads_table_ids"][0]
    result = _record(
        db_session, tenant, farm, user, s["batch"], [_simple_source(aid)],
        [_simple_destination(plate.id, table_id, count=200)], [_simple_allocation(aid, plate.id, 200)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    assert result.total_destination_plant_count == 200


@pytest.mark.integration
def test_biological_capacity_exceeded_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, _spec = _build_scenario(db_session, tenant, user, farm, tray_count=1, biological_position_count=200)
    aid = s["source_assignment_ids"][0]
    plate = s["destination_carriers"][0]
    table_id = s["intersalads_table_ids"][0]
    with pytest.raises(TransplantCapacityExceededError):
        _record(
            db_session, tenant, farm, user, s["batch"], [_simple_source(aid)],
            [_simple_destination(plate.id, table_id, count=201)], [_simple_allocation(aid, plate.id, 201)],
            effective_time=s["entry_time"] + timedelta(hours=2),
        )


@pytest.mark.integration
def test_existing_carrier_with_now_inactive_specification_remains_eligible(
    db_session, active_context_with_farm
) -> None:
    """Section 3's frozen rule: deactivating a CarrierSpecification blocks
    NEW Carrier registrations against it, never Transplant eligibility for a
    Carrier that already references it."""
    tenant, user, _headers, farm = active_context_with_farm
    s, spec = _build_scenario(db_session, tenant, user, farm, tray_count=1, biological_position_count=200)
    carrier_specification_service.deactivate_carrier_specification(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, specification_id=spec.id
    )
    aid = s["source_assignment_ids"][0]
    plate = s["destination_carriers"][0]
    table_id = s["intersalads_table_ids"][0]
    result = _record(
        db_session, tenant, farm, user, s["batch"], [_simple_source(aid)],
        [_simple_destination(plate.id, table_id, count=180)], [_simple_allocation(aid, plate.id, 180)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    assert result.total_destination_plant_count == 180


# =====================================================================
# Destination validation
# =====================================================================


@pytest.mark.integration
def test_wrong_destination_carrier_type_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    # `_build_scenario` requires the stage's own `nursery_cultivation_plate`
    # destination type; the generic `test_transplant.py` scenario's default
    # `cultivation_plate` carriers are a genuinely wrong type for THIS
    # stage's `required_carrier_type_id` -- reuse that mismatch directly.
    s, _spec = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    other = build_transplant_ready_scenario(
        db_session, tenant, user, farm, tray_count=1, transplanting_required_type="cultivation_plate",
    )
    aid = s["source_assignment_ids"][0]
    wrong_plate = other["destination_carriers"][0]
    table_id = s["intersalads_table_ids"][0]
    with pytest.raises(TransplantValidationError):
        _record(
            db_session, tenant, farm, user, s["batch"], [_simple_source(aid)],
            [_simple_destination(wrong_plate.id, table_id, count=100)],
            [_simple_allocation(aid, wrong_plate.id, 100)],
            effective_time=s["entry_time"] + timedelta(hours=2),
        )


@pytest.mark.integration
def test_plate_already_actively_assigned_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, _spec = _build_scenario(db_session, tenant, user, farm, tray_count=2)
    aid_a, aid_b = s["source_assignment_ids"]
    plate = s["destination_carriers"][0]
    table_a, table_b = s["intersalads_table_ids"][0], s["intersalads_table_ids"][1]

    _record(
        db_session, tenant, farm, user, s["batch"], [_simple_source(aid_a)],
        [_simple_destination(plate.id, table_a, count=100)], [_simple_allocation(aid_a, plate.id, 100)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    with pytest.raises(DestinationCarrierAlreadyAssignedError):
        _record(
            db_session, tenant, farm, user, s["batch"], [_simple_source(aid_b)],
            [_simple_destination(plate.id, table_b, count=50)], [_simple_allocation(aid_b, plate.id, 50)],
            effective_time=s["entry_time"] + timedelta(hours=3),
        )


@pytest.mark.integration
def test_wrong_destination_location_type_rejected(db_session, active_context_with_farm) -> None:
    """Movement's own occupancy-compatibility check, reused unmodified --
    a Grow Table is never compatible with a Nursery Cultivation Plate."""
    tenant, user, _headers, farm = active_context_with_farm
    s, _spec = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    aid = s["source_assignment_ids"][0]
    plate = s["destination_carriers"][0]
    wrong_type_location = s["seedling_table_ids"][1]
    with pytest.raises(IncompatibleOccupantTargetError):
        _record(
            db_session, tenant, farm, user, s["batch"], [_simple_source(aid)],
            [_simple_destination(plate.id, wrong_type_location, count=100)],
            [_simple_allocation(aid, plate.id, 100)],
            effective_time=s["entry_time"] + timedelta(hours=2),
        )


# =====================================================================
# Atomicity
# =====================================================================


@pytest.mark.integration
def test_multi_destination_one_placement_failure_rolls_back_everything(
    db_session, active_context_with_farm
) -> None:
    """Section 8: the second destination's Table is already full when this
    command runs -- proving the whole composite command (Transplant AND
    every physical Movement/Occupancy, including the FIRST destination's
    otherwise-valid placement) fails atomically, not partially."""
    tenant, user, _headers, farm = active_context_with_farm
    s, _spec = _build_scenario(db_session, tenant, user, farm, tray_count=2)
    # Fill the second Table to its configured capacity (4) with unrelated
    # occupants first, via ordinary Movement, so the composite command's
    # second placement genuinely fails on a real capacity conflict.
    from app.services import movement_service

    full_table_id = s["intersalads_table_ids"][1]
    filler_spec = _register_destination_spec(db_session, tenant, user, biological_position_count=50)
    from app.services import carrier_service

    for i in range(4):
        filler = carrier_service.register_carrier(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            specification_id=filler_spec.id, code=f"FILL-{uuid.uuid4().hex[:8]}", issued_date=None,
        )
        movement_service.execute_movement(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            client_command_id=uuid.uuid4(), effective_time=s["entry_time"] + timedelta(hours=1),
            occupant_kind="carrier", occupant_id=filler.id, destination_kind="location",
            destination_id=full_table_id, reason=None,
        )

    aid_a, aid_b = s["source_assignment_ids"]
    plate_a, plate_b = s["destination_carriers"][0], s["destination_carriers"][1]
    ok_table = s["intersalads_table_ids"][0]

    with pytest.raises(TargetOccupiedError):
        _record(
            db_session, tenant, farm, user, s["batch"],
            [_simple_source(aid_a), _simple_source(aid_b)],
            [
                _simple_destination(plate_a.id, ok_table, count=100),
                _simple_destination(plate_b.id, full_table_id, count=100),
            ],
            [_simple_allocation(aid_a, plate_a.id, 100), _simple_allocation(aid_b, plate_b.id, 100)],
            effective_time=s["entry_time"] + timedelta(hours=2),
        )

    assert db_session.execute(
        select(func.count()).select_from(TransplantEvent).where(TransplantEvent.batch_id == s["batch"].id)
    ).scalar_one() == 0
    assert db_session.execute(
        select(func.count()).select_from(TransplantDestinationLine)
    ).scalar_one() == 0
    assert db_session.execute(select(func.count()).select_from(TransplantAllocation)).scalar_one() == 0
    assert db_session.execute(
        select(func.count()).select_from(SeedlingSourceCheckpoint).where(
            SeedlingSourceCheckpoint.batch_id == s["batch"].id
        )
    ).scalar_one() == 0
    # Neither Plate has an active Occupancy -- no partial Movement survived.
    assert db_session.execute(
        select(func.count()).select_from(Occupancy).where(
            Occupancy.occupant_carrier_id.in_([plate_a.id, plate_b.id]), Occupancy.end_time.is_(None)
        )
    ).scalar_one() == 0
    # Section 9: the underlying audit events participate in the SAME
    # transaction as everything else -- neither the (never-reached)
    # crop_batch.transplanted event for this batch, nor a movement.executed
    # event for either Plate, survives the rollback. Scoped by event_data
    # content (not a bare tenant-wide count) since this scenario's own setup
    # legitimately created earlier, unrelated audit events (sowing,
    # germination, seedling entry, the filler Movements used to fill the
    # second Table).
    assert db_session.execute(
        text(
            "SELECT count(*) FROM audit_events WHERE action = 'crop_batch.transplanted' "
            "AND event_data->>'batch_id' = :bid"
        ),
        {"bid": str(s["batch"].id)},
    ).scalar_one() == 0
    assert db_session.execute(
        text(
            "SELECT count(*) FROM audit_events WHERE action = 'movement.executed' "
            "AND event_data->>'occupant_id' IN (:pa, :pb)"
        ),
        {"pa": str(plate_a.id), "pb": str(plate_b.id)},
    ).scalar_one() == 0


@pytest.mark.integration
def test_biological_capacity_failure_leaves_no_movement_state(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, _spec = _build_scenario(db_session, tenant, user, farm, tray_count=1, biological_position_count=200)
    aid = s["source_assignment_ids"][0]
    plate = s["destination_carriers"][0]
    table_id = s["intersalads_table_ids"][0]
    with pytest.raises(TransplantCapacityExceededError):
        _record(
            db_session, tenant, farm, user, s["batch"], [_simple_source(aid)],
            [_simple_destination(plate.id, table_id, count=250)], [_simple_allocation(aid, plate.id, 250)],
            effective_time=s["entry_time"] + timedelta(hours=2),
        )
    assert db_session.execute(
        select(func.count()).select_from(Movement).where(Movement.occupant_carrier_id == plate.id)
    ).scalar_one() == 0
    assert db_session.execute(
        text(
            "SELECT count(*) FROM audit_events WHERE action = 'crop_batch.transplanted' "
            "AND event_data->>'batch_id' = :bid"
        ),
        {"bid": str(s["batch"].id)},
    ).scalar_one() == 0
    assert db_session.execute(
        text("SELECT count(*) FROM audit_events WHERE action = 'movement.executed' AND event_data->>'occupant_id' = :pid"),
        {"pid": str(plate.id)},
    ).scalar_one() == 0


# =====================================================================
# Idempotency
# =====================================================================


@pytest.mark.integration
def test_exact_replay_returns_same_composite_result_no_duplicate_movements(
    db_session, active_context_with_farm
) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, _spec = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    aid = s["source_assignment_ids"][0]
    plate = s["destination_carriers"][0]
    table_id = s["intersalads_table_ids"][0]
    command_id = uuid.uuid4()

    first = _record(
        db_session, tenant, farm, user, s["batch"], [_simple_source(aid)],
        [_simple_destination(plate.id, table_id, count=150)], [_simple_allocation(aid, plate.id, 150)],
        client_command_id=command_id, effective_time=s["entry_time"] + timedelta(hours=2),
    )
    second = _record(
        db_session, tenant, farm, user, s["batch"], [_simple_source(aid)],
        [_simple_destination(plate.id, table_id, count=150)], [_simple_allocation(aid, plate.id, 150)],
        client_command_id=command_id, effective_time=s["entry_time"] + timedelta(hours=2),
    )
    assert second.id == first.id
    assert second.destination_lines[0].movement_id == first.destination_lines[0].movement_id
    assert db_session.execute(
        select(func.count()).select_from(Movement).where(Movement.occupant_carrier_id == plate.id)
    ).scalar_one() == 1
    assert db_session.execute(
        select(func.count()).select_from(TransplantEvent).where(TransplantEvent.batch_id == s["batch"].id)
    ).scalar_one() == 1


@pytest.mark.integration
def test_derived_movement_command_ids_deterministic(db_session, active_context_with_farm) -> None:
    outer = uuid.uuid4()
    cid = uuid.uuid4()
    first = intersalads_transplant_service._derive_movement_client_command_id(outer, cid)
    second = intersalads_transplant_service._derive_movement_client_command_id(outer, cid)
    assert first == second
    different_carrier = intersalads_transplant_service._derive_movement_client_command_id(outer, uuid.uuid4())
    assert different_carrier != first


@pytest.mark.integration
def test_mismatched_replay_payload_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, _spec = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    aid = s["source_assignment_ids"][0]
    plate = s["destination_carriers"][0]
    table_id = s["intersalads_table_ids"][0]
    command_id = uuid.uuid4()

    _record(
        db_session, tenant, farm, user, s["batch"], [_simple_source(aid)],
        [_simple_destination(plate.id, table_id, count=150)], [_simple_allocation(aid, plate.id, 150)],
        client_command_id=command_id, effective_time=s["entry_time"] + timedelta(hours=2),
    )
    with pytest.raises(TransplantCommandReusedWithDifferentPayloadError):
        _record(
            db_session, tenant, farm, user, s["batch"], [_simple_source(aid)],
            [_simple_destination(plate.id, table_id, count=100)], [_simple_allocation(aid, plate.id, 100)],
            client_command_id=command_id, effective_time=s["entry_time"] + timedelta(hours=2),
        )


@pytest.mark.integration
def test_replay_with_different_destination_location_reports_state_conflict(
    db_session, active_context_with_farm
) -> None:
    """Section 9's explicit, non-hand-waved case: the generic Transplant
    core's own fingerprint does not cover `destination_location_id` (it has
    no concept of location at all) -- a same-command-id resubmission with a
    different Table must not be silently accepted or fabricated."""
    tenant, user, _headers, farm = active_context_with_farm
    s, _spec = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    aid = s["source_assignment_ids"][0]
    plate = s["destination_carriers"][0]
    table_a, table_b = s["intersalads_table_ids"][0], s["intersalads_table_ids"][1]
    command_id = uuid.uuid4()

    _record(
        db_session, tenant, farm, user, s["batch"], [_simple_source(aid)],
        [_simple_destination(plate.id, table_a, count=150)], [_simple_allocation(aid, plate.id, 150)],
        client_command_id=command_id, effective_time=s["entry_time"] + timedelta(hours=2),
    )
    with pytest.raises(IntersaladsTransplantReplayStateConflictError):
        _record(
            db_session, tenant, farm, user, s["batch"], [_simple_source(aid)],
            [_simple_destination(plate.id, table_b, count=150)], [_simple_allocation(aid, plate.id, 150)],
            client_command_id=command_id, effective_time=s["entry_time"] + timedelta(hours=2),
        )


# =====================================================================
# Authorization / tenancy
# =====================================================================


@pytest.mark.integration
def test_transplant_manage_sufficient_via_http_no_movement_manage_required(client, active_context_with_farm, db_session) -> None:
    tenant, user, headers, farm = active_context_with_farm
    s, _spec = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    db_session.commit()
    aid = s["source_assignment_ids"][0]
    plate = s["destination_carriers"][0]
    table_id = s["intersalads_table_ids"][0]

    resp = client.post(
        f"/farms/{farm.id}/crop-batches/{s['batch'].id}/intersalads-transplants", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()),
            "effective_time": (s["entry_time"] + timedelta(hours=2)).isoformat(),
            "note": None,
            "source_lines": [
                {
                    "source_assignment_id": str(aid), "transplant_damage_count": 0, "qc_rejection_count": 0,
                    "sample_count": 0, "other_loss_count": 0, "other_loss_note": None, "note": None,
                }
            ],
            "destination_lines": [
                {
                    "destination_carrier_id": str(plate.id), "assigned_plant_count": 150,
                    "destination_location_id": str(table_id), "note": None,
                }
            ],
            "allocations": [
                {"source_assignment_id": str(aid), "destination_carrier_id": str(plate.id), "allocated_plant_count": 150}
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["destination_lines"][0]["destination_location_id"] == str(table_id)


@pytest.mark.integration
def test_storekeeper_role_without_transplant_manage_denied_via_http(client, active_context_with_farm, db_session) -> None:
    """`storekeeper` holds no `transplant.manage` -- `operator` does (it
    genuinely needs it for the existing plain `/transplants` endpoint), so
    it is not a useful denied-role fixture here."""
    tenant, user, headers, farm = active_context_with_farm
    from app.services import membership_service, user_service

    s, _spec = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    db_session.commit()
    storekeeper = user_service.create_user(
        db_session, oidc_issuer="iss", oidc_subject="isalads-sk", email="isalads-sk@example.com",
        display_name="Storekeeper",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant.id, user_id=storekeeper.id, role_code="storekeeper", actor_user_id=None
    )
    db_session.commit()
    op_headers = {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(storekeeper.id)}
    aid = s["source_assignment_ids"][0]
    plate = s["destination_carriers"][0]
    table_id = s["intersalads_table_ids"][0]
    resp = client.post(
        f"/farms/{farm.id}/crop-batches/{s['batch'].id}/intersalads-transplants", headers=op_headers,
        json={
            "client_command_id": str(uuid.uuid4()),
            "effective_time": (s["entry_time"] + timedelta(hours=2)).isoformat(), "note": None,
            "source_lines": [
                {
                    "source_assignment_id": str(aid), "transplant_damage_count": 0, "qc_rejection_count": 0,
                    "sample_count": 0, "other_loss_count": 0, "other_loss_note": None, "note": None,
                }
            ],
            "destination_lines": [
                {
                    "destination_carrier_id": str(plate.id), "assigned_plant_count": 150,
                    "destination_location_id": str(table_id), "note": None,
                }
            ],
            "allocations": [
                {"source_assignment_id": str(aid), "destination_carrier_id": str(plate.id), "allocated_plant_count": 150}
            ],
        },
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.integration
def test_cross_tenant_rejected(db_session, active_context_with_farm) -> None:
    """A farm never resolves cross-tenant at all -- the composite command's
    very first check (`_require_active_farm`, inherited unmodified from
    `_record_transplant_core`) already fails closed before anything
    downstream (source assignment, carrier, location) is ever reached."""
    tenant, user, _headers, farm = active_context_with_farm
    s, _spec = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    other_tenant = tenant_service.create_tenant(db_session, code="isalads-other-tenant", name="Other")
    aid = s["source_assignment_ids"][0]
    plate = s["destination_carriers"][0]
    table_id = s["intersalads_table_ids"][0]
    from app.services.errors import FarmNotFoundError

    with pytest.raises(FarmNotFoundError):
        intersalads_transplant_service.record_intersalads_transplant(
            db_session, tenant_id=other_tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
            client_command_id=uuid.uuid4(), effective_time=s["entry_time"] + timedelta(hours=2), note=None,
            source_lines=[_simple_source(aid)],
            destination_lines=[_simple_destination(plate.id, table_id, count=150)],
            allocations=[_simple_allocation(aid, plate.id, 150)],
        )


@pytest.mark.integration
def test_wrong_farm_rejected(db_session, active_context_with_farm) -> None:
    """Same tenant, a genuinely different (valid, active) Farm -- proves the
    Batch lookup itself is farm-scoped, not merely the outer farm check."""
    tenant, user, _headers, farm = active_context_with_farm
    from app.services import farm_service

    s, _spec = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    other_farm = farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code="isalads-other-farm", name="Other Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    aid = s["source_assignment_ids"][0]
    plate = s["destination_carriers"][0]
    table_id = s["intersalads_table_ids"][0]
    from app.services.errors import CropBatchNotFoundError

    with pytest.raises(CropBatchNotFoundError):
        intersalads_transplant_service.record_intersalads_transplant(
            db_session, tenant_id=tenant.id, farm_id=other_farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
            client_command_id=uuid.uuid4(), effective_time=s["entry_time"] + timedelta(hours=2), note=None,
            source_lines=[_simple_source(aid)],
            destination_lines=[_simple_destination(plate.id, table_id, count=150)],
            allocations=[_simple_allocation(aid, plate.id, 150)],
        )


# =====================================================================
# Audit
# =====================================================================


@pytest.mark.integration
def test_audit_preserves_both_underlying_events_no_synthetic_composite_event(
    db_session, active_context_with_farm
) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, _spec = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    aid = s["source_assignment_ids"][0]
    plate = s["destination_carriers"][0]
    table_id = s["intersalads_table_ids"][0]
    result = _record(
        db_session, tenant, farm, user, s["batch"], [_simple_source(aid)],
        [_simple_destination(plate.id, table_id, count=150)], [_simple_allocation(aid, plate.id, 150)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    transplant_audit = db_session.execute(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action == "crop_batch.transplanted", AuditEvent.entity_id == result.id
        )
    ).scalar_one()
    movement_audit = db_session.execute(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action == "movement.executed",
            AuditEvent.entity_id == result.destination_lines[0].movement_id,
        )
    ).scalar_one()
    assert transplant_audit == 1
    assert movement_audit == 1


# =====================================================================
# Traceability
# =====================================================================


@pytest.mark.integration
def test_backward_traceability_plate_to_seed_lot(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, _spec = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    aid = s["source_assignment_ids"][0]
    plate = s["destination_carriers"][0]
    table_id = s["intersalads_table_ids"][0]
    result = _record(
        db_session, tenant, farm, user, s["batch"], [_simple_source(aid)],
        [_simple_destination(plate.id, table_id, count=150)], [_simple_allocation(aid, plate.id, 150)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    assert len(result.source_lines) == 1
    source = result.source_lines[0]
    assert source.seed_lot.id == s["seed_lot"].id
    assert source.carrier.id == s["source_carriers"][0].id
    assert result.destination_lines[0].carrier.id == plate.id
    assert result.allocations[0].source_carrier.id == s["source_carriers"][0].id
    assert result.allocations[0].destination_carrier.id == plate.id
