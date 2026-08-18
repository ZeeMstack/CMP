"""CMP-014 rollback proofs: a failure partway through the harvest command's
single write block must leave no partial receipt behind, in addition to the
CMP-013 guarantees test_harvest_rollback.py already proves — and the same
Session must remain usable afterward."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text

from app.models.harvest_event import HarvestEvent
from app.models.produce_lot_ledger_entry import ProduceLotLedgerEntry
from app.services import (
    carrier_service,
    crop_batch_service,
    crop_service,
    harvest_service,
    production_system_service,
    sowing_service,
    workflow_service,
)
from app.services.errors import DuplicateProduceLotCodeError
from tests.conftest import ensure_seed_tray_specification


def _now():
    return datetime.now(timezone.utc)


def _build_scenario(db_session, tenant, user, farm, *, carrier_count=2, suffix=None):
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
    carriers = [
        carrier_service.register_carrier(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            specification_id=seed_tray_spec.id, code=f"ST-{suffix}-{n:04d}", issued_date=None,
        )
        for n in range(1, carrier_count + 1)
    ]
    sowing_service.sow_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
        lines=[
            {"carrier_id": c.id, "seed_lot_id": seed_lot.id, "sown_site_count": 20, "seed_count": 20, "line_note": None}
            for c in carriers
        ],
    )
    assignments = sowing_service.list_batch_carriers(db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id)
    assignment_by_carrier = {a.carrier.code: a.id for a in assignments}
    assignment_ids = [assignment_by_carrier[c.code] for c in carriers]

    crop_batch_service.transition_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), configured_transition_id=t1.id, effective_time=_now(), reason=None,
    )

    return {"batch": batch, "assignment_ids": assignment_ids}


def _assert_session_usable(db_session) -> None:
    db_session.execute(text("SELECT 1")).scalar_one()


@pytest.mark.integration
def test_duplicate_lot_code_rollback_leaves_no_partial_receipt(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    suffix = uuid.uuid4().hex[:6]
    s = _build_scenario(db_session, tenant, user, farm, carrier_count=2, suffix=suffix)
    aids = s["assignment_ids"]

    colliding_code = f"COLLIDE-{suffix}"
    harvest_service.record_harvest(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), effective_time=_now(), produce_lot_code=colliding_code, note=None,
        source_lines=[{"batch_carrier_assignment_id": aids[0], "harvested_weight_kg": Decimal("1.000"), "whole_unit_count": None, "note": None}],
    )

    with pytest.raises(DuplicateProduceLotCodeError):
        harvest_service.record_harvest(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
            client_command_id=uuid.uuid4(), effective_time=_now(), produce_lot_code=colliding_code, note=None,
            source_lines=[{"batch_carrier_assignment_id": aids[1], "harvested_weight_kg": Decimal("2.000"), "whole_unit_count": None, "note": None}],
        )

    _assert_session_usable(db_session)

    event_count = db_session.execute(
        select(func.count()).select_from(HarvestEvent).where(HarvestEvent.batch_id == s["batch"].id)
    ).scalar_one()
    assert event_count == 1, "the failed second harvest must not leave a second event behind"

    receipt_count = db_session.execute(
        select(func.count()).select_from(ProduceLotLedgerEntry)
        .join(HarvestEvent, HarvestEvent.id == ProduceLotLedgerEntry.harvest_event_id)
        .where(HarvestEvent.batch_id == s["batch"].id)
    ).scalar_one()
    assert receipt_count == 1, "the failed second harvest must not leave a partial/orphan receipt behind"


@pytest.mark.integration
def test_reused_command_id_after_rollback_creates_exactly_one_receipt(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    suffix = uuid.uuid4().hex[:6]
    s = _build_scenario(db_session, tenant, user, farm, carrier_count=2, suffix=suffix)
    aids = s["assignment_ids"]
    command_id = uuid.uuid4()

    colliding_code = f"COLLIDE2-{suffix}"
    harvest_service.record_harvest(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), effective_time=_now(), produce_lot_code=colliding_code, note=None,
        source_lines=[{"batch_carrier_assignment_id": aids[0], "harvested_weight_kg": Decimal("1.000"), "whole_unit_count": None, "note": None}],
    )
    with pytest.raises(DuplicateProduceLotCodeError):
        harvest_service.record_harvest(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
            client_command_id=command_id, effective_time=_now(), produce_lot_code=colliding_code, note=None,
            source_lines=[{"batch_carrier_assignment_id": aids[1], "harvested_weight_kg": Decimal("2.000"), "whole_unit_count": None, "note": None}],
        )
    _assert_session_usable(db_session)

    event = harvest_service.record_harvest(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=command_id, effective_time=_now(), produce_lot_code=f"FRESH-{suffix}", note=None,
        source_lines=[{"batch_carrier_assignment_id": aids[1], "harvested_weight_kg": Decimal("2.000"), "whole_unit_count": None, "note": None}],
    )
    receipt_count = db_session.execute(
        select(func.count()).select_from(ProduceLotLedgerEntry).where(ProduceLotLedgerEntry.harvest_event_id == event.id)
    ).scalar_one()
    assert receipt_count == 1
