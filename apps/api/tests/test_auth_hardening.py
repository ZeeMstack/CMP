"""AUTH-001A production-security hardening review (pre-commit): algorithm
allowlist configuration safety, WWW-Authenticate: Bearer on bearer-auth 401
responses, and the authentication-before-tenant-selection error-precedence
gap not already covered by tests/test_auth_context.py."""

import uuid

import pytest
from pydantic import ValidationError

from app.core.settings import Settings
from app.services import membership_service, tenant_service, user_service
from tests._oidc_test_support import (
    TEST_ISSUER,
    configured_oidc,  # noqa: F401
    mint_token,
    untrusted_signing_key,
)


# --- 5. Algorithm allowlist configuration safety -----------------------------


def test_settings_rejects_hmac_algorithm_in_config() -> None:
    with pytest.raises(ValidationError):
        Settings(oidc_allowed_algorithms=["HS256"])


def test_settings_rejects_none_algorithm_in_config() -> None:
    with pytest.raises(ValidationError):
        Settings(oidc_allowed_algorithms=["none"])


def test_settings_rejects_empty_algorithm_list() -> None:
    with pytest.raises(ValidationError):
        Settings(oidc_allowed_algorithms=[])


def test_settings_rejects_a_mix_of_valid_and_unsafe_algorithms() -> None:
    with pytest.raises(ValidationError):
        Settings(oidc_allowed_algorithms=["RS256", "HS256"])


def test_settings_accepts_the_default_and_other_asymmetric_algorithms() -> None:
    assert Settings().oidc_allowed_algorithms == ["RS256"]
    cfg = Settings(oidc_allowed_algorithms=["RS256", "ES256", "PS256"])
    assert cfg.oidc_allowed_algorithms == ["RS256", "ES256", "PS256"]


def test_settings_rejects_hmac_algorithm_supplied_via_environment_variable(monkeypatch) -> None:
    monkeypatch.setenv("OIDC_ALLOWED_ALGORITHMS", '["HS256"]')
    with pytest.raises(ValidationError):
        Settings()


# --- helpers for the HTTP-level tests below ----------------------------------


def _make_bearer_user_with_tenant(db_session):
    subject = f"hardening-subject-{uuid.uuid4().hex[:12]}"
    user = user_service.create_user(
        db_session, oidc_issuer=TEST_ISSUER, oidc_subject=subject, email="hardening@example.com", display_name="H"
    )
    tenant = tenant_service.create_tenant(db_session, code=f"t-hardening-{uuid.uuid4().hex[:8]}", name="Hardening Tenant")
    membership_service.add_membership(
        db_session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    db_session.commit()
    return user, subject, tenant


# --- 6. WWW-Authenticate: Bearer on 401s -------------------------------------


@pytest.mark.integration
def test_no_authorization_header_401_carries_www_authenticate_bearer(client) -> None:
    response = client.get("/farms")
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"


@pytest.mark.integration
def test_malformed_authorization_scheme_401_carries_www_authenticate_bearer(client) -> None:
    response = client.get("/farms", headers={"Authorization": "Basic dXNlcjpwYXNz"})
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"


@pytest.mark.integration
def test_malformed_jwt_401_carries_www_authenticate_bearer(client, configured_oidc) -> None:
    response = client.get("/farms", headers={"Authorization": "Bearer not-a-real-jwt"})
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"


@pytest.mark.integration
def test_expired_jwt_401_carries_www_authenticate_bearer(client, configured_oidc) -> None:
    token = mint_token(expires_in_seconds=-3600)
    response = client.get("/farms", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"


@pytest.mark.integration
def test_wrong_issuer_401_carries_www_authenticate_bearer(client, configured_oidc) -> None:
    token = mint_token(issuer="https://not-our-issuer.example")
    response = client.get("/farms", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"


@pytest.mark.integration
def test_invalid_signature_401_carries_www_authenticate_bearer(client, configured_oidc) -> None:
    token = mint_token(signing_key=untrusted_signing_key())
    response = client.get("/farms", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"


@pytest.mark.integration
def test_unknown_kid_401_carries_www_authenticate_bearer(client, configured_oidc) -> None:
    token = mint_token(kid="totally-unknown-kid-http-level")
    response = client.get("/farms", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"


@pytest.mark.integration
def test_ambiguous_bearer_plus_dev_headers_401_carries_www_authenticate_bearer(client, active_context, configured_oidc) -> None:
    _tenant, _user, dev_headers = active_context
    response = client.get(
        "/farms",
        headers={"Authorization": f"Bearer {mint_token()}", **dev_headers},
    )
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"


@pytest.mark.integration
def test_400_response_does_not_carry_www_authenticate(client, db_session, configured_oidc) -> None:
    _user, subject, _tenant = _make_bearer_user_with_tenant(db_session)
    response = client.get("/farms", headers={"Authorization": f"Bearer {mint_token(subject=subject)}"})
    assert response.status_code == 400
    assert "www-authenticate" not in {k.lower() for k in response.headers.keys()}


@pytest.mark.integration
def test_403_response_does_not_carry_www_authenticate(client, configured_oidc) -> None:
    response = client.get(
        "/farms",
        headers={"Authorization": f"Bearer {mint_token()}", "X-CMP-Tenant-Id": str(uuid.uuid4())},
    )
    assert response.status_code == 403
    assert "www-authenticate" not in {k.lower() for k in response.headers.keys()}


# --- 7. Authentication-before-tenant-selection precedence -------------------


@pytest.mark.integration
def test_invalid_bearer_with_malformed_tenant_header_is_401_not_400(client, configured_oidc) -> None:
    """A cryptographically invalid token must fail authentication before
    the tenant header is ever inspected -- a caller cannot use a malformed
    tenant header to probe tenant semantics before proving identity."""
    bad_token = mint_token(signing_key=untrusted_signing_key())
    response = client.get(
        "/farms", headers={"Authorization": f"Bearer {bad_token}", "X-CMP-Tenant-Id": "not-a-uuid"}
    )
    assert response.status_code == 401


@pytest.mark.integration
def test_expired_bearer_with_missing_tenant_header_is_401_not_400(client, configured_oidc) -> None:
    expired_token = mint_token(expires_in_seconds=-3600)
    response = client.get("/farms", headers={"Authorization": f"Bearer {expired_token}"})
    assert response.status_code == 401
