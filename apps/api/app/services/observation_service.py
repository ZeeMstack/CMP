import hashlib
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.batch_stage_run import BatchStageRun
from app.models.carrier import Carrier
from app.models.carrier_type import CarrierType
from app.models.crop_batch import CropBatch
from app.models.germination_check import GerminationCheck
from app.models.observation_definition import ObservationDefinition
from app.models.observation_event import ObservationEvent
from app.models.observation_value import ObservationValue
from app.models.sowing_event_line import SowingEventLine
from app.models.workflow_stage import WorkflowStage
from app.schemas.crop_batch import StageSummary
from app.schemas.observation_definition import ObservationDefinitionRead
from app.schemas.observation_event import (
    GerminationCheckRead,
    ObservationDefinitionSummary,
    ObservationEventRead,
    ObservationValueRead,
)
from app.schemas.sowing_event import CarrierSummary, CarrierTypeSummary
from app.services import farm_service
from app.services.audit import append_audit_event
from app.services.errors import (
    BatchCarrierAssignmentNotFoundError,
    CropBatchClosedError,
    CropBatchNotFoundError,
    DuplicateObservationDefinitionCodeError,
    FarmNotFoundError,
    InvalidObservationEffectiveTimeError,
    ObservationCommandReusedWithDifferentPayloadError,
    ObservationDefinitionNotFoundError,
    ObservationEventNotFoundError,
    ObservationValidationError,
    TooManyObservationEntriesError,
)

MAX_OBSERVATION_ENTRIES = 500

TYPE_TO_FIELD = {
    "integer": "value_integer",
    "decimal": "value_decimal",
    "percentage": "value_decimal",
    "boolean": "value_boolean",
    "text": "value_text",
}


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


# --- Observation definitions -----------------------------------------------------


def register_observation_definition(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    code: str,
    name: str,
    description: str | None,
    value_type: str,
    unit: str | None,
    target_scope: str,
    min_value: Decimal | None,
    max_value: Decimal | None,
) -> ObservationDefinition:
    definition = ObservationDefinition(
        id=uuid.uuid4(), tenant_id=tenant_id, code=code, name=name, description=description,
        value_type=value_type, unit=unit, target_scope=target_scope, min_value=min_value, max_value=max_value,
        status="active", created_by_user_id=actor_user_id,
    )
    db.add(definition)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateObservationDefinitionCodeError(f"{tenant_id}:{code}") from exc

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="observation_definition.created",
        entity_type="observation_definition", entity_id=definition.id,
        event_data={"code": definition.code, "value_type": value_type, "target_scope": target_scope},
    )
    db.commit()
    db.refresh(definition)
    return definition


def get_observation_definition(
    db: Session, *, tenant_id: uuid.UUID, definition_id: uuid.UUID
) -> ObservationDefinitionRead:
    definition = db.execute(
        select(ObservationDefinition).where(
            ObservationDefinition.id == definition_id, ObservationDefinition.tenant_id == tenant_id
        )
    ).scalar_one_or_none()
    if definition is None:
        raise ObservationDefinitionNotFoundError(str(definition_id))
    return ObservationDefinitionRead.model_validate(definition)


def list_observation_definitions(db: Session, *, tenant_id: uuid.UUID) -> list[ObservationDefinitionRead]:
    rows = db.execute(
        select(ObservationDefinition).where(ObservationDefinition.tenant_id == tenant_id).order_by(
            ObservationDefinition.code
        )
    ).scalars()
    return [ObservationDefinitionRead.model_validate(r) for r in rows]


# --- Observations ------------------------------------------------------------------


def _canonical_value_repr(value: dict) -> str:
    if value.get("value_integer") is not None:
        return f"int:{value['value_integer']}"
    if value.get("value_decimal") is not None:
        return f"dec:{value['value_decimal']}"
    if value.get("value_boolean") is not None:
        return f"bool:{value['value_boolean']}"
    return f"text:{value['value_text']}"


def _compute_observation_fingerprint(
    *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, batch_id: uuid.UUID,
    effective_time: datetime, note: str | None, values: list[dict], germination_checks: list[dict],
) -> str:
    sorted_values = sorted(
        values,
        key=lambda v: (str(v["observation_definition_id"]), str(v.get("batch_carrier_assignment_id") or "")),
    )
    sorted_checks = sorted(germination_checks, key=lambda c: str(c["batch_carrier_assignment_id"]))
    parts = [
        str(tenant_id), str(farm_id), str(actor_user_id), str(batch_id),
        effective_time.astimezone(timezone.utc).isoformat(), note or "",
    ]
    for v in sorted_values:
        parts.extend(
            [
                str(v["observation_definition_id"]),
                str(v.get("batch_carrier_assignment_id") or ""),
                _canonical_value_repr(v),
                v.get("note") or "",
            ]
        )
    for c in sorted_checks:
        parts.extend(
            [
                str(c["batch_carrier_assignment_id"]),
                str(c["inspected_site_count"]),
                str(c["normal_germinated_site_count"]),
                str(c["abnormal_germinated_site_count"]),
                str(c["failed_site_count"]),
                c.get("note") or "",
            ]
        )
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _find_existing_observation_event(
    db: Session, *, tenant_id: uuid.UUID, client_command_id: uuid.UUID
) -> ObservationEvent | None:
    return db.execute(
        select(ObservationEvent).where(
            ObservationEvent.tenant_id == tenant_id, ObservationEvent.client_command_id == client_command_id
        )
    ).scalar_one_or_none()


def record_observation(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    batch_id: uuid.UUID,
    client_command_id: uuid.UUID,
    effective_time: datetime,
    note: str | None,
    values: list[dict],
    germination_checks: list[dict],
) -> ObservationEvent:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    if effective_time > datetime.now(timezone.utc):
        raise InvalidObservationEffectiveTimeError("effective_time cannot be in the future")
    total_entries = len(values) + len(germination_checks)
    if total_entries < 1:
        raise ObservationValidationError("at least one value or germination check is required")
    if total_entries > MAX_OBSERVATION_ENTRIES:
        raise TooManyObservationEntriesError(f"a command may include at most {MAX_OBSERVATION_ENTRIES} entries")

    fingerprint = _compute_observation_fingerprint(
        tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, batch_id=batch_id,
        effective_time=effective_time, note=note, values=values, germination_checks=germination_checks,
    )

    existing = _find_existing_observation_event(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise ObservationCommandReusedWithDifferentPayloadError(str(client_command_id))

    batch = db.execute(
        select(CropBatch)
        .where(CropBatch.id == batch_id, CropBatch.tenant_id == tenant_id, CropBatch.farm_id == farm_id)
        .with_for_update()
    ).scalar_one_or_none()
    if batch is None:
        raise CropBatchNotFoundError(str(batch_id))

    existing = _find_existing_observation_event(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise ObservationCommandReusedWithDifferentPayloadError(str(client_command_id))

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
        raise InvalidObservationEffectiveTimeError("effective_time precedes the batch's creation effective time")
    if effective_time < active_run.entered_effective_time:
        raise InvalidObservationEffectiveTimeError("effective_time precedes the current stage run's entry time")

    sorted_definition_ids = sorted({v["observation_definition_id"] for v in values})
    definitions = list(
        db.execute(
            select(ObservationDefinition)
            .where(
                ObservationDefinition.id.in_(sorted_definition_ids), ObservationDefinition.tenant_id == tenant_id
            )
            .order_by(ObservationDefinition.id)
            .with_for_update()
        ).scalars()
    )
    definitions_by_id = {d.id: d for d in definitions}
    for did in sorted_definition_ids:
        if did not in definitions_by_id:
            raise ObservationDefinitionNotFoundError(str(did))

    assignment_ids = sorted(
        {v["batch_carrier_assignment_id"] for v in values if v.get("batch_carrier_assignment_id") is not None}
        | {c["batch_carrier_assignment_id"] for c in germination_checks}
    )
    assignments = list(
        db.execute(
            select(BatchCarrierAssignment)
            .where(
                BatchCarrierAssignment.id.in_(assignment_ids), BatchCarrierAssignment.tenant_id == tenant_id,
                BatchCarrierAssignment.farm_id == farm_id,
            )
            .order_by(BatchCarrierAssignment.id)
            .with_for_update()
        ).scalars()
    )
    assignments_by_id = {a.id: a for a in assignments}
    for aid in assignment_ids:
        if aid not in assignments_by_id:
            raise BatchCarrierAssignmentNotFoundError(str(aid))

    sown_counts_by_assignment: dict[uuid.UUID, int] = {}
    if germination_checks:
        rows = db.execute(
            select(SowingEventLine.batch_carrier_assignment_id, SowingEventLine.sown_site_count).where(
                SowingEventLine.batch_carrier_assignment_id.in_(
                    [c["batch_carrier_assignment_id"] for c in germination_checks]
                )
            )
        ).all()
        sown_counts_by_assignment = {r[0]: r[1] for r in rows}

    for v in values:
        definition = definitions_by_id[v["observation_definition_id"]]
        if definition.status != "active":
            raise ObservationValidationError(f"observation definition {definition.code} is not active")

        assignment_id = v.get("batch_carrier_assignment_id")
        if definition.target_scope == "crop_batch" and assignment_id is not None:
            raise ObservationValidationError(
                f"definition {definition.code} has target scope crop_batch; no assignment permitted"
            )
        if definition.target_scope == "carrier_assignment" and assignment_id is None:
            raise ObservationValidationError(
                f"definition {definition.code} has target scope carrier_assignment; an assignment is required"
            )

        expected_field = TYPE_TO_FIELD[definition.value_type]
        populated_fields = [
            f for f in ("value_integer", "value_decimal", "value_boolean", "value_text") if v.get(f) is not None
        ]
        if populated_fields != [expected_field]:
            raise ObservationValidationError(
                f"value type does not match definition {definition.code}'s declared value_type"
            )

        if definition.value_type == "integer":
            val = v["value_integer"]
            if definition.min_value is not None and val < definition.min_value:
                raise ObservationValidationError(f"value below definition {definition.code}'s minimum")
            if definition.max_value is not None and val > definition.max_value:
                raise ObservationValidationError(f"value above definition {definition.code}'s maximum")
        elif definition.value_type in ("decimal", "percentage"):
            val = v["value_decimal"]
            if definition.value_type == "percentage" and (val < 0 or val > 100):
                raise ObservationValidationError("percentage value must be within 0 and 100")
            if definition.min_value is not None and val < definition.min_value:
                raise ObservationValidationError(f"value below definition {definition.code}'s minimum")
            if definition.max_value is not None and val > definition.max_value:
                raise ObservationValidationError(f"value above definition {definition.code}'s maximum")

        if assignment_id is not None:
            assignment = assignments_by_id[assignment_id]
            if assignment.batch_id != batch.id:
                raise ObservationValidationError(f"assignment {assignment_id} does not belong to this batch")
            if assignment.released_effective_time is not None:
                raise ObservationValidationError(f"assignment {assignment_id} is not active")
            if effective_time < assignment.assigned_effective_time:
                raise InvalidObservationEffectiveTimeError(
                    f"effective_time precedes assignment {assignment_id}'s assigned_effective_time"
                )

    for c in germination_checks:
        assignment = assignments_by_id[c["batch_carrier_assignment_id"]]
        if assignment.batch_id != batch.id:
            raise ObservationValidationError(
                f"assignment {c['batch_carrier_assignment_id']} does not belong to this batch"
            )
        if assignment.released_effective_time is not None:
            raise ObservationValidationError(f"assignment {c['batch_carrier_assignment_id']} is not active")
        if effective_time < assignment.assigned_effective_time:
            raise InvalidObservationEffectiveTimeError(
                f"effective_time precedes assignment {c['batch_carrier_assignment_id']}'s assigned_effective_time"
            )
        sown_count = sown_counts_by_assignment.get(c["batch_carrier_assignment_id"])
        if sown_count is None:
            raise ObservationValidationError(
                f"no sowing line found for assignment {c['batch_carrier_assignment_id']}"
            )
        if c["inspected_site_count"] > sown_count:
            raise ObservationValidationError(
                "inspected_site_count cannot exceed the assignment's original sown_site_count"
            )

    event = ObservationEvent(
        id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, batch_id=batch.id,
        active_batch_stage_run_id=active_run.id, effective_time=effective_time, actor_user_id=actor_user_id,
        client_command_id=client_command_id, request_fingerprint=fingerprint, note=note,
    )
    db.add(event)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_observation_events_tenant_client_command_id":
            replay = _find_existing_observation_event(db, tenant_id=tenant_id, client_command_id=client_command_id)
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise ObservationCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    try:
        for v in values:
            db.add(
                ObservationValue(
                    id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, observation_event_id=event.id,
                    observation_definition_id=v["observation_definition_id"],
                    batch_carrier_assignment_id=v.get("batch_carrier_assignment_id"),
                    value_integer=v.get("value_integer"), value_decimal=v.get("value_decimal"),
                    value_boolean=v.get("value_boolean"), value_text=v.get("value_text"), note=v.get("note"),
                )
            )
        for c in germination_checks:
            db.add(
                GerminationCheck(
                    id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, observation_event_id=event.id,
                    batch_carrier_assignment_id=c["batch_carrier_assignment_id"],
                    inspected_site_count=c["inspected_site_count"],
                    normal_germinated_site_count=c["normal_germinated_site_count"],
                    abnormal_germinated_site_count=c["abnormal_germinated_site_count"],
                    failed_site_count=c["failed_site_count"], note=c.get("note"),
                )
            )
        db.flush()

        append_audit_event(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="crop_batch.observation_recorded",
            entity_type="observation_event", entity_id=event.id,
            event_data={
                "observation_event_id": str(event.id), "batch_id": str(batch.id),
                "batch_stage_run_id": str(active_run.id), "effective_time": effective_time.isoformat(),
                "client_command_id": str(client_command_id), "value_count": len(values),
                "germination_check_count": len(germination_checks),
                "definition_ids": [str(did) for did in sorted_definition_ids],
                "assignment_ids": [str(aid) for aid in assignment_ids],
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(event)
    return event


# --- Observation reads ---------------------------------------------------------------


def _observation_event_header_query():
    return (
        select(
            ObservationEvent,
            CropBatch.code.label("batch_code"),
            CropBatch.workflow_version_id.label("workflow_version_id"),
            WorkflowStage,
        )
        .join(CropBatch, CropBatch.id == ObservationEvent.batch_id)
        .join(BatchStageRun, BatchStageRun.id == ObservationEvent.active_batch_stage_run_id)
        .join(WorkflowStage, WorkflowStage.id == BatchStageRun.workflow_stage_id)
    )


def _load_values_for_events(db: Session, *, event_ids: list[uuid.UUID]) -> dict[uuid.UUID, list]:
    grouped: dict[uuid.UUID, list] = {eid: [] for eid in event_ids}
    if not event_ids:
        return grouped
    rows = db.execute(
        select(ObservationValue, ObservationDefinition, Carrier, CarrierType)
        .join(ObservationDefinition, ObservationDefinition.id == ObservationValue.observation_definition_id)
        .outerjoin(
            BatchCarrierAssignment, BatchCarrierAssignment.id == ObservationValue.batch_carrier_assignment_id
        )
        .outerjoin(Carrier, Carrier.id == BatchCarrierAssignment.carrier_id)
        .outerjoin(CarrierType, CarrierType.id == Carrier.carrier_type_id)
        .where(ObservationValue.observation_event_id.in_(event_ids))
        .order_by(ObservationDefinition.code)
    ).all()
    for value, definition, carrier, carrier_type in rows:
        grouped[value.observation_event_id].append(
            ObservationValueRead(
                id=value.id,
                definition=ObservationDefinitionSummary(
                    id=definition.id, code=definition.code, name=definition.name,
                    value_type=definition.value_type, unit=definition.unit,
                ),
                carrier=(
                    CarrierSummary(
                        id=carrier.id, code=carrier.code,
                        carrier_type=CarrierTypeSummary(id=carrier_type.id, code=carrier_type.code, name=carrier_type.name),
                    )
                    if carrier is not None
                    else None
                ),
                batch_carrier_assignment_id=value.batch_carrier_assignment_id,
                value_integer=value.value_integer, value_decimal=value.value_decimal,
                value_boolean=value.value_boolean, value_text=value.value_text, note=value.note,
            )
        )
    return grouped


def _load_germination_checks_for_events(db: Session, *, event_ids: list[uuid.UUID]) -> dict[uuid.UUID, list]:
    grouped: dict[uuid.UUID, list] = {eid: [] for eid in event_ids}
    if not event_ids:
        return grouped
    rows = db.execute(
        select(GerminationCheck, Carrier, CarrierType)
        .join(BatchCarrierAssignment, BatchCarrierAssignment.id == GerminationCheck.batch_carrier_assignment_id)
        .join(Carrier, Carrier.id == BatchCarrierAssignment.carrier_id)
        .join(CarrierType, CarrierType.id == Carrier.carrier_type_id)
        .where(GerminationCheck.observation_event_id.in_(event_ids))
        .order_by(Carrier.code, Carrier.id)
    ).all()
    for check, carrier, carrier_type in rows:
        total_germinated = check.normal_germinated_site_count + check.abnormal_germinated_site_count
        unresolved = (
            check.inspected_site_count
            - check.normal_germinated_site_count
            - check.abnormal_germinated_site_count
            - check.failed_site_count
        )
        percentage = (Decimal(total_germinated) / Decimal(check.inspected_site_count)) * Decimal(100)
        grouped[check.observation_event_id].append(
            GerminationCheckRead(
                id=check.id,
                carrier=CarrierSummary(
                    id=carrier.id, code=carrier.code,
                    carrier_type=CarrierTypeSummary(id=carrier_type.id, code=carrier_type.code, name=carrier_type.name),
                ),
                batch_carrier_assignment_id=check.batch_carrier_assignment_id,
                inspected_site_count=check.inspected_site_count,
                normal_germinated_site_count=check.normal_germinated_site_count,
                abnormal_germinated_site_count=check.abnormal_germinated_site_count,
                failed_site_count=check.failed_site_count,
                unresolved_site_count=unresolved,
                total_germinated_site_count=total_germinated,
                germination_percentage=percentage,
                note=check.note,
            )
        )
    return grouped


def _row_to_observation_event_read(row, values: list, germination_checks: list) -> ObservationEventRead:
    event: ObservationEvent = row[0]
    m = row._mapping
    stage: WorkflowStage = row[3]
    return ObservationEventRead(
        id=event.id, tenant_id=event.tenant_id, farm_id=event.farm_id, batch_id=event.batch_id,
        batch_code=m["batch_code"], workflow_version_id=m["workflow_version_id"],
        stage=StageSummary(id=stage.id, code=stage.code, name=stage.name, is_terminal=stage.is_terminal),
        effective_time=event.effective_time, recorded_time=event.recorded_time,
        actor_user_id=event.actor_user_id, client_command_id=event.client_command_id, note=event.note,
        values=values, germination_checks=germination_checks,
    )


def get_observation_event(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID, observation_event_id: uuid.UUID
) -> ObservationEventRead:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    _get_batch_row(db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id)
    row = db.execute(
        _observation_event_header_query().where(
            ObservationEvent.id == observation_event_id, ObservationEvent.tenant_id == tenant_id,
            ObservationEvent.batch_id == batch_id,
        )
    ).first()
    if row is None:
        raise ObservationEventNotFoundError(str(observation_event_id))
    values = _load_values_for_events(db, event_ids=[observation_event_id])[observation_event_id]
    checks = _load_germination_checks_for_events(db, event_ids=[observation_event_id])[observation_event_id]
    return _row_to_observation_event_read(row, values, checks)


def list_observation_events(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID
) -> list[ObservationEventRead]:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    _get_batch_row(db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id)
    rows = db.execute(
        _observation_event_header_query()
        .where(ObservationEvent.tenant_id == tenant_id, ObservationEvent.batch_id == batch_id)
        .order_by(ObservationEvent.effective_time, ObservationEvent.recorded_time)
    ).all()
    event_ids = [r[0].id for r in rows]
    values_by_event = _load_values_for_events(db, event_ids=event_ids)
    checks_by_event = _load_germination_checks_for_events(db, event_ids=event_ids)
    return [_row_to_observation_event_read(r, values_by_event[r[0].id], checks_by_event[r[0].id]) for r in rows]
