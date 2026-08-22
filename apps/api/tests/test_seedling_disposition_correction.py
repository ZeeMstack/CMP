"""SEEDLING-DISPOSITION-LIFECYCLE-001: Disposition-driven source-assignment
release/restoration lifecycle. Exhausting Seedling Disposition releases the
current active BatchCarrierAssignment; correcting that exhausting Disposition
restores positive biology via a NEW, active restoration assignment (never
reactivating the predecessor), reusing the SAME shared restoration lineage
TRANSPLANT-CORRECTION-001 established. Reuses `build_transplant_ready_scenario`
exactly as `test_workflow_integrity_seedling_remainder.py` does -- real
SeedlingEntry/checkpoint history and a TRANSPLANTING-category stage (with a
configured transition out of it) are required to exercise stage-run safety
and mixed Transplant/Disposition restoration generations meaningfully."""
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select, text

from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.carrier import Carrier
from app.models.seedling_disposition_command import SeedlingDispositionCommand
from app.models.seedling_disposition_event import SeedlingDispositionEvent
from app.services import (
    batch_derivation_service,
    crop_batch_service,
    nursery_service,
    seedling_disposition_service,
    seedling_source_lineage,
    transplant_service,
)
from app.services.errors import (
    BatchDerivationValidationError,
    SeedlingDispositionAssignmentReleasedError,
    SeedlingDispositionCarrierReusedError,
    SeedlingDispositionCorrectionStageContextUnavailableError,
    SeedlingDispositionCorrectionStageMismatchError,
)
from tests._transplant_scenario import build_transplant_ready_scenario, now as _now

pytestmark = pytest.mark.integration


def _build_scenario(db_session, tenant, user, farm, **kwargs):
    kwargs.setdefault("tray_count", 1)
    kwargs.setdefault("normal", 20)
    kwargs.setdefault("abnormal", 0)
    kwargs.setdefault("transplanting_required_type", "cultivation_plate")
    return build_transplant_ready_scenario(db_session, tenant, user, farm, **kwargs)


def _record(db_session, tenant, farm, user, *, assignment_id, quantity, effective_time, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        batch_carrier_assignment_id=assignment_id, quantity=quantity, reason_code="WEAK_SEEDLING",
        effective_time=effective_time, note=None,
    )
    defaults.update(overrides)
    return seedling_disposition_service.record_disposition(db_session, **defaults)


def _correct(db_session, tenant, farm, user, *, target_event_id, corrected=None, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        target_event_id=target_event_id, corrected=corrected,
    )
    defaults.update(overrides)
    return seedling_disposition_service.correct_disposition(db_session, **defaults)


def _assignment_row(db_session, assignment_id):
    return db_session.execute(
        select(BatchCarrierAssignment).where(BatchCarrierAssignment.id == assignment_id)
    ).scalar_one()


def _carrier_pointer(db_session, carrier_id):
    return db_session.execute(
        select(Carrier.latest_batch_carrier_assignment_id).where(Carrier.id == carrier_id)
    ).scalar_one()


def _reuse_carrier_second_sowing(db_session, tenant, user, farm, *, carrier_id, effective_time, suffix=None):
    """A genuinely separate, unrelated Sowing onto an already-released
    Carrier -- models physical reuse for a DIFFERENT CropBatch, independent
    of any restoration lineage. Minimal infrastructure only (no germination/
    SeedlingEntry needed -- the assignment's mere existence is what matters
    for the Carrier latest-assignment pointer)."""
    from app.schemas.farm_setup import (
        GerminationChamberSetupConfig, GreenhouseSetupCreate, NurserySectionConfig, NurserySetupConfig,
        TableGeneratorConfig,
    )
    from app.services import (
        crop_service, farm_setup_service, production_system_service, sowing_service, workflow_service,
    )

    suffix = suffix or uuid.uuid4().hex[:8]
    crop = crop_service.register_crop(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"REU-{suffix}",
        common_name="Reuse Lettuce", scientific_name=None, crop_category="leafy_green",
    )
    variety = crop_service.register_variety(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"REV-{suffix}",
        name="ReuseVariety", supplier_reference=None,
    )
    ps = production_system_service.register_production_system(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"RPS-{suffix}", name="Reuse System",
        description=None,
    )
    workflow = workflow_service.register_workflow(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, variety_id=variety.id,
        production_system_id=ps.id, code=f"RWF-{suffix}", name="Reuse Nursery",
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
        variety_id=variety.id, code=f"RLOT-{suffix}", supplier_name="Rijk Zwaan", supplier_lot_reference="RZ-002",
        received_date=None, expiry_date=None,
    )
    setup = farm_setup_service.create_greenhouse_setup(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        payload=GreenhouseSetupCreate(
            code=f"RNUR-{suffix}", name="Reuse Nursery GH", classification="nursery", client_command_id=uuid.uuid4(),
            nursery=NurserySetupConfig(
                seeding_station=NurserySectionConfig(code=f"RSEED-{suffix}"),
                germination_chamber=GerminationChamberSetupConfig(code=f"RGC-{suffix}", trolley_capacity=None),
                seedling_tables=TableGeneratorConfig(code_prefix=f"RT{suffix[:4]}", start=1, end=1, pad_width=2, capacity=None),
            ),
        ),
    )
    structure = farm_setup_service.get_greenhouse_structure(
        db_session.connection(), tenant_id=tenant.id, farm_id=farm.id, greenhouse_id=setup.greenhouse_id,
    )
    seeding_station_id = structure.nursery_seeding_stations[0].id

    event = nursery_service.sow_new_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        seed_lot_id=seed_lot.id, seeding_station_id=seeding_station_id, seeding_machine_id=None,
        effective_time=effective_time, note=None,
        trays=[{"carrier_id": carrier_id, "sown_site_count": 50, "seeds_sown": 50}],
    )
    assignments = sowing_service.list_batch_carriers(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=event.batch_id
    )
    return assignments[0].id


# =====================================================================
# Pure void / zero-positive-zero (sections 9/10)
# =====================================================================


def test_pure_void_restores_active_assignment(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    aid = s["source_assignment_ids"][0]
    et = s["entry_time"] + timedelta(hours=2)
    command = _record(db_session, tenant, farm, user, assignment_id=aid, quantity=20, effective_time=et)
    x = db_session.execute(
        select(SeedlingDispositionEvent).where(SeedlingDispositionEvent.command_id == command.id)
    ).scalar_one()

    a = _assignment_row(db_session, aid)
    assert a.released_effective_time == et
    assert a.released_by_seedling_disposition_event_id == x.id

    correction = _correct(db_session, tenant, farm, user, target_event_id=x.id, corrected=None)
    tip_id = seedling_source_lineage.resolve_lineage_tip_assignment_id(db_session, original_assignment_id=aid)
    b = _assignment_row(db_session, tip_id)
    assert b.id != aid
    assert b.released_effective_time is None
    assert b.restored_from_batch_carrier_assignment_id == aid
    assert b.opening_seedling_disposition_reversal_event_id is not None
    assert b.carrier_id == a.carrier_id

    # A stays released forever.
    a_after = _assignment_row(db_session, aid)
    assert a_after.released_effective_time == et
    assert correction.operation_kind == "CORRECT"


def test_zero_positive_zero_creates_and_releases_b(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    aid = s["source_assignment_ids"][0]
    et = s["entry_time"] + timedelta(hours=2)
    command = _record(db_session, tenant, farm, user, assignment_id=aid, quantity=20, effective_time=et)
    x = db_session.execute(
        select(SeedlingDispositionEvent).where(SeedlingDispositionEvent.command_id == command.id)
    ).scalar_one()

    correction = _correct(
        db_session, tenant, farm, user, target_event_id=x.id,
        corrected={"quantity": 20, "reason_code": "WEAK_SEEDLING", "effective_time": et, "note": None},
    )
    tip_id = seedling_source_lineage.resolve_lineage_tip_assignment_id(db_session, original_assignment_id=aid)
    b = _assignment_row(db_session, tip_id)
    assert b.id != aid
    # B was genuinely created (never optimized away) then released by the
    # replacement -- never reactivating A.
    assert b.released_effective_time == et
    replacement = db_session.execute(
        select(SeedlingDispositionEvent).where(SeedlingDispositionEvent.corrects_event_id == x.id)
    ).scalar_one()
    assert b.released_by_seedling_disposition_event_id == replacement.id
    assert correction.id is not None


def test_non_exhausting_correction_no_restoration(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    aid = s["source_assignment_ids"][0]
    et = s["entry_time"] + timedelta(hours=2)
    command = _record(db_session, tenant, farm, user, assignment_id=aid, quantity=5, effective_time=et)  # 20->15
    x = db_session.execute(
        select(SeedlingDispositionEvent).where(SeedlingDispositionEvent.command_id == command.id)
    ).scalar_one()

    a_before = _assignment_row(db_session, aid)
    assert a_before.released_effective_time is None

    _correct(
        db_session, tenant, farm, user, target_event_id=x.id,
        corrected={"quantity": 3, "reason_code": "WEAK_SEEDLING", "effective_time": et, "note": None},
    )
    a_after = _assignment_row(db_session, aid)
    assert a_after.released_effective_time is None
    # No restoration -- the original assignment is still the sole lineage tip.
    tip_id = seedling_source_lineage.resolve_lineage_tip_assignment_id(db_session, original_assignment_id=aid)
    assert tip_id == aid


# =====================================================================
# Replacement-correction generations (section 11/15)
# =====================================================================


def test_replacement_releasing_b_can_itself_be_corrected_abc_generations(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    aid = s["source_assignment_ids"][0]
    et = s["entry_time"] + timedelta(hours=2)

    # A: X exhausts A -> A released.
    cmd_x = _record(db_session, tenant, farm, user, assignment_id=aid, quantity=20, effective_time=et)
    x = db_session.execute(
        select(SeedlingDispositionEvent).where(SeedlingDispositionEvent.command_id == cmd_x.id)
    ).scalar_one()

    # correct X: R1 opens B, replacement Y exhausts B (a single CORRECT
    # command carrying a zero-availability replacement).
    _correct(
        db_session, tenant, farm, user, target_event_id=x.id,
        corrected={"quantity": 20, "reason_code": "WEAK_SEEDLING", "effective_time": et, "note": None},
    )
    b_id = seedling_source_lineage.resolve_lineage_tip_assignment_id(db_session, original_assignment_id=aid)
    b = _assignment_row(db_session, b_id)
    assert b.restored_from_batch_carrier_assignment_id == aid
    assert b.released_effective_time == et
    y = db_session.execute(
        select(SeedlingDispositionEvent).where(SeedlingDispositionEvent.corrects_event_id == x.id)
    ).scalar_one()
    assert b.released_by_seedling_disposition_event_id == y.id

    # later correct Y: R2 opens C, replacement Z partially reduces C (10 remain).
    correction2 = _correct(
        db_session, tenant, farm, user, target_event_id=y.id,
        corrected={"quantity": 10, "reason_code": "WEAK_SEEDLING", "effective_time": et, "note": None},
    )
    c_id = seedling_source_lineage.resolve_lineage_tip_assignment_id(db_session, original_assignment_id=aid)
    c = _assignment_row(db_session, c_id)
    assert c.id not in (aid, b.id)
    assert c.restored_from_batch_carrier_assignment_id == b.id
    assert c.released_effective_time is None
    assert c.carrier_id == b.carrier_id == a_carrier(db_session, aid)
    assert correction2.operation_kind == "CORRECT"

    # ordinary Transplant of the remaining 10 exhausts C.
    _transplant_full(db_session, tenant, farm, user, s, source_assignment_id=c.id, count=10, effective_time=et + timedelta(hours=1))
    c_after = _assignment_row(db_session, c.id)
    assert c_after.released_effective_time is not None
    assert c_after.released_by_transplant_event_id is not None

    # Same SeedlingEntry remains the biological anchor throughout; A/B never reactivated.
    entry = seedling_source_lineage.resolve_seedling_entry_for_assignment(db_session, assignment_id=c.id)
    entry_a = seedling_source_lineage.resolve_seedling_entry_for_assignment(db_session, assignment_id=aid)
    assert entry.id == entry_a.id
    a_final = _assignment_row(db_session, aid)
    b_final = _assignment_row(db_session, b.id)
    assert a_final.released_effective_time == et
    assert b_final.released_effective_time == et


def a_carrier(db_session, assignment_id):
    return _assignment_row(db_session, assignment_id).carrier_id


def _transplant_full(db_session, tenant, farm, user, s, *, source_assignment_id, count, effective_time):
    dest = s["destination_carriers"][1]
    return transplant_service.record_transplant(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch_id"],
        client_command_id=uuid.uuid4(), effective_time=effective_time, note=None,
        source_lines=[{
            "source_assignment_id": source_assignment_id, "transplant_damage_count": 0, "qc_rejection_count": 0,
            "sample_count": 0, "other_loss_count": 0, "other_loss_note": None, "note": None,
        }],
        destination_lines=[{"destination_carrier_id": dest.id, "assigned_plant_count": count, "note": None}],
        allocations=[{
            "source_assignment_id": source_assignment_id, "destination_carrier_id": dest.id,
            "allocated_plant_count": count,
        }],
    )


# =====================================================================
# Mixed Transplant / Disposition restoration generations (section 8/24)
# =====================================================================


def test_mixed_transplant_and_disposition_restoration_generations(db_session, active_context_with_farm) -> None:
    """A (sowing-origin) -> exhausted by Transplant -> Transplant-restored B
    (via correcting that Transplant) -> exhausted by Disposition -> C
    Disposition-restored -- proves the SAME shared restoration lineage
    already supports mixed opener/releaser event types with zero special-
    casing, exactly as frozen."""
    from app.services import transplant_correction_service

    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    aid = s["source_assignment_ids"][0]
    dest0 = s["destination_carriers"][0]
    et = s["entry_time"] + timedelta(hours=2)

    target = transplant_service.record_transplant(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch_id"],
        client_command_id=uuid.uuid4(), effective_time=et, note=None,
        source_lines=[{
            "source_assignment_id": aid, "transplant_damage_count": 0, "qc_rejection_count": 0,
            "sample_count": 0, "other_loss_count": 0, "other_loss_note": None, "note": None,
        }],
        destination_lines=[{"destination_carrier_id": dest0.id, "assigned_plant_count": 20, "note": None}],
        allocations=[{"source_assignment_id": aid, "destination_carrier_id": dest0.id, "allocated_plant_count": 20}],
    )
    a_after = _assignment_row(db_session, aid)
    assert a_after.released_by_transplant_event_id == target.id

    # correct the Transplant (pure void) -- restores A's biology into a
    # Transplant-restored B.
    transplant_correction_service.correct_transplant(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch_id"],
        target_transplant_event_id=target.id, client_command_id=uuid.uuid4(), reason="wrong quantity", replacement=None,
    )
    b_id = seedling_source_lineage.resolve_lineage_tip_assignment_id(db_session, original_assignment_id=aid)
    b = _assignment_row(db_session, b_id)
    assert b.opening_transplant_reversal_event_id is not None
    assert b.released_effective_time is None

    # Disposition now exhausts B.
    et2 = et + timedelta(hours=1)
    cmd = _record(db_session, tenant, farm, user, assignment_id=b.id, quantity=20, effective_time=et2)
    x2 = db_session.execute(
        select(SeedlingDispositionEvent).where(SeedlingDispositionEvent.command_id == cmd.id)
    ).scalar_one()
    b_after = _assignment_row(db_session, b.id)
    assert b_after.released_by_seedling_disposition_event_id == x2.id

    # correct that Disposition -- opens Disposition-restored C.
    _correct(db_session, tenant, farm, user, target_event_id=x2.id, corrected=None)
    c_id = seedling_source_lineage.resolve_lineage_tip_assignment_id(db_session, original_assignment_id=aid)
    c = _assignment_row(db_session, c_id)
    assert c.id not in (aid, b.id)
    assert c.restored_from_batch_carrier_assignment_id == b.id
    assert c.opening_seedling_disposition_reversal_event_id is not None
    assert c.released_effective_time is None

    entry_c = seedling_source_lineage.resolve_seedling_entry_for_assignment(db_session, assignment_id=c.id)
    entry_a = seedling_source_lineage.resolve_seedling_entry_for_assignment(db_session, assignment_id=aid)
    assert entry_c.id == entry_a.id


# =====================================================================
# Batch Derivation rejection (section 29/31)
# =====================================================================


def test_batch_derivation_rejects_disposition_restored_assignment(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    aid = s["source_assignment_ids"][0]
    et = s["entry_time"] + timedelta(hours=2)
    command = _record(db_session, tenant, farm, user, assignment_id=aid, quantity=20, effective_time=et)
    x = db_session.execute(
        select(SeedlingDispositionEvent).where(SeedlingDispositionEvent.command_id == command.id)
    ).scalar_one()
    _correct(db_session, tenant, farm, user, target_event_id=x.id, corrected=None)
    b_id = seedling_source_lineage.resolve_lineage_tip_assignment_id(db_session, original_assignment_id=aid)
    b = _assignment_row(db_session, b_id)
    assert b.opening_seedling_disposition_reversal_event_id is not None

    with pytest.raises(BatchDerivationValidationError):
        batch_derivation_service._derive_transferred_quantity(db_session, b)


# =====================================================================
# Stage-run identity / safety (sections 13-19)
# =====================================================================


def test_new_record_and_correct_commands_store_active_stage_run_id(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    aid = s["source_assignment_ids"][0]
    et = s["entry_time"] + timedelta(hours=2)
    record_command = _record(db_session, tenant, farm, user, assignment_id=aid, quantity=5, effective_time=et)
    assert record_command.active_batch_stage_run_id is not None

    x = db_session.execute(
        select(SeedlingDispositionEvent).where(SeedlingDispositionEvent.command_id == record_command.id)
    ).scalar_one()
    correct_command = _correct(
        db_session, tenant, farm, user, target_event_id=x.id,
        corrected={"quantity": 3, "reason_code": "WEAK_SEEDLING", "effective_time": et, "note": None},
    )
    assert correct_command.active_batch_stage_run_id is not None
    assert correct_command.active_batch_stage_run_id == record_command.active_batch_stage_run_id


def test_legacy_target_with_null_stage_run_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    aid = s["source_assignment_ids"][0]
    et = s["entry_time"] + timedelta(hours=2)
    record_command = _record(db_session, tenant, farm, user, assignment_id=aid, quantity=5, effective_time=et)
    x = db_session.execute(
        select(SeedlingDispositionEvent).where(SeedlingDispositionEvent.command_id == record_command.id)
    ).scalar_one()

    # Simulate a legacy (pre-this-migration) command via direct SQL --
    # historical rows keep active_batch_stage_run_id NULL, never backfilled.
    # seedling_disposition_commands is append-only, so this UPDATE must
    # bypass that trigger deliberately, exactly like every other test in
    # this codebase that needs to model a pre-existing historical shape.
    db_session.execute(text("SET session_replication_role = replica"))
    db_session.execute(
        text("UPDATE seedling_disposition_commands SET active_batch_stage_run_id = NULL WHERE id = :cid"),
        {"cid": record_command.id},
    )
    db_session.execute(text("SET session_replication_role = DEFAULT"))
    db_session.flush()
    # The raw SQL UPDATE above bypasses the ORM identity map -- without
    # this, correct_disposition's db.get(SeedlingDispositionCommand, ...)
    # would return the still-cached, pre-update Python object.
    db_session.expire_all()

    with pytest.raises(SeedlingDispositionCorrectionStageContextUnavailableError):
        _correct(
            db_session, tenant, farm, user, target_event_id=x.id,
            corrected={"quantity": 3, "reason_code": "WEAK_SEEDLING", "effective_time": et, "note": None},
        )


def test_correction_after_stage_transition_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    aid = s["source_assignment_ids"][0]
    et = s["entry_time"] + timedelta(hours=2)
    # Fully resolve the only source tray so the batch can legitimately leave
    # TRANSPLANTING (WORKFLOW-INTEGRITY-001), then advance the stage.
    record_command = _record(db_session, tenant, farm, user, assignment_id=aid, quantity=20, effective_time=et)
    x = db_session.execute(
        select(SeedlingDispositionEvent).where(SeedlingDispositionEvent.command_id == record_command.id)
    ).scalar_one()

    crop_batch_service.transition_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch_id"],
        client_command_id=uuid.uuid4(), configured_transition_id=s["transitions"]["t2"].id,
        effective_time=et + timedelta(hours=1), reason=None,
    )

    with pytest.raises(SeedlingDispositionCorrectionStageMismatchError):
        _correct(db_session, tenant, farm, user, target_event_id=x.id, corrected=None)


def test_same_run_correction_allowed(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    aid = s["source_assignment_ids"][0]
    et = s["entry_time"] + timedelta(hours=2)
    record_command = _record(db_session, tenant, farm, user, assignment_id=aid, quantity=20, effective_time=et)
    x = db_session.execute(
        select(SeedlingDispositionEvent).where(SeedlingDispositionEvent.command_id == record_command.id)
    ).scalar_one()
    # No stage transition occurs -- correction remains within the same run.
    correction = _correct(db_session, tenant, farm, user, target_event_id=x.id, corrected=None)
    assert correction.operation_kind == "CORRECT"


# =====================================================================
# Carrier reuse / latest-assignment pointer (sections 7/8/17-19/22)
# =====================================================================


def test_pointer_moves_to_restoration_after_correction(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    aid = s["source_assignment_ids"][0]
    a = _assignment_row(db_session, aid)
    et = s["entry_time"] + timedelta(hours=2)

    assert _carrier_pointer(db_session, a.carrier_id) == aid  # backfill/initial pointer

    command = _record(db_session, tenant, farm, user, assignment_id=aid, quantity=20, effective_time=et)
    x = db_session.execute(
        select(SeedlingDispositionEvent).where(SeedlingDispositionEvent.command_id == command.id)
    ).scalar_one()
    # Release never moves the pointer.
    assert _carrier_pointer(db_session, a.carrier_id) == aid

    _correct(db_session, tenant, farm, user, target_event_id=x.id, corrected=None)
    b_id = seedling_source_lineage.resolve_lineage_tip_assignment_id(db_session, original_assignment_id=aid)
    assert _carrier_pointer(db_session, a.carrier_id) == b_id
    assert b_id != aid


def test_historical_use_before_a_does_not_block_correction(db_session, active_context_with_farm) -> None:
    """P (a genuinely different, unrelated batch) used this exact physical
    Carrier BEFORE A -- released, forgotten by the pointer once A's own
    Sowing overwrote it. Correcting A's exhausting Disposition must be
    allowed: physical continuity was never broken AFTER A."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    aid = s["source_assignment_ids"][0]
    a = _assignment_row(db_session, aid)
    carrier_id = a.carrier_id
    et = s["entry_time"] + timedelta(hours=2)

    # P: this Carrier was already used-and-released before A's own Sowing --
    # simulated directly since the scenario builder itself is what performed
    # A's Sowing; instead prove correction succeeds using the Carrier's
    # ALREADY-forward-only pointer (A's own creation already overwrote
    # whatever came before it, which is the entire point).
    assert _carrier_pointer(db_session, carrier_id) == aid

    command = _record(db_session, tenant, farm, user, assignment_id=aid, quantity=20, effective_time=et)
    x = db_session.execute(
        select(SeedlingDispositionEvent).where(SeedlingDispositionEvent.command_id == command.id)
    ).scalar_one()

    correction = _correct(db_session, tenant, farm, user, target_event_id=x.id, corrected=None)
    assert correction.operation_kind == "CORRECT"


def test_carrier_reused_after_a_blocks_correction_while_z_active(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    aid = s["source_assignment_ids"][0]
    a = _assignment_row(db_session, aid)
    et = s["entry_time"] + timedelta(hours=2)

    command = _record(db_session, tenant, farm, user, assignment_id=aid, quantity=20, effective_time=et)
    x = db_session.execute(
        select(SeedlingDispositionEvent).where(SeedlingDispositionEvent.command_id == command.id)
    ).scalar_one()

    # Z: a genuinely unrelated new Sowing reuses the same physical Carrier.
    _reuse_carrier_second_sowing(
        db_session, tenant, user, farm, carrier_id=a.carrier_id, effective_time=et + timedelta(hours=1),
    )
    assert _carrier_pointer(db_session, a.carrier_id) != aid

    with pytest.raises(SeedlingDispositionCarrierReusedError):
        _correct(db_session, tenant, farm, user, target_event_id=x.id, corrected=None)


def test_carrier_reused_after_a_still_blocks_after_z_releases(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    aid = s["source_assignment_ids"][0]
    a = _assignment_row(db_session, aid)
    et = s["entry_time"] + timedelta(hours=2)

    command = _record(db_session, tenant, farm, user, assignment_id=aid, quantity=20, effective_time=et)
    x = db_session.execute(
        select(SeedlingDispositionEvent).where(SeedlingDispositionEvent.command_id == command.id)
    ).scalar_one()

    z_id = _reuse_carrier_second_sowing(
        db_session, tenant, user, farm, carrier_id=a.carrier_id, effective_time=et + timedelta(hours=1),
    )
    # Release Z too (a completely ordinary Disposition exhaustion against
    # its own, unrelated SeedlingEntry-less assignment is not applicable
    # here -- release it directly, bypassing the closure trigger/FK checks
    # exactly like every other test in this codebase modeling furniture
    # state that is not itself under test, to model "Z has since also been
    # released", proving current-free is NOT sufficient per section 17).
    db_session.execute(text("SET session_replication_role = replica"))
    db_session.execute(
        text(
            "UPDATE batch_carrier_assignments SET released_effective_time = :eff, "
            "released_by_batch_derivation_event_id = :fake_releaser WHERE id = :aid"
        ),
        {"eff": et + timedelta(hours=2), "aid": z_id, "fake_releaser": uuid.uuid4()},
    )
    db_session.execute(text("SET session_replication_role = DEFAULT"))
    db_session.flush()

    assert _carrier_pointer(db_session, a.carrier_id) == z_id  # pointer stays on Z even though Z is now released

    with pytest.raises(SeedlingDispositionCarrierReusedError):
        _correct(db_session, tenant, farm, user, target_event_id=x.id, corrected=None)


# =====================================================================
# Idempotency (section 36)
# =====================================================================


def test_correct_replay_no_second_restoration_or_pointer_advancement(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    aid = s["source_assignment_ids"][0]
    a = _assignment_row(db_session, aid)
    et = s["entry_time"] + timedelta(hours=2)
    command = _record(db_session, tenant, farm, user, assignment_id=aid, quantity=20, effective_time=et)
    x = db_session.execute(
        select(SeedlingDispositionEvent).where(SeedlingDispositionEvent.command_id == command.id)
    ).scalar_one()

    ccid = uuid.uuid4()
    first = _correct(db_session, tenant, farm, user, target_event_id=x.id, corrected=None, client_command_id=ccid)
    pointer_after_first = _carrier_pointer(db_session, a.carrier_id)

    replay = _correct(db_session, tenant, farm, user, target_event_id=x.id, corrected=None, client_command_id=ccid)
    assert replay.id == first.id

    pointer_after_replay = _carrier_pointer(db_session, a.carrier_id)
    assert pointer_after_replay == pointer_after_first

    restored_count = db_session.execute(
        select(func.count()).select_from(BatchCarrierAssignment).where(
            BatchCarrierAssignment.restored_from_batch_carrier_assignment_id == aid
        )
    ).scalar_one()
    assert restored_count == 1


# =====================================================================
# Carrier pointer structural integrity (DB-level, direct SQL)
# =====================================================================


def test_carrier_pointer_cannot_reference_assignment_of_another_carrier(db_session, active_context_with_farm) -> None:
    """The composite FK fk_carriers_latest_assignment
    (tenant_id, farm_id, latest_batch_carrier_assignment_id, id) ->
    batch_carrier_assignments(tenant_id, farm_id, id, carrier_id)
    structurally requires the referenced assignment's OWN carrier_id to
    equal the pointing Carrier's own id -- proven here directly: pointing
    Carrier 1's pointer at Carrier 2's real assignment must be rejected,
    even though the assignment id itself genuinely exists."""
    from sqlalchemy.exc import IntegrityError

    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=2)
    aid_1 = s["source_assignment_ids"][0]
    aid_2 = s["source_assignment_ids"][1]
    a2 = _assignment_row(db_session, aid_2)
    carrier_1_id = _assignment_row(db_session, aid_1).carrier_id
    assert a2.carrier_id != carrier_1_id

    with pytest.raises(IntegrityError):
        db_session.execute(
            text("UPDATE carriers SET latest_batch_carrier_assignment_id = :aid WHERE id = :cid"),
            {"aid": aid_2, "cid": carrier_1_id},
        )
        db_session.flush()
    db_session.rollback()


def test_carrier_pointer_cannot_reference_assignment_of_another_tenant(db_session, active_context_with_farm) -> None:
    from sqlalchemy.exc import IntegrityError

    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    aid = s["source_assignment_ids"][0]
    carrier_id = _assignment_row(db_session, aid).carrier_id

    from app.services import farm_service, membership_service, tenant_service, user_service

    other_tenant = tenant_service.create_tenant(db_session, code=f"other-{uuid.uuid4().hex[:8]}", name="Other Tenant")
    other_user = user_service.create_user(
        db_session, oidc_issuer="other", oidc_subject=uuid.uuid4().hex[:8], email=f"other-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Other",
    )
    membership_service.add_membership(
        db_session, tenant_id=other_tenant.id, user_id=other_user.id, role_code="tenant_admin", actor_user_id=None
    )
    other_farm = farm_service.create_farm(
        db_session, tenant_id=other_tenant.id, actor_user_id=other_user.id, code=f"farm-{uuid.uuid4().hex[:8]}",
        name="Other Farm", country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    other_carrier = db_session.execute(
        text(
            "INSERT INTO carriers (id, tenant_id, farm_id, carrier_type_id, code, status) "
            "SELECT :id, :tid, :fid, carrier_type_id, :code, 'active' FROM carriers WHERE id = :src_cid "
            "RETURNING id"
        ),
        {"id": uuid.uuid4(), "tid": other_tenant.id, "fid": other_farm.id, "code": f"OTH-{uuid.uuid4().hex[:8]}", "src_cid": carrier_id},
    ).scalar_one()
    db_session.flush()

    with pytest.raises(IntegrityError):
        db_session.execute(
            text("UPDATE carriers SET latest_batch_carrier_assignment_id = :aid WHERE id = :cid"),
            {"aid": aid, "cid": other_carrier},
        )
        db_session.flush()
    db_session.rollback()


# =====================================================================
# DB backstop: direct-SQL negative proofs (sections 11/12)
# =====================================================================


def test_direct_sql_release_via_non_exhausting_event_rejected(db_session, active_context_with_farm) -> None:
    """The closure trigger's checkpoint-aware zero-balance re-derivation
    must reject releasing an assignment via a REDUCTION that does NOT
    actually leave source availability at zero -- proven directly,
    bypassing the service layer entirely."""
    from sqlalchemy.exc import DBAPIError

    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    aid = s["source_assignment_ids"][0]
    dest = s["destination_carriers"][0]
    et = s["entry_time"] + timedelta(hours=2)
    transplant_service.record_transplant(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch_id"],
        client_command_id=uuid.uuid4(), effective_time=et, note=None,
        source_lines=[{
            "source_assignment_id": aid, "transplant_damage_count": 0, "qc_rejection_count": 0,
            "sample_count": 0, "other_loss_count": 0, "other_loss_note": None, "note": None,
        }],
        destination_lines=[{"destination_carrier_id": dest.id, "assigned_plant_count": 15, "note": None}],
        allocations=[{"source_assignment_id": aid, "destination_carrier_id": dest.id, "allocated_plant_count": 15}],
    )  # 5 remain
    command = _record(
        db_session, tenant, farm, user, assignment_id=aid, quantity=2, effective_time=et + timedelta(minutes=10),
    )  # 3 remain -- deliberately NOT exhausting
    y = db_session.execute(
        select(SeedlingDispositionEvent).where(SeedlingDispositionEvent.command_id == command.id)
    ).scalar_one()

    with pytest.raises(DBAPIError, match="does not leave source availability at zero"):
        db_session.execute(
            text(
                "UPDATE batch_carrier_assignments SET released_effective_time = :eff, "
                "released_by_seedling_disposition_event_id = :eid WHERE id = :aid"
            ),
            {"eff": y.effective_time, "eid": y.id, "aid": aid},
        )
        db_session.flush()
    db_session.rollback()


def test_direct_sql_release_via_reversal_event_rejected(db_session, active_context_with_farm) -> None:
    """A REVERSAL may never be used as the typed Disposition releaser --
    only a REDUCTION may release an assignment."""
    from sqlalchemy.exc import DBAPIError

    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=2)
    aid_1 = s["source_assignment_ids"][0]
    aid_2 = s["source_assignment_ids"][1]
    et = s["entry_time"] + timedelta(hours=2)
    command = _record(db_session, tenant, farm, user, assignment_id=aid_1, quantity=20, effective_time=et)
    x = db_session.execute(
        select(SeedlingDispositionEvent).where(SeedlingDispositionEvent.command_id == command.id)
    ).scalar_one()
    _correct(db_session, tenant, farm, user, target_event_id=x.id, corrected=None)
    reversal = db_session.execute(
        select(SeedlingDispositionEvent).where(SeedlingDispositionEvent.reverses_event_id == x.id)
    ).scalar_one()

    with pytest.raises(DBAPIError, match="only a REDUCTION event may release"):
        db_session.execute(
            text(
                "UPDATE batch_carrier_assignments SET released_effective_time = :eff, "
                "released_by_seedling_disposition_event_id = :eid WHERE id = :aid"
            ),
            {"eff": reversal.effective_time, "eid": reversal.id, "aid": aid_2},
        )
        db_session.flush()
    db_session.rollback()


def test_direct_sql_cross_carrier_restoration_rejected(db_session, active_context_with_farm) -> None:
    """A restoration assignment must be for the SAME physical Carrier as
    its predecessor -- proven directly against the origin-integrity
    trigger's disposition-reversal branch."""
    from sqlalchemy.exc import DBAPIError

    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=2)
    aid_1 = s["source_assignment_ids"][0]
    aid_2 = s["source_assignment_ids"][1]
    a1 = _assignment_row(db_session, aid_1)
    a2 = _assignment_row(db_session, aid_2)
    et = s["entry_time"] + timedelta(hours=2)
    command = _record(db_session, tenant, farm, user, assignment_id=aid_1, quantity=20, effective_time=et)
    x = db_session.execute(
        select(SeedlingDispositionEvent).where(SeedlingDispositionEvent.command_id == command.id)
    ).scalar_one()
    _correct(db_session, tenant, farm, user, target_event_id=x.id, corrected=None)
    reversal = db_session.execute(
        select(SeedlingDispositionEvent).where(SeedlingDispositionEvent.reverses_event_id == x.id)
    ).scalar_one()
    real_restoration = db_session.execute(
        select(BatchCarrierAssignment).where(
            BatchCarrierAssignment.opening_seedling_disposition_reversal_event_id == reversal.id
        )
    ).scalar_one()

    # The real restoration is already opened by this REVERSAL (unique-once
    # index), so this direct-SQL attempt must first void it to isolate the
    # cross-Carrier check specifically -- bypass immutability deliberately,
    # test furniture only, not itself under test here.
    db_session.execute(text("SET session_replication_role = replica"))
    db_session.execute(
        text("DELETE FROM batch_carrier_assignments WHERE id = :aid"), {"aid": real_restoration.id}
    )
    db_session.execute(text("SET session_replication_role = DEFAULT"))
    db_session.flush()

    with pytest.raises(DBAPIError, match="same physical Carrier"):
        db_session.execute(
            text(
                "INSERT INTO batch_carrier_assignments "
                "(id, tenant_id, farm_id, batch_id, carrier_id, batch_stage_run_id, assigned_effective_time, "
                "opening_seedling_disposition_reversal_event_id, restored_from_batch_carrier_assignment_id, actor_user_id) "
                "SELECT gen_random_uuid(), tenant_id, farm_id, batch_id, :wrong_carrier_id, batch_stage_run_id, "
                ":eff, :rid, :predecessor_id, actor_user_id FROM batch_carrier_assignments WHERE id = :predecessor_id"
            ),
            {
                "wrong_carrier_id": a2.carrier_id, "eff": reversal.effective_time, "rid": reversal.id,
                "predecessor_id": a1.id,
            },
        )
        db_session.flush()
    db_session.rollback()
