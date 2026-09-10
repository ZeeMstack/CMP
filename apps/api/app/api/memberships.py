import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.auth import TenantContext
from app.core.permissions import Permission, require_permission
from app.core.role_catalog import ROLE_CATALOG
from app.schemas.membership import (
    MembershipCreate,
    MembershipRead,
    MembershipRoleChange,
    MembershipWithUserRead,
    RoleOption,
)
from app.services import membership_service
from app.services.errors import (
    DuplicateMembershipError,
    LastActiveTenantAdminError,
    MembershipAlreadyActiveForUserError,
    MembershipNotActiveError,
    MembershipNotFoundError,
    MembershipNotInactiveError,
)

router = APIRouter(tags=["memberships"])


@router.get("/memberships", response_model=list[MembershipWithUserRead])
def list_memberships(
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.TENANT_MEMBERS_READ)),
) -> list[MembershipWithUserRead]:
    """AUTHZ-OPS-001: the Users & Roles administration table -- every
    membership (active and removed) for the caller's own tenant, joined
    with the owning User's display fields. Tenant-scoped by construction
    (`membership_service.list_memberships_for_tenant` filters by
    `ctx.tenant_id`) -- never any other tenant's rows."""
    rows = membership_service.list_memberships_for_tenant(db, tenant_id=ctx.tenant_id)
    return [
        MembershipWithUserRead(
            id=membership.id,
            user_id=membership.user_id,
            status=membership.status,
            role_code=membership.role_code,
            user_email=user.email,
            user_display_name=user.display_name,
        )
        for membership, user in rows
    ]


@router.get("/memberships/roles", response_model=list[RoleOption])
def list_assignable_roles(
    ctx: TenantContext = Depends(require_permission(Permission.TENANT_MEMBERS_READ)),
) -> list[RoleOption]:
    """AUTHZ-OPS-001 section 17: one small backend read so the frontend
    role picker never independently duplicates the approved role list or
    invents its own descriptions. `ctx` is required (and otherwise unused)
    purely to enforce the same tenant-membership-administration permission
    as every other endpoint on this router -- this is reference data, not
    tenant-specific, but still gated consistently rather than left open."""
    del ctx
    return [RoleOption(**entry) for entry in ROLE_CATALOG]


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


@router.post("/memberships/{membership_id}/role", response_model=MembershipRead)
def change_membership_role(
    membership_id: uuid.UUID,
    payload: MembershipRoleChange,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.TENANT_MEMBERS_MANAGE)),
) -> MembershipRead:
    try:
        membership = membership_service.change_role(
            db,
            tenant_id=ctx.tenant_id,
            membership_id=membership_id,
            new_role_code=payload.role_code,
            actor_user_id=ctx.user_id,
        )
    except MembershipNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="This user is not a member of this tenant"
        ) from exc
    except LastActiveTenantAdminError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You cannot change the role of the last active Tenant Admin",
        ) from exc
    return MembershipRead.model_validate(membership)


@router.post("/memberships/{membership_id}/deactivate", response_model=MembershipRead)
def deactivate_membership(
    membership_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.TENANT_MEMBERS_MANAGE)),
) -> MembershipRead:
    try:
        membership = membership_service.deactivate_membership(
            db, tenant_id=ctx.tenant_id, membership_id=membership_id, actor_user_id=ctx.user_id
        )
    except MembershipNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="This user is not a member of this tenant"
        ) from exc
    except MembershipNotActiveError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This user's access is already inactive"
        ) from exc
    except LastActiveTenantAdminError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You cannot deactivate the last active Tenant Admin",
        ) from exc
    return MembershipRead.model_validate(membership)


@router.post("/memberships/{membership_id}/reactivate", response_model=MembershipRead)
def reactivate_membership(
    membership_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.TENANT_MEMBERS_MANAGE)),
) -> MembershipRead:
    try:
        membership = membership_service.reactivate_membership(
            db, tenant_id=ctx.tenant_id, membership_id=membership_id, actor_user_id=ctx.user_id
        )
    except MembershipNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="This user is not a member of this tenant"
        ) from exc
    except MembershipNotInactiveError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This user's access is already active"
        ) from exc
    except MembershipAlreadyActiveForUserError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This user already has active access to this tenant",
        ) from exc
    return MembershipRead.model_validate(membership)
