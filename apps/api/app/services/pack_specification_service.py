"""POSTHARVEST-OPS-001B: PackSpecification / PackSpecificationVersion --
the commercial pack-standard configuration layer consumed by a later
Packing-contract ticket. Configuration only: no GradingEvent,
GradedProduceLot, PackingEvent/PackingInputLine/FinishedGoodsLot change,
Recall, Traceability, Dispatch, or frontend workspace belongs here.

Follows POSTHARVEST-OPS-001A's grade_definition_service.py conventions
exactly: full operational-command idempotency (tenant-scoped
client_command_id + SHA-256 fingerprint, pre/post-lock replay checks,
IntegrityError fallback) on every mutating command, the stable-parent-
locked-first ordering for version creation/lifecycle, and the two-audit-
event replacement-activation shape corrected in 001A's own pre-commit
review (previous version retired-by-supersession + new version activated,
both in the same transaction, cross-referencing each other)."""

import hashlib
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.crop import Crop
from app.models.grade_definition import GradeDefinition
from app.models.grade_definition_version import GradeDefinitionVersion
from app.models.pack_specification import PackSpecification
from app.models.pack_specification_version import PackSpecificationVersion
from app.models.packaging_unit import PackagingUnit
from app.models.variety import Variety
from app.services.audit import append_audit_event
from app.services.errors import (
    CropNotFoundError,
    DuplicatePackSpecificationCodeError,
    GradeDefinitionVersionNotFoundError,
    InvalidPackSpecificationVersionEffectiveTimeError,
    PackagingUnitNotActiveError,
    PackagingUnitNotFoundError,
    PackSpecificationCommandReusedWithDifferentPayloadError,
    PackSpecificationNotFoundError,
    PackSpecificationVersionActivationReusedWithDifferentPayloadError,
    PackSpecificationVersionCommandReusedWithDifferentPayloadError,
    PackSpecificationVersionNotActiveError,
    PackSpecificationVersionNotDraftError,
    PackSpecificationVersionNotFoundError,
    PackSpecificationVersionRetirementReusedWithDifferentPayloadError,
    PackSpecificationVersionValidationError,
    VarietyCropMismatchError,
)


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


# --- Fingerprints -----------------------------------------------------------------


def _compute_spec_fingerprint(
    *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID | None, code: str, name: str, crop_id: uuid.UUID,
    variety_id: uuid.UUID | None, customer_reference: str | None,
) -> str:
    parts = [
        str(tenant_id), str(actor_user_id) if actor_user_id else "", code, name, str(crop_id),
        str(variety_id) if variety_id else "", customer_reference or "",
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _compute_version_create_fingerprint(
    *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID | None, pack_specification_id: uuid.UUID,
    grade_definition_version_id: uuid.UUID | None, packaging_unit_id: uuid.UUID,
    nominal_net_weight_kg: Decimal | None, whole_units_per_pack: int | None, spec_notes: str | None,
) -> str:
    parts = [
        str(tenant_id), str(actor_user_id) if actor_user_id else "", str(pack_specification_id),
        str(grade_definition_version_id) if grade_definition_version_id else "", str(packaging_unit_id),
        str(nominal_net_weight_kg) if nominal_net_weight_kg is not None else "",
        str(whole_units_per_pack) if whole_units_per_pack is not None else "", spec_notes or "",
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _compute_lifecycle_fingerprint(
    *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID | None, pack_specification_id: uuid.UUID,
    version_id: uuid.UUID, effective_time: datetime,
) -> str:
    parts = [
        str(tenant_id), str(actor_user_id) if actor_user_id else "", str(pack_specification_id),
        str(version_id), effective_time.astimezone(timezone.utc).isoformat(),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


# --- PackSpecification --------------------------------------------------------------


def register_pack_specification(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    client_command_id: uuid.UUID,
    code: str,
    name: str,
    crop_id: uuid.UUID,
    variety_id: uuid.UUID | None,
    customer_reference: str | None,
) -> PackSpecification:
    fingerprint = _compute_spec_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, code=code, name=name, crop_id=crop_id,
        variety_id=variety_id, customer_reference=customer_reference,
    )

    existing = db.execute(
        select(PackSpecification).where(
            PackSpecification.tenant_id == tenant_id, PackSpecification.client_command_id == client_command_id
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise PackSpecificationCommandReusedWithDifferentPayloadError(str(client_command_id))

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

    spec = PackSpecification(
        tenant_id=tenant_id, crop_id=crop_id, variety_id=variety_id, code=code, name=name,
        customer_reference=customer_reference, client_command_id=client_command_id,
        request_fingerprint=fingerprint,
    )
    db.add(spec)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_pack_specifications_tenant_client_command_id":
            replay = db.execute(
                select(PackSpecification).where(
                    PackSpecification.tenant_id == tenant_id,
                    PackSpecification.client_command_id == client_command_id,
                )
            ).scalar_one_or_none()
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise PackSpecificationCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        if constraint == "ux_pack_specifications_tenant_code_lower":
            raise DuplicatePackSpecificationCodeError(f"{tenant_id}:{code}") from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="pack_specification.created",
        entity_type="pack_specification", entity_id=spec.id,
        event_data={
            "code": spec.code, "crop_id": str(crop_id), "variety_id": str(variety_id) if variety_id else None,
        },
    )
    db.commit()
    db.refresh(spec)
    return spec


def get_pack_specification(
    db: Session, *, tenant_id: uuid.UUID, pack_specification_id: uuid.UUID
) -> PackSpecification:
    spec = db.execute(
        select(PackSpecification).where(
            PackSpecification.id == pack_specification_id, PackSpecification.tenant_id == tenant_id
        )
    ).scalar_one_or_none()
    if spec is None:
        raise PackSpecificationNotFoundError(str(pack_specification_id))
    return spec


def list_pack_specifications(
    db: Session, *, tenant_id: uuid.UUID, crop_id: uuid.UUID | None = None,
    variety_id: uuid.UUID | None = None, customer_reference: str | None = None,
) -> list[PackSpecification]:
    query = select(PackSpecification).where(PackSpecification.tenant_id == tenant_id)
    if crop_id is not None:
        query = query.where(PackSpecification.crop_id == crop_id)
    if variety_id is not None:
        query = query.where(PackSpecification.variety_id == variety_id)
    if customer_reference is not None:
        query = query.where(PackSpecification.customer_reference == customer_reference)
    return list(db.execute(query.order_by(PackSpecification.code)).scalars())


def _lock_pack_specification(
    db: Session, *, tenant_id: uuid.UUID, pack_specification_id: uuid.UUID
) -> PackSpecification:
    spec = db.execute(
        select(PackSpecification)
        .where(PackSpecification.id == pack_specification_id, PackSpecification.tenant_id == tenant_id)
        .with_for_update()
    ).scalar_one_or_none()
    if spec is None:
        raise PackSpecificationNotFoundError(str(pack_specification_id))
    return spec


# --- PackSpecificationVersion: create ------------------------------------------------


def create_draft_version(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    client_command_id: uuid.UUID,
    pack_specification_id: uuid.UUID,
    grade_definition_version_id: uuid.UUID | None,
    packaging_unit_id: uuid.UUID,
    nominal_net_weight_kg: Decimal | None,
    whole_units_per_pack: int | None,
    spec_notes: str | None,
) -> PackSpecificationVersion:
    fingerprint = _compute_version_create_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, pack_specification_id=pack_specification_id,
        grade_definition_version_id=grade_definition_version_id, packaging_unit_id=packaging_unit_id,
        nominal_net_weight_kg=nominal_net_weight_kg, whole_units_per_pack=whole_units_per_pack,
        spec_notes=spec_notes,
    )

    existing = db.execute(
        select(PackSpecificationVersion).where(
            PackSpecificationVersion.tenant_id == tenant_id,
            PackSpecificationVersion.client_command_id == client_command_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise PackSpecificationVersionCommandReusedWithDifferentPayloadError(str(client_command_id))

    # Lock order: stable PackSpecification parent, then the referenced
    # PackagingUnit -- mirrors the ticket's own recommended ordering and
    # never inverts 001A's own "lock the stable parent first" idiom.
    spec = _lock_pack_specification(db, tenant_id=tenant_id, pack_specification_id=pack_specification_id)

    existing = db.execute(
        select(PackSpecificationVersion).where(
            PackSpecificationVersion.tenant_id == tenant_id,
            PackSpecificationVersion.client_command_id == client_command_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise PackSpecificationVersionCommandReusedWithDifferentPayloadError(str(client_command_id))

    if nominal_net_weight_kg is None and whole_units_per_pack is None:
        raise PackSpecificationVersionValidationError(
            "at least one of nominal_net_weight_kg or whole_units_per_pack is required"
        )
    if nominal_net_weight_kg is not None and nominal_net_weight_kg <= 0:
        raise PackSpecificationVersionValidationError("nominal_net_weight_kg must be positive")
    if whole_units_per_pack is not None and whole_units_per_pack <= 0:
        raise PackSpecificationVersionValidationError("whole_units_per_pack must be a positive integer")

    # PackagingUnit row lock -- this is what fully serializes this command
    # against a concurrent PackagingUnit retirement (POSTHARVEST-OPS-001B
    # concurrency requirement D): whichever transaction acquires this lock
    # first completes before the other can observe/mutate the row.
    unit = db.execute(
        select(PackagingUnit)
        .where(PackagingUnit.id == packaging_unit_id, PackagingUnit.tenant_id == tenant_id)
        .with_for_update()
    ).scalar_one_or_none()
    if unit is None:
        raise PackagingUnitNotFoundError(str(packaging_unit_id))
    if unit.status != "active":
        raise PackagingUnitNotActiveError(str(packaging_unit_id))

    if grade_definition_version_id is not None:
        grade_version = db.execute(
            select(GradeDefinitionVersion).where(
                GradeDefinitionVersion.id == grade_definition_version_id,
                GradeDefinitionVersion.tenant_id == tenant_id,
            )
        ).scalar_one_or_none()
        if grade_version is None:
            raise GradeDefinitionVersionNotFoundError(str(grade_definition_version_id))
        if grade_version.status == "draft":
            raise PackSpecificationVersionValidationError(
                f"grade_definition_version {grade_definition_version_id} is draft and cannot be referenced"
            )
        grade_definition = db.execute(
            select(GradeDefinition).where(GradeDefinition.id == grade_version.grade_definition_id)
        ).scalar_one()
        if grade_definition.crop_id != spec.crop_id:
            raise PackSpecificationVersionValidationError(
                "grade_definition_version's crop does not match this pack specification's crop"
            )
        if (
            spec.variety_id is not None
            and grade_definition.variety_id is not None
            and grade_definition.variety_id != spec.variety_id
        ):
            raise PackSpecificationVersionValidationError(
                "grade_definition_version's variety is incompatible with this pack specification's variety"
            )

    next_number = (
        db.execute(
            select(func.max(PackSpecificationVersion.version_number)).where(
                PackSpecificationVersion.pack_specification_id == pack_specification_id
            )
        ).scalar_one()
        or 0
    ) + 1

    version = PackSpecificationVersion(
        tenant_id=tenant_id, pack_specification_id=pack_specification_id, version_number=next_number,
        status="draft", grade_definition_version_id=grade_definition_version_id,
        packaging_unit_id=packaging_unit_id, nominal_net_weight_kg=nominal_net_weight_kg,
        whole_units_per_pack=whole_units_per_pack, spec_notes=spec_notes, created_by=actor_user_id,
        client_command_id=client_command_id, request_fingerprint=fingerprint,
    )
    db.add(version)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_pack_specification_versions_tenant_client_command_id":
            replay = db.execute(
                select(PackSpecificationVersion).where(
                    PackSpecificationVersion.tenant_id == tenant_id,
                    PackSpecificationVersion.client_command_id == client_command_id,
                )
            ).scalar_one_or_none()
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise PackSpecificationVersionCommandReusedWithDifferentPayloadError(
                str(client_command_id)
            ) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="pack_specification_version.created",
        entity_type="pack_specification_version", entity_id=version.id,
        event_data={"pack_specification_id": str(pack_specification_id), "version_number": version.version_number},
    )
    db.commit()
    db.refresh(version)
    return version


def get_version(
    db: Session, *, tenant_id: uuid.UUID, pack_specification_id: uuid.UUID, version_id: uuid.UUID
) -> PackSpecificationVersion:
    get_pack_specification(db, tenant_id=tenant_id, pack_specification_id=pack_specification_id)
    version = db.execute(
        select(PackSpecificationVersion).where(
            PackSpecificationVersion.id == version_id,
            PackSpecificationVersion.tenant_id == tenant_id,
            PackSpecificationVersion.pack_specification_id == pack_specification_id,
        )
    ).scalar_one_or_none()
    if version is None:
        raise PackSpecificationVersionNotFoundError(str(version_id))
    return version


def list_versions(
    db: Session, *, tenant_id: uuid.UUID, pack_specification_id: uuid.UUID, status: str | None = None
) -> list[PackSpecificationVersion]:
    get_pack_specification(db, tenant_id=tenant_id, pack_specification_id=pack_specification_id)
    query = select(PackSpecificationVersion).where(
        PackSpecificationVersion.tenant_id == tenant_id,
        PackSpecificationVersion.pack_specification_id == pack_specification_id,
    )
    if status is not None:
        query = query.where(PackSpecificationVersion.status == status)
    return list(db.execute(query.order_by(PackSpecificationVersion.version_number)).scalars())


# --- PackSpecificationVersion: lifecycle ---------------------------------------------


def _lock_version(
    db: Session, *, tenant_id: uuid.UUID, pack_specification_id: uuid.UUID, version_id: uuid.UUID
) -> PackSpecificationVersion:
    version = db.execute(
        select(PackSpecificationVersion)
        .where(
            PackSpecificationVersion.id == version_id,
            PackSpecificationVersion.tenant_id == tenant_id,
            PackSpecificationVersion.pack_specification_id == pack_specification_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if version is None:
        raise PackSpecificationVersionNotFoundError(str(version_id))
    return version


def activate_version(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    client_command_id: uuid.UUID,
    pack_specification_id: uuid.UUID,
    version_id: uuid.UUID,
    effective_time: datetime,
) -> PackSpecificationVersion:
    fingerprint = _compute_lifecycle_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, pack_specification_id=pack_specification_id,
        version_id=version_id, effective_time=effective_time,
    )

    def _find_by_activation_command() -> PackSpecificationVersion | None:
        return db.execute(
            select(PackSpecificationVersion).where(
                PackSpecificationVersion.tenant_id == tenant_id,
                PackSpecificationVersion.activation_client_command_id == client_command_id,
            )
        ).scalar_one_or_none()

    existing = _find_by_activation_command()
    if existing is not None:
        if existing.activation_request_fingerprint == fingerprint:
            return existing
        raise PackSpecificationVersionActivationReusedWithDifferentPayloadError(str(client_command_id))

    _lock_pack_specification(db, tenant_id=tenant_id, pack_specification_id=pack_specification_id)
    version = _lock_version(
        db, tenant_id=tenant_id, pack_specification_id=pack_specification_id, version_id=version_id
    )

    existing = _find_by_activation_command()
    if existing is not None:
        if existing.activation_request_fingerprint == fingerprint:
            return existing
        raise PackSpecificationVersionActivationReusedWithDifferentPayloadError(str(client_command_id))

    if version.status != "draft":
        raise PackSpecificationVersionNotDraftError(str(version_id))

    now = datetime.now(timezone.utc)
    if effective_time > now:
        raise InvalidPackSpecificationVersionEffectiveTimeError("effective_time cannot be in the future")

    previous_active = db.execute(
        select(PackSpecificationVersion)
        .where(
            PackSpecificationVersion.pack_specification_id == pack_specification_id,
            PackSpecificationVersion.status == "active",
        )
        .with_for_update()
    ).scalar_one_or_none()

    replaced_version_id: uuid.UUID | None = None
    replaced_version_number: int | None = None
    if previous_active is not None:
        if effective_time < previous_active.effective_from:
            raise InvalidPackSpecificationVersionEffectiveTimeError(
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
        if constraint == "ux_pack_specification_versions_tenant_activation_command":
            replay = _find_by_activation_command()
            if replay is not None and replay.activation_request_fingerprint == fingerprint:
                return replay
            raise PackSpecificationVersionActivationReusedWithDifferentPayloadError(
                str(client_command_id)
            ) from exc
        raise

    # Two independently meaningful lifecycle transitions on a replacement
    # activation -- each gets its own normal audit event, mirroring
    # 001A's own corrected pattern exactly.
    if previous_active is not None:
        append_audit_event(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id,
            action="pack_specification_version.retired", entity_type="pack_specification_version",
            entity_id=previous_active.id,
            event_data={
                "pack_specification_id": str(pack_specification_id), "version_number": replaced_version_number,
                "effective_until": effective_time.isoformat(), "reason": "superseded",
                "superseded_by_version_id": str(version.id),
            },
        )

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="pack_specification_version.activated",
        entity_type="pack_specification_version", entity_id=version.id,
        event_data={
            "pack_specification_id": str(pack_specification_id), "version_number": version.version_number,
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
    pack_specification_id: uuid.UUID,
    version_id: uuid.UUID,
    effective_time: datetime,
) -> PackSpecificationVersion:
    fingerprint = _compute_lifecycle_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, pack_specification_id=pack_specification_id,
        version_id=version_id, effective_time=effective_time,
    )

    def _find_by_retirement_command() -> PackSpecificationVersion | None:
        return db.execute(
            select(PackSpecificationVersion).where(
                PackSpecificationVersion.tenant_id == tenant_id,
                PackSpecificationVersion.retirement_client_command_id == client_command_id,
            )
        ).scalar_one_or_none()

    existing = _find_by_retirement_command()
    if existing is not None:
        if existing.retirement_request_fingerprint == fingerprint:
            return existing
        raise PackSpecificationVersionRetirementReusedWithDifferentPayloadError(str(client_command_id))

    _lock_pack_specification(db, tenant_id=tenant_id, pack_specification_id=pack_specification_id)
    version = _lock_version(
        db, tenant_id=tenant_id, pack_specification_id=pack_specification_id, version_id=version_id
    )

    existing = _find_by_retirement_command()
    if existing is not None:
        if existing.retirement_request_fingerprint == fingerprint:
            return existing
        raise PackSpecificationVersionRetirementReusedWithDifferentPayloadError(str(client_command_id))

    if version.status != "active":
        raise PackSpecificationVersionNotActiveError(str(version_id))

    now = datetime.now(timezone.utc)
    if effective_time > now:
        raise InvalidPackSpecificationVersionEffectiveTimeError("effective_time cannot be in the future")
    if effective_time < version.effective_from:
        raise InvalidPackSpecificationVersionEffectiveTimeError(
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
        if constraint == "ux_pack_specification_versions_tenant_retirement_command":
            replay = _find_by_retirement_command()
            if replay is not None and replay.retirement_request_fingerprint == fingerprint:
                return replay
            raise PackSpecificationVersionRetirementReusedWithDifferentPayloadError(
                str(client_command_id)
            ) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="pack_specification_version.retired",
        entity_type="pack_specification_version", entity_id=version.id,
        event_data={
            "pack_specification_id": str(pack_specification_id), "version_number": version.version_number,
            "effective_until": effective_time.isoformat(), "reason": "explicit",
        },
    )
    db.commit()
    db.refresh(version)
    return version
