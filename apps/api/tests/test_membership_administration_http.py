"""AUTHZ-OPS-001 focused HTTP-level tests for the Users & Roles
administration MVP (ticket section 28). Deliberately a small, high-value
set -- not an exhaustive matrix -- covering: authorized listing/role
assignment, denial for a role without TENANT_MEMBERS_*, cross-tenant
isolation, last-active-Tenant-Admin protection (deactivate and role
change), reactivation, and audit-event emission. Mirrors the fixture/
header conventions already established by
`tests/test_authz_mutation_enforcement_http.py`.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.audit_event import AuditEvent
from app.models.membership import TenantMembership
from app.services import membership_service, tenant_service, user_service


def _membership_headers(db_session, *, tenant_id, role_code: str) -> dict[str, str]:
    user = user_service.create_user(
        db_session,
        oidc_issuer="https://issuer.example",
        oidc_subject=f"memtest-{uuid.uuid4().hex}",
        email=f"{uuid.uuid4().hex}@example.com",
        display_name="Membership Test User",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_id, user_id=user.id, role_code=role_code, actor_user_id=None
    )
    return {"X-Dev-Tenant-Id": str(tenant_id), "X-Dev-User-Id": str(user.id)}


def _new_tenant(db_session, *, code_prefix: str):
    return tenant_service.create_tenant(
        db_session, code=f"t-{code_prefix}-{uuid.uuid4().hex[:8]}", name="Membership Admin Tenant"
    )


@pytest.mark.integration
def test_tenant_admin_can_list_memberships_with_friendly_fields(client, active_context_with_farm) -> None:
    tenant, admin_user, headers, _farm = active_context_with_farm

    response = client.get("/memberships", headers=headers)
    assert response.status_code == 200
    rows = response.json()
    assert any(r["user_id"] == str(admin_user.id) and r["role_code"] == "tenant_admin" for r in rows)
    # Friendly display fields present -- no need for the frontend to
    # separately fetch the User to render a row.
    admin_row = next(r for r in rows if r["user_id"] == str(admin_user.id))
    assert admin_row["user_email"] == admin_user.email
    assert admin_row["user_display_name"] == admin_user.display_name
    assert admin_row["status"] == "active"


@pytest.mark.integration
def test_tenant_admin_can_assign_an_approved_role(client, db_session, active_context_with_farm) -> None:
    tenant, _admin_user, headers, _farm = active_context_with_farm
    target_user = user_service.create_user(
        db_session,
        oidc_issuer="https://issuer.example",
        oidc_subject=f"assign-{uuid.uuid4().hex}",
        email="assignee@example.com",
        display_name="Assignee",
    )

    response = client.post(
        "/memberships", json={"user_id": str(target_user.id), "role_code": "operator"}, headers=headers
    )
    assert response.status_code == 201
    assert response.json()["role_code"] == "operator"

    roles_response = client.get("/memberships/roles", headers=headers)
    assert roles_response.status_code == 200
    codes = {r["code"] for r in roles_response.json()}
    assert "operator" in codes
    assert "tenant_admin" in codes
    for role in roles_response.json():
        assert role["description"]  # every role has a non-empty human description


@pytest.mark.integration
def test_role_without_membership_permission_is_forbidden(client, db_session) -> None:
    tenant = _new_tenant(db_session, code_prefix="deny")
    headers = _membership_headers(db_session, tenant_id=tenant.id, role_code="operator")

    assert client.get("/memberships", headers=headers).status_code == 403
    assert client.get("/memberships/roles", headers=headers).status_code == 403
    assert (
        client.post("/memberships", json={"user_id": str(uuid.uuid4()), "role_code": "operator"}, headers=headers).status_code
        == 403
    )


@pytest.mark.integration
def test_cross_tenant_membership_mutation_is_rejected(client, db_session, active_context_with_farm) -> None:
    """A tenant_admin of Tenant A must not be able to read or mutate a
    membership that belongs to Tenant B -- proven as a 404 (concealment),
    never a 403 (which would confirm the row exists)."""
    _tenant_a, _admin_user, headers_a, _farm = active_context_with_farm

    tenant_b = _new_tenant(db_session, code_prefix="xten")
    other_user = user_service.create_user(
        db_session,
        oidc_issuer="https://issuer.example",
        oidc_subject=f"xten-{uuid.uuid4().hex}",
        email="xten@example.com",
        display_name="Cross Tenant User",
    )
    membership_b = membership_service.add_membership(
        db_session, tenant_id=tenant_b.id, user_id=other_user.id, role_code="operator", actor_user_id=None
    )

    role_response = client.post(
        f"/memberships/{membership_b.id}/role", json={"role_code": "qc_officer"}, headers=headers_a
    )
    assert role_response.status_code == 404

    deactivate_response = client.post(f"/memberships/{membership_b.id}/deactivate", headers=headers_a)
    assert deactivate_response.status_code == 404

    # And it never appears in Tenant A's own membership list.
    list_response = client.get("/memberships", headers=headers_a)
    assert all(r["user_id"] != str(other_user.id) for r in list_response.json())


@pytest.mark.integration
def test_last_active_tenant_admin_cannot_be_deactivated(client, active_context_with_farm) -> None:
    tenant, admin_user, headers, _farm = active_context_with_farm
    # Resolve the admin's own membership id via the list endpoint rather
    # than reaching back into the service layer with a second session.
    rows = client.get("/memberships", headers=headers).json()
    admin_row = next(r for r in rows if r["user_id"] == str(admin_user.id))

    response = client.post(f"/memberships/{admin_row['id']}/deactivate", headers=headers)
    assert response.status_code == 409
    assert "last active Tenant Admin" in response.json()["detail"]


@pytest.mark.integration
def test_last_active_tenant_admin_cannot_be_demoted(client, active_context_with_farm) -> None:
    tenant, admin_user, headers, _farm = active_context_with_farm
    rows = client.get("/memberships", headers=headers).json()
    admin_row = next(r for r in rows if r["user_id"] == str(admin_user.id))

    response = client.post(
        f"/memberships/{admin_row['id']}/role", json={"role_code": "operator"}, headers=headers
    )
    assert response.status_code == 409
    assert "last active Tenant Admin" in response.json()["detail"]


@pytest.mark.integration
def test_second_admin_allows_first_to_be_deactivated_and_reactivated(
    client, db_session, active_context_with_farm
) -> None:
    """With TWO active tenant_admins, deactivating one is allowed (proves
    the protection is about the LAST admin, not admins in general), and
    the same historical membership row is reused on reactivation."""
    tenant, admin_user, headers, _farm = active_context_with_farm
    second_admin = user_service.create_user(
        db_session,
        oidc_issuer="https://issuer.example",
        oidc_subject=f"admin2-{uuid.uuid4().hex}",
        email="admin2@example.com",
        display_name="Second Admin",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant.id, user_id=second_admin.id, role_code="tenant_admin", actor_user_id=None
    )

    rows = client.get("/memberships", headers=headers).json()
    admin_row = next(r for r in rows if r["user_id"] == str(admin_user.id))

    deactivate_response = client.post(f"/memberships/{admin_row['id']}/deactivate", headers=headers)
    assert deactivate_response.status_code == 200
    assert deactivate_response.json()["status"] == "removed"

    # Reactivate using the second admin's session, since the first admin's
    # own dev-auth membership is currently removed (it can no longer make
    # authenticated requests itself).
    second_headers = {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(second_admin.id)}
    reactivate_response = client.post(f"/memberships/{admin_row['id']}/reactivate", headers=second_headers)
    assert reactivate_response.status_code == 200
    assert reactivate_response.json()["id"] == admin_row["id"]
    assert reactivate_response.json()["status"] == "active"
    assert reactivate_response.json()["role_code"] == "tenant_admin"

    # Reactivating an already-active membership is now rejected.
    already_active = client.post(f"/memberships/{admin_row['id']}/reactivate", headers=second_headers)
    assert already_active.status_code == 409


@pytest.mark.integration
def test_role_change_and_deactivate_emit_audit_events(client, db_session, active_context_with_farm) -> None:
    tenant, admin_user, headers, _farm = active_context_with_farm
    target_user = user_service.create_user(
        db_session,
        oidc_issuer="https://issuer.example",
        oidc_subject=f"audit-{uuid.uuid4().hex}",
        email="audit-target@example.com",
        display_name="Audit Target",
    )
    create_response = client.post(
        "/memberships", json={"user_id": str(target_user.id), "role_code": "operator"}, headers=headers
    )
    membership_id = create_response.json()["id"]

    role_response = client.post(
        f"/memberships/{membership_id}/role", json={"role_code": "qc_officer"}, headers=headers
    )
    assert role_response.status_code == 200

    deactivate_response = client.post(f"/memberships/{membership_id}/deactivate", headers=headers)
    assert deactivate_response.status_code == 200

    events = db_session.execute(
        select(AuditEvent).where(
            AuditEvent.tenant_id == tenant.id, AuditEvent.entity_id == uuid.UUID(membership_id)
        )
    ).scalars().all()
    actions = {e.action for e in events}
    assert "membership.created" in actions
    assert "membership.role_changed" in actions
    assert "membership.deactivated" in actions
    role_change_event = next(e for e in events if e.action == "membership.role_changed")
    assert role_change_event.event_data == {"role_code_before": "operator", "role_code_after": "qc_officer"}


@pytest.mark.integration
def test_user_lookup_by_email_found_and_not_found(client, db_session, active_context_with_farm) -> None:
    _tenant, _admin_user, headers, _farm = active_context_with_farm
    existing_user = user_service.create_user(
        db_session,
        oidc_issuer="https://issuer.example",
        oidc_subject=f"lookup-{uuid.uuid4().hex}",
        email="findme@example.com",
        display_name="Find Me",
    )

    found = client.get("/users/lookup", params={"email": "findme@example.com"}, headers=headers)
    assert found.status_code == 200
    assert found.json()["id"] == str(existing_user.id)
    assert found.json()["display_name"] == "Find Me"
    # No internal identity fields leaked.
    assert "oidc_subject" not in found.json()
    assert "oidc_issuer" not in found.json()

    not_found = client.get("/users/lookup", params={"email": "nobody@example.com"}, headers=headers)
    assert not_found.status_code == 404
    # Truthful pilot wording: signing in cannot create the missing User
    # (there is no auto-provisioning on first Auth0 login) -- must never
    # imply that asking the person to sign in would fix this.
    assert "sign in" not in not_found.json()["detail"]
    assert "Platform Administrator" in not_found.json()["detail"]


@pytest.mark.integration
def test_user_lookup_by_email_ambiguous_match_is_never_silently_resolved(
    client, db_session, active_context_with_farm
) -> None:
    """`users.email` carries no uniqueness constraint -- two distinct CMP
    identities can share one email. The lookup must refuse to guess which
    one was meant (never "first match wins"), and must never leak either
    candidate's internal identity fields while doing so."""
    _tenant, _admin_user, headers, _farm = active_context_with_farm
    user_service.create_user(
        db_session,
        oidc_issuer="https://issuer.example",
        oidc_subject=f"dup-a-{uuid.uuid4().hex}",
        email="shared@example.com",
        display_name="Shared A",
    )
    user_service.create_user(
        db_session,
        oidc_issuer="https://issuer.example",
        oidc_subject=f"dup-b-{uuid.uuid4().hex}",
        email="shared@example.com",
        display_name="Shared B",
    )

    response = client.get("/users/lookup", params={"email": "shared@example.com"}, headers=headers)
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "Platform Administrator" in detail
    assert "Shared A" not in detail
    assert "Shared B" not in detail


@pytest.mark.integration
def test_add_user_reactivates_existing_removed_membership_instead_of_duplicating(
    client, db_session, active_context_with_farm
) -> None:
    """A user who was previously deactivated, then re-added via the Add
    User flow, must reuse their original historical membership row (same
    `id`) rather than a second, duplicate one for the same (tenant, user)."""
    tenant, _admin_user, headers, _farm = active_context_with_farm
    target_user = user_service.create_user(
        db_session,
        oidc_issuer="https://issuer.example",
        oidc_subject=f"readd-{uuid.uuid4().hex}",
        email="readd@example.com",
        display_name="Re Added",
    )
    original = membership_service.add_membership(
        db_session, tenant_id=tenant.id, user_id=target_user.id, role_code="operator", actor_user_id=None
    )
    membership_service.deactivate_membership(
        db_session, tenant_id=tenant.id, membership_id=original.id, actor_user_id=None
    )

    response = client.post(
        "/memberships", json={"user_id": str(target_user.id), "role_code": "qc_officer"}, headers=headers
    )
    assert response.status_code == 201
    body = response.json()
    assert body["id"] == str(original.id)
    assert body["status"] == "active"
    assert body["role_code"] == "qc_officer"

    # Exactly one membership row exists for this (tenant, user) -- never two.
    rows = client.get("/memberships", headers=headers).json()
    matching = [r for r in rows if r["user_id"] == str(target_user.id)]
    assert len(matching) == 1

    events = db_session.execute(
        select(AuditEvent).where(AuditEvent.tenant_id == tenant.id, AuditEvent.entity_id == original.id)
    ).scalars().all()
    assert any(e.action == "membership.reactivated" for e in events)


@pytest.mark.integration
def test_add_membership_reactivates_deterministically_with_multiple_removed_rows(
    client, db_session, active_context_with_farm
) -> None:
    """The DB only guarantees at most one ACTIVE TenantMembership per
    (tenant, user) -- nothing prevents several REMOVED rows accumulating
    (legal, pre-existing data shape). `add_membership` must not assume a
    single historical row (that would raise MultipleResultsFound) and must
    deterministically reactivate exactly one -- the most-recently-updated
    -- leaving the other historical rows untouched and creating no new row."""
    tenant, _admin_user, _headers, _farm = active_context_with_farm
    target_user = user_service.create_user(
        db_session,
        oidc_issuer="https://issuer.example",
        oidc_subject=f"multi-removed-{uuid.uuid4().hex}",
        email="multiremoved@example.com",
        display_name="Multi Removed",
    )

    now = datetime.now(timezone.utc)
    membership_oldest = TenantMembership(
        tenant_id=tenant.id,
        user_id=target_user.id,
        role_code="operator",
        status="removed",
        updated_at=now - timedelta(days=2),
    )
    membership_middle = TenantMembership(
        tenant_id=tenant.id,
        user_id=target_user.id,
        role_code="storekeeper",
        status="removed",
        updated_at=now - timedelta(days=1),
    )
    membership_most_recent = TenantMembership(
        tenant_id=tenant.id,
        user_id=target_user.id,
        role_code="qc_officer",
        status="removed",
        updated_at=now,
    )
    db_session.add_all([membership_oldest, membership_middle, membership_most_recent])
    db_session.commit()

    reactivated = membership_service.add_membership(
        db_session,
        tenant_id=tenant.id,
        user_id=target_user.id,
        role_code="dispatch_officer",
        actor_user_id=None,
    )

    # Deterministic pick: the most-recently-updated historical row.
    assert reactivated.id == membership_most_recent.id
    assert reactivated.status == "active"
    assert reactivated.role_code == "dispatch_officer"

    # No new row created -- exactly the original three rows still exist.
    all_rows = db_session.execute(
        select(TenantMembership).where(
            TenantMembership.tenant_id == tenant.id, TenantMembership.user_id == target_user.id
        )
    ).scalars().all()
    assert len(all_rows) == 3

    active_rows = [m for m in all_rows if m.status == "active"]
    assert len(active_rows) == 1
    assert active_rows[0].id == membership_most_recent.id

    # The other two historical rows are untouched -- still removed, own role unchanged.
    others = {m.id: (m.status, m.role_code) for m in all_rows if m.id != membership_most_recent.id}
    assert others == {
        membership_oldest.id: ("removed", "operator"),
        membership_middle.id: ("removed", "storekeeper"),
    }

    reactivation_event = db_session.execute(
        select(AuditEvent).where(
            AuditEvent.tenant_id == tenant.id,
            AuditEvent.entity_id == membership_most_recent.id,
            AuditEvent.action == "membership.reactivated",
        )
    ).scalar_one()
    assert reactivation_event.event_data == {
        "role_code_before": "qc_officer",
        "role_code_after": "dispatch_officer",
        "reactivated_via": "add_membership",
    }
