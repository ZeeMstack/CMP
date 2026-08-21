"""WORKFLOW-INTEGRITY-001: a CropBatch may not leave a transplanting-
category BatchStageRun while any SeedlingEntry belonging to it still has
positive current source availability (structural checkpoint chain-tip
anchor plus applicable Seedling Disposition deltas, evaluated as of the
transition's own effective_time). Reuses `build_transplant_ready_scenario`
exactly as `test_transplant_correction.py` does, since real SeedlingEntry/
checkpoint history is required -- a synthetic stage-only scenario cannot
exercise this guard meaningfully."""
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.models.audit_event import AuditEvent
from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.batch_stage_run import BatchStageRun
from app.models.batch_stage_transition import BatchStageTransition
from app.services import (
    crop_batch_service,
    movement_service,
    seedling_disposition_service,
    transplant_correction_service,
    transplant_service,
)
from app.services.errors import (
    BatchStageHasUnresolvedSeedlingRemainderError,
    ConfiguredTransitionNotFoundError,
    CropBatchClosedError,
    QualityHoldOpenError,
    StageMismatchError,
)
from tests._transplant_scenario import build_transplant_ready_scenario, now as _now

pytestmark = pytest.mark.integration


def _build_scenario(db_session, tenant, user, farm, **kwargs):
    kwargs.setdefault("tray_count", 1)
    kwargs.setdefault("normal", 200)
    kwargs.setdefault("abnormal", 0)
    kwargs.setdefault("transplanting_required_type", "cultivation_plate")
    return build_transplant_ready_scenario(db_session, tenant, user, farm, **kwargs)


def _simple_source(assignment_id, **overrides):
    defaults = dict(
        source_assignment_id=assignment_id, transplant_damage_count=0, qc_rejection_count=0, sample_count=0,
        other_loss_count=0, other_loss_note=None, note=None,
    )
    defaults.update(overrides)
    return defaults


def _simple_destination(carrier_id, count=200, **overrides):
    defaults = dict(destination_carrier_id=carrier_id, assigned_plant_count=count, note=None)
    defaults.update(overrides)
    return defaults


def _simple_allocation(source_id, dest_id, count=200):
    return {"source_assignment_id": source_id, "destination_carrier_id": dest_id, "allocated_plant_count": count}


def _transplant(db_session, tenant, farm, user, batch, source_lines, destination_lines, allocations, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
    )
    defaults.update(overrides)
    return transplant_service.record_transplant(
        db_session, source_lines=source_lines, destination_lines=destination_lines, allocations=allocations,
        **defaults,
    )


def _leave_transplanting(db_session, tenant, farm, user, s, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch_id"],
        client_command_id=uuid.uuid4(), configured_transition_id=s["transitions"]["t2"].id,
        effective_time=_now(), reason=None,
    )
    defaults.update(overrides)
    return crop_batch_service.transition_stage(db_session, **defaults)


# --- Core blocking / allowing ------------------------------------------------------


def test_single_source_positive_remainder_blocks_and_error_is_structured(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    aid = s["source_assignment_ids"][0]
    dest = s["destination_carriers"][0]
    _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(dest.id, count=170)], [_simple_allocation(aid, dest.id, 170)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )  # 30 remain unresolved

    with pytest.raises(BatchStageHasUnresolvedSeedlingRemainderError) as excinfo:
        _leave_transplanting(db_session, tenant, farm, user, s, effective_time=s["entry_time"] + timedelta(hours=3))
    assert excinfo.value.unresolved_source_count == 1
    assert excinfo.value.total_unresolved_living_count == 30


def test_multiple_sources_one_positive_blocks(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=3)
    a, b, c = s["source_assignment_ids"]
    dests = s["destination_carriers"]
    et = s["entry_time"] + timedelta(hours=2)
    # A fully resolved (200), B partially (180, 20 remain), C fully resolved (200).
    _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(a)], [_simple_destination(dests[0].id, count=200)], [_simple_allocation(a, dests[0].id, 200)],
        effective_time=et,
    )
    _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(b)], [_simple_destination(dests[1].id, count=180)], [_simple_allocation(b, dests[1].id, 180)],
        effective_time=et,
    )
    _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(c)], [_simple_destination(dests[2].id, count=200)], [_simple_allocation(c, dests[2].id, 200)],
        effective_time=et,
    )
    with pytest.raises(BatchStageHasUnresolvedSeedlingRemainderError) as excinfo:
        _leave_transplanting(db_session, tenant, farm, user, s, effective_time=et + timedelta(hours=1))
    assert excinfo.value.unresolved_source_count == 1
    assert excinfo.value.total_unresolved_living_count == 20


def test_all_sources_zero_via_sequential_transplant_allows_exit(db_session, active_context_with_farm) -> None:
    """Also proves: partial Transplant followed by a later Transplant
    resolving the remainder allows exit, and destination-Plate living
    population (180 + 20 across two Plates here) never itself blocks."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    aid = s["source_assignment_ids"][0]
    dest1, dest2 = s["destination_carriers"][0], s["destination_carriers"][1]
    et = s["entry_time"] + timedelta(hours=2)
    _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(dest1.id, count=180)], [_simple_allocation(aid, dest1.id, 180)],
        effective_time=et,
    )
    # Still 20 remaining -- would block here.
    with pytest.raises(BatchStageHasUnresolvedSeedlingRemainderError):
        _leave_transplanting(db_session, tenant, farm, user, s, effective_time=et + timedelta(minutes=30))

    # A second, sequential Transplant resolves the remainder.
    _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(dest2.id, count=20)], [_simple_allocation(aid, dest2.id, 20)],
        effective_time=et + timedelta(hours=1),
    )
    transition = _leave_transplanting(db_session, tenant, farm, user, s, effective_time=et + timedelta(hours=2))
    assert transition is not None


def test_disposition_resolves_final_remainder_allows_exit_even_though_assignment_stays_active(
    db_session, active_context_with_farm
) -> None:
    """Covers matrix items 6, 7, and 22: WORKFLOW-INTEGRITY-001 protects
    biological completeness only -- it must never accidentally become a
    Carrier-cleanup rule. The known, separate SEEDLING-DISPOSITION-
    LIFECYCLE-001 gap (Disposition-driven exhaustion does not release the
    BatchCarrierAssignment) must not cause a false block here."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    aid = s["source_assignment_ids"][0]
    dest = s["destination_carriers"][0]
    et = s["entry_time"] + timedelta(hours=2)
    _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(dest.id, count=180)], [_simple_allocation(aid, dest.id, 180)],
        effective_time=et,
    )
    # Resolve the remaining 20 entirely through Disposition -- no further Transplant.
    seedling_disposition_service.record_disposition(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        batch_carrier_assignment_id=aid, quantity=20, reason_code="OTHER",
        effective_time=et + timedelta(minutes=30), note="resolved via disposition, no further transplant",
    )

    # The known, separate lifecycle gap: the assignment is NOT released by Disposition.
    assignment = db_session.get(BatchCarrierAssignment, aid)
    assert assignment.released_effective_time is None

    # Stage exit must still succeed -- biological truth, not administrative state.
    transition = _leave_transplanting(db_session, tenant, farm, user, s, effective_time=et + timedelta(hours=1))
    assert transition is not None


# --- Correction interaction ---------------------------------------------------------


def test_correction_before_exit_restores_then_replacement_resolves(db_session, active_context_with_farm) -> None:
    """Covers matrix items 8, 9, 10, and 17: correction-driven eligibility
    flows naturally through the same chain-tip/delta authority, with zero
    correction-specific logic in the guard itself."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    aid = s["source_assignment_ids"][0]
    dest = s["destination_carriers"][0]
    dest2 = s["destination_carriers"][1]
    et = s["entry_time"] + timedelta(hours=2)
    # Wrong: recorded as fully resolved (200), but it should only have been
    # 170. The batch is still in TRANSPLANTING throughout this whole test --
    # TRANSPLANT-CORRECTION-001's own stage-eligibility rule requires the
    # target's active_batch_stage_run_id to still be the batch's current
    # run, so correction must happen (and this test must prove the guard)
    # BEFORE any successful exit, never after.
    target = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(dest.id, count=200)], [_simple_allocation(aid, dest.id, 200)],
        effective_time=et,
    )
    # As originally (wrongly) recorded, biology reads fully resolved --
    # checked via the read helper directly (not by actually transitioning,
    # which would move the batch out of TRANSPLANTING and make the
    # subsequent correction attempt below fail on its OWN, unrelated
    # stage-eligibility rule).
    count, total = seedling_disposition_service.get_unresolved_seedling_remainder(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=s["batch_id"], as_of=et + timedelta(hours=1),
    )
    assert (count, total) == (0, 0)

    # Correct it: void the full-resolution record (restores 200), then
    # replacement legitimately resolves only 170, leaving 30.
    reversal = transplant_correction_service.correct_transplant(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch_id"],
        target_transplant_event_id=target.id, client_command_id=uuid.uuid4(), reason="wrong quantity",
        replacement={
            "note": None,
            "source_lines": [_simple_source(aid)],
            "destination_lines": [_simple_destination(dest2.id, count=170)],
            "allocations": [_simple_allocation(aid, dest2.id, 170)],
        },
    )
    assert reversal.event_kind == "REVERSAL"

    # 30 remain unresolved again -- exit must be blocked again.
    with pytest.raises(BatchStageHasUnresolvedSeedlingRemainderError) as excinfo:
        _leave_transplanting(db_session, tenant, farm, user, s, effective_time=et + timedelta(hours=2))
    assert excinfo.value.total_unresolved_living_count == 30

    # Resolve the remaining 30 via Disposition -- exit becomes eligible again.
    seedling_disposition_service.record_disposition(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        batch_carrier_assignment_id=aid, quantity=30, reason_code="OTHER",
        effective_time=et + timedelta(hours=2, minutes=30), note="resolves the corrected remainder",
    )
    assert (
        _leave_transplanting(db_session, tenant, farm, user, s, effective_time=et + timedelta(hours=3)) is not None
    )


# --- Boundaries: Movement, Quality Hold, non-transplanting stage, closed batch -----


def test_physical_movement_does_not_affect_eligibility(db_session, active_context_with_farm) -> None:
    from app.services import carrier_specification_service

    tenant, user, _headers, farm = active_context_with_farm
    spec = carrier_specification_service.register_carrier_specification(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, carrier_type_code="nursery_cultivation_plate",
        code=f"NCP-{uuid.uuid4().hex[:8]}", name="200 Hole Nursery Plate", length_mm=500, width_mm=300, height_mm=60,
        biological_position_count=200,
    )
    s = _build_scenario(
        db_session, tenant, user, farm, tray_count=1, transplanting_required_type="nursery_cultivation_plate",
        destination_specification_id=spec.id, intersalads_table_count=1,
    )
    aid = s["source_assignment_ids"][0]
    dest = s["destination_carriers"][0]
    et = s["entry_time"] + timedelta(hours=2)
    _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(dest.id, count=200)], [_simple_allocation(aid, dest.id, 200)],
        effective_time=et,
    )
    movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        effective_time=et + timedelta(minutes=30), occupant_kind="carrier", occupant_id=dest.id,
        destination_kind="location", destination_id=s["intersalads_table_ids"][0], reason=None,
    )
    transition = _leave_transplanting(db_session, tenant, farm, user, s, effective_time=et + timedelta(hours=1))
    assert transition is not None


def test_open_quality_hold_blocks_independently_even_at_zero_remainder(db_session, active_context_with_farm) -> None:
    from app.services import quality_hold_service

    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    aid = s["source_assignment_ids"][0]
    dest = s["destination_carriers"][0]
    et = s["entry_time"] + timedelta(hours=2)
    _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(dest.id, count=200)], [_simple_allocation(aid, dest.id, 200)],
        effective_time=et,
    )  # fully resolved -- biology alone would allow exit
    quality_hold_service.place_quality_hold(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        batch_id=s["batch_id"], effective_time=et + timedelta(minutes=10), source_observation_event_id=None,
        reason_code="LOW-GERMINATION", reason_text="qc concern",
    )
    with pytest.raises(QualityHoldOpenError):
        _leave_transplanting(db_session, tenant, farm, user, s, effective_time=et + timedelta(hours=1))


def test_leaving_seeding_stage_never_applies_this_guard(db_session, active_context_with_farm) -> None:
    """The first stage transition (SEEDING -> TRANSPLANTING, `t1`) happens
    before any Transplant is even possible -- every Tray necessarily still
    holds its full, untouched population at that moment. If the guard were
    (incorrectly) scoped to ANY stage carrying live SeedlingEntries rather
    than specifically `transplanting`-category exits, this transition
    would always fail, since nothing has ever had a chance to resolve
    anything yet. `build_transplant_ready_scenario` performs exactly this
    transition internally, as its own last setup step before returning --
    its plain success (no exception) with every Tray still at full 200 is
    the proof; asserted here explicitly rather than left implicit."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=2)  # succeeds only if t1 above already worked
    for aid in s["source_assignment_ids"]:
        assignment = db_session.get(BatchCarrierAssignment, aid)
        assert assignment.released_effective_time is None  # untouched, full 200 each
    current_stage = db_session.execute(
        select(BatchCarrierAssignment.batch_stage_run_id).where(BatchCarrierAssignment.id == s["source_assignment_ids"][0])
    ).scalar_one()
    assert current_stage is not None  # the SEEDING-run assignment itself remains a valid, untouched historical fact


def test_wrong_configured_transition_retains_existing_error_precedence(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    aid = s["source_assignment_ids"][0]
    dest = s["destination_carriers"][0]
    et = s["entry_time"] + timedelta(hours=2)
    _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(dest.id, count=170)], [_simple_allocation(aid, dest.id, 170)],
        effective_time=et,
    )  # 30 remain -- would trip the biological guard if reached

    # t1 (SEEDING->TRANSPLANTING) no longer matches the batch's CURRENT
    # stage (already TRANSPLANTING) -- must fail with StageMismatchError,
    # never the biological error, even though remainder is positive.
    with pytest.raises(StageMismatchError):
        _leave_transplanting(
            db_session, tenant, farm, user, s, configured_transition_id=s["transitions"]["t1"].id,
            effective_time=et + timedelta(hours=1),
        )
    with pytest.raises(ConfiguredTransitionNotFoundError):
        _leave_transplanting(
            db_session, tenant, farm, user, s, configured_transition_id=uuid.uuid4(),
            effective_time=et + timedelta(hours=1),
        )


def test_closed_batch_retains_existing_behavior(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    aid = s["source_assignment_ids"][0]
    dest = s["destination_carriers"][0]
    et = s["entry_time"] + timedelta(hours=2)
    _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(dest.id, count=200)], [_simple_allocation(aid, dest.id, 200)],
        effective_time=et,
    )
    _leave_transplanting(db_session, tenant, farm, user, s, effective_time=et + timedelta(hours=1))
    # Advance again, to the terminal COMPLETE stage, closing the batch.
    crop_batch_service.transition_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch_id"],
        client_command_id=uuid.uuid4(), configured_transition_id=s["transitions"]["t3"].id,
        effective_time=et + timedelta(hours=2), reason=None,
    )
    with pytest.raises(CropBatchClosedError):
        crop_batch_service.transition_stage(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch_id"],
            client_command_id=uuid.uuid4(), configured_transition_id=s["transitions"]["t3"].id,
            effective_time=et + timedelta(hours=3), reason=None,
        )


# --- As-of semantics and chronology --------------------------------------------------


def test_disposition_effective_after_requested_transition_time_does_not_resolve_it(
    db_session, active_context_with_farm
) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    aid = s["source_assignment_ids"][0]
    dest = s["destination_carriers"][0]
    et = s["entry_time"] + timedelta(hours=2)
    _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(dest.id, count=180)], [_simple_allocation(aid, dest.id, 180)],
        effective_time=et,
    )
    # Disposition resolves the remainder at 15:00-equivalent (et + 3h)...
    seedling_disposition_service.record_disposition(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        batch_carrier_assignment_id=aid, quantity=20, reason_code="OTHER",
        effective_time=et + timedelta(hours=3), note="resolved later",
    )
    # ...but the transition is requested at an EARLIER effective_time (et + 1h)
    # -- the later disposition must not retroactively validate it.
    with pytest.raises(BatchStageHasUnresolvedSeedlingRemainderError):
        _leave_transplanting(db_session, tenant, farm, user, s, effective_time=et + timedelta(hours=1))

    # Requested at/after the disposition's own time, it is correctly resolved.
    assert (
        _leave_transplanting(db_session, tenant, farm, user, s, effective_time=et + timedelta(hours=4)) is not None
    )


def test_disposition_cannot_equal_current_checkpoint_effective_time(db_session, active_context_with_farm) -> None:
    from app.services.errors import SeedlingDispositionPredatesCheckpointError

    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    aid = s["source_assignment_ids"][0]
    dest = s["destination_carriers"][0]
    et = s["entry_time"] + timedelta(hours=2)
    _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(dest.id, count=180)], [_simple_allocation(aid, dest.id, 180)],
        effective_time=et,
    )
    with pytest.raises(SeedlingDispositionPredatesCheckpointError):
        seedling_disposition_service.record_disposition(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            batch_carrier_assignment_id=aid, quantity=5, reason_code="OTHER",
            effective_time=et, note="exactly the checkpoint's own time",
        )


def test_no_successful_audit_event_on_rejected_transition(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    aid = s["source_assignment_ids"][0]
    dest = s["destination_carriers"][0]
    et = s["entry_time"] + timedelta(hours=2)
    _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(dest.id, count=170)], [_simple_allocation(aid, dest.id, 170)],
        effective_time=et,
    )
    before = db_session.execute(
        select(AuditEvent.id).where(AuditEvent.action.in_(["crop_batch.stage_transitioned", "crop_batch.closed"]))
    ).scalars().all()
    with pytest.raises(BatchStageHasUnresolvedSeedlingRemainderError):
        _leave_transplanting(db_session, tenant, farm, user, s, effective_time=et + timedelta(hours=1))
    after = db_session.execute(
        select(AuditEvent.id).where(AuditEvent.action.in_(["crop_batch.stage_transitioned", "crop_batch.closed"]))
    ).scalars().all()
    assert len(after) == len(before)


def test_rejected_attempt_does_not_poison_retry_idempotency(db_session, active_context_with_farm) -> None:
    """A guard-rejected attempt must not reserve its `client_command_id` --
    the guard raises before `db.add(BatchStageTransition)`, so no command
    record exists to replay against. Once the same remainder is resolved,
    retrying the exact same command (same client_command_id, same payload)
    must succeed cleanly: exactly one BatchStageTransition, exactly one
    audit event, no duplicate BatchStageRun."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    aid = s["source_assignment_ids"][0]
    dest = s["destination_carriers"][0]
    et = s["entry_time"] + timedelta(hours=2)
    _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(dest.id, count=170)], [_simple_allocation(aid, dest.id, 170)],
        effective_time=et,
    )  # 30 remain unresolved

    command_id = uuid.uuid4()
    transition_effective_time = et + timedelta(hours=1)

    # Baseline: the scenario builder's own SEEDING->TRANSPLANTING setup
    # transition already produced one `crop_batch.stage_transitioned` audit
    # event for this batch -- count from here, not from zero.
    audit_before = db_session.execute(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action == "crop_batch.stage_transitioned", AuditEvent.entity_id == s["batch_id"],
        )
    ).scalar_one()
    run_count_before = db_session.execute(
        select(func.count()).select_from(BatchStageRun).where(BatchStageRun.batch_id == s["batch_id"])
    ).scalar_one()

    # 1-4: first attempt is rejected while the remainder is positive.
    with pytest.raises(BatchStageHasUnresolvedSeedlingRemainderError):
        _leave_transplanting(
            db_session, tenant, farm, user, s,
            client_command_id=command_id, effective_time=transition_effective_time,
        )

    # 5: resolve the remainder through a legitimate existing operation
    # (Disposition), effective before the transition's own requested time
    # so it is visible to the guard's as_of evaluation on retry.
    seedling_disposition_service.record_disposition(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        batch_carrier_assignment_id=aid, quantity=30, reason_code="OTHER",
        effective_time=et + timedelta(minutes=30), note="resolves the remainder before retry",
    )

    # 6-7: retry the SAME command_id with the SAME payload (identical
    # effective_time/configured_transition_id/reason) -- must now succeed.
    transition = _leave_transplanting(
        db_session, tenant, farm, user, s,
        client_command_id=command_id, effective_time=transition_effective_time,
    )
    assert transition is not None

    # 8: exactly one successful BatchStageTransition for this command.
    transition_count = db_session.execute(
        select(func.count()).select_from(BatchStageTransition).where(
            BatchStageTransition.batch_id == s["batch_id"], BatchStageTransition.command_kind == "stage_transition",
            BatchStageTransition.client_command_id == command_id,
        )
    ).scalar_one()
    assert transition_count == 1

    # 9: exactly one successful transition audit event was added by this
    # command (on top of the scenario's own baseline).
    audit_after = db_session.execute(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action == "crop_batch.stage_transitioned", AuditEvent.entity_id == s["batch_id"],
        )
    ).scalar_one()
    assert audit_after - audit_before == 1

    # 10: no duplicate stage run -- exactly one new run was opened by this
    # successful transition (on top of the scenario's own baseline runs).
    run_count_after = db_session.execute(
        select(func.count()).select_from(BatchStageRun).where(BatchStageRun.batch_id == s["batch_id"])
    ).scalar_one()
    assert run_count_after - run_count_before == 1

    # Idempotent replay of the exact same (now-successful) command still
    # returns the original transition, unchanged.
    replay = _leave_transplanting(
        db_session, tenant, farm, user, s,
        client_command_id=command_id, effective_time=transition_effective_time,
    )
    assert replay.id == transition.id
