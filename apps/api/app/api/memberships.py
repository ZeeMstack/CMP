from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.auth import TenantContext
from app.core.permissions import Permission, require_permission
from app.schemas.membership import MembershipCreate, MembershipRead
from app.services import membership_service
from app.services.errors import DuplicateMembershipError

router = APIRouter(tags=["memberships"])


@router.post("/memberships", response_model=MembershipRead, status_code=status.HTTP_201_CREATED)
def create_membership(
    payload: MembershipCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.TENANT_MEMBERS_MANAGE)),
) -> MembershipRead:
    try:
        membership = membership_service.add_membership(
            db,
            tenant_id=ctx.tenant_id,
            user_id=payload.user_id,
            role_code=payload.role_code,
            actor_user_id=ctx.user_id,
        )
    except DuplicateMembershipError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Active membership already exists"
        ) from exc
    return MembershipRead.model_validate(membership)
