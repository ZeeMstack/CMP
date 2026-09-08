"""VINES-OPS-001B: InterVines -> Vines Production Transfer (Grow Cube
retained, Grow Bag introduced) composite command.

Domain/service and API coverage: Grow Bag representation/capacity, valid
destination hierarchy, happy path, Grow Cube retention, batch identity
retention, capacity 1/2/3 scenarios (the ticket's three required numeric
proofs), partial transfer, insufficient source population, insufficient
Grow Bag capacity, occupied Grow Bag Position, cross-Farm/tenant isolation,
permissions, idempotency, rollback, and lineage. Concurrency lives in its
own file (`test_vines_production_transfer_concurrency.py`)."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.occupancy import Occupancy
from app.models.transplant_event import TransplantEvent
from app.services import carrier_service, intervines_transplant_service, movement_service, vines_production_transfer_service
from app.services.errors import (
    InsufficientAvailableGrowBagPositionsError,
    InsufficientAvailableGrowBagsError,
    InsufficientAvailableInterVinesPlantsError,
    LocationNotFoundError,
    VinesProductionTransferReplayStateConflictError,
)
from tests._vines_production_scenario import build_vines_production_ready_scenario


def _now(s):
    return s["entry_time"] + timedelta(hours=2)


def _record(db_session, tenant, farm, user, s, plant_count, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), effective_time=_now(s), note=None,
        source_intervines_table_id=s["intervines_table_id"],
        destination_grow_gutter_id=s["grow_gutter_id"], grow_bag_specification_id=s["grow_bag_specification"].id,
    )
    defaults.update(overrides)
    return vines_production_transfer_service.record_vines_production_transfer(
        db_session, plant_count=plant_count, **defaults,
    )


# =====================================================================
# Grow Bag representation / capacity
# =====================================================================


@pytest.mark.integration
def test_bare_unspecified_grow_bag_is_never_selectable(db_session, active_context_with_farm) -> None:
    """`grow_bag` deliberately stays `requires_specification=False` at the
    platform level (flipping it, mirroring `seed_tray`'s own precedent,
    would break ~16 unrelated test scenario helpers across grading/packing/
    harvest/dispatch/traceability/downgrade-guards that use `grow_bag` as an
    arbitrary "any carrier type" default -- the exact blast radius
    `e5b8c3a72f04` already documented deferring for `seed_tray`). Capacity
    correctness is instead guaranteed structurally: `_select_available_grow_
    bags_for_update` filters on a specific `specification_id`, which a bare
    Carrier's `NULL` column can never match -- it is invisible to both the
    pool listing and the transfer command itself, without any platform-wide
    registration restriction."""
    tenant, user, _headers, farm = active_context_with_farm
    bare_bag = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        carrier_type_code="grow_bag", code="GB-BARE-0001", issued_date=None,
    )
    assert bare_bag.specification_id is None

    s = build_vines_production_ready_scenario(
        db_session, tenant, user, farm, intervines_plant_count=1, grow_bag_capacity=1, grow_bag_count=1,
        gutter_bag_positions=1,
    )
    pools = vines_production_transfer_service.list_available_grow_bag_pools(
        db_session, tenant_id=tenant.id, farm_id=farm.id
    )
    matching = next(p for p in pools if p.specification_id == s["grow_bag_specification"].id)
    # Exactly the 1 real, specified Bag -- the bare Bag never inflates this
    # count, since it has no specification_id to match at all.
    assert matching.available_bag_count == 1

    # The transfer itself succeeds using only the real Bag -- the bare one
    # is structurally invisible to `_select_available_grow_bags_for_update`.
    result = _record(db_session, tenant, farm, user, s, 1)
    assert result.grow_bags[0].grow_bag.id != bare_bag.id


@pytest.mark.integration
def test_grow_bag_pool_and_capacity_config(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = build_vines_production_ready_scenario(
        db_session, tenant, user, farm, intervines_plant_count=4, grow_bag_capacity=2, grow_bag_count=10,
    )
    pools = vines_production_transfer_service.list_available_grow_bag_pools(
        db_session, tenant_id=tenant.id, farm_id=farm.id
    )
    assert len(pools) == 1
    assert pools[0].specification_id == s["grow_bag_specification"].id
    assert pools[0].available_bag_count == 10
    assert pools[0].available_plant_capacity == 20


# =====================================================================
# Numeric proofs (capacity 1 / 2 / 3)
# =====================================================================


@pytest.mark.integration
def test_scenario_1_capacity_2_numeric_proof(db_session, active_context_with_farm) -> None:
    """Ticket Scenario 1: InterVines available = 72, capacity 2/bag, 40
    bags/positions available, transfer 72 -> 36 Bags used, 36 positions
    occupied, InterVines remaining = 0, Production living population = 72."""
    tenant, user, _headers, farm = active_context_with_farm
    s = build_vines_production_ready_scenario(
        db_session, tenant, user, farm, intervines_plant_count=72, grow_bag_capacity=2, grow_bag_count=40,
        gutter_bag_positions=40,
    )
    result = _record(db_session, tenant, farm, user, s, 72)

    assert result.plant_count == 72
    assert len(result.source_grow_cubes) == 72
    assert len(result.grow_bags) == 36
    assert sum(gb.assigned_plant_count for gb in result.grow_bags) == 72
    assert {gb.assigned_plant_count for gb in result.grow_bags} == {2}

    placements = vines_production_transfer_service.list_vines_production_placements(
        db_session, tenant_id=tenant.id, farm_id=farm.id
    )
    assert len(placements) == 1
    assert placements[0].plant_count == 72

    intervines_remaining = _intervines_remaining_plants(db_session, tenant, farm, s)
    assert intervines_remaining == 0

    # Physical reconciliation (frozen rule: the Grow Cube moves WITH the
    # plant): 0 of the 72 transferred Grow Cubes retain an active Occupancy
    # anywhere -- each was physically released from the InterVines Table,
    # not merely dropped from the read view via a released assignment.
    active_grow_cube_occupancies = db_session.execute(
        select(Occupancy).where(
            Occupancy.occupant_carrier_id.in_([c.id for c in result.source_grow_cubes]),
            Occupancy.end_time.is_(None),
        )
    ).scalars().all()
    assert active_grow_cube_occupancies == []

    # 72 Grow Cubes represented in production, resolvable via the same
    # backward lineage chain the drill-down read model uses.
    bag_details = vines_production_transfer_service.list_vines_production_placement_grow_bags(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=s["batch"].id, gutter_id=s["grow_gutter_id"],
    )
    assert len(bag_details) == 36
    assert sum(len(b.grow_cubes) for b in bag_details) == 72

    # 36 Grow Bags physically occupied at production Grow Bag Positions.
    from app.models.carrier import Carrier
    from app.models.carrier_type import CarrierType

    occupied_bag_count = db_session.execute(
        select(Occupancy)
        .join(Carrier, Carrier.id == Occupancy.occupant_carrier_id)
        .join(CarrierType, CarrierType.id == Carrier.carrier_type_id)
        .where(
            Occupancy.occupant_carrier_id.in_([gb.grow_bag.id for gb in result.grow_bags]),
            Occupancy.end_time.is_(None), CarrierType.code == "grow_bag",
        )
    ).scalars().all()
    assert len(occupied_bag_count) == 36


@pytest.mark.integration
def test_scenario_2_insufficient_grow_bag_capacity_rejects_atomically(db_session, active_context_with_farm) -> None:
    """Ticket Scenario 2: InterVines available = 50, capacity 2/bag, 20 bags
    (40 total capacity), request 45 -> rejected atomically, InterVines
    remaining = 50, no new production placement."""
    tenant, user, _headers, farm = active_context_with_farm
    s = build_vines_production_ready_scenario(
        db_session, tenant, user, farm, intervines_plant_count=50, grow_bag_capacity=2, grow_bag_count=20,
        gutter_bag_positions=20,
    )
    with pytest.raises(InsufficientAvailableGrowBagsError):
        _record(db_session, tenant, farm, user, s, 45)

    assert _intervines_remaining_plants(db_session, tenant, farm, s) == 50
    placements = vines_production_transfer_service.list_vines_production_placements(
        db_session, tenant_id=tenant.id, farm_id=farm.id
    )
    assert placements == []
    # Scoped to grow_bag-typed occupants only -- a global/unscoped query
    # would also pick up the scenario's own unrelated active Occupancies
    # (e.g. the germination trolley in its chamber).
    from app.models.carrier import Carrier
    from app.models.carrier_type import CarrierType

    active_bag_occupancies = db_session.execute(
        select(Occupancy)
        .join(Carrier, Carrier.id == Occupancy.occupant_carrier_id)
        .join(CarrierType, CarrierType.id == Carrier.carrier_type_id)
        .where(Occupancy.end_time.is_(None), CarrierType.code == "grow_bag")
    ).scalars().all()
    assert active_bag_occupancies == []


@pytest.mark.integration
def test_scenario_3_capacity_3_deterministic_fill(db_session, active_context_with_farm) -> None:
    """Ticket Scenario 3: InterVines available = 20, capacity 3/bag,
    transfer 20 -> 7 Bags (6 carrying 3, 1 carrying 2), total 20 plants."""
    tenant, user, _headers, farm = active_context_with_farm
    s = build_vines_production_ready_scenario(
        db_session, tenant, user, farm, intervines_plant_count=20, grow_bag_capacity=3, grow_bag_count=10,
        gutter_bag_positions=10,
    )
    result = _record(db_session, tenant, farm, user, s, 20)

    assert len(result.grow_bags) == 7
    counts = sorted((gb.assigned_plant_count for gb in result.grow_bags), reverse=True)
    assert counts == [3, 3, 3, 3, 3, 3, 2]
    assert sum(counts) == 20


def _intervines_remaining_plants(db_session, tenant, farm, s) -> int:
    placements = intervines_transplant_service.list_intervines_placements(
        db_session, tenant_id=tenant.id, farm_id=farm.id
    )
    return sum(p.plant_count for p in placements)


# =====================================================================
# Partial transfer / Grow Cube retention / batch identity
# =====================================================================


@pytest.mark.integration
def test_partial_transfer_retains_grow_cubes_and_batch_identity(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = build_vines_production_ready_scenario(
        db_session, tenant, user, farm, intervines_plant_count=10, grow_bag_capacity=1, grow_bag_count=6,
        gutter_bag_positions=6,
    )
    result = _record(db_session, tenant, farm, user, s, 6)

    assert result.batch_id == s["batch"].id
    assert result.batch_code == s["batch"].code
    assert len(result.source_grow_cubes) == 6
    assert len(result.grow_bags) == 6

    # Grow Cube retention + the frozen "moves with the plant" rule: each
    # source Grow Cube's InterVines Occupancy is CLOSED (no longer active
    # anywhere at the source Table), its historical row still names that
    # Table (lineage preserved), and it has no other active Occupancy --
    # the Grow Cube is retained and its identity persists, but it no
    # longer physically reads as present at InterVines.
    for cube in result.source_grow_cubes:
        no_active_occupancy = db_session.execute(
            select(Occupancy).where(Occupancy.occupant_carrier_id == cube.id, Occupancy.end_time.is_(None))
        ).scalar_one_or_none()
        assert no_active_occupancy is None
        closed_occupancy = db_session.execute(
            select(Occupancy).where(
                Occupancy.occupant_carrier_id == cube.id, Occupancy.target_location_id == s["intervines_table_id"],
            )
        ).scalar_one()
        assert closed_occupancy.end_time is not None
        cube_assignment = db_session.execute(
            select(BatchCarrierAssignment).where(
                BatchCarrierAssignment.carrier_id == cube.id, BatchCarrierAssignment.batch_id == s["batch"].id,
            )
        ).scalar_one()
        assert cube_assignment.released_effective_time is not None

    # InterVines remaining reflects only the 4 un-transferred plants.
    assert _intervines_remaining_plants(db_session, tenant, farm, s) == 4

    # No new Batch was created.
    from app.models.crop_batch import CropBatch

    batches = db_session.execute(
        select(CropBatch).where(CropBatch.tenant_id == tenant.id, CropBatch.farm_id == farm.id)
    ).scalars().all()
    assert len(batches) == 1
    assert batches[0].id == s["batch"].id


# =====================================================================
# Grow Cube physical movement closure (frozen rule: the Grow Cube moves
# WITH the plant -- its InterVines Occupancy must be closed, not left
# stale, once the plant is placed in a production Grow Bag)
# =====================================================================


@pytest.mark.integration
def test_grow_cube_occupancy_closed_and_linked_to_assigned_grow_bag(db_session, active_context_with_farm) -> None:
    """1. Before transfer, each Grow Cube has an active InterVines
    occupancy. 2. After transfer: that occupancy is no longer active (but
    its historical row still names the InterVines Table -- lineage is
    preserved); the same Grow Cube resolves, via the drill-down read model,
    to the one Grow Bag it was actually assigned to; and that Grow Bag
    occupies exactly one Grow Bag Position under the destination Gutter."""
    tenant, user, _headers, farm = active_context_with_farm
    s = build_vines_production_ready_scenario(
        db_session, tenant, user, farm, intervines_plant_count=3, grow_bag_capacity=1, grow_bag_count=3,
        gutter_bag_positions=3,
    )

    # Before: every source Grow Cube is actively occupying the InterVines Table.
    pre_occupancies = db_session.execute(
        select(Occupancy).where(
            Occupancy.target_location_id == s["intervines_table_id"], Occupancy.end_time.is_(None),
        )
    ).scalars().all()
    assert len(pre_occupancies) == 3
    pre_active_carrier_ids = {o.occupant_carrier_id for o in pre_occupancies}

    result = _record(db_session, tenant, farm, user, s, 3)
    assert len(result.source_grow_cubes) == 3
    assert {c.id for c in result.source_grow_cubes} == pre_active_carrier_ids

    for cube in result.source_grow_cubes:
        # No longer active anywhere.
        active_now = db_session.execute(
            select(Occupancy).where(Occupancy.occupant_carrier_id == cube.id, Occupancy.end_time.is_(None))
        ).scalar_one_or_none()
        assert active_now is None
        # Historical lineage preserved: it WAS at the InterVines Table.
        closed = db_session.execute(
            select(Occupancy).where(
                Occupancy.occupant_carrier_id == cube.id, Occupancy.target_location_id == s["intervines_table_id"],
            )
        ).scalar_one()
        assert closed.end_time is not None

    # Same Grow Cube resolves to its assigned Grow Bag, which occupies
    # exactly one Grow Bag Position under the destination Gutter.
    drill_down = vines_production_transfer_service.list_vines_production_placement_grow_bags(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=s["batch"].id, gutter_id=s["grow_gutter_id"],
    )
    resolved_cube_ids = {cube.grow_cube.id for row in drill_down for cube in row.grow_cubes}
    assert resolved_cube_ids == {c.id for c in result.source_grow_cubes}
    for row in drill_down:
        assert row.grow_bag_position_code is not None


@pytest.mark.integration
def test_transferred_grow_cube_cannot_be_transferred_again(db_session, active_context_with_farm) -> None:
    """3. The same Grow Cube cannot be transferred again: once its whole
    InterVines pool is consumed, a further request against the same source
    fails -- it can never be reselected (its `BatchCarrierAssignment` is
    released and its Occupancy is closed, both excluding it from the
    source-selection query). 4. Consequently one Grow Cube can never be
    linked to two active Grow Bags: exactly one `TransplantAllocation`
    exists for its source line, both before and after the failed retry."""
    tenant, user, _headers, farm = active_context_with_farm
    s = build_vines_production_ready_scenario(
        db_session, tenant, user, farm, intervines_plant_count=3, grow_bag_capacity=1, grow_bag_count=6,
        gutter_bag_positions=6,
    )
    from app.models.transplant_allocation import TransplantAllocation
    from app.models.transplant_source_line import TransplantSourceLine

    result = _record(db_session, tenant, farm, user, s, 3)
    first_cube_id = result.source_grow_cubes[0].id

    allocation_count_query = (
        select(TransplantAllocation)
        .join(TransplantSourceLine, TransplantSourceLine.id == TransplantAllocation.source_line_id)
        .where(TransplantSourceLine.source_carrier_id == first_cube_id)
    )
    assert len(db_session.execute(allocation_count_query).scalars().all()) == 1

    # The InterVines source is now fully exhausted -- a further request
    # (even for just 1 plant) cannot reselect any already-transferred Grow
    # Cube, because none remain eligible.
    with pytest.raises(InsufficientAvailableInterVinesPlantsError):
        _record(db_session, tenant, farm, user, s, 1, client_command_id=uuid.uuid4())

    # Still exactly one allocation for the first Grow Cube -- never doubled.
    assert len(db_session.execute(allocation_count_query).scalars().all()) == 1


@pytest.mark.integration
def test_atomic_rollback_restores_original_intervines_occupancy(
    db_session, active_context_with_farm, monkeypatch,
) -> None:
    """5. If destination placement fails partway through, the original
    InterVines Grow Cube occupancy remains fully intact and no production
    association survives -- proven by forcing the first Grow Bag placement
    Movement to fail after the biological Transplant (source release) has
    already flushed, then asserting everything rolls back together."""
    from app.models.carrier import Carrier
    from app.models.carrier_type import CarrierType

    tenant, user, _headers, farm = active_context_with_farm
    s = build_vines_production_ready_scenario(
        db_session, tenant, user, farm, intervines_plant_count=3, grow_bag_capacity=1, grow_bag_count=3,
        gutter_bag_positions=3,
    )
    pre_occupancies = db_session.execute(
        select(Occupancy).where(
            Occupancy.target_location_id == s["intervines_table_id"], Occupancy.end_time.is_(None),
        )
    ).scalars().all()
    assert len(pre_occupancies) == 3

    class _ForcedMovementFailure(Exception):
        pass

    def _raise(*args, **kwargs):
        raise _ForcedMovementFailure("forced failure before any Grow Bag placement Movement")

    monkeypatch.setattr(vines_production_transfer_service.movement_service, "_execute_movement_core", _raise)

    with pytest.raises(_ForcedMovementFailure):
        _record(db_session, tenant, farm, user, s, 3)

    # Nothing committed: InterVines occupancies untouched, source
    # assignments un-released, no TransplantEvent for this command survives.
    post_occupancies = db_session.execute(
        select(Occupancy).where(
            Occupancy.target_location_id == s["intervines_table_id"], Occupancy.end_time.is_(None),
        )
    ).scalars().all()
    assert {o.id for o in post_occupancies} == {o.id for o in pre_occupancies}
    events = db_session.execute(
        select(TransplantEvent).where(TransplantEvent.batch_id == s["batch"].id)
    ).scalars().all()
    # Only the scenario's own InterVines transplant (VINES-OPS-001A) --
    # the rejected Production transfer added zero events.
    assert len(events) == 1
    grow_cube_assignments = db_session.execute(
        select(BatchCarrierAssignment)
        .join(Carrier, Carrier.id == BatchCarrierAssignment.carrier_id)
        .join(CarrierType, CarrierType.id == Carrier.carrier_type_id)
        .where(BatchCarrierAssignment.batch_id == s["batch"].id, CarrierType.code == "grow_cube")
    ).scalars().all()
    assert all(a.released_effective_time is None for a in grow_cube_assignments)


@pytest.mark.integration
def test_insufficient_source_population_rejects_atomically(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = build_vines_production_ready_scenario(
        db_session, tenant, user, farm, intervines_plant_count=5, grow_bag_capacity=1, grow_bag_count=20,
        gutter_bag_positions=20,
    )
    with pytest.raises(InsufficientAvailableInterVinesPlantsError):
        _record(db_session, tenant, farm, user, s, 8)

    # Scoped to this Batch's own events -- the scenario's own InterVines
    # transplant (VINES-OPS-001A) already committed exactly one; the
    # rejected Production transfer must add zero more.
    events = db_session.execute(select(TransplantEvent).where(TransplantEvent.batch_id == s["batch"].id)).scalars().all()
    assert len(events) == 1
    assert _intervines_remaining_plants(db_session, tenant, farm, s) == 5


@pytest.mark.integration
def test_occupied_grow_bag_position_rejects_atomically(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = build_vines_production_ready_scenario(
        db_session, tenant, user, farm, intervines_plant_count=5, grow_bag_capacity=1, grow_bag_count=5,
        gutter_bag_positions=1,
    )
    # Pre-occupy the Gutter's ONE Grow Bag Position with an unrelated Grow
    # Bag via a direct Movement -- never through this composite.
    filler_bag = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        specification_id=s["grow_bag_specification"].id, code="GB-FILLER-0001", issued_date=None,
    )
    from app.models.location import Location
    from app.models.location_type import LocationType

    position_type = db_session.execute(select(LocationType).where(LocationType.code == "grow_bag_position")).scalar_one()
    position = db_session.execute(
        select(Location).where(Location.parent_location_id == s["grow_gutter_id"], Location.location_type_id == position_type.id)
    ).scalars().first()
    movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        effective_time=_now(s), occupant_kind="carrier", occupant_id=filler_bag.id,
        destination_kind="location", destination_id=position.id, reason=None,
    )

    with pytest.raises(InsufficientAvailableGrowBagPositionsError):
        _record(db_session, tenant, farm, user, s, 1)
    assert _intervines_remaining_plants(db_session, tenant, farm, s) == 5


@pytest.mark.integration
def test_wrong_destination_gutter_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = build_vines_production_ready_scenario(
        db_session, tenant, user, farm, intervines_plant_count=5, grow_bag_capacity=1, grow_bag_count=5,
        gutter_bag_positions=5,
    )
    with pytest.raises(LocationNotFoundError):
        _record(db_session, tenant, farm, user, s, 1, destination_grow_gutter_id=uuid.uuid4())


# =====================================================================
# Idempotency
# =====================================================================


@pytest.mark.integration
def test_exact_replay_returns_same_result(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = build_vines_production_ready_scenario(
        db_session, tenant, user, farm, intervines_plant_count=10, grow_bag_capacity=2, grow_bag_count=10,
        gutter_bag_positions=10,
    )
    command_id = uuid.uuid4()
    first = _record(db_session, tenant, farm, user, s, 6, client_command_id=command_id)
    second = _record(db_session, tenant, farm, user, s, 6, client_command_id=command_id)

    assert first.id == second.id
    assert {c.id for c in first.source_grow_cubes} == {c.id for c in second.source_grow_cubes}
    assert {gb.grow_bag.id for gb in first.grow_bags} == {gb.grow_bag.id for gb in second.grow_bags}
    # 2 total: the scenario's own InterVines transplant (VINES-OPS-001A)
    # plus exactly one Production transfer event -- the exact replay must
    # never add a third.
    events = db_session.execute(select(TransplantEvent).where(TransplantEvent.batch_id == s["batch"].id)).scalars().all()
    assert len(events) == 2


@pytest.mark.integration
def test_replay_with_different_plant_count_conflicts(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = build_vines_production_ready_scenario(
        db_session, tenant, user, farm, intervines_plant_count=10, grow_bag_capacity=2, grow_bag_count=10,
        gutter_bag_positions=10,
    )
    command_id = uuid.uuid4()
    _record(db_session, tenant, farm, user, s, 6, client_command_id=command_id)
    with pytest.raises(VinesProductionTransferReplayStateConflictError):
        _record(db_session, tenant, farm, user, s, 8, client_command_id=command_id)


# =====================================================================
# Lineage
# =====================================================================


@pytest.mark.integration
def test_lineage_grow_bag_to_grow_cube_to_seed_tray(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = build_vines_production_ready_scenario(
        db_session, tenant, user, farm, intervines_plant_count=3, grow_bag_capacity=2, grow_bag_count=5,
        gutter_bag_positions=5,
    )
    result = _record(db_session, tenant, farm, user, s, 3)

    drill_down = vines_production_transfer_service.list_vines_production_placement_grow_bags(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=s["batch"].id, gutter_id=s["grow_gutter_id"],
    )
    total_cubes = sum(len(row.grow_cubes) for row in drill_down)
    assert total_cubes == 3
    seed_tray_codes = {
        cube.source_seed_tray.code
        for row in drill_down
        for cube in row.grow_cubes
        if cube.source_seed_tray is not None
    }
    assert seed_tray_codes == {_tray_code_for(db_session, s)}


def _tray_code_for(db_session, s) -> str:
    from app.models.batch_carrier_assignment import BatchCarrierAssignment
    from app.models.carrier import Carrier

    assignment = db_session.get(BatchCarrierAssignment, s["source_assignment_ids"][0])
    carrier = db_session.get(Carrier, assignment.carrier_id)
    return carrier.code


# =====================================================================
# Tenant / Farm isolation
# =====================================================================


@pytest.mark.integration
def test_cross_farm_batch_rejected(db_session, active_context_with_farm) -> None:
    """The Batch's own Farm never resolves under a different Farm id --
    here the earliest structural check to fire is the destination Grow
    Gutter lookup (`other_farm` has no Vines Production topology at all),
    which is itself a farm-isolation proof: this Batch's real Gutter is
    simply invisible under any other Farm id."""
    from app.services import farm_service

    tenant, user, _headers, farm = active_context_with_farm
    s = build_vines_production_ready_scenario(db_session, tenant, user, farm, intervines_plant_count=5)
    other_farm = farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code="other-farm-vp", name="Other Farm VP",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    with pytest.raises(LocationNotFoundError):
        vines_production_transfer_service.record_vines_production_transfer(
            db_session, tenant_id=tenant.id, farm_id=other_farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
            client_command_id=uuid.uuid4(), effective_time=_now(s), note=None,
            source_intervines_table_id=s["intervines_table_id"], plant_count=1,
            destination_grow_gutter_id=s["grow_gutter_id"], grow_bag_specification_id=s["grow_bag_specification"].id,
        )


# =====================================================================
# Authorization (HTTP)
# =====================================================================


@pytest.mark.integration
def test_transplant_manage_sufficient_via_http(client, active_context_with_farm, db_session) -> None:
    tenant, user, headers, farm = active_context_with_farm
    s = build_vines_production_ready_scenario(
        db_session, tenant, user, farm, intervines_plant_count=5, grow_bag_capacity=1, grow_bag_count=5,
        gutter_bag_positions=5,
    )
    db_session.commit()

    resp = client.post(
        f"/farms/{farm.id}/crop-batches/{s['batch'].id}/vines-production-transfers", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now(s).isoformat(), "note": None,
            "source_intervines_table_id": str(s["intervines_table_id"]), "plant_count": 3,
            "destination_grow_gutter_id": str(s["grow_gutter_id"]),
            "grow_bag_specification_id": str(s["grow_bag_specification"].id),
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["plant_count"] == 3
    assert len(body["grow_bags"]) == 3


@pytest.mark.integration
def test_storekeeper_role_without_transplant_manage_denied_via_http(client, active_context_with_farm, db_session) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    from app.services import membership_service, user_service

    s = build_vines_production_ready_scenario(
        db_session, tenant, user, farm, intervines_plant_count=5, grow_bag_capacity=1, grow_bag_count=5,
        gutter_bag_positions=5,
    )
    db_session.commit()
    storekeeper = user_service.create_user(
        db_session, oidc_issuer="iss", oidc_subject="vp-sk", email="vp-sk@example.com", display_name="Storekeeper",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant.id, user_id=storekeeper.id, role_code="storekeeper", actor_user_id=None
    )
    db_session.commit()
    op_headers = {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(storekeeper.id)}

    resp = client.post(
        f"/farms/{farm.id}/crop-batches/{s['batch'].id}/vines-production-transfers", headers=op_headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now(s).isoformat(), "note": None,
            "source_intervines_table_id": str(s["intervines_table_id"]), "plant_count": 3,
            "destination_grow_gutter_id": str(s["grow_gutter_id"]),
            "grow_bag_specification_id": str(s["grow_bag_specification"].id),
        },
    )
    assert resp.status_code == 403, resp.text
