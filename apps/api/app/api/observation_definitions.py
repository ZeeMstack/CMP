import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.auth import TenantContext
from app.core.permissions import Permission, require_permission
from app.schemas.observation_definition import ObservationDefinitionCreate, ObservationDefinitionRead
from app.services import observation_service
from app.services.errors import DuplicateObservationDefinitionCodeError, ObservationDefinitionNotFoundError

router = APIRouter(tags=["observation-definitions"])


@router.post(
    "/observation-definitions", response_model=ObservationDefinitionRead, status_code=status.HTTP_201_CREATED
)
def create_observation_definition(
    payload: ObservationDefinitionCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.OBSERVATION_MANAGE)),
) -> ObservationDefinitionRead:
    try:
        definition = observation_service.register_observation_definition(
            db,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            code=payload.code,
            name=payload.name,
            description=payload.description,
            value_type=payload.value_type,
            unit=payload.unit,
            target_scope=payload.target_scope,
            min_value=payload.min_value,
            max_value=payload.max_value,
        )
    except DuplicateObservationDefinitionCodeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return observation_service.get_observation_definition(
        db, tenant_id=ctx.tenant_id, definition_id=definition.id
    )


@router.get("/observation-definitions", response_model=list[ObservationDefinitionRead])
def list_observation_definitions(
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.OBSERVATION_READ)),
) -> list[ObservationDefinitionRead]:
    return observation_service.list_observation_definitions(db, tenant_id=ctx.tenant_id)


@router.get("/observation-definitions/{definition_id}", response_model=ObservationDefinitionRead)
def get_observation_definition(
    definition_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.OBSERVATION_READ)),
) -> ObservationDefinitionRead:
    try:
        return observation_service.get_observation_definition(
            db, tenant_id=ctx.tenant_id, definition_id=definition_id
        )
    except ObservationDefinitionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
