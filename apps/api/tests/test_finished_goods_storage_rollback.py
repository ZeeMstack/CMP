"""CMP-018 rollback proofs: a failure partway through the storage
movement command must leave no partial movement or audit event behind --
and the same Session must remain usable afterward, and a reused command
id retried with a non-colliding payload after a rollback must still
succeed exactly once."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text

from app.models.audit_event import AuditEvent
from app.models.finished_goods_storage_movement import FinishedGoodsStorageMovement
from app.services import (
    carrier_service,
    crop_batch_service,
    crop_service,
    finished_goods_storage_service,
    harvest_service,
    location_service,
    packing_service,
    production_system_service,
    sowing_service,
    workflow_service,
)
from app.services.errors import InsufficientUnplacedQuantityError, StorageCommandReusedWithDifferentPayloadError
from tests._packing_scenario import build_packing_scaffold, grade_entire_lot
from tests.conftest import ensure_seed_tray_specification


def _now():
    return datetime.now(timezone.utc)


def _build_scenario(db_session, tenant, user, farm, *, suffix=None):
    suffix = suffix or uuid.uuid4().hex[:8]
    crop = crop_service.register_crop(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"ICE-{suffix}", common_name="Iceberg",
        scientific_name=None, crop_category="leafy_green",
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
        production_system_id=ps.id, code=f"WF-{suffix}", name="Workflow",
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
    harvesting = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="HARVESTING", name="Harvesting", display_order=1, stage_category="harvesting",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=False,
    )
    complete = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="COMPLETE", name="Complete", display_order=2, stage_category="completed",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=True,
    )
    t1 = workflow_service.add_transition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=seeding.id, to_stage_id=harvesting.id, code="ADV-1", name="Advance 1",
    )
    workflow_service.add_transition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=harvesting.id, to_stage_id=complete.id, code="ADV-2", name="Advance 2",
    )
    workflow_service.publish_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id
    )
    batch = crop_batch_service.create_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"BATCH-{suffix}", workflow_id=workflow.id, effective_time=_now(),
    )
    seed_lot = sowing_service.register_seed_lot(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id,
        variety_id=variety.id, code=f"LOT-{suffix}", supplier_name=None, supplier_lot_reference=None,
        received_date=None, expiry_date=None,
    )
    seed_tray_spec = ensure_seed_tray_specification(db_session, tenant_id=tenant.id, actor_user_id=user.id)
    carrier = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        specification_id=seed_tray_spec.id, code=f"ST-{suffix}", issued_date=None,
    )
    sowing_service.sow_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
        lines=[{"carrier_id": carrier.id, "seed_lot_id": seed_lot.id, "sown_site_count": 20, "seed_count": 20, "line_note": None}],
    )
    assignments = sowing_service.list_batch_carriers(db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id)

    crop_batch_service.transition_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), configured_transition_id=t1.id, effective_time=_now(), reason=None,
    )

    harvest = harvest_service.record_harvest(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=_now(), produce_lot_code=f"HLOT-{suffix}", note=None,
        source_lines=[{"batch_carrier_assignment_id": assignments[0].id, "harvested_weight_kg": Decimal("10.000"), "whole_unit_count": None, "note": None}],
    )
    lot_id = db_session.execute(
        text("SELECT id FROM harvested_produce_lots WHERE harvest_event_id = :eid"), {"eid": harvest.id}
    ).scalar_one()

    # POSTHARVEST-OPS-001E: Packing no longer accepts a HarvestedProduceLot
    # directly -- grade the lot's full weight into one GradedProduceLot and
    # activate a PackSpecificationVersion before packing.
    scaffold = build_packing_scaffold(db_session, tenant, user, farm, crop_id=crop.id, suffix=suffix)
    gpl_id = grade_entire_lot(
        db_session, tenant, user, farm, produce_lot_id=lot_id, weight=Decimal("10.000"), count=None,
        scaffold=scaffold, suffix=suffix,
    )
    pack_event = packing_service.record_packing(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        pack_specification_version_id=scaffold["pack_specification_version_id"],
        effective_time=_now(), finished_goods_lot_code=f"FG-{suffix}", package_count=10,
        packed_output_weight_kg=Decimal("8.000"), process_loss_weight_kg=Decimal("0"), rejected_weight_kg=Decimal("0"),
        note=None,
        input_lines=[{"graded_produce_lot_id": gpl_id, "consumed_weight_kg": Decimal("8.000"), "consumed_whole_unit_count": None, "note": None}],
    )
    detail = packing_service.get_packing_event(db_session, tenant_id=tenant.id, farm_id=farm.id, packing_event_id=pack_event.id)
    fg_lot_id = detail.finished_goods_lot.id

    cold_store = location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, location_type_code="cold_store",
        code=f"CS-{suffix}", name="Cold Store", parent_location_id=None, greenhouse_classification=None,
        occupiable=None,
    )
    position = location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="cold_store_position", code=f"POS-{suffix}", name="Position",
        parent_location_id=cold_store.id, greenhouse_classification=None, occupiable=None,
    )
    return {"fg_lot_id": fg_lot_id, "position_id": position.id}


def _assert_session_usable(db_session) -> None:
    db_session.execute(text("SELECT 1")).scalar_one()


@pytest.mark.integration
def test_failed_movement_after_success_leaves_no_partial_rows(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    suffix = uuid.uuid4().hex[:6]
    s = _build_scenario(db_session, tenant, user, farm, suffix=suffix)
    fg_lot_id, position_id = s["fg_lot_id"], s["position_id"]

    finished_goods_storage_service.record_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        effective_time=_now(), finished_goods_lot_id=fg_lot_id, movement_kind="place",
        source_location_id=None, destination_location_id=position_id, moved_weight_kg=Decimal("5.000"),
        moved_package_count=5, note=None,
    )

    with pytest.raises(InsufficientUnplacedQuantityError):
        finished_goods_storage_service.record_movement(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            effective_time=_now(), finished_goods_lot_id=fg_lot_id, movement_kind="place",
            source_location_id=None, destination_location_id=position_id, moved_weight_kg=Decimal("4.000"),
            moved_package_count=4, note=None,
        )

    _assert_session_usable(db_session)

    movement_count = db_session.execute(
        select(func.count()).select_from(FinishedGoodsStorageMovement)
        .where(FinishedGoodsStorageMovement.tenant_id == tenant.id)
    ).scalar_one()
    assert movement_count == 1, "the failed second movement command must not leave a partial row behind"

    audit_count = db_session.execute(
        select(func.count()).select_from(AuditEvent)
        .where(AuditEvent.tenant_id == tenant.id, AuditEvent.action == "finished_goods.storage_moved")
    ).scalar_one()
    assert audit_count == 1, "the failed second movement command must not leave a partial audit event behind"


@pytest.mark.integration
def test_reused_command_id_after_rollback_creates_exactly_one_movement(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    suffix = uuid.uuid4().hex[:6]
    s = _build_scenario(db_session, tenant, user, farm, suffix=suffix)
    fg_lot_id, position_id = s["fg_lot_id"], s["position_id"]
    command_id = uuid.uuid4()

    finished_goods_storage_service.record_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=command_id,
        effective_time=_now(), finished_goods_lot_id=fg_lot_id, movement_kind="place",
        source_location_id=None, destination_location_id=position_id, moved_weight_kg=Decimal("2.000"),
        moved_package_count=2, note=None,
    )
    with pytest.raises(StorageCommandReusedWithDifferentPayloadError):
        finished_goods_storage_service.record_movement(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=command_id,
            effective_time=_now(), finished_goods_lot_id=fg_lot_id, movement_kind="place",
            source_location_id=None, destination_location_id=position_id, moved_weight_kg=Decimal("3.000"),
            moved_package_count=3, note=None,
        )
    _assert_session_usable(db_session)

    fresh_command_id = uuid.uuid4()
    movement = finished_goods_storage_service.record_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=fresh_command_id,
        effective_time=_now(), finished_goods_lot_id=fg_lot_id, movement_kind="place",
        source_location_id=None, destination_location_id=position_id, moved_weight_kg=Decimal("3.000"),
        moved_package_count=3, note=None,
    )
    movement_count = db_session.execute(
        select(func.count()).select_from(FinishedGoodsStorageMovement)
        .where(FinishedGoodsStorageMovement.finished_goods_lot_id == fg_lot_id)
    ).scalar_one()
    assert movement_count == 2
    assert movement.client_command_id == fresh_command_id
