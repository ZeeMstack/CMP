import hashlib
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.batch_stage_run import BatchStageRun
from app.models.carrier import Carrier
from app.models.carrier_type import CarrierType
from app.models.crop import Crop
from app.models.crop_batch import CropBatch
from app.models.harvest_event import HarvestEvent
from app.models.harvest_population_event import HarvestPopulationEvent
from app.models.harvest_source_line import HarvestSourceLine
from app.models.harvest_source_line_correction import HarvestSourceLineCorrection
from app.models.harvested_produce_lot import HarvestedProduceLot
from app.models.produce_lot_ledger_entry import ProduceLotLedgerEntry
from app.models.variety import Variety
from app.models.workflow import Workflow
from app.models.workflow_stage import WorkflowStage
from app.schemas.crop_batch import CropSummary, StageSummary, VarietySummary, WorkflowSummary
from app.schemas.harvest import (
    MAX_WEIGHT_KG,
    MAX_WHOLE_UNIT_COUNT,
    HarvestedProduceLotRead,
    HarvestEventRead,
    HarvestSourceLineRead,
    canonical_decimal_str,
)
from app.schemas.leafy_harvest import (
    HarvestablePlateRead,
    LeafyHarvestEventRead,
    LeafyHarvestLocationRead,
    LeafyHarvestSourceLineCorrectionRead,
    LeafyHarvestSourceLineRead,
    LeafyLocationSlotRead,
)
from app.schemas.sowing_event import CarrierSummary, CarrierTypeSummary
from app.services import (
    farm_service,
    leafy_population_service,
    movement_service,
    produce_lot_ledger_service,
    quality_hold_service,
)
from app.services.audit import append_audit_event
from app.services.errors import (
    CarrierNotFoundError,
    CropBatchClosedError,
    CropBatchNotFoundError,
    DuplicateProduceLotCodeError,
    FarmNotFoundError,
    HarvestCarrierReusedError,
    HarvestCommandReusedWithDifferentPayloadError,
    HarvestCorrectionAlreadySupersededError,
    HarvestCorrectionCommandReusedWithDifferentPayloadError,
    HarvestCorrectionValidationError,
    HarvestedProduceLotNotFoundError,
    HarvestEventNotFoundError,
    HarvestLedgerBalanceError,
    HarvestPopulationInsufficientError,
    HarvestSourceAssignmentNotFoundError,
    HarvestSourceLineNotFoundError,
    HarvestValidationError,
    InvalidHarvestEffectiveTimeError,
    NoPopulationRootError,
    QualityHoldOpenError,
    TooManyHarvestLinesError,
    UnsupportedHarvestSourceCarrierTypeError,
)

MAX_SOURCE_LINES = 500
PRODUCTION_CULTIVATION_PLATE_CARRIER_TYPE_CODE = "production_cultivation_plate"


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


def _compute_harvest_fingerprint(
    *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, batch_id: uuid.UUID,
    effective_time: datetime, produce_lot_code: str, note: str | None, source_lines: list[dict],
) -> str:
    sorted_lines = sorted(source_lines, key=lambda line: str(line["batch_carrier_assignment_id"]))
    parts = [
        str(tenant_id), str(farm_id), str(actor_user_id), str(batch_id),
        effective_time.astimezone(timezone.utc).isoformat(), produce_lot_code, note or "",
    ]
    for line in sorted_lines:
        parts.extend(
            [
                str(line["batch_carrier_assignment_id"]), canonical_decimal_str(line["harvested_weight_kg"]),
                str(line["whole_unit_count"]) if line["whole_unit_count"] is not None else "",
                line.get("note") or "",
            ]
        )
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _find_existing_harvest_event(
    db: Session, *, tenant_id: uuid.UUID, client_command_id: uuid.UUID
) -> HarvestEvent | None:
    return db.execute(
        select(HarvestEvent).where(
            HarvestEvent.tenant_id == tenant_id, HarvestEvent.client_command_id == client_command_id
        )
    ).scalar_one_or_none()


# --- Command ------------------------------------------------------------------------
#
# HARVEST-OPS-001: the write path below is factored into three shared
# primitives -- (1) idempotency + CropBatch lock + Quality Hold + active
# check, (2) source-assignment/Carrier locking + generic validation, (3)
# the event/lot/receipt-ledger/source-line insert block + commit -- reused
# BYTE-FOR-BYTE by both the generic CMP-013 `record_harvest` (unchanged
# behavior, its own `stage_category == "harvesting"` eligibility gate
# preserved exactly) and the new Leafy-specific `record_leafy_harvest`
# (no stage-category gate at all, per HARVEST-OPS-001 decision 3). Neither
# caller duplicates the insert block itself.


def _lock_batch_for_harvest(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID,
    client_command_id: uuid.UUID, fingerprint: str,
) -> tuple[CropBatch | None, HarvestEvent | None]:
    """Idempotency pre-check, CropBatch lock, idempotency re-check, Quality
    Hold, CropBatch-active -- identical for every Harvest recording path
    (generic and Leafy alike). Returns `(batch, None)` to proceed, or
    `(None, existing_event)` to short-circuit as an exact replay."""
    existing = _find_existing_harvest_event(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return None, existing
        raise HarvestCommandReusedWithDifferentPayloadError(str(client_command_id))

    batch = db.execute(
        select(CropBatch)
        .where(CropBatch.id == batch_id, CropBatch.tenant_id == tenant_id, CropBatch.farm_id == farm_id)
        .with_for_update()
    ).scalar_one_or_none()
    if batch is None:
        raise CropBatchNotFoundError(str(batch_id))

    existing = _find_existing_harvest_event(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return None, existing
        raise HarvestCommandReusedWithDifferentPayloadError(str(client_command_id))

    if quality_hold_service.has_open_quality_hold(db, batch_id=batch.id):
        raise QualityHoldOpenError(str(batch_id))

    if batch.state != "active":
        raise CropBatchClosedError(str(batch_id))

    return batch, None


def _lock_active_stage_run(db: Session, *, batch: CropBatch) -> BatchStageRun:
    active_run = db.execute(
        select(BatchStageRun)
        .where(BatchStageRun.batch_id == batch.id, BatchStageRun.exited_effective_time.is_(None))
        .with_for_update()
    ).scalar_one_or_none()
    if active_run is None:
        raise CropBatchNotFoundError(str(batch.id))
    return active_run


def _lock_and_validate_harvest_sources(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch: CropBatch,
    assignment_ids: list[uuid.UUID],
) -> tuple[dict[uuid.UUID, BatchCarrierAssignment], dict[uuid.UUID, Carrier]]:
    """Locks and validates every source BatchCarrierAssignment (must exist,
    belong to this tenant/farm/batch, be currently active) and every
    distinct source Carrier (must exist, be active) -- shared, generic
    shape for every Harvest recording path."""
    assignments = list(
        db.execute(
            select(BatchCarrierAssignment).where(BatchCarrierAssignment.id.in_(assignment_ids))
            .order_by(BatchCarrierAssignment.id).with_for_update()
        ).scalars()
    )
    assignments_by_id = {a.id: a for a in assignments}
    for aid in assignment_ids:
        assignment = assignments_by_id.get(aid)
        if (
            assignment is None or assignment.tenant_id != tenant_id or assignment.farm_id != farm_id
            or assignment.batch_id != batch.id
        ):
            raise HarvestSourceAssignmentNotFoundError(str(aid))
        if assignment.released_effective_time is not None:
            raise HarvestValidationError(f"source assignment {aid} is not active")

    carrier_ids = sorted({a.carrier_id for a in assignments})
    carriers = list(
        db.execute(
            select(Carrier).where(Carrier.id.in_(carrier_ids), Carrier.tenant_id == tenant_id, Carrier.farm_id == farm_id)
            .order_by(Carrier.id).with_for_update()
        ).scalars()
    )
    carriers_by_id = {c.id: c for c in carriers}
    for cid in carrier_ids:
        carrier = carriers_by_id.get(cid)
        if carrier is None:
            raise CarrierNotFoundError(str(cid))
        if carrier.status != "active":
            raise HarvestValidationError(f"carrier {cid} is not active")

    return assignments_by_id, carriers_by_id


def _write_harvest_event_and_lot(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    batch: CropBatch,
    active_run: BatchStageRun,
    client_command_id: uuid.UUID,
    fingerprint: str,
    effective_time: datetime,
    produce_lot_code: str,
    note: str | None,
    source_lines: list[dict],
    assignments_by_id: dict[uuid.UUID, BatchCarrierAssignment],
    after_lines_inserted: (
        Callable[[Session, HarvestEvent, HarvestedProduceLot, dict[uuid.UUID, uuid.UUID]], None] | None
    ) = None,
    on_integrity_error: Callable[[IntegrityError], None] | None = None,
) -> HarvestEvent:
    """The one insert-block-plus-commit primitive shared by every Harvest
    recording path. `after_lines_inserted` (Leafy only) runs INSIDE the
    same transaction, immediately after the source lines are flushed --
    this is where Leafy inserts its own `HarvestPopulationEvent` CONSUMPTION
    rows and performs any resulting BCA zero-release, so a population
    violation rolls back the entire command atomically (no partial
    HarvestEvent/HarvestSourceLine/ledger-receipt ever persists).
    `on_integrity_error` (Leafy only) gets first refusal on a caught
    IntegrityError, to translate a population chronological-balance
    violation into its own domain error before the generic constraint-name
    handling below runs."""
    assignment_ids = sorted(assignments_by_id.keys())

    if effective_time < batch.created_effective_time:
        raise InvalidHarvestEffectiveTimeError("effective_time precedes the batch's creation effective time")
    if effective_time < active_run.entered_effective_time:
        raise InvalidHarvestEffectiveTimeError("effective_time precedes the current stage run's entry time")
    for aid in assignment_ids:
        if effective_time < assignments_by_id[aid].assigned_effective_time:
            raise InvalidHarvestEffectiveTimeError(
                f"effective_time precedes source assignment {aid}'s assigned_effective_time"
            )

    total_weight: Decimal = sum((line["harvested_weight_kg"] for line in source_lines), Decimal("0"))
    counts = [line["whole_unit_count"] for line in source_lines]
    total_count = sum(counts) if all(c is not None for c in counts) else None

    # Each individual line already passed the same envelope at the Pydantic
    # layer, but the *sum* across many valid lines can still exceed the
    # produce-lot's own bound — reject before any write rather than letting
    # the database CHECK/column-range constraint surface as a raw,
    # untranslated IntegrityError.
    if total_weight >= MAX_WEIGHT_KG:
        raise HarvestValidationError("the sum of source-line weights exceeds the supported total weight range")
    if total_count is not None and total_count > MAX_WHOLE_UNIT_COUNT:
        raise HarvestValidationError("the sum of source-line whole-unit counts exceeds the supported total count range")

    event_id = uuid.uuid4()
    lot_id = uuid.uuid4()
    line_ids = {aid: uuid.uuid4() for aid in assignment_ids}

    try:
        event = HarvestEvent(
            id=event_id, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch.id,
            active_batch_stage_run_id=active_run.id, effective_time=effective_time, actor_user_id=actor_user_id,
            client_command_id=client_command_id, request_fingerprint=fingerprint, note=note,
        )
        db.add(event)
        db.flush()

        batch_workflow = db.get(Workflow, batch.workflow_id)
        lot = HarvestedProduceLot(
            id=lot_id, tenant_id=tenant_id, farm_id=farm_id, code=produce_lot_code, harvest_event_id=event.id,
            batch_id=batch.id, workflow_id=batch.workflow_id, workflow_version_id=batch.workflow_version_id,
            crop_id=batch_workflow.crop_id, variety_id=batch_workflow.variety_id,
            total_harvested_weight_kg=total_weight, total_whole_unit_count=total_count, effective_time=effective_time,
        )
        db.add(lot)
        db.flush()

        # Deterministic opening receipt (CMP-014): id and produce_lot_id
        # both equal the lot's own id — an exact, reconstructible
        # projection of the lot/event, not an independent user command.
        # recorded_time is taken from the lot's own recorded_at (not a
        # fresh server default) so live creation and migration backfill
        # always produce identical rows; note is always NULL — the harvest
        # event already owns the user-provided note.
        db.add(
            ProduceLotLedgerEntry(
                id=lot.id, tenant_id=tenant_id, farm_id=farm_id, produce_lot_id=lot.id, harvest_event_id=event.id,
                entry_kind="harvest_receipt", weight_delta_kg=lot.total_harvested_weight_kg,
                whole_unit_count_delta=lot.total_whole_unit_count, effective_time=lot.effective_time,
                recorded_time=lot.recorded_at, actor_user_id=actor_user_id, note=None,
            )
        )
        db.flush()

        for line in source_lines:
            aid = line["batch_carrier_assignment_id"]
            db.add(
                HarvestSourceLine(
                    id=line_ids[aid], tenant_id=tenant_id, farm_id=farm_id, harvest_event_id=event.id,
                    batch_carrier_assignment_id=aid, carrier_id=assignments_by_id[aid].carrier_id,
                    harvested_weight_kg=line["harvested_weight_kg"], whole_unit_count=line["whole_unit_count"],
                    note=line.get("note"),
                )
            )
        db.flush()

        if after_lines_inserted is not None:
            after_lines_inserted(db, event, lot, line_ids)

        append_audit_event(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="crop_batch.harvested",
            entity_type="harvest_event", entity_id=event.id,
            event_data={
                "harvest_event_id": str(event.id), "produce_lot_id": str(lot.id), "produce_lot_code": lot.code,
                "batch_id": str(batch.id), "batch_stage_run_id": str(active_run.id),
                "effective_time": effective_time.isoformat(), "client_command_id": str(client_command_id),
                "source_assignment_ids": [str(aid) for aid in assignment_ids],
                "source_carrier_ids": [str(assignments_by_id[aid].carrier_id) for aid in assignment_ids],
                "source_line_count": len(source_lines),
                "total_harvested_weight_kg": canonical_decimal_str(total_weight),
                "total_whole_unit_count": total_count,
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if on_integrity_error is not None:
            on_integrity_error(exc)
        constraint = _constraint_name(exc)
        if constraint == "ux_harvest_events_tenant_client_command_id":
            replay = _find_existing_harvest_event(db, tenant_id=tenant_id, client_command_id=client_command_id)
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise HarvestCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        if constraint == "ux_harvested_produce_lots_tenant_code_lower":
            raise DuplicateProduceLotCodeError(f"{tenant_id}:{produce_lot_code}") from exc
        raise
    except Exception:
        db.rollback()
        raise
    db.refresh(event)
    return event


def record_harvest(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    batch_id: uuid.UUID,
    client_command_id: uuid.UUID,
    effective_time: datetime,
    produce_lot_code: str,
    note: str | None,
    source_lines: list[dict],
) -> HarvestEvent:
    """CMP-013, unchanged behavior: generic, batch-scoped Harvest, gated on
    the Batch's current WorkflowStage being `stage_category == "harvesting"`
    -- preserved exactly for backward compatibility (HARVEST-OPS-001 does
    not weaken or bypass this)."""
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    if effective_time > datetime.now(timezone.utc):
        raise InvalidHarvestEffectiveTimeError("effective_time cannot be in the future")
    if len(source_lines) > MAX_SOURCE_LINES:
        raise TooManyHarvestLinesError(f"a harvest command may include at most {MAX_SOURCE_LINES} source lines")

    fingerprint = _compute_harvest_fingerprint(
        tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, batch_id=batch_id,
        effective_time=effective_time, produce_lot_code=produce_lot_code, note=note, source_lines=source_lines,
    )

    batch, replay = _lock_batch_for_harvest(
        db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id,
        client_command_id=client_command_id, fingerprint=fingerprint,
    )
    if replay is not None:
        return replay

    active_run = _lock_active_stage_run(db, batch=batch)
    stage = db.get(WorkflowStage, active_run.workflow_stage_id)
    if stage.stage_category != "harvesting":
        raise HarvestValidationError("current workflow stage is not a harvesting stage")

    assignment_ids = sorted({line["batch_carrier_assignment_id"] for line in source_lines})
    assignments_by_id, _carriers_by_id = _lock_and_validate_harvest_sources(
        db, tenant_id=tenant_id, farm_id=farm_id, batch=batch, assignment_ids=assignment_ids,
    )

    return _write_harvest_event_and_lot(
        db, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, batch=batch, active_run=active_run,
        client_command_id=client_command_id, fingerprint=fingerprint, effective_time=effective_time,
        produce_lot_code=produce_lot_code, note=note, source_lines=source_lines, assignments_by_id=assignments_by_id,
    )


# --- Leafy Production Harvest ---------------------------------------------------------


def _resolve_carrier_type_code(db: Session, *, carrier_type_id: uuid.UUID) -> str | None:
    return db.execute(select(CarrierType.code).where(CarrierType.id == carrier_type_id)).scalar_one_or_none()


def record_leafy_harvest(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    batch_id: uuid.UUID,
    client_command_id: uuid.UUID,
    effective_time: datetime,
    produce_lot_code: str,
    note: str | None,
    source_lines: list[dict],
) -> HarvestEvent:
    """HARVEST-OPS-001: Leafy Production Harvest -- shares every write
    primitive with the generic `record_harvest` above, but with its own
    eligibility rules (decision 3): no `stage_category` gate at all, every
    source line must be an active `production_cultivation_plate` BCA with
    a positive authoritative living population, `whole_unit_count` is
    mandatory and is the sole biological-population authority (weight
    never reduces population). All source lines must share one CropBatch
    (never merged across batches, decision 10) -- already true by
    construction, since `_lock_and_validate_harvest_sources` already
    requires every assignment to belong to `batch`.

    Locking order (multi-root deadlock prevention): CropBatch, then every
    affected population-root BCA in deterministic (sorted UUID) order --
    never the caller's own request row order."""
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    if effective_time > datetime.now(timezone.utc):
        raise InvalidHarvestEffectiveTimeError("effective_time cannot be in the future")
    if len(source_lines) > MAX_SOURCE_LINES:
        raise TooManyHarvestLinesError(f"a harvest command may include at most {MAX_SOURCE_LINES} source lines")
    for line in source_lines:
        if line.get("whole_unit_count") is None or line["whole_unit_count"] <= 0:
            raise HarvestValidationError("whole_unit_count is mandatory and must be positive for a Leafy source line")

    fingerprint = _compute_harvest_fingerprint(
        tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, batch_id=batch_id,
        effective_time=effective_time, produce_lot_code=produce_lot_code, note=note, source_lines=source_lines,
    )

    batch, replay = _lock_batch_for_harvest(
        db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id,
        client_command_id=client_command_id, fingerprint=fingerprint,
    )
    if replay is not None:
        return replay

    # No stage_category gate for Leafy Harvest (decision 3) -- still
    # requires a real active stage run, since HarvestEvent's own schema
    # requires one, but never inspects its category.
    active_run = _lock_active_stage_run(db, batch=batch)

    assignment_ids = sorted({line["batch_carrier_assignment_id"] for line in source_lines})
    assignments_by_id, carriers_by_id = _lock_and_validate_harvest_sources(
        db, tenant_id=tenant_id, farm_id=farm_id, batch=batch, assignment_ids=assignment_ids,
    )
    source_lines_by_aid = {line["batch_carrier_assignment_id"]: line for line in source_lines}

    root_ids: set[uuid.UUID] = set()
    for aid in assignment_ids:
        assignment = assignments_by_id[aid]
        carrier = carriers_by_id[assignment.carrier_id]
        carrier_type_code = _resolve_carrier_type_code(db, carrier_type_id=carrier.carrier_type_id)
        if carrier_type_code != PRODUCTION_CULTIVATION_PLATE_CARRIER_TYPE_CODE:
            raise UnsupportedHarvestSourceCarrierTypeError(str(aid))
        root_id = assignment.population_root_batch_carrier_assignment_id
        if root_id is None:
            raise NoPopulationRootError(str(aid))
        root_ids.add(root_id)

    # Lock every affected population-root BCA in deterministic (sorted
    # UUID string) order, never request row order -- the multi-root
    # deadlock-prevention rule.
    for root_id in sorted(root_ids, key=str):
        db.execute(
            select(BatchCarrierAssignment.id).where(BatchCarrierAssignment.id == root_id).with_for_update()
        ).scalar_one()

    for aid in assignment_ids:
        assignment = assignments_by_id[aid]
        root_id = assignment.population_root_batch_carrier_assignment_id
        count = source_lines_by_aid[aid]["whole_unit_count"]
        living = leafy_population_service.get_current_living_population(
            db, root_batch_carrier_assignment_id=root_id
        )
        if living <= 0:
            raise HarvestPopulationInsufficientError(
                f"source assignment {aid} has no current living population to harvest"
            )
        if count > living:
            raise HarvestPopulationInsufficientError(
                f"source assignment {aid}: requested {count} heads exceeds current living population {living}"
            )
        opening = leafy_population_service.get_root_opening_population(
            db, root_batch_carrier_assignment_id=root_id
        )
        leafy_population_service.validate_chronological_balance(
            db, root_batch_carrier_assignment_id=root_id, opening=opening,
            new_effective_time=effective_time, new_delta=-count,
        )

    def _after_lines_inserted(
        db: Session, event: HarvestEvent, lot: HarvestedProduceLot, line_ids: dict[uuid.UUID, uuid.UUID]
    ) -> None:
        for aid in assignment_ids:
            assignment = assignments_by_id[aid]
            root_id = assignment.population_root_batch_carrier_assignment_id
            count = source_lines_by_aid[aid]["whole_unit_count"]
            consumption = HarvestPopulationEvent(
                id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id,
                population_root_batch_carrier_assignment_id=root_id, batch_carrier_assignment_id=aid,
                event_kind="CONSUMPTION", quantity_delta=-count, effective_time=effective_time,
                reverses_event_id=None, original_harvest_source_line_id=line_ids[aid],
                harvest_source_line_correction_id=None,
            )
            db.add(consumption)
            db.flush()

            available_after = leafy_population_service.get_current_living_population(
                db, root_batch_carrier_assignment_id=root_id, as_of=effective_time
            )
            if available_after == 0:
                assignment.released_effective_time = effective_time
                assignment.released_by_harvest_population_event_id = consumption.id
                db.flush()

    def _on_integrity_error(exc: IntegrityError) -> None:
        if leafy_population_service.is_balance_violation_error(exc):
            raise HarvestPopulationInsufficientError(
                "recording this harvest would drive the chronological authoritative living-population balance "
                "out of range"
            ) from exc

    # CMP-013's own `enforce_harvest_event_insert_integrity` trigger enforces
    # `stage_category = 'harvesting'` at the DB level too, not merely in the
    # generic service's own Python check (decision 2: never weaken it for
    # the generic path). This transaction-local marker is the widened
    # trigger's own escape hatch for the Leafy path only -- reset
    # automatically at transaction end (commit or rollback), never leaks to
    # another connection/transaction.
    db.execute(text("SET LOCAL cmp.leafy_harvest = 'true'"))

    return _write_harvest_event_and_lot(
        db, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, batch=batch, active_run=active_run,
        client_command_id=client_command_id, fingerprint=fingerprint, effective_time=effective_time,
        produce_lot_code=produce_lot_code, note=note, source_lines=source_lines, assignments_by_id=assignments_by_id,
        after_lines_inserted=_after_lines_inserted, on_integrity_error=_on_integrity_error,
    )


# --- Reads ------------------------------------------------------------------------


def _opener_kind_and_id(assignment: BatchCarrierAssignment) -> tuple[str, uuid.UUID]:
    """HARVEST-OPS-001: widened to recognize every current BCA opener kind
    -- previously fell through to `("derivation", None)` for ANY restored
    generation (Transplant-, Seedling-Disposition-, or Production-
    Disposition-restored), silently wrong. Order matters only in that
    exactly one branch can ever match (`ck_batch_carrier_assignments_
    exactly_one_opener` guarantees this at the DB level), so first-match
    is always the correct match."""
    if assignment.opening_sowing_event_id is not None:
        return "sowing", assignment.opening_sowing_event_id
    if assignment.opening_transplant_event_id is not None:
        return "transplant", assignment.opening_transplant_event_id
    if assignment.opening_batch_derivation_event_id is not None:
        return "derivation", assignment.opening_batch_derivation_event_id
    if assignment.opening_transplant_reversal_event_id is not None:
        return "transplant_reversal", assignment.opening_transplant_reversal_event_id
    if assignment.opening_seedling_disposition_reversal_event_id is not None:
        return "seedling_disposition_reversal", assignment.opening_seedling_disposition_reversal_event_id
    if assignment.opening_production_disposition_reversal_event_id is not None:
        return "production_disposition_reversal", assignment.opening_production_disposition_reversal_event_id
    return "harvest_reversal", assignment.opening_harvest_population_reversal_event_id


def _load_source_lines(db: Session, *, event_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[HarvestSourceLineRead]]:
    grouped: dict[uuid.UUID, list[HarvestSourceLineRead]] = {eid: [] for eid in event_ids}
    if not event_ids:
        return grouped
    rows = db.execute(
        select(HarvestSourceLine, Carrier, CarrierType, BatchCarrierAssignment)
        .join(Carrier, Carrier.id == HarvestSourceLine.carrier_id)
        .join(CarrierType, CarrierType.id == Carrier.carrier_type_id)
        .join(BatchCarrierAssignment, BatchCarrierAssignment.id == HarvestSourceLine.batch_carrier_assignment_id)
        .where(HarvestSourceLine.harvest_event_id.in_(event_ids))
        .order_by(Carrier.code, Carrier.id)
    ).all()
    for source_line, carrier, carrier_type, assignment in rows:
        opening_kind, opening_id = _opener_kind_and_id(assignment)
        grouped[source_line.harvest_event_id].append(
            HarvestSourceLineRead(
                id=source_line.id, batch_carrier_assignment_id=source_line.batch_carrier_assignment_id,
                carrier=CarrierSummary(
                    id=carrier.id, code=carrier.code,
                    carrier_type=CarrierTypeSummary(id=carrier_type.id, code=carrier_type.code, name=carrier_type.name),
                ),
                opening_kind=opening_kind, opening_id=opening_id,
                harvested_weight_kg=source_line.harvested_weight_kg, whole_unit_count=source_line.whole_unit_count,
                note=source_line.note,
            )
        )
    return grouped


def _harvest_event_header_query():
    return (
        select(
            HarvestEvent, CropBatch.code.label("batch_code"), CropBatch.workflow_id.label("workflow_id"),
            CropBatch.workflow_version_id.label("workflow_version_id"), Workflow.code.label("workflow_code"),
            Workflow.name.label("workflow_name"), Crop, Variety, WorkflowStage,
            HarvestedProduceLot.id.label("lot_id"), HarvestedProduceLot.code.label("lot_code"),
        )
        .join(CropBatch, CropBatch.id == HarvestEvent.batch_id)
        .join(Workflow, Workflow.id == CropBatch.workflow_id)
        .join(Crop, Crop.id == Workflow.crop_id)
        .outerjoin(Variety, Variety.id == Workflow.variety_id)
        .join(BatchStageRun, BatchStageRun.id == HarvestEvent.active_batch_stage_run_id)
        .join(WorkflowStage, WorkflowStage.id == BatchStageRun.workflow_stage_id)
        .join(HarvestedProduceLot, HarvestedProduceLot.harvest_event_id == HarvestEvent.id)
    )


def _row_to_harvest_event_read(row, source_lines: list[HarvestSourceLineRead]) -> HarvestEventRead:
    event: HarvestEvent = row[0]
    m = row._mapping
    crop: Crop = row[6]
    variety: Variety | None = row[7]
    stage: WorkflowStage = row[8]
    total_weight = sum((line.harvested_weight_kg for line in source_lines), Decimal("0"))
    counts = [line.whole_unit_count for line in source_lines]
    total_count = sum(counts) if all(c is not None for c in counts) else None
    return HarvestEventRead(
        id=event.id, tenant_id=event.tenant_id, farm_id=event.farm_id, batch_id=event.batch_id,
        batch_code=m["batch_code"], workflow=WorkflowSummary(id=m["workflow_id"], code=m["workflow_code"], name=m["workflow_name"]),
        workflow_version_id=m["workflow_version_id"], crop=CropSummary(id=crop.id, code=crop.code, common_name=crop.common_name),
        variety=(VarietySummary(id=variety.id, code=variety.code, name=variety.name) if variety is not None else None),
        stage=StageSummary(id=stage.id, code=stage.code, name=stage.name, is_terminal=stage.is_terminal),
        produce_lot_id=m["lot_id"], produce_lot_code=m["lot_code"], effective_time=event.effective_time,
        recorded_time=event.recorded_time, actor_user_id=event.actor_user_id, client_command_id=event.client_command_id,
        note=event.note, source_lines=source_lines, total_harvested_weight_kg=total_weight,
        total_whole_unit_count=total_count,
    )


def get_harvest_event(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID, harvest_event_id: uuid.UUID
) -> HarvestEventRead:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    _get_batch_row(db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id)
    row = db.execute(
        _harvest_event_header_query().where(
            HarvestEvent.id == harvest_event_id, HarvestEvent.tenant_id == tenant_id, HarvestEvent.batch_id == batch_id
        )
    ).first()
    if row is None:
        raise HarvestEventNotFoundError(str(harvest_event_id))
    source_lines = _load_source_lines(db, event_ids=[harvest_event_id])[harvest_event_id]
    return _row_to_harvest_event_read(row, source_lines)


def list_harvest_events(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID
) -> list[HarvestEventRead]:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    _get_batch_row(db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id)
    rows = db.execute(
        _harvest_event_header_query()
        .where(HarvestEvent.tenant_id == tenant_id, HarvestEvent.batch_id == batch_id)
        .order_by(HarvestEvent.effective_time, HarvestEvent.recorded_time)
    ).all()
    event_ids = [r[0].id for r in rows]
    source_by_event = _load_source_lines(db, event_ids=event_ids)
    return [_row_to_harvest_event_read(r, source_by_event[r[0].id]) for r in rows]


def _produce_lot_header_query():
    return (
        select(
            HarvestedProduceLot, CropBatch.code.label("batch_code"), Workflow.code.label("workflow_code"),
            Workflow.name.label("workflow_name"), Crop, Variety,
        )
        .join(CropBatch, CropBatch.id == HarvestedProduceLot.batch_id)
        .join(Workflow, Workflow.id == HarvestedProduceLot.workflow_id)
        .join(Crop, Crop.id == HarvestedProduceLot.crop_id)
        .outerjoin(Variety, Variety.id == HarvestedProduceLot.variety_id)
    )


def _row_to_produce_lot_read(row, source_lines: list[HarvestSourceLineRead]) -> HarvestedProduceLotRead:
    lot: HarvestedProduceLot = row[0]
    m = row._mapping
    crop: Crop = row[4]
    variety: Variety | None = row[5]
    return HarvestedProduceLotRead(
        id=lot.id, tenant_id=lot.tenant_id, farm_id=lot.farm_id, code=lot.code, harvest_event_id=lot.harvest_event_id,
        batch_id=lot.batch_id, batch_code=m["batch_code"],
        workflow=WorkflowSummary(id=lot.workflow_id, code=m["workflow_code"], name=m["workflow_name"]),
        workflow_version_id=lot.workflow_version_id, crop=CropSummary(id=crop.id, code=crop.code, common_name=crop.common_name),
        variety=(VarietySummary(id=variety.id, code=variety.code, name=variety.name) if variety is not None else None),
        total_harvested_weight_kg=lot.total_harvested_weight_kg, total_whole_unit_count=lot.total_whole_unit_count,
        effective_time=lot.effective_time, recorded_at=lot.recorded_at, source_lines=source_lines,
    )


def get_produce_lot(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, produce_lot_id: uuid.UUID
) -> HarvestedProduceLotRead:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    row = db.execute(
        _produce_lot_header_query().where(
            HarvestedProduceLot.id == produce_lot_id, HarvestedProduceLot.tenant_id == tenant_id,
            HarvestedProduceLot.farm_id == farm_id,
        )
    ).first()
    if row is None:
        raise HarvestedProduceLotNotFoundError(str(produce_lot_id))
    lot: HarvestedProduceLot = row[0]
    source_lines = _load_source_lines(db, event_ids=[lot.harvest_event_id])[lot.harvest_event_id]
    return _row_to_produce_lot_read(row, source_lines)


def list_produce_lots(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> list[HarvestedProduceLotRead]:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    rows = db.execute(
        _produce_lot_header_query()
        .where(HarvestedProduceLot.tenant_id == tenant_id, HarvestedProduceLot.farm_id == farm_id)
        .order_by(HarvestedProduceLot.code)
    ).all()
    event_ids = [r[0].harvest_event_id for r in rows]
    source_by_event = _load_source_lines(db, event_ids=event_ids)
    return [_row_to_produce_lot_read(r, source_by_event[r[0].harvest_event_id]) for r in rows]


# --- Leafy Harvest correction -----------------------------------------------------
#
# HARVEST-OPS-001: the immutable, non-branching commercial/audit correction
# chain for one original HarvestSourceLine (`harvest_source_line_corrections`,
# linked list via `supersedes_correction_id`), and its atomic biological
# (`harvest_population_events` REVERSAL/CONSUMPTION) and commercial
# (`produce_lot_ledger_entries` "harvest_adjustment") consequences. Neither
# the original HarvestSourceLine nor HarvestedProduceLot rows are ever
# modified. See the migration's own docstring for the full repeated-
# correction, void, and zero-release/restore/re-zero worked proofs this
# implementation must reproduce exactly.


def resolve_current_correction(db: Session, *, harvest_source_line_id: uuid.UUID) -> uuid.UUID | None:
    """The chain TIP for one original line's correction history -- the one
    correction row (if any) nothing else's `supersedes_correction_id`
    names as its own predecessor. `None` means never corrected."""
    successor = aliased(HarvestSourceLineCorrection)
    return db.execute(
        select(HarvestSourceLineCorrection.id).where(
            HarvestSourceLineCorrection.harvest_source_line_id == harvest_source_line_id,
            ~select(successor.id)
            .where(successor.supersedes_correction_id == HarvestSourceLineCorrection.id)
            .exists(),
        )
    ).scalar_one_or_none()


def get_current_effective_source_line(db: Session, *, harvest_source_line_id: uuid.UUID) -> dict:
    """Current-effective truth for one original HarvestSourceLine --
    structural, from the chain's own pointers, never `recorded_at`. Returns
    `{"harvested_weight_kg", "whole_unit_count", "is_void",
    "tip_correction_id", "original_harvested_weight_kg",
    "original_whole_unit_count"}`."""
    line = db.execute(
        select(HarvestSourceLine).where(HarvestSourceLine.id == harvest_source_line_id)
    ).scalar_one_or_none()
    if line is None:
        raise HarvestSourceLineNotFoundError(str(harvest_source_line_id))
    tip_id = resolve_current_correction(db, harvest_source_line_id=harvest_source_line_id)
    if tip_id is None:
        return {
            "harvested_weight_kg": line.harvested_weight_kg, "whole_unit_count": line.whole_unit_count,
            "is_void": False, "tip_correction_id": None,
            "original_harvested_weight_kg": line.harvested_weight_kg,
            "original_whole_unit_count": line.whole_unit_count,
        }
    tip = db.get(HarvestSourceLineCorrection, tip_id)
    return {
        "harvested_weight_kg": tip.corrected_harvested_weight_kg, "whole_unit_count": tip.corrected_whole_unit_count,
        "is_void": tip.is_void, "tip_correction_id": tip.id,
        "original_harvested_weight_kg": line.harvested_weight_kg, "original_whole_unit_count": line.whole_unit_count,
    }


def get_correction_history(db: Session, *, harvest_source_line_id: uuid.UUID) -> list[HarvestSourceLineCorrection]:
    """The full correction chain for one original line, in chain order
    (structural -- walked from the root forward, never a raw `recorded_at`
    sort, though the two always agree for a validly-constructed chain)."""
    corrections = {
        c.id: c
        for c in db.execute(
            select(HarvestSourceLineCorrection).where(
                HarvestSourceLineCorrection.harvest_source_line_id == harvest_source_line_id
            )
        ).scalars()
    }
    by_predecessor = {c.supersedes_correction_id: c for c in corrections.values()}
    ordered: list[HarvestSourceLineCorrection] = []
    current = by_predecessor.get(None)
    while current is not None:
        ordered.append(current)
        current = by_predecessor.get(current.id)
    return ordered


def _resolve_effective_consumption(
    db: Session, *, harvest_source_line_id: uuid.UUID
) -> HarvestPopulationEvent | None:
    """The un-reversed CONSUMPTION currently effective for one original
    line's lineage -- either the ORIGINAL CONSUMPTION (never corrected) or
    the most recent non-void correction's own replacement CONSUMPTION.
    `None` means the line is currently void (nothing outstanding to
    reverse). At most one such row can exist at a time by construction --
    never resolved by `recorded_at`."""
    reverser = aliased(HarvestPopulationEvent)
    correction_ids_subq = select(HarvestSourceLineCorrection.id).where(
        HarvestSourceLineCorrection.harvest_source_line_id == harvest_source_line_id
    )
    return db.execute(
        select(HarvestPopulationEvent).where(
            HarvestPopulationEvent.event_kind == "CONSUMPTION",
            (
                (HarvestPopulationEvent.original_harvest_source_line_id == harvest_source_line_id)
                | (HarvestPopulationEvent.harvest_source_line_correction_id.in_(correction_ids_subq))
            ),
            ~select(reverser.id).where(reverser.reverses_event_id == HarvestPopulationEvent.id).exists(),
        )
    ).scalar_one_or_none()


def _compute_correction_fingerprint(
    *, tenant_id, farm_id, actor_user_id, harvest_source_line_id, supersedes_correction_id, is_void,
    corrected_harvested_weight_kg, corrected_whole_unit_count, reason_code: str, note: str,
) -> str:
    parts = [
        str(tenant_id), str(farm_id), str(actor_user_id) if actor_user_id else "", str(harvest_source_line_id),
        str(supersedes_correction_id) if supersedes_correction_id is not None else "",
        "void" if is_void else "replace",
        canonical_decimal_str(corrected_harvested_weight_kg) if corrected_harvested_weight_kg is not None else "",
        str(corrected_whole_unit_count) if corrected_whole_unit_count is not None else "",
        reason_code, note,
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _find_existing_correction(
    db: Session, *, tenant_id: uuid.UUID, client_command_id: uuid.UUID
) -> HarvestSourceLineCorrection | None:
    return db.execute(
        select(HarvestSourceLineCorrection).where(
            HarvestSourceLineCorrection.tenant_id == tenant_id,
            HarvestSourceLineCorrection.client_command_id == client_command_id,
        )
    ).scalar_one_or_none()


def correct_leafy_harvest(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_command_id: uuid.UUID,
    harvest_source_line_id: uuid.UUID,
    supersedes_correction_id: uuid.UUID | None,
    is_void: bool,
    corrected_harvested_weight_kg: Decimal | None,
    corrected_whole_unit_count: int | None,
    reason_code: str,
    note: str,
) -> HarvestSourceLineCorrection:
    """HARVEST-OPS-001: one atomic correction of one original
    HarvestSourceLine -- `supersedes_correction_id` is the caller's own
    belief about the current chain tip (`None` for the first-ever
    correction); a stale belief (someone else corrected first) is a 409
    conflict (`HarvestCorrectionAlreadySupersededError`), never a silent
    retarget. Every non-void correction stores the COMPLETE corrected
    tuple (both fields, even if the operator changed only one) -- the
    caller is responsible for copying the unchanged field forward from the
    predecessor's own effective value; this function does not infer it.

    Biological consequence: CASE 1 (an effective CONSUMPTION exists) --
    REVERSAL of that exact CONSUMPTION, then (if not void) a REPLACEMENT
    CONSUMPTION for the new corrected count. CASE 2 (currently void, no
    effective CONSUMPTION) -- no REVERSAL; a REPLACEMENT CONSUMPTION (if
    not void) is created directly. A REVERSAL/REPLACEMENT always shares the
    ORIGINAL HarvestEvent's own `effective_time` (correcting Harvest time
    itself is out of scope). If reversing the exhausting CONSUMPTION
    restores positive population and the lineage's tip BCA was released by
    that EXACT event, a NEW BCA generation is opened (never the old one
    reactivated) -- mirrors LEAFY-OPS-001's own restoration pattern
    exactly, including the Carrier-reuse-protection guard.

    Commercial consequence: exactly one `harvest_adjustment` ledger entry,
    delta = corrected-or-zero minus the PREDECESSOR's own effective tuple
    (never the original once a prior correction exists) -- rejected before
    any write if it would drive the produce lot's own available balance
    negative (some quantity already consumed downstream in Packing)."""
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    if is_void:
        if corrected_harvested_weight_kg is not None or corrected_whole_unit_count is not None:
            raise HarvestCorrectionValidationError("a void correction must not carry corrected values")
    else:
        if corrected_harvested_weight_kg is None or corrected_harvested_weight_kg <= 0:
            raise HarvestCorrectionValidationError(
                "corrected_harvested_weight_kg is required and must be positive for a non-void correction"
            )
        if corrected_whole_unit_count is None or corrected_whole_unit_count <= 0:
            raise HarvestCorrectionValidationError(
                "corrected_whole_unit_count is required and must be positive for a non-void correction"
            )
    if not reason_code or not reason_code.strip():
        raise HarvestCorrectionValidationError("reason_code is required")
    if not note or not note.strip():
        raise HarvestCorrectionValidationError("note is required")

    fingerprint = _compute_correction_fingerprint(
        tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id,
        harvest_source_line_id=harvest_source_line_id, supersedes_correction_id=supersedes_correction_id,
        is_void=is_void, corrected_harvested_weight_kg=corrected_harvested_weight_kg,
        corrected_whole_unit_count=corrected_whole_unit_count, reason_code=reason_code, note=note,
    )

    existing = _find_existing_correction(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise HarvestCorrectionCommandReusedWithDifferentPayloadError(str(client_command_id))

    line = db.execute(
        select(HarvestSourceLine).where(
            HarvestSourceLine.id == harvest_source_line_id, HarvestSourceLine.tenant_id == tenant_id,
            HarvestSourceLine.farm_id == farm_id,
        )
    ).scalar_one_or_none()
    if line is None:
        raise HarvestSourceLineNotFoundError(str(harvest_source_line_id))

    assignment = db.execute(
        select(BatchCarrierAssignment).where(BatchCarrierAssignment.id == line.batch_carrier_assignment_id)
    ).scalar_one()
    root_id = assignment.population_root_batch_carrier_assignment_id
    if root_id is None:
        raise NoPopulationRootError(str(line.batch_carrier_assignment_id))

    # Section 34-equivalent: CropBatch first (shared lock-order convention).
    batch = db.execute(select(CropBatch).where(CropBatch.id == assignment.batch_id).with_for_update()).scalar_one()

    existing = _find_existing_correction(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise HarvestCorrectionCommandReusedWithDifferentPayloadError(str(client_command_id))

    if batch.state != "active":
        raise CropBatchClosedError(str(batch.id))

    # Then the population-root BCA (shared lock-order convention).
    db.execute(select(BatchCarrierAssignment.id).where(BatchCarrierAssignment.id == root_id).with_for_update()).scalar_one()

    # Concurrency: the caller's believed predecessor must still be the
    # current tip -- the partial unique index is the ultimate DB-level
    # backstop (see the IntegrityError handling below); this is the
    # friendlier, race-narrowed pre-check.
    current_tip_id = resolve_current_correction(db, harvest_source_line_id=harvest_source_line_id)
    if current_tip_id != supersedes_correction_id:
        raise HarvestCorrectionAlreadySupersededError(str(harvest_source_line_id))

    if supersedes_correction_id is None:
        predecessor_weight, predecessor_count = line.harvested_weight_kg, line.whole_unit_count
    else:
        predecessor = db.get(HarvestSourceLineCorrection, supersedes_correction_id)
        if predecessor.is_void:
            predecessor_weight, predecessor_count = Decimal("0"), 0
        else:
            predecessor_weight = predecessor.corrected_harvested_weight_kg
            predecessor_count = predecessor.corrected_whole_unit_count

    # CTO CORRECTION 1: reject a correction that changes nothing about the
    # effective tuple from its own immediate predecessor -- friendlier,
    # earlier rejection than the DB's own insert-integrity backstop
    # (enforce_harvest_source_line_correction_insert_integrity), which
    # enforces this identically as the ultimate authority.
    new_weight = Decimal("0") if is_void else corrected_harvested_weight_kg
    new_count = 0 if is_void else corrected_whole_unit_count
    predecessor_count_normalized = predecessor_count if predecessor_count is not None else 0
    if new_weight == (predecessor_weight if predecessor_weight is not None else Decimal("0")) and new_count == predecessor_count_normalized:
        raise HarvestCorrectionValidationError(
            "this correction does not change the effective tuple from its own immediate predecessor"
        )

    original_event_effective_time = db.execute(
        select(HarvestEvent.effective_time).where(HarvestEvent.id == line.harvest_event_id)
    ).scalar_one()

    effective_consumption = _resolve_effective_consumption(db, harvest_source_line_id=harvest_source_line_id)

    active_id = leafy_population_service.resolve_active_assignment_id_for_root(
        db, root_batch_carrier_assignment_id=root_id
    )
    predecessor_to_restore: BatchCarrierAssignment | None = None
    target_bca: BatchCarrierAssignment | None = None
    if active_id is not None:
        # CASE A: some generation is still active -- the effective
        # consumption (if any) and any replacement both target it. No
        # restoration.
        target_bca = db.execute(
            select(BatchCarrierAssignment).where(BatchCarrierAssignment.id == active_id)
        ).scalar_one()
    else:
        # CASE B: the whole lineage is currently exhausted. Restoration is
        # permitted ONLY when the lineage tip was released by the EXACT
        # effective consumption being reversed here.
        tip_id = leafy_population_service.resolve_lineage_tip_assignment_id(
            db, root_batch_carrier_assignment_id=root_id
        )
        tip = db.execute(select(BatchCarrierAssignment).where(BatchCarrierAssignment.id == tip_id)).scalar_one()
        if effective_consumption is None or tip.released_by_harvest_population_event_id != effective_consumption.id:
            raise HarvestPopulationInsufficientError(
                "this population lineage is currently exhausted by an unrelated event and cannot be corrected here"
            )
        predecessor_to_restore = tip

    target_for_floor = target_bca if target_bca is not None else predecessor_to_restore

    if not is_void:
        opening = leafy_population_service.get_root_opening_population(
            db, root_batch_carrier_assignment_id=root_id
        )
        exclude_kwargs = (
            {"exclude_harvest_population_event_id": effective_consumption.id}
            if effective_consumption is not None
            else {}
        )
        leafy_population_service.validate_chronological_balance(
            db, root_batch_carrier_assignment_id=root_id, opening=opening,
            new_effective_time=original_event_effective_time, new_delta=-corrected_whole_unit_count,
            **exclude_kwargs,
        )

    # Carrier-reuse protection -- terminal-tier, only when actually
    # restoring (mirrors LEAFY-OPS-001's own guard exactly).
    if predecessor_to_restore is not None:
        carrier = db.execute(
            select(Carrier).where(Carrier.id == predecessor_to_restore.carrier_id).with_for_update()
        ).scalar_one()
        if carrier.latest_batch_carrier_assignment_id != predecessor_to_restore.id:
            raise HarvestCarrierReusedError(str(predecessor_to_restore.carrier_id))

    lot = db.execute(
        select(HarvestedProduceLot).where(HarvestedProduceLot.harvest_event_id == line.harvest_event_id)
    ).scalar_one()

    correction_id = uuid.uuid4()

    try:
        correction = HarvestSourceLineCorrection(
            id=correction_id, tenant_id=tenant_id, farm_id=farm_id, harvest_source_line_id=harvest_source_line_id,
            supersedes_correction_id=supersedes_correction_id, is_void=is_void,
            corrected_harvested_weight_kg=corrected_harvested_weight_kg,
            corrected_whole_unit_count=corrected_whole_unit_count, reason_code=reason_code, note=note,
            actor_user_id=actor_user_id, client_command_id=client_command_id, request_fingerprint=fingerprint,
        )
        db.add(correction)
        db.flush()

        reversal = None
        if effective_consumption is not None:
            reversal = HarvestPopulationEvent(
                id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id,
                population_root_batch_carrier_assignment_id=root_id,
                batch_carrier_assignment_id=effective_consumption.batch_carrier_assignment_id,
                event_kind="REVERSAL", quantity_delta=-effective_consumption.quantity_delta,
                effective_time=original_event_effective_time, reverses_event_id=effective_consumption.id,
                original_harvest_source_line_id=None, harvest_source_line_correction_id=None,
            )
            db.add(reversal)
            db.flush()

        restored_assignment_id: uuid.UUID | None = None
        if predecessor_to_restore is not None:
            target_bca = BatchCarrierAssignment(
                id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, batch_id=batch.id,
                carrier_id=predecessor_to_restore.carrier_id,
                batch_stage_run_id=predecessor_to_restore.batch_stage_run_id,
                assigned_effective_time=original_event_effective_time, released_effective_time=None,
                opening_harvest_population_reversal_event_id=reversal.id,
                restored_from_batch_carrier_assignment_id=predecessor_to_restore.id,
                population_root_batch_carrier_assignment_id=root_id, actor_user_id=actor_user_id,
            )
            db.add(target_bca)
            db.flush()
            restored_assignment_id = target_bca.id

        replacement = None
        if not is_void:
            replacement = HarvestPopulationEvent(
                id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id,
                population_root_batch_carrier_assignment_id=root_id, batch_carrier_assignment_id=target_bca.id,
                event_kind="CONSUMPTION", quantity_delta=-corrected_whole_unit_count,
                effective_time=original_event_effective_time, reverses_event_id=None,
                original_harvest_source_line_id=None, harvest_source_line_correction_id=correction.id,
            )
            db.add(replacement)
            db.flush()

            available_after = leafy_population_service.get_current_living_population(
                db, root_batch_carrier_assignment_id=root_id, as_of=original_event_effective_time
            )
            if available_after == 0:
                target_bca.released_effective_time = original_event_effective_time
                target_bca.released_by_harvest_population_event_id = replacement.id
                db.flush()

        # Ledger adjustment -- lock the lot, compute the prior balance,
        # reject before insert if this delta would drive it negative
        # (some quantity already consumed downstream in Grading --
        # POSTHARVEST-OPS-001E: Packing no longer touches this ledger at
        # all, so Grading is the only possible cause).
        db.execute(
            select(HarvestedProduceLot.id).where(HarvestedProduceLot.id == lot.id).with_for_update()
        ).scalar_one()
        prior = db.execute(
            select(
                func.coalesce(func.sum(ProduceLotLedgerEntry.weight_delta_kg), 0),
                func.coalesce(func.sum(ProduceLotLedgerEntry.whole_unit_count_delta), 0),
            ).where(ProduceLotLedgerEntry.produce_lot_id == lot.id)
        ).one()
        prior_weight, prior_count = prior[0], prior[1]

        new_weight = corrected_harvested_weight_kg if not is_void else Decimal("0")
        new_count = corrected_whole_unit_count if not is_void else 0
        old_weight = predecessor_weight if predecessor_weight is not None else Decimal("0")
        old_count = predecessor_count if predecessor_count is not None else 0
        weight_delta = new_weight - old_weight
        count_delta = new_count - old_count

        if weight_delta != 0 or count_delta != 0:
            remaining_weight = prior_weight + weight_delta
            remaining_count = prior_count + count_delta
            if remaining_weight < 0 or remaining_count < 0:
                raise HarvestLedgerBalanceError(
                    "this correction would reduce the available Harvest Lot below zero because some quantity has "
                    "already been consumed in grading"
                )
            db.add(
                ProduceLotLedgerEntry(
                    id=correction.id, tenant_id=tenant_id, farm_id=farm_id, produce_lot_id=lot.id,
                    harvest_source_line_correction_id=correction.id, entry_kind="harvest_adjustment",
                    weight_delta_kg=weight_delta, whole_unit_count_delta=(count_delta if count_delta != 0 else None),
                    effective_time=original_event_effective_time, recorded_time=correction.recorded_at,
                    actor_user_id=actor_user_id, note=note,
                )
            )
            db.flush()

        append_audit_event(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="crop_batch.harvest_corrected",
            entity_type="harvest_source_line_correction", entity_id=correction.id,
            event_data={
                "correction_id": str(correction.id), "client_command_id": str(client_command_id),
                "harvest_source_line_id": str(harvest_source_line_id),
                "supersedes_correction_id": str(supersedes_correction_id) if supersedes_correction_id else None,
                "is_void": is_void, "reason_code": reason_code, "note": note,
                "original_harvested_weight_kg": canonical_decimal_str(line.harvested_weight_kg),
                "original_whole_unit_count": line.whole_unit_count,
                "predecessor_harvested_weight_kg": canonical_decimal_str(old_weight) if predecessor_weight is not None else None,
                "predecessor_whole_unit_count": predecessor_count,
                "corrected_harvested_weight_kg": (
                    canonical_decimal_str(corrected_harvested_weight_kg) if corrected_harvested_weight_kg is not None else None
                ),
                "corrected_whole_unit_count": corrected_whole_unit_count,
                "ledger_weight_delta_kg": canonical_decimal_str(weight_delta),
                "ledger_whole_unit_count_delta": count_delta,
                "population_root_batch_carrier_assignment_id": str(root_id),
                "reversed_event_id": str(effective_consumption.id) if effective_consumption else None,
                "reversal_event_id": str(reversal.id) if reversal else None,
                "replacement_event_id": str(replacement.id) if replacement else None,
                "restored_batch_carrier_assignment_id": str(restored_assignment_id) if restored_assignment_id else None,
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_harvest_source_line_corrections_tenant_client_command_id":
            replay = _find_existing_correction(db, tenant_id=tenant_id, client_command_id=client_command_id)
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise HarvestCorrectionCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        if constraint in (
            "ux_harvest_source_line_corrections_root_once", "ux_harvest_source_line_corrections_successor_once",
        ):
            raise HarvestCorrectionAlreadySupersededError(str(harvest_source_line_id)) from exc
        if leafy_population_service.is_balance_violation_error(exc):
            raise HarvestPopulationInsufficientError(
                "recording this correction would drive the chronological authoritative living-population balance "
                "out of range"
            ) from exc
        # A bare `RAISE EXCEPTION` from a trigger (e.g. the DB-level no-op-
        # correction backstop) surfaces as a plain ProgrammingError, not an
        # IntegrityError, and is deliberately never translated here -- the
        # service's own Python-level check above already gives the
        # friendly error for every legitimate caller; this branch is
        # unreachable via normal use and is direct-SQL-bypass defense in
        # depth only, exactly like every other bare-message trigger
        # elsewhere in this codebase (never translated to a domain error).
        raise
    except Exception:
        db.rollback()
        raise
    db.refresh(correction)
    return correction


# --- Leafy Harvest operator-facing API surface (Slice 2) --------------------------
#
# HARVEST-OPS-001 SLICE 2: read models and one thin ownership-verifying
# wrapper for the HTTP layer. Never redesigns Slice-1's frozen write/
# correction core above -- `record_leafy_harvest` and `correct_leafy_
# harvest` are called unchanged. These functions only assemble the
# Leafy-aware Read schemas (current-effective-vs-original, correction
# history, harvestable-plate eligibility) on top of that frozen core.

_LEAFY_LOCATION_TYPE_CODES = ("greenhouse", "zone", "span", "grow_table")


def _resolve_leafy_harvest_location_breakdown(db: Session, *, location_id: uuid.UUID) -> dict[str, LeafyLocationSlotRead]:
    """Walks `parent_location_id` upward from one leaf Location, slotting
    each ancestor by its own `location_type_code` -- never a hardcoded
    depth (CLAUDE.md: generic, UUID-based parent-child locations). Small,
    operator-scale per-row cost; mirrors `production_disposition_service.
    _resolve_location_ancestry_label`'s own established precedent."""
    slots: dict[str, LeafyLocationSlotRead] = {}
    current_id: uuid.UUID | None = location_id
    hops = 0
    while current_id is not None and hops < 10:
        row = db.execute(
            text(
                "SELECT l.id, l.code, l.name, l.parent_location_id, lt.code AS type_code "
                "FROM locations l JOIN location_types lt ON lt.id = l.location_type_id WHERE l.id = :id"
            ),
            {"id": current_id},
        ).mappings().first()
        if row is None:
            break
        if row["type_code"] in _LEAFY_LOCATION_TYPE_CODES and row["type_code"] not in slots:
            slots[row["type_code"]] = LeafyLocationSlotRead(id=row["id"], code=row["code"], name=row["name"])
        current_id = row["parent_location_id"]
        hops += 1
    return slots


def _leafy_harvest_location_read(db: Session, *, location_id: uuid.UUID | None) -> LeafyHarvestLocationRead | None:
    if location_id is None:
        return None
    slots = _resolve_leafy_harvest_location_breakdown(db, location_id=location_id)
    return LeafyHarvestLocationRead(
        greenhouse=slots.get("greenhouse"), zone=slots.get("zone"), span=slots.get("span"),
        grow_table=slots.get("grow_table"),
    )


def list_harvestable_production_plates(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID | None = None,
) -> list[HarvestablePlateRead]:
    """Every currently-eligible Leafy Harvest source: an active (unreleased)
    `production_cultivation_plate` BatchCarrierAssignment with positive
    current living population, from the Slice-1 shared authority (never an
    inline recomputation -- see the accompanying Slice 2 fix to `production_
    disposition_service.list_active_production_plates`, which had drifted
    stale for exactly this reason once Harvest existed). A zero-living
    Plate never appears here (disappears once fully harvested) but remains
    discoverable via Harvest history. Quality Hold never hides a row here
    (visible, flagged) -- only the write path (`record_leafy_harvest`,
    via the shared `_lock_batch_for_harvest`) actually blocks on it."""
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    query = (
        "SELECT bca.id AS assignment_id, bca.population_root_batch_carrier_assignment_id AS root_id, "
        "carrier.id AS carrier_id, carrier.code AS carrier_code, "
        "cb.id AS batch_id, cb.code AS batch_code, "
        "crop.common_name, variety.name AS variety_name, "
        "loc.id AS location_id "
        "FROM batch_carrier_assignments bca "
        "JOIN carriers carrier ON carrier.id = bca.carrier_id "
        "JOIN carrier_types ct ON ct.id = carrier.carrier_type_id AND ct.code = :plate_type_code "
        "JOIN crop_batches cb ON cb.id = bca.batch_id "
        "JOIN workflows wf ON wf.id = cb.workflow_id "
        "JOIN crops crop ON crop.id = wf.crop_id "
        "LEFT JOIN varieties variety ON variety.id = wf.variety_id "
        "LEFT JOIN occupancies occ ON occ.occupant_carrier_id = carrier.id AND occ.end_time IS NULL "
        "LEFT JOIN locations loc ON loc.id = occ.target_location_id "
        "WHERE bca.tenant_id = :tid AND bca.farm_id = :fid AND bca.released_effective_time IS NULL "
        "AND bca.population_root_batch_carrier_assignment_id IS NOT NULL "
    )
    params: dict[str, object] = {
        "tid": tenant_id, "fid": farm_id, "plate_type_code": PRODUCTION_CULTIVATION_PLATE_CARRIER_TYPE_CODE,
    }
    if batch_id is not None:
        query += "AND cb.id = :bid "
        params["bid"] = batch_id
    query += "ORDER BY cb.code, carrier.code"

    rows = db.execute(text(query), params).mappings().all()

    quality_hold_by_batch: dict[uuid.UUID, bool] = {}
    results: list[HarvestablePlateRead] = []
    for r in rows:
        root_id = r["root_id"]
        living = leafy_population_service.get_current_living_population(
            db, root_batch_carrier_assignment_id=root_id
        )
        if living <= 0:
            continue

        row_batch_id = r["batch_id"]
        if row_batch_id not in quality_hold_by_batch:
            quality_hold_by_batch[row_batch_id] = quality_hold_service.has_open_quality_hold(
                db, batch_id=row_batch_id
            )

        results.append(
            HarvestablePlateRead(
                production_plate_id=r["carrier_id"], production_plate_code=r["carrier_code"],
                batch_id=row_batch_id, batch_code=r["batch_code"], crop_common_name=r["common_name"],
                variety_name=r["variety_name"], current_living_heads=living,
                current_batch_carrier_assignment_id=r["assignment_id"],
                location=_leafy_harvest_location_read(db, location_id=r["location_id"]),
                has_location_warning=r["location_id"] is None,
                quality_hold_open=quality_hold_by_batch[row_batch_id],
            )
        )
    return results


def _leafy_harvest_source_line_read(
    db: Session, *, source_line: HarvestSourceLine, carrier: Carrier, carrier_type: CarrierType,
    harvest_effective_time: datetime,
) -> LeafyHarvestSourceLineRead:
    effective = get_current_effective_source_line(db, harvest_source_line_id=source_line.id)
    history = get_correction_history(db, harvest_source_line_id=source_line.id)
    # CTO CORRECTION 1: Harvest History must show WHERE the Plate physically
    # was WHEN THE HARVEST OCCURRED, never its current location -- a later
    # Movement must never silently rewrite this line's own historical
    # traceability fact. `None` (no Occupancy interval legitimately
    # contains this instant) stays `None`, never a fallback to current.
    historical_location_id = movement_service.get_carrier_location_as_of(
        db, carrier_id=carrier.id, as_of=harvest_effective_time
    )
    is_void = effective["is_void"]
    return LeafyHarvestSourceLineRead(
        id=source_line.id, batch_carrier_assignment_id=source_line.batch_carrier_assignment_id,
        carrier=CarrierSummary(
            id=carrier.id, code=carrier.code,
            carrier_type=CarrierTypeSummary(id=carrier_type.id, code=carrier_type.code, name=carrier_type.name),
        ),
        harvest_location=_leafy_harvest_location_read(db, location_id=historical_location_id),
        original_harvested_weight_kg=effective["original_harvested_weight_kg"],
        original_whole_unit_count=effective["original_whole_unit_count"],
        current_harvested_weight_kg=(Decimal("0") if is_void else effective["harvested_weight_kg"]),
        current_whole_unit_count=(0 if is_void else (effective["whole_unit_count"] or 0)),
        state=("VOID" if is_void else "ACTIVE"),
        correction_tip_id=effective["tip_correction_id"],
        correction_history=[
            LeafyHarvestSourceLineCorrectionRead(
                id=c.id, supersedes_correction_id=c.supersedes_correction_id, is_void=c.is_void,
                corrected_harvested_weight_kg=c.corrected_harvested_weight_kg,
                corrected_whole_unit_count=c.corrected_whole_unit_count, reason_code=c.reason_code, note=c.note,
                actor_user_id=c.actor_user_id, recorded_time=c.recorded_at,
            )
            for c in history
        ],
    )


def _load_leafy_source_lines(
    db: Session, *, event_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[LeafyHarvestSourceLineRead]]:
    grouped: dict[uuid.UUID, list[LeafyHarvestSourceLineRead]] = {eid: [] for eid in event_ids}
    if not event_ids:
        return grouped
    rows = db.execute(
        select(HarvestSourceLine, Carrier, CarrierType, HarvestEvent.effective_time)
        .join(Carrier, Carrier.id == HarvestSourceLine.carrier_id)
        .join(CarrierType, CarrierType.id == Carrier.carrier_type_id)
        .join(HarvestEvent, HarvestEvent.id == HarvestSourceLine.harvest_event_id)
        .where(HarvestSourceLine.harvest_event_id.in_(event_ids))
        .order_by(Carrier.code, Carrier.id)
    ).all()
    for source_line, carrier, carrier_type, harvest_effective_time in rows:
        grouped[source_line.harvest_event_id].append(
            _leafy_harvest_source_line_read(
                db, source_line=source_line, carrier=carrier, carrier_type=carrier_type,
                harvest_effective_time=harvest_effective_time,
            )
        )
    return grouped


def _row_to_leafy_harvest_event_read(
    db: Session, row, source_lines: list[LeafyHarvestSourceLineRead], *, tenant_id: uuid.UUID, farm_id: uuid.UUID,
) -> LeafyHarvestEventRead:
    event: HarvestEvent = row[0]
    m = row._mapping
    crop: Crop = row[6]
    variety: Variety | None = row[7]
    original_total_weight = sum((line.original_harvested_weight_kg for line in source_lines), Decimal("0"))
    original_counts = [line.original_whole_unit_count for line in source_lines]
    original_total_count = sum(original_counts) if all(c is not None for c in original_counts) else None
    current_total_weight = sum((line.current_harvested_weight_kg for line in source_lines), Decimal("0"))
    current_total_count = sum(line.current_whole_unit_count for line in source_lines)
    balance = produce_lot_ledger_service.get_balance(
        db, tenant_id=tenant_id, farm_id=farm_id, produce_lot_id=m["lot_id"]
    )
    return LeafyHarvestEventRead(
        id=event.id, tenant_id=event.tenant_id, farm_id=event.farm_id, batch_id=event.batch_id,
        batch_code=m["batch_code"], crop=CropSummary(id=crop.id, code=crop.code, common_name=crop.common_name),
        variety=(VarietySummary(id=variety.id, code=variety.code, name=variety.name) if variety is not None else None),
        effective_time=event.effective_time, recorded_time=event.recorded_time, actor_user_id=event.actor_user_id,
        produce_lot_id=m["lot_id"], produce_lot_code=m["lot_code"], note=event.note,
        original_total_harvested_weight_kg=original_total_weight, original_total_whole_unit_count=original_total_count,
        current_total_harvested_weight_kg=current_total_weight, current_total_whole_unit_count=current_total_count,
        available_balance_weight_kg=balance.available_weight_kg,
        available_balance_whole_unit_count=balance.available_whole_unit_count, source_lines=source_lines,
    )


def get_leafy_harvest_event(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, harvest_event_id: uuid.UUID,
) -> LeafyHarvestEventRead:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    row = db.execute(
        _harvest_event_header_query().where(
            HarvestEvent.id == harvest_event_id, HarvestEvent.tenant_id == tenant_id, HarvestEvent.farm_id == farm_id,
        )
    ).first()
    if row is None:
        raise HarvestEventNotFoundError(str(harvest_event_id))
    source_lines = _load_leafy_source_lines(db, event_ids=[harvest_event_id])[harvest_event_id]
    return _row_to_leafy_harvest_event_read(db, row, source_lines, tenant_id=tenant_id, farm_id=farm_id)


def list_leafy_harvest_events(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID | None = None,
) -> list[LeafyHarvestEventRead]:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    query = _harvest_event_header_query().where(
        HarvestEvent.tenant_id == tenant_id, HarvestEvent.farm_id == farm_id,
    )
    if batch_id is not None:
        query = query.where(HarvestEvent.batch_id == batch_id)
    rows = db.execute(query.order_by(HarvestEvent.effective_time, HarvestEvent.recorded_time)).all()
    event_ids = [r[0].id for r in rows]
    source_by_event = _load_leafy_source_lines(db, event_ids=event_ids)
    return [
        _row_to_leafy_harvest_event_read(db, r, source_by_event[r[0].id], tenant_id=tenant_id, farm_id=farm_id)
        for r in rows
    ]


def correct_leafy_harvest_source_line(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    harvest_event_id: uuid.UUID,
    harvest_source_line_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_command_id: uuid.UUID,
    supersedes_correction_id: uuid.UUID | None,
    is_void: bool,
    corrected_harvested_weight_kg: Decimal | None,
    corrected_whole_unit_count: int | None,
    reason_code: str,
    note: str,
) -> HarvestSourceLineCorrection:
    """HTTP-layer ownership wrapper around the frozen Slice-1 `correct_
    leafy_harvest`: verifies the given `harvest_source_line_id` genuinely
    belongs to the given `harvest_event_id` (and tenant/farm) BEFORE
    delegating -- a HarvestEvent may carry several Production Plates and
    the client always targets one specific line, so the URL's own event id
    must never be trusted without this check (a mismatched pair must 404,
    never silently correct the wrong line or leak another event's line
    across a tenant/farm boundary). Never modifies `correct_leafy_harvest`
    itself, which stays exactly as Slice 1 left it."""
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    line = db.execute(
        select(HarvestSourceLine).where(
            HarvestSourceLine.id == harvest_source_line_id, HarvestSourceLine.tenant_id == tenant_id,
            HarvestSourceLine.farm_id == farm_id, HarvestSourceLine.harvest_event_id == harvest_event_id,
        )
    ).scalar_one_or_none()
    if line is None:
        raise HarvestSourceLineNotFoundError(str(harvest_source_line_id))
    return correct_leafy_harvest(
        db, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, client_command_id=client_command_id,
        harvest_source_line_id=harvest_source_line_id, supersedes_correction_id=supersedes_correction_id,
        is_void=is_void, corrected_harvested_weight_kg=corrected_harvested_weight_kg,
        corrected_whole_unit_count=corrected_whole_unit_count, reason_code=reason_code, note=note,
    )
