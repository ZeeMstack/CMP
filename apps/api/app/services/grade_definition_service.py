"""POSTHARVEST-OPS-001A: configurable, versioned commercial Grade
definitions — configuration only (see the ticket's own frozen scope
exclusions; no GradingEvent/GradedProduceLot/Packing/Recall/Traceability
change belongs here).

**Idempotency deviation from the closest existing convention, on
purpose.** The closest existing versioned-configuration precedent in this
codebase, `workflow_service.register_workflow`/`create_draft_version`/
`publish_version`, does not use the `client_command_id` + SHA-256
fingerprint idempotent-replay pattern at all — it relies solely on the
parent-row lock plus a tenant-unique code/number constraint. This ticket's
own frozen ACTIVATE/RETIRE section explicitly requires "an already-active
exact idempotent retry must return the original successful result", and
its required test list (exact create/activation/retirement replay,
mismatched-payload conflict) only makes sense under the full command-
idempotency shape this codebase's *operational* commands already use
(`harvest_service`, `packing_service`, `dispatch_service`: tenant-scoped
`client_command_id` unique index + fingerprint, checked before and after
the lock, with an `IntegrityError` fallback for the residual race). This
module deliberately follows that operational-command idiom instead of
`workflow_service`'s simpler configuration-only one, since the ticket's
own requirements are unambiguous about wanting real replay semantics —
this is a conscious, reported deviation, not an oversight.

**Lock ordering.** Every mutating command locks the parent
`GradeDefinition` row first (`FOR UPDATE`), mirroring `workflow_service`'s
own `create_draft_version`/`publish_version` exactly — this is what fully
serializes concurrent version creation and concurrent
activate/retire/activate races against the same `GradeDefinition` without
any advisory lock.
"""

import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.crop import Crop
from app.models.grade_definition import GradeDefinition
from app.models.grade_definition_version import GradeDefinitionVersion
from app.models.variety import Variety
from app.services.audit import append_audit_event
from app.services.errors import (
    CropNotFoundError,
    DuplicateGradeDefinitionCodeError,
    GradeDefinitionCommandReusedWithDifferentPayloadError,
    GradeDefinitionNotFoundError,
    GradeDefinitionVersionActivationReusedWithDifferentPayloadError,
    GradeDefinitionVersionCommandReusedWithDifferentPayloadError,
    GradeDefinitionVersionNotActiveError,
    GradeDefinitionVersionNotDraftError,
    GradeDefinitionVersionNotFoundError,
    GradeDefinitionVersionRetirementReusedWithDifferentPayloadError,
    InvalidGradeDefinitionVersionEffectiveTimeError,
    VarietyCropMismatchError,
)


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


# --- Fingerprints -----------------------------------------------------------------


def _compute_definition_fingerprint(
    *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID | None, code: str, name: str, crop_id: uuid.UUID,
    variety_id: uuid.UUID | None, description: str | None,
) -> str:
    parts = [
        str(tenant_id), str(actor_user_id) if actor_user_id else "", code, name, str(crop_id),
        str(variety_id) if variety_id else "", description or "",
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _compute_version_create_fingerprint(
    *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID | None, grade_definition_id: uuid.UUID,
    spec_notes: str | None,
) -> str:
    parts = [
        str(tenant_id), str(actor_user_id) if actor_user_id else "", str(grade_definition_id),
        spec_notes or "",
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _compute_lifecycle_fingerprint(
    *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID | None, grade_definition_id: uuid.UUID,
    version_id: uuid.UUID, effective_time: datetime,
) -> str:
    parts = [
        str(tenant_id), str(actor_user_id) if actor_user_id else "", str(grade_definition_id),
        str(version_id), effective_time.astimezone(timezone.utc).isoformat(),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


# --- GradeDefinition ---------------------------------------------------------------


def register_grade_definition(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    client_command_id: uuid.UUID,
    code: str,
    name: str,
    crop_id: uuid.UUID,
    variety_id: uuid.UUID | None,
    description: str | None,
) -> GradeDefinition:
    fingerprint = _compute_definition_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, code=code, name=name, crop_id=crop_id,
        variety_id=variety_id, description=description,
    )

    existing = db.execute(
        select(GradeDefinition).where(
            GradeDefinition.tenant_id == tenant_id, GradeDefinition.client_command_id == client_command_id
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise GradeDefinitionCommandReusedWithDifferentPayloadError(str(client_command_id))

    crop = db.execute(
        select(Crop).where(Crop.id == crop_id, Crop.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if crop is None:
        raise CropNotFoundError(str(crop_id))

    if variety_id is not None:
        variety = db.execute(
            select(Variety).where(
                Variety.id == variety_id, Variety.tenant_id == tenant_id, Variety.crop_id == crop_id
            )
        ).scalar_one_or_none()
        if variety is None:
            raise VarietyCropMismatchError(str(variety_id))

    definition = GradeDefinition(
        tenant_id=tenant_id, crop_id=crop_id, variety_id=variety_id, code=code, name=name,
        description=description, client_command_id=client_command_id, request_fingerprint=fingerprint,
    )
    db.add(definition)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_grade_definitions_tenant_client_command_id":
            replay = db.execute(
                select(GradeDefinition).where(
                    GradeDefinition.tenant_id == tenant_id,
                    GradeDefinition.client_command_id == client_command_id,
                )
            ).scalar_one_or_none()
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise GradeDefinitionCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        if constraint == "ux_grade_definitions_tenant_code_lower":
            raise DuplicateGradeDefinitionCodeError(f"{tenant_id}:{code}") from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="grade_definition.created",
        entity_type="grade_definition", entity_id=definition.id,
        event_data={
            "code": definition.code, "crop_id": str(crop_id),
            "variety_id": str(variety_id) if variety_id else None,
        },
    )
    db.commit()
    db.refresh(definition)
    return definition


def get_grade_definition(
    db: Session, *, tenant_id: uuid.UUID, grade_definition_id: uuid.UUID
) -> GradeDefinition:
    definition = db.execute(
        select(GradeDefinition).where(
            GradeDefinition.id == grade_definition_id, GradeDefinition.tenant_id == tenant_id
        )
    ).scalar_one_or_none()
    if definition is None:
        raise GradeDefinitionNotFoundError(str(grade_definition_id))
    return definition


def list_grade_definitions(
    db: Session, *, tenant_id: uuid.UUID, crop_id: uuid.UUID | None = None,
    variety_id: uuid.UUID | None = None,
) -> list[GradeDefinition]:
    query = select(GradeDefinition).where(GradeDefinition.tenant_id == tenant_id)
    if crop_id is not None:
        query = query.where(GradeDefinition.crop_id == crop_id)
    if variety_id is not None:
        query = query.where(GradeDefinition.variety_id == variety_id)
    return list(db.execute(query.order_by(GradeDefinition.code)).scalars())


def _lock_grade_definition(
    db: Session, *, tenant_id: uuid.UUID, grade_definition_id: uuid.UUID
) -> GradeDefinition:
    definition = db.execute(
        select(GradeDefinition)
        .where(GradeDefinition.id == grade_definition_id, GradeDefinition.tenant_id == tenant_id)
        .with_for_update()
    ).scalar_one_or_none()
    if definition is None:
        raise GradeDefinitionNotFoundError(str(grade_definition_id))
    return definition


# --- GradeDefinitionVersion: create -------------------------------------------------


def create_draft_version(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    client_command_id: uuid.UUID,
    grade_definition_id: uuid.UUID,
    spec_notes: str | None,
) -> GradeDefinitionVersion:
    fingerprint = _compute_version_create_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, grade_definition_id=grade_definition_id,
        spec_notes=spec_notes,
    )

    existing = db.execute(
        select(GradeDefinitionVersion).where(
            GradeDefinitionVersion.tenant_id == tenant_id,
            GradeDefinitionVersion.client_command_id == client_command_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise GradeDefinitionVersionCommandReusedWithDifferentPayloadError(str(client_command_id))

    _lock_grade_definition(db, tenant_id=tenant_id, grade_definition_id=grade_definition_id)

    # Post-lock replay re-check — closes the TOCTOU window between the
    # pre-lock check above and this command actually holding the
    # serializing parent-row lock (mirrors packing_service's own
    # pre-lock/post-lock double check).
    existing = db.execute(
        select(GradeDefinitionVersion).where(
            GradeDefinitionVersion.tenant_id == tenant_id,
            GradeDefinitionVersion.client_command_id == client_command_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise GradeDefinitionVersionCommandReusedWithDifferentPayloadError(str(client_command_id))

    next_number = (
        db.execute(
            select(func.max(GradeDefinitionVersion.version_number)).where(
                GradeDefinitionVersion.grade_definition_id == grade_definition_id
            )
        ).scalar_one()
        or 0
    ) + 1

    version = GradeDefinitionVersion(
        tenant_id=tenant_id, grade_definition_id=grade_definition_id, version_number=next_number,
        status="draft", spec_notes=spec_notes, created_by=actor_user_id,
        client_command_id=client_command_id, request_fingerprint=fingerprint,
    )
    db.add(version)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_grade_definition_versions_tenant_client_command_id":
            replay = db.execute(
                select(GradeDefinitionVersion).where(
                    GradeDefinitionVersion.tenant_id == tenant_id,
                    GradeDefinitionVersion.client_command_id == client_command_id,
                )
            ).scalar_one_or_none()
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise GradeDefinitionVersionCommandReusedWithDifferentPayloadError(
                str(client_command_id)
            ) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="grade_definition_version.created",
        entity_type="grade_definition_version", entity_id=version.id,
        event_data={"grade_definition_id": str(grade_definition_id), "version_number": version.version_number},
    )
    db.commit()
    db.refresh(version)
    return version


def get_version(
    db: Session, *, tenant_id: uuid.UUID, grade_definition_id: uuid.UUID, version_id: uuid.UUID
) -> GradeDefinitionVersion:
    get_grade_definition(db, tenant_id=tenant_id, grade_definition_id=grade_definition_id)
    version = db.execute(
        select(GradeDefinitionVersion).where(
            GradeDefinitionVersion.id == version_id,
            GradeDefinitionVersion.tenant_id == tenant_id,
            GradeDefinitionVersion.grade_definition_id == grade_definition_id,
        )
    ).scalar_one_or_none()
    if version is None:
        raise GradeDefinitionVersionNotFoundError(str(version_id))
    return version


def list_versions(
    db: Session, *, tenant_id: uuid.UUID, grade_definition_id: uuid.UUID, status: str | None = None
) -> list[GradeDefinitionVersion]:
    get_grade_definition(db, tenant_id=tenant_id, grade_definition_id=grade_definition_id)
    query = select(GradeDefinitionVersion).where(
        GradeDefinitionVersion.tenant_id == tenant_id,
        GradeDefinitionVersion.grade_definition_id == grade_definition_id,
    )
    if status is not None:
        query = query.where(GradeDefinitionVersion.status == status)
    return list(db.execute(query.order_by(GradeDefinitionVersion.version_number)).scalars())


# --- GradeDefinitionVersion: lifecycle ----------------------------------------------


def _lock_version(
    db: Session, *, tenant_id: uuid.UUID, grade_definition_id: uuid.UUID, version_id: uuid.UUID
) -> GradeDefinitionVersion:
    version = db.execute(
        select(GradeDefinitionVersion)
        .where(
            GradeDefinitionVersion.id == version_id,
            GradeDefinitionVersion.tenant_id == tenant_id,
            GradeDefinitionVersion.grade_definition_id == grade_definition_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if version is None:
        raise GradeDefinitionVersionNotFoundError(str(version_id))
    return version


def activate_version(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    client_command_id: uuid.UUID,
    grade_definition_id: uuid.UUID,
    version_id: uuid.UUID,
    effective_time: datetime,
) -> GradeDefinitionVersion:
    fingerprint = _compute_lifecycle_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, grade_definition_id=grade_definition_id,
        version_id=version_id, effective_time=effective_time,
    )

    def _find_by_activation_command() -> GradeDefinitionVersion | None:
        return db.execute(
            select(GradeDefinitionVersion).where(
                GradeDefinitionVersion.tenant_id == tenant_id,
                GradeDefinitionVersion.activation_client_command_id == client_command_id,
            )
        ).scalar_one_or_none()

    existing = _find_by_activation_command()
    if existing is not None:
        if existing.activation_request_fingerprint == fingerprint:
            return existing
        raise GradeDefinitionVersionActivationReusedWithDifferentPayloadError(str(client_command_id))

    # Lock the stable parent row first — this is what fully serializes two
    # concurrent ACTIVATE commands against two different draft versions of
    # the SAME GradeDefinition (and ACTIVATE vs RETIRE) into one
    # deterministic, race-free outcome, mirroring workflow_service's own
    # publish_version lock ordering.
    _lock_grade_definition(db, tenant_id=tenant_id, grade_definition_id=grade_definition_id)
    version = _lock_version(
        db, tenant_id=tenant_id, grade_definition_id=grade_definition_id, version_id=version_id
    )

    existing = _find_by_activation_command()
    if existing is not None:
        if existing.activation_request_fingerprint == fingerprint:
            return existing
        raise GradeDefinitionVersionActivationReusedWithDifferentPayloadError(str(client_command_id))

    if version.status != "draft":
        raise GradeDefinitionVersionNotDraftError(str(version_id))

    now = datetime.now(timezone.utc)
    if effective_time > now:
        raise InvalidGradeDefinitionVersionEffectiveTimeError("effective_time cannot be in the future")

    previous_active = db.execute(
        select(GradeDefinitionVersion)
        .where(
            GradeDefinitionVersion.grade_definition_id == grade_definition_id,
            GradeDefinitionVersion.status == "active",
        )
        .with_for_update()
    ).scalar_one_or_none()

    replaced_version_id: uuid.UUID | None = None
    replaced_version_number: int | None = None
    if previous_active is not None:
        if effective_time < previous_active.effective_from:
            raise InvalidGradeDefinitionVersionEffectiveTimeError(
                "activation effective_time cannot precede the currently active version's own effective_from"
            )
        previous_active.status = "retired"
        previous_active.effective_until = effective_time
        replaced_version_id = previous_active.id
        replaced_version_number = previous_active.version_number
        db.flush()

    version.status = "active"
    version.effective_from = effective_time
    version.activation_client_command_id = client_command_id
    version.activation_request_fingerprint = fingerprint
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_grade_definition_versions_tenant_activation_command":
            replay = _find_by_activation_command()
            if replay is not None and replay.activation_request_fingerprint == fingerprint:
                return replay
            raise GradeDefinitionVersionActivationReusedWithDifferentPayloadError(
                str(client_command_id)
            ) from exc
        raise

    # Two independently meaningful lifecycle transitions happen here when a
    # replacement is involved (previous ACTIVE -> RETIRED, selected draft
    # DRAFT -> ACTIVE) -- each gets its own normal audit event, mirroring
    # every other two-sided lifecycle change in this codebase (e.g.
    # transplant correction's own REVERSAL + REPLACEMENT pair). Both are
    # appended in this same transaction as the two row mutations above, so
    # a rollback (the IntegrityError branch, or any earlier exception)
    # discards both lifecycle changes and both audit rows together -- never
    # one without the other.
    if previous_active is not None:
        append_audit_event(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="grade_definition_version.retired",
            entity_type="grade_definition_version", entity_id=previous_active.id,
            event_data={
                "grade_definition_id": str(grade_definition_id), "version_number": replaced_version_number,
                "effective_until": effective_time.isoformat(), "reason": "superseded",
                "superseded_by_version_id": str(version.id),
            },
        )

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="grade_definition_version.activated",
        entity_type="grade_definition_version", entity_id=version.id,
        event_data={
            "grade_definition_id": str(grade_definition_id), "version_number": version.version_number,
            "effective_from": effective_time.isoformat(),
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
    actor_user_id: uuid.UUID | None,
    client_command_id: uuid.UUID,
    grade_definition_id: uuid.UUID,
    version_id: uuid.UUID,
    effective_time: datetime,
) -> GradeDefinitionVersion:
    fingerprint = _compute_lifecycle_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, grade_definition_id=grade_definition_id,
        version_id=version_id, effective_time=effective_time,
    )

    def _find_by_retirement_command() -> GradeDefinitionVersion | None:
        return db.execute(
            select(GradeDefinitionVersion).where(
                GradeDefinitionVersion.tenant_id == tenant_id,
                GradeDefinitionVersion.retirement_client_command_id == client_command_id,
            )
        ).scalar_one_or_none()

    existing = _find_by_retirement_command()
    if existing is not None:
        if existing.retirement_request_fingerprint == fingerprint:
            return existing
        raise GradeDefinitionVersionRetirementReusedWithDifferentPayloadError(str(client_command_id))

    _lock_grade_definition(db, tenant_id=tenant_id, grade_definition_id=grade_definition_id)
    version = _lock_version(
        db, tenant_id=tenant_id, grade_definition_id=grade_definition_id, version_id=version_id
    )

    existing = _find_by_retirement_command()
    if existing is not None:
        if existing.retirement_request_fingerprint == fingerprint:
            return existing
        raise GradeDefinitionVersionRetirementReusedWithDifferentPayloadError(str(client_command_id))

    if version.status != "active":
        raise GradeDefinitionVersionNotActiveError(str(version_id))

    now = datetime.now(timezone.utc)
    if effective_time > now:
        raise InvalidGradeDefinitionVersionEffectiveTimeError("effective_time cannot be in the future")
    if effective_time < version.effective_from:
        raise InvalidGradeDefinitionVersionEffectiveTimeError(
            "retirement effective_time cannot precede this version's own effective_from"
        )

    version.status = "retired"
    version.effective_until = effective_time
    version.retirement_client_command_id = client_command_id
    version.retirement_request_fingerprint = fingerprint
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_grade_definition_versions_tenant_retirement_command":
            replay = _find_by_retirement_command()
            if replay is not None and replay.retirement_request_fingerprint == fingerprint:
                return replay
            raise GradeDefinitionVersionRetirementReusedWithDifferentPayloadError(
                str(client_command_id)
            ) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="grade_definition_version.retired",
        entity_type="grade_definition_version", entity_id=version.id,
        event_data={
            "grade_definition_id": str(grade_definition_id), "version_number": version.version_number,
            "effective_until": effective_time.isoformat(), "reason": "explicit",
        },
    )
    db.commit()
    db.refresh(version)
    return version
