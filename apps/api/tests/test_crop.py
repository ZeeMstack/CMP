import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.schemas.crop import CropCreate
from app.services import crop_service, tenant_service
from app.services.errors import CropNotFoundError, DuplicateCropCodeError

# --- Application-level (Pydantic) validation — no DB required ---


def test_crop_code_trimmed_and_uppercased() -> None:
    payload = CropCreate(code="  let-01  ", common_name="Lettuce", crop_category="leafy_green")
    assert payload.code == "LET-01"


def test_crop_blank_code_rejected() -> None:
    with pytest.raises(ValueError):
        CropCreate(code="   ", common_name="Lettuce", crop_category="leafy_green")


def test_invalid_crop_category_rejected() -> None:
    with pytest.raises(ValueError):
        CropCreate(code="LET", common_name="Lettuce", crop_category="nursery_only")


# --- Integration (DB) ---


def _register(db_session, tenant, **overrides):
    defaults = dict(
        tenant_id=tenant.id,
        actor_user_id=None,
        code="LET",
        common_name="Iceberg Lettuce",
        scientific_name=None,
        crop_category="leafy_green",
    )
    defaults.update(overrides)
    return crop_service.register_crop(db_session, **defaults)


@pytest.mark.integration
def test_crop_registration(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _register(db_session, tenant)
    assert crop.status == "active"
    assert crop.code == "LET"


@pytest.mark.integration
def test_crop_tenant_scoped_case_insensitive_uniqueness(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    _register(db_session, tenant, code="LET")
    with pytest.raises(DuplicateCropCodeError):
        _register(db_session, tenant, code="let")


@pytest.mark.integration
def test_same_crop_code_allowed_in_different_tenants(db_session, active_context) -> None:
    tenant_a, _user, _headers = active_context
    tenant_b = tenant_service.create_tenant(db_session, code="crop-tenant-b", name="Tenant B")
    crop_a = _register(db_session, tenant_a, code="LET")
    crop_b = _register(db_session, tenant_b, code="LET")
    assert crop_a.code == crop_b.code
    assert crop_a.tenant_id != crop_b.tenant_id


@pytest.mark.integration
def test_cross_tenant_crop_lookup_rejected(db_session, active_context) -> None:
    tenant_a, _user, _headers = active_context
    tenant_b = tenant_service.create_tenant(db_session, code="crop-tenant-c", name="Tenant C")
    crop = _register(db_session, tenant_a)
    with pytest.raises(CropNotFoundError):
        crop_service.get_crop(db_session, tenant_id=tenant_b.id, crop_id=crop.id)


@pytest.mark.integration
def test_crop_inactive_status_readable(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _register(db_session, tenant)
    crop.status = "inactive"
    db_session.flush()
    fetched = crop_service.get_crop(db_session, tenant_id=tenant.id, crop_id=crop.id)
    assert fetched.status == "inactive"


@pytest.mark.integration
def test_invalid_crop_status_rejected_by_postgres(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO crops (id, tenant_id, code, common_name, crop_category, status) "
                    "VALUES (:id, :tenant_id, 'BAD', 'Bad', 'leafy_green', 'bogus')"
                ),
                {"id": uuid.uuid4(), "tenant_id": tenant.id},
            )


@pytest.mark.integration
def test_failed_crop_registration_leaves_no_audit_event(db_session, active_context) -> None:
    from sqlalchemy import func, select

    from app.models.audit_event import AuditEvent

    tenant, _user, _headers = active_context
    _register(db_session, tenant, code="LET")
    with pytest.raises(DuplicateCropCodeError):
        _register(db_session, tenant, code="let")
    count = db_session.execute(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "crop.registered")
    ).scalar_one()
    assert count == 1


@pytest.mark.integration
def test_create_crop_via_api(client, active_context) -> None:
    tenant, _user, headers = active_context
    response = client.post(
        "/crops",
        headers=headers,
        json={"code": "tom", "common_name": "Tomato", "crop_category": "vine"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["tenant_id"] == str(tenant.id)
    assert body["code"] == "TOM"


@pytest.mark.integration
def test_unknown_crop_id_returns_404(client, active_context) -> None:
    _tenant, _user, headers = active_context
    response = client.get(f"/crops/{uuid.uuid4()}", headers=headers)
    assert response.status_code == 404
