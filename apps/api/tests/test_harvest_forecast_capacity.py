"""PILOT-PLAN-001A focused backend tests: Batch Harvest Forecast (LOW/
EXPECTED/HIGH range, revision history, one CURRENT forecast per Batch,
never mutated by actual Harvest or a Crop Issue), Production Capacity
Allocation (overlap/double-booking rejection, cancellation, UNKNOWN
capacity never fabricated, never creates real Occupancy), and the
Requirement Harvest Outlook read model (UOM comparability, multiple
contributing Batches), plus tenant/farm isolation."""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.crop_issue import CropIssue
from app.models.grower_inspection import GrowerInspection
from app.models.occupancy import Occupancy
from app.models.unit_of_measure import UnitOfMeasure
from app.schemas.harvest_forecast import RecordBatchHarvestForecast
from app.services import (
    capacity_plan_service,
    carrier_service,
    crop_batch_service,
    crop_service,
    harvest_forecast_service,
    harvest_service,
    location_service,
    planning_service,
    production_system_service,
    sowing_service,
    workflow_service,
)
from app.services.errors import (
    CapacityAllocationExceedsAuthoritativeCapacityError,
    CropBatchNotFoundError,
    ProductionCapacityAllocationNotFoundError,
)
from tests.conftest import ensure_seed_tray_specification
from tests.test_harvest import _build_scenario, _line, _now


def _uom(db_session, code: str) -> UnitOfMeasure:
    return db_session.execute(select(UnitOfMeasure).where(UnitOfMeasure.code == code)).scalar_one()


def _build_capacity_chamber(db_session, tenant, farm, user, *, capacity):
    greenhouse = location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="greenhouse", code=f"gh-{uuid.uuid4().hex[:8]}", name="GH",
        parent_location_id=None, greenhouse_classification="nursery", occupiable=None,
    )
    return location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="germination_chamber", code=f"gc-{uuid.uuid4().hex[:8]}", name="Chamber",
        parent_location_id=greenhouse.id, greenhouse_classification=None, occupiable=True, capacity=capacity,
    )


def _build_unconfigured_location(db_session, tenant, farm, user):
    """A non-occupiable Location with `capacity` never set -- authoritative
    capacity for it must read UNKNOWN, never fabricated."""
    return location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="greenhouse", code=f"gh-{uuid.uuid4().hex[:8]}", name="Unconfigured GH",
        parent_location_id=None, greenhouse_classification="nursery", occupiable=None,
    )


def _record_forecast(db_session, tenant, user, farm, batch, *, low="900", expected="1000", high="1100", uom=None,
                      revision_reason=None):
    uom = uom or _uom(db_session, "kg")
    return harvest_forecast_service.record_batch_harvest_forecast(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), window_start_date=date(2026, 9, 20), window_end_date=date(2026, 9, 25),
        low_quantity=Decimal(low), expected_quantity=Decimal(expected), high_quantity=Decimal(high),
        quantity_uom_id=uom.id, basis="grower_estimate", effective_time=_now(), notes=None,
        revision_reason=revision_reason,
    )


def _open_crop_issue(db_session, tenant, user, farm, batch):
    inspection = GrowerInspection(
        id=uuid.uuid4(), tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id, inspected_by_user_id=user.id,
        effective_time=_now(), overall_assessment="attention_needed", client_command_id=uuid.uuid4(),
        request_fingerprint="x",
    )
    db_session.add(inspection)
    db_session.flush()
    issue = CropIssue(
        id=uuid.uuid4(), tenant_id=tenant.id, farm_id=farm.id, code=f"CI-{uuid.uuid4().hex[:8]}", batch_id=batch.id,
        originating_grower_inspection_id=inspection.id, category="pest_evidence", severity="medium",
        description="aphids observed", status="open", opened_by_user_id=user.id, client_command_id=uuid.uuid4(),
        request_fingerprint="x",
    )
    db_session.add(issue)
    db_session.commit()
    return issue


# --- 1. forecast range shape (pure Pydantic, no DB) ---------------------------------


def test_forecast_range_must_satisfy_low_le_expected_le_high() -> None:
    with pytest.raises(ValueError):
        RecordBatchHarvestForecast(
            client_command_id=uuid.uuid4(), window_start_date=date(2026, 9, 20), window_end_date=date(2026, 9, 25),
            low_quantity=Decimal("1200"), expected_quantity=Decimal("1000"), high_quantity=Decimal("1100"),
            quantity_uom_id=uuid.uuid4(), basis="grower_estimate", effective_time=datetime.now(timezone.utc),
        )


def test_forecast_window_end_before_start_rejected() -> None:
    with pytest.raises(ValueError):
        RecordBatchHarvestForecast(
            client_command_id=uuid.uuid4(), window_start_date=date(2026, 9, 25), window_end_date=date(2026, 9, 20),
            low_quantity=Decimal("900"), expected_quantity=Decimal("1000"), high_quantity=Decimal("1100"),
            quantity_uom_id=uuid.uuid4(), basis="grower_estimate", effective_time=datetime.now(timezone.utc),
        )


# --- 2/3/12 (proof #2, #3): revision preserves history; exactly one current ---------


@pytest.mark.integration
def test_forecast_revision_preserves_history_and_exactly_one_current(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, carrier_count=1)
    batch = s["batch"]

    first = _record_forecast(
        db_session, tenant, user, farm, batch, low="1700", expected="1800", high="1900", revision_reason=None
    )
    assert first.revision_number == 1

    second = _record_forecast(
        db_session, tenant, user, farm, batch, low="1500", expected="1600", high="1700", revision_reason="cooler week"
    )
    assert second.revision_number == 2

    history = harvest_forecast_service.list_forecast_history(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id
    )
    assert [h.revision_number for h in history] == [1, 2]
    assert history[0].expected_quantity == Decimal("1800")
    assert history[0].is_current is False
    assert history[1].expected_quantity == Decimal("1600")
    assert history[1].is_current is True
    # exactly one current forecast
    current = harvest_forecast_service.get_current_forecast(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id
    )
    assert current.id == second.id
    assert sum(1 for h in history if h.is_current) == 1


# --- 4. forecast does not mutate Batch stage/occupancy -------------------------------


@pytest.mark.integration
def test_forecast_does_not_mutate_batch_stage(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, carrier_count=1)
    batch = s["batch"]
    before_state = batch.state

    _record_forecast(db_session, tenant, user, farm, batch)

    db_session.refresh(batch)
    assert batch.state == before_state


# --- 5. actual Harvest read does not rewrite forecast ---------------------------------


@pytest.mark.integration
def test_actual_harvest_does_not_rewrite_forecast(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, carrier_count=1)
    batch = s["batch"]
    forecast = _record_forecast(db_session, tenant, user, farm, batch, expected="1000")

    harvest_service.record_harvest(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=_now(), produce_lot_code=f"HLOT-{uuid.uuid4().hex[:6]}",
        note=None, source_lines=[_line(s["assignment_ids"][0], "250.000")],
    )

    unchanged = harvest_forecast_service.get_current_forecast(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id
    )
    assert unchanged.id == forecast.id
    assert unchanged.expected_quantity == Decimal("1000")

    status = harvest_forecast_service.get_forecast_status(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id
    )
    assert status.actual.total_harvested_weight_kg == Decimal("250.000")
    assert status.actual.comparable_to_forecast_uom is True
    assert status.actual.actual_quantity_in_forecast_uom == Decimal("250.000")
    assert status.actual.remaining_forecast_quantity_in_forecast_uom == Decimal("750.000")
    # the forecast row itself is still exactly what was recorded
    assert status.current_forecast.expected_quantity == Decimal("1000")


# --- 6/7/8/9/10: capacity allocation overlap / cancel / UNKNOWN / no Occupancy -------


@pytest.mark.integration
def test_overlapping_allocations_cannot_exceed_authoritative_capacity(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    chamber = _build_capacity_chamber(db_session, tenant, farm, user, capacity=5)

    capacity_plan_service.create_capacity_allocation(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        location_id=chamber.id, production_system_id=None, planned_start_date=date(2026, 10, 1),
        planned_end_date=date(2026, 10, 10), planned_capacity_amount=3, source_seeding_program_line_id=None,
        source_crop_batch_id=None, notes=None,
    )
    with pytest.raises(CapacityAllocationExceedsAuthoritativeCapacityError):
        capacity_plan_service.create_capacity_allocation(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            client_command_id=uuid.uuid4(), location_id=chamber.id, production_system_id=None,
            planned_start_date=date(2026, 10, 5), planned_end_date=date(2026, 10, 15),
            planned_capacity_amount=3, source_seeding_program_line_id=None, source_crop_batch_id=None, notes=None,
        )


@pytest.mark.integration
def test_non_overlapping_allocations_do_not_conflict(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    chamber = _build_capacity_chamber(db_session, tenant, farm, user, capacity=5)

    capacity_plan_service.create_capacity_allocation(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        location_id=chamber.id, production_system_id=None, planned_start_date=date(2026, 10, 1),
        planned_end_date=date(2026, 10, 10), planned_capacity_amount=5, source_seeding_program_line_id=None,
        source_crop_batch_id=None, notes=None,
    )
    # [start, end) half-open: 10-10 is the first free day, so this does not overlap.
    second = capacity_plan_service.create_capacity_allocation(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        location_id=chamber.id, production_system_id=None, planned_start_date=date(2026, 10, 10),
        planned_end_date=date(2026, 10, 20), planned_capacity_amount=5, source_seeding_program_line_id=None,
        source_crop_batch_id=None, notes=None,
    )
    assert second.status == "active"


@pytest.mark.integration
def test_cancelled_allocation_no_longer_consumes_planned_capacity(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    chamber = _build_capacity_chamber(db_session, tenant, farm, user, capacity=5)

    first = capacity_plan_service.create_capacity_allocation(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        location_id=chamber.id, production_system_id=None, planned_start_date=date(2026, 10, 1),
        planned_end_date=date(2026, 10, 10), planned_capacity_amount=5, source_seeding_program_line_id=None,
        source_crop_batch_id=None, notes=None,
    )
    capacity_plan_service.cancel_capacity_allocation(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, allocation_id=first.id,
        client_command_id=uuid.uuid4(),
    )
    # Now fully overlapping, full-capacity allocation succeeds since the
    # cancelled allocation no longer counts toward planned used capacity.
    second = capacity_plan_service.create_capacity_allocation(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        location_id=chamber.id, production_system_id=None, planned_start_date=date(2026, 10, 1),
        planned_end_date=date(2026, 10, 10), planned_capacity_amount=5, source_seeding_program_line_id=None,
        source_crop_batch_id=None, notes=None,
    )
    assert second.status == "active"

    summary = capacity_plan_service.get_location_capacity_summary(
        db_session, tenant_id=tenant.id, farm_id=farm.id, location_id=chamber.id, window_start_date=date(2026, 10, 1),
        window_end_date=date(2026, 10, 10),
    )
    assert summary.planned_used_capacity == 5


@pytest.mark.integration
def test_planned_allocation_does_not_create_actual_occupancy(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    chamber = _build_capacity_chamber(db_session, tenant, farm, user, capacity=5)

    before = db_session.execute(
        select(Occupancy).where(Occupancy.tenant_id == tenant.id, Occupancy.target_location_id == chamber.id)
    ).scalars().all()

    capacity_plan_service.create_capacity_allocation(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        location_id=chamber.id, production_system_id=None, planned_start_date=date(2026, 10, 1),
        planned_end_date=date(2026, 10, 10), planned_capacity_amount=3, source_seeding_program_line_id=None,
        source_crop_batch_id=None, notes=None,
    )

    after = db_session.execute(
        select(Occupancy).where(Occupancy.tenant_id == tenant.id, Occupancy.target_location_id == chamber.id)
    ).scalars().all()
    assert len(after) == len(before) == 0


@pytest.mark.integration
def test_unknown_capacity_is_not_fabricated_as_available(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    unconfigured = _build_unconfigured_location(db_session, tenant, farm, user)

    summary = capacity_plan_service.get_location_capacity_summary(
        db_session, tenant_id=tenant.id, farm_id=farm.id, location_id=unconfigured.id,
        window_start_date=date(2026, 10, 1), window_end_date=date(2026, 10, 10),
    )
    assert summary.capacity_status == "unknown"
    assert summary.authoritative_capacity is None
    assert summary.available_planned_capacity is None

    # An allocation can still be recorded against it (capacity unknown is
    # never treated as zero), never rejected for a fabricated reason.
    allocation = capacity_plan_service.create_capacity_allocation(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        location_id=unconfigured.id, production_system_id=None, planned_start_date=date(2026, 10, 1),
        planned_end_date=date(2026, 10, 10), planned_capacity_amount=999, source_seeding_program_line_id=None,
        source_crop_batch_id=None, notes=None,
    )
    assert allocation.status == "active"


# --- 11/12/13: Requirement Harvest Outlook -------------------------------------------


def _build_crop_and_variety(db_session, tenant, user, *, suffix):
    crop = crop_service.register_crop(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"ICE-{suffix}", common_name="Iceberg",
        scientific_name=None, crop_category="leafy_green",
    )
    variety = crop_service.register_variety(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"MAM-{suffix}",
        name="Mamutik", supplier_reference=None,
    )
    return crop, variety


def _build_batch_linked_to_line(db_session, tenant, user, farm, *, crop, variety, seeding_program_line_id, suffix):
    """A Crop Batch sown with `seeding_program_line_id` set AT SOW TIME --
    `sowing_events` is append-only, so this FK can only ever be set on
    insert, never retrofitted onto an already-sown batch."""
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
        code=f"BATCH-{suffix}", workflow_id=workflow.id, effective_time=_now(),
    )
    seed_lot = sowing_service.register_seed_lot(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id,
        variety_id=variety.id, code=f"LOT-{suffix}", supplier_name=None, supplier_lot_reference=None,
        received_date=None, expiry_date=None,
    )
    seed_tray_spec = ensure_seed_tray_specification(db_session, tenant_id=tenant.id, actor_user_id=user.id)
    carrier = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, specification_id=seed_tray_spec.id,
        code=f"ST-{suffix}", issued_date=None,
    )
    sowing_service.sow_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
        lines=[{
            "carrier_id": carrier.id, "seed_lot_id": seed_lot.id, "sown_site_count": 200, "seed_count": 200,
            "line_note": None,
        }],
        seeding_program_line_id=seeding_program_line_id,
    )
    return batch


def _build_requirement_with_batch(db_session, tenant, user, farm, *, forecast_uom_code="kg", forecast_expected="1000"):
    suffix = uuid.uuid4().hex[:8]
    crop, variety = _build_crop_and_variety(db_session, tenant, user, suffix=suffix)
    kg = _uom(db_session, "kg")
    requirement = planning_service.create_production_requirement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        crop_id=crop.id, variety_id=variety.id, required_by_date=date(2026, 10, 1),
        required_quantity=Decimal("2000"), quantity_uom_id=kg.id, reference=None, notes=None,
    )
    line = planning_service.create_seeding_program_line(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        production_requirement_id=requirement.id, client_command_id=uuid.uuid4(), planned_sow_date=date(2026, 9, 1),
        crop_id=crop.id, variety_id=variety.id, planned_quantity=Decimal("200"),
        planned_quantity_uom_id=_uom(db_session, "SEED").id, expected_coverage_quantity=Decimal("1000"),
        expected_coverage_uom_id=kg.id, notes=None,
    )
    batch = _build_batch_linked_to_line(
        db_session, tenant, user, farm, crop=crop, variety=variety, seeding_program_line_id=line.id, suffix=suffix
    )

    forecast_uom = _uom(db_session, forecast_uom_code)
    if forecast_expected is not None:
        _record_forecast(
            db_session, tenant, user, farm, batch, expected=forecast_expected,
            low=str(Decimal(forecast_expected) - 100), high=str(Decimal(forecast_expected) + 100), uom=forecast_uom,
        )
    return requirement, batch


@pytest.mark.integration
def test_requirement_outlook_sums_comparable_current_forecasts(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    requirement, _s = _build_requirement_with_batch(db_session, tenant, user, farm, forecast_expected="1000")

    outlook = planning_service.compute_requirement_harvest_outlook(
        db_session, tenant_id=tenant.id, farm_id=farm.id, requirement_id=requirement.id
    )
    assert outlook.forecast_comparable is True
    assert outlook.forecast_expected_quantity == Decimal("1000")
    assert outlook.batches_with_current_forecast_count == 1
    assert outlook.coverage_gap_quantity == Decimal("1000")  # 2000 required - 1000 forecast


@pytest.mark.integration
def test_requirement_outlook_incompatible_uom_not_silently_converted(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    # Forecast recorded in EA (count, conversion_family=None) against a
    # Requirement demanding kg -- no conversion path exists at all.
    requirement, _s = _build_requirement_with_batch(
        db_session, tenant, user, farm, forecast_uom_code="EA", forecast_expected="1000"
    )

    outlook = planning_service.compute_requirement_harvest_outlook(
        db_session, tenant_id=tenant.id, farm_id=farm.id, requirement_id=requirement.id
    )
    assert outlook.batches_with_current_forecast_count == 1
    assert outlook.forecast_comparable is False
    assert outlook.forecast_expected_quantity is None
    assert outlook.coverage_gap_quantity is None


@pytest.mark.integration
def test_multiple_batches_may_contribute_to_one_requirement(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    suffix = uuid.uuid4().hex[:8]
    crop, variety = _build_crop_and_variety(db_session, tenant, user, suffix=suffix)
    kg = _uom(db_session, "kg")
    requirement = planning_service.create_production_requirement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        crop_id=crop.id, variety_id=variety.id, required_by_date=date(2026, 10, 1),
        required_quantity=Decimal("2000"), quantity_uom_id=kg.id, reference=None, notes=None,
    )
    line1 = planning_service.create_seeding_program_line(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        production_requirement_id=requirement.id, client_command_id=uuid.uuid4(), planned_sow_date=date(2026, 9, 1),
        crop_id=crop.id, variety_id=variety.id, planned_quantity=Decimal("100"),
        planned_quantity_uom_id=_uom(db_session, "SEED").id, expected_coverage_quantity=Decimal("500"),
        expected_coverage_uom_id=kg.id, notes=None,
    )
    batch1 = _build_batch_linked_to_line(
        db_session, tenant, user, farm, crop=crop, variety=variety, seeding_program_line_id=line1.id,
        suffix=f"{suffix}a",
    )
    _record_forecast(db_session, tenant, user, farm, batch1, expected="600", low="500", high="700")

    line2 = planning_service.create_seeding_program_line(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        production_requirement_id=requirement.id, client_command_id=uuid.uuid4(), planned_sow_date=date(2026, 9, 2),
        crop_id=crop.id, variety_id=variety.id, planned_quantity=Decimal("100"),
        planned_quantity_uom_id=_uom(db_session, "SEED").id, expected_coverage_quantity=Decimal("500"),
        expected_coverage_uom_id=kg.id, notes=None,
    )
    batch2 = _build_batch_linked_to_line(
        db_session, tenant, user, farm, crop=crop, variety=variety, seeding_program_line_id=line2.id,
        suffix=f"{suffix}b",
    )
    _record_forecast(db_session, tenant, user, farm, batch2, expected="400", low="300", high="500")

    outlook = planning_service.compute_requirement_harvest_outlook(
        db_session, tenant_id=tenant.id, farm_id=farm.id, requirement_id=requirement.id
    )
    assert outlook.contributing_batch_count == 2
    assert outlook.batches_with_current_forecast_count == 2
    assert outlook.forecast_comparable is True
    assert outlook.forecast_expected_quantity == Decimal("1000")  # 600 + 400


# --- 14. open Crop Issue is a risk signal, never a forecast mutation -----------------


@pytest.mark.integration
def test_open_crop_issue_is_risk_signal_never_mutates_forecast(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, carrier_count=1)
    batch = s["batch"]
    _record_forecast(db_session, tenant, user, farm, batch, expected="1000")
    _open_crop_issue(db_session, tenant, user, farm, batch)

    status = harvest_forecast_service.get_forecast_status(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id
    )
    assert status.open_crop_issue_count == 1
    assert status.current_forecast.expected_quantity == Decimal("1000")


# --- 15. tenant/farm isolation ---------------------------------------------------------


@pytest.mark.integration
def test_forecast_and_capacity_allocation_tenant_farm_isolation(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, carrier_count=1)
    _record_forecast(db_session, tenant, user, farm, s["batch"])
    chamber = _build_capacity_chamber(db_session, tenant, farm, user, capacity=5)
    allocation = capacity_plan_service.create_capacity_allocation(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        location_id=chamber.id, production_system_id=None, planned_start_date=date(2026, 10, 1),
        planned_end_date=date(2026, 10, 10), planned_capacity_amount=1, source_seeding_program_line_id=None,
        source_crop_batch_id=None, notes=None,
    )

    from app.services import farm_service, membership_service, tenant_service, user_service

    other_tenant = tenant_service.create_tenant(db_session, code=f"other-{uuid.uuid4().hex[:8]}", name="Other Tenant")
    other_user = user_service.create_user(
        db_session, oidc_issuer="https://issuer.example", oidc_subject=f"other-{uuid.uuid4().hex[:8]}",
        email=f"other-{uuid.uuid4().hex[:8]}@example.com", display_name="Other User",
    )
    membership_service.add_membership(
        db_session, tenant_id=other_tenant.id, user_id=other_user.id, role_code="tenant_admin", actor_user_id=None,
    )
    other_farm = farm_service.create_farm(
        db_session, tenant_id=other_tenant.id, actor_user_id=other_user.id, code="other-farm", name="Other Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )

    with pytest.raises(CropBatchNotFoundError):
        # wrong tenant/farm entirely -- the Batch itself isn't visible to
        # this tenant, so lookup fails before ever reaching the forecast.
        harvest_forecast_service.get_current_forecast(
            db_session, tenant_id=other_tenant.id, farm_id=other_farm.id, batch_id=s["batch"].id
        )
    with pytest.raises(ProductionCapacityAllocationNotFoundError):
        capacity_plan_service.get_capacity_allocation(
            db_session, tenant_id=other_tenant.id, farm_id=other_farm.id, allocation_id=allocation.id
        )
