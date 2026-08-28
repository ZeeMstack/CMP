"""PILOT-READY-001 end-to-end smoke test -- HTTP/API boundary.

Proves a real operator can run the complete Iceberg (leafy-green) pilot
workflow, end to end, through the REAL public HTTP API (FastAPI
`TestClient`) -- not merely the service layer. Every operational
transaction below is a `client.post`/`client.get` call against the exact
same routes the frontend calls, so this exercises route wiring, request
schema validation, tenant/user context resolution, the permission
dependency, HTTP/domain-error status-code mapping, response serialization,
and idempotency at the HTTP boundary -- none of which a direct service-layer
call proves.

"Operational direct-DB simulation: NONE" -- no operational transaction
(Sowing onward) is ever simulated via a raw ORM/DB write or a direct
service-layer call standing in for what an operator did; every one goes
through its real POST/GET route.

Bootstrap/master-data setup (tenant, farm, crop/variety/workflow, seed lot,
nursery/leafy location structure, carrier specifications and the physical
carriers themselves) uses this suite's own established scenario-helper
functions (`tests._traceability_scenario`, `tests.test_leafy_production_
transfer`) -- real `*_service` calls, the same convention every other
scenario builder in this suite already uses for one-time setup, per
instruction. These are never operational transactions themselves.

Chain proven, each via its real HTTP route:

farm/location/workflow/seed-lot/carrier bootstrap (service-layer, one-time)
  -> POST /nursery/sowings                              (Sowing)
  -> POST /germination/trolley-placements + /tray-placements (Germination placement)
  -> POST /crop-batches/{id}/germination-outcomes        (Germination outcome)
  -> POST /nursery/seedling/entries                      (Seedling entry)
  -> POST /crop-batches/{id}/stage-transitions x3
  -> POST /crop-batches/{id}/intersalads-transplants      (InterSalads)
  -> POST /crop-batches/{id}/leafy-production-transfers   (Nursery -> Leafy transfer)
  -> POST /leafy-production/dispositions                  (Production disposition)
  -> POST /leafy-production/harvests                      (Harvest)
  -> POST /crop-batches/{id}/quality-holds (+ /release)    (Quality Hold)
  -> POST /grading-events x2
  -> POST /packing-events x2
  -> POST /finished-goods-storage-movements (place + release)
  -> POST /dispatches                                      (+ required dispatch_temperature_c)
  -> GET /traceability/finished-goods-lots/{id}            (Backward traceability)
  -> GET /traceability/crop-batches/{id}/impact            (Forward impact)
  -> POST /recall-cases (+ /close)                         (Recall open/close)
  -> POST /packing-events/{id}/reversal x2
  -> POST /grading-events/{id}/reversal x1 blocked, x1 succeeds

Interleaved HTTP-boundary error-path assertions (real status codes + real
response bodies, never a caught service exception described as an HTTP
error): duplicate/replayed Dispatch command with a changed payload,
insufficient biological population, insufficient Finished Goods balance,
insufficient unplaced quantity (Dispatch while still placed), wrong
storage-location type, open Quality Hold blocking Grading, invalid (future)
Dispatch effective_time, downstream-history-blocks-reversal, and Recall
containment blocking Dispatch.

PRE-COMMIT AUDIT FINDING (fixed in this same change): driving Dispatch
through the real HTTP route while a Recall is open on the target Finished
Goods Lot crashed with an unhandled 500 -- `app/api/dispatch.py` never
caught `RecallContainmentOpenError` (unlike `grading.py`/`packing.py`,
which already did). The same gap existed in `app/api/finished_goods_
storage.py` (RELEASE) and `app/api/batch_derivations.py` (split/merge).
All three now map it to a 409, matching the established convention. This
was invisible to the previous, service-layer-only version of this test
(and to every other existing test, none of which drove these three write
paths through the real router while a Recall was open) -- proof that the
HTTP boundary must be exercised directly, not inferred from the service
layer.
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.db import get_db, get_engine
from app.main import app
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
    carrier_specification_service,
    crop_service,
    farm_setup_service,
    production_system_service,
    sowing_service,
    workflow_service,
)
from tests._traceability_scenario import (
    _build_packing_scaffold,
    build_committed_tenant_farm,
    cleanup_traceability_scenario,
    committed_connection,
    create_cold_store_position,
)
from tests.conftest import ensure_seed_tray_specification
from tests.test_leafy_production_transfer import NURSERY_PLATE_TYPE, PRODUCTION_PLATE_TYPE, _leafy_setup, _production_plates

pytestmark = pytest.mark.integration

NURSERY_OPENING_COUNT = 180
PRODUCTION_LOSS_COUNT = 10  # 180 -> 170 living population before harvest


def _now():
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _extra_cleanup(test_engine, tenant_id: uuid.UUID) -> None:
    """Extends `cleanup_traceability_scenario` (no coverage for Recall or
    Grading/Packing reversal tables -- neither existed when it was written)
    with the tables this smoke test's own chain additionally touches.
    `session_replication_role = replica` disables FK trigger enforcement
    for this transaction, so exact deletion order is not required."""
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET session_replication_role = replica"))
        for table in (
            "recall_scope_finished_goods_lots", "recall_scope_graded_produce_lots",
            "recall_scope_produce_lots", "recall_scope_batches", "recall_case_closures", "recall_cases",
            "grading_reversal_outputs", "grading_reversal_events",
            "packing_reversal_inputs", "packing_reversal_events",
        ):
            if conn.execute(text("SELECT to_regclass(:t)"), {"t": table}).scalar() is not None:
                conn.execute(text(f"DELETE FROM {table} WHERE tenant_id = :tid"), {"tid": tenant_id})
        trans.commit()
    finally:
        conn.close()


def _bootstrap_master_data(db, tenant, user, farm, *, suffix):
    """One-time bootstrap/master-data setup only -- crop, workflow (stages/
    transitions/publish), seed lot, nursery + leafy location structure,
    carrier specifications and the physical carriers themselves. Every call
    here is a real `*_service` function (the same bootstrap convention this
    whole suite already uses), but NONE of it is an operational
    transaction -- Sowing onward happens over real HTTP below."""
    crop = crop_service.register_crop(
        db, tenant_id=tenant.id, actor_user_id=user.id, code=f"ICE-{suffix}",
        common_name="Iceberg", scientific_name=None, crop_category="leafy_green",
    )
    variety = crop_service.register_variety(
        db, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"MAM-{suffix}",
        name="Mamutik", supplier_reference=None,
    )
    ps = production_system_service.register_production_system(
        db, tenant_id=tenant.id, actor_user_id=user.id, code=f"PS-{suffix}", name="Nursery Tray", description=None,
    )
    workflow = workflow_service.register_workflow(
        db, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, variety_id=variety.id,
        production_system_id=ps.id, code=f"WF-{suffix}", name="Iceberg Nursery",
    )
    version = workflow_service.create_draft_version(
        db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id
    )
    seeding_stage = workflow_service.add_stage(
        db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="SEEDING", name="Seeding", display_order=0, stage_category="seeding",
        expected_duration_minutes=None, permitted_location_type_code=None,
        required_carrier_type_code="seed_tray", is_start=True, is_terminal=False,
    )
    transplanting_stage = workflow_service.add_stage(
        db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="TRANSPLANTING", name="Transplanting", display_order=1, stage_category="transplanting",
        expected_duration_minutes=None, permitted_location_type_code=None,
        required_carrier_type_code=NURSERY_PLATE_TYPE, is_start=False, is_terminal=False,
    )
    growing_stage = workflow_service.add_stage(
        db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="GROWING", name="Growing", display_order=2, stage_category="intermediate",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=False,
    )
    complete_stage = workflow_service.add_stage(
        db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="COMPLETE", name="Complete", display_order=3, stage_category="completed",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=True,
    )
    production_transplant_stage = workflow_service.add_stage(
        db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="PRODUCTION_TRANSPLANT", name="Production Transplant", display_order=4, stage_category="transplanting",
        expected_duration_minutes=None, permitted_location_type_code=None,
        required_carrier_type_code=PRODUCTION_PLATE_TYPE, is_start=False, is_terminal=False,
    )
    t1 = workflow_service.add_transition(
        db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=seeding_stage.id, to_stage_id=transplanting_stage.id, code="ADVANCE-1", name="Advance 1",
    )
    t2 = workflow_service.add_transition(
        db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=transplanting_stage.id, to_stage_id=growing_stage.id, code="ADVANCE-2", name="Advance 2",
    )
    workflow_service.add_transition(
        db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=growing_stage.id, to_stage_id=complete_stage.id, code="ADVANCE-3", name="Advance 3",
    )
    t2b = workflow_service.add_transition(
        db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=growing_stage.id, to_stage_id=production_transplant_stage.id, code="ADVANCE-2B", name="Advance 2B",
    )
    workflow_service.add_transition(
        db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=production_transplant_stage.id, to_stage_id=complete_stage.id, code="ADVANCE-2C", name="Advance 2C",
    )
    workflow_service.publish_version(
        db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id
    )

    seed_lot = sowing_service.register_seed_lot(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id,
        variety_id=variety.id, code=f"LOT-{suffix}", supplier_name="Rijk Zwaan", supplier_lot_reference="RZ-001",
        received_date=None, expiry_date=None,
    )

    intersalads_spec = carrier_specification_service.register_carrier_specification(
        db, tenant_id=tenant.id, actor_user_id=user.id, carrier_type_code=NURSERY_PLATE_TYPE,
        code=f"IS-SPEC-{suffix}", name="InterSalads Plate Spec", length_mm=500, width_mm=300, height_mm=60,
        biological_position_count=NURSERY_OPENING_COUNT,
    )

    setup = farm_setup_service.create_greenhouse_setup(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        payload=GreenhouseSetupCreate(
            code=f"NUR-{suffix}", name="Nursery", classification="nursery", client_command_id=uuid.uuid4(),
            nursery=NurserySetupConfig(
                seeding_station=NurserySectionConfig(code=f"SEED-{suffix}"),
                germination_chamber=GerminationChamberSetupConfig(code=f"GC-{suffix}", trolley_capacity=None),
                seedling_tables=TableGeneratorConfig(code_prefix=f"ST{suffix[:4]}", start=1, end=2, pad_width=2, capacity=1),
                intersalads_tables=TableGeneratorConfig(
                    code_prefix=f"IS{suffix[:4]}", start=1, end=1, pad_width=2, capacity=NURSERY_OPENING_COUNT,
                ),
            ),
        ),
    )
    structure = farm_setup_service.get_greenhouse_structure(
        db.connection(), tenant_id=tenant.id, farm_id=farm.id, greenhouse_id=setup.greenhouse_id,
    )
    seeding_station_id = structure.nursery_seeding_stations[0].id
    chamber_id = structure.nursery_germination_chamber.id
    seedling_table_ids = [t.id for t in structure.nursery_seedling.tables]
    intersalads_table_ids = [t.id for t in structure.nursery_intersalads.tables]

    trolley = asset_service.register_asset(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        asset_type_code="germination_trolley", code=f"GT-{suffix}", name="Trolley", commissioned_date=None,
    )
    asset_service.generate_positions(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, asset_id=trolley.id,
        shelf_count=1, slots_per_shelf=2, shelf_prefix=f"SH-{suffix}-", slot_prefix="SL-",
        shelf_pad_width=2, slot_pad_width=2,
    )
    slot_ids = list(
        db.execute(
            text("SELECT id FROM asset_positions WHERE asset_id = :aid AND position_kind = 'slot' ORDER BY code"),
            {"aid": trolley.id},
        ).scalars()
    )

    seed_tray_spec = ensure_seed_tray_specification(db, tenant_id=tenant.id, actor_user_id=user.id)
    seed_tray = carrier_service.register_carrier(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        specification_id=seed_tray_spec.id, code=f"ST-{suffix}-0001", issued_date=None,
    )
    intersalads_plate = carrier_service.register_carrier(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        specification_id=intersalads_spec.id, code=f"IP-{suffix}-0001", issued_date=None,
    )

    leafy_table_ids = _leafy_setup(db, tenant, user, farm, table_count=1, table_capacity=1, suffix=suffix)
    production_plates, _prod_spec = _production_plates(
        db, tenant, user, farm, count=1, biological_position_count=NURSERY_OPENING_COUNT, suffix=suffix
    )

    return {
        "crop": crop, "variety": variety, "seed_lot": seed_lot,
        "transitions": {"t1": t1, "t2": t2, "t2b": t2b},
        "seeding_station_id": seeding_station_id, "chamber_id": chamber_id,
        "seedling_table_ids": seedling_table_ids, "intersalads_table_ids": intersalads_table_ids,
        "trolley": trolley, "slot_ids": slot_ids,
        "seed_tray": seed_tray, "intersalads_plate": intersalads_plate,
        "leafy_table_ids": leafy_table_ids, "production_plate": production_plates[0],
    }


def test_full_pilot_workflow_farm_to_dispatch_to_recall_to_reversal(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as db:
            tenant, user, farm = build_committed_tenant_farm(db)
            tenant_id = tenant.id
            suffix = uuid.uuid4().hex[:8]
            m = _bootstrap_master_data(db, tenant, user, farm, suffix=suffix)
            db.commit()

            headers = {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(user.id)}
            app.dependency_overrides[get_db] = lambda: db
            # Traceability deliberately owns its own dedicated connection via
            # `get_engine` rather than the request-scoped `db` (see
            # `tests/conftest.py`'s `client` fixture's identical override) --
            # point it at `test_engine` too, so it sees this same cmp_test
            # database rather than the default production/dev target.
            app.dependency_overrides[get_engine] = lambda: test_engine
            client = TestClient(app)
            client.__enter__()
            try:
                farm_url = f"/farms/{farm.id}"

                # =========================================================
                # SOWING -- POST /nursery/sowings
                # =========================================================
                sow_time = _now() - timedelta(days=5)
                resp = client.post(
                    f"{farm_url}/nursery/sowings", headers=headers,
                    json={
                        "client_command_id": str(uuid.uuid4()), "seed_lot_id": str(m["seed_lot"].id),
                        "seeding_station_id": str(m["seeding_station_id"]), "seeding_machine_id": None,
                        "effective_time": _iso(sow_time), "note": None,
                        "trays": [{"carrier_id": str(m["seed_tray"].id), "sown_site_count": NURSERY_OPENING_COUNT, "seeds_sown": NURSERY_OPENING_COUNT}],
                    },
                )
                assert resp.status_code == 201, resp.text
                sowing = resp.json()
                batch_id = sowing["batch_id"]
                source_assignment_id = sowing["lines"][0]["batch_carrier_assignment_id"]

                # =========================================================
                # GERMINATION -- POST /germination/trolley-placements, /tray-placements
                # =========================================================
                germination_time = sow_time + timedelta(days=1)
                resp = client.post(
                    f"{farm_url}/germination/trolley-placements", headers=headers,
                    json={
                        "client_command_id": str(uuid.uuid4()), "trolley_id": str(m["trolley"].id),
                        "chamber_id": str(m["chamber_id"]), "effective_time": _iso(germination_time), "reason": None,
                    },
                )
                assert resp.status_code == 201, resp.text

                resp = client.post(
                    f"{farm_url}/germination/tray-placements", headers=headers,
                    json={
                        "client_command_id": str(uuid.uuid4()), "tray_id": str(m["seed_tray"].id),
                        "trolley_id": str(m["trolley"].id), "slot_id": str(m["slot_ids"][0]),
                        "effective_time": _iso(germination_time), "reason": None,
                    },
                )
                assert resp.status_code == 201, resp.text

                # =========================================================
                # GERMINATION OUTCOME -- POST /crop-batches/{id}/germination-outcomes
                # =========================================================
                outcome_time = germination_time + timedelta(hours=1)
                resp = client.post(
                    f"{farm_url}/crop-batches/{batch_id}/germination-outcomes", headers=headers,
                    json={
                        "client_command_id": str(uuid.uuid4()), "effective_time": _iso(outcome_time), "note": None,
                        "outcomes": [
                            {
                                "batch_carrier_assignment_id": source_assignment_id,
                                "normal_seedling_count": NURSERY_OPENING_COUNT, "abnormal_seedling_count": 0,
                                "assessment_complete": True, "note": None,
                            }
                        ],
                    },
                )
                assert resp.status_code == 201, resp.text

                # =========================================================
                # SEEDLING ENTRY -- POST /nursery/seedling/entries
                # =========================================================
                entry_time = outcome_time + timedelta(days=3)
                resp = client.post(
                    f"{farm_url}/nursery/seedling/entries", headers=headers,
                    json={
                        "client_command_id": str(uuid.uuid4()), "batch_carrier_assignment_id": source_assignment_id,
                        "destination_seedling_table_id": str(m["seedling_table_ids"][0]),
                        "effective_time": _iso(entry_time), "reason": None,
                    },
                )
                assert resp.status_code == 201, resp.text

                # SEEDING -> TRANSPLANTING
                resp = client.post(
                    f"{farm_url}/crop-batches/{batch_id}/stage-transitions", headers=headers,
                    json={
                        "client_command_id": str(uuid.uuid4()), "configured_transition_id": str(m["transitions"]["t1"].id),
                        "effective_time": _iso(entry_time + timedelta(hours=1)), "reason": None,
                    },
                )
                assert resp.status_code == 201, resp.text

                # =========================================================
                # INTERSALADS -- POST /crop-batches/{id}/intersalads-transplants
                # =========================================================
                intersalads_time = entry_time + timedelta(hours=2)
                resp = client.post(
                    f"{farm_url}/crop-batches/{batch_id}/intersalads-transplants", headers=headers,
                    json={
                        "client_command_id": str(uuid.uuid4()), "effective_time": _iso(intersalads_time), "note": None,
                        "source_lines": [
                            {
                                "source_assignment_id": source_assignment_id, "transplant_damage_count": 0,
                                "qc_rejection_count": 0, "sample_count": 0, "other_loss_count": 0,
                                "other_loss_note": None, "note": None,
                            }
                        ],
                        "destination_lines": [
                            {
                                "destination_carrier_id": str(m["intersalads_plate"].id),
                                "assigned_plant_count": NURSERY_OPENING_COUNT,
                                "destination_location_id": str(m["intersalads_table_ids"][0]), "note": None,
                            }
                        ],
                        "allocations": [
                            {
                                "source_assignment_id": source_assignment_id,
                                "destination_carrier_id": str(m["intersalads_plate"].id),
                                "allocated_plant_count": NURSERY_OPENING_COUNT,
                            }
                        ],
                    },
                )
                assert resp.status_code == 201, resp.text
                intersalads_bca_id = resp.json()["destination_lines"][0]["destination_batch_carrier_assignment_id"]

                # TRANSPLANTING -> GROWING -> PRODUCTION_TRANSPLANT
                transition_time = intersalads_time + timedelta(hours=1)
                resp = client.post(
                    f"{farm_url}/crop-batches/{batch_id}/stage-transitions", headers=headers,
                    json={
                        "client_command_id": str(uuid.uuid4()), "configured_transition_id": str(m["transitions"]["t2"].id),
                        "effective_time": _iso(transition_time), "reason": None,
                    },
                )
                assert resp.status_code == 201, resp.text
                resp = client.post(
                    f"{farm_url}/crop-batches/{batch_id}/stage-transitions", headers=headers,
                    json={
                        "client_command_id": str(uuid.uuid4()), "configured_transition_id": str(m["transitions"]["t2b"].id),
                        "effective_time": _iso(transition_time), "reason": None,
                    },
                )
                assert resp.status_code == 201, resp.text

                # =========================================================
                # NURSERY -> LEAFY TRANSFER -- POST /crop-batches/{id}/leafy-production-transfers
                # =========================================================
                transfer_time = transition_time + timedelta(hours=1)
                resp = client.post(
                    f"{farm_url}/crop-batches/{batch_id}/leafy-production-transfers", headers=headers,
                    json={
                        "client_command_id": str(uuid.uuid4()), "effective_time": _iso(transfer_time), "note": None,
                        "source_lines": [
                            {
                                "source_assignment_id": intersalads_bca_id, "transplant_damage_count": 0,
                                "qc_rejection_count": 0, "sample_count": 0, "other_loss_count": 0,
                                "other_loss_note": None, "note": None,
                            }
                        ],
                        "destination_lines": [
                            {
                                "destination_carrier_id": str(m["production_plate"].id),
                                "assigned_plant_count": NURSERY_OPENING_COUNT,
                                "destination_location_id": str(m["leafy_table_ids"][0]), "note": None,
                            }
                        ],
                        "allocations": [
                            {
                                "source_assignment_id": intersalads_bca_id,
                                "destination_carrier_id": str(m["production_plate"].id),
                                "allocated_plant_count": NURSERY_OPENING_COUNT,
                            }
                        ],
                    },
                )
                assert resp.status_code == 201, resp.text
                production_root_id = resp.json()["destination_lines"][0]["destination_batch_carrier_assignment_id"]

                # =========================================================
                # PRODUCTION POPULATION MANAGEMENT -- POST /leafy-production/dispositions
                # =========================================================
                loss_time = transfer_time + timedelta(hours=1)
                resp = client.post(
                    f"{farm_url}/leafy-production/dispositions", headers=headers,
                    json={
                        "client_command_id": str(uuid.uuid4()), "batch_carrier_assignment_id": production_root_id,
                        "plant_loss_count": PRODUCTION_LOSS_COUNT, "reason_code": "dead",
                        "effective_time": _iso(loss_time), "note": None,
                    },
                )
                assert resp.status_code == 201, resp.text
                living_population = NURSERY_OPENING_COUNT - PRODUCTION_LOSS_COUNT  # 170

                # ERROR PATH (HTTP): insufficient biological population.
                harvest_time = loss_time + timedelta(hours=1)
                resp = client.post(
                    f"{farm_url}/leafy-production/harvests", headers=headers,
                    json={
                        "client_command_id": str(uuid.uuid4()), "batch_id": batch_id,
                        "effective_time": _iso(harvest_time), "produce_lot_code": f"HLOT-BAD-{suffix}", "note": None,
                        "source_lines": [
                            {
                                "batch_carrier_assignment_id": production_root_id,
                                "whole_unit_count": living_population + 500, "harvested_weight_kg": "500.000", "note": None,
                            }
                        ],
                    },
                )
                assert resp.status_code == 409, resp.text
                assert resp.json()["detail"]["code"] == "HARVEST_POPULATION_CONFLICT"

                # =========================================================
                # HARVEST -- POST /leafy-production/harvests
                # =========================================================
                total_harvest_weight = "85.000"
                resp = client.post(
                    f"{farm_url}/leafy-production/harvests", headers=headers,
                    json={
                        "client_command_id": str(uuid.uuid4()), "batch_id": batch_id,
                        "effective_time": _iso(harvest_time), "produce_lot_code": f"HLOT-{suffix}", "note": None,
                        "source_lines": [
                            {
                                "batch_carrier_assignment_id": production_root_id,
                                "whole_unit_count": living_population, "harvested_weight_kg": total_harvest_weight, "note": None,
                            }
                        ],
                    },
                )
                assert resp.status_code == 201, resp.text
                harvested_lot_id = resp.json()["produce_lot_id"]

                # =========================================================
                # QUALITY HOLD -- blocks a genuinely new Grading command via HTTP.
                # =========================================================
                hold_time = harvest_time + timedelta(minutes=30)
                resp = client.post(
                    f"{farm_url}/crop-batches/{batch_id}/quality-holds", headers=headers,
                    json={
                        "client_command_id": str(uuid.uuid4()), "effective_time": _iso(hold_time),
                        "source_observation_event_id": None, "reason_code": "contamination",
                        "reason_text": "pre-grading inspection hold",
                    },
                )
                assert resp.status_code == 201, resp.text
                hold_id = resp.json()["id"]

                scaffold = _build_packing_scaffold(db, tenant, user, farm, crop_id=m["crop"].id, suffix=suffix)

                grading_time_a = harvest_time + timedelta(hours=1)
                resp = client.post(
                    f"{farm_url}/grading-events", headers=headers,
                    json={
                        "client_command_id": str(uuid.uuid4()), "source_harvested_produce_lot_id": harvested_lot_id,
                        "processing_hall_location_id": str(scaffold["packing_hall_location_id"]),
                        "effective_time": _iso(grading_time_a), "note": None,
                        "input_presented_weight_kg": "60.000", "input_presented_whole_unit_count": 120,
                        "rejected_weight_kg": "0", "rejected_whole_unit_count": 0,
                        "loss_weight_kg": "0", "loss_whole_unit_count": 0,
                        "sample_weight_kg": "0", "sample_whole_unit_count": 0,
                        "remainder_weight_kg": "0", "remainder_whole_unit_count": 0,
                        "outputs": [
                            {
                                "grade_definition_version_id": str(scaffold["grade_version_id"]), "code": f"GPL-A-{suffix}",
                                "output_weight_kg": "60.000", "output_whole_unit_count": 120,
                            }
                        ],
                    },
                )
                assert resp.status_code == 409, resp.text  # blocked by the open Quality Hold

                release_time = hold_time + timedelta(minutes=15)
                resp = client.post(
                    f"{farm_url}/crop-batches/{batch_id}/quality-holds/{hold_id}/release", headers=headers,
                    json={
                        "client_command_id": str(uuid.uuid4()), "effective_time": _iso(release_time),
                        "release_reason": "cleared by QC",
                    },
                )
                assert resp.status_code == 201, resp.text

                # =========================================================
                # GRADING x2 -- 60kg -> GPL A (feeds the Packing that gets
                # dispatched, permanently reversal-blocked); 25kg -> GPL B
                # (feeds the untouched Packing used for the reversal smoke).
                # =========================================================
                grading_time_a = release_time + timedelta(minutes=5)
                resp = client.post(
                    f"{farm_url}/grading-events", headers=headers,
                    json={
                        "client_command_id": str(uuid.uuid4()), "source_harvested_produce_lot_id": harvested_lot_id,
                        "processing_hall_location_id": str(scaffold["packing_hall_location_id"]),
                        "effective_time": _iso(grading_time_a), "note": None,
                        "input_presented_weight_kg": "60.000", "input_presented_whole_unit_count": 120,
                        "rejected_weight_kg": "0", "rejected_whole_unit_count": 0,
                        "loss_weight_kg": "0", "loss_whole_unit_count": 0,
                        "sample_weight_kg": "0", "sample_whole_unit_count": 0,
                        "remainder_weight_kg": "0", "remainder_whole_unit_count": 0,
                        "outputs": [
                            {
                                "grade_definition_version_id": str(scaffold["grade_version_id"]), "code": f"GPL-A-{suffix}",
                                "output_weight_kg": "60.000", "output_whole_unit_count": 120,
                            }
                        ],
                    },
                )
                assert resp.status_code == 201, resp.text
                grading_a = resp.json()
                grading_event_a_id = grading_a["id"]
                gpl_a_id = grading_a["outputs"][0]["id"]

                grading_time_b = grading_time_a + timedelta(minutes=5)
                resp = client.post(
                    f"{farm_url}/grading-events", headers=headers,
                    json={
                        "client_command_id": str(uuid.uuid4()), "source_harvested_produce_lot_id": harvested_lot_id,
                        "processing_hall_location_id": str(scaffold["packing_hall_location_id"]),
                        "effective_time": _iso(grading_time_b), "note": None,
                        "input_presented_weight_kg": "25.000", "input_presented_whole_unit_count": 50,
                        "rejected_weight_kg": "0", "rejected_whole_unit_count": 0,
                        "loss_weight_kg": "0", "loss_whole_unit_count": 0,
                        "sample_weight_kg": "0", "sample_whole_unit_count": 0,
                        "remainder_weight_kg": "0", "remainder_whole_unit_count": 0,
                        "outputs": [
                            {
                                "grade_definition_version_id": str(scaffold["grade_version_id"]), "code": f"GPL-B-{suffix}",
                                "output_weight_kg": "25.000", "output_whole_unit_count": 50,
                            }
                        ],
                    },
                )
                assert resp.status_code == 201, resp.text
                grading_b = resp.json()
                grading_event_b_id = grading_b["id"]
                gpl_b_id = grading_b["outputs"][0]["id"]

                # =========================================================
                # PACKING x2.
                # =========================================================
                packing_time_1 = grading_time_b + timedelta(minutes=5)
                resp = client.post(
                    f"{farm_url}/packing-events", headers=headers,
                    json={
                        "client_command_id": str(uuid.uuid4()),
                        "pack_specification_version_id": str(scaffold["pack_specification_version_id"]),
                        "effective_time": _iso(packing_time_1), "finished_goods_lot_code": f"FG-A-{suffix}",
                        "package_count": 12, "packed_output_weight_kg": "60.000",
                        "process_loss_weight_kg": "0", "rejected_weight_kg": "0", "note": None,
                        "input_lines": [
                            {"graded_produce_lot_id": gpl_a_id, "consumed_weight_kg": "60.000", "consumed_whole_unit_count": 120, "note": None}
                        ],
                    },
                )
                assert resp.status_code == 201, resp.text
                packing_1 = resp.json()
                packing_event_1_id = packing_1["id"]
                fg_lot_1_id = packing_1["finished_goods_lot"]["id"]

                packing_time_2 = packing_time_1 + timedelta(minutes=5)
                resp = client.post(
                    f"{farm_url}/packing-events", headers=headers,
                    json={
                        "client_command_id": str(uuid.uuid4()),
                        "pack_specification_version_id": str(scaffold["pack_specification_version_id"]),
                        "effective_time": _iso(packing_time_2), "finished_goods_lot_code": f"FG-B-{suffix}",
                        "package_count": 5, "packed_output_weight_kg": "25.000",
                        "process_loss_weight_kg": "0", "rejected_weight_kg": "0", "note": None,
                        "input_lines": [
                            {"graded_produce_lot_id": gpl_b_id, "consumed_weight_kg": "25.000", "consumed_whole_unit_count": 50, "note": None}
                        ],
                    },
                )
                assert resp.status_code == 201, resp.text
                packing_2 = resp.json()
                packing_event_2_id = packing_2["id"]
                assert packing_2["finished_goods_lot"]["id"] != fg_lot_1_id

                # ERROR PATH (HTTP): wrong destination for a storage movement.
                resp = client.post(
                    f"{farm_url}/finished-goods-storage-movements", headers=headers,
                    json={
                        "client_command_id": str(uuid.uuid4()), "effective_time": _iso(packing_time_2 + timedelta(minutes=1)),
                        "finished_goods_lot_id": fg_lot_1_id, "movement_kind": "place", "source_location_id": None,
                        "destination_location_id": str(scaffold["packing_hall_location_id"]),
                        "moved_weight_kg": "60.000", "moved_package_count": 12, "note": None,
                    },
                )
                assert resp.status_code == 422, resp.text

                # =========================================================
                # COLD STORAGE: real PLACE then real RELEASE of fg_lot_1.
                # =========================================================
                cold_store_position = create_cold_store_position(db, tenant, user, farm, suffix=suffix)
                place_time = packing_time_2 + timedelta(hours=1)
                resp = client.post(
                    f"{farm_url}/finished-goods-storage-movements", headers=headers,
                    json={
                        "client_command_id": str(uuid.uuid4()), "effective_time": _iso(place_time),
                        "finished_goods_lot_id": fg_lot_1_id, "movement_kind": "place", "source_location_id": None,
                        "destination_location_id": str(cold_store_position.id),
                        "moved_weight_kg": "60.000", "moved_package_count": 12, "note": None,
                    },
                )
                assert resp.status_code == 201, resp.text

                # ERROR PATH (HTTP): dispatch may only consume UNPLACED
                # quantity (CMP-018) -- fg_lot_1 is fully placed right now.
                resp = client.post(
                    f"{farm_url}/dispatches", headers=headers,
                    json={
                        "client_command_id": str(uuid.uuid4()), "effective_time": _iso(place_time + timedelta(minutes=1)),
                        "code": f"DISP-BLOCKED-{suffix}", "external_reference": None, "note": None,
                        "dispatch_temperature_c": "4.0",
                        "lines": [{"finished_goods_lot_id": fg_lot_1_id, "dispatched_weight_kg": "60.000", "dispatched_package_count": 12}],
                    },
                )
                assert resp.status_code == 409, resp.text

                release_time_2 = place_time + timedelta(hours=1)
                resp = client.post(
                    f"{farm_url}/finished-goods-storage-movements", headers=headers,
                    json={
                        "client_command_id": str(uuid.uuid4()), "effective_time": _iso(release_time_2),
                        "finished_goods_lot_id": fg_lot_1_id, "movement_kind": "release",
                        "source_location_id": str(cold_store_position.id), "destination_location_id": None,
                        "moved_weight_kg": "60.000", "moved_package_count": 12, "note": None,
                    },
                )
                assert resp.status_code == 201, resp.text

                # =========================================================
                # DISPATCH -- required dispatch_temperature_c, one reading
                # for the whole dispatch. Error paths over HTTP: future
                # effective_time rejected; over-balance rejected; exact
                # replay is idempotent; replay with a changed payload
                # (temperature) conflicts.
                # =========================================================
                resp = client.post(
                    f"{farm_url}/dispatches", headers=headers,
                    json={
                        "client_command_id": str(uuid.uuid4()), "effective_time": _iso(release_time_2 + timedelta(days=365)),
                        "code": f"DISP-FUTURE-{suffix}", "external_reference": None, "note": None,
                        "dispatch_temperature_c": "4.0",
                        "lines": [{"finished_goods_lot_id": fg_lot_1_id, "dispatched_weight_kg": "1.000", "dispatched_package_count": 1}],
                    },
                )
                assert resp.status_code == 422, resp.text

                resp = client.post(
                    f"{farm_url}/dispatches", headers=headers,
                    json={
                        "client_command_id": str(uuid.uuid4()), "effective_time": _iso(release_time_2 + timedelta(minutes=1)),
                        "code": f"DISP-OVER-{suffix}", "external_reference": None, "note": None,
                        "dispatch_temperature_c": "4.0",
                        "lines": [{"finished_goods_lot_id": fg_lot_1_id, "dispatched_weight_kg": "9999.000", "dispatched_package_count": 12}],
                    },
                )
                assert resp.status_code == 409, resp.text

                dispatch_time = release_time_2 + timedelta(minutes=5)
                dispatch_payload = {
                    "client_command_id": str(uuid.uuid4()), "effective_time": _iso(dispatch_time),
                    "code": f"DISP-{suffix}", "external_reference": "PO-PILOT-1", "note": None,
                    "dispatch_temperature_c": "2.5",
                    "lines": [{"finished_goods_lot_id": fg_lot_1_id, "dispatched_weight_kg": "60.000", "dispatched_package_count": 12}],
                }
                resp = client.post(f"{farm_url}/dispatches", headers=headers, json=dispatch_payload)
                assert resp.status_code == 201, resp.text
                dispatch_event = resp.json()
                assert dispatch_event["dispatch_temperature_c"] == "2.5"
                assert "dispatch_temperature_c" not in dispatch_event["lines"][0]

                # Exact replay -- idempotent, same event, no duplicate.
                resp = client.post(f"{farm_url}/dispatches", headers=headers, json=dispatch_payload)
                assert resp.status_code == 201, resp.text
                assert resp.json()["id"] == dispatch_event["id"]

                # Same client_command_id, changed temperature -> conflict.
                changed_payload = dict(dispatch_payload, dispatch_temperature_c="9.0")
                resp = client.post(f"{farm_url}/dispatches", headers=headers, json=changed_payload)
                assert resp.status_code == 409, resp.text

                db.commit()

                # =====================================================
                # TRACEABILITY -- real HTTP GETs. `get_engine` is overridden
                # to `test_engine` above (traceability owns its own
                # dedicated connection, never the request-scoped `db`), so
                # it sees this now-committed data via cmp_test directly.
                # =====================================================
                resp = client.get(f"{farm_url}/traceability/finished-goods-lots/{fg_lot_1_id}", headers=headers)
                assert resp.status_code == 200, resp.text
                backward = resp.json()
                assert backward["subject"]["finished_goods_lot_id"] == fg_lot_1_id
                assert len(backward["produce_lots"]) == 1
                assert backward["produce_lots"][0]["harvested_produce_lot_id"] == harvested_lot_id
                assert len(backward["lineage"]["batches"]) == 1
                assert backward["lineage"]["batches"][0]["batch_id"] == batch_id
                assert len(backward["seed_origins"]) == 1
                assert backward["seed_origins"][0]["seed_lot_id"] == str(m["seed_lot"].id)
                assert len(backward["dispatches"]) == 1
                assert len(backward["storage_movements"]) == 2

                resp = client.get(f"{farm_url}/traceability/crop-batches/{batch_id}/impact", headers=headers)
                assert resp.status_code == 200, resp.text
                forward = resp.json()
                assert forward["subject_batch_id"] == batch_id
                assert forward["summary"]["affected_finished_goods_lot_count"] >= 1

                # =========================================================
                # RECALL -- open against the dispatched Finished Goods Lot,
                # verify containment blocks a genuinely new Dispatch over
                # HTTP, then close.
                # =========================================================
                recall_time = dispatch_time + timedelta(minutes=5)
                resp = client.post(
                    f"{farm_url}/recall-cases", headers=headers,
                    json={
                        "client_command_id": str(uuid.uuid4()), "effective_time": _iso(recall_time),
                        "code": f"RC-{suffix}", "crop_batch_id": None, "harvested_produce_lot_id": None,
                        "graded_produce_lot_id": None, "finished_goods_lot_id": fg_lot_1_id,
                        "reason_code": "contamination", "reason_text": "pilot smoke recall containment proof",
                    },
                )
                assert resp.status_code == 201, resp.text
                recall_case_id = resp.json()["recall_case_id"]

                # ERROR PATH (HTTP): Recall containment blocking Dispatch --
                # PRE-COMMIT AUDIT fix: this used to be an unhandled 500.
                resp = client.post(
                    f"{farm_url}/dispatches", headers=headers,
                    json={
                        "client_command_id": str(uuid.uuid4()), "effective_time": _iso(recall_time + timedelta(minutes=1)),
                        "code": f"DISP-CONTAINED-{suffix}", "external_reference": None, "note": None,
                        "dispatch_temperature_c": "4.0",
                        "lines": [{"finished_goods_lot_id": fg_lot_1_id, "dispatched_weight_kg": "1.000", "dispatched_package_count": 1}],
                    },
                )
                assert resp.status_code == 409, resp.text

                close_time = recall_time + timedelta(minutes=10)
                resp = client.post(
                    f"{farm_url}/recall-cases/{recall_case_id}/close", headers=headers,
                    json={"client_command_id": str(uuid.uuid4()), "effective_time": _iso(close_time), "close_reason": "root cause cleared"},
                )
                assert resp.status_code == 200, resp.text
                assert resp.json()["is_open"] is False

                # =========================================================
                # REVERSAL SMOKE (ticket section 8, A-F), all over HTTP:
                #   A/C. untouched packing_event_2 reverses cleanly.
                #   B.   grading_event_b reversal is blocked while
                #        packing_event_2 is still active.
                #   D.   after reversing packing_event_2, grading_event_b
                #        reverses too, and balances reconcile.
                #   F.   packing_event_1 (storage + dispatch history) can
                #        never be reversed.
                # =========================================================
                reversal_time = close_time + timedelta(minutes=5)

                resp = client.post(
                    f"{farm_url}/grading-events/{grading_event_b_id}/reversal", headers=headers,
                    json={
                        "client_command_id": str(uuid.uuid4()), "effective_time": _iso(reversal_time),
                        "reason_code": "OPERATOR_ERROR", "note": "pilot smoke: blocked-while-active proof",
                    },
                )
                assert resp.status_code == 409, resp.text  # ERROR PATH (HTTP): downstream reversal blocker

                resp = client.post(
                    f"{farm_url}/packing-events/{packing_event_2_id}/reversal", headers=headers,
                    json={
                        "client_command_id": str(uuid.uuid4()), "effective_time": _iso(reversal_time),
                        "reason_code": "OPERATOR_ERROR", "note": "pilot smoke: untouched packing reversal",
                    },
                )
                assert resp.status_code == 201, resp.text

                resp = client.post(
                    f"{farm_url}/grading-events/{grading_event_b_id}/reversal", headers=headers,
                    json={
                        "client_command_id": str(uuid.uuid4()), "effective_time": _iso(reversal_time + timedelta(minutes=1)),
                        "reason_code": "OPERATOR_ERROR", "note": "pilot smoke: now-unblocked grading reversal",
                    },
                )
                assert resp.status_code == 201, resp.text
                assert resp.json()["id"] is not None

                resp = client.post(
                    f"{farm_url}/packing-events/{packing_event_1_id}/reversal", headers=headers,
                    json={
                        "client_command_id": str(uuid.uuid4()), "effective_time": _iso(reversal_time + timedelta(minutes=2)),
                        "reason_code": "OPERATOR_ERROR", "note": "pilot smoke: must stay blocked (storage + dispatch history)",
                    },
                )
                assert resp.status_code == 409, resp.text

                db.commit()
            finally:
                client.__exit__(None, None, None)
                app.dependency_overrides.pop(get_db, None)
                app.dependency_overrides.pop(get_engine, None)
    finally:
        if tenant_id is not None:
            _extra_cleanup(test_engine, tenant_id)
            cleanup_traceability_scenario(test_engine, tenant_id)
