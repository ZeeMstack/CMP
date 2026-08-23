"""TRANSPLANT-CORRECTION-001: immutable correction/void of a biological
Transplant event.

Never mutates or deletes the original (target) TransplantEvent or its
domain rows. A correction is exactly one REVERSAL (mandatory) plus,
optionally, one REPLACEMENT -- both committed atomically in this module's
single orchestrating transaction, composing `transplant_service.
_record_transplant_core` for the REPLACEMENT leg exactly as `intersalads_
transplant_service` already composes it for an ordinary placement.

Effective time is entirely server-derived (frozen product decision): both
legs land at the target's own `effective_time` (`T`) -- the caller never
supplies a correction effective time. `recorded_time`/`recorded_at` (server
defaults) remain the true "when was this correction actually entered"
facts.

Eligibility (all proven under lock, before any write):
- target.event_kind in (RECORD, REPLACEMENT) -- a REVERSAL may never
  itself be corrected;
- target has not already been corrected (reversed) once;
- the Batch is active and its CURRENT active BatchStageRun.id still equals
  the target's own `active_batch_stage_run_id` (stage CATEGORY alone is
  not sufficient -- a batch that left and re-entered an equivalent stage
  in a different run remains ineligible);
- every source line's own checkpoint is still the structural chain tip
  (no later Transplant/Disposition/other checkpoint activity on that
  source);
- every destination assignment target opened is still unreleased (no
  downstream consumption, e.g. Batch Derivation, exists yet).

An open Quality Hold does NOT block correction (frozen decision) -- no
hold-state check exists here by design, not omission.
"""

import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.batch_carrier_population_checkpoint import BatchCarrierPopulationCheckpoint
from app.models.batch_stage_run import BatchStageRun
from app.models.carrier import Carrier
from app.models.carrier_type import CarrierType
from app.models.crop_batch import CropBatch
from app.models.seedling_source_checkpoint import SeedlingSourceCheckpoint
from app.models.transplant_destination_line import TransplantDestinationLine
from app.models.transplant_event import TransplantEvent
from app.models.transplant_source_line import TransplantSourceLine
from app.services import farm_service, transplant_service, transplant_source_authority
from app.services.audit import append_audit_event
from app.services.errors import (
    CropBatchClosedError,
    CropBatchNotFoundError,
    FarmNotFoundError,
    TransplantAlreadyCorrectedError,
    TransplantCorrectionCarrierReusedError,
    TransplantCorrectionCommandReusedWithDifferentPayloadError,
    TransplantCorrectionDestinationConsumedError,
    TransplantCorrectionNotChainTipError,
    TransplantCorrectionReplayStateConflictError,
    TransplantCorrectionStageMismatchError,
    TransplantCorrectionTargetKindNotEligibleError,
    TransplantCorrectionValidationError,
    TransplantEventNotFoundError,
)

_REPLACEMENT_COMMAND_NAMESPACE = uuid.UUID("b3d7f1a4-6c9e-4f28-8a1d-5e2c9b7f4a63")

_ELIGIBLE_TARGET_KINDS = ("RECORD", "REPLACEMENT")


def _derive_replacement_client_command_id(
    outer_client_command_id: uuid.UUID, target_transplant_event_id: uuid.UUID
) -> uuid.UUID:
    """Same deterministic-UUID5 philosophy as `intersalads_transplant_
    service._derive_movement_client_command_id` -- the same (outer
    command, target event) pair always re-derives the same child
    REPLACEMENT identity, so an exact replay never creates a second
    REPLACEMENT and never collides with an ordinary caller-chosen
    client_command_id (which would have to guess a UUID5 hash of internal
    ids it has no way to construct)."""
    return uuid.uuid5(
        _REPLACEMENT_COMMAND_NAMESPACE, f"{outer_client_command_id}:{target_transplant_event_id}:replacement"
    )


def _compute_correction_fingerprint(
    *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID,
    target_transplant_event_id: uuid.UUID, reason: str, replacement: dict | None,
) -> str:
    """Deliberately excludes effective_time -- both legs are entirely
    server-derived from the target, never caller-supplied (section 5/28)."""
    if replacement is None:
        marker_parts = ["VOID"]
    else:
        sorted_sources = sorted(replacement["source_lines"], key=lambda line: str(line["source_assignment_id"]))
        sorted_destinations = sorted(
            replacement["destination_lines"], key=lambda line: str(line["destination_carrier_id"])
        )
        sorted_allocations = sorted(
            replacement["allocations"],
            key=lambda a: (str(a["source_assignment_id"]), str(a["destination_carrier_id"])),
        )
        marker_parts = ["REPLACE", replacement.get("note") or ""]
        for line in sorted_sources:
            marker_parts.extend(
                [
                    str(line["source_assignment_id"]), str(line["transplant_damage_count"]),
                    str(line["qc_rejection_count"]), str(line["sample_count"]), str(line["other_loss_count"]),
                    line.get("other_loss_note") or "", line.get("note") or "",
                ]
            )
        for line in sorted_destinations:
            marker_parts.extend(
                [str(line["destination_carrier_id"]), str(line["assigned_plant_count"]), line.get("note") or ""]
            )
        for a in sorted_allocations:
            marker_parts.extend(
                [str(a["source_assignment_id"]), str(a["destination_carrier_id"]), str(a["allocated_plant_count"])]
            )
    parts = [str(tenant_id), str(farm_id), str(actor_user_id), str(target_transplant_event_id), reason, *marker_parts]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _find_existing_reversal(db: Session, *, tenant_id: uuid.UUID, client_command_id: uuid.UUID) -> TransplantEvent | None:
    return db.execute(
        select(TransplantEvent).where(
            TransplantEvent.tenant_id == tenant_id, TransplantEvent.client_command_id == client_command_id
        )
    ).scalar_one_or_none()


def _verify_replay(db: Session, *, existing: TransplantEvent, fingerprint: str, replacement: dict | None) -> TransplantEvent:
    if existing.event_kind != "REVERSAL":
        # The outer client_command_id must own a REVERSAL row -- any other
        # kind found under this id means it was never a correction command
        # at all (a genuine client_command_id collision with an unrelated
        # ordinary Transplant command).
        raise TransplantCorrectionCommandReusedWithDifferentPayloadError(str(existing.client_command_id))
    if existing.request_fingerprint != fingerprint:
        raise TransplantCorrectionCommandReusedWithDifferentPayloadError(str(existing.client_command_id))
    replacement_client_command_id = _derive_replacement_client_command_id(
        existing.client_command_id, existing.reverses_transplant_event_id
    )
    found_replacement = db.execute(
        select(TransplantEvent.id).where(
            TransplantEvent.tenant_id == existing.tenant_id,
            TransplantEvent.client_command_id == replacement_client_command_id,
        )
    ).scalar_one_or_none()
    if replacement is not None and found_replacement is None:
        raise TransplantCorrectionReplayStateConflictError(str(existing.id))
    if replacement is None and found_replacement is not None:
        raise TransplantCorrectionReplayStateConflictError(str(existing.id))
    return existing


def correct_transplant(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    batch_id: uuid.UUID,
    target_transplant_event_id: uuid.UUID,
    client_command_id: uuid.UUID,
    reason: str,
    replacement: dict | None,
) -> TransplantEvent:
    """Returns the REVERSAL TransplantEvent (the outer command's own durable
    identity). `replacement`, when given, is the normal biological
    Transplant payload (`source_lines`, `destination_lines`, `allocations`,
    optional `note`) representing the correct facts -- a
    `source_assignment_id` matching a source this correction just
    restored is transparently remapped to the restored assignment id;
    any other id is used exactly as given (a genuinely different, correct
    source Tray)."""
    farm = farm_service.get_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    if farm.status != "active":
        raise FarmNotFoundError(str(farm_id))

    reason = reason.strip()
    if not reason:
        raise TransplantCorrectionValidationError("reason is required and must be non-empty")

    fingerprint = _compute_correction_fingerprint(
        tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id,
        target_transplant_event_id=target_transplant_event_id, reason=reason, replacement=replacement,
    )

    existing = _find_existing_reversal(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        return _verify_replay(db, existing=existing, fingerprint=fingerprint, replacement=replacement)

    batch = db.execute(
        select(CropBatch)
        .where(CropBatch.id == batch_id, CropBatch.tenant_id == tenant_id, CropBatch.farm_id == farm_id)
        .with_for_update()
    ).scalar_one_or_none()
    if batch is None:
        raise CropBatchNotFoundError(str(batch_id))

    existing = _find_existing_reversal(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        return _verify_replay(db, existing=existing, fingerprint=fingerprint, replacement=replacement)

    if batch.state != "active":
        raise CropBatchClosedError(str(batch_id))

    target = db.execute(
        select(TransplantEvent)
        .where(
            TransplantEvent.id == target_transplant_event_id, TransplantEvent.tenant_id == tenant_id,
            TransplantEvent.farm_id == farm_id, TransplantEvent.batch_id == batch.id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if target is None:
        raise TransplantEventNotFoundError(str(target_transplant_event_id))
    if target.event_kind not in _ELIGIBLE_TARGET_KINDS:
        raise TransplantCorrectionTargetKindNotEligibleError(str(target_transplant_event_id))

    already_corrected = db.execute(
        select(TransplantEvent.id).where(
            TransplantEvent.reverses_transplant_event_id == target.id, TransplantEvent.tenant_id == tenant_id
        )
    ).scalar_one_or_none()
    if already_corrected is not None:
        raise TransplantAlreadyCorrectedError(str(target_transplant_event_id))

    active_run = db.execute(
        select(BatchStageRun)
        .where(BatchStageRun.batch_id == batch.id, BatchStageRun.exited_effective_time.is_(None))
        .with_for_update()
    ).scalar_one_or_none()
    if active_run is None or active_run.id != target.active_batch_stage_run_id:
        raise TransplantCorrectionStageMismatchError(str(target_transplant_event_id))

    source_lines = list(
        db.execute(
            select(TransplantSourceLine).where(TransplantSourceLine.transplant_event_id == target.id)
        ).scalars()
    )
    destination_lines = list(
        db.execute(
            select(TransplantDestinationLine).where(TransplantDestinationLine.transplant_event_id == target.id)
        ).scalars()
    )

    # Section 21: downstream eligibility -- every source's own checkpoint
    # must still be the structural chain tip (no successor). NURSERY-OPS-
    # 005A: a source's checkpoint may instead live in the sibling
    # batch_carrier_population_checkpoints table (nursery_cultivation_
    # plate-backed sources) -- never both; whichever table actually has a
    # row for this source line is authoritative for it.
    for line in source_lines:
        seedling_checkpoint_id = db.execute(
            select(SeedlingSourceCheckpoint.id).where(SeedlingSourceCheckpoint.transplant_source_line_id == line.id)
        ).scalar_one_or_none()
        if seedling_checkpoint_id is not None:
            has_successor = db.execute(
                select(SeedlingSourceCheckpoint.id).where(
                    SeedlingSourceCheckpoint.previous_checkpoint_id == seedling_checkpoint_id
                )
            ).scalar_one_or_none()
            if has_successor is not None:
                raise TransplantCorrectionNotChainTipError(str(target_transplant_event_id))
            continue

        population_checkpoint_id = db.execute(
            select(BatchCarrierPopulationCheckpoint.id).where(
                BatchCarrierPopulationCheckpoint.transplant_source_line_id == line.id
            )
        ).scalar_one()
        has_population_successor = db.execute(
            select(BatchCarrierPopulationCheckpoint.id).where(
                BatchCarrierPopulationCheckpoint.previous_checkpoint_id == population_checkpoint_id
            )
        ).scalar_one_or_none()
        if has_population_successor is not None:
            raise TransplantCorrectionNotChainTipError(str(target_transplant_event_id))

    source_assignment_ids = sorted({line.source_batch_carrier_assignment_id for line in source_lines})
    destination_assignment_ids = sorted({line.destination_batch_carrier_assignment_id for line in destination_lines})
    all_assignment_ids = sorted(set(source_assignment_ids) | set(destination_assignment_ids))

    assignments = list(
        db.execute(
            select(BatchCarrierAssignment)
            .where(BatchCarrierAssignment.id.in_(all_assignment_ids))
            .order_by(BatchCarrierAssignment.id)
            .with_for_update()
        ).scalars()
    )
    assignments_by_id = {a.id: a for a in assignments}

    # Section 21: any destination assignment already released/consumed by
    # another biological lifecycle blocks correction.
    for did in destination_assignment_ids:
        if assignments_by_id[did].released_effective_time is not None:
            raise TransplantCorrectionDestinationConsumedError(str(target_transplant_event_id))

    carrier_ids = sorted({a.carrier_id for a in assignments})
    carriers_by_id = {
        c.id: c
        for c in db.execute(
            select(Carrier).where(Carrier.id.in_(carrier_ids)).order_by(Carrier.id).with_for_update()
        ).scalars()
    }

    # NURSERY-OPS-005A: Carrier-reuse safety, applied consistently to every
    # Transplant correction restoration path (Seed-Tray-backed and Nursery-
    # Plate-backed alike -- closes a pre-existing gap this file never had).
    # Under the Carrier lock just taken, re-read Carrier.latest_batch_
    # carrier_assignment_id for every source about to be restored (fully
    # exhausted by the target): if it no longer identifies the exact
    # assignment being restored, this Carrier has since been legitimately
    # reassigned to a later, unrelated use, and physical continuity with
    # the biology this correction would restore has been broken --
    # permanently blocked for this historical correction, even if that
    # later use has itself since been released and the Carrier is
    # currently free again (mirrors seedling_disposition_service's own
    # proven `SeedlingDispositionCarrierReusedError` check exactly).
    for line in source_lines:
        original = assignments_by_id[line.source_batch_carrier_assignment_id]
        if original.released_by_transplant_event_id == target.id:
            carrier = carriers_by_id[original.carrier_id]
            if carrier.latest_batch_carrier_assignment_id != original.id:
                raise TransplantCorrectionCarrierReusedError(str(original.carrier_id))

    carrier_type_ids = {c.carrier_type_id for c in carriers_by_id.values()}
    carrier_types_by_id = {
        ct.id: ct for ct in db.execute(select(CarrierType).where(CarrierType.id.in_(carrier_type_ids))).scalars()
    }

    effective_time = target.effective_time

    try:
        reversal = TransplantEvent(
            id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, batch_id=batch.id,
            active_batch_stage_run_id=active_run.id, effective_time=effective_time, actor_user_id=actor_user_id,
            client_command_id=client_command_id, request_fingerprint=fingerprint, note=None,
            event_kind="REVERSAL", reverses_transplant_event_id=target.id, correction_reason=reason,
        )
        db.add(reversal)
        db.flush()

        # Section 14 Case B: release exactly the destination assignment(s)
        # opened by the exact event being reversed.
        for did in destination_assignment_ids:
            a = assignments_by_id[did]
            a.released_effective_time = effective_time
            a.released_by_transplant_event_id = reversal.id
        db.flush()

        # Section 8/10/16: restore ALL source effects of the target. A
        # source fully exhausted by the target (released_by == target) gets
        # a brand-new restored assignment for the same physical Carrier; a
        # source the target never fully consumed keeps using its own,
        # still-active assignment directly -- either way the checkpoint
        # records the ACTUAL CURRENT assignment, never the historical one.
        restored_assignment_by_original: dict[uuid.UUID, uuid.UUID] = {}
        for line in source_lines:
            original = assignments_by_id[line.source_batch_carrier_assignment_id]
            if original.released_by_transplant_event_id == target.id:
                active_assignment = BatchCarrierAssignment(
                    id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, batch_id=batch.id,
                    carrier_id=original.carrier_id, batch_stage_run_id=original.batch_stage_run_id,
                    assigned_effective_time=effective_time, released_effective_time=None,
                    opening_transplant_reversal_event_id=reversal.id,
                    restored_from_batch_carrier_assignment_id=original.id, actor_user_id=actor_user_id,
                )
                db.add(active_assignment)
                db.flush()
            else:
                active_assignment = original

            # NURSERY-OPS-005A: resolve the restored assignment's own
            # biological population authority via the ONE unified
            # resolver -- dispatches seed_tray into the existing,
            # unchanged SeedlingEntry path, nursery_cultivation_plate into
            # the new BatchCarrierAssignment/BatchCarrierPopulation
            # Checkpoint path. Reaching `None` here indicates a genuine
            # invariant violation (the target's own original source line
            # already proved a resolvable authority when it was recorded),
            # not a normal caller error -- kept as the existing generic
            # defensive error for this call site.
            carrier_type_code = carrier_types_by_id[carriers_by_id[active_assignment.carrier_id].carrier_type_id].code
            authority = transplant_source_authority.resolve_source_authority(
                db, assignment_id=active_assignment.id, carrier_type_code=carrier_type_code
            )
            if authority is None:
                raise TransplantCorrectionValidationError(
                    f"source assignment {active_assignment.id} has no resolvable biological population authority"
                )

            reversal_source_line = TransplantSourceLine(
                id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, transplant_event_id=reversal.id,
                source_batch_carrier_assignment_id=active_assignment.id, source_carrier_id=active_assignment.carrier_id,
                source_plant_count=line.source_plant_count, discarded_plant_count=0,
                transplant_damage_count=0, qc_rejection_count=0, sample_count=0, other_loss_count=0,
                other_loss_note=None, note=None,
            )
            db.add(reversal_source_line)
            db.flush()

            transplant_source_authority.append_source_consumption_checkpoint(
                db, authority=authority, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch.id,
                assignment_id=active_assignment.id, transplant_source_line_id=reversal_source_line.id,
                remainder_after=line.source_plant_count, effective_time=effective_time,
            )
            db.flush()

            restored_assignment_by_original[line.source_batch_carrier_assignment_id] = active_assignment.id

        replacement_event = None
        if replacement is not None:
            replacement_client_command_id = _derive_replacement_client_command_id(client_command_id, target.id)

            def _remap(aid: uuid.UUID) -> uuid.UUID:
                return restored_assignment_by_original.get(aid, aid)

            mapped_source_lines = [
                {**sl, "source_assignment_id": _remap(sl["source_assignment_id"])}
                for sl in replacement["source_lines"]
            ]
            mapped_allocations = [
                {**a, "source_assignment_id": _remap(a["source_assignment_id"])}
                for a in replacement["allocations"]
            ]
            replacement_event, _is_new = transplant_service._record_transplant_core(
                db, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, batch_id=batch.id,
                client_command_id=replacement_client_command_id, effective_time=effective_time,
                note=replacement.get("note"), source_lines=mapped_source_lines,
                destination_lines=replacement["destination_lines"], allocations=mapped_allocations,
                emit_audit=False, corrects_transplant_event_id=target.id,
            )

        append_audit_event(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="crop_batch.transplant_corrected",
            entity_type="transplant_event", entity_id=reversal.id,
            event_data={
                "target_transplant_event_id": str(target.id),
                "reversal_transplant_event_id": str(reversal.id),
                "replacement_transplant_event_id": str(replacement_event.id) if replacement_event else None,
                "correction_reason": reason,
                "correcting_actor_user_id": str(actor_user_id),
                "recorded_at": reversal.recorded_time.isoformat(),
                "original_effective_time": effective_time.isoformat(),
                "client_command_id": str(client_command_id),
            },
        )
    except IntegrityError as exc:
        db.rollback()
        replay = _find_existing_reversal(db, tenant_id=tenant_id, client_command_id=client_command_id)
        if replay is not None:
            return _verify_replay(db, existing=replay, fingerprint=fingerprint, replacement=replacement)
        raise TransplantCorrectionValidationError(str(exc)) from exc

    db.commit()
    db.refresh(reversal)
    return reversal


def resolve_authoritative_transplant(db: Session, *, event_id: uuid.UUID) -> uuid.UUID | None:
    """TRANSPLANT-CORRECTION-001 section 8/31: bounded iterative traversal
    with visited-id cycle protection (defensive only -- structurally
    unreachable given `reverses_transplant_event_id`/`corrects_transplant_
    event_id` always reference an already-existing, earlier-inserted row).
    Untouched RECORD/REPLACEMENT -> itself; voided (REVERSAL, no
    REPLACEMENT) -> None; corrected -> its REPLACEMENT, recursively resolved
    onward if that REPLACEMENT was itself later corrected."""
    visited: set[uuid.UUID] = set()
    current = event_id
    while True:
        if current in visited:
            raise TransplantCorrectionValidationError(f"correction chain cycle detected at {current}")
        visited.add(current)
        has_reversal = db.execute(
            select(TransplantEvent.id).where(TransplantEvent.reverses_transplant_event_id == current)
        ).scalar_one_or_none()
        if has_reversal is None:
            return current
        replacement_id = db.execute(
            select(TransplantEvent.id).where(TransplantEvent.corrects_transplant_event_id == current)
        ).scalar_one_or_none()
        if replacement_id is None:
            return None
        current = replacement_id


def describe_correction(db: Session, *, tenant_id: uuid.UUID, reversal_event_id: uuid.UUID) -> dict:
    reversal = db.execute(
        select(TransplantEvent).where(
            TransplantEvent.id == reversal_event_id, TransplantEvent.tenant_id == tenant_id,
            TransplantEvent.event_kind == "REVERSAL",
        )
    ).scalar_one_or_none()
    if reversal is None:
        raise TransplantEventNotFoundError(str(reversal_event_id))
    target = db.get(TransplantEvent, reversal.reverses_transplant_event_id)
    replacement = db.execute(
        select(TransplantEvent).where(TransplantEvent.corrects_transplant_event_id == target.id)
    ).scalar_one_or_none()
    status = "corrected" if replacement is not None else "voided"
    return {
        "target_event_id": target.id,
        "status": status,
        "reversal_event_id": reversal.id,
        "replacement_event_id": replacement.id if replacement is not None else None,
        "reason": reversal.correction_reason,
    }
