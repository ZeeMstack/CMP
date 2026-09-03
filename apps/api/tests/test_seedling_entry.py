"""NURSERY-OPS-003A: Seedling Entry & Placement. Tests the new
`seedling_entry_service.py` (`seedling_entries` table) -- the atomic pairing
of a physical `Movement` (Trolley Slot -> Seedling Table) with an immutable
biological handoff freeze referencing the historically-valid completed
`GerminationOutcomeSnapshot`. Reuses `movement_service._execute_movement_core`
and `germination_outcome_service.record_germination_outcomes` verbatim via
this module's own thin orchestration -- this file tests only the new
Seedling-entry-specific validation, freeze/resolution, atomicity,
concurrency, and DB integrity; not generic Movement/Occupancy mechanics
(test_movement*.py/test_occupancy_capacity*.py) or Germination outcome
semantics (test_germination_outcome.py) already proven elsewhere."""
import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.models.movement import Movement

from app.schemas.farm_setup import (
    GerminationChamberSetupConfig,
    GreenhouseSetupCreate,
    NurserySectionConfig,
    NurserySetupConfig,
    TableGeneratorConfig,
)
from app.services import (
    asset_service,
    carrier_service,
    crop_service,
    farm_setup_service,
    germination_outcome_service,
    germination_service,
    location_service,
    movement_service,
    nursery_service,
    production_system_service,
    seedling_entry_service,
    sowing_service,
    workflow_service,
)
from app.services.errors import (
    IncompatibleOccupantTargetError,
    NoCompletedGerminationHandoffError,
    SeedlingEntryAlreadyExistsError,
    SeedlingEntryCommandReusedWithDifferentPayloadError,
    SeedlingEntryPhysicalChronologyError,
    SeedlingTableInvalidError,
    TargetNotOccupiableError,
    TargetOccupiedError,
)
from tests._traceability_scenario import cleanup_traceability_scenario
from tests.conftest import ensure_seed_tray_specification


def _now():
    return datetime.now(timezone.utc)


# =====================================================================
# Scenario builder
# =====================================================================


def _build_scenario(
    db_session, tenant, user, farm, *, suffix=None, tray_count=2, table_count=2, table_capacity=None,
    slots_per_shelf=4, shelf_count=2,
):
    """A complete Seedling-ready Nursery: Greenhouse + Seeding Station +
    Germination Chamber + Seedling Area/Tables (via Farm Setup), one
    Germination Trolley (enough slots for `tray_count` Trays), one Sown Crop
    Batch with `tray_count` Seed Trays."""
    suffix = suffix or uuid.uuid4().hex[:8]

    crop = crop_service.register_crop(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"ICE-{suffix}",
        common_name="Iceberg Lettuce", scientific_name=None, crop_category="leafy_green",
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
        production_system_id=ps.id, code=f"WF-{suffix}", name="Iceberg Nursery",
    )
    version = workflow_service.create_draft_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id
    )
    seeding_stage = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="SEEDING", name="Seeding", display_order=0, stage_category="seeding",
        expected_duration_minutes=None, permitted_location_type_code=None,
        required_carrier_type_code="seed_tray", is_start=True, is_terminal=False,
    )
    complete_stage = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="COMPLETE", name="Complete", display_order=1, stage_category="completed",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=True,
    )
    workflow_service.add_transition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=seeding_stage.id, to_stage_id=complete_stage.id, code="ADVANCE-1", name="Advance 1",
    )
    workflow_service.publish_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id
    )

    seed_lot = sowing_service.register_seed_lot(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id,
        variety_id=variety.id, code=f"LOT-{suffix}", supplier_name="Rijk Zwaan", supplier_lot_reference="RZ-001",
        received_date=None, expiry_date=None,
    )

    setup = farm_setup_service.create_greenhouse_setup(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        payload=GreenhouseSetupCreate(
            code=f"NUR-{suffix}", name="Nursery", classification="nursery", client_command_id=uuid.uuid4(),
            nursery=NurserySetupConfig(
                seeding_station=NurserySectionConfig(code=f"SEED-{suffix}"),
                germination_chamber=GerminationChamberSetupConfig(code=f"GC-{suffix}", trolley_capacity=None),
                seedling_tables=TableGeneratorConfig(
                    code_prefix=f"ST{suffix[:4]}", start=1, end=table_count, pad_width=2, capacity=table_capacity
                ),
            ),
        ),
    )
    structure = farm_setup_service.get_greenhouse_structure(
        db_session.connection(), tenant_id=tenant.id, farm_id=farm.id, greenhouse_id=setup.greenhouse_id,
    )
    seeding_station_id = structure.nursery_seeding_stations[0].id
    chamber_id = structure.nursery_germination_chamber.id
    table_ids = [t.id for t in structure.nursery_seedling.tables]

    trolley = asset_service.register_asset(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        asset_type_code="germination_trolley", code=f"GT-{suffix}", name="Trolley", commissioned_date=None,
    )
    asset_service.generate_positions(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, asset_id=trolley.id,
        shelf_count=shelf_count, slots_per_shelf=slots_per_shelf, shelf_prefix=f"SH-{suffix}-", slot_prefix="SL-",
        shelf_pad_width=2, slot_pad_width=2,
    )

    seed_tray_spec = ensure_seed_tray_specification(db_session, tenant_id=tenant.id, actor_user_id=user.id)
    carriers = [
        carrier_service.register_carrier(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            specification_id=seed_tray_spec.id, code=f"ST-{suffix}-{n:04d}", issued_date=None,
        )
        for n in range(1, tray_count + 1)
    ]

    sow_time = _now() - timedelta(days=3)
    event = nursery_service.sow_new_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        seed_lot_id=seed_lot.id, seeding_station_id=seeding_station_id, seeding_machine_id=None,
        effective_time=sow_time, note=None,
        trays=[{"carrier_id": c.id, "sown_site_count": 200, "seeds_sown": 200} for c in carriers],
    )

    germination_service.place_trolley_in_chamber(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        trolley_id=trolley.id, chamber_id=chamber_id, effective_time=sow_time + timedelta(minutes=5), reason=None,
    )

    assignments = sowing_service.list_batch_carriers(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=event.batch_id
    )
    assignment_by_carrier_code = {a.carrier.code: a.id for a in assignments}

    return {
        "greenhouse_id": setup.greenhouse_id, "chamber_id": chamber_id, "table_ids": table_ids,
        "trolley": trolley, "carriers": carriers, "batch_id": event.batch_id, "sowing_event_id": event.id,
        "assignment_ids": [assignment_by_carrier_code[c.code] for c in carriers],
    }


def _slot_ids(db_session, trolley_id):
    return list(
        db_session.execute(
            text("SELECT id FROM asset_positions WHERE asset_id = :aid AND position_kind = 'slot' ORDER BY code"),
            {"aid": trolley_id},
        ).scalars()
    )


def _place_in_germination(db_session, tenant, user, farm, s, *, tray_index=0, effective_time=None):
    """Places the Tray into the next free Slot on the Trolley (the Trolley
    itself is placed into the Chamber once, in `_build_scenario`)."""
    # Slots are assigned by raw index -- callers place Trays in increasing
    # tray_index order, so each Tray always claims a distinct, still-free slot.
    slot_id = _slot_ids(db_session, s["trolley"].id)[tray_index]
    return germination_service.place_tray(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        tray_id=s["carriers"][tray_index].id, trolley_id=s["trolley"].id, asset_position_id=slot_id,
        effective_time=effective_time or _now(), reason=None,
    )


def _record_outcome(
    db_session, tenant, user, farm, *, batch_id, assignment_id, normal, abnormal, complete, effective_time,
    client_command_id=None,
):
    return germination_outcome_service.record_germination_outcomes(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch_id,
        client_command_id=client_command_id or uuid.uuid4(), effective_time=effective_time, note=None,
        outcomes=[
            {
                "batch_carrier_assignment_id": assignment_id, "normal_seedling_count": normal,
                "abnormal_seedling_count": abnormal, "assessment_complete": complete, "note": None,
            }
        ],
    )


def _record_entry(
    db_session, tenant, user, farm, *, assignment_id, table_id, effective_time, client_command_id=None, reason=None,
):
    return seedling_entry_service.record_seedling_entry(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=client_command_id or uuid.uuid4(), batch_carrier_assignment_id=assignment_id,
        destination_seedling_table_id=table_id, effective_time=effective_time, reason=reason,
    )


# =====================================================================
# Topology / compatibility (section 6/13/59)
# =====================================================================


@pytest.mark.integration
def test_seed_tray_to_seedling_table_movement_accepted(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    _place_in_germination(db_session, tenant, user, farm, s)
    movement = movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        effective_time=_now(), occupant_kind="carrier", occupant_id=s["carriers"][0].id,
        destination_kind="location", destination_id=s["table_ids"][0], reason=None,
    )
    assert movement.destination_location_id == s["table_ids"][0]


@pytest.mark.integration
def test_wrong_carrier_type_to_seedling_table_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    plate = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        carrier_type_code="cultivation_plate", code=f"CP-{uuid.uuid4().hex[:8]}", issued_date=None,
    )
    with pytest.raises(IncompatibleOccupantTargetError):
        movement_service.execute_movement(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            effective_time=_now(), occupant_kind="carrier", occupant_id=plate.id,
            destination_kind="location", destination_id=s["table_ids"][0], reason=None,
        )


@pytest.mark.integration
def test_seed_tray_to_seedling_area_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    table = location_service.get_location(db_session, tenant_id=tenant.id, farm_id=farm.id, location_id=s["table_ids"][0])
    with pytest.raises(TargetNotOccupiableError):
        movement_service.execute_movement(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            effective_time=_now(), occupant_kind="carrier", occupant_id=s["carriers"][0].id,
            destination_kind="location", destination_id=table.parent_location_id, reason=None,
        )


@pytest.mark.integration
def test_seedling_table_capacity_enforced(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=2, table_count=1, table_capacity=1)
    _place_in_germination(db_session, tenant, user, farm, s, tray_index=0)
    _place_in_germination(db_session, tenant, user, farm, s, tray_index=1)
    movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        effective_time=_now(), occupant_kind="carrier", occupant_id=s["carriers"][0].id,
        destination_kind="location", destination_id=s["table_ids"][0], reason=None,
    )
    with pytest.raises(TargetOccupiedError):
        movement_service.execute_movement(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            effective_time=_now(), occupant_kind="carrier", occupant_id=s["carriers"][1].id,
            destination_kind="location", destination_id=s["table_ids"][0], reason=None,
        )


# =====================================================================
# Entry (section 10/11/26/59)
# =====================================================================


@pytest.mark.integration
def test_valid_entry_freezes_correct_snapshot_and_moves_tray(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    _place_in_germination(db_session, tenant, user, farm, s)
    t1 = _now() - timedelta(hours=1)
    _record_outcome(
        db_session, tenant, user, farm, batch_id=s["batch_id"], assignment_id=s["assignment_ids"][0],
        normal=190, abnormal=6, complete=True, effective_time=t1,
    )
    t2 = _now()
    entry = _record_entry(
        db_session, tenant, user, farm, assignment_id=s["assignment_ids"][0], table_id=s["table_ids"][0],
        effective_time=t2,
    )
    assert entry.starting_living_seedling_count == 196
    assert entry.effective_time == t2
    movement = db_session.get(Movement, entry.movement_id)
    assert movement.destination_location_id == s["table_ids"][0]
    assert movement.occupant_carrier_id == s["carriers"][0].id
    snapshot = db_session.execute(
        text("SELECT normal_seedling_count, abnormal_seedling_count FROM germination_outcome_snapshots WHERE id = :id"),
        {"id": entry.source_germination_outcome_snapshot_id},
    ).mappings().first()
    assert snapshot["normal_seedling_count"] == 190 and snapshot["abnormal_seedling_count"] == 6


@pytest.mark.integration
def test_historical_resolution_picks_snapshot_valid_at_effective_time_not_a_later_one(
    db_session, active_context_with_farm
) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    base = _now() - timedelta(days=2)
    _place_in_germination(db_session, tenant, user, farm, s, effective_time=base - timedelta(hours=1))
    t1 = base
    t2 = base + timedelta(hours=6)
    t3 = base + timedelta(days=1)
    g1 = _record_outcome(
        db_session, tenant, user, farm, batch_id=s["batch_id"], assignment_id=s["assignment_ids"][0],
        normal=190, abnormal=6, complete=True, effective_time=t1,
    )
    _record_outcome(
        db_session, tenant, user, farm, batch_id=s["batch_id"], assignment_id=s["assignment_ids"][0],
        normal=180, abnormal=10, complete=True, effective_time=t3,
    )
    entry = _record_entry(
        db_session, tenant, user, farm, assignment_id=s["assignment_ids"][0], table_id=s["table_ids"][0],
        effective_time=t2,
    )
    g1_snapshot_id = db_session.execute(
        text("SELECT id FROM germination_outcome_snapshots WHERE observation_event_id = :oe"), {"oe": g1.id}
    ).scalar_one()
    assert entry.source_germination_outcome_snapshot_id == g1_snapshot_id
    assert entry.starting_living_seedling_count == 196


@pytest.mark.integration
def test_no_completed_snapshot_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    _place_in_germination(db_session, tenant, user, farm, s)
    with pytest.raises(NoCompletedGerminationHandoffError):
        _record_entry(
            db_session, tenant, user, farm, assignment_id=s["assignment_ids"][0], table_id=s["table_ids"][0],
            effective_time=_now(),
        )


@pytest.mark.integration
def test_provisional_only_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    _place_in_germination(db_session, tenant, user, farm, s)
    _record_outcome(
        db_session, tenant, user, farm, batch_id=s["batch_id"], assignment_id=s["assignment_ids"][0],
        normal=150, abnormal=5, complete=False, effective_time=_now() - timedelta(hours=1),
    )
    with pytest.raises(NoCompletedGerminationHandoffError):
        _record_entry(
            db_session, tenant, user, farm, assignment_id=s["assignment_ids"][0], table_id=s["table_ids"][0],
            effective_time=_now(),
        )


@pytest.mark.integration
def test_future_completed_snapshot_not_selected_for_earlier_entry(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    _place_in_germination(db_session, tenant, user, farm, s)
    base = _now() - timedelta(days=2)
    _record_outcome(
        db_session, tenant, user, farm, batch_id=s["batch_id"], assignment_id=s["assignment_ids"][0],
        normal=190, abnormal=6, complete=True, effective_time=base + timedelta(hours=6),
    )
    with pytest.raises(NoCompletedGerminationHandoffError):
        _record_entry(
            db_session, tenant, user, farm, assignment_id=s["assignment_ids"][0], table_id=s["table_ids"][0],
            effective_time=base,
        )


@pytest.mark.integration
def test_exactly_one_entry_per_assignment(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1, table_count=2)
    _place_in_germination(db_session, tenant, user, farm, s)
    _record_outcome(
        db_session, tenant, user, farm, batch_id=s["batch_id"], assignment_id=s["assignment_ids"][0],
        normal=190, abnormal=6, complete=True, effective_time=_now() - timedelta(hours=1),
    )
    _record_entry(
        db_session, tenant, user, farm, assignment_id=s["assignment_ids"][0], table_id=s["table_ids"][0],
        effective_time=_now(),
    )
    with pytest.raises(SeedlingEntryAlreadyExistsError):
        _record_entry(
            db_session, tenant, user, farm, assignment_id=s["assignment_ids"][0], table_id=s["table_ids"][1],
            effective_time=_now(),
        )
    count = db_session.execute(
        text("SELECT count(*) FROM seedling_entries WHERE batch_carrier_assignment_id = :aid"),
        {"aid": s["assignment_ids"][0]},
    ).scalar_one()
    assert count == 1


@pytest.mark.integration
def test_wrong_table_type_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    _place_in_germination(db_session, tenant, user, farm, s)
    _record_outcome(
        db_session, tenant, user, farm, batch_id=s["batch_id"], assignment_id=s["assignment_ids"][0],
        normal=190, abnormal=6, complete=True, effective_time=_now() - timedelta(hours=1),
    )
    with pytest.raises(SeedlingTableInvalidError):
        _record_entry(
            db_session, tenant, user, farm, assignment_id=s["assignment_ids"][0], table_id=s["chamber_id"],
            effective_time=_now(),
        )


# =====================================================================
# Physical chronology (NURSERY-OPS-003A.1, section 2-9)
# =====================================================================


@pytest.mark.integration
def test_late_entry_with_no_later_movement_succeeds(db_session, active_context_with_farm) -> None:
    """Section 5/9.B: the Tray has moved exactly once (its original
    Germination placement) -- no later physical Movement exists. A late
    operator entry, dated after that original placement's own
    effective_time, does not falsify any physical chronology and must
    succeed."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    placement_time = _now() - timedelta(hours=6)
    _place_in_germination(db_session, tenant, user, farm, s, effective_time=placement_time)
    _record_outcome(
        db_session, tenant, user, farm, batch_id=s["batch_id"], assignment_id=s["assignment_ids"][0],
        normal=190, abnormal=6, complete=True, effective_time=placement_time + timedelta(hours=1),
    )
    entry = _record_entry(
        db_session, tenant, user, farm, assignment_id=s["assignment_ids"][0], table_id=s["table_ids"][0],
        effective_time=placement_time + timedelta(hours=2),
    )
    assert entry.starting_living_seedling_count == 196


@pytest.mark.integration
def test_backdated_entry_after_later_physical_move_rejected(db_session, active_context_with_farm) -> None:
    """Section 2/9.C: the Tray physically moved Germination -> Table A at
    T1 (a bare Movement, not yet a SeedlingEntry), then Table A -> Table B
    at T2 (another bare Movement). A first SeedlingEntry attempt at
    effective_time=T1 targeting Table A would fabricate a Movement dated at
    a point the Tray has since moved past -- must be rejected, not silently
    inserted."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1, table_count=2)
    _place_in_germination(db_session, tenant, user, farm, s, effective_time=_now() - timedelta(hours=4))
    _record_outcome(
        db_session, tenant, user, farm, batch_id=s["batch_id"], assignment_id=s["assignment_ids"][0],
        normal=190, abnormal=6, complete=True, effective_time=_now() - timedelta(hours=3),
    )
    t1 = _now() - timedelta(hours=2)
    movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        effective_time=t1, occupant_kind="carrier", occupant_id=s["carriers"][0].id,
        destination_kind="location", destination_id=s["table_ids"][0], reason=None,
    )
    t2 = _now() - timedelta(hours=1)
    movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        effective_time=t2, occupant_kind="carrier", occupant_id=s["carriers"][0].id,
        destination_kind="location", destination_id=s["table_ids"][1], reason=None,
    )

    movements_before = db_session.execute(
        text("SELECT count(*) FROM movements WHERE occupant_carrier_id = :cid"), {"cid": s["carriers"][0].id}
    ).scalar_one()
    occupancy_before = db_session.execute(
        text("SELECT target_location_id FROM occupancies WHERE occupant_carrier_id = :cid AND end_time IS NULL"),
        {"cid": s["carriers"][0].id},
    ).scalar_one()
    audit_before = db_session.execute(
        text("SELECT count(*) FROM audit_events WHERE tenant_id = :tid AND action = 'crop_batch.seedling_entry_recorded'"),
        {"tid": tenant.id},
    ).scalar_one()

    with pytest.raises(SeedlingEntryPhysicalChronologyError):
        _record_entry(
            db_session, tenant, user, farm, assignment_id=s["assignment_ids"][0], table_id=s["table_ids"][0],
            effective_time=t1,
        )

    entry_count = db_session.execute(
        text("SELECT count(*) FROM seedling_entries WHERE batch_carrier_assignment_id = :aid"),
        {"aid": s["assignment_ids"][0]},
    ).scalar_one()
    movements_after = db_session.execute(
        text("SELECT count(*) FROM movements WHERE occupant_carrier_id = :cid"), {"cid": s["carriers"][0].id}
    ).scalar_one()
    occupancy_after = db_session.execute(
        text("SELECT target_location_id FROM occupancies WHERE occupant_carrier_id = :cid AND end_time IS NULL"),
        {"cid": s["carriers"][0].id},
    ).scalar_one()
    audit_after = db_session.execute(
        text("SELECT count(*) FROM audit_events WHERE tenant_id = :tid AND action = 'crop_batch.seedling_entry_recorded'"),
        {"tid": tenant.id},
    ).scalar_one()

    assert entry_count == 0, "no SeedlingEntry may be created from a rejected temporal chronology"
    assert movements_after == movements_before, "no new (false) Movement may be inserted"
    assert occupancy_after == occupancy_before == s["table_ids"][1], "current Occupancy (Table B) must remain unchanged"
    assert audit_after == audit_before, "no seedling_entry_recorded audit event for a rejected command"


@pytest.mark.integration
def test_replay_after_later_physical_move_still_returns_original(db_session, active_context_with_farm) -> None:
    """Section 7/9.E: a successful SeedlingEntry, replayed by its exact
    client_command_id, must return the original entry/Movement unchanged
    even after the Tray has since physically moved again -- replay never
    re-resolves against current physical chronology."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1, table_count=2)
    _place_in_germination(db_session, tenant, user, farm, s, effective_time=_now() - timedelta(hours=3))
    _record_outcome(
        db_session, tenant, user, farm, batch_id=s["batch_id"], assignment_id=s["assignment_ids"][0],
        normal=190, abnormal=6, complete=True, effective_time=_now() - timedelta(hours=2),
    )
    ccid = uuid.uuid4()
    entry_effective_time = _now() - timedelta(hours=1)
    original = _record_entry(
        db_session, tenant, user, farm, assignment_id=s["assignment_ids"][0], table_id=s["table_ids"][0],
        effective_time=entry_effective_time, client_command_id=ccid,
    )

    # Tray physically moves again, off the Seedling Table this entry anchored.
    movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        effective_time=_now(), occupant_kind="carrier", occupant_id=s["carriers"][0].id,
        destination_kind="location", destination_id=s["table_ids"][1], reason=None,
    )

    replay = seedling_entry_service.record_seedling_entry(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=ccid,
        batch_carrier_assignment_id=s["assignment_ids"][0], destination_seedling_table_id=s["table_ids"][0],
        effective_time=entry_effective_time, reason=None,
    )
    assert replay.id == original.id
    assert replay.movement_id == original.movement_id

    movement_count = db_session.execute(
        text(
            "SELECT count(*) FROM movements WHERE occupant_carrier_id = :cid AND destination_location_id = :loc"
        ),
        {"cid": s["carriers"][0].id, "loc": s["table_ids"][0]},
    ).scalar_one()
    assert movement_count == 1, "replay must not create a second Movement to the original Table"


# =====================================================================
# History / immutability (section 12/16/44/59)
# =====================================================================


@pytest.mark.integration
def test_later_completed_snapshot_does_not_alter_frozen_entry(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    t1 = _now() - timedelta(days=1)
    _place_in_germination(db_session, tenant, user, farm, s, effective_time=t1 - timedelta(hours=2))
    _record_outcome(
        db_session, tenant, user, farm, batch_id=s["batch_id"], assignment_id=s["assignment_ids"][0],
        normal=190, abnormal=6, complete=True, effective_time=t1,
    )
    entry = _record_entry(
        db_session, tenant, user, farm, assignment_id=s["assignment_ids"][0], table_id=s["table_ids"][0],
        effective_time=_now() - timedelta(hours=1),
    )
    original_source = entry.source_germination_outcome_snapshot_id
    original_starting = entry.starting_living_seedling_count

    # A later, historically-valid completed reassessment at effective_time
    # BEFORE t1 (still legal under 002B's own historical-entry model) --
    # must never rewrite the already-frozen entry.
    _record_outcome(
        db_session, tenant, user, farm, batch_id=s["batch_id"], assignment_id=s["assignment_ids"][0],
        normal=195, abnormal=0, complete=True, effective_time=t1 - timedelta(hours=1),
    )
    refreshed = db_session.execute(
        text("SELECT source_germination_outcome_snapshot_id, starting_living_seedling_count FROM seedling_entries WHERE id = :id"),
        {"id": entry.id},
    ).mappings().first()
    assert refreshed["source_germination_outcome_snapshot_id"] == original_source
    assert refreshed["starting_living_seedling_count"] == original_starting == 196


@pytest.mark.integration
def test_seedling_entry_immutable_no_update_no_delete(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    _place_in_germination(db_session, tenant, user, farm, s)
    _record_outcome(
        db_session, tenant, user, farm, batch_id=s["batch_id"], assignment_id=s["assignment_ids"][0],
        normal=190, abnormal=6, complete=True, effective_time=_now() - timedelta(hours=1),
    )
    entry = _record_entry(
        db_session, tenant, user, farm, assignment_id=s["assignment_ids"][0], table_id=s["table_ids"][0],
        effective_time=_now(),
    )
    with pytest.raises(DBAPIError):
        db_session.execute(
            text("UPDATE seedling_entries SET starting_living_seedling_count = 1 WHERE id = :id"), {"id": entry.id}
        )
        db_session.flush()
    db_session.rollback()
    with pytest.raises(DBAPIError):
        db_session.execute(text("DELETE FROM seedling_entries WHERE id = :id"), {"id": entry.id})
        db_session.flush()
    db_session.rollback()


# =====================================================================
# Atomicity (section 15/52/59)
# =====================================================================


@pytest.mark.integration
def test_movement_failure_creates_no_seedling_entry(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=2, table_count=1, table_capacity=1)
    _place_in_germination(db_session, tenant, user, farm, s, tray_index=0)
    _place_in_germination(db_session, tenant, user, farm, s, tray_index=1)
    for i in range(2):
        _record_outcome(
            db_session, tenant, user, farm, batch_id=s["batch_id"], assignment_id=s["assignment_ids"][i],
            normal=190, abnormal=6, complete=True, effective_time=_now() - timedelta(hours=1),
        )
    _record_entry(
        db_session, tenant, user, farm, assignment_id=s["assignment_ids"][0], table_id=s["table_ids"][0],
        effective_time=_now(),
    )
    with pytest.raises(TargetOccupiedError):
        _record_entry(
            db_session, tenant, user, farm, assignment_id=s["assignment_ids"][1], table_id=s["table_ids"][0],
            effective_time=_now(),
        )
    count = db_session.execute(
        text("SELECT count(*) FROM seedling_entries WHERE batch_carrier_assignment_id = :aid"),
        {"aid": s["assignment_ids"][1]},
    ).scalar_one()
    assert count == 0
    # Tray 2 must remain wherever it was (Germination), not half-moved.
    occ = movement_service.get_occupancy(
        db_session, tenant_id=tenant.id, farm_id=farm.id, occupant_kind="carrier", occupant_id=s["carriers"][1].id
    )
    assert occ.target_location_id is None  # still on an asset_position (trolley slot), not a Location


# =====================================================================
# DB direct-write integrity (section 47/59) -- defense in depth
# =====================================================================


def _valid_entry_ingredients(db_session, tenant, user, farm, s, *, tray_index=0, table_index=0):
    _place_in_germination(db_session, tenant, user, farm, s, tray_index=tray_index)
    t1 = _now() - timedelta(hours=1)
    event = _record_outcome(
        db_session, tenant, user, farm, batch_id=s["batch_id"], assignment_id=s["assignment_ids"][tray_index],
        normal=190, abnormal=6, complete=True, effective_time=t1,
    )
    snapshot_id = db_session.execute(
        text("SELECT id FROM germination_outcome_snapshots WHERE observation_event_id = :oe"), {"oe": event.id}
    ).scalar_one()
    t2 = _now()
    movement = movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        effective_time=t2, occupant_kind="carrier", occupant_id=s["carriers"][tray_index].id,
        destination_kind="location", destination_id=s["table_ids"][table_index], reason=None,
    )
    return snapshot_id, movement, t2


def _raw_insert_seedling_entry(db_session, tenant, farm, s, *, tray_index, snapshot_id, movement_id, starting_count, effective_time):
    db_session.execute(
        text(
            "INSERT INTO seedling_entries "
            "(id, tenant_id, farm_id, batch_id, batch_carrier_assignment_id, "
            "source_germination_outcome_snapshot_id, movement_id, starting_living_seedling_count, "
            "effective_time, actor_user_id, client_command_id, request_fingerprint) "
            "VALUES (gen_random_uuid(), :tid, :fid, :bid, :aid, :sid, :mid, :cnt, :eff, NULL, gen_random_uuid(), 'x')"
        ),
        {
            "tid": tenant.id, "fid": farm.id, "bid": s["batch_id"], "aid": s["assignment_ids"][tray_index],
            "sid": snapshot_id, "mid": movement_id, "cnt": starting_count, "eff": effective_time,
        },
    )
    db_session.flush()


@pytest.mark.integration
def test_direct_write_wrong_starting_count_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    snapshot_id, movement, t2 = _valid_entry_ingredients(db_session, tenant, user, farm, s)
    with pytest.raises(DBAPIError, match="starting_living_seedling_count"):
        _raw_insert_seedling_entry(
            db_session, tenant, farm, s, tray_index=0, snapshot_id=snapshot_id, movement_id=movement.id,
            starting_count=999, effective_time=t2,
        )
    db_session.rollback()


@pytest.mark.integration
def test_direct_write_incomplete_snapshot_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    _place_in_germination(db_session, tenant, user, farm, s)
    event = _record_outcome(
        db_session, tenant, user, farm, batch_id=s["batch_id"], assignment_id=s["assignment_ids"][0],
        normal=150, abnormal=5, complete=False, effective_time=_now() - timedelta(hours=1),
    )
    snapshot_id = db_session.execute(
        text("SELECT id FROM germination_outcome_snapshots WHERE observation_event_id = :oe"), {"oe": event.id}
    ).scalar_one()
    movement = movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        effective_time=_now(), occupant_kind="carrier", occupant_id=s["carriers"][0].id,
        destination_kind="location", destination_id=s["table_ids"][0], reason=None,
    )
    with pytest.raises(DBAPIError, match="completed assessment"):
        _raw_insert_seedling_entry(
            db_session, tenant, farm, s, tray_index=0, snapshot_id=snapshot_id, movement_id=movement.id,
            starting_count=155, effective_time=movement.effective_time,
        )
    db_session.rollback()


@pytest.mark.integration
def test_direct_write_cross_assignment_snapshot_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=2, table_count=2)
    _place_in_germination(db_session, tenant, user, farm, s, tray_index=0)
    _place_in_germination(db_session, tenant, user, farm, s, tray_index=1)
    event0 = _record_outcome(
        db_session, tenant, user, farm, batch_id=s["batch_id"], assignment_id=s["assignment_ids"][0],
        normal=190, abnormal=6, complete=True, effective_time=_now() - timedelta(hours=1),
    )
    snapshot0_id = db_session.execute(
        text("SELECT id FROM germination_outcome_snapshots WHERE observation_event_id = :oe"), {"oe": event0.id}
    ).scalar_one()
    movement1 = movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        effective_time=_now(), occupant_kind="carrier", occupant_id=s["carriers"][1].id,
        destination_kind="location", destination_id=s["table_ids"][1], reason=None,
    )
    with pytest.raises(DBAPIError, match="does not belong to this assignment"):
        _raw_insert_seedling_entry(
            db_session, tenant, farm, s, tray_index=1, snapshot_id=snapshot0_id, movement_id=movement1.id,
            starting_count=196, effective_time=movement1.effective_time,
        )
    db_session.rollback()


@pytest.mark.integration
def test_direct_write_movement_wrong_destination_type_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    _place_in_germination(db_session, tenant, user, farm, s)
    event = _record_outcome(
        db_session, tenant, user, farm, batch_id=s["batch_id"], assignment_id=s["assignment_ids"][0],
        normal=190, abnormal=6, complete=True, effective_time=_now() - timedelta(hours=1),
    )
    snapshot_id = db_session.execute(
        text("SELECT id FROM germination_outcome_snapshots WHERE observation_event_id = :oe"), {"oe": event.id}
    ).scalar_one()
    # Movement still physically inside Germination (Trolley Slot), never
    # reaching a seedling_table -- the entry must not be freezable on top of it.
    slot_movement_id = db_session.execute(
        text(
            "SELECT opened_by_movement_id FROM occupancies WHERE occupant_carrier_id = :cid AND end_time IS NULL"
        ),
        {"cid": s["carriers"][0].id},
    ).scalar_one()
    movement_effective = db_session.execute(
        text("SELECT effective_time FROM movements WHERE id = :mid"), {"mid": slot_movement_id}
    ).scalar_one()
    with pytest.raises(DBAPIError, match="must be a seedling_table location"):
        _raw_insert_seedling_entry(
            db_session, tenant, farm, s, tray_index=0, snapshot_id=snapshot_id, movement_id=slot_movement_id,
            starting_count=196, effective_time=movement_effective,
        )
    db_session.rollback()


@pytest.mark.integration
def test_direct_write_duplicate_assignment_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1, table_count=2)
    _record_outcome(
        db_session, tenant, user, farm, batch_id=s["batch_id"], assignment_id=s["assignment_ids"][0],
        normal=190, abnormal=6, complete=True, effective_time=_now() - timedelta(hours=1),
    )
    _place_in_germination(db_session, tenant, user, farm, s)
    entry = _record_entry(
        db_session, tenant, user, farm, assignment_id=s["assignment_ids"][0], table_id=s["table_ids"][0],
        effective_time=_now(),
    )
    movement2 = movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        effective_time=_now(), occupant_kind="carrier", occupant_id=s["carriers"][0].id,
        destination_kind="location", destination_id=s["table_ids"][1], reason=None,
    )
    with pytest.raises(DBAPIError):
        _raw_insert_seedling_entry(
            db_session, tenant, farm, s, tray_index=0, snapshot_id=entry.source_germination_outcome_snapshot_id,
            movement_id=movement2.id, starting_count=196, effective_time=movement2.effective_time,
        )
    db_session.rollback()


# =====================================================================
# No side effects (section 34/55/59)
# =====================================================================


@pytest.mark.integration
def test_no_side_effects_on_assignment_batch_or_germination_history(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    _place_in_germination(db_session, tenant, user, farm, s)
    event = _record_outcome(
        db_session, tenant, user, farm, batch_id=s["batch_id"], assignment_id=s["assignment_ids"][0],
        normal=190, abnormal=6, complete=True, effective_time=_now() - timedelta(hours=1),
    )
    before_assignment = dict(
        db_session.execute(
            text(
                "SELECT batch_id, carrier_id, batch_stage_run_id, assigned_effective_time, released_effective_time "
                "FROM batch_carrier_assignments WHERE id = :id"
            ),
            {"id": s["assignment_ids"][0]},
        ).mappings().first()
    )
    before_batch = dict(
        db_session.execute(text("SELECT state, code FROM crop_batches WHERE id = :id"), {"id": s["batch_id"]}).mappings().first()
    )
    before_snapshot = dict(
        db_session.execute(
            text("SELECT normal_seedling_count, abnormal_seedling_count, assessment_complete FROM germination_outcome_snapshots WHERE observation_event_id = :oe"),
            {"oe": event.id},
        ).mappings().first()
    )
    transitions_before = db_session.execute(
        text("SELECT count(*) FROM batch_stage_transitions WHERE batch_id = :bid"), {"bid": s["batch_id"]}
    ).scalar_one()
    assignment_count_before = db_session.execute(
        text("SELECT count(*) FROM batch_carrier_assignments WHERE batch_id = :bid"), {"bid": s["batch_id"]}
    ).scalar_one()

    _record_entry(
        db_session, tenant, user, farm, assignment_id=s["assignment_ids"][0], table_id=s["table_ids"][0],
        effective_time=_now(),
    )

    after_assignment = dict(
        db_session.execute(
            text(
                "SELECT batch_id, carrier_id, batch_stage_run_id, assigned_effective_time, released_effective_time "
                "FROM batch_carrier_assignments WHERE id = :id"
            ),
            {"id": s["assignment_ids"][0]},
        ).mappings().first()
    )
    after_batch = dict(
        db_session.execute(text("SELECT state, code FROM crop_batches WHERE id = :id"), {"id": s["batch_id"]}).mappings().first()
    )
    after_snapshot = dict(
        db_session.execute(
            text("SELECT normal_seedling_count, abnormal_seedling_count, assessment_complete FROM germination_outcome_snapshots WHERE observation_event_id = :oe"),
            {"oe": event.id},
        ).mappings().first()
    )
    transitions_after = db_session.execute(
        text("SELECT count(*) FROM batch_stage_transitions WHERE batch_id = :bid"), {"bid": s["batch_id"]}
    ).scalar_one()
    assignment_count_after = db_session.execute(
        text("SELECT count(*) FROM batch_carrier_assignments WHERE batch_id = :bid"), {"bid": s["batch_id"]}
    ).scalar_one()

    assert before_assignment == after_assignment
    assert before_batch == after_batch
    assert before_snapshot == after_snapshot
    # transitions_before already reflects the batch's own initial_entry row
    # (created at CropBatch creation, unrelated to this ticket) -- what
    # matters is that recording a SeedlingEntry adds no NEW transition.
    assert transitions_before == transitions_after
    assert assignment_count_before == assignment_count_after


# =====================================================================
# Concurrency (section 29/30/31/53/59) -- separate committed sessions
# =====================================================================


def _build_committed_scenario(test_engine, *, tray_count=2, table_count=2, table_capacity=None):
    conn = test_engine.connect()
    session = Session(bind=conn)
    from app.services import farm_service, membership_service, tenant_service, user_service

    suffix = uuid.uuid4().hex[:10]
    tenant = tenant_service.create_tenant(session, code=f"seed-conc-{suffix}", name="Seedling Concurrency Tenant")
    user = user_service.create_user(
        session, oidc_issuer="seed-conc", oidc_subject=suffix, email=f"seed-conc-{suffix}@example.com",
        display_name="Seedling Conc User",
    )
    membership_service.add_membership(session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None)
    farm = farm_service.create_farm(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Seedling Conc Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    s = _build_scenario(session, tenant, user, farm, suffix=suffix, tray_count=tray_count, table_count=table_count, table_capacity=table_capacity)
    # Well before any concurrency test's own effective_time (which range
    # from "now" down to "now minus a few minutes") -- avoids the generic
    # Movement rule that effective_time may never precede the occupant's
    # current active occupancy.
    placement_time = _now() - timedelta(hours=6)
    for i in range(tray_count):
        _place_in_germination(session, tenant, user, farm, s, tray_index=i, effective_time=placement_time)
        _record_outcome(
            session, tenant, user, farm, batch_id=s["batch_id"], assignment_id=s["assignment_ids"][i],
            normal=190, abnormal=6, complete=True, effective_time=_now() - timedelta(hours=1),
        )
    session.commit()
    result = {
        "tenant_id": tenant.id, "user_id": user.id, "farm_id": farm.id,
        "assignment_ids": s["assignment_ids"], "table_ids": s["table_ids"], "carrier_ids": [c.id for c in s["carriers"]],
    }
    session.close()
    conn.close()
    return result


def _entry_worker(test_engine, results, name, *, tenant_id, farm_id, user_id, client_command_id, assignment_id, table_id, effective_time, barrier):
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        barrier.wait(timeout=10)
        entry = seedling_entry_service.record_seedling_entry(
            session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=user_id, client_command_id=client_command_id,
            batch_carrier_assignment_id=assignment_id, destination_seedling_table_id=table_id,
            effective_time=effective_time, reason=None,
        )
        results[name] = ("ok", entry.id, entry.source_germination_outcome_snapshot_id, entry.starting_living_seedling_count)
    except SeedlingEntryAlreadyExistsError as exc:
        session.rollback()
        results[name] = ("already_exists", str(exc))
    except TargetOccupiedError as exc:
        session.rollback()
        results[name] = ("target_occupied", str(exc))
    except Exception as exc:  # pragma: no cover - surfaced via assertion below
        session.rollback()
        results[name] = ("error", repr(exc))
    finally:
        session.close()
        conn.close()


@pytest.mark.integration
def test_concurrent_same_command_id_resolves_to_single_entry(test_engine) -> None:
    scenario = _build_committed_scenario(test_engine, tray_count=1, table_count=1)
    try:
        ccid = uuid.uuid4()
        effective_time = _now()
        barrier = threading.Barrier(2)
        results: dict[str, object] = {}
        threads = [
            threading.Thread(
                target=_entry_worker, args=(test_engine, results, name),
                kwargs=dict(
                    tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], user_id=scenario["user_id"],
                    client_command_id=ccid, assignment_id=scenario["assignment_ids"][0],
                    table_id=scenario["table_ids"][0], effective_time=effective_time, barrier=barrier,
                ),
            )
            for name in ("a", "b")
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        assert results["a"][0] == "ok" and results["b"][0] == "ok", results
        assert results["a"][1] == results["b"][1], "both calls must resolve to the SAME SeedlingEntry"

        check_conn = test_engine.connect()
        try:
            entry_count = check_conn.execute(
                text("SELECT count(*) FROM seedling_entries WHERE tenant_id = :tid"), {"tid": scenario["tenant_id"]}
            ).scalar_one()
            movement_count = check_conn.execute(
                text("SELECT count(*) FROM movements WHERE tenant_id = :tid AND destination_location_id = :loc"),
                {"tid": scenario["tenant_id"], "loc": scenario["table_ids"][0]},
            ).scalar_one()
        finally:
            check_conn.close()
        assert entry_count == 1
        assert movement_count == 1, "exact replay must not create a second Movement"
    finally:
        cleanup_traceability_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_concurrent_different_commands_same_tray_exactly_one_entry(test_engine) -> None:
    scenario = _build_committed_scenario(test_engine, tray_count=1, table_count=2)
    try:
        effective_time = _now()
        barrier = threading.Barrier(2)
        results: dict[str, object] = {}
        threads = [
            threading.Thread(
                target=_entry_worker, args=(test_engine, results, name),
                kwargs=dict(
                    tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], user_id=scenario["user_id"],
                    client_command_id=uuid.uuid4(), assignment_id=scenario["assignment_ids"][0],
                    table_id=scenario["table_ids"][i], effective_time=effective_time, barrier=barrier,
                ),
            )
            for i, name in enumerate(("a", "b"))
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("already_exists") == 1, results

        check_conn = test_engine.connect()
        try:
            entry_count = check_conn.execute(
                text("SELECT count(*) FROM seedling_entries WHERE batch_carrier_assignment_id = :aid"),
                {"aid": scenario["assignment_ids"][0]},
            ).scalar_one()
            active_occupancy_count = check_conn.execute(
                text("SELECT count(*) FROM occupancies WHERE occupant_carrier_id = :cid AND end_time IS NULL"),
                {"cid": scenario["carrier_ids"][0]},
            ).scalar_one()
        finally:
            check_conn.close()
        assert entry_count == 1
        assert active_occupancy_count == 1, "no double current Occupancy"
    finally:
        cleanup_traceability_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_concurrent_two_trays_race_last_table_slot(test_engine) -> None:
    scenario = _build_committed_scenario(test_engine, tray_count=2, table_count=1, table_capacity=1)
    try:
        effective_time = _now()
        barrier = threading.Barrier(2)
        results: dict[str, object] = {}
        threads = [
            threading.Thread(
                target=_entry_worker, args=(test_engine, results, name),
                kwargs=dict(
                    tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], user_id=scenario["user_id"],
                    client_command_id=uuid.uuid4(), assignment_id=scenario["assignment_ids"][i],
                    table_id=scenario["table_ids"][0], effective_time=effective_time, barrier=barrier,
                ),
            )
            for i, name in enumerate(("a", "b"))
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("target_occupied") == 1, results

        check_conn = test_engine.connect()
        try:
            entry_count = check_conn.execute(
                text("SELECT count(*) FROM seedling_entries WHERE tenant_id = :tid"), {"tid": scenario["tenant_id"]}
            ).scalar_one()
            active_at_table = check_conn.execute(
                text("SELECT count(*) FROM occupancies WHERE target_location_id = :loc AND end_time IS NULL"),
                {"loc": scenario["table_ids"][0]},
            ).scalar_one()
        finally:
            check_conn.close()
        assert entry_count == 1, "the losing command must create no partial audit artifact that falsely claims entry"
        assert active_at_table == 1
    finally:
        cleanup_traceability_scenario(test_engine, scenario["tenant_id"])


def _reassess_worker(test_engine, results, *, tenant_id, farm_id, user_id, batch_id, assignment_id, effective_time, barrier):
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        barrier.wait(timeout=10)
        germination_outcome_service.record_germination_outcomes(
            session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=user_id, batch_id=batch_id,
            client_command_id=uuid.uuid4(), effective_time=effective_time, note=None,
            outcomes=[
                {
                    "batch_carrier_assignment_id": assignment_id, "normal_seedling_count": 180,
                    "abnormal_seedling_count": 15, "assessment_complete": True, "note": None,
                }
            ],
        )
        session.commit()
        results["reassess"] = ("ok",)
    except Exception as exc:  # pragma: no cover
        session.rollback()
        results["reassess"] = ("error", repr(exc))
    finally:
        session.close()
        conn.close()


@pytest.mark.integration
def test_concurrent_germination_reassessment_does_not_corrupt_entry_consistency(test_engine) -> None:
    """Section 31: a newer completed snapshot (G2, whose own effective_time
    is deliberately AFTER the entry's effective_time, so it is never
    eligible for THIS entry's resolution regardless of commit ordering) is
    recorded concurrently with the SeedlingEntry command. The entry must
    deterministically freeze G1 (id and quantity from the SAME row) --
    never a mixed id/count pairing, never G2."""
    scenario = _build_committed_scenario(test_engine, tray_count=1, table_count=1)
    try:
        entry_effective_time = _now() - timedelta(minutes=10)
        g2_effective_time = _now() - timedelta(minutes=5)
        barrier = threading.Barrier(2)
        results: dict[str, object] = {}

        check_conn = test_engine.connect()
        batch_id = check_conn.execute(
            text("SELECT batch_id FROM batch_carrier_assignments WHERE id = :aid"),
            {"aid": scenario["assignment_ids"][0]},
        ).scalar_one()
        check_conn.close()

        t_entry = threading.Thread(
            target=_entry_worker, args=(test_engine, results, "entry"),
            kwargs=dict(
                tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], user_id=scenario["user_id"],
                client_command_id=uuid.uuid4(), assignment_id=scenario["assignment_ids"][0],
                table_id=scenario["table_ids"][0], effective_time=entry_effective_time, barrier=barrier,
            ),
        )
        t_reassess = threading.Thread(
            target=_reassess_worker, args=(test_engine, results),
            kwargs=dict(
                tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], user_id=scenario["user_id"],
                batch_id=batch_id, assignment_id=scenario["assignment_ids"][0], effective_time=g2_effective_time,
                barrier=barrier,
            ),
        )

        t_entry.start()
        t_reassess.start()
        t_entry.join(timeout=15)
        t_reassess.join(timeout=15)
        assert results["entry"][0] == "ok", results
        assert results["reassess"][0] == "ok", results
        assert results["entry"][3] == 196, "must freeze G1 (190+6), never G2 (180+15=195)"

        check_conn = test_engine.connect()
        try:
            row = check_conn.execute(
                text("SELECT starting_living_seedling_count FROM seedling_entries WHERE id = :id"),
                {"id": results["entry"][1]},
            ).mappings().first()
        finally:
            check_conn.close()
        assert row["starting_living_seedling_count"] == 196
    finally:
        cleanup_traceability_scenario(test_engine, scenario["tenant_id"])
