import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.models.audit_event import AuditEvent
from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.transplant_allocation import TransplantAllocation
from app.models.transplant_destination_line import TransplantDestinationLine
from app.models.transplant_event import TransplantEvent
from app.models.transplant_source_line import TransplantSourceLine
from app.schemas.transplant_event import (
    TransplantAllocationIn,
    TransplantDestinationLineIn,
    TransplantEventCreate,
    TransplantSourceLineIn,
)
from app.services import (
    carrier_service,
    crop_batch_service,
    crop_service,
    production_system_service,
    sowing_service,
    transplant_service,
    workflow_service,
)
from app.services.errors import (
    CarrierNotFoundError,
    DestinationCarrierAlreadyAssignedError,
    InvalidTransplantEffectiveTimeError,
    SourceAssignmentAlreadyReleasedError,
    TransplantCommandReusedWithDifferentPayloadError,
    TransplantValidationError,
)

# --- Application-level (Pydantic) validation — no DB required ---


def _source(**overrides):
    defaults = dict(source_assignment_id=uuid.uuid4(), source_plant_count=200, discarded_plant_count=0)
    defaults.update(overrides)
    return TransplantSourceLineIn(**defaults)


def _destination(**overrides):
    defaults = dict(destination_carrier_id=uuid.uuid4(), assigned_plant_count=200)
    defaults.update(overrides)
    return TransplantDestinationLineIn(**defaults)


def _allocation(source_id, dest_id, count=200):
    return TransplantAllocationIn(
        source_assignment_id=source_id, destination_carrier_id=dest_id, allocated_plant_count=count
    )


def test_source_line_discard_exceeding_count_rejected() -> None:
    with pytest.raises(ValueError):
        _source(source_plant_count=100, discarded_plant_count=101)


def test_event_duplicate_source_assignment_rejected() -> None:
    sid = uuid.uuid4()
    dest = _destination()
    with pytest.raises(ValueError):
        TransplantEventCreate(
            client_command_id=uuid.uuid4(), effective_time=datetime.now(timezone.utc),
            source_lines=[_source(source_assignment_id=sid), _source(source_assignment_id=sid)],
            destination_lines=[dest], allocations=[_allocation(sid, dest.destination_carrier_id)],
        )


def test_event_duplicate_destination_carrier_rejected() -> None:
    did = uuid.uuid4()
    src = _source()
    with pytest.raises(ValueError):
        TransplantEventCreate(
            client_command_id=uuid.uuid4(), effective_time=datetime.now(timezone.utc),
            source_lines=[src],
            destination_lines=[_destination(destination_carrier_id=did), _destination(destination_carrier_id=did)],
            allocations=[_allocation(src.source_assignment_id, did)],
        )


def test_event_duplicate_allocation_pair_rejected() -> None:
    src = _source()
    dest = _destination()
    alloc = _allocation(src.source_assignment_id, dest.destination_carrier_id, 100)
    with pytest.raises(ValueError):
        TransplantEventCreate(
            client_command_id=uuid.uuid4(), effective_time=datetime.now(timezone.utc),
            source_lines=[src], destination_lines=[dest], allocations=[alloc, alloc],
        )


def test_event_allocation_undeclared_source_rejected() -> None:
    src = _source()
    dest = _destination()
    with pytest.raises(ValueError):
        TransplantEventCreate(
            client_command_id=uuid.uuid4(), effective_time=datetime.now(timezone.utc),
            source_lines=[src], destination_lines=[dest],
            allocations=[_allocation(uuid.uuid4(), dest.destination_carrier_id)],
        )


def test_event_allocation_undeclared_destination_rejected() -> None:
    src = _source()
    dest = _destination()
    with pytest.raises(ValueError):
        TransplantEventCreate(
            client_command_id=uuid.uuid4(), effective_time=datetime.now(timezone.utc),
            source_lines=[src], destination_lines=[dest],
            allocations=[_allocation(src.source_assignment_id, uuid.uuid4())],
        )


def test_event_unused_destination_line_rejected() -> None:
    src = _source()
    dest_used = _destination()
    dest_unused = _destination()
    with pytest.raises(ValueError):
        TransplantEventCreate(
            client_command_id=uuid.uuid4(), effective_time=datetime.now(timezone.utc),
            source_lines=[src], destination_lines=[dest_used, dest_unused],
            allocations=[_allocation(src.source_assignment_id, dest_used.destination_carrier_id)],
        )


def test_event_unused_non_discarded_source_line_rejected() -> None:
    src_used = _source()
    src_unused = _source()
    dest = _destination(assigned_plant_count=200)
    with pytest.raises(ValueError):
        TransplantEventCreate(
            client_command_id=uuid.uuid4(), effective_time=datetime.now(timezone.utc),
            source_lines=[src_used, src_unused], destination_lines=[dest],
            allocations=[_allocation(src_used.source_assignment_id, dest.destination_carrier_id)],
        )


def test_event_fully_discarded_source_without_allocation_accepted() -> None:
    src_used = _source()
    src_discarded = _source(source_plant_count=50, discarded_plant_count=50)
    dest = _destination()
    payload = TransplantEventCreate(
        client_command_id=uuid.uuid4(), effective_time=datetime.now(timezone.utc),
        source_lines=[src_used, src_discarded], destination_lines=[dest],
        allocations=[_allocation(src_used.source_assignment_id, dest.destination_carrier_id)],
    )
    assert len(payload.source_lines) == 2


def test_event_requires_at_least_one_destination_line() -> None:
    with pytest.raises(ValueError):
        TransplantEventCreate(
            client_command_id=uuid.uuid4(), effective_time=datetime.now(timezone.utc),
            source_lines=[_source()], destination_lines=[], allocations=[],
        )


def test_event_rejects_extra_fields() -> None:
    src = _source()
    dest = _destination()
    with pytest.raises(ValueError):
        TransplantEventCreate(
            client_command_id=uuid.uuid4(), effective_time=datetime.now(timezone.utc), source_lines=[src],
            destination_lines=[dest], allocations=[_allocation(src.source_assignment_id, dest.destination_carrier_id)],
            batch_id=uuid.uuid4(),
        )


def test_event_naive_effective_time_rejected() -> None:
    src = _source()
    dest = _destination()
    with pytest.raises(ValueError):
        TransplantEventCreate(
            client_command_id=uuid.uuid4(), effective_time=datetime.now(), source_lines=[src],
            destination_lines=[dest], allocations=[_allocation(src.source_assignment_id, dest.destination_carrier_id)],
        )


def test_event_too_many_source_lines_rejected() -> None:
    lines = [_source() for _ in range(201)]
    dest = _destination()
    with pytest.raises(ValueError):
        TransplantEventCreate(
            client_command_id=uuid.uuid4(), effective_time=datetime.now(timezone.utc), source_lines=lines,
            destination_lines=[dest], allocations=[],
        )


# --- Integration helpers ----------------------------------------------------------


def _now():
    return datetime.now(timezone.utc)


def _build_scenario(db_session, tenant, user, farm, *, suffix=None, transplanting_required_type="cultivation_plate"):
    suffix = suffix or uuid.uuid4().hex[:8]
    crop = crop_service.register_crop(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"ICE-{suffix}",
        common_name="Iceberg", scientific_name=None, crop_category="leafy_green",
    )
    variety = crop_service.register_variety(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"MAM-{suffix}",
        name="Mamutik", supplier_reference=None,
    )
    ps = production_system_service.register_production_system(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"PS-{suffix}", name="Nursery Tray",
        description=None,
    )
    workflow = workflow_service.register_workflow(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, variety_id=variety.id,
        production_system_id=ps.id, code=f"WF-{suffix}", name="Workflow",
    )
    version = workflow_service.create_draft_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id
    )
    seeding = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="SEEDING", name="Seeding", display_order=0, stage_category="seeding",
        expected_duration_minutes=None, permitted_location_type_code=None,
        required_carrier_type_code="seed_tray", is_start=True, is_terminal=False,
    )
    transplanting = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="TRANSPLANTING", name="Transplanting", display_order=1, stage_category="transplanting",
        expected_duration_minutes=None, permitted_location_type_code=None,
        required_carrier_type_code=transplanting_required_type, is_start=False, is_terminal=False,
    )
    growing = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="GROWING", name="Growing", display_order=2, stage_category="intermediate",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=False,
    )
    complete = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="COMPLETE", name="Complete", display_order=3, stage_category="completed",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=True,
    )
    t1 = workflow_service.add_transition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=seeding.id, to_stage_id=transplanting.id, code="ADVANCE-1", name="Advance 1",
    )
    t2 = workflow_service.add_transition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=transplanting.id, to_stage_id=growing.id, code="ADVANCE-2", name="Advance 2",
    )
    t3 = workflow_service.add_transition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=growing.id, to_stage_id=complete.id, code="ADVANCE-3", name="Advance 3",
    )
    workflow_service.publish_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id
    )
    batch = crop_batch_service.create_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"BATCH-{suffix}", workflow_id=workflow.id, effective_time=_now(),
    )
    seed_lot = sowing_service.register_seed_lot(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id,
        variety_id=variety.id, code=f"LOT-{suffix}", supplier_name=None, supplier_lot_reference=None,
        received_date=None, expiry_date=None,
    )
    source_carriers = [
        carrier_service.register_carrier(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            carrier_type_code="seed_tray", code=f"ST-{suffix}-{n:04d}", issued_date=None,
        )
        for n in range(1, 5)
    ]
    sowing_service.sow_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
        lines=[
            {
                "carrier_id": c.id, "seed_lot_id": seed_lot.id, "sown_site_count": 200, "seed_count": 200,
                "line_note": None,
            }
            for c in source_carriers
        ],
    )
    assignments = sowing_service.list_batch_carriers(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id
    )
    assignment_by_carrier_code = {a.carrier.code: a.id for a in assignments}
    source_assignment_ids = [assignment_by_carrier_code[c.code] for c in source_carriers]

    crop_batch_service.transition_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), configured_transition_id=t1.id, effective_time=_now(), reason=None,
    )

    destination_carriers = [
        carrier_service.register_carrier(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            carrier_type_code="cultivation_plate", code=f"CP-{suffix}-{n:04d}", issued_date=None,
        )
        for n in range(1, 5)
    ]
    return {
        "crop": crop, "variety": variety, "workflow": workflow,
        "stages": {"SEEDING": seeding, "TRANSPLANTING": transplanting, "GROWING": growing, "COMPLETE": complete},
        "transitions": {"t1": t1, "t2": t2, "t3": t3}, "batch": batch, "seed_lot": seed_lot,
        "source_carriers": source_carriers, "source_assignment_ids": source_assignment_ids,
        "destination_carriers": destination_carriers,
    }


def _simple_source(assignment_id, **overrides):
    defaults = dict(source_assignment_id=assignment_id, source_plant_count=200, discarded_plant_count=0, note=None)
    defaults.update(overrides)
    return defaults


def _simple_destination(carrier_id, **overrides):
    defaults = dict(destination_carrier_id=carrier_id, assigned_plant_count=200, note=None)
    defaults.update(overrides)
    return defaults


def _simple_allocation(source_id, dest_id, count=200):
    return {"source_assignment_id": source_id, "destination_carrier_id": dest_id, "allocated_plant_count": count}


def _transplant(db_session, tenant, farm, user, batch, source_lines, destination_lines, allocations, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
    )
    defaults.update(overrides)
    return transplant_service.record_transplant(
        db_session, source_lines=source_lines, destination_lines=destination_lines, allocations=allocations,
        **defaults,
    )


# --- Core behavior --------------------------------------------------------------


@pytest.mark.integration
def test_transplant_one_to_one_succeeds(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    source_lines = [_simple_source(aid) for aid in s["source_assignment_ids"]]
    destination_lines = [_simple_destination(c.id) for c in s["destination_carriers"]]
    allocations = [
        _simple_allocation(aid, c.id) for aid, c in zip(s["source_assignment_ids"], s["destination_carriers"])
    ]
    event = _transplant(db_session, tenant, farm, user, s["batch"], source_lines, destination_lines, allocations)

    assert db_session.execute(
        select(func.count()).select_from(TransplantEvent).where(TransplantEvent.batch_id == s["batch"].id)
    ).scalar_one() == 1
    for aid in s["source_assignment_ids"]:
        assignment = db_session.get(BatchCarrierAssignment, aid)
        assert assignment.released_effective_time == event.effective_time
        assert assignment.released_by_transplant_event_id == event.id
    active_destination_assignments = list(
        db_session.execute(
            select(BatchCarrierAssignment).where(
                BatchCarrierAssignment.opening_transplant_event_id == event.id
            )
        ).scalars()
    )
    assert len(active_destination_assignments) == 4
    assert all(a.released_effective_time is None for a in active_destination_assignments)
    audit_count = db_session.execute(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action == "crop_batch.transplanted", AuditEvent.entity_id == event.id
        )
    ).scalar_one()
    assert audit_count == 1


@pytest.mark.integration
def test_transplant_many_to_many_lineage_exact(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    a0, a1 = s["source_assignment_ids"][0], s["source_assignment_ids"][1]
    d0, d1 = s["destination_carriers"][0].id, s["destination_carriers"][1].id
    source_lines = [_simple_source(a0), _simple_source(a1)]
    destination_lines = [
        _simple_destination(d0, assigned_plant_count=220), _simple_destination(d1, assigned_plant_count=180),
    ]
    allocations = [
        _simple_allocation(a0, d0, 120), _simple_allocation(a0, d1, 80),
        _simple_allocation(a1, d0, 100), _simple_allocation(a1, d1, 100),
    ]
    event = _transplant(db_session, tenant, farm, user, s["batch"], source_lines, destination_lines, allocations)

    assert db_session.execute(
        select(func.count()).select_from(TransplantAllocation).where(
            TransplantAllocation.transplant_event_id == event.id
        )
    ).scalar_one() == 4
    read = transplant_service.get_transplant_event(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=s["batch"].id, transplant_event_id=event.id
    )
    pairs = {(a.source_carrier.id, a.destination_carrier.id): a.allocated_plant_count for a in read.allocations}
    source_carrier_by_assignment = {a0: s["source_carriers"][0].id, a1: s["source_carriers"][1].id}
    assert pairs[(source_carrier_by_assignment[a0], d0)] == 120
    assert pairs[(source_carrier_by_assignment[a0], d1)] == 80
    assert pairs[(source_carrier_by_assignment[a1], d0)] == 100
    assert pairs[(source_carrier_by_assignment[a1], d1)] == 100


@pytest.mark.integration
def test_transplant_fully_discarded_source_succeeds(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    used, discarded = s["source_assignment_ids"][0], s["source_assignment_ids"][1]
    source_lines = [
        _simple_source(used, source_plant_count=200),
        _simple_source(discarded, source_plant_count=200, discarded_plant_count=200),
    ]
    destination_lines = [_simple_destination(s["destination_carriers"][0].id)]
    allocations = [_simple_allocation(used, s["destination_carriers"][0].id, 200)]
    event = _transplant(db_session, tenant, farm, user, s["batch"], source_lines, destination_lines, allocations)
    assert event.id is not None
    discarded_assignment = db_session.get(BatchCarrierAssignment, discarded)
    assert discarded_assignment.released_effective_time == event.effective_time


@pytest.mark.integration
def test_source_not_from_sowing_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    source_lines = [_simple_source(aid) for aid in s["source_assignment_ids"]]
    destination_lines = [_simple_destination(c.id) for c in s["destination_carriers"]]
    allocations = [
        _simple_allocation(aid, c.id) for aid, c in zip(s["source_assignment_ids"], s["destination_carriers"])
    ]
    _transplant(db_session, tenant, farm, user, s["batch"], source_lines, destination_lines, allocations)

    destination_assignment_id = db_session.execute(
        select(BatchCarrierAssignment.id).where(
            BatchCarrierAssignment.carrier_id == s["destination_carriers"][0].id
        )
    ).scalar_one()
    fresh_destination = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        carrier_type_code="cultivation_plate", code="CP-FRESH-0001", issued_date=None,
    )
    with pytest.raises(TransplantValidationError):
        _transplant(
            db_session, tenant, farm, user, s["batch"],
            [_simple_source(destination_assignment_id)], [_simple_destination(fresh_destination.id)],
            [_simple_allocation(destination_assignment_id, fresh_destination.id)],
        )


@pytest.mark.integration
def test_source_assignment_already_released_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    source_lines = [_simple_source(aid) for aid in s["source_assignment_ids"]]
    destination_lines = [_simple_destination(c.id) for c in s["destination_carriers"]]
    allocations = [
        _simple_allocation(aid, c.id) for aid, c in zip(s["source_assignment_ids"], s["destination_carriers"])
    ]
    _transplant(db_session, tenant, farm, user, s["batch"], source_lines, destination_lines, allocations)

    fresh_destination = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        carrier_type_code="cultivation_plate", code="CP-FRESH-RELEASED", issued_date=None,
    )
    with pytest.raises(SourceAssignmentAlreadyReleasedError):
        _transplant(
            db_session, tenant, farm, user, s["batch"],
            [_simple_source(s["source_assignment_ids"][0])], [_simple_destination(fresh_destination.id)],
            [_simple_allocation(s["source_assignment_ids"][0], fresh_destination.id)],
        )


@pytest.mark.integration
def test_destination_carrier_already_assigned_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    source_lines = [_simple_source(aid) for aid in s["source_assignment_ids"]]
    destination_lines = [_simple_destination(c.id) for c in s["destination_carriers"]]
    allocations = [
        _simple_allocation(aid, c.id) for aid, c in zip(s["source_assignment_ids"], s["destination_carriers"])
    ]
    _transplant(db_session, tenant, farm, user, s["batch"], source_lines, destination_lines, allocations)

    s2 = _build_scenario(db_session, tenant, user, farm, suffix="reuse2")
    with pytest.raises(DestinationCarrierAlreadyAssignedError):
        _transplant(
            db_session, tenant, farm, user, s2["batch"],
            [_simple_source(s2["source_assignment_ids"][0])], [_simple_destination(s["destination_carriers"][0].id)],
            [_simple_allocation(s2["source_assignment_ids"][0], s["destination_carriers"][0].id)],
        )


@pytest.mark.integration
def test_source_destination_carrier_overlap_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    source_carrier_id = s["source_carriers"][0].id
    with pytest.raises(TransplantValidationError):
        _transplant(
            db_session, tenant, farm, user, s["batch"],
            [_simple_source(s["source_assignment_ids"][0])], [_simple_destination(source_carrier_id)],
            [_simple_allocation(s["source_assignment_ids"][0], source_carrier_id)],
        )


@pytest.mark.integration
def test_inactive_destination_carrier_rejected(db_session, active_context_with_farm) -> None:
    from app.models.carrier import Carrier

    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    destination_carrier = db_session.get(Carrier, s["destination_carriers"][0].id)
    destination_carrier.status = "inactive"
    db_session.flush()
    with pytest.raises(TransplantValidationError):
        _transplant(
            db_session, tenant, farm, user, s["batch"],
            [_simple_source(s["source_assignment_ids"][0])], [_simple_destination(s["destination_carriers"][0].id)],
            [_simple_allocation(s["source_assignment_ids"][0], s["destination_carriers"][0].id)],
        )


@pytest.mark.integration
def test_wrong_destination_carrier_type_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    wrong_type_carrier = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        carrier_type_code="grow_cube", code="GC-WRONG", issued_date=None,
    )
    with pytest.raises(TransplantValidationError):
        _transplant(
            db_session, tenant, farm, user, s["batch"],
            [_simple_source(s["source_assignment_ids"][0])], [_simple_destination(wrong_type_carrier.id)],
            [_simple_allocation(s["source_assignment_ids"][0], wrong_type_carrier.id)],
        )


@pytest.mark.integration
def test_missing_transplanting_stage_configuration_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, transplanting_required_type=None)
    with pytest.raises(TransplantValidationError):
        _transplant(
            db_session, tenant, farm, user, s["batch"],
            [_simple_source(s["source_assignment_ids"][0])], [_simple_destination(s["destination_carriers"][0].id)],
            [_simple_allocation(s["source_assignment_ids"][0], s["destination_carriers"][0].id)],
        )


@pytest.mark.integration
def test_command_in_non_transplanting_stage_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    # Advance past TRANSPLANTING into COMPLETE.
    crop_batch_service.transition_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), configured_transition_id=s["transitions"]["t2"].id, effective_time=_now(),
        reason=None,
    )
    with pytest.raises(TransplantValidationError):
        _transplant(
            db_session, tenant, farm, user, s["batch"],
            [_simple_source(s["source_assignment_ids"][0])], [_simple_destination(s["destination_carriers"][0].id)],
            [_simple_allocation(s["source_assignment_ids"][0], s["destination_carriers"][0].id)],
        )


@pytest.mark.integration
def test_future_effective_time_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    with pytest.raises(InvalidTransplantEffectiveTimeError):
        _transplant(
            db_session, tenant, farm, user, s["batch"],
            [_simple_source(s["source_assignment_ids"][0])], [_simple_destination(s["destination_carriers"][0].id)],
            [_simple_allocation(s["source_assignment_ids"][0], s["destination_carriers"][0].id)],
            effective_time=_now() + timedelta(hours=1),
        )


@pytest.mark.integration
def test_source_count_exceeds_sown_site_count_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    with pytest.raises(TransplantValidationError):
        _transplant(
            db_session, tenant, farm, user, s["batch"],
            [_simple_source(s["source_assignment_ids"][0], source_plant_count=201)],
            [_simple_destination(s["destination_carriers"][0].id, assigned_plant_count=201)],
            [_simple_allocation(s["source_assignment_ids"][0], s["destination_carriers"][0].id, 201)],
        )


@pytest.mark.integration
def test_in_memory_reconciliation_mismatch_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    with pytest.raises(TransplantValidationError):
        _transplant(
            db_session, tenant, farm, user, s["batch"],
            [_simple_source(s["source_assignment_ids"][0], source_plant_count=200)],
            [_simple_destination(s["destination_carriers"][0].id, assigned_plant_count=150)],
            [_simple_allocation(s["source_assignment_ids"][0], s["destination_carriers"][0].id, 150)],
        )


# --- Idempotency --------------------------------------------------------------------


@pytest.mark.integration
def test_exact_transplant_retry_returns_original_event(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    command_id = uuid.uuid4()
    effective_time = _now()
    source_lines = [_simple_source(s["source_assignment_ids"][0])]
    destination_lines = [_simple_destination(s["destination_carriers"][0].id)]
    allocations = [_simple_allocation(s["source_assignment_ids"][0], s["destination_carriers"][0].id)]
    first = _transplant(
        db_session, tenant, farm, user, s["batch"], source_lines, destination_lines, allocations,
        client_command_id=command_id, effective_time=effective_time,
    )
    second = _transplant(
        db_session, tenant, farm, user, s["batch"], source_lines, destination_lines, allocations,
        client_command_id=command_id, effective_time=effective_time,
    )
    assert first.id == second.id
    assert db_session.execute(
        select(func.count()).select_from(TransplantEvent).where(TransplantEvent.batch_id == s["batch"].id)
    ).scalar_one() == 1


@pytest.mark.integration
def test_reused_command_id_different_payload_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    command_id = uuid.uuid4()
    _transplant(
        db_session, tenant, farm, user, s["batch"], [_simple_source(s["source_assignment_ids"][0])],
        [_simple_destination(s["destination_carriers"][0].id)],
        [_simple_allocation(s["source_assignment_ids"][0], s["destination_carriers"][0].id)],
        client_command_id=command_id,
    )
    with pytest.raises(TransplantCommandReusedWithDifferentPayloadError):
        _transplant(
            db_session, tenant, farm, user, s["batch"], [_simple_source(s["source_assignment_ids"][1])],
            [_simple_destination(s["destination_carriers"][1].id)],
            [_simple_allocation(s["source_assignment_ids"][1], s["destination_carriers"][1].id)],
            client_command_id=command_id,
        )


@pytest.mark.integration
def test_retry_after_stage_progression_returns_original_event(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    command_id = uuid.uuid4()
    effective_time = _now()
    source_lines = [_simple_source(s["source_assignment_ids"][0])]
    destination_lines = [_simple_destination(s["destination_carriers"][0].id)]
    allocations = [_simple_allocation(s["source_assignment_ids"][0], s["destination_carriers"][0].id)]
    first = _transplant(
        db_session, tenant, farm, user, s["batch"], source_lines, destination_lines, allocations,
        client_command_id=command_id, effective_time=effective_time,
    )
    crop_batch_service.transition_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), configured_transition_id=s["transitions"]["t2"].id, effective_time=_now(),
        reason=None,
    )
    retry = _transplant(
        db_session, tenant, farm, user, s["batch"], source_lines, destination_lines, allocations,
        client_command_id=command_id, effective_time=effective_time,
    )
    assert retry.id == first.id


# --- Direct-SQL immutability ---------------------------------------------------------


@pytest.mark.integration
def test_transplant_event_direct_sql_update_and_delete_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    event = _transplant(
        db_session, tenant, farm, user, s["batch"], [_simple_source(s["source_assignment_ids"][0])],
        [_simple_destination(s["destination_carriers"][0].id)],
        [_simple_allocation(s["source_assignment_ids"][0], s["destination_carriers"][0].id)],
    )
    with pytest.raises(DBAPIError):
        db_session.execute(text("UPDATE transplant_events SET note = 'x' WHERE id = :id"), {"id": event.id})
        db_session.flush()
    db_session.rollback()
    with pytest.raises(DBAPIError):
        db_session.execute(text("DELETE FROM transplant_events WHERE id = :id"), {"id": event.id})
        db_session.flush()
    db_session.rollback()


@pytest.mark.integration
def test_batch_carrier_assignment_cannot_reopen(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    _transplant(
        db_session, tenant, farm, user, s["batch"], [_simple_source(s["source_assignment_ids"][0])],
        [_simple_destination(s["destination_carriers"][0].id)],
        [_simple_allocation(s["source_assignment_ids"][0], s["destination_carriers"][0].id)],
    )
    with pytest.raises(DBAPIError):
        db_session.execute(
            text("UPDATE batch_carrier_assignments SET released_effective_time = NULL WHERE id = :id"),
            {"id": s["source_assignment_ids"][0]},
        )
        db_session.flush()
    db_session.rollback()


# --- Cross-tenant --------------------------------------------------------------------


@pytest.mark.integration
def test_cross_tenant_transplant_rejected(db_session, active_context_with_farm) -> None:
    from app.services import membership_service, tenant_service, user_service
    from app.services.errors import FarmNotFoundError

    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)

    tenant_b = tenant_service.create_tenant(db_session, code="transplant-tenant-b", name="Tenant B")
    user_b = user_service.create_user(
        db_session, oidc_issuer="iss", oidc_subject="transplant-b", email="transplantb@example.com",
        display_name="B",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_b.id, user_id=user_b.id, role_code="tenant_admin", actor_user_id=None
    )
    with pytest.raises(FarmNotFoundError):
        _transplant(
            db_session, tenant_b, farm, user_b, s["batch"], [_simple_source(s["source_assignment_ids"][0])],
            [_simple_destination(s["destination_carriers"][0].id)],
            [_simple_allocation(s["source_assignment_ids"][0], s["destination_carriers"][0].id)],
        )


# --- API ------------------------------------------------------------------------


@pytest.mark.integration
def test_transplant_api_smoke(client, active_context_with_farm, db_session) -> None:
    tenant, user, headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    db_session.commit()

    resp = client.post(
        f"/farms/{farm.id}/crop-batches/{s['batch'].id}/transplants", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": datetime.now(timezone.utc).isoformat(),
            "source_lines": [
                {"source_assignment_id": str(aid), "source_plant_count": 200, "discarded_plant_count": 0}
                for aid in s["source_assignment_ids"]
            ],
            "destination_lines": [
                {"destination_carrier_id": str(c.id), "assigned_plant_count": 200}
                for c in s["destination_carriers"]
            ],
            "allocations": [
                {
                    "source_assignment_id": str(aid), "destination_carrier_id": str(c.id),
                    "allocated_plant_count": 200,
                }
                for aid, c in zip(s["source_assignment_ids"], s["destination_carriers"])
            ],
        },
    )
    assert resp.status_code == 201
    event = resp.json()
    assert len(event["source_lines"]) == 4
    assert len(event["destination_lines"]) == 4
    assert len(event["allocations"]) == 4
    assert event["total_source_plant_count"] == 800
    assert event["total_destination_plant_count"] == 800
    assert event["total_discarded_plant_count"] == 0

    list_resp = client.get(f"/farms/{farm.id}/crop-batches/{s['batch'].id}/transplants", headers=headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    get_resp = client.get(
        f"/farms/{farm.id}/crop-batches/{s['batch'].id}/transplants/{event['id']}", headers=headers
    )
    assert get_resp.status_code == 200


@pytest.mark.integration
def test_transplant_routes_exactly_three_no_mutation_and_no_lineage_route() -> None:
    from app.main import app

    schema = app.openapi()
    transplant_paths = {p: ops for p, ops in schema["paths"].items() if "transplant" in p}
    ops_count = sum(len(ops) for ops in transplant_paths.values())
    assert ops_count == 3, transplant_paths
    methods = {method.upper() for ops in transplant_paths.values() for method in ops}
    assert methods == {"GET", "POST"}
    assert not any("lineage" in p for p in transplant_paths)
