"""LEAFY-OPS-001: Production Biological Disposition -- authoritative living
population for a Production Cultivation Plate's BatchCarrierAssignment
lineage. Mirrors `test_seedling_disposition.py`'s coverage shape for the
sibling authority, adapted for the population-root design proven in the
`a5c9e21f7b64` migration and the ticket's own A -> B -> C worked example.
Reuses `test_leafy_production_transfer.py`'s scenario builders (the exact
same precedent `test_leafy_production_transfer_read_apis.py` already
established) to get a REAL, 005B-composite-created Production Cultivation
Plate BCA with a known opening population, rather than fabricating one."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.crop_batch import CropBatch
from app.models.occupancy import Occupancy
from app.models.production_disposition_event import ProductionDispositionEvent
from app.services import production_disposition_service
from app.services.errors import (
    BatchCarrierAssignmentNotFoundError,
    CropBatchClosedError,
    InvalidProductionDispositionEffectiveTimeError,
    InvalidProductionDispositionReasonError,
    NoPopulationRootError,
    ProductionDispositionAssignmentReleasedError,
    ProductionDispositionBalanceError,
    ProductionDispositionCommandReusedWithDifferentPayloadError,
    ProductionDispositionValidationError,
    UnsupportedProductionDispositionCarrierTypeError,
)
from tests.test_leafy_production_transfer import (
    NURSERY_PLATE_TYPE,
    PRODUCTION_PLATE_TYPE,
    _leafy_setup,
    _nursery_plate_source_scenario,
    _production_plates,
    _record,
    _simple_allocation,
    _simple_destination,
    _simple_source,
)

pytestmark = pytest.mark.integration


def _plate_scenario(db_session, tenant, user, farm, *, opening_count=180, table_capacity=1):
    """A real, 005B-composite-created Production Cultivation Plate BCA with
    a known opening population -- returns `(batch, root_id)`. `root_id`
    equals the BCA's own id (freshly transplant-created, self-referencing
    root)."""
    s, aids = _nursery_plate_source_scenario(db_session, tenant, user, farm, opening_count=opening_count)
    table_ids = _leafy_setup(db_session, tenant, user, farm, table_capacity=table_capacity)
    plates, _spec = _production_plates(db_session, tenant, user, farm, count=1)
    result = _record(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aids[0])], [_simple_destination(plates[0].id, table_ids[0], count=opening_count)],
        [_simple_allocation(aids[0], plates[0].id, opening_count)],
        effective_time=s["transfer_ready_time"] + timedelta(hours=1),
    )
    root_id = result.destination_lines[0].destination_batch_carrier_assignment_id
    return s["batch"], root_id, s["transfer_ready_time"] + timedelta(hours=1)


def _record_loss(db_session, tenant, farm, user, bca_id, count, *, reason_code="dead", note=None, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        batch_carrier_assignment_id=bca_id, plant_loss_count=count, reason_code=reason_code,
        effective_time=datetime.now(timezone.utc), note=note,
    )
    defaults.update(overrides)
    return production_disposition_service.record_disposition(db_session, **defaults)


def _correct(db_session, tenant, farm, user, target_event_id, corrected=None, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        target_event_id=target_event_id, corrected=corrected,
    )
    defaults.update(overrides)
    return production_disposition_service.correct_disposition(db_session, **defaults)


def _last_event(db_session, command):
    return db_session.execute(
        select(ProductionDispositionEvent).where(ProductionDispositionEvent.command_id == command.id)
    ).scalar_one()


# =====================================================================
# Opening population / backfill (backfill itself proven in the migration
# downgrade-guard test file)
# =====================================================================


def test_opening_population_resolved_from_transplant_destination_line(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, _t = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    assert production_disposition_service.get_root_opening_population(
        db_session, root_batch_carrier_assignment_id=root_id
    ) == 180
    assert production_disposition_service.get_current_living_population(
        db_session, root_batch_carrier_assignment_id=root_id
    ) == 180


def test_future_transplant_destination_bca_gets_self_root(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, _t = _plate_scenario(db_session, tenant, user, farm)
    bca = db_session.get(BatchCarrierAssignment, root_id)
    assert bca.population_root_batch_carrier_assignment_id == bca.id


# =====================================================================
# Record: partial / zero
# =====================================================================


def test_partial_disposition_reduces_living_population(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    command = _record_loss(db_session, tenant, farm, user, root_id, 5, effective_time=t0 + timedelta(hours=1))
    event = _last_event(db_session, command)
    assert event.quantity_delta == -5
    assert production_disposition_service.get_current_living_population(
        db_session, root_batch_carrier_assignment_id=root_id
    ) == 175


def test_partial_disposition_bca_remains_active_and_occupancy_unchanged(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    occ_count_before = db_session.execute(
        select(Occupancy.id).where(Occupancy.occupant_carrier_id == db_session.get(BatchCarrierAssignment, root_id).carrier_id)
    ).all()
    _record_loss(db_session, tenant, farm, user, root_id, 5, effective_time=t0 + timedelta(hours=1))
    bca = db_session.get(BatchCarrierAssignment, root_id)
    assert bca.released_effective_time is None
    occ_count_after = db_session.execute(
        select(Occupancy.id).where(Occupancy.occupant_carrier_id == bca.carrier_id)
    ).all()
    assert occ_count_before == occ_count_after


def test_no_stage_transition_from_disposition(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    from app.services import crop_batch_service

    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    _batch_before, run_before, _stage_before = crop_batch_service.get_current_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id
    )
    _record_loss(db_session, tenant, farm, user, root_id, 5, effective_time=t0 + timedelta(hours=1))
    _batch_after, run_after, _stage_after = crop_batch_service.get_current_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id
    )
    assert run_after.id == run_before.id


def test_exact_zero_disposition_releases_bca(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=5)
    command = _record_loss(db_session, tenant, farm, user, root_id, 5, effective_time=t0 + timedelta(hours=1))
    event = _last_event(db_session, command)
    bca = db_session.get(BatchCarrierAssignment, root_id)
    assert bca.released_effective_time == event.effective_time
    assert bca.released_by_production_disposition_event_id == event.id
    assert production_disposition_service.get_current_living_population(
        db_session, root_batch_carrier_assignment_id=root_id
    ) == 0


def test_zero_release_does_not_touch_occupancy(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=5)
    carrier_id = db_session.get(BatchCarrierAssignment, root_id).carrier_id
    before = db_session.execute(
        select(Occupancy.id, Occupancy.end_time).where(Occupancy.occupant_carrier_id == carrier_id)
    ).all()
    _record_loss(db_session, tenant, farm, user, root_id, 5, effective_time=t0 + timedelta(hours=1))
    after = db_session.execute(
        select(Occupancy.id, Occupancy.end_time).where(Occupancy.occupant_carrier_id == carrier_id)
    ).all()
    assert before == after


def test_over_loss_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=5)
    with pytest.raises(ProductionDispositionBalanceError):
        _record_loss(db_session, tenant, farm, user, root_id, 6, effective_time=t0 + timedelta(hours=1))


# =====================================================================
# Idempotency / conflict
# =====================================================================


def test_exact_replay_returns_same_command(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    cid = uuid.uuid4()
    first = _record_loss(db_session, tenant, farm, user, root_id, 5, effective_time=t0 + timedelta(hours=1), client_command_id=cid)
    second = _record_loss(db_session, tenant, farm, user, root_id, 5, effective_time=t0 + timedelta(hours=1), client_command_id=cid)
    assert second.id == first.id
    events = db_session.execute(
        select(ProductionDispositionEvent).where(ProductionDispositionEvent.command_id == first.id)
    ).all()
    assert len(events) == 1
    assert production_disposition_service.get_current_living_population(
        db_session, root_batch_carrier_assignment_id=root_id
    ) == 175


def test_same_id_different_payload_conflict(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    cid = uuid.uuid4()
    _record_loss(db_session, tenant, farm, user, root_id, 5, effective_time=t0 + timedelta(hours=1), client_command_id=cid)
    with pytest.raises(ProductionDispositionCommandReusedWithDifferentPayloadError):
        _record_loss(db_session, tenant, farm, user, root_id, 6, effective_time=t0 + timedelta(hours=1), client_command_id=cid)


# =====================================================================
# Rejections
# =====================================================================


def test_wrong_carrier_type_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, aids = _nursery_plate_source_scenario(db_session, tenant, user, farm, opening_count=180)
    with pytest.raises(UnsupportedProductionDispositionCarrierTypeError):
        _record_loss(db_session, tenant, farm, user, aids[0], 5, effective_time=s["transfer_ready_time"] + timedelta(hours=1))


def test_historical_generation_rejected_after_restoration(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=5)
    exhaust = _record_loss(db_session, tenant, farm, user, root_id, 5, effective_time=t0 + timedelta(hours=1))
    exhaust_event = _last_event(db_session, exhaust)
    _correct(db_session, tenant, farm, user, exhaust_event.id)
    # root_id (generation A) is now released; a new generation B is active.
    with pytest.raises(ProductionDispositionAssignmentReleasedError):
        _record_loss(db_session, tenant, farm, user, root_id, 1, effective_time=t0 + timedelta(hours=3))


def test_wrong_reason_code_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    with pytest.raises(InvalidProductionDispositionReasonError):
        _record_loss(db_session, tenant, farm, user, root_id, 5, reason_code="not_a_real_reason", effective_time=t0 + timedelta(hours=1))


def test_other_reason_requires_note(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    with pytest.raises(ProductionDispositionValidationError):
        _record_loss(db_session, tenant, farm, user, root_id, 5, reason_code="other", note=None, effective_time=t0 + timedelta(hours=1))
    # With a note, it succeeds.
    _record_loss(db_session, tenant, farm, user, root_id, 5, reason_code="other", note="unusual case", effective_time=t0 + timedelta(hours=1))


def test_future_effective_time_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, _t = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    with pytest.raises(InvalidProductionDispositionEffectiveTimeError):
        _record_loss(db_session, tenant, farm, user, root_id, 5, effective_time=datetime.now(timezone.utc) + timedelta(days=1))


def test_effective_time_before_assignment_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    with pytest.raises(InvalidProductionDispositionEffectiveTimeError):
        _record_loss(db_session, tenant, farm, user, root_id, 5, effective_time=t0 - timedelta(days=1))


def test_unknown_assignment_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    with pytest.raises(BatchCarrierAssignmentNotFoundError):
        _record_loss(db_session, tenant, farm, user, uuid.uuid4(), 5)


def test_inactive_batch_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    # Direct-SQL, trigger-bypassed state simulation (test-only): the normal
    # close path requires transitioning into a terminal WorkflowStage, which
    # this scenario's 2-stage fixture doesn't configure -- bypassing here
    # only proves record_disposition's own `batch.state != "active"` guard,
    # mirroring the same session_replication_role bypass pattern already
    # used elsewhere in this test suite for direct-SQL state simulation.
    current_db = db_session.execute(text("SELECT current_database()")).scalar_one()
    assert current_db == "cmp_test"
    db_session.execute(text("SET session_replication_role = replica"))
    db_session.execute(
        text("UPDATE crop_batches SET state = 'closed', closed_effective_time = now() WHERE id = :id"),
        {"id": batch.id},
    )
    db_session.execute(text("SET session_replication_role = DEFAULT"))
    db_session.commit()
    with pytest.raises(CropBatchClosedError):
        _record_loss(db_session, tenant, farm, user, root_id, 5, effective_time=t0 + timedelta(hours=1))


# =====================================================================
# Quality Hold / mixed Nursery+Production
# =====================================================================


def test_quality_hold_does_not_block_disposition(db_session, active_context_with_farm) -> None:
    from app.services import quality_hold_service

    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    quality_hold_service.place_quality_hold(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=t0 + timedelta(minutes=30),
        source_observation_event_id=None, reason_code="OTHER", reason_text="test hold",
    )
    # A truthful disposition must still be recordable.
    command = _record_loss(db_session, tenant, farm, user, root_id, 5, effective_time=t0 + timedelta(hours=1))
    assert command is not None


def test_mixed_nursery_and_production_disposition_allowed(db_session, active_context_with_farm) -> None:
    """LEAFY-OPS-001 section 23/26: `_plate_scenario` already transitions
    the Batch through TRANSPLANTING -> GROWING -> PRODUCTION_TRANSPLANT
    (never into a `stage_category = 'production'` stage) -- a Production
    Plate disposition must remain legal without any further stage
    transition, proving mixed-placement biology recording."""
    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    command = _record_loss(db_session, tenant, farm, user, root_id, 5, effective_time=t0 + timedelta(hours=1))
    assert command is not None


# =====================================================================
# Tenant / farm isolation
# =====================================================================


def test_tenant_isolation(db_session, active_context_with_farm) -> None:
    from app.services import farm_service, membership_service, tenant_service, user_service

    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)

    other_tenant = tenant_service.create_tenant(db_session, code=f"other-{uuid.uuid4().hex[:8]}", name="Other")
    other_user = user_service.create_user(
        db_session, oidc_issuer="other", oidc_subject=uuid.uuid4().hex[:8],
        email=f"other-{uuid.uuid4().hex[:6]}@example.com", display_name="Other",
    )
    membership_service.add_membership(
        db_session, tenant_id=other_tenant.id, user_id=other_user.id, role_code="tenant_admin", actor_user_id=None
    )
    other_farm = farm_service.create_farm(
        db_session, tenant_id=other_tenant.id, actor_user_id=other_user.id, code=f"farm-{uuid.uuid4().hex[:6]}",
        name="Other Farm", country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    with pytest.raises(BatchCarrierAssignmentNotFoundError):
        production_disposition_service.record_disposition(
            db_session, tenant_id=other_tenant.id, farm_id=other_farm.id, actor_user_id=other_user.id,
            client_command_id=uuid.uuid4(), batch_carrier_assignment_id=root_id, plant_loss_count=5,
            reason_code="dead", effective_time=t0 + timedelta(hours=1), note=None,
        )


def test_farm_isolation(db_session, active_context_with_farm) -> None:
    from app.services import farm_service

    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    other_farm = farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm2-{uuid.uuid4().hex[:6]}",
        name="Second Farm", country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    with pytest.raises(BatchCarrierAssignmentNotFoundError):
        production_disposition_service.record_disposition(
            db_session, tenant_id=tenant.id, farm_id=other_farm.id, actor_user_id=user.id,
            client_command_id=uuid.uuid4(), batch_carrier_assignment_id=root_id, plant_loss_count=5,
            reason_code="dead", effective_time=t0 + timedelta(hours=1), note=None,
        )


# =====================================================================
# Direct-SQL trigger-bypass proofs
# =====================================================================


def test_direct_sql_wrong_root_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    _batch2, root_id2, _t2 = _plate_scenario(db_session, tenant, user, farm, opening_count=100)

    from app.models.production_disposition_command import ProductionDispositionCommand

    cmd = ProductionDispositionCommand(
        id=uuid.uuid4(), tenant_id=tenant.id, farm_id=farm.id, batch_id=_batch.id,
        batch_carrier_assignment_id=root_id, operation_kind="RECORD", target_event_id=None,
        actor_user_id=user.id, client_command_id=uuid.uuid4(), request_fingerprint="x",
    )
    db_session.add(cmd)
    db_session.flush()

    bad_event = ProductionDispositionEvent(
        id=uuid.uuid4(), tenant_id=tenant.id, farm_id=farm.id, command_id=cmd.id,
        batch_carrier_assignment_id=root_id, population_root_batch_carrier_assignment_id=root_id2,
        event_kind="REDUCTION", reason_code="dead", quantity_delta=-1, effective_time=t0 + timedelta(hours=1),
        note=None, reverses_event_id=None, corrects_event_id=None,
    )
    db_session.add(bad_event)
    with pytest.raises(Exception):
        db_session.flush()
    db_session.rollback()


def test_direct_sql_cross_lineage_never_summed(db_session, active_context_with_farm) -> None:
    """Two independent lineages never share a root id -- an event on
    lineage 1 can never be summed into lineage 2's balance."""
    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    _batch2, root_id2, t02 = _plate_scenario(db_session, tenant, user, farm, opening_count=100)
    _record_loss(db_session, tenant, farm, user, root_id, 50, effective_time=t0 + timedelta(hours=1))
    assert production_disposition_service.get_current_living_population(
        db_session, root_batch_carrier_assignment_id=root_id2
    ) == 100
