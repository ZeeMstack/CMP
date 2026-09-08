"""STORE-INV-003: HTTP-level permission enforcement and tenant isolation
for the new Reservation/Issue routes -- mirrors
`test_store_inv_002a2_quality_http.py`'s own approach: a granted role
succeeds, a zero/wrong-permission role is denied with zero side effects,
and a cross-tenant read resolves to 404, never leaking existence."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models.inventory_reservation import InventoryReservation
from app.services import farm_service, membership_service, tenant_service, user_service
from tests._store_reservation_scenario import build_scenario, receive_and_putaway

def _now():
    return datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _enable_dev_auth(monkeypatch):
    import app.core.dev_auth as dev_auth_module

    monkeypatch.setattr(dev_auth_module.settings, "enable_dev_auth", True)


def _membership_headers(db_session, *, tenant_id, role_code: str) -> tuple[object, dict[str, str]]:
    user = user_service.create_user(
        db_session, oidc_issuer="https://issuer.example", oidc_subject=f"r-{uuid.uuid4().hex}",
        email=f"{uuid.uuid4().hex}@example.com", display_name="Reservation HTTP Test User",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_id, user_id=user.id, role_code=role_code, actor_user_id=None
    )
    return user, {"X-Dev-Tenant-Id": str(tenant_id), "X-Dev-User-Id": str(user.id)}


@pytest.mark.integration
def test_storekeeper_can_reserve_and_issue_qc_officer_cannot(client, db_session, test_engine) -> None:
    scenario = build_scenario(test_engine)
    cohort_id, bin_id = receive_and_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("20"),
    )
    db_session.commit()

    _storekeeper, storekeeper_headers = _membership_headers(
        db_session, tenant_id=scenario["tenant_id"], role_code="storekeeper"
    )
    _qc, qc_headers = _membership_headers(db_session, tenant_id=scenario["tenant_id"], role_code="qc_officer")
    db_session.commit()

    before_count = db_session.execute(select(func.count()).select_from(InventoryReservation)).scalar_one()
    denied = client.post(
        f"/farms/{scenario['farm_id']}/inventory-reservations",
        json={
            "client_command_id": str(uuid.uuid4()), "purpose": "QC attempt", "effective_time": _now().isoformat(),
            "lines": [{"inventory_item_id": str(scenario["item_id"]), "quantity": "5"}],
        },
        headers=qc_headers,
    )
    assert denied.status_code == 403
    after_count = db_session.execute(select(func.count()).select_from(InventoryReservation)).scalar_one()
    assert after_count == before_count

    allowed = client.post(
        f"/farms/{scenario['farm_id']}/inventory-reservations",
        json={
            "client_command_id": str(uuid.uuid4()), "purpose": "Storekeeper reservation",
            "effective_time": _now().isoformat(),
            "lines": [{"inventory_item_id": str(scenario["item_id"]), "quantity": "5"}],
        },
        headers=storekeeper_headers,
    )
    assert allowed.status_code == 201
    reservation_id = allowed.json()["id"]

    issue_denied = client.post(
        f"/farms/{scenario['farm_id']}/inventory-issues",
        json={
            "client_command_id": str(uuid.uuid4()), "purpose": "QC issue attempt", "effective_time": _now().isoformat(),
            "lines": [
                {
                    "inventory_item_id": str(scenario["item_id"]), "inventory_quantity_cohort_id": str(cohort_id),
                    "source_location_id": str(bin_id), "quantity": "1",
                }
            ],
        },
        headers=qc_headers,
    )
    assert issue_denied.status_code == 403

    issue_allowed = client.post(
        f"/farms/{scenario['farm_id']}/inventory-issues",
        json={
            "client_command_id": str(uuid.uuid4()), "purpose": "Storekeeper issue", "effective_time": _now().isoformat(),
            "lines": [
                {
                    "inventory_item_id": str(scenario["item_id"]), "inventory_quantity_cohort_id": str(cohort_id),
                    "source_location_id": str(bin_id), "quantity": "1",
                }
            ],
        },
        headers=storekeeper_headers,
    )
    assert issue_allowed.status_code == 201

    # cross-tenant read: a second tenant's storekeeper must never see this
    # reservation -- 404, never a generic 403 leaking existence.
    other_tenant = tenant_service.create_tenant(db_session, code=f"t-other-{uuid.uuid4().hex[:8]}", name="Other Tenant")
    _other_farm = farm_service.create_farm(
        db_session, tenant_id=other_tenant.id, actor_user_id=None, code="other-farm", name="Other Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    _other_user, other_headers = _membership_headers(db_session, tenant_id=other_tenant.id, role_code="storekeeper")
    db_session.commit()

    cross_tenant_read = client.get(f"/inventory-reservations/{reservation_id}", headers=other_headers)
    assert cross_tenant_read.status_code == 404

    own_tenant_read = client.get(f"/inventory-reservations/{reservation_id}", headers=storekeeper_headers)
    assert own_tenant_read.status_code == 200
    assert own_tenant_read.json()["id"] == reservation_id
