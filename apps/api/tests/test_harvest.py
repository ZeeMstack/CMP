import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models.harvest_event import HarvestEvent
from app.models.harvested_produce_lot import HarvestedProduceLot
from app.schemas.harvest import MAX_WHOLE_UNIT_COUNT, HarvestEventCreate, HarvestSourceLineIn, canonical_decimal_str
from app.services import (
    crop_batch_service,
    crop_service,
    harvest_service,
    production_system_service,
    quality_hold_service,
    sowing_service,
    workflow_service,
)
from app.services import carrier_service
from app.services.errors import (
    CropBatchClosedError,
    DuplicateProduceLotCodeError,
    HarvestCommandReusedWithDifferentPayloadError,
    HarvestValidationError,
    QualityHoldOpenError,
)
from tests.conftest import ensure_seed_tray_specification

# --- Application-level (Pydantic) validation — no DB required ---


def test_source_line_rejects_binary_float_weight() -> None:
    with pytest.raises(ValueError):
        HarvestSourceLineIn(batch_carrier_assignment_id=uuid.uuid4(), harvested_weight_kg=12.375)


def test_source_line_rejects_excess_decimal_scale() -> None:
    with pytest.raises(ValueError):
        HarvestSourceLineIn(batch_carrier_assignment_id=uuid.uuid4(), harvested_weight_kg="12.3751")


def test_source_line_accepts_string_decimal_weight() -> None:
    line = HarvestSourceLineIn(batch_carrier_assignment_id=uuid.uuid4(), harvested_weight_kg="12.375")
    assert line.harvested_weight_kg == Decimal("12.375")


def test_source_line_rejects_non_positive_weight() -> None:
    with pytest.raises(ValueError):
        HarvestSourceLineIn(batch_carrier_assignment_id=uuid.uuid4(), harvested_weight_kg="0")


def test_source_line_rejects_non_positive_count() -> None:
    with pytest.raises(ValueError):
        HarvestSourceLineIn(batch_carrier_assignment_id=uuid.uuid4(), harvested_weight_kg="1", whole_unit_count=0)


def test_event_rejects_empty_source_lines() -> None:
    with pytest.raises(ValueError):
        HarvestEventCreate(
            client_command_id=uuid.uuid4(), effective_time=datetime.now(timezone.utc), produce_lot_code="LOT-1",
            source_lines=[],
        )


def test_event_rejects_duplicate_assignment_ids() -> None:
    aid = uuid.uuid4()
    with pytest.raises(ValueError):
        HarvestEventCreate(
            client_command_id=uuid.uuid4(), effective_time=datetime.now(timezone.utc), produce_lot_code="LOT-1",
            source_lines=[
                HarvestSourceLineIn(batch_carrier_assignment_id=aid, harvested_weight_kg="1"),
                HarvestSourceLineIn(batch_carrier_assignment_id=aid, harvested_weight_kg="1"),
            ],
        )


def test_event_rejects_mixed_count_presence() -> None:
    with pytest.raises(ValueError):
        HarvestEventCreate(
            client_command_id=uuid.uuid4(), effective_time=datetime.now(timezone.utc), produce_lot_code="LOT-1",
            source_lines=[
                HarvestSourceLineIn(batch_carrier_assignment_id=uuid.uuid4(), harvested_weight_kg="1", whole_unit_count=5),
                HarvestSourceLineIn(batch_carrier_assignment_id=uuid.uuid4(), harvested_weight_kg="1"),
            ],
        )


def test_event_rejects_blank_lot_code() -> None:
    with pytest.raises(ValueError):
        HarvestEventCreate(
            client_command_id=uuid.uuid4(), effective_time=datetime.now(timezone.utc), produce_lot_code="   ",
            source_lines=[HarvestSourceLineIn(batch_carrier_assignment_id=uuid.uuid4(), harvested_weight_kg="1")],
        )


def test_event_naive_effective_time_rejected() -> None:
    with pytest.raises(ValueError):
        HarvestEventCreate(
            client_command_id=uuid.uuid4(), effective_time=datetime.now(), produce_lot_code="LOT-1",
            source_lines=[HarvestSourceLineIn(batch_carrier_assignment_id=uuid.uuid4(), harvested_weight_kg="1")],
        )


def test_source_line_accepts_trailing_zero_padded_weight() -> None:
    # "1.2000" has a raw exponent of -4 (four literal decimal digits) but
    # normalizes to 1.2 — exactly representable in <=3 decimal places, so it
    # must be accepted, not rejected on its literal (unnormalized) form.
    line = HarvestSourceLineIn(batch_carrier_assignment_id=uuid.uuid4(), harvested_weight_kg="1.2000")
    assert line.harvested_weight_kg == Decimal("1.2000")
    assert canonical_decimal_str(line.harvested_weight_kg) == "1.2"


def test_source_line_accepts_safe_scientific_notation() -> None:
    # "1.000E-3" normalizes to exactly 0.001 — no precision is lost.
    line = HarvestSourceLineIn(batch_carrier_assignment_id=uuid.uuid4(), harvested_weight_kg="1.000E-3")
    assert canonical_decimal_str(line.harvested_weight_kg) == "0.001"


def test_source_line_rejects_scientific_notation_with_excess_precision() -> None:
    # "1.234E-2" = 0.01234, which has 5 significant decimal places even
    # after normalization — genuinely excess precision, correctly rejected.
    with pytest.raises(ValueError):
        HarvestSourceLineIn(batch_carrier_assignment_id=uuid.uuid4(), harvested_weight_kg="1.234E-2")


def test_canonical_decimal_str_normalizes_negative_zero() -> None:
    assert canonical_decimal_str(Decimal("-0")) == "0"
    assert canonical_decimal_str(Decimal("1.2")) == canonical_decimal_str(Decimal("1.20")) == canonical_decimal_str(Decimal("1.200"))


def test_source_line_rejects_count_above_bigint_max() -> None:
    with pytest.raises(ValueError):
        HarvestSourceLineIn(
            batch_carrier_assignment_id=uuid.uuid4(), harvested_weight_kg="1",
            whole_unit_count=MAX_WHOLE_UNIT_COUNT + 1,
        )


def test_source_line_accepts_count_at_bigint_max() -> None:
    line = HarvestSourceLineIn(
        batch_carrier_assignment_id=uuid.uuid4(), harvested_weight_kg="1", whole_unit_count=MAX_WHOLE_UNIT_COUNT
    )
    assert line.whole_unit_count == MAX_WHOLE_UNIT_COUNT


def test_event_rejects_extra_fields() -> None:
    with pytest.raises(ValueError):
        HarvestEventCreate(
            client_command_id=uuid.uuid4(), effective_time=datetime.now(timezone.utc), produce_lot_code="LOT-1",
            source_lines=[HarvestSourceLineIn(batch_carrier_assignment_id=uuid.uuid4(), harvested_weight_kg="1")],
            batch_id=uuid.uuid4(),
        )


# --- Integration helpers ----------------------------------------------------------


def _now():
    return datetime.now(timezone.utc)


def _build_scenario(db_session, tenant, user, farm, *, carrier_count=4, suffix=None):
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
            {"carrier_id": c.id, "seed_lot_id": seed_lot.id, "sown_site_count": 200, "seed_count": 200, "line_note": None}
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

    return {
        "crop": crop, "variety": variety, "workflow": workflow, "batch": batch, "carriers": carriers,
        "assignment_ids": assignment_ids,
    }


def _line(aid, weight="10.500", count=None, note=None):
    return {"batch_carrier_assignment_id": aid, "harvested_weight_kg": Decimal(weight), "whole_unit_count": count, "note": note}


@pytest.mark.integration
def test_harvest_creates_event_lot_and_partial_source_lines(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, carrier_count=4)
    aids = s["assignment_ids"]
    suffix = uuid.uuid4().hex[:6]

    event = harvest_service.record_harvest(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), effective_time=_now(), produce_lot_code=f"HLOT-{suffix}", note=None,
        source_lines=[_line(aids[0], "10.500"), _line(aids[1], "5.250"), _line(aids[2], "3.100")],
    )

    lot = db_session.execute(
        select(HarvestedProduceLot).where(HarvestedProduceLot.harvest_event_id == event.id)
    ).scalar_one()
    assert lot.code == f"HLOT-{suffix}"
    assert lot.total_harvested_weight_kg == Decimal("18.850")
    assert lot.total_whole_unit_count is None
    assert lot.batch_id == s["batch"].id
    assert lot.crop_id == s["crop"].id
    assert lot.variety_id == s["variety"].id

    line_count = db_session.execute(
        select(func.count()).select_from(HarvestEvent).where(HarvestEvent.id == event.id)
    ).scalar_one()
    assert line_count == 1

    db_session.refresh(s["batch"])
    assert s["batch"].state == "active"

    read = harvest_service.get_harvest_event(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=s["batch"].id, harvest_event_id=event.id
    )
    assert len(read.source_lines) == 3
    assert read.total_whole_unit_count is None
    assert read.stage.code == "HARVESTING"


@pytest.mark.integration
def test_harvest_wrong_stage_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    suffix = uuid.uuid4().hex[:6]
    # Build a scenario but do NOT transition into the harvesting stage —
    # reuse _build_scenario's pieces minus the final transition.
    crop = crop_service.register_crop(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"C-{suffix}", common_name="Iceberg",
        scientific_name=None, crop_category="leafy_green",
    )
    variety = crop_service.register_variety(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"V-{suffix}",
        name="Variety", supplier_reference=None,
    )
    ps = production_system_service.register_production_system(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"PS-{suffix}", name="PS", description=None,
    )
    workflow = workflow_service.register_workflow(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, variety_id=variety.id,
        production_system_id=ps.id, code=f"WF-{suffix}", name="WF",
    )
    version = workflow_service.create_draft_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id
    )
    seeding = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="SEEDING", name="Seeding", display_order=0, stage_category="seeding", expected_duration_minutes=None,
        permitted_location_type_code=None, required_carrier_type_code="seed_tray", is_start=True, is_terminal=False,
    )
    complete = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="COMPLETE", name="Complete", display_order=1, stage_category="completed", expected_duration_minutes=None,
        permitted_location_type_code=None, required_carrier_type_code=None, is_start=False, is_terminal=True,
    )
    workflow_service.add_transition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=seeding.id, to_stage_id=complete.id, code="ADV", name="Adv",
    )
    workflow_service.publish_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id
    )
    batch = crop_batch_service.create_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"B-{suffix}", workflow_id=workflow.id, effective_time=_now(),
    )
    seed_lot = sowing_service.register_seed_lot(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id,
        variety_id=variety.id, code=f"LOT-{suffix}", supplier_name=None, supplier_lot_reference=None,
        received_date=None, expiry_date=None,
    )
    carrier = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        specification_id=ensure_seed_tray_specification(db_session, tenant_id=tenant.id, actor_user_id=user.id).id,
        code=f"ST-{suffix}", issued_date=None,
    )
    sowing_service.sow_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
        lines=[{"carrier_id": carrier.id, "seed_lot_id": seed_lot.id, "sown_site_count": 10, "seed_count": 10, "line_note": None}],
    )
    assignment = sowing_service.list_batch_carriers(db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id)[0]

    with pytest.raises(HarvestValidationError):
        harvest_service.record_harvest(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
            client_command_id=uuid.uuid4(), effective_time=_now(), produce_lot_code=f"LOT2-{suffix}", note=None,
            source_lines=[_line(assignment.id)],
        )


@pytest.mark.integration
def test_repeated_harvest_from_same_assignment_succeeds(db_session, active_context_with_farm) -> None:
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
    assert event1.id != event2.id

    line_count = db_session.execute(
        select(func.count()).select_from(HarvestEvent).where(HarvestEvent.batch_id == s["batch"].id)
    ).scalar_one()
    assert line_count == 2


@pytest.mark.integration
def test_harvest_exact_retry_returns_original_event(db_session, active_context_with_farm) -> None:
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


@pytest.mark.integration
def test_harvest_decimal_canonicalization_same_fingerprint_retry(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, carrier_count=1)
    aid = s["assignment_ids"][0]
    suffix = uuid.uuid4().hex[:6]
    command_id = uuid.uuid4()
    effective_time = _now()

    first = harvest_service.record_harvest(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=command_id, effective_time=effective_time, produce_lot_code=f"CAN-{suffix}", note=None,
        source_lines=[_line(aid, "1.2")],
    )
    retry = harvest_service.record_harvest(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=command_id, effective_time=effective_time, produce_lot_code=f"CAN-{suffix}", note=None,
        source_lines=[_line(aid, "1.200")],
    )
    assert retry.id == first.id


@pytest.mark.integration
def test_harvest_reused_command_id_different_payload_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, carrier_count=1)
    aid = s["assignment_ids"][0]
    suffix = uuid.uuid4().hex[:6]
    command_id = uuid.uuid4()

    harvest_service.record_harvest(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=command_id, effective_time=_now(), produce_lot_code=f"X-{suffix}", note=None,
        source_lines=[_line(aid, "1.000")],
    )
    with pytest.raises(HarvestCommandReusedWithDifferentPayloadError):
        harvest_service.record_harvest(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
            client_command_id=command_id, effective_time=_now(), produce_lot_code=f"X-{suffix}", note="different",
            source_lines=[_line(aid, "1.000")],
        )


@pytest.mark.integration
def test_duplicate_produce_lot_code_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, carrier_count=2)
    aids = s["assignment_ids"]
    suffix = uuid.uuid4().hex[:6]

    harvest_service.record_harvest(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), effective_time=_now(), produce_lot_code=f"DUP-{suffix}", note=None,
        source_lines=[_line(aids[0], "1.000")],
    )
    with pytest.raises(DuplicateProduceLotCodeError):
        harvest_service.record_harvest(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
            client_command_id=uuid.uuid4(), effective_time=_now(), produce_lot_code=f"DUP-{suffix}", note=None,
            source_lines=[_line(aids[1], "2.000")],
        )


@pytest.mark.integration
def test_aggregate_weight_sum_exceeding_max_rejected_before_write(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, carrier_count=2)
    aids = s["assignment_ids"]
    suffix = uuid.uuid4().hex[:6]

    with pytest.raises(HarvestValidationError):
        harvest_service.record_harvest(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
            client_command_id=uuid.uuid4(), effective_time=_now(), produce_lot_code=f"BIG-{suffix}", note=None,
            source_lines=[_line(aids[0], "60000000000.000"), _line(aids[1], "60000000000.000")],
        )

    event_count = db_session.execute(
        select(func.count()).select_from(HarvestEvent).where(HarvestEvent.batch_id == s["batch"].id)
    ).scalar_one()
    assert event_count == 0, "a rejected aggregate-total command must leave no partial event behind"


@pytest.mark.integration
def test_aggregate_count_sum_exceeding_bigint_max_rejected_before_write(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, carrier_count=2)
    aids = s["assignment_ids"]
    suffix = uuid.uuid4().hex[:6]

    with pytest.raises(HarvestValidationError):
        harvest_service.record_harvest(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
            client_command_id=uuid.uuid4(), effective_time=_now(), produce_lot_code=f"BIGCOUNT-{suffix}", note=None,
            source_lines=[
                _line(aids[0], "1.000", count=MAX_WHOLE_UNIT_COUNT),
                _line(aids[1], "1.000", count=MAX_WHOLE_UNIT_COUNT),
            ],
        )


@pytest.mark.integration
def test_open_hold_blocks_harvest_and_release_permits_and_retry_survives(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, carrier_count=2)
    aids = s["assignment_ids"]
    suffix = uuid.uuid4().hex[:6]

    pre_hold_event = harvest_service.record_harvest(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), effective_time=_now(), produce_lot_code=f"PRE-{suffix}", note=None,
        source_lines=[_line(aids[0], "1.000")],
    )

    hold = quality_hold_service.place_quality_hold(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), effective_time=_now(), source_observation_event_id=None,
        reason_code="pest", reason_text="aphids",
    )

    with pytest.raises(QualityHoldOpenError):
        harvest_service.record_harvest(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
            client_command_id=uuid.uuid4(), effective_time=_now(), produce_lot_code=f"BLOCKED-{suffix}", note=None,
            source_lines=[_line(aids[1], "1.000")],
        )

    # Exact retry of the pre-hold event must still succeed.
    retry = harvest_service.record_harvest(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=pre_hold_event.client_command_id, effective_time=pre_hold_event.effective_time,
        produce_lot_code=f"PRE-{suffix}", note=None, source_lines=[_line(aids[0], "1.000")],
    )
    assert retry.id == pre_hold_event.id

    quality_hold_service.release_quality_hold(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        hold_id=hold.id, client_command_id=uuid.uuid4(), effective_time=_now(), release_reason="resolved",
    )
    unblocked = harvest_service.record_harvest(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), effective_time=_now(), produce_lot_code=f"POST-{suffix}", note=None,
        source_lines=[_line(aids[1], "1.000")],
    )
    assert unblocked.id != pre_hold_event.id
