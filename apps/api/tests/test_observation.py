import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.models.audit_event import AuditEvent
from app.models.observation_event import ObservationEvent
from app.models.observation_value import ObservationValue
from app.schemas.observation_event import ObservationEventCreate, ObservationValueIn
from app.services import (
    carrier_service,
    crop_batch_service,
    crop_service,
    observation_service,
    production_system_service,
    sowing_service,
    workflow_service,
)
from app.services.errors import (
    ObservationCommandReusedWithDifferentPayloadError,
    ObservationValidationError,
)
from tests.conftest import ensure_seed_tray_specification

# --- Application-level (Pydantic) validation — no DB required ---


def test_value_exactly_one_typed_field_required() -> None:
    with pytest.raises(ValueError):
        ObservationValueIn(observation_definition_id=uuid.uuid4())
    with pytest.raises(ValueError):
        ObservationValueIn(observation_definition_id=uuid.uuid4(), value_integer=1, value_text="x")


def test_value_blank_text_rejected() -> None:
    with pytest.raises(ValueError):
        ObservationValueIn(observation_definition_id=uuid.uuid4(), value_text="   ")


def test_value_boolean_strict_rejects_integer_coercion() -> None:
    with pytest.raises(ValueError):
        ObservationValueIn(observation_definition_id=uuid.uuid4(), value_boolean=1)


def _value(**overrides):
    defaults = dict(observation_definition_id=uuid.uuid4(), value_text="ok")
    defaults.update(overrides)
    return ObservationValueIn(**defaults)


def test_event_duplicate_definition_target_rejected() -> None:
    definition_id = uuid.uuid4()
    with pytest.raises(ValueError):
        ObservationEventCreate(
            client_command_id=uuid.uuid4(), effective_time=datetime.now(timezone.utc),
            values=[_value(observation_definition_id=definition_id), _value(observation_definition_id=definition_id)],
        )


def test_event_requires_at_least_one_entry() -> None:
    with pytest.raises(ValueError):
        ObservationEventCreate(client_command_id=uuid.uuid4(), effective_time=datetime.now(timezone.utc))


def test_event_naive_effective_time_rejected() -> None:
    with pytest.raises(ValueError):
        ObservationEventCreate(
            client_command_id=uuid.uuid4(), effective_time=datetime.now(), values=[_value()]
        )


def test_event_rejects_extra_fields() -> None:
    with pytest.raises(ValueError):
        ObservationEventCreate(
            client_command_id=uuid.uuid4(), effective_time=datetime.now(timezone.utc), values=[_value()],
            batch_id=uuid.uuid4(),
        )


def test_event_more_than_500_combined_entries_rejected() -> None:
    with pytest.raises(ValueError):
        ObservationEventCreate(
            client_command_id=uuid.uuid4(), effective_time=datetime.now(timezone.utc),
            values=[_value(observation_definition_id=uuid.uuid4()) for _ in range(501)],
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
        expected_duration_minutes=None, permitted_location_type_code=None,
        required_carrier_type_code="seed_tray", is_start=True, is_terminal=False,
    )
    germination = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="GERMINATION", name="Germination", display_order=1, stage_category="germination",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=False,
    )
    complete = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="COMPLETE", name="Complete", display_order=2, stage_category="completed",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=True,
    )
    t1 = workflow_service.add_transition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=seeding.id, to_stage_id=germination.id, code="ADVANCE-1", name="Advance 1",
    )
    t2 = workflow_service.add_transition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=germination.id, to_stage_id=complete.id, code="ADVANCE-2", name="Advance 2",
    )
    workflow_service.publish_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id
    )
    batch = crop_batch_service.create_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"BATCH-{suffix}", workflow_id=workflow.id, effective_time=_now(),
    )
    seed_lot = sowing_service.register_seed_lot(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id,
        variety_id=variety.id, code=f"LOT-{suffix}", supplier_name=None, supplier_lot_reference=None,
        received_date=None, expiry_date=None,
    )
    seed_tray_spec = ensure_seed_tray_specification(db_session, tenant_id=tenant.id, actor_user_id=user.id)
    carriers = [
        carrier_service.register_carrier(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            specification_id=seed_tray_spec.id, code=f"ST-{suffix}-{n:04d}", issued_date=None,
        )
        for n in range(1, 5)
    ]
    sowing_event = sowing_service.sow_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
        lines=[
            {
                "carrier_id": c.id, "seed_lot_id": seed_lot.id, "sown_site_count": 200, "seed_count": 200,
                "line_note": None,
            }
            for c in carriers
        ],
    )
    assignments = sowing_service.list_batch_carriers(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id
    )
    assignment_by_carrier_code = {a.carrier.code: a.id for a in assignments}
    return {
        "crop": crop, "variety": variety, "workflow": workflow, "stages": {"SEEDING": seeding, "GERMINATION": germination, "COMPLETE": complete},
        "transitions": {"t1": t1, "t2": t2}, "batch": batch, "seed_lot": seed_lot, "carriers": carriers,
        "sowing_event": sowing_event, "assignment_ids": [assignment_by_carrier_code[c.code] for c in carriers],
    }


def _register_definition(db_session, tenant, user, **overrides):
    defaults = dict(
        tenant_id=tenant.id, actor_user_id=user.id, code=f"DEF-{uuid.uuid4().hex[:8]}", name="A metric",
        description=None, value_type="decimal", unit=None, target_scope="either", min_value=None, max_value=None,
    )
    defaults.update(overrides)
    return observation_service.register_observation_definition(db_session, **defaults)


def _record(db_session, tenant, user, farm, batch, values=None, germination_checks=None, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
    )
    defaults.update(overrides)
    return observation_service.record_observation(
        db_session, values=values or [], germination_checks=germination_checks or [], **defaults
    )


# --- Core behavior --------------------------------------------------------------


@pytest.mark.integration
def test_batch_level_observation_succeeds(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    definition = _register_definition(db_session, tenant, user, value_type="decimal", target_scope="crop_batch")
    event = _record(
        db_session, tenant, user, farm, s["batch"],
        values=[{"observation_definition_id": definition.id, "value_decimal": Decimal("21.5")}],
    )
    assert db_session.execute(select(func.count()).select_from(ObservationValue)).scalar_one() == 1
    audit_count = db_session.execute(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "crop_batch.observation_recorded")
    ).scalar_one()
    assert audit_count == 1
    assert event.batch_id == s["batch"].id


@pytest.mark.integration
def test_assignment_level_observation_succeeds(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    definition = _register_definition(
        db_session, tenant, user, value_type="integer", target_scope="carrier_assignment"
    )
    _record(
        db_session, tenant, user, farm, s["batch"],
        values=[
            {
                "observation_definition_id": definition.id, "batch_carrier_assignment_id": s["assignment_ids"][0],
                "value_integer": 5,
            }
        ],
    )
    assert db_session.execute(select(func.count()).select_from(ObservationValue)).scalar_one() == 1


@pytest.mark.integration
def test_either_scope_permits_batch_and_assignment_targets(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    definition = _register_definition(db_session, tenant, user, value_type="text", target_scope="either")
    _record(
        db_session, tenant, user, farm, s["batch"],
        values=[
            {"observation_definition_id": definition.id, "value_text": "batch note"},
            {
                "observation_definition_id": definition.id, "batch_carrier_assignment_id": s["assignment_ids"][0],
                "value_text": "carrier note",
            },
        ],
    )
    assert db_session.execute(select(func.count()).select_from(ObservationValue)).scalar_one() == 2


@pytest.mark.integration
def test_crop_batch_scope_with_assignment_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    definition = _register_definition(db_session, tenant, user, value_type="text", target_scope="crop_batch")
    with pytest.raises(ObservationValidationError):
        _record(
            db_session, tenant, user, farm, s["batch"],
            values=[
                {
                    "observation_definition_id": definition.id,
                    "batch_carrier_assignment_id": s["assignment_ids"][0], "value_text": "x",
                }
            ],
        )


@pytest.mark.integration
def test_carrier_assignment_scope_without_assignment_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    definition = _register_definition(
        db_session, tenant, user, value_type="text", target_scope="carrier_assignment"
    )
    with pytest.raises(ObservationValidationError):
        _record(
            db_session, tenant, user, farm, s["batch"],
            values=[{"observation_definition_id": definition.id, "value_text": "x"}],
        )


@pytest.mark.integration
def test_inactive_definition_rejected(db_session, active_context_with_farm) -> None:
    from app.models.observation_definition import ObservationDefinition

    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    definition = _register_definition(db_session, tenant, user, value_type="text", target_scope="either")
    db_session.get(ObservationDefinition, definition.id).status = "inactive"
    db_session.flush()
    with pytest.raises(ObservationValidationError):
        _record(
            db_session, tenant, user, farm, s["batch"],
            values=[{"observation_definition_id": definition.id, "value_text": "x"}],
        )


@pytest.mark.integration
def test_typed_value_mismatch_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    definition = _register_definition(db_session, tenant, user, value_type="integer", target_scope="either")
    with pytest.raises(ObservationValidationError):
        _record(
            db_session, tenant, user, farm, s["batch"],
            values=[{"observation_definition_id": definition.id, "value_text": "5"}],
        )


@pytest.mark.integration
def test_numeric_value_below_minimum_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    definition = _register_definition(
        db_session, tenant, user, value_type="integer", target_scope="either", min_value=Decimal("0"),
        max_value=Decimal("10"),
    )
    with pytest.raises(ObservationValidationError):
        _record(
            db_session, tenant, user, farm, s["batch"],
            values=[{"observation_definition_id": definition.id, "value_integer": -1}],
        )


@pytest.mark.integration
def test_numeric_value_above_maximum_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    definition = _register_definition(
        db_session, tenant, user, value_type="integer", target_scope="either", min_value=Decimal("0"),
        max_value=Decimal("10"),
    )
    with pytest.raises(ObservationValidationError):
        _record(
            db_session, tenant, user, farm, s["batch"],
            values=[{"observation_definition_id": definition.id, "value_integer": 11}],
        )


@pytest.mark.integration
def test_percentage_value_out_of_hard_range_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    definition = _register_definition(db_session, tenant, user, value_type="percentage", target_scope="either")
    with pytest.raises(ObservationValidationError):
        _record(
            db_session, tenant, user, farm, s["batch"],
            values=[{"observation_definition_id": definition.id, "value_decimal": Decimal("150")}],
        )


@pytest.mark.integration
def test_assignment_from_another_batch_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s1 = _build_scenario(db_session, tenant, user, farm)
    s2 = _build_scenario(db_session, tenant, user, farm)
    definition = _register_definition(
        db_session, tenant, user, value_type="text", target_scope="carrier_assignment"
    )
    with pytest.raises(ObservationValidationError):
        _record(
            db_session, tenant, user, farm, s1["batch"],
            values=[
                {
                    "observation_definition_id": definition.id, "batch_carrier_assignment_id": s2["assignment_ids"][0],
                    "value_text": "x",
                }
            ],
        )


@pytest.mark.integration
def test_effective_time_before_assignment_assigned_time_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    definition = _register_definition(
        db_session, tenant, user, value_type="text", target_scope="carrier_assignment"
    )
    with pytest.raises(Exception):
        _record(
            db_session, tenant, user, farm, s["batch"],
            values=[
                {
                    "observation_definition_id": definition.id, "batch_carrier_assignment_id": s["assignment_ids"][0],
                    "value_text": "x",
                }
            ],
            effective_time=s["sowing_event"].effective_time - timedelta(days=1),
        )


@pytest.mark.integration
def test_future_effective_time_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    definition = _register_definition(db_session, tenant, user, value_type="text", target_scope="crop_batch")
    with pytest.raises(Exception):
        _record(
            db_session, tenant, user, farm, s["batch"],
            values=[{"observation_definition_id": definition.id, "value_text": "x"}],
            effective_time=_now() + timedelta(hours=1),
        )


@pytest.mark.integration
def test_duplicate_definition_target_rejected_by_db(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    definition = _register_definition(db_session, tenant, user, value_type="text", target_scope="crop_batch")
    event = _record(
        db_session, tenant, user, farm, s["batch"],
        values=[{"observation_definition_id": definition.id, "value_text": "first"}],
    )
    with pytest.raises(DBAPIError):
        db_session.execute(
            text(
                "INSERT INTO observation_values (id, tenant_id, farm_id, observation_event_id, "
                "observation_definition_id, value_text, recorded_at) VALUES "
                "(:id, :tenant_id, :farm_id, :event_id, :def_id, 'second', now())"
            ),
            {
                "id": uuid.uuid4(), "tenant_id": tenant.id, "farm_id": farm.id, "event_id": event.id,
                "def_id": definition.id,
            },
        )
        db_session.flush()
    db_session.rollback()


# --- Idempotency --------------------------------------------------------------------


@pytest.mark.integration
def test_exact_observation_retry_returns_original_event(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    definition = _register_definition(db_session, tenant, user, value_type="text", target_scope="crop_batch")
    command_id = uuid.uuid4()
    effective_time = _now()
    first = _record(
        db_session, tenant, user, farm, s["batch"],
        values=[{"observation_definition_id": definition.id, "value_text": "ok"}],
        client_command_id=command_id, effective_time=effective_time,
    )
    second = _record(
        db_session, tenant, user, farm, s["batch"],
        values=[{"observation_definition_id": definition.id, "value_text": "ok"}],
        client_command_id=command_id, effective_time=effective_time,
    )
    assert first.id == second.id
    assert db_session.execute(select(func.count()).select_from(ObservationEvent)).scalar_one() == 1


@pytest.mark.integration
def test_reused_command_id_different_payload_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    definition = _register_definition(db_session, tenant, user, value_type="text", target_scope="crop_batch")
    command_id = uuid.uuid4()
    _record(
        db_session, tenant, user, farm, s["batch"],
        values=[{"observation_definition_id": definition.id, "value_text": "ok"}], client_command_id=command_id,
    )
    with pytest.raises(ObservationCommandReusedWithDifferentPayloadError):
        _record(
            db_session, tenant, user, farm, s["batch"],
            values=[{"observation_definition_id": definition.id, "value_text": "different"}],
            client_command_id=command_id,
        )


@pytest.mark.integration
def test_retry_after_stage_progression_returns_original_event(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    definition = _register_definition(db_session, tenant, user, value_type="text", target_scope="crop_batch")
    command_id = uuid.uuid4()
    effective_time = _now()
    first = _record(
        db_session, tenant, user, farm, s["batch"],
        values=[{"observation_definition_id": definition.id, "value_text": "ok"}],
        client_command_id=command_id, effective_time=effective_time,
    )
    crop_batch_service.transition_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), configured_transition_id=s["transitions"]["t1"].id,
        effective_time=_now(), reason=None,
    )
    retry = _record(
        db_session, tenant, user, farm, s["batch"],
        values=[{"observation_definition_id": definition.id, "value_text": "ok"}],
        client_command_id=command_id, effective_time=effective_time,
    )
    assert retry.id == first.id
    assert db_session.execute(select(func.count()).select_from(ObservationEvent)).scalar_one() == 1


@pytest.mark.integration
def test_retry_after_definition_deactivated_returns_original_event(db_session, active_context_with_farm) -> None:
    from app.models.observation_definition import ObservationDefinition

    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    definition = _register_definition(db_session, tenant, user, value_type="text", target_scope="crop_batch")
    command_id = uuid.uuid4()
    effective_time = _now()
    first = _record(
        db_session, tenant, user, farm, s["batch"],
        values=[{"observation_definition_id": definition.id, "value_text": "ok"}],
        client_command_id=command_id, effective_time=effective_time,
    )
    db_session.get(ObservationDefinition, definition.id).status = "inactive"
    db_session.flush()
    retry = _record(
        db_session, tenant, user, farm, s["batch"],
        values=[{"observation_definition_id": definition.id, "value_text": "ok"}],
        client_command_id=command_id, effective_time=effective_time,
    )
    assert retry.id == first.id


# --- Direct-SQL immutability ---------------------------------------------------------


@pytest.mark.integration
def test_observation_event_direct_sql_update_and_delete_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    definition = _register_definition(db_session, tenant, user, value_type="text", target_scope="crop_batch")
    event = _record(
        db_session, tenant, user, farm, s["batch"],
        values=[{"observation_definition_id": definition.id, "value_text": "ok"}],
    )

    with pytest.raises(DBAPIError):
        db_session.execute(text("UPDATE observation_events SET note = 'x' WHERE id = :id"), {"id": event.id})
        db_session.flush()
    db_session.rollback()

    with pytest.raises(DBAPIError):
        db_session.execute(text("DELETE FROM observation_events WHERE id = :id"), {"id": event.id})
        db_session.flush()
    db_session.rollback()


@pytest.mark.integration
def test_observation_value_direct_sql_update_and_delete_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    definition = _register_definition(db_session, tenant, user, value_type="text", target_scope="crop_batch")
    _record(
        db_session, tenant, user, farm, s["batch"],
        values=[{"observation_definition_id": definition.id, "value_text": "ok"}],
    )
    value = db_session.execute(select(ObservationValue)).scalars().first()

    with pytest.raises(DBAPIError):
        db_session.execute(
            text("UPDATE observation_values SET value_text = 'changed' WHERE id = :id"), {"id": value.id}
        )
        db_session.flush()
    db_session.rollback()

    with pytest.raises(DBAPIError):
        db_session.execute(text("DELETE FROM observation_values WHERE id = :id"), {"id": value.id})
        db_session.flush()
    db_session.rollback()


# --- Cross-tenant --------------------------------------------------------------------


@pytest.mark.integration
def test_cross_tenant_observation_rejected(db_session, active_context_with_farm) -> None:
    from app.services import membership_service, tenant_service, user_service
    from app.services.errors import FarmNotFoundError

    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    definition = _register_definition(db_session, tenant, user, value_type="text", target_scope="crop_batch")

    tenant_b = tenant_service.create_tenant(db_session, code="obs-tenant-b", name="Tenant B")
    user_b = user_service.create_user(
        db_session, oidc_issuer="iss", oidc_subject="obs-b", email="obsb@example.com", display_name="B"
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_b.id, user_id=user_b.id, role_code="tenant_admin", actor_user_id=None
    )
    with pytest.raises(FarmNotFoundError):
        _record(
            db_session, tenant_b, user_b, farm, s["batch"],
            values=[{"observation_definition_id": definition.id, "value_text": "x"}],
        )


# --- API ------------------------------------------------------------------------


@pytest.mark.integration
def test_observation_api_smoke(client, active_context_with_farm, db_session) -> None:
    tenant, user, headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    definition = _register_definition(db_session, tenant, user, value_type="decimal", target_scope="crop_batch")
    db_session.commit()

    resp = client.post(
        f"/farms/{farm.id}/crop-batches/{s['batch'].id}/observations", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": datetime.now(timezone.utc).isoformat(),
            "values": [{"observation_definition_id": str(definition.id), "value_decimal": "21.5"}],
        },
    )
    assert resp.status_code == 201
    event = resp.json()
    assert len(event["values"]) == 1

    list_resp = client.get(f"/farms/{farm.id}/crop-batches/{s['batch'].id}/observations", headers=headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    get_resp = client.get(
        f"/farms/{farm.id}/crop-batches/{s['batch'].id}/observations/{event['id']}", headers=headers
    )
    assert get_resp.status_code == 200
