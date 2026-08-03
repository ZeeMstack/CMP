import pytest

from app.schemas.production_system import ProductionSystemCreate
from app.services import production_system_service, tenant_service
from app.services.errors import DuplicateProductionSystemCodeError

# --- Application-level (Pydantic) validation — no DB required ---


def test_production_system_code_trimmed_and_uppercased() -> None:
    payload = ProductionSystemCreate(code="  nursery-tray  ", name="Nursery Seed Tray")
    assert payload.code == "NURSERY-TRAY"


def test_production_system_blank_code_rejected() -> None:
    with pytest.raises(ValueError):
        ProductionSystemCreate(code=" ", name="Nursery Seed Tray")


# --- Integration (DB) ---


def _register(db_session, tenant, **overrides):
    defaults = dict(
        tenant_id=tenant.id,
        actor_user_id=None,
        code="NURSERY-TRAY",
        name="Nursery Seed Tray",
        description=None,
    )
    defaults.update(overrides)
    return production_system_service.register_production_system(db_session, **defaults)


@pytest.mark.integration
def test_production_system_creation(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    ps = _register(db_session, tenant)
    assert ps.status == "active"
    assert ps.code == "NURSERY-TRAY"


@pytest.mark.integration
def test_production_system_tenant_scoped_uniqueness(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    _register(db_session, tenant)
    with pytest.raises(DuplicateProductionSystemCodeError):
        _register(db_session, tenant, code="nursery-tray")


@pytest.mark.integration
def test_same_production_system_code_allowed_in_different_tenants(db_session, active_context) -> None:
    tenant_a, _user, _headers = active_context
    tenant_b = tenant_service.create_tenant(db_session, code="ps-tenant-b", name="Tenant B")
    ps_a = _register(db_session, tenant_a)
    ps_b = _register(db_session, tenant_b)
    assert ps_a.code == ps_b.code
    assert ps_a.tenant_id != ps_b.tenant_id


@pytest.mark.integration
def test_production_system_inactive_status_readable(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    ps = _register(db_session, tenant)
    ps.status = "inactive"
    db_session.flush()
    fetched = production_system_service.get_production_system(
        db_session, tenant_id=tenant.id, production_system_id=ps.id
    )
    assert fetched.status == "inactive"


@pytest.mark.integration
def test_create_production_system_via_api(client, active_context) -> None:
    tenant, _user, headers = active_context
    response = client.post(
        "/production-systems", headers=headers, json={"code": "leafy-plate", "name": "Leafy Cultivation Plate"}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["tenant_id"] == str(tenant.id)
    assert body["code"] == "LEAFY-PLATE"
