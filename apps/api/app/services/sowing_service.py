import hashlib
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.batch_stage_run import BatchStageRun
from app.models.carrier import Carrier
from app.models.carrier_specification import CarrierSpecification
from app.models.carrier_type import CarrierType
from app.models.crop import Crop
from app.models.crop_batch import CropBatch
from app.models.location import Location
from app.models.seed_lot import SeedLot
from app.models.sowing_event import SowingEvent
from app.models.sowing_event_line import SowingEventLine
from app.models.variety import Variety
from app.models.workflow import Workflow
from app.models.workflow_stage import WorkflowStage
from app.models.workflow_version import WorkflowVersion
from app.schemas.crop_batch import CropSummary, StageSummary, VarietySummary
from app.schemas.seed_lot import SeedLotRead
from app.schemas.sowing_event import (
    BatchCarrierAssignmentRead,
    CarrierSummary,
    CarrierTypeSummary,
    SeedingMachineSummary,
    SeedingStationSummary,
    SeedLotBatchSummary,
    SeedLotSummary,
    SowingEventLineRead,
    SowingEventRead,
)
from app.services import carrier_service, farm_service
from app.services.audit import append_audit_event
from app.services.errors import (
    BatchAlreadySownError,
    CarrierAlreadyAssignedError,
    CarrierNotFoundError,
    CropBatchClosedError,
    CropBatchNotFoundError,
    CropNotFoundError,
    DuplicateSeedLotCodeError,
    FarmNotFoundError,
    InvalidSowingEffectiveTimeError,
    MixedSeedLotInSowingCommandError,
    SeedLotNotFoundError,
    SeedLotValidationError,
    SowingCapacityExceededError,
    SowingCommandReusedWithDifferentPayloadError,
    SowingEventNotFoundError,
    SowingValidationError,
    TooManySowingLinesError,
    VarietyNotFoundError,
)

MAX_SOWING_LINES = 500


def _require_active_farm(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID):
    farm = farm_service.get_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    if farm.status != "active":
        raise FarmNotFoundError(str(farm_id))
    return farm


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _get_batch_row(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID) -> CropBatch:
    batch = db.execute(
        select(CropBatch).where(
            CropBatch.id == batch_id, CropBatch.tenant_id == tenant_id, CropBatch.farm_id == farm_id
        )
    ).scalar_one_or_none()
    if batch is None:
        raise CropBatchNotFoundError(str(batch_id))
    return batch


# --- Seed lots ------------------------------------------------------------------


def register_seed_lot(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    crop_id: uuid.UUID,
    variety_id: uuid.UUID,
    code: str,
    supplier_name: str | None,
    supplier_lot_reference: str | None,
    received_date,
    expiry_date,
) -> SeedLot:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    crop = db.execute(select(Crop).where(Crop.id == crop_id, Crop.tenant_id == tenant_id)).scalar_one_or_none()
    if crop is None:
        raise CropNotFoundError(str(crop_id))

    variety = db.execute(
        select(Variety).where(
            Variety.id == variety_id, Variety.tenant_id == tenant_id, Variety.crop_id == crop_id
        )
    ).scalar_one_or_none()
    if variety is None:
        raise VarietyNotFoundError(str(variety_id))

    if received_date is not None and expiry_date is not None and expiry_date < received_date:
        raise SeedLotValidationError("expiry_date cannot precede received_date")

    seed_lot = SeedLot(
        id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, crop_id=crop_id, variety_id=variety_id,
        code=code, supplier_name=supplier_name, supplier_lot_reference=supplier_lot_reference,
        received_date=received_date, expiry_date=expiry_date, created_by_user_id=actor_user_id,
    )
    db.add(seed_lot)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateSeedLotCodeError(f"{tenant_id}:{code}") from exc

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="seed_lot.registered",
        entity_type="seed_lot", entity_id=seed_lot.id,
        event_data={
            "seed_lot_id": str(seed_lot.id), "code": seed_lot.code, "crop_id": str(crop_id),
            "variety_id": str(variety_id),
        },
    )
    db.commit()
    db.refresh(seed_lot)
    return seed_lot


def _seed_lot_detail_query():
    return (
        select(
            SeedLot,
            Crop.id.label("crop_id"),
            Crop.code.label("crop_code"),
            Crop.common_name.label("crop_common_name"),
            Variety.id.label("variety_id"),
            Variety.code.label("variety_code"),
            Variety.name.label("variety_name"),
        )
        .join(Crop, Crop.id == SeedLot.crop_id)
        .join(Variety, Variety.id == SeedLot.variety_id)
    )


def _row_to_seed_lot_read(row) -> SeedLotRead:
    lot: SeedLot = row[0]
    m = row._mapping
    return SeedLotRead(
        id=lot.id, tenant_id=lot.tenant_id, farm_id=lot.farm_id,
        crop=CropSummary(id=m["crop_id"], code=m["crop_code"], common_name=m["crop_common_name"]),
        variety=VarietySummary(id=m["variety_id"], code=m["variety_code"], name=m["variety_name"]),
        code=lot.code, supplier_name=lot.supplier_name, supplier_lot_reference=lot.supplier_lot_reference,
        received_date=lot.received_date, expiry_date=lot.expiry_date, status=lot.status,
        created_at=lot.created_at, updated_at=lot.updated_at,
    )


def get_seed_lot(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, seed_lot_id: uuid.UUID) -> SeedLotRead:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    row = db.execute(
        _seed_lot_detail_query().where(
            SeedLot.id == seed_lot_id, SeedLot.tenant_id == tenant_id, SeedLot.farm_id == farm_id
        )
    ).first()
    if row is None:
        raise SeedLotNotFoundError(str(seed_lot_id))
    return _row_to_seed_lot_read(row)


def list_seed_lots(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> list[SeedLotRead]:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    rows = db.execute(
        _seed_lot_detail_query()
        .where(SeedLot.tenant_id == tenant_id, SeedLot.farm_id == farm_id)
        .order_by(SeedLot.code)
    ).all()
    return [_row_to_seed_lot_read(r) for r in rows]


def list_batches_for_seed_lot(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, seed_lot_id: uuid.UUID
) -> list[SeedLotBatchSummary]:
    """NURSERY-OPS-001 section 49: "which Crop Batches were sown from this
    Seed Lot" -- a simple related-batches read, not a full traceability UI."""
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    lot = db.execute(
        select(SeedLot).where(SeedLot.id == seed_lot_id, SeedLot.tenant_id == tenant_id, SeedLot.farm_id == farm_id)
    ).scalar_one_or_none()
    if lot is None:
        raise SeedLotNotFoundError(str(seed_lot_id))
    rows = db.execute(
        select(CropBatch.id, CropBatch.code, SowingEvent.effective_time)
        .select_from(SowingEventLine)
        .join(SowingEvent, SowingEvent.id == SowingEventLine.sowing_event_id)
        .join(CropBatch, CropBatch.id == SowingEvent.batch_id)
        .where(SowingEventLine.tenant_id == tenant_id, SowingEventLine.seed_lot_id == seed_lot_id)
        .distinct()
        .order_by(SowingEvent.effective_time.desc())
    ).all()
    return [SeedLotBatchSummary(id=r[0], code=r[1], sown_effective_time=r[2]) for r in rows]


# --- Sowing ----------------------------------------------------------------------


def _compute_sowing_fingerprint(
    *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, batch_id: uuid.UUID,
    effective_time: datetime, note: str | None, lines: list[dict],
) -> str:
    sorted_lines = sorted(lines, key=lambda line: str(line["carrier_id"]))
    parts = [
        str(tenant_id), str(farm_id), str(actor_user_id), str(batch_id),
        effective_time.astimezone(timezone.utc).isoformat(), note or "",
    ]
    for line in sorted_lines:
        parts.extend(
            [
                str(line["carrier_id"]),
                str(line["seed_lot_id"]),
                str(line["sown_site_count"]),
                str(line["seed_count"]),
                line.get("line_note") or "",
            ]
        )
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _find_existing_sowing_event(
    db: Session, *, tenant_id: uuid.UUID, client_command_id: uuid.UUID
) -> SowingEvent | None:
    return db.execute(
        select(SowingEvent).where(
            SowingEvent.tenant_id == tenant_id, SowingEvent.client_command_id == client_command_id
        )
    ).scalar_one_or_none()


def _find_existing_sowing_event_for_batch(db: Session, *, tenant_id: uuid.UUID, batch_id: uuid.UUID) -> SowingEvent | None:
    """NURSERY-OPS-001: a Crop Batch may have at most one Sowing Event,
    ever (`ux_sowing_events_batch_id`, DB-enforced). Used to distinguish a
    genuinely new sowing command (rejected -- see BatchAlreadySownError)
    from an exact replay of the one that already exists (handled by the
    ordinary client_command_id idempotency path above it)."""
    return db.execute(
        select(SowingEvent).where(SowingEvent.tenant_id == tenant_id, SowingEvent.batch_id == batch_id)
    ).scalar_one_or_none()


def _sow_batch_core(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    batch_id: uuid.UUID,
    client_command_id: uuid.UUID,
    effective_time: datetime,
    note: str | None,
    lines: list[dict],
    request_fingerprint: str,
    seeding_station_id: uuid.UUID | None = None,
    seeding_machine_id: uuid.UUID | None = None,
) -> SowingEvent:
    """Validate + insert + flush only -- no idempotency check, no row
    locking for serialization, no audit event, no commit. Callers own all
    three: `sow_batch` below (its own client_command_id scheme, batch/
    carrier/seed-lot row locks) and NURSERY-OPS-001's
    `nursery_service.sow_new_batch` (its own combined idempotency/locking
    spanning batch-creation AND sowing as one command). Mirrors
    FARM-SETUP-001's `_create_location_core` split exactly -- zero behavior
    change to the public `sow_batch` below, reverified against the full
    existing sowing test suite. `seeding_station_id`/`seeding_machine_id`
    are NURSERY-OPS-001 additions (provenance only, already validated by
    the caller before this point -- this function only persists them)."""
    farm = _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    if effective_time > datetime.now(timezone.utc):
        raise InvalidSowingEffectiveTimeError("effective_time cannot be in the future")
    if len(lines) > MAX_SOWING_LINES:
        raise TooManySowingLinesError(f"a sowing command may include at most {MAX_SOWING_LINES} lines")
    carrier_ids_in = [line["carrier_id"] for line in lines]
    if len(carrier_ids_in) != len(set(carrier_ids_in)):
        raise SowingValidationError("duplicate carrier_id within one sowing command")

    batch = db.execute(
        select(CropBatch)
        .where(CropBatch.id == batch_id, CropBatch.tenant_id == tenant_id, CropBatch.farm_id == farm_id)
        .with_for_update()
    ).scalar_one_or_none()
    if batch is None:
        raise CropBatchNotFoundError(str(batch_id))

    if batch.state != "active":
        raise CropBatchClosedError(str(batch_id))

    active_run = db.execute(
        select(BatchStageRun)
        .where(BatchStageRun.batch_id == batch.id, BatchStageRun.exited_effective_time.is_(None))
        .with_for_update()
    ).scalar_one_or_none()
    if active_run is None:
        raise CropBatchNotFoundError(str(batch_id))

    if effective_time < batch.created_effective_time:
        raise InvalidSowingEffectiveTimeError("effective_time precedes the batch's creation effective time")
    if effective_time < active_run.entered_effective_time:
        raise InvalidSowingEffectiveTimeError("effective_time precedes the current stage run's entry time")

    stage = db.get(WorkflowStage, active_run.workflow_stage_id)
    if stage.stage_category != "seeding":
        raise SowingValidationError("current workflow stage is not a seeding stage")
    if stage.required_carrier_type_id is None:
        raise SowingValidationError("current workflow stage has no required carrier type configured")

    workflow_version = db.get(WorkflowVersion, batch.workflow_version_id)
    workflow = db.get(Workflow, workflow_version.workflow_id)
    if workflow.variety_id is None:
        raise SowingValidationError("batch's workflow has no variety; sowing is not permitted")
    variety = db.get(Variety, workflow.variety_id)
    if variety is None or variety.status != "active":
        raise SowingValidationError("batch's workflow variety is not active")

    # Lock carriers, then seed lots, each in deterministic sorted-UUID order.
    sorted_carrier_ids = sorted(set(carrier_ids_in))
    carriers = list(
        db.execute(
            select(Carrier)
            .where(
                Carrier.id.in_(sorted_carrier_ids), Carrier.tenant_id == tenant_id, Carrier.farm_id == farm_id
            )
            .order_by(Carrier.id)
            .with_for_update()
        ).scalars()
    )
    carriers_by_id = {c.id: c for c in carriers}
    for cid in sorted_carrier_ids:
        if cid not in carriers_by_id:
            raise CarrierNotFoundError(str(cid))

    sorted_seed_lot_ids = sorted({line["seed_lot_id"] for line in lines})
    # NURSERY-OPS-001.1: one Crop Batch -> exactly one Seed Lot. Every line
    # of this event must reference the SAME Seed Lot -- checked here before
    # any row is written (and again at the DB layer by
    # `enforce_sowing_event_line_insert_integrity`, see migration
    # a7e4f2c9b381), closing a gap in CMP-009's original per-line design
    # where two lines of one event could otherwise cite two different Seed
    # Lots of the same crop/variety.
    if len(sorted_seed_lot_ids) != 1:
        raise MixedSeedLotInSowingCommandError(
            "a sowing command's lines must all reference the same seed lot"
        )
    canonical_seed_lot_id = sorted_seed_lot_ids[0]
    seed_lots = list(
        db.execute(
            select(SeedLot)
            .where(
                SeedLot.id.in_(sorted_seed_lot_ids), SeedLot.tenant_id == tenant_id, SeedLot.farm_id == farm_id
            )
            .order_by(SeedLot.id)
            .with_for_update()
        ).scalars()
    )
    seed_lots_by_id = {s.id: s for s in seed_lots}
    for sid in sorted_seed_lot_ids:
        if sid not in seed_lots_by_id:
            raise SeedLotNotFoundError(str(sid))

    active_assignment_carrier_ids = set(
        db.execute(
            select(BatchCarrierAssignment.carrier_id).where(
                BatchCarrierAssignment.tenant_id == tenant_id,
                BatchCarrierAssignment.carrier_id.in_(sorted_carrier_ids),
                BatchCarrierAssignment.released_effective_time.is_(None),
            )
        ).scalars()
    )

    # CARRIER-CONFIG-001B: seed-tray capacity enforcement. One batched query
    # for every distinct specification_id present among the locked carriers
    # -- never a query per carrier. A carrier with no specification (legacy,
    # pre-CARRIER-CONFIG-001A) or a specification with no
    # biological_position_count recorded skips this check entirely: CMP has
    # no physical capacity fact to compare against, so nothing is enforced,
    # nothing is fabricated. `seed_count` is never compared against
    # biological_position_count -- multiple seeds may legitimately occupy
    # one planting position (see CarrierSpecification's own docstring).
    specification_ids = {
        c.specification_id for c in carriers_by_id.values() if c.specification_id is not None
    }
    specifications_by_id: dict[uuid.UUID, CarrierSpecification] = {}
    if specification_ids:
        specifications_by_id = {
            s.id: s
            for s in db.execute(
                select(CarrierSpecification).where(CarrierSpecification.id.in_(specification_ids))
            ).scalars()
        }
    line_by_carrier_id = {line["carrier_id"]: line for line in lines}

    for cid in sorted_carrier_ids:
        carrier = carriers_by_id[cid]
        if carrier.status != "active":
            raise SowingValidationError(f"carrier {cid} is not active")
        if carrier.carrier_type_id != stage.required_carrier_type_id:
            raise SowingValidationError(f"carrier {cid} does not match the stage's required carrier type")
        if cid in active_assignment_carrier_ids:
            raise CarrierAlreadyAssignedError(str(cid))
        specification = (
            specifications_by_id.get(carrier.specification_id) if carrier.specification_id is not None else None
        )
        if specification is not None and specification.biological_position_count is not None:
            sown_site_count = line_by_carrier_id[cid]["sown_site_count"]
            if sown_site_count is not None and sown_site_count > specification.biological_position_count:
                raise SowingCapacityExceededError(
                    f"carrier {cid}: sown_site_count ({sown_site_count}) exceeds its specification's "
                    f"biological_position_count ({specification.biological_position_count})"
                )

    local_sow_date = effective_time.astimezone(ZoneInfo(farm.timezone)).date()
    for sid in sorted_seed_lot_ids:
        seed_lot = seed_lots_by_id[sid]
        if seed_lot.status != "active":
            raise SowingValidationError(f"seed lot {sid} is not active")
        if seed_lot.crop_id != workflow.crop_id:
            raise SowingValidationError(f"seed lot {sid} crop does not match the batch's workflow crop")
        if seed_lot.variety_id != workflow.variety_id:
            raise SowingValidationError(f"seed lot {sid} variety does not match the batch's workflow variety")
        if seed_lot.received_date is not None and local_sow_date < seed_lot.received_date:
            raise InvalidSowingEffectiveTimeError(f"seed lot {sid} has not yet been received on the sowing date")
        if seed_lot.expiry_date is not None and local_sow_date > seed_lot.expiry_date:
            raise InvalidSowingEffectiveTimeError(f"seed lot {sid} is expired on the sowing date")

    event = SowingEvent(
        id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, batch_id=batch.id,
        active_batch_stage_run_id=active_run.id, effective_time=effective_time,
        actor_user_id=actor_user_id, client_command_id=client_command_id,
        request_fingerprint=request_fingerprint, note=note,
        seeding_station_id=seeding_station_id, seeding_machine_id=seeding_machine_id,
        seed_lot_id=canonical_seed_lot_id,
    )
    db.add(event)
    db.flush()

    assignment_by_carrier: dict[uuid.UUID, BatchCarrierAssignment] = {}
    for cid in sorted_carrier_ids:
        assignment = BatchCarrierAssignment(
            id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, batch_id=batch.id, carrier_id=cid,
            batch_stage_run_id=active_run.id, assigned_effective_time=effective_time,
            released_effective_time=None, opening_sowing_event_id=event.id, actor_user_id=actor_user_id,
        )
        db.add(assignment)
        assignment_by_carrier[cid] = assignment
    db.flush()

    for line in lines:
        db.add(
            SowingEventLine(
                id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, sowing_event_id=event.id,
                batch_carrier_assignment_id=assignment_by_carrier[line["carrier_id"]].id,
                carrier_id=line["carrier_id"], seed_lot_id=line["seed_lot_id"],
                sown_site_count=line["sown_site_count"], seed_count=line["seed_count"],
                line_note=line.get("line_note"),
            )
        )
    db.flush()

    return event


def sow_batch(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    batch_id: uuid.UUID,
    client_command_id: uuid.UUID,
    effective_time: datetime,
    note: str | None,
    lines: list[dict],
) -> SowingEvent:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    fingerprint = _compute_sowing_fingerprint(
        tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, batch_id=batch_id,
        effective_time=effective_time, note=note, lines=lines,
    )

    existing = _find_existing_sowing_event(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise SowingCommandReusedWithDifferentPayloadError(str(client_command_id))

    # Lock the batch row HERE (in the wrapper, before any idempotency
    # re-check) -- `_sow_batch_core` below re-locks the same row again,
    # which is a harmless no-op re-entrant lock within the same
    # transaction/session. This ordering matters: both re-checks below
    # must run AFTER serialization, or a losing concurrent duplicate (same
    # client_command_id, racing another attempt against the same batch)
    # could slip past both checks before either commits and reach
    # `_sow_batch_core`'s own carrier-conflict check instead of resolving
    # as a replay -- exactly the bug this lock-then-recheck ordering
    # prevents (see test_concurrent_duplicate_sowing_command_id_is_idempotent).
    batch = db.execute(
        select(CropBatch)
        .where(CropBatch.id == batch_id, CropBatch.tenant_id == tenant_id, CropBatch.farm_id == farm_id)
        .with_for_update()
    ).scalar_one_or_none()
    if batch is None:
        raise CropBatchNotFoundError(str(batch_id))

    # Re-check idempotency now that we're serialized behind the batch lock.
    existing = _find_existing_sowing_event(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise SowingCommandReusedWithDifferentPayloadError(str(client_command_id))

    # NURSERY-OPS-001: a genuinely new command targeting a batch that
    # already has a Sowing Event is rejected outright -- at most one ever,
    # system-wide (see BatchAlreadySownError, ux_sowing_events_batch_id).
    # Checked here too (after the lock, after the replay re-check) so a
    # losing concurrent duplicate resolves deterministically as "already
    # sown" rather than racing into the carrier-conflict check below.
    already_sown = _find_existing_sowing_event_for_batch(db, tenant_id=tenant_id, batch_id=batch_id)
    if already_sown is not None:
        raise BatchAlreadySownError(str(batch_id))

    # Everything from here on operates on an already-flushed `event` row (or
    # fails before any row exists). Any failure — expected or not — must
    # roll back the whole command; assignments and lines must never be left
    # half-written against a committed event, and the session must not
    # carry a failed transaction into the caller.
    try:
        event = _sow_batch_core(
            db, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, batch_id=batch_id,
            client_command_id=client_command_id, effective_time=effective_time, note=note, lines=lines,
            request_fingerprint=fingerprint,
        )
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        # A losing concurrent duplicate of the SAME client_command_id can
        # violate ux_sowing_events_batch_id and
        # ux_sowing_events_tenant_client_command_id simultaneously (both
        # target the very row the winner just committed) -- which one
        # Postgres reports is not guaranteed by insertion/definition order,
        # so a genuine replay must always be checked first, regardless of
        # which constraint name comes back, before ever concluding
        # "already sown by a DIFFERENT command" (section 18's ordering
        # rule: replay resolves before any other mutable-state
        # conclusion).
        if constraint in ("ux_sowing_events_tenant_client_command_id", "ux_sowing_events_batch_id"):
            replay = _find_existing_sowing_event(db, tenant_id=tenant_id, client_command_id=client_command_id)
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            if constraint == "ux_sowing_events_batch_id":
                raise BatchAlreadySownError(str(batch_id)) from exc
            raise SowingCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise
    except Exception:
        db.rollback()
        raise

    try:
        sorted_carrier_ids = sorted({line["carrier_id"] for line in lines})
        sorted_seed_lot_ids = sorted({line["seed_lot_id"] for line in lines})
        site_counts = [line["sown_site_count"] for line in lines]
        # NURSERY-OPS-001.1: sown_site_count may now be unrecorded (None)
        # per line -- summing would either crash or silently treat unknown
        # as zero, so the total is itself None unless EVERY line's site
        # count is actually known.
        total_sown_site_count = sum(site_counts) if all(c is not None for c in site_counts) else None
        append_audit_event(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="crop_batch.sown",
            entity_type="sowing_event", entity_id=event.id,
            event_data={
                "sowing_event_id": str(event.id), "batch_id": str(batch_id),
                "batch_stage_run_id": str(event.active_batch_stage_run_id), "effective_time": effective_time.isoformat(),
                "client_command_id": str(client_command_id), "carrier_count": len(sorted_carrier_ids),
                "total_sown_site_count": total_sown_site_count,
                "total_seed_count": sum(line["seed_count"] for line in lines),
                "seed_lot_ids": [str(sid) for sid in sorted_seed_lot_ids],
                "carrier_ids": [str(cid) for cid in sorted_carrier_ids],
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(event)
    return event


# --- Sowing reads -----------------------------------------------------------------


def _sowing_event_header_query():
    return (
        select(
            SowingEvent,
            CropBatch.code.label("batch_code"),
            CropBatch.workflow_version_id.label("workflow_version_id"),
            WorkflowStage,
            Location,
            Asset,
        )
        .join(CropBatch, CropBatch.id == SowingEvent.batch_id)
        .join(BatchStageRun, BatchStageRun.id == SowingEvent.active_batch_stage_run_id)
        .join(WorkflowStage, WorkflowStage.id == BatchStageRun.workflow_stage_id)
        .outerjoin(Location, Location.id == SowingEvent.seeding_station_id)
        .outerjoin(Asset, Asset.id == SowingEvent.seeding_machine_id)
    )


def _load_lines_for_events(db: Session, *, event_ids: list[uuid.UUID]) -> dict[uuid.UUID, list]:
    grouped: dict[uuid.UUID, list] = {eid: [] for eid in event_ids}
    if not event_ids:
        return grouped
    rows = db.execute(
        select(SowingEventLine, Carrier, CarrierType, SeedLot, Crop, Variety)
        .join(Carrier, Carrier.id == SowingEventLine.carrier_id)
        .join(CarrierType, CarrierType.id == Carrier.carrier_type_id)
        .join(SeedLot, SeedLot.id == SowingEventLine.seed_lot_id)
        .join(Crop, Crop.id == SeedLot.crop_id)
        .join(Variety, Variety.id == SeedLot.variety_id)
        .where(SowingEventLine.sowing_event_id.in_(event_ids))
        .order_by(Carrier.code, Carrier.id)
    ).all()
    for line, carrier, carrier_type, seed_lot, crop, variety in rows:
        grouped[line.sowing_event_id].append(
            SowingEventLineRead(
                id=line.id,
                batch_carrier_assignment_id=line.batch_carrier_assignment_id,
                carrier=CarrierSummary(
                    id=carrier.id, code=carrier.code,
                    carrier_type=CarrierTypeSummary(id=carrier_type.id, code=carrier_type.code, name=carrier_type.name),
                ),
                seed_lot=SeedLotSummary(
                    id=seed_lot.id, code=seed_lot.code, supplier_lot_reference=seed_lot.supplier_lot_reference,
                    crop=CropSummary(id=crop.id, code=crop.code, common_name=crop.common_name),
                    variety=VarietySummary(id=variety.id, code=variety.code, name=variety.name),
                ),
                sown_site_count=line.sown_site_count, seed_count=line.seed_count, line_note=line.line_note,
            )
        )
    return grouped


def _row_to_sowing_event_read(row, lines: list) -> SowingEventRead:
    event: SowingEvent = row[0]
    m = row._mapping
    stage: WorkflowStage = row[3]
    seeding_station: Location | None = row[4]
    seeding_machine: Asset | None = row[5]
    return SowingEventRead(
        id=event.id, tenant_id=event.tenant_id, farm_id=event.farm_id, batch_id=event.batch_id,
        batch_code=m["batch_code"], workflow_version_id=m["workflow_version_id"],
        stage=StageSummary(id=stage.id, code=stage.code, name=stage.name, is_terminal=stage.is_terminal),
        effective_time=event.effective_time, recorded_time=event.recorded_time,
        actor_user_id=event.actor_user_id, client_command_id=event.client_command_id, note=event.note,
        seeding_station=(
            SeedingStationSummary(id=seeding_station.id, code=seeding_station.code, name=seeding_station.name)
            if seeding_station is not None else None
        ),
        seeding_machine=(
            SeedingMachineSummary(id=seeding_machine.id, code=seeding_machine.code, name=seeding_machine.name)
            if seeding_machine is not None else None
        ),
        lines=lines,
        total_seeds_sown=sum(line.seed_count for line in lines),
    )


def get_sowing_event(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID, sowing_event_id: uuid.UUID
) -> SowingEventRead:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    _get_batch_row(db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id)
    row = db.execute(
        _sowing_event_header_query().where(
            SowingEvent.id == sowing_event_id, SowingEvent.tenant_id == tenant_id, SowingEvent.batch_id == batch_id
        )
    ).first()
    if row is None:
        raise SowingEventNotFoundError(str(sowing_event_id))
    lines = _load_lines_for_events(db, event_ids=[sowing_event_id])[sowing_event_id]
    return _row_to_sowing_event_read(row, lines)


def list_sowing_events(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID
) -> list[SowingEventRead]:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    _get_batch_row(db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id)
    rows = db.execute(
        _sowing_event_header_query()
        .where(SowingEvent.tenant_id == tenant_id, SowingEvent.batch_id == batch_id)
        .order_by(SowingEvent.effective_time, SowingEvent.recorded_time)
    ).all()
    event_ids = [r[0].id for r in rows]
    lines_by_event = _load_lines_for_events(db, event_ids=event_ids)
    return [_row_to_sowing_event_read(r, lines_by_event[r[0].id]) for r in rows]


# --- Carrier-assignment reads ------------------------------------------------------


def _assignment_row_to_read(row) -> BatchCarrierAssignmentRead:
    assignment, carrier, carrier_type = row
    return BatchCarrierAssignmentRead(
        id=assignment.id, batch_id=assignment.batch_id,
        carrier=CarrierSummary(
            id=carrier.id, code=carrier.code,
            carrier_type=CarrierTypeSummary(id=carrier_type.id, code=carrier_type.code, name=carrier_type.name),
        ),
        assigned_effective_time=assignment.assigned_effective_time,
        released_effective_time=assignment.released_effective_time,
        opening_sowing_event_id=assignment.opening_sowing_event_id,
        opening_transplant_event_id=assignment.opening_transplant_event_id,
        released_by_transplant_event_id=assignment.released_by_transplant_event_id,
        opening_batch_derivation_event_id=assignment.opening_batch_derivation_event_id,
        released_by_batch_derivation_event_id=assignment.released_by_batch_derivation_event_id,
    )


def list_batch_carriers(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID
) -> list[BatchCarrierAssignmentRead]:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    _get_batch_row(db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id)
    rows = db.execute(
        select(BatchCarrierAssignment, Carrier, CarrierType)
        .join(Carrier, Carrier.id == BatchCarrierAssignment.carrier_id)
        .join(CarrierType, CarrierType.id == Carrier.carrier_type_id)
        .where(BatchCarrierAssignment.tenant_id == tenant_id, BatchCarrierAssignment.batch_id == batch_id)
        .order_by(Carrier.code, Carrier.id)
    ).all()
    return [_assignment_row_to_read(row) for row in rows]


def get_carrier_batch_assignment(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, carrier_id: uuid.UUID
) -> BatchCarrierAssignmentRead | None:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    carrier_service.get_carrier(db, tenant_id=tenant_id, farm_id=farm_id, carrier_id=carrier_id)
    row = db.execute(
        select(BatchCarrierAssignment, Carrier, CarrierType)
        .join(Carrier, Carrier.id == BatchCarrierAssignment.carrier_id)
        .join(CarrierType, CarrierType.id == Carrier.carrier_type_id)
        .where(
            BatchCarrierAssignment.tenant_id == tenant_id,
            BatchCarrierAssignment.carrier_id == carrier_id,
            BatchCarrierAssignment.released_effective_time.is_(None),
        )
    ).first()
    if row is None:
        return None
    return _assignment_row_to_read(row)
