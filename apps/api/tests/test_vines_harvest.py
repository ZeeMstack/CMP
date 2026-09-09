"""VINES-OPS-003: Vines Production Harvest -- reuses the generic CMP-013/
HARVEST-OPS-001 Harvest domain (`harvest_events`/`harvest_source_lines`/
`harvested_produce_lots`), extended with a Grow-Gutter-Location source-line
anchor (`5a26ba0dae6c`). Covers: happy path, repeat harvest (no population
change), multi-Gutter allocation within one event, disposed Grow Cube
exclusion, empty-gutter rejection, quality-hold gating, idempotency, tenant
isolation, audit, Grading integration, traceability, and correction.
Concurrency lives in its own file (`test_vines_harvest_concurrency.py`)."""

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.audit_event import AuditEvent
from app.models.harvest_source_line import HarvestSourceLine
from app.models.harvest_source_line_grow_bag import HarvestSourceLineGrowBag
from app.services import (
    grade_definition_service,
    grading_service,
    harvest_service,
    location_service,
    production_disposition_service,
    quality_hold_service,
)
from app.services.errors import (
    HarvestCommandReusedWithDifferentPayloadError,
    HarvestCorrectionAlreadySupersededError,
    HarvestCorrectionCommandReusedWithDifferentPayloadError,
    HarvestEventNotFoundError,
    HarvestValidationError,
    QualityHoldOpenError,
)
from tests._vines_harvest_scenario import build_vines_harvest_ready_scenario

pytestmark = pytest.mark.integration


def _record(db_session, tenant, farm, user, s, lines, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), effective_time=s["harvest_time"], produce_lot_code=f"LOT-{uuid.uuid4().hex[:8]}",
        note=None,
    )
    defaults.update(overrides)
    source_lines = [
        {"source_location_id": gid, "harvested_weight_kg": Decimal(w), "whole_unit_count": None, "note": None}
        for gid, w in lines
    ]
    return harvest_service.record_vines_harvest(db_session, source_lines=source_lines, **defaults)


# =====================================================================
# Happy path / repeat harvest / no population change
# =====================================================================


@pytest.mark.integration
def test_happy_path_creates_event_and_lot(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = build_vines_harvest_ready_scenario(db_session, tenant, user, farm, intervines_plant_count=4)

    event = _record(db_session, tenant, farm, user, s, [(s["grow_gutter_id"], "10.000")])
    detail = harvest_service.get_vines_harvest_event(db_session, tenant_id=tenant.id, farm_id=farm.id, harvest_event_id=event.id)

    assert detail.batch_id == s["batch"].id
    assert detail.original_total_harvested_weight_kg == Decimal("10.000")
    assert detail.current_total_harvested_weight_kg == Decimal("10.000")
    assert len(detail.source_lines) == 1
    assert detail.source_lines[0].gutter.id == s["grow_gutter_id"]
    # 4 plants at capacity 2/bag -> ceil(4/2) = 2 Grow Bags actually used
    # (out of the 10 registered but not all assigned).
    assert len(detail.source_lines[0].grow_bags) == 2


@pytest.mark.integration
def test_scenario_1_repeat_harvest_two_events_no_population_change(db_session, active_context_with_farm) -> None:
    """Ticket Scenario 1: Batch with 20 living plants; Day 1 harvest 10kg,
    Day 7 harvest 8kg -> 2 distinct events/lots, total raw history 18kg,
    living population remains 20."""
    tenant, user, _headers, farm = active_context_with_farm
    s = build_vines_harvest_ready_scenario(
        db_session, tenant, user, farm, intervines_plant_count=20, grow_bag_capacity=2, grow_bag_count=10,
    )
    living_before = production_disposition_service.get_current_living_population(
        db_session, root_batch_carrier_assignment_id=s["transfer"].grow_bags[0].destination_batch_carrier_assignment_id
    )

    event1 = _record(
        db_session, tenant, farm, user, s, [(s["grow_gutter_id"], "10.000")],
        effective_time=s["harvest_time"], produce_lot_code="LOT-DAY1",
    )
    event2 = _record(
        db_session, tenant, farm, user, s, [(s["grow_gutter_id"], "8.000")],
        effective_time=s["harvest_time"] + timedelta(hours=6), produce_lot_code="LOT-DAY7",
        client_command_id=uuid.uuid4(),
    )
    assert event1.id != event2.id

    history = harvest_service.list_vines_harvest_events(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=s["batch"].id
    )
    assert len(history) == 2
    lot_ids = {h.produce_lot_id for h in history}
    assert len(lot_ids) == 2  # distinct HarvestedProduceLots
    total_raw = sum((h.original_total_harvested_weight_kg for h in history), Decimal("0"))
    assert total_raw == Decimal("18.000")

    # No population change from harvesting, on ANY grow bag under the gutter.
    for bag in s["transfer"].grow_bags:
        living = production_disposition_service.get_current_living_population(
            db_session, root_batch_carrier_assignment_id=bag.destination_batch_carrier_assignment_id
        )
        assert living == 2  # capacity 2, still fully living
    total_living = sum(
        production_disposition_service.get_current_living_population(
            db_session, root_batch_carrier_assignment_id=bag.destination_batch_carrier_assignment_id
        )
        for bag in s["transfer"].grow_bags
    )
    assert total_living == 20 == living_before + 20 - living_before  # unchanged at 20


# =====================================================================
# Scenario 2: multi-Gutter source allocation within one event
# =====================================================================


@pytest.mark.integration
def test_scenario_2_two_gutters_one_event(db_session, active_context_with_farm) -> None:
    """Ticket Scenario 2: GUT-001=15kg, GUT-002=12kg -> one Harvest event of
    27kg with source allocation preserved per Gutter; Batch remains one and
    unchanged. Uses a scenario with a single Grow Gutter capacity split
    across two DIFFERENT batches' own Gutters is not what's being tested --
    instead this builds one Batch transferred onto ONE Gutter (own helper),
    and a second, independent Gutter is populated via a second transfer
    drawing from a second InterVines source group in the SAME Batch."""
    tenant, user, _headers, farm = active_context_with_farm
    from app.schemas.farm_setup import (
        GreenhouseSetupCreate, GutterGeneratorConfig, SpanSetupConfig, VinesSetupConfig, ZoneSetupConfig,
    )
    from app.services import carrier_service as _carrier_service
    from app.services import crop_batch_service, farm_setup_service, intervines_transplant_service
    from tests._transplant_scenario import build_transplant_ready_scenario

    suffix = uuid.uuid4().hex[:8]
    # One Batch, one InterVines source group with enough plants for BOTH gutters.
    ts = build_transplant_ready_scenario(
        db_session, tenant, user, farm, suffix=suffix, tray_count=1, normal=10,
        transplanting_required_type="grow_cube", intervines_table_count=1, intervines_table_capacity=1000,
        second_transplant_required_type="grow_bag",
    )
    extra_cubes_needed = max(0, 10 - len(ts["destination_carriers"]))
    if extra_cubes_needed:
        _carrier_service.bulk_register_carriers(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, carrier_type_code="grow_cube",
            code_prefix=f"GCX{suffix[:6]}-", start=1, end=extra_cubes_needed, pad_width=4,
        )
    table_id = ts["intervines_table_ids"][0]
    entry_time = ts["entry_time"] + timedelta(hours=1)
    intervines_transplant_service.record_intervines_transplant(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=ts["batch"].id,
        client_command_id=uuid.uuid4(), effective_time=entry_time, note=None,
        source_assignment_id=ts["source_assignment_ids"][0], plant_count=10, destination_location_id=table_id,
        grow_cube_specification_id=None,
    )
    crop_batch_service.transition_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=ts["batch"].id,
        client_command_id=uuid.uuid4(), configured_transition_id=ts["transitions"]["t2"].id,
        effective_time=entry_time + timedelta(minutes=5), reason=None,
    )
    crop_batch_service.transition_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=ts["batch"].id,
        client_command_id=uuid.uuid4(), configured_transition_id=ts["transitions"]["t2b"].id,
        effective_time=entry_time + timedelta(minutes=10), reason=None,
    )

    setup = farm_setup_service.create_greenhouse_setup(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        payload=GreenhouseSetupCreate(
            code=f"VGH-{suffix}", name="Vines Greenhouse", classification="vines", client_command_id=uuid.uuid4(),
            vines=VinesSetupConfig(
                zones=[
                    ZoneSetupConfig(
                        code="Z1",
                        spans=[
                            SpanSetupConfig(
                                code="S1",
                                gutters=GutterGeneratorConfig(
                                    code_prefix=f"GUT{suffix[:4]}-", start=1, end=2, pad_width=2,
                                    bag_positions_per_gutter=10, bag_position_code_prefix=f"POS{suffix[:4]}-",
                                    bag_position_pad_width=3,
                                ),
                            )
                        ],
                    )
                ]
            ),
        ),
    )
    structure = farm_setup_service.get_greenhouse_structure(
        db_session.connection(), tenant_id=tenant.id, farm_id=farm.id, greenhouse_id=setup.greenhouse_id,
    )
    gutter1, gutter2 = structure.vines_zones[0].spans[0].gutters[0], structure.vines_zones[0].spans[0].gutters[1]

    from app.services import carrier_service, carrier_specification_service, vines_production_transfer_service as vpts

    spec = carrier_specification_service.register_carrier_specification(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, carrier_type_code="grow_bag",
        code=f"GB-SPEC-{suffix[:6]}", name="Bag", length_mm=300, width_mm=300, height_mm=200,
        biological_position_count=1,
    )
    carrier_service.bulk_register_carriers(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, specification_id=spec.id,
        code_prefix=f"GB{suffix[:6]}-", start=1, end=10, pad_width=4,
    )
    transfer_time = entry_time + timedelta(hours=2)
    transfer1 = vpts.record_vines_production_transfer(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=ts["batch"].id,
        client_command_id=uuid.uuid4(), effective_time=transfer_time, note=None,
        source_intervines_table_id=table_id, plant_count=5, destination_grow_gutter_id=gutter1.id,
        grow_bag_specification_id=spec.id,
    )
    transfer2 = vpts.record_vines_production_transfer(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=ts["batch"].id,
        client_command_id=uuid.uuid4(), effective_time=transfer_time, note=None,
        source_intervines_table_id=table_id, plant_count=5, destination_grow_gutter_id=gutter2.id,
        grow_bag_specification_id=spec.id,
    )
    assert len(transfer1.grow_bags) == 5 and len(transfer2.grow_bags) == 5

    harvest_time = transfer_time + timedelta(hours=1)
    event = harvest_service.record_vines_harvest(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=ts["batch"].id,
        client_command_id=uuid.uuid4(), effective_time=harvest_time, produce_lot_code=f"LOT-{suffix}", note=None,
        source_lines=[
            {"source_location_id": gutter1.id, "harvested_weight_kg": Decimal("15.000"), "whole_unit_count": None, "note": None},
            {"source_location_id": gutter2.id, "harvested_weight_kg": Decimal("12.000"), "whole_unit_count": None, "note": None},
        ],
    )
    detail = harvest_service.get_vines_harvest_event(db_session, tenant_id=tenant.id, farm_id=farm.id, harvest_event_id=event.id)
    assert detail.original_total_harvested_weight_kg == Decimal("27.000")
    by_gutter = {line.gutter.id: line.original_harvested_weight_kg for line in detail.source_lines}
    assert by_gutter[gutter1.id] == Decimal("15.000")
    assert by_gutter[gutter2.id] == Decimal("12.000")
    assert detail.batch_id == ts["batch"].id  # one Batch, unchanged


# =====================================================================
# Scenario 3: disposed Grow Cube / empty gutter exclusion
# =====================================================================


@pytest.mark.integration
def test_scenario_3_disposed_grow_cube_excluded_from_lineage(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = build_vines_harvest_ready_scenario(
        db_session, tenant, user, farm, intervines_plant_count=2, grow_bag_capacity=2, grow_bag_count=1,
        gutter_bag_positions=1,
    )
    bag = s["transfer"].grow_bags[0]
    gc_to_dispose = s["transfer"].source_grow_cubes[0].id

    production_disposition_service.record_grow_cube_disposition(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        batch_carrier_assignment_id=bag.destination_batch_carrier_assignment_id,
        grow_cube_carrier_ids=[gc_to_dispose], reason_code="dead", effective_time=s["harvest_time"], note=None,
    )

    event = _record(db_session, tenant, farm, user, s, [(s["grow_gutter_id"], "3.000")])
    detail = harvest_service.get_vines_harvest_event(db_session, tenant_id=tenant.id, farm_id=farm.id, harvest_event_id=event.id)
    # Grow Bag still has 1 living Grow Cube -> still appears in lineage
    # (the ticket: "Disposed GC-002 must remain excluded from living-source
    # detail" -- the BAG still qualifies via its other living plant, but the
    # SPECIFIC disposed Grow Cube is never separately implied as a source).
    assert len(detail.source_lines[0].grow_bags) == 1
    assert detail.source_lines[0].grow_bags[0].id == bag.grow_bag.id

    # No population change from the harvest itself.
    living = production_disposition_service.get_current_living_population(
        db_session, root_batch_carrier_assignment_id=bag.destination_batch_carrier_assignment_id
    )
    assert living == 1


@pytest.mark.integration
def test_gutter_with_zero_living_plants_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = build_vines_harvest_ready_scenario(
        db_session, tenant, user, farm, intervines_plant_count=1, grow_bag_capacity=1, grow_bag_count=1,
        gutter_bag_positions=1,
    )
    bag = s["transfer"].grow_bags[0]
    gc_id = s["transfer"].source_grow_cubes[0].id
    production_disposition_service.record_grow_cube_disposition(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        batch_carrier_assignment_id=bag.destination_batch_carrier_assignment_id,
        grow_cube_carrier_ids=[gc_id], reason_code="dead", effective_time=s["harvest_time"], note=None,
    )
    with pytest.raises(HarvestValidationError):
        _record(db_session, tenant, farm, user, s, [(s["grow_gutter_id"], "1.000")])


# =====================================================================
# Quality hold
# =====================================================================


@pytest.mark.integration
def test_quality_hold_blocks_harvest(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = build_vines_harvest_ready_scenario(db_session, tenant, user, farm, intervines_plant_count=2, grow_bag_count=1, grow_bag_capacity=2)
    quality_hold_service.place_quality_hold(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), effective_time=s["harvest_time"], source_observation_event_id=None,
        reason_code="OTHER", reason_text="test hold",
    )
    with pytest.raises(QualityHoldOpenError):
        _record(db_session, tenant, farm, user, s, [(s["grow_gutter_id"], "1.000")])


# =====================================================================
# Idempotency
# =====================================================================


@pytest.mark.integration
def test_replay_same_client_command_id_returns_same_event(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = build_vines_harvest_ready_scenario(db_session, tenant, user, farm, intervines_plant_count=2, grow_bag_count=1, grow_bag_capacity=2)
    cid = uuid.uuid4()
    first = _record(db_session, tenant, farm, user, s, [(s["grow_gutter_id"], "5.000")], client_command_id=cid, produce_lot_code="LOT-X")
    second = _record(db_session, tenant, farm, user, s, [(s["grow_gutter_id"], "5.000")], client_command_id=cid, produce_lot_code="LOT-X")
    assert first.id == second.id
    lines = db_session.execute(select(HarvestSourceLine).where(HarvestSourceLine.harvest_event_id == first.id)).scalars().all()
    assert len(lines) == 1


@pytest.mark.integration
def test_replay_same_client_command_id_different_payload_conflicts(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = build_vines_harvest_ready_scenario(db_session, tenant, user, farm, intervines_plant_count=2, grow_bag_count=1, grow_bag_capacity=2)
    cid = uuid.uuid4()
    _record(db_session, tenant, farm, user, s, [(s["grow_gutter_id"], "5.000")], client_command_id=cid, produce_lot_code="LOT-A")
    with pytest.raises(HarvestCommandReusedWithDifferentPayloadError):
        _record(db_session, tenant, farm, user, s, [(s["grow_gutter_id"], "6.000")], client_command_id=cid, produce_lot_code="LOT-A")


# =====================================================================
# Tenant isolation
# =====================================================================


@pytest.mark.integration
def test_tenant_isolation_cannot_harvest_against_foreign_gutter(db_session, active_context_with_farm) -> None:
    from app.services import farm_service, membership_service, tenant_service, user_service
    from app.services.errors import CropBatchNotFoundError

    tenant, user, _headers, farm = active_context_with_farm
    s = build_vines_harvest_ready_scenario(db_session, tenant, user, farm, intervines_plant_count=2, grow_bag_count=1, grow_bag_capacity=2)

    other_tenant = tenant_service.create_tenant(db_session, code=f"other-{uuid.uuid4().hex[:8]}", name="Other Tenant")
    other_user = user_service.create_user(
        db_session, oidc_issuer="other", oidc_subject=uuid.uuid4().hex, email=f"{uuid.uuid4().hex}@example.com",
        display_name="Other User",
    )
    membership_service.add_membership(db_session, tenant_id=other_tenant.id, user_id=other_user.id, role_code="tenant_admin", actor_user_id=None)
    other_farm = farm_service.create_farm(
        db_session, tenant_id=other_tenant.id, actor_user_id=other_user.id, code="other-farm", name="Other Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    # The Batch itself is tenant-scoped -- a foreign tenant/farm can never
    # even resolve it, let alone its Gutter (isolation enforced at the
    # earliest possible point, before any Location lookup).
    with pytest.raises(CropBatchNotFoundError):
        harvest_service.record_vines_harvest(
            db_session, tenant_id=other_tenant.id, farm_id=other_farm.id, actor_user_id=other_user.id,
            batch_id=s["batch"].id, client_command_id=uuid.uuid4(), effective_time=s["harvest_time"],
            produce_lot_code="LOT-CROSS", note=None,
            source_lines=[{"source_location_id": s["grow_gutter_id"], "harvested_weight_kg": Decimal("1.000"), "whole_unit_count": None, "note": None}],
        )


# =====================================================================
# Audit
# =====================================================================


@pytest.mark.integration
def test_record_writes_one_audit_event(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = build_vines_harvest_ready_scenario(db_session, tenant, user, farm, intervines_plant_count=2, grow_bag_count=1, grow_bag_capacity=2)
    event = _record(db_session, tenant, farm, user, s, [(s["grow_gutter_id"], "4.000")])
    events = db_session.execute(
        select(AuditEvent).where(AuditEvent.tenant_id == tenant.id, AuditEvent.action == "crop_batch.harvested", AuditEvent.entity_id == event.id)
    ).scalars().all()
    assert len(events) == 1
    assert events[0].event_data["total_harvested_weight_kg"] == "4"


# =====================================================================
# Grading integration
# =====================================================================


@pytest.mark.integration
def test_grading_integration_lot_visible_and_gradable(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = build_vines_harvest_ready_scenario(db_session, tenant, user, farm, intervines_plant_count=2, grow_bag_count=1, grow_bag_capacity=2)
    event = _record(db_session, tenant, farm, user, s, [(s["grow_gutter_id"], "10.000")])
    detail = harvest_service.get_vines_harvest_event(db_session, tenant_id=tenant.id, farm_id=farm.id, harvest_event_id=event.id)

    # 1. Visible: appears in the SAME generic listing Grading's own source
    # picker consumes -- never a Vines-specific grading route.
    all_lots = harvest_service.list_produce_lots(db_session, tenant_id=tenant.id, farm_id=farm.id)
    assert any(lot.id == detail.produce_lot_id for lot in all_lots)

    # 2. Eligible: a real grading event can be recorded against it, subject
    # to the SAME generic quality/recall/crop-match rules as any other lot.
    crop_id = db_session.execute(
        select(harvest_service.CropBatch.workflow_id).where(harvest_service.CropBatch.id == s["batch"].id)
    ).scalar_one()
    from app.models.workflow import Workflow as WorkflowModel

    workflow_row = db_session.execute(select(WorkflowModel.crop_id).where(WorkflowModel.id == crop_id)).scalar_one()

    hall = location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, location_type_code="packing_hall",
        code=f"hall-{uuid.uuid4().hex[:6]}", name="Processing Hall", parent_location_id=None,
        greenhouse_classification=None, occupiable=False,
    )
    grade_definition = grade_definition_service.register_grade_definition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"grade-{uuid.uuid4().hex[:6]}", name="Premium", crop_id=workflow_row, variety_id=None, description=None,
    )
    grade_version = grade_definition_service.create_draft_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        grade_definition_id=grade_definition.id, spec_notes=None,
    )
    grade_definition_service.activate_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        grade_definition_id=grade_definition.id, version_id=grade_version.id,
        effective_time=s["harvest_time"] - timedelta(days=1),
    )

    grading_event = grading_service.record_grading(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        source_harvested_produce_lot_id=detail.produce_lot_id, processing_hall_location_id=hall.id,
        effective_time=s["harvest_time"] + timedelta(minutes=30), note=None,
        input_presented_weight_kg=Decimal("10.000"), input_presented_whole_unit_count=None,
        rejected_weight_kg=Decimal("0"), rejected_whole_unit_count=None,
        loss_weight_kg=Decimal("0"), loss_whole_unit_count=None,
        sample_weight_kg=Decimal("0"), sample_whole_unit_count=None,
        remainder_weight_kg=Decimal("2.000"), remainder_whole_unit_count=None,
        outputs=[
            {
                "grade_definition_version_id": grade_version.id, "code": f"GPL-{uuid.uuid4().hex[:8]}",
                "output_weight_kg": Decimal("8.000"), "output_whole_unit_count": None,
            }
        ],
    )
    assert grading_event.id is not None


# =====================================================================
# Traceability
# =====================================================================


@pytest.mark.integration
def test_traceability_grow_bag_lineage_resolves_to_seed_tray(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = build_vines_harvest_ready_scenario(db_session, tenant, user, farm, intervines_plant_count=2, grow_bag_count=1, grow_bag_capacity=2)
    event = _record(db_session, tenant, farm, user, s, [(s["grow_gutter_id"], "5.000")])
    detail = harvest_service.get_vines_harvest_event(db_session, tenant_id=tenant.id, farm_id=farm.id, harvest_event_id=event.id)

    line = detail.source_lines[0]
    assert line.harvest_location is not None
    assert line.harvest_location.gutter is not None
    assert line.harvest_location.greenhouse is not None
    assert len(line.grow_bags) == 1
    bag_id = line.grow_bags[0].id

    from app.services import vines_production_transfer_service as vpts

    bag_reads = vpts.list_vines_production_placement_grow_bags(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=s["batch"].id, gutter_id=s["grow_gutter_id"],
    )
    matching = next(b for b in bag_reads if b.grow_bag.id == bag_id)
    assert len(matching.grow_cubes) == 2
    assert all(c.source_seed_tray is not None for c in matching.grow_cubes)


# =====================================================================
# Correction
# =====================================================================


@pytest.mark.integration
def test_correction_void_then_replace(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = build_vines_harvest_ready_scenario(db_session, tenant, user, farm, intervines_plant_count=2, grow_bag_count=1, grow_bag_capacity=2)
    event = _record(db_session, tenant, farm, user, s, [(s["grow_gutter_id"], "10.000")])
    detail = harvest_service.get_vines_harvest_event(db_session, tenant_id=tenant.id, farm_id=farm.id, harvest_event_id=event.id)
    line_id = detail.source_lines[0].id

    corrected = harvest_service.correct_vines_harvest_source_line(
        db_session, tenant_id=tenant.id, farm_id=farm.id, harvest_event_id=event.id, harvest_source_line_id=line_id,
        actor_user_id=user.id, client_command_id=uuid.uuid4(), supersedes_correction_id=None, is_void=False,
        corrected_harvested_weight_kg=Decimal("9.000"), reason_code="scale_error", note="reweighed",
    )
    detail2 = harvest_service.get_vines_harvest_event(db_session, tenant_id=tenant.id, farm_id=farm.id, harvest_event_id=event.id)
    assert detail2.source_lines[0].current_harvested_weight_kg == Decimal("9.000")
    assert detail2.current_total_harvested_weight_kg == Decimal("9.000")
    assert detail2.original_total_harvested_weight_kg == Decimal("10.000")  # original immutable

    voided = harvest_service.correct_vines_harvest_source_line(
        db_session, tenant_id=tenant.id, farm_id=farm.id, harvest_event_id=event.id, harvest_source_line_id=line_id,
        actor_user_id=user.id, client_command_id=uuid.uuid4(), supersedes_correction_id=corrected.id, is_void=True,
        corrected_harvested_weight_kg=None, reason_code="mistake", note="wrong batch entirely",
    )
    detail3 = harvest_service.get_vines_harvest_event(db_session, tenant_id=tenant.id, farm_id=farm.id, harvest_event_id=event.id)
    assert detail3.source_lines[0].state == "VOID"
    assert detail3.current_total_harvested_weight_kg == Decimal("0")


@pytest.mark.integration
def test_correction_stale_supersedes_id_conflicts(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = build_vines_harvest_ready_scenario(db_session, tenant, user, farm, intervines_plant_count=2, grow_bag_count=1, grow_bag_capacity=2)
    event = _record(db_session, tenant, farm, user, s, [(s["grow_gutter_id"], "10.000")])
    detail = harvest_service.get_vines_harvest_event(db_session, tenant_id=tenant.id, farm_id=farm.id, harvest_event_id=event.id)
    line_id = detail.source_lines[0].id

    harvest_service.correct_vines_harvest_source_line(
        db_session, tenant_id=tenant.id, farm_id=farm.id, harvest_event_id=event.id, harvest_source_line_id=line_id,
        actor_user_id=user.id, client_command_id=uuid.uuid4(), supersedes_correction_id=None, is_void=False,
        corrected_harvested_weight_kg=Decimal("9.000"), reason_code="scale_error", note="reweighed",
    )
    with pytest.raises(HarvestCorrectionAlreadySupersededError):
        harvest_service.correct_vines_harvest_source_line(
            db_session, tenant_id=tenant.id, farm_id=farm.id, harvest_event_id=event.id, harvest_source_line_id=line_id,
            actor_user_id=user.id, client_command_id=uuid.uuid4(), supersedes_correction_id=None, is_void=False,
            corrected_harvested_weight_kg=Decimal("7.000"), reason_code="scale_error", note="reweighed again",
        )
