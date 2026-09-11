"""PILOT-BLOCKER-003 F01: GET /inventory-quantity-cohorts/{cohort_id}/
storage-breakdown must establish tenant ownership of `cohort_id` BEFORE
computing any balance/bucket, and must return the same concealed 404 for a
foreign-tenant cohort as for a nonexistent one. Covers both the HTTP route
(`inventory_storage.get_cohort_storage_breakdown`) and the underlying
service (`inventory_storage_service.get_cohort_bucket_breakdown`)."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.services import inventory_storage_service
from app.services.errors import InventoryQuantityCohortNotFoundError
from tests._store_custody_scenario import build_store_bin, receive_cohort
from tests._store_inv_scenario import build_category, build_item, uom_id


@pytest.fixture(autouse=True)
def _enable_dev_auth(monkeypatch):
    """Mirrors `test_store_inv_002b_custody.py`'s own sanctioned
    monkeypatch -- this local `.env` runs with `ENABLE_DEV_AUTH=false`."""
    import app.core.dev_auth as dev_auth_module

    monkeypatch.setattr(dev_auth_module.settings, "enable_dev_auth", True)


def _second_tenant_scenario(db_session):
    from app.services import farm_service, membership_service, tenant_service, user_service

    tenant = tenant_service.create_tenant(db_session, code=f"t-f01-{uuid.uuid4().hex[:8]}", name="Other Tenant")
    user = user_service.create_user(
        db_session, oidc_issuer="https://issuer.example", oidc_subject=f"f01-{uuid.uuid4().hex}",
        email=f"{uuid.uuid4().hex}@example.com", display_name="Other Tenant User",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    farm = farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"other-farm-{uuid.uuid4().hex[:8]}",
        name="Other Farm", country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=user.id)
    return tenant, user, farm, item


@pytest.mark.integration
def test_own_tenant_mixed_buckets_returned(client, db_session, active_context_with_farm) -> None:
    """A: own-tenant cohort, mixed not-put-away + bin balance -- succeeds
    with the correct breakdown."""
    tenant, user, headers, farm = active_context_with_farm
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=user.id)
    cohort_id = receive_cohort(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, item_id=item.id,
        quantity=Decimal("100"),
    )
    bin_ = build_store_bin(db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id)
    inventory_storage_service.record_putaway(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, destination_location_id=bin_.id, quantity=Decimal("40"),
        effective_time=datetime.now(timezone.utc),
    )
    db_session.commit()

    resp = client.get(f"/inventory-quantity-cohorts/{cohort_id}/storage-breakdown", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert Decimal(body["not_put_away_quantity"]) == Decimal("60")
    bucket_labels = {b["location_id"]: Decimal(b["balance"]) for b in body["buckets"]}
    assert bucket_labels[str(bin_.id)] == Decimal("40")


@pytest.mark.integration
def test_foreign_tenant_cohort_concealed_404(client, db_session, active_context_with_farm) -> None:
    """B: Tenant A requests Tenant B's cohort -- 404, no Tenant B balances
    or bin labels leaked."""
    tenant_a, _user_a, headers_a, _farm_a = active_context_with_farm
    tenant_b, user_b, farm_b, item_b = _second_tenant_scenario(db_session)
    cohort_b = receive_cohort(
        db_session, tenant_id=tenant_b.id, farm_id=farm_b.id, actor_user_id=user_b.id, item_id=item_b.id,
        quantity=Decimal("77"),
    )
    bin_b = build_store_bin(db_session, tenant_id=tenant_b.id, farm_id=farm_b.id, actor_user_id=user_b.id)
    inventory_storage_service.record_putaway(
        db_session, tenant_id=tenant_b.id, farm_id=farm_b.id, actor_user_id=user_b.id,
        client_command_id=uuid.uuid4(), cohort_id=cohort_b, destination_location_id=bin_b.id,
        quantity=Decimal("30"),
        effective_time=datetime.now(timezone.utc),
    )
    db_session.commit()

    resp = client.get(f"/inventory-quantity-cohorts/{cohort_b}/storage-breakdown", headers=headers_a)
    assert resp.status_code == 404
    body = resp.json()
    assert body == {"detail": "Cohort not found"}
    raw_text = resp.text
    assert "77" not in raw_text
    assert "30" not in raw_text
    assert bin_b.name not in raw_text


@pytest.mark.integration
def test_nonexistent_cohort_same_concealed_404(client, active_context_with_farm) -> None:
    """C: unknown cohort UUID gets the identical concealed 404 as a foreign
    cohort -- no distinguishable error text."""
    _tenant, _user, headers, _farm = active_context_with_farm
    resp = client.get(f"/inventory-quantity-cohorts/{uuid.uuid4()}/storage-breakdown", headers=headers)
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Cohort not found"}


@pytest.mark.integration
def test_service_level_ownership_enforced_before_balance_read(db_session, active_context_with_farm) -> None:
    """Service-level guarantee behind A/B/C: `get_cohort_bucket_breakdown`
    itself raises for a cohort_id/tenant_id pair that isn't real ownership,
    never falling through to balance computation -- covers both a foreign
    tenant and a nonexistent cohort with the same exception type."""
    tenant_a, user_a, _headers_a, farm_a = active_context_with_farm
    tenant_b, user_b, farm_b, item_b = _second_tenant_scenario(db_session)
    cohort_b = receive_cohort(
        db_session, tenant_id=tenant_b.id, farm_id=farm_b.id, actor_user_id=user_b.id, item_id=item_b.id,
        quantity=Decimal("5"),
    )
    db_session.commit()

    with pytest.raises(InventoryQuantityCohortNotFoundError):
        inventory_storage_service.get_cohort_bucket_breakdown(db_session, tenant_id=tenant_a.id, cohort_id=cohort_b)

    with pytest.raises(InventoryQuantityCohortNotFoundError):
        inventory_storage_service.get_cohort_bucket_breakdown(db_session, tenant_id=tenant_a.id, cohort_id=uuid.uuid4())
