"""NURSERY-OPS-005A: chained Transplant source authority.

Covers the highest-value items of the required test matrix: population
authority derivation/consumption, chaining eligibility, and the new
production-entry workflow-integrity guard. Existing Seed-Tray-path
regression coverage lives in `test_transplant.py`/`test_transplant_
correction.py` (unchanged); this file only adds NEW behavior."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.batch_carrier_population_checkpoint import BatchCarrierPopulationCheckpoint
from app.services import carrier_specification_service, crop_batch_service, transplant_source_authority, transplant_service
from app.services.errors import (
    BatchStageHasUnresolvedPreProductionRemainderError,
    BatchStageHasUnresolvedSeedlingRemainderError,
    TransplantCommandReusedWithDifferentPayloadError,
    TransplantValidationError,
    UnsupportedTransplantSourceCarrierTypeError,
)
from tests._transplant_scenario import build_transplant_ready_scenario, now as _now


def _spec(db_session, tenant, user, *, carrier_type_code, code, count=200):
    return carrier_specification_service.register_carrier_specification(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, carrier_type_code=carrier_type_code,
        code=code, name=code, length_mm=300, width_mm=200, height_mm=50, biological_position_count=count,
    )


def _nursery_plate_scenario(
    db_session, tenant, user, farm, *, suffix=None, count=200, production_stage=False, tray_count=4,
):
    suffix = suffix or uuid.uuid4().hex[:8]
    spec = _spec(
        db_session, tenant, user, carrier_type_code="nursery_cultivation_plate", code=f"NP-SPEC-{suffix}",
        count=count,
    )
    scenario = build_transplant_ready_scenario(
        db_session, tenant, user, farm, suffix=suffix, tray_count=tray_count, normal=200, abnormal=0,
        transplanting_required_type="nursery_cultivation_plate", destination_specification_id=spec.id,
        production_stage=production_stage,
    )
    return scenario, spec


def _simple_source(assignment_id, **overrides):
    defaults = dict(
        source_assignment_id=assignment_id, transplant_damage_count=0, qc_rejection_count=0, sample_count=0,
        other_loss_count=0, other_loss_note=None, note=None,
    )
    defaults.update(overrides)
    return defaults


def _simple_destination(carrier_id, count, **overrides):
    defaults = dict(destination_carrier_id=carrier_id, assigned_plant_count=count, note=None)
    defaults.update(overrides)
    return defaults


def _simple_allocation(source_id, dest_id, count):
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


# --- Population authority ---------------------------------------------------------


@pytest.mark.integration
def test_nursery_plate_opening_population_derived_not_stored(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, _spec = _nursery_plate_scenario(db_session, tenant, user, farm)
    aid = s["source_assignment_ids"][0]
    plate1 = s["destination_carriers"][0]
    event = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(plate1.id, 200)], [_simple_allocation(aid, plate1.id, 200)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    destination_assignment = db_session.execute(
        select(BatchCarrierAssignment).where(BatchCarrierAssignment.opening_transplant_event_id == event.id)
    ).scalar_one()
    # No checkpoint row yet -- opening population is derived at read time,
    # never written for a normal fresh destination.
    checkpoint_count = db_session.execute(
        select(func.count()).select_from(BatchCarrierPopulationCheckpoint).where(
            BatchCarrierPopulationCheckpoint.batch_carrier_assignment_id == destination_assignment.id
        )
    ).scalar_one()
    assert checkpoint_count == 0


@pytest.mark.integration
def test_multi_source_nursery_plate_opening_population_equals_destination_total(
    db_session, active_context_with_farm
) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, _spec = _nursery_plate_scenario(db_session, tenant, user, farm, count=500)
    aid1, aid2 = s["source_assignment_ids"][0], s["source_assignment_ids"][1]
    plate1 = s["destination_carriers"][0]
    event = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid1), _simple_source(aid2)], [_simple_destination(plate1.id, 400)],
        [_simple_allocation(aid1, plate1.id, 200), _simple_allocation(aid2, plate1.id, 200)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    destination_assignment = db_session.execute(
        select(BatchCarrierAssignment).where(BatchCarrierAssignment.opening_transplant_event_id == event.id)
    ).scalar_one()
    authority = transplant_source_authority.SourceAuthority(kind="batch_carrier_population")
    available = transplant_source_authority.get_source_available(
        db_session, authority=authority, assignment_id=destination_assignment.id, as_of=_now(),
    )
    assert available == 400


@pytest.mark.integration
def test_nursery_plate_accepted_as_downstream_transplant_source(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, _spec = _nursery_plate_scenario(db_session, tenant, user, farm)
    aid = s["source_assignment_ids"][0]
    plate1, plate2 = s["destination_carriers"][0], s["destination_carriers"][1]
    first = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(plate1.id, 200)], [_simple_allocation(aid, plate1.id, 200)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    plate1_assignment = db_session.execute(
        select(BatchCarrierAssignment).where(BatchCarrierAssignment.opening_transplant_event_id == first.id)
    ).scalar_one()

    second = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(plate1_assignment.id)], [_simple_destination(plate2.id, 80)],
        [_simple_allocation(plate1_assignment.id, plate2.id, 80)],
        effective_time=s["entry_time"] + timedelta(hours=4),
    )
    assert second is not None
    checkpoint = db_session.execute(
        select(BatchCarrierPopulationCheckpoint).where(
            BatchCarrierPopulationCheckpoint.batch_carrier_assignment_id == plate1_assignment.id
        )
    ).scalar_one()
    assert checkpoint.remainder_after == 120
    refreshed = db_session.get(BatchCarrierAssignment, plate1_assignment.id)
    assert refreshed.released_effective_time is None  # partial -- stays active


@pytest.mark.integration
def test_production_plate_rejected_as_transplant_source(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    spec = _spec(
        db_session, tenant, user, carrier_type_code="production_cultivation_plate",
        code=f"PP-SPEC-{uuid.uuid4().hex[:8]}",
    )
    s = build_transplant_ready_scenario(
        db_session, tenant, user, farm, transplanting_required_type="production_cultivation_plate",
        destination_specification_id=spec.id,
    )
    aid = s["source_assignment_ids"][0]
    plate1, plate2 = s["destination_carriers"][0], s["destination_carriers"][1]
    first = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(plate1.id, 200)], [_simple_allocation(aid, plate1.id, 200)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    production_assignment = db_session.execute(
        select(BatchCarrierAssignment).where(BatchCarrierAssignment.opening_transplant_event_id == first.id)
    ).scalar_one()

    with pytest.raises(UnsupportedTransplantSourceCarrierTypeError):
        _transplant(
            db_session, tenant, farm, user, s["batch"],
            [_simple_source(production_assignment.id)], [_simple_destination(plate2.id, 100)],
            [_simple_allocation(production_assignment.id, plate2.id, 100)],
            effective_time=s["entry_time"] + timedelta(hours=4),
        )


@pytest.mark.integration
def test_full_downstream_consumption_releases_nursery_plate_source(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, _spec = _nursery_plate_scenario(db_session, tenant, user, farm)
    aid = s["source_assignment_ids"][0]
    plate1, plate2 = s["destination_carriers"][0], s["destination_carriers"][1]
    first = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(plate1.id, 200)], [_simple_allocation(aid, plate1.id, 200)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    plate1_assignment = db_session.execute(
        select(BatchCarrierAssignment).where(BatchCarrierAssignment.opening_transplant_event_id == first.id)
    ).scalar_one()

    second = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(plate1_assignment.id)], [_simple_destination(plate2.id, 200)],
        [_simple_allocation(plate1_assignment.id, plate2.id, 200)],
        effective_time=s["entry_time"] + timedelta(hours=4),
    )
    checkpoint = db_session.execute(
        select(BatchCarrierPopulationCheckpoint).where(
            BatchCarrierPopulationCheckpoint.batch_carrier_assignment_id == plate1_assignment.id
        )
    ).scalar_one()
    assert checkpoint.remainder_after == 0
    refreshed = db_session.get(BatchCarrierAssignment, plate1_assignment.id)
    assert refreshed.released_effective_time == second.effective_time
    assert refreshed.released_by_transplant_event_id == second.id


@pytest.mark.integration
def test_over_consumption_of_nursery_plate_source_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, _spec = _nursery_plate_scenario(db_session, tenant, user, farm, count=500)
    aid = s["source_assignment_ids"][0]
    plate1, plate2 = s["destination_carriers"][0], s["destination_carriers"][1]
    first = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(plate1.id, 200)], [_simple_allocation(aid, plate1.id, 200)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    plate1_assignment = db_session.execute(
        select(BatchCarrierAssignment).where(BatchCarrierAssignment.opening_transplant_event_id == first.id)
    ).scalar_one()

    with pytest.raises(TransplantValidationError):
        _transplant(
            db_session, tenant, farm, user, s["batch"],
            [_simple_source(plate1_assignment.id)], [_simple_destination(plate2.id, 250)],
            [_simple_allocation(plate1_assignment.id, plate2.id, 250)],
            effective_time=s["entry_time"] + timedelta(hours=4),
        )


@pytest.mark.integration
def test_sequential_partial_consumptions_append_structural_chain(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, _spec = _nursery_plate_scenario(db_session, tenant, user, farm)
    aid = s["source_assignment_ids"][0]
    plate1, plate2, plate3 = s["destination_carriers"][0], s["destination_carriers"][1], s["destination_carriers"][2]
    first = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(plate1.id, 200)], [_simple_allocation(aid, plate1.id, 200)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    plate1_assignment = db_session.execute(
        select(BatchCarrierAssignment).where(BatchCarrierAssignment.opening_transplant_event_id == first.id)
    ).scalar_one()

    _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(plate1_assignment.id)], [_simple_destination(plate2.id, 60)],
        [_simple_allocation(plate1_assignment.id, plate2.id, 60)],
        effective_time=s["entry_time"] + timedelta(hours=4),
    )
    _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(plate1_assignment.id)], [_simple_destination(plate3.id, 40)],
        [_simple_allocation(plate1_assignment.id, plate3.id, 40)],
        effective_time=s["entry_time"] + timedelta(hours=6),
    )

    checkpoints = list(
        db_session.execute(
            select(BatchCarrierPopulationCheckpoint).where(
                BatchCarrierPopulationCheckpoint.batch_carrier_assignment_id == plate1_assignment.id
            )
        ).scalars()
    )
    assert len(checkpoints) == 2
    tip = next(c for c in checkpoints if c.remainder_after == 100)
    root = next(c for c in checkpoints if c.remainder_after == 140)
    assert tip.previous_checkpoint_id == root.id
    assert root.previous_checkpoint_id is None
    refreshed = db_session.get(BatchCarrierAssignment, plate1_assignment.id)
    assert refreshed.released_effective_time is None


@pytest.mark.integration
def test_exact_replay_writes_no_duplicate_checkpoint(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, _spec = _nursery_plate_scenario(db_session, tenant, user, farm)
    aid = s["source_assignment_ids"][0]
    plate1, plate2 = s["destination_carriers"][0], s["destination_carriers"][1]
    first = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(plate1.id, 200)], [_simple_allocation(aid, plate1.id, 200)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    plate1_assignment = db_session.execute(
        select(BatchCarrierAssignment).where(BatchCarrierAssignment.opening_transplant_event_id == first.id)
    ).scalar_one()

    command_id = uuid.uuid4()
    second = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(plate1_assignment.id)], [_simple_destination(plate2.id, 80)],
        [_simple_allocation(plate1_assignment.id, plate2.id, 80)],
        effective_time=s["entry_time"] + timedelta(hours=4), client_command_id=command_id,
    )
    replay = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(plate1_assignment.id)], [_simple_destination(plate2.id, 80)],
        [_simple_allocation(plate1_assignment.id, plate2.id, 80)],
        effective_time=s["entry_time"] + timedelta(hours=4), client_command_id=command_id,
    )
    assert replay.id == second.id
    checkpoint_count = db_session.execute(
        select(func.count()).select_from(BatchCarrierPopulationCheckpoint).where(
            BatchCarrierPopulationCheckpoint.batch_carrier_assignment_id == plate1_assignment.id
        )
    ).scalar_one()
    assert checkpoint_count == 1


@pytest.mark.integration
def test_same_command_id_different_payload_conflicts(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, _spec = _nursery_plate_scenario(db_session, tenant, user, farm)
    aid = s["source_assignment_ids"][0]
    plate1, plate2 = s["destination_carriers"][0], s["destination_carriers"][1]
    first = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(plate1.id, 200)], [_simple_allocation(aid, plate1.id, 200)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    plate1_assignment = db_session.execute(
        select(BatchCarrierAssignment).where(BatchCarrierAssignment.opening_transplant_event_id == first.id)
    ).scalar_one()

    command_id = uuid.uuid4()
    _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(plate1_assignment.id)], [_simple_destination(plate2.id, 80)],
        [_simple_allocation(plate1_assignment.id, plate2.id, 80)],
        effective_time=s["entry_time"] + timedelta(hours=4), client_command_id=command_id,
    )
    with pytest.raises(TransplantCommandReusedWithDifferentPayloadError):
        _transplant(
            db_session, tenant, farm, user, s["batch"],
            [_simple_source(plate1_assignment.id)], [_simple_destination(plate2.id, 60)],
            [_simple_allocation(plate1_assignment.id, plate2.id, 60)],
            effective_time=s["entry_time"] + timedelta(hours=4), client_command_id=command_id,
        )


@pytest.mark.integration
def test_different_batch_nursery_plate_source_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s1, _spec1 = _nursery_plate_scenario(db_session, tenant, user, farm, suffix="a")
    s2, _spec2 = _nursery_plate_scenario(db_session, tenant, user, farm, suffix="b")
    aid1 = s1["source_assignment_ids"][0]
    plate1_batch1 = s1["destination_carriers"][0]
    plate1_batch2 = s2["destination_carriers"][0]
    first = _transplant(
        db_session, tenant, farm, user, s1["batch"],
        [_simple_source(aid1)], [_simple_destination(plate1_batch1.id, 200)],
        [_simple_allocation(aid1, plate1_batch1.id, 200)],
        effective_time=s1["entry_time"] + timedelta(hours=2),
    )
    plate1_assignment = db_session.execute(
        select(BatchCarrierAssignment).where(BatchCarrierAssignment.opening_transplant_event_id == first.id)
    ).scalar_one()

    # plate1_assignment belongs to Batch 1 -- using it as a source for
    # Batch 2's own transplant command must be rejected (cross-batch merge
    # remains prohibited, independent of carrier type).
    with pytest.raises(Exception):
        _transplant(
            db_session, tenant, farm, user, s2["batch"],
            [_simple_source(plate1_assignment.id)], [_simple_destination(plate1_batch2.id, 100)],
            [_simple_allocation(plate1_assignment.id, plate1_batch2.id, 100)],
            effective_time=s2["entry_time"] + timedelta(hours=4),
        )


# --- Stage integrity ---------------------------------------------------------------


@pytest.mark.integration
def test_entering_production_blocked_by_nursery_plate_remainder(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, _spec = _nursery_plate_scenario(db_session, tenant, user, farm, production_stage=True, tray_count=1)
    aid = s["source_assignment_ids"][0]
    plate1 = s["destination_carriers"][0]
    _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(plate1.id, 200)], [_simple_allocation(aid, plate1.id, 200)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    # Advance the Batch: TRANSPLANTING -> GROWING (t2) is legal regardless
    # (only leaving TRANSPLANTING is guarded by the Seedling remainder
    # check, and every Seed Tray was fully consumed by the transplant
    # above). GROWING -> PRODUCTION (t4) must now be blocked: Plate 1
    # still holds all 200 plants, untransferred to any further destination.
    crop_batch_service.transition_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), configured_transition_id=s["transitions"]["t2"].id,
        effective_time=s["entry_time"] + timedelta(hours=3), reason=None,
    )
    with pytest.raises(BatchStageHasUnresolvedPreProductionRemainderError) as exc_info:
        crop_batch_service.transition_stage(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
            client_command_id=uuid.uuid4(), configured_transition_id=s["transitions"]["t4"].id,
            effective_time=s["entry_time"] + timedelta(hours=5), reason=None,
        )
    assert exc_info.value.unresolved_source_count == 1
    assert exc_info.value.total_unresolved_living_count == 200


@pytest.mark.integration
def test_released_nursery_plate_excluded_from_unresolved_remainder(db_session, active_context_with_farm) -> None:
    """A released/fully-exhausted Nursery Plate must never count toward
    unresolved pre-production remainder -- proven directly against the
    remainder function itself. (A still-active Plate holding untransferred
    living biology correctly DOES count, even after chained consolidation
    onto it -- see `test_entering_production_blocked_by_nursery_plate_
    remainder`: within NURSERY-OPS-005A's own scope, biology chained
    between Nursery Plates always ends up on SOME active Nursery Plate, so
    genuinely resolving it requires NURSERY-OPS-005B's future Production
    transfer, not further Nursery-to-Nursery consolidation.)"""
    tenant, user, _headers, farm = active_context_with_farm
    s, _spec = _nursery_plate_scenario(db_session, tenant, user, farm, tray_count=1)
    aid = s["source_assignment_ids"][0]
    plate1, plate2 = s["destination_carriers"][0], s["destination_carriers"][1]
    first = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(plate1.id, 200)], [_simple_allocation(aid, plate1.id, 200)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    plate1_assignment = db_session.execute(
        select(BatchCarrierAssignment).where(BatchCarrierAssignment.opening_transplant_event_id == first.id)
    ).scalar_one()
    _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(plate1_assignment.id)], [_simple_destination(plate2.id, 200)],
        [_simple_allocation(plate1_assignment.id, plate2.id, 200)],
        effective_time=s["entry_time"] + timedelta(hours=4),
    )
    refreshed = db_session.get(BatchCarrierAssignment, plate1_assignment.id)
    assert refreshed.released_effective_time is not None  # confirmed exhausted/released

    unresolved_count, unresolved_living = transplant_source_authority.get_unresolved_batch_carrier_population_remainder(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=s["batch"].id,
        as_of=s["entry_time"] + timedelta(hours=5),
    )
    # Plate 2 (active, holding the 200 plants) still counts -- Plate 1
    # (released) must not contribute a second time.
    assert unresolved_count == 1
    assert unresolved_living == 200


@pytest.mark.integration
def test_entering_production_succeeds_with_no_nursery_plate_activity(db_session, active_context_with_farm) -> None:
    """When a Batch's Transplant activity never touches nursery_cultivation_
    plate at all (an ordinary Seed Tray -> generic cultivation_plate
    transplant, ordinary pre-005A behavior, fully resolving the Seedling
    remainder), the NEW production-entry guard's own Nursery-Plate check
    trivially passes (zero nursery_cultivation_plate assignments exist for
    this batch) -- proving the new guard adds no friction to a Batch that
    never uses the new chained-source capability at all."""
    tenant, user, _headers, farm = active_context_with_farm
    s = build_transplant_ready_scenario(
        db_session, tenant, user, farm, tray_count=1, transplanting_required_type="cultivation_plate",
        production_stage=True,
    )
    aid = s["source_assignment_ids"][0]
    plate1 = s["destination_carriers"][0]
    _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(plate1.id, 200)], [_simple_allocation(aid, plate1.id, 200)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    crop_batch_service.transition_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), configured_transition_id=s["transitions"]["t2"].id,
        effective_time=s["entry_time"] + timedelta(hours=3), reason=None,
    )
    transition = crop_batch_service.transition_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), configured_transition_id=s["transitions"]["t4"].id,
        effective_time=s["entry_time"] + timedelta(hours=4), reason=None,
    )
    assert transition is not None


@pytest.mark.integration
def test_existing_leaving_transplanting_guard_unchanged(db_session, active_context_with_farm) -> None:
    """Regression: the pre-existing Seedling-remainder guard on LEAVING a
    transplanting-category stage must still fire exactly as before,
    completely independent of the new production-entry guard."""
    tenant, user, _headers, farm = active_context_with_farm
    s, _spec = _nursery_plate_scenario(db_session, tenant, user, farm)
    # Deliberately consume only ONE of the four sown Seed Trays -- the
    # other three remain unresolved.
    aid = s["source_assignment_ids"][0]
    plate1 = s["destination_carriers"][0]
    _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(plate1.id, 200)], [_simple_allocation(aid, plate1.id, 200)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    with pytest.raises(BatchStageHasUnresolvedSeedlingRemainderError):
        crop_batch_service.transition_stage(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
            client_command_id=uuid.uuid4(), configured_transition_id=s["transitions"]["t2"].id,
            effective_time=s["entry_time"] + timedelta(hours=3), reason=None,
        )
