import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.core.permissions import Permission, has_permission
from app.models.audit_event import AuditEvent
from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.seedling_source_checkpoint import SeedlingSourceCheckpoint
from app.models.transplant_event import TransplantEvent
from app.models.transplant_source_line import TransplantSourceLine
from app.services import (
    batch_derivation_service,
    crop_batch_service,
    movement_service,
    seedling_disposition_service,
    seedling_source_lineage,
    transplant_correction_service,
    transplant_service,
)
from app.services.errors import (
    BatchDerivationValidationError,
    CropBatchClosedError,
    TransplantAlreadyCorrectedError,
    TransplantCorrectionCommandReusedWithDifferentPayloadError,
    TransplantCorrectionNotChainTipError,
    TransplantCorrectionStageMismatchError,
    TransplantCorrectionTargetKindNotEligibleError,
    TransplantCorrectionValidationError,
)
from tests._transplant_scenario import build_transplant_ready_scenario, now as _now

pytestmark = pytest.mark.integration


def _build_scenario(db_session, tenant, user, farm, **kwargs):
    kwargs.setdefault("tray_count", 4)
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


def _correct(db_session, tenant, farm, user, batch, target_event_id, *, reason="correction", replacement=None, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        target_transplant_event_id=target_event_id, client_command_id=uuid.uuid4(), reason=reason,
        replacement=replacement,
    )
    defaults.update(overrides)
    return transplant_correction_service.correct_transplant(db_session, **defaults)


# --- Pure void ---------------------------------------------------------------------


def test_pure_void_reverses_all_source_effects(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    aid = s["source_assignment_ids"][0]
    dest = s["destination_carriers"][0]
    target = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(dest.id)], [_simple_allocation(aid, dest.id)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )

    reversal = _correct(db_session, tenant, farm, user, s["batch"], target.id)

    assert reversal.event_kind == "REVERSAL"
    assert reversal.reverses_transplant_event_id == target.id
    assert reversal.correction_reason == "correction"
    assert reversal.effective_time == target.effective_time

    # Destination assignment released by the reversal.
    dest_assignment = db_session.execute(
        select(BatchCarrierAssignment).where(BatchCarrierAssignment.opening_transplant_event_id == target.id)
    ).scalar_one()
    assert dest_assignment.released_by_transplant_event_id == reversal.id
    assert dest_assignment.released_effective_time == target.effective_time

    # Original source assignment A: was never released (200 - 200 = 0
    # remainder released it), so it should have been released BY THE
    # TARGET (full exhaustion) and a restored assignment B should now exist.
    original = db_session.get(BatchCarrierAssignment, aid)
    assert original.released_by_transplant_event_id == target.id
    restored = db_session.execute(
        select(BatchCarrierAssignment).where(BatchCarrierAssignment.restored_from_batch_carrier_assignment_id == aid)
    ).scalar_one()
    assert restored.opening_transplant_reversal_event_id == reversal.id
    assert restored.released_effective_time is None
    assert restored.carrier_id == original.carrier_id

    # Checkpoint restored to the full pre-target quantity, referencing B.
    checkpoint = db_session.execute(
        select(SeedlingSourceCheckpoint).where(
            SeedlingSourceCheckpoint.source_batch_carrier_assignment_id == restored.id
        )
    ).scalar_one()
    assert checkpoint.remainder_after == 200

    resolver_result = transplant_correction_service.resolve_authoritative_transplant(db_session, event_id=target.id)
    assert resolver_result is None  # voided


def test_wrong_quantity_correction_non_exhausted_source(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    aid = s["source_assignment_ids"][0]
    dest = s["destination_carriers"][0]
    dest2 = s["destination_carriers"][1]
    # Mistakenly transplant only 150 of 200 -- remainder 50, assignment stays active.
    target = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(dest.id, count=150)], [_simple_allocation(aid, dest.id, 150)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    original = db_session.get(BatchCarrierAssignment, aid)
    assert original.released_effective_time is None  # not exhausted

    replacement = {
        "note": None,
        "source_lines": [_simple_source(aid)],
        "destination_lines": [_simple_destination(dest2.id, count=200)],
        "allocations": [_simple_allocation(aid, dest2.id, 200)],
    }
    reversal = _correct(db_session, tenant, farm, user, s["batch"], target.id, replacement=replacement)

    described = transplant_correction_service.describe_correction(db_session, tenant_id=tenant.id, reversal_event_id=reversal.id)
    assert described["status"] == "corrected"
    replacement_event = db_session.get(TransplantEvent, described["replacement_event_id"])
    assert replacement_event.event_kind == "REPLACEMENT"
    assert replacement_event.corrects_transplant_event_id == target.id
    assert replacement_event.effective_time == target.effective_time

    resolver_result = transplant_correction_service.resolve_authoritative_transplant(db_session, event_id=target.id)
    assert resolver_result == replacement_event.id


# --- Full exhaustion restoration + reuse -------------------------------------------


def test_full_exhaustion_restored_tray_is_fully_usable(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    aid = s["source_assignment_ids"][0]
    dest = s["destination_carriers"][0]
    target = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(dest.id)], [_simple_allocation(aid, dest.id)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    reversal = _correct(db_session, tenant, farm, user, s["batch"], target.id)
    restored = db_session.execute(
        select(BatchCarrierAssignment).where(BatchCarrierAssignment.restored_from_batch_carrier_assignment_id == aid)
    ).scalar_one()

    # Appears in the biological Tray listing as active again.
    trays = seedling_disposition_service.list_seedling_biological_trays(db_session, tenant_id=tenant.id, farm_id=farm.id)
    row = next(t for t in trays if t.batch_carrier_assignment_id == restored.id)
    assert row.assignment_active is True
    assert row.current_source_available_count == 200

    # Seedling Disposition works against the restored assignment.
    command = seedling_disposition_service.record_disposition(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        batch_carrier_assignment_id=restored.id, quantity=10, reason_code="OTHER",
        effective_time=target.effective_time + timedelta(minutes=1), note="restored-tray disposition",
    )
    assert command is not None

    # A brand-new ordinary Transplant can source from the restored Tray.
    dest2 = s["destination_carriers"][1]
    new_transplant = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(restored.id)], [_simple_destination(dest2.id, count=190)],
        [_simple_allocation(restored.id, dest2.id, 190)],
        effective_time=target.effective_time + timedelta(minutes=2),
    )
    assert new_transplant.event_kind == "RECORD"
    db_session.refresh(restored)
    assert restored.released_effective_time == new_transplant.effective_time  # fully exhausted normally


def test_same_plate_reversal_release_then_replacement_open(db_session, active_context_with_farm) -> None:
    """Section 30 case A: destination corrected to the SAME Plate carrier
    within one correction transaction -- release-then-flush-then-insert."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    aid = s["source_assignment_ids"][0]
    wrong_dest = s["destination_carriers"][0]
    target = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(wrong_dest.id)], [_simple_allocation(aid, wrong_dest.id)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    replacement = {
        "note": None,
        "source_lines": [_simple_source(aid)],
        "destination_lines": [_simple_destination(wrong_dest.id)],  # SAME carrier
        "allocations": [_simple_allocation(aid, wrong_dest.id)],
    }
    reversal = _correct(db_session, tenant, farm, user, s["batch"], target.id, replacement=replacement)
    described = transplant_correction_service.describe_correction(db_session, tenant_id=tenant.id, reversal_event_id=reversal.id)
    replacement_event = db_session.get(TransplantEvent, described["replacement_event_id"])
    new_dest_assignment = db_session.execute(
        select(BatchCarrierAssignment).where(BatchCarrierAssignment.opening_transplant_event_id == replacement_event.id)
    ).scalar_one()
    assert new_dest_assignment.carrier_id == wrong_dest.id
    assert new_dest_assignment.released_effective_time is None


def test_restored_source_immediately_reconsumed_and_closed(db_session, active_context_with_farm) -> None:
    """Section 30 case B: restored source assignment opened by REVERSAL @ T
    then fully closed by REPLACEMENT @ T in the same transaction."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    aid = s["source_assignment_ids"][0]
    dest = s["destination_carriers"][0]
    dest2 = s["destination_carriers"][1]
    target = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(dest.id)], [_simple_allocation(aid, dest.id)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    replacement = {
        "note": None,
        "source_lines": [_simple_source(aid)],  # remapped to the restored assignment internally
        "destination_lines": [_simple_destination(dest2.id)],
        "allocations": [_simple_allocation(aid, dest2.id)],
    }
    reversal = _correct(db_session, tenant, farm, user, s["batch"], target.id, replacement=replacement)
    restored = db_session.execute(
        select(BatchCarrierAssignment).where(BatchCarrierAssignment.restored_from_batch_carrier_assignment_id == aid)
    ).scalar_one()
    assert restored.opening_transplant_reversal_event_id == reversal.id
    assert restored.assigned_effective_time == target.effective_time
    assert restored.released_effective_time == target.effective_time  # closed same T, same transaction


# --- Checkpoint authority / chronology ----------------------------------------------


def test_ordinary_independent_record_same_time_still_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    aid = s["source_assignment_ids"][0]
    dest = s["destination_carriers"][0]
    dest2 = s["destination_carriers"][1]
    et = s["entry_time"] + timedelta(hours=2)
    _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(dest.id, count=100)], [_simple_allocation(aid, dest.id, 100)],
        effective_time=et,
    )
    from app.services.errors import InvalidTransplantEffectiveTimeError

    with pytest.raises(InvalidTransplantEffectiveTimeError):
        _transplant(
            db_session, tenant, farm, user, s["batch"],
            [_simple_source(aid)], [_simple_destination(dest2.id, count=50)], [_simple_allocation(aid, dest2.id, 50)],
            effective_time=et,  # exact same time as the first, independent RECORD
        )


# --- Eligibility ----------------------------------------------------------------


def test_later_source_checkpoint_blocks_correction(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    aid = s["source_assignment_ids"][0]
    dest = s["destination_carriers"][0]
    dest2 = s["destination_carriers"][1]
    et = s["entry_time"] + timedelta(hours=2)
    target = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(dest.id, count=100)], [_simple_allocation(aid, dest.id, 100)],
        effective_time=et,
    )
    # A second, later transplant consumes more of the same (still-active) source.
    _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(dest2.id, count=50)], [_simple_allocation(aid, dest2.id, 50)],
        effective_time=et + timedelta(hours=1),
    )
    with pytest.raises(TransplantCorrectionNotChainTipError):
        _correct(db_session, tenant, farm, user, s["batch"], target.id)


def test_already_corrected_target_blocked(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    aid = s["source_assignment_ids"][0]
    dest = s["destination_carriers"][0]
    target = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(dest.id)], [_simple_allocation(aid, dest.id)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    _correct(db_session, tenant, farm, user, s["batch"], target.id)
    with pytest.raises(TransplantAlreadyCorrectedError):
        _correct(db_session, tenant, farm, user, s["batch"], target.id)


def test_reversal_itself_cannot_be_corrected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    aid = s["source_assignment_ids"][0]
    dest = s["destination_carriers"][0]
    target = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(dest.id)], [_simple_allocation(aid, dest.id)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    reversal = _correct(db_session, tenant, farm, user, s["batch"], target.id)
    with pytest.raises(TransplantCorrectionTargetKindNotEligibleError):
        _correct(db_session, tenant, farm, user, s["batch"], reversal.id)


def test_batch_derivation_rejects_reversal_restored_assignment(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    aid = s["source_assignment_ids"][0]
    dest = s["destination_carriers"][0]
    target = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(dest.id)], [_simple_allocation(aid, dest.id)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    _correct(db_session, tenant, farm, user, s["batch"], target.id)
    restored = db_session.execute(
        select(BatchCarrierAssignment).where(BatchCarrierAssignment.restored_from_batch_carrier_assignment_id == aid)
    ).scalar_one()
    with pytest.raises(BatchDerivationValidationError):
        batch_derivation_service._derive_transferred_quantity(db_session, restored)


# --- Idempotency ------------------------------------------------------------------


def test_correction_exact_replay_returns_same_reversal(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    aid = s["source_assignment_ids"][0]
    dest = s["destination_carriers"][0]
    target = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(dest.id)], [_simple_allocation(aid, dest.id)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    outer_id = uuid.uuid4()
    first = _correct(db_session, tenant, farm, user, s["batch"], target.id, client_command_id=outer_id)
    second = _correct(db_session, tenant, farm, user, s["batch"], target.id, client_command_id=outer_id)
    assert first.id == second.id


def test_correction_same_command_different_payload_conflict(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    aid = s["source_assignment_ids"][0]
    dest = s["destination_carriers"][0]
    target = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(dest.id)], [_simple_allocation(aid, dest.id)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    outer_id = uuid.uuid4()
    _correct(db_session, tenant, farm, user, s["batch"], target.id, client_command_id=outer_id, reason="first reason")
    with pytest.raises(TransplantCorrectionCommandReusedWithDifferentPayloadError):
        _correct(db_session, tenant, farm, user, s["batch"], target.id, client_command_id=outer_id, reason="different reason")


# --- Authorization ------------------------------------------------------------------


def test_transplant_correct_permission_matrix() -> None:
    from app.core.auth import TenantContext

    approved = {"tenant_admin", "farm_manager", "head_grower", "production_supervisor"}
    denied = {
        "operator", "storekeeper", "qc_officer", "packing_supervisor", "cold_store_supervisor",
        "dispatch_officer", "auditor", "read_only",
    }
    for role in approved:
        ctx = TenantContext(tenant_id=uuid.uuid4(), user_id=uuid.uuid4(), role_code=role)
        assert has_permission(ctx, Permission.TRANSPLANT_CORRECT), role
    for role in denied:
        ctx = TenantContext(tenant_id=uuid.uuid4(), user_id=uuid.uuid4(), role_code=role)
        assert not has_permission(ctx, Permission.TRANSPLANT_CORRECT), role


# --- Audit ------------------------------------------------------------------------


def test_audit_exactly_one_correction_event_no_misleading_transplanted(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    aid = s["source_assignment_ids"][0]
    dest = s["destination_carriers"][0]
    dest2 = s["destination_carriers"][1]
    target = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(dest.id)], [_simple_allocation(aid, dest.id)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    before_count = db_session.execute(
        select(AuditEvent.id).where(AuditEvent.action == "crop_batch.transplanted")
    ).scalars().all()

    replacement = {
        "note": None,
        "source_lines": [_simple_source(aid)],
        "destination_lines": [_simple_destination(dest2.id)],
        "allocations": [_simple_allocation(aid, dest2.id)],
    }
    reversal = _correct(db_session, tenant, farm, user, s["batch"], target.id, replacement=replacement)

    corrected_events = db_session.execute(
        select(AuditEvent).where(
            AuditEvent.action == "crop_batch.transplant_corrected", AuditEvent.entity_id == reversal.id
        )
    ).scalars().all()
    assert len(corrected_events) == 1
    assert corrected_events[0].event_data["target_transplant_event_id"] == str(target.id)

    after_count = db_session.execute(
        select(AuditEvent.id).where(AuditEvent.action == "crop_batch.transplanted")
    ).scalars().all()
    assert len(after_count) == len(before_count)  # REPLACEMENT never emits crop_batch.transplanted


# --- Chain resolver -----------------------------------------------------------------


def test_authoritative_chain_untouched_record(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    aid = s["source_assignment_ids"][0]
    dest = s["destination_carriers"][0]
    target = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(dest.id)], [_simple_allocation(aid, dest.id)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    assert transplant_correction_service.resolve_authoritative_transplant(db_session, event_id=target.id) == target.id


# --- PRE-COMMIT CORRECTION: mandatory minimum-matrix biological proofs -------------


def test_wrong_source_tray_correction(db_session, active_context_with_farm) -> None:
    """Recorded Tray A -> P1, actual was Tray B -> P1: A is restored, the
    replacement uses B, the authoritative chain points to the replacement,
    and both A's and B's checkpoint balances reconcile."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=2)
    wrong_tray, correct_tray = s["source_assignment_ids"][0], s["source_assignment_ids"][1]
    dest = s["destination_carriers"][0]
    target = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(wrong_tray)], [_simple_destination(dest.id)], [_simple_allocation(wrong_tray, dest.id)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    replacement = {
        "note": None,
        "source_lines": [_simple_source(correct_tray)],
        "destination_lines": [_simple_destination(dest.id)],
        "allocations": [_simple_allocation(correct_tray, dest.id)],
    }
    reversal = _correct(db_session, tenant, farm, user, s["batch"], target.id, replacement=replacement)
    described = transplant_correction_service.describe_correction(
        db_session, tenant_id=tenant.id, reversal_event_id=reversal.id
    )
    replacement_event = db_session.get(TransplantEvent, described["replacement_event_id"])

    # A (wrong Tray) is restored, fully back to 200, untouched by B's story.
    restored_a = db_session.execute(
        select(BatchCarrierAssignment).where(
            BatchCarrierAssignment.restored_from_batch_carrier_assignment_id == wrong_tray
        )
    ).scalar_one()
    assert restored_a.released_effective_time is None
    checkpoint_a = db_session.execute(
        select(SeedlingSourceCheckpoint).where(
            SeedlingSourceCheckpoint.source_batch_carrier_assignment_id == restored_a.id
        )
    ).scalar_one()
    assert checkpoint_a.remainder_after == 200

    # B (correct Tray) was never touched by the target -- the replacement
    # fully exhausts it directly, no restoration needed.
    correct_assignment = db_session.get(BatchCarrierAssignment, correct_tray)
    assert correct_assignment.released_by_transplant_event_id == replacement_event.id
    checkpoint_b = db_session.execute(
        select(SeedlingSourceCheckpoint).where(
            SeedlingSourceCheckpoint.transplant_source_line_id.in_(
                select(TransplantSourceLine.id).where(TransplantSourceLine.transplant_event_id == replacement_event.id)
            )
        )
    ).scalar_one()
    assert checkpoint_b.remainder_after == 0

    assert (
        transplant_correction_service.resolve_authoritative_transplant(db_session, event_id=target.id)
        == replacement_event.id
    )


def test_multi_source_multi_destination_reallocation_correction(db_session, active_context_with_farm) -> None:
    """A->P1=100, A->P2=40, B->P2=60 corrected to a different valid split
    (A->P1=60, A->P2=80, B->P1=40, B->P2=20) touching the SAME sources and
    destinations with the SAME per-destination totals -- proves the generic
    primitive supports genuine multi-source/multi-destination reallocation,
    not just single-line correction."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=2)
    a, b = s["source_assignment_ids"][0], s["source_assignment_ids"][1]
    p1, p2 = s["destination_carriers"][0], s["destination_carriers"][1]
    p3, p4 = s["destination_carriers"][2], s["destination_carriers"][3]
    target = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(a), _simple_source(b)],
        [_simple_destination(p1.id, count=100), _simple_destination(p2.id, count=100)],
        [
            _simple_allocation(a, p1.id, 100), _simple_allocation(a, p2.id, 40),
            _simple_allocation(b, p2.id, 60),
        ],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    # Neither source was exhausted (A remainder 60, B remainder 140) --
    # no restoration required, checkpoints simply restore in place.
    assert db_session.get(BatchCarrierAssignment, a).released_effective_time is None
    assert db_session.get(BatchCarrierAssignment, b).released_effective_time is None

    replacement = {
        "note": None,
        "source_lines": [_simple_source(a), _simple_source(b)],
        "destination_lines": [_simple_destination(p3.id, count=100), _simple_destination(p4.id, count=100)],
        "allocations": [
            _simple_allocation(a, p3.id, 60), _simple_allocation(a, p4.id, 80),
            _simple_allocation(b, p3.id, 40), _simple_allocation(b, p4.id, 20),
        ],
    }
    reversal = _correct(db_session, tenant, farm, user, s["batch"], target.id, replacement=replacement)
    described = transplant_correction_service.describe_correction(
        db_session, tenant_id=tenant.id, reversal_event_id=reversal.id
    )
    replacement_event = db_session.get(TransplantEvent, described["replacement_event_id"])

    replacement_lines = db_session.execute(
        select(TransplantSourceLine).where(TransplantSourceLine.transplant_event_id == replacement_event.id)
    ).scalars().all()
    checkpoints = db_session.execute(
        select(SeedlingSourceCheckpoint).where(
            SeedlingSourceCheckpoint.transplant_source_line_id.in_([ln.id for ln in replacement_lines])
        )
    ).scalars().all()
    total_source = sum(ln.source_plant_count for ln in replacement_lines)
    total_discarded = sum(ln.discarded_plant_count for ln in replacement_lines)
    total_remainder = sum(cp.remainder_after for cp in checkpoints)
    assert total_source == total_discarded + total_remainder + 200  # 60+140 (100+100 destinations)


def test_disposition_loss_correction(db_session, active_context_with_farm) -> None:
    """Original Transplant records 20 transplant-damage; the replacement
    corrects the disposition to 5 rejected + 3 sampled -- proves the
    reversal restores the FULL pre-event source quantity (not merely the
    original successful-transfer count) and the replacement re-declares
    the corrected loss split, ending at a correct final checkpoint balance."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    aid = s["source_assignment_ids"][0]
    dest, dest2 = s["destination_carriers"][0], s["destination_carriers"][1]
    target = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid, transplant_damage_count=20)],
        [_simple_destination(dest.id, count=180)],
        [_simple_allocation(aid, dest.id, 180)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    # 180 + 20 == 200 -- fully exhausted, original assignment released.
    assert db_session.get(BatchCarrierAssignment, aid).released_effective_time is not None

    replacement = {
        "note": None,
        "source_lines": [_simple_source(aid, qc_rejection_count=5, sample_count=3)],
        "destination_lines": [_simple_destination(dest2.id, count=192)],
        "allocations": [_simple_allocation(aid, dest2.id, 192)],
    }
    reversal = _correct(db_session, tenant, farm, user, s["batch"], target.id, replacement=replacement)
    described = transplant_correction_service.describe_correction(
        db_session, tenant_id=tenant.id, reversal_event_id=reversal.id
    )
    replacement_event = db_session.get(TransplantEvent, described["replacement_event_id"])

    # Reversal checkpoint restores the FULL pre-event 200 -- not 180
    # (the original successful count) and not merely undoing the damage.
    # Both the reversal's and the replacement's own source lines reference
    # the SAME restored assignment (same physical Tray) -- scope the query
    # to the reversal's own source line specifically, not just the
    # assignment id, which now matches two checkpoint rows.
    reversal_line = db_session.execute(
        select(TransplantSourceLine).where(TransplantSourceLine.transplant_event_id == reversal.id)
    ).scalar_one()
    restored = db_session.get(BatchCarrierAssignment, reversal_line.source_batch_carrier_assignment_id)
    assert restored.restored_from_batch_carrier_assignment_id == aid
    reversal_checkpoint = db_session.execute(
        select(SeedlingSourceCheckpoint).where(
            SeedlingSourceCheckpoint.transplant_source_line_id == reversal_line.id
        )
    ).scalar_one()
    assert reversal_checkpoint.remainder_after == 200

    # Replacement re-declares the corrected disposition: 192 + 5 + 3 = 200.
    replacement_line = db_session.execute(
        select(TransplantSourceLine).where(TransplantSourceLine.transplant_event_id == replacement_event.id)
    ).scalar_one()
    assert replacement_line.discarded_plant_count == 8
    assert replacement_line.qc_rejection_count == 5
    assert replacement_line.sample_count == 3
    final_checkpoint = db_session.execute(
        select(SeedlingSourceCheckpoint).where(
            SeedlingSourceCheckpoint.transplant_source_line_id == replacement_line.id
        )
    ).scalar_one()
    assert final_checkpoint.remainder_after == 0


def test_multi_generation_restoration_a_to_b_to_c(db_session, active_context_with_farm) -> None:
    """A -> exhausted by X -> corrected -> restored B; B -> exhausted by Y
    -> corrected -> restored C. Proves C is the sole active assignment for
    the Carrier, resolves to the SAME original SeedlingEntry, the
    structural checkpoint chain stays continuous end to end, C appears in
    the biological Tray listing, and a later biological operation can use it."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    a = s["source_assignment_ids"][0]
    dest1, dest2, dest3 = s["destination_carriers"][0], s["destination_carriers"][1], s["destination_carriers"][2]
    t1 = s["entry_time"] + timedelta(hours=2)

    x = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(a)], [_simple_destination(dest1.id)], [_simple_allocation(a, dest1.id)],
        effective_time=t1,
    )
    _correct(db_session, tenant, farm, user, s["batch"], x.id, reason="wrong quantity, restore and redo")
    b = db_session.execute(
        select(BatchCarrierAssignment).where(BatchCarrierAssignment.restored_from_batch_carrier_assignment_id == a)
    ).scalar_one()

    t2 = t1 + timedelta(hours=1)
    y = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(b.id)], [_simple_destination(dest2.id)], [_simple_allocation(b.id, dest2.id)],
        effective_time=t2,
    )
    _correct(db_session, tenant, farm, user, s["batch"], y.id, reason="wrong quantity again, restore and redo")
    c = db_session.execute(
        select(BatchCarrierAssignment).where(BatchCarrierAssignment.restored_from_batch_carrier_assignment_id == b.id)
    ).scalar_one()

    # C is the sole active assignment for this physical Carrier.
    original_carrier_id = db_session.get(BatchCarrierAssignment, a).carrier_id
    assert c.carrier_id == original_carrier_id
    active_for_carrier = db_session.execute(
        select(func.count()).select_from(BatchCarrierAssignment).where(
            BatchCarrierAssignment.carrier_id == c.carrier_id, BatchCarrierAssignment.released_effective_time.is_(None)
        )
    ).scalar_one()
    assert active_for_carrier == 1

    # C resolves to the SAME original SeedlingEntry as A.
    entry_from_c = seedling_source_lineage.resolve_seedling_entry_for_assignment(db_session, assignment_id=c.id)
    entry_from_a = seedling_source_lineage.resolve_seedling_entry_for_assignment(db_session, assignment_id=a)
    assert entry_from_c.id == entry_from_a.id

    # Structural checkpoint chain is one continuous, unbranched sequence
    # (X's checkpoint, its REVERSAL's, Y's, its REVERSAL's -- exactly 4).
    all_checkpoints = db_session.execute(
        select(SeedlingSourceCheckpoint).where(SeedlingSourceCheckpoint.seedling_entry_id == entry_from_a.id)
    ).scalars().all()
    assert len(all_checkpoints) == 4
    tips = [
        cp for cp in all_checkpoints
        if not any(other.previous_checkpoint_id == cp.id for other in all_checkpoints)
    ]
    assert len(tips) == 1

    # C is exposed by the biological Tray listing as active.
    trays = seedling_disposition_service.list_seedling_biological_trays(db_session, tenant_id=tenant.id, farm_id=farm.id)
    row = next(t for t in trays if t.batch_carrier_assignment_id == c.id)
    assert row.assignment_active is True
    assert row.current_source_available_count == 200

    # A subsequent, ordinary biological operation (Transplant) can use C.
    t3 = t2 + timedelta(hours=1)
    z = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(c.id)], [_simple_destination(dest3.id, count=190)], [_simple_allocation(c.id, dest3.id, 190)],
        effective_time=t3,
    )
    assert z.event_kind == "RECORD"


def _reach_same_stage_minimal_batch(db_session, tenant, user, farm, s, *, suffix):
    """A second, minimal CropBatch under the SAME workflow/version, sown
    with exactly one seed_tray Carrier (merge_batches requires every source
    batch to have at least one active assignment) and advanced into the
    SAME TRANSPLANTING-category stage as `s["batch"]`."""
    from app.services import carrier_service, sowing_service

    from tests.conftest import ensure_seed_tray_specification

    batch2 = crop_batch_service.create_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"BATCH2-{suffix}", workflow_id=s["workflow"].id, effective_time=_now(),
    )
    seed_tray_spec = ensure_seed_tray_specification(db_session, tenant_id=tenant.id, actor_user_id=user.id)
    carrier = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        specification_id=seed_tray_spec.id, code=f"ST2-{suffix}", issued_date=None,
    )
    sowing_service.sow_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch2.id,
        client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
        lines=[
            {
                "carrier_id": carrier.id, "seed_lot_id": s["seed_lot"].id, "sown_site_count": 50, "seed_count": 50,
                "line_note": None,
            }
        ],
    )
    crop_batch_service.transition_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch2.id,
        client_command_id=uuid.uuid4(), configured_transition_id=s["transitions"]["t1"].id,
        effective_time=_now(), reason=None,
    )
    return batch2


def test_destination_consumed_by_batch_derivation_blocks_correction(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    aid = s["source_assignment_ids"][0]
    dest = s["destination_carriers"][0]
    target = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(dest.id)], [_simple_allocation(aid, dest.id)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    # Source fully exhausted -> the ONLY active assignment left on
    # s["batch"] is the destination Plate itself, satisfying merge_batches'
    # complete-coverage-of-active-assignments requirement trivially.
    suffix = uuid.uuid4().hex[:8]
    batch2 = _reach_same_stage_minimal_batch(db_session, tenant, user, farm, s, suffix=suffix)

    batch_derivation_service.merge_batches(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        source_batch_ids=[s["batch"].id, batch2.id], client_command_id=uuid.uuid4(),
        effective_time=_now(), note=None, output_batch_code=f"MERGED-{suffix}",
    )
    dest_assignment = db_session.execute(
        select(BatchCarrierAssignment).where(BatchCarrierAssignment.opening_transplant_event_id == target.id)
    ).scalar_one()
    assert dest_assignment.released_by_batch_derivation_event_id is not None

    # A finding worth recording precisely: `merge_batches`/`split_batch`
    # both always supersede/close EVERY source batch they touch (proven by
    # `test_batch_derivation.py`'s own `test_split_creates_two_output_
    # batches_and_supersedes_source`), so `s["batch"]` itself is now
    # 'superseded' -- `correct_transplant`'s own `CropBatchClosedError`
    # check (batch must be active) necessarily fires BEFORE the dedicated
    # `TransplantCorrectionDestinationConsumedError` destination check is
    # ever reached. Correction is still correctly rejected either way --
    # this proves the real, reachable behavior of the one production
    # mechanism that can release a transplant-opened destination
    # assignment via Batch Derivation, rather than asserting an error type
    # that this specific path cannot actually produce today. The dedicated
    # destination-released check remains a legitimate structural backstop
    # for any other/future releaser of a transplant-opened assignment.
    db_session.refresh(s["batch"])
    assert s["batch"].state == "superseded"
    with pytest.raises(CropBatchClosedError):
        _correct(db_session, tenant, farm, user, s["batch"], target.id)


def test_physical_movement_does_not_block_correction(db_session, active_context_with_farm) -> None:
    """Movement history != biological correction eligibility -- an ordinary
    physical Movement of the destination Carrier, recorded AFTER the
    Transplant, must never block a later biological correction. Movement
    itself is never touched by the correction."""
    from app.services import carrier_specification_service

    tenant, user, _headers, farm = active_context_with_farm
    spec = carrier_specification_service.register_carrier_specification(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, carrier_type_code="nursery_cultivation_plate",
        code=f"NCP-{uuid.uuid4().hex[:8]}", name="200 Hole Nursery Plate", length_mm=500, width_mm=300, height_mm=60,
        biological_position_count=200,
    )
    s = _build_scenario(
        db_session, tenant, user, farm, tray_count=1,
        transplanting_required_type="nursery_cultivation_plate", destination_specification_id=spec.id,
        intersalads_table_count=1,
    )
    aid = s["source_assignment_ids"][0]
    dest = s["destination_carriers"][0]
    target = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aid)], [_simple_destination(dest.id)], [_simple_allocation(aid, dest.id)],
        effective_time=s["entry_time"] + timedelta(hours=2),
    )
    movement = movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        effective_time=s["entry_time"] + timedelta(hours=3), occupant_kind="carrier", occupant_id=dest.id,
        destination_kind="location", destination_id=s["intersalads_table_ids"][0], reason=None,
    )

    reversal = _correct(db_session, tenant, farm, user, s["batch"], target.id)
    assert reversal.event_kind == "REVERSAL"

    # Movement itself is completely untouched.
    db_session.refresh(movement)
    assert movement.id is not None


def test_direct_sql_reversal_cannot_release_unrelated_assignment(db_session, active_context_with_farm) -> None:
    """DB-integrity proof (section 14 Case B): a REVERSAL may only close the
    destination assignment opened by the exact event it reverses -- direct
    SQL attempting to point a REVERSAL's release at an unrelated destination
    assignment must be rejected at the DB layer, not merely by service code."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, tray_count=2)
    a, b = s["source_assignment_ids"][0], s["source_assignment_ids"][1]
    dest_a, dest_unrelated = s["destination_carriers"][0], s["destination_carriers"][1]
    effective_time = s["entry_time"] + timedelta(hours=2)
    target = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(a)], [_simple_destination(dest_a.id)], [_simple_allocation(a, dest_a.id)],
        effective_time=effective_time,
    )
    unrelated = _transplant(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(b)], [_simple_destination(dest_unrelated.id)], [_simple_allocation(b, dest_unrelated.id)],
        effective_time=effective_time,
    )
    reversal = _correct(db_session, tenant, farm, user, s["batch"], target.id)

    unrelated_dest_assignment = db_session.execute(
        select(BatchCarrierAssignment).where(BatchCarrierAssignment.opening_transplant_event_id == unrelated.id)
    ).scalar_one()

    with pytest.raises(DBAPIError, match="may only release the destination assignment opened by the exact event"):
        db_session.execute(
            text(
                "UPDATE batch_carrier_assignments SET released_effective_time = :t, "
                "released_by_transplant_event_id = :rid WHERE id = :aid"
            ),
            {"t": reversal.effective_time, "rid": reversal.id, "aid": unrelated_dest_assignment.id},
        )
        db_session.flush()
    db_session.rollback()
