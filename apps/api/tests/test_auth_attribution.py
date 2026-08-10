"""AUTH-001A end-to-end regression: an authenticated/tenant-context request
that writes through an existing backend route must attribute
`audit_events.actor_user_id` to the resolved CMP user -- for both the
dev-header path (TenantContext propagation) and the bearer-token path
(bearer identity resolves to the same CMP user UUID as attribution).
Also re-proves that tenant isolation (cross-tenant 404) still holds once a
real `TenantContext` -- not `DevTenantContext` -- is the thing granting
access, using the farms route as the representative example."""

import pytest
from sqlalchemy import select

from app.models.audit_event import AuditEvent
from app.services import farm_service, membership_service, tenant_service, user_service
from tests._oidc_test_support import TEST_ISSUER, configured_oidc, mint_token  # noqa: F401


@pytest.mark.integration
def test_dev_path_write_attributes_audit_event_to_context_user(client, db_session, active_context) -> None:
    tenant, user, headers = active_context
    response = client.post(
        "/farms",
        headers=headers,
        json={"code": "attr-dev-01", "name": "Attribution Dev Farm", "country_code": "AE", "timezone": "Asia/Dubai"},
    )
    assert response.status_code == 201
    farm_id = response.json()["id"]

    event = db_session.execute(
        select(AuditEvent).where(AuditEvent.action == "farm.created", AuditEvent.entity_id == farm_id)
    ).scalar_one()
    assert event.actor_user_id == user.id
    assert event.tenant_id == tenant.id


@pytest.mark.integration
def test_bearer_path_write_attributes_audit_event_to_resolved_cmp_user(client, db_session, configured_oidc) -> None:
    subject = "bearer-attribution-subject"
    user = user_service.create_user(
        db_session, oidc_issuer=TEST_ISSUER, oidc_subject=subject, email="attr@example.com", display_name="Attr User"
    )
    tenant = tenant_service.create_tenant(db_session, code="t-attr-bearer", name="Attribution Bearer Tenant")
    membership_service.add_membership(
        db_session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    db_session.commit()

    token = mint_token(subject=subject)
    response = client.post(
        "/farms",
        headers={"Authorization": f"Bearer {token}", "X-CMP-Tenant-Id": str(tenant.id)},
        json={"code": "attr-bearer-01", "name": "Attribution Bearer Farm", "country_code": "AE", "timezone": "Asia/Dubai"},
    )
    assert response.status_code == 201
    farm_id = response.json()["id"]

    event = db_session.execute(
        select(AuditEvent).where(AuditEvent.action == "farm.created", AuditEvent.entity_id == farm_id)
    ).scalar_one()
    # The bearer-resolved identity must produce the exact same CMP user UUID
    # that a dev-path TenantContext would have -- not a placeholder, not the
    # tenant id, not anything derived from the token/claims directly.
    assert event.actor_user_id == user.id
    assert event.tenant_id == tenant.id


@pytest.mark.integration
def test_bearer_and_dev_path_produce_identical_actor_attribution_shape(client, db_session, configured_oidc) -> None:
    """Both trust paths must converge on the same CMP user identity concept
    -- not just 'some UUID', but literally the same row -- when the same
    person authenticates through either mechanism against memberships they
    actually hold."""
    subject = "dual-path-subject"
    user = user_service.create_user(
        db_session, oidc_issuer=TEST_ISSUER, oidc_subject=subject, email="dual@example.com", display_name="Dual User"
    )
    tenant = tenant_service.create_tenant(db_session, code="t-attr-dual", name="Dual Path Tenant")
    membership_service.add_membership(
        db_session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    db_session.commit()

    dev_headers = {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(user.id)}
    dev_response = client.post(
        "/farms",
        headers=dev_headers,
        json={"code": "attr-dual-dev", "name": "Dual Dev Farm", "country_code": "AE", "timezone": "Asia/Dubai"},
    )
    assert dev_response.status_code == 201

    bearer_headers = {"Authorization": f"Bearer {mint_token(subject=subject)}", "X-CMP-Tenant-Id": str(tenant.id)}
    bearer_response = client.post(
        "/farms",
        headers=bearer_headers,
        json={"code": "attr-dual-bearer", "name": "Dual Bearer Farm", "country_code": "AE", "timezone": "Asia/Dubai"},
    )
    assert bearer_response.status_code == 201

    dev_event = db_session.execute(
        select(AuditEvent).where(AuditEvent.action == "farm.created", AuditEvent.entity_id == dev_response.json()["id"])
    ).scalar_one()
    bearer_event = db_session.execute(
        select(AuditEvent).where(
            AuditEvent.action == "farm.created", AuditEvent.entity_id == bearer_response.json()["id"]
        )
    ).scalar_one()
    assert dev_event.actor_user_id == bearer_event.actor_user_id == user.id


@pytest.mark.integration
def test_cross_tenant_farm_lookup_still_404s_under_bearer_tenant_context(client, db_session, configured_oidc) -> None:
    other_tenant = tenant_service.create_tenant(db_session, code="t-attr-other", name="Other Tenant")
    other_farm = farm_service.create_farm(
        db_session,
        tenant_id=other_tenant.id,
        actor_user_id=None,
        code="other-farm-01",
        name="Other Farm",
        country_code="AE",
        city_region=None,
        timezone="Asia/Dubai",
    )

    subject = "isolation-check-subject"
    user = user_service.create_user(
        db_session, oidc_issuer=TEST_ISSUER, oidc_subject=subject, email="iso@example.com", display_name="Iso User"
    )
    own_tenant = tenant_service.create_tenant(db_session, code="t-attr-own", name="Own Tenant")
    membership_service.add_membership(
        db_session, tenant_id=own_tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    db_session.commit()

    response = client.get(
        f"/farms/{other_farm.id}",
        headers={"Authorization": f"Bearer {mint_token(subject=subject)}", "X-CMP-Tenant-Id": str(own_tenant.id)},
    )
    assert response.status_code == 404
