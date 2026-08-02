import uuid

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.membership import APPROVED_ROLE_CODES


def _normalize_and_validate_role_code(v: str) -> str:
    v = v.strip().lower()
    if v not in APPROVED_ROLE_CODES:
        allowed = ", ".join(sorted(APPROVED_ROLE_CODES))
        raise ValueError(f"role_code must be one of: {allowed}")
    return v


class MembershipCreate(BaseModel):
    user_id: uuid.UUID
    role_code: str

    @field_validator("role_code")
    @classmethod
    def validate_role_code(cls, v: str) -> str:
        return _normalize_and_validate_role_code(v)


class BootstrapMembershipCreate(BaseModel):
    """Development-only: creates a membership without requiring an existing
    active membership, to bootstrap a tenant's first member."""

    tenant_id: uuid.UUID
    user_id: uuid.UUID
    role_code: str

    @field_validator("role_code")
    @classmethod
    def validate_role_code(cls, v: str) -> str:
        return _normalize_and_validate_role_code(v)


class MembershipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    status: str
    role_code: str | None
