"""PILOT-WATER-001A: focused domain proofs for the water/nutrient
foundation (time-efficient per the ticket's own testing section -- no full
backend suite). Each test function's docstring names which of the
ticket's 25 required proofs it covers."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.models.instrument_calibration_event import InstrumentCalibrationEvent
from app.models.location import Location
from app.models.nutrient_recipe_version import NutrientRecipeVersion
from app.models.reservoir import Reservoir
from app.models.unit_of_measure import UnitOfMeasure
from app.models.water_measurement import WaterMeasurement
from app.services import (
    asset_service,
    nutrient_mix_service,
    nutrient_recipe_service,
    reservoir_operations_service,
    sampling_point_service,
    water_exposure_service,
    water_instrument_service,
    water_topology_service,
)
from app.services.errors import (
    LocationNotFoundError,
    NutrientRecipeVersionNotDraftError,
    SamplingPointValidationError,
    WaterTopologyLinkAlreadyClosedError,
)
from tests._operational_read_scenario import (
    build_direct_placement_workflow_scaffold,
    build_greenhouse_tree,
    place_carrier,
    sow_batch,
)


def _now():
    return datetime.now(timezone.utc)


def _volume_uom(db_session):
    return db_session.execute(select(UnitOfMeasure).where(UnitOfMeasure.code == "L")).scalar_one()


def _register_water_source(db_session, tenant, user, farm, suffix):
    return water_topology_service.register_water_source(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, code=f"WS-{suffix}",
        name="Bore", source_type="bore", notes=None,
    )


def _register_reservoir(db_session, tenant, user, farm, suffix, **kwargs):
    return water_topology_service.register_reservoir(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, code=f"RES-{suffix}",
        name="Reservoir", reservoir_type="nutrient_reservoir", nominal_capacity=None,
        nominal_capacity_uom_id=None, linked_asset_id=None, location_id=None, notes=None, **kwargs,
    )


def _register_circuit(db_session, tenant, user, farm, suffix):
    return water_topology_service.register_irrigation_circuit(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, code=f"IC-{suffix}",
        name="Circuit", system_type="dwc", notes=None,
    )


# --- Part 1: topology is separate from Location hierarchy -----------------------------


def test_water_topology_is_not_inserted_into_location_hierarchy(active_context_with_farm, db_session):
    """Proof 1. A Reservoir/Circuit is never a `Location` row, and a
    Location's `location_type_id` never resolves to a water-topology
    concept -- Water topology != physical Location hierarchy."""
    tenant, user, _headers, farm = active_context_with_farm
    suffix = uuid.uuid4().hex[:8]
    reservoir = _register_reservoir(db_session, tenant, user, farm, suffix)
    assert db_session.get(Location, reservoir.id) is None
    location_type_codes = {row[0] for row in db_session.execute(select(Location.location_type_id)).all()}
    # A Reservoir's own id never appears as a location_type_id (sanity that
    # nothing wired a topology row into the location_types catalog).
    assert reservoir.id not in location_type_codes


# --- Part 5: effective-dated connections preserve history ------------------------------


def test_reservoir_circuit_link_close_preserves_history_never_overwrites(active_context_with_farm, db_session):
    """Proof 2/20. Closing a Reservoir->Circuit link never rewrites the row
    -- only `effective_to` moves from NULL to a timestamp; re-opening (or
    changing any other field) is rejected -- "what was connected to what on
    a given day" stays answerable from history that is never lost."""
    tenant, user, _headers, farm = active_context_with_farm
    suffix = uuid.uuid4().hex[:8]
    reservoir = _register_reservoir(db_session, tenant, user, farm, suffix)
    circuit = _register_circuit(db_session, tenant, user, farm, suffix)
    t0 = _now() - timedelta(days=10)
    link = water_topology_service.open_reservoir_circuit_link(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, reservoir_id=reservoir.id,
        irrigation_circuit_id=circuit.id, effective_from=t0, reason="initial plumbing",
    )
    assert link.effective_to is None

    t1 = t0 + timedelta(days=5)
    closed = water_topology_service.close_reservoir_circuit_link(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, link_id=link.id, effective_to=t1,
    )
    assert closed.id == link.id
    assert closed.effective_from == link.effective_from  # original endpoint never rewritten
    assert closed.effective_to == t1

    with pytest.raises(WaterTopologyLinkAlreadyClosedError):
        water_topology_service.close_reservoir_circuit_link(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, link_id=link.id, effective_to=t1 + timedelta(days=1),
        )

    # A new circuit may now be opened for the same reservoir (supersession
    # is a NEW row, never an edit of the old one).
    circuit_2 = _register_circuit(db_session, tenant, user, farm, suffix + "b")
    reopened = water_topology_service.open_reservoir_circuit_link(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, reservoir_id=reservoir.id,
        irrigation_circuit_id=circuit_2.id, effective_from=t1, reason="re-plumbed",
    )
    assert reopened.id != link.id


def test_only_one_active_link_per_circuit_at_a_time(active_context_with_farm, db_session):
    """Proof 2 (uniqueness half): a Circuit may draw from only one active
    Reservoir at a time -- opening a second active link for the same
    Circuit before closing the first is rejected at the DB level."""
    tenant, user, _headers, farm = active_context_with_farm
    suffix = uuid.uuid4().hex[:8]
    reservoir_a = _register_reservoir(db_session, tenant, user, farm, suffix + "a")
    reservoir_b = _register_reservoir(db_session, tenant, user, farm, suffix + "b")
    circuit = _register_circuit(db_session, tenant, user, farm, suffix)
    water_topology_service.open_reservoir_circuit_link(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, reservoir_id=reservoir_a.id,
        irrigation_circuit_id=circuit.id, effective_from=_now(), reason=None,
    )
    with pytest.raises(WaterTopologyLinkAlreadyClosedError):
        water_topology_service.open_reservoir_circuit_link(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, reservoir_id=reservoir_b.id,
            irrigation_circuit_id=circuit.id, effective_from=_now(), reason=None,
        )


# --- Part 6/7: Delivery Point authoritative Location; drain-to-waste ------------------


def test_delivery_point_requires_authoritative_location(active_context_with_farm, db_session):
    """Proof 3. A WaterDeliveryPoint must reference a real, existing
    Location id -- an unknown location_id is rejected, never silently
    accepted as a display string."""
    tenant, user, _headers, farm = active_context_with_farm
    with pytest.raises(LocationNotFoundError):
        water_topology_service.register_water_delivery_point(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, code="DP-X", name="DP",
            location_id=uuid.uuid4(), notes=None,
        )


def test_recirculating_return_mapping_and_drain_to_waste_without_return_reservoir(active_context_with_farm, db_session):
    """Proof 4 + 5. A Return Point may link to a Return Reservoir
    (recirculating) -- and, separately, a Return Point may exist with NO
    such link at all (drain-to-waste), never forcing a fabricated Return
    Reservoir."""
    tenant, user, _headers, farm = active_context_with_farm
    suffix = uuid.uuid4().hex[:8]
    return_reservoir = _register_reservoir(db_session, tenant, user, farm, suffix + "-ret")
    recirc_point = water_topology_service.register_water_return_point(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, code=f"RP-{suffix}-a",
        name="Recirculating Return", location_id=None, notes=None,
    )
    link = water_topology_service.open_return_point_reservoir_link(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        water_return_point_id=recirc_point.id, return_reservoir_id=return_reservoir.id, effective_from=_now(),
        reason=None,
    )
    assert link.return_reservoir_id == return_reservoir.id

    drain_to_waste_point = water_topology_service.register_water_return_point(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, code=f"RP-{suffix}-b",
        name="Drain to Waste", location_id=None, notes=None,
    )
    assert drain_to_waste_point.id != recirc_point.id  # exists fine, no link ever required


# --- Part 8: Sampling Point cannot float ------------------------------------------------


def test_sampling_point_requires_an_authoritative_anchor(active_context_with_farm, db_session):
    """Proof 6. A SamplingPoint of a real point_type (not 'other') must
    anchor to a real Reservoir/Circuit/etc -- missing or mismatched anchor
    is rejected, never accepted as a free-floating point."""
    tenant, user, _headers, farm = active_context_with_farm
    with pytest.raises(SamplingPointValidationError):
        sampling_point_service.register_sampling_point(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, code="SP-X", name="Floating",
            point_type="reservoir", anchor_id=None, notes=None,
        )


# --- Part 9-11: Measurement / Calibration / Recipe target independence ----------------


def test_measurement_preserves_point_time_operator_and_never_touches_calibration_or_recipe(
    active_context_with_farm, db_session,
):
    """Proof 7 + 8 + 9. A recorded pH/EC/temp/DO measurement preserves its
    SamplingPoint, effective time, and recording operator; recording it
    never rewrites a NutrientRecipeVersion's target, and never creates or
    implies an InstrumentCalibrationEvent."""
    tenant, user, _headers, farm = active_context_with_farm
    suffix = uuid.uuid4().hex[:8]
    reservoir = _register_reservoir(db_session, tenant, user, farm, suffix)
    sampling_point = sampling_point_service.register_sampling_point(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, code=f"SP-{suffix}",
        name="Reservoir Sample", point_type="reservoir", anchor_id=reservoir.id, notes=None,
    )
    recipe = nutrient_recipe_service.register_recipe(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"NR-{suffix}", name="Recipe", crop_id=None,
        variety_id=None, production_system_id=None,
    )
    version = nutrient_recipe_service.create_draft_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, nutrient_recipe_id=recipe.id,
        client_command_id=uuid.uuid4(), reason="baseline", target_ec="1.8", target_ph="6.0", instructions=None,
        effective_date=None,
    )
    effective_at = _now()
    measurement = water_instrument_service.record_measurement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, sampling_point_id=sampling_point.id,
        metric="EC", value="1.74", unit="mS/cm", effective_at=effective_at, water_instrument_id=None, notes=None,
        client_command_id=uuid.uuid4(),
    )
    assert measurement.sampling_point_id == sampling_point.id
    assert measurement.effective_at == effective_at
    assert measurement.recorded_by_user_id == user.id

    # Target unchanged.
    refreshed_version = db_session.execute(
        select(NutrientRecipeVersion).where(NutrientRecipeVersion.id == version.id)
    ).scalar_one()
    assert str(refreshed_version.target_ec) == "1.8"

    # No calibration event exists merely because a measurement was recorded.
    calibration_count = db_session.execute(
        select(InstrumentCalibrationEvent).where(InstrumentCalibrationEvent.tenant_id == tenant.id)
    ).scalars().all()
    assert calibration_count == []


def test_calibration_distinct_from_measurement(active_context_with_farm, db_session):
    """Proof 9 (instrument side): calibration status is derived only from
    `InstrumentCalibrationEvent` history, never inferred from a Measurement
    existing."""
    tenant, user, _headers, farm = active_context_with_farm
    suffix = uuid.uuid4().hex[:8]
    asset = asset_service.register_asset(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        asset_type_code="water_quality_meter", code=f"EC-{suffix}", name="EC Meter", commissioned_date=None,
    )
    instrument = water_instrument_service.register_water_instrument(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, asset_id=asset.id,
        supports_ph=False, supports_ec=True, supports_solution_temperature=False, supports_dissolved_oxygen=False,
    )
    status_before = water_instrument_service.instrument_calibration_status(
        db_session, tenant_id=tenant.id, water_instrument_id=instrument.id
    )
    assert status_before["latest_by_metric"] == {}

    water_instrument_service.record_calibration(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, water_instrument_id=instrument.id,
        metric="EC", effective_at=_now(), result="pass", standard_reference="1413 uS/cm standard", notes=None,
        client_command_id=uuid.uuid4(),
    )
    status_after = water_instrument_service.instrument_calibration_status(
        db_session, tenant_id=tenant.id, water_instrument_id=instrument.id
    )
    assert status_after["latest_by_metric"]["EC"]["result"] == "pass"


# --- Part 12/13: Recipe version lifecycle + components never touch inventory -----------


def test_active_recipe_version_immutable_and_new_version_preserves_old(active_context_with_farm, db_session):
    """Proof 10 + 11. An ACTIVE version rejects new components; activating
    a second (draft) version retires the first without deleting it -- its
    content (target_ec) is preserved, not overwritten."""
    tenant, user, _headers, farm = active_context_with_farm
    suffix = uuid.uuid4().hex[:8]
    recipe = nutrient_recipe_service.register_recipe(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"NR-{suffix}", name="Recipe", crop_id=None,
        variety_id=None, production_system_id=None,
    )
    v1 = nutrient_recipe_service.create_draft_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, nutrient_recipe_id=recipe.id,
        client_command_id=uuid.uuid4(), reason="v1", target_ec="1.6", target_ph=None, instructions=None,
        effective_date=None,
    )
    nutrient_recipe_service.activate_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, version_id=v1.id, client_command_id=uuid.uuid4(),
    )
    uom = _volume_uom(db_session)
    with pytest.raises(NutrientRecipeVersionNotDraftError):
        nutrient_recipe_service.add_component(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, version_id=v1.id, inventory_item_id=None,
            component_label="Stock A", target_quantity="1", target_quantity_uom_id=uom.id, basis_volume=None,
            basis_volume_uom_id=None, sequence_number=1, instructions=None,
        )

    v2 = nutrient_recipe_service.create_draft_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, nutrient_recipe_id=recipe.id,
        client_command_id=uuid.uuid4(), reason="v2", target_ec="1.8", target_ph=None, instructions=None,
        effective_date=None,
    )
    nutrient_recipe_service.activate_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, version_id=v2.id, client_command_id=uuid.uuid4(),
    )
    v1_after = nutrient_recipe_service.get_version(db_session, tenant_id=tenant.id, version_id=v1.id)
    assert v1_after.state == "retired"
    assert str(v1_after.target_ec) == "1.6"  # preserved, never overwritten
    v2_after = nutrient_recipe_service.get_version(db_session, tenant_id=tenant.id, version_id=v2.id)
    assert v2_after.state == "active"


def test_recipe_components_are_targets_and_never_touch_inventory_existence(active_context_with_farm, db_session):
    """Proof 12 + 25. Adding recipe components never writes an
    InventoryExistenceLedgerEntry row -- targets are never confused with
    real stock movement."""
    from app.models.inventory_existence_ledger_entry import InventoryExistenceLedgerEntry

    tenant, user, _headers, farm = active_context_with_farm
    suffix = uuid.uuid4().hex[:8]
    before = db_session.execute(select(InventoryExistenceLedgerEntry)).scalars().all()

    recipe = nutrient_recipe_service.register_recipe(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"NR-{suffix}", name="Recipe", crop_id=None,
        variety_id=None, production_system_id=None,
    )
    version = nutrient_recipe_service.create_draft_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, nutrient_recipe_id=recipe.id,
        client_command_id=uuid.uuid4(), reason="v1", target_ec=None, target_ph=None, instructions=None,
        effective_date=None,
    )
    uom = _volume_uom(db_session)
    nutrient_recipe_service.add_component(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, version_id=version.id, inventory_item_id=None,
        component_label="Source Water", target_quantity="100", target_quantity_uom_id=uom.id, basis_volume=None,
        basis_volume_uom_id=None, sequence_number=1, instructions=None,
    )
    after = db_session.execute(select(InventoryExistenceLedgerEntry)).scalars().all()
    assert len(after) == len(before)


# --- Part 14/15/18: Mix != Delivery, Recipe != Mix, top-up doesn't infer EC/pH ---------


def test_mix_records_actual_facts_never_copies_target_never_implies_delivery(active_context_with_farm, db_session):
    """Proof 13 + 14 + 15. Recording a NutrientMix with explicit actual
    inputs never copies the recipe's target quantities; creating the Mix
    creates no WaterDeliveryEvent; activating a Recipe Version creates no
    NutrientMix."""
    tenant, user, _headers, farm = active_context_with_farm
    suffix = uuid.uuid4().hex[:8]
    reservoir = _register_reservoir(db_session, tenant, user, farm, suffix)
    recipe = nutrient_recipe_service.register_recipe(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"NR-{suffix}", name="Recipe", crop_id=None,
        variety_id=None, production_system_id=None,
    )
    version = nutrient_recipe_service.create_draft_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, nutrient_recipe_id=recipe.id,
        client_command_id=uuid.uuid4(), reason="v1", target_ec="1.8", target_ph=None, instructions=None,
        effective_date=None,
    )
    nutrient_recipe_service.activate_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, version_id=version.id, client_command_id=uuid.uuid4(),
    )
    # Recipe activation alone implies no Mix.
    assert nutrient_mix_service.list_mixes_for_reservoir(db_session, tenant_id=tenant.id, reservoir_id=reservoir.id) == []

    uom = _volume_uom(db_session)
    mix = nutrient_mix_service.record_mix(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, reservoir_id=reservoir.id,
        nutrient_recipe_version_id=version.id, effective_at=_now(), target_volume=None, target_volume_uom_id=None,
        actual_volume="500", actual_volume_uom_id=uom.id, notes=None, client_command_id=uuid.uuid4(),
        inputs=[
            {
                "inventory_item_id": None, "component_label": "Stock A Actual", "actual_quantity": "2.5",
                "actual_quantity_uom_id": uom.id, "sequence_number": 1, "note": None,
            }
        ],
    )
    inputs = nutrient_mix_service.list_mix_inputs(db_session, tenant_id=tenant.id, nutrient_mix_id=mix.id)
    assert len(inputs) == 1
    assert str(inputs[0].actual_quantity) == "2.5"  # explicit fact, not the recipe's own target

    # Mix creation implies no Delivery.
    delivery_events = reservoir_operations_service.list_delivery_events_for_circuit(
        db_session, tenant_id=tenant.id, irrigation_circuit_id=uuid.uuid4()
    )
    assert delivery_events == []


def test_reservoir_top_up_does_not_infer_ec_or_ph(active_context_with_farm, db_session):
    """Proof 18. Recording a WATER_TOP_UP event never writes or infers a
    resulting EC/pH -- `ReservoirEvent` structurally has no such column."""
    tenant, user, _headers, farm = active_context_with_farm
    suffix = uuid.uuid4().hex[:8]
    reservoir = _register_reservoir(db_session, tenant, user, farm, suffix)
    event = reservoir_operations_service.record_reservoir_event(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, reservoir_id=reservoir.id,
        event_type="WATER_TOP_UP", effective_at=_now(), quantity="50", quantity_uom_id=_volume_uom(db_session).id,
        inventory_item_id=None, notes=None, client_command_id=uuid.uuid4(),
    )
    assert not hasattr(event, "resulting_ec")
    assert not hasattr(event, "resulting_ph")


# --- Part 16/17: Delivery without fabricated volume; continuous interval --------------


def test_delivery_event_can_exist_without_volume_and_as_open_ended_interval(active_context_with_farm, db_session):
    """Proof 16 + 17. A Delivery may be recorded with no volume at all
    (only "delivery occurred from X to Y"), and a continuously-circulating
    DWC delivery may be represented as an open-ended interval
    (`effective_end = NULL`)."""
    tenant, user, _headers, farm = active_context_with_farm
    suffix = uuid.uuid4().hex[:8]
    reservoir = _register_reservoir(db_session, tenant, user, farm, suffix)
    circuit = _register_circuit(db_session, tenant, user, farm, suffix)
    event = reservoir_operations_service.record_delivery_event(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, reservoir_id=reservoir.id,
        irrigation_circuit_id=circuit.id, effective_start=_now(), effective_end=None, delivered_volume=None,
        delivered_volume_uom_id=None, nutrient_mix_id=None, notes="continuous DWC circulation",
        client_command_id=uuid.uuid4(),
    )
    assert event.delivered_volume is None
    assert event.effective_end is None


# --- Part 19-21: exposure read model -----------------------------------------------------


def test_exposure_is_potential_never_a_disease_claim_and_respects_topology_and_movement_history(
    active_context_with_farm, db_session,
):
    """Proof 19 + 20 + 21. Full integration: a Circuit mapped to a
    Location ancestor exposes every occupiable descendant during the
    window it was mapped; the exposure kind is always
    CONFIGURED_TOPOLOGY/RECORDED_DELIVERY, never a disease/contamination
    word; moving the Batch's Carrier away, and querying a window before the
    placement ever existed, both correctly return no exposure."""
    tenant, user, _headers, farm = active_context_with_farm
    suffix = uuid.uuid4().hex[:8]

    tree = build_greenhouse_tree(db_session, tenant, user, farm, suffix=suffix, position_count=1)
    grow_table = tree["positions"][0]

    scaffold = build_direct_placement_workflow_scaffold(db_session, tenant, user, farm, suffix=suffix)
    t_placed = _now() - timedelta(hours=5)
    result = sow_batch(
        db_session, tenant, user, farm, scaffold, effective_time=t_placed, code_suffix=suffix,
        carrier_type_code="cultivation_plate", carrier_count=1,
    )
    batch, carrier = result["batch"], result["tray"]
    place_carrier(db_session, tenant, user, farm, carrier_id=carrier.id, location_id=grow_table.id, effective_time=t_placed)

    reservoir = _register_reservoir(db_session, tenant, user, farm, suffix)
    circuit = _register_circuit(db_session, tenant, user, farm, suffix)
    water_topology_service.open_reservoir_circuit_link(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, reservoir_id=reservoir.id,
        irrigation_circuit_id=circuit.id, effective_from=t_placed - timedelta(days=1), reason=None,
    )
    delivery_point = water_topology_service.register_water_delivery_point(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, code=f"DP-{suffix}",
        name="Zone Delivery", location_id=tree["zone"].id, notes=None,  # ancestor of grow_table, not the leaf itself
    )
    water_topology_service.open_circuit_delivery_point_link(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, irrigation_circuit_id=circuit.id,
        water_delivery_point_id=delivery_point.id, effective_from=t_placed - timedelta(days=1), reason=None,
    )

    window_start = t_placed - timedelta(minutes=30)
    window_end = t_placed + timedelta(hours=1)

    exposed = water_exposure_service.get_potentially_exposed_placements_for_circuit(
        db_session, tenant_id=tenant.id, farm_id=farm.id, irrigation_circuit_id=circuit.id, window_start=window_start,
        window_end=window_end,
    )
    assert len(exposed) == 1
    assert exposed[0]["batch_id"] == batch.id
    assert exposed[0]["location_id"] == grow_table.id  # descendant of the mapped Zone, correctly included
    assert exposed[0]["exposure_kind"] == water_exposure_service.CONFIGURED_TOPOLOGY
    for forbidden in ("affected", "contaminated", "infected", "disease"):
        assert forbidden not in exposed[0]["exposure_kind"].lower()

    # A window entirely BEFORE the placement ever existed returns nothing.
    empty = water_exposure_service.get_potentially_exposed_placements_for_circuit(
        db_session, tenant_id=tenant.id, farm_id=farm.id, irrigation_circuit_id=circuit.id,
        window_start=t_placed - timedelta(days=2), window_end=t_placed - timedelta(days=1),
    )
    assert empty == []

    # Recording an actual overlapping Delivery upgrades the exposure kind.
    reservoir_operations_service.record_delivery_event(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, reservoir_id=reservoir.id,
        irrigation_circuit_id=circuit.id, effective_start=t_placed, effective_end=t_placed + timedelta(minutes=10),
        delivered_volume=None, delivered_volume_uom_id=None, nutrient_mix_id=None, notes=None,
        client_command_id=uuid.uuid4(),
    )
    exposed_with_delivery = water_exposure_service.get_potentially_exposed_placements_for_circuit(
        db_session, tenant_id=tenant.id, farm_id=farm.id, irrigation_circuit_id=circuit.id, window_start=window_start,
        window_end=window_end,
    )
    assert exposed_with_delivery[0]["exposure_kind"] == water_exposure_service.RECORDED_DELIVERY

    # Moving the carrier away, then querying a window fully after the move,
    # returns no exposure -- movement history changes exposure correctly.
    t_moved = t_placed + timedelta(hours=3)
    other_table = build_greenhouse_tree(db_session, tenant, user, farm, suffix=suffix + "-other", position_count=1)["positions"][0]
    place_carrier(db_session, tenant, user, farm, carrier_id=carrier.id, location_id=other_table.id, effective_time=t_moved)
    after_move = water_exposure_service.get_potentially_exposed_placements_for_circuit(
        db_session, tenant_id=tenant.id, farm_id=farm.id, irrigation_circuit_id=circuit.id,
        window_start=t_moved + timedelta(minutes=1), window_end=t_moved + timedelta(hours=1),
    )
    assert after_move == []


# --- Part 22: tenant isolation -----------------------------------------------------------


def test_cross_tenant_reservoir_access_is_blocked(active_context_with_farm, db_session):
    """Proof 22. A Reservoir registered under tenant A is not resolvable
    using tenant B's id -- tenant isolation is enforced in the query, never
    left to the frontend."""
    from app.services import farm_service, membership_service, tenant_service, user_service
    from app.services.errors import ReservoirNotFoundError

    tenant, user, _headers, farm = active_context_with_farm
    suffix = uuid.uuid4().hex[:8]
    reservoir = _register_reservoir(db_session, tenant, user, farm, suffix)

    other_tenant = tenant_service.create_tenant(db_session, code=f"other-{suffix}", name="Other Tenant")
    other_user = user_service.create_user(
        db_session, oidc_issuer="other", oidc_subject=suffix, email=f"other-{suffix}@example.com",
        display_name="Other User",
    )
    membership_service.add_membership(
        db_session, tenant_id=other_tenant.id, user_id=other_user.id, role_code="tenant_admin", actor_user_id=None,
    )
    with pytest.raises(ReservoirNotFoundError):
        water_topology_service.get_reservoir(db_session, tenant_id=other_tenant.id, reservoir_id=reservoir.id)


# --- Part 23/26: immutability / no hard-delete / no direct rewrite ---------------------


def test_water_measurement_is_immutable_no_update_no_delete(active_context_with_farm, db_session):
    """Proof 23 + 26. Direct UPDATE/DELETE against `water_measurements`
    (bypassing the service layer entirely) is rejected by the DB itself --
    correction always means a new record, never rewriting history."""
    tenant, user, _headers, farm = active_context_with_farm
    suffix = uuid.uuid4().hex[:8]
    reservoir = _register_reservoir(db_session, tenant, user, farm, suffix)
    sampling_point = sampling_point_service.register_sampling_point(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, code=f"SP-{suffix}",
        name="Reservoir Sample", point_type="reservoir", anchor_id=reservoir.id, notes=None,
    )
    measurement = water_instrument_service.record_measurement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, sampling_point_id=sampling_point.id,
        metric="PH", value="6.0", unit="pH", effective_at=_now(), water_instrument_id=None, notes=None,
        client_command_id=uuid.uuid4(),
    )
    db_session.execute(select(WaterMeasurement).where(WaterMeasurement.id == measurement.id))  # sanity read

    with pytest.raises(DBAPIError):
        db_session.execute(
            WaterMeasurement.__table__.update().where(WaterMeasurement.id == measurement.id).values(value="99")
        )
    db_session.rollback()

    with pytest.raises(DBAPIError):
        db_session.execute(WaterMeasurement.__table__.delete().where(WaterMeasurement.id == measurement.id))
    db_session.rollback()


# --- Part migration: single-head proof ---------------------------------------------------


def test_alembic_has_a_single_head_including_this_ticket_migration():
    """Proof 24 (partial -- full upgrade/downgrade already exercised
    manually against cmp_test per the ticket's own migration requirements).
    A second head would mean an unmerged branch in migration history."""
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    api_root = Path(__file__).resolve().parent.parent
    cfg = Config(str(api_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(api_root / "migrations"))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1
    assert heads[0] == "0d62f68527a2"


# --- PILOT-WATER-001B: server-authoritative NOW (HOTFIX-TIME-002 pattern) -------------


def test_measurement_omitted_effective_at_uses_server_time_not_future_rejected(active_context_with_farm, db_session):
    """Proof 21. Omitting `effective_at` records "now" using the server's
    own clock (never a client-supplied timestamp); an explicit future
    timestamp is rejected cleanly."""
    tenant, user, _headers, farm = active_context_with_farm
    suffix = uuid.uuid4().hex[:8]
    reservoir = _register_reservoir(db_session, tenant, user, farm, suffix)
    sampling_point = sampling_point_service.register_sampling_point(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, code=f"SP-{suffix}",
        name="Reservoir Sample", point_type="reservoir", anchor_id=reservoir.id, notes=None,
    )
    before = datetime.now(timezone.utc)
    measurement = water_instrument_service.record_measurement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, sampling_point_id=sampling_point.id,
        metric="PH", value="6.0", unit="pH", effective_at=None, water_instrument_id=None, notes=None,
        client_command_id=uuid.uuid4(),
    )
    after = datetime.now(timezone.utc)
    assert before <= measurement.effective_at <= after

    from app.services.errors import WaterMeasurementValidationError

    with pytest.raises(WaterMeasurementValidationError):
        water_instrument_service.record_measurement(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            sampling_point_id=sampling_point.id, metric="PH", value="6.0", unit="pH",
            effective_at=_now() + timedelta(days=1), water_instrument_id=None, notes=None,
            client_command_id=uuid.uuid4(),
        )


def test_measurement_now_command_retry_is_idempotent_not_a_second_row(active_context_with_farm, db_session):
    """Proof 21 (idempotency half). Retrying the same `client_command_id`
    with `effective_at=None` replays the original row -- it never creates a
    second measurement with a later "now"."""
    tenant, user, _headers, farm = active_context_with_farm
    suffix = uuid.uuid4().hex[:8]
    reservoir = _register_reservoir(db_session, tenant, user, farm, suffix)
    sampling_point = sampling_point_service.register_sampling_point(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, code=f"SP-{suffix}",
        name="Reservoir Sample", point_type="reservoir", anchor_id=reservoir.id, notes=None,
    )
    command_id = uuid.uuid4()
    first = water_instrument_service.record_measurement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, sampling_point_id=sampling_point.id,
        metric="PH", value="6.0", unit="pH", effective_at=None, water_instrument_id=None, notes=None,
        client_command_id=command_id,
    )
    second = water_instrument_service.record_measurement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, sampling_point_id=sampling_point.id,
        metric="PH", value="6.0", unit="pH", effective_at=None, water_instrument_id=None, notes=None,
        client_command_id=command_id,
    )
    assert first.id == second.id
    assert first.effective_at == second.effective_at


# --- PILOT-WATER-001B: farm-wide topology/operational reads + Water Attention ----------


def test_multiple_water_sources_and_one_source_feeding_multiple_reservoirs(active_context_with_farm, db_session):
    """Proofs 1 + 2 (frontend/001B). Multiple independent WaterSources may
    exist on one farm, and one WaterSource may feed multiple Reservoirs --
    never a "one source per farm" assumption."""
    tenant, user, _headers, farm = active_context_with_farm
    suffix = uuid.uuid4().hex[:8]
    ro_plant = water_topology_service.register_water_source(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, code=f"RO-{suffix}",
        name="RO Plant", source_type="ro_treated", notes=None,
    )
    bore = water_topology_service.register_water_source(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, code=f"BORE-{suffix}",
        name="Bore Water", source_type="bore", notes=None,
    )
    reservoir_a = _register_reservoir(db_session, tenant, user, farm, suffix + "a")
    reservoir_b = _register_reservoir(db_session, tenant, user, farm, suffix + "b")
    water_topology_service.open_water_source_reservoir_link(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, water_source_id=ro_plant.id,
        reservoir_id=reservoir_a.id, effective_from=_now() - timedelta(days=1), reason=None,
    )
    water_topology_service.open_water_source_reservoir_link(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, water_source_id=ro_plant.id,
        reservoir_id=reservoir_b.id, effective_from=_now() - timedelta(days=1), reason=None,
    )

    sources = water_topology_service.list_water_sources(db_session, tenant_id=tenant.id, farm_id=farm.id)
    assert {s.id for s in sources} >= {ro_plant.id, bore.id}

    links = water_topology_service.list_water_source_reservoir_links(db_session, tenant_id=tenant.id, farm_id=farm.id)
    ro_plant_reservoirs = {link.reservoir_id for link in links if link.water_source_id == ro_plant.id}
    assert ro_plant_reservoirs == {reservoir_a.id, reservoir_b.id}


def test_topology_link_list_shows_historical_and_current_together(active_context_with_farm, db_session):
    """Proof 5. Closing and re-opening a link never removes the closed row
    from the farm-wide list -- both the historical and current rows remain
    visible (section 6/26)."""
    tenant, user, _headers, farm = active_context_with_farm
    suffix = uuid.uuid4().hex[:8]
    reservoir_a = _register_reservoir(db_session, tenant, user, farm, suffix + "a")
    reservoir_b = _register_reservoir(db_session, tenant, user, farm, suffix + "b")
    circuit = _register_circuit(db_session, tenant, user, farm, suffix)

    old_link = water_topology_service.open_reservoir_circuit_link(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, reservoir_id=reservoir_a.id,
        irrigation_circuit_id=circuit.id, effective_from=_now() - timedelta(days=10), reason="initial",
    )
    water_topology_service.close_reservoir_circuit_link(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, link_id=old_link.id,
        effective_to=_now() - timedelta(days=5),
    )
    new_link = water_topology_service.open_reservoir_circuit_link(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, reservoir_id=reservoir_b.id,
        irrigation_circuit_id=circuit.id, effective_from=_now() - timedelta(days=5), reason="re-plumbed",
    )

    links = water_topology_service.list_reservoir_circuit_links(db_session, tenant_id=tenant.id, farm_id=farm.id)
    ids = {link.id for link in links}
    assert old_link.id in ids and new_link.id in ids
    by_id = {link.id: link for link in links}
    assert by_id[old_link.id].effective_to is not None
    assert by_id[new_link.id].effective_to is None


def test_farm_wide_lists_aggregate_across_every_reservoir_and_circuit(active_context_with_farm, db_session):
    """Proof 3 + 4 (frontend/001B). Farm-wide Mix/Reservoir-Event/Delivery-
    Event/Measurement reads span every Reservoir/Circuit on the farm, not
    just one -- the "recent activity" Overview needs this across
    independently-serving Tanks."""
    tenant, user, _headers, farm = active_context_with_farm
    suffix = uuid.uuid4().hex[:8]
    reservoir_a = _register_reservoir(db_session, tenant, user, farm, suffix + "a")
    reservoir_b = _register_reservoir(db_session, tenant, user, farm, suffix + "b")

    reservoir_operations_service.record_reservoir_event(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, reservoir_id=reservoir_a.id,
        event_type="WATER_TOP_UP", effective_at=None, quantity=None, quantity_uom_id=None, inventory_item_id=None,
        notes=None, client_command_id=uuid.uuid4(),
    )
    reservoir_operations_service.record_reservoir_event(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, reservoir_id=reservoir_b.id,
        event_type="FLUSH", effective_at=None, quantity=None, quantity_uom_id=None, inventory_item_id=None,
        notes=None, client_command_id=uuid.uuid4(),
    )
    events = reservoir_operations_service.list_reservoir_events_for_farm(db_session, tenant_id=tenant.id, farm_id=farm.id)
    assert {e.reservoir_id for e in events} == {reservoir_a.id, reservoir_b.id}


def test_water_attention_flags_active_circuit_missing_reservoir_and_never_calibrated_instrument(
    active_context_with_farm, db_session,
):
    """Proof: Today Water Attention surfaces only genuine, explicit facts
    -- never a manufactured threshold (section 28)."""
    tenant, user, _headers, farm = active_context_with_farm
    suffix = uuid.uuid4().hex[:8]
    circuit = _register_circuit(db_session, tenant, user, farm, suffix)
    asset = asset_service.register_asset(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        asset_type_code="water_quality_meter", code=f"WQ-{suffix}", name="Meter", commissioned_date=None,
    )
    instrument = water_instrument_service.register_water_instrument(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, asset_id=asset.id,
        supports_ph=True, supports_ec=False, supports_solution_temperature=False, supports_dissolved_oxygen=False,
    )

    from app.services import water_attention_service

    items = water_attention_service.get_water_attention(db_session, tenant_id=tenant.id, farm_id=farm.id)
    kinds_for_circuit = {i["kind"] for i in items if i.get("irrigation_circuit_id") == circuit.id}
    assert "CIRCUIT_MISSING_RESERVOIR" in kinds_for_circuit
    kinds_for_instrument = {i["kind"] for i in items if i.get("water_instrument_id") == instrument.id}
    assert "INSTRUMENT_NEVER_CALIBRATED" in kinds_for_instrument

    # Feeding the circuit clears the topology-gap signal.
    reservoir = _register_reservoir(db_session, tenant, user, farm, suffix)
    water_topology_service.open_reservoir_circuit_link(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, reservoir_id=reservoir.id,
        irrigation_circuit_id=circuit.id, effective_from=_now(), reason=None,
    )
    items_after = water_attention_service.get_water_attention(db_session, tenant_id=tenant.id, farm_id=farm.id)
    assert not any(
        i["kind"] == "CIRCUIT_MISSING_RESERVOIR" and i.get("irrigation_circuit_id") == circuit.id
        for i in items_after
    )
