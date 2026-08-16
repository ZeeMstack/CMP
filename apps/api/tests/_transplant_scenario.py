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


def now():
    return datetime.now(timezone.utc)


def build_transplant_ready_scenario(
    db_session, tenant, user, farm, *, suffix=None, tray_count=4, normal=200, abnormal=0,
    transplanting_required_type="cultivation_plate",
):
    """A Batch with `tray_count` Seed Trays, each sown, germinated, and
    entered through SeedlingEntry (frozen `starting_living_seedling_count =
    normal + abnormal`), workflow already advanced into a TRANSPLANTING-
    category stage. Also returns `destination_carriers` (4 pre-registered
    `transplanting_required_type` carriers, reusable across tests) and the
    configured stage/transition ids `transplant_service` itself checks."""
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
                    code_prefix=f"ST{suffix[:4]}", start=1, end=2, pad_width=2, capacity=tray_count
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
        shelf_count=2, slots_per_shelf=4, shelf_prefix=f"SH-{suffix}-", slot_prefix="SL-",
        shelf_pad_width=2, slot_pad_width=2,
    )

    carriers = [
        carrier_service.register_carrier(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            carrier_type_code="seed_tray", code=f"ST-{suffix}-{n:04d}", issued_date=None,
        )
        for n in range(1, tray_count + 1)
    ]

    sow_time = now() - timedelta(days=5)
    event = nursery_service.sow_new_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        seed_lot_id=seed_lot.id, seeding_station_id=seeding_station_id, seeding_machine_id=None,
        effective_time=sow_time, note=None,
        trays=[{"carrier_id": c.id, "seeds_sown": normal + abnormal} for c in carriers],
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
        germination_service.place_tray_in_slot(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            tray_id=carrier.id, trolley_id=trolley.id, slot_id=slots[i], effective_time=germination_time,
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
                carrier_type_code=transplanting_required_type, code=f"CP-{suffix}-{n:04d}", issued_date=None,
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
            "COMPLETE": complete_stage,
        },
        "transitions": {"t1": t1, "t2": t2, "t3": t3},
        "batch": batch, "batch_id": batch_id, "seed_lot": seed_lot,
        "source_carriers": carriers, "source_assignment_ids": source_assignment_ids, "entry_ids": entry_ids,
        "entry_time": entry_time, "sow_time": sow_time, "starting": normal + abnormal,
        "destination_carriers": destination_carriers,
    }
