"""NURSERY-OPS-004A: SeedlingSourceCheckpoint / balance-window mechanics.
Not re-testing ordinary transplant validation (already covered by
test_transplant.py) or ordinary disposition validation (already covered by
test_seedling_disposition.py) -- this file is specifically about the
checkpoint/balance-window model itself: the literal anchor-formula sequence,
the strict checkpoint temporal floor on both dispositions and transplants,
pre-checkpoint corrections being frozen, partial/sequential transplant of
the same Tray, conditional release, and the deliberate
`current_living_seedling_count` vs `current_source_available_count`
distinction."""
import uuid
from datetime import timedelta

import pytest

from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.seedling_entry import SeedlingEntry
from app.models.seedling_source_checkpoint import SeedlingSourceCheckpoint
from app.services import seedling_disposition_service, transplant_service
from app.services.errors import (
    InvalidTransplantEffectiveTimeError,
    SeedlingDispositionPredatesCheckpointError,
    SourceAssignmentAlreadyReleasedError,
)
from tests._transplant_scenario import build_transplant_ready_scenario


def _build_scenario(db_session, tenant, user, farm, *, normal=200, abnormal=0, tray_count=1):
    return build_transplant_ready_scenario(
        db_session, tenant, user, farm, tray_count=tray_count, normal=normal, abnormal=abnormal,
    )


def _disposition(db_session, tenant, user, farm, *, assignment_id, quantity, effective_time, reason_code="WEAK_SEEDLING"):
    return seedling_disposition_service.record_disposition(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=uuid.uuid4(), batch_carrier_assignment_id=assignment_id, quantity=quantity,
        reason_code=reason_code, effective_time=effective_time, note=None,
    )


def _correct(db_session, tenant, user, farm, *, target_event_id, corrected=None):
    return seedling_disposition_service.correct_disposition(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=uuid.uuid4(), target_event_id=target_event_id, corrected=corrected,
    )


def _transplant_one(
    db_session, tenant, user, farm, batch, *, source_assignment_id, destination_carrier_id, effective_time,
    allocated, damage=0, rejection=0, sample=0, other=0, other_note=None,
):
    source_lines = [
        {
            "source_assignment_id": source_assignment_id, "transplant_damage_count": damage,
            "qc_rejection_count": rejection, "sample_count": sample, "other_loss_count": other,
            "other_loss_note": other_note, "note": None,
        }
    ]
    destination_lines = [{"destination_carrier_id": destination_carrier_id, "assigned_plant_count": allocated, "note": None}]
    allocations = [
        {
            "source_assignment_id": source_assignment_id, "destination_carrier_id": destination_carrier_id,
            "allocated_plant_count": allocated,
        }
    ]
    return transplant_service.record_transplant(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=effective_time, note=None, source_lines=source_lines,
        destination_lines=destination_lines, allocations=allocations,
    )


def _checkpoints_for_entry(db_session, entry_id):
    return list(
        db_session.query(SeedlingSourceCheckpoint)
        .filter(SeedlingSourceCheckpoint.seedling_entry_id == entry_id)
        .order_by(SeedlingSourceCheckpoint.effective_time)
        .all()
    )


def _tray_row(db_session, tenant, farm, assignment_id):
    rows = seedling_disposition_service.list_seedling_biological_trays(db_session, tenant_id=tenant.id, farm_id=farm.id)
    return next(r for r in rows if r.batch_carrier_assignment_id == assignment_id)


@pytest.mark.integration
def test_literal_checkpoint_sequence(db_session, active_context_with_farm) -> None:
    """The exact worked sequence from NURSERY-OPS-004A's own design:
    start=200 -> disposition -10 -> 190 -> transplant leaves checkpoint #1
    remainder=70 -> disposition -5 -> 65 -> transplant leaves checkpoint #2
    (chained to #1) remainder=5 -> disposition -2 -> 3. Proves the anchor
    formula `anchor_value + SUM(deltas strictly after anchor_time)` at every
    step, using both the SeedlingEntry anchor and each successive
    checkpoint anchor."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, normal=200)
    entry = db_session.get(SeedlingEntry, s["entry_ids"][0])
    aid = s["source_assignment_ids"][0]
    t0 = s["entry_time"]

    anchor_value, anchor_time, has_checkpoint = seedling_disposition_service.get_source_availability_anchor(
        db_session, seedling_entry=entry
    )
    assert (anchor_value, anchor_time, has_checkpoint) == (200, entry.effective_time, False)

    t1 = t0 + timedelta(hours=1)
    _disposition(db_session, tenant, user, farm, assignment_id=aid, quantity=10, effective_time=t1)
    assert seedling_disposition_service.get_source_available(db_session, seedling_entry=entry, as_of=t1) == 190

    t2 = t0 + timedelta(hours=2)
    event1 = _transplant_one(
        db_session, tenant, user, farm, s["batch"], source_assignment_id=aid,
        destination_carrier_id=s["destination_carriers"][0].id, effective_time=t2, allocated=120,
    )
    checkpoints = _checkpoints_for_entry(db_session, entry.id)
    assert len(checkpoints) == 1
    cp1 = checkpoints[0]
    assert cp1.remainder_after == 70
    assert cp1.effective_time == t2
    assert cp1.previous_checkpoint_id is None
    assert cp1.transplant_source_line_id is not None

    anchor_value, anchor_time, has_checkpoint = seedling_disposition_service.get_source_availability_anchor(
        db_session, seedling_entry=entry
    )
    assert (anchor_value, anchor_time, has_checkpoint) == (70, t2, True)

    t3 = t0 + timedelta(hours=3)
    _disposition(db_session, tenant, user, farm, assignment_id=aid, quantity=5, effective_time=t3)
    assert seedling_disposition_service.get_source_available(db_session, seedling_entry=entry, as_of=t3) == 65

    t4 = t0 + timedelta(hours=4)
    event2 = _transplant_one(
        db_session, tenant, user, farm, s["batch"], source_assignment_id=aid,
        destination_carrier_id=s["destination_carriers"][1].id, effective_time=t4, allocated=60,
    )
    checkpoints = _checkpoints_for_entry(db_session, entry.id)
    assert len(checkpoints) == 2
    cp2 = checkpoints[1]
    assert cp2.remainder_after == 5
    assert cp2.effective_time == t4
    assert cp2.previous_checkpoint_id == cp1.id

    anchor_value, anchor_time, has_checkpoint = seedling_disposition_service.get_source_availability_anchor(
        db_session, seedling_entry=entry
    )
    assert (anchor_value, anchor_time, has_checkpoint) == (5, t4, True)

    t5 = t0 + timedelta(hours=5)
    _disposition(db_session, tenant, user, farm, assignment_id=aid, quantity=2, effective_time=t5)
    assert seedling_disposition_service.get_source_available(db_session, seedling_entry=entry, as_of=t5) == 3

    # The assignment stayed active across both partial transplants -- never
    # released, since remainder never reached zero.
    assert db_session.get(BatchCarrierAssignment, aid).released_effective_time is None
    assert event1.id != event2.id


@pytest.mark.integration
def test_disposition_at_checkpoint_boundary_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, normal=100)
    entry = db_session.get(SeedlingEntry, s["entry_ids"][0])
    aid = s["source_assignment_ids"][0]
    t0 = s["entry_time"]
    t1 = t0 + timedelta(hours=1)
    _transplant_one(
        db_session, tenant, user, farm, s["batch"], source_assignment_id=aid,
        destination_carrier_id=s["destination_carriers"][0].id, effective_time=t1, allocated=60,
    )
    with pytest.raises(SeedlingDispositionPredatesCheckpointError):
        _disposition(db_session, tenant, user, farm, assignment_id=aid, quantity=1, effective_time=t1)


@pytest.mark.integration
def test_disposition_before_checkpoint_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, normal=100)
    aid = s["source_assignment_ids"][0]
    t0 = s["entry_time"]
    t1 = t0 + timedelta(hours=2)
    _transplant_one(
        db_session, tenant, user, farm, s["batch"], source_assignment_id=aid,
        destination_carrier_id=s["destination_carriers"][0].id, effective_time=t1, allocated=60,
    )
    with pytest.raises(SeedlingDispositionPredatesCheckpointError):
        _disposition(db_session, tenant, user, farm, assignment_id=aid, quantity=1, effective_time=t0 + timedelta(hours=1))


@pytest.mark.integration
def test_transplant_at_checkpoint_boundary_rejected(db_session, active_context_with_farm) -> None:
    """A second transplant against the same, still-active source assignment
    (remainder > 0) with effective_time exactly equal to the first
    transplant's checkpoint is rejected -- the checkpoint temporal floor is
    strict, matching the equivalent disposition-side floor exactly."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, normal=100)
    aid = s["source_assignment_ids"][0]
    t0 = s["entry_time"]
    t1 = t0 + timedelta(hours=1)
    _transplant_one(
        db_session, tenant, user, farm, s["batch"], source_assignment_id=aid,
        destination_carrier_id=s["destination_carriers"][0].id, effective_time=t1, allocated=60,
    )
    with pytest.raises(InvalidTransplantEffectiveTimeError):
        _transplant_one(
            db_session, tenant, user, farm, s["batch"], source_assignment_id=aid,
            destination_carrier_id=s["destination_carriers"][1].id, effective_time=t1, allocated=10,
        )


@pytest.mark.integration
def test_transplant_at_earliest_valid_moment_with_no_checkpoint_yet_allowed(db_session, active_context_with_farm) -> None:
    """Before any checkpoint exists, the anchor is the SeedlingEntry itself
    and its own floor is at-or-after (not strictly-after) -- unlike a
    checkpoint anchor, which is always strict. `build_transplant_ready_
    scenario` only ever advances into TRANSPLANTING strictly after
    SeedlingEntry, so the stage-run's own entry time -- not the
    SeedlingEntry anchor -- is what actually binds here; a transplant at
    that earliest valid instant must still succeed."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, normal=100)
    aid = s["source_assignment_ids"][0]
    event = _transplant_one(
        db_session, tenant, user, farm, s["batch"], source_assignment_id=aid,
        destination_carrier_id=s["destination_carriers"][0].id,
        effective_time=s["entry_time"] + timedelta(hours=1), allocated=100,
    )
    assert event is not None


@pytest.mark.integration
def test_correction_of_pre_checkpoint_disposition_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, normal=100)
    aid = s["source_assignment_ids"][0]
    t0 = s["entry_time"]
    command = _disposition(db_session, tenant, user, farm, assignment_id=aid, quantity=5, effective_time=t0 + timedelta(hours=1))
    event_id = db_session.execute(
        __import__("sqlalchemy").text(
            "SELECT id FROM seedling_disposition_events WHERE command_id = :cid AND event_kind = 'REDUCTION'"
        ),
        {"cid": command.id},
    ).scalar_one()

    _transplant_one(
        db_session, tenant, user, farm, s["batch"], source_assignment_id=aid,
        destination_carrier_id=s["destination_carriers"][0].id, effective_time=t0 + timedelta(hours=2), allocated=50,
    )

    with pytest.raises(SeedlingDispositionPredatesCheckpointError):
        _correct(db_session, tenant, user, farm, target_event_id=event_id, corrected=None)


@pytest.mark.integration
def test_correction_of_post_checkpoint_disposition_succeeds(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, normal=100)
    aid = s["source_assignment_ids"][0]
    t0 = s["entry_time"]
    _transplant_one(
        db_session, tenant, user, farm, s["batch"], source_assignment_id=aid,
        destination_carrier_id=s["destination_carriers"][0].id, effective_time=t0 + timedelta(hours=1), allocated=50,
    )
    command = _disposition(
        db_session, tenant, user, farm, assignment_id=aid, quantity=5, effective_time=t0 + timedelta(hours=2)
    )
    event_id = db_session.execute(
        __import__("sqlalchemy").text(
            "SELECT id FROM seedling_disposition_events WHERE command_id = :cid AND event_kind = 'REDUCTION'"
        ),
        {"cid": command.id},
    ).scalar_one()

    correction = _correct(db_session, tenant, user, farm, target_event_id=event_id, corrected=None)
    assert correction is not None


@pytest.mark.integration
def test_partial_transplant_leaves_assignment_active_for_sequential_transplant(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, normal=100)
    aid = s["source_assignment_ids"][0]
    t0 = s["entry_time"]
    _transplant_one(
        db_session, tenant, user, farm, s["batch"], source_assignment_id=aid,
        destination_carrier_id=s["destination_carriers"][0].id, effective_time=t0 + timedelta(hours=1), allocated=40,
    )
    assert db_session.get(BatchCarrierAssignment, aid).released_effective_time is None

    second = _transplant_one(
        db_session, tenant, user, farm, s["batch"], source_assignment_id=aid,
        destination_carrier_id=s["destination_carriers"][1].id, effective_time=t0 + timedelta(hours=2), allocated=60,
    )
    assert second is not None
    assert db_session.get(BatchCarrierAssignment, aid).released_effective_time == t0 + timedelta(hours=2)


@pytest.mark.integration
def test_full_consumption_transplant_releases_assignment_after_checkpoint_recorded(
    db_session, active_context_with_farm
) -> None:
    """Proves the write-order bug fix: the checkpoint is inserted BEFORE
    the conditional release, so a full-consumption transplant succeeds and
    both facts (the checkpoint referencing the now-released assignment, and
    the release itself) are visible afterward -- not a self-inflicted
    rejection."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, normal=100)
    entry = db_session.get(SeedlingEntry, s["entry_ids"][0])
    aid = s["source_assignment_ids"][0]
    t0 = s["entry_time"]

    event = _transplant_one(
        db_session, tenant, user, farm, s["batch"], source_assignment_id=aid,
        destination_carrier_id=s["destination_carriers"][0].id, effective_time=t0 + timedelta(hours=1), allocated=100,
    )
    assignment = db_session.get(BatchCarrierAssignment, aid)
    assert assignment.released_effective_time == t0 + timedelta(hours=1)
    assert assignment.released_by_transplant_event_id == event.id

    checkpoints = _checkpoints_for_entry(db_session, entry.id)
    assert len(checkpoints) == 1
    assert checkpoints[0].remainder_after == 0
    assert checkpoints[0].source_batch_carrier_assignment_id == aid


@pytest.mark.integration
def test_transplant_against_released_assignment_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, normal=100)
    aid = s["source_assignment_ids"][0]
    t0 = s["entry_time"]
    _transplant_one(
        db_session, tenant, user, farm, s["batch"], source_assignment_id=aid,
        destination_carrier_id=s["destination_carriers"][0].id, effective_time=t0 + timedelta(hours=1), allocated=100,
    )
    with pytest.raises(SourceAssignmentAlreadyReleasedError):
        _transplant_one(
            db_session, tenant, user, farm, s["batch"], source_assignment_id=aid,
            destination_carrier_id=s["destination_carriers"][1].id, effective_time=t0 + timedelta(hours=2), allocated=1,
        )


@pytest.mark.integration
def test_reconciliation_exact_worked_example(db_session, active_context_with_farm) -> None:
    """190 = 120 (successful) + 3 (damage) + 1 (rejection) + 2 (sample) +
    4 (other, with required note) + 60 (remainder)."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, normal=190)
    aid = s["source_assignment_ids"][0]
    event = _transplant_one(
        db_session, tenant, user, farm, s["batch"], source_assignment_id=aid,
        destination_carrier_id=s["destination_carriers"][0].id, effective_time=s["entry_time"] + timedelta(hours=1),
        allocated=120, damage=3, rejection=1, sample=2, other=4, other_note="unusual case",
    )
    detail = transplant_service.get_transplant_event(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=s["batch_id"], transplant_event_id=event.id,
    )
    line = detail.source_lines[0]
    assert line.source_available_before == 190
    assert line.successful_transferred_count == 120
    assert line.transplant_damage_count == 3
    assert line.qc_rejection_count == 1
    assert line.sample_count == 2
    assert line.other_loss_count == 4
    assert line.other_loss_note == "unusual case"
    assert line.discarded_plant_count == 10
    assert line.remainder_after == 60
    assert 120 + 10 + 60 == 190
    assert detail.total_source_available_before == 190
    assert detail.total_destination_plant_count == 120
    assert detail.total_discarded_plant_count == 10
    assert detail.total_remainder_after == 60


@pytest.mark.integration
def test_current_living_count_unaffected_by_transplant_only_by_dispositions(db_session, active_context_with_farm) -> None:
    """`current_living_seedling_count` (checkpoint-unaware) only ever
    changes via SeedlingDispositionEvents -- a transplant, even one with
    categorized losses, never writes a disposition event and must never
    move this figure. `current_source_available_count` is the one that
    reflects transplant consumption."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, normal=100)
    aid = s["source_assignment_ids"][0]
    t0 = s["entry_time"]

    before = _tray_row(db_session, tenant, farm, aid)
    assert before.current_living_seedling_count == 100
    assert before.current_source_available_count == 100
    assert before.is_depleted is False

    _transplant_one(
        db_session, tenant, user, farm, s["batch"], source_assignment_id=aid,
        destination_carrier_id=s["destination_carriers"][0].id, effective_time=t0 + timedelta(hours=1),
        allocated=70, damage=10, rejection=5, sample=5, other=10, other_note="loss",
    )

    after = _tray_row(db_session, tenant, farm, aid)
    assert after.current_living_seedling_count == 100
    assert after.current_source_available_count == 0
    assert after.is_depleted is True
    assert after.checkpoint_count == 1
    assert after.latest_checkpoint_remainder_after == 0


@pytest.mark.integration
def test_is_depleted_reflects_source_available_not_living_count(db_session, active_context_with_farm) -> None:
    """A partial-remainder-zero (full-consumption) transplant makes
    `is_depleted=True` even though many of the original seedlings are still
    "living" in the checkpoint-unaware sense -- proving `is_depleted` was
    deliberately redefined around `source_available`, not
    `current_living_seedling_count` (NURSERY-OPS-004A section 28)."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, normal=100)
    aid = s["source_assignment_ids"][0]
    t0 = s["entry_time"]
    _transplant_one(
        db_session, tenant, user, farm, s["batch"], source_assignment_id=aid,
        destination_carrier_id=s["destination_carriers"][0].id, effective_time=t0 + timedelta(hours=1), allocated=100,
    )
    row = _tray_row(db_session, tenant, farm, aid)
    assert row.current_living_seedling_count == 100
    assert row.current_source_available_count == 0
    assert row.is_depleted is True
