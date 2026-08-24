import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.models.audit_event import AuditEvent
from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.carrier import Carrier
from app.models.seedling_source_checkpoint import SeedlingSourceCheckpoint
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
    carrier_specification_service,
    crop_batch_service,
    transplant_service,
)
from app.services.errors import (
    CarrierNotFoundError,
    DestinationCarrierAlreadyAssignedError,
    InvalidTransplantEffectiveTimeError,
    SourceAssignmentAlreadyReleasedError,
    TransplantCapacityExceededError,
    TransplantCommandReusedWithDifferentPayloadError,
    TransplantValidationError,
    UnsupportedTransplantSourceCarrierTypeError,
)
from tests._transplant_scenario import build_transplant_ready_scenario, now as _now

# --- Application-level (Pydantic) validation — no DB required ---


def _source(**overrides):
    defaults = dict(source_assignment_id=uuid.uuid4())
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


def test_source_line_other_loss_requires_note() -> None:
    with pytest.raises(ValueError):
        _source(other_loss_count=3, other_loss_note=None)


def test_source_line_other_loss_zero_note_not_required() -> None:
    line = _source(other_loss_count=0)
    assert line.other_loss_note is None


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


def _build_scenario(
    db_session, tenant, user, farm, *, suffix=None, transplanting_required_type="cultivation_plate", tray_count=4,
):
    return build_transplant_ready_scenario(
        db_session, tenant, user, farm, suffix=suffix, tray_count=tray_count, normal=200, abnormal=0,
        transplanting_required_type=transplanting_required_type,
    )


def _simple_source(assignment_id, **overrides):
    defaults = dict(
        source_assignment_id=assignment_id, transplant_damage_count=0, qc_rejection_count=0, sample_count=0,
        other_loss_count=0, other_loss_note=None, note=None,
    )
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
    event = _transplant(
        db_session, tenant, farm, user, s["batch"], source_lines, destination_lines, allocations,
        effective_time=s["entry_time"] + timedelta(hours=2),
    )

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
    checkpoint_count = db_session.execute(
        select(func.count()).select_from(SeedlingSourceCheckpoint).where(
            SeedlingSourceCheckpoint.batch_id == s["batch"].id
        )
    ).scalar_one()
    assert checkpoint_count == 4
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
    event = _transplant(
        db_session, tenant, farm, user, s["batch"], source_lines, destination_lines, allocations,
        effective_time=s["entry_time"] + timedelta(hours=2),
    )

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
        _simple_source(used),
        _simple_source(discarded, transplant_damage_count=200),
    ]
    destination_lines = [_simple_destination(s["destination_carriers"][0].id)]
    allocations = [_simple_allocation(used, s["destination_carriers"][0].id, 200)]
    event = _transplant(
        db_session, tenant, farm, user, s["batch"], source_lines, destination_lines, allocations,
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    assert event.id is not None
    discarded_assignment = db_session.get(BatchCarrierAssignment, discarded)
    assert discarded_assignment.released_effective_time == event.effective_time


@pytest.mark.integration
def test_source_with_ineligible_carrier_type_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    source_lines = [_simple_source(aid) for aid in s["source_assignment_ids"]]
    destination_lines = [_simple_destination(c.id) for c in s["destination_carriers"]]
    allocations = [
        _simple_allocation(aid, c.id) for aid, c in zip(s["source_assignment_ids"], s["destination_carriers"])
    ]
    _transplant(
        db_session, tenant, farm, user, s["batch"], source_lines, destination_lines, allocations,
        effective_time=s["entry_time"] + timedelta(hours=2),
    )

    # The destination assignment just opened by that transplant sits on a
    # generic `cultivation_plate` carrier -- not one of the two carrier
    # types NURSERY-OPS-005A's unified source-authority resolver treats as
    # eligible Transplant sources (`seed_tray`, `nursery_cultivation_plate`).
    # It must be rejected as categorically unsupported, distinct from (and
    # checked before) any biological-population-authority check.
    destination_assignment_id = db_session.execute(
        select(BatchCarrierAssignment.id).where(
            BatchCarrierAssignment.carrier_id == s["destination_carriers"][0].id
        )
    ).scalar_one()
    fresh_destination = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        carrier_type_code="cultivation_plate", code="CP-FRESH-0001", issued_date=None,
    )
    with pytest.raises(UnsupportedTransplantSourceCarrierTypeError):
        _transplant(
            db_session, tenant, farm, user, s["batch"],
            [_simple_source(destination_assignment_id)], [_simple_destination(fresh_destination.id)],
            [_simple_allocation(destination_assignment_id, fresh_destination.id)],
            effective_time=s["entry_time"] + timedelta(hours=3),
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
    _transplant(
        db_session, tenant, farm, user, s["batch"], source_lines, destination_lines, allocations,
        effective_time=s["entry_time"] + timedelta(hours=2),
    )

    fresh_destination = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        carrier_type_code="cultivation_plate", code="CP-FRESH-RELEASED", issued_date=None,
    )
    with pytest.raises(SourceAssignmentAlreadyReleasedError):
        _transplant(
            db_session, tenant, farm, user, s["batch"],
            [_simple_source(s["source_assignment_ids"][0])], [_simple_destination(fresh_destination.id)],
            [_simple_allocation(s["source_assignment_ids"][0], fresh_destination.id)],
            effective_time=s["entry_time"] + timedelta(hours=3),
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
    _transplant(
        db_session, tenant, farm, user, s["batch"], source_lines, destination_lines, allocations,
        effective_time=s["entry_time"] + timedelta(hours=2),
    )

    s2 = _build_scenario(db_session, tenant, user, farm, suffix="reuse2")
    with pytest.raises(DestinationCarrierAlreadyAssignedError):
        _transplant(
            db_session, tenant, farm, user, s2["batch"],
            [_simple_source(s2["source_assignment_ids"][0])], [_simple_destination(s["destination_carriers"][0].id)],
            [_simple_allocation(s2["source_assignment_ids"][0], s["destination_carriers"][0].id)],
            effective_time=s2["entry_time"] + timedelta(hours=2),
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
            effective_time=s["entry_time"] + timedelta(hours=2),
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
            effective_time=s["entry_time"] + timedelta(hours=2),
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
            effective_time=s["entry_time"] + timedelta(hours=2),
        )


@pytest.mark.integration
def test_missing_transplanting_stage_configuration_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, transplanting_required_type=None)
    fresh_destination = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        carrier_type_code="cultivation_plate", code="CP-ANY-0001", issued_date=None,
    )
    with pytest.raises(TransplantValidationError):
        _transplant(
            db_session, tenant, farm, user, s["batch"],
            [_simple_source(s["source_assignment_ids"][0])], [_simple_destination(fresh_destination.id)],
            [_simple_allocation(s["source_assignment_ids"][0], fresh_destination.id)],
            effective_time=s["entry_time"] + timedelta(hours=2),
        )


@pytest.mark.integration
def test_command_in_non_transplanting_stage_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    # WORKFLOW-INTEGRITY-001: a single Tray, fully resolved by the one
    # Transplant below, so leaving TRANSPLANTING is legitimately eligible --
    # this test is about the destination stage-category check, not about
    # unresolved Seedling remainder.
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(s["source_assignment_ids"][0])], [_simple_destination(s["destination_carriers"][0].id)],
        [_simple_allocation(s["source_assignment_ids"][0], s["destination_carriers"][0].id)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    # Advance past TRANSPLANTING into GROWING.
    crop_batch_service.transition_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), configured_transition_id=s["transitions"]["t2"].id,
        effective_time=s["entry_time"] + timedelta(hours=2), reason=None,
    )
    with pytest.raises(TransplantValidationError):
        _transplant(
            db_session, tenant, farm, user, s["batch"],
            [_simple_source(s["source_assignment_ids"][0])], [_simple_destination(s["destination_carriers"][0].id)],
            [_simple_allocation(s["source_assignment_ids"][0], s["destination_carriers"][0].id)],
            effective_time=s["entry_time"] + timedelta(hours=3),
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
def test_sown_site_count_never_consulted_for_modern_source(db_session, active_context_with_farm) -> None:
    """NURSERY-OPS-004A section 61: the modern checkpoint transplant flow
    must succeed regardless of the source Tray's own SowingEventLine
    sown_site_count, proving it never consults that field and never
    substitutes seed_count for it. CARRIER-CONFIG-001B: sown_site_count is
    now always recorded (non-NULL) for a genuinely new Sowing command --
    this is in fact a STRONGER proof of the original claim than the
    pre-001B NULL case this test used to exercise: transplant succeeds
    identically whether sown_site_count is populated or NULL, because it
    is never read either way."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    sown_count = db_session.execute(
        text("SELECT sown_site_count FROM sowing_event_lines WHERE batch_carrier_assignment_id = :aid"),
        {"aid": s["source_assignment_ids"][0]},
    ).scalar_one()
    assert sown_count == 200
    event = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(s["source_assignment_ids"][0])], [_simple_destination(s["destination_carriers"][0].id)],
        [_simple_allocation(s["source_assignment_ids"][0], s["destination_carriers"][0].id)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    assert event.id is not None


@pytest.mark.integration
def test_source_reconciliation_mismatch_rejected(db_session, active_context_with_farm) -> None:
    """Allocation + loss exceeding the authoritative source availability
    (200) must be rejected -- remainder would go negative."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    with pytest.raises(TransplantValidationError):
        _transplant(
            db_session, tenant, farm, user, s["batch"],
            [_simple_source(s["source_assignment_ids"][0], transplant_damage_count=10)],
            [_simple_destination(s["destination_carriers"][0].id, assigned_plant_count=200)],
            [_simple_allocation(s["source_assignment_ids"][0], s["destination_carriers"][0].id, 200)],
            effective_time=s["entry_time"] + timedelta(hours=2),
        )


@pytest.mark.integration
def test_partial_allocation_with_remainder_succeeds(db_session, active_context_with_farm) -> None:
    """NURSERY-OPS-004A: unlike the pre-checkpoint model (where every
    source line had to be fully consumed by destination+discarded),
    allocating less than the full source_available_before is now legitimate
    -- the unallocated remainder is server-derived and checkpointed, not an
    error."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    event = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(s["source_assignment_ids"][0])],
        [_simple_destination(s["destination_carriers"][0].id, assigned_plant_count=150)],
        [_simple_allocation(s["source_assignment_ids"][0], s["destination_carriers"][0].id, 150)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    read = transplant_service.get_transplant_event(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=s["batch"].id, transplant_event_id=event.id
    )
    assert read.source_lines[0].remainder_after == 50
    assignment = db_session.get(BatchCarrierAssignment, s["source_assignment_ids"][0])
    assert assignment.released_effective_time is None


@pytest.mark.integration
def test_destination_line_allocation_mismatch_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    with pytest.raises(TransplantValidationError):
        _transplant(
            db_session, tenant, farm, user, s["batch"],
            [_simple_source(s["source_assignment_ids"][0])],
            [_simple_destination(s["destination_carriers"][0].id, assigned_plant_count=200)],
            [_simple_allocation(s["source_assignment_ids"][0], s["destination_carriers"][0].id, 150)],
            effective_time=s["entry_time"] + timedelta(hours=2),
        )


# --- Idempotency --------------------------------------------------------------------


@pytest.mark.integration
def test_exact_transplant_retry_returns_original_event(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    command_id = uuid.uuid4()
    effective_time = s["entry_time"] + timedelta(hours=2)
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
        client_command_id=command_id, effective_time=s["entry_time"] + timedelta(hours=2),
    )
    with pytest.raises(TransplantCommandReusedWithDifferentPayloadError):
        _transplant(
            db_session, tenant, farm, user, s["batch"], [_simple_source(s["source_assignment_ids"][1])],
            [_simple_destination(s["destination_carriers"][1].id)],
            [_simple_allocation(s["source_assignment_ids"][1], s["destination_carriers"][1].id)],
            client_command_id=command_id, effective_time=s["entry_time"] + timedelta(hours=2),
        )


@pytest.mark.integration
def test_retry_after_stage_progression_returns_original_event(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    # WORKFLOW-INTEGRITY-001: a single, fully-resolved Tray -- the batch
    # must be legitimately eligible to leave TRANSPLANTING for this test's
    # own concern (idempotent retry after stage progression) to be reachable.
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    command_id = uuid.uuid4()
    effective_time = s["entry_time"] + timedelta(hours=2)
    source_lines = [_simple_source(s["source_assignment_ids"][0])]
    destination_lines = [_simple_destination(s["destination_carriers"][0].id)]
    allocations = [_simple_allocation(s["source_assignment_ids"][0], s["destination_carriers"][0].id)]
    first = _transplant(
        db_session, tenant, farm, user, s["batch"], source_lines, destination_lines, allocations,
        client_command_id=command_id, effective_time=effective_time,
    )
    crop_batch_service.transition_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), configured_transition_id=s["transitions"]["t2"].id,
        effective_time=effective_time + timedelta(hours=1), reason=None,
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
        effective_time=s["entry_time"] + timedelta(hours=2),
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
        effective_time=s["entry_time"] + timedelta(hours=2),
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
            effective_time=s["entry_time"] + timedelta(hours=2),
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
            "client_command_id": str(uuid.uuid4()),
            "effective_time": (s["entry_time"] + timedelta(hours=2)).isoformat(),
            "source_lines": [
                {
                    "source_assignment_id": str(aid), "transplant_damage_count": 0, "qc_rejection_count": 0,
                    "sample_count": 0, "other_loss_count": 0,
                }
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
    assert resp.status_code == 201, resp.text
    event = resp.json()
    assert len(event["source_lines"]) == 4
    assert len(event["destination_lines"]) == 4
    assert len(event["allocations"]) == 4
    assert event["total_source_available_before"] == 800
    assert event["total_destination_plant_count"] == 800
    assert event["total_discarded_plant_count"] == 0
    assert event["total_remainder_after"] == 0

    list_resp = client.get(f"/farms/{farm.id}/crop-batches/{s['batch'].id}/transplants", headers=headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    get_resp = client.get(
        f"/farms/{farm.id}/crop-batches/{s['batch'].id}/transplants/{event['id']}", headers=headers
    )
    assert get_resp.status_code == 200


@pytest.mark.integration
def test_transplant_routes_exactly_four_no_lineage_route() -> None:
    """NURSERY-OPS-004B.1 added a genuinely new, deliberately-scoped
    composite route (`/intersalads-transplants`) -- this guard scopes
    itself to the plain generic `/transplants` surface specifically (by
    exact path, not merely the "transplant" substring). TRANSPLANT-
    CORRECTION-001 added a fourth, equally deliberate route
    (`/transplants/{event_id}/correct`) -- this guard's own name/count was
    updated to match rather than broadened to accept an arbitrary count, so
    it keeps proving its original intent (no ACCIDENTAL extra mutation/
    lineage route) without being broken by either intentional addition."""
    from app.main import app

    schema = app.openapi()
    transplant_paths = {
        p: ops for p, ops in schema["paths"].items()
        if "transplant" in p and "intersalads-transplants" not in p
    }
    ops_count = sum(len(ops) for ops in transplant_paths.values())
    assert ops_count == 4, transplant_paths
    methods = {method.upper() for ops in transplant_paths.values() for method in ops}
    assert methods == {"GET", "POST"}
    assert not any("lineage" in p for p in transplant_paths)


@pytest.mark.integration
def test_intersalads_transplant_route_exactly_one_post_only(active_context_with_farm) -> None:
    """Section 15/24: no correction/void route, no GET/list route -- the
    composite command exposes exactly one POST, nothing else, in this
    ticket."""
    from app.main import app

    schema = app.openapi()
    composite_paths = {p: ops for p, ops in schema["paths"].items() if "intersalads-transplants" in p}
    assert len(composite_paths) == 1
    ops = next(iter(composite_paths.values()))
    assert set(ops) == {"post"}


# =====================================================================
# NURSERY-OPS-004B.1: destination biological capacity (shared core --
# reachable from BOTH the plain /transplants endpoint used here AND the
# InterSalads composite command; test_intersalads_transplant.py adds only
# the handful of composite-specific proofs, not a duplicate matrix)
# =====================================================================


def _register_nursery_plate_spec(db_session, tenant, user, *, biological_position_count=200, suffix=None):
    suffix = suffix or uuid.uuid4().hex[:8]
    return carrier_specification_service.register_carrier_specification(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, carrier_type_code="nursery_cultivation_plate",
        code=f"CAP-{suffix}", name="Capacity Test Plate", length_mm=500, width_mm=300, height_mm=60,
        biological_position_count=biological_position_count,
    )


@pytest.mark.integration
def test_assigned_plant_count_below_capacity_succeeds(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    spec = _register_nursery_plate_spec(db_session, tenant, user, biological_position_count=200)
    s = build_transplant_ready_scenario(
        db_session, tenant, user, farm, tray_count=1, transplanting_required_type="nursery_cultivation_plate",
        destination_specification_id=spec.id,
    )
    aid = s["source_assignment_ids"][0]
    plate = s["destination_carriers"][0]
    event = _transplant(
        db_session, tenant, farm, user, s["batch"], [_simple_source(aid)], [_simple_destination(plate.id, assigned_plant_count=150)],
        [_simple_allocation(aid, plate.id, 150)], effective_time=s["entry_time"] + timedelta(hours=2),
    )
    assert db_session.execute(
        select(TransplantDestinationLine.assigned_plant_count).where(
            TransplantDestinationLine.transplant_event_id == event.id
        )
    ).scalar_one() == 150


@pytest.mark.integration
def test_assigned_plant_count_at_exact_capacity_succeeds(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    spec = _register_nursery_plate_spec(db_session, tenant, user, biological_position_count=200)
    s = build_transplant_ready_scenario(
        db_session, tenant, user, farm, tray_count=1, transplanting_required_type="nursery_cultivation_plate",
        destination_specification_id=spec.id,
    )
    aid = s["source_assignment_ids"][0]
    plate = s["destination_carriers"][0]
    event = _transplant(
        db_session, tenant, farm, user, s["batch"], [_simple_source(aid)], [_simple_destination(plate.id, assigned_plant_count=200)],
        [_simple_allocation(aid, plate.id, 200)], effective_time=s["entry_time"] + timedelta(hours=2),
    )
    assert db_session.execute(
        select(TransplantDestinationLine.assigned_plant_count).where(
            TransplantDestinationLine.transplant_event_id == event.id
        )
    ).scalar_one() == 200


@pytest.mark.integration
def test_assigned_plant_count_above_capacity_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    spec = _register_nursery_plate_spec(db_session, tenant, user, biological_position_count=200)
    s = build_transplant_ready_scenario(
        db_session, tenant, user, farm, tray_count=1, transplanting_required_type="nursery_cultivation_plate",
        destination_specification_id=spec.id,
    )
    aid = s["source_assignment_ids"][0]
    plate = s["destination_carriers"][0]
    with pytest.raises(TransplantCapacityExceededError):
        _transplant(
            db_session, tenant, farm, user, s["batch"], [_simple_source(aid)],
            [_simple_destination(plate.id, assigned_plant_count=201)], [_simple_allocation(aid, plate.id, 201)],
            effective_time=s["entry_time"] + timedelta(hours=2),
        )


@pytest.mark.integration
def test_required_specification_destination_with_no_specification_rejected_safely(
    db_session, active_context_with_farm
) -> None:
    """nursery_cultivation_plate has required_specification=True since its
    own inception -- a Carrier with no specification_id is structurally
    unreachable via `carrier_service.register_carrier` (it refuses to
    create one), so this historical-shaped state must be constructed via
    raw SQL, matching the established pattern for other structurally-
    frozen legacy scenarios."""
    tenant, user, _headers, farm = active_context_with_farm
    # `destination_specification_id` must be a valid spec so the scenario
    # builder's own destination-carrier auto-registration (unused by this
    # test) doesn't itself fail -- the actual carrier under test is a
    # separate, deliberately spec-less raw-SQL row constructed below.
    throwaway_spec = _register_nursery_plate_spec(db_session, tenant, user, biological_position_count=200)
    s = build_transplant_ready_scenario(
        db_session, tenant, user, farm, tray_count=1, transplanting_required_type="nursery_cultivation_plate",
        destination_specification_id=throwaway_spec.id,
    )
    plate_type_id = db_session.execute(
        text("SELECT id FROM carrier_types WHERE code = 'nursery_cultivation_plate'")
    ).scalar_one()
    carrier_id = uuid.uuid4()
    db_session.execute(
        text(
            "INSERT INTO carriers (id, tenant_id, farm_id, carrier_type_id, code, status, specification_id, "
            "issued_date, retired_date) VALUES (:id, :tid, :fid, :ctid, :code, 'active', NULL, NULL, NULL)"
        ),
        {"id": carrier_id, "tid": tenant.id, "fid": farm.id, "ctid": plate_type_id, "code": f"NOSPEC-{uuid.uuid4().hex[:8]}"},
    )
    plate = db_session.get(Carrier, carrier_id)
    aid = s["source_assignment_ids"][0]
    with pytest.raises(TransplantValidationError):
        _transplant(
            db_session, tenant, farm, user, s["batch"], [_simple_source(aid)],
            [_simple_destination(plate.id, assigned_plant_count=100)], [_simple_allocation(aid, plate.id, 100)],
            effective_time=s["entry_time"] + timedelta(hours=2),
        )


@pytest.mark.integration
def test_non_required_specification_type_with_capacity_still_enforces_it(db_session, active_context_with_farm) -> None:
    """Section 4: 'If a Carrier Type does NOT require a specification: if a
    specification/capacity exists, use it.' The generic `cultivation_plate`
    type does not require one, but a Carrier that voluntarily references a
    specification with a real capacity is still capacity-checked."""
    tenant, user, _headers, farm = active_context_with_farm
    spec = carrier_specification_service.register_carrier_specification(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, carrier_type_code="cultivation_plate",
        code=f"GEN-{uuid.uuid4().hex[:8]}", name="Generic Plate With Capacity", length_mm=400, width_mm=300,
        height_mm=None, biological_position_count=100,
    )
    s = build_transplant_ready_scenario(
        db_session, tenant, user, farm, tray_count=1, transplanting_required_type="cultivation_plate",
        destination_specification_id=spec.id,
    )
    aid = s["source_assignment_ids"][0]
    plate = s["destination_carriers"][0]
    with pytest.raises(TransplantCapacityExceededError):
        _transplant(
            db_session, tenant, farm, user, s["batch"], [_simple_source(aid)],
            [_simple_destination(plate.id, assigned_plant_count=101)], [_simple_allocation(aid, plate.id, 101)],
            effective_time=s["entry_time"] + timedelta(hours=2),
        )


@pytest.mark.integration
def test_non_required_specification_type_without_capacity_not_invented(db_session, active_context_with_farm) -> None:
    """Section 4: 'if no biological-position capacity exists, do not invent
    one.' The default `cultivation_plate` scenario carriers have no
    specification at all -- capacity must not block them (this is also
    already proven implicitly by every other passing test in this file
    using the default scenario; asserted explicitly here for the record)."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    aid = s["source_assignment_ids"][0]
    plate = s["destination_carriers"][0]
    event = _transplant(
        db_session, tenant, farm, user, s["batch"], [_simple_source(aid)],
        [_simple_destination(plate.id, assigned_plant_count=200)], [_simple_allocation(aid, plate.id, 200)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    assert db_session.execute(
        select(TransplantDestinationLine.assigned_plant_count).where(
            TransplantDestinationLine.transplant_event_id == event.id
        )
    ).scalar_one() == 200


@pytest.mark.integration
def test_direct_sql_capacity_violation_rejected_by_db_backstop(db_session, active_context_with_farm) -> None:
    """Migration b7e2f4a9c1d6's `enforce_transplant_destination_capacity`
    trigger -- unreachable via the normal application path (the service
    check above already blocks it before any insert), proven here exactly
    like DOMAIN-FARM-002's own capacity trigger test precedent: a direct,
    fully self-consistent INSERT bypassing the service layer entirely.
    `DEFERRABLE INITIALLY DEFERRED` triggers fire at real transaction
    COMMIT, not at savepoint release or flush -- `SET CONSTRAINTS ALL
    IMMEDIATE` forces the check to run inside this nested savepoint so the
    test can observe it without ever committing the outer transaction."""
    tenant, user, _headers, farm = active_context_with_farm
    spec = _register_nursery_plate_spec(db_session, tenant, user, biological_position_count=50)
    s = build_transplant_ready_scenario(
        db_session, tenant, user, farm, tray_count=1, transplanting_required_type="nursery_cultivation_plate",
        destination_specification_id=spec.id,
    )
    aid = s["source_assignment_ids"][0]
    source_carrier_id = s["source_carriers"][0].id
    plate = s["destination_carriers"][0]
    active_run_id = db_session.execute(
        text("SELECT id FROM batch_stage_runs WHERE batch_id = :bid AND exited_effective_time IS NULL"),
        {"bid": s["batch"].id},
    ).scalar_one()
    effective_time = s["entry_time"] + timedelta(hours=2)

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            event_id, source_line_id, dest_assignment_id, dest_line_id = (
                uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            )
            db_session.execute(
                text(
                    "INSERT INTO transplant_events (id, tenant_id, farm_id, batch_id, "
                    "active_batch_stage_run_id, effective_time, actor_user_id, client_command_id, "
                    "request_fingerprint, note) VALUES (:id, :tid, :fid, :bid, :run_id, :et, :uid, "
                    "gen_random_uuid(), 'direct-sql-test', NULL)"
                ),
                {
                    "id": event_id, "tid": tenant.id, "fid": farm.id, "bid": s["batch"].id, "run_id": active_run_id,
                    "et": effective_time, "uid": user.id,
                },
            )
            db_session.execute(
                text(
                    "INSERT INTO transplant_source_lines (id, tenant_id, farm_id, transplant_event_id, "
                    "source_batch_carrier_assignment_id, source_carrier_id, source_plant_count, "
                    "discarded_plant_count, transplant_damage_count, qc_rejection_count, sample_count, "
                    "other_loss_count) VALUES (:id, :tid, :fid, :eid, :aid, :cid, 999, 0, 0, 0, 0, 0)"
                ),
                {
                    "id": source_line_id, "tid": tenant.id, "fid": farm.id, "eid": event_id, "aid": aid,
                    "cid": source_carrier_id,
                },
            )
            db_session.execute(
                text(
                    "INSERT INTO batch_carrier_assignments (id, tenant_id, farm_id, batch_id, carrier_id, "
                    "batch_stage_run_id, assigned_effective_time, opening_transplant_event_id, actor_user_id) "
                    "VALUES (:id, :tid, :fid, :bid, :cid, :run_id, :et, :eid, :uid)"
                ),
                {
                    "id": dest_assignment_id, "tid": tenant.id, "fid": farm.id, "bid": s["batch"].id,
                    "cid": plate.id, "run_id": active_run_id, "et": effective_time, "eid": event_id,
                    "uid": user.id,
                },
            )
            db_session.execute(
                text(
                    "INSERT INTO transplant_destination_lines (id, tenant_id, farm_id, transplant_event_id, "
                    "destination_batch_carrier_assignment_id, destination_carrier_id, assigned_plant_count) "
                    "VALUES (:id, :tid, :fid, :eid, :daid, :cid, 999)"
                ),
                {
                    "id": dest_line_id, "tid": tenant.id, "fid": farm.id, "eid": event_id,
                    "daid": dest_assignment_id, "cid": plate.id,
                },
            )
            db_session.execute(
                text(
                    "INSERT INTO transplant_allocations (id, tenant_id, farm_id, transplant_event_id, "
                    "source_line_id, destination_line_id, allocated_plant_count) "
                    "VALUES (gen_random_uuid(), :tid, :fid, :eid, :sid, :did, 999)"
                ),
                {"tid": tenant.id, "fid": farm.id, "eid": event_id, "sid": source_line_id, "did": dest_line_id},
            )
            db_session.execute(
                text(
                    "UPDATE batch_carrier_assignments SET released_effective_time = :et, "
                    "released_by_transplant_event_id = :eid WHERE id = :aid"
                ),
                {"et": effective_time, "eid": event_id, "aid": aid},
            )
            db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


@pytest.mark.integration
def test_direct_sql_update_of_committed_destination_line_rejected(db_session, active_context_with_farm) -> None:
    """Pre-commit audit section 5/6: the DATABASE truth, not documentation
    or service code -- `transplant_destination_lines_no_update`
    (BEFORE UPDATE, unconditional, immediate -- not deferred, established by
    the original CMP-011 migration `f3a8c2e1b975`, shared `reject_append_
    only_mutation()` function) rejects ANY UPDATE to a committed destination
    line, including `assigned_plant_count`, before the row-level values are
    even compared -- this is Outcome 1 from the audit's required matrix: the
    existing immutable-history protection already covers UPDATE, so the new
    capacity trigger's `AFTER INSERT`-only scope is sufficient; it does not
    also need to fire on UPDATE."""
    tenant, user, _headers, farm = active_context_with_farm
    spec = _register_nursery_plate_spec(db_session, tenant, user, biological_position_count=50)
    s = build_transplant_ready_scenario(
        db_session, tenant, user, farm, tray_count=1, transplanting_required_type="nursery_cultivation_plate",
        destination_specification_id=spec.id,
    )
    plate = s["destination_carriers"][0]
    # Case A: a valid, committed line within capacity.
    event = transplant_service.record_transplant(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), effective_time=s["entry_time"] + timedelta(hours=2), note=None,
        source_lines=[_simple_source(s["source_assignment_ids"][0])],
        destination_lines=[_simple_destination(plate.id, assigned_plant_count=40)],
        allocations=[_simple_allocation(s["source_assignment_ids"][0], plate.id, 40)],
    )
    # Case B: direct SQL UPDATE attempting to push assigned_plant_count
    # above the Plate's known capacity (50) -- must be rejected outright,
    # by the pre-existing immutability trigger, not by the capacity trigger.
    with pytest.raises(DBAPIError, match="append-only|append_only|cannot be updated|immutable") as exc_info:
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "UPDATE transplant_destination_lines SET assigned_plant_count = 999 "
                    "WHERE transplant_event_id = :eid"
                ),
                {"eid": event.id},
            )
    # Confirm committed state was never mutated (Outcome 3 -- the
    # unacceptable one -- did not occur).
    unchanged = db_session.execute(
        select(TransplantDestinationLine.assigned_plant_count).where(
            TransplantDestinationLine.transplant_event_id == event.id
        )
    ).scalar_one()
    assert unchanged == 40


@pytest.mark.integration
def test_db_backstop_rejects_structurally_corrupt_null_specification_id(db_session, active_context_with_farm) -> None:
    """Pre-commit audit section 7: a `nursery_cultivation_plate` Carrier
    with a raw-SQL-corrupted `specification_id IS NULL` (structurally
    unreachable via the service layer, see
    `test_required_specification_destination_with_no_specification_rejected_safely`
    above, which already proves the SERVICE rejects it) must ALSO be
    rejected by the DB capacity trigger itself if that service check were
    ever bypassed -- proven here via the same `SET CONSTRAINTS ALL
    IMMEDIATE` technique, building a fully self-consistent fake event
    exactly like `test_direct_sql_capacity_violation_rejected_by_db_backstop`
    above, this time against a NULL-specification destination Carrier."""
    tenant, user, _headers, farm = active_context_with_farm
    throwaway_spec = _register_nursery_plate_spec(db_session, tenant, user, biological_position_count=200)
    s = build_transplant_ready_scenario(
        db_session, tenant, user, farm, tray_count=1, transplanting_required_type="nursery_cultivation_plate",
        destination_specification_id=throwaway_spec.id,
    )
    plate_type_id = db_session.execute(
        text("SELECT id FROM carrier_types WHERE code = 'nursery_cultivation_plate'")
    ).scalar_one()
    corrupt_carrier_id = uuid.uuid4()
    db_session.execute(
        text(
            "INSERT INTO carriers (id, tenant_id, farm_id, carrier_type_id, code, status, specification_id, "
            "issued_date, retired_date) VALUES (:id, :tid, :fid, :ctid, :code, 'active', NULL, NULL, NULL)"
        ),
        {"id": corrupt_carrier_id, "tid": tenant.id, "fid": farm.id, "ctid": plate_type_id, "code": f"CORRUPT-{uuid.uuid4().hex[:8]}"},
    )
    aid = s["source_assignment_ids"][0]
    source_carrier_id = s["source_carriers"][0].id
    active_run_id = db_session.execute(
        text("SELECT id FROM batch_stage_runs WHERE batch_id = :bid AND exited_effective_time IS NULL"),
        {"bid": s["batch"].id},
    ).scalar_one()
    effective_time = s["entry_time"] + timedelta(hours=2)

    with pytest.raises(DBAPIError, match="requires a specification"):
        with db_session.begin_nested():
            event_id, source_line_id, dest_assignment_id, dest_line_id = (
                uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            )
            db_session.execute(
                text(
                    "INSERT INTO transplant_events (id, tenant_id, farm_id, batch_id, "
                    "active_batch_stage_run_id, effective_time, actor_user_id, client_command_id, "
                    "request_fingerprint, note) VALUES (:id, :tid, :fid, :bid, :run_id, :et, :uid, "
                    "gen_random_uuid(), 'direct-sql-test-2', NULL)"
                ),
                {
                    "id": event_id, "tid": tenant.id, "fid": farm.id, "bid": s["batch"].id, "run_id": active_run_id,
                    "et": effective_time, "uid": user.id,
                },
            )
            db_session.execute(
                text(
                    "INSERT INTO transplant_source_lines (id, tenant_id, farm_id, transplant_event_id, "
                    "source_batch_carrier_assignment_id, source_carrier_id, source_plant_count, "
                    "discarded_plant_count, transplant_damage_count, qc_rejection_count, sample_count, "
                    "other_loss_count) VALUES (:id, :tid, :fid, :eid, :aid, :cid, 200, 0, 0, 0, 0, 0)"
                ),
                {
                    "id": source_line_id, "tid": tenant.id, "fid": farm.id, "eid": event_id, "aid": aid,
                    "cid": source_carrier_id,
                },
            )
            db_session.execute(
                text(
                    "INSERT INTO batch_carrier_assignments (id, tenant_id, farm_id, batch_id, carrier_id, "
                    "batch_stage_run_id, assigned_effective_time, opening_transplant_event_id, "
                    "population_root_batch_carrier_assignment_id, actor_user_id) "
                    "VALUES (:id, :tid, :fid, :bid, :cid, :run_id, :et, :eid, :id, :uid)"
                ),
                {
                    "id": dest_assignment_id, "tid": tenant.id, "fid": farm.id, "bid": s["batch"].id,
                    "cid": corrupt_carrier_id, "run_id": active_run_id, "et": effective_time, "eid": event_id,
                    "uid": user.id,
                },
            )
            db_session.execute(
                text(
                    "INSERT INTO transplant_destination_lines (id, tenant_id, farm_id, transplant_event_id, "
                    "destination_batch_carrier_assignment_id, destination_carrier_id, assigned_plant_count) "
                    "VALUES (:id, :tid, :fid, :eid, :daid, :cid, 200)"
                ),
                {
                    "id": dest_line_id, "tid": tenant.id, "fid": farm.id, "eid": event_id,
                    "daid": dest_assignment_id, "cid": corrupt_carrier_id,
                },
            )
            db_session.execute(
                text(
                    "INSERT INTO transplant_allocations (id, tenant_id, farm_id, transplant_event_id, "
                    "source_line_id, destination_line_id, allocated_plant_count) "
                    "VALUES (gen_random_uuid(), :tid, :fid, :eid, :sid, :did, 200)"
                ),
                {"tid": tenant.id, "fid": farm.id, "eid": event_id, "sid": source_line_id, "did": dest_line_id},
            )
            seedling_entry_id = db_session.execute(
                text("SELECT id FROM seedling_entries WHERE batch_carrier_assignment_id = :aid"), {"aid": aid}
            ).scalar_one()
            db_session.execute(
                text(
                    "INSERT INTO seedling_source_checkpoints (id, tenant_id, farm_id, batch_id, "
                    "seedling_entry_id, source_batch_carrier_assignment_id, transplant_source_line_id, "
                    "previous_checkpoint_id, remainder_after, effective_time) "
                    "VALUES (gen_random_uuid(), :tid, :fid, :bid, :seid, :aid, :slid, NULL, 0, :et)"
                ),
                {
                    "tid": tenant.id, "fid": farm.id, "bid": s["batch"].id, "seid": seedling_entry_id, "aid": aid,
                    "slid": source_line_id, "et": effective_time,
                },
            )
            db_session.execute(
                text(
                    "UPDATE batch_carrier_assignments SET released_effective_time = :et, "
                    "released_by_transplant_event_id = :eid WHERE id = :aid"
                ),
                {"et": effective_time, "eid": event_id, "aid": aid},
            )
            db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


@pytest.mark.integration
def test_db_backstop_layering_null_capacity_on_unreferenced_specification(db_session, active_context_with_farm) -> None:
    """Pre-commit audit section 7, second half: a genuinely NEW
    `carrier_specifications` row for `nursery_cultivation_plate` with
    `biological_position_count = NULL`, raw-SQL-inserted (bypassing the
    service layer's `_require_minimum_fields_if_specification_required`,
    which is Python-only, not itself a DB constraint -- the column-level
    CHECK constraint permits NULL unconditionally). No existing Carrier/
    Specification DB constraint prevents this row from existing while
    unreferenced (the structural-freeze trigger only engages once a Carrier
    references it). Confirms the capacity trigger's own design is robust
    regardless of *how* a NULL capacity was reached -- it queries the live
    joined state at insert time, not a separately-enforced invariant."""
    tenant, user, _headers, farm = active_context_with_farm
    plate_type_id = db_session.execute(
        text("SELECT id FROM carrier_types WHERE code = 'nursery_cultivation_plate'")
    ).scalar_one()
    corrupt_spec_id = uuid.uuid4()
    db_session.execute(
        text(
            "INSERT INTO carrier_specifications (id, tenant_id, carrier_type_id, code, name, "
            "biological_position_count, status) VALUES (:id, :tid, :ctid, :code, 'Corrupt Null Capacity', "
            "NULL, 'active')"
        ),
        {"id": corrupt_spec_id, "tid": tenant.id, "ctid": plate_type_id, "code": f"NULLCAP-{uuid.uuid4().hex[:8]}"},
    )
    s = build_transplant_ready_scenario(
        db_session, tenant, user, farm, tray_count=1, transplanting_required_type="nursery_cultivation_plate",
        destination_specification_id=corrupt_spec_id,
    )
    plate = s["destination_carriers"][0]
    aid = s["source_assignment_ids"][0]
    with pytest.raises(TransplantValidationError):
        _transplant(
            db_session, tenant, farm, user, s["batch"], [_simple_source(aid)],
            [_simple_destination(plate.id, assigned_plant_count=100)], [_simple_allocation(aid, plate.id, 100)],
            effective_time=s["entry_time"] + timedelta(hours=2),
        )
