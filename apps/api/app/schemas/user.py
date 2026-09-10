import uuid

from pydantic import BaseModel, ConfigDict, field_validator


class UserCreate(BaseModel):
    oidc_issuer: str
    oidc_subject: str
    email: str
    display_name: str

    @field_validator("oidc_issuer", "oidc_subject", "email", "display_name")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    oidc_issuer: str
    oidc_subject: str
    email: str
    display_name: str
    status: str


class UserLookupRead(BaseModel):
    """AUTHZ-OPS-001: the minimal, administrative-only shape returned by
    `GET /users/lookup` -- just enough for a Tenant Admin to confirm they
    found the right person before adding them to the tenant. Deliberately
    excludes `oidc_issuer`/`oidc_subject`/`status` (CLAUDE.md: never expose
    internal identity provider ids in the UI)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
