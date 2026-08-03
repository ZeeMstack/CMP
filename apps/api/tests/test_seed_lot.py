import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.schemas.seed_lot import SeedLotCreate
from app.services import crop_service, sowing_service
from app.services.errors import (
    CropNotFoundError,
    DuplicateSeedLotCodeError,
    FarmNotFoundError,
    SeedLotNotFoundError,
    SeedLotValidationError,
    VarietyNotFoundError,
)

# --- Application-level (Pydantic) validation — no DB required ---


def test_seed_lot_code_trimmed_and_uppercased() -> None:
    payload = SeedLotCreate(crop_id=uuid.uuid4(), variety_id=uuid.uuid4(), code="  lot-001  ")
    assert payload.code == "LOT-001"


def test_seed_lot_blank_code_rejected() -> None:
    with pytest.raises(ValueError):
        SeedLotCreate(crop_id=uuid.uuid4(), variety_id=uuid.uuid4(), code="   ")


def test_seed_lot_blank_supplier_fields_become_none() -> None:
    payload = SeedLotCreate(
        crop_id=uuid.uuid4(), variety_id=uuid.uuid4(), code="LOT-001",
        supplier_name="  ", supplier_lot_reference="   ",
    )
    assert payload.supplier_name is None
    assert payload.supplier_lot_reference is None


def test_seed_lot_supplier_fields_trimmed() -> None:
    payload = SeedLotCreate(
        crop_id=uuid.uuid4(), variety_id=uuid.uuid4(), code="LOT-001",
        supplier_name="  Acme Seeds  ", supplier_lot_reference="  REF-1  ",
    )
    assert payload.supplier_name == "Acme Seeds"
    assert payload.supplier_lot_reference == "REF-1"


def test_seed_lot_expiry_before_received_rejected_by_schema() -> None:
    with pytest.raises(ValueError):
        SeedLotCreate(
            crop_id=uuid.uuid4(), variety_id=uuid.uuid4(), code="LOT-001",
            received_date=date(2026, 6, 1), expiry_date=date(2026, 5, 1),
        )


def test_seed_lot_create_rejects_extra_fields() -> None:
    with pytest.raises(ValueError):
        SeedLotCreate(crop_id=uuid.uuid4(), variety_id=uuid.uuid4(), code="LOT-001", status="active")


# --- Integration (DB) ---------------------------------------------------------


def _register(db_session, tenant, user, farm, crop, variety, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id, variety_id=variety.id,
        code="LOT-0001", supplier_name=None, supplier_lot_reference=None, received_date=None, expiry_date=None,
    )
    defaults.update(overrides)
    return sowing_service.register_seed_lot(db_session, **defaults)


def _crop_and_variety(db_session, tenant, *, suffix=""):
    crop = crop_service.register_crop(
        db_session, tenant_id=tenant.id, actor_user_id=None, code=f"ICE{suffix}", common_name="Iceberg",
        scientific_name=None, crop_category="leafy_green",
    )
    variety = crop_service.register_variety(
        db_session, tenant_id=tenant.id, actor_user_id=None, crop_id=crop.id, code=f"MAM{suffix}",
        name="Mamutik RZ", supplier_reference=None,
    )
    return crop, variety


@pytest.mark.integration
def test_seed_lot_registration_and_read(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    crop, variety = _crop_and_variety(db_session, tenant)
    lot = _register(db_session, tenant, user, farm, crop, variety, code="LOT-0001")
    assert lot.code == "LOT-0001"
    assert lot.status == "active"
    assert lot.created_by_user_id == user.id

    read = sowing_service.get_seed_lot(db_session, tenant_id=tenant.id, farm_id=farm.id, seed_lot_id=lot.id)
    assert read.crop.id == crop.id
    assert read.variety.id == variety.id


@pytest.mark.integration
def test_seed_lot_code_unique_case_insensitive_per_tenant(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    crop, variety = _crop_and_variety(db_session, tenant)
    _register(db_session, tenant, user, farm, crop, variety, code="LOT-0001")
    with pytest.raises(DuplicateSeedLotCodeError):
        _register(db_session, tenant, user, farm, crop, variety, code="lot-0001")


@pytest.mark.integration
def test_seed_lot_code_allowed_in_another_tenant(db_session, active_context_with_farm) -> None:
    from app.services import farm_service, membership_service, tenant_service, user_service

    tenant, user, _headers, farm = active_context_with_farm
    crop, variety = _crop_and_variety(db_session, tenant)
    _register(db_session, tenant, user, farm, crop, variety, code="LOT-0001")

    tenant_b = tenant_service.create_tenant(db_session, code="seed-lot-tenant-b", name="Tenant B")
    user_b = user_service.create_user(
        db_session, oidc_issuer="iss", oidc_subject="seedlot-b", email="seedlotb@example.com", display_name="B"
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_b.id, user_id=user_b.id, role_code="tenant_admin", actor_user_id=None
    )
    farm_b = farm_service.create_farm(
        db_session, tenant_id=tenant_b.id, actor_user_id=user_b.id, code="farm-b", name="Farm B",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    crop_b, variety_b = _crop_and_variety(db_session, tenant_b)
    lot_b = _register(db_session, tenant_b, user_b, farm_b, crop_b, variety_b, code="LOT-0001")
    assert lot_b.code == "LOT-0001"


@pytest.mark.integration
def test_seed_lot_crop_not_found_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _crop, variety = _crop_and_variety(db_session, tenant)
    with pytest.raises(CropNotFoundError):
        _register(db_session, tenant, user, farm, type("X", (), {"id": uuid.uuid4()})(), variety)


@pytest.mark.integration
def test_seed_lot_variety_crop_mismatch_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    crop_a, _variety_a = _crop_and_variety(db_session, tenant, suffix="A")
    _crop_b, variety_b = _crop_and_variety(db_session, tenant, suffix="B")
    with pytest.raises(VarietyNotFoundError):
        _register(db_session, tenant, user, farm, crop_a, variety_b)


@pytest.mark.integration
def test_seed_lot_inactive_farm_rejected(db_session, active_context_with_farm) -> None:
    from app.models.farm import Farm

    tenant, user, _headers, farm = active_context_with_farm
    crop, variety = _crop_and_variety(db_session, tenant)
    db_farm = db_session.get(Farm, farm.id)
    db_farm.status = "inactive"
    db_session.flush()
    with pytest.raises(FarmNotFoundError):
        _register(db_session, tenant, user, farm, crop, variety)


@pytest.mark.integration
def test_seed_lot_expiry_before_received_rejected_by_service(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    crop, variety = _crop_and_variety(db_session, tenant)
    with pytest.raises(SeedLotValidationError):
        _register(
            db_session, tenant, user, farm, crop, variety,
            received_date=date(2026, 6, 1), expiry_date=date(2026, 5, 1),
        )


@pytest.mark.integration
def test_seed_lot_creator_user_id_not_null_at_db_level(db_session, active_context_with_farm) -> None:
    tenant, _user, _headers, farm = active_context_with_farm
    crop, variety = _crop_and_variety(db_session, tenant)
    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                "INSERT INTO seed_lots (id, tenant_id, farm_id, crop_id, variety_id, code, status, "
                "created_at, updated_at) VALUES "
                "(:id, :tenant_id, :farm_id, :crop_id, :variety_id, 'LOT-NULL', 'active', now(), now())"
            ),
            {
                "id": uuid.uuid4(), "tenant_id": tenant.id, "farm_id": farm.id, "crop_id": crop.id,
                "variety_id": variety.id,
            },
        )
    db_session.rollback()


@pytest.mark.integration
def test_seed_lot_cannot_be_hard_deleted(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    crop, variety = _crop_and_variety(db_session, tenant)
    lot = _register(db_session, tenant, user, farm, crop, variety)
    with pytest.raises(DBAPIError):
        db_session.execute(text("DELETE FROM seed_lots WHERE id = :id"), {"id": lot.id})
        db_session.flush()
    db_session.rollback()


@pytest.mark.integration
def test_seed_lot_not_found(db_session, active_context_with_farm) -> None:
    tenant, _user, _headers, farm = active_context_with_farm
    with pytest.raises(SeedLotNotFoundError):
        sowing_service.get_seed_lot(db_session, tenant_id=tenant.id, farm_id=farm.id, seed_lot_id=uuid.uuid4())


# --- API ------------------------------------------------------------------------


@pytest.mark.integration
def test_seed_lot_api_smoke_and_cross_tenant_rejected(client, active_context_with_farm, db_session) -> None:
    tenant, _user, headers, farm = active_context_with_farm
    crop, variety = _crop_and_variety(db_session, tenant)
    db_session.commit()

    create_resp = client.post(
        f"/farms/{farm.id}/seed-lots", headers=headers,
        json={"crop_id": str(crop.id), "variety_id": str(variety.id), "code": "LOT-0001"},
    )
    assert create_resp.status_code == 201
    lot = create_resp.json()

    get_resp = client.get(f"/farms/{farm.id}/seed-lots/{lot['id']}", headers=headers)
    assert get_resp.status_code == 200

    list_resp = client.get(f"/farms/{farm.id}/seed-lots", headers=headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    from app.services import membership_service, tenant_service, user_service

    tenant_b = tenant_service.create_tenant(db_session, code="seed-lot-api-tenant-b", name="Tenant B")
    user_b = user_service.create_user(
        db_session, oidc_issuer="iss", oidc_subject="seedlot-api-b", email="seedlotapib@example.com",
        display_name="B",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_b.id, user_id=user_b.id, role_code="tenant_admin", actor_user_id=None
    )
    headers_b = {"X-Dev-Tenant-Id": str(tenant_b.id), "X-Dev-User-Id": str(user_b.id)}
    cross_resp = client.get(f"/farms/{farm.id}/seed-lots/{lot['id']}", headers=headers_b)
    assert cross_resp.status_code == 404


@pytest.mark.integration
def test_seed_lot_routes_have_no_mutation_endpoints() -> None:
    from app.main import app

    schema = app.openapi()
    seed_lot_paths = {p: ops for p, ops in schema["paths"].items() if "seed-lots" in p}
    methods = {method.upper() for ops in seed_lot_paths.values() for method in ops}
    assert methods == {"GET", "POST"}
    assert len(seed_lot_paths) == 2
