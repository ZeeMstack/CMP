"""NURSERY-OPS-005B: Leafy Production Transfer composite (Nursery
Cultivation Plate source -> Production Cultivation Plate destination ->
physical placement on a Leafy grow_table), mirroring `test_intersalads_
transplant.py`'s coverage shape for the sibling composite. Concurrency is
out of this ticket's required scope (005A already proves the shared
`_record_transplant_core` locking discipline; this composite adds only the
same destination-Location lock-ordering InterSalads already has its own
concurrency proof for). Migration/downgrade-guard coverage lives in
`test_leafy_production_occupancy_compatibility_downgrade_guard.py`. Does
not duplicate existing `test_transplant.py`/`test_batch_carrier_population_
checkpoint*.py`/`test_movement*.py` coverage for behavior this composite
reuses unchanged -- only what the composite itself adds or could plausibly
regress.

Every scenario here uses two sequential transplanting-category stages
(TRANSPLANTING, required=nursery_cultivation_plate; PRODUCTION_TRANSPLANT,
required=production_cultivation_plate) because a single WorkflowStage's
`required_carrier_type_id` cannot serve two different destination Carrier
types -- see `_nursery_plate_source_scenario`'s own docstring. This models
exactly how a real tenant would configure two sequential physical
transplant operations, and never calls or touches 005A's own stage guards
beyond the ordinary, pre-existing `transition_stage` mechanism."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.batch_carrier_population_checkpoint import BatchCarrierPopulationCheckpoint
from app.models.movement import Movement
from app.models.occupancy import Occupancy
from app.schemas.farm_setup import GreenhouseSetupCreate, LeafySetupConfig, SpanSetupConfig, TableGeneratorConfig, ZoneSetupConfig
from app.services import carrier_service, carrier_specification_service, farm_setup_service, leafy_production_transfer_service, transplant_service
from app.services.errors import (
    DestinationCarrierAlreadyAssignedError,
    LeafyProductionTransferReplayStateConflictError,
    TargetOccupiedError,
    TransplantCapacityExceededError,
    TransplantCommandReusedWithDifferentPayloadError,
    TransplantValidationError,
    UnsupportedTransplantSourceCarrierTypeError,
)
from tests._transplant_scenario import build_transplant_ready_scenario, now as _now

NURSERY_PLATE_TYPE = "nursery_cultivation_plate"
PRODUCTION_PLATE_TYPE = "production_cultivation_plate"


def _leafy_setup(db_session, tenant, user, farm, *, table_count=3, table_capacity=1, suffix=None):
    suffix = suffix or uuid.uuid4().hex[:8]
    setup = farm_setup_service.create_greenhouse_setup(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        payload=GreenhouseSetupCreate(
            code=f"LGH-{suffix}", name="Leafy", classification="leafy_greens", client_command_id=uuid.uuid4(),
            leafy=LeafySetupConfig(
                zones=[
                    ZoneSetupConfig(
                        code=f"Z{suffix[:4]}",
                        spans=[
                            SpanSetupConfig(
                                code=f"S{suffix[:4]}",
                                tables=TableGeneratorConfig(
                                    code_prefix=f"T{suffix[:4]}", start=1, end=table_count, pad_width=2,
                                    capacity=table_capacity,
                                ),
                            )
                        ],
                    )
                ]
            ),
        ),
    )
    structure = farm_setup_service.get_greenhouse_structure(
        db_session.connection(), tenant_id=tenant.id, farm_id=farm.id, greenhouse_id=setup.greenhouse_id,
    )
    table_ids = [t.id for t in structure.leafy_zones[0].spans[0].tables]
    return table_ids


def _production_plates(db_session, tenant, user, farm, *, count=3, biological_position_count=200, suffix=None):
    suffix = suffix or uuid.uuid4().hex[:8]
    spec = carrier_specification_service.register_carrier_specification(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, carrier_type_code=PRODUCTION_PLATE_TYPE,
        code=f"PP-SPEC-{suffix}", name="Production Plate Spec", length_mm=600, width_mm=400, height_mm=80,
        biological_position_count=biological_position_count,
    )
    plates = [
        carrier_service.register_carrier(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, specification_id=spec.id,
            code=f"PP-{suffix}-{i}", issued_date=None,
        )
        for i in range(count)
    ]
    return plates, spec


def _nursery_plate_source_scenario(
    db_session, tenant, user, farm, *, suffix=None, source_count=1, opening_count=200
):
    """Seed Tray -> Nursery Cultivation Plate (one per requested source),
    via the real generic Transplant flow (not the composite) -- gives
    `source_count` real, active, 005A-authoritative `nursery_cultivation_
    plate` source assignments on the SAME Batch to use as this composite's
    own sources. Then explicitly transitions the Batch TRANSPLANTING ->
    GROWING -> PRODUCTION_TRANSPLANT (a SECOND transplanting-category stage
    requiring `production_cultivation_plate`, since a single WorkflowStage's
    required_carrier_type_id cannot serve both this opening transplant's
    destination type and the composite's own different destination type) --
    every seed tray is fully consumed by its own opening transplant, so
    leaving TRANSPLANTING never trips the pre-existing leaving-transplanting
    remainder guard. This helper never calls the composite itself and never
    touches 005A's own guard code -- only the ordinary, pre-existing
    `transition_stage` mechanism, exactly as a real operator/tenant
    configuration would use it between two sequential physical transplant
    operations. Returns `(scenario_dict, [assignment_ids])`; the scenario
    dict gains `transfer_ready_time`, strictly after which the composite's
    own `effective_time` must fall (the PRODUCTION_TRANSPLANT stage run's
    own entry time)."""
    suffix = suffix or uuid.uuid4().hex[:8]
    nursery_spec = carrier_specification_service.register_carrier_specification(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, carrier_type_code=NURSERY_PLATE_TYPE,
        code=f"NP-SPEC-{suffix}", name="Nursery Plate Spec", length_mm=500, width_mm=300, height_mm=60,
        biological_position_count=opening_count,
    )
    s = build_transplant_ready_scenario(
        db_session, tenant, user, farm, suffix=suffix, tray_count=source_count, normal=opening_count, abnormal=0,
        transplanting_required_type=NURSERY_PLATE_TYPE, destination_specification_id=nursery_spec.id,
        second_transplant_required_type=PRODUCTION_PLATE_TYPE,
    )
    assignment_ids = []
    for i in range(source_count):
        seed_tray_aid = s["source_assignment_ids"][i]
        nursery_plate = s["destination_carriers"][i]
        opening_event = transplant_service.record_transplant(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch_id"],
            client_command_id=uuid.uuid4(), effective_time=s["entry_time"] + timedelta(hours=1), note=None,
            source_lines=[
                {
                    "source_assignment_id": seed_tray_aid, "transplant_damage_count": 0, "qc_rejection_count": 0,
                    "sample_count": 0, "other_loss_count": 0, "other_loss_note": None, "note": None,
                }
            ],
            destination_lines=[{"destination_carrier_id": nursery_plate.id, "assigned_plant_count": opening_count, "note": None}],
            allocations=[
                {
                    "source_assignment_id": seed_tray_aid, "destination_carrier_id": nursery_plate.id,
                    "allocated_plant_count": opening_count,
                }
            ],
        )
        assignment_ids.append(
            db_session.execute(
                select(BatchCarrierAssignment.id).where(
                    BatchCarrierAssignment.opening_transplant_event_id == opening_event.id
                )
            ).scalar_one()
        )

    from app.services import crop_batch_service

    transition_time = s["entry_time"] + timedelta(hours=2)
    crop_batch_service.transition_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch_id"],
        client_command_id=uuid.uuid4(), configured_transition_id=s["transitions"]["t2"].id,
        effective_time=transition_time, reason=None,
    )
    crop_batch_service.transition_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch_id"],
        client_command_id=uuid.uuid4(), configured_transition_id=s["transitions"]["t2b"].id,
        effective_time=transition_time, reason=None,
    )
    s["transfer_ready_time"] = transition_time
    return s, assignment_ids


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
    return leafy_production_transfer_service.record_leafy_production_transfer(
        db_session, source_lines=source_lines, destination_lines=destination_lines, allocations=allocations,
        **defaults,
    )


# =====================================================================
# Happy path / core correctness
# =====================================================================


@pytest.mark.integration
def test_valid_nursery_to_production_transfer(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, aids = _nursery_plate_source_scenario(db_session, tenant, user, farm)
    table_ids = _leafy_setup(db_session, tenant, user, farm)
    plates, _spec = _production_plates(db_session, tenant, user, farm)

    result = _record(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aids[0])], [_simple_destination(plates[0].id, table_ids[0], count=150)],
        [_simple_allocation(aids[0], plates[0].id, 150)],
        effective_time=s["transfer_ready_time"] + timedelta(hours=1),
    )

    assert result.total_destination_plant_count == 150
    assert result.total_remainder_after == 50
    assert len(result.destination_lines) == 1
    dline = result.destination_lines[0]
    assert dline.destination_location_id == table_ids[0]
    assert dline.assigned_plant_count == 150

    destination_assignment = db_session.execute(
        select(BatchCarrierAssignment).where(
            BatchCarrierAssignment.id == dline.destination_batch_carrier_assignment_id
        )
    ).scalar_one()
    assert destination_assignment.carrier_id == plates[0].id
    assert destination_assignment.released_effective_time is None
    # Opening population is derived, never stored -- no checkpoint yet.
    checkpoint_rows = db_session.execute(
        select(BatchCarrierPopulationCheckpoint).where(
            BatchCarrierPopulationCheckpoint.batch_carrier_assignment_id == destination_assignment.id
        )
    ).all()
    assert checkpoint_rows == []

    movement = db_session.get(Movement, dline.movement_id)
    assert movement.occupant_carrier_id == plates[0].id
    assert movement.destination_location_id == table_ids[0]
    active_occupancy = db_session.execute(
        select(Occupancy).where(Occupancy.occupant_carrier_id == plates[0].id, Occupancy.end_time.is_(None))
    ).scalar_one()
    assert active_occupancy.target_location_id == table_ids[0]


@pytest.mark.integration
def test_source_partial_remainder_stays_active(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, aids = _nursery_plate_source_scenario(db_session, tenant, user, farm)
    table_ids = _leafy_setup(db_session, tenant, user, farm)
    plates, _spec = _production_plates(db_session, tenant, user, farm, count=1)

    _record(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aids[0])], [_simple_destination(plates[0].id, table_ids[0], count=120)],
        [_simple_allocation(aids[0], plates[0].id, 120)],
        effective_time=s["transfer_ready_time"] + timedelta(hours=1),
    )
    source_after = db_session.get(BatchCarrierAssignment, aids[0])
    assert source_after.released_effective_time is None


@pytest.mark.integration
def test_source_full_exhaustion_releases(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, aids = _nursery_plate_source_scenario(db_session, tenant, user, farm)
    table_ids = _leafy_setup(db_session, tenant, user, farm)
    plates, _spec = _production_plates(db_session, tenant, user, farm, count=1)

    _record(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aids[0])], [_simple_destination(plates[0].id, table_ids[0], count=200)],
        [_simple_allocation(aids[0], plates[0].id, 200)],
        effective_time=s["transfer_ready_time"] + timedelta(hours=1),
    )
    source_after = db_session.get(BatchCarrierAssignment, aids[0])
    assert source_after.released_effective_time is not None
    # Physical Occupancy of the source Nursery Plate is NOT automatically
    # changed by biological release -- this composite never issues a
    # Movement for a source Carrier.
    movements_touching_source = db_session.execute(
        select(Movement).where(Movement.occupant_carrier_id == source_after.carrier_id)
    ).all()
    assert movements_touching_source == []


@pytest.mark.integration
def test_n_sources_to_one_destination(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, aids = _nursery_plate_source_scenario(db_session, tenant, user, farm, source_count=2, opening_count=100)
    table_ids = _leafy_setup(db_session, tenant, user, farm)
    plates, _spec = _production_plates(db_session, tenant, user, farm, count=1, biological_position_count=200)

    result = _record(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aids[0]), _simple_source(aids[1])],
        [_simple_destination(plates[0].id, table_ids[0], count=200)],
        [_simple_allocation(aids[0], plates[0].id, 100), _simple_allocation(aids[1], plates[0].id, 100)],
        effective_time=s["transfer_ready_time"] + timedelta(hours=1),
    )
    assert result.total_destination_plant_count == 200
    assert len(result.source_lines) == 2


@pytest.mark.integration
def test_one_source_to_multiple_destinations(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, aids = _nursery_plate_source_scenario(db_session, tenant, user, farm, opening_count=200)
    table_ids = _leafy_setup(db_session, tenant, user, farm, table_count=2)
    plates, _spec = _production_plates(db_session, tenant, user, farm, count=2)

    result = _record(
        db_session, tenant, farm, user, s["batch"], [_simple_source(aids[0])],
        [
            _simple_destination(plates[0].id, table_ids[0], count=120),
            _simple_destination(plates[1].id, table_ids[1], count=80),
        ],
        [
            _simple_allocation(aids[0], plates[0].id, 120),
            _simple_allocation(aids[0], plates[1].id, 80),
        ],
        effective_time=s["transfer_ready_time"] + timedelta(hours=1),
    )
    assert result.total_destination_plant_count == 200
    assert len(result.destination_lines) == 2


@pytest.mark.integration
def test_true_n_by_m_allocation(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, aids = _nursery_plate_source_scenario(db_session, tenant, user, farm, source_count=2, opening_count=150)
    table_ids = _leafy_setup(db_session, tenant, user, farm, table_count=2)
    plates, _spec = _production_plates(db_session, tenant, user, farm, count=2, biological_position_count=200)

    result = _record(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aids[0]), _simple_source(aids[1])],
        [
            _simple_destination(plates[0].id, table_ids[0], count=150),
            _simple_destination(plates[1].id, table_ids[1], count=150),
        ],
        [
            _simple_allocation(aids[0], plates[0].id, 100), _simple_allocation(aids[0], plates[1].id, 50),
            _simple_allocation(aids[1], plates[0].id, 50), _simple_allocation(aids[1], plates[1].id, 100),
        ],
        effective_time=s["transfer_ready_time"] + timedelta(hours=1),
    )
    assert result.total_destination_plant_count == 300
    assert len(result.allocations) == 4


# =====================================================================
# Rejections
# =====================================================================


@pytest.mark.integration
def test_different_batch_merge_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s1, aids1 = _nursery_plate_source_scenario(db_session, tenant, user, farm, suffix="x")
    s2, aids2 = _nursery_plate_source_scenario(db_session, tenant, user, farm, suffix="y")
    table_ids = _leafy_setup(db_session, tenant, user, farm)
    plates, _spec = _production_plates(db_session, tenant, user, farm, count=1)

    with pytest.raises(Exception):
        _record(
            db_session, tenant, farm, user, s1["batch"],
            [_simple_source(aids1[0]), _simple_source(aids2[0])],
            [_simple_destination(plates[0].id, table_ids[0], count=400)],
            [_simple_allocation(aids1[0], plates[0].id, 200), _simple_allocation(aids2[0], plates[0].id, 200)],
            effective_time=max(s1["transfer_ready_time"], s2["transfer_ready_time"]) + timedelta(hours=1),
        )


@pytest.mark.integration
def test_wrong_source_carrier_type_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    # A generic cultivation_plate destination, opened by an ordinary
    # Transplant, is not an eligible source type -- isolated from the
    # destination-type check by giving the Batch a SECOND transplanting
    # stage (required=production_cultivation_plate) to run the composite
    # call from, exactly like the other scenarios here.
    cp_spec = carrier_specification_service.register_carrier_specification(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, carrier_type_code="cultivation_plate",
        code=f"CP-SPEC-{uuid.uuid4().hex[:6]}", name="Generic Plate", length_mm=500, width_mm=300, height_mm=60,
        biological_position_count=200,
    )
    s = build_transplant_ready_scenario(
        db_session, tenant, user, farm, tray_count=1, transplanting_required_type="cultivation_plate",
        destination_specification_id=cp_spec.id, second_transplant_required_type=PRODUCTION_PLATE_TYPE,
    )
    seed_tray_aid = s["source_assignment_ids"][0]
    wrong_plate = s["destination_carriers"][0]
    opening_event = transplant_service.record_transplant(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch_id"],
        client_command_id=uuid.uuid4(), effective_time=s["entry_time"] + timedelta(hours=1), note=None,
        source_lines=[
            {
                "source_assignment_id": seed_tray_aid, "transplant_damage_count": 0, "qc_rejection_count": 0,
                "sample_count": 0, "other_loss_count": 0, "other_loss_note": None, "note": None,
            }
        ],
        destination_lines=[{"destination_carrier_id": wrong_plate.id, "assigned_plant_count": 200, "note": None}],
        allocations=[
            {
                "source_assignment_id": seed_tray_aid, "destination_carrier_id": wrong_plate.id,
                "allocated_plant_count": 200,
            }
        ],
    )
    wrong_aid = db_session.execute(
        select(BatchCarrierAssignment.id).where(
            BatchCarrierAssignment.opening_transplant_event_id == opening_event.id
        )
    ).scalar_one()

    from app.services import crop_batch_service

    transition_time = s["entry_time"] + timedelta(hours=2)
    crop_batch_service.transition_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch_id"],
        client_command_id=uuid.uuid4(), configured_transition_id=s["transitions"]["t2"].id,
        effective_time=transition_time, reason=None,
    )
    crop_batch_service.transition_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch_id"],
        client_command_id=uuid.uuid4(), configured_transition_id=s["transitions"]["t2b"].id,
        effective_time=transition_time, reason=None,
    )

    table_ids = _leafy_setup(db_session, tenant, user, farm)
    plates, _spec2 = _production_plates(db_session, tenant, user, farm, count=1)

    with pytest.raises(UnsupportedTransplantSourceCarrierTypeError):
        _record(
            db_session, tenant, farm, user, s["batch"],
            [_simple_source(wrong_aid)], [_simple_destination(plates[0].id, table_ids[0], count=200)],
            [_simple_allocation(wrong_aid, plates[0].id, 200)],
            effective_time=transition_time + timedelta(hours=1),
        )


@pytest.mark.integration
def test_wrong_destination_carrier_type_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, aids = _nursery_plate_source_scenario(db_session, tenant, user, farm)
    table_ids = _leafy_setup(db_session, tenant, user, farm)
    # A Carrier that is NOT production_cultivation_plate-typed.
    wrong_type_carrier = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        carrier_type_code="cultivation_plate", code=f"WRONG-{uuid.uuid4().hex[:6]}", issued_date=None,
    )
    with pytest.raises(TransplantValidationError):
        _record(
            db_session, tenant, farm, user, s["batch"],
            [_simple_source(aids[0])],
            [_simple_destination(wrong_type_carrier.id, table_ids[0], count=200)],
            [_simple_allocation(aids[0], wrong_type_carrier.id, 200)],
            effective_time=s["transfer_ready_time"] + timedelta(hours=1),
        )


@pytest.mark.integration
def test_destination_capacity_exceeded_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, aids = _nursery_plate_source_scenario(db_session, tenant, user, farm, opening_count=200)
    table_ids = _leafy_setup(db_session, tenant, user, farm)
    plates, _spec = _production_plates(db_session, tenant, user, farm, count=1, biological_position_count=100)

    with pytest.raises(TransplantCapacityExceededError):
        _record(
            db_session, tenant, farm, user, s["batch"],
            [_simple_source(aids[0])], [_simple_destination(plates[0].id, table_ids[0], count=150)],
            [_simple_allocation(aids[0], plates[0].id, 150)],
            effective_time=s["transfer_ready_time"] + timedelta(hours=1),
        )


@pytest.mark.integration
def test_destination_plate_already_assigned_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s1, aids1 = _nursery_plate_source_scenario(db_session, tenant, user, farm, suffix="a", opening_count=200)
    s2, aids2 = _nursery_plate_source_scenario(db_session, tenant, user, farm, suffix="b", opening_count=200)
    table_ids = _leafy_setup(db_session, tenant, user, farm, table_count=2)
    plates, _spec = _production_plates(db_session, tenant, user, farm, count=1)

    _record(
        db_session, tenant, farm, user, s1["batch"], [_simple_source(aids1[0])],
        [_simple_destination(plates[0].id, table_ids[0], count=100)],
        [_simple_allocation(aids1[0], plates[0].id, 100)],
        effective_time=s1["transfer_ready_time"] + timedelta(hours=1),
    )
    with pytest.raises(DestinationCarrierAlreadyAssignedError):
        _record(
            db_session, tenant, farm, user, s2["batch"], [_simple_source(aids2[0])],
            [_simple_destination(plates[0].id, table_ids[1], count=100)],
            [_simple_allocation(aids2[0], plates[0].id, 100)],
            effective_time=s2["transfer_ready_time"] + timedelta(hours=1),
        )


@pytest.mark.integration
def test_invalid_leafy_table_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, aids = _nursery_plate_source_scenario(db_session, tenant, user, farm)
    plates, _spec = _production_plates(db_session, tenant, user, farm, count=1)

    with pytest.raises(Exception):
        _record(
            db_session, tenant, farm, user, s["batch"],
            [_simple_source(aids[0])],
            [_simple_destination(plates[0].id, uuid.uuid4(), count=200)],
            [_simple_allocation(aids[0], plates[0].id, 200)],
            effective_time=s["transfer_ready_time"] + timedelta(hours=1),
        )


@pytest.mark.integration
def test_table_capacity_exceeded_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s1, aids1 = _nursery_plate_source_scenario(db_session, tenant, user, farm, suffix="a", opening_count=200)
    s2, aids2 = _nursery_plate_source_scenario(db_session, tenant, user, farm, suffix="b", opening_count=200)
    table_ids = _leafy_setup(db_session, tenant, user, farm, table_count=1, table_capacity=1)
    plates, _spec = _production_plates(db_session, tenant, user, farm, count=2)

    _record(
        db_session, tenant, farm, user, s1["batch"], [_simple_source(aids1[0])],
        [_simple_destination(plates[0].id, table_ids[0], count=100)],
        [_simple_allocation(aids1[0], plates[0].id, 100)],
        effective_time=s1["transfer_ready_time"] + timedelta(hours=1),
    )
    with pytest.raises(TargetOccupiedError):
        _record(
            db_session, tenant, farm, user, s2["batch"], [_simple_source(aids2[0])],
            [_simple_destination(plates[1].id, table_ids[0], count=100)],
            [_simple_allocation(aids2[0], plates[1].id, 100)],
            effective_time=s2["transfer_ready_time"] + timedelta(hours=1),
        )


@pytest.mark.integration
def test_same_table_multiple_destinations_accepted_within_capacity(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, aids = _nursery_plate_source_scenario(db_session, tenant, user, farm, opening_count=200)
    table_ids = _leafy_setup(db_session, tenant, user, farm, table_count=1, table_capacity=2)
    plates, _spec = _production_plates(db_session, tenant, user, farm, count=2)

    result = _record(
        db_session, tenant, farm, user, s["batch"], [_simple_source(aids[0])],
        [
            _simple_destination(plates[0].id, table_ids[0], count=100),
            _simple_destination(plates[1].id, table_ids[0], count=100),
        ],
        [
            _simple_allocation(aids[0], plates[0].id, 100),
            _simple_allocation(aids[0], plates[1].id, 100),
        ],
        effective_time=s["transfer_ready_time"] + timedelta(hours=1),
    )
    assert len(result.destination_lines) == 2
    active_occupancies = db_session.execute(
        select(Occupancy).where(Occupancy.target_location_id == table_ids[0], Occupancy.end_time.is_(None))
    ).scalars().all()
    assert len(active_occupancies) == 2


# =====================================================================
# Atomicity, idempotency, replay
# =====================================================================


@pytest.mark.integration
def test_atomic_rollback_when_one_movement_fails(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, aids = _nursery_plate_source_scenario(db_session, tenant, user, farm, opening_count=200)
    table_ids = _leafy_setup(db_session, tenant, user, farm, table_count=1, table_capacity=1)
    plates, _spec = _production_plates(db_session, tenant, user, farm, count=2)

    # Pre-fill the (capacity-1) Table so the SECOND destination's Movement
    # fails -- the whole command, including the first destination's
    # otherwise-valid Transplant/Movement, must roll back atomically.
    filler = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        carrier_type_code="cultivation_plate", code=f"FILL-{uuid.uuid4().hex[:6]}", issued_date=None,
    )
    from app.services import movement_service

    movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        effective_time=s["transfer_ready_time"] + timedelta(minutes=30), occupant_kind="carrier",
        occupant_id=filler.id, destination_kind="location", destination_id=table_ids[0], reason=None,
    )

    with pytest.raises(TargetOccupiedError):
        _record(
            db_session, tenant, farm, user, s["batch"], [_simple_source(aids[0])],
            [
                _simple_destination(plates[0].id, table_ids[0], count=100),
                _simple_destination(plates[1].id, table_ids[0], count=100),
            ],
            [
                _simple_allocation(aids[0], plates[0].id, 100), _simple_allocation(aids[0], plates[1].id, 100),
            ],
            effective_time=s["transfer_ready_time"] + timedelta(hours=1),
        )
    # Nothing from the failed composite committed: source remains untouched.
    source_after = db_session.get(BatchCarrierAssignment, aids[0])
    assert source_after.released_effective_time is None
    destination_bca = db_session.execute(
        select(BatchCarrierAssignment).where(BatchCarrierAssignment.carrier_id == plates[0].id)
    ).scalar_one_or_none()
    assert destination_bca is None


@pytest.mark.integration
def test_exact_replay_returns_same_result_no_duplicate(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, aids = _nursery_plate_source_scenario(db_session, tenant, user, farm, opening_count=200)
    table_ids = _leafy_setup(db_session, tenant, user, farm)
    plates, _spec = _production_plates(db_session, tenant, user, farm, count=1)

    command_id = uuid.uuid4()
    first = _record(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aids[0])], [_simple_destination(plates[0].id, table_ids[0], count=150)],
        [_simple_allocation(aids[0], plates[0].id, 150)],
        effective_time=s["transfer_ready_time"] + timedelta(hours=1), client_command_id=command_id,
    )
    second = _record(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aids[0])], [_simple_destination(plates[0].id, table_ids[0], count=150)],
        [_simple_allocation(aids[0], plates[0].id, 150)],
        effective_time=s["transfer_ready_time"] + timedelta(hours=1), client_command_id=command_id,
    )
    assert second.id == first.id
    assert second.destination_lines[0].movement_id == first.destination_lines[0].movement_id
    movement_rows = db_session.execute(select(Movement).where(Movement.occupant_carrier_id == plates[0].id)).all()
    assert len(movement_rows) == 1


@pytest.mark.integration
def test_same_id_different_payload_conflict(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, aids = _nursery_plate_source_scenario(db_session, tenant, user, farm, opening_count=200)
    table_ids = _leafy_setup(db_session, tenant, user, farm)
    plates, _spec = _production_plates(db_session, tenant, user, farm, count=1)

    command_id = uuid.uuid4()
    _record(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aids[0])], [_simple_destination(plates[0].id, table_ids[0], count=150)],
        [_simple_allocation(aids[0], plates[0].id, 150)],
        effective_time=s["transfer_ready_time"] + timedelta(hours=1), client_command_id=command_id,
    )
    with pytest.raises(TransplantCommandReusedWithDifferentPayloadError):
        _record(
            db_session, tenant, farm, user, s["batch"],
            [_simple_source(aids[0])], [_simple_destination(plates[0].id, table_ids[0], count=100)],
            [_simple_allocation(aids[0], plates[0].id, 100)],
            effective_time=s["transfer_ready_time"] + timedelta(hours=1), client_command_id=command_id,
        )


@pytest.mark.integration
def test_replay_movement_state_verification(db_session, active_context_with_farm) -> None:
    """A committed composite followed by a raw-SQL deletion of its own
    Movement row (simulating externally-tampered state) must surface
    `LeafyProductionTransferReplayStateConflictError` on replay, never a
    silently fabricated response."""
    tenant, user, _headers, farm = active_context_with_farm
    s, aids = _nursery_plate_source_scenario(db_session, tenant, user, farm, opening_count=200)
    table_ids = _leafy_setup(db_session, tenant, user, farm)
    plates, _spec = _production_plates(db_session, tenant, user, farm, count=1)

    command_id = uuid.uuid4()
    _record(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aids[0])], [_simple_destination(plates[0].id, table_ids[0], count=150)],
        [_simple_allocation(aids[0], plates[0].id, 150)],
        effective_time=s["transfer_ready_time"] + timedelta(hours=1), client_command_id=command_id,
    )
    from sqlalchemy import text

    db_session.execute(text("SET session_replication_role = replica"))
    db_session.execute(text("DELETE FROM occupancies WHERE occupant_carrier_id = :cid"), {"cid": plates[0].id})
    db_session.execute(text("DELETE FROM movements WHERE occupant_carrier_id = :cid"), {"cid": plates[0].id})
    db_session.execute(text("SET session_replication_role = DEFAULT"))

    with pytest.raises(LeafyProductionTransferReplayStateConflictError):
        _record(
            db_session, tenant, farm, user, s["batch"],
            [_simple_source(aids[0])], [_simple_destination(plates[0].id, table_ids[0], count=150)],
            [_simple_allocation(aids[0], plates[0].id, 150)],
            effective_time=s["transfer_ready_time"] + timedelta(hours=1), client_command_id=command_id,
        )


# =====================================================================
# Isolation, no stage transition
# =====================================================================


@pytest.mark.integration
def test_tenant_isolation(db_session, active_context_with_farm) -> None:
    from app.services import farm_service, membership_service, tenant_service, user_service

    tenant, user, _headers, farm = active_context_with_farm
    s, aids = _nursery_plate_source_scenario(db_session, tenant, user, farm)
    table_ids = _leafy_setup(db_session, tenant, user, farm)

    other_tenant = tenant_service.create_tenant(db_session, code=f"other-{uuid.uuid4().hex[:8]}", name="Other")
    other_user = user_service.create_user(
        db_session, oidc_issuer="other", oidc_subject=uuid.uuid4().hex[:8],
        email=f"other-{uuid.uuid4().hex[:6]}@example.com", display_name="Other",
    )
    membership_service.add_membership(
        db_session, tenant_id=other_tenant.id, user_id=other_user.id, role_code="tenant_admin", actor_user_id=None
    )
    other_farm = farm_service.create_farm(
        db_session, tenant_id=other_tenant.id, actor_user_id=other_user.id, code=f"farm-{uuid.uuid4().hex[:6]}",
        name="Other Farm", country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    other_plates, _spec = _production_plates(db_session, other_tenant, other_user, other_farm, count=1)

    with pytest.raises(Exception):
        _record(
            db_session, tenant, farm, user, s["batch"],
            [_simple_source(aids[0])], [_simple_destination(other_plates[0].id, table_ids[0], count=100)],
            [_simple_allocation(aids[0], other_plates[0].id, 100)],
            effective_time=s["transfer_ready_time"] + timedelta(hours=1),
        )


@pytest.mark.integration
def test_farm_isolation(db_session, active_context_with_farm) -> None:
    from app.services import farm_service

    tenant, user, _headers, farm = active_context_with_farm
    s, aids = _nursery_plate_source_scenario(db_session, tenant, user, farm)
    other_farm = farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm2-{uuid.uuid4().hex[:6]}",
        name="Second Farm", country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    other_table_ids = _leafy_setup(db_session, tenant, user, other_farm)
    other_plates, _spec = _production_plates(db_session, tenant, user, other_farm, count=1)

    with pytest.raises(Exception):
        _record(
            db_session, tenant, farm, user, s["batch"],
            [_simple_source(aids[0])],
            [_simple_destination(other_plates[0].id, other_table_ids[0], count=100)],
            [_simple_allocation(aids[0], other_plates[0].id, 100)],
            effective_time=s["transfer_ready_time"] + timedelta(hours=1),
        )


@pytest.mark.integration
def test_no_automatic_stage_transition(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, aids = _nursery_plate_source_scenario(db_session, tenant, user, farm, opening_count=200)
    table_ids = _leafy_setup(db_session, tenant, user, farm)
    plates, _spec = _production_plates(db_session, tenant, user, farm, count=1)

    from app.services import crop_batch_service

    _batch_before, run_before, stage_before = crop_batch_service.get_current_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=s["batch_id"],
    )

    _record(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aids[0])], [_simple_destination(plates[0].id, table_ids[0], count=200)],
        [_simple_allocation(aids[0], plates[0].id, 200)],
        effective_time=s["transfer_ready_time"] + timedelta(hours=1),
    )

    _batch_after, run_after, stage_after = crop_batch_service.get_current_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=s["batch_id"],
    )
    assert run_after.id == run_before.id
    assert stage_after.id == stage_before.id
