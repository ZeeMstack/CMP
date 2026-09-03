"""NURSERY-OPS-002A / PILOT-UX-001B: Germination Placement (physical
placement only, no biological outcome). Frozen authoritative model: a
Germination Trolley Asset occupies a Germination Chamber Location directly
(no chamber_position); a Seed Tray Carrier occupies a Trolley Level directly
(new-model `direct_level`, `mode="direct"`) or one of that Level's child
Slot AssetPositions (legacy-compatible `legacy_level`, `mode="legacy"`).
Reuses `movement_service.execute_movement` verbatim via
`germination_service`'s thin orchestration layer -- this file tests only
the Germination-specific validation/reads, not generic Movement/Occupancy
mechanics already proven in test_movement*.py/test_occupancy_capacity*.py."""
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
    GerminationLevelNotConfiguredError,
    GerminationPlacementMustUseGerminationOperationError,
    GerminationTraySlotInvalidError,
    GerminationTrolleyInvalidError,
    IncompatibleOccupantTargetError,
    LocationNotFoundError,
    TargetNotOccupiableError,
    TargetOccupiedError,
    TrayNotSownError,
    TrolleyNotInGerminationError,
)
from tests.conftest import ensure_seed_tray_specification


def _now():
    return datetime.now(timezone.utc)


def _build_scenario(
    db_session, tenant, user, farm, *, suffix=None, chamber_capacity=None, trolley_count=1, tray_count=2,
    trolley_mode="direct", level_count=2, trays_per_level=2,
):
    """A complete Germination-ready Nursery: Greenhouse + Seeding Station +
    Germination Chamber (via Farm Setup), `trolley_count` Germination
    Trolleys, one Sown Crop Batch with `tray_count` Seed Trays carrying
    active, sowing-origin BatchCarrierAssignments.

    `trolley_mode="direct"` (the default, matching new Farm Setup) builds
    each Trolley through the real `farm_setup_service` Nursery Trolley
    path -- `level_count` Levels, each with `capacity=trays_per_level`, zero
    child Slots. `trolley_mode="legacy"` builds each Trolley through the
    unchanged GENERIC `asset_service.register_asset`/`generate_positions`
    path instead -- `level_count` shelves x `trays_per_level` child slots
    each -- reproducing exactly what a Trolley created before PILOT-UX-001B
    looks like."""
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

    trolley_setup_configs = []
    if trolley_mode == "direct":
        for t in range(trolley_count):
            trolley_setup_configs.append(
                TrolleySetupConfig(
                    code=f"GT-{suffix}-{t}",
                    levels=TrolleyLevelGeneratorConfig(
                        level_count=level_count, trays_per_level=trays_per_level, level_pad_width=2,
                    ),
                )
            )

    setup = farm_setup_service.create_greenhouse_setup(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        payload=GreenhouseSetupCreate(
            code=f"NUR-{suffix}", name="Nursery", classification="nursery", client_command_id=uuid.uuid4(),
            nursery=NurserySetupConfig(
                seeding_station=NurserySectionConfig(code=f"SEED-{suffix}"),
                germination_chamber=GerminationChamberSetupConfig(code=f"GC-{suffix}", trolley_capacity=chamber_capacity),
                trolleys=trolley_setup_configs,
            ),
        ),
    )
    structure = farm_setup_service.get_greenhouse_structure(
        db_session.connection(), tenant_id=tenant.id, farm_id=farm.id, greenhouse_id=setup.greenhouse_id,
    )
    seeding_station_id = structure.nursery_seeding_stations[0].id
    chamber_id = structure.nursery_germination_chamber.id

    if trolley_mode == "direct":
        # GreenhouseSetupCreate normalizes every code (strip + upper) --
        # match that here so the lookup below finds what was actually
        # persisted, regardless of `suffix`'s own casing.
        codes = [f"GT-{suffix}-{t}".upper() for t in range(trolley_count)]
        by_code = {
            a.code: a
            for a in asset_service.list_assets(
                db_session, tenant_id=tenant.id, farm_id=farm.id, asset_type_code="germination_trolley"
            )
        }
        trolleys = [by_code[c] for c in codes]
    else:
        trolleys = []
        for t in range(trolley_count):
            trolley = asset_service.register_asset(
                db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
                asset_type_code="germination_trolley", code=f"GT-{suffix}-{t}", name=f"Trolley {t}", commissioned_date=None,
            )
            asset_service.generate_positions(
                db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, asset_id=trolley.id,
                shelf_count=level_count, slots_per_shelf=trays_per_level, shelf_prefix=f"SH-{suffix}-{t}-", slot_prefix="SL-",
                shelf_pad_width=2, slot_pad_width=2,
            )
            trolleys.append(trolley)

    seed_tray_spec = ensure_seed_tray_specification(db_session, tenant_id=tenant.id, actor_user_id=user.id)
    carriers = [
        carrier_service.register_carrier(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            specification_id=seed_tray_spec.id, code=f"ST-{suffix}-{n:04d}", issued_date=None,
        )
        for n in range(1, tray_count + 1)
    ]

    event = nursery_service.sow_new_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        seed_lot_id=seed_lot.id, seeding_station_id=seeding_station_id, seeding_machine_id=None,
        effective_time=_now(), note=None,
        trays=[{"carrier_id": c.id, "sown_site_count": 200, "seeds_sown": 200} for c in carriers],
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


def _direct_level_ids(db_session, trolley_id):
    """Every `direct_level` (shelf, zero children, capacity configured) on
    the Trolley, ordered by code."""
    rows = db_session.execute(
        text(
            "SELECT p.id FROM asset_positions p "
            "WHERE p.asset_id = :aid AND p.position_kind = 'shelf' AND p.capacity IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM asset_positions c WHERE c.parent_position_id = p.id) "
            "ORDER BY p.code"
        ),
        {"aid": trolley_id},
    ).scalars().all()
    return list(rows)


def _legacy_level_ids(db_session, trolley_id):
    """Every `legacy_level` (shelf with >=1 child slot) on the Trolley."""
    rows = db_session.execute(
        text(
            "SELECT DISTINCT parent_position_id FROM asset_positions "
            "WHERE asset_id = :aid AND position_kind = 'slot' ORDER BY parent_position_id"
        ),
        {"aid": trolley_id},
    ).scalars().all()
    return list(rows)


def _legacy_slot_ids(db_session, trolley_id):
    rows = db_session.execute(
        text("SELECT id FROM asset_positions WHERE asset_id = :aid AND position_kind = 'slot' ORDER BY code"),
        {"aid": trolley_id},
    ).scalars().all()
    return list(rows)


def _place_tray(db_session, tenant, user, farm, s, *, tray_index=0, trolley_index=0, asset_position_id=None, client_command_id=None):
    asset_position_id = asset_position_id or _direct_level_ids(db_session, s["trolleys"][trolley_index].id)[0]
    return germination_service.place_tray(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=client_command_id or uuid.uuid4(),
        tray_id=s["carriers"][tray_index].id, trolley_id=s["trolleys"][trolley_index].id,
        asset_position_id=asset_position_id, effective_time=_now(), reason=None,
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
# Direct-Level placement (PILOT-UX-001B sections 15-16, B)
# =====================================================================


@pytest.mark.integration
def test_tray_placement_into_direct_level(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    _place_trolley(db_session, tenant, user, farm, s)
    movement = _place_tray(db_session, tenant, user, farm, s)
    assert movement.destination_asset_position_id is not None
    assert movement.source_asset_position_id is None


@pytest.mark.integration
def test_direct_level_capacity_accepts_exactly_capacity_and_rejects_next(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, level_count=1, trays_per_level=4, tray_count=5)
    _place_trolley(db_session, tenant, user, farm, s)
    level_id = _direct_level_ids(db_session, s["trolleys"][0].id)[0]
    for i in range(4):
        _place_tray(db_session, tenant, user, farm, s, tray_index=i, asset_position_id=level_id)
    with pytest.raises(TargetOccupiedError):
        _place_tray(db_session, tenant, user, farm, s, tray_index=4, asset_position_id=level_id)


@pytest.mark.integration
def test_tray_placement_requires_active_batch_carrier_assignment(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    _place_trolley(db_session, tenant, user, farm, s)
    unsown_tray = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        specification_id=ensure_seed_tray_specification(db_session, tenant_id=tenant.id, actor_user_id=user.id).id,
        code=f"ST-UNSOWN-{uuid.uuid4().hex[:8]}", issued_date=None,
    )
    level_id = _direct_level_ids(db_session, s["trolleys"][0].id)[0]
    with pytest.raises(TrayNotSownError):
        germination_service.place_tray(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            tray_id=unsown_tray.id, trolley_id=s["trolleys"][0].id, asset_position_id=level_id, effective_time=_now(), reason=None,
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
    level_id = _direct_level_ids(db_session, s["trolleys"][0].id)[0]
    with pytest.raises(GerminationTraySlotInvalidError):
        germination_service.place_tray(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            tray_id=grow_bag.id, trolley_id=s["trolleys"][0].id, asset_position_id=level_id, effective_time=_now(), reason=None,
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
def test_tray_placement_level_not_belonging_to_trolley_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, trolley_count=2, tray_count=1)
    _place_trolley(db_session, tenant, user, farm, s, trolley_index=0)
    other_trolley_level = _direct_level_ids(db_session, s["trolleys"][1].id)[0]
    with pytest.raises(AssetPositionNotFoundError):
        germination_service.place_tray(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            tray_id=s["carriers"][0].id, trolley_id=s["trolleys"][0].id, asset_position_id=other_trolley_level,
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
        germination_service.place_tray(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            tray_id=s["carriers"][0].id, trolley_id=other_trolley.id, asset_position_id=uuid.uuid4(),
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
# Legacy compatibility (PILOT-UX-001B sections 2, C)
# =====================================================================


@pytest.mark.integration
def test_legacy_slot_placement_still_works(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1, trolley_mode="legacy")
    _place_trolley(db_session, tenant, user, farm, s)
    slot_id = _legacy_slot_ids(db_session, s["trolleys"][0].id)[0]
    movement = _place_tray(db_session, tenant, user, farm, s, asset_position_id=slot_id)
    assert movement.destination_asset_position_id == slot_id


@pytest.mark.integration
def test_direct_placement_onto_legacy_level_parent_rejected(db_session, active_context_with_farm) -> None:
    """PILOT-UX-001B section 2: a `legacy_level` (has child Slots) is never
    itself a valid placement target -- the caller must target one of its
    child Slots instead."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1, trolley_mode="legacy")
    _place_trolley(db_session, tenant, user, farm, s)
    legacy_level_id = _legacy_level_ids(db_session, s["trolleys"][0].id)[0]
    with pytest.raises(GerminationTraySlotInvalidError):
        _place_tray(db_session, tenant, user, farm, s, asset_position_id=legacy_level_id)


@pytest.mark.integration
def test_legacy_slot_active_occupancy_resolves_correctly(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1, trolley_mode="legacy")
    _place_trolley(db_session, tenant, user, farm, s)
    slot_id = _legacy_slot_ids(db_session, s["trolleys"][0].id)[0]
    _place_tray(db_session, tenant, user, farm, s, asset_position_id=slot_id)

    from app.services import movement_service

    resolved = movement_service.get_resolved_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, occupant_kind="carrier", occupant_id=s["carriers"][0].id
    )
    assert resolved["fixed_location_path"][-1]["code"] == db_session.execute(
        text("SELECT code FROM locations WHERE id = :id"), {"id": s["chamber_id"]}
    ).scalar_one()
    assert len(resolved["position_path"]) == 2, "legacy path is [shelf, slot]"

    trays = germination_service.list_germination_trays(db_session, tenant_id=tenant.id, farm_id=farm.id)
    by_carrier = {t.tray.id: t for t in trays}
    placement = by_carrier[s["carriers"][0].id].placement
    assert placement.position.mode == "legacy"
    assert placement.position.id == slot_id


@pytest.mark.integration
def test_direct_level_active_occupancy_resolves_correctly(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    _place_trolley(db_session, tenant, user, farm, s)
    level_id = _direct_level_ids(db_session, s["trolleys"][0].id)[0]
    _place_tray(db_session, tenant, user, farm, s, asset_position_id=level_id)

    from app.services import movement_service

    resolved = movement_service.get_resolved_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, occupant_kind="carrier", occupant_id=s["carriers"][0].id
    )
    assert len(resolved["position_path"]) == 1, "direct-model path is [shelf] only"

    trays = germination_service.list_germination_trays(db_session, tenant_id=tenant.id, farm_id=farm.id)
    by_carrier = {t.tray.id: t for t in trays}
    placement = by_carrier[s["carriers"][0].id].placement
    assert placement.position.mode == "direct"
    assert placement.position.id == level_id
    assert placement.position.level_code == placement.position.code


# =====================================================================
# Invalid Level (PILOT-UX-001B sections 2, D)
# =====================================================================


def _make_invalid_level(db_session, tenant, farm, trolley_id) -> uuid.UUID:
    """Manufactures an `invalid_level` -- zero child Slots AND NULL
    capacity. No production code path creates this state (new Farm Setup
    always sets `capacity`; the generic legacy generator always creates
    child Slots) -- it can only arise from a partially-configured/legacy
    row, so this test constructs it directly, exactly like
    `test_asset_position.py`'s own direct-SQL DB-constraint tests do."""
    level_id = uuid.uuid4()
    db_session.execute(
        text(
            "INSERT INTO asset_positions (id, asset_id, parent_position_id, position_kind, code, name, capacity) "
            "VALUES (:id, :aid, NULL, 'shelf', :code, :name, NULL)"
        ),
        {"id": level_id, "aid": trolley_id, "code": f"INVALID-{uuid.uuid4().hex[:6]}", "name": "Unconfigured Level"},
    )
    db_session.flush()
    return level_id


@pytest.mark.integration
def test_invalid_level_rejects_placement_as_configuration_error(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    _place_trolley(db_session, tenant, user, farm, s)
    invalid_level_id = _make_invalid_level(db_session, tenant, farm, s["trolleys"][0].id)
    with pytest.raises(GerminationLevelNotConfiguredError):
        _place_tray(db_session, tenant, user, farm, s, asset_position_id=invalid_level_id)


@pytest.mark.integration
def test_invalid_level_not_advertised_as_available(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, level_count=1, trays_per_level=2, tray_count=1)
    _place_trolley(db_session, tenant, user, farm, s)
    invalid_level_id = _make_invalid_level(db_session, tenant, farm, s["trolleys"][0].id)

    levels = germination_service.list_trolley_levels(db_session, tenant_id=tenant.id, farm_id=farm.id, trolley_id=s["trolleys"][0].id)
    by_id = {lvl.id: lvl for lvl in levels}
    invalid = by_id[invalid_level_id]
    assert invalid.mode == "invalid"
    assert invalid.capacity is None
    assert invalid.available_capacity is None

    available = germination_service.list_available_trolleys(db_session, tenant_id=tenant.id, farm_id=farm.id)
    trolley_summary = next(t for t in available if t.id == s["trolleys"][0].id)
    # Only the real direct_level's capacity (2) counts -- the invalid_level contributes nothing.
    assert trolley_summary.total_capacity == 2


# =====================================================================
# Mixed Trolley (PILOT-UX-001B section E)
# =====================================================================


@pytest.mark.integration
def test_mixed_trolley_legacy_and_direct_levels_behave_independently(db_session, active_context_with_farm) -> None:
    """A single Trolley may carry both a legacy Level (from before this
    ticket) and a new direct_level (added afterward, e.g. via additive
    extension) -- each is classified and enforced purely from its own
    structure."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, level_count=1, trays_per_level=1, tray_count=2)
    trolley = s["trolleys"][0]

    # Add a legacy-shaped Level (2 child Slots) to the SAME Trolley, using
    # the unchanged generic generator -- exactly how an operator might
    # extend an existing Trolley through the generic Asset Position API.
    asset_service.generate_positions(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, asset_id=trolley.id,
        shelf_count=1, slots_per_shelf=2, shelf_prefix=f"LEGACY-{uuid.uuid4().hex[:6]}-", slot_prefix="SL-",
        shelf_pad_width=2, slot_pad_width=2,
    )

    _place_trolley(db_session, tenant, user, farm, s)

    direct_level_id = _direct_level_ids(db_session, trolley.id)[0]
    legacy_level_id = _legacy_level_ids(db_session, trolley.id)[0]
    legacy_slot_id = _legacy_slot_ids(db_session, trolley.id)[0]

    levels = germination_service.list_trolley_levels(db_session, tenant_id=tenant.id, farm_id=farm.id, trolley_id=trolley.id)
    by_id = {lvl.id: lvl for lvl in levels}
    assert by_id[direct_level_id].mode == "direct"
    assert by_id[legacy_level_id].mode == "legacy"

    # Direct Level accepts a Tray directly; legacy Level's own row is
    # rejected but its child Slot is accepted -- both on the SAME Trolley.
    _place_tray(db_session, tenant, user, farm, s, tray_index=0, asset_position_id=direct_level_id)
    with pytest.raises(GerminationTraySlotInvalidError):
        _place_tray(db_session, tenant, user, farm, s, tray_index=1, asset_position_id=legacy_level_id)
    _place_tray(db_session, tenant, user, farm, s, tray_index=1, asset_position_id=legacy_slot_id)


# =====================================================================
# Trolley movement with resident Trays (section 14)
# =====================================================================


@pytest.mark.integration
def test_moving_trolley_preserves_tray_occupancy_and_updates_resolved_location(db_session, active_context_with_farm) -> None:
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
    _asset_type, other_positions = asset_service._generate_levels_core(
        db_session, tenant_id=tenant.id, farm_id=farm.id, asset_id=other_asset.id,
        level_count=1, level_prefix="ELSEWHERE-L", level_pad_width=2, trays_per_level=1,
    )
    other_level = other_positions[0]
    from app.services import movement_service

    movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        effective_time=_now(), occupant_kind="carrier", occupant_id=s["carriers"][1].id,
        destination_kind="asset_position", destination_id=other_level.id, reason=None,
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
    assert available[0].total_capacity == 4
    assert available[0].occupied_count == 0
    assert available[0].available_capacity == 4

    _place_tray(db_session, tenant, user, farm, s, tray_index=0, trolley_index=0)
    available_after = germination_service.list_available_trolleys(db_session, tenant_id=tenant.id, farm_id=farm.id)
    assert available_after[0].occupied_count == 1
    assert available_after[0].available_capacity == 3


@pytest.mark.integration
def test_list_trolley_levels_reports_direct_mode_and_capacity(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    _place_trolley(db_session, tenant, user, farm, s)
    _place_tray(db_session, tenant, user, farm, s)

    levels = germination_service.list_trolley_levels(db_session, tenant_id=tenant.id, farm_id=farm.id, trolley_id=s["trolleys"][0].id)
    assert len(levels) == 2
    assert all(lvl.mode == "direct" for lvl in levels)
    assert all(lvl.capacity == 2 for lvl in levels)
    occupied = [lvl for lvl in levels if lvl.occupied_count > 0]
    assert len(occupied) == 1
    assert occupied[0].available_capacity == 1


@pytest.mark.integration
def test_list_trolley_levels_reports_legacy_mode_and_slots(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1, trolley_mode="legacy")
    _place_trolley(db_session, tenant, user, farm, s)
    slot_id = _legacy_slot_ids(db_session, s["trolleys"][0].id)[0]
    _place_tray(db_session, tenant, user, farm, s, asset_position_id=slot_id)

    levels = germination_service.list_trolley_levels(db_session, tenant_id=tenant.id, farm_id=farm.id, trolley_id=s["trolleys"][0].id)
    assert len(levels) == 2
    assert all(lvl.mode == "legacy" for lvl in levels)
    assert all(lvl.capacity is None for lvl in levels)
    occupied_level = next(lvl for lvl in levels if any(sl.id == slot_id for sl in lvl.slots))
    assert any(sl.occupied for sl in occupied_level.slots if sl.id == slot_id)
    assert occupied_level.occupied_count == 1
    assert occupied_level.available_capacity == 1


# =====================================================================
# Idempotency (section 28)
# =====================================================================


@pytest.mark.integration
def test_tray_placement_exact_replay_resolved_before_mutable_validation(db_session, active_context_with_farm) -> None:
    """Retrying the SAME successful command after the Level it filled is now
    occupied (by itself) must replay the original success, never fail with
    TargetOccupiedError."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    _place_trolley(db_session, tenant, user, farm, s)
    ccid = uuid.uuid4()
    level_id = _direct_level_ids(db_session, s["trolleys"][0].id)[0]
    effective_time = _now()
    first = germination_service.place_tray(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=ccid,
        tray_id=s["carriers"][0].id, trolley_id=s["trolleys"][0].id, asset_position_id=level_id,
        effective_time=effective_time, reason=None,
    )
    replay = germination_service.place_tray(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=ccid,
        tray_id=s["carriers"][0].id, trolley_id=s["trolleys"][0].id, asset_position_id=level_id,
        effective_time=effective_time, reason=None,
    )
    assert replay.id == first.id


# =====================================================================
# Direct-DB compatibility invariants (section 38 / PILOT-UX-001B section 4)
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
    """Direct Tray-to-Chamber placement remains out of scope/unsupported --
    the compatibility rule is `carrier:seed_tray -> position:shelf`
    (Level), never `carrier:seed_tray -> location:germination_chamber`."""
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
def test_compatibility_catalog_lists_seed_tray_to_both_shelf_and_slot(db_session) -> None:
    """PILOT-UX-001B migration effect: `carrier:seed_tray` is compatible
    with BOTH `position:shelf` (new-model direct Level) and
    `position:slot` (legacy) -- the pre-existing `slot` row is untouched,
    the new `shelf` row is additive."""
    rows = db_session.execute(
        text(
            "SELECT r.target_position_kind FROM occupancy_compatibility_rules r "
            "JOIN carrier_types ct ON ct.id = r.occupant_carrier_type_id "
            "WHERE ct.code = 'seed_tray' AND r.target_position_kind IS NOT NULL"
        )
    ).scalars().all()
    assert sorted(rows) == ["shelf", "slot"]


@pytest.mark.integration
def test_seed_tray_to_trolley_level_remains_accepted(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    _place_trolley(db_session, tenant, user, farm, s)
    movement = _place_tray(db_session, tenant, user, farm, s)
    assert movement.destination_asset_position_id is not None


# =====================================================================
# Generic movement bypass (PILOT-UX-001B section 5, F)
# =====================================================================


@pytest.mark.integration
def test_generic_movement_cannot_place_seed_tray_onto_direct_level(client, db_session, active_context_with_farm) -> None:
    tenant, user, headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    _place_trolley(db_session, tenant, user, farm, s)
    level_id = _direct_level_ids(db_session, s["trolleys"][0].id)[0]
    db_session.commit()

    resp = client.post(
        f"/farms/{farm.id}/movements", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()),
            "occupant": {"kind": "carrier", "id": str(s["carriers"][0].id)},
            "destination": {"kind": "asset_position", "id": str(level_id)},
            "effective_time": _now().isoformat(),
        },
    )
    assert resp.status_code == 422, resp.text

    active = db_session.execute(
        select(func.count()).select_from(Occupancy).where(
            Occupancy.occupant_carrier_id == s["carriers"][0].id, Occupancy.end_time.is_(None)
        )
    ).scalar_one()
    assert active == 0, "the generic endpoint must not have created any Occupancy"


@pytest.mark.integration
def test_generic_movement_cannot_place_seed_tray_onto_legacy_slot(client, db_session, active_context_with_farm) -> None:
    tenant, user, headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1, trolley_mode="legacy")
    _place_trolley(db_session, tenant, user, farm, s)
    slot_id = _legacy_slot_ids(db_session, s["trolleys"][0].id)[0]
    db_session.commit()

    resp = client.post(
        f"/farms/{farm.id}/movements", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()),
            "occupant": {"kind": "carrier", "id": str(s["carriers"][0].id)},
            "destination": {"kind": "asset_position", "id": str(slot_id)},
            "effective_time": _now().isoformat(),
        },
    )
    assert resp.status_code == 422, resp.text

    active = db_session.execute(
        select(func.count()).select_from(Occupancy).where(
            Occupancy.occupant_carrier_id == s["carriers"][0].id, Occupancy.end_time.is_(None)
        )
    ).scalar_one()
    assert active == 0, "the generic endpoint must not have created any Occupancy, even for a legacy Slot target"


@pytest.mark.integration
def test_generic_movement_still_allows_unrelated_carrier_asset_position_placement(client, db_session, active_context_with_farm) -> None:
    """The bypass guard must be narrow -- it only concerns a seed_tray
    Carrier targeting a germination_trolley-owned AssetPosition; any other
    Carrier/AssetPosition combination the generic compatibility catalog
    already allows (e.g. `grow_cube -> table_position`, section 44's own
    established pattern) must still work through the generic endpoint,
    completely unaffected by this Germination-specific guard."""
    tenant, user, headers, farm = active_context_with_farm
    trolley = asset_service.register_asset(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        asset_type_code="germination_trolley", code=f"GT-UNREL-{uuid.uuid4().hex[:8]}", name="Trolley", commissioned_date=None,
    )
    seed_tray_spec = ensure_seed_tray_specification(db_session, tenant_id=tenant.id, actor_user_id=user.id)
    seed_tray = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        specification_id=seed_tray_spec.id, code=f"ST-UNREL-{uuid.uuid4().hex[:8]}", issued_date=None,
    )
    # A seed_tray targeting a NON-germination_trolley AssetPosition -- no
    # such compatible position kind actually exists for seed_tray outside
    # shelf/slot, so instead prove the inverse: an asset_position that IS
    # NOT owned by a germination_trolley never trips the guard, by directly
    # exercising the guard function.
    from app.services import germination_service as gs

    other_asset = asset_service.register_asset(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        asset_type_code="germination_trolley", code=f"GT-UNREL2-{uuid.uuid4().hex[:8]}", name="Other", commissioned_date=None,
    )
    _asset_type, positions = asset_service._generate_levels_core(
        db_session, tenant_id=tenant.id, farm_id=farm.id, asset_id=other_asset.id,
        level_count=1, level_prefix="UNREL-L", level_pad_width=2, trays_per_level=1,
    )
    db_session.commit()
    # Sanity: the guard DOES fire for this combination (it IS a
    # germination_trolley position) -- proves the negative-path assertion
    # below (a non-seed_tray carrier) is meaningful, not vacuous.
    with pytest.raises(GerminationPlacementMustUseGerminationOperationError):
        gs.reject_generic_bypass_for_seed_tray_placement(
            db_session, occupant_kind="carrier", occupant_id=seed_tray.id,
            destination_kind="asset_position", destination_id=positions[0].id,
        )
    # A non-seed_tray carrier onto the SAME position never trips the guard.
    grow_bag = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        carrier_type_code="grow_bag", code=f"GB-UNREL-{uuid.uuid4().hex[:8]}", issued_date=None,
    )
    gs.reject_generic_bypass_for_seed_tray_placement(
        db_session, occupant_kind="carrier", occupant_id=grow_bag.id,
        destination_kind="asset_position", destination_id=positions[0].id,
    )  # must not raise


@pytest.mark.integration
def test_germination_operation_still_succeeds_after_bypass_rejected(db_session, active_context_with_farm) -> None:
    """The frozen rule closes the generic bypass without touching the
    domain operation itself -- `germination_service.place_tray` reaches
    `movement_service.execute_movement` directly and is unaffected."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    _place_trolley(db_session, tenant, user, farm, s)
    movement = _place_tray(db_session, tenant, user, farm, s)
    assert movement.destination_asset_position_id is not None


# =====================================================================
# Concurrency (section 29) -- deterministic, threading.Barrier, no sleeps
# =====================================================================


def _build_committed_concurrency_scenario(test_engine, *, chamber_capacity, trolley_mode="direct", level_count=3, trays_per_level=2):
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
        s = _build_scenario(
            session, tenant, user, farm, suffix=suffix, chamber_capacity=chamber_capacity, trolley_count=3, tray_count=2,
            trolley_mode=trolley_mode, level_count=level_count, trays_per_level=trays_per_level,
        )
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
            "batch_stage_runs", "batch_stage_transitions", "crop_batches", "carrier_specifications", "carriers",
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


def _tray_worker(test_engine, results, name, barrier, *, tenant_id, farm_id, user_id, tray_id, trolley_id, asset_position_id, effective_time=None):
    from sqlalchemy.orm import Session

    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        barrier.wait(timeout=10)
        movement = germination_service.place_tray(
            session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=user_id, client_command_id=uuid.uuid4(),
            tray_id=tray_id, trolley_id=trolley_id, asset_position_id=asset_position_id,
            effective_time=effective_time or _now(), reason=None,
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
def test_concurrent_case_c_two_trays_last_exclusive_direct_level_capacity(test_engine) -> None:
    """PILOT-UX-001B: two concurrent placements racing for the LAST
    remaining unit of a `direct_level`'s capacity -- built with
    `level_count=1, trays_per_level=1` so the Level's capacity is exactly
    1, reproducing the original exclusive-slot race under the new model."""
    scenario = _build_committed_concurrency_scenario(test_engine, chamber_capacity=None, level_count=1, trays_per_level=1)
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
        level_id = _direct_level_ids(session, scenario["trolley_ids"][0])[0]
    finally:
        session.close()
        conn.close()

    try:
        results = _run_pair(
            test_engine, _tray_worker,
            kwargs_a=dict(tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], user_id=scenario["user_id"],
                          tray_id=scenario["tray_ids"][0], trolley_id=scenario["trolley_ids"][0], asset_position_id=level_id),
            kwargs_b=dict(tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], user_id=scenario["user_id"],
                          tray_id=scenario["tray_ids"][1], trolley_id=scenario["trolley_ids"][0], asset_position_id=level_id),
        )
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("conflict") == 1, results
    finally:
        _cleanup_concurrency_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_concurrent_case_d_same_tray_two_direct_levels(test_engine) -> None:
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
        levels = _direct_level_ids(session, scenario["trolley_ids"][0])
    finally:
        session.close()
        conn.close()

    try:
        # A single shared `effective_time` for both workers -- whichever
        # thread's write actually commits first (decided by the occupant
        # row lock, not by which thread happened to call `_now()`
        # microseconds earlier) becomes "the current occupancy" for the
        # other; using each worker's own independently-captured `_now()`
        # here would let real-world scheduling jitter make the second
        # writer's timestamp appear to precede the first writer's already-
        # committed occupancy, spuriously tripping `InvalidEffectiveTimeError`
        # even though both moves are legitimately sequential. Equal
        # timestamps sidestep that entirely (`effective_time <
        # current_occupancy.effective_time` is false when they're equal).
        shared_effective_time = _now()
        results = _run_pair(
            test_engine, _tray_worker,
            kwargs_a=dict(tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], user_id=scenario["user_id"],
                          tray_id=scenario["tray_ids"][0], trolley_id=scenario["trolley_ids"][0], asset_position_id=levels[0],
                          effective_time=shared_effective_time),
            kwargs_b=dict(tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], user_id=scenario["user_id"],
                          tray_id=scenario["tray_ids"][0], trolley_id=scenario["trolley_ids"][0], asset_position_id=levels[1],
                          effective_time=shared_effective_time),
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


@pytest.mark.integration
def test_concurrent_case_e_two_trays_last_legacy_slot(test_engine) -> None:
    """The pre-existing legacy-Slot race, unchanged, still proven safe
    after PILOT-UX-001B."""
    scenario = _build_committed_concurrency_scenario(test_engine, chamber_capacity=None, trolley_mode="legacy")
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
        slot_id = _legacy_slot_ids(session, scenario["trolley_ids"][0])[0]
    finally:
        session.close()
        conn.close()

    try:
        results = _run_pair(
            test_engine, _tray_worker,
            kwargs_a=dict(tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], user_id=scenario["user_id"],
                          tray_id=scenario["tray_ids"][0], trolley_id=scenario["trolley_ids"][0], asset_position_id=slot_id),
            kwargs_b=dict(tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], user_id=scenario["user_id"],
                          tray_id=scenario["tray_ids"][1], trolley_id=scenario["trolley_ids"][0], asset_position_id=slot_id),
        )
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("conflict") == 1, results
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
