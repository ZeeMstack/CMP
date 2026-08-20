import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.batch_stage_run import BatchStageRun
from app.models.carrier import Carrier
from app.models.carrier_specification import CarrierSpecification
from app.models.carrier_type import CarrierType
from app.models.crop import Crop
from app.models.crop_batch import CropBatch
from app.models.seed_lot import SeedLot
from app.models.seedling_entry import SeedlingEntry
from app.models.seedling_source_checkpoint import SeedlingSourceCheckpoint
from app.models.sowing_event_line import SowingEventLine
from app.models.transplant_allocation import TransplantAllocation
from app.models.transplant_destination_line import TransplantDestinationLine
from app.models.transplant_event import TransplantEvent
from app.models.transplant_source_line import TransplantSourceLine
from app.models.variety import Variety
from app.models.workflow_stage import WorkflowStage
from app.schemas.crop_batch import StageSummary
from app.schemas.sowing_event import CarrierSummary, CarrierTypeSummary, CropSummary, SeedLotSummary, VarietySummary
from app.schemas.transplant_event import (
    TransplantAllocationRead,
    TransplantDestinationLineRead,
    TransplantEventRead,
    TransplantSourceLineRead,
)
from app.services import farm_service, seedling_disposition_service
from app.services.audit import append_audit_event
from app.services.errors import (
    CarrierNotFoundError,
    CropBatchClosedError,
    CropBatchNotFoundError,
    DestinationCarrierAlreadyAssignedError,
    FarmNotFoundError,
    InvalidTransplantEffectiveTimeError,
    SourceAssignmentAlreadyReleasedError,
    SourceAssignmentHasNoSeedlingEntryError,
    SourceAssignmentNotFoundError,
    TooManyTransplantLinesError,
    TransplantCapacityExceededError,
    TransplantCommandReusedWithDifferentPayloadError,
    TransplantEventNotFoundError,
    TransplantValidationError,
)

MAX_SOURCE_LINES = 200
MAX_DESTINATION_LINES = 500
MAX_ALLOCATIONS = 2000


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


# --- Idempotency ------------------------------------------------------------------


def _compute_transplant_fingerprint(
    *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, batch_id: uuid.UUID,
    effective_time: datetime, note: str | None, source_lines: list[dict], destination_lines: list[dict],
    allocations: list[dict],
) -> str:
    """NURSERY-OPS-004A section 47: the fingerprint covers every logical
    caller-controlled fact -- including the new categorized loss counts --
    but deliberately never a server-derived quantity (`source_plant_count`/
    `source_available_before`, `remainder_after`): those are recomputed
    fresh on every call (including a replay) from the same authoritative
    Seedling balance, never trusted from a prior computation."""
    sorted_sources = sorted(source_lines, key=lambda line: str(line["source_assignment_id"]))
    sorted_destinations = sorted(destination_lines, key=lambda line: str(line["destination_carrier_id"]))
    sorted_allocations = sorted(
        allocations, key=lambda a: (str(a["source_assignment_id"]), str(a["destination_carrier_id"]))
    )
    parts = [
        str(tenant_id), str(farm_id), str(actor_user_id), str(batch_id),
        effective_time.astimezone(timezone.utc).isoformat(), note or "",
    ]
    for line in sorted_sources:
        parts.extend(
            [
                str(line["source_assignment_id"]), str(line["transplant_damage_count"]),
                str(line["qc_rejection_count"]), str(line["sample_count"]), str(line["other_loss_count"]),
                line.get("other_loss_note") or "", line.get("note") or "",
            ]
        )
    for line in sorted_destinations:
        parts.extend(
            [str(line["destination_carrier_id"]), str(line["assigned_plant_count"]), line.get("note") or ""]
        )
    for a in sorted_allocations:
        parts.extend(
            [str(a["source_assignment_id"]), str(a["destination_carrier_id"]), str(a["allocated_plant_count"])]
        )
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _find_existing_transplant_event(
    db: Session, *, tenant_id: uuid.UUID, client_command_id: uuid.UUID
) -> TransplantEvent | None:
    return db.execute(
        select(TransplantEvent).where(
            TransplantEvent.tenant_id == tenant_id, TransplantEvent.client_command_id == client_command_id
        )
    ).scalar_one_or_none()


# --- Command ------------------------------------------------------------------------


def _record_transplant_core(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    batch_id: uuid.UUID,
    client_command_id: uuid.UUID,
    effective_time: datetime,
    note: str | None,
    source_lines: list[dict],
    destination_lines: list[dict],
    allocations: list[dict],
) -> tuple[TransplantEvent, bool]:
    """NURSERY-OPS-004B.0: the validate+lock+write core of `record_transplant`,
    with no commit and no refresh -- extracted so a future composite
    orchestration (NURSERY-OPS-004B: transplant + destination Movement/
    Occupancy in one outer transaction) can call this directly, exactly the
    same extraction pattern `movement_service._execute_movement_core` and
    `seedling_entry_service`'s own composition of it already established.
    Returns `(event, is_new)` -- `is_new=False` whenever `event` is an
    already-committed row returned by an idempotency short-circuit (exact
    replay before any lock, exact replay after the CropBatch lock, or a
    concurrent-race replay recovered from a flush-time IntegrityError); the
    caller must skip `db.commit()`/`db.refresh()` in that case, since
    nothing new was written this call. `is_new=True` only when this call
    itself created the TransplantEvent and its full write set below.

    NURSERY-OPS-004A: source authority is entirely server-derived from
    SeedlingEntry + SeedlingDispositionEvents + SeedlingSourceCheckpoints
    (never caller-supplied, never bounded by `sown_site_count`/`seed_count`).
    Each source line's `source_plant_count` becomes the authoritative
    `source_available_before`; `remainder_after` is server-computed and
    persisted as an immutable `SeedlingSourceCheckpoint` chained to any
    prior checkpoint for the same Tray. A source assignment is released iff
    its own `remainder_after == 0`; otherwise it remains active for a
    future, sequential partial transplant. Same CropBatch throughout --
    never calls `batch_derivation_service`, never creates a child Batch.

    Deliberately carries no blanket `except Exception: db.rollback()` --
    only the flush-time `IntegrityError` branch below calls `db.rollback()`,
    because Postgres has already forced that transaction into an aborted
    state by that point regardless (the same constraint
    `_execute_movement_core`'s own docstring documents, made explicit here
    rather than engineered away). A non-DB exception raised inside this
    core (e.g. from `append_audit_event`) is NOT caught here -- rollback
    ownership for that case belongs to whichever caller owns the outer
    transaction (the public `record_transplant` wrapper below, or a future
    composite orchestration), never to this reusable core. A caller
    composing this core with earlier writes of its own in the SAME
    transaction must therefore call this core FIRST, before any write it
    cannot afford to lose to the IntegrityError-triggered rollback below --
    exactly the same caveat already accepted for `_execute_movement_core`."""
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    if effective_time > datetime.now(timezone.utc):
        raise InvalidTransplantEffectiveTimeError("effective_time cannot be in the future")
    if len(source_lines) > MAX_SOURCE_LINES:
        raise TooManyTransplantLinesError(f"a transplant command may include at most {MAX_SOURCE_LINES} source lines")
    if len(destination_lines) > MAX_DESTINATION_LINES:
        raise TooManyTransplantLinesError(
            f"a transplant command may include at most {MAX_DESTINATION_LINES} destination lines"
        )
    if len(allocations) > MAX_ALLOCATIONS:
        raise TooManyTransplantLinesError(f"a transplant command may include at most {MAX_ALLOCATIONS} allocations")

    fingerprint = _compute_transplant_fingerprint(
        tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, batch_id=batch_id,
        effective_time=effective_time, note=note, source_lines=source_lines,
        destination_lines=destination_lines, allocations=allocations,
    )

    # Section 26: exact replay resolves here, before ANY lock, before
    # checkpoint/current-state validation, before source-availability
    # recomputation -- must survive a newer checkpoint, lower source
    # availability, a since-released source assignment, or newer
    # dispositions, exactly like every other command in this codebase.
    existing = _find_existing_transplant_event(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing, False
        raise TransplantCommandReusedWithDifferentPayloadError(str(client_command_id))

    batch = db.execute(
        select(CropBatch)
        .where(CropBatch.id == batch_id, CropBatch.tenant_id == tenant_id, CropBatch.farm_id == farm_id)
        .with_for_update()
    ).scalar_one_or_none()
    if batch is None:
        raise CropBatchNotFoundError(str(batch_id))

    existing = _find_existing_transplant_event(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing, False
        raise TransplantCommandReusedWithDifferentPayloadError(str(client_command_id))

    if batch.state != "active":
        raise CropBatchClosedError(str(batch_id))

    active_run = db.execute(
        select(BatchStageRun)
        .where(BatchStageRun.batch_id == batch.id, BatchStageRun.exited_effective_time.is_(None))
        .with_for_update()
    ).scalar_one_or_none()
    if active_run is None:
        raise CropBatchNotFoundError(str(batch_id))

    stage = db.get(WorkflowStage, active_run.workflow_stage_id)
    if stage.stage_category != "transplanting":
        raise TransplantValidationError("current workflow stage is not a transplanting stage")
    if stage.required_carrier_type_id is None:
        raise TransplantValidationError(
            "current transplanting stage has no required destination carrier type configured"
        )

    if effective_time < batch.created_effective_time:
        raise InvalidTransplantEffectiveTimeError("effective_time precedes the batch's creation effective time")
    if effective_time < active_run.entered_effective_time:
        raise InvalidTransplantEffectiveTimeError("effective_time precedes the current stage run's entry time")

    # Source carriers are derived from (immutable) assignment.carrier_id via an
    # unlocked read — safe because carrier_id never changes after insert.
    source_assignment_ids = sorted({line["source_assignment_id"] for line in source_lines})
    unlocked_source_assignments = list(
        db.execute(
            select(BatchCarrierAssignment).where(BatchCarrierAssignment.id.in_(source_assignment_ids))
        ).scalars()
    )
    unlocked_by_id = {a.id: a for a in unlocked_source_assignments}
    for aid in source_assignment_ids:
        if aid not in unlocked_by_id:
            raise SourceAssignmentNotFoundError(str(aid))

    destination_carrier_ids = sorted({line["destination_carrier_id"] for line in destination_lines})
    source_carrier_ids = sorted({unlocked_by_id[aid].carrier_id for aid in source_assignment_ids})

    overlap = set(source_carrier_ids) & set(destination_carrier_ids)
    if overlap:
        raise TransplantValidationError(f"carrier(s) {sorted(overlap)} cannot be both source and destination")

    all_carrier_ids = sorted(set(source_carrier_ids) | set(destination_carrier_ids))
    carriers = list(
        db.execute(
            select(Carrier)
            .where(Carrier.id.in_(all_carrier_ids), Carrier.tenant_id == tenant_id, Carrier.farm_id == farm_id)
            .order_by(Carrier.id)
            .with_for_update()
        ).scalars()
    )
    carriers_by_id = {c.id: c for c in carriers}
    for cid in all_carrier_ids:
        if cid not in carriers_by_id:
            raise CarrierNotFoundError(str(cid))

    active_assignment_carrier_ids = set(
        db.execute(
            select(BatchCarrierAssignment.carrier_id).where(
                BatchCarrierAssignment.tenant_id == tenant_id,
                BatchCarrierAssignment.carrier_id.in_(destination_carrier_ids),
                BatchCarrierAssignment.released_effective_time.is_(None),
            )
        ).scalars()
    )

    # NURSERY-OPS-004B.1: destination biological capacity. Every destination
    # carrier in one command already shares the same `carrier_type_id` (the
    # check just below this block enforces that), so the destination
    # CarrierType's `requires_specification` only needs resolving once. One
    # batched specification lookup, never a query per destination -- mirrors
    # CARRIER-CONFIG-001B's identical pattern in
    # `sowing_service._sow_batch_core`. Deliberately does NOT read
    # `CarrierSpecification.status` -- an existing active Carrier whose
    # specification has since gone inactive remains eligible (frozen product
    # rule, section 3): a specification going inactive only blocks NEW
    # Carrier registrations against it, never Transplant eligibility for a
    # Carrier that already references it.
    destination_carrier_type = db.get(CarrierType, stage.required_carrier_type_id)
    destination_line_by_carrier_id = {line["destination_carrier_id"]: line for line in destination_lines}
    destination_specification_ids = {
        carriers_by_id[cid].specification_id
        for cid in destination_carrier_ids
        if carriers_by_id[cid].specification_id is not None
    }
    destination_specifications_by_id: dict[uuid.UUID, CarrierSpecification] = {}
    if destination_specification_ids:
        destination_specifications_by_id = {
            s.id: s
            for s in db.execute(
                select(CarrierSpecification).where(CarrierSpecification.id.in_(destination_specification_ids))
            ).scalars()
        }

    for cid in destination_carrier_ids:
        carrier = carriers_by_id[cid]
        if carrier.status != "active":
            raise TransplantValidationError(f"destination carrier {cid} is not active")
        if carrier.carrier_type_id != stage.required_carrier_type_id:
            raise TransplantValidationError(
                f"destination carrier {cid} does not match the transplanting stage's required carrier type"
            )
        if cid in active_assignment_carrier_ids:
            raise DestinationCarrierAlreadyAssignedError(str(cid))

        specification = (
            destination_specifications_by_id.get(carrier.specification_id)
            if carrier.specification_id is not None
            else None
        )
        if destination_carrier_type.requires_specification:
            if specification is None or specification.biological_position_count is None:
                raise TransplantValidationError(
                    f"destination carrier {cid} requires a specification with a positive "
                    f"biological_position_count, but none is configured"
                )
        if specification is not None and specification.biological_position_count is not None:
            assigned_plant_count = destination_line_by_carrier_id[cid]["assigned_plant_count"]
            if assigned_plant_count > specification.biological_position_count:
                raise TransplantCapacityExceededError(
                    f"destination carrier {cid}: assigned_plant_count ({assigned_plant_count}) exceeds its "
                    f"specification's biological_position_count ({specification.biological_position_count})"
                )

    # Lock source assignments in deterministic order and re-validate under lock.
    assignments = list(
        db.execute(
            select(BatchCarrierAssignment)
            .where(BatchCarrierAssignment.id.in_(source_assignment_ids))
            .order_by(BatchCarrierAssignment.id)
            .with_for_update()
        ).scalars()
    )
    assignments_by_id = {a.id: a for a in assignments}

    # Section 5/21: modern source authority is SeedlingEntry-anchored --
    # lock each source's SeedlingEntry too (deterministic id order,
    # AFTER assignments -- section 44's chain), and resolve
    # source_available_before from the checkpoint-aware anchor formula,
    # never from sown_site_count/seed_count.
    entries_by_assignment: dict[uuid.UUID, SeedlingEntry] = {}
    seedling_entry_rows = list(
        db.execute(
            select(SeedlingEntry)
            .where(SeedlingEntry.batch_carrier_assignment_id.in_(source_assignment_ids))
            .order_by(SeedlingEntry.id)
            .with_for_update()
        ).scalars()
    )
    for entry in seedling_entry_rows:
        entries_by_assignment[entry.batch_carrier_assignment_id] = entry

    for aid in source_assignment_ids:
        assignment = assignments_by_id[aid]
        if assignment.tenant_id != tenant_id or assignment.farm_id != farm_id or assignment.batch_id != batch.id:
            raise SourceAssignmentNotFoundError(str(aid))
        if assignment.released_effective_time is not None:
            raise SourceAssignmentAlreadyReleasedError(str(aid))
        if aid not in entries_by_assignment:
            raise SourceAssignmentHasNoSeedlingEntryError(str(aid))
        if effective_time < assignment.assigned_effective_time:
            raise InvalidTransplantEffectiveTimeError(
                f"effective_time precedes source assignment {aid}'s assigned_effective_time"
            )
        carrier = carriers_by_id[assignment.carrier_id]
        if carrier.status != "active":
            raise TransplantValidationError(f"source carrier {assignment.carrier_id} is not active")

    # Section 6/7/22/23: derive each source's server-authoritative
    # source_available_before, and enforce the append-forward temporal
    # floor against the currently-open balance window (the latest
    # checkpoint, or SeedlingEntry itself if none exists yet). Mirrors the
    # DB trigger's own branching exactly: once a checkpoint exists it has
    # already frozen everything through its own effective_time, so a new
    # transplant must be strictly AFTER it; with no checkpoint yet, a
    # transplant AT the SeedlingEntry's own effective_time is still valid.
    source_available_before: dict[uuid.UUID, int] = {}
    for aid in source_assignment_ids:
        entry = entries_by_assignment[aid]
        anchor_value, anchor_time, has_checkpoint = seedling_disposition_service.get_source_availability_anchor(
            db, seedling_entry=entry
        )
        floor_violated = effective_time <= anchor_time if has_checkpoint else effective_time < anchor_time
        if floor_violated:
            raise InvalidTransplantEffectiveTimeError(
                f"effective_time precedes source assignment {aid}'s currently-open balance window "
                f"(anchor at {anchor_time.isoformat()})"
            )
        source_available_before[aid] = seedling_disposition_service.get_source_available(
            db, seedling_entry=entry, as_of=effective_time
        )

    # --- Per-source reconciliation (section 16/17) ---------------------------------
    allocated_by_source: dict[uuid.UUID, int] = {}
    allocated_by_destination: dict[uuid.UUID, int] = {}
    for a in allocations:
        allocated_by_source[a["source_assignment_id"]] = (
            allocated_by_source.get(a["source_assignment_id"], 0) + a["allocated_plant_count"]
        )
        allocated_by_destination[a["destination_carrier_id"]] = (
            allocated_by_destination.get(a["destination_carrier_id"], 0) + a["allocated_plant_count"]
        )

    remainder_by_source: dict[uuid.UUID, int] = {}
    discarded_by_source: dict[uuid.UUID, int] = {}
    for line in source_lines:
        aid = line["source_assignment_id"]
        available = source_available_before[aid]
        successful = allocated_by_source.get(aid, 0)
        damage = line["transplant_damage_count"]
        rejection = line["qc_rejection_count"]
        sample = line["sample_count"]
        other = line["other_loss_count"]
        discarded = damage + rejection + sample + other
        remainder = available - successful - discarded
        if remainder < 0:
            raise TransplantValidationError(
                f"source assignment {aid} does not reconcile: successful {successful} + damage {damage} "
                f"+ rejection {rejection} + sample {sample} + other {other} exceeds the authoritative "
                f"source_available_before {available}"
            )
        remainder_by_source[aid] = remainder
        discarded_by_source[aid] = discarded

    for line in destination_lines:
        cid = line["destination_carrier_id"]
        allocated = allocated_by_destination.get(cid, 0)
        if allocated != line["assigned_plant_count"]:
            raise TransplantValidationError(
                f"destination carrier {cid} does not reconcile: allocated {allocated} != "
                f"assigned_plant_count {line['assigned_plant_count']}"
            )

    total_source = sum(source_available_before.values())
    total_destination = sum(line["assigned_plant_count"] for line in destination_lines)
    total_discarded = sum(discarded_by_source.values())
    total_remainder = sum(remainder_by_source.values())
    if total_source != total_destination + total_discarded + total_remainder:
        raise TransplantValidationError("transplant event totals do not reconcile")

    # --- Writes -------------------------------------------------------------------
    try:
        event = TransplantEvent(
            id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, batch_id=batch.id,
            active_batch_stage_run_id=active_run.id, effective_time=effective_time, actor_user_id=actor_user_id,
            client_command_id=client_command_id, request_fingerprint=fingerprint, note=note,
        )
        db.add(event)
        db.flush()

        source_line_by_assignment: dict[uuid.UUID, TransplantSourceLine] = {}
        for line in source_lines:
            aid = line["source_assignment_id"]
            source_line = TransplantSourceLine(
                id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, transplant_event_id=event.id,
                source_batch_carrier_assignment_id=aid, source_carrier_id=assignments_by_id[aid].carrier_id,
                source_plant_count=source_available_before[aid], discarded_plant_count=discarded_by_source[aid],
                transplant_damage_count=line["transplant_damage_count"], qc_rejection_count=line["qc_rejection_count"],
                sample_count=line["sample_count"], other_loss_count=line["other_loss_count"],
                other_loss_note=line.get("other_loss_note"), note=line.get("note"),
            )
            db.add(source_line)
            source_line_by_assignment[aid] = source_line
        db.flush()

        destination_assignment_by_carrier: dict[uuid.UUID, BatchCarrierAssignment] = {}
        for line in destination_lines:
            cid = line["destination_carrier_id"]
            destination_assignment = BatchCarrierAssignment(
                id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, batch_id=batch.id, carrier_id=cid,
                batch_stage_run_id=active_run.id, assigned_effective_time=effective_time,
                released_effective_time=None, opening_sowing_event_id=None,
                opening_transplant_event_id=event.id, released_by_transplant_event_id=None,
                actor_user_id=actor_user_id,
            )
            db.add(destination_assignment)
            destination_assignment_by_carrier[cid] = destination_assignment
        db.flush()

        destination_line_by_carrier: dict[uuid.UUID, TransplantDestinationLine] = {}
        for line in destination_lines:
            cid = line["destination_carrier_id"]
            destination_line = TransplantDestinationLine(
                id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, transplant_event_id=event.id,
                destination_batch_carrier_assignment_id=destination_assignment_by_carrier[cid].id,
                destination_carrier_id=cid, assigned_plant_count=line["assigned_plant_count"],
                note=line.get("note"),
            )
            db.add(destination_line)
            destination_line_by_carrier[cid] = destination_line
        db.flush()

        for a in allocations:
            db.add(
                TransplantAllocation(
                    id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, transplant_event_id=event.id,
                    source_line_id=source_line_by_assignment[a["source_assignment_id"]].id,
                    destination_line_id=destination_line_by_carrier[a["destination_carrier_id"]].id,
                    allocated_plant_count=a["allocated_plant_count"],
                )
            )
        db.flush()

        # Section 10/22: exactly one checkpoint per modern source line,
        # inserted LAST (after allocations exist, so the DB trigger can
        # verify remainder arithmetic against real allocation sums),
        # chained to the actual latest prior checkpoint for that Tray.
        for aid in source_assignment_ids:
            entry = entries_by_assignment[aid]
            previous_checkpoint_id = db.execute(
                select(SeedlingSourceCheckpoint.id)
                .where(SeedlingSourceCheckpoint.seedling_entry_id == entry.id)
                .order_by(
                    SeedlingSourceCheckpoint.effective_time.desc(),
                    SeedlingSourceCheckpoint.recorded_at.desc(),
                    SeedlingSourceCheckpoint.id.desc(),
                )
                .limit(1)
            ).scalar_one_or_none()
            db.add(
                SeedlingSourceCheckpoint(
                    id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, batch_id=batch.id,
                    seedling_entry_id=entry.id, source_batch_carrier_assignment_id=aid,
                    transplant_source_line_id=source_line_by_assignment[aid].id,
                    previous_checkpoint_id=previous_checkpoint_id,
                    remainder_after=remainder_by_source[aid], effective_time=effective_time,
                )
            )
        db.flush()

        # Section 29/30/45: conditional release -- only when this source's
        # own remainder reaches zero, and only AFTER its own checkpoint
        # exists (the checkpoint trigger itself asserts the assignment is
        # still active at checkpoint-insert time -- releasing first would
        # make every full-consumption transplant trip that guard against
        # itself). One source reaching zero must never release another
        # source that still has remainder (each assignment decided
        # independently).
        for aid, assignment in assignments_by_id.items():
            if remainder_by_source[aid] == 0:
                assignment.released_effective_time = effective_time
                assignment.released_by_transplant_event_id = event.id
        db.flush()

        append_audit_event(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="crop_batch.transplanted",
            entity_type="transplant_event", entity_id=event.id,
            event_data={
                "transplant_event_id": str(event.id), "batch_id": str(batch.id),
                "batch_stage_run_id": str(active_run.id), "effective_time": effective_time.isoformat(),
                "client_command_id": str(client_command_id),
                "source_assignment_ids": [str(aid) for aid in source_assignment_ids],
                "source_carrier_ids": [str(cid) for cid in source_carrier_ids],
                "destination_assignment_ids": [
                    str(destination_assignment_by_carrier[cid].id) for cid in destination_carrier_ids
                ],
                "destination_carrier_ids": [str(cid) for cid in destination_carrier_ids],
                "source_line_count": len(source_lines), "destination_line_count": len(destination_lines),
                "allocation_count": len(allocations), "total_source_available_before": total_source,
                "total_destination_plant_count": total_destination, "total_discarded_plant_count": total_discarded,
                "total_remainder_after": total_remainder,
            },
        )
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_transplant_events_tenant_client_command_id":
            replay = _find_existing_transplant_event(db, tenant_id=tenant_id, client_command_id=client_command_id)
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay, False
            raise TransplantCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise
    return event, True


def record_transplant(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    batch_id: uuid.UUID,
    client_command_id: uuid.UUID,
    effective_time: datetime,
    note: str | None,
    source_lines: list[dict],
    destination_lines: list[dict],
    allocations: list[dict],
) -> TransplantEvent:
    """Public entry point: runs `_record_transplant_core` then owns the
    transaction boundary (commit + refresh) itself, exactly as before this
    function was split -- every existing caller's behavior is unchanged.
    `db.rollback()` on any exception from the core (not just IntegrityError)
    preserves this function's own long-standing contract that no partial
    write ever survives a failed transplant command, exactly as the
    combined function did before NURSERY-OPS-004B.0's extraction -- this is
    deliberately kept here, on the public wrapper that owns the transaction,
    rather than inside the reusable core (see `_record_transplant_core`'s
    own docstring)."""
    try:
        event, is_new = _record_transplant_core(
            db, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, batch_id=batch_id,
            client_command_id=client_command_id, effective_time=effective_time, note=note,
            source_lines=source_lines, destination_lines=destination_lines, allocations=allocations,
        )
    except Exception:
        db.rollback()
        raise
    if is_new:
        db.commit()
        db.refresh(event)
    return event


# --- Reads ------------------------------------------------------------------------


def _transplant_event_header_query():
    return (
        select(
            TransplantEvent,
            CropBatch.code.label("batch_code"),
            CropBatch.workflow_version_id.label("workflow_version_id"),
            WorkflowStage,
        )
        .join(CropBatch, CropBatch.id == TransplantEvent.batch_id)
        .join(BatchStageRun, BatchStageRun.id == TransplantEvent.active_batch_stage_run_id)
        .join(WorkflowStage, WorkflowStage.id == BatchStageRun.workflow_stage_id)
    )


def _load_source_lines(db: Session, *, event_ids: list[uuid.UUID]) -> dict[uuid.UUID, list]:
    grouped: dict[uuid.UUID, list] = {eid: [] for eid in event_ids}
    if not event_ids:
        return grouped
    # Aggregate manually since multiple allocations may share a source line.
    totals: dict[uuid.UUID, int] = {}
    for row in db.execute(
        select(TransplantAllocation.source_line_id, TransplantAllocation.allocated_plant_count)
    ).all():
        totals[row[0]] = totals.get(row[0], 0) + row[1]

    checkpoints_by_line: dict[uuid.UUID, uuid.UUID] = {}
    for row in db.execute(
        select(SeedlingSourceCheckpoint.transplant_source_line_id, SeedlingSourceCheckpoint.id)
    ).all():
        checkpoints_by_line[row[0]] = row[1]

    rows = db.execute(
        select(TransplantSourceLine, Carrier, CarrierType, SeedLot, Crop, Variety, SowingEventLine.sowing_event_id)
        .join(Carrier, Carrier.id == TransplantSourceLine.source_carrier_id)
        .join(CarrierType, CarrierType.id == Carrier.carrier_type_id)
        .join(SowingEventLine, SowingEventLine.batch_carrier_assignment_id == TransplantSourceLine.source_batch_carrier_assignment_id)
        .join(SeedLot, SeedLot.id == SowingEventLine.seed_lot_id)
        .join(Crop, Crop.id == SeedLot.crop_id)
        .join(Variety, Variety.id == SeedLot.variety_id)
        .where(TransplantSourceLine.transplant_event_id.in_(event_ids))
        .order_by(Carrier.code, Carrier.id)
    ).all()
    for source_line, carrier, carrier_type, seed_lot, crop, variety, sowing_event_id in rows:
        successful = totals.get(source_line.id, 0)
        grouped[source_line.transplant_event_id].append(
            TransplantSourceLineRead(
                id=source_line.id,
                source_batch_carrier_assignment_id=source_line.source_batch_carrier_assignment_id,
                carrier=CarrierSummary(
                    id=carrier.id, code=carrier.code,
                    carrier_type=CarrierTypeSummary(id=carrier_type.id, code=carrier_type.code, name=carrier_type.name),
                ),
                seed_lot=SeedLotSummary(
                    id=seed_lot.id, code=seed_lot.code, supplier_lot_reference=seed_lot.supplier_lot_reference,
                    crop=CropSummary(id=crop.id, code=crop.code, common_name=crop.common_name),
                    variety=VarietySummary(id=variety.id, code=variety.code, name=variety.name),
                ),
                sowing_event_id=sowing_event_id,
                source_available_before=source_line.source_plant_count,
                successful_transferred_count=successful,
                transplant_damage_count=source_line.transplant_damage_count,
                qc_rejection_count=source_line.qc_rejection_count,
                sample_count=source_line.sample_count,
                other_loss_count=source_line.other_loss_count,
                other_loss_note=source_line.other_loss_note,
                discarded_plant_count=source_line.discarded_plant_count,
                remainder_after=source_line.source_plant_count - successful - source_line.discarded_plant_count,
                checkpoint_id=checkpoints_by_line[source_line.id],
                note=source_line.note,
            )
        )
    return grouped


def _load_destination_lines(db: Session, *, event_ids: list[uuid.UUID]) -> dict[uuid.UUID, list]:
    grouped: dict[uuid.UUID, list] = {eid: [] for eid in event_ids}
    if not event_ids:
        return grouped
    totals: dict[uuid.UUID, int] = {}
    for row in db.execute(
        select(TransplantAllocation.destination_line_id, TransplantAllocation.allocated_plant_count)
    ).all():
        totals[row[0]] = totals.get(row[0], 0) + row[1]

    rows = db.execute(
        select(TransplantDestinationLine, Carrier, CarrierType)
        .join(Carrier, Carrier.id == TransplantDestinationLine.destination_carrier_id)
        .join(CarrierType, CarrierType.id == Carrier.carrier_type_id)
        .where(TransplantDestinationLine.transplant_event_id.in_(event_ids))
        .order_by(Carrier.code, Carrier.id)
    ).all()
    for destination_line, carrier, carrier_type in rows:
        grouped[destination_line.transplant_event_id].append(
            TransplantDestinationLineRead(
                id=destination_line.id,
                destination_batch_carrier_assignment_id=destination_line.destination_batch_carrier_assignment_id,
                carrier=CarrierSummary(
                    id=carrier.id, code=carrier.code,
                    carrier_type=CarrierTypeSummary(id=carrier_type.id, code=carrier_type.code, name=carrier_type.name),
                ),
                assigned_plant_count=destination_line.assigned_plant_count,
                allocated_plant_count=totals.get(destination_line.id, 0),
                note=destination_line.note,
            )
        )
    return grouped


def _load_allocations(db: Session, *, event_ids: list[uuid.UUID]) -> dict[uuid.UUID, list]:
    grouped: dict[uuid.UUID, list] = {eid: [] for eid in event_ids}
    if not event_ids:
        return grouped
    rows = db.execute(
        select(
            TransplantAllocation,
            TransplantSourceLine.source_carrier_id,
            TransplantDestinationLine.destination_carrier_id,
        )
        .join(TransplantSourceLine, TransplantSourceLine.id == TransplantAllocation.source_line_id)
        .join(TransplantDestinationLine, TransplantDestinationLine.id == TransplantAllocation.destination_line_id)
        .where(TransplantAllocation.transplant_event_id.in_(event_ids))
    ).all()
    carrier_ids = {r[1] for r in rows} | {r[2] for r in rows}
    carriers_by_id: dict[uuid.UUID, tuple[Carrier, CarrierType]] = {}
    if carrier_ids:
        for carrier, carrier_type in db.execute(
            select(Carrier, CarrierType)
            .join(CarrierType, CarrierType.id == Carrier.carrier_type_id)
            .where(Carrier.id.in_(carrier_ids))
        ).all():
            carriers_by_id[carrier.id] = (carrier, carrier_type)

    def _summary(cid: uuid.UUID) -> CarrierSummary:
        carrier, carrier_type = carriers_by_id[cid]
        return CarrierSummary(
            id=carrier.id, code=carrier.code,
            carrier_type=CarrierTypeSummary(id=carrier_type.id, code=carrier_type.code, name=carrier_type.name),
        )

    for allocation, source_carrier_id, destination_carrier_id in rows:
        grouped[allocation.transplant_event_id].append(
            TransplantAllocationRead(
                id=allocation.id, source_carrier=_summary(source_carrier_id),
                destination_carrier=_summary(destination_carrier_id),
                allocated_plant_count=allocation.allocated_plant_count,
            )
        )
    for event_id in grouped:
        grouped[event_id].sort(key=lambda a: (a.source_carrier.code, a.destination_carrier.code))
    return grouped


def _row_to_transplant_event_read(row, source_lines: list, destination_lines: list, allocations: list) -> TransplantEventRead:
    event: TransplantEvent = row[0]
    m = row._mapping
    stage: WorkflowStage = row[3]
    return TransplantEventRead(
        id=event.id, tenant_id=event.tenant_id, farm_id=event.farm_id, batch_id=event.batch_id,
        batch_code=m["batch_code"], workflow_version_id=m["workflow_version_id"],
        stage=StageSummary(id=stage.id, code=stage.code, name=stage.name, is_terminal=stage.is_terminal),
        effective_time=event.effective_time, recorded_time=event.recorded_time,
        actor_user_id=event.actor_user_id, client_command_id=event.client_command_id, note=event.note,
        source_lines=source_lines, destination_lines=destination_lines, allocations=allocations,
        total_source_available_before=sum(line.source_available_before for line in source_lines),
        total_destination_plant_count=sum(line.assigned_plant_count for line in destination_lines),
        total_discarded_plant_count=sum(line.discarded_plant_count for line in source_lines),
        total_remainder_after=sum(line.remainder_after for line in source_lines),
    )


def get_transplant_event(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID, transplant_event_id: uuid.UUID
) -> TransplantEventRead:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    _get_batch_row(db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id)
    row = db.execute(
        _transplant_event_header_query().where(
            TransplantEvent.id == transplant_event_id, TransplantEvent.tenant_id == tenant_id,
            TransplantEvent.batch_id == batch_id,
        )
    ).first()
    if row is None:
        raise TransplantEventNotFoundError(str(transplant_event_id))
    source_lines = _load_source_lines(db, event_ids=[transplant_event_id])[transplant_event_id]
    destination_lines = _load_destination_lines(db, event_ids=[transplant_event_id])[transplant_event_id]
    allocations = _load_allocations(db, event_ids=[transplant_event_id])[transplant_event_id]
    return _row_to_transplant_event_read(row, source_lines, destination_lines, allocations)


def list_transplant_events(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID
) -> list[TransplantEventRead]:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    _get_batch_row(db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id)
    rows = db.execute(
        _transplant_event_header_query()
        .where(TransplantEvent.tenant_id == tenant_id, TransplantEvent.batch_id == batch_id)
        .order_by(TransplantEvent.effective_time, TransplantEvent.recorded_time)
    ).all()
    event_ids = [r[0].id for r in rows]
    source_by_event = _load_source_lines(db, event_ids=event_ids)
    destination_by_event = _load_destination_lines(db, event_ids=event_ids)
    allocations_by_event = _load_allocations(db, event_ids=event_ids)
    return [
        _row_to_transplant_event_read(
            r, source_by_event[r[0].id], destination_by_event[r[0].id], allocations_by_event[r[0].id]
        )
        for r in rows
    ]
