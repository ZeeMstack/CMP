"""CMP-016 rollback proofs: a failure partway through the packing
command's single write block must leave no partial finished-goods
receipt behind — and the same Session must remain usable afterward, and a
reused command id retried with a non-colliding payload after a rollback
must still succeed with exactly one receipt."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text

from app.models.finished_goods_ledger_entry import FinishedGoodsLedgerEntry
from app.models.finished_goods_lot import FinishedGoodsLot
from app.services import (
    carrier_service,
    crop_batch_service,
    crop_service,
    harvest_service,
    packing_service,
    production_system_service,
    sowing_service,
    workflow_service,
)
from app.services.errors import DuplicateFinishedGoodsLotCodeError


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
    carrier = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        carrier_type_code="seed_tray", code=f"ST-{suffix}", issued_date=None,
    )
    sowing_service.sow_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
        lines=[{"carrier_id": carrier.id, "seed_lot_id": seed_lot.id, "sown_site_count": 20, "seed_count": 20, "line_note": None}],
    )
    assignments = sowing_service.list_batch_carriers(db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id)
    assignment_id = assignments[0].id

    crop_batch_service.transition_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), configured_transition_id=t1.id, effective_time=_now(), reason=None,
    )

    harvest = harvest_service.record_harvest(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=_now(), produce_lot_code=f"HLOT-{suffix}", note=None,
        source_lines=[{"batch_carrier_assignment_id": assignment_id, "harvested_weight_kg": Decimal("10.000"), "whole_unit_count": None, "note": None}],
    )
    lot_id = db_session.execute(
        text("SELECT id FROM harvested_produce_lots WHERE harvest_event_id = :eid"), {"eid": harvest.id}
    ).scalar_one()

    return {"lot_id": lot_id}


def _assert_session_usable(db_session) -> None:
    db_session.execute(text("SELECT 1")).scalar_one()


@pytest.mark.integration
def test_duplicate_finished_goods_lot_code_rollback_leaves_no_partial_receipt(
    db_session, active_context_with_farm
) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    suffix = uuid.uuid4().hex[:6]
    s = _build_scenario(db_session, tenant, user, farm, suffix=suffix)
    lot_id = s["lot_id"]
    colliding_code = f"COLLIDE-{suffix}"

    packing_service.record_packing(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        effective_time=_now(), finished_goods_lot_code=colliding_code, package_count=3,
        packed_output_weight_kg=Decimal("2.000"), process_loss_weight_kg=Decimal("0"), rejected_weight_kg=Decimal("0"),
        note=None,
        input_lines=[{"harvested_produce_lot_id": lot_id, "consumed_weight_kg": Decimal("2.000"), "consumed_whole_unit_count": None, "note": None}],
    )

    with pytest.raises(DuplicateFinishedGoodsLotCodeError):
        packing_service.record_packing(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            effective_time=_now(), finished_goods_lot_code=colliding_code, package_count=5,
            packed_output_weight_kg=Decimal("3.000"), process_loss_weight_kg=Decimal("0"), rejected_weight_kg=Decimal("0"),
            note=None,
            input_lines=[{"harvested_produce_lot_id": lot_id, "consumed_weight_kg": Decimal("3.000"), "consumed_whole_unit_count": None, "note": None}],
        )

    _assert_session_usable(db_session)

    fg_count = db_session.execute(
        select(func.count()).select_from(FinishedGoodsLot).where(FinishedGoodsLot.tenant_id == tenant.id)
    ).scalar_one()
    assert fg_count == 1, "the failed second packing command must not leave a second finished-goods lot behind"

    receipt_count = db_session.execute(
        select(func.count()).select_from(FinishedGoodsLedgerEntry).where(FinishedGoodsLedgerEntry.tenant_id == tenant.id)
    ).scalar_one()
    assert receipt_count == 1, "the failed second packing command must not leave a partial/orphan receipt behind"


@pytest.mark.integration
def test_reused_command_id_after_rollback_creates_exactly_one_receipt(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    suffix = uuid.uuid4().hex[:6]
    s = _build_scenario(db_session, tenant, user, farm, suffix=suffix)
    lot_id = s["lot_id"]
    command_id = uuid.uuid4()
    colliding_code = f"COLLIDE2-{suffix}"

    packing_service.record_packing(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        effective_time=_now(), finished_goods_lot_code=colliding_code, package_count=1,
        packed_output_weight_kg=Decimal("1.000"), process_loss_weight_kg=Decimal("0"), rejected_weight_kg=Decimal("0"),
        note=None,
        input_lines=[{"harvested_produce_lot_id": lot_id, "consumed_weight_kg": Decimal("1.000"), "consumed_whole_unit_count": None, "note": None}],
    )
    with pytest.raises(DuplicateFinishedGoodsLotCodeError):
        packing_service.record_packing(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=command_id,
            effective_time=_now(), finished_goods_lot_code=colliding_code, package_count=2,
            packed_output_weight_kg=Decimal("2.000"), process_loss_weight_kg=Decimal("0"), rejected_weight_kg=Decimal("0"),
            note=None,
            input_lines=[{"harvested_produce_lot_id": lot_id, "consumed_weight_kg": Decimal("2.000"), "consumed_whole_unit_count": None, "note": None}],
        )
    _assert_session_usable(db_session)

    event = packing_service.record_packing(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=command_id,
        effective_time=_now(), finished_goods_lot_code=f"FRESH-{suffix}", package_count=2,
        packed_output_weight_kg=Decimal("2.000"), process_loss_weight_kg=Decimal("0"), rejected_weight_kg=Decimal("0"),
        note=None,
        input_lines=[{"harvested_produce_lot_id": lot_id, "consumed_weight_kg": Decimal("2.000"), "consumed_whole_unit_count": None, "note": None}],
    )
    receipt_count = db_session.execute(
        select(func.count()).select_from(FinishedGoodsLedgerEntry).where(FinishedGoodsLedgerEntry.packing_event_id == event.id)
    ).scalar_one()
    assert receipt_count == 1
