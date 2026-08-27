"""POSTHARVEST-OPS-001C: Processing/Grading -- the first real
transformation between `HarvestedProduceLot` and (future) Packing.

One `GradingEvent` references EXACTLY ONE `HarvestedProduceLot` (a direct
FK, never a join/line table) and directly owns 0..N `GradedProduceLot`
children (never a `grading_output_lines` join table — each row IS the
output). Follows the exact operational-command conventions this codebase
already established for `harvest_service`/`packing_service`: tenant-scoped
`client_command_id` + SHA-256 fingerprint idempotency (pre-lock and
post-lock replay checks, `IntegrityError` fallback), the CropBatch-before-
HarvestedProduceLot lock order, and the same quality-hold/recall source-
material gates packing's own input protection already uses.

Frozen reconciliation: `input_presented = SUM(graded outputs) + rejected +
loss + sample + remainder`; the HarvestedProduceLot ledger debit equals
`-(input_presented - remainder)` (`processed`), never the full presented
amount — remainder is retained on the same lot for a later GradingEvent,
never re-credited, never a separate lot/ledger entry.
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
from app.models.graded_produce_lot import GradedProduceLot
from app.models.graded_produce_lot_ledger_entry import GradedProduceLotLedgerEntry
from app.models.grade_definition import GradeDefinition
from app.models.grade_definition_version import GradeDefinitionVersion
from app.models.grading_event import GradingEvent
from app.models.harvested_produce_lot import HarvestedProduceLot
from app.models.location import Location
from app.models.location_type import LocationType
from app.models.produce_lot_ledger_entry import ProduceLotLedgerEntry
from app.models.variety import Variety
from app.schemas.crop_batch import CropSummary, VarietySummary
from app.schemas.grading import GradedProduceLotRead, GradingEventRead
from app.schemas.harvest import MAX_WEIGHT_KG, canonical_decimal_str
from app.services import farm_service, quality_hold_service, recall_service
from app.services.audit import append_audit_event
from app.services.errors import (
    DuplicateGradedProduceLotCodeError,
    FarmNotFoundError,
    GradedProduceLotNotFoundError,
    GradeDefinitionVersionNotFoundError,
    GradingCommandReusedWithDifferentPayloadError,
    GradingEventNotFoundError,
    GradingSourceProduceLotNotFoundError,
    GradingValidationError,
    InsufficientHarvestedProduceLotBalanceError,
    InvalidGradingEffectiveTimeError,
    ProcessingHallLocationInvalidError,
    QualityHoldOpenError,
    RecallContainmentOpenError,
    TooManyGradingOutputsError,
)

MAX_GRADING_OUTPUTS = 50
PROCESSING_HALL_LOCATION_TYPE_CODE = "packing_hall"


def _require_active_farm(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID):
    farm = farm_service.get_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    if farm.status != "active":
        raise FarmNotFoundError(str(farm_id))
    return farm


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _compute_grading_fingerprint(
    *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, effective_time: datetime,
    note: str | None, source_harvested_produce_lot_id: uuid.UUID, processing_hall_location_id: uuid.UUID,
    input_presented_weight_kg: Decimal, input_presented_whole_unit_count: int | None,
    rejected_weight_kg: Decimal, rejected_whole_unit_count: int | None,
    loss_weight_kg: Decimal, loss_whole_unit_count: int | None,
    sample_weight_kg: Decimal, sample_whole_unit_count: int | None,
    remainder_weight_kg: Decimal, remainder_whole_unit_count: int | None,
    outputs: list[dict],
) -> str:
    sorted_outputs = sorted(outputs, key=lambda o: str(o["grade_definition_version_id"]))
    parts = [
        str(tenant_id), str(farm_id), str(actor_user_id), effective_time.astimezone(timezone.utc).isoformat(),
        note or "", str(source_harvested_produce_lot_id), str(processing_hall_location_id),
        canonical_decimal_str(input_presented_weight_kg),
        str(input_presented_whole_unit_count) if input_presented_whole_unit_count is not None else "",
        canonical_decimal_str(rejected_weight_kg),
        str(rejected_whole_unit_count) if rejected_whole_unit_count is not None else "",
        canonical_decimal_str(loss_weight_kg),
        str(loss_whole_unit_count) if loss_whole_unit_count is not None else "",
        canonical_decimal_str(sample_weight_kg),
        str(sample_whole_unit_count) if sample_whole_unit_count is not None else "",
        canonical_decimal_str(remainder_weight_kg),
        str(remainder_whole_unit_count) if remainder_whole_unit_count is not None else "",
    ]
    for output in sorted_outputs:
        parts.extend(
            [
                str(output["grade_definition_version_id"]), output["code"],
                canonical_decimal_str(output["output_weight_kg"]),
                str(output["output_whole_unit_count"]) if output["output_whole_unit_count"] is not None else "",
            ]
        )
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _find_existing_grading_event(
    db: Session, *, tenant_id: uuid.UUID, client_command_id: uuid.UUID
) -> GradingEvent | None:
    return db.execute(
        select(GradingEvent).where(
            GradingEvent.tenant_id == tenant_id, GradingEvent.client_command_id == client_command_id
        )
    ).scalar_one_or_none()


# --- Command ------------------------------------------------------------------------


def record_grading(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_command_id: uuid.UUID,
    source_harvested_produce_lot_id: uuid.UUID,
    processing_hall_location_id: uuid.UUID,
    effective_time: datetime,
    note: str | None,
    input_presented_weight_kg: Decimal,
    input_presented_whole_unit_count: int | None,
    rejected_weight_kg: Decimal,
    rejected_whole_unit_count: int | None,
    loss_weight_kg: Decimal,
    loss_whole_unit_count: int | None,
    sample_weight_kg: Decimal,
    sample_whole_unit_count: int | None,
    remainder_weight_kg: Decimal,
    remainder_whole_unit_count: int | None,
    outputs: list[dict],
) -> GradingEvent:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    if effective_time > datetime.now(timezone.utc):
        raise InvalidGradingEffectiveTimeError("effective_time cannot be in the future")
    if len(outputs) > MAX_GRADING_OUTPUTS:
        raise TooManyGradingOutputsError(f"a grading command may include at most {MAX_GRADING_OUTPUTS} outputs")

    fingerprint = _compute_grading_fingerprint(
        tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, effective_time=effective_time,
        note=note, source_harvested_produce_lot_id=source_harvested_produce_lot_id,
        processing_hall_location_id=processing_hall_location_id,
        input_presented_weight_kg=input_presented_weight_kg,
        input_presented_whole_unit_count=input_presented_whole_unit_count, rejected_weight_kg=rejected_weight_kg,
        rejected_whole_unit_count=rejected_whole_unit_count, loss_weight_kg=loss_weight_kg,
        loss_whole_unit_count=loss_whole_unit_count, sample_weight_kg=sample_weight_kg,
        sample_whole_unit_count=sample_whole_unit_count, remainder_weight_kg=remainder_weight_kg,
        remainder_whole_unit_count=remainder_whole_unit_count, outputs=outputs,
    )

    existing = _find_existing_grading_event(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise GradingCommandReusedWithDifferentPayloadError(str(client_command_id))

    lot = db.execute(
        select(HarvestedProduceLot).where(HarvestedProduceLot.id == source_harvested_produce_lot_id)
    ).scalar_one_or_none()
    if lot is None or lot.tenant_id != tenant_id or lot.farm_id != farm_id:
        raise GradingSourceProduceLotNotFoundError(str(source_harvested_produce_lot_id))

    # Lock order: CropBatch before HarvestedProduceLot — the same global
    # order harvest correction/packing/quality-hold/recall already use.
    batch = db.execute(
        select(CropBatch).where(CropBatch.id == lot.batch_id).with_for_update()
    ).scalar_one_or_none()
    if batch is None or batch.tenant_id != tenant_id or batch.farm_id != farm_id:
        raise GradingSourceProduceLotNotFoundError(str(source_harvested_produce_lot_id))

    existing = _find_existing_grading_event(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise GradingCommandReusedWithDifferentPayloadError(str(client_command_id))

    # A genuinely new grading command is blocked while the source batch has
    # an open quality hold or an open batch-scope recall — mirrors
    # packing_service's own source-material gate exactly.
    if quality_hold_service.has_open_quality_hold(db, batch_id=batch.id):
        raise QualityHoldOpenError(str(batch.id))
    if recall_service.has_open_batch_recall(db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch.id):
        raise RecallContainmentOpenError(str(batch.id))

    locked_lot = db.execute(
        select(HarvestedProduceLot).where(HarvestedProduceLot.id == lot.id).with_for_update()
    ).scalar_one()

    if recall_service.has_open_produce_lot_recall(
        db, tenant_id=tenant_id, farm_id=farm_id, produce_lot_id=locked_lot.id
    ):
        raise RecallContainmentOpenError(str(locked_lot.id))

    balance_row = db.execute(
        select(
            func.sum(ProduceLotLedgerEntry.weight_delta_kg).label("weight"),
            func.sum(ProduceLotLedgerEntry.whole_unit_count_delta).label("count"),
        ).where(ProduceLotLedgerEntry.produce_lot_id == locked_lot.id)
    ).one()
    available_weight: Decimal = balance_row.weight if balance_row.weight is not None else Decimal("0")
    available_count: int | None = balance_row.count

    # --- count-mode consistency against the source lot's own mode ------------------
    lot_tracks_count = locked_lot.total_whole_unit_count is not None
    if lot_tracks_count:
        if input_presented_whole_unit_count is None:
            raise GradingValidationError(
                "source produce lot tracks whole-unit count; input_presented_whole_unit_count is required"
            )
    else:
        if input_presented_whole_unit_count is not None:
            raise GradingValidationError(
                "source produce lot does not track whole-unit count; grading count fields must be null"
            )

    # --- source availability: compare PRESENTED (never merely processed) -----------
    if input_presented_weight_kg > available_weight:
        raise InsufficientHarvestedProduceLotBalanceError(str(locked_lot.id))
    if lot_tracks_count:
        if available_count is None or input_presented_whole_unit_count > available_count:
            raise InsufficientHarvestedProduceLotBalanceError(str(locked_lot.id))

    if input_presented_weight_kg >= MAX_WEIGHT_KG:
        raise GradingValidationError("input_presented_weight_kg exceeds the supported total weight range")

    # --- weight reconciliation: input_presented = SUM(outputs) + reject + loss + sample + remainder ---
    output_weight_total: Decimal = sum((o["output_weight_kg"] for o in outputs), Decimal("0"))
    expected_total = output_weight_total + rejected_weight_kg + loss_weight_kg + sample_weight_kg + remainder_weight_kg
    if input_presented_weight_kg != expected_total:
        raise GradingValidationError(
            "input_presented_weight_kg does not reconcile into graded outputs, rejection, loss, sample, "
            "and remainder"
        )
    if remainder_weight_kg >= input_presented_weight_kg:
        raise GradingValidationError("a grading event must process a positive quantity (remainder < presented)")

    if lot_tracks_count:
        output_count_total = sum(
            (o["output_whole_unit_count"] for o in outputs if o["output_whole_unit_count"] is not None), 0
        )
        expected_count_total = (
            output_count_total + rejected_whole_unit_count + loss_whole_unit_count + sample_whole_unit_count
            + remainder_whole_unit_count
        )
        if input_presented_whole_unit_count != expected_count_total:
            raise GradingValidationError(
                "input_presented_whole_unit_count does not reconcile into graded outputs, rejection, loss, "
                "sample, and remainder counts"
            )
        if remainder_whole_unit_count >= input_presented_whole_unit_count:
            raise GradingValidationError(
                "a grading event must process a positive count quantity (remainder count < presented count)"
            )

    # --- Processing/Packing Hall: same tenant/farm, active, type=packing_hall -------
    hall_row = db.execute(
        select(Location, LocationType.code)
        .join(LocationType, LocationType.id == Location.location_type_id)
        .where(
            Location.id == processing_hall_location_id, Location.tenant_id == tenant_id,
            Location.farm_id == farm_id,
        )
    ).first()
    if hall_row is None:
        raise ProcessingHallLocationInvalidError(str(processing_hall_location_id))
    hall, hall_type_code = hall_row
    if hall_type_code != PROCESSING_HALL_LOCATION_TYPE_CODE or hall.status != "active":
        raise ProcessingHallLocationInvalidError(str(processing_hall_location_id))

    # --- per-output grade-version compatibility -------------------------------------
    for output in outputs:
        grade_version = db.execute(
            select(GradeDefinitionVersion).where(
                GradeDefinitionVersion.id == output["grade_definition_version_id"],
                GradeDefinitionVersion.tenant_id == tenant_id,
            )
        ).scalar_one_or_none()
        if grade_version is None:
            raise GradeDefinitionVersionNotFoundError(str(output["grade_definition_version_id"]))
        if grade_version.status == "draft":
            raise GradingValidationError(
                f"grade_definition_version {grade_version.id} is draft and cannot be referenced"
            )
        if effective_time < grade_version.effective_from:
            raise GradingValidationError(
                f"grade_definition_version {grade_version.id} is not yet effective at this event's effective_time"
            )
        if grade_version.effective_until is not None and effective_time >= grade_version.effective_until:
            raise GradingValidationError(
                f"grade_definition_version {grade_version.id} is no longer effective at this event's "
                "effective_time"
            )

        grade_definition = db.execute(
            select(GradeDefinition).where(GradeDefinition.id == grade_version.grade_definition_id)
        ).scalar_one()
        if grade_definition.crop_id != locked_lot.crop_id:
            raise GradingValidationError(
                f"grade_definition_version {grade_version.id} crop does not match the source produce lot's crop"
            )
        if grade_definition.variety_id is not None and grade_definition.variety_id != locked_lot.variety_id:
            raise GradingValidationError(
                f"grade_definition_version {grade_version.id} variety is incompatible with the source produce "
                "lot's variety"
            )

    processed_weight_kg = input_presented_weight_kg - remainder_weight_kg
    processed_whole_unit_count = (
        input_presented_whole_unit_count - remainder_whole_unit_count if lot_tracks_count else None
    )

    event_id = uuid.uuid4()
    output_lot_ids = {o["grade_definition_version_id"]: uuid.uuid4() for o in outputs}

    try:
        event = GradingEvent(
            id=event_id, tenant_id=tenant_id, farm_id=farm_id,
            source_harvested_produce_lot_id=locked_lot.id, processing_hall_location_id=processing_hall_location_id,
            effective_time=effective_time, actor_user_id=actor_user_id, client_command_id=client_command_id,
            request_fingerprint=fingerprint, note=note,
            input_presented_weight_kg=input_presented_weight_kg,
            input_presented_whole_unit_count=input_presented_whole_unit_count,
            rejected_weight_kg=rejected_weight_kg, rejected_whole_unit_count=rejected_whole_unit_count,
            loss_weight_kg=loss_weight_kg, loss_whole_unit_count=loss_whole_unit_count,
            sample_weight_kg=sample_weight_kg, sample_whole_unit_count=sample_whole_unit_count,
            remainder_weight_kg=remainder_weight_kg, remainder_whole_unit_count=remainder_whole_unit_count,
        )
        db.add(event)
        db.flush()

        graded_lot_objs: dict[uuid.UUID, GradedProduceLot] = {}
        for output in outputs:
            grade_version_id = output["grade_definition_version_id"]
            graded_lot = GradedProduceLot(
                id=output_lot_ids[grade_version_id], tenant_id=tenant_id, farm_id=farm_id,
                grading_event_id=event.id, crop_id=locked_lot.crop_id, variety_id=locked_lot.variety_id,
                grade_definition_version_id=grade_version_id, code=output["code"],
                original_received_weight_kg=output["output_weight_kg"],
                original_received_whole_unit_count=output["output_whole_unit_count"],
                effective_time=effective_time,
            )
            db.add(graded_lot)
            graded_lot_objs[grade_version_id] = graded_lot
        db.flush()

        # Deterministic opening receipt per graded lot (mirrors CMP-014's
        # own harvest_receipt convention one level down the chain).
        for graded_lot in graded_lot_objs.values():
            db.add(
                GradedProduceLotLedgerEntry(
                    id=graded_lot.id, tenant_id=tenant_id, farm_id=farm_id,
                    graded_produce_lot_id=graded_lot.id, grading_event_id=event.id, entry_kind="grading_receipt",
                    weight_delta_kg=graded_lot.original_received_weight_kg,
                    whole_unit_count_delta=graded_lot.original_received_whole_unit_count,
                    effective_time=graded_lot.effective_time, recorded_time=graded_lot.recorded_at,
                    actor_user_id=actor_user_id, note=None,
                )
            )
        db.flush()

        # Deterministic grading_consumption debit — exactly one per event,
        # id = event.id (a GradingEvent has exactly one source lot and one
        # net-processed quantity, unlike packing's own per-input-line debits).
        db.add(
            ProduceLotLedgerEntry(
                id=event.id, tenant_id=tenant_id, farm_id=farm_id, produce_lot_id=locked_lot.id,
                harvest_event_id=None, harvest_source_line_correction_id=None,
                grading_event_id=event.id, entry_kind="grading_consumption",
                weight_delta_kg=-processed_weight_kg,
                whole_unit_count_delta=-processed_whole_unit_count if lot_tracks_count else None,
                effective_time=effective_time, recorded_time=event.recorded_time, actor_user_id=actor_user_id,
                note=None,
            )
        )
        db.flush()

        append_audit_event(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="grading_event.created",
            entity_type="grading_event", entity_id=event.id,
            event_data={
                "grading_event_id": str(event.id),
                "source_harvested_produce_lot_id": str(locked_lot.id),
                "processing_hall_location_id": str(processing_hall_location_id),
                "effective_time": effective_time.isoformat(), "client_command_id": str(client_command_id),
                "output_count": len(outputs),
                "graded_produce_lot_ids": [str(o.id) for o in graded_lot_objs.values()],
                "input_presented_weight_kg": canonical_decimal_str(input_presented_weight_kg),
                "processed_weight_kg": canonical_decimal_str(processed_weight_kg),
                "remainder_weight_kg": canonical_decimal_str(remainder_weight_kg),
                "rejected_weight_kg": canonical_decimal_str(rejected_weight_kg),
                "loss_weight_kg": canonical_decimal_str(loss_weight_kg),
                "sample_weight_kg": canonical_decimal_str(sample_weight_kg),
            },
        )
        db.flush()
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_grading_events_tenant_client_command_id":
            replay = _find_existing_grading_event(db, tenant_id=tenant_id, client_command_id=client_command_id)
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise GradingCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        if constraint == "ux_graded_produce_lots_tenant_code_lower":
            raise DuplicateGradedProduceLotCodeError(str(tenant_id)) from exc
        raise
    except Exception:
        db.rollback()
        raise
    db.refresh(event)
    return event


# --- Reads ------------------------------------------------------------------------


def _load_outputs(db: Session, *, event_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[GradedProduceLotRead]]:
    grouped: dict[uuid.UUID, list[GradedProduceLotRead]] = {eid: [] for eid in event_ids}
    if not event_ids:
        return grouped
    rows = db.execute(
        select(GradedProduceLot, Crop, Variety)
        .join(Crop, Crop.id == GradedProduceLot.crop_id)
        .outerjoin(Variety, Variety.id == GradedProduceLot.variety_id)
        .where(GradedProduceLot.grading_event_id.in_(event_ids))
        .order_by(GradedProduceLot.code)
    ).all()
    for lot, crop, variety in rows:
        grouped[lot.grading_event_id].append(_row_to_graded_lot_read(lot, crop, variety))
    return grouped


def _row_to_graded_lot_read(lot: GradedProduceLot, crop: Crop, variety: Variety | None) -> GradedProduceLotRead:
    return GradedProduceLotRead(
        id=lot.id, tenant_id=lot.tenant_id, farm_id=lot.farm_id, grading_event_id=lot.grading_event_id,
        code=lot.code, crop=CropSummary(id=crop.id, code=crop.code, common_name=crop.common_name),
        variety=(VarietySummary(id=variety.id, code=variety.code, name=variety.name) if variety else None),
        grade_definition_version_id=lot.grade_definition_version_id,
        original_received_weight_kg=lot.original_received_weight_kg,
        original_received_whole_unit_count=lot.original_received_whole_unit_count,
        effective_time=lot.effective_time, recorded_at=lot.recorded_at,
    )


def _row_to_grading_event_read(
    event: GradingEvent, produce_lot_code: str, outputs: list[GradedProduceLotRead]
) -> GradingEventRead:
    processed_weight_kg = event.input_presented_weight_kg - event.remainder_weight_kg
    processed_whole_unit_count = (
        event.input_presented_whole_unit_count - event.remainder_whole_unit_count
        if event.input_presented_whole_unit_count is not None
        else None
    )
    return GradingEventRead(
        id=event.id, tenant_id=event.tenant_id, farm_id=event.farm_id,
        source_harvested_produce_lot_id=event.source_harvested_produce_lot_id,
        source_produce_lot_code=produce_lot_code,
        processing_hall_location_id=event.processing_hall_location_id, effective_time=event.effective_time,
        recorded_time=event.recorded_time, actor_user_id=event.actor_user_id,
        client_command_id=event.client_command_id, note=event.note,
        input_presented_weight_kg=event.input_presented_weight_kg,
        input_presented_whole_unit_count=event.input_presented_whole_unit_count,
        rejected_weight_kg=event.rejected_weight_kg, rejected_whole_unit_count=event.rejected_whole_unit_count,
        loss_weight_kg=event.loss_weight_kg, loss_whole_unit_count=event.loss_whole_unit_count,
        sample_weight_kg=event.sample_weight_kg, sample_whole_unit_count=event.sample_whole_unit_count,
        remainder_weight_kg=event.remainder_weight_kg, remainder_whole_unit_count=event.remainder_whole_unit_count,
        processed_weight_kg=processed_weight_kg, processed_whole_unit_count=processed_whole_unit_count,
        outputs=outputs,
    )


def get_grading_event(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, grading_event_id: uuid.UUID
) -> GradingEventRead:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    row = db.execute(
        select(GradingEvent, HarvestedProduceLot.code)
        .join(HarvestedProduceLot, HarvestedProduceLot.id == GradingEvent.source_harvested_produce_lot_id)
        .where(
            GradingEvent.id == grading_event_id, GradingEvent.tenant_id == tenant_id,
            GradingEvent.farm_id == farm_id,
        )
    ).first()
    if row is None:
        raise GradingEventNotFoundError(str(grading_event_id))
    event, lot_code = row
    outputs = _load_outputs(db, event_ids=[grading_event_id])[grading_event_id]
    return _row_to_grading_event_read(event, lot_code, outputs)


def list_grading_events(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID,
    source_harvested_produce_lot_id: uuid.UUID | None = None,
) -> list[GradingEventRead]:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    query = (
        select(GradingEvent, HarvestedProduceLot.code)
        .join(HarvestedProduceLot, HarvestedProduceLot.id == GradingEvent.source_harvested_produce_lot_id)
        .where(GradingEvent.tenant_id == tenant_id, GradingEvent.farm_id == farm_id)
    )
    if source_harvested_produce_lot_id is not None:
        query = query.where(GradingEvent.source_harvested_produce_lot_id == source_harvested_produce_lot_id)
    rows = db.execute(query.order_by(GradingEvent.effective_time, GradingEvent.recorded_time)).all()
    event_ids = [r[0].id for r in rows]
    outputs_by_event = _load_outputs(db, event_ids=event_ids)
    return [_row_to_grading_event_read(r[0], r[1], outputs_by_event[r[0].id]) for r in rows]


def get_graded_produce_lot(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, graded_produce_lot_id: uuid.UUID
) -> GradedProduceLotRead:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    row = db.execute(
        select(GradedProduceLot, Crop, Variety)
        .join(Crop, Crop.id == GradedProduceLot.crop_id)
        .outerjoin(Variety, Variety.id == GradedProduceLot.variety_id)
        .where(
            GradedProduceLot.id == graded_produce_lot_id, GradedProduceLot.tenant_id == tenant_id,
            GradedProduceLot.farm_id == farm_id,
        )
    ).first()
    if row is None:
        raise GradedProduceLotNotFoundError(str(graded_produce_lot_id))
    lot, crop, variety = row
    return _row_to_graded_lot_read(lot, crop, variety)


def list_graded_produce_lots(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, crop_id: uuid.UUID | None = None,
    variety_id: uuid.UUID | None = None, grade_definition_version_id: uuid.UUID | None = None,
    grading_event_id: uuid.UUID | None = None,
) -> list[GradedProduceLotRead]:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    query = (
        select(GradedProduceLot, Crop, Variety)
        .join(Crop, Crop.id == GradedProduceLot.crop_id)
        .outerjoin(Variety, Variety.id == GradedProduceLot.variety_id)
        .where(GradedProduceLot.tenant_id == tenant_id, GradedProduceLot.farm_id == farm_id)
    )
    if crop_id is not None:
        query = query.where(GradedProduceLot.crop_id == crop_id)
    if variety_id is not None:
        query = query.where(GradedProduceLot.variety_id == variety_id)
    if grade_definition_version_id is not None:
        query = query.where(GradedProduceLot.grade_definition_version_id == grade_definition_version_id)
    if grading_event_id is not None:
        query = query.where(GradedProduceLot.grading_event_id == grading_event_id)
    rows = db.execute(query.order_by(GradedProduceLot.code)).all()
    return [_row_to_graded_lot_read(lot, crop, variety) for lot, crop, variety in rows]
