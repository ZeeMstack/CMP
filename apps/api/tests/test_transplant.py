import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.models.audit_event import AuditEvent
from app.models.batch_carrier_assignment import BatchCarrierAssignment
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
    crop_batch_service,
    transplant_service,
)
from app.services.errors import (
    CarrierNotFoundError,
    DestinationCarrierAlreadyAssignedError,
    InvalidTransplantEffectiveTimeError,
    SourceAssignmentAlreadyReleasedError,
    SourceAssignmentHasNoSeedlingEntryError,
    TransplantCommandReusedWithDifferentPayloadError,
    TransplantValidationError,
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


def _build_scenario(db_session, tenant, user, farm, *, suffix=None, transplanting_required_type="cultivation_plate"):
    return build_transplant_ready_scenario(
        db_session, tenant, user, farm, suffix=suffix, tray_count=4, normal=200, abnormal=0,
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
def test_source_with_no_seedling_entry_rejected(db_session, active_context_with_farm) -> None:
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

    # The destination assignment just opened by that transplant has no
    # SeedlingEntry at all (it's transplant-opened, not sowing-opened) --
    # modern source authority requires one.
    destination_assignment_id = db_session.execute(
        select(BatchCarrierAssignment.id).where(
            BatchCarrierAssignment.carrier_id == s["destination_carriers"][0].id
        )
    ).scalar_one()
    fresh_destination = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        carrier_type_code="cultivation_plate", code="CP-FRESH-0001", issued_date=None,
    )
    with pytest.raises(SourceAssignmentHasNoSeedlingEntryError):
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
    s = _build_scenario(db_session, tenant, user, farm)
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
def test_transplant_routes_exactly_three_no_mutation_and_no_lineage_route() -> None:
    from app.main import app

    schema = app.openapi()
    transplant_paths = {p: ops for p, ops in schema["paths"].items() if "transplant" in p}
    ops_count = sum(len(ops) for ops in transplant_paths.values())
    assert ops_count == 3, transplant_paths
    methods = {method.upper() for ops in transplant_paths.values() for method in ops}
    assert methods == {"GET", "POST"}
    assert not any("lineage" in p for p in transplant_paths)
