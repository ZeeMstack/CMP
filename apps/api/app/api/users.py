from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.auth import TenantContext
from app.core.db import get_db
from app.core.permissions import Permission, require_permission
from app.schemas.user import UserLookupRead
from app.services import user_service

router = APIRouter(tags=["users"])

_NOT_PROVISIONED_DETAIL = (
    "No GrowCMP user exists for this email. The user must first be provisioned by a Platform "
    "Administrator before they can be added to this tenant."
)
_AMBIGUOUS_DETAIL = (
    "More than one GrowCMP identity uses this email. A Platform Administrator must resolve the "
    "identity before tenant access can be assigned."
)


@router.get("/users/lookup", response_model=UserLookupRead)
def lookup_user_by_email(
    email: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.TENANT_MEMBERS_READ)),
) -> UserLookupRead:
    """AUTHZ-OPS-001 section 8 (CTO correction pass): the "Add Existing
    User" prerequisite step. CMP has no self-service signup, no invitation
    mechanism, and -- critically -- **no auto-provisioning on first Auth0
    login either**: `app.core.auth._resolve_cmp_user_for_identity` returns
    a plain 403 when no matching User row exists; it never creates one. The
    only paths that ever create a User are `/dev/bootstrap/users` (dev-only)
    and Platform Admin tenant onboarding (`platform_tenant_service.
    onboard_tenant`, which requires the Platform Admin to already know the
    target's `oidc_issuer`/`oidc_subject` -- not just an email). A Tenant
    Admin therefore cannot provision a brand-new identity by any means, and
    telling them to "ask the person to sign in" would be false: signing in
    with no existing User row still ends in a 403, not a new account.

    `users.email` has no uniqueness constraint -- exactly one match is the
    only case this endpoint can safely resolve on the caller's behalf:

    - 0 matches: truthful "not provisioned yet" guidance (404).
    - 1 match: resolved (200).
    - 2+ matches: refuses to guess which identity was meant -- an
      operator-facing ambiguity error (409) naming the Platform Admin as
      the one who must resolve it, never silently picking one (the prior
      version of this endpoint's underlying lookup took "the first match",
      which could have attached the wrong identity to a tenant).

    Deliberately tenant-unscoped (Users are not tenant-owned records --
    `tenant_id` lives on TenantMembership, not User) -- still gated by
    `TENANT_MEMBERS_READ` so only a caller already trusted to administer
    this tenant's membership can probe whether an email is a known CMP
    identity at all. Exact-match only (no partial/fuzzy search, no listing)
    -- this is a single-identity resolution step for the Add User flow, not
    a general User directory. Returns only `id`/`email`/`display_name`
    (`UserLookupRead`) -- never `oidc_issuer`/`oidc_subject`/`status`, and
    never any other tenant's membership/role information for this User.
    `id` stays in the API contract because the subsequent `POST
    /memberships` call needs it, but the frontend never renders it -- and
    that endpoint independently re-resolves `ctx.tenant_id`/permission from
    the caller's own request, never trusting anything about tenant context
    from this lookup."""
    del ctx
    matches = user_service.find_users_by_email(db, email=email)
    if len(matches) == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_PROVISIONED_DETAIL)
    if len(matches) > 1:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_AMBIGUOUS_DETAIL)
    return UserLookupRead.model_validate(matches[0])
