"""POSTHARVEST-OPS-001B: PackagingUnit -- a simple tenant-scoped, stable
commercial identity with no versioning and a two-state lifecycle
(active -> retired). Follows the same operational-command idempotency
idiom POSTHARVEST-OPS-001A established for GradeDefinition/
GradeDefinitionVersion (tenant-scoped client_command_id + SHA-256
fingerprint, pre/post-lock replay checks, IntegrityError fallback) rather
than the older, idempotency-free workflow_service convention -- see
grade_definition_service.py's own module docstring for the full
rationale, which applies unchanged here."""

import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.packaging_unit import PackagingUnit
from app.services.audit import append_audit_event
from app.services.errors import (
    DuplicatePackagingUnitCodeError,
    PackagingUnitCommandReusedWithDifferentPayloadError,
    PackagingUnitNotActiveError,
    PackagingUnitNotFoundError,
    PackagingUnitRetirementReusedWithDifferentPayloadError,
)


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _compute_create_fingerprint(
    *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID | None, code: str, name: str
) -> str:
    parts = [str(tenant_id), str(actor_user_id) if actor_user_id else "", code, name]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _compute_retirement_fingerprint(
    *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID | None, packaging_unit_id: uuid.UUID
) -> str:
    parts = [str(tenant_id), str(actor_user_id) if actor_user_id else "", str(packaging_unit_id)]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def register_packaging_unit(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    client_command_id: uuid.UUID,
    code: str,
    name: str,
) -> PackagingUnit:
    fingerprint = _compute_create_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, code=code, name=name
    )

    existing = db.execute(
        select(PackagingUnit).where(
            PackagingUnit.tenant_id == tenant_id, PackagingUnit.client_command_id == client_command_id
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise PackagingUnitCommandReusedWithDifferentPayloadError(str(client_command_id))

    unit = PackagingUnit(
        tenant_id=tenant_id, code=code, name=name, status="active", client_command_id=client_command_id,
        request_fingerprint=fingerprint,
    )
    db.add(unit)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_packaging_units_tenant_client_command_id":
            replay = db.execute(
                select(PackagingUnit).where(
                    PackagingUnit.tenant_id == tenant_id,
                    PackagingUnit.client_command_id == client_command_id,
                )
            ).scalar_one_or_none()
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise PackagingUnitCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        if constraint == "ux_packaging_units_tenant_code_lower":
            raise DuplicatePackagingUnitCodeError(f"{tenant_id}:{code}") from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="packaging_unit.created",
        entity_type="packaging_unit", entity_id=unit.id, event_data={"code": unit.code, "name": unit.name},
    )
    db.commit()
    db.refresh(unit)
    return unit


def get_packaging_unit(
    db: Session, *, tenant_id: uuid.UUID, packaging_unit_id: uuid.UUID
) -> PackagingUnit:
    unit = db.execute(
        select(PackagingUnit).where(
            PackagingUnit.id == packaging_unit_id, PackagingUnit.tenant_id == tenant_id
        )
    ).scalar_one_or_none()
    if unit is None:
        raise PackagingUnitNotFoundError(str(packaging_unit_id))
    return unit


def list_packaging_units(
    db: Session, *, tenant_id: uuid.UUID, status: str | None = None
) -> list[PackagingUnit]:
    query = select(PackagingUnit).where(PackagingUnit.tenant_id == tenant_id)
    if status is not None:
        query = query.where(PackagingUnit.status == status)
    return list(db.execute(query.order_by(PackagingUnit.code)).scalars())


def _lock_packaging_unit(
    db: Session, *, tenant_id: uuid.UUID, packaging_unit_id: uuid.UUID
) -> PackagingUnit:
    unit = db.execute(
        select(PackagingUnit)
        .where(PackagingUnit.id == packaging_unit_id, PackagingUnit.tenant_id == tenant_id)
        .with_for_update()
    ).scalar_one_or_none()
    if unit is None:
        raise PackagingUnitNotFoundError(str(packaging_unit_id))
    return unit


def retire_packaging_unit(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    client_command_id: uuid.UUID,
    packaging_unit_id: uuid.UUID,
) -> PackagingUnit:
    fingerprint = _compute_retirement_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, packaging_unit_id=packaging_unit_id
    )

    def _find_by_retirement_command() -> PackagingUnit | None:
        return db.execute(
            select(PackagingUnit).where(
                PackagingUnit.tenant_id == tenant_id,
                PackagingUnit.retirement_client_command_id == client_command_id,
            )
        ).scalar_one_or_none()

    existing = _find_by_retirement_command()
    if existing is not None:
        if existing.retirement_request_fingerprint == fingerprint:
            return existing
        raise PackagingUnitRetirementReusedWithDifferentPayloadError(str(client_command_id))

    unit = _lock_packaging_unit(db, tenant_id=tenant_id, packaging_unit_id=packaging_unit_id)

    existing = _find_by_retirement_command()
    if existing is not None:
        if existing.retirement_request_fingerprint == fingerprint:
            return existing
        raise PackagingUnitRetirementReusedWithDifferentPayloadError(str(client_command_id))

    if unit.status != "active":
        raise PackagingUnitNotActiveError(str(packaging_unit_id))

    unit.status = "retired"
    unit.retirement_client_command_id = client_command_id
    unit.retirement_request_fingerprint = fingerprint
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_packaging_units_tenant_retirement_command":
            replay = _find_by_retirement_command()
            if replay is not None and replay.retirement_request_fingerprint == fingerprint:
                return replay
            raise PackagingUnitRetirementReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="packaging_unit.retired",
        entity_type="packaging_unit", entity_id=unit.id, event_data={"code": unit.code},
    )
    db.commit()
    db.refresh(unit)
    return unit
