"""PILOT-AGRO-001: Growing Protocol identity/versioning, protocol stage
requirements (Observation + Care Activity), and Batch <-> Protocol Version
assignment history.

Version lifecycle (`draft -> active -> retired`) mirrors `workflow_
service`'s `create_draft_version`/`publish_version` and `grade_definition_
service`'s per-command idempotency-column convention: activating a new
version automatically retires the previously ACTIVE one in the same
transaction (its `retirement_client_command_id` stays NULL, distinguishing
"superseded by replacement" from an explicit `retire_version` call --
mirrors `GradeDefinitionVersion`'s own documented convention exactly).
Agronomic content (`ProtocolObservationRequirement`/`ProtocolCareActivity`)
may only be added while the owning version is DRAFT -- enforced here, the
same place `workflow_service.add_stage` enforces `WorkflowVersionNotDraft
Error`, never a DB trigger.

FROZEN: AGE != STAGE. `due_observation_requirements`
(`batch_protocol_status`) is a deterministic READ over existing facts
(BatchStageRun, BatchProtocolAssignment, GrowerInspection/ObservationEvent
history, ProtocolObservationRequirement) -- it never writes anything, never
advances a Batch's stage, and is recomputed fresh on every call."""

import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.batch_protocol_assignment import BatchProtocolAssignment
from app.models.batch_stage_run import BatchStageRun
from app.models.crop import Crop
from app.models.crop_batch import CropBatch
from app.models.crop_issue import CropIssue
from app.models.growing_protocol import GrowingProtocol
from app.models.growing_protocol_version import GrowingProtocolVersion
from app.models.observation_definition import ObservationDefinition
from app.models.observation_event import ObservationEvent
from app.models.observation_value import ObservationValue
from app.models.production_system import ProductionSystem
from app.models.protocol_care_activity import ProtocolCareActivity
from app.models.protocol_observation_requirement import ProtocolObservationRequirement
from app.models.variety import Variety
from app.models.workflow_stage import WorkflowStage
from app.services.audit import append_audit_event
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
from app.services import farm_service


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _fingerprint(*parts: object) -> str:
    return hashlib.sha256("|".join("" if p is None else str(p) for p in parts).encode("utf-8")).hexdigest()


def _require_active_farm(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID):
    farm = farm_service.get_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    if farm.status != "active":
        raise FarmNotFoundError(str(farm_id))
    return farm


# --- Growing Protocol identity ------------------------------------------------------


def register_protocol(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    code: str,
    name: str,
    crop_id: uuid.UUID,
    variety_id: uuid.UUID | None,
    production_system_id: uuid.UUID | None,
    season_context: str | None,
) -> GrowingProtocol:
    crop = db.execute(select(Crop).where(Crop.id == crop_id, Crop.tenant_id == tenant_id)).scalar_one_or_none()
    if crop is None:
        raise CropNotFoundError(str(crop_id))
    if variety_id is not None:
        variety = db.execute(
            select(Variety).where(Variety.id == variety_id, Variety.tenant_id == tenant_id, Variety.crop_id == crop_id)
        ).scalar_one_or_none()
        if variety is None:
            raise VarietyCropMismatchError(str(variety_id))
    if production_system_id is not None:
        ps = db.execute(
            select(ProductionSystem).where(
                ProductionSystem.id == production_system_id, ProductionSystem.tenant_id == tenant_id
            )
        ).scalar_one_or_none()
        if ps is None:
            raise ProductionSystemNotFoundError(str(production_system_id))

    protocol = GrowingProtocol(
        tenant_id=tenant_id, crop_id=crop_id, variety_id=variety_id, production_system_id=production_system_id,
        season_context=season_context, code=code, name=name, created_by_user_id=actor_user_id,
    )
    db.add(protocol)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateGrowingProtocolCodeError(f"{tenant_id}:{code}") from exc

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="growing_protocol.registered",
        entity_type="growing_protocol", entity_id=protocol.id,
        event_data={"code": protocol.code, "crop_id": str(crop_id), "variety_id": str(variety_id) if variety_id else None},
    )
    db.commit()
    db.refresh(protocol)
    return protocol


def get_protocol(db: Session, *, tenant_id: uuid.UUID, growing_protocol_id: uuid.UUID) -> GrowingProtocol:
    protocol = db.execute(
        select(GrowingProtocol).where(
            GrowingProtocol.id == growing_protocol_id, GrowingProtocol.tenant_id == tenant_id
        )
    ).scalar_one_or_none()
    if protocol is None:
        raise GrowingProtocolNotFoundError(str(growing_protocol_id))
    return protocol


def list_protocols(db: Session, *, tenant_id: uuid.UUID) -> list[GrowingProtocol]:
    return list(
        db.execute(
            select(GrowingProtocol).where(GrowingProtocol.tenant_id == tenant_id).order_by(GrowingProtocol.code)
        ).scalars()
    )


def _lock_protocol(db: Session, *, tenant_id: uuid.UUID, growing_protocol_id: uuid.UUID) -> GrowingProtocol:
    protocol = db.execute(
        select(GrowingProtocol)
        .where(GrowingProtocol.id == growing_protocol_id, GrowingProtocol.tenant_id == tenant_id)
        .with_for_update()
    ).scalar_one_or_none()
    if protocol is None:
        raise GrowingProtocolNotFoundError(str(growing_protocol_id))
    return protocol


def _lock_version(
    db: Session, *, tenant_id: uuid.UUID, growing_protocol_id: uuid.UUID, version_id: uuid.UUID
) -> GrowingProtocolVersion:
    version = db.execute(
        select(GrowingProtocolVersion)
        .where(
            GrowingProtocolVersion.id == version_id, GrowingProtocolVersion.tenant_id == tenant_id,
            GrowingProtocolVersion.growing_protocol_id == growing_protocol_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if version is None:
        raise GrowingProtocolVersionNotFoundError(str(version_id))
    return version


# --- Version lifecycle ---------------------------------------------------------------


def create_draft_version(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    growing_protocol_id: uuid.UUID,
    client_command_id: uuid.UUID,
    reason: str,
    effective_date,
) -> GrowingProtocolVersion:
    fingerprint = _fingerprint(tenant_id, growing_protocol_id, reason, effective_date)

    def _find_by_command() -> GrowingProtocolVersion | None:
        return db.execute(
            select(GrowingProtocolVersion).where(
                GrowingProtocolVersion.tenant_id == tenant_id,
                GrowingProtocolVersion.client_command_id == client_command_id,
            )
        ).scalar_one_or_none()

    existing = _find_by_command()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise GrowingProtocolVersionCommandReusedWithDifferentPayloadError(str(client_command_id))

    protocol = _lock_protocol(db, tenant_id=tenant_id, growing_protocol_id=growing_protocol_id)

    existing = _find_by_command()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise GrowingProtocolVersionCommandReusedWithDifferentPayloadError(str(client_command_id))

    next_number = (
        db.execute(
            select(func.max(GrowingProtocolVersion.version_number)).where(
                GrowingProtocolVersion.growing_protocol_id == protocol.id
            )
        ).scalar_one()
        or 0
    ) + 1

    version = GrowingProtocolVersion(
        tenant_id=tenant_id, growing_protocol_id=protocol.id, version_number=next_number, state="draft",
        author_user_id=actor_user_id, reason=reason, effective_date=effective_date,
        client_command_id=client_command_id, request_fingerprint=fingerprint,
    )
    db.add(version)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_growing_protocol_versions_tenant_client_command_id":
            replay = _find_by_command()
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise GrowingProtocolVersionCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="growing_protocol_version.created",
        entity_type="growing_protocol_version", entity_id=version.id,
        event_data={"growing_protocol_id": str(growing_protocol_id), "version_number": version.version_number},
    )
    db.commit()
    db.refresh(version)
    return version


def get_version(
    db: Session, *, tenant_id: uuid.UUID, growing_protocol_id: uuid.UUID, version_id: uuid.UUID
) -> GrowingProtocolVersion:
    get_protocol(db, tenant_id=tenant_id, growing_protocol_id=growing_protocol_id)
    version = db.execute(
        select(GrowingProtocolVersion).where(
            GrowingProtocolVersion.id == version_id, GrowingProtocolVersion.tenant_id == tenant_id,
            GrowingProtocolVersion.growing_protocol_id == growing_protocol_id,
        )
    ).scalar_one_or_none()
    if version is None:
        raise GrowingProtocolVersionNotFoundError(str(version_id))
    return version


def list_versions(db: Session, *, tenant_id: uuid.UUID, growing_protocol_id: uuid.UUID) -> list[GrowingProtocolVersion]:
    get_protocol(db, tenant_id=tenant_id, growing_protocol_id=growing_protocol_id)
    return list(
        db.execute(
            select(GrowingProtocolVersion)
            .where(
                GrowingProtocolVersion.tenant_id == tenant_id,
                GrowingProtocolVersion.growing_protocol_id == growing_protocol_id,
            )
            .order_by(GrowingProtocolVersion.version_number)
        ).scalars()
    )


def activate_version(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    growing_protocol_id: uuid.UUID,
    version_id: uuid.UUID,
    client_command_id: uuid.UUID,
) -> GrowingProtocolVersion:
    fingerprint = _fingerprint(tenant_id, growing_protocol_id, version_id, "activate")

    def _find_by_command() -> GrowingProtocolVersion | None:
        return db.execute(
            select(GrowingProtocolVersion).where(
                GrowingProtocolVersion.tenant_id == tenant_id,
                GrowingProtocolVersion.activation_client_command_id == client_command_id,
            )
        ).scalar_one_or_none()

    existing = _find_by_command()
    if existing is not None:
        if existing.activation_request_fingerprint == fingerprint:
            return existing
        raise GrowingProtocolVersionCommandReusedWithDifferentPayloadError(str(client_command_id))

    _lock_protocol(db, tenant_id=tenant_id, growing_protocol_id=growing_protocol_id)
    version = _lock_version(db, tenant_id=tenant_id, growing_protocol_id=growing_protocol_id, version_id=version_id)

    existing = _find_by_command()
    if existing is not None:
        if existing.activation_request_fingerprint == fingerprint:
            return existing
        raise GrowingProtocolVersionCommandReusedWithDifferentPayloadError(str(client_command_id))

    if version.state != "draft":
        raise GrowingProtocolVersionNotDraftError(str(version_id))

    now = datetime.now(timezone.utc)
    previous_active = db.execute(
        select(GrowingProtocolVersion)
        .where(
            GrowingProtocolVersion.growing_protocol_id == growing_protocol_id,
            GrowingProtocolVersion.state == "active",
        )
        .with_for_update()
    ).scalar_one_or_none()

    replaced_version_id: uuid.UUID | None = None
    if previous_active is not None:
        previous_active.state = "retired"
        previous_active.retired_at = now
        replaced_version_id = previous_active.id
        db.flush()

    version.state = "active"
    version.activated_at = now
    version.activation_client_command_id = client_command_id
    version.activation_request_fingerprint = fingerprint
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_growing_protocol_versions_tenant_activation_command":
            replay = _find_by_command()
            if replay is not None and replay.activation_request_fingerprint == fingerprint:
                return replay
            raise GrowingProtocolVersionCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    if previous_active is not None:
        append_audit_event(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="growing_protocol_version.retired",
            entity_type="growing_protocol_version", entity_id=previous_active.id,
            event_data={
                "growing_protocol_id": str(growing_protocol_id), "reason": "superseded",
                "superseded_by_version_id": str(version.id),
            },
        )
    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="growing_protocol_version.activated",
        entity_type="growing_protocol_version", entity_id=version.id,
        event_data={
            "growing_protocol_id": str(growing_protocol_id), "version_number": version.version_number,
            "replaced_version_id": str(replaced_version_id) if replaced_version_id else None,
        },
    )
    db.commit()
    db.refresh(version)
    return version


def retire_version(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    growing_protocol_id: uuid.UUID,
    version_id: uuid.UUID,
    client_command_id: uuid.UUID,
) -> GrowingProtocolVersion:
    """Explicit retirement WITHOUT a replacement (discontinuing this
    version outright) -- distinct from the automatic retire-on-activate
    inside `activate_version`."""
    fingerprint = _fingerprint(tenant_id, growing_protocol_id, version_id, "retire")

    def _find_by_command() -> GrowingProtocolVersion | None:
        return db.execute(
            select(GrowingProtocolVersion).where(
                GrowingProtocolVersion.tenant_id == tenant_id,
                GrowingProtocolVersion.retirement_client_command_id == client_command_id,
            )
        ).scalar_one_or_none()

    existing = _find_by_command()
    if existing is not None:
        if existing.retirement_request_fingerprint == fingerprint:
            return existing
        raise GrowingProtocolVersionCommandReusedWithDifferentPayloadError(str(client_command_id))

    _lock_protocol(db, tenant_id=tenant_id, growing_protocol_id=growing_protocol_id)
    version = _lock_version(db, tenant_id=tenant_id, growing_protocol_id=growing_protocol_id, version_id=version_id)

    existing = _find_by_command()
    if existing is not None:
        if existing.retirement_request_fingerprint == fingerprint:
            return existing
        raise GrowingProtocolVersionCommandReusedWithDifferentPayloadError(str(client_command_id))

    if version.state != "active":
        raise GrowingProtocolVersionNotDraftError(str(version_id))

    version.state = "retired"
    version.retired_at = datetime.now(timezone.utc)
    version.retirement_client_command_id = client_command_id
    version.retirement_request_fingerprint = fingerprint
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_growing_protocol_versions_tenant_retirement_command":
            replay = _find_by_command()
            if replay is not None and replay.retirement_request_fingerprint == fingerprint:
                return replay
            raise GrowingProtocolVersionCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="growing_protocol_version.retired",
        entity_type="growing_protocol_version", entity_id=version.id,
        event_data={"growing_protocol_id": str(growing_protocol_id), "reason": "explicit"},
    )
    db.commit()
    db.refresh(version)
    return version


# --- Protocol stage requirements (DRAFT-only) -----------------------------------------


def add_observation_requirement(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    growing_protocol_id: uuid.UUID,
    version_id: uuid.UUID,
    stage_category: str,
    observation_definition_id: uuid.UUID,
    requirement_level: str,
    frequency_days: int | None,
    due_window_start_days: int | None,
    due_window_end_days: int | None,
    instructions: str | None,
    escalation_guidance: str | None,
    display_order: int,
) -> ProtocolObservationRequirement:
    version = get_version(db, tenant_id=tenant_id, growing_protocol_id=growing_protocol_id, version_id=version_id)
    if version.state != "draft":
        raise GrowingProtocolVersionNotDraftError(str(version_id))

    definition = db.execute(
        select(ObservationDefinition).where(
            ObservationDefinition.id == observation_definition_id, ObservationDefinition.tenant_id == tenant_id
        )
    ).scalar_one_or_none()
    if definition is None:
        raise ObservationDefinitionNotFoundError(str(observation_definition_id))

    requirement = ProtocolObservationRequirement(
        tenant_id=tenant_id, growing_protocol_version_id=version.id, stage_category=stage_category,
        observation_definition_id=observation_definition_id, requirement_level=requirement_level,
        frequency_days=frequency_days, due_window_start_days=due_window_start_days,
        due_window_end_days=due_window_end_days, instructions=instructions,
        escalation_guidance=escalation_guidance, display_order=display_order,
    )
    db.add(requirement)
    db.flush()

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="protocol_observation_requirement.added",
        entity_type="protocol_observation_requirement", entity_id=requirement.id,
        event_data={
            "growing_protocol_version_id": str(version_id), "stage_category": stage_category,
            "observation_definition_id": str(observation_definition_id), "requirement_level": requirement_level,
        },
    )
    db.commit()
    db.refresh(requirement)
    return requirement


def list_observation_requirements(
    db: Session, *, tenant_id: uuid.UUID, version_id: uuid.UUID
) -> list[ProtocolObservationRequirement]:
    return list(
        db.execute(
            select(ProtocolObservationRequirement)
            .where(
                ProtocolObservationRequirement.tenant_id == tenant_id,
                ProtocolObservationRequirement.growing_protocol_version_id == version_id,
            )
            .order_by(ProtocolObservationRequirement.display_order)
        ).scalars()
    )


def add_care_activity(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    growing_protocol_id: uuid.UUID,
    version_id: uuid.UUID,
    stage_category: str,
    activity_type: str,
    title: str,
    instructions: str | None,
    frequency_days: int | None,
    display_order: int,
) -> ProtocolCareActivity:
    version = get_version(db, tenant_id=tenant_id, growing_protocol_id=growing_protocol_id, version_id=version_id)
    if version.state != "draft":
        raise GrowingProtocolVersionNotDraftError(str(version_id))

    activity = ProtocolCareActivity(
        tenant_id=tenant_id, growing_protocol_version_id=version.id, stage_category=stage_category,
        activity_type=activity_type, title=title, instructions=instructions, frequency_days=frequency_days,
        display_order=display_order,
    )
    db.add(activity)
    db.flush()

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="protocol_care_activity.added",
        entity_type="protocol_care_activity", entity_id=activity.id,
        event_data={"growing_protocol_version_id": str(version_id), "stage_category": stage_category, "activity_type": activity_type},
    )
    db.commit()
    db.refresh(activity)
    return activity


def list_care_activities(db: Session, *, tenant_id: uuid.UUID, version_id: uuid.UUID) -> list[ProtocolCareActivity]:
    return list(
        db.execute(
            select(ProtocolCareActivity)
            .where(
                ProtocolCareActivity.tenant_id == tenant_id,
                ProtocolCareActivity.growing_protocol_version_id == version_id,
            )
            .order_by(ProtocolCareActivity.display_order)
        ).scalars()
    )


# --- Batch <-> Protocol Version assignment ---------------------------------------------


def _get_batch_row(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID) -> CropBatch:
    batch = db.execute(
        select(CropBatch).where(
            CropBatch.id == batch_id, CropBatch.tenant_id == tenant_id, CropBatch.farm_id == farm_id
        )
    ).scalar_one_or_none()
    if batch is None:
        raise CropBatchNotFoundError(str(batch_id))
    return batch


def assign_batch_protocol(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    batch_id: uuid.UUID,
    growing_protocol_version_id: uuid.UUID,
    effective_from: datetime | None,
    reason: str | None,
    client_command_id: uuid.UUID,
) -> BatchProtocolAssignment:
    """PILOT-AGRO-001 section 6: only one CURRENT assignment per Batch
    (`ux_batch_protocol_assignments_active_batch`). Changing protocol
    closes the previous current row's `effective_to` and inserts a new
    current row in the same transaction -- exactly `BatchStageRun`'s own
    "close previous, open next" shape -- so `Batch used V1 until X` / `used
    V2 from X` is always readable from history, never rewritten."""
    fingerprint = _fingerprint(tenant_id, farm_id, batch_id, growing_protocol_version_id, effective_from, reason)

    def _find_by_command() -> BatchProtocolAssignment | None:
        return db.execute(
            select(BatchProtocolAssignment).where(
                BatchProtocolAssignment.tenant_id == tenant_id,
                BatchProtocolAssignment.client_command_id == client_command_id,
            )
        ).scalar_one_or_none()

    existing = _find_by_command()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise BatchProtocolAssignmentCommandReusedWithDifferentPayloadError(str(client_command_id))

    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    batch = db.execute(
        select(CropBatch)
        .where(CropBatch.id == batch_id, CropBatch.tenant_id == tenant_id, CropBatch.farm_id == farm_id)
        .with_for_update()
    ).scalar_one_or_none()
    if batch is None:
        raise CropBatchNotFoundError(str(batch_id))

    existing = _find_by_command()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise BatchProtocolAssignmentCommandReusedWithDifferentPayloadError(str(client_command_id))

    version = db.execute(
        select(GrowingProtocolVersion).where(
            GrowingProtocolVersion.id == growing_protocol_version_id, GrowingProtocolVersion.tenant_id == tenant_id
        )
    ).scalar_one_or_none()
    if version is None:
        raise GrowingProtocolVersionNotFoundError(str(growing_protocol_version_id))
    if version.state != "active":
        raise BatchProtocolVersionNotActiveError(str(growing_protocol_version_id))

    resolved_effective_from = effective_from or datetime.now(timezone.utc)

    previous = db.execute(
        select(BatchProtocolAssignment)
        .where(BatchProtocolAssignment.batch_id == batch_id, BatchProtocolAssignment.effective_to.is_(None))
        .with_for_update()
    ).scalar_one_or_none()
    if previous is not None:
        previous.effective_to = resolved_effective_from
        db.flush()

    assignment = BatchProtocolAssignment(
        tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id, growing_protocol_version_id=growing_protocol_version_id,
        assigned_by_user_id=actor_user_id, effective_from=resolved_effective_from, reason=reason,
        client_command_id=client_command_id, request_fingerprint=fingerprint,
    )
    db.add(assignment)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_batch_protocol_assignments_tenant_client_command_id":
            replay = _find_by_command()
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise BatchProtocolAssignmentCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="batch_protocol_assignment.created",
        entity_type="batch_protocol_assignment", entity_id=assignment.id,
        event_data={
            "batch_id": str(batch_id), "growing_protocol_version_id": str(growing_protocol_version_id),
            "previous_assignment_id": str(previous.id) if previous else None,
        },
    )
    db.commit()
    db.refresh(assignment)
    return assignment


def get_current_assignment(
    db: Session, *, tenant_id: uuid.UUID, batch_id: uuid.UUID
) -> BatchProtocolAssignment | None:
    return db.execute(
        select(BatchProtocolAssignment).where(
            BatchProtocolAssignment.tenant_id == tenant_id, BatchProtocolAssignment.batch_id == batch_id,
            BatchProtocolAssignment.effective_to.is_(None),
        )
    ).scalar_one_or_none()


def list_batch_assignments(db: Session, *, tenant_id: uuid.UUID, batch_id: uuid.UUID) -> list[BatchProtocolAssignment]:
    return list(
        db.execute(
            select(BatchProtocolAssignment)
            .where(BatchProtocolAssignment.tenant_id == tenant_id, BatchProtocolAssignment.batch_id == batch_id)
            .order_by(BatchProtocolAssignment.effective_from)
        ).scalars()
    )


# --- Deterministic due/deviation read (section 18) ------------------------------------


def get_batch_protocol_status(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID) -> dict:
    """FROZEN: age informs display only, never a stage/farm-event trigger.
    Every input is an already-recorded fact: the Batch's current
    `BatchStageRun` (actual stage + entry time), the current
    `BatchProtocolAssignment` (assigned Protocol Version), that version's
    `ProtocolObservationRequirement`s for the current `stage_category`, and
    the most recent `GrowerInspection`/`ObservationEvent` touching each
    required `ObservationDefinition` since stage entry."""
    batch = _get_batch_row(db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id)

    active_run = db.execute(
        select(BatchStageRun, WorkflowStage)
        .join(WorkflowStage, WorkflowStage.id == BatchStageRun.workflow_stage_id)
        .where(BatchStageRun.batch_id == batch.id, BatchStageRun.exited_effective_time.is_(None))
    ).first()
    current_stage_category = active_run[1].stage_category if active_run else None
    days_in_stage = None
    if active_run is not None:
        days_in_stage = (datetime.now(timezone.utc) - active_run[0].entered_effective_time).days

    assignment = get_current_assignment(db, tenant_id=tenant_id, batch_id=batch_id)
    version = None
    protocol = None
    requirements_out: list[dict] = []
    if assignment is not None:
        version = db.get(GrowingProtocolVersion, assignment.growing_protocol_version_id)
        protocol = db.get(GrowingProtocol, version.growing_protocol_id) if version else None

    if assignment is not None and version is not None and current_stage_category is not None and active_run is not None:
        requirements = db.execute(
            select(ProtocolObservationRequirement, ObservationDefinition)
            .join(
                ObservationDefinition,
                ObservationDefinition.id == ProtocolObservationRequirement.observation_definition_id,
            )
            .where(
                ProtocolObservationRequirement.growing_protocol_version_id == version.id,
                ProtocolObservationRequirement.stage_category == current_stage_category,
            )
            .order_by(ProtocolObservationRequirement.display_order)
        ).all()

        stage_entered = active_run[0].entered_effective_time
        now = datetime.now(timezone.utc)
        for requirement, definition in requirements:
            last_value = db.execute(
                select(func.max(ObservationEvent.effective_time))
                .select_from(ObservationEvent)
                .join(ObservationValue, ObservationValue.observation_event_id == ObservationEvent.id)
                .where(
                    ObservationEvent.batch_id == batch.id,
                    ObservationEvent.effective_time >= stage_entered,
                    ObservationValue.observation_definition_id == definition.id,
                )
            ).scalar_one_or_none()

            is_due = last_value is None
            is_overdue = False
            if requirement.frequency_days is not None and last_value is not None:
                days_since = (now - last_value).days
                is_overdue = days_since >= requirement.frequency_days
                is_due = is_due or is_overdue
            elif requirement.frequency_days is None and last_value is None and requirement.requirement_level == "required":
                is_overdue = days_in_stage is not None and (
                    requirement.due_window_end_days is not None and days_in_stage > requirement.due_window_end_days
                )

            is_outside_window = False
            if requirement.due_window_end_days is not None and days_in_stage is not None:
                is_outside_window = days_in_stage > requirement.due_window_end_days and last_value is None

            requirements_out.append(
                {
                    "requirement": requirement,
                    "observation_definition_code": definition.code,
                    "observation_definition_name": definition.name,
                    "is_due": is_due,
                    "is_overdue": is_overdue,
                    "is_outside_expected_window": is_outside_window,
                    "last_satisfied_at": last_value,
                }
            )

    open_issue_count = db.execute(
        select(func.count(CropIssue.id)).where(
            CropIssue.tenant_id == tenant_id, CropIssue.farm_id == farm_id, CropIssue.batch_id == batch_id,
            CropIssue.status != "closed",
        )
    ).scalar_one()

    return {
        "current_assignment": assignment,
        "protocol": protocol,
        "protocol_version": version,
        "current_stage_category": current_stage_category,
        "days_in_stage": days_in_stage,
        "due_observation_requirements": requirements_out,
        "open_crop_issue_count": open_issue_count,
    }
