import uuid

from pydantic import BaseModel


class AuthMeUser(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str


class AuthMeMembership(BaseModel):
    tenant_id: uuid.UUID
    tenant_code: str
    tenant_name: str
    role_code: str


class AuthMeRead(BaseModel):
    """GET /auth/me's contract. Deliberately excludes oidc_subject, the raw
    oidc_issuer, any raw token claims, and the token itself -- only CMP/
    application facts a frontend needs to decide what to show next
    (login-complete-no-access vs. auto-select vs. tenant picker)."""

    user: AuthMeUser
    memberships: list[AuthMeMembership]
