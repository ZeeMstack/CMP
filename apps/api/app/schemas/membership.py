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


class MembershipWithUserRead(BaseModel):
    """AUTHZ-OPS-001: one row of the Users & Roles administration table --
    membership fields plus the joined User's display fields, so the
    frontend never needs a second per-row lookup (and never renders a bare
    `user_id` UUID as the row's identity)."""

    id: uuid.UUID
    user_id: uuid.UUID
    status: str
    role_code: str | None
    user_email: str
    user_display_name: str


class MembershipRoleChange(BaseModel):
    role_code: str

    @field_validator("role_code")
    @classmethod
    def validate_role_code(cls, v: str) -> str:
        return _normalize_and_validate_role_code(v)


class RoleOption(BaseModel):
    """AUTHZ-OPS-001 section 17: a small, explicit, backend-owned read so
    the frontend role dropdown never duplicates the approved role list or
    invents its own descriptions. Descriptions are explanatory copy only --
    never consulted for authorization (the role -> permission policy in
    `app.core.permissions.ROLE_PERMISSIONS` is the sole authorization
    source, entirely independent of this text)."""

    code: str
    name: str
    description: str
