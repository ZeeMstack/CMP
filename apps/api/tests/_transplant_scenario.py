"""Shared, non-collected scenario helper for NURSERY-OPS-004A transplant
tests. Builds a real Nursery Seed Tray scenario (sow -> Germination ->
SeedlingEntry), each source Tray SeedlingEntry-anchored, matching the ONLY
source shape modern `transplant_service.record_transplant` accepts --
`sown_site_count` is deliberately never recorded for these Trays
(NURSERY-OPS-001.1), proving the modern path never depends on it. Mirrors
`test_seedling_disposition.py`'s own `_build_entered_scenario` shape,
extended with the TRANSPLANTING/GROWING/COMPLETE workflow stages
`transplant_service` itself requires. Not a test file itself (pytest's
default `test_*.py` discovery glob does not match this name)."""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.models.carrier import Carrier
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
    crop_batch_service,
    crop_service,
    farm_setup_service,
    germination_outcome_service,
    germination_service,
    nursery_service,
    production_system_service,
    seedling_entry_service,
    sowing_service,
    workflow_service,
)
from tests.conftest import ensure_seed_tray_specification


def now():
    return datetime.now(timezone.utc)


def build_transplant_ready_scenario(
    db_session, tenant, user, farm, *, suffix=None, tray_count=4, normal=200, abnormal=0,
    transplanting_required_type="cultivation_plate", legacy_seed_tray_no_specification=False,
    destination_specification_id=None, intersalads_table_count=0, intersalads_table_capacity=None,
    production_stage=False, second_transplant_required_type=None,
):
    """A Batch with `tray_count` Seed Trays, each sown, germinated, and
    entered through SeedlingEntry (frozen `starting_living_seedling_count =
    normal + abnormal`), workflow already advanced into a TRANSPLANTING-
    category stage. Also returns `destination_carriers` (4 pre-registered
    `transplanting_required_type` carriers, reusable across tests) and the
    configured stage/transition ids `transplant_service` itself checks.

    Sows via `nursery_service.sow_new_batch`, which hard-requires the
    workflow's SEEDING stage to use `seed_tray` (see nursery_service.
    SEED_TRAY_CARRIER_TYPE_CODE) -- seed_tray is not a free choice here the
    way it is in other domains' scenario builders.

    CARRIER-CONFIG-001A: `legacy_seed_tray_no_specification=True` (default
    False, unchanged behavior for every existing caller) constructs the
    seed_tray Carriers via a direct raw-SQL INSERT (specification_id column
    omitted, defaulting NULL) instead of `carrier_service.register_carrier`,
    which at head schema correctly requires a specification for seed_tray.
    This models a genuinely valid, still-supported historical Carrier state
    (a pre-001A seed_tray row) for the handful of downgrade-guard callers
    that need a real seed_tray without ever creating a committed
    carrier_specifications row (which would otherwise make e5b8c3a72f04's
    own, unconditional guard fire before the older guard under test).

    NURSERY-OPS-004B.1: `destination_specification_id` (default `None`,
    unchanged behavior for every existing caller) registers the 4
    `destination_carriers` against that specification instead of by bare
    `carrier_type_code` -- required for `transplanting_required_type`
    values that `requires_specification` (e.g. `nursery_cultivation_plate`),
    which `carrier_service.register_carrier` rejects without one.

    NURSERY-OPS-005A: `production_stage=True` (default False, unchanged
    behavior for every existing caller) adds one extra stage/transition --
    GROWING -> PRODUCTION (stage_category="production", no required Carrier
    type) -- alongside the existing GROWING -> COMPLETE transition (t3),
    never replacing it. Returned as `stages["PRODUCTION"]`/`transitions
    ["t4"]` (both `None` when not requested).

    NURSERY-OPS-005B: `second_transplant_required_type` (default `None`,
    unchanged behavior for every existing caller) adds a SECOND
    transplanting-category stage, GROWING -> PRODUCTION_TRANSPLANT,
    required_carrier_type_code=<given type> -- needed because a single
    WorkflowStage's required_carrier_type_id is one column, so chaining an
    opening transplant of one destination type and a later, differently-
    typed destination transplant (e.g. the Leafy Production Transfer
    composite's own production_cultivation_plate) needs two distinct
    transplanting-category stages, exactly how a real tenant would
    configure two sequential physical transplant operations. Returned as
    `stages["PRODUCTION_TRANSPLANT"]`/`transitions["t2b"]` (both `None`
    when not requested); never auto-transitioned into -- the caller must
    call `crop_batch_service.transition_stage` explicitly."""
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
    transplanting_stage = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="TRANSPLANTING", name="Transplanting", display_order=1, stage_category="transplanting",
        expected_duration_minutes=None, permitted_location_type_code=None,
        required_carrier_type_code=transplanting_required_type, is_start=False, is_terminal=False,
    )
    growing_stage = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="GROWING", name="Growing", display_order=2, stage_category="intermediate",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=False,
    )
    complete_stage = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="COMPLETE", name="Complete", display_order=3, stage_category="completed",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=True,
    )
    t1 = workflow_service.add_transition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=seeding_stage.id, to_stage_id=transplanting_stage.id, code="ADVANCE-1", name="Advance 1",
    )
    t2 = workflow_service.add_transition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=transplanting_stage.id, to_stage_id=growing_stage.id, code="ADVANCE-2", name="Advance 2",
    )
    t3 = workflow_service.add_transition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=growing_stage.id, to_stage_id=complete_stage.id, code="ADVANCE-3", name="Advance 3",
    )
    production_stage_obj = None
    t4 = None
    if production_stage:
        production_stage_obj = workflow_service.add_stage(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
            code="PRODUCTION", name="Production", display_order=4, stage_category="production",
            expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
            is_start=False, is_terminal=True,
        )
        t4 = workflow_service.add_transition(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
            from_stage_id=growing_stage.id, to_stage_id=production_stage_obj.id, code="ADVANCE-4", name="Advance 4",
        )
    # NURSERY-OPS-005B: `second_transplant_required_type` (default None,
    # unchanged behavior for every existing caller) adds a SECOND
    # transplanting-category stage, GROWING -> PRODUCTION_TRANSPLANT,
    # required_carrier_type_code=<given type>. A single WorkflowStage's
    # required_carrier_type_id is one column, so a Batch chaining a
    # Nursery-Plate-typed opening transplant (needs the FIRST TRANSPLANTING
    # stage's own required type) and a later, DIFFERENTLY-typed destination
    # transplant (e.g. production_cultivation_plate, 005B's own composite)
    # genuinely needs two distinct transplanting-category stages -- exactly
    # how a real tenant would configure two sequential physical transplant
    # operations. Returned as `stages["PRODUCTION_TRANSPLANT"]`/
    # `transitions["t2b"]` (both None when not requested). The caller is
    # responsible for explicitly transitioning into it via `crop_batch_
    # service.transition_stage` before recording a transplant destined for
    # it -- this helper never auto-transitions.
    production_transplant_stage_obj = None
    t2b = None
    if second_transplant_required_type is not None:
        # NOT terminal: transitioning INTO a terminal stage closes the
        # Batch atomically (crop_batch_service's own documented behavior),
        # which would make this stage unusable for any further command --
        # the whole point of this stage is to host the Leafy Production
        # Transfer composite call(s) that happen strictly AFTER entering
        # it. Needs its own outgoing transition to satisfy workflow
        # publication validation ("non-terminal stage must have at least
        # one outgoing transition") -- reuses the existing `complete_stage`
        # as a harmless, always-available target no test needs to reach.
        production_transplant_stage_obj = workflow_service.add_stage(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
            code="PRODUCTION_TRANSPLANT", name="Production Transplant", display_order=5,
            stage_category="transplanting", expected_duration_minutes=None, permitted_location_type_code=None,
            required_carrier_type_code=second_transplant_required_type, is_start=False, is_terminal=False,
        )
        t2b = workflow_service.add_transition(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
            from_stage_id=growing_stage.id, to_stage_id=production_transplant_stage_obj.id, code="ADVANCE-2B",
            name="Advance 2B",
        )
        workflow_service.add_transition(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
            from_stage_id=production_transplant_stage_obj.id, to_stage_id=complete_stage.id, code="ADVANCE-2C",
            name="Advance 2C",
        )
    workflow_service.publish_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id
    )

    seed_lot = sowing_service.register_seed_lot(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id,
        variety_id=variety.id, code=f"LOT-{suffix}", supplier_name="Rijk Zwaan", supplier_lot_reference="RZ-001",
        received_date=None, expiry_date=None,
    )

    nursery_config_kwargs = dict(
        seeding_station=NurserySectionConfig(code=f"SEED-{suffix}"),
        germination_chamber=GerminationChamberSetupConfig(code=f"GC-{suffix}", trolley_capacity=None),
        seedling_tables=TableGeneratorConfig(
            code_prefix=f"ST{suffix[:4]}", start=1, end=2, pad_width=2, capacity=tray_count
        ),
    )
    # NURSERY-OPS-004B.1: opt-in InterSalads Tables, same greenhouse -- 0
    # (default) is unchanged behavior for every existing caller of this
    # shared scenario builder.
    if intersalads_table_count > 0:
        nursery_config_kwargs["intersalads_tables"] = TableGeneratorConfig(
            code_prefix=f"IS{suffix[:4]}", start=1, end=intersalads_table_count, pad_width=2,
            capacity=intersalads_table_capacity,
        )
    setup = farm_setup_service.create_greenhouse_setup(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        payload=GreenhouseSetupCreate(
            code=f"NUR-{suffix}", name="Nursery", classification="nursery", client_command_id=uuid.uuid4(),
            nursery=NurserySetupConfig(**nursery_config_kwargs),
        ),
    )
    structure = farm_setup_service.get_greenhouse_structure(
        db_session.connection(), tenant_id=tenant.id, farm_id=farm.id, greenhouse_id=setup.greenhouse_id,
    )
    seeding_station_id = structure.nursery_seeding_stations[0].id
    chamber_id = structure.nursery_germination_chamber.id
    table_ids = [t.id for t in structure.nursery_seedling.tables]
    intersalads_table_ids = (
        [t.id for t in structure.nursery_intersalads.tables] if structure.nursery_intersalads else []
    )

    trolley = asset_service.register_asset(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        asset_type_code="germination_trolley", code=f"GT-{suffix}", name="Trolley", commissioned_date=None,
    )
    asset_service.generate_positions(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, asset_id=trolley.id,
        shelf_count=2, slots_per_shelf=4, shelf_prefix=f"SH-{suffix}-", slot_prefix="SL-",
        shelf_pad_width=2, slot_pad_width=2,
    )

    if legacy_seed_tray_no_specification:
        seed_tray_type_id = db_session.execute(
            text("SELECT id FROM carrier_types WHERE code = 'seed_tray'")
        ).scalar_one()
        carriers = []
        for n in range(1, tray_count + 1):
            carrier_id = uuid.uuid4()
            code = f"ST-{suffix}-{n:04d}"
            db_session.execute(
                text(
                    "INSERT INTO carriers (id, tenant_id, farm_id, carrier_type_id, code, status, issued_date, "
                    "retired_date) VALUES (:id, :tid, :fid, :ctid, :code, 'active', NULL, NULL)"
                ),
                {"id": carrier_id, "tid": tenant.id, "fid": farm.id, "ctid": seed_tray_type_id, "code": code},
            )
            carriers.append(db_session.get(Carrier, carrier_id))
    else:
        seed_tray_spec = ensure_seed_tray_specification(db_session, tenant_id=tenant.id, actor_user_id=user.id)
        carriers = [
            carrier_service.register_carrier(
                db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
                specification_id=seed_tray_spec.id, code=f"ST-{suffix}-{n:04d}", issued_date=None,
            )
            for n in range(1, tray_count + 1)
        ]

    sow_time = now() - timedelta(days=5)
    event = nursery_service.sow_new_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        seed_lot_id=seed_lot.id, seeding_station_id=seeding_station_id, seeding_machine_id=None,
        effective_time=sow_time, note=None,
        trays=[{"carrier_id": c.id, "sown_site_count": normal + abnormal, "seeds_sown": normal + abnormal} for c in carriers],
    )
    germination_service.place_trolley_in_chamber(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        trolley_id=trolley.id, chamber_id=chamber_id, effective_time=sow_time + timedelta(minutes=5), reason=None,
    )
    slots = list(
        db_session.execute(
            text("SELECT id FROM asset_positions WHERE asset_id = :aid AND position_kind = 'slot' ORDER BY code"),
            {"aid": trolley.id},
        ).scalars()
    )

    assignments = sowing_service.list_batch_carriers(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=event.batch_id
    )
    assignment_by_carrier_code = {a.carrier.code: a.id for a in assignments}
    source_assignment_ids = [assignment_by_carrier_code[c.code] for c in carriers]

    germination_time = sow_time + timedelta(days=1)
    entry_time = sow_time + timedelta(days=4)
    entry_ids = []
    for i, carrier in enumerate(carriers):
        germination_service.place_tray(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            tray_id=carrier.id, trolley_id=trolley.id, asset_position_id=slots[i], effective_time=germination_time,
            reason=None,
        )
        germination_outcome_service.record_germination_outcomes(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=event.batch_id,
            client_command_id=uuid.uuid4(), effective_time=germination_time + timedelta(hours=1), note=None,
            outcomes=[
                {
                    "batch_carrier_assignment_id": source_assignment_ids[i], "normal_seedling_count": normal,
                    "abnormal_seedling_count": abnormal, "assessment_complete": True, "note": None,
                }
            ],
        )
        entry = seedling_entry_service.record_seedling_entry(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            batch_carrier_assignment_id=source_assignment_ids[i], destination_seedling_table_id=table_ids[i % len(table_ids)],
            effective_time=entry_time, reason=None,
        )
        entry_ids.append(entry.id)

    batch_id = event.batch_id
    crop_batch_service.transition_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch_id,
        client_command_id=uuid.uuid4(), configured_transition_id=t1.id, effective_time=entry_time + timedelta(hours=1),
        reason=None,
    )

    destination_carriers = (
        [
            carrier_service.register_carrier(
                db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
                **(
                    {"specification_id": destination_specification_id}
                    if destination_specification_id is not None
                    else {"carrier_type_code": transplanting_required_type}
                ),
                code=f"CP-{suffix}-{n:04d}", issued_date=None,
            )
            for n in range(1, 5)
        ]
        if transplanting_required_type is not None
        else []
    )

    from app.models.crop_batch import CropBatch

    batch = db_session.get(CropBatch, batch_id)

    return {
        "crop": crop, "variety": variety, "workflow": workflow,
        "stages": {
            "SEEDING": seeding_stage, "TRANSPLANTING": transplanting_stage, "GROWING": growing_stage,
            "COMPLETE": complete_stage, "PRODUCTION": production_stage_obj,
            "PRODUCTION_TRANSPLANT": production_transplant_stage_obj,
        },
        "transitions": {"t1": t1, "t2": t2, "t3": t3, "t4": t4, "t2b": t2b},
        "batch": batch, "batch_id": batch_id, "seed_lot": seed_lot,
        "source_carriers": carriers, "source_assignment_ids": source_assignment_ids, "entry_ids": entry_ids,
        "entry_time": entry_time, "sow_time": sow_time, "starting": normal + abnormal,
        "destination_carriers": destination_carriers, "intersalads_table_ids": intersalads_table_ids,
        "seedling_table_ids": table_ids,
    }
