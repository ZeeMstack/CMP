"""VINES-OPS-002: Vines Production plant-loss (Biological Disposition)
domain coverage -- reuses VINES-OPS-001B's own proven `_vines_production_
scenario.build_vines_production_ready_scenario` plus a real, committed
`vines_production_transfer_service.record_vines_production_transfer` so
every test disposes REAL Grow Cubes placed in REAL Grow Bags, exactly the
shape a Vines operator floor encounters. Covers: happy path, specific Grow
Cube targeting inside a multi-plant Grow Bag, the ticket's own numeric
proofs (Scenarios 1-3), reason validation, wrong-Bag targeting, tenant/Farm
isolation, idempotency, audit, traceability (drill-down read + history),
correction (void), and Grow Bag capacity-after-loss. Concurrency proofs A-C
live in their own file (`test_vines_production_disposition_concurrency.py`)."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models.audit_event import AuditEvent
from app.services import production_disposition_service, vines_production_transfer_service
from app.services.errors import (
    InvalidProductionDispositionReasonError,
    ProductionDispositionGrowCubeAlreadyDisposedError,
    ProductionDispositionGrowCubeNotInAssignmentError,
    ProductionDispositionValidationError,
)
from tests._vines_production_scenario import build_vines_production_ready_scenario

pytestmark = pytest.mark.integration


def _transfer_now(s):
    return s["entry_time"] + timedelta(hours=2)


def _do_transfer(db_session, tenant, farm, user, s, plant_count, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), effective_time=_transfer_now(s), note=None,
        source_intervines_table_id=s["intervines_table_id"],
        destination_grow_gutter_id=s["grow_gutter_id"], grow_bag_specification_id=s["grow_bag_specification"].id,
    )
    defaults.update(overrides)
    return vines_production_transfer_service.record_vines_production_transfer(
        db_session, plant_count=plant_count, **defaults,
    )


def _loss_now(s):
    return _transfer_now(s) + timedelta(hours=1)


def _record_loss(db_session, tenant, farm, user, *, batch_carrier_assignment_id, grow_cube_carrier_ids, s, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        reason_code="dead", effective_time=_loss_now(s), note=None,
    )
    defaults.update(overrides)
    return production_disposition_service.record_grow_cube_disposition(
        db_session, batch_carrier_assignment_id=batch_carrier_assignment_id,
        grow_cube_carrier_ids=grow_cube_carrier_ids, **defaults,
    )


# =====================================================================
# Numeric proof 1: capacity 2, dispose 1 -> living 1, lost 1, free capacity 1
# =====================================================================


@pytest.mark.integration
def test_scenario_1_dispose_one_of_two_leaves_capacity_and_free_capacity_correct(
    db_session, active_context_with_farm,
) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = build_vines_production_ready_scenario(
        db_session, tenant, user, farm, intervines_plant_count=2, grow_bag_capacity=2, grow_bag_count=1,
        gutter_bag_positions=1,
    )
    transfer = _do_transfer(db_session, tenant, farm, user, s, 2)
    bag_assignment_id = transfer.grow_bags[0].destination_batch_carrier_assignment_id
    gc_to_dispose = transfer.source_grow_cubes[0].id

    command = _record_loss(
        db_session, tenant, farm, user, batch_carrier_assignment_id=bag_assignment_id,
        grow_cube_carrier_ids=[gc_to_dispose], s=s,
    )
    assert command.operation_kind == "RECORD"

    living = production_disposition_service.get_current_living_population(
        db_session, root_batch_carrier_assignment_id=bag_assignment_id
    )
    assert living == 1

    bags = vines_production_transfer_service.list_vines_production_placement_grow_bags(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=s["batch"].id, gutter_id=s["grow_gutter_id"],
    )
    bag = next(b for b in bags if b.batch_carrier_assignment_id == bag_assignment_id)
    assert bag.assigned_plant_count == 2  # capacity/opening never rewritten
    assert bag.capacity == 2
    assert bag.living_plant_count == 1
    assert bag.free_capacity == 1  # capacity - living, never capacity - opening

    removed = next(c for c in bag.grow_cubes if c.grow_cube.id == gc_to_dispose)
    living_cube = next(c for c in bag.grow_cubes if c.grow_cube.id != gc_to_dispose)
    assert removed.status == "removed"
    assert removed.disposition is not None
    assert removed.disposition.reason_code == "dead"
    assert living_cube.status == "living"
    assert living_cube.disposition is None


# =====================================================================
# Numeric proof 2: gutter with 10 bags x 2 plants = 20, lose 3 specific
# plants from 3 different bags -> gutter living = 17, no other plant
# identities affected
# =====================================================================


@pytest.mark.integration
def test_scenario_2_losing_three_specific_plants_across_three_bags_leaves_gutter_at_seventeen(
    db_session, active_context_with_farm,
) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = build_vines_production_ready_scenario(
        db_session, tenant, user, farm, intervines_plant_count=20, grow_bag_capacity=2, grow_bag_count=10,
        gutter_bag_positions=10,
    )
    transfer = _do_transfer(db_session, tenant, farm, user, s, 20)
    assert len(transfer.grow_bags) == 10

    # Dispose exactly one specific plant from each of 3 different bags --
    # resolve each bag's own actual Grow Cube via the drill-down read (never
    # assume ordering of source_grow_cubes vs. bag assignment).
    all_bags = vines_production_transfer_service.list_vines_production_placement_grow_bags(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=s["batch"].id, gutter_id=s["grow_gutter_id"],
    )
    disposed_cube_ids = []
    for bag_read in all_bags[:3]:
        gc_id = bag_read.grow_cubes[0].grow_cube.id
        disposed_cube_ids.append(gc_id)
        _record_loss(
            db_session, tenant, farm, user, batch_carrier_assignment_id=bag_read.batch_carrier_assignment_id,
            grow_cube_carrier_ids=[gc_id], s=s, client_command_id=uuid.uuid4(),
        )

    placements = vines_production_transfer_service.list_vines_production_placements(
        db_session, tenant_id=tenant.id, farm_id=farm.id,
    )
    row = next(p for p in placements if p.batch_id == s["batch"].id and p.gutter_id == s["grow_gutter_id"])
    assert row.living_plant_count == 17
    assert row.lost_plant_count == 3
    assert row.plant_count == 20  # opening total untouched

    # No other plant identity was affected: every untouched bag still shows
    # both its Grow Cubes as living.
    refreshed_bags = vines_production_transfer_service.list_vines_production_placement_grow_bags(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=s["batch"].id, gutter_id=s["grow_gutter_id"],
    )
    for bag in refreshed_bags:
        if bag.batch_carrier_assignment_id in [b.batch_carrier_assignment_id for b in all_bags[:3]]:
            living_count = sum(1 for c in bag.grow_cubes if c.status == "living")
            assert living_count == 1
        else:
            assert all(c.status == "living" for c in bag.grow_cubes)


# =====================================================================
# Numeric proof 3: attempt to dispose an already-disposed Grow Cube again
# =====================================================================


@pytest.mark.integration
def test_scenario_3_disposing_already_disposed_grow_cube_is_rejected_and_population_unchanged(
    db_session, active_context_with_farm,
) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = build_vines_production_ready_scenario(
        db_session, tenant, user, farm, intervines_plant_count=2, grow_bag_capacity=2, grow_bag_count=1,
        gutter_bag_positions=1,
    )
    transfer = _do_transfer(db_session, tenant, farm, user, s, 2)
    bag_assignment_id = transfer.grow_bags[0].destination_batch_carrier_assignment_id
    gc_id = transfer.source_grow_cubes[0].id

    _record_loss(
        db_session, tenant, farm, user, batch_carrier_assignment_id=bag_assignment_id,
        grow_cube_carrier_ids=[gc_id], s=s,
    )
    living_after_first = production_disposition_service.get_current_living_population(
        db_session, root_batch_carrier_assignment_id=bag_assignment_id
    )
    assert living_after_first == 1

    loss_count_before = db_session.execute(
        select(production_disposition_service.ProductionDispositionEvent).where(
            production_disposition_service.ProductionDispositionEvent.population_root_batch_carrier_assignment_id
            == bag_assignment_id
        )
    ).scalars().all()

    with pytest.raises(ProductionDispositionGrowCubeAlreadyDisposedError):
        _record_loss(
            db_session, tenant, farm, user, batch_carrier_assignment_id=bag_assignment_id,
            grow_cube_carrier_ids=[gc_id], s=s, client_command_id=uuid.uuid4(),
        )

    living_after_second = production_disposition_service.get_current_living_population(
        db_session, root_batch_carrier_assignment_id=bag_assignment_id
    )
    assert living_after_second == living_after_first
    loss_count_after = db_session.execute(
        select(production_disposition_service.ProductionDispositionEvent).where(
            production_disposition_service.ProductionDispositionEvent.population_root_batch_carrier_assignment_id
            == bag_assignment_id
        )
    ).scalars().all()
    assert len(loss_count_after) == len(loss_count_before)


# =====================================================================
# Validation
# =====================================================================


@pytest.mark.integration
def test_invalid_reason_code_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = build_vines_production_ready_scenario(
        db_session, tenant, user, farm, intervines_plant_count=1, grow_bag_capacity=1, grow_bag_count=1,
        gutter_bag_positions=1,
    )
    transfer = _do_transfer(db_session, tenant, farm, user, s, 1)
    bag_assignment_id = transfer.grow_bags[0].destination_batch_carrier_assignment_id
    gc_id = transfer.source_grow_cubes[0].id

    with pytest.raises(InvalidProductionDispositionReasonError):
        _record_loss(
            db_session, tenant, farm, user, batch_carrier_assignment_id=bag_assignment_id,
            grow_cube_carrier_ids=[gc_id], s=s, reason_code="not_a_real_reason",
        )


@pytest.mark.integration
def test_other_reason_requires_note(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = build_vines_production_ready_scenario(
        db_session, tenant, user, farm, intervines_plant_count=1, grow_bag_capacity=1, grow_bag_count=1,
        gutter_bag_positions=1,
    )
    transfer = _do_transfer(db_session, tenant, farm, user, s, 1)
    bag_assignment_id = transfer.grow_bags[0].destination_batch_carrier_assignment_id
    gc_id = transfer.source_grow_cubes[0].id

    with pytest.raises(ProductionDispositionValidationError):
        _record_loss(
            db_session, tenant, farm, user, batch_carrier_assignment_id=bag_assignment_id,
            grow_cube_carrier_ids=[gc_id], s=s, reason_code="other", note=None,
        )

    # succeeds once a note is supplied
    command = _record_loss(
        db_session, tenant, farm, user, batch_carrier_assignment_id=bag_assignment_id,
        grow_cube_carrier_ids=[gc_id], s=s, reason_code="other", note="unexpected wilt",
    )
    assert command.operation_kind == "RECORD"


@pytest.mark.integration
def test_grow_cube_not_placed_in_this_grow_bag_is_rejected(db_session, active_context_with_farm) -> None:
    """A Grow Cube from a DIFFERENT Grow Bag may never be disposed by naming
    a foreign bag's own `batch_carrier_assignment_id`."""
    tenant, user, _headers, farm = active_context_with_farm
    s = build_vines_production_ready_scenario(
        db_session, tenant, user, farm, intervines_plant_count=2, grow_bag_capacity=1, grow_bag_count=2,
        gutter_bag_positions=2,
    )
    transfer = _do_transfer(db_session, tenant, farm, user, s, 2)
    assert len(transfer.grow_bags) == 2
    bag_a = transfer.grow_bags[0]
    bag_b = transfer.grow_bags[1]

    all_bags = vines_production_transfer_service.list_vines_production_placement_grow_bags(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=s["batch"].id, gutter_id=s["grow_gutter_id"],
    )
    bag_b_cube_id = next(
        b for b in all_bags if b.batch_carrier_assignment_id == bag_b.destination_batch_carrier_assignment_id
    ).grow_cubes[0].grow_cube.id

    with pytest.raises(ProductionDispositionGrowCubeNotInAssignmentError):
        _record_loss(
            db_session, tenant, farm, user, batch_carrier_assignment_id=bag_a.destination_batch_carrier_assignment_id,
            grow_cube_carrier_ids=[bag_b_cube_id], s=s,
        )


@pytest.mark.integration
def test_duplicate_grow_cube_ids_in_one_request_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = build_vines_production_ready_scenario(
        db_session, tenant, user, farm, intervines_plant_count=2, grow_bag_capacity=2, grow_bag_count=1,
        gutter_bag_positions=1,
    )
    transfer = _do_transfer(db_session, tenant, farm, user, s, 2)
    bag_assignment_id = transfer.grow_bags[0].destination_batch_carrier_assignment_id
    gc_id = transfer.source_grow_cubes[0].id

    with pytest.raises(ProductionDispositionValidationError):
        _record_loss(
            db_session, tenant, farm, user, batch_carrier_assignment_id=bag_assignment_id,
            grow_cube_carrier_ids=[gc_id, gc_id], s=s,
        )


# =====================================================================
# Idempotency
# =====================================================================


@pytest.mark.integration
def test_replay_same_client_command_id_returns_same_command(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = build_vines_production_ready_scenario(
        db_session, tenant, user, farm, intervines_plant_count=1, grow_bag_capacity=1, grow_bag_count=1,
        gutter_bag_positions=1,
    )
    transfer = _do_transfer(db_session, tenant, farm, user, s, 1)
    bag_assignment_id = transfer.grow_bags[0].destination_batch_carrier_assignment_id
    gc_id = transfer.source_grow_cubes[0].id
    client_command_id = uuid.uuid4()

    first = _record_loss(
        db_session, tenant, farm, user, batch_carrier_assignment_id=bag_assignment_id,
        grow_cube_carrier_ids=[gc_id], s=s, client_command_id=client_command_id,
    )
    second = _record_loss(
        db_session, tenant, farm, user, batch_carrier_assignment_id=bag_assignment_id,
        grow_cube_carrier_ids=[gc_id], s=s, client_command_id=client_command_id,
    )
    assert first.id == second.id

    events = db_session.execute(
        select(production_disposition_service.ProductionDispositionEvent).where(
            production_disposition_service.ProductionDispositionEvent.command_id == first.id
        )
    ).scalars().all()
    assert len(events) == 1


@pytest.mark.integration
def test_replay_same_client_command_id_different_payload_conflicts(db_session, active_context_with_farm) -> None:
    from app.services.errors import ProductionDispositionCommandReusedWithDifferentPayloadError

    tenant, user, _headers, farm = active_context_with_farm
    s = build_vines_production_ready_scenario(
        db_session, tenant, user, farm, intervines_plant_count=1, grow_bag_capacity=1, grow_bag_count=1,
        gutter_bag_positions=1,
    )
    transfer = _do_transfer(db_session, tenant, farm, user, s, 1)
    bag_assignment_id = transfer.grow_bags[0].destination_batch_carrier_assignment_id
    gc_id = transfer.source_grow_cubes[0].id
    client_command_id = uuid.uuid4()

    _record_loss(
        db_session, tenant, farm, user, batch_carrier_assignment_id=bag_assignment_id,
        grow_cube_carrier_ids=[gc_id], s=s, client_command_id=client_command_id, reason_code="dead",
    )
    with pytest.raises(ProductionDispositionCommandReusedWithDifferentPayloadError):
        _record_loss(
            db_session, tenant, farm, user, batch_carrier_assignment_id=bag_assignment_id,
            grow_cube_carrier_ids=[gc_id], s=s, client_command_id=client_command_id, reason_code="disease_removal",
        )


# =====================================================================
# Audit
# =====================================================================


@pytest.mark.integration
def test_record_writes_one_audit_event(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = build_vines_production_ready_scenario(
        db_session, tenant, user, farm, intervines_plant_count=1, grow_bag_capacity=1, grow_bag_count=1,
        gutter_bag_positions=1,
    )
    transfer = _do_transfer(db_session, tenant, farm, user, s, 1)
    bag_assignment_id = transfer.grow_bags[0].destination_batch_carrier_assignment_id
    gc_id = transfer.source_grow_cubes[0].id

    command = _record_loss(
        db_session, tenant, farm, user, batch_carrier_assignment_id=bag_assignment_id,
        grow_cube_carrier_ids=[gc_id], s=s,
    )

    events = db_session.execute(
        select(AuditEvent).where(
            AuditEvent.tenant_id == tenant.id,
            AuditEvent.action == "crop_batch.vines_grow_cube_disposition_recorded",
        )
    ).scalars().all()
    assert len(events) == 1
    assert events[0].event_data["command_id"] == str(command.id)
    assert events[0].event_data["grow_cube_carrier_ids"] == [str(gc_id)]


# =====================================================================
# Traceability
# =====================================================================


@pytest.mark.integration
def test_history_shows_removed_grow_cube_with_reason_and_actor(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = build_vines_production_ready_scenario(
        db_session, tenant, user, farm, intervines_plant_count=1, grow_bag_capacity=1, grow_bag_count=1,
        gutter_bag_positions=1,
    )
    transfer = _do_transfer(db_session, tenant, farm, user, s, 1)
    bag_assignment_id = transfer.grow_bags[0].destination_batch_carrier_assignment_id
    gc_id = transfer.source_grow_cubes[0].id

    _record_loss(
        db_session, tenant, farm, user, batch_carrier_assignment_id=bag_assignment_id,
        grow_cube_carrier_ids=[gc_id], s=s, reason_code="disease_removal", note="powdery mildew",
    )

    history = vines_production_transfer_service.get_vines_production_disposition_history(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=s["batch"].id,
    )
    lineage = next(h for h in history if h.population_root_batch_carrier_assignment_id == bag_assignment_id)
    assert lineage.opening_population == 1
    assert lineage.current_living_population == 0
    assert lineage.is_active is False  # fully exhausted -> released, same rule as Leafy
    reduction = next(e for e in lineage.events if e.event_kind == "REDUCTION")
    assert reduction.reason_code == "disease_removal"
    assert reduction.note == "powdery mildew"
    assert reduction.actor_user_id == user.id
    assert [c.id for c in reduction.grow_cubes] == [gc_id]


# =====================================================================
# Correction (void) -- frees the Grow Cube for a later, truthful disposition
# =====================================================================


@pytest.mark.integration
def test_void_correction_frees_grow_cube_for_redisposal(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = build_vines_production_ready_scenario(
        db_session, tenant, user, farm, intervines_plant_count=1, grow_bag_capacity=1, grow_bag_count=1,
        gutter_bag_positions=1,
    )
    transfer = _do_transfer(db_session, tenant, farm, user, s, 1)
    bag_assignment_id = transfer.grow_bags[0].destination_batch_carrier_assignment_id
    gc_id = transfer.source_grow_cubes[0].id

    command = _record_loss(
        db_session, tenant, farm, user, batch_carrier_assignment_id=bag_assignment_id,
        grow_cube_carrier_ids=[gc_id], s=s,
    )
    target_event_id = db_session.execute(
        select(production_disposition_service.ProductionDispositionEvent.id).where(
            production_disposition_service.ProductionDispositionEvent.command_id == command.id
        )
    ).scalar_one()

    production_disposition_service.correct_grow_cube_disposition(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        target_event_id=target_event_id, corrected=None,
    )

    living = production_disposition_service.get_current_living_population(
        db_session, root_batch_carrier_assignment_id=bag_assignment_id
    )
    assert living == 1  # restored

    status = production_disposition_service.get_grow_cube_disposition_status(
        db_session, grow_cube_carrier_ids=[gc_id]
    )
    assert gc_id not in status  # eligible again

    # A later, truthful disposition of the SAME Grow Cube now succeeds.
    replacement_assignment_id = db_session.execute(
        select(production_disposition_service.BatchCarrierAssignment.id).where(
            production_disposition_service.BatchCarrierAssignment.population_root_batch_carrier_assignment_id
            == bag_assignment_id,
            production_disposition_service.BatchCarrierAssignment.released_effective_time.is_(None),
        )
    ).scalar_one()
    _record_loss(
        db_session, tenant, farm, user, batch_carrier_assignment_id=replacement_assignment_id,
        grow_cube_carrier_ids=[gc_id], s=s, client_command_id=uuid.uuid4(),
    )
    living_after = production_disposition_service.get_current_living_population(
        db_session, root_batch_carrier_assignment_id=bag_assignment_id
    )
    assert living_after == 0


# =====================================================================
# Tenant/Farm isolation
# =====================================================================


@pytest.mark.integration
def test_cannot_dispose_against_assignment_from_another_tenant(db_session, active_context_with_farm) -> None:
    from app.services import farm_service, membership_service, tenant_service, user_service
    from app.services.errors import BatchCarrierAssignmentNotFoundError

    tenant, user, _headers, farm = active_context_with_farm
    s = build_vines_production_ready_scenario(
        db_session, tenant, user, farm, intervines_plant_count=1, grow_bag_capacity=1, grow_bag_count=1,
        gutter_bag_positions=1,
    )
    transfer = _do_transfer(db_session, tenant, farm, user, s, 1)
    bag_assignment_id = transfer.grow_bags[0].destination_batch_carrier_assignment_id
    gc_id = transfer.source_grow_cubes[0].id

    other_tenant = tenant_service.create_tenant(db_session, code=f"other-{uuid.uuid4().hex[:8]}", name="Other Tenant")
    other_user = user_service.create_user(
        db_session, oidc_issuer="other", oidc_subject=uuid.uuid4().hex, email=f"{uuid.uuid4().hex}@example.com",
        display_name="Other User",
    )
    membership_service.add_membership(
        db_session, tenant_id=other_tenant.id, user_id=other_user.id, role_code="tenant_admin", actor_user_id=None
    )
    other_farm = farm_service.create_farm(
        db_session, tenant_id=other_tenant.id, actor_user_id=other_user.id, code="other-farm", name="Other Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )

    with pytest.raises(BatchCarrierAssignmentNotFoundError):
        _record_loss(
            db_session, other_tenant, other_farm, other_user, batch_carrier_assignment_id=bag_assignment_id,
            grow_cube_carrier_ids=[gc_id], s=s,
        )
