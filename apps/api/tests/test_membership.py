import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.models.membership import APPROVED_ROLE_CODES
from app.schemas.membership import MembershipCreate
from app.services import membership_service, tenant_service, user_service
from app.services.errors import DuplicateMembershipError

# --- Application-level (Pydantic) validation — no DB required ---


def test_role_code_normalized_to_lowercase() -> None:
    payload = MembershipCreate(user_id=uuid.uuid4(), role_code="TENANT_ADMIN")
    assert payload.role_code == "tenant_admin"


def test_invalid_role_code_rejected_by_schema() -> None:
    with pytest.raises(ValueError):
        MembershipCreate(user_id=uuid.uuid4(), role_code="not_a_real_role")


def test_missing_role_code_rejected_by_schema() -> None:
    with pytest.raises(ValueError):
        MembershipCreate.model_validate({"user_id": str(uuid.uuid4())})


# --- Integration (DB) ---


@pytest.mark.integration
def test_add_membership(db_session) -> None:
    tenant = tenant_service.create_tenant(db_session, code="t-mem-1", name="T1")
    user = user_service.create_user(
        db_session, oidc_issuer="iss", oidc_subject="s1", email="e1@example.com", display_name="U1"
    )
    membership = membership_service.add_membership(
        db_session, tenant_id=tenant.id, user_id=user.id, role_code="operator", actor_user_id=user.id
    )
    assert membership.status == "active"
    assert membership.role_code == "operator"
    assert membership.tenant_id == tenant.id
    assert membership.user_id == user.id


@pytest.mark.integration
def test_valid_role_code_accepted_for_every_approved_value(db_session) -> None:
    tenant = tenant_service.create_tenant(db_session, code="t-mem-roles", name="Roles")
    for i, role in enumerate(sorted(APPROVED_ROLE_CODES)):
        user = user_service.create_user(
            db_session,
            oidc_issuer="iss",
            oidc_subject=f"role-{i}",
            email=f"role{i}@example.com",
            display_name=f"U{i}",
        )
        membership = membership_service.add_membership(
            db_session, tenant_id=tenant.id, user_id=user.id, role_code=role, actor_user_id=None
        )
        assert membership.role_code == role


@pytest.mark.integration
def test_duplicate_active_membership_is_rejected(db_session) -> None:
    tenant = tenant_service.create_tenant(db_session, code="t-mem-2", name="T2")
    user = user_service.create_user(
        db_session, oidc_issuer="iss", oidc_subject="s2", email="e2@example.com", display_name="U2"
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant.id, user_id=user.id, role_code="operator", actor_user_id=None
    )
    with pytest.raises(DuplicateMembershipError):
        membership_service.add_membership(
            db_session, tenant_id=tenant.id, user_id=user.id, role_code="operator", actor_user_id=None
        )


@pytest.mark.integration
def test_invalid_role_code_rejected_by_database_check_constraint(db_session) -> None:
    tenant = tenant_service.create_tenant(db_session, code="t-mem-3", name="T3")
    user = user_service.create_user(
        db_session, oidc_issuer="iss", oidc_subject="s3", email="e3@example.com", display_name="U3"
    )
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO tenant_memberships (id, tenant_id, user_id, status, role_code) "
                    "VALUES (:id, :tenant_id, :user_id, 'active', 'not_a_real_role')"
                ),
                {"id": uuid.uuid4(), "tenant_id": tenant.id, "user_id": user.id},
            )


@pytest.mark.integration
def test_missing_role_code_rejected_by_database_for_active_membership(db_session) -> None:
    tenant = tenant_service.create_tenant(db_session, code="t-mem-4", name="T4")
    user = user_service.create_user(
        db_session, oidc_issuer="iss", oidc_subject="s4", email="e4@example.com", display_name="U4"
    )
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO tenant_memberships (id, tenant_id, user_id, status, role_code) "
                    "VALUES (:id, :tenant_id, :user_id, 'active', NULL)"
                ),
                {"id": uuid.uuid4(), "tenant_id": tenant.id, "user_id": user.id},
            )


@pytest.mark.integration
def test_bootstrap_membership_endpoint_enables_subsequent_tenant_scoped_access(client) -> None:
    tenant = client.post(
        "/dev/bootstrap/tenants", json={"code": "boot-mem", "name": "Boot Membership"}
    ).json()
    user = client.post(
        "/dev/bootstrap/users",
        json={
            "oidc_issuer": "https://issuer.example",
            "oidc_subject": "boot-mem-user",
            "email": "bootmem@example.com",
            "display_name": "Boot User",
        },
    ).json()

    membership_response = client.post(
        "/dev/bootstrap/memberships",
        json={"tenant_id": tenant["id"], "user_id": user["id"], "role_code": "TENANT_ADMIN"},
    )
    assert membership_response.status_code == 201
    assert membership_response.json()["role_code"] == "tenant_admin"

    headers = {"X-Dev-Tenant-Id": tenant["id"], "X-Dev-User-Id": user["id"]}
    farms_response = client.get("/farms", headers=headers)
    assert farms_response.status_code == 200
