import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.auth import TenantContext
from app.core.permissions import Permission, require_permission
from app.schemas.workflow import (
    WorkflowCreate,
    WorkflowRead,
    WorkflowVersionDetailRead,
    WorkflowVersionRead,
)
from app.schemas.workflow_stage import WorkflowStageCreate, WorkflowStageRead
from app.schemas.workflow_transition import WorkflowTransitionCreate, WorkflowTransitionRead
from app.services import workflow_service
from app.services.errors import (
    CarrierTypeReferenceNotFoundError,
    CropNotFoundError,
    DuplicateStageCodeError,
    DuplicateTransitionCodeError,
    DuplicateTransitionPairError,
    DuplicateWorkflowCodeError,
    LocationTypeReferenceNotFoundError,
    ProductionSystemNotFoundError,
    SelfTransitionError,
    VarietyCropMismatchError,
    WorkflowNotFoundError,
    WorkflowPublicationValidationError,
    WorkflowStageNotFoundError,
    WorkflowVersionNotDraftError,
    WorkflowVersionNotFoundError,
)

router = APIRouter(tags=["workflows"])


@router.post("/workflows", response_model=WorkflowRead, status_code=status.HTTP_201_CREATED)
def create_workflow(
    payload: WorkflowCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WORKFLOW_MANAGE)),
) -> WorkflowRead:
    try:
        workflow = workflow_service.register_workflow(
            db,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            crop_id=payload.crop_id,
            variety_id=payload.variety_id,
            production_system_id=payload.production_system_id,
            code=payload.code,
            name=payload.name,
        )
    except CropNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crop not found") from exc
    except ProductionSystemNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Production system not found"
        ) from exc
    except VarietyCropMismatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Variety not found for this crop"
        ) from exc
    except DuplicateWorkflowCodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Workflow code already exists in this tenant"
        ) from exc
    return WorkflowRead.model_validate(workflow)


@router.get("/workflows", response_model=list[WorkflowRead])
def list_workflows(
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WORKFLOW_READ)),
) -> list[WorkflowRead]:
    workflows = workflow_service.list_workflows(db, tenant_id=ctx.tenant_id)
    return [WorkflowRead.model_validate(workflow) for workflow in workflows]


@router.get("/workflows/{workflow_id}", response_model=WorkflowRead)
def get_workflow(
    workflow_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WORKFLOW_READ)),
) -> WorkflowRead:
    try:
        workflow = workflow_service.get_workflow(db, tenant_id=ctx.tenant_id, workflow_id=workflow_id)
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found") from exc
    return WorkflowRead.model_validate(workflow)


@router.post(
    "/workflows/{workflow_id}/versions",
    response_model=WorkflowVersionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_draft_version(
    workflow_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WORKFLOW_MANAGE)),
) -> WorkflowVersionRead:
    try:
        version = workflow_service.create_draft_version(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, workflow_id=workflow_id
        )
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found") from exc
    return WorkflowVersionRead.model_validate(version)


@router.get("/workflows/{workflow_id}/versions", response_model=list[WorkflowVersionRead])
def list_workflow_versions(
    workflow_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WORKFLOW_READ)),
) -> list[WorkflowVersionRead]:
    try:
        versions = workflow_service.list_versions(db, tenant_id=ctx.tenant_id, workflow_id=workflow_id)
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found") from exc
    return [WorkflowVersionRead.model_validate(v) for v in versions]


@router.get(
    "/workflows/{workflow_id}/versions/{version_id}", response_model=WorkflowVersionDetailRead
)
def get_workflow_version(
    workflow_id: uuid.UUID,
    version_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WORKFLOW_READ)),
) -> WorkflowVersionDetailRead:
    try:
        version = workflow_service.get_workflow_version(
            db, tenant_id=ctx.tenant_id, workflow_id=workflow_id, version_id=version_id
        )
    except (WorkflowNotFoundError, WorkflowVersionNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    stages = workflow_service.get_stages(db, version_id=version.id)
    transitions = workflow_service.get_transitions(db, version_id=version.id)
    return WorkflowVersionDetailRead(
        id=version.id,
        tenant_id=version.tenant_id,
        workflow_id=version.workflow_id,
        version_number=version.version_number,
        state=version.state,
        created_at=version.created_at,
        published_at=version.published_at,
        retired_at=version.retired_at,
        stages=[WorkflowStageRead.model_validate(s) for s in stages],
        transitions=[WorkflowTransitionRead.model_validate(t) for t in transitions],
    )


@router.post(
    "/workflows/{workflow_id}/versions/{version_id}/stages",
    response_model=WorkflowStageRead,
    status_code=status.HTTP_201_CREATED,
)
def add_stage(
    workflow_id: uuid.UUID,
    version_id: uuid.UUID,
    payload: WorkflowStageCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WORKFLOW_MANAGE)),
) -> WorkflowStageRead:
    try:
        stage = workflow_service.add_stage(
            db,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            workflow_id=workflow_id,
            version_id=version_id,
            code=payload.code,
            name=payload.name,
            display_order=payload.display_order,
            stage_category=payload.stage_category,
            expected_duration_minutes=payload.expected_duration_minutes,
            permitted_location_type_code=payload.permitted_location_type_code,
            required_carrier_type_code=payload.required_carrier_type_code,
            is_start=payload.is_start,
            is_terminal=payload.is_terminal,
        )
    except (WorkflowNotFoundError, WorkflowVersionNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except WorkflowVersionNotDraftError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Workflow version is not in draft state"
        ) from exc
    except LocationTypeReferenceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown permitted_location_type_code"
        ) from exc
    except CarrierTypeReferenceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown required_carrier_type_code"
        ) from exc
    except DuplicateStageCodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Stage code already exists in this workflow version"
        ) from exc
    return WorkflowStageRead.model_validate(stage)


@router.post(
    "/workflows/{workflow_id}/versions/{version_id}/transitions",
    response_model=WorkflowTransitionRead,
    status_code=status.HTTP_201_CREATED,
)
def add_transition(
    workflow_id: uuid.UUID,
    version_id: uuid.UUID,
    payload: WorkflowTransitionCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WORKFLOW_MANAGE)),
) -> WorkflowTransitionRead:
    try:
        transition = workflow_service.add_transition(
            db,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            workflow_id=workflow_id,
            version_id=version_id,
            from_stage_id=payload.from_stage_id,
            to_stage_id=payload.to_stage_id,
            code=payload.code,
            name=payload.name,
        )
    except (WorkflowNotFoundError, WorkflowVersionNotFoundError, WorkflowStageNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except WorkflowVersionNotDraftError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Workflow version is not in draft state"
        ) from exc
    except SelfTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="A stage cannot transition to itself"
        ) from exc
    except DuplicateTransitionPairError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This from-stage/to-stage pair already exists"
        ) from exc
    except DuplicateTransitionCodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Transition code already exists in this workflow version",
        ) from exc
    return WorkflowTransitionRead.model_validate(transition)


@router.post(
    "/workflows/{workflow_id}/versions/{version_id}/publish", response_model=WorkflowVersionRead
)
def publish_workflow_version(
    workflow_id: uuid.UUID,
    version_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WORKFLOW_MANAGE)),
) -> WorkflowVersionRead:
    try:
        version = workflow_service.publish_version(
            db,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            workflow_id=workflow_id,
            version_id=version_id,
        )
    except (WorkflowNotFoundError, WorkflowVersionNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except WorkflowVersionNotDraftError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Only a draft workflow version can be published"
        ) from exc
    except WorkflowPublicationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.reason) from exc
    return WorkflowVersionRead.model_validate(version)
