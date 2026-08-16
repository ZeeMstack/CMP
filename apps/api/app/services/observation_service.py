import hashlib
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.batch_stage_run import BatchStageRun
from app.models.carrier import Carrier
from app.models.carrier_type import CarrierType
from app.models.crop_batch import CropBatch
from app.models.germination_check import GerminationCheck
from app.models.germination_outcome_snapshot import GerminationOutcomeSnapshot
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
    germination_outcomes: list[dict],
) -> str:
    sorted_values = sorted(
        values,
        key=lambda v: (str(v["observation_definition_id"]), str(v.get("batch_carrier_assignment_id") or "")),
    )
    sorted_checks = sorted(germination_checks, key=lambda c: str(c["batch_carrier_assignment_id"]))
    sorted_outcomes = sorted(germination_outcomes, key=lambda o: str(o["batch_carrier_assignment_id"]))
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
    for o in sorted_outcomes:
        parts.extend(
            [
                str(o["batch_carrier_assignment_id"]),
                str(o["normal_seedling_count"]),
                str(o["abnormal_seedling_count"]),
                str(o["assessment_complete"]),
                o.get("note") or "",
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
    germination_outcomes: list[dict] | None = None,
) -> ObservationEvent:
    # Defaulted (not a required positional-equivalent like `values`/
    # `germination_checks`) so every pre-existing caller of this function
    # (the generic observation API route, and every legacy test) is
    # completely unaffected by NURSERY-OPS-002B's addition.
    germination_outcomes = germination_outcomes or []
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    if effective_time > datetime.now(timezone.utc):
        raise InvalidObservationEffectiveTimeError("effective_time cannot be in the future")
    total_entries = len(values) + len(germination_checks) + len(germination_outcomes)
    if total_entries < 1:
        raise ObservationValidationError("at least one value, germination check, or germination outcome is required")
    if total_entries > MAX_OBSERVATION_ENTRIES:
        raise TooManyObservationEntriesError(f"a command may include at most {MAX_OBSERVATION_ENTRIES} entries")

    fingerprint = _compute_observation_fingerprint(
        tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, batch_id=batch_id,
        effective_time=effective_time, note=note, values=values, germination_checks=germination_checks,
        germination_outcomes=germination_outcomes,
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

    if effective_time < batch.created_effective_time:
        raise InvalidObservationEffectiveTimeError("effective_time precedes the batch's creation effective time")

    # NURSERY-OPS-002B.1: a command containing ONLY germination_outcomes
    # (the exact, sole shape `germination_outcome_service.py` ever
    # produces -- `values`/`germination_checks` are always empty for it)
    # must attach the ObservationEvent to whichever BatchStageRun was
    # HISTORICALLY active at `effective_time`, not merely the batch's
    # currently-open run -- a historical outcome must remain recordable
    # after the batch has since progressed to a later stage, exactly like
    # BatchCarrierAssignment's own temporal (not current-state) validation.
    # Deliberately isolated to this exact shape: any command that also
    # carries generic `values` or legacy `germination_checks` keeps the
    # ORIGINAL "current active run, effective_time must be >= its entry"
    # semantics completely unchanged, since those are established,
    # untouched CMP-010 behavior this ticket does not revisit.
    if germination_outcomes and not values and not germination_checks:
        historical_runs = list(
            db.execute(
                select(BatchStageRun)
                .where(
                    BatchStageRun.batch_id == batch.id,
                    BatchStageRun.entered_effective_time <= effective_time,
                    or_(
                        BatchStageRun.exited_effective_time.is_(None),
                        BatchStageRun.exited_effective_time > effective_time,
                    ),
                )
                .with_for_update()
            ).scalars()
        )
        if len(historical_runs) == 0:
            raise InvalidObservationEffectiveTimeError(
                "no workflow stage run was active for this batch at the given effective_time"
            )
        if len(historical_runs) > 1:
            raise ObservationValidationError(
                "more than one workflow stage run is active for this batch at the given effective_time; "
                "this indicates a data integrity issue that must be resolved before recording an outcome"
            )
        active_run = historical_runs[0]
    else:
        active_run = db.execute(
            select(BatchStageRun)
            .where(BatchStageRun.batch_id == batch.id, BatchStageRun.exited_effective_time.is_(None))
            .with_for_update()
        ).scalar_one_or_none()
        if active_run is None:
            raise CropBatchNotFoundError(str(batch_id))
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
        | {o["batch_carrier_assignment_id"] for o in germination_outcomes}
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

    # NURSERY-OPS-002B (section F/5): distinguish "no SowingEventLine row"
    # from "row exists, sown_site_count was never recorded" -- a plain
    # `.get()` on this dict cannot tell the two apart, so callers below use
    # `in`/membership before reading the mapped value.
    sown_counts_by_assignment: dict[uuid.UUID, int | None] = {}
    if germination_checks:
        rows = db.execute(
            select(SowingEventLine.batch_carrier_assignment_id, SowingEventLine.sown_site_count).where(
                SowingEventLine.batch_carrier_assignment_id.in_(
                    [c["batch_carrier_assignment_id"] for c in germination_checks]
                )
            )
        ).all()
        sown_counts_by_assignment = {r[0]: r[1] for r in rows}

    # --- NURSERY-OPS-002B: modern, individual-seedling-based outcome context
    seed_counts_by_assignment: dict[uuid.UUID, int] = {}
    carrier_type_codes_by_assignment: dict[uuid.UUID, str] = {}
    latest_completed_effective_by_assignment: dict[uuid.UUID, datetime] = {}
    if germination_outcomes:
        outcome_assignment_ids = [o["batch_carrier_assignment_id"] for o in germination_outcomes]
        seed_rows = db.execute(
            select(SowingEventLine.batch_carrier_assignment_id, SowingEventLine.seed_count).where(
                SowingEventLine.batch_carrier_assignment_id.in_(outcome_assignment_ids)
            )
        ).all()
        seed_counts_by_assignment = {r[0]: r[1] for r in seed_rows}

        carrier_ids = [assignments_by_id[aid].carrier_id for aid in outcome_assignment_ids if aid in assignments_by_id]
        type_rows = db.execute(
            select(Carrier.id, CarrierType.code)
            .join(CarrierType, CarrierType.id == Carrier.carrier_type_id)
            .where(Carrier.id.in_(carrier_ids))
        ).all()
        carrier_type_by_carrier_id = {r[0]: r[1] for r in type_rows}
        for aid in outcome_assignment_ids:
            if aid in assignments_by_id:
                carrier_type_codes_by_assignment[aid] = carrier_type_by_carrier_id.get(
                    assignments_by_id[aid].carrier_id
                )

        # Section 12/M/23.E: the "no newer provisional after an established
        # completed handoff" boundary, enforced symmetrically in both
        # directions (see the DB trigger's own comment for why the
        # symmetry matters under concurrency) -- the latest completed AND
        # the latest provisional snapshot's effective_time per assignment,
        # across ALL prior events.
        completed_rows = db.execute(
            select(GerminationOutcomeSnapshot.batch_carrier_assignment_id, ObservationEvent.effective_time)
            .join(ObservationEvent, ObservationEvent.id == GerminationOutcomeSnapshot.observation_event_id)
            .where(
                GerminationOutcomeSnapshot.batch_carrier_assignment_id.in_(outcome_assignment_ids),
                GerminationOutcomeSnapshot.assessment_complete.is_(True),
            )
        ).all()
        for aid, eff in completed_rows:
            if aid not in latest_completed_effective_by_assignment or eff > latest_completed_effective_by_assignment[aid]:
                latest_completed_effective_by_assignment[aid] = eff

        latest_provisional_effective_by_assignment: dict[uuid.UUID, datetime] = {}
        provisional_rows = db.execute(
            select(GerminationOutcomeSnapshot.batch_carrier_assignment_id, ObservationEvent.effective_time)
            .join(ObservationEvent, ObservationEvent.id == GerminationOutcomeSnapshot.observation_event_id)
            .where(
                GerminationOutcomeSnapshot.batch_carrier_assignment_id.in_(outcome_assignment_ids),
                GerminationOutcomeSnapshot.assessment_complete.is_(False),
            )
        ).all()
        for aid, eff in provisional_rows:
            if aid not in latest_provisional_effective_by_assignment or eff > latest_provisional_effective_by_assignment[aid]:
                latest_provisional_effective_by_assignment[aid] = eff

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
        # NURSERY-OPS-002B (section F/5): CASE A (no SowingEventLine row at
        # all) vs CASE B (row exists, sown_site_count never recorded) are
        # different facts and must not share one message -- `in` tests key
        # presence, distinct from the mapped value being None.
        if c["batch_carrier_assignment_id"] not in sown_counts_by_assignment:
            raise ObservationValidationError(
                f"no sowing line found for assignment {c['batch_carrier_assignment_id']}"
            )
        sown_count = sown_counts_by_assignment[c["batch_carrier_assignment_id"]]
        if sown_count is None:
            raise ObservationValidationError(
                f"Site-based GerminationCheck requires a recorded sown_site_count for assignment "
                f"{c['batch_carrier_assignment_id']}; none is on record."
            )
        if c["inspected_site_count"] > sown_count:
            raise ObservationValidationError(
                "inspected_site_count cannot exceed the assignment's original sown_site_count"
            )

    for o in germination_outcomes:
        assignment_id = o["batch_carrier_assignment_id"]
        assignment = assignments_by_id[assignment_id]
        if assignment.batch_id != batch.id:
            raise ObservationValidationError(f"assignment {assignment_id} does not belong to this batch")

        # Section 17/P: TEMPORAL truth, not current-state truth -- a
        # historical entry must remain valid if effective_time occurred
        # while the assignment was genuinely active, even if the assignment
        # has SINCE been released. Deliberately does NOT reuse the
        # `released_effective_time is not None` current-state check used
        # above for legacy values/germination_checks (section 4: their
        # existing behavior is preserved unchanged).
        if effective_time < assignment.assigned_effective_time:
            raise InvalidObservationEffectiveTimeError(
                f"effective_time precedes assignment {assignment_id}'s assigned_effective_time"
            )
        if assignment.released_effective_time is not None and effective_time >= assignment.released_effective_time:
            raise InvalidObservationEffectiveTimeError(
                f"effective_time is at or after assignment {assignment_id}'s release; "
                "the assignment was not active at that time"
            )

        if carrier_type_codes_by_assignment.get(assignment_id) != "seed_tray":
            raise ObservationValidationError(
                f"germination outcome assignment {assignment_id} must be a seed_tray carrier"
            )

        if assignment_id not in seed_counts_by_assignment:
            raise ObservationValidationError(f"no sowing line found for assignment {assignment_id}")
        seed_count = seed_counts_by_assignment[assignment_id]
        if o["normal_seedling_count"] + o["abnormal_seedling_count"] > seed_count:
            raise ObservationValidationError(
                "normal and abnormal seedling counts cannot exceed the assignment's authoritative seed_count"
            )

        if not o["assessment_complete"]:
            latest_completed = latest_completed_effective_by_assignment.get(assignment_id)
            if latest_completed is not None and effective_time > latest_completed:
                raise ObservationValidationError(
                    f"assignment {assignment_id} already has a completed Germination outcome at or after this "
                    "effective time; a new provisional snapshot cannot be recorded after an established handoff"
                )
        else:
            # Symmetric to the provisional-side check above (section 23.E):
            # makes the invariant hold even when two concurrent commands
            # race and commit in an order that disagrees with their own
            # effective_time values.
            latest_provisional = latest_provisional_effective_by_assignment.get(assignment_id)
            if latest_provisional is not None and latest_provisional > effective_time:
                raise ObservationValidationError(
                    f"assignment {assignment_id} already has a provisional Germination outcome with a later "
                    "effective time; record a new provisional correction or use a later effective time for this "
                    "completed outcome"
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
        for o in germination_outcomes:
            db.add(
                GerminationOutcomeSnapshot(
                    id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, observation_event_id=event.id,
                    batch_carrier_assignment_id=o["batch_carrier_assignment_id"],
                    normal_seedling_count=o["normal_seedling_count"],
                    abnormal_seedling_count=o["abnormal_seedling_count"],
                    assessment_complete=o["assessment_complete"], note=o.get("note"),
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
                "germination_outcome_count": len(germination_outcomes),
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
