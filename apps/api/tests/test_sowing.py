import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.models.audit_event import AuditEvent
from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.movement import Movement
from app.models.occupancy import Occupancy
from app.models.sowing_event import SowingEvent
from app.models.sowing_event_line import SowingEventLine
from app.schemas.sowing_event import SowingEventCreate, SowingEventLineIn
from app.services import (
    carrier_service,
    crop_batch_service,
    crop_service,
    production_system_service,
    sowing_service,
    workflow_service,
)
from app.services.errors import (
    CarrierAlreadyAssignedError,
    CropBatchClosedError,
    InvalidSowingEffectiveTimeError,
    SowingCommandReusedWithDifferentPayloadError,
    SowingValidationError,
    TooManySowingLinesError,
)

# --- Application-level (Pydantic) validation — no DB required ---


def _line(**overrides):
    defaults = dict(carrier_id=uuid.uuid4(), seed_lot_id=uuid.uuid4(), sown_site_count=200, seed_count=200)
    defaults.update(overrides)
    return SowingEventLineIn(**defaults)


def test_sowing_line_seed_count_below_site_count_rejected() -> None:
    with pytest.raises(ValueError):
        _line(sown_site_count=200, seed_count=100)


def test_sowing_line_non_positive_counts_rejected() -> None:
    with pytest.raises(ValueError):
        _line(sown_site_count=0, seed_count=10)
    with pytest.raises(ValueError):
        _line(sown_site_count=10, seed_count=0)


def test_sowing_line_note_blank_becomes_none() -> None:
    line = _line(line_note="   ")
    assert line.line_note is None


def test_sowing_event_duplicate_carrier_rejected() -> None:
    carrier_id = uuid.uuid4()
    with pytest.raises(ValueError):
        SowingEventCreate(
            client_command_id=uuid.uuid4(), effective_time=datetime.now(timezone.utc),
            lines=[_line(carrier_id=carrier_id), _line(carrier_id=carrier_id)],
        )


def test_sowing_event_naive_effective_time_rejected() -> None:
    with pytest.raises(ValueError):
        SowingEventCreate(client_command_id=uuid.uuid4(), effective_time=datetime.now(), lines=[_line()])


def test_sowing_event_requires_at_least_one_line() -> None:
    with pytest.raises(ValueError):
        SowingEventCreate(client_command_id=uuid.uuid4(), effective_time=datetime.now(timezone.utc), lines=[])


def test_sowing_event_rejects_more_than_500_lines() -> None:
    with pytest.raises(ValueError):
        SowingEventCreate(
            client_command_id=uuid.uuid4(), effective_time=datetime.now(timezone.utc),
            lines=[_line() for _ in range(501)],
        )


def test_sowing_event_rejects_extra_fields() -> None:
    with pytest.raises(ValueError):
        SowingEventCreate(
            client_command_id=uuid.uuid4(), effective_time=datetime.now(timezone.utc), lines=[_line()],
            batch_id=uuid.uuid4(),
        )


# --- Integration helpers ----------------------------------------------------------


def _now():
    return datetime.now(timezone.utc)


def _build_scenario(
    db_session, tenant, user, farm, *, suffix=None, with_variety=True,
    required_carrier_type_code="seed_tray",
):
    suffix = suffix or uuid.uuid4().hex[:8]
    crop = crop_service.register_crop(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"ICE-{suffix}",
        common_name="Iceberg Lettuce", scientific_name=None, crop_category="leafy_green",
    )
    variety = crop_service.register_variety(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"MAM-{suffix}",
        name="Mamutik RZ", supplier_reference=None,
    )
    ps = production_system_service.register_production_system(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"PS-{suffix}", name="Nursery Tray",
        description=None,
    )
    workflow = workflow_service.register_workflow(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id,
        variety_id=(variety.id if with_variety else None), production_system_id=ps.id,
        code=f"WF-{suffix}", name="Iceberg Nursery",
    )
    version = workflow_service.create_draft_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id
    )
    stage_defs = [
        ("SEEDING", "seeding", required_carrier_type_code, True, False),
        ("GERMINATION", "germination", None, False, False),
        ("COMPLETE", "completed", None, False, True),
    ]
    stages = {}
    for i, (code, category, carrier_type_code, is_start, is_terminal) in enumerate(stage_defs):
        stage = workflow_service.add_stage(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id,
            version_id=version.id, code=code, name=code.title(), display_order=i, stage_category=category,
            expected_duration_minutes=None, permitted_location_type_code=None,
            required_carrier_type_code=carrier_type_code, is_start=is_start, is_terminal=is_terminal,
        )
        stages[code] = stage
    transitions = {}
    codes = [c for c, *_ in stage_defs]
    for i in range(len(codes) - 1):
        t = workflow_service.add_transition(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id,
            version_id=version.id, from_stage_id=stages[codes[i]].id, to_stage_id=stages[codes[i + 1]].id,
            code=f"ADVANCE-{i}", name=f"Advance {i}",
        )
        transitions[(codes[i], codes[i + 1])] = t
    published = workflow_service.publish_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id
    )
    batch = crop_batch_service.create_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=uuid.uuid4(), code=f"BATCH-{suffix}", workflow_id=workflow.id, effective_time=_now(),
    )
    seed_lot = sowing_service.register_seed_lot(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id,
        variety_id=variety.id, code=f"LOT-{suffix}", supplier_name=None, supplier_lot_reference=None,
        received_date=None, expiry_date=None,
    )
    carriers = [
        carrier_service.register_carrier(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            carrier_type_code="seed_tray", code=f"ST-{suffix}-{n:04d}", issued_date=None,
        )
        for n in range(1, 5)
    ]
    return {
        "crop": crop, "variety": variety, "workflow": workflow, "version": published, "stages": stages,
        "transitions": transitions, "batch": batch, "seed_lot": seed_lot, "carriers": carriers,
    }


def _sow(db_session, tenant, user, farm, batch, lines, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
    )
    defaults.update(overrides)
    return sowing_service.sow_batch(db_session, lines=lines, **defaults)


def _simple_line(carrier, seed_lot, **overrides):
    defaults = dict(
        carrier_id=carrier.id, seed_lot_id=seed_lot.id, sown_site_count=200, seed_count=200, line_note=None
    )
    defaults.update(overrides)
    return defaults


# --- Core sowing behavior ----------------------------------------------------------


@pytest.mark.integration
def test_sow_single_carrier_creates_event_assignment_and_audit(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    event = _sow(db_session, tenant, user, farm, s["batch"], [_simple_line(s["carriers"][0], s["seed_lot"])])

    assert db_session.execute(select(func.count()).select_from(SowingEvent)).scalar_one() == 1
    assert db_session.execute(select(func.count()).select_from(SowingEventLine)).scalar_one() == 1
    assignments = list(
        db_session.execute(select(BatchCarrierAssignment).where(BatchCarrierAssignment.batch_id == s["batch"].id))
        .scalars()
    )
    assert len(assignments) == 1
    assert assignments[0].carrier_id == s["carriers"][0].id
    assert assignments[0].released_effective_time is None
    audit_count = db_session.execute(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "crop_batch.sown")
    ).scalar_one()
    assert audit_count == 1
    assert event.batch_id == s["batch"].id


@pytest.mark.integration
def test_sow_multiple_carriers_atomic(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    lines = [_simple_line(c, s["seed_lot"]) for c in s["carriers"]]
    _sow(db_session, tenant, user, farm, s["batch"], lines)

    assert db_session.execute(select(func.count()).select_from(SowingEventLine)).scalar_one() == 4
    assert db_session.execute(select(func.count()).select_from(BatchCarrierAssignment)).scalar_one() == 4


@pytest.mark.integration
def test_sow_no_occupancy_or_movement_rows_created(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    before_occ = db_session.execute(select(func.count()).select_from(Occupancy)).scalar_one()
    before_mov = db_session.execute(select(func.count()).select_from(Movement)).scalar_one()

    _sow(db_session, tenant, user, farm, s["batch"], [_simple_line(s["carriers"][0], s["seed_lot"])])

    after_occ = db_session.execute(select(func.count()).select_from(Occupancy)).scalar_one()
    after_mov = db_session.execute(select(func.count()).select_from(Movement)).scalar_one()
    assert after_occ == before_occ
    assert after_mov == before_mov


@pytest.mark.integration
def test_sow_non_seeding_stage_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    crop_batch_service.transition_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), configured_transition_id=s["transitions"][("SEEDING", "GERMINATION")].id,
        effective_time=_now(), reason=None,
    )
    with pytest.raises(SowingValidationError):
        _sow(db_session, tenant, user, farm, s["batch"], [_simple_line(s["carriers"][0], s["seed_lot"])])


@pytest.mark.integration
def test_sow_missing_required_carrier_type_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, required_carrier_type_code=None)
    with pytest.raises(SowingValidationError):
        _sow(db_session, tenant, user, farm, s["batch"], [_simple_line(s["carriers"][0], s["seed_lot"])])


@pytest.mark.integration
def test_sow_carrier_type_mismatch_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    wrong_type_carrier = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        carrier_type_code="cultivation_plate", code="CP-0001", issued_date=None,
    )
    with pytest.raises(SowingValidationError):
        _sow(db_session, tenant, user, farm, s["batch"], [_simple_line(wrong_type_carrier, s["seed_lot"])])


@pytest.mark.integration
def test_sow_carrier_already_assigned_to_another_batch_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s1 = _build_scenario(db_session, tenant, user, farm)
    s2 = _build_scenario(db_session, tenant, user, farm)
    _sow(db_session, tenant, user, farm, s1["batch"], [_simple_line(s1["carriers"][0], s1["seed_lot"])])
    with pytest.raises(CarrierAlreadyAssignedError):
        _sow(db_session, tenant, user, farm, s2["batch"], [_simple_line(s1["carriers"][0], s2["seed_lot"])])


@pytest.mark.integration
def test_sow_batch_without_variety_workflow_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, with_variety=False)
    with pytest.raises(SowingValidationError):
        _sow(db_session, tenant, user, farm, s["batch"], [_simple_line(s["carriers"][0], s["seed_lot"])])


@pytest.mark.integration
def test_sow_inactive_workflow_variety_rejected(db_session, active_context_with_farm) -> None:
    from app.models.variety import Variety

    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    # Deactivate only after publication succeeds — publish-time validation
    # already requires an active variety, so this must happen afterward to
    # isolate the sowing-time check.
    db_session.get(Variety, s["variety"].id).status = "inactive"
    db_session.flush()
    with pytest.raises(SowingValidationError):
        _sow(db_session, tenant, user, farm, s["batch"], [_simple_line(s["carriers"][0], s["seed_lot"])])


@pytest.mark.integration
def test_sow_seed_lot_crop_mismatch_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    other = _build_scenario(db_session, tenant, user, farm)
    with pytest.raises(SowingValidationError):
        _sow(db_session, tenant, user, farm, s["batch"], [_simple_line(s["carriers"][0], other["seed_lot"])])


@pytest.mark.integration
def test_sow_inactive_seed_lot_rejected(db_session, active_context_with_farm) -> None:
    from app.models.seed_lot import SeedLot

    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    db_session.get(SeedLot, s["seed_lot"].id).status = "inactive"
    db_session.flush()
    with pytest.raises(SowingValidationError):
        _sow(db_session, tenant, user, farm, s["batch"], [_simple_line(s["carriers"][0], s["seed_lot"])])


@pytest.mark.integration
def test_sow_expired_seed_lot_rejected_in_farm_timezone(db_session, active_context_with_farm) -> None:
    from app.models.seed_lot import SeedLot

    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    lot = db_session.get(SeedLot, s["seed_lot"].id)
    lot.expiry_date = (datetime.now(timezone.utc) - timedelta(days=2)).date()
    db_session.flush()
    with pytest.raises(InvalidSowingEffectiveTimeError):
        _sow(db_session, tenant, user, farm, s["batch"], [_simple_line(s["carriers"][0], s["seed_lot"])])


@pytest.mark.integration
def test_sow_not_yet_received_seed_lot_rejected_in_farm_timezone(db_session, active_context_with_farm) -> None:
    from app.models.seed_lot import SeedLot

    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    lot = db_session.get(SeedLot, s["seed_lot"].id)
    lot.received_date = (datetime.now(timezone.utc) + timedelta(days=2)).date()
    db_session.flush()
    with pytest.raises(InvalidSowingEffectiveTimeError):
        _sow(db_session, tenant, user, farm, s["batch"], [_simple_line(s["carriers"][0], s["seed_lot"])])


@pytest.mark.integration
def test_sow_closed_batch_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    crop_batch_service.transition_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), configured_transition_id=s["transitions"][("SEEDING", "GERMINATION")].id,
        effective_time=_now(), reason=None,
    )
    crop_batch_service.transition_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), configured_transition_id=s["transitions"][("GERMINATION", "COMPLETE")].id,
        effective_time=_now(), reason=None,
    )
    with pytest.raises(CropBatchClosedError):
        _sow(db_session, tenant, user, farm, s["batch"], [_simple_line(s["carriers"][0], s["seed_lot"])])


@pytest.mark.integration
def test_sow_future_effective_time_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    with pytest.raises(InvalidSowingEffectiveTimeError):
        _sow(
            db_session, tenant, user, farm, s["batch"], [_simple_line(s["carriers"][0], s["seed_lot"])],
            effective_time=_now() + timedelta(hours=1),
        )


@pytest.mark.integration
def test_sow_effective_time_before_batch_creation_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    with pytest.raises(InvalidSowingEffectiveTimeError):
        _sow(
            db_session, tenant, user, farm, s["batch"], [_simple_line(s["carriers"][0], s["seed_lot"])],
            effective_time=s["batch"].created_effective_time - timedelta(days=1),
        )


@pytest.mark.integration
def test_sow_too_many_lines_rejected_before_writes(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    lines = [_simple_line(s["carriers"][0], s["seed_lot"], seed_count=1, sown_site_count=1) for _ in range(501)]
    # Bypass carrier-uniqueness so the 501-line guard is what actually fires.
    for i, line in enumerate(lines):
        line["carrier_id"] = uuid.uuid4()
    with pytest.raises(TooManySowingLinesError):
        _sow(db_session, tenant, user, farm, s["batch"], lines)
    assert db_session.execute(select(func.count()).select_from(SowingEvent)).scalar_one() == 0


@pytest.mark.integration
def test_sow_repeated_events_with_disjoint_carriers_succeed(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    _sow(db_session, tenant, user, farm, s["batch"], [_simple_line(s["carriers"][0], s["seed_lot"])])
    _sow(db_session, tenant, user, farm, s["batch"], [_simple_line(s["carriers"][1], s["seed_lot"])])
    assert db_session.execute(select(func.count()).select_from(SowingEvent)).scalar_one() == 2
    assert db_session.execute(select(func.count()).select_from(BatchCarrierAssignment)).scalar_one() == 2


# --- Idempotency --------------------------------------------------------------------


@pytest.mark.integration
def test_sow_exact_retry_returns_original_event(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    command_id = uuid.uuid4()
    effective_time = _now()
    first = _sow(
        db_session, tenant, user, farm, s["batch"], [_simple_line(s["carriers"][0], s["seed_lot"])],
        client_command_id=command_id, effective_time=effective_time,
    )
    second = _sow(
        db_session, tenant, user, farm, s["batch"], [_simple_line(s["carriers"][0], s["seed_lot"])],
        client_command_id=command_id, effective_time=effective_time,
    )
    assert first.id == second.id
    assert db_session.execute(select(func.count()).select_from(SowingEvent)).scalar_one() == 1
    assert db_session.execute(select(func.count()).select_from(BatchCarrierAssignment)).scalar_one() == 1


@pytest.mark.integration
def test_sow_reused_command_id_different_payload_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    command_id = uuid.uuid4()
    _sow(
        db_session, tenant, user, farm, s["batch"], [_simple_line(s["carriers"][0], s["seed_lot"])],
        client_command_id=command_id,
    )
    with pytest.raises(SowingCommandReusedWithDifferentPayloadError):
        _sow(
            db_session, tenant, user, farm, s["batch"], [_simple_line(s["carriers"][1], s["seed_lot"])],
            client_command_id=command_id,
        )


@pytest.mark.integration
def test_sow_retry_after_batch_progression_returns_original_event(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    command_id = uuid.uuid4()
    effective_time = _now()
    first = _sow(
        db_session, tenant, user, farm, s["batch"], [_simple_line(s["carriers"][0], s["seed_lot"])],
        client_command_id=command_id, effective_time=effective_time,
    )
    crop_batch_service.transition_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), configured_transition_id=s["transitions"][("SEEDING", "GERMINATION")].id,
        effective_time=_now(), reason=None,
    )
    retry = _sow(
        db_session, tenant, user, farm, s["batch"], [_simple_line(s["carriers"][0], s["seed_lot"])],
        client_command_id=command_id, effective_time=effective_time,
    )
    assert retry.id == first.id
    assert db_session.execute(select(func.count()).select_from(SowingEvent)).scalar_one() == 1


# --- Direct-SQL immutability ---------------------------------------------------------


@pytest.mark.integration
def test_sowing_event_direct_sql_update_and_delete_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    event = _sow(db_session, tenant, user, farm, s["batch"], [_simple_line(s["carriers"][0], s["seed_lot"])])

    with pytest.raises(DBAPIError):
        db_session.execute(text("UPDATE sowing_events SET note = 'x' WHERE id = :id"), {"id": event.id})
        db_session.flush()
    db_session.rollback()

    with pytest.raises(DBAPIError):
        db_session.execute(text("DELETE FROM sowing_events WHERE id = :id"), {"id": event.id})
        db_session.flush()
    db_session.rollback()


@pytest.mark.integration
def test_batch_carrier_assignment_direct_sql_update_and_delete_rejected(
    db_session, active_context_with_farm
) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    _sow(db_session, tenant, user, farm, s["batch"], [_simple_line(s["carriers"][0], s["seed_lot"])])
    assignment = db_session.execute(
        select(BatchCarrierAssignment).where(BatchCarrierAssignment.batch_id == s["batch"].id)
    ).scalar_one()

    with pytest.raises(DBAPIError):
        db_session.execute(
            text("UPDATE batch_carrier_assignments SET released_effective_time = now() WHERE id = :id"),
            {"id": assignment.id},
        )
        db_session.flush()
    db_session.rollback()

    with pytest.raises(DBAPIError):
        db_session.execute(text("DELETE FROM batch_carrier_assignments WHERE id = :id"), {"id": assignment.id})
        db_session.flush()
    db_session.rollback()


@pytest.mark.integration
def test_sowing_event_line_direct_sql_update_and_delete_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    _sow(db_session, tenant, user, farm, s["batch"], [_simple_line(s["carriers"][0], s["seed_lot"])])
    line = db_session.execute(select(SowingEventLine)).scalars().first()

    with pytest.raises(DBAPIError):
        db_session.execute(text("UPDATE sowing_event_lines SET seed_count = 999 WHERE id = :id"), {"id": line.id})
        db_session.flush()
    db_session.rollback()

    with pytest.raises(DBAPIError):
        db_session.execute(text("DELETE FROM sowing_event_lines WHERE id = :id"), {"id": line.id})
        db_session.flush()
    db_session.rollback()


@pytest.mark.integration
def test_batch_carrier_assignment_wrong_carrier_type_rejected_by_direct_sql(
    db_session, active_context_with_farm
) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    event = _sow(db_session, tenant, user, farm, s["batch"], [_simple_line(s["carriers"][0], s["seed_lot"])])
    wrong_type_carrier = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        carrier_type_code="cultivation_plate", code="CP-DIRECT", issued_date=None,
    )
    active_run_id = db_session.execute(
        text("SELECT active_batch_stage_run_id FROM sowing_events WHERE id = :id"), {"id": event.id}
    ).scalar_one()
    with pytest.raises(DBAPIError):
        db_session.execute(
            text(
                "INSERT INTO batch_carrier_assignments (id, tenant_id, farm_id, batch_id, carrier_id, "
                "batch_stage_run_id, assigned_effective_time, opening_sowing_event_id, actor_user_id) "
                "VALUES (:id, :tenant_id, :farm_id, :batch_id, :carrier_id, :run_id, :eff, :event_id, :user_id)"
            ),
            {
                "id": uuid.uuid4(), "tenant_id": tenant.id, "farm_id": farm.id, "batch_id": s["batch"].id,
                "carrier_id": wrong_type_carrier.id, "run_id": active_run_id, "eff": event.effective_time,
                "event_id": event.id, "user_id": user.id,
            },
        )
        db_session.flush()
    db_session.rollback()


# --- Cross-tenant --------------------------------------------------------------------


@pytest.mark.integration
def test_sow_cross_tenant_batch_rejected(db_session, active_context_with_farm) -> None:
    from app.services import farm_service, membership_service, tenant_service, user_service
    from app.services.errors import CropBatchNotFoundError, FarmNotFoundError

    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)

    tenant_b = tenant_service.create_tenant(db_session, code="sowing-tenant-b", name="Tenant B")
    user_b = user_service.create_user(
        db_session, oidc_issuer="iss", oidc_subject="sowing-b", email="sowingb@example.com", display_name="B"
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_b.id, user_id=user_b.id, role_code="tenant_admin", actor_user_id=None
    )
    # Tenant A's own farm is invisible to tenant B — rejected before the
    # batch is ever looked up.
    with pytest.raises(FarmNotFoundError):
        _sow(
            db_session, tenant_b, user_b, farm, s["batch"], [_simple_line(s["carriers"][0], s["seed_lot"])],
        )

    # A farm tenant B genuinely owns still can't see tenant A's batch.
    farm_b = farm_service.create_farm(
        db_session, tenant_id=tenant_b.id, actor_user_id=user_b.id, code="sowing-farm-b", name="Farm B",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    with pytest.raises(CropBatchNotFoundError):
        _sow(
            db_session, tenant_b, user_b, farm_b, s["batch"], [_simple_line(s["carriers"][0], s["seed_lot"])],
        )


# --- API ------------------------------------------------------------------------


@pytest.mark.integration
def test_sowing_api_smoke(client, active_context_with_farm, db_session) -> None:
    tenant, user, headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    db_session.commit()

    resp = client.post(
        f"/farms/{farm.id}/crop-batches/{s['batch'].id}/sowings", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()),
            "effective_time": datetime.now(timezone.utc).isoformat(),
            "lines": [
                {
                    "carrier_id": str(s["carriers"][0].id), "seed_lot_id": str(s["seed_lot"].id),
                    "sown_site_count": 200, "seed_count": 200,
                }
            ],
        },
    )
    assert resp.status_code == 201
    event = resp.json()
    assert len(event["lines"]) == 1
    assert event["lines"][0]["carrier"]["code"] == s["carriers"][0].code

    list_resp = client.get(f"/farms/{farm.id}/crop-batches/{s['batch'].id}/sowings", headers=headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    get_resp = client.get(
        f"/farms/{farm.id}/crop-batches/{s['batch'].id}/sowings/{event['id']}", headers=headers
    )
    assert get_resp.status_code == 200

    carriers_resp = client.get(f"/farms/{farm.id}/crop-batches/{s['batch'].id}/carriers", headers=headers)
    assert carriers_resp.status_code == 200
    assert len(carriers_resp.json()) == 1

    assignment_resp = client.get(
        f"/farms/{farm.id}/carriers/{s['carriers'][0].id}/batch-assignment", headers=headers
    )
    assert assignment_resp.status_code == 200
    assert assignment_resp.json()["batch_id"] == str(s["batch"].id)

    unassigned_resp = client.get(
        f"/farms/{farm.id}/carriers/{s['carriers'][1].id}/batch-assignment", headers=headers
    )
    assert unassigned_resp.status_code == 200
    assert unassigned_resp.json() is None


@pytest.mark.integration
def test_sowing_routes_have_no_mutation_endpoints() -> None:
    from app.main import app

    schema = app.openapi()
    relevant_paths = {
        p: ops for p, ops in schema["paths"].items() if "sowings" in p or "batch-assignment" in p
        or p.endswith("/carriers")
    }
    methods = {method.upper() for ops in relevant_paths.values() for method in ops}
    assert methods <= {"GET", "POST"}
    assert "PUT" not in methods and "PATCH" not in methods and "DELETE" not in methods


@pytest.mark.integration
def test_full_api_has_exactly_eight_seed_and_sowing_routes() -> None:
    from app.main import app

    schema = app.openapi()
    cmp009_ops = [
        (p, method.upper())
        for p, ops in schema["paths"].items()
        for method in ops
        if "seed-lots" in p or "sowings" in p or (p.endswith("/carriers") and "crop-batches" in p)
        or "batch-assignment" in p
    ]
    assert len(cmp009_ops) == 8, cmp009_ops
