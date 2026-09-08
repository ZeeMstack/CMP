"""VINES-OPS-001A: InterVines Transplant (Seed Tray -> Grow Cube -> InterVines
Table) composite command.

Domain/service and API coverage for the composite: happy path, partial
transfer, the ticket's two required numeric proofs, insufficient-seedling and
insufficient-Grow-Cube atomic rejection, wrong-destination-type rejection,
tenant/Farm isolation, permissions, idempotency (including a materially
different payload conflict), lineage, and the read views. Concurrency lives
in its own file (`test_intervines_transplant_concurrency.py`). Does not
duplicate existing `test_transplant.py`/`test_movement*.py` coverage for
behavior the composite reuses unchanged (source reconciliation math, Movement
occupancy-compatibility/capacity enforcement)."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.movement import Movement
from app.models.occupancy import Occupancy
from app.models.transplant_event import TransplantEvent
from app.services import carrier_service, intervines_transplant_service, transplant_service
from app.services.errors import (
    DestinationCarrierAlreadyAssignedError,
    IncompatibleOccupantTargetError,
    InsufficientAvailableGrowCubesError,
    IntervinesTransplantReplayStateConflictError,
    TransplantValidationError,
)
from tests._transplant_scenario import build_transplant_ready_scenario, now as _now

DESTINATION_TYPE = "grow_cube"


def _build_scenario(db_session, tenant, user, farm, *, tray_count=1, table_capacity=1000, **overrides):
    # An InterVines Table holds many Grow Cubes simultaneously (mirrors an
    # InterSalads Table holding many Plates) -- `movement_service`'s own
    # capacity rule treats a NULL `capacity` as effectively 1 (exclusive,
    # backward-compatible default), so every test here needs an explicit,
    # generously-sized capacity, never the bare default.
    return build_transplant_ready_scenario(
        db_session, tenant, user, farm, tray_count=tray_count, transplanting_required_type=DESTINATION_TYPE,
        intervines_table_count=1, intervines_table_capacity=table_capacity, **overrides,
    )


def _add_grow_cubes(db_session, tenant, user, farm, *, count, prefix):
    return carrier_service.bulk_register_carriers(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        carrier_type_code=DESTINATION_TYPE, code_prefix=prefix, start=1, end=count, pad_width=4,
    )


def _record(db_session, tenant, farm, user, batch, source_assignment_id, plant_count, destination_location_id, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
        grow_cube_specification_id=None,
    )
    defaults.update(overrides)
    return intervines_transplant_service.record_intervines_transplant(
        db_session, source_assignment_id=source_assignment_id, plant_count=plant_count,
        destination_location_id=destination_location_id, **defaults,
    )


# =====================================================================
# Happy path / numeric proofs
# =====================================================================


@pytest.mark.integration
def test_partial_transplant_with_placement(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, normal=100)
    _add_grow_cubes(db_session, tenant, user, farm, count=120, prefix="GC-A-")
    aid = s["source_assignment_ids"][0]
    table_id = s["intervines_table_ids"][0]

    result = _record(
        db_session, tenant, farm, user, s["batch"], aid, 72, table_id,
        effective_time=s["entry_time"] + timedelta(hours=2),
    )

    assert result.plant_count == 72
    assert len(result.grow_cubes) == 72
    assert result.total_remainder_after == 100 - 72
    assert {gc.destination_location_id for gc in result.grow_cubes} == {table_id}

    # Every allocated Grow Cube: exactly one live BatchCarrierAssignment and
    # one live Occupancy at the requested Table.
    for gc in result.grow_cubes:
        assignment = db_session.get(BatchCarrierAssignment, gc.destination_batch_carrier_assignment_id)
        assert assignment.released_effective_time is None
        movement = db_session.get(Movement, gc.movement_id)
        assert movement.occupant_carrier_id == gc.carrier.id
        assert movement.destination_location_id == table_id
        active_occupancy = db_session.execute(
            select(Occupancy).where(Occupancy.occupant_carrier_id == gc.carrier.id, Occupancy.end_time.is_(None))
        ).scalar_one()
        assert active_occupancy.target_location_id == table_id


@pytest.mark.integration
def test_scenario_1_numeric_proof(db_session, active_context_with_farm) -> None:
    """Ticket Scenario 1: Seedling available = 100, available Grow Cubes =
    120, transfer = 72 -> remaining seedlings 28, 72 Grow Cubes occupied, 72
    InterVines living population."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, normal=100)
    _add_grow_cubes(db_session, tenant, user, farm, count=120, prefix="GC-S1-")
    aid = s["source_assignment_ids"][0]
    table_id = s["intervines_table_ids"][0]

    result = _record(
        db_session, tenant, farm, user, s["batch"], aid, 72, table_id,
        effective_time=s["entry_time"] + timedelta(hours=2),
    )

    assert result.total_source_available_before == 100
    assert result.total_remainder_after == 28
    assert result.plant_count == 72
    placements = intervines_transplant_service.list_intervines_placements(
        db_session, tenant_id=tenant.id, farm_id=farm.id
    )
    assert len(placements) == 1
    assert placements[0].plant_count == 72
    assert placements[0].batch_id == s["batch"].id


@pytest.mark.integration
def test_scenario_2_insufficient_grow_cubes_rejects_atomically(db_session, active_context_with_farm) -> None:
    """Ticket Scenario 2: Seedling available = 30, available Grow Cubes =
    20, request = 25 -> command rejected atomically, seedling remaining 30,
    Grow Cubes occupied 0."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, normal=30)
    _add_grow_cubes(db_session, tenant, user, farm, count=16, prefix="GC-S2-")  # 4 already from the scenario + 16 = 20
    aid = s["source_assignment_ids"][0]
    table_id = s["intervines_table_ids"][0]

    with pytest.raises(InsufficientAvailableGrowCubesError):
        _record(
            db_session, tenant, farm, user, s["batch"], aid, 25, table_id,
            effective_time=s["entry_time"] + timedelta(hours=2),
        )

    assert db_session.execute(select(TransplantEvent)).scalars().first() is None
    assignment = db_session.get(BatchCarrierAssignment, aid)
    assert assignment.released_effective_time is None
    # Scoped to the InterVines Table itself -- the scenario's own setup
    # (germination trolley in its chamber, the source Tray on its Seedling
    # Table) legitimately holds unrelated active Occupancies elsewhere;
    # only the Table this command targeted must show zero.
    occupied = db_session.execute(
        select(Occupancy).where(Occupancy.target_location_id == table_id, Occupancy.end_time.is_(None))
    ).scalars().all()
    assert occupied == []


@pytest.mark.integration
def test_already_occupied_grow_cubes_excluded_from_pool(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=2, normal=50)
    _add_grow_cubes(db_session, tenant, user, farm, count=6, prefix="GC-OCC-")  # 4 + 6 = 10 total
    table_id = s["intervines_table_ids"][0]

    # Consume 8 of the 10 available Grow Cubes with a first command.
    first = _record(
        db_session, tenant, farm, user, s["batch"], s["source_assignment_ids"][0], 8, table_id,
        effective_time=s["entry_time"] + timedelta(hours=1),
    )
    assert first.plant_count == 8

    # Only 2 remain -- requesting 3 from the second source must reject
    # atomically without touching the 2 that ARE available.
    with pytest.raises(InsufficientAvailableGrowCubesError):
        _record(
            db_session, tenant, farm, user, s["batch"], s["source_assignment_ids"][1], 3, table_id,
            effective_time=s["entry_time"] + timedelta(hours=2),
        )
    assignment = db_session.get(BatchCarrierAssignment, s["source_assignment_ids"][1])
    assert assignment.released_effective_time is None


@pytest.mark.integration
def test_wrong_destination_location_type_rejected(db_session, active_context_with_farm) -> None:
    """A Seedling Table (not an InterVines Table) is not occupancy-
    compatible with a `grow_cube` Carrier -- rejected by the pre-existing,
    unmodified `movement_service._check_compatibility`, never a new check
    this composite invents."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    _add_grow_cubes(db_session, tenant, user, farm, count=10, prefix="GC-WD-")
    aid = s["source_assignment_ids"][0]
    # The scenario's own single Tray already occupies seedling_table_ids[0]
    # at its own capacity (`tray_count`) -- picking that one here would hit
    # `TargetOccupiedError` before `movement_service._execute_movement_core`
    # ever reaches its compatibility check (capacity is checked first in
    # that shared, unmodified core). seedling_table_ids[1] is a genuinely
    # empty Seedling Table of the wrong type, so this actually exercises
    # the compatibility rejection this test is named for.
    wrong_location_id = s["seedling_table_ids"][1]

    with pytest.raises(IncompatibleOccupantTargetError):
        _record(
            db_session, tenant, farm, user, s["batch"], aid, 5, wrong_location_id,
            effective_time=s["entry_time"] + timedelta(hours=2),
        )


@pytest.mark.integration
def test_wrong_required_carrier_type_rejected(db_session, active_context_with_farm) -> None:
    """The Batch's own TRANSPLANTING stage requires a different Carrier type
    than `grow_cube` -- `_record_transplant_core`'s own unmodified stage-type
    check rejects this before any Grow Cube is ever touched."""
    tenant, user, _headers, farm = active_context_with_farm
    s = build_transplant_ready_scenario(
        db_session, tenant, user, farm, tray_count=1, transplanting_required_type="cultivation_plate",
        intervines_table_count=1,
    )
    _add_grow_cubes(db_session, tenant, user, farm, count=10, prefix="GC-WT-")
    aid = s["source_assignment_ids"][0]
    table_id = s["intervines_table_ids"][0]

    with pytest.raises(TransplantValidationError):
        _record(
            db_session, tenant, farm, user, s["batch"], aid, 5, table_id,
            effective_time=s["entry_time"] + timedelta(hours=2),
        )


@pytest.mark.integration
def test_specification_scoped_pool(db_session, active_context_with_farm) -> None:
    from app.services import carrier_specification_service

    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, normal=100)
    table_id = s["intervines_table_ids"][0]
    spec = carrier_specification_service.register_carrier_specification(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, carrier_type_code=DESTINATION_TYPE,
        code=f"GC-SPEC-{uuid.uuid4().hex[:6]}", name="4cm Rockwool Cube", length_mm=40, width_mm=40, height_mm=40,
        biological_position_count=1,
    )
    carrier_service.bulk_register_carriers(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, specification_id=spec.id,
        code_prefix="GC-SP-", start=1, end=5, pad_width=3,
    )
    _add_grow_cubes(db_session, tenant, user, farm, count=10, prefix="GC-UNSPEC-")

    pools = intervines_transplant_service.list_available_grow_cube_pools(db_session, tenant_id=tenant.id, farm_id=farm.id)
    by_spec = {p.specification_id: p.available_count for p in pools}
    assert by_spec[spec.id] == 5
    assert by_spec[None] == 14  # 4 from the base scenario + 10 unspecified

    aid = s["source_assignment_ids"][0]
    result = _record(
        db_session, tenant, farm, user, s["batch"], aid, 5, table_id,
        grow_cube_specification_id=spec.id, effective_time=s["entry_time"] + timedelta(hours=2),
    )
    assert {gc.carrier.id for gc in result.grow_cubes} == {c.id for c in carrier_service.list_carriers(
        db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_type_code=DESTINATION_TYPE
    ) if c.specification_id == spec.id}


# =====================================================================
# Idempotency
# =====================================================================


@pytest.mark.integration
def test_exact_replay_returns_same_result_no_duplicate_rows(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, normal=100)
    _add_grow_cubes(db_session, tenant, user, farm, count=40, prefix="GC-IDEM-")
    aid = s["source_assignment_ids"][0]
    table_id = s["intervines_table_ids"][0]
    command_id = uuid.uuid4()

    first = _record(
        db_session, tenant, farm, user, s["batch"], aid, 10, table_id, client_command_id=command_id,
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    second = _record(
        db_session, tenant, farm, user, s["batch"], aid, 10, table_id, client_command_id=command_id,
        effective_time=s["entry_time"] + timedelta(hours=2),
    )

    assert first.id == second.id
    assert {gc.carrier.id for gc in first.grow_cubes} == {gc.carrier.id for gc in second.grow_cubes}
    assert {gc.movement_id for gc in first.grow_cubes} == {gc.movement_id for gc in second.grow_cubes}
    event_count = db_session.execute(
        select(TransplantEvent).where(TransplantEvent.batch_id == s["batch"].id)
    ).scalars().all()
    assert len(event_count) == 1
    # Scoped to the InterVines Table itself (see test_scenario_2's own
    # identical comment) -- the scenario's germination/seedling setup
    # legitimately holds unrelated active Occupancies elsewhere.
    active_occupancies = db_session.execute(
        select(Occupancy).where(Occupancy.target_location_id == table_id, Occupancy.end_time.is_(None))
    ).scalars().all()
    assert len(active_occupancies) == 10


@pytest.mark.integration
def test_replay_with_different_plant_count_conflicts(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, normal=100)
    _add_grow_cubes(db_session, tenant, user, farm, count=40, prefix="GC-CONF-")
    aid = s["source_assignment_ids"][0]
    table_id = s["intervines_table_ids"][0]
    command_id = uuid.uuid4()

    _record(
        db_session, tenant, farm, user, s["batch"], aid, 10, table_id, client_command_id=command_id,
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    with pytest.raises(IntervinesTransplantReplayStateConflictError):
        _record(
            db_session, tenant, farm, user, s["batch"], aid, 12, table_id, client_command_id=command_id,
            effective_time=s["entry_time"] + timedelta(hours=2),
        )


# =====================================================================
# Tenant / Farm isolation
# =====================================================================


@pytest.mark.integration
def test_grow_cube_pool_is_farm_scoped(db_session, active_context_with_farm) -> None:
    """Grow Cubes registered in a DIFFERENT Farm (same tenant) are never
    visible to this Farm's pool query -- `_select_available_grow_cubes_for_
    update` filters on `Carrier.farm_id`, never just `tenant_id`. Proven by
    requesting more than this Farm's own local pool while a same-tenant
    sibling Farm has plenty spare."""
    from app.services import farm_service

    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, normal=50)
    other_farm = farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code="other-farm", name="Other Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    _add_grow_cubes(db_session, tenant, user, other_farm, count=50, prefix="GC-OTHERFARM-")
    aid = s["source_assignment_ids"][0]
    table_id = s["intervines_table_ids"][0]

    # farm has only its own 4 base Grow Cubes -- requesting 5 must fail
    # even though other_farm has 50 spare.
    with pytest.raises(InsufficientAvailableGrowCubesError):
        _record(
            db_session, tenant, farm, user, s["batch"], aid, 5, table_id,
            effective_time=s["entry_time"] + timedelta(hours=2),
        )


@pytest.mark.integration
def test_cross_farm_batch_rejected(db_session, active_context_with_farm) -> None:
    """The Batch itself never resolves under the wrong Farm -- `_record_
    transplant_core`'s own unmodified `_get_batch_row` (tenant+farm+id
    scoped) already fails closed before any Grow Cube is ever selected."""
    from app.services import farm_service

    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, normal=50)
    other_farm = farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code="other-farm-2", name="Other Farm 2",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    _add_grow_cubes(db_session, tenant, user, other_farm, count=10, prefix="GC-XFB-")
    aid = s["source_assignment_ids"][0]
    table_id = s["intervines_table_ids"][0]

    from app.services.errors import CropBatchNotFoundError

    with pytest.raises(CropBatchNotFoundError):
        intervines_transplant_service.record_intervines_transplant(
            db_session, tenant_id=tenant.id, farm_id=other_farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
            client_command_id=uuid.uuid4(), effective_time=s["entry_time"] + timedelta(hours=2), note=None,
            source_assignment_id=aid, plant_count=5, destination_location_id=table_id,
            grow_cube_specification_id=None,
        )


# =====================================================================
# Traceability / lineage
# =====================================================================


@pytest.mark.integration
def test_lineage_fields_are_complete(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, normal=40)
    _add_grow_cubes(db_session, tenant, user, farm, count=10, prefix="GC-LIN-")
    aid = s["source_assignment_ids"][0]
    table_id = s["intervines_table_ids"][0]

    result = _record(
        db_session, tenant, farm, user, s["batch"], aid, 5, table_id,
        effective_time=s["entry_time"] + timedelta(hours=2),
    )

    assert result.batch_id == s["batch"].id
    assert result.batch_code == s["batch"].code
    assert result.source_assignment_id == aid
    assert result.source_carrier.id == s["source_carriers"][0].id
    assert result.destination_location_id == table_id
    assert result.actor_user_id == user.id
    for gc in result.grow_cubes:
        assert gc.destination_location_id == table_id
        assert gc.carrier.id is not None

    detail = intervines_transplant_service.list_intervines_placement_grow_cubes(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=s["batch"].id, table_id=table_id
    )
    assert len(detail) == 5
    assert {d.carrier.id for d in detail} == {gc.carrier.id for gc in result.grow_cubes}


# =====================================================================
# Authorization (HTTP)
# =====================================================================


@pytest.mark.integration
def test_transplant_manage_sufficient_via_http(client, active_context_with_farm, db_session) -> None:
    tenant, user, headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, normal=40)
    _add_grow_cubes(db_session, tenant, user, farm, count=10, prefix="GC-HTTP-")
    db_session.commit()
    aid = s["source_assignment_ids"][0]
    table_id = s["intervines_table_ids"][0]

    resp = client.post(
        f"/farms/{farm.id}/crop-batches/{s['batch'].id}/intervines-transplants", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()),
            "effective_time": (s["entry_time"] + timedelta(hours=2)).isoformat(),
            "note": None, "source_assignment_id": str(aid), "plant_count": 5,
            "destination_location_id": str(table_id), "grow_cube_specification_id": None,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["plant_count"] == 5
    assert len(body["grow_cubes"]) == 5


@pytest.mark.integration
def test_storekeeper_role_without_transplant_manage_denied_via_http(client, active_context_with_farm, db_session) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    from app.services import membership_service, user_service

    s = _build_scenario(db_session, tenant, user, farm, normal=40)
    _add_grow_cubes(db_session, tenant, user, farm, count=10, prefix="GC-DENY-")
    db_session.commit()
    storekeeper = user_service.create_user(
        db_session, oidc_issuer="iss", oidc_subject="ivines-sk", email="ivines-sk@example.com",
        display_name="Storekeeper",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant.id, user_id=storekeeper.id, role_code="storekeeper", actor_user_id=None
    )
    db_session.commit()
    op_headers = {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(storekeeper.id)}
    aid = s["source_assignment_ids"][0]
    table_id = s["intervines_table_ids"][0]

    resp = client.post(
        f"/farms/{farm.id}/crop-batches/{s['batch'].id}/intervines-transplants", headers=op_headers,
        json={
            "client_command_id": str(uuid.uuid4()),
            "effective_time": (s["entry_time"] + timedelta(hours=2)).isoformat(),
            "note": None, "source_assignment_id": str(aid), "plant_count": 5,
            "destination_location_id": str(table_id), "grow_cube_specification_id": None,
        },
    )
    assert resp.status_code == 403, resp.text


# =====================================================================
# Domain integrity: one Grow Cube can never carry more than one living plant
# =====================================================================


@pytest.mark.integration
def test_grow_cube_one_plant_invariant_holds_without_specification(db_session, active_context_with_farm) -> None:
    """VINES-OPS-001A closure section 5: a Grow Cube with NO CarrierSpecification
    at all (no admin-configured `biological_position_count`, nothing this
    composite's own destination-line construction ever depends on) must
    still be structurally impossible to double-assign to a second living
    plant. This test deliberately does NOT go through `intervines_transplant_
    service`'s own pool-selection query a second time (that would only prove
    OUR OWN filtering works, already covered by `test_already_occupied_grow_
    cubes_excluded_from_pool` above) -- it instead calls the shared, generic
    `transplant_service.record_transplant` PUBLIC entry point directly with
    an EXPLICIT `destination_carrier_id` naming the already-occupied Grow
    Cube, simulating any other present-or-future caller (not just this
    composite) that might supply a destination Carrier id explicitly. The
    unmodified, carrier-type-agnostic `DestinationCarrierAlreadyAssignedError`
    check inside `_record_transplant_core` -- which runs unconditionally,
    before and independent of any CarrierSpecification/`requires_specification`
    logic -- is what this test proves actually holds for `grow_cube`."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=2, normal=50)
    # A grow_cube Carrier with NO specification_id at all, given a code that
    # sorts before the scenario's own "CP-..." destination_carriers so our
    # composite's own ascending-code pool selection deterministically picks
    # it first for a plant_count=1 request.
    bare_cube = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        carrier_type_code=DESTINATION_TYPE, code="AAA-BARE-0001", issued_date=None,
    )
    assert bare_cube.specification_id is None
    table_id = s["intervines_table_ids"][0]
    source_a, source_b = s["source_assignment_ids"][0], s["source_assignment_ids"][1]

    first = _record(
        db_session, tenant, farm, user, s["batch"], source_a, 1, table_id,
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    assert len(first.grow_cubes) == 1
    assert first.grow_cubes[0].carrier.id == bare_cube.id

    active_assignments_before = db_session.execute(
        select(BatchCarrierAssignment).where(
            BatchCarrierAssignment.carrier_id == bare_cube.id, BatchCarrierAssignment.released_effective_time.is_(None),
        )
    ).scalars().all()
    assert len(active_assignments_before) == 1

    # Direct attempt via the shared generic entry point (not this
    # composite), explicitly naming the already-occupied bare Grow Cube as
    # the destination for a SECOND, unrelated source's plant.
    with pytest.raises(DestinationCarrierAlreadyAssignedError):
        transplant_service.record_transplant(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
            client_command_id=uuid.uuid4(), effective_time=s["entry_time"] + timedelta(hours=3), note=None,
            source_lines=[
                {
                    "source_assignment_id": source_b, "transplant_damage_count": 0, "qc_rejection_count": 0,
                    "sample_count": 0, "other_loss_count": 0, "other_loss_note": None, "note": None,
                }
            ],
            destination_lines=[
                {"destination_carrier_id": bare_cube.id, "assigned_plant_count": 1, "note": None}
            ],
            allocations=[
                {"source_assignment_id": source_b, "destination_carrier_id": bare_cube.id, "allocated_plant_count": 1}
            ],
        )

    # No second assignment was created -- exactly the one from the first,
    # legitimate command still stands.
    active_assignments_after = db_session.execute(
        select(BatchCarrierAssignment).where(BatchCarrierAssignment.carrier_id == bare_cube.id)
    ).scalars().all()
    assert len(active_assignments_after) == 1
    assert active_assignments_after[0].released_effective_time is None
    source_b_assignment = db_session.get(BatchCarrierAssignment, source_b)
    assert source_b_assignment.released_effective_time is None
