import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.carrier_type import CarrierType
from app.models.crop import Crop
from app.models.location_type import LocationType
from app.models.production_system import ProductionSystem
from app.models.variety import Variety
from app.models.workflow import Workflow
from app.models.workflow_stage import WorkflowStage
from app.models.workflow_transition import WorkflowTransition
from app.models.workflow_version import WorkflowVersion
from app.services.audit import append_audit_event
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


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


# --- Workflows ----------------------------------------------------------------


def register_workflow(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    crop_id: uuid.UUID,
    variety_id: uuid.UUID | None,
    production_system_id: uuid.UUID,
    code: str,
    name: str,
) -> Workflow:
    crop = db.execute(
        select(Crop).where(Crop.id == crop_id, Crop.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if crop is None:
        raise CropNotFoundError(str(crop_id))

    production_system = db.execute(
        select(ProductionSystem).where(
            ProductionSystem.id == production_system_id, ProductionSystem.tenant_id == tenant_id
        )
    ).scalar_one_or_none()
    if production_system is None:
        raise ProductionSystemNotFoundError(str(production_system_id))

    if variety_id is not None:
        variety = db.execute(
            select(Variety).where(
                Variety.id == variety_id, Variety.tenant_id == tenant_id, Variety.crop_id == crop_id
            )
        ).scalar_one_or_none()
        if variety is None:
            raise VarietyCropMismatchError(str(variety_id))

    workflow = Workflow(
        tenant_id=tenant_id,
        crop_id=crop_id,
        variety_id=variety_id,
        production_system_id=production_system_id,
        code=code,
        name=name,
    )
    db.add(workflow)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateWorkflowCodeError(f"{tenant_id}:{code}") from exc

    append_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="workflow.registered",
        entity_type="workflow",
        entity_id=workflow.id,
        event_data={
            "code": workflow.code,
            "crop_id": str(crop_id),
            "variety_id": str(variety_id) if variety_id else None,
            "production_system_id": str(production_system_id),
        },
    )
    db.commit()
    db.refresh(workflow)
    return workflow


def get_workflow(db: Session, *, tenant_id: uuid.UUID, workflow_id: uuid.UUID) -> Workflow:
    workflow = db.execute(
        select(Workflow).where(Workflow.id == workflow_id, Workflow.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if workflow is None:
        raise WorkflowNotFoundError(str(workflow_id))
    return workflow


def list_workflows(db: Session, *, tenant_id: uuid.UUID) -> list[Workflow]:
    return list(
        db.execute(select(Workflow).where(Workflow.tenant_id == tenant_id).order_by(Workflow.code)).scalars()
    )


# --- Workflow versions ----------------------------------------------------------


def create_draft_version(
    db: Session, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID | None, workflow_id: uuid.UUID
) -> WorkflowVersion:
    workflow = db.execute(
        select(Workflow).where(Workflow.id == workflow_id, Workflow.tenant_id == tenant_id).with_for_update()
    ).scalar_one_or_none()
    if workflow is None:
        raise WorkflowNotFoundError(str(workflow_id))

    next_number = (
        db.execute(
            select(func.max(WorkflowVersion.version_number)).where(WorkflowVersion.workflow_id == workflow.id)
        ).scalar_one()
        or 0
    ) + 1

    version = WorkflowVersion(
        tenant_id=tenant_id,
        workflow_id=workflow.id,
        version_number=next_number,
        state="draft",
    )
    db.add(version)
    db.flush()

    append_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="workflow_version.created",
        entity_type="workflow_version",
        entity_id=version.id,
        event_data={"workflow_id": str(workflow_id), "version_number": version.version_number},
    )
    db.commit()
    db.refresh(version)
    return version


def list_versions(db: Session, *, tenant_id: uuid.UUID, workflow_id: uuid.UUID) -> list[WorkflowVersion]:
    """PILOT-SETUP-001B6A: mirrors `grade_definition_service.list_versions`/
    `pack_specification_service.list_versions` exactly -- confirms the
    parent Workflow exists in this tenant first (so an unknown/cross-tenant
    `workflow_id` raises `WorkflowNotFoundError`, never a bare empty list),
    then returns every version row (draft/published/retired) ordered
    ascending by `version_number`, the same deterministic ordering those two
    siblings already use. No stage/transition content is loaded here --
    `get_workflow_version` remains the sole source for that."""
    get_workflow(db, tenant_id=tenant_id, workflow_id=workflow_id)
    return list(
        db.execute(
            select(WorkflowVersion)
            .where(WorkflowVersion.tenant_id == tenant_id, WorkflowVersion.workflow_id == workflow_id)
            .order_by(WorkflowVersion.version_number)
        ).scalars()
    )


def get_workflow_version(
    db: Session, *, tenant_id: uuid.UUID, workflow_id: uuid.UUID, version_id: uuid.UUID
) -> WorkflowVersion:
    get_workflow(db, tenant_id=tenant_id, workflow_id=workflow_id)
    version = db.execute(
        select(WorkflowVersion).where(
            WorkflowVersion.id == version_id,
            WorkflowVersion.tenant_id == tenant_id,
            WorkflowVersion.workflow_id == workflow_id,
        )
    ).scalar_one_or_none()
    if version is None:
        raise WorkflowVersionNotFoundError(str(version_id))
    return version


def get_stages(db: Session, *, version_id: uuid.UUID) -> list[WorkflowStage]:
    return list(
        db.execute(
            select(WorkflowStage)
            .where(WorkflowStage.workflow_version_id == version_id)
            .order_by(WorkflowStage.display_order, WorkflowStage.code)
        ).scalars()
    )


def get_transitions(db: Session, *, version_id: uuid.UUID) -> list[WorkflowTransition]:
    return list(
        db.execute(
            select(WorkflowTransition)
            .where(WorkflowTransition.workflow_version_id == version_id)
            .order_by(WorkflowTransition.code)
        ).scalars()
    )


# --- Workflow stages --------------------------------------------------------------


def add_stage(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    workflow_id: uuid.UUID,
    version_id: uuid.UUID,
    code: str,
    name: str,
    display_order: int,
    stage_category: str,
    expected_duration_minutes: int | None,
    permitted_location_type_code: str | None,
    required_carrier_type_code: str | None,
    is_start: bool,
    is_terminal: bool,
) -> WorkflowStage:
    version = get_workflow_version(db, tenant_id=tenant_id, workflow_id=workflow_id, version_id=version_id)
    if version.state != "draft":
        raise WorkflowVersionNotDraftError(str(version_id))

    permitted_location_type_id = None
    if permitted_location_type_code is not None:
        location_type = db.execute(
            select(LocationType).where(LocationType.code == permitted_location_type_code)
        ).scalar_one_or_none()
        if location_type is None:
            raise LocationTypeReferenceNotFoundError(permitted_location_type_code)
        permitted_location_type_id = location_type.id

    required_carrier_type_id = None
    if required_carrier_type_code is not None:
        carrier_type = db.execute(
            select(CarrierType).where(CarrierType.code == required_carrier_type_code)
        ).scalar_one_or_none()
        if carrier_type is None:
            raise CarrierTypeReferenceNotFoundError(required_carrier_type_code)
        required_carrier_type_id = carrier_type.id

    stage = WorkflowStage(
        tenant_id=tenant_id,
        workflow_version_id=version.id,
        code=code,
        name=name,
        display_order=display_order,
        stage_category=stage_category,
        expected_duration_minutes=expected_duration_minutes,
        permitted_location_type_id=permitted_location_type_id,
        required_carrier_type_id=required_carrier_type_id,
        is_start=is_start,
        is_terminal=is_terminal,
    )
    db.add(stage)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateStageCodeError(f"{version_id}:{code}") from exc

    append_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="workflow_stage.created",
        entity_type="workflow_stage",
        entity_id=stage.id,
        event_data={
            "workflow_version_id": str(version_id),
            "code": stage.code,
            "stage_category": stage.stage_category,
        },
    )
    db.commit()
    db.refresh(stage)
    return stage


# --- Workflow transitions --------------------------------------------------------


def add_transition(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    workflow_id: uuid.UUID,
    version_id: uuid.UUID,
    from_stage_id: uuid.UUID,
    to_stage_id: uuid.UUID,
    code: str,
    name: str,
) -> WorkflowTransition:
    version = get_workflow_version(db, tenant_id=tenant_id, workflow_id=workflow_id, version_id=version_id)
    if version.state != "draft":
        raise WorkflowVersionNotDraftError(str(version_id))

    if from_stage_id == to_stage_id:
        raise SelfTransitionError(str(from_stage_id))

    found_ids = set(
        db.execute(
            select(WorkflowStage.id).where(
                WorkflowStage.tenant_id == tenant_id,
                WorkflowStage.workflow_version_id == version.id,
                WorkflowStage.id.in_([from_stage_id, to_stage_id]),
            )
        ).scalars()
    )
    if from_stage_id not in found_ids or to_stage_id not in found_ids:
        raise WorkflowStageNotFoundError(f"{from_stage_id},{to_stage_id}")

    transition = WorkflowTransition(
        tenant_id=tenant_id,
        workflow_version_id=version.id,
        from_stage_id=from_stage_id,
        to_stage_id=to_stage_id,
        code=code,
        name=name,
    )
    db.add(transition)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "uq_workflow_transitions_pair":
            raise DuplicateTransitionPairError(f"{from_stage_id}->{to_stage_id}") from exc
        if constraint == "ux_workflow_transitions_version_code_lower":
            raise DuplicateTransitionCodeError(f"{version_id}:{code}") from exc
        raise

    append_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="workflow_transition.created",
        entity_type="workflow_transition",
        entity_id=transition.id,
        event_data={
            "workflow_version_id": str(version_id),
            "code": transition.code,
            "from_stage_id": str(from_stage_id),
            "to_stage_id": str(to_stage_id),
        },
    )
    db.commit()
    db.refresh(transition)
    return transition


# --- Publication ------------------------------------------------------------------


def _validate_publication_graph(
    db: Session, *, workflow: Workflow, stages: list[WorkflowStage], transitions: list[WorkflowTransition]
) -> None:
    if not stages:
        raise WorkflowPublicationValidationError("workflow version has no stages")

    start_stages = [s for s in stages if s.is_start]
    if len(start_stages) != 1:
        raise WorkflowPublicationValidationError("workflow version must have exactly one start stage")

    terminal_stages = [s for s in stages if s.is_terminal]
    if not terminal_stages:
        raise WorkflowPublicationValidationError("workflow version must have at least one terminal stage")

    stage_ids = {s.id for s in stages}
    outgoing: dict[uuid.UUID, list[uuid.UUID]] = {s.id: [] for s in stages}
    for t in transitions:
        if t.from_stage_id == t.to_stage_id:
            raise WorkflowPublicationValidationError("self-transitions are not permitted")
        if t.from_stage_id not in stage_ids or t.to_stage_id not in stage_ids:
            raise WorkflowPublicationValidationError("transition references a stage outside this version")
        outgoing[t.from_stage_id].append(t.to_stage_id)

    for s in stages:
        has_outgoing = len(outgoing[s.id]) > 0
        if s.is_terminal and has_outgoing:
            raise WorkflowPublicationValidationError(
                f"terminal stage '{s.code}' must not have outgoing transitions"
            )
        if not s.is_terminal and not has_outgoing:
            raise WorkflowPublicationValidationError(
                f"non-terminal stage '{s.code}' must have at least one outgoing transition"
            )

    start_id = start_stages[0].id
    visited = {start_id}
    queue = [start_id]
    while queue:
        current = queue.pop(0)
        for nxt in outgoing[current]:
            if nxt not in visited:
                visited.add(nxt)
                queue.append(nxt)
    if stage_ids - visited:
        raise WorkflowPublicationValidationError("one or more stages are not reachable from the start stage")

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {s.id: WHITE for s in stages}

    def _has_cycle(node: uuid.UUID) -> bool:
        color[node] = GRAY
        for nxt in outgoing[node]:
            if color[nxt] == GRAY:
                return True
            if color[nxt] == WHITE and _has_cycle(nxt):
                return True
        color[node] = BLACK
        return False

    for s in stages:
        if color[s.id] == WHITE and _has_cycle(s.id):
            raise WorkflowPublicationValidationError("workflow graph contains a cycle")

    crop = db.get(Crop, workflow.crop_id)
    if crop is None or crop.status != "active":
        raise WorkflowPublicationValidationError("referenced crop is not active")

    if workflow.variety_id is not None:
        variety = db.get(Variety, workflow.variety_id)
        if variety is None or variety.status != "active":
            raise WorkflowPublicationValidationError("referenced variety is not active")

    production_system = db.get(ProductionSystem, workflow.production_system_id)
    if production_system is None or production_system.status != "active":
        raise WorkflowPublicationValidationError("referenced production system is not active")

    location_type_ids = {s.permitted_location_type_id for s in stages if s.permitted_location_type_id is not None}
    for location_type_id in location_type_ids:
        if db.get(LocationType, location_type_id) is None:
            raise WorkflowPublicationValidationError("referenced location type does not exist")

    carrier_type_ids = {s.required_carrier_type_id for s in stages if s.required_carrier_type_id is not None}
    for carrier_type_id in carrier_type_ids:
        if db.get(CarrierType, carrier_type_id) is None:
            raise WorkflowPublicationValidationError("referenced carrier type does not exist")


def publish_version(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    workflow_id: uuid.UUID,
    version_id: uuid.UUID,
) -> WorkflowVersion:
    workflow = db.execute(
        select(Workflow).where(Workflow.id == workflow_id, Workflow.tenant_id == tenant_id).with_for_update()
    ).scalar_one_or_none()
    if workflow is None:
        raise WorkflowNotFoundError(str(workflow_id))

    version = db.execute(
        select(WorkflowVersion)
        .where(
            WorkflowVersion.id == version_id,
            WorkflowVersion.tenant_id == tenant_id,
            WorkflowVersion.workflow_id == workflow_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if version is None:
        raise WorkflowVersionNotFoundError(str(version_id))
    if version.state != "draft":
        raise WorkflowVersionNotDraftError(str(version_id))

    stages = get_stages(db, version_id=version.id)
    transitions = get_transitions(db, version_id=version.id)

    _validate_publication_graph(db, workflow=workflow, stages=stages, transitions=transitions)

    previous = db.execute(
        select(WorkflowVersion)
        .where(WorkflowVersion.workflow_id == workflow_id, WorkflowVersion.state == "published")
        .with_for_update()
    ).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    replaced_version_id: uuid.UUID | None = None
    if previous is not None:
        previous.state = "retired"
        previous.retired_at = now
        replaced_version_id = previous.id
        db.flush()

    version.state = "published"
    version.published_at = now
    db.flush()

    append_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="workflow.published",
        entity_type="workflow_version",
        entity_id=version.id,
        event_data={
            "workflow_id": str(workflow_id),
            "workflow_version_id": str(version.id),
            "version_number": version.version_number,
            "replaced_version_id": str(replaced_version_id) if replaced_version_id else None,
            "stage_count": len(stages),
            "transition_count": len(transitions),
            "published_at": now.isoformat(),
        },
    )
    db.commit()
    db.refresh(version)
    return version
