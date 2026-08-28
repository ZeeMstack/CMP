"""POSTHARVEST-OPS-001E: Packing consumes GradedProduceLot exclusively --

    HarvestedProduceLot -> GradingEvent -> GradedProduceLot
        -> PackingInputLine -> PackingEvent -> FinishedGoodsLot

Every PackingEvent pins an exact PackSpecificationVersion (tenant-scoped
only, never farm-scoped). There is no supported direct
`HarvestedProduceLot -> Packing` path -- HarvestedProduceLot's own
commercial balance is affected by Grading only, from this ticket onward.

Follows the exact operational-command conventions this codebase already
established for `grading_service`/the legacy `packing_service`:
tenant-scoped `client_command_id` + SHA-256 fingerprint idempotency
(pre-lock and post-lock replay checks, `IntegrityError` fallback), and a
strictly ascending lock order -- CropBatch, then HarvestedProduceLot, then
GradedProduceLot -- never inverted, mirroring the codebase's global order
one tier further than Grading's own CropBatch-before-HarvestedProduceLot.
"""

import hashlib
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.crop import Crop
from app.models.crop_batch import CropBatch
from app.models.finished_goods_ledger_entry import FinishedGoodsLedgerEntry
from app.models.finished_goods_lot import FinishedGoodsLot
from app.models.finished_goods_storage_movement import FinishedGoodsStorageMovement
from app.models.graded_produce_lot import GradedProduceLot
from app.models.graded_produce_lot_ledger_entry import GradedProduceLotLedgerEntry
from app.models.grading_event import GradingEvent
from app.models.harvested_produce_lot import HarvestedProduceLot
from app.models.pack_specification import PackSpecification
from app.models.pack_specification_version import PackSpecificationVersion
from app.models.packing_event import PackingEvent
from app.models.packing_input_line import PackingInputLine
from app.models.packing_reversal_event import PackingReversalEvent
from app.models.packing_reversal_input import PackingReversalInput
from app.models.variety import Variety
from app.schemas.crop_batch import CropSummary, VarietySummary
from app.schemas.harvest import MAX_WEIGHT_KG, canonical_decimal_str
from app.schemas.packing import (
    FinishedGoodsLotRead,
    FinishedGoodsLotSummary,
    PackingEventRead,
    PackingInputLineRead,
    PackingReversalEventRead,
    PackingReversalInputRead,
)
from app.services import farm_service, quality_hold_service, recall_service
from app.services.audit import append_audit_event
from app.services.errors import (
    DuplicateFinishedGoodsLotCodeError,
    FarmNotFoundError,
    FinishedGoodsLotNotFoundError,
    InsufficientGradedProduceLotBalanceError,
    InvalidPackingEffectiveTimeError,
    InvalidPackingReversalEffectiveTimeError,
    PackingCommandReusedWithDifferentPayloadError,
    PackingCropVarietyMismatchError,
    PackingEventAlreadyReversedError,
    PackingEventNotFoundError,
    PackingGradeVersionMismatchError,
    PackingInputGradedProduceLotNotFoundError,
    PackingReversalBlockedByDownstreamActivityError,
    PackingReversalCommandReusedWithDifferentPayloadError,
    PackingReversalEventNotFoundError,
    PackingReversalValidationError,
    PackingValidationError,
    PackSpecificationVersionNotFoundError,
    PackSpecificationVersionNotUsableError,
    QualityHoldOpenError,
    RecallContainmentOpenError,
    TooManyPackingInputLinesError,
)

MAX_PACKING_INPUT_LINES = 50


def _require_active_farm(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID):
    farm = farm_service.get_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    if farm.status != "active":
        raise FarmNotFoundError(str(farm_id))
    return farm


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _compute_packing_fingerprint(
    *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, effective_time: datetime,
    note: str | None, pack_specification_version_id: uuid.UUID, finished_goods_lot_code: str,
    packed_output_weight_kg: Decimal, package_count: int, process_loss_weight_kg: Decimal,
    rejected_weight_kg: Decimal, input_lines: list[dict],
) -> str:
    sorted_lines = sorted(input_lines, key=lambda line: str(line["graded_produce_lot_id"]))
    parts = [
        str(tenant_id), str(farm_id), str(actor_user_id), effective_time.astimezone(timezone.utc).isoformat(),
        note or "", str(pack_specification_version_id), finished_goods_lot_code,
        canonical_decimal_str(packed_output_weight_kg), str(package_count),
        canonical_decimal_str(process_loss_weight_kg), canonical_decimal_str(rejected_weight_kg),
    ]
    for line in sorted_lines:
        parts.extend(
            [
                str(line["graded_produce_lot_id"]), canonical_decimal_str(line["consumed_weight_kg"]),
                str(line["consumed_whole_unit_count"]) if line["consumed_whole_unit_count"] is not None else "",
                line.get("note") or "",
            ]
        )
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _find_existing_packing_event(
    db: Session, *, tenant_id: uuid.UUID, client_command_id: uuid.UUID
) -> PackingEvent | None:
    return db.execute(
        select(PackingEvent).where(
            PackingEvent.tenant_id == tenant_id, PackingEvent.client_command_id == client_command_id
        )
    ).scalar_one_or_none()


# --- Command ------------------------------------------------------------------------


def record_packing(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_command_id: uuid.UUID,
    pack_specification_version_id: uuid.UUID,
    effective_time: datetime,
    finished_goods_lot_code: str,
    package_count: int,
    packed_output_weight_kg: Decimal,
    process_loss_weight_kg: Decimal,
    rejected_weight_kg: Decimal,
    note: str | None,
    input_lines: list[dict],
) -> PackingEvent:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    if effective_time > datetime.now(timezone.utc):
        raise InvalidPackingEffectiveTimeError("effective_time cannot be in the future")
    if len(input_lines) > MAX_PACKING_INPUT_LINES:
        raise TooManyPackingInputLinesError(
            f"a packing command may include at most {MAX_PACKING_INPUT_LINES} input lines"
        )

    total_input_weight_kg: Decimal = sum(
        (line["consumed_weight_kg"] for line in input_lines), Decimal("0")
    )

    fingerprint = _compute_packing_fingerprint(
        tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, effective_time=effective_time,
        note=note, pack_specification_version_id=pack_specification_version_id,
        finished_goods_lot_code=finished_goods_lot_code, packed_output_weight_kg=packed_output_weight_kg,
        package_count=package_count, process_loss_weight_kg=process_loss_weight_kg,
        rejected_weight_kg=rejected_weight_kg, input_lines=input_lines,
    )

    existing = _find_existing_packing_event(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise PackingCommandReusedWithDifferentPayloadError(str(client_command_id))

    # Resolve source graded produce lots and their upstream grading-event /
    # harvested-produce-lot / crop-batch ancestry first, without trusting
    # any mutable balance or containment state -- the authoritative reads
    # only happen once every lock tier below is actually held. No
    # proportional ambiguity: one GradedProduceLot names exactly one
    # GradingEvent, which names exactly one source HarvestedProduceLot.
    gpl_ids = sorted({line["graded_produce_lot_id"] for line in input_lines})
    ancestry_rows = db.execute(
        select(GradedProduceLot, GradingEvent.source_harvested_produce_lot_id, HarvestedProduceLot.batch_id)
        .join(GradingEvent, GradingEvent.id == GradedProduceLot.grading_event_id)
        .join(HarvestedProduceLot, HarvestedProduceLot.id == GradingEvent.source_harvested_produce_lot_id)
        .where(GradedProduceLot.id.in_(gpl_ids))
    ).all()
    gpls_by_id = {row[0].id: row[0] for row in ancestry_rows}
    hpl_id_by_gpl = {row[0].id: row[1] for row in ancestry_rows}
    batch_id_by_gpl = {row[0].id: row[2] for row in ancestry_rows}
    for gid in gpl_ids:
        gpl = gpls_by_id.get(gid)
        if gpl is None or gpl.tenant_id != tenant_id or gpl.farm_id != farm_id:
            raise PackingInputGradedProduceLotNotFoundError(str(gid))

    batch_ids = sorted(set(batch_id_by_gpl.values()))
    hpl_ids = sorted(set(hpl_id_by_gpl.values()))

    # Lock order: CropBatch -> HarvestedProduceLot -> GradedProduceLot,
    # strictly ascending, matching the global order -- never locking a
    # GradedProduceLot first and walking backward to its batch/HPL
    # afterward (that would invert against a concurrent batch-/HPL-source
    # Recall opening, which locks in this same ascending order).
    batches = list(
        db.execute(
            select(CropBatch)
            .where(CropBatch.id.in_(batch_ids), CropBatch.tenant_id == tenant_id, CropBatch.farm_id == farm_id)
            .order_by(CropBatch.id).with_for_update()
        ).scalars()
    )
    if len(batches) != len(batch_ids):
        found = {b.id for b in batches}
        missing = [bid for bid in batch_ids if bid not in found]
        raise PackingInputGradedProduceLotNotFoundError(str(missing[0]))

    existing = _find_existing_packing_event(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise PackingCommandReusedWithDifferentPayloadError(str(client_command_id))

    # A genuinely new packing command is blocked while any upstream source
    # crop batch has an open quality hold or open batch-scope recall --
    # inherited containment, walked one hop further than Grading's own
    # identical gate.
    for batch in batches:
        if quality_hold_service.has_open_quality_hold(db, batch_id=batch.id):
            raise QualityHoldOpenError(str(batch.id))
    for batch in batches:
        if recall_service.has_open_batch_recall(db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch.id):
            raise RecallContainmentOpenError(str(batch.id))

    locked_hpls = list(
        db.execute(
            select(HarvestedProduceLot).where(HarvestedProduceLot.id.in_(hpl_ids))
            .order_by(HarvestedProduceLot.id).with_for_update()
        ).scalars()
    )
    for hpl in locked_hpls:
        if recall_service.has_open_produce_lot_recall(
            db, tenant_id=tenant_id, farm_id=farm_id, produce_lot_id=hpl.id
        ):
            raise RecallContainmentOpenError(str(hpl.id))

    locked_gpls = list(
        db.execute(
            select(GradedProduceLot).where(GradedProduceLot.id.in_(gpl_ids))
            .order_by(GradedProduceLot.id).with_for_update()
        ).scalars()
    )
    locked_gpls_by_id = {g.id: g for g in locked_gpls}
    for gpl in locked_gpls:
        if recall_service.has_open_graded_produce_lot_recall(
            db, tenant_id=tenant_id, farm_id=farm_id, graded_produce_lot_id=gpl.id
        ):
            raise RecallContainmentOpenError(str(gpl.id))

    # Post-lock idempotency recheck -- a concurrent replay of this exact
    # command could have committed while every lock tier above was being
    # acquired.
    existing = _find_existing_packing_event(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise PackingCommandReusedWithDifferentPayloadError(str(client_command_id))

    # --- input commercial compatibility: crop/variety exact match, incl. NULL ---
    crop_ids = {gpl.crop_id for gpl in locked_gpls}
    variety_ids = {gpl.variety_id for gpl in locked_gpls}
    if len(crop_ids) != 1 or len(variety_ids) != 1:
        raise PackingCropVarietyMismatchError(
            "all input graded produce lots in one packing command must share the same crop and the exact "
            "same variety (including all-NULL)"
        )
    crop_id = next(iter(crop_ids))
    variety_id = next(iter(variety_ids))

    grade_version_ids = {gpl.grade_definition_version_id for gpl in locked_gpls}
    if len(grade_version_ids) != 1:
        raise PackingGradeVersionMismatchError(
            "all input graded produce lots in one packing command must share the exact same "
            "grade_definition_version_id"
        )
    grade_version_id = next(iter(grade_version_ids))

    # --- PackSpecificationVersion resolution + compatibility ---------------------
    # Tenant-scoped only (PackSpecification/PackSpecificationVersion carry
    # no farm_id) -- never a farm-qualified lookup. A since-retired
    # GradeDefinitionVersion on an input GPL is never re-validated here --
    # that window was already proven at Grading time; only PackSpec's OWN
    # effective window (below) and exact grade-pin equality matter now.
    spec_version = db.execute(
        select(PackSpecificationVersion).where(
            PackSpecificationVersion.id == pack_specification_version_id,
            PackSpecificationVersion.tenant_id == tenant_id,
        )
    ).scalar_one_or_none()
    if spec_version is None:
        raise PackSpecificationVersionNotFoundError(str(pack_specification_version_id))
    if spec_version.status == "draft":
        raise PackSpecificationVersionNotUsableError(
            f"pack_specification_version {pack_specification_version_id} is draft and cannot be referenced"
        )
    if effective_time < spec_version.effective_from:
        raise PackSpecificationVersionNotUsableError(
            f"pack_specification_version {pack_specification_version_id} is not yet effective at this "
            "event's effective_time"
        )
    if spec_version.effective_until is not None and effective_time >= spec_version.effective_until:
        raise PackSpecificationVersionNotUsableError(
            f"pack_specification_version {pack_specification_version_id} is no longer effective at this "
            "event's effective_time"
        )
    spec = db.execute(
        select(PackSpecification).where(PackSpecification.id == spec_version.pack_specification_id)
    ).scalar_one()
    if spec.crop_id != crop_id:
        raise PackingCropVarietyMismatchError(
            f"pack specification {spec.id} crop does not match the input graded produce lots' crop"
        )
    if spec.variety_id is not None and spec.variety_id != variety_id:
        raise PackingCropVarietyMismatchError(
            f"pack specification {spec.id} variety is incompatible with the input graded produce lots' variety"
        )
    if (
        spec_version.grade_definition_version_id is not None
        and spec_version.grade_definition_version_id != grade_version_id
    ):
        raise PackingGradeVersionMismatchError(
            f"pack_specification_version {spec_version.id} pinned grade does not match the input graded "
            "produce lots' grade"
        )

    # --- chronology + balance per input line -------------------------------------
    balance_rows = db.execute(
        select(
            GradedProduceLotLedgerEntry.graded_produce_lot_id,
            func.sum(GradedProduceLotLedgerEntry.weight_delta_kg).label("weight"),
            func.sum(GradedProduceLotLedgerEntry.whole_unit_count_delta).label("count"),
            func.max(GradedProduceLotLedgerEntry.effective_time).label("last_effective_time"),
        )
        .where(GradedProduceLotLedgerEntry.graded_produce_lot_id.in_(gpl_ids))
        .group_by(GradedProduceLotLedgerEntry.graded_produce_lot_id)
    ).all()
    balances_by_gpl = {r.graded_produce_lot_id: r for r in balance_rows}

    for gpl in locked_gpls:
        if effective_time < gpl.effective_time:
            raise InvalidPackingEffectiveTimeError(
                f"effective_time precedes source graded produce lot {gpl.id}'s own effective_time"
            )
        bal = balances_by_gpl.get(gpl.id)
        if bal is not None and bal.last_effective_time is not None and effective_time < bal.last_effective_time:
            raise InvalidPackingEffectiveTimeError(
                f"effective_time precedes the latest existing ledger entry for source graded produce lot {gpl.id}"
            )

    if total_input_weight_kg >= MAX_WEIGHT_KG:
        raise PackingValidationError("the sum of input-line weights exceeds the supported total weight range")
    if total_input_weight_kg != packed_output_weight_kg + process_loss_weight_kg + rejected_weight_kg:
        raise PackingValidationError(
            "total input weight does not reconcile into packed output, process loss, and rejected weight"
        )

    for line in input_lines:
        gid = line["graded_produce_lot_id"]
        gpl = locked_gpls_by_id[gid]
        bal = balances_by_gpl.get(gid)
        available_weight = bal.weight if bal is not None else Decimal("0")
        available_count = bal.count if bal is not None else None
        consumed_weight = line["consumed_weight_kg"]
        consumed_count = line["consumed_whole_unit_count"]

        if gpl.original_received_whole_unit_count is None:
            if consumed_count is not None:
                raise PackingValidationError(
                    f"source graded produce lot {gid} does not track whole-unit count; consumed count must be null"
                )
        elif consumed_count is None:
            raise PackingValidationError(
                f"source graded produce lot {gid} tracks whole-unit count; consumed count is required"
            )

        if consumed_weight > available_weight:
            raise InsufficientGradedProduceLotBalanceError(str(gid))
        remaining_weight = available_weight - consumed_weight
        remaining_count = None
        if consumed_count is not None:
            if available_count is None or consumed_count > available_count:
                raise InsufficientGradedProduceLotBalanceError(str(gid))
            remaining_count = available_count - consumed_count
            if (remaining_weight == 0 and remaining_count > 0) or (remaining_weight > 0 and remaining_count == 0):
                raise PackingValidationError(
                    f"packing would leave source graded produce lot {gid} with mismatched residual weight/count"
                )

    event_id = uuid.uuid4()
    line_ids = {gid: uuid.uuid4() for gid in gpl_ids}

    try:
        event = PackingEvent(
            id=event_id, tenant_id=tenant_id, farm_id=farm_id,
            pack_specification_version_id=pack_specification_version_id, crop_id=crop_id, variety_id=variety_id,
            total_input_weight_kg=total_input_weight_kg, packed_output_weight_kg=packed_output_weight_kg,
            process_loss_weight_kg=process_loss_weight_kg, rejected_weight_kg=rejected_weight_kg,
            effective_time=effective_time, actor_user_id=actor_user_id, client_command_id=client_command_id,
            request_fingerprint=fingerprint, note=note,
        )
        db.add(event)
        db.flush()

        fg_lot = FinishedGoodsLot(
            id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, code=finished_goods_lot_code,
            packing_event_id=event.id, crop_id=crop_id, variety_id=variety_id,
            net_packed_weight_kg=packed_output_weight_kg, package_count=package_count,
            effective_time=effective_time,
        )
        db.add(fg_lot)
        db.flush()

        # Deterministic opening receipt (CMP-016, unchanged shape): id and
        # finished_goods_lot_id both equal the lot's own id.
        db.add(
            FinishedGoodsLedgerEntry(
                id=fg_lot.id, tenant_id=tenant_id, farm_id=farm_id, finished_goods_lot_id=fg_lot.id,
                packing_event_id=event.id, entry_kind="packing_receipt",
                weight_delta_kg=fg_lot.net_packed_weight_kg, package_count_delta=fg_lot.package_count,
                effective_time=fg_lot.effective_time, recorded_time=fg_lot.recorded_time,
                actor_user_id=actor_user_id, note=None,
            )
        )
        db.flush()

        # Deterministic packing_consumption debit identity, mirroring CMP-
        # 015's own historical convention one layer up: each ledger debit's
        # id equals its own PackingInputLine's id -- one exact debit per
        # line, trivially reconstructible, no independent client command id.
        input_line_objs: dict[uuid.UUID, PackingInputLine] = {}
        for line in input_lines:
            gid = line["graded_produce_lot_id"]
            obj = PackingInputLine(
                id=line_ids[gid], tenant_id=tenant_id, farm_id=farm_id, packing_event_id=event.id,
                graded_produce_lot_id=gid, consumed_weight_kg=line["consumed_weight_kg"],
                consumed_whole_unit_count=line["consumed_whole_unit_count"], note=line.get("note"),
            )
            db.add(obj)
            input_line_objs[gid] = obj
        db.flush()

        for gid, obj in input_line_objs.items():
            count_delta = -obj.consumed_whole_unit_count if obj.consumed_whole_unit_count is not None else None
            db.add(
                GradedProduceLotLedgerEntry(
                    id=obj.id, tenant_id=tenant_id, farm_id=farm_id, graded_produce_lot_id=gid,
                    grading_event_id=None, packing_event_id=event.id, entry_kind="packing_consumption",
                    weight_delta_kg=-obj.consumed_weight_kg, whole_unit_count_delta=count_delta,
                    effective_time=effective_time, recorded_time=obj.recorded_time, actor_user_id=actor_user_id,
                    note=obj.note,
                )
            )
        db.flush()

        append_audit_event(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="produce_lot.packed",
            entity_type="packing_event", entity_id=event.id,
            event_data={
                "packing_event_id": str(event.id),
                "pack_specification_version_id": str(pack_specification_version_id),
                "finished_goods_lot_id": str(fg_lot.id), "finished_goods_lot_code": fg_lot.code,
                "source_graded_produce_lot_ids": [str(gid) for gid in gpl_ids],
                "packing_input_line_ids": [str(line_ids[gid]) for gid in gpl_ids],
                "ledger_entry_ids": [str(line_ids[gid]) for gid in gpl_ids],
                "effective_time": effective_time.isoformat(), "client_command_id": str(client_command_id),
                "source_count": len(gpl_ids), "total_input_weight_kg": canonical_decimal_str(total_input_weight_kg),
                "packed_output_weight_kg": canonical_decimal_str(packed_output_weight_kg),
                "process_loss_weight_kg": canonical_decimal_str(process_loss_weight_kg),
                "rejected_weight_kg": canonical_decimal_str(rejected_weight_kg), "package_count": package_count,
            },
        )
        db.flush()
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_packing_events_tenant_client_command_id":
            replay = _find_existing_packing_event(db, tenant_id=tenant_id, client_command_id=client_command_id)
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise PackingCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        if constraint == "ux_finished_goods_lots_tenant_code_lower":
            raise DuplicateFinishedGoodsLotCodeError(f"{tenant_id}:{finished_goods_lot_code}") from exc
        raise
    except Exception:
        db.rollback()
        raise
    db.refresh(event)
    return event


# --- POSTHARVEST-OPS-001H: reversal -------------------------------------------------


def _compute_packing_reversal_fingerprint(
    *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, effective_time: datetime,
    packing_event_id: uuid.UUID, reason_code: str, note: str | None,
) -> str:
    parts = [
        str(tenant_id), str(farm_id), str(actor_user_id), effective_time.astimezone(timezone.utc).isoformat(),
        str(packing_event_id), reason_code, note or "",
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _find_existing_packing_reversal_event(
    db: Session, *, tenant_id: uuid.UUID, client_command_id: uuid.UUID
) -> PackingReversalEvent | None:
    return db.execute(
        select(PackingReversalEvent).where(
            PackingReversalEvent.tenant_id == tenant_id, PackingReversalEvent.client_command_id == client_command_id
        )
    ).scalar_one_or_none()


def reverse_packing_event(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_command_id: uuid.UUID,
    packing_event_id: uuid.UUID,
    effective_time: datetime,
    reason_code: str,
    note: str | None,
) -> PackingReversalEvent:
    """001H: whole-event reversal only -- never a field-by-field
    correction. Restores every source GradedProduceLot's ledger balance by
    the exact quantity each `packing_consumption` debited, and neutralizes
    the FinishedGoodsLot's opening quantity. Blocked while the
    FinishedGoodsLot's own ledger carries any entry beyond its own
    `packing_receipt` (currently: any `dispatch_issue`), or while its
    storage-movement history is non-empty at all (never inferred from a
    live/net placed balance -- see `PRE-COMMIT AUDIT` comments at the gate
    itself) -- none of dispatch, storage placement/release has a reversal
    mechanism in this ticket's scope. `reason_code` is mandatory; `note` is
    optional (mirrors `SeedlingDispositionEvent`'s own REVERSAL shape, the
    closest existing "whole-event reversal" precedent in this codebase --
    not `HarvestSourceLineCorrection`'s stricter both-mandatory shape,
    which is a linked-list field correction, not a reversal)."""
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    if effective_time > datetime.now(timezone.utc):
        raise InvalidPackingReversalEffectiveTimeError("effective_time cannot be in the future")
    if not reason_code.strip():
        raise PackingReversalValidationError("reason_code is mandatory for a packing reversal")
    note = note.strip() if note is not None and note.strip() else None

    fingerprint = _compute_packing_reversal_fingerprint(
        tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, effective_time=effective_time,
        packing_event_id=packing_event_id, reason_code=reason_code, note=note,
    )

    existing = _find_existing_packing_reversal_event(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise PackingReversalCommandReusedWithDifferentPayloadError(str(client_command_id))

    event = db.execute(
        select(PackingEvent).where(
            PackingEvent.id == packing_event_id, PackingEvent.tenant_id == tenant_id,
            PackingEvent.farm_id == farm_id,
        )
    ).scalar_one_or_none()
    if event is None:
        raise PackingEventNotFoundError(str(packing_event_id))

    fg_lot = db.execute(
        select(FinishedGoodsLot).where(FinishedGoodsLot.packing_event_id == event.id)
    ).scalar_one()

    input_lines = list(
        db.execute(
            select(PackingInputLine).where(PackingInputLine.packing_event_id == event.id)
            .order_by(PackingInputLine.graded_produce_lot_id)
        ).scalars()
    )
    gpl_ids = sorted({line.graded_produce_lot_id for line in input_lines})

    # Lock order: GradedProduceLot (tier 3) before FinishedGoodsLot
    # (tier 4), matching the codebase's global ascending lock order.
    db.execute(
        select(GradedProduceLot).where(GradedProduceLot.id.in_(gpl_ids)).order_by(GradedProduceLot.id)
        .with_for_update()
    ).scalars().all()
    locked_fg_lot = db.execute(
        select(FinishedGoodsLot).where(FinishedGoodsLot.id == fg_lot.id).with_for_update()
    ).scalar_one()

    # Post-lock idempotency recheck -- a concurrent replay of this exact
    # command could have committed while the locks above were being
    # acquired.
    existing = _find_existing_packing_reversal_event(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise PackingReversalCommandReusedWithDifferentPayloadError(str(client_command_id))

    already_reversed = db.execute(
        select(PackingReversalEvent.id).where(PackingReversalEvent.packing_event_id == event.id)
    ).scalar_one_or_none()
    if already_reversed is not None:
        raise PackingEventAlreadyReversedError(str(packing_event_id))

    if effective_time < event.effective_time:
        raise InvalidPackingReversalEffectiveTimeError(
            "effective_time cannot precede the target packing event's own effective_time"
        )

    # Downstream gate, PRE-COMMIT AUDIT (POSTHARVEST-OPS-001H): neither
    # dispatch nor storage placement has a reversal mechanism in this
    # ticket's scope, so this must never infer safety from a live/net
    # balance -- only from the complete absence of any downstream fact.
    #
    # (1) Ledger-based: the finished-goods ledger is this codebase's own
    # sole source of truth for a lot's commercial activity (see
    # `FinishedGoodsStorageMovement`'s own docstring: storage movements
    # never touch it). ANY ledger entry beyond the lot's own
    # `packing_receipt` blocks reversal outright -- currently that means
    # `dispatch_issue` (the only other kind that exists today), but this
    # check is written against `entry_kind` generically, not a `DispatchLine`
    # existence check, so it automatically covers any future ledger kind
    # too without needing to be revisited.
    has_other_ledger_activity = db.execute(
        select(FinishedGoodsLedgerEntry.id).where(
            FinishedGoodsLedgerEntry.finished_goods_lot_id == locked_fg_lot.id,
            FinishedGoodsLedgerEntry.entry_kind != "packing_receipt",
        )
    ).first()
    if has_other_ledger_activity is not None:
        raise PackingReversalBlockedByDownstreamActivityError(str(locked_fg_lot.id))

    # (2) Storage-history-based: `finished_goods_storage_movements` is its
    # own immutable, insert-only custody history -- a lot placed into cold
    # storage and later fully released back to "unplaced" nets to zero, but
    # the physical custody fact (it WAS placed) still happened and is never
    # undone by any row in this table. Net/live balance is never a proxy
    # for "this never happened" -- ANY committed movement row for this lot,
    # regardless of current net placement, blocks reversal.
    has_storage_history = db.execute(
        select(FinishedGoodsStorageMovement.id).where(
            FinishedGoodsStorageMovement.finished_goods_lot_id == locked_fg_lot.id
        )
    ).first()
    if has_storage_history is not None:
        raise PackingReversalBlockedByDownstreamActivityError(str(locked_fg_lot.id))

    reversal_id = uuid.uuid4()
    input_row_ids = {line.id: uuid.uuid4() for line in input_lines}

    try:
        reversal = PackingReversalEvent(
            id=reversal_id, tenant_id=tenant_id, farm_id=farm_id, packing_event_id=event.id,
            effective_time=effective_time, actor_user_id=actor_user_id, client_command_id=client_command_id,
            request_fingerprint=fingerprint, reason_code=reason_code, note=note,
        )
        db.add(reversal)
        db.flush()

        input_rows: list[PackingReversalInput] = []
        for line in input_lines:
            row = PackingReversalInput(
                id=input_row_ids[line.id], tenant_id=tenant_id, farm_id=farm_id,
                packing_reversal_event_id=reversal.id, packing_input_line_id=line.id,
                graded_produce_lot_id=line.graded_produce_lot_id, restored_weight_kg=line.consumed_weight_kg,
                restored_whole_unit_count=line.consumed_whole_unit_count,
            )
            db.add(row)
            input_rows.append(row)
        db.flush()

        for row in input_rows:
            db.add(
                GradedProduceLotLedgerEntry(
                    id=row.id, tenant_id=tenant_id, farm_id=farm_id, graded_produce_lot_id=row.graded_produce_lot_id,
                    grading_event_id=None, packing_event_id=None, grading_reversal_event_id=None,
                    packing_reversal_event_id=reversal.id, entry_kind="packing_reversal",
                    weight_delta_kg=row.restored_weight_kg, whole_unit_count_delta=row.restored_whole_unit_count,
                    effective_time=effective_time, recorded_time=reversal.recorded_time, actor_user_id=actor_user_id,
                    note=note,
                )
            )
        db.flush()

        # Neutralize the FinishedGoodsLot's opening quantity -- a negative
        # entry equal to the original packing_receipt (the downstream gate
        # above guarantees this always exactly zeroes the lot's balance).
        db.add(
            FinishedGoodsLedgerEntry(
                id=reversal.id, tenant_id=tenant_id, farm_id=farm_id, finished_goods_lot_id=locked_fg_lot.id,
                packing_event_id=None, dispatch_line_id=None, packing_reversal_event_id=reversal.id,
                entry_kind="packing_reversal", weight_delta_kg=-locked_fg_lot.net_packed_weight_kg,
                package_count_delta=-locked_fg_lot.package_count, effective_time=effective_time,
                recorded_time=reversal.recorded_time, actor_user_id=actor_user_id, note=None,
            )
        )
        db.flush()

        append_audit_event(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="packing_event.reversed",
            entity_type="packing_reversal_event", entity_id=reversal.id,
            event_data={
                "packing_reversal_event_id": str(reversal.id), "packing_event_id": str(event.id),
                "finished_goods_lot_id": str(locked_fg_lot.id), "reason_code": reason_code,
                "effective_time": effective_time.isoformat(), "client_command_id": str(client_command_id),
                "neutralized_weight_kg": canonical_decimal_str(locked_fg_lot.net_packed_weight_kg),
                "input_count": len(input_rows),
                "graded_produce_lot_ids": [str(r.graded_produce_lot_id) for r in input_rows],
            },
        )
        db.flush()
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_packing_reversal_events_tenant_client_command_id":
            replay = _find_existing_packing_reversal_event(
                db, tenant_id=tenant_id, client_command_id=client_command_id
            )
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise PackingReversalCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        if constraint == "ux_packing_reversal_events_packing_event_id":
            raise PackingEventAlreadyReversedError(str(packing_event_id)) from exc
        raise
    except Exception:
        db.rollback()
        raise
    db.refresh(reversal)
    return reversal


def get_packing_reversal_event(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, packing_event_id: uuid.UUID
) -> PackingReversalEventRead:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    reversal = db.execute(
        select(PackingReversalEvent).where(
            PackingReversalEvent.packing_event_id == packing_event_id,
            PackingReversalEvent.tenant_id == tenant_id, PackingReversalEvent.farm_id == farm_id,
        )
    ).scalar_one_or_none()
    if reversal is None:
        raise PackingReversalEventNotFoundError(str(packing_event_id))
    return _row_to_packing_reversal_event_read(db, reversal)


def _row_to_packing_reversal_event_read(db: Session, reversal: PackingReversalEvent) -> PackingReversalEventRead:
    ledger_entry = db.execute(
        select(FinishedGoodsLedgerEntry).where(FinishedGoodsLedgerEntry.id == reversal.id)
    ).scalar_one()
    input_rows = db.execute(
        select(PackingReversalInput, GradedProduceLot.code)
        .join(GradedProduceLot, GradedProduceLot.id == PackingReversalInput.graded_produce_lot_id)
        .where(PackingReversalInput.packing_reversal_event_id == reversal.id)
        .order_by(GradedProduceLot.code)
    ).all()
    inputs = [
        PackingReversalInputRead(
            id=row.id, graded_produce_lot_id=row.graded_produce_lot_id, graded_produce_lot_code=code,
            restored_weight_kg=row.restored_weight_kg, restored_whole_unit_count=row.restored_whole_unit_count,
        )
        for row, code in input_rows
    ]
    return PackingReversalEventRead(
        id=reversal.id, tenant_id=reversal.tenant_id, farm_id=reversal.farm_id,
        packing_event_id=reversal.packing_event_id, effective_time=reversal.effective_time,
        recorded_time=reversal.recorded_time, actor_user_id=reversal.actor_user_id,
        client_command_id=reversal.client_command_id, reason_code=reversal.reason_code, note=reversal.note,
        neutralized_finished_goods_weight_kg=-ledger_entry.weight_delta_kg,
        neutralized_finished_goods_package_count=-ledger_entry.package_count_delta, inputs=inputs,
    )


# --- Reads ------------------------------------------------------------------------


def _packing_event_header_query():
    return (
        select(PackingEvent, Crop, Variety, FinishedGoodsLot)
        .join(Crop, Crop.id == PackingEvent.crop_id)
        .outerjoin(Variety, Variety.id == PackingEvent.variety_id)
        .join(FinishedGoodsLot, FinishedGoodsLot.packing_event_id == PackingEvent.id)
    )


def _load_input_lines(db: Session, *, event_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[PackingInputLineRead]]:
    grouped: dict[uuid.UUID, list[PackingInputLineRead]] = {eid: [] for eid in event_ids}
    if not event_ids:
        return grouped
    rows = db.execute(
        select(PackingInputLine, GradedProduceLot.code, GradedProduceLot.grade_definition_version_id)
        .join(GradedProduceLot, GradedProduceLot.id == PackingInputLine.graded_produce_lot_id)
        .where(PackingInputLine.packing_event_id.in_(event_ids))
        .order_by(GradedProduceLot.code, GradedProduceLot.id)
    ).all()
    for line, gpl_code, grade_definition_version_id in rows:
        grouped[line.packing_event_id].append(
            PackingInputLineRead(
                id=line.id, graded_produce_lot_id=line.graded_produce_lot_id, graded_produce_lot_code=gpl_code,
                grade_definition_version_id=grade_definition_version_id,
                consumed_weight_kg=line.consumed_weight_kg, consumed_whole_unit_count=line.consumed_whole_unit_count,
                ledger_entry_id=line.id, note=line.note, recorded_time=line.recorded_time,
            )
        )
    return grouped


def _row_to_packing_event_read(row, input_lines: list[PackingInputLineRead]) -> PackingEventRead:
    event: PackingEvent = row[0]
    crop: Crop = row[1]
    variety: Variety | None = row[2]
    fg_lot: FinishedGoodsLot = row[3]
    grade_definition_version_id = input_lines[0].grade_definition_version_id if input_lines else None
    return PackingEventRead(
        id=event.id, tenant_id=event.tenant_id, farm_id=event.farm_id,
        pack_specification_version_id=event.pack_specification_version_id,
        grade_definition_version_id=grade_definition_version_id,
        crop=CropSummary(id=crop.id, code=crop.code, common_name=crop.common_name),
        variety=(
            VarietySummary(id=variety.id, code=variety.code, name=variety.name) if variety is not None else None
        ),
        finished_goods_lot=FinishedGoodsLotSummary(
            id=fg_lot.id, code=fg_lot.code, net_packed_weight_kg=fg_lot.net_packed_weight_kg,
            package_count=fg_lot.package_count,
        ),
        input_lines=input_lines, total_input_weight_kg=event.total_input_weight_kg,
        packed_output_weight_kg=event.packed_output_weight_kg, process_loss_weight_kg=event.process_loss_weight_kg,
        rejected_weight_kg=event.rejected_weight_kg, effective_time=event.effective_time,
        recorded_time=event.recorded_time, actor_user_id=event.actor_user_id,
        client_command_id=event.client_command_id, note=event.note,
    )


def get_packing_event(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, packing_event_id: uuid.UUID
) -> PackingEventRead:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    row = db.execute(
        _packing_event_header_query().where(
            PackingEvent.id == packing_event_id, PackingEvent.tenant_id == tenant_id,
            PackingEvent.farm_id == farm_id,
        )
    ).first()
    if row is None:
        raise PackingEventNotFoundError(str(packing_event_id))
    input_lines = _load_input_lines(db, event_ids=[packing_event_id])[packing_event_id]
    return _row_to_packing_event_read(row, input_lines)


def list_packing_events(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> list[PackingEventRead]:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    rows = db.execute(
        _packing_event_header_query()
        .where(PackingEvent.tenant_id == tenant_id, PackingEvent.farm_id == farm_id)
        .order_by(PackingEvent.effective_time, PackingEvent.recorded_time)
    ).all()
    event_ids = [r[0].id for r in rows]
    lines_by_event = _load_input_lines(db, event_ids=event_ids)
    return [_row_to_packing_event_read(r, lines_by_event[r[0].id]) for r in rows]


def _finished_goods_lot_header_query():
    return (
        select(FinishedGoodsLot, Crop, Variety, PackingEvent.pack_specification_version_id)
        .join(Crop, Crop.id == FinishedGoodsLot.crop_id)
        .outerjoin(Variety, Variety.id == FinishedGoodsLot.variety_id)
        .join(PackingEvent, PackingEvent.id == FinishedGoodsLot.packing_event_id)
    )


def _load_source_graded_lot_ids(db: Session, *, event_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[uuid.UUID]]:
    grouped: dict[uuid.UUID, list[uuid.UUID]] = {eid: [] for eid in event_ids}
    if not event_ids:
        return grouped
    rows = db.execute(
        select(PackingInputLine.packing_event_id, PackingInputLine.graded_produce_lot_id)
        .join(GradedProduceLot, GradedProduceLot.id == PackingInputLine.graded_produce_lot_id)
        .where(PackingInputLine.packing_event_id.in_(event_ids))
        .order_by(GradedProduceLot.code, GradedProduceLot.id)
    ).all()
    for eid, gpl_id in rows:
        grouped[eid].append(gpl_id)
    return grouped


def _row_to_finished_goods_lot_read(row, source_graded_produce_lot_ids: list[uuid.UUID]) -> FinishedGoodsLotRead:
    lot: FinishedGoodsLot = row[0]
    crop: Crop = row[1]
    variety: Variety | None = row[2]
    pack_specification_version_id: uuid.UUID = row[3]
    return FinishedGoodsLotRead(
        id=lot.id, tenant_id=lot.tenant_id, farm_id=lot.farm_id, code=lot.code,
        packing_event_id=lot.packing_event_id, pack_specification_version_id=pack_specification_version_id,
        crop=CropSummary(id=crop.id, code=crop.code, common_name=crop.common_name),
        variety=(
            VarietySummary(id=variety.id, code=variety.code, name=variety.name) if variety is not None else None
        ),
        net_packed_weight_kg=lot.net_packed_weight_kg, package_count=lot.package_count,
        source_graded_produce_lot_ids=source_graded_produce_lot_ids, effective_time=lot.effective_time,
        recorded_time=lot.recorded_time,
    )


def get_finished_goods_lot(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, finished_goods_lot_id: uuid.UUID
) -> FinishedGoodsLotRead:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    row = db.execute(
        _finished_goods_lot_header_query().where(
            FinishedGoodsLot.id == finished_goods_lot_id, FinishedGoodsLot.tenant_id == tenant_id,
            FinishedGoodsLot.farm_id == farm_id,
        )
    ).first()
    if row is None:
        raise FinishedGoodsLotNotFoundError(str(finished_goods_lot_id))
    lot: FinishedGoodsLot = row[0]
    source_ids = _load_source_graded_lot_ids(db, event_ids=[lot.packing_event_id])[lot.packing_event_id]
    return _row_to_finished_goods_lot_read(row, source_ids)


def list_finished_goods_lots(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> list[FinishedGoodsLotRead]:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    rows = db.execute(
        _finished_goods_lot_header_query()
        .where(FinishedGoodsLot.tenant_id == tenant_id, FinishedGoodsLot.farm_id == farm_id)
        .order_by(FinishedGoodsLot.code)
    ).all()
    event_ids = [r[0].packing_event_id for r in rows]
    ids_by_event = _load_source_graded_lot_ids(db, event_ids=event_ids)
    return [_row_to_finished_goods_lot_read(r, ids_by_event[r[0].packing_event_id]) for r in rows]
