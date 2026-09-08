"""Shared, non-collected scenario helper for VINES-OPS-001B tests. Builds a
real InterVines-populated Batch (reusing `_transplant_scenario.build_
transplant_ready_scenario` + `intervines_transplant_service.record_
intervines_transplant`, VINES-OPS-001A's own already-proven path, unchanged)
plus a real Vines Production Greenhouse (Zone -> Span -> Grow Gutter -> Grow
Bag Position, via the existing generic farm-setup Vines template) and a
configured Grow Bag CarrierSpecification/pool. Not a test file itself
(pytest's default `test_*.py` discovery glob does not match this name)."""
import uuid
from datetime import timedelta

from app.schemas.farm_setup import (
    GreenhouseSetupCreate,
    GutterGeneratorConfig,
    SpanSetupConfig,
    VinesSetupConfig,
    ZoneSetupConfig,
)
from app.services import (
    carrier_service,
    carrier_specification_service,
    crop_batch_service,
    farm_setup_service,
    intervines_transplant_service,
)
from tests._transplant_scenario import build_transplant_ready_scenario

GROW_CUBE_TYPE = "grow_cube"
GROW_BAG_TYPE = "grow_bag"


def build_vines_production_ready_scenario(
    db_session, tenant, user, farm, *, suffix=None, intervines_plant_count=4,
    grow_bag_capacity=1, grow_bag_count=10, gutter_bag_positions=20,
):
    """Returns a dict with a Batch carrying `intervines_plant_count` living
    plants in Grow Cubes at one InterVines Table, one Vines Production
    Greenhouse with exactly one Grow Gutter (`gutter_bag_positions` free
    Grow Bag Positions under it), and `grow_bag_count` active, unassigned
    Grow Bag Carriers of one CarrierSpecification (`grow_bag_capacity`
    plants each)."""
    suffix = suffix or uuid.uuid4().hex[:8]

    # `normal` matches `intervines_plant_count` exactly (no seedling
    # surplus): leaving the TRANSPLANTING stage later is blocked by
    # WORKFLOW-INTEGRITY-001 while any living Seedling remainder is still
    # unresolved, and this scenario has no disposition step to resolve one.
    s = build_transplant_ready_scenario(
        db_session, tenant, user, farm, suffix=suffix, tray_count=1, normal=intervines_plant_count,
        transplanting_required_type=GROW_CUBE_TYPE, intervines_table_count=1, intervines_table_capacity=1000,
        # A Batch's active WorkflowStage gates the required destination
        # Carrier type for ANY Transplant (`_record_transplant_core`'s own
        # unmodified check) -- the InterVines transplant needs the Batch at
        # its TRANSPLANTING(grow_cube) stage, but the LATER Vines Production
        # transfer (destination grow_bag) needs a SECOND, differently-typed
        # transplanting-category stage, exactly the same two-stage pattern
        # NURSERY-OPS-005B's own Leafy Production Transfer already
        # established for its own second, differently-typed destination.
        second_transplant_required_type=GROW_BAG_TYPE,
    )
    extra_cubes_needed = max(0, intervines_plant_count - len(s["destination_carriers"]))
    if extra_cubes_needed:
        carrier_service.bulk_register_carriers(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            carrier_type_code=GROW_CUBE_TYPE, code_prefix=f"GCVP{suffix[:6]}-", start=1, end=extra_cubes_needed,
            pad_width=4,
        )
    table_id = s["intervines_table_ids"][0]
    aid = s["source_assignment_ids"][0]
    intervines_effective_time = s["entry_time"] + timedelta(hours=1)
    intervines_result = intervines_transplant_service.record_intervines_transplant(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), effective_time=intervines_effective_time, note=None,
        source_assignment_id=aid, plant_count=intervines_plant_count, destination_location_id=table_id,
        grow_cube_specification_id=None,
    )

    # Advance the Batch through GROWING into the second transplanting-
    # category stage (PRODUCTION_TRANSPLANT, required type grow_bag) --
    # never auto-transitioned by the scenario builder itself.
    crop_batch_service.transition_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), configured_transition_id=s["transitions"]["t2"].id,
        effective_time=intervines_effective_time + timedelta(minutes=5), reason=None,
    )
    crop_batch_service.transition_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), configured_transition_id=s["transitions"]["t2b"].id,
        effective_time=intervines_effective_time + timedelta(minutes=10), reason=None,
    )

    setup = farm_setup_service.create_greenhouse_setup(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        payload=GreenhouseSetupCreate(
            code=f"VGH-{suffix}", name="Vines Greenhouse", classification="vines", client_command_id=uuid.uuid4(),
            vines=VinesSetupConfig(
                zones=[
                    ZoneSetupConfig(
                        code="Z1",
                        spans=[
                            SpanSetupConfig(
                                code="S1",
                                gutters=GutterGeneratorConfig(
                                    code_prefix=f"GUT{suffix[:4]}-", start=1, end=1, pad_width=2,
                                    bag_positions_per_gutter=gutter_bag_positions,
                                    bag_position_code_prefix=f"POS{suffix[:4]}-", bag_position_pad_width=3,
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
    gutter = structure.vines_zones[0].spans[0].gutters[0]

    grow_bag_spec = carrier_specification_service.register_carrier_specification(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, carrier_type_code=GROW_BAG_TYPE,
        code=f"GB-SPEC-{suffix[:6]}", name="Standard Tomato Bag", length_mm=300, width_mm=300, height_mm=200,
        biological_position_count=grow_bag_capacity,
    )
    grow_bags = carrier_service.bulk_register_carriers(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, specification_id=grow_bag_spec.id,
        code_prefix=f"GB{suffix[:6]}-", start=1, end=grow_bag_count, pad_width=4,
    )

    return {
        "batch": s["batch"], "batch_id": s["batch"].id,
        "intervines_table_id": table_id, "intervines_result": intervines_result,
        "source_assignment_ids": s["source_assignment_ids"],
        "grow_gutter_id": gutter.id, "greenhouse_id": setup.greenhouse_id,
        "grow_bag_specification": grow_bag_spec, "grow_bags": grow_bags,
        "entry_time": intervines_effective_time,
    }
