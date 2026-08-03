import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.schemas.crop import VarietyCreate
from app.services import crop_service, tenant_service
from app.services.errors import CropNotFoundError, DuplicateVarietyCodeError, VarietyNotFoundError

# --- Application-level (Pydantic) validation — no DB required ---


def test_variety_code_trimmed_and_uppercased() -> None:
    payload = VarietyCreate(code="  mam-rz  ", name="Mamutik RZ")
    assert payload.code == "MAM-RZ"


def test_variety_blank_code_rejected() -> None:
    with pytest.raises(ValueError):
        VarietyCreate(code="  ", name="Mamutik RZ")


# --- Integration (DB) ---


def _register_crop(db_session, tenant, **overrides):
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


def _register_variety(db_session, tenant, crop, **overrides):
    defaults = dict(
        tenant_id=tenant.id,
        actor_user_id=None,
        crop_id=crop.id,
        code="MAM",
        name="Mamutik RZ",
        supplier_reference=None,
    )
    defaults.update(overrides)
    return crop_service.register_variety(db_session, **defaults)


@pytest.mark.integration
def test_variety_creation(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _register_crop(db_session, tenant)
    variety = _register_variety(db_session, tenant, crop)
    assert variety.crop_id == crop.id
    assert variety.status == "active"


@pytest.mark.integration
def test_duplicate_variety_code_rejected_within_one_crop(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _register_crop(db_session, tenant)
    _register_variety(db_session, tenant, crop, code="MAM")
    with pytest.raises(DuplicateVarietyCodeError):
        _register_variety(db_session, tenant, crop, code="mam")


@pytest.mark.integration
def test_same_variety_code_allowed_under_another_crop(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop_a = _register_crop(db_session, tenant, code="LET")
    crop_b = _register_crop(db_session, tenant, code="TOM")
    variety_a = _register_variety(db_session, tenant, crop_a, code="V1")
    variety_b = _register_variety(db_session, tenant, crop_b, code="V1")
    assert variety_a.code == variety_b.code
    assert variety_a.crop_id != variety_b.crop_id


@pytest.mark.integration
def test_variety_same_tenant_enforcement(db_session, active_context) -> None:
    tenant_a, _user, _headers = active_context
    tenant_b = tenant_service.create_tenant(db_session, code="variety-tenant-b", name="Tenant B")
    crop = _register_crop(db_session, tenant_a)
    variety = _register_variety(db_session, tenant_a, crop)
    with pytest.raises(CropNotFoundError):
        crop_service.get_variety(db_session, tenant_id=tenant_b.id, crop_id=crop.id, variety_id=variety.id)


@pytest.mark.integration
def test_variety_cannot_be_accessed_through_another_tenant(db_session, active_context) -> None:
    tenant_a, _user, _headers = active_context
    tenant_b = tenant_service.create_tenant(db_session, code="variety-tenant-c", name="Tenant C")
    crop_b = _register_crop(db_session, tenant_b, code="LET")
    crop = _register_crop(db_session, tenant_a)
    variety = _register_variety(db_session, tenant_a, crop)
    with pytest.raises(VarietyNotFoundError):
        crop_service.get_variety(db_session, tenant_id=tenant_b.id, crop_id=crop_b.id, variety_id=variety.id)


@pytest.mark.integration
def test_variety_cross_tenant_crop_reference_rejected_by_postgres(db_session, active_context) -> None:
    tenant_a, _user, _headers = active_context
    tenant_b = tenant_service.create_tenant(db_session, code="variety-tenant-d", name="Tenant D")
    crop = _register_crop(db_session, tenant_a)
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO varieties (id, tenant_id, crop_id, code, name) "
                    "VALUES (:id, :tenant_id, :crop_id, 'BAD', 'Bad')"
                ),
                {"id": uuid.uuid4(), "tenant_id": tenant_b.id, "crop_id": crop.id},
            )


@pytest.mark.integration
def test_create_variety_via_api(client, active_context) -> None:
    tenant, _user, headers = active_context
    crop_resp = client.post(
        "/crops", headers=headers, json={"code": "let", "common_name": "Lettuce", "crop_category": "leafy_green"}
    )
    crop_id = crop_resp.json()["id"]
    response = client.post(
        f"/crops/{crop_id}/varieties", headers=headers, json={"code": "mam", "name": "Mamutik RZ"}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["crop_id"] == crop_id
    assert body["code"] == "MAM"
