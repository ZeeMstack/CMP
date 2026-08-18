"""NURSERY-OPS-002B: the modern, INDIVIDUAL-SEEDLING-based Germination
outcome (`germination_outcome_service.py`, table `germination_outcome_snapshots`).
Reuses the existing, unmodified `observation_service.record_observation`
idempotency/concurrency/audit machinery verbatim -- this file tests only the
new outcome-specific validation, reads, and the legacy GerminationCheck
NULL-vs-missing-row error correction, not domain logic already covered by
test_germination_check.py/test_observation.py/test_nursery_ops.py."""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.germination_outcome_snapshot import GerminationOutcomeSnapshot
from app.models.movement import Movement
from app.schemas.germination_outcome import GerminationOutcomeCommandCreate, GerminationOutcomeIn
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
    crop_batch_service,
    crop_service,
    farm_setup_service,
    germination_outcome_service,
    germination_service,
    nursery_service,
    observation_service,
    production_system_service,
    seedling_entry_service,
    sowing_service,
    workflow_service,
)
from app.services.errors import (
    CropBatchNotFoundError,
    InvalidObservationEffectiveTimeError,
    ObservationCommandReusedWithDifferentPayloadError,
    ObservationValidationError,
)
from tests.conftest import ensure_seed_tray_specification


def _now():
    return datetime.now(timezone.utc)


# =====================================================================
# Scenario builders
# =====================================================================


def _build_modern_scenario(db_session, tenant, user, farm, *, suffix=None, tray_count=3):
    """Modern NURSERY-OPS-001 operator Sowing flow -- `sown_site_count`
    is always NULL, `seed_count` is always populated. This is the shape
    the frozen product decision requires the modern outcome to work with."""
    suffix = suffix or uuid.uuid4().hex[:8]
    crop = crop_service.register_crop(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"ICE-{suffix}",
        common_name="Iceberg Lettuce", scientific_name=None, crop_category="leafy_green",
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
        production_system_id=ps.id, code=f"WF-{suffix}", name="Iceberg Nursery",
    )
    version = workflow_service.create_draft_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id
    )
    seeding_stage = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="SEEDING", name="Seeding", display_order=0, stage_category="seeding",
        expected_duration_minutes=None, permitted_location_type_code=None,
        required_carrier_type_code="seed_tray", is_start=True, is_terminal=False,
    )
    complete_stage = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="COMPLETE", name="Complete", display_order=1, stage_category="completed",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=True,
    )
    workflow_service.add_transition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=seeding_stage.id, to_stage_id=complete_stage.id, code="ADVANCE-1", name="Advance 1",
    )
    workflow_service.publish_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id
    )
    seed_lot = sowing_service.register_seed_lot(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id,
        variety_id=variety.id, code=f"LOT-{suffix}", supplier_name=None, supplier_lot_reference=None,
        received_date=None, expiry_date=None,
    )
    setup = farm_setup_service.create_greenhouse_setup(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        payload=GreenhouseSetupCreate(
            code=f"NUR-{suffix}", name="Nursery", classification="nursery", client_command_id=uuid.uuid4(),
            nursery=NurserySetupConfig(seeding_station=NurserySectionConfig(code=f"SEED-{suffix}")),
        ),
    )
    structure = farm_setup_service.get_greenhouse_structure(
        db_session.connection(), tenant_id=tenant.id, farm_id=farm.id, greenhouse_id=setup.greenhouse_id,
    )
    seeding_station_id = structure.nursery_seeding_stations[0].id
    seed_tray_spec = ensure_seed_tray_specification(db_session, tenant_id=tenant.id, actor_user_id=user.id)
    carriers = [
        carrier_service.register_carrier(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            specification_id=seed_tray_spec.id, code=f"ST-{suffix}-{n:04d}", issued_date=None,
        )
        for n in range(1, tray_count + 1)
    ]
    event = nursery_service.sow_new_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        seed_lot_id=seed_lot.id, seeding_station_id=seeding_station_id, seeding_machine_id=None,
        effective_time=_now(), note=None,
        trays=[{"carrier_id": c.id, "seeds_sown": 200} for c in carriers],
    )
    assignments = sowing_service.list_batch_carriers(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=event.batch_id
    )
    assignment_by_carrier_code = {a.carrier.code: a.id for a in assignments}
    return {
        "batch_id": event.batch_id, "carriers": carriers,
        "assignment_ids": [assignment_by_carrier_code[c.code] for c in carriers],
        "sowing_event_id": event.id,
    }


def _build_legacy_scenario(db_session, tenant, user, farm, *, suffix=None, seed_count=210, sown_site_count=200):
    """Legacy generic Sowing path with an explicit, populated
    `sown_site_count` -- used only for the Seeds-vs-Sites distinction proof
    and the legacy-GerminationCheck-still-works regression."""
    suffix = suffix or uuid.uuid4().hex[:8]
    crop = crop_service.register_crop(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"ICE-{suffix}",
        common_name="Iceberg", scientific_name=None, crop_category="leafy_green",
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
    batch_created_time = _now() - timedelta(hours=1)
    sow_time = _now()
    batch = crop_batch_service.create_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"BATCH-{suffix}", workflow_id=workflow.id, effective_time=batch_created_time,
    )
    seed_lot = sowing_service.register_seed_lot(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id,
        variety_id=variety.id, code=f"LOT-{suffix}", supplier_name=None, supplier_lot_reference=None,
        received_date=None, expiry_date=None,
    )
    carrier = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        specification_id=ensure_seed_tray_specification(
            db_session, tenant_id=tenant.id, actor_user_id=user.id,
        ).id, code=f"ST-{suffix}-0001", issued_date=None,
    )
    sowing_service.sow_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=sow_time, note=None,
        lines=[
            {
                "carrier_id": carrier.id, "seed_lot_id": seed_lot.id, "sown_site_count": sown_site_count,
                "seed_count": seed_count, "line_note": None,
            }
        ],
    )
    assignments = sowing_service.list_batch_carriers(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id
    )
    return {
        "batch_id": batch.id, "carrier": carrier, "assignment_id": assignments[0].id,
        "batch_created_time": batch_created_time, "sow_time": sow_time,
    }


def _build_release_scenario(db_session, tenant, user, farm, *, suffix=None):
    """A Batch that advances Seeding -> Transplanting -> real
    `transplant_service.record_transplant`, releasing the source
    assignment -- used only by the temporal-assignment-validation tests.

    NURSERY-OPS-004A modernized `record_transplant` to require a real,
    SeedlingEntry-anchored source. To keep `sow_time + 2 days` ("mid_time",
    used by `test_historical_outcome_before_release_accepted_even_when_
    now_released`) a valid moment for a caller to record a fresh
    PROVISIONAL Germination outcome, this scenario's own internal
    Germination pipeline (needed only to satisfy `record_transplant`'s new
    precondition) is deliberately timed to complete AFTER mid_time -- a
    provisional outcome at or before an assignment's own latest COMPLETED
    outcome time is fine (`observation_service.record_observation` only
    rejects a provisional recorded AFTER a completed one), but one strictly
    after it is not, so the internal outcome/SeedlingEntry pipeline here
    runs at sow_time+3d/+4d, strictly after mid_time (sow_time+2d) and
    strictly before release_time (sow_time+5d, unchanged)."""
    suffix = suffix or uuid.uuid4().hex[:8]
    from app.services import transplant_service

    crop = crop_service.register_crop(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"ICE-{suffix}",
        common_name="Iceberg", scientific_name=None, crop_category="leafy_green",
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
    transplanting = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="TRANSPLANTING", name="Transplanting", display_order=1, stage_category="transplanting",
        expected_duration_minutes=None, permitted_location_type_code=None,
        required_carrier_type_code="cultivation_plate", is_start=False, is_terminal=False,
    )
    complete = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="COMPLETE", name="Complete", display_order=2, stage_category="completed",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=True,
    )
    t1 = workflow_service.add_transition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=seeding.id, to_stage_id=transplanting.id, code="ADVANCE-1", name="Advance 1",
    )
    workflow_service.add_transition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=transplanting.id, to_stage_id=complete.id, code="ADVANCE-2", name="Advance 2",
    )
    workflow_service.publish_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id
    )
    seed_lot = sowing_service.register_seed_lot(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id,
        variety_id=variety.id, code=f"LOT-{suffix}", supplier_name=None, supplier_lot_reference=None,
        received_date=None, expiry_date=None,
    )

    setup = farm_setup_service.create_greenhouse_setup(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        payload=GreenhouseSetupCreate(
            code=f"NUR-{suffix}", name="Nursery", classification="nursery", client_command_id=uuid.uuid4(),
            nursery=NurserySetupConfig(
                seeding_station=NurserySectionConfig(code=f"SEED-{suffix}"),
                germination_chamber=GerminationChamberSetupConfig(code=f"GC-{suffix}", trolley_capacity=None),
                seedling_tables=TableGeneratorConfig(
                    code_prefix=f"ST{suffix[:4]}", start=1, end=1, pad_width=2, capacity=1
                ),
            ),
        ),
    )
    structure = farm_setup_service.get_greenhouse_structure(
        db_session.connection(), tenant_id=tenant.id, farm_id=farm.id, greenhouse_id=setup.greenhouse_id,
    )
    seeding_station_id = structure.nursery_seeding_stations[0].id
    chamber_id = structure.nursery_germination_chamber.id
    table_id = structure.nursery_seedling.tables[0].id

    trolley = asset_service.register_asset(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        asset_type_code="germination_trolley", code=f"GT-{suffix}", name="Trolley", commissioned_date=None,
    )
    asset_service.generate_positions(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, asset_id=trolley.id,
        shelf_count=1, slots_per_shelf=1, shelf_prefix=f"SH-{suffix}-", slot_prefix="SL-",
        shelf_pad_width=2, slot_pad_width=2,
    )
    slot_id = db_session.execute(
        text("SELECT id FROM asset_positions WHERE asset_id = :aid AND position_kind = 'slot' ORDER BY code"),
        {"aid": trolley.id},
    ).scalar_one()

    carrier = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        specification_id=ensure_seed_tray_specification(
            db_session, tenant_id=tenant.id, actor_user_id=user.id,
        ).id, code=f"ST-{suffix}-0001", issued_date=None,
    )

    sow_time = _now() - timedelta(days=10)
    event = nursery_service.sow_new_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        seed_lot_id=seed_lot.id, seeding_station_id=seeding_station_id, seeding_machine_id=None,
        effective_time=sow_time, note=None, trays=[{"carrier_id": carrier.id, "seeds_sown": 200}],
    )
    batch_id = event.batch_id
    assignments = sowing_service.list_batch_carriers(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch_id
    )
    assignment_id = assignments[0].id

    germination_time = sow_time + timedelta(days=1)
    germination_service.place_trolley_in_chamber(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        trolley_id=trolley.id, chamber_id=chamber_id, effective_time=germination_time, reason=None,
    )
    germination_service.place_tray_in_slot(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        tray_id=carrier.id, trolley_id=trolley.id, slot_id=slot_id, effective_time=germination_time, reason=None,
    )

    # Strictly AFTER mid_time (sow_time+2d) -- see the docstring above.
    outcome_time = sow_time + timedelta(days=3)
    germination_outcome_service.record_germination_outcomes(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch_id,
        client_command_id=uuid.uuid4(), effective_time=outcome_time, note=None,
        outcomes=[
            {
                "batch_carrier_assignment_id": assignment_id, "normal_seedling_count": 190,
                "abnormal_seedling_count": 6, "assessment_complete": True, "note": None,
            }
        ],
    )

    entry_time = sow_time + timedelta(days=4)
    seedling_entry_service.record_seedling_entry(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        batch_carrier_assignment_id=assignment_id, destination_seedling_table_id=table_id,
        effective_time=entry_time, reason=None,
    )

    crop_batch_service.transition_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch_id,
        client_command_id=uuid.uuid4(), configured_transition_id=t1.id, effective_time=entry_time + timedelta(hours=1),
        reason=None,
    )
    destination_carrier = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        carrier_type_code="cultivation_plate", code=f"CP-{suffix}-0001", issued_date=None,
    )
    release_time = sow_time + timedelta(days=5)
    transplant_service.record_transplant(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch_id,
        client_command_id=uuid.uuid4(), effective_time=release_time, note=None,
        source_lines=[
            {
                "source_assignment_id": assignment_id, "transplant_damage_count": 0, "qc_rejection_count": 0,
                "sample_count": 0, "other_loss_count": 0, "other_loss_note": None, "note": None,
            }
        ],
        destination_lines=[
            {"destination_carrier_id": destination_carrier.id, "assigned_plant_count": 196, "note": None}
        ],
        allocations=[
            {
                "source_assignment_id": assignment_id, "destination_carrier_id": destination_carrier.id,
                "allocated_plant_count": 196,
            }
        ],
    )
    return {
        "batch_id": batch_id, "assignment_id": assignment_id, "sow_time": sow_time, "release_time": release_time,
    }


def _outcome(assignment_id, **overrides):
    defaults = dict(
        batch_carrier_assignment_id=assignment_id, normal_seedling_count=190, abnormal_seedling_count=6,
        assessment_complete=False, note=None,
    )
    defaults.update(overrides)
    return defaults


def _record(db_session, tenant, user, farm, batch_id, outcomes, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch_id,
        client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
    )
    defaults.update(overrides)
    return germination_outcome_service.record_germination_outcomes(db_session, outcomes=outcomes, **defaults)


# =====================================================================
# 1. Modern sowing compatibility
# =====================================================================


@pytest.mark.integration
def test_modern_sowing_flow_allows_germination_outcome(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_modern_scenario(db_session, tenant, user, farm)
    event = _record(db_session, tenant, user, farm, s["batch_id"], [_outcome(s["assignment_ids"][0])])
    assert db_session.execute(select(func.count()).select_from(GerminationOutcomeSnapshot)).scalar_one() == 1
    assert event.batch_id == s["batch_id"]


@pytest.mark.integration
def test_legacy_site_check_on_modern_tray_gets_truthful_distinct_error(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_modern_scenario(db_session, tenant, user, farm)
    with pytest.raises(ObservationValidationError, match="requires a recorded sown_site_count"):
        observation_service.record_observation(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch_id"],
            client_command_id=uuid.uuid4(), effective_time=_now(), note=None, values=[],
            germination_checks=[
                {
                    "batch_carrier_assignment_id": s["assignment_ids"][0], "inspected_site_count": 50,
                    "normal_germinated_site_count": 40, "abnormal_germinated_site_count": 5, "failed_site_count": 5,
                }
            ],
        )


@pytest.mark.integration
def test_missing_sowing_line_still_raises_original_case_a_message(db_session, active_context_with_farm) -> None:
    """CASE A (no SowingEventLine row at all) must remain distinct from
    CASE B (row exists, sown_site_count is NULL) -- proven using a
    transplant-opened assignment (a cultivation_plate assignment has NO
    SowingEventLine row at all, unlike every sowing-opened assignment,
    which always has exactly one) -- the one realistic way CASE A is
    actually reachable through the service layer."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_release_scenario(db_session, tenant, user, farm)
    plate_assignment_id = db_session.execute(
        text(
            "SELECT bca.id FROM batch_carrier_assignments bca "
            "JOIN carriers c ON c.id = bca.carrier_id JOIN carrier_types ct ON ct.id = c.carrier_type_id "
            "WHERE bca.batch_id = :bid AND ct.code = 'cultivation_plate'"
        ),
        {"bid": s["batch_id"]},
    ).scalar_one()
    with pytest.raises(ObservationValidationError, match=r"^no sowing line found"):
        observation_service.record_observation(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch_id"],
            client_command_id=uuid.uuid4(), effective_time=s["release_time"] + timedelta(days=1), note=None,
            values=[],
            germination_checks=[
                {
                    "batch_carrier_assignment_id": plate_assignment_id, "inspected_site_count": 1,
                    "normal_germinated_site_count": 1, "abnormal_germinated_site_count": 0, "failed_site_count": 0,
                }
            ],
        )


# =====================================================================
# 2. Seeds vs. Sites remain distinct
# =====================================================================


@pytest.mark.integration
def test_seeds_210_sown_sites_200_outcome_uses_seed_count_not_sites(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_legacy_scenario(db_session, tenant, user, farm, seed_count=210, sown_site_count=200)
    event = _record(
        db_session, tenant, user, farm, s["batch_id"],
        [_outcome(s["assignment_id"], normal_seedling_count=190, abnormal_seedling_count=8, assessment_complete=True)],
    )
    read = germination_outcome_service.describe_germination_outcome_command(
        db_session, tenant_id=tenant.id, farm_id=farm.id, event=event
    )
    snap = read.snapshots[0]
    assert snap.living_seedling_count == 198
    # 198 living is valid against seed_count=210, and would ALSO have been
    # valid against sown_site_count=200 in this particular case -- the real
    # proof is the boundary test below, where only seed_count as the anchor
    # permits a value between the two.
    current = germination_outcome_service.get_current_germination_outcomes(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=s["batch_id"]
    )
    tray = current.trays[0]
    assert tray.seeds_sown == 210
    assert tray.sown_site_count == 200
    assert tray.current_seed_to_living_gap_count == 210 - 198


@pytest.mark.integration
def test_living_count_between_sown_sites_and_seed_count_only_valid_against_seed_count(
    db_session, active_context_with_farm
) -> None:
    """Proves the anchor is truly seed_count, not sown_site_count: 205 living
    exceeds Sown Sites (200) but not Seeds Sown (210) -- must succeed."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_legacy_scenario(db_session, tenant, user, farm, seed_count=210, sown_site_count=200)
    event = _record(
        db_session, tenant, user, farm, s["batch_id"],
        [_outcome(s["assignment_id"], normal_seedling_count=200, abnormal_seedling_count=5)],
    )
    assert event is not None


@pytest.mark.integration
def test_living_yield_percentage_uses_seeds_not_sites(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_legacy_scenario(db_session, tenant, user, farm, seed_count=200, sown_site_count=200)
    _record(db_session, tenant, user, farm, s["batch_id"], [_outcome(s["assignment_id"], normal_seedling_count=190, abnormal_seedling_count=6)])
    current = germination_outcome_service.get_current_germination_outcomes(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=s["batch_id"]
    )
    tray = current.trays[0]
    assert tray.living_seedling_yield_percent == Decimal("98")


# =====================================================================
# 3. Living quantity (normal + abnormal, abnormal never a loss)
# =====================================================================


@pytest.mark.integration
def test_normal_190_abnormal_6_living_196(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_modern_scenario(db_session, tenant, user, farm)
    event = _record(db_session, tenant, user, farm, s["batch_id"], [_outcome(s["assignment_ids"][0], normal_seedling_count=190, abnormal_seedling_count=6)])
    read = germination_outcome_service.describe_germination_outcome_command(db_session, tenant_id=tenant.id, farm_id=farm.id, event=event)
    assert read.snapshots[0].living_seedling_count == 196


@pytest.mark.integration
def test_abnormal_included_in_authoritative_living_quantity(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_modern_scenario(db_session, tenant, user, farm)
    _record(db_session, tenant, user, farm, s["batch_id"], [_outcome(s["assignment_ids"][0], normal_seedling_count=190, abnormal_seedling_count=6, assessment_complete=True)])
    current = germination_outcome_service.get_current_germination_outcomes(db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=s["batch_id"])
    assert current.trays[0].authoritative_living_seedling_count == 196


@pytest.mark.integration
def test_no_loss_table_or_row_created_for_abnormal(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_modern_scenario(db_session, tenant, user, farm)
    tables_before = set(
        db_session.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")).scalars()
    )
    _record(db_session, tenant, user, farm, s["batch_id"], [_outcome(s["assignment_ids"][0], normal_seedling_count=190, abnormal_seedling_count=6)])
    tables_after = set(
        db_session.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")).scalars()
    )
    assert tables_before == tables_after
    assert not any("loss" in t for t in tables_after)


# =====================================================================
# 4. Snapshot semantics (point-in-time, not additive)
# =====================================================================


@pytest.mark.integration
def test_repeated_snapshots_latest_wins_not_additive(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_modern_scenario(db_session, tenant, user, farm)
    aid = s["assignment_ids"][0]
    # Sequential real timestamps (not artificial past offsets): the modern
    # scenario's Batch is created "now", so an offset like `now - 3 days`
    # would precede the Batch's own creation time. Real elapsed wall-clock
    # time between statements is enough to keep these strictly increasing.
    day4 = _now()
    _record(db_session, tenant, user, farm, s["batch_id"], [_outcome(aid, normal_seedling_count=150, abnormal_seedling_count=5)], effective_time=day4)
    day5 = _now()
    _record(db_session, tenant, user, farm, s["batch_id"], [_outcome(aid, normal_seedling_count=185, abnormal_seedling_count=7)], effective_time=day5)
    day7 = _now()
    _record(db_session, tenant, user, farm, s["batch_id"], [_outcome(aid, normal_seedling_count=190, abnormal_seedling_count=6)], effective_time=day7)

    current = germination_outcome_service.get_current_germination_outcomes(db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=s["batch_id"])
    tray = current.trays[0]
    assert tray.current_living_seedling_count == 196  # day7's 190+6, NOT summed
    assert tray.historical_snapshot_count == 3


# =====================================================================
# 5. Completion / authoritative handoff
# =====================================================================


@pytest.mark.integration
def test_completed_snapshot_establishes_authoritative_handoff(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_modern_scenario(db_session, tenant, user, farm)
    aid = s["assignment_ids"][0]
    _record(db_session, tenant, user, farm, s["batch_id"], [_outcome(aid, normal_seedling_count=190, abnormal_seedling_count=6, assessment_complete=True)])
    current = germination_outcome_service.get_current_germination_outcomes(db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=s["batch_id"])
    tray = current.trays[0]
    assert tray.assessment_complete is True
    assert tray.authoritative_living_seedling_count == 196


@pytest.mark.integration
def test_no_completed_snapshot_authoritative_quantity_unresolved(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_modern_scenario(db_session, tenant, user, farm)
    _record(db_session, tenant, user, farm, s["batch_id"], [_outcome(s["assignment_ids"][0], assessment_complete=False)])
    current = germination_outcome_service.get_current_germination_outcomes(db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=s["batch_id"])
    assert current.trays[0].authoritative_living_seedling_count is None


@pytest.mark.integration
def test_newer_completed_snapshot_supersedes_prior_completed(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_modern_scenario(db_session, tenant, user, farm)
    aid = s["assignment_ids"][0]
    t1 = _now()
    _record(db_session, tenant, user, farm, s["batch_id"], [_outcome(aid, normal_seedling_count=190, abnormal_seedling_count=6, assessment_complete=True)], effective_time=t1)
    t2 = _now()
    _record(db_session, tenant, user, farm, s["batch_id"], [_outcome(aid, normal_seedling_count=185, abnormal_seedling_count=4, assessment_complete=True)], effective_time=t2)
    current = germination_outcome_service.get_current_germination_outcomes(db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=s["batch_id"])
    assert current.trays[0].authoritative_living_seedling_count == 189


@pytest.mark.integration
def test_newer_provisional_after_completion_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_modern_scenario(db_session, tenant, user, farm)
    aid = s["assignment_ids"][0]
    t1 = _now()
    _record(db_session, tenant, user, farm, s["batch_id"], [_outcome(aid, assessment_complete=True)], effective_time=t1)
    t2 = _now()
    with pytest.raises(ObservationValidationError, match="already has a completed Germination outcome"):
        _record(db_session, tenant, user, farm, s["batch_id"], [_outcome(aid, assessment_complete=False)], effective_time=t2)


@pytest.mark.integration
def test_historical_provisional_before_completion_effective_time_allowed(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_modern_scenario(db_session, tenant, user, farm)
    aid = s["assignment_ids"][0]
    # t_backfill captured first (earlier real timestamp), t_complete second
    # (later) -- but RECORDED in the opposite order, so the completed
    # snapshot's effective_time is genuinely later than the backfilled
    # provisional's, exactly matching the "historical backfill" case.
    t_backfill = _now()
    t_complete = _now()
    _record(db_session, tenant, user, farm, s["batch_id"], [_outcome(aid, assessment_complete=True)], effective_time=t_complete)
    event = _record(
        db_session, tenant, user, farm, s["batch_id"],
        [_outcome(aid, normal_seedling_count=150, abnormal_seedling_count=5, assessment_complete=False)],
        effective_time=t_backfill,
    )
    assert event is not None
    assert db_session.execute(select(func.count()).select_from(GerminationOutcomeSnapshot)).scalar_one() == 2


# =====================================================================
# 6. Temporal assignment validation
# =====================================================================


@pytest.mark.integration
def test_historical_outcome_before_release_accepted_even_when_now_released(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_release_scenario(db_session, tenant, user, farm)
    mid_time = s["sow_time"] + timedelta(days=2)
    assert mid_time < s["release_time"]
    event = _record(db_session, tenant, user, farm, s["batch_id"], [_outcome(s["assignment_id"])], effective_time=mid_time)
    assert event is not None


@pytest.mark.integration
def test_outcome_before_assignment_start_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    # Uses the legacy (single-stage, no transplanting transition) scenario,
    # whose active stage run's own entry time is the Batch's creation time
    # -- earlier than Sowing/assignment start -- so a value between the two
    # violates ONLY the assignment-specific check, not the current-stage-run
    # entry check `record_observation` runs first.
    s = _build_legacy_scenario(db_session, tenant, user, farm)
    too_early = s["sow_time"] - timedelta(minutes=30)
    with pytest.raises(InvalidObservationEffectiveTimeError, match="precedes assignment"):
        _record(db_session, tenant, user, farm, s["batch_id"], [_outcome(s["assignment_id"])], effective_time=too_early)


@pytest.mark.integration
def test_outcome_at_or_after_release_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_release_scenario(db_session, tenant, user, farm)
    with pytest.raises(InvalidObservationEffectiveTimeError, match="at or after"):
        _record(db_session, tenant, user, farm, s["batch_id"], [_outcome(s["assignment_id"])], effective_time=s["release_time"])


# =====================================================================
# 7. Quantity integrity
# =====================================================================


def test_negative_normal_rejected() -> None:
    with pytest.raises(ValidationError):
        GerminationOutcomeIn(batch_carrier_assignment_id=uuid.uuid4(), normal_seedling_count=-1, abnormal_seedling_count=0, assessment_complete=False)


def test_negative_abnormal_rejected() -> None:
    with pytest.raises(ValidationError):
        GerminationOutcomeIn(batch_carrier_assignment_id=uuid.uuid4(), normal_seedling_count=0, abnormal_seedling_count=-1, assessment_complete=False)


@pytest.mark.integration
def test_normal_plus_abnormal_exceeds_seed_count_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_modern_scenario(db_session, tenant, user, farm)
    with pytest.raises(ObservationValidationError, match="cannot exceed"):
        _record(db_session, tenant, user, farm, s["batch_id"], [_outcome(s["assignment_ids"][0], normal_seedling_count=195, abnormal_seedling_count=10)])


@pytest.mark.integration
def test_completed_snapshot_with_living_less_than_seed_count_valid(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_modern_scenario(db_session, tenant, user, farm)
    event = _record(db_session, tenant, user, farm, s["batch_id"], [_outcome(s["assignment_ids"][0], normal_seedling_count=190, abnormal_seedling_count=6, assessment_complete=True)])
    assert event is not None  # 196 living < 200 seed_count, no forced equality


@pytest.mark.integration
def test_no_automatic_non_germination_field_exists(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_modern_scenario(db_session, tenant, user, farm)
    event = _record(db_session, tenant, user, farm, s["batch_id"], [_outcome(s["assignment_ids"][0], normal_seedling_count=190, abnormal_seedling_count=6, assessment_complete=True)])
    read = germination_outcome_service.describe_germination_outcome_command(db_session, tenant_id=tenant.id, farm_id=farm.id, event=event)
    dumped = read.model_dump()
    assert "non_germination" not in str(dumped).lower()
    assert "loss" not in str(dumped).lower()


# =====================================================================
# 8. Multi-tray / Batch aggregation
# =====================================================================


@pytest.mark.integration
def test_multiple_trays_independent_outcomes(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_modern_scenario(db_session, tenant, user, farm, tray_count=3)
    _record(
        db_session, tenant, user, farm, s["batch_id"],
        [
            _outcome(s["assignment_ids"][0], normal_seedling_count=190, abnormal_seedling_count=6, assessment_complete=True),
            _outcome(s["assignment_ids"][1], normal_seedling_count=180, abnormal_seedling_count=10, assessment_complete=True),
        ],
    )
    current = germination_outcome_service.get_current_germination_outcomes(db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=s["batch_id"])
    by_id = {t.batch_carrier_assignment_id: t for t in current.trays}
    assert by_id[s["assignment_ids"][0]].authoritative_living_seedling_count == 196
    assert by_id[s["assignment_ids"][1]].authoritative_living_seedling_count == 190
    assert by_id[s["assignment_ids"][2]].authoritative_living_seedling_count is None


@pytest.mark.integration
def test_batch_aggregate_transparently_incomplete_when_one_tray_unresolved(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_modern_scenario(db_session, tenant, user, farm, tray_count=3)
    _record(
        db_session, tenant, user, farm, s["batch_id"],
        [
            _outcome(s["assignment_ids"][0], normal_seedling_count=190, abnormal_seedling_count=6, assessment_complete=True),
            _outcome(s["assignment_ids"][1], normal_seedling_count=180, abnormal_seedling_count=10, assessment_complete=True),
        ],
    )
    current = germination_outcome_service.get_current_germination_outcomes(db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=s["batch_id"])
    assert current.authoritative_living_seedling_total == 386
    assert current.completed_tray_count == 2
    assert current.unresolved_tray_count == 1
    assert current.all_resolved is False


# =====================================================================
# 9. Idempotency
# =====================================================================


@pytest.mark.integration
def test_exact_replay_returns_original(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_modern_scenario(db_session, tenant, user, farm)
    ccid = uuid.uuid4()
    eff = _now()
    first = _record(db_session, tenant, user, farm, s["batch_id"], [_outcome(s["assignment_ids"][0])], client_command_id=ccid, effective_time=eff)
    second = _record(db_session, tenant, user, farm, s["batch_id"], [_outcome(s["assignment_ids"][0])], client_command_id=ccid, effective_time=eff)
    assert first.id == second.id
    assert db_session.execute(select(func.count()).select_from(GerminationOutcomeSnapshot)).scalar_one() == 1


@pytest.mark.integration
def test_same_command_id_different_payload_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_modern_scenario(db_session, tenant, user, farm)
    ccid = uuid.uuid4()
    eff = _now()
    _record(db_session, tenant, user, farm, s["batch_id"], [_outcome(s["assignment_ids"][0], normal_seedling_count=190)], client_command_id=ccid, effective_time=eff)
    with pytest.raises(ObservationCommandReusedWithDifferentPayloadError):
        _record(db_session, tenant, user, farm, s["batch_id"], [_outcome(s["assignment_ids"][0], normal_seedling_count=185)], client_command_id=ccid, effective_time=eff)


# =====================================================================
# 10. Immutability
# =====================================================================


@pytest.mark.integration
def test_direct_update_and_delete_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_modern_scenario(db_session, tenant, user, farm)
    _record(db_session, tenant, user, farm, s["batch_id"], [_outcome(s["assignment_ids"][0])])
    row = db_session.execute(select(GerminationOutcomeSnapshot)).scalars().first()

    with pytest.raises(DBAPIError):
        db_session.execute(text("UPDATE germination_outcome_snapshots SET normal_seedling_count = 999 WHERE id = :id"), {"id": row.id})
        db_session.flush()
    db_session.rollback()

    with pytest.raises(DBAPIError):
        db_session.execute(text("DELETE FROM germination_outcome_snapshots WHERE id = :id"), {"id": row.id})
        db_session.flush()
    db_session.rollback()


# =====================================================================
# 11. DB direct-write integrity
# =====================================================================


@pytest.mark.integration
def test_direct_write_assignment_from_other_batch_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s1 = _build_modern_scenario(db_session, tenant, user, farm)
    s2 = _build_modern_scenario(db_session, tenant, user, farm)
    event = _record(db_session, tenant, user, farm, s1["batch_id"], [_outcome(s1["assignment_ids"][0])])
    with pytest.raises(DBAPIError, match="does not belong to this observation event"):
        db_session.execute(
            text(
                "INSERT INTO germination_outcome_snapshots "
                "(id, tenant_id, farm_id, observation_event_id, batch_carrier_assignment_id, "
                "normal_seedling_count, abnormal_seedling_count, assessment_complete) "
                "VALUES (gen_random_uuid(), :tid, :fid, :eid, :aid, 10, 0, false)"
            ),
            {"tid": tenant.id, "fid": farm.id, "eid": event.id, "aid": s2["assignment_ids"][0]},
        )
    db_session.rollback()


@pytest.mark.integration
def test_direct_write_non_seed_tray_assignment_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    from app.services import batch_derivation_service, transplant_service

    s = _build_release_scenario(db_session, tenant, user, farm)
    # the destination cultivation_plate assignment (opened by the transplant
    # in _build_release_scenario) is NOT a seed_tray.
    plate_assignment = db_session.execute(
        text(
            "SELECT bca.id FROM batch_carrier_assignments bca "
            "JOIN carriers c ON c.id = bca.carrier_id JOIN carrier_types ct ON ct.id = c.carrier_type_id "
            "WHERE bca.batch_id = :bid AND ct.code = 'cultivation_plate'"
        ),
        {"bid": s["batch_id"]},
    ).scalar_one()
    event = observation_service.record_observation(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch_id"],
        client_command_id=uuid.uuid4(), effective_time=s["release_time"] + timedelta(days=1), note=None,
        values=[
            {
                "observation_definition_id": _register_dummy_definition(db_session, tenant, user),
                "batch_carrier_assignment_id": None, "value_integer": 1, "value_decimal": None,
                "value_boolean": None, "value_text": None, "note": None,
            }
        ],
        germination_checks=[], germination_outcomes=[],
    )
    with pytest.raises(DBAPIError, match="must be a seed_tray carrier"):
        db_session.execute(
            text(
                "INSERT INTO germination_outcome_snapshots "
                "(id, tenant_id, farm_id, observation_event_id, batch_carrier_assignment_id, "
                "normal_seedling_count, abnormal_seedling_count, assessment_complete) "
                "VALUES (gen_random_uuid(), :tid, :fid, :eid, :aid, 10, 0, false)"
            ),
            {"tid": tenant.id, "fid": farm.id, "eid": event.id, "aid": plate_assignment},
        )
    db_session.rollback()


def _register_dummy_definition(db_session, tenant, user):
    definition = observation_service.register_observation_definition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"DUMMY-{uuid.uuid4().hex[:8]}", name="Dummy",
        description=None, value_type="integer", unit=None, target_scope="crop_batch", min_value=None, max_value=None,
    )
    return definition.id


@pytest.mark.integration
def test_direct_write_count_above_seed_count_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_modern_scenario(db_session, tenant, user, farm)
    event = observation_service.record_observation(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch_id"],
        client_command_id=uuid.uuid4(), effective_time=_now(), note=None, values=[], germination_checks=[],
        germination_outcomes=[_outcome(s["assignment_ids"][1], normal_seedling_count=100, abnormal_seedling_count=50)],
    )
    with pytest.raises(DBAPIError, match="cannot exceed"):
        db_session.execute(
            text(
                "INSERT INTO germination_outcome_snapshots "
                "(id, tenant_id, farm_id, observation_event_id, batch_carrier_assignment_id, "
                "normal_seedling_count, abnormal_seedling_count, assessment_complete) "
                "VALUES (gen_random_uuid(), :tid, :fid, :eid, :aid, 195, 10, false)"
            ),
            {"tid": tenant.id, "fid": farm.id, "eid": event.id, "aid": s["assignment_ids"][0]},
        )
    db_session.rollback()


@pytest.mark.integration
def test_direct_write_newer_provisional_after_completion_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_modern_scenario(db_session, tenant, user, farm)
    aid = s["assignment_ids"][0]
    t1 = _now()
    _record(db_session, tenant, user, farm, s["batch_id"], [_outcome(aid, assessment_complete=True)], effective_time=t1)
    t2 = _now()
    event2 = observation_service.record_observation(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch_id"],
        client_command_id=uuid.uuid4(), effective_time=t2, note=None, values=[], germination_checks=[],
        germination_outcomes=[_outcome(s["assignment_ids"][1])],
    )
    with pytest.raises(DBAPIError, match="already has a completed Germination outcome"):
        db_session.execute(
            text(
                "INSERT INTO germination_outcome_snapshots "
                "(id, tenant_id, farm_id, observation_event_id, batch_carrier_assignment_id, "
                "normal_seedling_count, abnormal_seedling_count, assessment_complete) "
                "VALUES (gen_random_uuid(), :tid, :fid, :eid, :aid, 100, 0, false)"
            ),
            {"tid": tenant.id, "fid": farm.id, "eid": event2.id, "aid": aid},
        )
    db_session.rollback()


# =====================================================================
# 12. No side effects
# =====================================================================


@pytest.mark.integration
def test_batch_carrier_assignment_unchanged(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_modern_scenario(db_session, tenant, user, farm)
    aid = s["assignment_ids"][0]
    before = db_session.execute(select(BatchCarrierAssignment).where(BatchCarrierAssignment.id == aid)).scalar_one()
    before_snapshot = (before.id, before.batch_id, before.released_effective_time, before.opening_sowing_event_id)
    _record(db_session, tenant, user, farm, s["batch_id"], [_outcome(aid, assessment_complete=True)])
    db_session.refresh(before)
    after_snapshot = (before.id, before.batch_id, before.released_effective_time, before.opening_sowing_event_id)
    assert before_snapshot == after_snapshot


@pytest.mark.integration
def test_occupancy_and_movement_unchanged(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_modern_scenario(db_session, tenant, user, farm)
    movement_count_before = db_session.execute(select(func.count()).select_from(Movement)).scalar_one()
    _record(db_session, tenant, user, farm, s["batch_id"], [_outcome(s["assignment_ids"][0], assessment_complete=True)])
    movement_count_after = db_session.execute(select(func.count()).select_from(Movement)).scalar_one()
    assert movement_count_before == movement_count_after


@pytest.mark.integration
def test_no_batch_derivation_or_transplant_created(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_modern_scenario(db_session, tenant, user, farm)
    counts_before = db_session.execute(
        text("SELECT (SELECT count(*) FROM transplant_events), (SELECT count(*) FROM batch_derivation_events)")
    ).first()
    _record(db_session, tenant, user, farm, s["batch_id"], [_outcome(s["assignment_ids"][0], assessment_complete=True)])
    counts_after = db_session.execute(
        text("SELECT (SELECT count(*) FROM transplant_events), (SELECT count(*) FROM batch_derivation_events)")
    ).first()
    assert counts_before == counts_after


@pytest.mark.integration
def test_no_workflow_stage_transition(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_modern_scenario(db_session, tenant, user, farm)
    run_before = db_session.execute(
        text("SELECT id, workflow_stage_id FROM batch_stage_runs WHERE batch_id = :bid AND exited_effective_time IS NULL"),
        {"bid": s["batch_id"]},
    ).first()
    _record(db_session, tenant, user, farm, s["batch_id"], [_outcome(s["assignment_ids"][0], assessment_complete=True)])
    run_after = db_session.execute(
        text("SELECT id, workflow_stage_id FROM batch_stage_runs WHERE batch_id = :bid AND exited_effective_time IS NULL"),
        {"bid": s["batch_id"]},
    ).first()
    assert run_before == run_after


# =====================================================================
# 13. Authorization / tenant isolation
# =====================================================================


@pytest.mark.integration
def test_write_permission_requires_observation_entry_manage(db_session) -> None:
    from app.core.auth import TenantContext
    from app.core.permissions import Permission, has_permission

    for role in ("operator", "production_supervisor", "head_grower", "qc_officer", "tenant_admin"):
        ctx = TenantContext(tenant_id=uuid.uuid4(), user_id=uuid.uuid4(), role_code=role)
        assert has_permission(ctx, Permission.OBSERVATION_ENTRY_MANAGE), role
    storekeeper_ctx = TenantContext(tenant_id=uuid.uuid4(), user_id=uuid.uuid4(), role_code="storekeeper")
    assert not has_permission(storekeeper_ctx, Permission.OBSERVATION_ENTRY_MANAGE)


@pytest.mark.integration
def test_write_http_requires_observation_entry_manage(client, db_session) -> None:
    from app.services import farm_service, membership_service, tenant_service, user_service

    suffix = uuid.uuid4().hex[:8]
    tenant = tenant_service.create_tenant(db_session, code=f"go-authz-{suffix}", name="GO Authz Tenant")
    user = user_service.create_user(
        db_session, oidc_issuer="go-authz", oidc_subject=suffix, email=f"{suffix}@example.com", display_name="GO Authz",
    )
    membership_service.add_membership(db_session, tenant_id=tenant.id, user_id=user.id, role_code="storekeeper", actor_user_id=None)
    farm = farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    headers = {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(user.id)}
    db_session.commit()

    resp = client.post(
        f"/farms/{farm.id}/crop-batches/{uuid.uuid4()}/germination-outcomes", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now().isoformat(),
            "outcomes": [
                {"batch_carrier_assignment_id": str(uuid.uuid4()), "normal_seedling_count": 1, "abnormal_seedling_count": 0, "assessment_complete": False}
            ],
        },
    )
    assert resp.status_code == 403


@pytest.mark.integration
def test_read_http_requires_observation_read(client, db_session) -> None:
    from app.services import farm_service, membership_service, tenant_service, user_service

    suffix = uuid.uuid4().hex[:8]
    tenant = tenant_service.create_tenant(db_session, code=f"go-read-{suffix}", name="GO Read Tenant")
    user = user_service.create_user(
        db_session, oidc_issuer="go-read", oidc_subject=suffix, email=f"{suffix}@example.com", display_name="GO Read",
    )
    membership_service.add_membership(db_session, tenant_id=tenant.id, user_id=user.id, role_code="operator", actor_user_id=None)
    farm = farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    headers = {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(user.id)}
    db_session.commit()
    s = _build_modern_scenario(db_session, tenant, user, farm)
    db_session.commit()

    resp = client.get(f"/farms/{farm.id}/crop-batches/{s['batch_id']}/germination-outcomes/current", headers=headers)
    assert resp.status_code == 200

    no_membership_headers = {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(uuid.uuid4())}
    resp2 = client.get(f"/farms/{farm.id}/crop-batches/{s['batch_id']}/germination-outcomes/current", headers=no_membership_headers)
    assert resp2.status_code in (401, 403)


@pytest.mark.integration
def test_cross_tenant_batch_read_is_404(client, db_session) -> None:
    from app.services import farm_service, membership_service, tenant_service, user_service

    suffix = uuid.uuid4().hex[:8]
    tenant_a = tenant_service.create_tenant(db_session, code=f"go-iso-a-{suffix}", name="A")
    user_a = user_service.create_user(db_session, oidc_issuer="go-iso-a", oidc_subject=suffix, email=f"a-{suffix}@example.com", display_name="A")
    membership_service.add_membership(db_session, tenant_id=tenant_a.id, user_id=user_a.id, role_code="tenant_admin", actor_user_id=None)
    farm_a = farm_service.create_farm(
        db_session, tenant_id=tenant_a.id, actor_user_id=user_a.id, code=f"farm-a-{suffix}", name="Farm A",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    s = _build_modern_scenario(db_session, tenant_a, user_a, farm_a, suffix=suffix)

    tenant_b = tenant_service.create_tenant(db_session, code=f"go-iso-b-{suffix}", name="B")
    user_b = user_service.create_user(db_session, oidc_issuer="go-iso-b", oidc_subject=suffix, email=f"b-{suffix}@example.com", display_name="B")
    membership_service.add_membership(db_session, tenant_id=tenant_b.id, user_id=user_b.id, role_code="tenant_admin", actor_user_id=None)
    headers_b = {"X-Dev-Tenant-Id": str(tenant_b.id), "X-Dev-User-Id": str(user_b.id)}
    db_session.commit()

    resp = client.get(f"/farms/{farm_a.id}/crop-batches/{s['batch_id']}/germination-outcomes/current", headers=headers_b)
    assert resp.status_code == 404


# =====================================================================
# 14. Concurrency
# =====================================================================


def _build_committed_scenario(test_engine, *, suffix):
    from sqlalchemy.orm import Session

    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        from app.services import farm_service, membership_service, tenant_service, user_service

        tenant = tenant_service.create_tenant(session, code=f"go-race-{suffix}", name="GO Race Tenant")
        user = user_service.create_user(session, oidc_issuer="go-race", oidc_subject=suffix, email=f"go-race-{suffix}@example.com", display_name="GO Race User")
        membership_service.add_membership(session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None)
        farm = farm_service.create_farm(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="GO Race Farm",
            country_code="AE", city_region=None, timezone="Asia/Dubai",
        )
        s = _build_modern_scenario(session, tenant, user, farm, suffix=suffix, tray_count=2)
        session.commit()
        result = {"tenant_id": tenant.id, "farm_id": farm.id, "user_id": user.id, "batch_id": s["batch_id"], "assignment_ids": s["assignment_ids"]}
    finally:
        session.close()
        conn.close()
    return result


def _cleanup_committed_scenario(test_engine, tenant_id) -> None:
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET session_replication_role = replica"))
        for table in (
            "germination_outcome_snapshots", "observation_events", "sowing_event_lines", "sowing_events",
            "batch_carrier_assignments", "batch_stage_transitions", "batch_stage_runs", "crop_batches",
            "carrier_specifications", "carriers", "seed_lots", "locations", "workflow_transitions",
            "workflow_stages", "workflow_versions", "workflows", "production_systems", "varieties", "crops",
            "audit_events", "farms", "tenant_memberships",
        ):
            conn.execute(text(f"DELETE FROM {table} WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})
        conn.execute(text("SET session_replication_role = DEFAULT"))
        trans.commit()
    finally:
        conn.close()


def _worker(test_engine, results, name, barrier, *, kwargs):
    from sqlalchemy.orm import Session

    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        barrier.wait(timeout=10)
        event = germination_outcome_service.record_germination_outcomes(session, **kwargs)
        results[name] = ("ok", event.id)
    except ObservationCommandReusedWithDifferentPayloadError as exc:
        results[name] = ("conflict", str(exc))
    except ObservationValidationError as exc:
        results[name] = ("rejected", str(exc))
    except Exception as exc:  # pragma: no cover - surfaced via assertion
        results[name] = ("error", repr(exc))
    finally:
        session.close()
        conn.close()


@pytest.mark.integration
def test_concurrent_same_command_id_same_payload_collapses(test_engine) -> None:
    import threading

    scenario = _build_committed_scenario(test_engine, suffix=uuid.uuid4().hex[:8])
    try:
        ccid = uuid.uuid4()
        eff = _now()
        kwargs = dict(
            tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            batch_id=scenario["batch_id"], client_command_id=ccid, effective_time=eff, note=None,
            outcomes=[_outcome(scenario["assignment_ids"][0])],
        )
        barrier = threading.Barrier(2)
        results: dict = {}
        t_a = threading.Thread(target=_worker, args=(test_engine, results, "a", barrier), kwargs={"kwargs": kwargs})
        t_b = threading.Thread(target=_worker, args=(test_engine, results, "b", barrier), kwargs={"kwargs": kwargs})
        t_a.start()
        t_b.start()
        t_a.join(timeout=15)
        t_b.join(timeout=15)
        assert results["a"][0] == "ok" and results["b"][0] == "ok"
        assert results["a"][1] == results["b"][1]

        conn = test_engine.connect()
        count = conn.execute(
            text("SELECT count(*) FROM germination_outcome_snapshots WHERE batch_carrier_assignment_id = :aid"),
            {"aid": scenario["assignment_ids"][0]},
        ).scalar_one()
        conn.close()
        assert count == 1
    finally:
        _cleanup_committed_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_concurrent_two_provisional_snapshots_different_trays_both_succeed(test_engine) -> None:
    import threading

    scenario = _build_committed_scenario(test_engine, suffix=uuid.uuid4().hex[:8])
    try:
        eff = _now()
        kwargs_a = dict(
            tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(), effective_time=eff, note=None,
            outcomes=[_outcome(scenario["assignment_ids"][0])],
        )
        kwargs_b = dict(
            tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(), effective_time=eff, note=None,
            outcomes=[_outcome(scenario["assignment_ids"][1])],
        )
        barrier = threading.Barrier(2)
        results: dict = {}
        t_a = threading.Thread(target=_worker, args=(test_engine, results, "a", barrier), kwargs={"kwargs": kwargs_a})
        t_b = threading.Thread(target=_worker, args=(test_engine, results, "b", barrier), kwargs={"kwargs": kwargs_b})
        t_a.start()
        t_b.start()
        t_a.join(timeout=15)
        t_b.join(timeout=15)
        assert results["a"][0] == "ok" and results["b"][0] == "ok", results
    finally:
        _cleanup_committed_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_concurrent_completed_racing_newer_provisional_invariant_protected(test_engine) -> None:
    import threading

    scenario = _build_committed_scenario(test_engine, suffix=uuid.uuid4().hex[:8])
    try:
        aid = scenario["assignment_ids"][0]
        t1 = _now()
        kwargs_completed = dict(
            tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(), effective_time=t1, note=None,
            outcomes=[_outcome(aid, assessment_complete=True)],
        )
        # Real elapsed wall-clock time (dict construction above) separates
        # t1 from t2 -- no artificial forward offset that risks landing in
        # the future by the time the worker thread actually executes.
        t2 = _now()
        kwargs_provisional = dict(
            tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(), effective_time=t2, note=None,
            outcomes=[_outcome(aid, assessment_complete=False)],
        )
        barrier = threading.Barrier(2)
        results: dict = {}
        t_a = threading.Thread(target=_worker, args=(test_engine, results, "a", barrier), kwargs={"kwargs": kwargs_completed})
        t_b = threading.Thread(target=_worker, args=(test_engine, results, "b", barrier), kwargs={"kwargs": kwargs_provisional})
        t_a.start()
        t_b.start()
        t_a.join(timeout=15)
        t_b.join(timeout=15)
        # The guard is symmetric (both directions check against each
        # other -- see observation_service.py/the migration trigger), so
        # regardless of which command wins the batch-row lock race, EXACTLY
        # one of the two succeeds and the other is rejected: whichever
        # arrives first finds nothing to conflict with and commits; whichever
        # arrives second sees the first's already-committed row and is
        # rejected, since together they would leave a provisional newer
        # than the latest completion.
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("rejected") == 1, results

        conn = test_engine.connect()
        rows = conn.execute(
            text(
                "SELECT gos.assessment_complete, oe.effective_time FROM germination_outcome_snapshots gos "
                "JOIN observation_events oe ON oe.id = gos.observation_event_id "
                "WHERE gos.batch_carrier_assignment_id = :aid ORDER BY oe.effective_time"
            ),
            {"aid": aid},
        ).all()
        conn.close()
        # Whichever one committed, the final state must never show a
        # provisional newer than the latest completed snapshot.
        completed_times = [r[1] for r in rows if r[0]]
        provisional_times = [r[1] for r in rows if not r[0]]
        if completed_times and provisional_times:
            assert max(provisional_times) <= max(completed_times)
    finally:
        _cleanup_committed_scenario(test_engine, scenario["tenant_id"])


# =====================================================================
# NURSERY-OPS-002B.1: historical stage-run context closure
# =====================================================================


def _build_stage_history_scenario(db_session, tenant, user, farm, *, suffix=None):
    """A Batch that starts in SEEDING, later advances through a
    `germination`-category stage, then later still to COMPLETE -- used only
    to prove `ObservationEvent.active_batch_stage_run_id` remains
    historically truthful across workflow progression. No transplant/
    carrier-type machinery needed: plain `transition_stage` advancement."""
    suffix = suffix or uuid.uuid4().hex[:8]
    crop = crop_service.register_crop(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"ICE-{suffix}",
        common_name="Iceberg", scientific_name=None, crop_category="leafy_green",
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
    version = workflow_service.create_draft_version(db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id)
    seeding = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="SEEDING", name="Seeding", display_order=0, stage_category="seeding", expected_duration_minutes=None,
        permitted_location_type_code=None, required_carrier_type_code="seed_tray", is_start=True, is_terminal=False,
    )
    germination = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="GERMINATION", name="Germination", display_order=1, stage_category="germination",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=False,
    )
    # Non-terminal "later stage" -- advancing here must NOT close the Batch
    # (unlike a genuinely terminal stage), so a first-time historical outcome
    # recording remains possible afterward. A real terminal stage still
    # exists further on so the workflow itself is structurally complete, but
    # these tests never advance into it.
    seedling = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="SEEDLING", name="Seedling", display_order=2, stage_category="nursery", expected_duration_minutes=None,
        permitted_location_type_code=None, required_carrier_type_code=None, is_start=False, is_terminal=False,
    )
    complete = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="COMPLETE", name="Complete", display_order=3, stage_category="completed", expected_duration_minutes=None,
        permitted_location_type_code=None, required_carrier_type_code=None, is_start=False, is_terminal=True,
    )
    t1 = workflow_service.add_transition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=seeding.id, to_stage_id=germination.id, code="ADVANCE-1", name="Advance 1",
    )
    t2 = workflow_service.add_transition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=germination.id, to_stage_id=seedling.id, code="ADVANCE-2", name="Advance 2",
    )
    workflow_service.add_transition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=seedling.id, to_stage_id=complete.id, code="ADVANCE-3", name="Advance 3",
    )
    workflow_service.publish_version(db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id)

    batch_created = _now() - timedelta(days=20)
    batch = crop_batch_service.create_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"BATCH-{suffix}", workflow_id=workflow.id, effective_time=batch_created,
    )
    seed_lot = sowing_service.register_seed_lot(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id, variety_id=variety.id,
        code=f"LOT-{suffix}", supplier_name=None, supplier_lot_reference=None, received_date=None, expiry_date=None,
    )
    carrier = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        specification_id=ensure_seed_tray_specification(db_session, tenant_id=tenant.id, actor_user_id=user.id).id,
        code=f"ST-{suffix}-0001", issued_date=None,
    )
    sow_time = batch_created + timedelta(hours=1)
    sowing_service.sow_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=sow_time, note=None,
        lines=[{"carrier_id": carrier.id, "seed_lot_id": seed_lot.id, "sown_site_count": None, "seed_count": 200, "line_note": None}],
    )
    assignment = sowing_service.list_batch_carriers(db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id)[0]

    return {
        "batch": batch, "assignment_id": assignment.id, "batch_created": batch_created, "sow_time": sow_time,
        "seeding_stage": seeding, "germination_stage": germination, "seedling_stage": seedling, "complete_stage": complete,
        "t1": t1, "t2": t2,
    }


def _advance_stage(db_session, tenant, user, farm, s, *, transition, effective_time):
    crop_batch_service.transition_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), configured_transition_id=transition.id, effective_time=effective_time,
        reason=None,
    )


def _stage_run_id(db_session, batch_id, stage_id):
    return db_session.execute(
        text("SELECT id FROM batch_stage_runs WHERE batch_id = :bid AND workflow_stage_id = :sid"),
        {"bid": batch_id, "sid": stage_id},
    ).scalar_one()


@pytest.mark.integration
def test_current_stage_normal_entry_still_works(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_stage_history_scenario(db_session, tenant, user, farm)
    _advance_stage(db_session, tenant, user, farm, s, transition=s["t1"], effective_time=s["batch_created"] + timedelta(days=1))
    germination_run_id = _stage_run_id(db_session, s["batch"].id, s["germination_stage"].id)
    event = _record(
        db_session, tenant, user, farm, s["batch"].id, [_outcome(s["assignment_id"])],
        effective_time=s["batch_created"] + timedelta(days=2),
    )
    assert event.active_batch_stage_run_id == germination_run_id


@pytest.mark.integration
def test_historical_entry_after_batch_progresses_references_historically_valid_run(db_session, active_context_with_farm) -> None:
    """The exact scenario from section 6: Germination active at T1, Batch
    later advances to a different stage at T2, outcome entered (recorded)
    well after T2 with effective_time=T1 -- must reference the Germination
    run that was truthfully active at T1, not the currently-active run."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_stage_history_scenario(db_session, tenant, user, farm)
    _advance_stage(db_session, tenant, user, farm, s, transition=s["t1"], effective_time=s["batch_created"] + timedelta(days=1))
    germination_run_id = _stage_run_id(db_session, s["batch"].id, s["germination_stage"].id)
    t1 = s["batch_created"] + timedelta(days=3)
    _advance_stage(db_session, tenant, user, farm, s, transition=s["t2"], effective_time=s["batch_created"] + timedelta(days=5))
    seedling_run_id = _stage_run_id(db_session, s["batch"].id, s["seedling_stage"].id)

    event = _record(db_session, tenant, user, farm, s["batch"].id, [_outcome(s["assignment_id"])], effective_time=t1)

    assert event.active_batch_stage_run_id == germination_run_id
    assert event.active_batch_stage_run_id != seedling_run_id


@pytest.mark.integration
def test_event_cannot_reference_stage_run_beginning_after_effective_time(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_stage_history_scenario(db_session, tenant, user, farm)
    _advance_stage(db_session, tenant, user, farm, s, transition=s["t1"], effective_time=s["batch_created"] + timedelta(days=1))
    seedling_entered = s["batch_created"] + timedelta(days=5)
    _advance_stage(db_session, tenant, user, farm, s, transition=s["t2"], effective_time=seedling_entered)
    seedling_run_id = _stage_run_id(db_session, s["batch"].id, s["seedling_stage"].id)

    # Direct-SQL proof: an ObservationEvent referencing the SEEDLING run
    # (entered day+5) with an effective_time BEFORE that entry (day+3) must
    # be rejected by the corrected trigger.
    with pytest.raises(DBAPIError, match="precedes the referenced stage run"):
        db_session.execute(
            text(
                "INSERT INTO observation_events "
                "(id, tenant_id, farm_id, batch_id, active_batch_stage_run_id, effective_time, actor_user_id, "
                "client_command_id, request_fingerprint) "
                "VALUES (gen_random_uuid(), :tid, :fid, :bid, :run_id, :eff, :uid, gen_random_uuid(), 'x')"
            ),
            {
                "tid": tenant.id, "fid": farm.id, "bid": s["batch"].id, "run_id": seedling_run_id,
                "eff": s["batch_created"] + timedelta(days=3), "uid": user.id,
            },
        )
    db_session.rollback()


@pytest.mark.integration
def test_direct_write_event_at_or_after_run_exit_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_stage_history_scenario(db_session, tenant, user, farm)
    _advance_stage(db_session, tenant, user, farm, s, transition=s["t1"], effective_time=s["batch_created"] + timedelta(days=1))
    germination_run_id = _stage_run_id(db_session, s["batch"].id, s["germination_stage"].id)
    exit_time = s["batch_created"] + timedelta(days=5)
    _advance_stage(db_session, tenant, user, farm, s, transition=s["t2"], effective_time=exit_time)

    # The Germination run exited at day+5; an event referencing it at or
    # after that exit must be rejected -- it was no longer truthfully active.
    with pytest.raises(DBAPIError, match="at or after the referenced stage run"):
        db_session.execute(
            text(
                "INSERT INTO observation_events "
                "(id, tenant_id, farm_id, batch_id, active_batch_stage_run_id, effective_time, actor_user_id, "
                "client_command_id, request_fingerprint) "
                "VALUES (gen_random_uuid(), :tid, :fid, :bid, :run_id, :eff, :uid, gen_random_uuid(), 'x')"
            ),
            {"tid": tenant.id, "fid": farm.id, "bid": s["batch"].id, "run_id": germination_run_id, "eff": exit_time, "uid": user.id},
        )
    db_session.rollback()


@pytest.mark.integration
def test_direct_write_event_cannot_reference_another_batchs_stage_run(db_session, active_context_with_farm) -> None:
    """Regression proof: the pre-existing, unmodified
    `v_run_batch_id <> NEW.batch_id` check still holds after the 002B.1
    correction."""
    tenant, user, _headers, farm = active_context_with_farm
    s1 = _build_stage_history_scenario(db_session, tenant, user, farm, suffix="s1")
    s2 = _build_stage_history_scenario(db_session, tenant, user, farm, suffix="s2")
    other_run_id = _stage_run_id(db_session, s2["batch"].id, s2["seeding_stage"].id)

    with pytest.raises(DBAPIError, match="does not belong to this batch"):
        db_session.execute(
            text(
                "INSERT INTO observation_events "
                "(id, tenant_id, farm_id, batch_id, active_batch_stage_run_id, effective_time, actor_user_id, "
                "client_command_id, request_fingerprint) "
                "VALUES (gen_random_uuid(), :tid, :fid, :bid, :run_id, :eff, :uid, gen_random_uuid(), 'x')"
            ),
            {
                "tid": tenant.id, "fid": farm.id, "bid": s1["batch"].id, "run_id": other_run_id,
                "eff": s2["batch_created"], "uid": user.id,
            },
        )
    db_session.rollback()


@pytest.mark.integration
def test_replay_after_stage_change_stays_bound_to_original_stage_run(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_stage_history_scenario(db_session, tenant, user, farm)
    _advance_stage(db_session, tenant, user, farm, s, transition=s["t1"], effective_time=s["batch_created"] + timedelta(days=1))
    germination_run_id = _stage_run_id(db_session, s["batch"].id, s["germination_stage"].id)
    t1 = s["batch_created"] + timedelta(days=3)
    ccid = uuid.uuid4()

    first = _record(db_session, tenant, user, farm, s["batch"].id, [_outcome(s["assignment_id"])], client_command_id=ccid, effective_time=t1)
    assert first.active_batch_stage_run_id == germination_run_id

    _advance_stage(db_session, tenant, user, farm, s, transition=s["t2"], effective_time=s["batch_created"] + timedelta(days=5))

    # Exact replay of the SAME command after the batch has progressed AGAIN
    # must return the original event, still bound to the Germination run --
    # never re-resolved against today's (now COMPLETE) stage state.
    replay = _record(db_session, tenant, user, farm, s["batch"].id, [_outcome(s["assignment_id"])], client_command_id=ccid, effective_time=t1)
    assert replay.id == first.id
    assert replay.active_batch_stage_run_id == germination_run_id


@pytest.mark.integration
def test_recording_historical_outcome_creates_no_transition_and_mutates_no_stage_run(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_stage_history_scenario(db_session, tenant, user, farm)
    _advance_stage(db_session, tenant, user, farm, s, transition=s["t1"], effective_time=s["batch_created"] + timedelta(days=1))
    t1 = s["batch_created"] + timedelta(days=3)
    _advance_stage(db_session, tenant, user, farm, s, transition=s["t2"], effective_time=s["batch_created"] + timedelta(days=5))

    germination_run_before = db_session.execute(
        text("SELECT id, workflow_stage_id, entered_effective_time, exited_effective_time, closed_by_transition_id FROM batch_stage_runs WHERE batch_id = :bid AND workflow_stage_id = :sid"),
        {"bid": s["batch"].id, "sid": s["germination_stage"].id},
    ).mappings().first()
    transition_count_before = db_session.execute(
        text("SELECT count(*) FROM batch_stage_transitions WHERE batch_id = :bid"), {"bid": s["batch"].id}
    ).scalar_one()

    _record(db_session, tenant, user, farm, s["batch"].id, [_outcome(s["assignment_id"])], effective_time=t1)

    germination_run_after = db_session.execute(
        text("SELECT id, workflow_stage_id, entered_effective_time, exited_effective_time, closed_by_transition_id FROM batch_stage_runs WHERE batch_id = :bid AND workflow_stage_id = :sid"),
        {"bid": s["batch"].id, "sid": s["germination_stage"].id},
    ).mappings().first()
    transition_count_after = db_session.execute(
        text("SELECT count(*) FROM batch_stage_transitions WHERE batch_id = :bid"), {"bid": s["batch"].id}
    ).scalar_one()

    assert dict(germination_run_before) == dict(germination_run_after)
    assert transition_count_before == transition_count_after
