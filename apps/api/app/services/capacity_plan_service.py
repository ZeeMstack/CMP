import hashlib
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.location import Location
from app.models.production_capacity_allocation import ProductionCapacityAllocation
from app.schemas.capacity_plan import (
    CAPACITY_UNIT,
    LocationCapacitySummaryRead,
    ProductionCapacityAllocationRead,
)
from app.services import crop_batch_service, farm_service, location_service, planning_service, production_system_service
from app.services.audit import append_audit_event
from app.services.errors import (
    CapacityAllocationExceedsAuthoritativeCapacityError,
    FarmNotFoundError,
    ProductionCapacityAllocationCommandReusedWithDifferentPayloadError,
    ProductionCapacityAllocationNotEditableError,
    ProductionCapacityAllocationNotFoundError,
)


def _require_active_farm(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID):
    farm = farm_service.get_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    if farm.status != "active":
        raise FarmNotFoundError(str(farm_id))
    return farm


def _effective_capacity(location: Location) -> int | None:
    """PILOT-PLAN-001A: the sole authoritative capacity source is
    `locations.capacity` (DOMAIN-FARM-002). For an occupiable Location,
    NULL means the physical-occupancy default of 1 (same semantics the
    Occupancy insert trigger enforces). For a non-occupiable Location
    (e.g. a Zone/Span/Gutter used only as a planning aggregation point),
    nothing is ever placed there directly, so NULL genuinely means
    UNKNOWN/NOT CONFIGURED -- never fabricated as 1, unlimited, or zero.
    A farm can make a non-occupiable Location's capacity KNOWN at any
    time by setting `Location.capacity` through the existing generic
    location-update command (e.g. a Grow Gutter's bag-position count) --
    this service adds no new capacity field anywhere."""
    if location.capacity is not None:
        return location.capacity
    return 1 if location.occupiable else None


def _next_allocation_code_locked(db: Session, *, tenant_id: uuid.UUID) -> str:
    year = datetime.now(timezone.utc).year
    prefix = f"CAP-{year}"
    count = db.execute(
        select(func.count()).select_from(ProductionCapacityAllocation).where(
            ProductionCapacityAllocation.tenant_id == tenant_id,
            ProductionCapacityAllocation.code.like(f"{prefix}-%"),
        )
    ).scalar_one()
    return f"{prefix}-{count + 1:03d}"


def _compute_create_fingerprint(
    *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, location_id: uuid.UUID,
    production_system_id: uuid.UUID | None, planned_start_date: date, planned_end_date: date,
    planned_capacity_amount: int, source_seeding_program_line_id: uuid.UUID | None,
    source_crop_batch_id: uuid.UUID | None, notes: str | None,
) -> str:
    parts = [
        str(tenant_id), str(farm_id), str(actor_user_id), str(location_id),
        str(production_system_id) if production_system_id else "", planned_start_date.isoformat(),
        planned_end_date.isoformat(), str(planned_capacity_amount),
        str(source_seeding_program_line_id) if source_seeding_program_line_id else "",
        str(source_crop_batch_id) if source_crop_batch_id else "", notes or "",
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _compute_update_fingerprint(
    *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, allocation_id: uuid.UUID, planned_start_date: date,
    planned_end_date: date, planned_capacity_amount: int, production_system_id: uuid.UUID | None,
    notes: str | None,
) -> str:
    parts = [
        str(tenant_id), str(actor_user_id), str(allocation_id), planned_start_date.isoformat(),
        planned_end_date.isoformat(), str(planned_capacity_amount),
        str(production_system_id) if production_system_id else "", notes or "",
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _planned_used_capacity(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, location_id: uuid.UUID, planned_start_date: date,
    planned_end_date: date, exclude_allocation_id: uuid.UUID | None,
) -> int:
    """[start, end) half-open overlap: two windows overlap iff
    `a.start < b.end AND b.start < a.end`. See docs/domain/
    HARVEST_FORECAST_CAPACITY_MODEL.md §Time Semantics."""
    query = select(func.coalesce(func.sum(ProductionCapacityAllocation.planned_capacity_amount), 0)).where(
        ProductionCapacityAllocation.tenant_id == tenant_id, ProductionCapacityAllocation.farm_id == farm_id,
        ProductionCapacityAllocation.location_id == location_id, ProductionCapacityAllocation.status == "active",
        ProductionCapacityAllocation.planned_start_date < planned_end_date,
        planned_start_date < ProductionCapacityAllocation.planned_end_date,
    )
    if exclude_allocation_id is not None:
        query = query.where(ProductionCapacityAllocation.id != exclude_allocation_id)
    return db.execute(query).scalar_one()


def _check_capacity(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, location: Location, planned_start_date: date,
    planned_end_date: date, planned_capacity_amount: int, exclude_allocation_id: uuid.UUID | None,
) -> None:
    authoritative = _effective_capacity(location)
    if authoritative is None:
        # PART 5: "if capacity is unknown, surface UNKNOWN -- never fake a
        # limit." We cannot prove a violation, so the write is allowed.
        return
    used = _planned_used_capacity(
        db, tenant_id=tenant_id, farm_id=farm_id, location_id=location.id, planned_start_date=planned_start_date,
        planned_end_date=planned_end_date, exclude_allocation_id=exclude_allocation_id,
    )
    if used + planned_capacity_amount > authoritative:
        raise CapacityAllocationExceedsAuthoritativeCapacityError(
            f"Location {location.code}: overlapping planned capacity ({used + planned_capacity_amount} "
            f"{CAPACITY_UNIT}s) would exceed authoritative capacity ({authoritative} {CAPACITY_UNIT}s)."
        )


def _row_to_read(db: Session, allocation: ProductionCapacityAllocation, location: Location) -> ProductionCapacityAllocationRead:
    return ProductionCapacityAllocationRead(
        id=allocation.id, tenant_id=allocation.tenant_id, farm_id=allocation.farm_id, code=allocation.code,
        location_id=allocation.location_id, location_code=location.code,
        production_system_id=allocation.production_system_id, planned_start_date=allocation.planned_start_date,
        planned_end_date=allocation.planned_end_date, planned_capacity_amount=allocation.planned_capacity_amount,
        source_seeding_program_line_id=allocation.source_seeding_program_line_id,
        source_crop_batch_id=allocation.source_crop_batch_id, status=allocation.status, notes=allocation.notes,
        created_by_user_id=allocation.created_by_user_id, created_at=allocation.created_at,
        updated_at=allocation.updated_at, cancelled_by_user_id=allocation.cancelled_by_user_id,
        cancelled_at=allocation.cancelled_at,
    )


def create_capacity_allocation(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_command_id: uuid.UUID,
    location_id: uuid.UUID,
    production_system_id: uuid.UUID | None,
    planned_start_date: date,
    planned_end_date: date,
    planned_capacity_amount: int,
    source_seeding_program_line_id: uuid.UUID | None,
    source_crop_batch_id: uuid.UUID | None,
    notes: str | None,
) -> ProductionCapacityAllocation:
    """PILOT-PLAN-001A Part 5: a PLANNING reservation only -- never creates
    Occupancy, never reserves a Carrier, never creates or moves a Batch."""
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    location = location_service.get_location(db, tenant_id=tenant_id, farm_id=farm_id, location_id=location_id)
    if production_system_id is not None:
        production_system_service.get_production_system(db, tenant_id=tenant_id, production_system_id=production_system_id)
    if source_seeding_program_line_id is not None:
        planning_service.get_seeding_program_line(
            db, tenant_id=tenant_id, farm_id=farm_id, line_id=source_seeding_program_line_id
        )
    if source_crop_batch_id is not None:
        crop_batch_service.get_batch(db, tenant_id=tenant_id, farm_id=farm_id, batch_id=source_crop_batch_id)

    fingerprint = _compute_create_fingerprint(
        tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, location_id=location_id,
        production_system_id=production_system_id, planned_start_date=planned_start_date,
        planned_end_date=planned_end_date, planned_capacity_amount=planned_capacity_amount,
        source_seeding_program_line_id=source_seeding_program_line_id, source_crop_batch_id=source_crop_batch_id,
        notes=notes,
    )

    def _find_replay() -> ProductionCapacityAllocation | None:
        return db.execute(
            select(ProductionCapacityAllocation).where(
                ProductionCapacityAllocation.tenant_id == tenant_id,
                ProductionCapacityAllocation.client_command_id == client_command_id,
            )
        ).scalar_one_or_none()

    existing = _find_replay()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise ProductionCapacityAllocationCommandReusedWithDifferentPayloadError(str(client_command_id))

    # Tenant-scoped advisory lock, keyed by Location -- serializes
    # concurrent overlap checks/writes against the same capacity resource
    # so double-booking cannot slip through a race (mirrors `planning_
    # service`'s own code-generation lock shape).
    db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(f"capacity_allocation:{location_id}", 0))))

    existing = _find_replay()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise ProductionCapacityAllocationCommandReusedWithDifferentPayloadError(str(client_command_id))

    _check_capacity(
        db, tenant_id=tenant_id, farm_id=farm_id, location=location, planned_start_date=planned_start_date,
        planned_end_date=planned_end_date, planned_capacity_amount=planned_capacity_amount,
        exclude_allocation_id=None,
    )

    code = _next_allocation_code_locked(db, tenant_id=tenant_id)
    allocation = ProductionCapacityAllocation(
        id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, code=code, location_id=location_id,
        production_system_id=production_system_id, planned_start_date=planned_start_date,
        planned_end_date=planned_end_date, planned_capacity_amount=planned_capacity_amount,
        source_seeding_program_line_id=source_seeding_program_line_id,
        source_crop_batch_id=source_crop_batch_id, status="active", notes=notes,
        created_by_user_id=actor_user_id, client_command_id=client_command_id, request_fingerprint=fingerprint,
    )
    db.add(allocation)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        replay = _find_replay()
        if replay is not None and replay.request_fingerprint == fingerprint:
            return replay
        raise ProductionCapacityAllocationCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="production_capacity_allocation.created",
        entity_type="production_capacity_allocation", entity_id=allocation.id,
        event_data={
            "code": code, "location_id": str(location_id), "planned_start_date": planned_start_date.isoformat(),
            "planned_end_date": planned_end_date.isoformat(), "planned_capacity_amount": planned_capacity_amount,
        },
    )
    db.commit()
    db.refresh(allocation)
    return allocation


def _lock_allocation(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, allocation_id: uuid.UUID
) -> ProductionCapacityAllocation:
    allocation = db.execute(
        select(ProductionCapacityAllocation)
        .where(
            ProductionCapacityAllocation.id == allocation_id, ProductionCapacityAllocation.tenant_id == tenant_id,
            ProductionCapacityAllocation.farm_id == farm_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if allocation is None:
        raise ProductionCapacityAllocationNotFoundError(str(allocation_id))
    return allocation


def update_capacity_allocation(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    allocation_id: uuid.UUID,
    client_command_id: uuid.UUID,
    planned_start_date: date,
    planned_end_date: date,
    planned_capacity_amount: int,
    production_system_id: uuid.UUID | None,
    notes: str | None,
) -> ProductionCapacityAllocation:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    if production_system_id is not None:
        production_system_service.get_production_system(db, tenant_id=tenant_id, production_system_id=production_system_id)

    db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(f"capacity_allocation_update:{allocation_id}", 0))))
    allocation = _lock_allocation(db, tenant_id=tenant_id, farm_id=farm_id, allocation_id=allocation_id)

    fingerprint = _compute_update_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, allocation_id=allocation_id,
        planned_start_date=planned_start_date, planned_end_date=planned_end_date,
        planned_capacity_amount=planned_capacity_amount, production_system_id=production_system_id, notes=notes,
    )
    if allocation.update_client_command_id == client_command_id:
        if allocation.update_request_fingerprint == fingerprint:
            return allocation
        raise ProductionCapacityAllocationCommandReusedWithDifferentPayloadError(str(client_command_id))

    if allocation.status != "active":
        raise ProductionCapacityAllocationNotEditableError(f"allocation {allocation.code} is not active")

    location = location_service.get_location(
        db, tenant_id=tenant_id, farm_id=farm_id, location_id=allocation.location_id
    )
    # Serialize against the same Location's other writers too, keyed by
    # Location (not just this allocation) so the overlap check below is
    # race-free.
    db.execute(
        select(func.pg_advisory_xact_lock(func.hashtextextended(f"capacity_allocation:{allocation.location_id}", 0)))
    )
    _check_capacity(
        db, tenant_id=tenant_id, farm_id=farm_id, location=location, planned_start_date=planned_start_date,
        planned_end_date=planned_end_date, planned_capacity_amount=planned_capacity_amount,
        exclude_allocation_id=allocation.id,
    )

    before = {
        "planned_start_date": allocation.planned_start_date.isoformat(),
        "planned_end_date": allocation.planned_end_date.isoformat(),
        "planned_capacity_amount": allocation.planned_capacity_amount,
    }
    allocation.planned_start_date = planned_start_date
    allocation.planned_end_date = planned_end_date
    allocation.planned_capacity_amount = planned_capacity_amount
    allocation.production_system_id = production_system_id
    allocation.notes = notes
    allocation.update_client_command_id = client_command_id
    allocation.update_request_fingerprint = fingerprint

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="production_capacity_allocation.updated",
        entity_type="production_capacity_allocation", entity_id=allocation.id,
        event_data={
            "before": before,
            "after": {
                "planned_start_date": planned_start_date.isoformat(), "planned_end_date": planned_end_date.isoformat(),
                "planned_capacity_amount": planned_capacity_amount,
            },
        },
    )
    db.commit()
    db.refresh(allocation)
    return allocation


def cancel_capacity_allocation(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, allocation_id: uuid.UUID,
    client_command_id: uuid.UUID,
) -> ProductionCapacityAllocation:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    allocation = _lock_allocation(db, tenant_id=tenant_id, farm_id=farm_id, allocation_id=allocation_id)

    if allocation.cancel_client_command_id == client_command_id:
        return allocation
    if allocation.status == "cancelled":
        # Naturally idempotent under a different command id -- mirrors
        # `planning_service.cancel_production_requirement`.
        return allocation

    allocation.status = "cancelled"
    allocation.cancelled_by_user_id = actor_user_id
    allocation.cancelled_at = datetime.now(timezone.utc)
    allocation.cancel_client_command_id = client_command_id
    allocation.cancel_request_fingerprint = hashlib.sha256(str(client_command_id).encode("utf-8")).hexdigest()

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="production_capacity_allocation.cancelled",
        entity_type="production_capacity_allocation", entity_id=allocation.id, event_data={"code": allocation.code},
    )
    db.commit()
    db.refresh(allocation)
    return allocation


def get_capacity_allocation(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, allocation_id: uuid.UUID
) -> ProductionCapacityAllocationRead:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    allocation = db.execute(
        select(ProductionCapacityAllocation).where(
            ProductionCapacityAllocation.id == allocation_id, ProductionCapacityAllocation.tenant_id == tenant_id,
            ProductionCapacityAllocation.farm_id == farm_id,
        )
    ).scalar_one_or_none()
    if allocation is None:
        raise ProductionCapacityAllocationNotFoundError(str(allocation_id))
    location = location_service.get_location(db, tenant_id=tenant_id, farm_id=farm_id, location_id=allocation.location_id)
    return _row_to_read(db, allocation, location)


def list_capacity_allocations(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, location_id: uuid.UUID | None = None,
) -> list[ProductionCapacityAllocationRead]:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    query = select(ProductionCapacityAllocation).where(
        ProductionCapacityAllocation.tenant_id == tenant_id, ProductionCapacityAllocation.farm_id == farm_id,
    )
    if location_id is not None:
        query = query.where(ProductionCapacityAllocation.location_id == location_id)
    rows = db.execute(query.order_by(ProductionCapacityAllocation.planned_start_date)).scalars().all()
    location_cache: dict[uuid.UUID, Location] = {}
    result = []
    for row in rows:
        if row.location_id not in location_cache:
            location_cache[row.location_id] = location_service.get_location(
                db, tenant_id=tenant_id, farm_id=farm_id, location_id=row.location_id
            )
        result.append(_row_to_read(db, row, location_cache[row.location_id]))
    return result


def get_location_capacity_summary(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, location_id: uuid.UUID, window_start_date: date,
    window_end_date: date,
) -> LocationCapacitySummaryRead:
    """PILOT-PLAN-001A Part 5/6: PLANNED / AVAILABLE surfaced as distinct
    dimensions, never collapsed with ACTUAL occupancy (a separate,
    physical-truth read -- see `location_service`/`occupancy_service` for
    that)."""
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    location = location_service.get_location(db, tenant_id=tenant_id, farm_id=farm_id, location_id=location_id)
    authoritative = _effective_capacity(location)
    used = _planned_used_capacity(
        db, tenant_id=tenant_id, farm_id=farm_id, location_id=location_id, planned_start_date=window_start_date,
        planned_end_date=window_end_date, exclude_allocation_id=None,
    )
    allocations = [
        a for a in list_capacity_allocations(db, tenant_id=tenant_id, farm_id=farm_id, location_id=location_id)
        if a.status == "active" and a.planned_start_date < window_end_date and window_start_date < a.planned_end_date
    ]
    return LocationCapacitySummaryRead(
        location_id=location_id, location_code=location.code, window_start_date=window_start_date,
        window_end_date=window_end_date, capacity_status="known" if authoritative is not None else "unknown",
        authoritative_capacity=authoritative, planned_used_capacity=used,
        available_planned_capacity=(authoritative - used) if authoritative is not None else None,
        allocations=allocations,
    )
