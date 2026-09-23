"""PILOT-AGRO-001: Grower Inspection recording. An ACTUAL FARM EVENT --
never proof that a protocol requirement was followed, only a record of
what a grower actually observed. Reuses (never duplicates) the existing
Observation architecture (CMP-010) for any structured values recorded in
the same command, and never reduces `crop_batches` living inventory
(ISSUE != LOSS; ABNORMAL/WEAK != LOSS) -- `inspected_count`/`affected_
count` are descriptive fields only."""

import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.crop_batch import CropBatch
from app.models.grower_inspection import GrowerInspection
from app.models.inspection_finding import InspectionFinding
from app.models.occupancy import Occupancy
from app.services import growing_protocol_service, observation_service
from app.services.audit import append_audit_event
from app.services.errors import (
    BatchCarrierAssignmentNotFoundError,
    CropBatchClosedError,
    CropBatchNotFoundError,
    FarmNotFoundError,
    GrowerInspectionCommandReusedWithDifferentPayloadError,
    GrowerInspectionNotFoundError,
    GrowerInspectionValidationError,
)
from app.services import farm_service


def _require_active_farm(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID):
    farm = farm_service.get_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    if farm.status != "active":
        raise FarmNotFoundError(str(farm_id))
    return farm


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _fingerprint(*parts: object) -> str:
    return hashlib.sha256("|".join("" if p is None else str(p) for p in parts).encode("utf-8")).hexdigest()


def _observation_value_repr(v: dict) -> tuple:
    return (
        str(v["observation_definition_id"]), str(v.get("batch_carrier_assignment_id") or ""),
        v.get("value_integer"), str(v.get("value_decimal")) if v.get("value_decimal") is not None else None,
        v.get("value_boolean"), v.get("value_text"), v.get("note"),
    )


def _resolve_current_location_id(db: Session, *, carrier_id: uuid.UUID) -> uuid.UUID | None:
    """Point-in-time snapshot only -- captured once at record time and
    never re-derived later (section 8/19: Inspection preserves placement/
    location even if the Carrier is later moved)."""
    return db.execute(
        select(Occupancy.target_location_id).where(
            Occupancy.occupant_carrier_id == carrier_id, Occupancy.end_time.is_(None)
        )
    ).scalar_one_or_none()


def _find_by_command(db: Session, *, tenant_id: uuid.UUID, client_command_id: uuid.UUID) -> GrowerInspection | None:
    return db.execute(
        select(GrowerInspection).where(
            GrowerInspection.tenant_id == tenant_id, GrowerInspection.client_command_id == client_command_id
        )
    ).scalar_one_or_none()


def record_inspection(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_command_id: uuid.UUID,
    batch_id: uuid.UUID,
    batch_carrier_assignment_id: uuid.UUID | None,
    effective_time: datetime | None,
    inspected_count: int | None,
    overall_assessment: str,
    notes: str | None,
    findings: list[dict],
    observation_values: list[dict],
) -> GrowerInspection:
    fingerprint = _fingerprint(
        tenant_id, farm_id, batch_id, batch_carrier_assignment_id,
        effective_time.astimezone(timezone.utc).isoformat() if effective_time else "now",
        inspected_count, overall_assessment, notes,
        sorted(
            (f["category"], f["severity"], f.get("affected_count"), f.get("notes"), f.get("suspected_cause"))
            for f in findings
        ),
        sorted(_observation_value_repr(v) for v in observation_values),
    )

    existing = _find_by_command(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise GrowerInspectionCommandReusedWithDifferentPayloadError(str(client_command_id))

    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    batch = db.execute(
        select(CropBatch)
        .where(CropBatch.id == batch_id, CropBatch.tenant_id == tenant_id, CropBatch.farm_id == farm_id)
        .with_for_update()
    ).scalar_one_or_none()
    if batch is None:
        raise CropBatchNotFoundError(str(batch_id))

    existing = _find_by_command(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise GrowerInspectionCommandReusedWithDifferentPayloadError(str(client_command_id))

    if batch.state != "active":
        raise CropBatchClosedError(str(batch_id))

    if inspected_count is not None:
        for f in findings:
            affected = f.get("affected_count")
            if affected is not None and affected > inspected_count:
                raise GrowerInspectionValidationError(
                    "a finding's affected_count cannot exceed the inspection's inspected_count"
                )

    resolved_effective_time = effective_time or datetime.now(timezone.utc)
    if resolved_effective_time > datetime.now(timezone.utc):
        raise GrowerInspectionValidationError("effective_time cannot be in the future")
    if resolved_effective_time < batch.created_effective_time:
        raise GrowerInspectionValidationError("effective_time precedes the batch's creation effective time")

    location_id = None
    if batch_carrier_assignment_id is not None:
        assignment = db.execute(
            select(BatchCarrierAssignment).where(
                BatchCarrierAssignment.id == batch_carrier_assignment_id,
                BatchCarrierAssignment.tenant_id == tenant_id, BatchCarrierAssignment.farm_id == farm_id,
            )
        ).scalar_one_or_none()
        if assignment is None:
            raise BatchCarrierAssignmentNotFoundError(str(batch_carrier_assignment_id))
        if assignment.batch_id != batch.id:
            raise GrowerInspectionValidationError(
                f"batch_carrier_assignment {batch_carrier_assignment_id} does not belong to this batch"
            )
        location_id = _resolve_current_location_id(db, carrier_id=assignment.carrier_id)

    current_assignment = growing_protocol_service.get_current_assignment(db, tenant_id=tenant_id, batch_id=batch_id)
    growing_protocol_version_id = current_assignment.growing_protocol_version_id if current_assignment else None

    # UX-OPS-001C/R1 (N05): ONE transaction for the whole command. The
    # Observation write is the non-committing, transaction-composable path,
    # so the ObservationEvent, its ObservationValues, the GrowerInspection,
    # its InspectionFindings, and both audit events
    # (`crop_batch.observation_recorded`, `grower_inspection.recorded`)
    # commit together below -- or, on ANY failure, all roll back together.
    # Previously `record_observation` committed on its own first, so a
    # later inspection failure left an orphaned ObservationEvent behind.
    try:
        observation_event_id = None
        if observation_values:
            event = observation_service.record_observation_in_transaction(
                db, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, batch_id=batch_id,
                client_command_id=client_command_id, effective_time=resolved_effective_time,
                note=notes, values=observation_values, germination_checks=[],
            )
            observation_event_id = event.id

        inspection = GrowerInspection(
            tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id,
            batch_carrier_assignment_id=batch_carrier_assignment_id, location_id=location_id,
            growing_protocol_version_id=growing_protocol_version_id, inspected_by_user_id=actor_user_id,
            effective_time=resolved_effective_time, inspected_count=inspected_count,
            overall_assessment=overall_assessment, notes=notes, observation_event_id=observation_event_id,
            client_command_id=client_command_id, request_fingerprint=fingerprint,
        )
        db.add(inspection)
        db.flush()

        for f in findings:
            db.add(
                InspectionFinding(
                    tenant_id=tenant_id, farm_id=farm_id, grower_inspection_id=inspection.id, category=f["category"],
                    severity=f["severity"], affected_count=f.get("affected_count"), notes=f.get("notes"),
                    suspected_cause=f.get("suspected_cause"),
                )
            )
        db.flush()

        append_audit_event(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="grower_inspection.recorded",
            entity_type="grower_inspection", entity_id=inspection.id,
            event_data={
                "batch_id": str(batch_id), "batch_carrier_assignment_id": str(batch_carrier_assignment_id) if batch_carrier_assignment_id else None,
                "overall_assessment": overall_assessment, "finding_count": len(findings),
                "observation_event_id": str(observation_event_id) if observation_event_id else None,
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # A concurrent submission of the SAME command committed first (its
        # Inspection and Observation share this client_command_id) -- replay
        # it if the payload matches; never a second record.
        if _constraint_name(exc) in (
            "ux_grower_inspections_tenant_client_command_id",
            "ux_observation_events_tenant_client_command_id",
        ):
            replay = _find_by_command(db, tenant_id=tenant_id, client_command_id=client_command_id)
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise GrowerInspectionCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise
    except Exception:
        db.rollback()
        raise
    db.refresh(inspection)
    return inspection


def get_inspection(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, inspection_id: uuid.UUID
) -> GrowerInspection:
    inspection = db.execute(
        select(GrowerInspection).where(
            GrowerInspection.id == inspection_id, GrowerInspection.tenant_id == tenant_id,
            GrowerInspection.farm_id == farm_id,
        )
    ).scalar_one_or_none()
    if inspection is None:
        raise GrowerInspectionNotFoundError(str(inspection_id))
    return inspection


def list_findings(db: Session, *, tenant_id: uuid.UUID, inspection_id: uuid.UUID) -> list[InspectionFinding]:
    return list(
        db.execute(
            select(InspectionFinding)
            .where(InspectionFinding.tenant_id == tenant_id, InspectionFinding.grower_inspection_id == inspection_id)
            .order_by(InspectionFinding.recorded_at)
        ).scalars()
    )


def list_inspections_for_batch(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID
) -> list[GrowerInspection]:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    return list(
        db.execute(
            select(GrowerInspection)
            .where(
                GrowerInspection.tenant_id == tenant_id, GrowerInspection.farm_id == farm_id,
                GrowerInspection.batch_id == batch_id,
            )
            .order_by(GrowerInspection.effective_time.desc())
        ).scalars()
    )
