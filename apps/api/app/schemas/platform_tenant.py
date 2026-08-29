from pydantic import BaseModel, ConfigDict, field_validator

from app.schemas.membership import MembershipRead
from app.schemas.tenant import TenantCreate, TenantRead
from app.schemas.user import UserRead


class PlatformTenantOnboardingAdminCreate(BaseModel):
    """The initial tenant_admin identity a Platform Admin is
    administratively vouching for -- an OIDC binding, never a password or
    local credential (see `app.services.platform_tenant_service`). Mirrors
    `app.schemas.user.UserCreate`'s exact field/validation shape, since the
    resulting User (new or resolved) must satisfy the same User model
    requirements either way."""

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


class PlatformTenantOnboardingCreate(BaseModel):
    """`POST /platform/tenants` request body -- one onboarding command from
    the caller's perspective: create the Tenant, resolve-or-create its
    initial admin User, establish an active tenant_admin Membership."""

    tenant: TenantCreate
    initial_admin: PlatformTenantOnboardingAdminCreate


class PlatformTenantOnboardingResponse(BaseModel):
    """Purpose-built response combining the three existing read schemas --
    enough for the future B3 UI to confirm all three onboarding facts
    without exposing any secret/token. `admin_user_created` distinguishes a
    brand-new User from a resolved pre-existing one, since both are valid,
    non-error outcomes of the same command."""

    model_config = ConfigDict(from_attributes=True)

    tenant: TenantRead
    admin_user: UserRead
    admin_user_created: bool
    membership: MembershipRead
