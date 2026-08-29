"""PILOT-SETUP-001B2: Platform Admin Tenant onboarding.

Every route below depends on `require_platform_admin`
(`app.core.platform_auth`) and nothing else for authorization -- no
`X-Dev-Tenant-Id`, no `X-CMP-Tenant-Id`, no `TenantContext`, no tenant
`Permission` check. These are explicitly platform-level routes: they expose
Tenant metadata (id/code/name/status) only, never Farm/CropBatch/Location/
Harvest/post-harvest or any other tenant-operational data, and a Platform
Admin gains no implicit `TenantMembership` of any kind by calling them (see
`app.services.platform_tenant_service`).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.auth import AuthenticatedPrincipal
from app.core.db import get_db, get_engine
from app.core.platform_auth import require_platform_admin
from app.schemas.membership import MembershipRead
from app.schemas.platform_tenant import PlatformTenantOnboardingCreate, PlatformTenantOnboardingResponse
from app.schemas.tenant import TenantRead
from app.schemas.user import UserRead
from app.services import platform_tenant_service, tenant_service
from app.services.errors import (
    AdminIdentityEmailMismatchError,
    DuplicateMembershipError,
    DuplicateTenantCodeError,
    DuplicateUserIdentityError,
)

router = APIRouter(prefix="/platform/tenants", tags=["platform-tenants"])


@router.get("", response_model=list[TenantRead])
def list_platform_tenants(
    db: Session = Depends(get_db),
    _principal: AuthenticatedPrincipal = Depends(require_platform_admin),
) -> list[TenantRead]:
    tenants = tenant_service.list_tenants(db)
    return [TenantRead.model_validate(t) for t in tenants]


@router.get("/{tenant_id}", response_model=TenantRead)
def get_platform_tenant(
    tenant_id: uuid.UUID,
    db: Session = Depends(get_db),
    _principal: AuthenticatedPrincipal = Depends(require_platform_admin),
) -> TenantRead:
    tenant = tenant_service.get_tenant(db, tenant_id=tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return TenantRead.model_validate(tenant)


@router.post("", response_model=PlatformTenantOnboardingResponse, status_code=status.HTTP_201_CREATED)
def onboard_platform_tenant(
    payload: PlatformTenantOnboardingCreate,
    db_engine: Engine = Depends(get_engine),
    _principal: AuthenticatedPrincipal = Depends(require_platform_admin),
) -> PlatformTenantOnboardingResponse:
    """Creates a Tenant, resolves-or-creates its initial administrative
    User (by exact OIDC issuer+subject identity), and establishes an
    active `tenant_admin` Membership -- atomically (see
    `app.services.platform_tenant_service.onboard_tenant`). The requesting
    Platform Admin themselves receives no Membership of any kind; only the
    requested `initial_admin` identity does."""
    try:
        result = platform_tenant_service.onboard_tenant(
            db_engine,
            tenant_code=payload.tenant.code,
            tenant_name=payload.tenant.name,
            admin_oidc_issuer=payload.initial_admin.oidc_issuer,
            admin_oidc_subject=payload.initial_admin.oidc_subject,
            admin_email=payload.initial_admin.email,
            admin_display_name=payload.initial_admin.display_name,
        )
    except DuplicateTenantCodeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tenant code already exists") from exc
    except AdminIdentityEmailMismatchError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except DuplicateUserIdentityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A User already exists for this issuer/subject"
        ) from exc
    except DuplicateMembershipError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Active membership already exists"
        ) from exc

    return PlatformTenantOnboardingResponse(
        tenant=TenantRead(
            id=result.tenant_id, code=result.tenant_code, name=result.tenant_name, status=result.tenant_status
        ),
        admin_user=UserRead(
            id=result.admin_user_id,
            oidc_issuer=result.admin_user_oidc_issuer,
            oidc_subject=result.admin_user_oidc_subject,
            email=result.admin_user_email,
            display_name=result.admin_user_display_name,
            status=result.admin_user_status,
        ),
        admin_user_created=result.admin_user_created,
        membership=MembershipRead(
            id=result.membership_id,
            tenant_id=result.tenant_id,
            user_id=result.admin_user_id,
            status=result.membership_status,
            role_code=result.membership_role_code,
        ),
    )
