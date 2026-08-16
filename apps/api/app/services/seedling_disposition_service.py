"""NURSERY-OPS-003B: Seedling Biological Dispositions & Current Living
Quantity.

Adds biological quantity-reducing facts AFTER `SeedlingEntry`
(NURSERY-OPS-003A). `SeedlingEntry.starting_living_seedling_count` remains
the sole, immutable starting anchor -- this module never rewrites it, never
re-reads the latest Germination snapshot as a substitute, and never infers a
starting quantity from Seeds Sown/Sown Sites/current physical Occupancy.

Two kinds of immutable, insert-only `SeedlingDispositionEvent` rows:

- REDUCTION (`quantity_delta < 0`): seedlings that stopped continuing in the
  living population (confirmed mortality, weak/diseased/pest/physically
  damaged seedlings removed from continuation, QC-rejected seedlings that
  stop progressing, destructive sampling). A descriptive observation alone
  NEVER creates one of these -- only an explicit disposition command does.
- REVERSAL (`quantity_delta > 0`): the EXACT negation of one specific,
  named prior REDUCTION (`reverses_event_id`) -- accounting correction,
  never biological resurrection. No ordinary event may ever carry a
  positive delta.

`current_living_seedling_count` is never persisted -- always
`SeedlingEntry.starting_living_seedling_count + SUM(quantity_delta)`,
chronologically validated (grouped by `effective_time`, walked forward) to
never dip below zero or exceed the frozen starting quantity at ANY point in
history, not merely in the final aggregate.

A `SeedlingDispositionCommand` is the logical operator-command header: a
RECORD command always produces exactly one REDUCTION; a CORRECT command
always produces exactly one REVERSAL and, optionally, one replacement
REDUCTION (`corrects_event_id`) -- both committed atomically, in one
transaction. This mirrors the same header-plus-variable-child-lines shape
already established by `SowingEvent`/`TransplantEvent`/the modern
Germination outcome's own `ObservationEvent` pairing -- deliberately not
built on `ObservationEvent` itself (matching `SeedlingEntry`'s own
precedent of a dedicated, narrow typed header).

MVP safeguard (frozen product decision, section 0.E): a NEW disposition or
correction command is permitted only while the source
`BatchCarrierAssignment` is still currently active/unreleased -- today's
`transplant_service` does not yet freeze its own authoritative Seedling
input quantity, so post-release Seedling history must not be allowed to
change after downstream consumption may already exist. Exact replay of an
already-successful command remains valid regardless (checked before this
safeguard, exactly like every other command in this codebase)."""

import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.seedling_source_checkpoint import SeedlingSourceCheckpoint
from app.models.crop_batch import CropBatch
from app.models.seedling_disposition_command import SeedlingDispositionCommand
from app.models.seedling_disposition_event import SeedlingDispositionEvent
from app.models.seedling_disposition_reason import SeedlingDispositionReason
from app.models.seedling_entry import SeedlingEntry
from app.schemas.seedling_disposition import (
    SeedlingBiologicalTrayRead,
    SeedlingDispositionCorrectResult,
    SeedlingDispositionEventRead,
    SeedlingDispositionHistoryRead,
    SeedlingDispositionReasonRead,
    SeedlingDispositionRecordResult,
)
from app.services import farm_service
from app.services.audit import append_audit_event
from app.services.errors import (
    BatchCarrierAssignmentNotFoundError,
    FarmNotFoundError,
    InvalidSeedlingDispositionEffectiveTimeError,
    InvalidSeedlingDispositionReasonError,
    NoSeedlingEntryError,
    SeedlingDispositionAlreadyCorrectedError,
    SeedlingDispositionAssignmentReleasedError,
    SeedlingDispositionBalanceError,
    SeedlingDispositionCommandReusedWithDifferentPayloadError,
    SeedlingDispositionEventNotFoundError,
    SeedlingDispositionNotReductionError,
    SeedlingDispositionPredatesCheckpointError,
    SeedlingDispositionValidationError,
)

OTHER_REASON_CODE = "OTHER"

_CHRONOLOGICAL_BALANCE_MARKER = "CMP-DOMAIN-SEEDLING-003B chronological balance violated"


def _require_active_farm(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> None:
    farm = farm_service.get_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    if farm.status != "active":
        raise FarmNotFoundError(str(farm_id))


def _blank(note: str | None) -> bool:
    return note is None or not note.strip()


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _is_balance_violation_error(exc: IntegrityError) -> bool:
    """DOMAIN-SEEDLING-003B: the DB-layer chronological-balance backstop
    (`enforce_seedling_disposition_event_insert_integrity`) raises with
    SQLSTATE 23514 (check_violation) so it surfaces as `IntegrityError` --
    mirrors `movement_service._is_capacity_exceeded_error`'s own identical
    marker-matching pattern exactly. In the normal application path this
    branch is a genuine, reachable concurrency backstop (unlike the OTHER
    validations this trigger also performs, which stay unreachable via the
    service and use a plain, uncaught RAISE EXCEPTION -- defense-in-depth
    only, proven via direct-SQL tests)."""
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    message = getattr(diag, "message_primary", None) or str(orig or exc)
    return _CHRONOLOGICAL_BALANCE_MARKER in message


def _compute_record_fingerprint(
    *, tenant_id, farm_id, actor_user_id, batch_carrier_assignment_id, quantity, reason_code,
    effective_time: datetime, note: str | None,
) -> str:
    parts = [
        "RECORD", str(tenant_id), str(farm_id), str(actor_user_id) if actor_user_id else "",
        str(batch_carrier_assignment_id), str(quantity), reason_code,
        effective_time.astimezone(timezone.utc).isoformat(), note or "",
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _compute_correct_fingerprint(
    *, tenant_id, farm_id, actor_user_id, target_event_id, corrected: dict | None,
) -> str:
    if corrected is None:
        corrected_parts = ["void"]
    else:
        corrected_parts = [
            "replace", str(corrected["quantity"]), corrected["reason_code"],
            corrected["effective_time"].astimezone(timezone.utc).isoformat(), corrected.get("note") or "",
        ]
    parts = [
        "CORRECT", str(tenant_id), str(farm_id), str(actor_user_id) if actor_user_id else "",
        str(target_event_id), *corrected_parts,
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _find_existing_command(db: Session, *, tenant_id: uuid.UUID, client_command_id: uuid.UUID) -> SeedlingDispositionCommand | None:
    return db.execute(
        select(SeedlingDispositionCommand).where(
            SeedlingDispositionCommand.tenant_id == tenant_id,
            SeedlingDispositionCommand.client_command_id == client_command_id,
        )
    ).scalar_one_or_none()


def _latest_checkpoint_anchor(
    db: Session, *, seedling_entry_id: uuid.UUID
) -> tuple[int, datetime] | tuple[None, None]:
    """NURSERY-OPS-004A: `(remainder_after, effective_time)` of the latest
    `SeedlingSourceCheckpoint` for this Tray, or `(None, None)` if no
    transplant has ever consumed it. Ties broken by `effective_time` DESC,
    then `recorded_at` DESC, then `id` DESC -- presentation-only tie-break,
    matching every other chronological read in this module; checkpoint
    `effective_time` is itself DB-enforced strictly monotonic (section 22),
    so a genuine tie can never actually occur here."""
    row = db.execute(
        select(SeedlingSourceCheckpoint.remainder_after, SeedlingSourceCheckpoint.effective_time)
        .where(SeedlingSourceCheckpoint.seedling_entry_id == seedling_entry_id)
        .order_by(
            SeedlingSourceCheckpoint.effective_time.desc(),
            SeedlingSourceCheckpoint.recorded_at.desc(),
            SeedlingSourceCheckpoint.id.desc(),
        )
        .limit(1)
    ).first()
    if row is None:
        return None, None
    return row[0], row[1]


def _resolve_anchor(
    db: Session, *, seedling_entry_id: uuid.UUID, starting: int
) -> tuple[int, datetime | None]:
    """`(anchor_value, anchor_time)` -- the latest checkpoint's own
    `remainder_after`/`effective_time` if one exists, otherwise `(starting,
    None)`. `anchor_time=None` (no checkpoint) deliberately does NOT fall
    back to `SeedlingEntry.effective_time` here -- that floor is already,
    separately, enforced by `record_disposition`/`correct_disposition`
    themselves (section 58.A: "no checkpoint: 003B behavior unchanged")."""
    remainder, checkpoint_time = _latest_checkpoint_anchor(db, seedling_entry_id=seedling_entry_id)
    if remainder is not None:
        return remainder, checkpoint_time
    return starting, None


def get_source_availability_anchor(
    db: Session, *, seedling_entry: SeedlingEntry
) -> tuple[int, datetime, bool]:
    """Public: `(anchor_value, anchor_time, has_checkpoint)` for a Tray's
    currently-open biological balance window -- the latest
    `SeedlingSourceCheckpoint`'s `remainder_after`/`effective_time` (with
    `has_checkpoint=True`), or the frozen `SeedlingEntry`'s own starting
    quantity/effective_time (with `has_checkpoint=False`) if no transplant
    has consumed it yet. Reused by `transplant_service` to derive
    `source_available_before` AND to select the correct temporal-floor
    branch -- strictly-greater-than once a checkpoint has closed a window,
    at-or-after when the SeedlingEntry itself is still the anchor
    (NURSERY-OPS-004A section 5/6/7/22/23) -- the one place both modules
    agree on what "the current anchor" means."""
    remainder, checkpoint_time = _latest_checkpoint_anchor(db, seedling_entry_id=seedling_entry.id)
    if remainder is not None:
        return remainder, checkpoint_time, True
    return seedling_entry.starting_living_seedling_count, seedling_entry.effective_time, False


def get_source_available(
    db: Session, *, seedling_entry: SeedlingEntry, as_of: datetime
) -> int:
    """Public: the authoritative, server-derived source availability for
    this Tray as of `as_of` -- `anchor_value + SUM(disposition deltas with
    anchor_time < effective_time <= as_of)`. Never caller-supplied, never
    bounded by `sown_site_count`/`seed_count` (NURSERY-OPS-004A section 5/6/7)."""
    anchor_value, anchor_time, _has_checkpoint = get_source_availability_anchor(db, seedling_entry=seedling_entry)
    delta_sum = db.execute(
        select(func.coalesce(func.sum(SeedlingDispositionEvent.quantity_delta), 0)).where(
            SeedlingDispositionEvent.seedling_entry_id == seedling_entry.id,
            SeedlingDispositionEvent.effective_time > anchor_time,
            SeedlingDispositionEvent.effective_time <= as_of,
        )
    ).scalar_one()
    return anchor_value + delta_sum


def _validate_chronological_balance(
    db: Session, *, seedling_entry_id: uuid.UUID, starting: int, new_effective_time: datetime, new_delta: int,
    exclude_event_id: uuid.UUID | None = None,
) -> None:
    """Section 24/26/82, extended by NURSERY-OPS-004A section 7/8/24/41:
    resolves the currently-open balance window's anchor (the latest
    checkpoint's `remainder_after`, or `starting` if none exists yet),
    rejects a new event at or before that anchor's own `effective_time`
    (the checkpoint temporal floor -- a checkpoint has already frozen
    everything through its own time), then groups ALL deltas strictly
    AFTER that anchor time (existing rows, minus `exclude_event_id` if
    given, plus the pending new one) by `effective_time`, walks the groups
    in chronological order, and proves the running balance never dips
    below zero or exceeds the anchor value at any point -- not merely in
    the final aggregate."""
    anchor_value, anchor_time = _resolve_anchor(db, seedling_entry_id=seedling_entry_id, starting=starting)

    if anchor_time is not None and new_effective_time <= anchor_time:
        raise SeedlingDispositionPredatesCheckpointError(
            f"effective_time {new_effective_time.isoformat()} is at or before the latest transplant "
            f"checkpoint's own effective_time {anchor_time.isoformat()} -- this fact has already been "
            f"consumed into an immutable transplant handoff and can no longer be changed"
        )

    query = select(
        SeedlingDispositionEvent.effective_time, SeedlingDispositionEvent.quantity_delta, SeedlingDispositionEvent.id
    ).where(SeedlingDispositionEvent.seedling_entry_id == seedling_entry_id)
    if anchor_time is not None:
        query = query.where(SeedlingDispositionEvent.effective_time > anchor_time)
    rows = db.execute(query).all()

    grouped: dict[datetime, int] = {}
    for et, delta, eid in rows:
        if exclude_event_id is not None and eid == exclude_event_id:
            continue
        grouped[et] = grouped.get(et, 0) + delta
    grouped[new_effective_time] = grouped.get(new_effective_time, 0) + new_delta

    running = anchor_value
    for et in sorted(grouped):
        running += grouped[et]
        if running < 0:
            raise SeedlingDispositionBalanceError(
                f"recording this event would drive the chronological Seedling living-quantity balance "
                f"below zero as of {et.isoformat()}"
            )
        if running > anchor_value:
            raise SeedlingDispositionBalanceError(
                f"recording this event would drive the chronological Seedling living-quantity balance "
                f"above the current open balance window's own opening quantity as of {et.isoformat()}"
            )


def _current_balance(db: Session, *, seedling_entry_id: uuid.UUID, starting: int) -> int:
    """`current_living_seedling_count` -- UNCHANGED NURSERY-OPS-003B
    meaning, deliberately checkpoint-unaware (NURSERY-OPS-004A section 27):
    all living plants historically associated with this Tray's entire
    disposition history, net of every disposition ever recorded against
    it. This is NOT "how many plants remain available to transplant" --
    see `get_source_available` for that question."""
    total = db.execute(
        select(SeedlingDispositionEvent.quantity_delta).where(
            SeedlingDispositionEvent.seedling_entry_id == seedling_entry_id
        )
    ).scalars().all()
    return starting + sum(total)


# --- RECORD ------------------------------------------------------------------------


def record_disposition(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_command_id: uuid.UUID,
    batch_carrier_assignment_id: uuid.UUID,
    quantity: int,
    reason_code: str,
    effective_time: datetime,
    note: str | None,
) -> SeedlingDispositionCommand:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    fingerprint = _compute_record_fingerprint(
        tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id,
        batch_carrier_assignment_id=batch_carrier_assignment_id, quantity=quantity, reason_code=reason_code,
        effective_time=effective_time, note=note,
    )

    # Section 38: exact replay resolves here, before ANY lock, before the
    # currently-active-assignment safeguard, before balance recomputation.
    existing = _find_existing_command(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise SeedlingDispositionCommandReusedWithDifferentPayloadError(str(client_command_id))

    if effective_time > datetime.now(timezone.utc):
        raise InvalidSeedlingDispositionEffectiveTimeError("effective_time cannot be in the future")
    if reason_code == OTHER_REASON_CODE and _blank(note):
        raise SeedlingDispositionValidationError("OTHER requires a non-blank note")

    assignment_batch_id = db.execute(
        select(BatchCarrierAssignment.batch_id).where(
            BatchCarrierAssignment.id == batch_carrier_assignment_id,
            BatchCarrierAssignment.tenant_id == tenant_id,
            BatchCarrierAssignment.farm_id == farm_id,
        )
    ).scalar_one_or_none()
    if assignment_batch_id is None:
        raise BatchCarrierAssignmentNotFoundError(str(batch_carrier_assignment_id))

    # Section 34: lock the owning CropBatch FIRST -- the same lock target
    # and order established by seedling_entry_service (which itself matches
    # observation_service.record_observation), avoiding the exact deadlock
    # class fixed there.
    db.execute(select(CropBatch.id).where(CropBatch.id == assignment_batch_id).with_for_update()).scalar_one()

    existing = _find_existing_command(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise SeedlingDispositionCommandReusedWithDifferentPayloadError(str(client_command_id))

    entry = db.execute(
        select(SeedlingEntry).where(SeedlingEntry.batch_carrier_assignment_id == batch_carrier_assignment_id)
    ).scalar_one_or_none()
    if entry is None:
        raise NoSeedlingEntryError(str(batch_carrier_assignment_id))

    assignment = db.execute(
        select(BatchCarrierAssignment).where(BatchCarrierAssignment.id == batch_carrier_assignment_id)
    ).scalar_one()
    if assignment.released_effective_time is not None:
        raise SeedlingDispositionAssignmentReleasedError(str(batch_carrier_assignment_id))

    reason_exists = db.execute(
        select(SeedlingDispositionReason.code).where(SeedlingDispositionReason.code == reason_code)
    ).scalar_one_or_none()
    if reason_exists is None:
        raise InvalidSeedlingDispositionReasonError(reason_code)

    if effective_time < entry.effective_time:
        raise InvalidSeedlingDispositionEffectiveTimeError(
            "effective_time precedes the SeedlingEntry's own effective_time"
        )
    if effective_time < assignment.assigned_effective_time:
        raise InvalidSeedlingDispositionEffectiveTimeError(
            "effective_time precedes the assignment's assigned_effective_time"
        )

    _validate_chronological_balance(
        db, seedling_entry_id=entry.id, starting=entry.starting_living_seedling_count,
        new_effective_time=effective_time, new_delta=-quantity,
    )

    command = SeedlingDispositionCommand(
        id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, batch_id=entry.batch_id,
        seedling_entry_id=entry.id, operation_kind="RECORD", target_event_id=None,
        actor_user_id=actor_user_id, client_command_id=client_command_id, request_fingerprint=fingerprint,
    )
    db.add(command)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_seedling_disposition_commands_tenant_client_command_id":
            replay = _find_existing_command(db, tenant_id=tenant_id, client_command_id=client_command_id)
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise SeedlingDispositionCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    event = SeedlingDispositionEvent(
        id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, command_id=command.id,
        seedling_entry_id=entry.id, event_kind="REDUCTION", reason_code=reason_code,
        quantity_delta=-quantity, effective_time=effective_time, note=note,
        reverses_event_id=None, corrects_event_id=None,
    )
    db.add(event)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _is_balance_violation_error(exc):
            raise SeedlingDispositionBalanceError(
                "recording this event would violate the chronological Seedling living-quantity balance"
            ) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="crop_batch.seedling_disposition_recorded",
        entity_type="seedling_disposition_event", entity_id=event.id,
        event_data={
            "command_id": str(command.id), "client_command_id": str(client_command_id),
            "seedling_entry_id": str(entry.id), "batch_carrier_assignment_id": str(batch_carrier_assignment_id),
            "reason_code": reason_code, "quantity": quantity, "effective_time": effective_time.isoformat(),
        },
    )
    db.commit()
    db.refresh(command)
    return command


# --- CORRECT (void or replace) ------------------------------------------------------


def correct_disposition(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_command_id: uuid.UUID,
    target_event_id: uuid.UUID,
    corrected: dict | None,
) -> SeedlingDispositionCommand:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    fingerprint = _compute_correct_fingerprint(
        tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id,
        target_event_id=target_event_id, corrected=corrected,
    )

    existing = _find_existing_command(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise SeedlingDispositionCommandReusedWithDifferentPayloadError(str(client_command_id))

    if corrected is not None:
        if corrected["effective_time"] > datetime.now(timezone.utc):
            raise InvalidSeedlingDispositionEffectiveTimeError("effective_time cannot be in the future")
        if corrected["reason_code"] == OTHER_REASON_CODE and _blank(corrected.get("note")):
            raise SeedlingDispositionValidationError("OTHER requires a non-blank note")

    target_probe = db.execute(
        select(SeedlingDispositionEvent.seedling_entry_id).where(
            SeedlingDispositionEvent.id == target_event_id,
            SeedlingDispositionEvent.tenant_id == tenant_id,
            SeedlingDispositionEvent.farm_id == farm_id,
        )
    ).scalar_one_or_none()
    if target_probe is None:
        raise SeedlingDispositionEventNotFoundError(str(target_event_id))

    entry = db.get(SeedlingEntry, target_probe)

    # Section 34: CropBatch first, same discipline as RECORD.
    db.execute(select(CropBatch.id).where(CropBatch.id == entry.batch_id).with_for_update()).scalar_one()

    existing = _find_existing_command(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise SeedlingDispositionCommandReusedWithDifferentPayloadError(str(client_command_id))

    target = db.execute(
        select(SeedlingDispositionEvent).where(SeedlingDispositionEvent.id == target_event_id)
    ).scalar_one()
    if target.event_kind != "REDUCTION":
        raise SeedlingDispositionNotReductionError(str(target_event_id))
    already_corrected = db.execute(
        select(SeedlingDispositionEvent.id).where(SeedlingDispositionEvent.reverses_event_id == target.id)
    ).scalar_one_or_none()
    if already_corrected is not None:
        raise SeedlingDispositionAlreadyCorrectedError(str(target_event_id))

    # NURSERY-OPS-004A section 6/25: a target already consumed into a
    # transplant checkpoint may never be newly corrected -- a REVERSAL
    # sharing the target's own effective_time would retroactively rewrite
    # a quantity a downstream, immutable transplant handoff already relied
    # on. Deliberately checked and raised BEFORE the release check below --
    # this is a distinct reason (history-frozen), not "assignment released"
    # (the assignment may still be fully active with remainder > 0).
    _, checkpoint_time = _latest_checkpoint_anchor(db, seedling_entry_id=entry.id)
    if checkpoint_time is not None and target.effective_time <= checkpoint_time:
        raise SeedlingDispositionPredatesCheckpointError(str(target_event_id))

    assignment = db.execute(
        select(BatchCarrierAssignment).where(BatchCarrierAssignment.id == entry.batch_carrier_assignment_id)
    ).scalar_one()
    if assignment.released_effective_time is not None:
        raise SeedlingDispositionAssignmentReleasedError(str(entry.batch_carrier_assignment_id))

    if corrected is not None:
        reason_exists = db.execute(
            select(SeedlingDispositionReason.code).where(SeedlingDispositionReason.code == corrected["reason_code"])
        ).scalar_one_or_none()
        if reason_exists is None:
            raise InvalidSeedlingDispositionReasonError(corrected["reason_code"])
        if corrected["effective_time"] < entry.effective_time:
            raise InvalidSeedlingDispositionEffectiveTimeError(
                "effective_time precedes the SeedlingEntry's own effective_time"
            )
        if corrected["effective_time"] < assignment.assigned_effective_time:
            raise InvalidSeedlingDispositionEffectiveTimeError(
                "effective_time precedes the assignment's assigned_effective_time"
            )
        # Section 19/23: simulate the target's cancellation (the REVERSAL
        # exactly negates it at its own effective_time) by excluding the
        # target's own contribution, then check the replacement's delta --
        # the reversal insert itself needs no separate check (mathematically
        # safe by construction: same effective_time as target, exact
        # negation -- see module-level reasoning in the service tests).
        _validate_chronological_balance(
            db, seedling_entry_id=entry.id, starting=entry.starting_living_seedling_count,
            new_effective_time=corrected["effective_time"], new_delta=-corrected["quantity"],
            exclude_event_id=target.id,
        )

    command = SeedlingDispositionCommand(
        id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, batch_id=entry.batch_id,
        seedling_entry_id=entry.id, operation_kind="CORRECT", target_event_id=target.id,
        actor_user_id=actor_user_id, client_command_id=client_command_id, request_fingerprint=fingerprint,
    )
    db.add(command)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_seedling_disposition_commands_tenant_client_command_id":
            replay = _find_existing_command(db, tenant_id=tenant_id, client_command_id=client_command_id)
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise SeedlingDispositionCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    reversal = SeedlingDispositionEvent(
        id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, command_id=command.id,
        seedling_entry_id=entry.id, event_kind="REVERSAL", reason_code=target.reason_code,
        quantity_delta=-target.quantity_delta, effective_time=target.effective_time, note=None,
        reverses_event_id=target.id, corrects_event_id=None,
    )
    db.add(reversal)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_seedling_disposition_events_reverses_once":
            raise SeedlingDispositionAlreadyCorrectedError(str(target_event_id)) from exc
        raise

    replacement = None
    if corrected is not None:
        replacement = SeedlingDispositionEvent(
            id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, command_id=command.id,
            seedling_entry_id=entry.id, event_kind="REDUCTION", reason_code=corrected["reason_code"],
            quantity_delta=-corrected["quantity"], effective_time=corrected["effective_time"],
            note=corrected.get("note"), reverses_event_id=None, corrects_event_id=target.id,
        )
        db.add(replacement)
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            if _is_balance_violation_error(exc):
                raise SeedlingDispositionBalanceError(
                    "recording this correction would violate the chronological Seedling living-quantity balance"
                ) from exc
            raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="crop_batch.seedling_disposition_corrected",
        entity_type="seedling_disposition_event", entity_id=target.id,
        event_data={
            "command_id": str(command.id), "client_command_id": str(client_command_id),
            "target_event_id": str(target.id), "reversal_event_id": str(reversal.id),
            "replacement_event_id": str(replacement.id) if replacement else None,
            "original_quantity": -target.quantity_delta, "original_reason_code": target.reason_code,
            "corrected_quantity": corrected["quantity"] if corrected else None,
            "corrected_reason_code": corrected["reason_code"] if corrected else None,
        },
    )
    db.commit()
    db.refresh(command)
    return command


# --- Command reads (compose the rich response) --------------------------------------


def _to_event_read(row) -> SeedlingDispositionEventRead:
    return SeedlingDispositionEventRead(
        id=row["id"], command_id=row["command_id"], seedling_entry_id=row["seedling_entry_id"],
        event_kind=row["event_kind"], reason_code=row["reason_code"], quantity_delta=row["quantity_delta"],
        effective_time=row["effective_time"], note=row["note"], reverses_event_id=row["reverses_event_id"],
        corrects_event_id=row["corrects_event_id"], actor_user_id=row["actor_user_id"],
        recorded_at=row["recorded_at"],
    )


_EVENT_SELECT = (
    "SELECT e.id, e.command_id, e.seedling_entry_id, e.event_kind, e.reason_code, e.quantity_delta, "
    "e.effective_time, e.note, e.reverses_event_id, e.corrects_event_id, e.recorded_at, c.actor_user_id "
    "FROM seedling_disposition_events e JOIN seedling_disposition_commands c ON c.id = e.command_id "
)


def describe_record_result(db: Session, *, command: SeedlingDispositionCommand) -> SeedlingDispositionRecordResult:
    entry = db.get(SeedlingEntry, command.seedling_entry_id)
    row = db.execute(
        text(_EVENT_SELECT + "WHERE e.command_id = :cid"), {"cid": command.id}
    ).mappings().first()
    event = _to_event_read(row)
    resulting = _current_balance(db, seedling_entry_id=entry.id, starting=entry.starting_living_seedling_count)
    previous = resulting - event.quantity_delta
    return SeedlingDispositionRecordResult(
        command_id=command.id, client_command_id=command.client_command_id, seedling_entry_id=entry.id,
        event=event, previous_living_seedling_count=previous, quantity_delta=event.quantity_delta,
        resulting_living_seedling_count=resulting,
    )


def describe_correct_result(db: Session, *, command: SeedlingDispositionCommand) -> SeedlingDispositionCorrectResult:
    entry = db.get(SeedlingEntry, command.seedling_entry_id)
    rows = db.execute(
        text(_EVENT_SELECT + "WHERE e.command_id = :cid ORDER BY e.event_kind DESC"), {"cid": command.id}
    ).mappings().all()
    by_kind = {r["event_kind"]: r for r in rows}
    reversal_row = next(r for r in rows if r["event_kind"] == "REVERSAL")
    replacement_row = next((r for r in rows if r["event_kind"] == "REDUCTION"), None)
    target_row = db.execute(
        text(_EVENT_SELECT + "WHERE e.id = :eid"), {"eid": command.target_event_id}
    ).mappings().first()

    resulting = _current_balance(db, seedling_entry_id=entry.id, starting=entry.starting_living_seedling_count)
    net_delta = reversal_row["quantity_delta"] + (replacement_row["quantity_delta"] if replacement_row else 0)
    previous = resulting - net_delta
    return SeedlingDispositionCorrectResult(
        command_id=command.id, client_command_id=command.client_command_id, seedling_entry_id=entry.id,
        target_event=_to_event_read(target_row), reversal_event=_to_event_read(reversal_row),
        replacement_event=_to_event_read(replacement_row) if replacement_row else None,
        previous_living_seedling_count=previous, resulting_living_seedling_count=resulting,
    )


# --- Reads ---------------------------------------------------------------------------


def list_seedling_disposition_reasons(db: Session) -> list[SeedlingDispositionReasonRead]:
    rows = db.execute(select(SeedlingDispositionReason).order_by(SeedlingDispositionReason.code)).scalars()
    return [SeedlingDispositionReasonRead(code=r.code, name=r.name) for r in rows]


def list_seedling_biological_trays(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID
) -> list[SeedlingBiologicalTrayRead]:
    """Section 54/57: every Tray that has a `SeedlingEntry` (active OR
    released -- section 56 wants released context visible too), with its
    frozen start and derived current balance. One query, no N+1.

    NURSERY-OPS-004A section 28: extended with the latest transplant
    checkpoint (if any) and the checkpoint-aware `current_source_available_
    count` -- `current_living_seedling_count` stays exactly as it was
    (checkpoint-unaware; see `_current_balance`'s own docstring)."""
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    rows = db.execute(
        text(
            "SELECT cb.id AS batch_id, cb.code AS batch_code, "
            "carrier.id AS tray_id, carrier.code AS tray_code, "
            "crop.common_name AS crop_common_name, variety.name AS variety_name, sl.code AS seed_lot_code, "
            "bca.id AS assignment_id, bca.released_effective_time, "
            "se.id AS seedling_entry_id, se.starting_living_seedling_count, "
            "agg.total_reduction_magnitude, agg.total_reversal_magnitude, agg.event_count, "
            "cp.id AS checkpoint_id, cp.effective_time AS checkpoint_effective_time, "
            "cp.remainder_after AS checkpoint_remainder_after, cpcount.checkpoint_count, "
            "COALESCE(cp.remainder_after, se.starting_living_seedling_count) "
            "  + COALESCE(post.delta_sum, 0) AS current_source_available_count, "
            "table_loc.id AS table_id, table_loc.code AS table_code "
            "FROM seedling_entries se "
            "JOIN batch_carrier_assignments bca ON bca.id = se.batch_carrier_assignment_id "
            "JOIN crop_batches cb ON cb.id = se.batch_id "
            "JOIN carriers carrier ON carrier.id = bca.carrier_id "
            "JOIN sowing_event_lines sel ON sel.batch_carrier_assignment_id = bca.id "
            "JOIN seed_lots sl ON sl.id = sel.seed_lot_id "
            "JOIN crops crop ON crop.id = sl.crop_id "
            "JOIN varieties variety ON variety.id = sl.variety_id "
            "LEFT JOIN LATERAL ( "
            "  SELECT "
            "    COALESCE(SUM(CASE WHEN quantity_delta < 0 THEN -quantity_delta ELSE 0 END), 0) AS total_reduction_magnitude, "
            "    COALESCE(SUM(CASE WHEN quantity_delta > 0 THEN quantity_delta ELSE 0 END), 0) AS total_reversal_magnitude, "
            "    COUNT(*) AS event_count "
            "  FROM seedling_disposition_events WHERE seedling_entry_id = se.id "
            ") agg ON true "
            "LEFT JOIN LATERAL ( "
            "  SELECT id, effective_time, remainder_after FROM seedling_source_checkpoints "
            "  WHERE seedling_entry_id = se.id "
            "  ORDER BY effective_time DESC, recorded_at DESC, id DESC LIMIT 1 "
            ") cp ON true "
            "LEFT JOIN LATERAL ( "
            "  SELECT COUNT(*) AS checkpoint_count FROM seedling_source_checkpoints WHERE seedling_entry_id = se.id "
            ") cpcount ON true "
            "LEFT JOIN LATERAL ( "
            "  SELECT COALESCE(SUM(quantity_delta), 0) AS delta_sum FROM seedling_disposition_events "
            "  WHERE seedling_entry_id = se.id AND (cp.effective_time IS NULL OR effective_time > cp.effective_time) "
            ") post ON true "
            "LEFT JOIN occupancies occ ON occ.occupant_carrier_id = carrier.id AND occ.end_time IS NULL "
            "LEFT JOIN locations table_loc ON table_loc.id = occ.target_location_id "
            "LEFT JOIN location_types table_lt ON table_lt.id = table_loc.location_type_id AND table_lt.code = 'seedling_table' "
            "WHERE se.tenant_id = :tid AND se.farm_id = :fid "
            "ORDER BY cb.code, carrier.code"
        ),
        {"tid": tenant_id, "fid": farm_id},
    ).mappings().all()

    results = []
    for r in rows:
        starting = r["starting_living_seedling_count"]
        reduction = r["total_reduction_magnitude"]
        reversal = r["total_reversal_magnitude"]
        current = starting - reduction + reversal
        source_available = r["current_source_available_count"]
        results.append(
            SeedlingBiologicalTrayRead(
                batch_id=r["batch_id"], batch_code=r["batch_code"], tray_id=r["tray_id"], tray_code=r["tray_code"],
                crop_common_name=r["crop_common_name"], variety_name=r["variety_name"], seed_lot_code=r["seed_lot_code"],
                batch_carrier_assignment_id=r["assignment_id"], seedling_entry_id=r["seedling_entry_id"],
                starting_living_seedling_count=starting, total_reduction_magnitude=reduction,
                total_reversal_magnitude=reversal, current_living_seedling_count=current,
                current_source_available_count=source_available,
                checkpoint_count=r["checkpoint_count"], latest_checkpoint_id=r["checkpoint_id"],
                latest_checkpoint_effective_time=r["checkpoint_effective_time"],
                latest_checkpoint_remainder_after=r["checkpoint_remainder_after"],
                is_depleted=(source_available == 0), event_count=r["event_count"],
                seedling_table_id=r["table_id"], seedling_table_code=r["table_code"],
                assignment_active=(r["released_effective_time"] is None),
                assignment_released_effective_time=r["released_effective_time"],
            )
        )
    return results


def get_seedling_disposition_history(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, seedling_entry_id: uuid.UUID
) -> SeedlingDispositionHistoryRead:
    entry = db.execute(
        select(SeedlingEntry).where(
            SeedlingEntry.id == seedling_entry_id, SeedlingEntry.tenant_id == tenant_id,
            SeedlingEntry.farm_id == farm_id,
        )
    ).scalar_one_or_none()
    if entry is None:
        raise NoSeedlingEntryError(str(seedling_entry_id))

    rows = db.execute(
        text(
            _EVENT_SELECT + "WHERE e.seedling_entry_id = :eid ORDER BY e.effective_time, e.recorded_at, e.id"
        ),
        {"eid": seedling_entry_id},
    ).mappings().all()
    events = [_to_event_read(r) for r in rows]
    current = _current_balance(db, seedling_entry_id=entry.id, starting=entry.starting_living_seedling_count)
    return SeedlingDispositionHistoryRead(
        seedling_entry_id=entry.id, starting_living_seedling_count=entry.starting_living_seedling_count,
        current_living_seedling_count=current, events=events,
    )
