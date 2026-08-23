"""One-off, disposable seed script for NURSERY-OPS-005B real-browser QA.
TEST-ONLY. Targets ONLY `cmp_qa_005b` (verified by database identity, never
by trusting the connection string alone) -- never the long-lived dev
database `cmp`. Builds the exact fixture the ticket's own §45 specifies,
entirely through real, already-proven services (never ad-hoc invalid raw
SQL), so every row this creates is exactly what the real application would
produce."""

import sys
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

QA_DATABASE_URL = "postgresql+psycopg://cmp:cmp@localhost:5432/cmp_qa_005b"


def main() -> None:
    import app.main  # noqa: F401 -- side effect only: registers the full SQLAlchemy model graph

    engine = create_engine(QA_DATABASE_URL)
    with engine.connect() as conn:
        current_db = conn.execute(text("SELECT current_database()")).scalar_one()
    if current_db != "cmp_qa_005b":
        print(f"refusing to seed database {current_db!r}; expected exactly 'cmp_qa_005b'", file=sys.stderr)
        sys.exit(1)

    from app.services import (
        carrier_service,
        carrier_specification_service,
        crop_service,
        farm_service,
        farm_setup_service,
        membership_service,
        production_system_service,
        tenant_service,
        transplant_service,
        user_service,
        workflow_service,
    )
    from app.schemas.farm_setup import (
        GerminationChamberSetupConfig,
        GreenhouseSetupCreate,
        LeafySetupConfig,
        NurserySectionConfig,
        NurserySetupConfig,
        SpanSetupConfig,
        TableGeneratorConfig,
        ZoneSetupConfig,
    )

    conn = engine.connect()
    session = Session(bind=conn)

    def now():
        return datetime.now(timezone.utc)

    tenant = tenant_service.create_tenant(session, code="qa005b", name="QA 005B Tenant")
    user = user_service.create_user(
        session, oidc_issuer="qa005b", oidc_subject="operator", email="operator@qa005b.example.com",
        display_name="QA Operator",
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    farm = farm_service.create_farm(
        session, tenant_id=tenant.id, actor_user_id=user.id, code="QA-FARM", name="QA Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )

    # --- Nursery Greenhouse with >=2 InterSalads Tables -------------------
    nursery_setup = farm_setup_service.create_greenhouse_setup(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        payload=GreenhouseSetupCreate(
            code="NUR-01", name="QA Nursery", classification="nursery", client_command_id=uuid.uuid4(),
            nursery=NurserySetupConfig(
                seeding_station=NurserySectionConfig(code="SEED-01", name="Seeding Station"),
                germination_chamber=GerminationChamberSetupConfig(
                    code="GC-01", name="Germination Chamber", trolley_capacity=None,
                ),
                seedling_tables=TableGeneratorConfig(code_prefix="SDL", start=1, end=1, pad_width=2, capacity=10),
                intersalads_tables=TableGeneratorConfig(code_prefix="IS", start=1, end=2, pad_width=2, capacity=4),
            ),
        ),
    )

    # --- Leafy Greenhouse: Zone1/Span1/Table A(capacity 1)/Table B(capacity 2) -
    leafy_setup = farm_setup_service.create_greenhouse_setup(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        payload=GreenhouseSetupCreate(
            code="LEAFY-01", name="QA Leafy Production", classification="leafy_greens",
            client_command_id=uuid.uuid4(),
            leafy=LeafySetupConfig(
                zones=[
                    ZoneSetupConfig(
                        code="Z01",
                        spans=[
                            SpanSetupConfig(
                                code="S01",
                                tables=TableGeneratorConfig(code_prefix="TA", start=1, end=1, pad_width=2, capacity=1),
                            )
                        ],
                    ),
                    ZoneSetupConfig(
                        code="Z02",
                        spans=[
                            SpanSetupConfig(
                                code="S02",
                                tables=TableGeneratorConfig(code_prefix="TB", start=1, end=1, pad_width=2, capacity=2),
                            )
                        ],
                    ),
                ]
            ),
        ),
    )

    # --- Crop/Variety/Workflow: SEEDING -> TRANSPLANTING(nursery_cultivation_plate)
    #     -> GROWING -> PRODUCTION_TRANSPLANT(production_cultivation_plate) --------
    crop = crop_service.register_crop(
        session, tenant_id=tenant.id, actor_user_id=user.id, code="ICE", common_name="Iceberg Lettuce",
        scientific_name=None, crop_category="leafy_green",
    )
    variety = crop_service.register_variety(
        session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code="MAM", name="Mamutik",
        supplier_reference=None,
    )
    ps = production_system_service.register_production_system(
        session, tenant_id=tenant.id, actor_user_id=user.id, code="HYDRO", name="Hydroponic NFT", description=None,
    )
    workflow = workflow_service.register_workflow(
        session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, variety_id=variety.id,
        production_system_id=ps.id, code="WF-ICE", name="Iceberg Production Workflow",
    )
    version = workflow_service.create_draft_version(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id
    )
    seeding = workflow_service.add_stage(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="SEEDING", name="Seeding", display_order=0, stage_category="seeding",
        expected_duration_minutes=None, permitted_location_type_code=None,
        required_carrier_type_code="seed_tray", is_start=True, is_terminal=False,
    )
    transplanting = workflow_service.add_stage(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="TRANSPLANTING", name="Transplanting", display_order=1, stage_category="transplanting",
        expected_duration_minutes=None, permitted_location_type_code=None,
        required_carrier_type_code="nursery_cultivation_plate", is_start=False, is_terminal=False,
    )
    growing = workflow_service.add_stage(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="GROWING", name="Growing", display_order=2, stage_category="intermediate",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=False,
    )
    production_transplant = workflow_service.add_stage(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="PRODUCTION_TRANSPLANT", name="Production Transplant", display_order=3, stage_category="transplanting",
        expected_duration_minutes=None, permitted_location_type_code=None,
        required_carrier_type_code="production_cultivation_plate", is_start=False, is_terminal=False,
    )
    complete = workflow_service.add_stage(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="COMPLETE", name="Complete", display_order=4, stage_category="completed",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=True,
    )
    t1 = workflow_service.add_transition(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=seeding.id, to_stage_id=transplanting.id, code="ADV-1", name="Advance 1",
    )
    t2 = workflow_service.add_transition(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=transplanting.id, to_stage_id=growing.id, code="ADV-2", name="Advance 2",
    )
    t2b = workflow_service.add_transition(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=growing.id, to_stage_id=production_transplant.id, code="ADV-2B", name="Advance 2B",
    )
    workflow_service.add_transition(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=production_transplant.id, to_stage_id=complete.id, code="ADV-3", name="Advance 3",
    )
    workflow_service.publish_version(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id
    )

    # --- Carrier specifications ---------------------------------------------
    seed_tray_spec = carrier_specification_service.register_carrier_specification(
        session, tenant_id=tenant.id, actor_user_id=user.id, carrier_type_code="seed_tray",
        code="ST-200", name="200 Cell Seed Tray", length_mm=500, width_mm=300, height_mm=50,
        biological_position_count=200,
    )
    nursery_plate_spec = carrier_specification_service.register_carrier_specification(
        session, tenant_id=tenant.id, actor_user_id=user.id, carrier_type_code="nursery_cultivation_plate",
        code="NP-200", name="200 Hole Nursery Plate", length_mm=500, width_mm=300, height_mm=60,
        biological_position_count=200,
    )
    production_plate_spec = carrier_specification_service.register_carrier_specification(
        session, tenant_id=tenant.id, actor_user_id=user.id, carrier_type_code="production_cultivation_plate",
        code="PP-200", name="200 Hole Production Plate", length_mm=600, width_mm=400, height_mm=80,
        biological_position_count=200,
    )

    # --- Batch with 2 active Nursery Cultivation Plate sources --------------
    from app.services import germination_outcome_service, nursery_service, seedling_entry_service, sowing_service

    seeding_station = session.execute(
        text(
            "SELECT l.id FROM locations l "
            "JOIN location_types lt ON lt.id = l.location_type_id AND lt.code = 'seeding_station' "
            "WHERE l.tenant_id = :tid AND l.farm_id = :fid"
        ),
        {"tid": tenant.id, "fid": farm.id},
    ).scalar_one()
    seed_lot = sowing_service.register_seed_lot(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id,
        variety_id=variety.id, code="LOT-QA-001", supplier_name="QA Supplier", supplier_lot_reference="QA-1",
        received_date=None, expiry_date=None,
    )
    seed_trays = [
        carrier_service.register_carrier(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            specification_id=seed_tray_spec.id, code=f"ST-QA-{i}", issued_date=None,
        )
        for i in (1, 2)
    ]
    sow_time = now() - timedelta(days=20)
    sow_result = nursery_service.sow_new_batch(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        seed_lot_id=seed_lot.id, seeding_station_id=seeding_station, seeding_machine_id=None,
        effective_time=sow_time, note=None,
        trays=[{"carrier_id": t.id, "sown_site_count": 200, "seeds_sown": 200} for t in seed_trays],
    )
    batch_id = sow_result.batch_id
    session.commit()

    # Germinate + create SeedlingEntry for each tray (frozen count 200).
    seedling_table_id = session.execute(
        text(
            "SELECT l.id FROM locations l "
            "JOIN location_types lt ON lt.id = l.location_type_id AND lt.code = 'seedling_table' "
            "WHERE l.tenant_id = :tid AND l.farm_id = :fid LIMIT 1"
        ),
        {"tid": tenant.id, "fid": farm.id},
    ).scalar_one()
    germination_time = sow_time + timedelta(days=5)
    for tray in seed_trays:
        assignment_id = session.execute(
            text(
                "SELECT id FROM batch_carrier_assignments WHERE carrier_id = :cid AND released_effective_time IS NULL"
            ),
            {"cid": tray.id},
        ).scalar_one()
        germination_outcome_service.record_germination_outcomes(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch_id,
            client_command_id=uuid.uuid4(), effective_time=germination_time, note=None,
            outcomes=[
                {
                    "batch_carrier_assignment_id": assignment_id, "normal_seedling_count": 200,
                    "abnormal_seedling_count": 0, "assessment_complete": True, "note": None,
                }
            ],
        )
        seedling_entry_service.record_seedling_entry(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            client_command_id=uuid.uuid4(), batch_carrier_assignment_id=assignment_id,
            destination_seedling_table_id=seedling_table_id,
            effective_time=germination_time + timedelta(hours=1), reason=None,
        )
    session.commit()

    # Transition SEEDING -> TRANSPLANTING.
    from app.services import crop_batch_service

    transplanting_time = germination_time + timedelta(days=2)
    crop_batch_service.transition_stage(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch_id,
        client_command_id=uuid.uuid4(), configured_transition_id=t1.id, effective_time=transplanting_time,
        reason=None,
    )
    session.commit()

    # Two Nursery Cultivation Plates, opened by real Transplants.
    nursery_plates = [
        carrier_service.register_carrier(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            specification_id=nursery_plate_spec.id, code=f"NP-QA-{i}", issued_date=None,
        )
        for i in (1, 2)
    ]
    seed_tray_assignment_ids = [
        session.execute(
            text("SELECT id FROM batch_carrier_assignments WHERE carrier_id = :cid AND released_effective_time IS NULL"),
            {"cid": tray.id},
        ).scalar_one()
        for tray in seed_trays
    ]
    for tray_aid, plate in zip(seed_tray_assignment_ids, nursery_plates):
        transplant_service.record_transplant(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch_id,
            client_command_id=uuid.uuid4(), effective_time=transplanting_time + timedelta(hours=1), note=None,
            source_lines=[
                {
                    "source_assignment_id": tray_aid, "transplant_damage_count": 0, "qc_rejection_count": 0,
                    "sample_count": 0, "other_loss_count": 0, "other_loss_note": None, "note": None,
                }
            ],
            destination_lines=[{"destination_carrier_id": plate.id, "assigned_plant_count": 200, "note": None}],
            allocations=[
                {"source_assignment_id": tray_aid, "destination_carrier_id": plate.id, "allocated_plant_count": 200}
            ],
        )
    session.commit()

    # Transition TRANSPLANTING -> GROWING -> PRODUCTION_TRANSPLANT.
    transfer_ready_time = transplanting_time + timedelta(hours=3)
    crop_batch_service.transition_stage(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch_id,
        client_command_id=uuid.uuid4(), configured_transition_id=t2.id, effective_time=transfer_ready_time,
        reason=None,
    )
    crop_batch_service.transition_stage(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch_id,
        client_command_id=uuid.uuid4(), configured_transition_id=t2b.id, effective_time=transfer_ready_time,
        reason=None,
    )
    session.commit()

    # --- >=3 available Production Cultivation Plates ------------------------
    for i in (1, 2, 3):
        carrier_service.register_carrier(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            specification_id=production_plate_spec.id, code=f"PP-QA-{i}", issued_date=None,
        )
    session.commit()

    print("QA fixture seeded successfully.")
    print(f"tenant_id={tenant.id}")
    print(f"user_id={user.id}")
    print(f"farm_id={farm.id}")
    print(f"batch_id={batch_id}")
    print(f"nursery_greenhouse_id={nursery_setup.greenhouse_id}")
    print(f"leafy_greenhouse_id={leafy_setup.greenhouse_id}")

    session.close()
    conn.close()


if __name__ == "__main__":
    main()
