"""HARVEST-OPS-001 BUILD SLICE 1: the immutable Harvest source-line
correction chain -- repeated correction, void, correct-a-void, zero-
release -> restore -> re-zero, ledger adjustment math, concurrency, and the
correction-reconciliation DB backstop. Mirrors `test_production_
disposition_correction.py`'s coverage shape for the sibling authority, and
proves every worked example the architecture-revalidation design laid
out, with exact numbers."""

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.harvest_source_line import HarvestSourceLine
from app.models.harvest_source_line_correction import HarvestSourceLineCorrection
from app.models.harvested_produce_lot import HarvestedProduceLot
from app.models.produce_lot_ledger_entry import ProduceLotLedgerEntry
from app.services import harvest_service, leafy_population_service
from app.services.errors import (
    HarvestCorrectionAlreadySupersededError,
    HarvestCorrectionCommandReusedWithDifferentPayloadError,
    HarvestCorrectionValidationError,
    HarvestLedgerBalanceError,
)
from tests._packing_scenario import build_packing_scaffold
from tests.test_leafy_harvest import _harvest, _line
from tests.test_production_disposition import _plate_scenario

pytestmark = pytest.mark.integration


def _grade_partial(db_session, tenant, farm, user, *, lot, weight, count, output_weight, loss_weight, suffix):
    """POSTHARVEST-OPS-001E: HarvestedProduceLot balance is debited by
    Grading (grading_consumption), never by Packing (which now consumes
    exclusively from GradedProduceLot balance) -- this replaces what used
    to be a direct `packing_service.record_packing` call against the HPL
    for tests whose actual purpose is proving harvest-correction safety
    against an already-reduced HPL balance, regardless of which downstream
    operation reduced it."""
    from app.services import grading_service

    scaffold = build_packing_scaffold(db_session, tenant, user, farm, crop_id=lot.crop_id, suffix=suffix)
    grading_service.record_grading(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        source_harvested_produce_lot_id=lot.id, processing_hall_location_id=scaffold["packing_hall_location_id"],
        effective_time=lot.effective_time + timedelta(hours=1), note=None,
        input_presented_weight_kg=weight, input_presented_whole_unit_count=count,
        rejected_weight_kg=Decimal("0"), rejected_whole_unit_count=(0 if count is not None else None),
        loss_weight_kg=loss_weight, loss_whole_unit_count=(0 if count is not None else None),
        sample_weight_kg=Decimal("0"), sample_whole_unit_count=(0 if count is not None else None),
        remainder_weight_kg=Decimal("0"), remainder_whole_unit_count=(0 if count is not None else None),
        outputs=[
            {
                "grade_definition_version_id": scaffold["grade_definition_version_id"], "code": f"GPL-{suffix}",
                "output_weight_kg": output_weight, "output_whole_unit_count": count,
            }
        ],
    )


def _correct(db_session, tenant, farm, user, harvest_source_line_id, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        harvest_source_line_id=harvest_source_line_id, supersedes_correction_id=None, is_void=False,
        corrected_harvested_weight_kg=None, corrected_whole_unit_count=None, reason_code="miscounted",
        note="test correction",
    )
    defaults.update(overrides)
    return harvest_service.correct_leafy_harvest(db_session, **defaults)


def _only_source_line(db_session, event) -> HarvestSourceLine:
    return db_session.execute(
        select(HarvestSourceLine).where(HarvestSourceLine.harvest_event_id == event.id)
    ).scalar_one()


def _lot_for(db_session, event) -> HarvestedProduceLot:
    return db_session.execute(
        select(HarvestedProduceLot).where(HarvestedProduceLot.harvest_event_id == event.id)
    ).scalar_one()


def _balance(db_session, lot_id):
    weight = db_session.execute(
        select(ProduceLotLedgerEntry.weight_delta_kg).where(ProduceLotLedgerEntry.produce_lot_id == lot_id)
    ).scalars().all()
    count = db_session.execute(
        select(ProduceLotLedgerEntry.whole_unit_count_delta).where(ProduceLotLedgerEntry.produce_lot_id == lot_id)
    ).scalars().all()
    return sum(weight, Decimal("0")), sum((c for c in count if c is not None), 0)


# =====================================================================
# First correction / repeated correction ("correction of a correction")
# =====================================================================


def test_first_correction_count_only_stores_complete_tuple(db_session, active_context_with_farm) -> None:
    """Operator changes only the count -- the stored correction row still
    carries BOTH fields, weight copied forward from the original."""
    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    event = _harvest(db_session, tenant, farm, user, batch.id, [_line(root_id, 5, "2.500")], effective_time=t0 + timedelta(hours=1))
    line = _only_source_line(db_session, event)

    correction = _correct(
        db_session, tenant, farm, user, line.id,
        corrected_harvested_weight_kg=Decimal("2.500"), corrected_whole_unit_count=4,
    )
    db_session.refresh(correction)
    assert correction.corrected_harvested_weight_kg == Decimal("2.500")
    assert correction.corrected_whole_unit_count == 4


def test_first_correction_weight_only_stores_complete_tuple(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    event = _harvest(db_session, tenant, farm, user, batch.id, [_line(root_id, 5, "2.500")], effective_time=t0 + timedelta(hours=1))
    line = _only_source_line(db_session, event)

    correction = _correct(
        db_session, tenant, farm, user, line.id,
        corrected_harvested_weight_kg=Decimal("2.000"), corrected_whole_unit_count=5,
    )
    db_session.refresh(correction)
    assert correction.corrected_harvested_weight_kg == Decimal("2.000")
    assert correction.corrected_whole_unit_count == 5


def test_repeated_correction_uses_predecessor_not_original(db_session, active_context_with_farm) -> None:
    """Worked proof: 5/2.5 -> correction1 4/2.0 (delta -1/-0.5) ->
    correction2 6/3.0, delta MUST be +2/+1.0 relative to correction1, never
    +1/+0.5 relative to the original."""
    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    event = _harvest(db_session, tenant, farm, user, batch.id, [_line(root_id, 5, "2.500")], effective_time=t0 + timedelta(hours=1))
    line = _only_source_line(db_session, event)
    lot = _lot_for(db_session, event)

    c1 = _correct(
        db_session, tenant, farm, user, line.id,
        corrected_harvested_weight_kg=Decimal("2.000"), corrected_whole_unit_count=4,
    )
    weight_after_c1, count_after_c1 = _balance(db_session, lot.id)
    assert weight_after_c1 == Decimal("2.000")
    assert count_after_c1 == 4

    c2 = _correct(
        db_session, tenant, farm, user, line.id, supersedes_correction_id=c1.id,
        corrected_harvested_weight_kg=Decimal("3.000"), corrected_whole_unit_count=6,
    )
    weight_after_c2, count_after_c2 = _balance(db_session, lot.id)
    assert weight_after_c2 == Decimal("3.000")
    assert count_after_c2 == 6

    adjustment2 = db_session.execute(
        select(ProduceLotLedgerEntry).where(
            ProduceLotLedgerEntry.harvest_source_line_correction_id == c2.id, ProduceLotLedgerEntry.entry_kind == "harvest_adjustment"
        )
    ).scalar_one()
    assert adjustment2.weight_delta_kg == Decimal("1.000")
    assert adjustment2.whole_unit_count_delta == 2

    current = harvest_service.get_current_effective_source_line(db_session, harvest_source_line_id=line.id)
    assert current["harvested_weight_kg"] == Decimal("3.000")
    assert current["whole_unit_count"] == 6
    assert current["original_harvested_weight_kg"] == Decimal("2.500")
    assert current["original_whole_unit_count"] == 5


def test_correction_of_correction_biological_population(db_session, active_context_with_farm) -> None:
    """Worked proof: opening 10, original -5 -> living 5. Correction 1
    reverses +5, replaces -4 -> living 6. Correction 2 reverses +4,
    replaces -6 -> living 4."""
    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=10)
    event = _harvest(db_session, tenant, farm, user, batch.id, [_line(root_id, 5, "2.500")], effective_time=t0 + timedelta(hours=1))
    line = _only_source_line(db_session, event)
    assert leafy_population_service.get_current_living_population(db_session, root_batch_carrier_assignment_id=root_id) == 5

    c1 = _correct(
        db_session, tenant, farm, user, line.id, corrected_harvested_weight_kg=Decimal("2.000"), corrected_whole_unit_count=4,
    )
    assert leafy_population_service.get_current_living_population(db_session, root_batch_carrier_assignment_id=root_id) == 6

    _correct(
        db_session, tenant, farm, user, line.id, supersedes_correction_id=c1.id,
        corrected_harvested_weight_kg=Decimal("3.000"), corrected_whole_unit_count=6,
    )
    assert leafy_population_service.get_current_living_population(db_session, root_batch_carrier_assignment_id=root_id) == 4


# =====================================================================
# Pure void / correct-a-void
# =====================================================================


def test_pure_void_restores_population_and_zeros_ledger(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    event = _harvest(db_session, tenant, farm, user, batch.id, [_line(root_id, 5, "2.500")], effective_time=t0 + timedelta(hours=1))
    line = _only_source_line(db_session, event)
    lot = _lot_for(db_session, event)
    assert leafy_population_service.get_current_living_population(db_session, root_batch_carrier_assignment_id=root_id) == 175

    correction = _correct(db_session, tenant, farm, user, line.id, is_void=True)
    db_session.refresh(correction)
    assert correction.is_void is True
    assert correction.corrected_harvested_weight_kg is None
    assert correction.corrected_whole_unit_count is None

    assert leafy_population_service.get_current_living_population(db_session, root_batch_carrier_assignment_id=root_id) == 180
    weight, count = _balance(db_session, lot.id)
    assert weight == Decimal("0")
    assert count == 0

    current = harvest_service.get_current_effective_source_line(db_session, harvest_source_line_id=line.id)
    assert current["is_void"] is True
    assert current["harvested_weight_kg"] is None
    assert current["whole_unit_count"] is None


def test_correct_a_void_creates_direct_replacement_no_fake_reversal(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    event = _harvest(db_session, tenant, farm, user, batch.id, [_line(root_id, 5, "2.500")], effective_time=t0 + timedelta(hours=1))
    line = _only_source_line(db_session, event)
    lot = _lot_for(db_session, event)

    void_correction = _correct(db_session, tenant, farm, user, line.id, is_void=True)
    assert leafy_population_service.get_current_living_population(db_session, root_batch_carrier_assignment_id=root_id) == 180

    unvoid = _correct(
        db_session, tenant, farm, user, line.id, supersedes_correction_id=void_correction.id,
        corrected_harvested_weight_kg=Decimal("1.500"), corrected_whole_unit_count=3,
    )
    assert leafy_population_service.get_current_living_population(db_session, root_batch_carrier_assignment_id=root_id) == 177
    weight, count = _balance(db_session, lot.id)
    assert weight == Decimal("1.500")
    assert count == 3

    adjustment = db_session.execute(
        select(ProduceLotLedgerEntry).where(ProduceLotLedgerEntry.harvest_source_line_correction_id == unvoid.id)
    ).scalar_one()
    assert adjustment.weight_delta_kg == Decimal("1.500")
    assert adjustment.whole_unit_count_delta == 3


# =====================================================================
# Zero release -> restore -> re-zero (ticket's own required example)
# =====================================================================


def test_zero_release_restore_re_zero(db_session, active_context_with_farm) -> None:
    """Opening 5. Original harvest -5 -> A released. Correction 1 (5 -> 4):
    +5 against A restores population -> new BCA B, replacement -4 against
    B -> living 1, B active. Correction 2 (4 -> 5): +4 against B (B still
    active, no restoration), replacement -5 against B -> B hits zero -> B
    released. A stays historically released forever, no C generation."""
    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=5)
    event = _harvest(db_session, tenant, farm, user, batch.id, [_line(root_id, 5, "2.500")], effective_time=t0 + timedelta(hours=1))
    line = _only_source_line(db_session, event)

    a = db_session.get(BatchCarrierAssignment, root_id)
    assert a.released_effective_time is not None
    assert a.released_by_harvest_population_event_id is not None

    c1 = _correct(
        db_session, tenant, farm, user, line.id, corrected_harvested_weight_kg=Decimal("2.000"), corrected_whole_unit_count=4,
    )
    b = db_session.execute(
        select(BatchCarrierAssignment).where(
            BatchCarrierAssignment.opening_harvest_population_reversal_event_id.is_not(None),
            BatchCarrierAssignment.restored_from_batch_carrier_assignment_id == root_id,
        )
    ).scalar_one()
    assert b.id != root_id
    assert b.released_effective_time is None
    assert b.restored_from_batch_carrier_assignment_id == root_id
    assert b.population_root_batch_carrier_assignment_id == root_id
    assert b.carrier_id == a.carrier_id
    assert leafy_population_service.get_current_living_population(db_session, root_batch_carrier_assignment_id=root_id) == 1

    a_after_c1 = db_session.get(BatchCarrierAssignment, root_id)
    assert a_after_c1.released_effective_time == a.released_effective_time  # untouched, never reactivated

    _correct(
        db_session, tenant, farm, user, line.id, supersedes_correction_id=c1.id,
        corrected_harvested_weight_kg=Decimal("2.500"), corrected_whole_unit_count=5,
    )
    b_final = db_session.get(BatchCarrierAssignment, b.id)
    assert b_final.released_effective_time is not None
    assert b_final.released_by_harvest_population_event_id is not None
    assert leafy_population_service.get_current_living_population(db_session, root_batch_carrier_assignment_id=root_id) == 0

    a_final = db_session.get(BatchCarrierAssignment, root_id)
    assert a_final.released_effective_time == a.released_effective_time

    # No unnecessary C generation -- exactly two restored/original
    # generations exist for this root (A, B).
    generations = db_session.execute(
        select(BatchCarrierAssignment.id).where(
            BatchCarrierAssignment.population_root_batch_carrier_assignment_id == root_id
        )
    ).scalars().all()
    assert set(generations) == {root_id, b.id}


# =====================================================================
# Ledger: negative-balance guard / atomicity
# =====================================================================


def test_safe_correction_after_partial_packing_consumption(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    event = _harvest(db_session, tenant, farm, user, batch.id, [_line(root_id, 5, "2.500")], effective_time=t0 + timedelta(hours=1))
    line = _only_source_line(db_session, event)
    lot = _lot_for(db_session, event)

    _grade_partial(
        db_session, tenant, farm, user, lot=lot, weight=Decimal("1.500"), count=3,
        output_weight=Decimal("1.400"), loss_weight=Decimal("0.100"), suffix="safe-correction",
    )
    weight_before, count_before = _balance(db_session, lot.id)
    assert weight_before == Decimal("1.000")
    assert count_before == 2

    # Correct 5/2.5 -> 4/2.0 (delta -1/-0.5): 1.0-0.5=0.5 >= 0, 2-1=1 >= 0 -- safe.
    _correct(
        db_session, tenant, farm, user, line.id, corrected_harvested_weight_kg=Decimal("2.000"), corrected_whole_unit_count=4,
    )
    weight_after, count_after = _balance(db_session, lot.id)
    assert weight_after == Decimal("0.500")
    assert count_after == 1


def test_unsafe_correction_rejected_and_biology_left_untouched(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    event = _harvest(db_session, tenant, farm, user, batch.id, [_line(root_id, 5, "2.500")], effective_time=t0 + timedelta(hours=1))
    line = _only_source_line(db_session, event)
    lot = _lot_for(db_session, event)

    # Fully consume the lot (weight AND count both to zero -- a matched
    # residual, satisfying Grading's own consistency rule), so ANY
    # subsequent reducing correction is guaranteed unsafe.
    _grade_partial(
        db_session, tenant, farm, user, lot=lot, weight=Decimal("2.500"), count=5,
        output_weight=Decimal("2.400"), loss_weight=Decimal("0.100"), suffix="unsafe-correction",
    )
    living_before = leafy_population_service.get_current_living_population(db_session, root_batch_carrier_assignment_id=root_id)

    with pytest.raises(HarvestLedgerBalanceError):
        _correct(
            db_session, tenant, farm, user, line.id, corrected_harvested_weight_kg=Decimal("2.000"), corrected_whole_unit_count=4,
        )

    # Atomic: no correction row, no biology change either.
    correction_count = db_session.execute(
        select(HarvestSourceLineCorrection.id).where(HarvestSourceLineCorrection.harvest_source_line_id == line.id)
    ).all()
    assert len(correction_count) == 0
    assert leafy_population_service.get_current_living_population(
        db_session, root_batch_carrier_assignment_id=root_id
    ) == living_before


def test_original_lot_totals_never_change(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    event = _harvest(db_session, tenant, farm, user, batch.id, [_line(root_id, 5, "2.500")], effective_time=t0 + timedelta(hours=1))
    line = _only_source_line(db_session, event)
    lot = _lot_for(db_session, event)
    original_weight, original_count = lot.total_harvested_weight_kg, lot.total_whole_unit_count

    _correct(
        db_session, tenant, farm, user, line.id, corrected_harvested_weight_kg=Decimal("2.000"), corrected_whole_unit_count=4,
    )
    db_session.refresh(lot)
    assert lot.total_harvested_weight_kg == original_weight
    assert lot.total_whole_unit_count == original_count

    line_row = db_session.get(HarvestSourceLine, line.id)
    assert line_row.harvested_weight_kg == Decimal("2.500")
    assert line_row.whole_unit_count == 5


# =====================================================================
# Concurrency / chain-branch prevention
# =====================================================================


def test_stale_predecessor_gets_conflict(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    event = _harvest(db_session, tenant, farm, user, batch.id, [_line(root_id, 5, "2.500")], effective_time=t0 + timedelta(hours=1))
    line = _only_source_line(db_session, event)

    _correct(
        db_session, tenant, farm, user, line.id, corrected_harvested_weight_kg=Decimal("2.000"), corrected_whole_unit_count=4,
    )
    # Retrying against supersedes_correction_id=None (stale -- the chain
    # already has a root correction) must never silently retarget.
    with pytest.raises(HarvestCorrectionAlreadySupersededError):
        _correct(
            db_session, tenant, farm, user, line.id, corrected_harvested_weight_kg=Decimal("3.000"), corrected_whole_unit_count=6,
        )


def test_idempotent_retry_returns_same_correction(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    event = _harvest(db_session, tenant, farm, user, batch.id, [_line(root_id, 5, "2.500")], effective_time=t0 + timedelta(hours=1))
    line = _only_source_line(db_session, event)
    cid = uuid.uuid4()

    first = _correct(
        db_session, tenant, farm, user, line.id, client_command_id=cid,
        corrected_harvested_weight_kg=Decimal("2.000"), corrected_whole_unit_count=4,
    )
    second = _correct(
        db_session, tenant, farm, user, line.id, client_command_id=cid,
        corrected_harvested_weight_kg=Decimal("2.000"), corrected_whole_unit_count=4,
    )
    assert second.id == first.id
    corrections = db_session.execute(
        select(HarvestSourceLineCorrection.id).where(HarvestSourceLineCorrection.harvest_source_line_id == line.id)
    ).all()
    assert len(corrections) == 1


def test_same_command_id_different_payload_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    event = _harvest(db_session, tenant, farm, user, batch.id, [_line(root_id, 5, "2.500")], effective_time=t0 + timedelta(hours=1))
    line = _only_source_line(db_session, event)
    cid = uuid.uuid4()

    _correct(
        db_session, tenant, farm, user, line.id, client_command_id=cid,
        corrected_harvested_weight_kg=Decimal("2.000"), corrected_whole_unit_count=4,
    )
    with pytest.raises(HarvestCorrectionCommandReusedWithDifferentPayloadError):
        _correct(
            db_session, tenant, farm, user, line.id, client_command_id=cid,
            corrected_harvested_weight_kg=Decimal("1.000"), corrected_whole_unit_count=2,
        )


def test_reason_and_note_required(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    event = _harvest(db_session, tenant, farm, user, batch.id, [_line(root_id, 5, "2.500")], effective_time=t0 + timedelta(hours=1))
    line = _only_source_line(db_session, event)

    with pytest.raises(HarvestCorrectionValidationError):
        _correct(
            db_session, tenant, farm, user, line.id, corrected_harvested_weight_kg=Decimal("2.000"),
            corrected_whole_unit_count=4, note="",
        )
    with pytest.raises(HarvestCorrectionValidationError):
        _correct(
            db_session, tenant, farm, user, line.id, corrected_harvested_weight_kg=Decimal("2.000"),
            corrected_whole_unit_count=4, reason_code="",
        )


# =====================================================================
# Correction-reconciliation direct-SQL bypass proof
# =====================================================================


def test_direct_sql_reconciliation_mismatch_rejected(test_engine) -> None:
    """Mirrors CMP-013's own `test_late_direct_sql_source_line_reruns_
    deferred_reconciliation` pattern exactly: the deferred reconciliation
    constraint trigger only fires at a REAL commit, never a `db_session`
    fixture's own savepoint-scoped one -- build and commit a real scenario
    on a dedicated connection, then attempt the mismatched late insert on
    that same connection and prove COMMIT itself fails."""
    from sqlalchemy.orm import Session

    from app.services import farm_service, membership_service, tenant_service, user_service
    from tests.test_leafy_production_transfer import (
        _leafy_setup, _nursery_plate_source_scenario, _production_plates, _record, _simple_allocation,
        _simple_destination, _simple_source,
    )

    from tests._traceability_scenario import cleanup_traceability_scenario

    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]
    tenant_id = None
    try:
        tenant = tenant_service.create_tenant(session, code=f"hc-recon-{suffix}", name="Harvest Reconciliation Tenant")
        tenant_id = tenant.id
        user = user_service.create_user(
            session, oidc_issuer="hc-recon", oidc_subject=suffix, email=f"hc-recon-{suffix}@example.com",
            display_name="Recon User",
        )
        membership_service.add_membership(
            session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
        )
        farm = farm_service.create_farm(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Recon Farm",
            country_code="AE", city_region=None, timezone="Asia/Dubai",
        )
        s, aids = _nursery_plate_source_scenario(session, tenant, user, farm, suffix=suffix, opening_count=180)
        table_ids = _leafy_setup(session, tenant, user, farm, suffix=suffix)
        plates, _spec = _production_plates(session, tenant, user, farm, suffix=suffix, count=1)
        result = _record(
            session, tenant, farm, user, s["batch"],
            [_simple_source(aids[0])], [_simple_destination(plates[0].id, table_ids[0], count=180)],
            [_simple_allocation(aids[0], plates[0].id, 180)],
            effective_time=s["transfer_ready_time"] + timedelta(hours=1),
        )
        root_id = result.destination_lines[0].destination_batch_carrier_assignment_id
        event = _harvest(
            session, tenant, farm, user, s["batch"].id, [_line(root_id, 5, "2.500")],
            effective_time=s["transfer_ready_time"] + timedelta(hours=2),
        )
        line = _only_source_line(session, event)
        session.commit()

        correction_id = uuid.uuid4()
        session.execute(
            text(
                "INSERT INTO harvest_source_line_corrections "
                "(id, tenant_id, farm_id, harvest_source_line_id, supersedes_correction_id, is_void, "
                "corrected_harvested_weight_kg, corrected_whole_unit_count, reason_code, note, actor_user_id, "
                "client_command_id, request_fingerprint) "
                "VALUES (:id, :tid, :fid, :lid, NULL, false, :w, :c, 'x', 'x', :uid, :cid, 'x')"
            ),
            {
                "id": correction_id, "tid": tenant.id, "fid": farm.id, "lid": line.id,
                "w": Decimal("2.000"), "c": 4, "uid": user.id, "cid": uuid.uuid4(),
            },
        )
        # No accompanying harvest_adjustment ledger row was posted -- the
        # deferred reconciliation trigger must catch this mismatch at the
        # REAL commit.
        with pytest.raises(Exception, match="reconciliation failed"):
            session.commit()
    finally:
        session.rollback()
        session.close()
        conn.close()
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)
