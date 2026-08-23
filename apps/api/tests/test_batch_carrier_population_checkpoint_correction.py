"""NURSERY-OPS-005A: Transplant correction/restoration for a
BatchCarrierPopulationCheckpoint-backed (nursery_cultivation_plate) source,
plus the Carrier-reuse protection now applied consistently to every
Transplant correction restoration path."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.batch_carrier_population_checkpoint import BatchCarrierPopulationCheckpoint
from app.models.carrier import Carrier
from app.models.location import Location
from app.models.location_type import LocationType
from app.services import (
    carrier_specification_service,
    nursery_service,
    transplant_correction_service,
    transplant_service,
    transplant_source_authority,
)
from app.services.errors import TransplantCorrectionCarrierReusedError, TransplantCorrectionNotChainTipError
from tests._transplant_scenario import build_transplant_ready_scenario, now as _now

pytestmark = pytest.mark.integration


def _spec(db_session, tenant, user, *, carrier_type_code, code, count=500):
    return carrier_specification_service.register_carrier_specification(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, carrier_type_code=carrier_type_code,
        code=code, name=code, length_mm=300, width_mm=200, height_mm=50, biological_position_count=count,
    )


def _nursery_plate_scenario(db_session, tenant, user, farm, *, suffix=None, tray_count=4, count=500):
    suffix = suffix or uuid.uuid4().hex[:8]
    spec = _spec(db_session, tenant, user, carrier_type_code="nursery_cultivation_plate", code=f"NP-SPEC-{suffix}", count=count)
    return build_transplant_ready_scenario(
        db_session, tenant, user, farm, suffix=suffix, tray_count=tray_count, normal=200, abnormal=0,
        transplanting_required_type="nursery_cultivation_plate", destination_specification_id=spec.id,
    )


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


def _correct(db_session, tenant, farm, user, batch, target_event_id, *, reason="correction", replacement=None, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        target_transplant_event_id=target_event_id, client_command_id=uuid.uuid4(), reason=reason,
        replacement=replacement,
    )
    defaults.update(overrides)
    return transplant_correction_service.correct_transplant(db_session, **defaults)


def _first_plate_assignment(db_session, seed_transplant, plate1, farm, tenant, user, s):
    return db_session.execute(
        select(BatchCarrierAssignment).where(BatchCarrierAssignment.opening_transplant_event_id == seed_transplant.id)
    ).scalar_one()


def _tip_checkpoint(db_session, assignment_id):
    """The structural chain-tip BatchCarrierPopulationCheckpoint for one
    assignment -- may be one of several rows (a correction appends a new
    checkpoint alongside the one it doesn't erase; immutable history)."""
    rows = list(
        db_session.execute(
            select(BatchCarrierPopulationCheckpoint).where(
                BatchCarrierPopulationCheckpoint.batch_carrier_assignment_id == assignment_id
            )
        ).scalars()
    )
    by_id = {r.id: r for r in rows}
    successors = {r.previous_checkpoint_id for r in rows if r.previous_checkpoint_id is not None}
    tips = [r for r in rows if r.id not in successors]
    assert len(tips) == 1, f"expected exactly one chain-tip checkpoint, found {len(tips)}"
    return tips[0]


@pytest.mark.integration
def test_correct_full_exhausting_nursery_plate_consumption_restores_new_bca(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _nursery_plate_scenario(db_session, tenant, user, farm, tray_count=1)
    aid = s["source_assignment_ids"][0]
    plate1, plate2 = s["destination_carriers"][0], s["destination_carriers"][1]
    first = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(plate1.id, 200)], [_simple_allocation(aid, plate1.id, 200)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    plate1_assignment = _first_plate_assignment(db_session, first, plate1, farm, tenant, user, s)

    second = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(plate1_assignment.id)], [_simple_destination(plate2.id, 200)],
        [_simple_allocation(plate1_assignment.id, plate2.id, 200)],
        effective_time=s["entry_time"] + timedelta(hours=4),
    )
    refreshed = db_session.get(BatchCarrierAssignment, plate1_assignment.id)
    assert refreshed.released_effective_time is not None

    reversal = _correct(db_session, tenant, farm, user, s["batch"], second.id)
    assert reversal.event_kind == "REVERSAL"

    # Predecessor never reactivated.
    predecessor = db_session.get(BatchCarrierAssignment, plate1_assignment.id)
    assert predecessor.released_effective_time is not None
    assert predecessor.released_by_transplant_event_id == second.id

    restored = db_session.execute(
        select(BatchCarrierAssignment).where(
            BatchCarrierAssignment.restored_from_batch_carrier_assignment_id == plate1_assignment.id
        )
    ).scalar_one()
    assert restored.opening_transplant_reversal_event_id == reversal.id
    assert restored.released_effective_time is None
    assert restored.carrier_id == plate1_assignment.carrier_id

    checkpoint = db_session.execute(
        select(BatchCarrierPopulationCheckpoint).where(
            BatchCarrierPopulationCheckpoint.batch_carrier_assignment_id == restored.id
        )
    ).scalar_one()
    assert checkpoint.remainder_after == 200
    assert checkpoint.previous_checkpoint_id is None


@pytest.mark.integration
def test_correct_partial_nursery_plate_consumption(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _nursery_plate_scenario(db_session, tenant, user, farm, tray_count=1)
    aid = s["source_assignment_ids"][0]
    plate1, plate2 = s["destination_carriers"][0], s["destination_carriers"][1]
    first = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(plate1.id, 200)], [_simple_allocation(aid, plate1.id, 200)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    plate1_assignment = _first_plate_assignment(db_session, first, plate1, farm, tenant, user, s)

    second = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(plate1_assignment.id)], [_simple_destination(plate2.id, 80)],
        [_simple_allocation(plate1_assignment.id, plate2.id, 80)],
        effective_time=s["entry_time"] + timedelta(hours=4),
    )
    # Not exhausted -- same assignment stays active.
    still_active = db_session.get(BatchCarrierAssignment, plate1_assignment.id)
    assert still_active.released_effective_time is None

    reversal = _correct(db_session, tenant, farm, user, s["batch"], second.id)
    assert reversal.event_kind == "REVERSAL"

    # No new generation -- the partial correction operates on the SAME
    # still-active assignment (mirrors the existing Seed-Tray behavior).
    no_restoration = db_session.execute(
        select(BatchCarrierAssignment).where(
            BatchCarrierAssignment.restored_from_batch_carrier_assignment_id == plate1_assignment.id
        )
    ).scalar_one_or_none()
    assert no_restoration is None

    checkpoint = _tip_checkpoint(db_session, plate1_assignment.id)
    assert checkpoint.remainder_after == 200  # fully restored


@pytest.mark.integration
def test_reversal_plus_replacement_consumes_restored_nursery_plate(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _nursery_plate_scenario(db_session, tenant, user, farm, tray_count=1)
    aid = s["source_assignment_ids"][0]
    plate1, plate2, plate3 = s["destination_carriers"][0], s["destination_carriers"][1], s["destination_carriers"][2]
    first = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(plate1.id, 200)], [_simple_allocation(aid, plate1.id, 200)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    plate1_assignment = _first_plate_assignment(db_session, first, plate1, farm, tenant, user, s)

    second = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(plate1_assignment.id)], [_simple_destination(plate2.id, 200)],
        [_simple_allocation(plate1_assignment.id, plate2.id, 200)],
        effective_time=s["entry_time"] + timedelta(hours=4),
    )

    replacement = dict(
        source_lines=[_simple_source(plate1_assignment.id)],
        destination_lines=[_simple_destination(plate3.id, 200)],
        allocations=[_simple_allocation(plate1_assignment.id, plate3.id, 200)],
        note=None,
    )
    reversal = _correct(db_session, tenant, farm, user, s["batch"], second.id, replacement=replacement)
    assert reversal.event_kind == "REVERSAL"

    restored = db_session.execute(
        select(BatchCarrierAssignment).where(
            BatchCarrierAssignment.restored_from_batch_carrier_assignment_id == plate1_assignment.id
        )
    ).scalar_one()
    # The replacement (via source_assignment_id remap) consumed the
    # restored generation, not the original -- fully exhausted again.
    refreshed_restored = db_session.get(BatchCarrierAssignment, restored.id)
    assert refreshed_restored.released_effective_time is not None
    checkpoint = _tip_checkpoint(db_session, restored.id)
    assert checkpoint.remainder_after == 0


@pytest.mark.integration
def test_correction_blocked_after_downstream_nursery_plate_consumption(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _nursery_plate_scenario(db_session, tenant, user, farm, tray_count=1)
    aid = s["source_assignment_ids"][0]
    plate1, plate2, plate3 = s["destination_carriers"][0], s["destination_carriers"][1], s["destination_carriers"][2]
    first = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(plate1.id, 200)], [_simple_allocation(aid, plate1.id, 200)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    plate1_assignment = _first_plate_assignment(db_session, first, plate1, farm, tenant, user, s)

    second = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(plate1_assignment.id)], [_simple_destination(plate2.id, 80)],
        [_simple_allocation(plate1_assignment.id, plate2.id, 80)],
        effective_time=s["entry_time"] + timedelta(hours=4),
    )
    # A further, later consumption from the SAME source -- second's own
    # checkpoint is no longer the chain tip.
    _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(plate1_assignment.id)], [_simple_destination(plate3.id, 120)],
        [_simple_allocation(plate1_assignment.id, plate3.id, 120)],
        effective_time=s["entry_time"] + timedelta(hours=6),
    )

    with pytest.raises(TransplantCorrectionNotChainTipError):
        _correct(db_session, tenant, farm, user, s["batch"], second.id)


@pytest.mark.integration
def test_carrier_reuse_blocks_nursery_plate_restoration(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _nursery_plate_scenario(db_session, tenant, user, farm, tray_count=1)
    aid = s["source_assignment_ids"][0]
    plate1, plate2 = s["destination_carriers"][0], s["destination_carriers"][1]
    first = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(plate1.id, 200)], [_simple_allocation(aid, plate1.id, 200)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    plate1_assignment = _first_plate_assignment(db_session, first, plate1, farm, tenant, user, s)

    second = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(plate1_assignment.id)], [_simple_destination(plate2.id, 200)],
        [_simple_allocation(plate1_assignment.id, plate2.id, 200)],
        effective_time=s["entry_time"] + timedelta(hours=4),
    )
    # Legitimately reuse Plate 1's now-released physical Carrier as a
    # FRESH destination for a completely different Batch's own transplant
    # -- the real `maintain_carrier_latest_assignment_pointer` DB trigger
    # advances Carrier.latest_batch_carrier_assignment_id forward exactly
    # as it would in production, no manual manipulation.
    s2 = _nursery_plate_scenario(db_session, tenant, user, farm, suffix="reuse", tray_count=1)
    aid2 = s2["source_assignment_ids"][0]
    _transplant(
        db_session, tenant, farm, user, s2["batch"],
        [_simple_source(aid2)], [_simple_destination(plate1.id, 200)], [_simple_allocation(aid2, plate1.id, 200)],
        effective_time=s2["entry_time"] + timedelta(hours=2),
    )

    with pytest.raises(TransplantCorrectionCarrierReusedError):
        _correct(db_session, tenant, farm, user, s["batch"], second.id)


@pytest.mark.integration
def test_carrier_reuse_protection_also_applies_to_seed_tray_path(db_session, active_context_with_farm) -> None:
    """Regression/extension proof: the SAME Carrier-reuse check now guards
    the pre-existing Seed-Tray restoration path too (it previously had no
    such protection at all)."""
    tenant, user, _headers, farm = active_context_with_farm
    s = build_transplant_ready_scenario(
        db_session, tenant, user, farm, tray_count=1, transplanting_required_type="cultivation_plate",
    )
    aid = s["source_assignment_ids"][0]
    dest = s["destination_carriers"][0]
    target = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(dest.id, 200)], [_simple_allocation(aid, dest.id, 200)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    original = db_session.get(BatchCarrierAssignment, aid)
    assert original.released_by_transplant_event_id == target.id

    # Legitimately reuse the now-released Seed Tray Carrier for a fresh
    # sowing -- the real `maintain_carrier_latest_assignment_pointer` DB
    # trigger advances the pointer forward exactly as it would in
    # production, no manual manipulation.
    seeding_station = db_session.execute(
        select(Location).where(
            Location.tenant_id == tenant.id, Location.farm_id == farm.id,
            Location.location_type_id.in_(select(LocationType.id).where(LocationType.code == "seeding_station")),
        )
    ).scalars().first()
    nursery_service.sow_new_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        seed_lot_id=s["seed_lot"].id, seeding_station_id=seeding_station.id, seeding_machine_id=None,
        effective_time=s["entry_time"] + timedelta(hours=4), note=None,
        trays=[{"carrier_id": original.carrier_id, "sown_site_count": 50, "seeds_sown": 50}],
    )

    with pytest.raises(TransplantCorrectionCarrierReusedError):
        _correct(db_session, tenant, farm, user, s["batch"], target.id)


@pytest.mark.integration
def test_multi_generation_restoration_preserves_immediate_predecessor_lineage(
    db_session, active_context_with_farm
) -> None:
    """NURSERY-OPS-005A pre-commit audit correction 1: A -> X exhausts A ->
    correction of X restores B -> Y exhausts B -> correction of Y restores
    C. Proves the restoration chain always points at the IMMEDIATE
    predecessor generation (B.restored_from == A, C.restored_from == B --
    never C.restored_from == A), that every historical generation stays
    permanently released (never reactivated), that each restored
    generation's BatchCarrierPopulationCheckpoint starts its OWN
    independent chain (never continuing an ancestor's), and that the
    unified source-authority resolver -- not a manually reconstructed
    count -- resolves C as the Carrier's current authority with the
    correct population. Structural proof only: every assertion below is
    keyed on `restored_from_batch_carrier_assignment_id` and each
    generation's own checkpoint chain (`previous_checkpoint_id`), never on
    `recorded_at`/`effective_time` ordering."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _nursery_plate_scenario(db_session, tenant, user, farm, tray_count=1)
    aid = s["source_assignment_ids"][0]
    plate1, plate2, plate3 = s["destination_carriers"][0], s["destination_carriers"][1], s["destination_carriers"][2]

    # --- Generation A: Seed Tray -> Plate1, opened with exactly 100. -------
    opening = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(plate1.id, 100)], [_simple_allocation(aid, plate1.id, 100)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    a_assignment = _first_plate_assignment(db_session, opening, plate1, farm, tenant, user, s)
    a_id = a_assignment.id
    a_carrier_id = a_assignment.carrier_id

    # --- X fully exhausts A (100/100) -> A released. ------------------------
    x_event = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(a_id)], [_simple_destination(plate2.id, 100)], [_simple_allocation(a_id, plate2.id, 100)],
        effective_time=s["entry_time"] + timedelta(hours=4),
    )
    a_after_x = db_session.get(BatchCarrierAssignment, a_id)
    assert a_after_x.released_effective_time is not None
    assert a_after_x.released_by_transplant_event_id == x_event.id
    # A's own checkpoint (written by X's consumption of it) -- captured so
    # B's own opening checkpoint can be proven structurally independent
    # from it below, never merely inferred from BCA fields alone.
    a_checkpoint = db_session.execute(
        select(BatchCarrierPopulationCheckpoint).where(
            BatchCarrierPopulationCheckpoint.batch_carrier_assignment_id == a_id
        )
    ).scalar_one()
    assert a_checkpoint.remainder_after == 0

    # --- Correct X -> REVERSAL R restores Generation B. ---------------------
    reversal_r = _correct(db_session, tenant, farm, user, s["batch"], x_event.id)
    assert reversal_r.event_kind == "REVERSAL"

    b_assignment = db_session.execute(
        select(BatchCarrierAssignment).where(
            BatchCarrierAssignment.restored_from_batch_carrier_assignment_id == a_id
        )
    ).scalar_one()
    b_id = b_assignment.id
    assert b_id != a_id
    assert b_assignment.restored_from_batch_carrier_assignment_id == a_id
    assert b_assignment.opening_transplant_reversal_event_id == reversal_r.id
    assert b_assignment.released_effective_time is None
    assert b_assignment.carrier_id == a_carrier_id

    # A must remain released, untouched, after B's creation.
    a_after_b = db_session.get(BatchCarrierAssignment, a_id)
    assert a_after_b.released_effective_time is not None
    assert a_after_b.released_by_transplant_event_id == x_event.id

    b_checkpoint = db_session.execute(
        select(BatchCarrierPopulationCheckpoint).where(
            BatchCarrierPopulationCheckpoint.batch_carrier_assignment_id == b_id
        )
    ).scalar_one()
    assert b_checkpoint.batch_carrier_assignment_id == b_id
    assert b_checkpoint.remainder_after == 100
    assert b_checkpoint.previous_checkpoint_id is None
    # Structurally independent from A's own checkpoint history -- B's chain
    # never continues A's.
    assert b_checkpoint.id != a_checkpoint.id
    assert b_checkpoint.previous_checkpoint_id != a_checkpoint.id

    # Carrier's current generation is B while it remains the tip.
    carrier_after_b = db_session.get(Carrier, a_carrier_id)
    assert carrier_after_b.latest_batch_carrier_assignment_id == b_id

    # --- Y fully exhausts B (100/100) -> B released. ------------------------
    y_event = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(b_id)], [_simple_destination(plate3.id, 100)], [_simple_allocation(b_id, plate3.id, 100)],
        effective_time=s["entry_time"] + timedelta(hours=6),
    )
    b_after_y = db_session.get(BatchCarrierAssignment, b_id)
    assert b_after_y.released_effective_time is not None
    assert b_after_y.released_by_transplant_event_id == y_event.id
    b_consumption_checkpoint = _tip_checkpoint(db_session, b_id)
    assert b_consumption_checkpoint.remainder_after == 0
    assert b_consumption_checkpoint.previous_checkpoint_id == b_checkpoint.id

    # --- Correct Y -> new restored Generation C. -----------------------------
    reversal_r2 = _correct(db_session, tenant, farm, user, s["batch"], y_event.id)
    assert reversal_r2.event_kind == "REVERSAL"

    c_assignment = db_session.execute(
        select(BatchCarrierAssignment).where(
            BatchCarrierAssignment.restored_from_batch_carrier_assignment_id == b_id
        )
    ).scalar_one()
    c_id = c_assignment.id
    assert c_id != b_id
    assert c_id != a_id
    assert c_assignment.restored_from_batch_carrier_assignment_id == b_id
    # The chain must preserve the IMMEDIATE predecessor -- never collapse
    # back onto the root.
    assert c_assignment.restored_from_batch_carrier_assignment_id != a_id
    assert c_assignment.opening_transplant_reversal_event_id == reversal_r2.id
    assert c_assignment.released_effective_time is None
    assert c_assignment.carrier_id == a_carrier_id

    # Both A and B must remain released, untouched, after C's creation.
    a_after_c = db_session.get(BatchCarrierAssignment, a_id)
    assert a_after_c.released_effective_time is not None
    assert a_after_c.released_by_transplant_event_id == x_event.id
    b_after_c = db_session.get(BatchCarrierAssignment, b_id)
    assert b_after_c.released_effective_time is not None
    assert b_after_c.released_by_transplant_event_id == y_event.id

    c_checkpoint = db_session.execute(
        select(BatchCarrierPopulationCheckpoint).where(
            BatchCarrierPopulationCheckpoint.batch_carrier_assignment_id == c_id
        )
    ).scalar_one()
    assert c_checkpoint.batch_carrier_assignment_id == c_id
    assert c_checkpoint.transplant_source_line_id is not None
    assert c_checkpoint.remainder_after == 100
    assert c_checkpoint.previous_checkpoint_id is None
    # Structurally independent from BOTH A's and B's own checkpoint chains.
    assert c_checkpoint.id not in (a_checkpoint.id, b_checkpoint.id, b_consumption_checkpoint.id)
    assert c_checkpoint.previous_checkpoint_id not in (a_checkpoint.id, b_checkpoint.id, b_consumption_checkpoint.id)

    # Carrier's current generation is now C -- A and B are historical.
    carrier_after_c = db_session.get(Carrier, a_carrier_id)
    assert carrier_after_c.latest_batch_carrier_assignment_id == c_id

    # --- Unified resolver proof: C resolves as the current authority. -------
    authority = transplant_source_authority.resolve_source_authority(
        db_session, assignment_id=c_id, carrier_type_code="nursery_cultivation_plate",
    )
    assert authority is not None
    assert authority.kind == "batch_carrier_population"
    resolved_available = transplant_source_authority.get_source_available(
        db_session, authority=authority, assignment_id=c_id, as_of=s["entry_time"] + timedelta(hours=8),
    )
    assert resolved_available == 100
