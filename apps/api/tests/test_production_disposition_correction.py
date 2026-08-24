"""LEAFY-OPS-001 BUILD section 15-18: Production Biological Disposition
correction/restoration -- CASE A (target did not exhaust its BCA, no
restoration) vs CASE B (target DID exhaust its BCA, restoration into a NEW
generation), the full A -> B -> C population-lineage proof, and Carrier
reuse protection. Mirrors `test_seedling_disposition_correction.py`'s
coverage shape for the sibling authority."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.carrier import Carrier
from app.models.production_disposition_event import ProductionDispositionEvent
from app.services import production_disposition_service
from app.services.errors import (
    ProductionDispositionAlreadyCorrectedError,
    ProductionDispositionCarrierReusedError,
    ProductionDispositionCommandReusedWithDifferentPayloadError,
    ProductionDispositionNotReductionError,
)
from tests.test_production_disposition import _last_event, _plate_scenario, _record_loss

pytestmark = pytest.mark.integration


def _correct(db_session, tenant, farm, user, target_event_id, corrected=None, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        target_event_id=target_event_id, corrected=corrected,
    )
    defaults.update(overrides)
    return production_disposition_service.correct_disposition(db_session, **defaults)


def _events_for_command(db_session, command_id):
    return db_session.execute(
        select(ProductionDispositionEvent).where(ProductionDispositionEvent.command_id == command_id)
    ).scalars().all()


# =====================================================================
# CASE A: target did not exhaust its BCA -- no restoration.
# =====================================================================


def test_case_a_pure_reversal_stays_on_same_active_bca(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    record = _record_loss(db_session, tenant, farm, user, root_id, 5, effective_time=t0 + timedelta(hours=1))
    target = _last_event(db_session, record)

    correct = _correct(db_session, tenant, farm, user, target.id)
    events = _events_for_command(db_session, correct.id)
    assert len(events) == 1
    reversal = events[0]
    assert reversal.event_kind == "REVERSAL"
    assert reversal.batch_carrier_assignment_id == root_id
    assert reversal.effective_time == target.effective_time
    assert reversal.quantity_delta == 5

    bca = db_session.get(BatchCarrierAssignment, root_id)
    assert bca.released_effective_time is None
    assert production_disposition_service.get_current_living_population(
        db_session, root_batch_carrier_assignment_id=root_id
    ) == 180


def test_case_a_reversal_plus_replacement_both_on_same_bca(db_session, active_context_with_farm) -> None:
    """180 -5 => 175; correct to actual loss 3 => 177."""
    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    record = _record_loss(db_session, tenant, farm, user, root_id, 5, effective_time=t0 + timedelta(hours=1))
    target = _last_event(db_session, record)

    correct = _correct(
        db_session, tenant, farm, user, target.id,
        corrected={"plant_loss_count": 3, "reason_code": "dead", "effective_time": t0 + timedelta(hours=2), "note": None},
    )
    events = {e.event_kind: e for e in _events_for_command(db_session, correct.id)}
    assert events["REVERSAL"].batch_carrier_assignment_id == root_id
    assert events["REDUCTION"].batch_carrier_assignment_id == root_id
    assert events["REDUCTION"].corrects_event_id == target.id

    bca = db_session.get(BatchCarrierAssignment, root_id)
    assert bca.released_effective_time is None
    assert production_disposition_service.get_current_living_population(
        db_session, root_batch_carrier_assignment_id=root_id
    ) == 177


# =====================================================================
# CASE B: target DID exhaust its BCA -- restoration into a NEW generation.
# =====================================================================


def test_case_b_pure_reversal_restores_new_generation(db_session, active_context_with_farm) -> None:
    """5 -5 => 0, A released. Correction reversal restores 5 into NEW BCA B."""
    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=5)
    record = _record_loss(db_session, tenant, farm, user, root_id, 5, effective_time=t0 + timedelta(hours=1))
    target = _last_event(db_session, record)
    a = db_session.get(BatchCarrierAssignment, root_id)
    assert a.released_effective_time is not None

    correct = _correct(db_session, tenant, farm, user, target.id)
    events = _events_for_command(db_session, correct.id)
    assert len(events) == 1
    reversal = events[0]
    # REVERSAL always references the target's own (now-released) generation.
    assert reversal.batch_carrier_assignment_id == root_id

    b = db_session.execute(
        select(BatchCarrierAssignment).where(
            BatchCarrierAssignment.opening_production_disposition_reversal_event_id == reversal.id
        )
    ).scalar_one()
    assert b.id != root_id
    assert b.released_effective_time is None
    assert b.restored_from_batch_carrier_assignment_id == root_id
    assert b.population_root_batch_carrier_assignment_id == root_id
    assert b.carrier_id == a.carrier_id

    # Historical BCA A never reactivated.
    a_after = db_session.get(BatchCarrierAssignment, root_id)
    assert a_after.released_effective_time == a.released_effective_time

    assert production_disposition_service.get_current_living_population(
        db_session, root_batch_carrier_assignment_id=root_id
    ) == 5


def test_case_b_reversal_plus_replacement_replacement_on_new_bca(db_session, active_context_with_farm) -> None:
    """CASE B with a replacement: REVERSAL references A; replacement
    references the newly-restored B, never A."""
    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=5)
    record = _record_loss(db_session, tenant, farm, user, root_id, 5, effective_time=t0 + timedelta(hours=1))
    target = _last_event(db_session, record)

    correct = _correct(
        db_session, tenant, farm, user, target.id,
        corrected={"plant_loss_count": 2, "reason_code": "dead", "effective_time": t0 + timedelta(hours=2), "note": None},
    )
    events = {e.event_kind: e for e in _events_for_command(db_session, correct.id)}
    reversal = events["REVERSAL"]
    replacement = events["REDUCTION"]
    assert reversal.batch_carrier_assignment_id == root_id

    b = db_session.execute(
        select(BatchCarrierAssignment).where(
            BatchCarrierAssignment.opening_production_disposition_reversal_event_id == reversal.id
        )
    ).scalar_one()
    assert replacement.batch_carrier_assignment_id == b.id
    assert replacement.batch_carrier_assignment_id != root_id

    assert production_disposition_service.get_current_living_population(
        db_session, root_batch_carrier_assignment_id=root_id
    ) == 3


# =====================================================================
# A -> B -> C worked proof (ticket section 18, exact)
# =====================================================================


def test_a_to_b_to_c_population_lineage(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=5)

    # E1: A -5 => 0, A released.
    e1_cmd = _record_loss(db_session, tenant, farm, user, root_id, 5, effective_time=t0 + timedelta(hours=1))
    e1 = _last_event(db_session, e1_cmd)
    assert production_disposition_service.get_current_living_population(
        db_session, root_batch_carrier_assignment_id=root_id
    ) == 0

    # E2: reversal +5 => 5, B created.
    correct1 = _correct(db_session, tenant, farm, user, e1.id)
    e2 = _events_for_command(db_session, correct1.id)[0]
    b = db_session.execute(
        select(BatchCarrierAssignment).where(
            BatchCarrierAssignment.opening_production_disposition_reversal_event_id == e2.id
        )
    ).scalar_one()
    assert production_disposition_service.get_current_living_population(
        db_session, root_batch_carrier_assignment_id=root_id
    ) == 5

    # E3: B -2 => 3.
    e3_cmd = _record_loss(db_session, tenant, farm, user, b.id, 2, effective_time=t0 + timedelta(hours=2))
    _last_event(db_session, e3_cmd)
    assert production_disposition_service.get_current_living_population(
        db_session, root_batch_carrier_assignment_id=root_id
    ) == 3

    # E4: B -3 => 0, B released.
    e4_cmd = _record_loss(db_session, tenant, farm, user, b.id, 3, effective_time=t0 + timedelta(hours=3))
    e4 = _last_event(db_session, e4_cmd)
    b_after = db_session.get(BatchCarrierAssignment, b.id)
    assert b_after.released_effective_time is not None
    assert production_disposition_service.get_current_living_population(
        db_session, root_batch_carrier_assignment_id=root_id
    ) == 0

    # E5: reversal +3 => 3, C created.
    correct2 = _correct(db_session, tenant, farm, user, e4.id)
    e5 = _events_for_command(db_session, correct2.id)[0]
    c = db_session.execute(
        select(BatchCarrierAssignment).where(
            BatchCarrierAssignment.opening_production_disposition_reversal_event_id == e5.id
        )
    ).scalar_one()
    assert c.restored_from_batch_carrier_assignment_id == b.id
    assert c.population_root_batch_carrier_assignment_id == root_id
    assert production_disposition_service.get_current_living_population(
        db_session, root_batch_carrier_assignment_id=root_id
    ) == 3

    # E6: C -1 => 2.
    e6_cmd = _record_loss(db_session, tenant, farm, user, c.id, 1, effective_time=t0 + timedelta(hours=4))
    _last_event(db_session, e6_cmd)
    assert production_disposition_service.get_current_living_population(
        db_session, root_batch_carrier_assignment_id=root_id
    ) == 2

    # No TransplantDestinationLine was ever fabricated for B or C.
    from app.models.transplant_destination_line import TransplantDestinationLine

    for gen_id in (b.id, c.id):
        assert db_session.execute(
            select(TransplantDestinationLine.id).where(
                TransplantDestinationLine.destination_batch_carrier_assignment_id == gen_id
            )
        ).scalar_one_or_none() is None

    # Historical A and B never reactivated.
    a_final = db_session.get(BatchCarrierAssignment, root_id)
    b_final = db_session.get(BatchCarrierAssignment, b.id)
    assert a_final.released_effective_time is not None
    assert b_final.released_effective_time is not None
    c_final = db_session.get(BatchCarrierAssignment, c.id)
    assert c_final.released_effective_time is None


# =====================================================================
# Immutability / uniqueness / permissions-adjacent
# =====================================================================


def test_original_event_immutable(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    record = _record_loss(db_session, tenant, farm, user, root_id, 5, effective_time=t0 + timedelta(hours=1))
    target = _last_event(db_session, record)
    original_delta = target.quantity_delta
    _correct(
        db_session, tenant, farm, user, target.id,
        corrected={"plant_loss_count": 3, "reason_code": "dead", "effective_time": t0 + timedelta(hours=2), "note": None},
    )
    db_session.refresh(target)
    assert target.quantity_delta == original_delta


def test_direct_reversal_uniqueness(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    record = _record_loss(db_session, tenant, farm, user, root_id, 5, effective_time=t0 + timedelta(hours=1))
    target = _last_event(db_session, record)
    _correct(db_session, tenant, farm, user, target.id)
    with pytest.raises(ProductionDispositionAlreadyCorrectedError):
        _correct(db_session, tenant, farm, user, target.id)


def test_reversal_cannot_be_corrected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    record = _record_loss(db_session, tenant, farm, user, root_id, 5, effective_time=t0 + timedelta(hours=1))
    target = _last_event(db_session, record)
    correct = _correct(db_session, tenant, farm, user, target.id)
    reversal = _events_for_command(db_session, correct.id)[0]
    with pytest.raises(ProductionDispositionNotReductionError):
        _correct(db_session, tenant, farm, user, reversal.id)


def test_correction_idempotent_replay(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    record = _record_loss(db_session, tenant, farm, user, root_id, 5, effective_time=t0 + timedelta(hours=1))
    target = _last_event(db_session, record)
    cid = uuid.uuid4()
    first = _correct(db_session, tenant, farm, user, target.id, client_command_id=cid)
    second = _correct(db_session, tenant, farm, user, target.id, client_command_id=cid)
    assert second.id == first.id
    assert len(_events_for_command(db_session, first.id)) == 1


def test_correction_same_id_different_payload_conflict(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    record = _record_loss(db_session, tenant, farm, user, root_id, 5, effective_time=t0 + timedelta(hours=1))
    target = _last_event(db_session, record)
    cid = uuid.uuid4()
    _correct(db_session, tenant, farm, user, target.id, client_command_id=cid, corrected=None)
    with pytest.raises(ProductionDispositionCommandReusedWithDifferentPayloadError):
        _correct(
            db_session, tenant, farm, user, target.id, client_command_id=cid,
            corrected={"plant_loss_count": 1, "reason_code": "dead", "effective_time": t0 + timedelta(hours=2), "note": None},
        )


def test_corrected_lineage_traceable(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    record = _record_loss(db_session, tenant, farm, user, root_id, 5, effective_time=t0 + timedelta(hours=1))
    target = _last_event(db_session, record)
    correct = _correct(
        db_session, tenant, farm, user, target.id,
        corrected={"plant_loss_count": 3, "reason_code": "dead", "effective_time": t0 + timedelta(hours=2), "note": None},
    )
    events = {e.event_kind: e for e in _events_for_command(db_session, correct.id)}
    assert events["REVERSAL"].reverses_event_id == target.id
    assert events["REDUCTION"].corrects_event_id == target.id


# =====================================================================
# Carrier reuse protection
# =====================================================================


def test_carrier_reuse_blocks_restoration(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=5)
    record = _record_loss(db_session, tenant, farm, user, root_id, 5, effective_time=t0 + timedelta(hours=1))
    target = _last_event(db_session, record)
    a = db_session.get(BatchCarrierAssignment, root_id)

    other_carrier = db_session.get(Carrier, a.carrier_id)
    assert other_carrier.latest_batch_carrier_assignment_id == a.id

    # Simulate the physical Carrier having since been reused for a
    # different Batch: directly advance `Carrier.latest_batch_carrier_
    # assignment_id` to an unrelated new row (trigger-bypassed, test-only --
    # only the POINTER value matters for this guard, not a fully-valid new
    # BCA lifecycle, mirroring test_seedling_disposition_correction.py's
    # own established direct-SQL reuse-simulation pattern).
    from sqlalchemy import text as _text

    current_db = db_session.execute(_text("SELECT current_database()")).scalar_one()
    assert current_db == "cmp_test"
    new_bca_id = uuid.uuid4()
    db_session.execute(_text("SET session_replication_role = replica"))
    db_session.execute(
        _text(
            "INSERT INTO batch_carrier_assignments "
            "(id, tenant_id, farm_id, batch_id, carrier_id, batch_stage_run_id, assigned_effective_time, "
            "opening_sowing_event_id, actor_user_id) "
            "SELECT :nid, tenant_id, farm_id, batch_id, carrier_id, batch_stage_run_id, now(), "
            ":dummy_opener, actor_user_id "
            "FROM batch_carrier_assignments WHERE id = :aid"
        ),
        {"nid": new_bca_id, "aid": a.id, "dummy_opener": uuid.uuid4()},
    )
    db_session.execute(
        _text("UPDATE carriers SET latest_batch_carrier_assignment_id = :nid WHERE id = :cid"),
        {"nid": new_bca_id, "cid": a.carrier_id},
    )
    db_session.execute(_text("SET session_replication_role = DEFAULT"))
    db_session.commit()

    with pytest.raises(ProductionDispositionCarrierReusedError):
        _correct(db_session, tenant, farm, user, target.id)
