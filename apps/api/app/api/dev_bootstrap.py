from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas.membership import BootstrapMembershipCreate, MembershipRead
from app.schemas.tenant import TenantCreate, TenantRead
from app.schemas.user import UserCreate, UserRead
from app.services import membership_service, tenant_service, user_service
from app.services.errors import (
    DuplicateMembershipError,
    DuplicateTenantCodeError,
    DuplicateUserIdentityError,
)

router = APIRouter(prefix="/dev/bootstrap", tags=["dev-bootstrap"])


@router.post("/tenants", response_model=TenantRead, status_code=status.HTTP_201_CREATED)
def bootstrap_tenant(payload: TenantCreate, db: Session = Depends(get_db)) -> TenantRead:
    try:
        tenant = tenant_service.create_tenant(db, code=payload.code, name=payload.name)
    except DuplicateTenantCodeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tenant code already exists") from exc
    return TenantRead.model_validate(tenant)


@router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def bootstrap_user(payload: UserCreate, db: Session = Depends(get_db)) -> UserRead:
    try:
        user = user_service.create_user(
            db,
            oidc_issuer=payload.oidc_issuer,
            oidc_subject=payload.oidc_subject,
            email=payload.email,
            display_name=payload.display_name,
        )
    except DuplicateUserIdentityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User already exists for this issuer/subject",
        ) from exc
    return UserRead.model_validate(user)


@router.post("/memberships", response_model=MembershipRead, status_code=status.HTTP_201_CREATED)
def bootstrap_membership(payload: BootstrapMembershipCreate, db: Session = Depends(get_db)) -> MembershipRead:
    """Development-only: creates a tenant's first membership. No active
    membership is required to call this — that's the whole point of a
    bootstrap route. `POST /memberships` (not under /dev/bootstrap) is for
    an already-active member to add further members."""
    try:
        membership = membership_service.add_membership(
            db,
            tenant_id=payload.tenant_id,
            user_id=payload.user_id,
            role_code=payload.role_code,
            actor_user_id=None,
        )
    except DuplicateMembershipError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Active membership already exists"
        ) from exc
    return MembershipRead.model_validate(membership)
