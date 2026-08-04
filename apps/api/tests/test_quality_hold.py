import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.schemas.quality_hold import QualityHoldCreate, QualityHoldReleaseCreate
from app.services import (
    crop_batch_service,
    crop_service,
    observation_service,
    production_system_service,
    quality_hold_service,
    workflow_service,
)
from app.services.errors import (
    InvalidQualityHoldEffectiveTimeError,
    ObservationEventNotFoundError,
    QualityHoldAlreadyReleasedError,
    QualityHoldCommandReusedWithDifferentPayloadError,
    QualityHoldNotFoundError,
    QualityHoldValidationError,
)

# --- Application-level (Pydantic) validation — no DB required ---


def test_hold_reason_code_trimmed_and_uppercased() -> None:
    payload = QualityHoldCreate(
        client_command_id=uuid.uuid4(), effective_time=datetime.now(timezone.utc),
        reason_code="  low-germination  ", reason_text="Below threshold",
    )
    assert payload.reason_code == "LOW-GERMINATION"


def test_hold_blank_reason_code_rejected() -> None:
    with pytest.raises(ValueError):
        QualityHoldCreate(
            client_command_id=uuid.uuid4(), effective_time=datetime.now(timezone.utc), reason_code="   ",
            reason_text="x",
        )


def test_hold_blank_reason_text_rejected() -> None:
    with pytest.raises(ValueError):
        QualityHoldCreate(
            client_command_id=uuid.uuid4(), effective_time=datetime.now(timezone.utc), reason_code="X",
            reason_text="   ",
        )


def test_hold_naive_effective_time_rejected() -> None:
    with pytest.raises(ValueError):
        QualityHoldCreate(
            client_command_id=uuid.uuid4(), effective_time=datetime.now(), reason_code="X", reason_text="x",
        )


def test_hold_create_rejects_extra_fields() -> None:
    with pytest.raises(ValueError):
        QualityHoldCreate(
            client_command_id=uuid.uuid4(), effective_time=datetime.now(timezone.utc), reason_code="X",
            reason_text="x", severity="blocking",
        )


def test_release_blank_reason_rejected() -> None:
    with pytest.raises(ValueError):
        QualityHoldReleaseCreate(
            client_command_id=uuid.uuid4(), effective_time=datetime.now(timezone.utc), release_reason="   "
        )


# --- Integration helpers ----------------------------------------------------------


def _now():
    return datetime.now(timezone.utc)


def _build_scenario(db_session, tenant, user, farm, *, suffix=None):
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
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=True, is_terminal=False,
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
    batch = crop_batch_service.create_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"BATCH-{suffix}", workflow_id=workflow.id, effective_time=_now(),
    )
    return {"batch": batch}


def _place(db_session, tenant, user, farm, batch, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=_now(), source_observation_event_id=None,
        reason_code="LOW-GERMINATION", reason_text="Germination below threshold",
    )
    defaults.update(overrides)
    return quality_hold_service.place_quality_hold(db_session, **defaults)


def _release(db_session, tenant, user, farm, batch, hold_id, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id, hold_id=hold_id,
        client_command_id=uuid.uuid4(), effective_time=_now(), release_reason="Reinspected and passed",
    )
    defaults.update(overrides)
    return quality_hold_service.release_quality_hold(db_session, **defaults)


def _register_definition(db_session, tenant, user):
    return observation_service.register_observation_definition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"DEF-{uuid.uuid4().hex[:8]}",
        name="A metric", description=None, value_type="text", unit=None, target_scope="crop_batch",
        min_value=None, max_value=None,
    )


def _record_observation(db_session, tenant, user, farm, batch, definition, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
        values=[{"observation_definition_id": definition.id, "value_text": "ok"}], germination_checks=[],
    )
    defaults.update(overrides)
    return observation_service.record_observation(db_session, **defaults)


# --- Core behavior --------------------------------------------------------------


@pytest.mark.integration
def test_place_hold_and_read(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    hold = _place(db_session, tenant, user, farm, s["batch"])
    read = quality_hold_service.get_quality_hold(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=s["batch"].id, hold_id=hold.id
    )
    assert read.is_open is True
    assert read.release is None
    assert read.reason_code == "LOW-GERMINATION"


@pytest.mark.integration
def test_place_hold_with_source_observation(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    definition = _register_definition(db_session, tenant, user)
    observation = _record_observation(db_session, tenant, user, farm, s["batch"], definition)
    hold = _place(db_session, tenant, user, farm, s["batch"], source_observation_event_id=observation.id)
    assert hold.source_observation_event_id == observation.id


@pytest.mark.integration
def test_place_hold_source_observation_from_another_batch_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s1 = _build_scenario(db_session, tenant, user, farm)
    s2 = _build_scenario(db_session, tenant, user, farm)
    definition = _register_definition(db_session, tenant, user)
    observation = _record_observation(db_session, tenant, user, farm, s2["batch"], definition)
    with pytest.raises(ObservationEventNotFoundError):
        _place(db_session, tenant, user, farm, s1["batch"], source_observation_event_id=observation.id)


@pytest.mark.integration
def test_place_hold_source_observation_after_hold_effective_time_rejected(
    db_session, active_context_with_farm
) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    definition = _register_definition(db_session, tenant, user)
    observation = _record_observation(db_session, tenant, user, farm, s["batch"], definition, effective_time=_now())
    # A moment strictly after batch creation but strictly before the
    # observation's own effective time — always <= now() since it is
    # earlier than the (already-valid, non-future) observation time.
    hold_time = s["batch"].created_effective_time + (
        observation.effective_time - s["batch"].created_effective_time
    ) / 2
    with pytest.raises(QualityHoldValidationError):
        _place(
            db_session, tenant, user, farm, s["batch"], source_observation_event_id=observation.id,
            effective_time=hold_time,
        )


@pytest.mark.integration
def test_multiple_simultaneous_open_holds_permitted(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    hold_a = _place(db_session, tenant, user, farm, s["batch"], reason_code="REASON-A")
    hold_b = _place(db_session, tenant, user, farm, s["batch"], reason_code="REASON-B")
    holds = quality_hold_service.list_quality_holds(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=s["batch"].id
    )
    assert {h.id for h in holds} == {hold_a.id, hold_b.id}
    assert all(h.is_open for h in holds)


@pytest.mark.integration
def test_release_hold_and_read(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    hold = _place(db_session, tenant, user, farm, s["batch"])
    _release(db_session, tenant, user, farm, s["batch"], hold.id)
    read = quality_hold_service.get_quality_hold(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=s["batch"].id, hold_id=hold.id
    )
    assert read.is_open is False
    assert read.release is not None


@pytest.mark.integration
def test_one_release_per_hold_enforced(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    hold = _place(db_session, tenant, user, farm, s["batch"])
    _release(db_session, tenant, user, farm, s["batch"], hold.id)
    with pytest.raises(QualityHoldAlreadyReleasedError):
        _release(db_session, tenant, user, farm, s["batch"], hold.id)


@pytest.mark.integration
def test_release_effective_time_before_hold_effective_time_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    hold_time = _now()
    hold = _place(db_session, tenant, user, farm, s["batch"], effective_time=hold_time)
    with pytest.raises(InvalidQualityHoldEffectiveTimeError):
        _release(db_session, tenant, user, farm, s["batch"], hold.id, effective_time=hold_time - timedelta(hours=1))


@pytest.mark.integration
def test_release_future_effective_time_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    hold = _place(db_session, tenant, user, farm, s["batch"])
    with pytest.raises(InvalidQualityHoldEffectiveTimeError):
        _release(db_session, tenant, user, farm, s["batch"], hold.id, effective_time=_now() + timedelta(hours=1))


@pytest.mark.integration
def test_hold_not_found(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    with pytest.raises(QualityHoldNotFoundError):
        _release(db_session, tenant, user, farm, s["batch"], uuid.uuid4())


# --- Idempotency --------------------------------------------------------------------


@pytest.mark.integration
def test_exact_hold_retry_returns_original_hold(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    command_id = uuid.uuid4()
    effective_time = _now()
    first = _place(db_session, tenant, user, farm, s["batch"], client_command_id=command_id, effective_time=effective_time)
    second = _place(db_session, tenant, user, farm, s["batch"], client_command_id=command_id, effective_time=effective_time)
    assert first.id == second.id


@pytest.mark.integration
def test_hold_reused_command_id_different_payload_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    command_id = uuid.uuid4()
    _place(db_session, tenant, user, farm, s["batch"], client_command_id=command_id, reason_code="A")
    with pytest.raises(QualityHoldCommandReusedWithDifferentPayloadError):
        _place(db_session, tenant, user, farm, s["batch"], client_command_id=command_id, reason_code="B")


@pytest.mark.integration
def test_exact_release_retry_returns_original_release(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    hold = _place(db_session, tenant, user, farm, s["batch"])
    command_id = uuid.uuid4()
    effective_time = _now()
    first = _release(db_session, tenant, user, farm, s["batch"], hold.id, client_command_id=command_id, effective_time=effective_time)
    second = _release(db_session, tenant, user, farm, s["batch"], hold.id, client_command_id=command_id, effective_time=effective_time)
    assert first.id == second.id


@pytest.mark.integration
def test_release_reused_command_id_different_payload_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    hold = _place(db_session, tenant, user, farm, s["batch"])
    command_id = uuid.uuid4()
    _release(db_session, tenant, user, farm, s["batch"], hold.id, client_command_id=command_id, release_reason="A")
    with pytest.raises(QualityHoldCommandReusedWithDifferentPayloadError):
        _release(db_session, tenant, user, farm, s["batch"], hold.id, client_command_id=command_id, release_reason="B")


# --- Direct-SQL immutability ---------------------------------------------------------


@pytest.mark.integration
def test_quality_hold_direct_sql_update_and_delete_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    hold = _place(db_session, tenant, user, farm, s["batch"])

    with pytest.raises(DBAPIError):
        db_session.execute(text("UPDATE quality_holds SET reason_text = 'x' WHERE id = :id"), {"id": hold.id})
        db_session.flush()
    db_session.rollback()

    with pytest.raises(DBAPIError):
        db_session.execute(text("DELETE FROM quality_holds WHERE id = :id"), {"id": hold.id})
        db_session.flush()
    db_session.rollback()


@pytest.mark.integration
def test_quality_hold_release_direct_sql_update_and_delete_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    hold = _place(db_session, tenant, user, farm, s["batch"])
    release = _release(db_session, tenant, user, farm, s["batch"], hold.id)

    with pytest.raises(DBAPIError):
        db_session.execute(
            text("UPDATE quality_hold_releases SET release_reason = 'x' WHERE id = :id"), {"id": release.id}
        )
        db_session.flush()
    db_session.rollback()

    with pytest.raises(DBAPIError):
        db_session.execute(text("DELETE FROM quality_hold_releases WHERE id = :id"), {"id": release.id})
        db_session.flush()
    db_session.rollback()


# --- Cross-tenant --------------------------------------------------------------------


@pytest.mark.integration
def test_cross_tenant_hold_rejected(db_session, active_context_with_farm) -> None:
    from app.services import membership_service, tenant_service, user_service
    from app.services.errors import FarmNotFoundError

    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)

    tenant_b = tenant_service.create_tenant(db_session, code="hold-tenant-b", name="Tenant B")
    user_b = user_service.create_user(
        db_session, oidc_issuer="iss", oidc_subject="hold-b", email="holdb@example.com", display_name="B"
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_b.id, user_id=user_b.id, role_code="tenant_admin", actor_user_id=None
    )
    with pytest.raises(FarmNotFoundError):
        _place(db_session, tenant_b, user_b, farm, s["batch"])


# --- API ------------------------------------------------------------------------


@pytest.mark.integration
def test_quality_hold_api_smoke(client, active_context_with_farm, db_session) -> None:
    tenant, user, headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    db_session.commit()

    resp = client.post(
        f"/farms/{farm.id}/crop-batches/{s['batch'].id}/quality-holds", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": datetime.now(timezone.utc).isoformat(),
            "reason_code": "low-germination", "reason_text": "Germination below threshold",
        },
    )
    assert resp.status_code == 201
    hold = resp.json()
    assert hold["is_open"] is True

    list_resp = client.get(f"/farms/{farm.id}/crop-batches/{s['batch'].id}/quality-holds", headers=headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    release_resp = client.post(
        f"/farms/{farm.id}/crop-batches/{s['batch'].id}/quality-holds/{hold['id']}/release", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": datetime.now(timezone.utc).isoformat(),
            "release_reason": "Reinspected and passed",
        },
    )
    assert release_resp.status_code == 201
    assert release_resp.json()["is_open"] is False


@pytest.mark.integration
def test_quality_hold_routes_have_no_mutation_endpoints() -> None:
    from app.main import app

    schema = app.openapi()
    hold_paths = {p: ops for p, ops in schema["paths"].items() if "quality-holds" in p}
    methods = {method.upper() for ops in hold_paths.values() for method in ops}
    assert methods == {"GET", "POST"}


@pytest.mark.integration
def test_full_api_has_exactly_ten_cmp010_operations() -> None:
    from app.main import app

    schema = app.openapi()
    cmp010_ops = [
        (p, method.upper())
        for p, ops in schema["paths"].items()
        for method in ops
        if "observation-definitions" in p or "/observations" in p or "quality-holds" in p
    ]
    assert len(cmp010_ops) == 10, cmp010_ops
