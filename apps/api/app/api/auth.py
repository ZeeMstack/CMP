from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import AuthenticatedPrincipal, require_authenticated_principal
from app.core.db import get_db
from app.models.user import User
from app.schemas.auth import AuthMeMembership, AuthMeRead, AuthMeUser
from app.services import membership_service

router = APIRouter(tags=["auth"])


@router.get("/auth/me", response_model=AuthMeRead)
def get_auth_me(
    principal: AuthenticatedPrincipal = Depends(require_authenticated_principal),
    db: Session = Depends(get_db),
) -> AuthMeRead:
    """Deliberately does not require X-CMP-Tenant-Id -- its whole purpose
    is letting a client discover which tenants it may select next.
    `require_authenticated_principal` has already proven the caller is a
    known, active CMP user (unknown/inactive identities never reach this
    body -- 403 before this point). Zero accessible memberships is a
    perfectly valid, successful response (`memberships: []`), not an
    error -- that's how a frontend knows to show "access not
    provisioned"."""
    # principal.user_id is guaranteed to reference an active user by this
    # point (require_authenticated_principal already validated it).
    user = db.get(User, principal.user_id)
    assert user is not None  # noqa: S101 -- invariant guaranteed by the dependency, not user input

    memberships = membership_service.list_active_memberships_for_user(db, user_id=principal.user_id)

    return AuthMeRead(
        user=AuthMeUser(id=user.id, email=user.email, display_name=user.display_name),
        memberships=[
            AuthMeMembership(
                tenant_id=tenant.id,
                tenant_code=tenant.code,
                tenant_name=tenant.name,
                role_code=membership.role_code,
            )
            for membership, tenant in memberships
        ],
    )
