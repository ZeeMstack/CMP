import hashlib
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.models.crop import Crop
from app.models.crop_batch import CropBatch
from app.models.production_requirement import ProductionRequirement
from app.models.seeding_program_line import SeedingProgramLine
from app.models.sowing_event import SowingEvent
from app.models.sowing_event_line import SowingEventLine
from app.models.unit_of_measure import UnitOfMeasure
from app.models.variety import Variety
from app.schemas.crop_batch import CropSummary, VarietySummary
from app.schemas.planning import (
    LinkedSowingSummary,
    ProductionRequirementRead,
    RequirementFulfillment,
    SeedingProgramLineDetailRead,
    SeedingProgramLineRead,
    UomSummary,
)
from app.services import crop_service, farm_service, unit_of_measure_service
from app.services.audit import append_audit_event
from app.services.errors import (
    FarmNotFoundError,
    ProductionRequirementCommandReusedWithDifferentPayloadError,
    ProductionRequirementNotEditableError,
    ProductionRequirementNotFoundError,
    ProductionRequirementValidationError,
    SeedingProgramLineCommandReusedWithDifferentPayloadError,
    SeedingProgramLineNotEditableError,
    SeedingProgramLineNotFoundError,
    SeedingProgramLineValidationError,
)

_PlannedUom = aliased(UnitOfMeasure)
_CoverageUom = aliased(UnitOfMeasure)


def _require_active_farm(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID):
    farm = farm_service.get_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    if farm.status != "active":
        raise FarmNotFoundError(str(farm_id))
    return farm


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _uom_summary(uom: UnitOfMeasure) -> UomSummary:
    return UomSummary(id=uom.id, code=uom.code, name=uom.name, quantity_kind=uom.quantity_kind)


# === Production Requirement =========================================================


def _next_requirement_code_locked(db: Session, *, tenant_id: uuid.UUID) -> str:
    """Caller must already hold the tenant-scoped advisory lock (see
    `create_production_requirement`) before calling this -- mirrors
    `goods_receipt_service._next_receipt_code`'s exact lock-then-count
    shape, scoped by tenant (not farm) since `code` uniqueness is
    tenant-wide (`ux_production_requirements_tenant_code_lower`)."""
    year = datetime.now(timezone.utc).year
    prefix = f"PR-{year}"
    count = db.execute(
        select(func.count()).select_from(ProductionRequirement).where(
            ProductionRequirement.tenant_id == tenant_id, ProductionRequirement.code.like(f"{prefix}-%")
        )
    ).scalar_one()
    return f"{prefix}-{count + 1:03d}"


def _compute_requirement_create_fingerprint(
    *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, crop_id: uuid.UUID,
    variety_id: uuid.UUID | None, required_by_date: date, required_quantity: Decimal,
    quantity_uom_id: uuid.UUID, reference: str | None, notes: str | None,
) -> str:
    parts = [
        str(tenant_id), str(farm_id), str(actor_user_id), str(crop_id), str(variety_id) if variety_id else "",
        required_by_date.isoformat(), str(required_quantity), str(quantity_uom_id), reference or "", notes or "",
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def create_production_requirement(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_command_id: uuid.UUID,
    crop_id: uuid.UUID,
    variety_id: uuid.UUID | None,
    required_by_date: date,
    required_quantity: Decimal,
    quantity_uom_id: uuid.UUID,
    reference: str | None,
    notes: str | None,
) -> ProductionRequirement:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    crop_service.get_crop(db, tenant_id=tenant_id, crop_id=crop_id)
    if variety_id is not None:
        crop_service.get_variety(db, tenant_id=tenant_id, crop_id=crop_id, variety_id=variety_id)
    unit_of_measure_service.get_uom(db, uom_id=quantity_uom_id)

    fingerprint = _compute_requirement_create_fingerprint(
        tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, crop_id=crop_id, variety_id=variety_id,
        required_by_date=required_by_date, required_quantity=required_quantity, quantity_uom_id=quantity_uom_id,
        reference=reference, notes=notes,
    )

    def _find_existing() -> ProductionRequirement | None:
        return db.execute(
            select(ProductionRequirement).where(
                ProductionRequirement.tenant_id == tenant_id,
                ProductionRequirement.client_command_id == client_command_id,
            )
        ).scalar_one_or_none()

    existing = _find_existing()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise ProductionRequirementCommandReusedWithDifferentPayloadError(str(client_command_id))

    # Tenant-scoped advisory lock serializes concurrent code generation --
    # mirrors goods_receipt_service._next_receipt_code exactly.
    db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(f"production_requirement_code:{tenant_id}", 0))))

    existing = _find_existing()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise ProductionRequirementCommandReusedWithDifferentPayloadError(str(client_command_id))

    code = _next_requirement_code_locked(db, tenant_id=tenant_id)
    requirement = ProductionRequirement(
        id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, code=code, crop_id=crop_id, variety_id=variety_id,
        required_by_date=required_by_date, required_quantity=required_quantity, quantity_uom_id=quantity_uom_id,
        reference=reference, notes=notes, status="open", created_by_user_id=actor_user_id,
        client_command_id=client_command_id, request_fingerprint=fingerprint,
    )
    db.add(requirement)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        replay = _find_existing()
        if replay is not None and replay.request_fingerprint == fingerprint:
            return replay
        raise ProductionRequirementCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="production_requirement.created",
        entity_type="production_requirement", entity_id=requirement.id,
        event_data={
            "code": code, "crop_id": str(crop_id), "variety_id": str(variety_id) if variety_id else None,
            "required_by_date": required_by_date.isoformat(), "required_quantity": str(required_quantity),
            "quantity_uom_id": str(quantity_uom_id),
        },
    )
    db.commit()
    db.refresh(requirement)
    return requirement


def _lock_requirement(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, requirement_id: uuid.UUID) -> ProductionRequirement:
    requirement = db.execute(
        select(ProductionRequirement)
        .where(
            ProductionRequirement.id == requirement_id, ProductionRequirement.tenant_id == tenant_id,
            ProductionRequirement.farm_id == farm_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if requirement is None:
        raise ProductionRequirementNotFoundError(str(requirement_id))
    return requirement


def _compute_requirement_update_fingerprint(
    *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, requirement_id: uuid.UUID, required_by_date: date,
    required_quantity: Decimal, reference: str | None, notes: str | None,
) -> str:
    parts = [
        str(tenant_id), str(actor_user_id), str(requirement_id), required_by_date.isoformat(),
        str(required_quantity), reference or "", notes or "",
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def update_production_requirement(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    requirement_id: uuid.UUID,
    client_command_id: uuid.UUID,
    required_by_date: date,
    required_quantity: Decimal,
    reference: str | None,
    notes: str | None,
) -> ProductionRequirement:
    """Full-replace of the requirement's own editable fields -- only while
    `status = 'open'`. `crop_id`/`variety_id`/`quantity_uom_id` are
    identity and have no update path."""
    fingerprint = _compute_requirement_update_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, requirement_id=requirement_id,
        required_by_date=required_by_date, required_quantity=required_quantity, reference=reference, notes=notes,
    )

    def _find_by_update_command() -> ProductionRequirement | None:
        return db.execute(
            select(ProductionRequirement).where(
                ProductionRequirement.tenant_id == tenant_id,
                ProductionRequirement.update_client_command_id == client_command_id,
            )
        ).scalar_one_or_none()

    existing = _find_by_update_command()
    if existing is not None:
        if existing.update_request_fingerprint == fingerprint:
            return existing
        raise ProductionRequirementCommandReusedWithDifferentPayloadError(str(client_command_id))

    requirement = _lock_requirement(db, tenant_id=tenant_id, farm_id=farm_id, requirement_id=requirement_id)

    existing = _find_by_update_command()
    if existing is not None:
        if existing.update_request_fingerprint == fingerprint:
            return existing
        raise ProductionRequirementCommandReusedWithDifferentPayloadError(str(client_command_id))

    if requirement.status != "open":
        raise ProductionRequirementNotEditableError(str(requirement_id))

    before = {
        "required_by_date": requirement.required_by_date.isoformat(),
        "required_quantity": str(requirement.required_quantity),
        "reference": requirement.reference, "notes": requirement.notes,
    }
    requirement.required_by_date = required_by_date
    requirement.required_quantity = required_quantity
    requirement.reference = reference
    requirement.notes = notes
    requirement.update_client_command_id = client_command_id
    requirement.update_request_fingerprint = fingerprint
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_production_requirements_tenant_update_command":
            replay = _find_by_update_command()
            if replay is not None and replay.update_request_fingerprint == fingerprint:
                return replay
        raise ProductionRequirementCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="production_requirement.updated",
        entity_type="production_requirement", entity_id=requirement.id,
        event_data={
            "before": before,
            "after": {
                "required_by_date": required_by_date.isoformat(), "required_quantity": str(required_quantity),
                "reference": reference, "notes": notes,
            },
        },
    )
    db.commit()
    db.refresh(requirement)
    return requirement


def _compute_requirement_status_fingerprint(
    *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, requirement_id: uuid.UUID
) -> str:
    parts = [str(tenant_id), str(actor_user_id), str(requirement_id)]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def close_production_requirement(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID,
    requirement_id: uuid.UUID, client_command_id: uuid.UUID,
) -> ProductionRequirement:
    """OPEN -> CLOSED. Naturally idempotent: repeating the command once
    already closed is a harmless no-op (returns the current row unchanged,
    never re-audited) -- mirrors `location_service.deactivate_location`'s
    own status-command shape."""
    fingerprint = _compute_requirement_status_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, requirement_id=requirement_id
    )

    def _find_by_command() -> ProductionRequirement | None:
        return db.execute(
            select(ProductionRequirement).where(
                ProductionRequirement.tenant_id == tenant_id,
                ProductionRequirement.close_client_command_id == client_command_id,
            )
        ).scalar_one_or_none()

    existing = _find_by_command()
    if existing is not None:
        if existing.close_request_fingerprint == fingerprint:
            return existing
        raise ProductionRequirementCommandReusedWithDifferentPayloadError(str(client_command_id))

    requirement = _lock_requirement(db, tenant_id=tenant_id, farm_id=farm_id, requirement_id=requirement_id)

    existing = _find_by_command()
    if existing is not None:
        if existing.close_request_fingerprint == fingerprint:
            return existing
        raise ProductionRequirementCommandReusedWithDifferentPayloadError(str(client_command_id))

    if requirement.status == "cancelled":
        raise ProductionRequirementValidationError("cannot close a cancelled requirement")

    if requirement.status != "closed":
        requirement.status = "closed"
        requirement.close_client_command_id = client_command_id
        requirement.close_request_fingerprint = fingerprint
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            replay = _find_by_command()
            if replay is not None and replay.close_request_fingerprint == fingerprint:
                return replay
            raise ProductionRequirementCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        append_audit_event(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="production_requirement.closed",
            entity_type="production_requirement", entity_id=requirement.id, event_data={"code": requirement.code},
        )
        db.commit()
        db.refresh(requirement)
    return requirement


def cancel_production_requirement(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID,
    requirement_id: uuid.UUID, client_command_id: uuid.UUID,
) -> ProductionRequirement:
    """OPEN or CLOSED -> CANCELLED (business need no longer exists).
    Naturally idempotent, same shape as `close_production_requirement`."""
    fingerprint = _compute_requirement_status_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, requirement_id=requirement_id
    )

    def _find_by_command() -> ProductionRequirement | None:
        return db.execute(
            select(ProductionRequirement).where(
                ProductionRequirement.tenant_id == tenant_id,
                ProductionRequirement.cancel_client_command_id == client_command_id,
            )
        ).scalar_one_or_none()

    existing = _find_by_command()
    if existing is not None:
        if existing.cancel_request_fingerprint == fingerprint:
            return existing
        raise ProductionRequirementCommandReusedWithDifferentPayloadError(str(client_command_id))

    requirement = _lock_requirement(db, tenant_id=tenant_id, farm_id=farm_id, requirement_id=requirement_id)

    existing = _find_by_command()
    if existing is not None:
        if existing.cancel_request_fingerprint == fingerprint:
            return existing
        raise ProductionRequirementCommandReusedWithDifferentPayloadError(str(client_command_id))

    if requirement.status != "cancelled":
        requirement.status = "cancelled"
        requirement.cancel_client_command_id = client_command_id
        requirement.cancel_request_fingerprint = fingerprint
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            replay = _find_by_command()
            if replay is not None and replay.cancel_request_fingerprint == fingerprint:
                return replay
            raise ProductionRequirementCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        append_audit_event(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="production_requirement.cancelled",
            entity_type="production_requirement", entity_id=requirement.id, event_data={"code": requirement.code},
        )
        db.commit()
        db.refresh(requirement)
    return requirement


def _compute_fulfillment(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, requirement: ProductionRequirement
) -> RequirementFulfillment:
    """No false precision: `planned_coverage_quantity` sums only non-
    cancelled plan lines' `expected_coverage_quantity` (already in the
    requirement's own UOM). `actual_sowings_count` counts real Sowing
    Events linked to ANY of this requirement's plan lines -- INCLUDING
    lines later cancelled, since an already-executed Sowing is historical
    fact and is never rewritten by a later plan change. Never equates seeds
    sown with kg harvested."""
    lines = list(
        db.execute(
            select(SeedingProgramLine).where(
                SeedingProgramLine.tenant_id == tenant_id, SeedingProgramLine.farm_id == farm_id,
                SeedingProgramLine.production_requirement_id == requirement.id,
            )
        ).scalars()
    )
    active_lines = [line for line in lines if line.status != "cancelled"]
    planned_coverage = sum((line.expected_coverage_quantity for line in active_lines), Decimal("0"))
    demand = requirement.required_quantity
    delta = demand - planned_coverage
    is_overplanned = delta < 0
    gap_quantity = delta if delta > 0 else Decimal("0")
    overplanned_quantity = -delta if is_overplanned else Decimal("0")

    all_line_ids = [line.id for line in lines]
    actual_sowings_count = 0
    if all_line_ids:
        actual_sowings_count = db.execute(
            select(func.count()).select_from(SowingEvent).where(
                SowingEvent.tenant_id == tenant_id, SowingEvent.seeding_program_line_id.in_(all_line_ids)
            )
        ).scalar_one()

    return RequirementFulfillment(
        demand_quantity=demand, planned_coverage_quantity=planned_coverage, gap_quantity=gap_quantity,
        is_overplanned=is_overplanned, overplanned_quantity=overplanned_quantity,
        planned_lines_count=len(active_lines), actual_sowings_count=actual_sowings_count,
    )


def _requirement_detail_query():
    return (
        select(ProductionRequirement, Crop, Variety, UnitOfMeasure)
        .join(Crop, Crop.id == ProductionRequirement.crop_id)
        .outerjoin(Variety, Variety.id == ProductionRequirement.variety_id)
        .join(UnitOfMeasure, UnitOfMeasure.id == ProductionRequirement.quantity_uom_id)
    )


def _row_to_requirement_read(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, row) -> ProductionRequirementRead:
    requirement, crop, variety, uom = row
    fulfillment = _compute_fulfillment(db, tenant_id=tenant_id, farm_id=farm_id, requirement=requirement)
    return ProductionRequirementRead(
        id=requirement.id, tenant_id=requirement.tenant_id, farm_id=requirement.farm_id, code=requirement.code,
        crop=CropSummary(id=crop.id, code=crop.code, common_name=crop.common_name),
        variety=VarietySummary(id=variety.id, code=variety.code, name=variety.name) if variety is not None else None,
        required_by_date=requirement.required_by_date, required_quantity=requirement.required_quantity,
        uom=_uom_summary(uom), reference=requirement.reference, notes=requirement.notes, status=requirement.status,
        created_by_user_id=requirement.created_by_user_id, created_at=requirement.created_at,
        updated_at=requirement.updated_at, fulfillment=fulfillment,
    )


def get_production_requirement(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, requirement_id: uuid.UUID
) -> ProductionRequirementRead:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    row = db.execute(
        _requirement_detail_query().where(
            ProductionRequirement.id == requirement_id, ProductionRequirement.tenant_id == tenant_id,
            ProductionRequirement.farm_id == farm_id,
        )
    ).first()
    if row is None:
        raise ProductionRequirementNotFoundError(str(requirement_id))
    return _row_to_requirement_read(db, tenant_id=tenant_id, farm_id=farm_id, row=row)


def list_production_requirements(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID
) -> list[ProductionRequirementRead]:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    rows = db.execute(
        _requirement_detail_query()
        .where(ProductionRequirement.tenant_id == tenant_id, ProductionRequirement.farm_id == farm_id)
        .order_by(ProductionRequirement.required_by_date, ProductionRequirement.code)
    ).all()
    return [_row_to_requirement_read(db, tenant_id=tenant_id, farm_id=farm_id, row=row) for row in rows]


# === Seeding Program Line ============================================================


def _compute_line_create_fingerprint(
    *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, production_requirement_id: uuid.UUID,
    planned_sow_date: date, crop_id: uuid.UUID, variety_id: uuid.UUID | None, planned_quantity: Decimal,
    planned_quantity_uom_id: uuid.UUID, expected_coverage_quantity: Decimal, expected_coverage_uom_id: uuid.UUID,
    notes: str | None,
) -> str:
    parts = [
        str(tenant_id), str(farm_id), str(actor_user_id), str(production_requirement_id),
        planned_sow_date.isoformat(), str(crop_id), str(variety_id) if variety_id else "",
        str(planned_quantity), str(planned_quantity_uom_id), str(expected_coverage_quantity),
        str(expected_coverage_uom_id), notes or "",
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def create_seeding_program_line(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    production_requirement_id: uuid.UUID,
    client_command_id: uuid.UUID,
    planned_sow_date: date,
    crop_id: uuid.UUID,
    variety_id: uuid.UUID | None,
    planned_quantity: Decimal,
    planned_quantity_uom_id: uuid.UUID,
    expected_coverage_quantity: Decimal,
    expected_coverage_uom_id: uuid.UUID,
    notes: str | None,
) -> SeedingProgramLine:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    crop_service.get_crop(db, tenant_id=tenant_id, crop_id=crop_id)
    if variety_id is not None:
        crop_service.get_variety(db, tenant_id=tenant_id, crop_id=crop_id, variety_id=variety_id)
    planned_uom = unit_of_measure_service.get_uom(db, uom_id=planned_quantity_uom_id)
    if planned_uom.quantity_kind != "count":
        raise SeedingProgramLineValidationError(
            "planned sowing quantity must use a count unit of measure (e.g. SEED, EA)"
        )
    unit_of_measure_service.get_uom(db, uom_id=expected_coverage_uom_id)

    fingerprint = _compute_line_create_fingerprint(
        tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id,
        production_requirement_id=production_requirement_id, planned_sow_date=planned_sow_date, crop_id=crop_id,
        variety_id=variety_id, planned_quantity=planned_quantity, planned_quantity_uom_id=planned_quantity_uom_id,
        expected_coverage_quantity=expected_coverage_quantity, expected_coverage_uom_id=expected_coverage_uom_id,
        notes=notes,
    )

    def _find_existing() -> SeedingProgramLine | None:
        return db.execute(
            select(SeedingProgramLine).where(
                SeedingProgramLine.tenant_id == tenant_id, SeedingProgramLine.client_command_id == client_command_id
            )
        ).scalar_one_or_none()

    existing = _find_existing()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise SeedingProgramLineCommandReusedWithDifferentPayloadError(str(client_command_id))

    requirement = db.execute(
        select(ProductionRequirement)
        .where(
            ProductionRequirement.id == production_requirement_id, ProductionRequirement.tenant_id == tenant_id,
            ProductionRequirement.farm_id == farm_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if requirement is None:
        raise ProductionRequirementNotFoundError(str(production_requirement_id))

    existing = _find_existing()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise SeedingProgramLineCommandReusedWithDifferentPayloadError(str(client_command_id))

    if requirement.status != "open":
        raise SeedingProgramLineValidationError("parent production requirement is not open")
    if crop_id != requirement.crop_id:
        raise SeedingProgramLineValidationError("crop does not match the parent requirement's crop")
    if expected_coverage_uom_id != requirement.quantity_uom_id:
        raise SeedingProgramLineValidationError(
            "expected coverage must be expressed in the parent requirement's own unit of measure"
        )

    line = SeedingProgramLine(
        id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, production_requirement_id=production_requirement_id,
        planned_sow_date=planned_sow_date, crop_id=crop_id, variety_id=variety_id, planned_quantity=planned_quantity,
        planned_quantity_uom_id=planned_quantity_uom_id, expected_coverage_quantity=expected_coverage_quantity,
        expected_coverage_uom_id=expected_coverage_uom_id, notes=notes, status="planned",
        created_by_user_id=actor_user_id, client_command_id=client_command_id, request_fingerprint=fingerprint,
    )
    db.add(line)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        replay = _find_existing()
        if replay is not None and replay.request_fingerprint == fingerprint:
            return replay
        raise SeedingProgramLineCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="seeding_program_line.created",
        entity_type="seeding_program_line", entity_id=line.id,
        event_data={
            "production_requirement_id": str(production_requirement_id),
            "planned_sow_date": planned_sow_date.isoformat(), "planned_quantity": str(planned_quantity),
            "expected_coverage_quantity": str(expected_coverage_quantity),
        },
    )
    db.commit()
    db.refresh(line)
    return line


def _linked_sowing_count(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, line_id: uuid.UUID) -> int:
    return db.execute(
        select(func.count()).select_from(SowingEvent).where(
            SowingEvent.tenant_id == tenant_id, SowingEvent.farm_id == farm_id,
            SowingEvent.seeding_program_line_id == line_id,
        )
    ).scalar_one()


def _lock_line(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, line_id: uuid.UUID) -> SeedingProgramLine:
    line = db.execute(
        select(SeedingProgramLine)
        .where(
            SeedingProgramLine.id == line_id, SeedingProgramLine.tenant_id == tenant_id,
            SeedingProgramLine.farm_id == farm_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if line is None:
        raise SeedingProgramLineNotFoundError(str(line_id))
    return line


def _compute_line_update_fingerprint(
    *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, line_id: uuid.UUID, planned_sow_date: date,
    planned_quantity: Decimal, expected_coverage_quantity: Decimal, notes: str | None,
) -> str:
    parts = [
        str(tenant_id), str(actor_user_id), str(line_id), planned_sow_date.isoformat(), str(planned_quantity),
        str(expected_coverage_quantity), notes or "",
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def update_seeding_program_line(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    line_id: uuid.UUID,
    client_command_id: uuid.UUID,
    planned_sow_date: date,
    planned_quantity: Decimal,
    expected_coverage_quantity: Decimal,
    notes: str | None,
) -> SeedingProgramLine:
    """Full-replace of the line's own editable fields -- only while
    `status = 'planned'` AND no actual Sowing has linked to it yet (once
    linked, editing the plan would make the historical linkage
    nonsensical)."""
    fingerprint = _compute_line_update_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, line_id=line_id, planned_sow_date=planned_sow_date,
        planned_quantity=planned_quantity, expected_coverage_quantity=expected_coverage_quantity, notes=notes,
    )

    def _find_by_update_command() -> SeedingProgramLine | None:
        return db.execute(
            select(SeedingProgramLine).where(
                SeedingProgramLine.tenant_id == tenant_id,
                SeedingProgramLine.update_client_command_id == client_command_id,
            )
        ).scalar_one_or_none()

    existing = _find_by_update_command()
    if existing is not None:
        if existing.update_request_fingerprint == fingerprint:
            return existing
        raise SeedingProgramLineCommandReusedWithDifferentPayloadError(str(client_command_id))

    line = _lock_line(db, tenant_id=tenant_id, farm_id=farm_id, line_id=line_id)

    existing = _find_by_update_command()
    if existing is not None:
        if existing.update_request_fingerprint == fingerprint:
            return existing
        raise SeedingProgramLineCommandReusedWithDifferentPayloadError(str(client_command_id))

    if line.status != "planned":
        raise SeedingProgramLineNotEditableError(str(line_id))
    if _linked_sowing_count(db, tenant_id=tenant_id, farm_id=farm_id, line_id=line.id) > 0:
        raise SeedingProgramLineNotEditableError(str(line_id))

    before = {
        "planned_sow_date": line.planned_sow_date.isoformat(), "planned_quantity": str(line.planned_quantity),
        "expected_coverage_quantity": str(line.expected_coverage_quantity), "notes": line.notes,
    }
    line.planned_sow_date = planned_sow_date
    line.planned_quantity = planned_quantity
    line.expected_coverage_quantity = expected_coverage_quantity
    line.notes = notes
    line.update_client_command_id = client_command_id
    line.update_request_fingerprint = fingerprint
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_seeding_program_lines_tenant_update_command":
            replay = _find_by_update_command()
            if replay is not None and replay.update_request_fingerprint == fingerprint:
                return replay
        raise SeedingProgramLineCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="seeding_program_line.updated",
        entity_type="seeding_program_line", entity_id=line.id,
        event_data={
            "before": before,
            "after": {
                "planned_sow_date": planned_sow_date.isoformat(), "planned_quantity": str(planned_quantity),
                "expected_coverage_quantity": str(expected_coverage_quantity), "notes": notes,
            },
        },
    )
    db.commit()
    db.refresh(line)
    return line


def _compute_line_status_fingerprint(*, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, line_id: uuid.UUID) -> str:
    parts = [str(tenant_id), str(actor_user_id), str(line_id)]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def cancel_seeding_program_line(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, line_id: uuid.UUID,
    client_command_id: uuid.UUID,
) -> SeedingProgramLine:
    """PLANNED -> CANCELLED. Allowed even if actual Sowings have already
    linked to this line -- cancelling means "no MORE sowings planned
    against this line", never rewrites the Sowings that already happened.
    Naturally idempotent, same shape as the Production Requirement status
    commands."""
    fingerprint = _compute_line_status_fingerprint(tenant_id=tenant_id, actor_user_id=actor_user_id, line_id=line_id)

    def _find_by_command() -> SeedingProgramLine | None:
        return db.execute(
            select(SeedingProgramLine).where(
                SeedingProgramLine.tenant_id == tenant_id,
                SeedingProgramLine.cancel_client_command_id == client_command_id,
            )
        ).scalar_one_or_none()

    existing = _find_by_command()
    if existing is not None:
        if existing.cancel_request_fingerprint == fingerprint:
            return existing
        raise SeedingProgramLineCommandReusedWithDifferentPayloadError(str(client_command_id))

    line = _lock_line(db, tenant_id=tenant_id, farm_id=farm_id, line_id=line_id)

    existing = _find_by_command()
    if existing is not None:
        if existing.cancel_request_fingerprint == fingerprint:
            return existing
        raise SeedingProgramLineCommandReusedWithDifferentPayloadError(str(client_command_id))

    if line.status != "cancelled":
        line.status = "cancelled"
        line.cancel_client_command_id = client_command_id
        line.cancel_request_fingerprint = fingerprint
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            replay = _find_by_command()
            if replay is not None and replay.cancel_request_fingerprint == fingerprint:
                return replay
            raise SeedingProgramLineCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        append_audit_event(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="seeding_program_line.cancelled",
            entity_type="seeding_program_line", entity_id=line.id, event_data={},
        )
        db.commit()
        db.refresh(line)
    return line


def _line_detail_query():
    return (
        select(SeedingProgramLine, ProductionRequirement.code, Crop, Variety, _PlannedUom, _CoverageUom)
        .join(ProductionRequirement, ProductionRequirement.id == SeedingProgramLine.production_requirement_id)
        .join(Crop, Crop.id == SeedingProgramLine.crop_id)
        .outerjoin(Variety, Variety.id == SeedingProgramLine.variety_id)
        .join(_PlannedUom, _PlannedUom.id == SeedingProgramLine.planned_quantity_uom_id)
        .join(_CoverageUom, _CoverageUom.id == SeedingProgramLine.expected_coverage_uom_id)
    )


def _row_to_line_read(db: Session, *, row) -> SeedingProgramLineRead:
    line, requirement_code, crop, variety, planned_uom, coverage_uom = row
    linked_count = _linked_sowing_count(db, tenant_id=line.tenant_id, farm_id=line.farm_id, line_id=line.id)
    return SeedingProgramLineRead(
        id=line.id, tenant_id=line.tenant_id, farm_id=line.farm_id,
        production_requirement_id=line.production_requirement_id, requirement_code=requirement_code,
        planned_sow_date=line.planned_sow_date, crop=CropSummary(id=crop.id, code=crop.code, common_name=crop.common_name),
        variety=VarietySummary(id=variety.id, code=variety.code, name=variety.name) if variety is not None else None,
        planned_quantity=line.planned_quantity, planned_quantity_uom=_uom_summary(planned_uom),
        expected_coverage_quantity=line.expected_coverage_quantity, expected_coverage_uom=_uom_summary(coverage_uom),
        notes=line.notes, status=line.status, linked_sowing_count=linked_count,
        created_by_user_id=line.created_by_user_id, created_at=line.created_at, updated_at=line.updated_at,
    )


def list_linked_sowings(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, line_id: uuid.UUID
) -> list[LinkedSowingSummary]:
    rows = db.execute(
        select(
            SowingEvent.id, SowingEvent.batch_id, CropBatch.code, SowingEvent.effective_time,
            func.coalesce(func.sum(SowingEventLine.seed_count), 0),
        )
        .join(CropBatch, CropBatch.id == SowingEvent.batch_id)
        .outerjoin(SowingEventLine, SowingEventLine.sowing_event_id == SowingEvent.id)
        .where(
            SowingEvent.tenant_id == tenant_id, SowingEvent.farm_id == farm_id,
            SowingEvent.seeding_program_line_id == line_id,
        )
        .group_by(SowingEvent.id, SowingEvent.batch_id, CropBatch.code, SowingEvent.effective_time)
        .order_by(SowingEvent.effective_time)
    ).all()
    return [
        LinkedSowingSummary(id=r[0], batch_id=r[1], batch_code=r[2], effective_time=r[3], total_seeds_sown=int(r[4]))
        for r in rows
    ]


def get_seeding_program_line(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, line_id: uuid.UUID
) -> SeedingProgramLineDetailRead:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    row = db.execute(
        _line_detail_query().where(
            SeedingProgramLine.id == line_id, SeedingProgramLine.tenant_id == tenant_id,
            SeedingProgramLine.farm_id == farm_id,
        )
    ).first()
    if row is None:
        raise SeedingProgramLineNotFoundError(str(line_id))
    base = _row_to_line_read(db, row=row)
    linked_sowings = list_linked_sowings(db, tenant_id=tenant_id, farm_id=farm_id, line_id=line_id)
    return SeedingProgramLineDetailRead(**base.model_dump(), linked_sowings=linked_sowings)


def list_seeding_program_lines(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, production_requirement_id: uuid.UUID | None = None
) -> list[SeedingProgramLineRead]:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    query = _line_detail_query().where(
        SeedingProgramLine.tenant_id == tenant_id, SeedingProgramLine.farm_id == farm_id
    )
    if production_requirement_id is not None:
        query = query.where(SeedingProgramLine.production_requirement_id == production_requirement_id)
    rows = db.execute(query.order_by(SeedingProgramLine.planned_sow_date, SeedingProgramLine.id)).all()
    return [_row_to_line_read(db, row=row) for row in rows]
