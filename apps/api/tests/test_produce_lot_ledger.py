import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models.audit_event import AuditEvent
from app.models.harvested_produce_lot import HarvestedProduceLot
from app.models.produce_lot_ledger_entry import ProduceLotLedgerEntry
from app.services import (
    carrier_service,
    crop_batch_service,
    crop_service,
    harvest_service,
    produce_lot_ledger_service,
    production_system_service,
    sowing_service,
    workflow_service,
)
from app.services.errors import HarvestedProduceLotNotFoundError


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
    carriers = [
        carrier_service.register_carrier(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            carrier_type_code="seed_tray", code=f"ST-{suffix}-{n:04d}", issued_date=None,
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


def _line(aid, weight="10.500", count=None, note=None):
    return {"batch_carrier_assignment_id": aid, "harvested_weight_kg": Decimal(weight), "whole_unit_count": count, "note": note}


def _receipt_row(db_session, produce_lot_id):
    return db_session.execute(
        select(ProduceLotLedgerEntry).where(ProduceLotLedgerEntry.produce_lot_id == produce_lot_id)
    ).scalar_one()


@pytest.mark.integration
def test_harvest_creates_one_deterministic_receipt(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, carrier_count=1)
    aid = s["assignment_ids"][0]
    suffix = uuid.uuid4().hex[:6]

    event = harvest_service.record_harvest(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), effective_time=_now(), produce_lot_code=f"HLOT-{suffix}", note="op note",
        source_lines=[_line(aid, "10.500", count=40)],
    )

    lot = db_session.execute(
        select(HarvestedProduceLot).where(HarvestedProduceLot.harvest_event_id == event.id)
    ).scalar_one()
    receipt = _receipt_row(db_session, lot.id)

    assert receipt.id == lot.id
    assert receipt.produce_lot_id == lot.id
    assert receipt.harvest_event_id == event.id
    assert receipt.tenant_id == lot.tenant_id
    assert receipt.farm_id == lot.farm_id
    assert receipt.entry_kind == "harvest_receipt"
    assert receipt.weight_delta_kg == lot.total_harvested_weight_kg == Decimal("10.500")
    assert receipt.whole_unit_count_delta == lot.total_whole_unit_count == 40
    assert receipt.effective_time == lot.effective_time == event.effective_time
    assert receipt.recorded_time == lot.recorded_at
    assert receipt.actor_user_id == event.actor_user_id == user.id
    # The receipt note is always NULL, even though the harvest command's own
    # note ("op note") is non-null — the event already owns that note.
    assert receipt.note is None


@pytest.mark.integration
def test_receipt_count_null_when_lot_count_null(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, carrier_count=1)
    aid = s["assignment_ids"][0]
    suffix = uuid.uuid4().hex[:6]

    event = harvest_service.record_harvest(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), effective_time=_now(), produce_lot_code=f"NOCOUNT-{suffix}", note=None,
        source_lines=[_line(aid, "1.000")],
    )

    lot = db_session.execute(
        select(HarvestedProduceLot).where(HarvestedProduceLot.harvest_event_id == event.id)
    ).scalar_one()
    receipt = _receipt_row(db_session, lot.id)
    assert lot.total_whole_unit_count is None
    assert receipt.whole_unit_count_delta is None


@pytest.mark.integration
def test_exact_harvest_retry_creates_no_duplicate_receipt(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, carrier_count=1)
    aid = s["assignment_ids"][0]
    suffix = uuid.uuid4().hex[:6]
    command_id = uuid.uuid4()
    effective_time = _now()

    first = harvest_service.record_harvest(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=command_id, effective_time=effective_time, produce_lot_code=f"R-{suffix}", note=None,
        source_lines=[_line(aid, "1.200")],
    )
    retry = harvest_service.record_harvest(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=command_id, effective_time=effective_time, produce_lot_code=f"R-{suffix}", note=None,
        source_lines=[_line(aid, "1.200")],
    )
    assert retry.id == first.id

    receipt_count = db_session.execute(
        select(func.count()).select_from(ProduceLotLedgerEntry).where(ProduceLotLedgerEntry.harvest_event_id == first.id)
    ).scalar_one()
    assert receipt_count == 1, "an exact retry must not create a second receipt"


@pytest.mark.integration
def test_second_harvest_creates_a_second_independent_receipt(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, carrier_count=1)
    aid = s["assignment_ids"][0]
    suffix = uuid.uuid4().hex[:6]

    event1 = harvest_service.record_harvest(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), effective_time=_now(), produce_lot_code=f"A-{suffix}", note=None,
        source_lines=[_line(aid, "1.000")],
    )
    event2 = harvest_service.record_harvest(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), effective_time=_now(), produce_lot_code=f"B-{suffix}", note=None,
        source_lines=[_line(aid, "2.000")],
    )
    receipt_count = db_session.execute(
        select(func.count()).select_from(ProduceLotLedgerEntry)
        .where(ProduceLotLedgerEntry.harvest_event_id.in_([event1.id, event2.id]))
    ).scalar_one()
    assert receipt_count == 2


@pytest.mark.integration
def test_balance_equals_received_when_only_receipt_exists(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, carrier_count=1)
    aid = s["assignment_ids"][0]
    suffix = uuid.uuid4().hex[:6]

    event = harvest_service.record_harvest(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), effective_time=_now(), produce_lot_code=f"BAL-{suffix}", note=None,
        source_lines=[_line(aid, "7.250", count=12)],
    )

    lot = db_session.execute(
        select(HarvestedProduceLot).where(HarvestedProduceLot.harvest_event_id == event.id)
    ).scalar_one()

    balance = produce_lot_ledger_service.get_balance(
        db_session, tenant_id=tenant.id, farm_id=farm.id, produce_lot_id=lot.id
    )
    assert balance.received_weight_kg == balance.available_weight_kg == Decimal("7.250")
    assert balance.received_whole_unit_count == balance.available_whole_unit_count == 12
    assert balance.entry_count == 1
    assert balance.last_effective_time == lot.effective_time


@pytest.mark.integration
def test_get_ledger_lists_the_single_receipt(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, carrier_count=1)
    aid = s["assignment_ids"][0]
    suffix = uuid.uuid4().hex[:6]

    event = harvest_service.record_harvest(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), effective_time=_now(), produce_lot_code=f"LEDG-{suffix}", note=None,
        source_lines=[_line(aid, "4.000")],
    )

    lot = db_session.execute(
        select(HarvestedProduceLot).where(HarvestedProduceLot.harvest_event_id == event.id)
    ).scalar_one()

    ledger = produce_lot_ledger_service.get_ledger(
        db_session, tenant_id=tenant.id, farm_id=farm.id, produce_lot_id=lot.id
    )
    assert len(ledger) == 1
    assert ledger[0].id == lot.id
    assert ledger[0].entry_kind == "harvest_receipt"
    assert ledger[0].produce_lot_code == lot.code
    assert ledger[0].note is None


@pytest.mark.integration
def test_get_balance_unknown_lot_raises_not_found(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    with pytest.raises(HarvestedProduceLotNotFoundError):
        produce_lot_ledger_service.get_balance(
            db_session, tenant_id=tenant.id, farm_id=farm.id, produce_lot_id=uuid.uuid4()
        )


@pytest.mark.integration
def test_harvest_creates_no_additional_audit_event_for_the_receipt(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, carrier_count=1)
    aid = s["assignment_ids"][0]
    suffix = uuid.uuid4().hex[:6]

    before = db_session.execute(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.tenant_id == tenant.id)
    ).scalar_one()
    harvest_service.record_harvest(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), effective_time=_now(), produce_lot_code=f"AUD-{suffix}", note=None,
        source_lines=[_line(aid, "1.000")],
    )
    after = db_session.execute(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.tenant_id == tenant.id)
    ).scalar_one()
    assert after - before == 1, "the receipt must not create a second audit event beyond the existing harvest audit"
