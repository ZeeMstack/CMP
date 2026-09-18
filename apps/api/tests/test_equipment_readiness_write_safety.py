"""N02A: focused proof that Sowing, Germination Trolley placement, and
Transplant destination validation authoritatively re-check Equipment
Readiness inside their own write transaction -- a stale "available"
selector result, or a direct service/API call, can no longer allocate a
tracked resource whose current readiness is not READY. See
docs/domain/EQUIPMENT_READINESS_MODEL.md and
`equipment_readiness_service.require_ready_for_allocation`.

Six cases, matching the ticket's own required regression list exactly:
1. Sowing rejects a Seed Tray in MAINTENANCE.
2. Sowing rejects a tracked Seed Tray in UNKNOWN (never assessed).
3. Germination rejects a Trolley that moved READY -> MAINTENANCE before
   the placement command.
4. Transplant rejects a non-ready destination Carrier, atomically (no
   partial destination assignment/occupancy/audit row survives).
5. A readiness-untracked carrier type (`grow_cube`) remains unaffected.
6. An exact replay of an already-committed command still returns its
   original result, even though the underlying equipment's readiness has
   since changed.
"""
import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models.asset_position import AssetPosition
from app.models.audit_event import AuditEvent
from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.transplant_event import TransplantEvent
from app.schemas.farm_setup import (
    GerminationChamberSetupConfig,
    GreenhouseSetupCreate,
    NurserySectionConfig,
    NurserySetupConfig,
)
from app.services import (
    asset_service,
    carrier_service,
    crop_batch_service,
    crop_service,
    equipment_readiness_service,
    farm_service,
    farm_setup_service,
    germination_service,
    intervines_transplant_service,
    membership_service,
    production_system_service,
    sowing_service,
    tenant_service,
    transplant_service,
    user_service,
    workflow_service,
)
from app.services.errors import (
    EquipmentReadinessNotReadyError,
    EquipmentReadinessNotTrackedError,
    SowingValidationError,
)
from tests._transplant_scenario import build_transplant_ready_scenario
from tests.conftest import ensure_seed_tray_specification, mark_readiness_ready


def _now_utc():
    return datetime.now(timezone.utc)


def _build_sowing_scenario(db_session, tenant, user, farm, *, suffix=None):
    """Minimal Seeding-stage workflow + batch + one unmarked (UNKNOWN)
    seed_tray Carrier -- deliberately never calls `mark_readiness_ready`,
    since these tests need full control over the Carrier's readiness."""
    suffix = suffix or uuid.uuid4().hex[:8]
    crop = crop_service.register_crop(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"ICE-{suffix}",
        common_name="Iceberg Lettuce", scientific_name=None, crop_category="leafy_green",
    )
    variety = crop_service.register_variety(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"MAM-{suffix}",
        name="Mamutik RZ", supplier_reference=None,
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
    seeding = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="SEEDING", name="Seeding", display_order=0, stage_category="seeding",
        expected_duration_minutes=None, permitted_location_type_code=None,
        required_carrier_type_code="seed_tray", is_start=True, is_terminal=False,
    )
    complete = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="COMPLETE", name="Complete", display_order=1, stage_category="completed",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=True,
    )
    workflow_service.add_transition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=seeding.id, to_stage_id=complete.id, code="ADVANCE", name="Advance",
    )
    workflow_service.publish_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id
    )
    batch = crop_batch_service.create_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"BATCH-{suffix}", workflow_id=workflow.id, effective_time=_now_utc(),
    )
    seed_lot = sowing_service.register_seed_lot(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id,
        variety_id=variety.id, code=f"LOT-{suffix}", supplier_name=None, supplier_lot_reference=None,
        received_date=None, expiry_date=None,
    )
    seed_tray_spec = ensure_seed_tray_specification(db_session, tenant_id=tenant.id, actor_user_id=user.id)
    carrier = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        specification_id=seed_tray_spec.id, code=f"ST-{suffix}-0001", issued_date=None,
    )
    return {"batch": batch, "seed_lot": seed_lot, "carrier": carrier}


def _sow_one(db_session, tenant, user, farm, s, *, client_command_id=None):
    return sowing_service.sow_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=client_command_id or uuid.uuid4(), effective_time=_now_utc(), note=None,
        lines=[
            {
                "carrier_id": s["carrier"].id, "seed_lot_id": s["seed_lot"].id, "sown_site_count": 200,
                "seed_count": 200, "line_note": None,
            }
        ],
    )


# =====================================================================
# 1-2. Sowing rejects a non-ready destination Seed Tray
# =====================================================================


@pytest.mark.integration
def test_sowing_rejects_maintenance_seed_tray(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_sowing_scenario(db_session, tenant, user, farm)
    state = equipment_readiness_service.get_readiness_for_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=s["carrier"].id
    )
    equipment_readiness_service.send_to_maintenance(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
        client_command_id=uuid.uuid4(), note="damaged roller",
    )

    with pytest.raises(EquipmentReadinessNotReadyError):
        _sow_one(db_session, tenant, user, farm, s)

    # No SowingEvent, no BatchCarrierAssignment -- the readiness rejection
    # must not leave a partial write behind.
    assert db_session.execute(
        select(func.count()).select_from(BatchCarrierAssignment).where(
            BatchCarrierAssignment.carrier_id == s["carrier"].id
        )
    ).scalar_one() == 0


@pytest.mark.integration
def test_sowing_rejects_unknown_seed_tray(db_session, active_context_with_farm) -> None:
    """A freshly-registered Seed Tray starts `unknown`, never `ready` --
    UNKNOWN != READY is a frozen rule with no exception (docs/domain/
    EQUIPMENT_READINESS_MODEL.md)."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_sowing_scenario(db_session, tenant, user, farm)
    state = equipment_readiness_service.get_readiness_for_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=s["carrier"].id
    )
    assert state.current_state == "unknown"

    with pytest.raises(EquipmentReadinessNotReadyError):
        _sow_one(db_session, tenant, user, farm, s)


# =====================================================================
# 3. Germination rejects a Trolley that moved READY -> MAINTENANCE before
#    the placement command
# =====================================================================


@pytest.mark.integration
def test_germination_rejects_trolley_moved_to_maintenance_before_placement(
    db_session, active_context_with_farm
) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    suffix = uuid.uuid4().hex[:8]

    s = _build_sowing_scenario(db_session, tenant, user, farm, suffix=suffix)
    mark_readiness_ready(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, carrier_id=s["carrier"].id
    )
    _sow_one(db_session, tenant, user, farm, s)

    setup = farm_setup_service.create_greenhouse_setup(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        payload=GreenhouseSetupCreate(
            code=f"NUR-{suffix}", name="Nursery", classification="nursery", client_command_id=uuid.uuid4(),
            nursery=NurserySetupConfig(
                seeding_station=NurserySectionConfig(code=f"SEED-{suffix}"),
                germination_chamber=GerminationChamberSetupConfig(code=f"GC-{suffix}", trolley_capacity=1),
            ),
        ),
    )
    structure = farm_setup_service.get_greenhouse_structure(
        db_session.connection(), tenant_id=tenant.id, farm_id=farm.id, greenhouse_id=setup.greenhouse_id,
    )
    chamber_id = structure.nursery_germination_chamber.id

    trolley = asset_service.register_asset(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        asset_type_code="germination_trolley", code=f"GT-{suffix}", name="Trolley", commissioned_date=None,
    )
    asset_service.generate_positions(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, asset_id=trolley.id,
        shelf_count=1, slots_per_shelf=1, shelf_prefix=f"SH-{suffix}-", slot_prefix="SL-",
        shelf_pad_width=2, slot_pad_width=2,
    )
    level_id = db_session.execute(
        select(AssetPosition.id).where(AssetPosition.asset_id == trolley.id, AssetPosition.position_kind == "slot")
    ).scalar_one()

    # The Trolley is READY, exactly what an operator's "available trolleys"
    # selector would have shown when the placement form was opened.
    mark_readiness_ready(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, asset_id=trolley.id
    )
    germination_service.place_trolley_in_chamber(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        trolley_id=trolley.id, chamber_id=chamber_id, effective_time=_now_utc(), reason=None,
    )

    # Before the placement command actually arrives, the Trolley is sent to
    # Maintenance -- the exact "stale form" race this ticket closes.
    trolley_state = equipment_readiness_service.get_readiness_for_asset(
        db_session, tenant_id=tenant.id, farm_id=farm.id, asset_id=trolley.id
    )
    equipment_readiness_service.send_to_maintenance(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=trolley_state.id,
        client_command_id=uuid.uuid4(), note="roller bearing failure",
    )

    with pytest.raises(EquipmentReadinessNotReadyError):
        germination_service.place_tray(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            client_command_id=uuid.uuid4(), tray_id=s["carrier"].id, trolley_id=trolley.id,
            asset_position_id=level_id, effective_time=_now_utc(), reason=None,
        )


# =====================================================================
# 4. Transplant rejects a non-ready destination Carrier, atomically
# =====================================================================


@pytest.mark.integration
def test_transplant_rejects_non_ready_destination_atomically(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = build_transplant_ready_scenario(db_session, tenant, user, farm, tray_count=1)

    destination = s["destination_carriers"][0]
    dest_state = equipment_readiness_service.get_readiness_for_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=destination.id
    )
    equipment_readiness_service.send_to_maintenance(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=dest_state.id,
        client_command_id=uuid.uuid4(), note="cracked plate",
    )

    source_assignment_id = s["source_assignment_ids"][0]
    audit_count_before = db_session.execute(select(func.count()).select_from(AuditEvent)).scalar_one()

    with pytest.raises(EquipmentReadinessNotReadyError):
        transplant_service.record_transplant(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch_id"],
            client_command_id=uuid.uuid4(), effective_time=s["entry_time"] + timedelta(hours=2), note=None,
            source_lines=[
                {
                    "source_assignment_id": source_assignment_id, "transplant_damage_count": 0,
                    "qc_rejection_count": 0, "sample_count": 0, "other_loss_count": 0, "other_loss_note": None,
                    "note": None,
                }
            ],
            destination_lines=[{"destination_carrier_id": destination.id, "assigned_plant_count": 200, "note": None}],
            allocations=[
                {
                    "source_assignment_id": source_assignment_id, "destination_carrier_id": destination.id,
                    "allocated_plant_count": 200,
                }
            ],
        )

    # Atomic: no TransplantEvent, no new destination BatchCarrierAssignment,
    # the source assignment stays unreleased, and no new audit row.
    assert db_session.execute(select(func.count()).select_from(TransplantEvent)).scalar_one() == 0
    assert db_session.execute(
        select(func.count()).select_from(BatchCarrierAssignment).where(
            BatchCarrierAssignment.carrier_id == destination.id
        )
    ).scalar_one() == 0
    source_assignment = db_session.get(BatchCarrierAssignment, source_assignment_id)
    assert source_assignment.released_effective_time is None
    audit_count_after = db_session.execute(select(func.count()).select_from(AuditEvent)).scalar_one()
    assert audit_count_after == audit_count_before


# =====================================================================
# 5. A readiness-untracked carrier type remains unaffected
# =====================================================================


@pytest.mark.integration
def test_untracked_carrier_type_unaffected_by_readiness_gate(db_session, active_context_with_farm) -> None:
    """`grow_cube` (VINES-OPS-001A) is deliberately NOT readiness-tracked
    (docs/domain/EQUIPMENT_READINESS_MODEL.md) -- InterVines Transplant
    must keep succeeding without ANY readiness setup for its destination
    pool, proving the gate never fabricates a requirement for an untracked
    type."""
    tenant, user, _headers, farm = active_context_with_farm
    s = build_transplant_ready_scenario(
        db_session, tenant, user, farm, tray_count=1, transplanting_required_type="grow_cube",
        intervines_table_count=1, intervines_table_capacity=10,
    )
    grow_cubes = carrier_service.bulk_register_carriers(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        carrier_type_code="grow_cube", code_prefix=f"GC-{uuid.uuid4().hex[:6]}-", start=1, end=5, pad_width=2,
    )
    for gc in grow_cubes:
        with pytest.raises(EquipmentReadinessNotTrackedError):
            equipment_readiness_service.get_readiness_for_carrier(
                db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=gc.id
            )

    result = intervines_transplant_service.record_intervines_transplant(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch_id"],
        client_command_id=uuid.uuid4(), effective_time=s["entry_time"] + timedelta(hours=2), note=None,
        source_assignment_id=s["source_assignment_ids"][0], plant_count=5,
        destination_location_id=s["intervines_table_ids"][0], grow_cube_specification_id=None,
    )
    assert result.plant_count == 5


# =====================================================================
# 6. Exact replay still returns the original result despite a later
#    readiness change
# =====================================================================


@pytest.mark.integration
def test_exact_replay_unaffected_by_later_readiness_change(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    suffix = uuid.uuid4().hex[:8]
    s = _build_sowing_scenario(db_session, tenant, user, farm, suffix=suffix)
    mark_readiness_ready(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, carrier_id=s["carrier"].id
    )

    setup = farm_setup_service.create_greenhouse_setup(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        payload=GreenhouseSetupCreate(
            code=f"NUR-{suffix}", name="Nursery", classification="nursery", client_command_id=uuid.uuid4(),
            nursery=NurserySetupConfig(
                seeding_station=NurserySectionConfig(code=f"SEED-{suffix}"),
                germination_chamber=GerminationChamberSetupConfig(code=f"GC-{suffix}", trolley_capacity=1),
            ),
        ),
    )
    structure = farm_setup_service.get_greenhouse_structure(
        db_session.connection(), tenant_id=tenant.id, farm_id=farm.id, greenhouse_id=setup.greenhouse_id,
    )
    chamber_id = structure.nursery_germination_chamber.id

    trolley = asset_service.register_asset(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        asset_type_code="germination_trolley", code=f"GT-{suffix}", name="Trolley", commissioned_date=None,
    )
    asset_service.generate_positions(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, asset_id=trolley.id,
        shelf_count=1, slots_per_shelf=1, shelf_prefix=f"SH-{suffix}-", slot_prefix="SL-",
        shelf_pad_width=2, slot_pad_width=2,
    )
    level_id = db_session.execute(
        select(AssetPosition.id).where(AssetPosition.asset_id == trolley.id, AssetPosition.position_kind == "slot")
    ).scalar_one()

    mark_readiness_ready(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, asset_id=trolley.id
    )
    _sow_one(db_session, tenant, user, farm, s)
    germination_service.place_trolley_in_chamber(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        trolley_id=trolley.id, chamber_id=chamber_id, effective_time=_now_utc(), reason=None,
    )

    ccid = uuid.uuid4()
    effective_time = _now_utc()
    first = germination_service.place_tray(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=ccid,
        tray_id=s["carrier"].id, trolley_id=trolley.id, asset_position_id=level_id,
        effective_time=effective_time, reason=None,
    )

    # The Trolley is now sent to Maintenance -- a later readiness change
    # must never turn a valid replay of the already-committed command into
    # a new failure (frozen rule 11).
    trolley_state = equipment_readiness_service.get_readiness_for_asset(
        db_session, tenant_id=tenant.id, farm_id=farm.id, asset_id=trolley.id
    )
    equipment_readiness_service.send_to_maintenance(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=trolley_state.id,
        client_command_id=uuid.uuid4(), note="scheduled service",
    )

    replay = germination_service.place_tray(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=ccid,
        tray_id=s["carrier"].id, trolley_id=trolley.id, asset_position_id=level_id,
        effective_time=effective_time, reason=None,
    )
    assert replay.id == first.id


# =====================================================================
# 7. Concurrency: the allocation command and a readiness transition
#    genuinely serialize on the readiness row -- no deadlock, and the
#    final state is always internally consistent with whichever one
#    actually committed first.
# =====================================================================


def _build_committed_ready_sowing_scenario(test_engine, *, suffix):
    """Mirrors `test_sowing_concurrency.py`'s own `_build_committed_scenario`
    shape -- committed setup data via a dedicated connection, carrier
    brought to READY via the real lifecycle so the race below starts from
    a genuinely allocation-eligible state."""
    conn = test_engine.connect()
    session = Session(bind=conn)
    tenant = tenant_service.create_tenant(session, code=f"n02a-race-{suffix}", name="N02A Race Tenant")
    user = user_service.create_user(
        session, oidc_issuer="n02a-race", oidc_subject=suffix, email=f"n02a-race-{suffix}@example.com",
        display_name="N02A Race User",
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    farm = farm_service.create_farm(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="N02A Race Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    crop = crop_service.register_crop(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"crop-{suffix}", common_name="Iceberg",
        scientific_name=None, crop_category="leafy_green",
    )
    variety = crop_service.register_variety(
        session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"var-{suffix}",
        name="Mamutik", supplier_reference=None,
    )
    ps = production_system_service.register_production_system(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"ps-{suffix}", name="Nursery Tray",
        description=None,
    )
    workflow = workflow_service.register_workflow(
        session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, variety_id=variety.id,
        production_system_id=ps.id, code=f"wf-{suffix}", name="Race Workflow",
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
    complete = workflow_service.add_stage(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="COMPLETE", name="Complete", display_order=1, stage_category="completed",
        expected_duration_minutes=None, permitted_location_type_code=None,
        required_carrier_type_code=None, is_start=False, is_terminal=True,
    )
    workflow_service.add_transition(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=seeding.id, to_stage_id=complete.id, code="ADVANCE", name="Advance",
    )
    workflow_service.publish_version(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id
    )
    batch = crop_batch_service.create_batch(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"BATCH-{suffix}", workflow_id=workflow.id, effective_time=_now_utc(),
    )
    seed_lot = sowing_service.register_seed_lot(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id,
        variety_id=variety.id, code=f"lot-{suffix}", supplier_name=None, supplier_lot_reference=None,
        received_date=None, expiry_date=None,
    )
    seed_tray_spec = ensure_seed_tray_specification(session, tenant_id=tenant.id, actor_user_id=user.id)
    carrier = carrier_service.register_carrier(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        specification_id=seed_tray_spec.id, code=f"ST-{suffix}-0001", issued_date=None,
    )
    ready_state = mark_readiness_ready(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, carrier_id=carrier.id
    )
    result = {
        "tenant_id": tenant.id, "user_id": user.id, "farm_id": farm.id, "batch_id": batch.id,
        "seed_lot_id": seed_lot.id, "carrier_id": carrier.id, "state_id": ready_state.id,
    }
    session.close()
    conn.close()
    return result


def _cleanup_committed_ready_sowing_scenario(test_engine, tenant_id) -> None:
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET session_replication_role = replica"))
        for table in (
            "sowing_event_lines", "batch_carrier_assignments", "sowing_events", "equipment_readiness_states",
            "cleaning_events", "seed_lots", "carrier_specifications", "carriers", "batch_stage_runs",
            "batch_stage_transitions", "crop_batches", "workflow_transitions", "workflow_stages",
            "workflow_versions", "workflows", "production_systems", "varieties", "crops", "audit_events",
            "farms", "tenant_memberships",
        ):
            conn.execute(text(f"DELETE FROM {table} WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})
        conn.execute(text("SET session_replication_role = DEFAULT"))
        trans.commit()
    finally:
        conn.close()


@pytest.mark.integration
def test_allocation_and_readiness_transition_serialize_no_deadlock(test_engine) -> None:
    """Proves the lock-order fix this ticket makes to `retire` (Carrier/
    Asset row locked BEFORE its EquipmentReadinessState row, matching
    `require_ready_for_allocation`'s own callers): a concurrent Sowing
    command and a concurrent `retire` targeting the SAME Carrier's
    readiness must serialize cleanly -- never deadlock -- and the DB ends
    up in exactly one of two internally-consistent states depending on
    which committed first."""
    suffix = uuid.uuid4().hex[:10]
    scenario = _build_committed_ready_sowing_scenario(test_engine, suffix=suffix)
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}

    def sow_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            event = sowing_service.sow_batch(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
                effective_time=_now_utc(), note=None,
                lines=[
                    {
                        "carrier_id": scenario["carrier_id"], "seed_lot_id": scenario["seed_lot_id"],
                        "sown_site_count": 200, "seed_count": 200, "line_note": None,
                    }
                ],
            )
            results["sow"] = ("ok", event.id)
        except EquipmentReadinessNotReadyError as exc:
            results["sow"] = ("not_ready", str(exc))
        except SowingValidationError as exc:
            # `retire` also flips the Carrier's own registry `status` to
            # `retired` in the same commit -- if `retire` wins the race,
            # Sowing's own pre-existing `status == 'active'` check (which
            # runs before the readiness check) is an equally correct,
            # equally serialized rejection of the same underlying fact.
            results["sow"] = ("not_ready", str(exc))
        except Exception as exc:  # pragma: no cover - surfaced via assertion below
            results["sow"] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    def retire_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            equipment_readiness_service.retire(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], state_id=scenario["state_id"], client_command_id=uuid.uuid4(),
                note="retired mid-race",
            )
            results["retire"] = ("ok", None)
        except Exception as exc:  # pragma: no cover - surfaced via assertion below
            results["retire"] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_sow = threading.Thread(target=sow_worker)
    t_retire = threading.Thread(target=retire_worker)
    t_sow.start()
    t_retire.start()
    t_sow.join(timeout=15)
    t_retire.join(timeout=15)

    try:
        assert not t_sow.is_alive() and not t_retire.is_alive()
        # Never a deadlock/timeout, never an unexpected exception.
        assert results["retire"][0] == "ok", results
        assert results["sow"][0] in ("ok", "not_ready"), results

        with test_engine.connect() as verify_conn:
            final_state = verify_conn.execute(
                text("SELECT current_state FROM equipment_readiness_states WHERE id = :id"),
                {"id": scenario["state_id"]},
            ).scalar_one()
            assignment_count = verify_conn.execute(
                text("SELECT count(*) FROM batch_carrier_assignments WHERE carrier_id = :cid"),
                {"cid": scenario["carrier_id"]},
            ).scalar_one()
        assert final_state == "retired"
        # Internally consistent either way: Sowing won the race (committed
        # before retire) -> one assignment exists despite the carrier now
        # showing retired; retire won -> Sowing correctly saw non-ready and
        # created nothing.
        if results["sow"][0] == "ok":
            assert assignment_count == 1
        else:
            assert assignment_count == 0
    finally:
        _cleanup_committed_ready_sowing_scenario(test_engine, scenario["tenant_id"])
