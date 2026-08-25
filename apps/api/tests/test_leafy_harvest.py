"""HARVEST-OPS-001 BUILD SLICE 1: Leafy Production Harvest recording and its
authoritative biological population integration. Mirrors `test_production_
disposition.py`'s coverage shape and scenario-builder reuse pattern for the
sibling authority -- gets a REAL, 005B-composite-created Production
Cultivation Plate BCA with a known opening population, never a fabricated
one."""

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.harvest_population_event import HarvestPopulationEvent
from app.models.occupancy import Occupancy
from app.models.transplant_destination_line import TransplantDestinationLine
from app.services import harvest_service, leafy_population_service
from app.services.errors import (
    CropBatchClosedError,
    HarvestPopulationInsufficientError,
    HarvestSourceAssignmentNotFoundError,
    HarvestValidationError,
    NoPopulationRootError,
    QualityHoldOpenError,
    UnsupportedHarvestSourceCarrierTypeError,
)
from tests.test_leafy_production_transfer import (
    _leafy_setup,
    _nursery_plate_source_scenario,
    _production_plates,
    _record,
    _simple_allocation,
    _simple_destination,
    _simple_source,
)
from tests.test_production_disposition import _plate_scenario

pytestmark = pytest.mark.integration


def _line(aid, count, weight="1.000", **overrides):
    defaults = dict(batch_carrier_assignment_id=aid, whole_unit_count=count, harvested_weight_kg=Decimal(weight), note=None)
    defaults.update(overrides)
    return defaults


def _harvest(db_session, tenant, farm, user, batch_id, source_lines, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch_id,
        client_command_id=uuid.uuid4(), effective_time=None, produce_lot_code=f"HL-{uuid.uuid4().hex[:8]}",
        note=None, source_lines=source_lines,
    )
    defaults.update(overrides)
    return harvest_service.record_leafy_harvest(db_session, **defaults)


def _two_plate_scenario(db_session, tenant, user, farm, *, counts=(180, 100)):
    """Two active Production Cultivation Plate BCAs on the SAME CropBatch --
    a real multi-Plate Leafy Production Transfer, not fabricated data."""
    s, aids = _nursery_plate_source_scenario(
        db_session, tenant, user, farm, source_count=len(counts), opening_count=max(counts) + 20
    )
    table_ids = _leafy_setup(db_session, tenant, user, farm, table_count=len(counts))
    plates, _spec = _production_plates(db_session, tenant, user, farm, count=len(counts))
    t0 = s["transfer_ready_time"] + timedelta(hours=1)
    result = _record(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aids[i]) for i in range(len(counts))],
        [_simple_destination(plates[i].id, table_ids[i], count=counts[i]) for i in range(len(counts))],
        [_simple_allocation(aids[i], plates[i].id, counts[i]) for i in range(len(counts))],
        effective_time=t0,
    )
    root_ids = [dl.destination_batch_carrier_assignment_id for dl in result.destination_lines]
    return s["batch"], root_ids, t0


# =====================================================================
# RECORDING
# =====================================================================


def test_partial_leafy_harvest_reduces_population_and_keeps_bca_active(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    event = _harvest(
        db_session, tenant, farm, user, batch.id, [_line(root_id, 100, "50.000")], effective_time=t0 + timedelta(hours=1)
    )
    assert leafy_population_service.get_current_living_population(
        db_session, root_batch_carrier_assignment_id=root_id
    ) == 80
    bca = db_session.get(BatchCarrierAssignment, root_id)
    assert bca.released_effective_time is None
    assert event.id is not None


def test_exact_zero_leafy_harvest_releases_bca(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=100)
    _harvest(db_session, tenant, farm, user, batch.id, [_line(root_id, 100, "40.000")], effective_time=t0 + timedelta(hours=1))
    bca = db_session.get(BatchCarrierAssignment, root_id)
    assert bca.released_effective_time is not None
    assert bca.released_by_harvest_population_event_id is not None
    assert leafy_population_service.get_current_living_population(
        db_session, root_batch_carrier_assignment_id=root_id
    ) == 0


def test_same_batch_multi_plate_harvest(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    batch, root_ids, t0 = _two_plate_scenario(db_session, tenant, user, farm, counts=(180, 100))
    _harvest(
        db_session, tenant, farm, user, batch.id,
        [_line(root_ids[0], 50, "20.000"), _line(root_ids[1], 30, "10.000")], effective_time=t0 + timedelta(hours=1),
    )
    assert leafy_population_service.get_current_living_population(
        db_session, root_batch_carrier_assignment_id=root_ids[0]
    ) == 130
    assert leafy_population_service.get_current_living_population(
        db_session, root_batch_carrier_assignment_id=root_ids[1]
    ) == 70


def test_multi_plate_harvest_zero_exhausts_only_the_matching_plate(db_session, active_context_with_farm) -> None:
    """Plate A: 180 harvested -> 0. Plate B: 100 harvested 100 -> 80. Only
    Plate A's BCA is released."""
    tenant, user, _headers, farm = active_context_with_farm
    batch, root_ids, t0 = _two_plate_scenario(db_session, tenant, user, farm, counts=(180, 100))
    _harvest(
        db_session, tenant, farm, user, batch.id,
        [_line(root_ids[0], 180, "70.000"), _line(root_ids[1], 20, "8.000")], effective_time=t0 + timedelta(hours=1),
    )
    bca_a = db_session.get(BatchCarrierAssignment, root_ids[0])
    bca_b = db_session.get(BatchCarrierAssignment, root_ids[1])
    assert bca_a.released_effective_time is not None
    assert bca_b.released_effective_time is None
    assert leafy_population_service.get_current_living_population(
        db_session, root_batch_carrier_assignment_id=root_ids[0]
    ) == 0
    assert leafy_population_service.get_current_living_population(
        db_session, root_batch_carrier_assignment_id=root_ids[1]
    ) == 80


def test_rejects_nursery_cultivation_plate_source(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, aids = _nursery_plate_source_scenario(db_session, tenant, user, farm, opening_count=180)
    with pytest.raises(UnsupportedHarvestSourceCarrierTypeError):
        _harvest(
            db_session, tenant, farm, user, s["batch"].id, [_line(aids[0], 5, "2.000")],
            effective_time=s["transfer_ready_time"] + timedelta(hours=1),
        )


def test_requires_whole_unit_count(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    with pytest.raises(HarvestValidationError):
        _harvest(
            db_session, tenant, farm, user, batch.id, [_line(root_id, None, "2.000")], effective_time=t0 + timedelta(hours=1)
        )


def test_rejects_over_harvest_by_population(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=5)
    with pytest.raises(HarvestPopulationInsufficientError):
        _harvest(
            db_session, tenant, farm, user, batch.id, [_line(root_id, 6, "2.000")], effective_time=t0 + timedelta(hours=1)
        )


def test_rejects_harvest_when_living_population_already_zero(db_session, active_context_with_farm) -> None:
    """After an exact-zero harvest, the BCA is released -- a second harvest
    attempt against the SAME (now-released) assignment id is rejected
    exactly like any other release-active check, before population
    sufficiency is even considered (there is no active generation for this
    root at all -- it would need a correction/restoration first)."""
    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=5)
    _harvest(db_session, tenant, farm, user, batch.id, [_line(root_id, 5, "2.000")], effective_time=t0 + timedelta(hours=1))
    with pytest.raises(HarvestValidationError):
        _harvest(
            db_session, tenant, farm, user, batch.id, [_line(root_id, 1, "0.400")], effective_time=t0 + timedelta(hours=2)
        )


def test_raw_weight_independent_from_count(db_session, active_context_with_farm) -> None:
    """A large recorded weight never itself reduces biological population --
    only whole_unit_count does."""
    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    _harvest(
        db_session, tenant, farm, user, batch.id, [_line(root_id, 10, "500.000")], effective_time=t0 + timedelta(hours=1)
    )
    assert leafy_population_service.get_current_living_population(
        db_session, root_batch_carrier_assignment_id=root_id
    ) == 170


def test_quality_hold_blocks_leafy_harvest(db_session, active_context_with_farm) -> None:
    from app.services import quality_hold_service

    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    quality_hold_service.place_quality_hold(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=t0 + timedelta(minutes=30),
        source_observation_event_id=None, reason_code="OTHER", reason_text="test hold",
    )
    with pytest.raises(QualityHoldOpenError):
        _harvest(
            db_session, tenant, farm, user, batch.id, [_line(root_id, 5, "2.000")], effective_time=t0 + timedelta(hours=1)
        )


def test_no_stage_category_gate_for_leafy_harvest(db_session, active_context_with_farm) -> None:
    """`_plate_scenario`'s own Batch never transitions into a
    stage_category='harvesting' WorkflowStage -- Leafy Harvest must still
    succeed (decision 3), unlike generic record_harvest."""
    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    event = _harvest(
        db_session, tenant, farm, user, batch.id, [_line(root_id, 5, "2.000")], effective_time=t0 + timedelta(hours=1)
    )
    assert event is not None


def test_no_automatic_stage_transition(db_session, active_context_with_farm) -> None:
    from app.services import crop_batch_service

    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    _batch_before, run_before, _stage_before = crop_batch_service.get_current_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id
    )
    _harvest(db_session, tenant, farm, user, batch.id, [_line(root_id, 5, "2.000")], effective_time=t0 + timedelta(hours=1))
    _batch_after, run_after, _stage_after = crop_batch_service.get_current_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id
    )
    assert run_after.id == run_before.id


def test_occupancy_unchanged_by_harvest(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    carrier_id = db_session.get(BatchCarrierAssignment, root_id).carrier_id
    before = db_session.execute(
        select(Occupancy.id, Occupancy.end_time).where(Occupancy.occupant_carrier_id == carrier_id)
    ).all()
    _harvest(db_session, tenant, farm, user, batch.id, [_line(root_id, 180, "70.000")], effective_time=t0 + timedelta(hours=1))
    after = db_session.execute(
        select(Occupancy.id, Occupancy.end_time).where(Occupancy.occupant_carrier_id == carrier_id)
    ).all()
    assert before == after


def test_inactive_batch_rejected(db_session, active_context_with_farm) -> None:
    from sqlalchemy import text

    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
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
        _harvest(
            db_session, tenant, farm, user, batch.id, [_line(root_id, 5, "2.000")], effective_time=t0 + timedelta(hours=1)
        )


# =====================================================================
# POPULATION -- shared authority with Plant Loss
# =====================================================================


def test_harvest_and_disposition_share_one_root_balance(db_session, active_context_with_farm) -> None:
    from tests.test_production_disposition import _record_loss

    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    _record_loss(db_session, tenant, farm, user, root_id, 5, effective_time=t0 + timedelta(hours=1))
    _harvest(db_session, tenant, farm, user, batch.id, [_line(root_id, 50, "20.000")], effective_time=t0 + timedelta(hours=2))
    assert leafy_population_service.get_current_living_population(
        db_session, root_batch_carrier_assignment_id=root_id
    ) == 125
    # Both tables' rows genuinely exist and both contribute.
    disposition_events = db_session.execute(
        select(HarvestPopulationEvent).where(
            HarvestPopulationEvent.population_root_batch_carrier_assignment_id == root_id
        )
    ).scalars().all()
    assert len(disposition_events) == 1
    assert disposition_events[0].quantity_delta == -50


def test_same_effective_time_deterministic_grouping(db_session, active_context_with_farm) -> None:
    """A Plant Loss and a Harvest sharing the exact same effective_time
    must not be sensitive to insertion order."""
    from tests.test_production_disposition import _record_loss

    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    shared_time = t0 + timedelta(hours=1)
    _harvest(db_session, tenant, farm, user, batch.id, [_line(root_id, 50, "20.000")], effective_time=shared_time)
    _record_loss(db_session, tenant, farm, user, root_id, 5, effective_time=shared_time)
    assert leafy_population_service.get_current_living_population(
        db_session, root_batch_carrier_assignment_id=root_id
    ) == 125


def test_backdated_harvest_cannot_create_historical_negative_balance(db_session, active_context_with_farm) -> None:
    from tests.test_production_disposition import _record_loss

    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=10)
    _record_loss(db_session, tenant, farm, user, root_id, 8, effective_time=t0 + timedelta(hours=3))
    # Backdated harvest, BEFORE the loss chronologically, would still put
    # the running balance negative if the loss + harvest together exceed
    # the opening quantity at any point walked forward.
    with pytest.raises(HarvestPopulationInsufficientError):
        _harvest(
            db_session, tenant, farm, user, batch.id, [_line(root_id, 5, "2.000")], effective_time=t0 + timedelta(hours=1)
        )


def test_no_fake_transplant_destination_line_created_by_harvest(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    _harvest(db_session, tenant, farm, user, batch.id, [_line(root_id, 180, "70.000")], effective_time=t0 + timedelta(hours=1))
    line_count = db_session.execute(
        select(TransplantDestinationLine.id).where(
            TransplantDestinationLine.destination_batch_carrier_assignment_id == root_id
        )
    ).all()
    assert len(line_count) == 1  # the ORIGINAL transplant line only, never a second one


# =====================================================================
# Tenant / farm isolation
# =====================================================================


def test_tenant_isolation(db_session, active_context_with_farm) -> None:
    from app.services import farm_service, membership_service, tenant_service, user_service

    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)

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
    with pytest.raises(Exception):
        harvest_service.record_leafy_harvest(
            db_session, tenant_id=other_tenant.id, farm_id=other_farm.id, actor_user_id=other_user.id,
            batch_id=batch.id, client_command_id=uuid.uuid4(), effective_time=t0 + timedelta(hours=1),
            produce_lot_code=f"HL-{uuid.uuid4().hex[:8]}", note=None, source_lines=[_line(root_id, 5, "2.000")],
        )
