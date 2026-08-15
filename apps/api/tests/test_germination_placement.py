"""NURSERY-OPS-002A: Germination Placement (physical placement only, no
biological outcome). Frozen authoritative model: a Germination Trolley
Asset occupies a Germination Chamber Location directly (no
chamber_position); a Seed Tray Carrier occupies a Trolley Slot
AssetPosition. Reuses `movement_service.execute_movement` verbatim via
`germination_service`'s thin orchestration layer -- this file tests only
the new Germination-specific validation/reads, not generic Movement/
Occupancy mechanics already proven in test_movement*.py/
test_occupancy_capacity*.py."""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select, text

from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.occupancy import Occupancy
from app.schemas.farm_setup import (
    GerminationChamberSetupConfig,
    GreenhouseSetupCreate,
    NurserySectionConfig,
    NurserySetupConfig,
    TrolleyLevelGeneratorConfig,
    TrolleySetupConfig,
)
from app.services import (
    asset_service,
    carrier_service,
    crop_service,
    farm_setup_service,
    germination_service,
    location_service,
    nursery_service,
    production_system_service,
    sowing_service,
    workflow_service,
)
from app.services.errors import (
    AssetPositionNotFoundError,
    AssetNotFoundError,
    GerminationChamberInvalidError,
    GerminationTraySlotInvalidError,
    GerminationTrolleyInvalidError,
    IncompatibleOccupantTargetError,
    LocationNotFoundError,
    TargetNotOccupiableError,
    TargetOccupiedError,
    TrayNotSownError,
    TrolleyNotInGerminationError,
)


def _now():
    return datetime.now(timezone.utc)


def _build_scenario(db_session, tenant, user, farm, *, suffix=None, chamber_capacity=None, trolley_count=1, tray_count=2):
    """A complete Germination-ready Nursery: Greenhouse + Seeding Station +
    Germination Chamber (via Farm Setup), `trolley_count` Germination
    Trolleys (8 shelves x 5 slots each), one Sown Crop Batch with
    `tray_count` Seed Trays carrying active, sowing-origin
    BatchCarrierAssignments."""
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
                germination_chamber=GerminationChamberSetupConfig(code=f"GC-{suffix}", trolley_capacity=chamber_capacity),
            ),
        ),
    )
    structure = farm_setup_service.get_greenhouse_structure(
        db_session.connection(), tenant_id=tenant.id, farm_id=farm.id, greenhouse_id=setup.greenhouse_id,
    )
    seeding_station_id = structure.nursery_seeding_stations[0].id
    chamber_id = structure.nursery_germination_chamber.id

    trolleys = []
    for t in range(trolley_count):
        trolley = asset_service.register_asset(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            asset_type_code="germination_trolley", code=f"GT-{suffix}-{t}", name=f"Trolley {t}", commissioned_date=None,
        )
        asset_service.generate_positions(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, asset_id=trolley.id,
            shelf_count=2, slots_per_shelf=2, shelf_prefix=f"SH-{suffix}-{t}-", slot_prefix="SL-",
            shelf_pad_width=2, slot_pad_width=2,
        )
        trolleys.append(trolley)

    carriers = [
        carrier_service.register_carrier(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            carrier_type_code="seed_tray", code=f"ST-{suffix}-{n:04d}", issued_date=None,
        )
        for n in range(1, tray_count + 1)
    ]

    event = nursery_service.sow_new_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        seed_lot_id=seed_lot.id, seeding_station_id=seeding_station_id, seeding_machine_id=None,
        effective_time=_now(), note=None,
        trays=[{"carrier_id": c.id, "seeds_sown": 200} for c in carriers],
    )

    return {
        "crop": crop, "variety": variety, "seed_lot": seed_lot, "chamber_id": chamber_id,
        "greenhouse_id": setup.greenhouse_id, "trolleys": trolleys, "carriers": carriers,
        "batch_id": event.batch_id, "sowing_event_id": event.id,
    }


def _place_trolley(db_session, tenant, user, farm, s, *, trolley_index=0, chamber_id=None, client_command_id=None):
    return germination_service.place_trolley_in_chamber(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=client_command_id or uuid.uuid4(),
        trolley_id=s["trolleys"][trolley_index].id, chamber_id=chamber_id or s["chamber_id"],
        effective_time=_now(), reason=None,
    )


def _slot_ids(db_session, trolley_id):
    rows = db_session.execute(
        text("SELECT id FROM asset_positions WHERE asset_id = :aid AND position_kind = 'slot' ORDER BY code"),
        {"aid": trolley_id},
    ).scalars().all()
    return list(rows)


def _place_tray(db_session, tenant, user, farm, s, *, tray_index=0, trolley_index=0, slot_id=None, client_command_id=None):
    slot_id = slot_id or _slot_ids(db_session, s["trolleys"][trolley_index].id)[0]
    return germination_service.place_tray_in_slot(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=client_command_id or uuid.uuid4(),
        tray_id=s["carriers"][tray_index].id, trolley_id=s["trolleys"][trolley_index].id, slot_id=slot_id,
        effective_time=_now(), reason=None,
    )


# =====================================================================
# Farm Setup (section 42)
# =====================================================================


@pytest.mark.integration
def test_farm_setup_chamber_is_occupiable_with_capacity_and_no_chamber_position(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, chamber_capacity=4, trolley_count=0, tray_count=1)
    chamber = location_service.get_location(db_session, tenant_id=tenant.id, farm_id=farm.id, location_id=s["chamber_id"])
    assert chamber.occupiable is True
    assert chamber.capacity == 4
    children = location_service.list_children(db_session, tenant_id=tenant.id, farm_id=farm.id, location_id=s["chamber_id"])
    assert children == []


@pytest.mark.integration
def test_generic_location_create_defaults_germination_chamber_occupiable_true(db_session, active_context_with_farm) -> None:
    """NURSERY-OPS-002A.1: occupiable=true must be true of ANY Germination
    Chamber created through ANY authorized path, not merely a Farm-Setup
    override layered on top of a catalog default that still says otherwise.
    Uses the real, generic `location_service.create_location` -- the same
    service function an authorized generic Location caller (e.g. the plain
    `POST /farms/{farm_id}/locations` route) uses -- with no explicit
    `occupiable` override, to prove the LocationType catalog's own
    `default_occupiable` is what now governs, independent of Farm Setup."""
    tenant, user, _headers, farm = active_context_with_farm
    suffix = uuid.uuid4().hex[:8]
    greenhouse = location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="greenhouse", code=f"NUR-{suffix}", name="Nursery",
        parent_location_id=None, greenhouse_classification="nursery", occupiable=None,
    )
    chamber = location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="germination_chamber", code=f"GC-{suffix}", name="Germination Chamber",
        parent_location_id=greenhouse.id, greenhouse_classification=None, occupiable=None,
    )
    assert chamber.occupiable is True


# =====================================================================
# Trolley placement (section 13)
# =====================================================================


@pytest.mark.integration
def test_trolley_initial_placement_into_chamber(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    movement = _place_trolley(db_session, tenant, user, farm, s)
    assert movement.destination_location_id == s["chamber_id"]
    assert movement.source_location_id is None


@pytest.mark.integration
def test_trolley_move_chamber_to_chamber(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    other_chamber = location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="germination_chamber", code=f"GC2-{uuid.uuid4().hex[:8]}", name="Second Chamber",
        parent_location_id=s["greenhouse_id"], greenhouse_classification=None, occupiable=True,
    )
    _place_trolley(db_session, tenant, user, farm, s)
    moved = _place_trolley(db_session, tenant, user, farm, s, chamber_id=other_chamber.id)
    assert moved.source_location_id == s["chamber_id"]
    assert moved.destination_location_id == other_chamber.id


@pytest.mark.integration
def test_trolley_placement_capacity_enforced(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, chamber_capacity=1, trolley_count=2, tray_count=1)
    _place_trolley(db_session, tenant, user, farm, s, trolley_index=0)
    with pytest.raises(TargetOccupiedError):
        _place_trolley(db_session, tenant, user, farm, s, trolley_index=1)


@pytest.mark.integration
def test_trolley_placement_wrong_asset_type_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, trolley_count=0, tray_count=1)
    scale = asset_service.register_asset(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        asset_type_code="weighing_scale", code=f"WS-{uuid.uuid4().hex[:8]}", name="Scale", commissioned_date=None,
    )
    with pytest.raises(GerminationTrolleyInvalidError):
        germination_service.place_trolley_in_chamber(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            trolley_id=scale.id, chamber_id=s["chamber_id"], effective_time=_now(), reason=None,
        )


@pytest.mark.integration
def test_trolley_placement_non_germination_target_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    with pytest.raises(GerminationChamberInvalidError):
        germination_service.place_trolley_in_chamber(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            trolley_id=s["trolleys"][0].id, chamber_id=s["greenhouse_id"], effective_time=_now(), reason=None,
        )


@pytest.mark.integration
def test_trolley_placement_wrong_farm_chamber_rejected(db_session, active_context_with_farm) -> None:
    from app.services import farm_service

    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    other_farm = farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{uuid.uuid4().hex[:8]}",
        name="Other Farm", country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    other_gh = location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=other_farm.id, actor_user_id=user.id,
        location_type_code="greenhouse", code=f"ogh-{uuid.uuid4().hex[:8]}", name="Other GH",
        parent_location_id=None, greenhouse_classification="nursery", occupiable=None,
    )
    other_chamber = location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=other_farm.id, actor_user_id=user.id,
        location_type_code="germination_chamber", code=f"ogc-{uuid.uuid4().hex[:8]}", name="Other Chamber",
        parent_location_id=other_gh.id, greenhouse_classification=None, occupiable=True,
    )
    with pytest.raises(LocationNotFoundError):
        germination_service.place_trolley_in_chamber(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            trolley_id=s["trolleys"][0].id, chamber_id=other_chamber.id, effective_time=_now(), reason=None,
        )


# =====================================================================
# Tray placement (sections 15-16)
# =====================================================================


@pytest.mark.integration
def test_tray_placement_into_trolley_slot(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    _place_trolley(db_session, tenant, user, farm, s)
    movement = _place_tray(db_session, tenant, user, farm, s)
    assert movement.destination_asset_position_id is not None
    assert movement.source_asset_position_id is None


@pytest.mark.integration
def test_tray_placement_requires_active_batch_carrier_assignment(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    _place_trolley(db_session, tenant, user, farm, s)
    unsown_tray = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        carrier_type_code="seed_tray", code=f"ST-UNSOWN-{uuid.uuid4().hex[:8]}", issued_date=None,
    )
    slot_id = _slot_ids(db_session, s["trolleys"][0].id)[0]
    with pytest.raises(TrayNotSownError):
        germination_service.place_tray_in_slot(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            tray_id=unsown_tray.id, trolley_id=s["trolleys"][0].id, slot_id=slot_id, effective_time=_now(), reason=None,
        )


@pytest.mark.integration
def test_tray_placement_wrong_carrier_type_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    _place_trolley(db_session, tenant, user, farm, s)
    grow_bag = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        carrier_type_code="grow_bag", code=f"GB-{uuid.uuid4().hex[:8]}", issued_date=None,
    )
    slot_id = _slot_ids(db_session, s["trolleys"][0].id)[0]
    with pytest.raises(GerminationTraySlotInvalidError):
        germination_service.place_tray_in_slot(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            tray_id=grow_bag.id, trolley_id=s["trolleys"][0].id, slot_id=slot_id, effective_time=_now(), reason=None,
        )


@pytest.mark.integration
def test_tray_placement_on_trolley_not_in_germination_rejected(db_session, active_context_with_farm) -> None:
    """Section 16's central rule: even though the generic Movement primitive
    would happily allow it, placing a tray onto a Trolley that is not
    currently in a Germination Chamber must be rejected by this
    Germination-specific orchestration."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    # Trolley never placed anywhere.
    with pytest.raises(TrolleyNotInGerminationError):
        _place_tray(db_session, tenant, user, farm, s)


@pytest.mark.integration
def test_tray_placement_slot_not_belonging_to_trolley_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, trolley_count=2, tray_count=1)
    _place_trolley(db_session, tenant, user, farm, s, trolley_index=0)
    other_trolley_slot = _slot_ids(db_session, s["trolleys"][1].id)[0]
    with pytest.raises(AssetPositionNotFoundError):
        germination_service.place_tray_in_slot(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            tray_id=s["carriers"][0].id, trolley_id=s["trolleys"][0].id, slot_id=other_trolley_slot,
            effective_time=_now(), reason=None,
        )


@pytest.mark.integration
def test_tray_placement_wrong_tenant_trolley_rejected(db_session, active_context_with_farm) -> None:
    from app.services import farm_service, membership_service, tenant_service, user_service

    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    suffix = uuid.uuid4().hex[:8]
    other_tenant = tenant_service.create_tenant(db_session, code=f"other-{suffix}", name="Other")
    other_user = user_service.create_user(
        db_session, oidc_issuer="other", oidc_subject=suffix, email=f"{suffix}@example.com", display_name="Other",
    )
    membership_service.add_membership(db_session, tenant_id=other_tenant.id, user_id=other_user.id, role_code="tenant_admin", actor_user_id=None)
    other_farm = farm_service.create_farm(
        db_session, tenant_id=other_tenant.id, actor_user_id=other_user.id, code=f"farm-{suffix}", name="Other Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    other_trolley = asset_service.register_asset(
        db_session, tenant_id=other_tenant.id, farm_id=other_farm.id, actor_user_id=other_user.id,
        asset_type_code="germination_trolley", code=f"GT-OTHER-{suffix}", name="Other Trolley", commissioned_date=None,
    )
    with pytest.raises(AssetNotFoundError):
        germination_service.place_tray_in_slot(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            tray_id=s["carriers"][0].id, trolley_id=other_trolley.id, slot_id=uuid.uuid4(),
            effective_time=_now(), reason=None,
        )


@pytest.mark.integration
def test_tray_movement_leaves_batch_carrier_assignment_unchanged(db_session, active_context_with_farm) -> None:
    """Section 18 (mandatory regression proof)."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    assignment_before = db_session.execute(
        select(BatchCarrierAssignment).where(
            BatchCarrierAssignment.carrier_id == s["carriers"][0].id, BatchCarrierAssignment.tenant_id == tenant.id,
        )
    ).scalar_one()
    _place_trolley(db_session, tenant, user, farm, s)
    _place_tray(db_session, tenant, user, farm, s)
    assignment_after = db_session.execute(
        select(BatchCarrierAssignment).where(
            BatchCarrierAssignment.carrier_id == s["carriers"][0].id, BatchCarrierAssignment.tenant_id == tenant.id,
        )
    ).scalar_one()
    assert assignment_after.id == assignment_before.id
    assert assignment_after.batch_id == assignment_before.batch_id
    assert assignment_after.released_effective_time is None
    assert assignment_after.opening_sowing_event_id == assignment_before.opening_sowing_event_id
    assert db_session.execute(
        select(func.count()).select_from(BatchCarrierAssignment).where(
            BatchCarrierAssignment.carrier_id == s["carriers"][0].id
        )
    ).scalar_one() == 1


# =====================================================================
# Trolley movement with resident Trays (section 14)
# =====================================================================


@pytest.mark.integration
def test_moving_trolley_preserves_tray_slot_occupancy_and_updates_resolved_location(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    other_chamber = location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="germination_chamber", code=f"GC2-{uuid.uuid4().hex[:8]}", name="Second Chamber",
        parent_location_id=s["greenhouse_id"], greenhouse_classification=None, occupiable=True,
    )
    _place_trolley(db_session, tenant, user, farm, s)
    _place_tray(db_session, tenant, user, farm, s)

    from app.services import movement_service

    tray_occupancy_before = movement_service.get_occupancy(
        db_session, tenant_id=tenant.id, farm_id=farm.id, occupant_kind="carrier", occupant_id=s["carriers"][0].id
    )

    _place_trolley(db_session, tenant, user, farm, s, chamber_id=other_chamber.id)

    tray_occupancy_after = movement_service.get_occupancy(
        db_session, tenant_id=tenant.id, farm_id=farm.id, occupant_kind="carrier", occupant_id=s["carriers"][0].id
    )
    assert tray_occupancy_after.id == tray_occupancy_before.id
    assert tray_occupancy_after.target_asset_position_id == tray_occupancy_before.target_asset_position_id

    resolved = movement_service.get_resolved_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, occupant_kind="carrier", occupant_id=s["carriers"][0].id
    )
    assert resolved["fixed_location_path"][-1]["code"] == other_chamber.code
    # Only ONE Movement record for the tray -- the Trolley's own move does
    # not create a recursive Movement/Occupancy record for the tray.
    tray_movement_count = db_session.execute(
        text(
            "SELECT count(*) FROM movements WHERE occupant_carrier_id = :cid"
        ),
        {"cid": s["carriers"][0].id},
    ).scalar_one()
    assert tray_movement_count == 1


# =====================================================================
# Reads (sections 19-23)
# =====================================================================


@pytest.mark.integration
def test_list_germination_trays_states(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, trolley_count=1, tray_count=3)
    _place_trolley(db_session, tenant, user, farm, s)
    _place_tray(db_session, tenant, user, farm, s, tray_index=0)
    # Tray 1: placed on an asset_position that does NOT resolve through a
    # Trolley-in-Chamber (a bare, ungrounded asset_position) -- "elsewhere".
    other_asset = asset_service.register_asset(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        asset_type_code="germination_trolley", code=f"GT-ELSEWHERE-{uuid.uuid4().hex[:8]}", name="Ungrounded Trolley",
        commissioned_date=None,
    )
    other_positions = asset_service.generate_positions(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, asset_id=other_asset.id,
        shelf_count=1, slots_per_shelf=1, shelf_prefix="ESH-", slot_prefix="ESL-", shelf_pad_width=2, slot_pad_width=2,
    )
    other_slot = next(p for p in other_positions if p.position_kind == "slot")
    from app.services import movement_service

    movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        effective_time=_now(), occupant_kind="carrier", occupant_id=s["carriers"][1].id,
        destination_kind="asset_position", destination_id=other_slot.id, reason=None,
    )
    # Tray 2: never placed -- "awaiting_placement".

    trays = germination_service.list_germination_trays(db_session, tenant_id=tenant.id, farm_id=farm.id)
    by_carrier = {t.tray.id: t for t in trays}
    assert by_carrier[s["carriers"][0].id].state == "in_germination"
    assert by_carrier[s["carriers"][0].id].placement is not None
    assert by_carrier[s["carriers"][0].id].placement.chamber.id == s["chamber_id"]
    assert by_carrier[s["carriers"][1].id].state == "elsewhere"
    assert by_carrier[s["carriers"][1].id].placement is None
    assert by_carrier[s["carriers"][2].id].state == "awaiting_placement"
    assert by_carrier[s["carriers"][2].id].placement is None
    assert by_carrier[s["carriers"][0].id].seeds_sown == 200
    assert by_carrier[s["carriers"][0].id].batch_id == s["batch_id"]


@pytest.mark.integration
def test_list_available_chambers_reports_remaining_capacity(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, chamber_capacity=2, trolley_count=1, tray_count=1)
    before = {c.id: c for c in germination_service.list_available_chambers(db_session, tenant_id=tenant.id, farm_id=farm.id)}
    assert before[s["chamber_id"]].active_trolley_count == 0
    assert before[s["chamber_id"]].remaining_capacity == 2

    _place_trolley(db_session, tenant, user, farm, s)

    after = {c.id: c for c in germination_service.list_available_chambers(db_session, tenant_id=tenant.id, farm_id=farm.id)}
    assert after[s["chamber_id"]].active_trolley_count == 1
    assert after[s["chamber_id"]].remaining_capacity == 1


@pytest.mark.integration
def test_list_available_trolleys_only_those_in_a_chamber(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, trolley_count=2, tray_count=1)
    assert germination_service.list_available_trolleys(db_session, tenant_id=tenant.id, farm_id=farm.id) == []

    _place_trolley(db_session, tenant, user, farm, s, trolley_index=0)
    available = germination_service.list_available_trolleys(db_session, tenant_id=tenant.id, farm_id=farm.id)
    assert len(available) == 1
    assert available[0].id == s["trolleys"][0].id
    assert available[0].total_slot_count == 4
    assert available[0].occupied_slot_count == 0
    assert available[0].available_slot_count == 4

    _place_tray(db_session, tenant, user, farm, s, tray_index=0, trolley_index=0)
    available_after = germination_service.list_available_trolleys(db_session, tenant_id=tenant.id, farm_id=farm.id)
    assert available_after[0].occupied_slot_count == 1
    assert available_after[0].available_slot_count == 3


@pytest.mark.integration
def test_list_trolley_slots_reports_occupied_flag(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    _place_trolley(db_session, tenant, user, farm, s)
    _place_tray(db_session, tenant, user, farm, s)

    slots = germination_service.list_trolley_slots(db_session, tenant_id=tenant.id, farm_id=farm.id, trolley_id=s["trolleys"][0].id)
    assert len(slots) == 4
    occupied = [sl for sl in slots if sl.occupied]
    assert len(occupied) == 1
    assert all(sl.shelf_code for sl in slots)


# =====================================================================
# Idempotency (section 28)
# =====================================================================


@pytest.mark.integration
def test_tray_placement_exact_replay_resolved_before_mutable_validation(db_session, active_context_with_farm) -> None:
    """Retrying the SAME successful command after the slot it filled is now
    occupied (by itself) must replay the original success, never fail with
    TargetOccupiedError."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    _place_trolley(db_session, tenant, user, farm, s)
    ccid = uuid.uuid4()
    slot_id = _slot_ids(db_session, s["trolleys"][0].id)[0]
    effective_time = _now()
    first = germination_service.place_tray_in_slot(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=ccid,
        tray_id=s["carriers"][0].id, trolley_id=s["trolleys"][0].id, slot_id=slot_id,
        effective_time=effective_time, reason=None,
    )
    replay = germination_service.place_tray_in_slot(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=ccid,
        tray_id=s["carriers"][0].id, trolley_id=s["trolleys"][0].id, slot_id=slot_id,
        effective_time=effective_time, reason=None,
    )
    assert replay.id == first.id


# =====================================================================
# Direct-DB compatibility invariants (section 38)
# =====================================================================


@pytest.mark.integration
def test_direct_db_germination_trolley_to_chamber_accepted(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, trolley_count=1, tray_count=1)
    from app.services import movement_service

    movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        effective_time=_now(), occupant_kind="asset", occupant_id=s["trolleys"][0].id,
        destination_kind="location", destination_id=s["chamber_id"], reason=None,
    )
    active = db_session.execute(
        select(func.count()).select_from(Occupancy).where(
            Occupancy.occupant_asset_id == s["trolleys"][0].id, Occupancy.end_time.is_(None)
        )
    ).scalar_one()
    assert active == 1


@pytest.mark.integration
def test_seed_tray_to_germination_chamber_rejected(db_session, active_context_with_farm) -> None:
    """Section 31/38: direct Tray-to-Chamber placement remains out of
    scope/unsupported -- the compatibility rule was never added."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, trolley_count=0, tray_count=1)
    from app.services import movement_service

    with pytest.raises(IncompatibleOccupantTargetError):
        movement_service.execute_movement(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            effective_time=_now(), occupant_kind="carrier", occupant_id=s["carriers"][0].id,
            destination_kind="location", destination_id=s["chamber_id"], reason=None,
        )


@pytest.mark.integration
def test_compatibility_catalog_no_longer_lists_trolley_to_chamber_position(db_session) -> None:
    """Section 38: `germination_trolley -> chamber_position` must no longer
    exist in the global compatibility catalog at all (not just be
    unreachable via the hierarchy) -- `germination_trolley ->
    germination_chamber` must be the sole rule for this occupant type."""
    rows = db_session.execute(
        text(
            "SELECT lt.code AS target_code FROM occupancy_compatibility_rules r "
            "JOIN asset_types at ON at.id = r.occupant_asset_type_id "
            "LEFT JOIN location_types lt ON lt.id = r.target_location_type_id "
            "WHERE at.code = 'germination_trolley'"
        )
    ).scalars().all()
    assert list(rows) == ["germination_chamber"]


@pytest.mark.integration
def test_seed_tray_to_trolley_slot_remains_accepted(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    _place_trolley(db_session, tenant, user, farm, s)
    movement = _place_tray(db_session, tenant, user, farm, s)
    assert movement.destination_asset_position_id is not None


# =====================================================================
# Concurrency (section 29) -- deterministic, threading.Barrier, no sleeps
# =====================================================================


def _build_committed_concurrency_scenario(test_engine, *, chamber_capacity):
    from sqlalchemy.orm import Session

    conn = test_engine.connect()
    session = Session(bind=conn)
    tenant_svc_result = None
    try:
        from app.services import (
            farm_service, membership_service, tenant_service, user_service,
        )

        suffix = uuid.uuid4().hex[:10]
        tenant = tenant_service.create_tenant(session, code=f"germ-race-{suffix}", name="Germ Race Tenant")
        user = user_service.create_user(
            session, oidc_issuer="germ-race", oidc_subject=suffix, email=f"germ-race-{suffix}@example.com",
            display_name="Germ Race User",
        )
        membership_service.add_membership(session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None)
        farm = farm_service.create_farm(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Germ Race Farm",
            country_code="AE", city_region=None, timezone="Asia/Dubai",
        )
        s = _build_scenario(session, tenant, user, farm, suffix=suffix, chamber_capacity=chamber_capacity, trolley_count=3, tray_count=2)
        session.commit()
        tenant_svc_result = {
            "tenant_id": tenant.id, "farm_id": farm.id, "user_id": user.id, "chamber_id": s["chamber_id"],
            "trolley_ids": [t.id for t in s["trolleys"]], "tray_ids": [c.id for c in s["carriers"]],
        }
    finally:
        session.close()
        conn.close()
    return tenant_svc_result


def _cleanup_concurrency_scenario(test_engine, tenant_id: uuid.UUID) -> None:
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET session_replication_role = replica"))
        for table in (
            "occupancies", "movements", "sowing_event_lines", "sowing_events", "batch_carrier_assignments",
            "batch_stage_runs", "batch_stage_transitions", "crop_batches", "carriers",
            "asset_positions", "assets", "seed_lots", "locations", "workflow_transitions", "workflow_stages",
            "workflow_versions", "workflows", "production_systems", "varieties", "crops", "audit_events",
            "farms", "tenant_memberships", "tenants",
        ):
            if table == "asset_positions":
                conn.execute(
                    text("DELETE FROM asset_positions WHERE asset_id IN (SELECT id FROM assets WHERE tenant_id = :tid)"),
                    {"tid": tenant_id},
                )
            elif table in ("tenants",):
                conn.execute(text(f"DELETE FROM {table} WHERE id = :tid"), {"tid": tenant_id})
            else:
                conn.execute(text(f"DELETE FROM {table} WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("SET session_replication_role = DEFAULT"))
        trans.commit()
    finally:
        conn.close()


def _run_pair(test_engine, worker, *, kwargs_a, kwargs_b):
    import threading

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    t_a = threading.Thread(target=worker, args=(test_engine, results, "a", barrier), kwargs=kwargs_a)
    t_b = threading.Thread(target=worker, args=(test_engine, results, "b", barrier), kwargs=kwargs_b)
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)
    assert not t_a.is_alive() and not t_b.is_alive()
    return results


def _trolley_worker(test_engine, results, name, barrier, *, tenant_id, farm_id, user_id, trolley_id, chamber_id):
    from sqlalchemy.orm import Session

    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        barrier.wait(timeout=10)
        movement = germination_service.place_trolley_in_chamber(
            session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=user_id, client_command_id=uuid.uuid4(),
            trolley_id=trolley_id, chamber_id=chamber_id, effective_time=_now(), reason=None,
        )
        results[name] = ("ok", movement.id)
    except TargetOccupiedError as exc:
        results[name] = ("conflict", str(exc))
    except Exception as exc:  # pragma: no cover - surfaced via assertion
        results[name] = ("error", repr(exc))
    finally:
        session.close()
        conn.close()


def _tray_worker(test_engine, results, name, barrier, *, tenant_id, farm_id, user_id, tray_id, trolley_id, slot_id):
    from sqlalchemy.orm import Session

    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        barrier.wait(timeout=10)
        movement = germination_service.place_tray_in_slot(
            session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=user_id, client_command_id=uuid.uuid4(),
            tray_id=tray_id, trolley_id=trolley_id, slot_id=slot_id, effective_time=_now(), reason=None,
        )
        results[name] = ("ok", movement.id)
    except TargetOccupiedError as exc:
        results[name] = ("conflict", str(exc))
    except Exception as exc:  # pragma: no cover - surfaced via assertion
        results[name] = ("error", repr(exc))
    finally:
        session.close()
        conn.close()


@pytest.mark.integration
def test_concurrent_case_a_two_trolleys_last_chamber_capacity(test_engine) -> None:
    scenario = _build_committed_concurrency_scenario(test_engine, chamber_capacity=1)
    try:
        results = _run_pair(
            test_engine, _trolley_worker,
            kwargs_a=dict(tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], user_id=scenario["user_id"],
                          trolley_id=scenario["trolley_ids"][0], chamber_id=scenario["chamber_id"]),
            kwargs_b=dict(tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], user_id=scenario["user_id"],
                          trolley_id=scenario["trolley_ids"][1], chamber_id=scenario["chamber_id"]),
        )
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("conflict") == 1, results
    finally:
        _cleanup_concurrency_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_concurrent_case_b_same_trolley_two_chambers(test_engine) -> None:
    scenario = _build_committed_concurrency_scenario(test_engine, chamber_capacity=None)
    try:
        conn = test_engine.connect()
        from sqlalchemy.orm import Session

        session = Session(bind=conn)
        other_chamber = location_service.create_location(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            location_type_code="germination_chamber", code=f"GC2-{uuid.uuid4().hex[:8]}", name="Second Chamber",
            parent_location_id=location_service.get_location(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], location_id=scenario["chamber_id"]
            ).parent_location_id,
            greenhouse_classification=None, occupiable=True,
        )
        session.commit()
        other_chamber_id = other_chamber.id
        session.close()
        conn.close()

        results = _run_pair(
            test_engine, _trolley_worker,
            kwargs_a=dict(tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], user_id=scenario["user_id"],
                          trolley_id=scenario["trolley_ids"][0], chamber_id=scenario["chamber_id"]),
            kwargs_b=dict(tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], user_id=scenario["user_id"],
                          trolley_id=scenario["trolley_ids"][0], chamber_id=other_chamber_id),
        )
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 2, results  # sequential (source lock serializes); both may succeed as a move

        conn2 = test_engine.connect()
        active_count = conn2.execute(
            text("SELECT COUNT(*) FROM occupancies WHERE occupant_asset_id = :aid AND end_time IS NULL"),
            {"aid": scenario["trolley_ids"][0]},
        ).scalar_one()
        conn2.close()
        assert active_count == 1, "exactly one current Occupancy for the Trolley, regardless of race outcome"
    finally:
        _cleanup_concurrency_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_concurrent_case_c_two_trays_last_exclusive_slot(test_engine) -> None:
    scenario = _build_committed_concurrency_scenario(test_engine, chamber_capacity=None)
    conn = test_engine.connect()
    from sqlalchemy.orm import Session

    session = Session(bind=conn)
    try:
        germination_service.place_trolley_in_chamber(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), trolley_id=scenario["trolley_ids"][0], chamber_id=scenario["chamber_id"],
            effective_time=_now(), reason=None,
        )
        session.commit()
        slot_id = _slot_ids(session, scenario["trolley_ids"][0])[0]
    finally:
        session.close()
        conn.close()

    try:
        results = _run_pair(
            test_engine, _tray_worker,
            kwargs_a=dict(tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], user_id=scenario["user_id"],
                          tray_id=scenario["tray_ids"][0], trolley_id=scenario["trolley_ids"][0], slot_id=slot_id),
            kwargs_b=dict(tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], user_id=scenario["user_id"],
                          tray_id=scenario["tray_ids"][1], trolley_id=scenario["trolley_ids"][0], slot_id=slot_id),
        )
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("conflict") == 1, results
    finally:
        _cleanup_concurrency_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_concurrent_case_d_same_tray_two_slots(test_engine) -> None:
    scenario = _build_committed_concurrency_scenario(test_engine, chamber_capacity=None)
    conn = test_engine.connect()
    from sqlalchemy.orm import Session

    session = Session(bind=conn)
    try:
        germination_service.place_trolley_in_chamber(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), trolley_id=scenario["trolley_ids"][0], chamber_id=scenario["chamber_id"],
            effective_time=_now(), reason=None,
        )
        session.commit()
        slots = _slot_ids(session, scenario["trolley_ids"][0])
    finally:
        session.close()
        conn.close()

    try:
        results = _run_pair(
            test_engine, _tray_worker,
            kwargs_a=dict(tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], user_id=scenario["user_id"],
                          tray_id=scenario["tray_ids"][0], trolley_id=scenario["trolley_ids"][0], slot_id=slots[0]),
            kwargs_b=dict(tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], user_id=scenario["user_id"],
                          tray_id=scenario["tray_ids"][0], trolley_id=scenario["trolley_ids"][0], slot_id=slots[1]),
        )
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 2, results  # both are legal sequential moves of the same tray

        conn2 = test_engine.connect()
        active_count = conn2.execute(
            text("SELECT COUNT(*) FROM occupancies WHERE occupant_carrier_id = :cid AND end_time IS NULL"),
            {"cid": scenario["tray_ids"][0]},
        ).scalar_one()
        conn2.close()
        assert active_count == 1, "exactly one current Occupancy for the Tray, regardless of race outcome"
    finally:
        _cleanup_concurrency_scenario(test_engine, scenario["tenant_id"])


# =====================================================================
# Authorization (section 34)
# =====================================================================


@pytest.mark.integration
def test_place_trolley_requires_movement_manage(db_session) -> None:
    from app.core.auth import TenantContext
    from app.core.permissions import Permission, has_permission

    for role in ("operator", "production_supervisor", "tenant_admin"):
        ctx = TenantContext(tenant_id=uuid.uuid4(), user_id=uuid.uuid4(), role_code=role)
        assert has_permission(ctx, Permission.MOVEMENT_MANAGE), role

    storekeeper_ctx = TenantContext(tenant_id=uuid.uuid4(), user_id=uuid.uuid4(), role_code="storekeeper")
    assert not has_permission(storekeeper_ctx, Permission.MOVEMENT_MANAGE)


@pytest.mark.integration
def test_place_trolley_http_requires_movement_manage_storekeeper_denied(client, db_session) -> None:
    from app.services import farm_service, membership_service, tenant_service, user_service

    suffix = uuid.uuid4().hex[:8]
    tenant = tenant_service.create_tenant(db_session, code=f"germ-authz-{suffix}", name="Germ Authz Tenant")
    user = user_service.create_user(
        db_session, oidc_issuer="germ-authz", oidc_subject=suffix, email=f"{suffix}@example.com", display_name="Germ Authz",
    )
    membership_service.add_membership(db_session, tenant_id=tenant.id, user_id=user.id, role_code="storekeeper", actor_user_id=None)
    farm = farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    headers = {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(user.id)}
    db_session.commit()

    resp = client.post(
        f"/farms/{farm.id}/germination/trolley-placements", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "trolley_id": str(uuid.uuid4()), "chamber_id": str(uuid.uuid4()),
            "effective_time": _now().isoformat(),
        },
    )
    assert resp.status_code == 403


@pytest.mark.integration
def test_available_chambers_http_requires_location_read(client, db_session) -> None:
    from app.services import farm_service, membership_service, tenant_service, user_service

    suffix = uuid.uuid4().hex[:8]
    tenant = tenant_service.create_tenant(db_session, code=f"germ-chread-{suffix}", name="Germ Chamber Read Tenant")
    user = user_service.create_user(
        db_session, oidc_issuer="germ-chread", oidc_subject=suffix, email=f"{suffix}@example.com", display_name="Chamber Read",
    )
    membership_service.add_membership(db_session, tenant_id=tenant.id, user_id=user.id, role_code="operator", actor_user_id=None)
    farm = farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    headers = {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(user.id)}
    db_session.commit()

    resp = client.get(f"/farms/{farm.id}/germination/chambers/available", headers=headers)
    assert resp.status_code == 200

    no_membership_headers = {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(uuid.uuid4())}
    resp2 = client.get(f"/farms/{farm.id}/germination/chambers/available", headers=no_membership_headers)
    assert resp2.status_code in (401, 403)


# =====================================================================
# Tenant/farm isolation (section 35)
# =====================================================================


@pytest.mark.integration
def test_cross_tenant_chamber_read_is_404(client, db_session) -> None:
    from app.services import farm_service, membership_service, tenant_service, user_service

    suffix = uuid.uuid4().hex[:8]
    tenant_a = tenant_service.create_tenant(db_session, code=f"iso-a-{suffix}", name="A")
    user_a = user_service.create_user(
        db_session, oidc_issuer="iso-a", oidc_subject=suffix, email=f"a-{suffix}@example.com", display_name="A",
    )
    membership_service.add_membership(db_session, tenant_id=tenant_a.id, user_id=user_a.id, role_code="tenant_admin", actor_user_id=None)
    farm_a = farm_service.create_farm(
        db_session, tenant_id=tenant_a.id, actor_user_id=user_a.id, code=f"farm-a-{suffix}", name="Farm A",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    s = _build_scenario(db_session, tenant_a, user_a, farm_a, suffix=suffix, tray_count=1)

    tenant_b = tenant_service.create_tenant(db_session, code=f"iso-b-{suffix}", name="B")
    user_b = user_service.create_user(
        db_session, oidc_issuer="iso-b", oidc_subject=suffix, email=f"b-{suffix}@example.com", display_name="B",
    )
    membership_service.add_membership(db_session, tenant_id=tenant_b.id, user_id=user_b.id, role_code="tenant_admin", actor_user_id=None)
    headers_b = {"X-Dev-Tenant-Id": str(tenant_b.id), "X-Dev-User-Id": str(user_b.id)}
    db_session.commit()

    resp = client.post(
        f"/farms/{farm_a.id}/germination/trolley-placements", headers=headers_b,
        json={
            "client_command_id": str(uuid.uuid4()), "trolley_id": str(s["trolleys"][0].id),
            "chamber_id": str(s["chamber_id"]), "effective_time": _now().isoformat(),
        },
    )
    assert resp.status_code == 404
