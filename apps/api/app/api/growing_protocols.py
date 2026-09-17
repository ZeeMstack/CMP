import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import TenantContext
from app.core.db import get_db
from app.core.permissions import Permission, require_permission
from app.schemas.growing_protocol import (
    BatchProtocolAssignIn,
    BatchProtocolAssignmentRead,
    BatchProtocolStatusRead,
    DueRequirementRead,
    FarmProtocolDueSummaryItem,
    GrowingProtocolCreate,
    GrowingProtocolRead,
    GrowingProtocolVersionActivateIn,
    GrowingProtocolVersionCreate,
    GrowingProtocolVersionRead,
    GrowingProtocolVersionRetireIn,
    ProtocolCareActivityCreate,
    ProtocolCareActivityRead,
    ProtocolObservationRequirementCreate,
    ProtocolObservationRequirementRead,
)
from app.services import growing_protocol_service
from app.services.errors import (
    BatchProtocolAssignmentCommandReusedWithDifferentPayloadError,
    BatchProtocolVersionNotActiveError,
    CropBatchNotFoundError,
    CropNotFoundError,
    DuplicateGrowingProtocolCodeError,
    FarmNotFoundError,
    GrowingProtocolNotFoundError,
    GrowingProtocolVersionCommandReusedWithDifferentPayloadError,
    GrowingProtocolVersionNotDraftError,
    GrowingProtocolVersionNotFoundError,
    ObservationDefinitionNotFoundError,
    ProductionSystemNotFoundError,
    VarietyCropMismatchError,
)

router = APIRouter(tags=["growing-protocols"])

_NOT_FOUND_ERRORS = (
    GrowingProtocolNotFoundError, GrowingProtocolVersionNotFoundError, CropNotFoundError,
    ProductionSystemNotFoundError, VarietyCropMismatchError, ObservationDefinitionNotFoundError,
    FarmNotFoundError, CropBatchNotFoundError,
)
_CONFLICT_ERRORS = (
    DuplicateGrowingProtocolCodeError, GrowingProtocolVersionCommandReusedWithDifferentPayloadError,
    GrowingProtocolVersionNotDraftError, BatchProtocolAssignmentCommandReusedWithDifferentPayloadError,
    BatchProtocolVersionNotActiveError,
)


@router.post("/growing-protocols", response_model=GrowingProtocolRead, status_code=status.HTTP_201_CREATED)
def create_growing_protocol(
    payload: GrowingProtocolCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.GROWING_PROTOCOL_MANAGE)),
) -> GrowingProtocolRead:
    try:
        protocol = growing_protocol_service.register_protocol(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, code=payload.code, name=payload.name,
            crop_id=payload.crop_id, variety_id=payload.variety_id, production_system_id=payload.production_system_id,
            season_context=payload.season_context,
        )
    except _NOT_FOUND_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except _CONFLICT_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return GrowingProtocolRead.model_validate(protocol)


@router.get("/growing-protocols", response_model=list[GrowingProtocolRead])
def list_growing_protocols(
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.GROWING_PROTOCOL_READ)),
) -> list[GrowingProtocolRead]:
    return [GrowingProtocolRead.model_validate(p) for p in growing_protocol_service.list_protocols(db, tenant_id=ctx.tenant_id)]


@router.get("/growing-protocols/{growing_protocol_id}", response_model=GrowingProtocolRead)
def get_growing_protocol(
    growing_protocol_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.GROWING_PROTOCOL_READ)),
) -> GrowingProtocolRead:
    try:
        protocol = growing_protocol_service.get_protocol(db, tenant_id=ctx.tenant_id, growing_protocol_id=growing_protocol_id)
    except GrowingProtocolNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return GrowingProtocolRead.model_validate(protocol)


@router.post(
    "/growing-protocols/{growing_protocol_id}/versions", response_model=GrowingProtocolVersionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_protocol_version(
    growing_protocol_id: uuid.UUID,
    payload: GrowingProtocolVersionCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.GROWING_PROTOCOL_MANAGE)),
) -> GrowingProtocolVersionRead:
    try:
        version = growing_protocol_service.create_draft_version(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, growing_protocol_id=growing_protocol_id,
            client_command_id=payload.client_command_id, reason=payload.reason, effective_date=payload.effective_date,
        )
    except _NOT_FOUND_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except _CONFLICT_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return GrowingProtocolVersionRead.model_validate(version)


@router.get("/growing-protocols/{growing_protocol_id}/versions", response_model=list[GrowingProtocolVersionRead])
def list_protocol_versions(
    growing_protocol_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.GROWING_PROTOCOL_READ)),
) -> list[GrowingProtocolVersionRead]:
    try:
        versions = growing_protocol_service.list_versions(db, tenant_id=ctx.tenant_id, growing_protocol_id=growing_protocol_id)
    except GrowingProtocolNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return [GrowingProtocolVersionRead.model_validate(v) for v in versions]


@router.get(
    "/growing-protocols/{growing_protocol_id}/versions/{version_id}", response_model=GrowingProtocolVersionRead
)
def get_protocol_version(
    growing_protocol_id: uuid.UUID,
    version_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.GROWING_PROTOCOL_READ)),
) -> GrowingProtocolVersionRead:
    try:
        version = growing_protocol_service.get_version(
            db, tenant_id=ctx.tenant_id, growing_protocol_id=growing_protocol_id, version_id=version_id
        )
    except _NOT_FOUND_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return GrowingProtocolVersionRead.model_validate(version)


@router.post(
    "/growing-protocols/{growing_protocol_id}/versions/{version_id}/activate",
    response_model=GrowingProtocolVersionRead,
)
def activate_protocol_version(
    growing_protocol_id: uuid.UUID,
    version_id: uuid.UUID,
    payload: GrowingProtocolVersionActivateIn,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.GROWING_PROTOCOL_MANAGE)),
) -> GrowingProtocolVersionRead:
    try:
        version = growing_protocol_service.activate_version(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, growing_protocol_id=growing_protocol_id,
            version_id=version_id, client_command_id=payload.client_command_id,
        )
    except _NOT_FOUND_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except _CONFLICT_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return GrowingProtocolVersionRead.model_validate(version)


@router.post(
    "/growing-protocols/{growing_protocol_id}/versions/{version_id}/retire",
    response_model=GrowingProtocolVersionRead,
)
def retire_protocol_version(
    growing_protocol_id: uuid.UUID,
    version_id: uuid.UUID,
    payload: GrowingProtocolVersionRetireIn,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.GROWING_PROTOCOL_MANAGE)),
) -> GrowingProtocolVersionRead:
    try:
        version = growing_protocol_service.retire_version(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, growing_protocol_id=growing_protocol_id,
            version_id=version_id, client_command_id=payload.client_command_id,
        )
    except _NOT_FOUND_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except _CONFLICT_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return GrowingProtocolVersionRead.model_validate(version)


@router.post(
    "/growing-protocols/{growing_protocol_id}/versions/{version_id}/observation-requirements",
    response_model=ProtocolObservationRequirementRead, status_code=status.HTTP_201_CREATED,
)
def add_observation_requirement(
    growing_protocol_id: uuid.UUID,
    version_id: uuid.UUID,
    payload: ProtocolObservationRequirementCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.GROWING_PROTOCOL_MANAGE)),
) -> ProtocolObservationRequirementRead:
    try:
        requirement = growing_protocol_service.add_observation_requirement(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, growing_protocol_id=growing_protocol_id,
            version_id=version_id, stage_category=payload.stage_category,
            observation_definition_id=payload.observation_definition_id, requirement_level=payload.requirement_level,
            frequency_days=payload.frequency_days, due_window_start_days=payload.due_window_start_days,
            due_window_end_days=payload.due_window_end_days, stage_sequence_index=payload.stage_sequence_index,
            instructions=payload.instructions, escalation_guidance=payload.escalation_guidance,
            display_order=payload.display_order,
        )
    except _NOT_FOUND_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except _CONFLICT_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ProtocolObservationRequirementRead.model_validate(requirement)


@router.get(
    "/growing-protocols/{growing_protocol_id}/versions/{version_id}/observation-requirements",
    response_model=list[ProtocolObservationRequirementRead],
)
def list_observation_requirements(
    growing_protocol_id: uuid.UUID,
    version_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.GROWING_PROTOCOL_READ)),
) -> list[ProtocolObservationRequirementRead]:
    try:
        growing_protocol_service.get_version(db, tenant_id=ctx.tenant_id, growing_protocol_id=growing_protocol_id, version_id=version_id)
    except _NOT_FOUND_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    requirements = growing_protocol_service.list_observation_requirements(db, tenant_id=ctx.tenant_id, version_id=version_id)
    return [ProtocolObservationRequirementRead.model_validate(r) for r in requirements]


@router.post(
    "/growing-protocols/{growing_protocol_id}/versions/{version_id}/care-activities",
    response_model=ProtocolCareActivityRead, status_code=status.HTTP_201_CREATED,
)
def add_care_activity(
    growing_protocol_id: uuid.UUID,
    version_id: uuid.UUID,
    payload: ProtocolCareActivityCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.GROWING_PROTOCOL_MANAGE)),
) -> ProtocolCareActivityRead:
    try:
        activity = growing_protocol_service.add_care_activity(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, growing_protocol_id=growing_protocol_id,
            version_id=version_id, stage_category=payload.stage_category, activity_type=payload.activity_type,
            title=payload.title, instructions=payload.instructions, frequency_days=payload.frequency_days,
            stage_sequence_index=payload.stage_sequence_index, display_order=payload.display_order,
        )
    except _NOT_FOUND_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except _CONFLICT_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ProtocolCareActivityRead.model_validate(activity)


@router.get(
    "/growing-protocols/{growing_protocol_id}/versions/{version_id}/care-activities",
    response_model=list[ProtocolCareActivityRead],
)
def list_care_activities(
    growing_protocol_id: uuid.UUID,
    version_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.GROWING_PROTOCOL_READ)),
) -> list[ProtocolCareActivityRead]:
    try:
        growing_protocol_service.get_version(db, tenant_id=ctx.tenant_id, growing_protocol_id=growing_protocol_id, version_id=version_id)
    except _NOT_FOUND_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    activities = growing_protocol_service.list_care_activities(db, tenant_id=ctx.tenant_id, version_id=version_id)
    return [ProtocolCareActivityRead.model_validate(a) for a in activities]


# --- Batch <-> Protocol Version assignment (farm/batch scoped) -----------------------


@router.post(
    "/farms/{farm_id}/crop-batches/{batch_id}/protocol-assignments",
    response_model=BatchProtocolAssignmentRead, status_code=status.HTTP_201_CREATED,
)
def assign_batch_protocol(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    payload: BatchProtocolAssignIn,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.GROWING_PROTOCOL_MANAGE)),
) -> BatchProtocolAssignmentRead:
    try:
        assignment = growing_protocol_service.assign_batch_protocol(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, batch_id=batch_id,
            growing_protocol_version_id=payload.growing_protocol_version_id, effective_from=payload.effective_from,
            reason=payload.reason, client_command_id=payload.client_command_id,
        )
    except _NOT_FOUND_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except _CONFLICT_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return BatchProtocolAssignmentRead.model_validate(assignment)


@router.get(
    "/farms/{farm_id}/crop-batches/{batch_id}/protocol-assignments",
    response_model=list[BatchProtocolAssignmentRead],
)
def list_batch_protocol_assignments(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.GROWING_PROTOCOL_READ)),
) -> list[BatchProtocolAssignmentRead]:
    assignments = growing_protocol_service.list_batch_assignments(db, tenant_id=ctx.tenant_id, batch_id=batch_id)
    return [BatchProtocolAssignmentRead.model_validate(a) for a in assignments]


@router.get(
    "/farms/{farm_id}/crop-batches/{batch_id}/protocol-status", response_model=BatchProtocolStatusRead
)
def get_batch_protocol_status(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.GROWING_PROTOCOL_READ)),
) -> BatchProtocolStatusRead:
    try:
        status_data = growing_protocol_service.get_batch_protocol_status(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id
        )
    except _NOT_FOUND_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return BatchProtocolStatusRead(
        current_assignment=(
            BatchProtocolAssignmentRead.model_validate(status_data["current_assignment"])
            if status_data["current_assignment"] else None
        ),
        protocol=GrowingProtocolRead.model_validate(status_data["protocol"]) if status_data["protocol"] else None,
        protocol_version=(
            GrowingProtocolVersionRead.model_validate(status_data["protocol_version"])
            if status_data["protocol_version"] else None
        ),
        current_stage_category=status_data["current_stage_category"],
        current_stage_occurrence_index=status_data["current_stage_occurrence_index"],
        days_in_stage=status_data["days_in_stage"],
        due_observation_requirements=[
            DueRequirementRead(
                requirement=ProtocolObservationRequirementRead.model_validate(r["requirement"]),
                observation_definition_code=r["observation_definition_code"],
                observation_definition_name=r["observation_definition_name"],
                is_due=r["is_due"], is_overdue=r["is_overdue"],
                is_outside_expected_window=r["is_outside_expected_window"], last_satisfied_at=r["last_satisfied_at"],
            )
            for r in status_data["due_observation_requirements"]
        ],
        open_crop_issue_count=status_data["open_crop_issue_count"],
    )


@router.get(
    "/farms/{farm_id}/growing-protocols/due-summary", response_model=list[FarmProtocolDueSummaryItem]
)
def get_farm_protocol_due_summary(
    farm_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.GROWING_PROTOCOL_READ)),
) -> list[FarmProtocolDueSummaryItem]:
    """Today on the Farm's "Inspections Due" section -- see
    `growing_protocol_service.list_farm_protocol_due_summary`'s own
    docstring for exactly what is (and deliberately is not) included."""
    rows = growing_protocol_service.list_farm_protocol_due_summary(db, tenant_id=ctx.tenant_id, farm_id=farm_id)
    return [
        FarmProtocolDueSummaryItem(
            batch_id=r["batch_id"], batch_code=r["batch_code"],
            protocol=GrowingProtocolRead.model_validate(r["protocol"]) if r["protocol"] else None,
            protocol_version=(
                GrowingProtocolVersionRead.model_validate(r["protocol_version"]) if r["protocol_version"] else None
            ),
            due_count=r["due_count"], overdue_count=r["overdue_count"],
            open_crop_issue_count=r["open_crop_issue_count"],
        )
        for r in rows
    ]
