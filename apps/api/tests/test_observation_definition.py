import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.schemas.observation_definition import ObservationDefinitionCreate
from app.services import observation_service
from app.services.errors import DuplicateObservationDefinitionCodeError, ObservationDefinitionNotFoundError

# --- Application-level (Pydantic) validation — no DB required ---


def _payload(**overrides):
    defaults = dict(code="TRAY-TEMP", name="Tray Temperature", value_type="decimal", target_scope="either")
    defaults.update(overrides)
    return ObservationDefinitionCreate(**defaults)


def test_definition_code_trimmed_and_uppercased() -> None:
    payload = _payload(code="  tray-temp  ")
    assert payload.code == "TRAY-TEMP"


def test_definition_blank_code_rejected() -> None:
    with pytest.raises(ValueError):
        _payload(code="   ")


def test_definition_blank_name_rejected() -> None:
    with pytest.raises(ValueError):
        _payload(name="   ")


def test_definition_blank_description_and_unit_become_none() -> None:
    payload = _payload(description="   ", unit="  ")
    assert payload.description is None
    assert payload.unit is None


def test_definition_invalid_value_type_rejected() -> None:
    with pytest.raises(ValueError):
        _payload(value_type="float")


def test_definition_invalid_target_scope_rejected() -> None:
    with pytest.raises(ValueError):
        _payload(target_scope="carrier")


def test_definition_min_exceeds_max_rejected() -> None:
    with pytest.raises(ValueError):
        _payload(min_value=Decimal("10"), max_value=Decimal("5"))


def test_definition_boolean_with_bounds_rejected() -> None:
    with pytest.raises(ValueError):
        _payload(value_type="boolean", min_value=Decimal("0"))


def test_definition_text_with_bounds_rejected() -> None:
    with pytest.raises(ValueError):
        _payload(value_type="text", max_value=Decimal("100"))


def test_definition_percentage_min_below_zero_rejected() -> None:
    with pytest.raises(ValueError):
        _payload(value_type="percentage", min_value=Decimal("-5"))


def test_definition_percentage_max_above_hundred_rejected() -> None:
    with pytest.raises(ValueError):
        _payload(value_type="percentage", max_value=Decimal("150"))


def test_definition_percentage_bounds_within_range_accepted() -> None:
    payload = _payload(value_type="percentage", min_value=Decimal("10"), max_value=Decimal("90"))
    assert payload.min_value == Decimal("10")


def test_definition_integer_fractional_min_rejected() -> None:
    with pytest.raises(ValueError):
        _payload(value_type="integer", min_value=Decimal("1.5"))


def test_definition_integer_fractional_max_rejected() -> None:
    with pytest.raises(ValueError):
        _payload(value_type="integer", max_value=Decimal("10.25"))


def test_definition_integer_integral_bounds_accepted() -> None:
    payload = _payload(value_type="integer", min_value=Decimal("0"), max_value=Decimal("100"))
    assert payload.max_value == Decimal("100")


def test_definition_create_rejects_extra_fields() -> None:
    with pytest.raises(ValueError):
        ObservationDefinitionCreate(
            code="X", name="X", value_type="text", target_scope="either", status="active"
        )


# --- Integration (DB) ---------------------------------------------------------


def _register(db_session, tenant, user, **overrides):
    defaults = dict(
        tenant_id=tenant.id, actor_user_id=user.id, code="TRAY-TEMP", name="Tray Temperature",
        description=None, value_type="decimal", unit="C", target_scope="either", min_value=None, max_value=None,
    )
    defaults.update(overrides)
    return observation_service.register_observation_definition(db_session, **defaults)


@pytest.mark.integration
def test_definition_registration_and_read(db_session, active_context) -> None:
    tenant, user, _headers = active_context
    definition = _register(db_session, tenant, user)
    assert definition.status == "active"
    assert definition.created_by_user_id == user.id

    read = observation_service.get_observation_definition(
        db_session, tenant_id=tenant.id, definition_id=definition.id
    )
    assert read.code == "TRAY-TEMP"
    assert read.value_type == "decimal"


@pytest.mark.integration
def test_definition_code_unique_case_insensitive_per_tenant(db_session, active_context) -> None:
    tenant, user, _headers = active_context
    _register(db_session, tenant, user, code="TRAY-TEMP")
    with pytest.raises(DuplicateObservationDefinitionCodeError):
        _register(db_session, tenant, user, code="tray-temp")


@pytest.mark.integration
def test_definition_code_allowed_in_another_tenant(db_session, active_context) -> None:
    from app.services import membership_service, tenant_service, user_service

    tenant, user, _headers = active_context
    _register(db_session, tenant, user, code="TRAY-TEMP")

    tenant_b = tenant_service.create_tenant(db_session, code="obs-def-tenant-b", name="Tenant B")
    user_b = user_service.create_user(
        db_session, oidc_issuer="iss", oidc_subject="obsdef-b", email="obsdefb@example.com", display_name="B"
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_b.id, user_id=user_b.id, role_code="tenant_admin", actor_user_id=None
    )
    definition_b = _register(db_session, tenant_b, user_b, code="TRAY-TEMP")
    assert definition_b.code == "TRAY-TEMP"


@pytest.mark.integration
def test_definition_not_found(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    with pytest.raises(ObservationDefinitionNotFoundError):
        observation_service.get_observation_definition(
            db_session, tenant_id=tenant.id, definition_id=uuid.uuid4()
        )


@pytest.mark.integration
def test_definition_creator_user_id_not_null_at_db_level(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                "INSERT INTO observation_definitions (id, tenant_id, code, name, value_type, target_scope, "
                "status, created_at, updated_at) VALUES "
                "(:id, :tenant_id, 'X', 'X', 'text', 'either', 'active', now(), now())"
            ),
            {"id": uuid.uuid4(), "tenant_id": tenant.id},
        )
    db_session.rollback()


@pytest.mark.integration
def test_definition_status_only_update_permitted_at_db_level(db_session, active_context) -> None:
    from app.models.observation_definition import ObservationDefinition

    tenant, user, _headers = active_context
    definition = _register(db_session, tenant, user)
    db_definition = db_session.get(ObservationDefinition, definition.id)
    db_definition.status = "inactive"
    db_session.flush()  # must not raise
    db_session.refresh(db_definition)
    assert db_definition.status == "inactive"


@pytest.mark.integration
def test_definition_semantic_field_update_rejected_at_db_level(db_session, active_context) -> None:
    tenant, user, _headers = active_context
    definition = _register(db_session, tenant, user)
    with pytest.raises(DBAPIError):
        db_session.execute(
            text("UPDATE observation_definitions SET name = 'Renamed' WHERE id = :id"), {"id": definition.id}
        )
        db_session.flush()
    db_session.rollback()


@pytest.mark.integration
def test_definition_cannot_be_hard_deleted(db_session, active_context) -> None:
    tenant, user, _headers = active_context
    definition = _register(db_session, tenant, user)
    with pytest.raises(DBAPIError):
        db_session.execute(text("DELETE FROM observation_definitions WHERE id = :id"), {"id": definition.id})
        db_session.flush()
    db_session.rollback()


# --- API ------------------------------------------------------------------------


@pytest.mark.integration
def test_definition_api_smoke_and_no_mutation_routes(client, active_context) -> None:
    _tenant, _user, headers = active_context
    create_resp = client.post(
        "/observation-definitions", headers=headers,
        json={"code": "TRAY-TEMP", "name": "Tray Temperature", "value_type": "decimal", "target_scope": "either"},
    )
    assert create_resp.status_code == 201
    definition = create_resp.json()

    get_resp = client.get(f"/observation-definitions/{definition['id']}", headers=headers)
    assert get_resp.status_code == 200

    list_resp = client.get("/observation-definitions", headers=headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    from app.main import app

    schema = app.openapi()
    definition_paths = {p: ops for p, ops in schema["paths"].items() if "observation-definitions" in p}
    methods = {method.upper() for ops in definition_paths.values() for method in ops}
    assert methods == {"GET", "POST"}
    assert len(definition_paths) == 2
