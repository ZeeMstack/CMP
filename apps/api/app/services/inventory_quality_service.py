"""STORE-INV-002A.2: quality disposition commands and the usable-existence
read model (`docs/domain/STORE_INVENTORY_MODEL.md` §11), built on top of
`.1`'s already-merged foundation plus the CTO-closure-pass additive
migration `abcdb6f371f9` (`InventoryQualityCommand`, `QualityDispositionEvent.
command_id`).

Command-level idempotency (CTO closure pass, replacing the original
cohort-lock-only design that could not prevent a reused `client_command_id`
from being replayed concurrently against two DIFFERENT cohorts): every
Quality command writes exactly one `InventoryQualityCommand` header row,
unique on `(tenant_id, client_command_id)`, BEFORE any `QualityDispositionEvent`
row. `RECORD`/`PARTIAL` commands own exactly one child event;
`CORRECT`/`PARTIAL_CORRECT` commands own one REVERSAL/child event plus an
optional replacement -- all resolved via `QualityDispositionEvent.command_id`,
never via the (now unused, for `.2`-issued rows) `client_command_id`/
`request_fingerprint` columns still nullable-present on that table.

Current derived quality state for a cohort is never a stored column: it is
always resolved as the latest (by `effective_time`, `recorded_time`, `id`),
non-`REVERSAL` event that has not itself been the target of a `REVERSAL` --
exactly the same "current event" definition the `.1` DB trigger
(`enforce_quality_disposition_event_insert_integrity`) already enforces for
what a correction may legally target. A cohort with no such event at all is
implicit `RELEASED` (`qc_release_required = false`, nothing has happened to
it yet).

Every writer locks the source `InventoryQuantityCohort` row (`FOR UPDATE`,
reusing `.1`'s own `_lock_cohort`) before resolving current state or
inserting."""

import hashlib
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.goods_receipt import GoodsReceipt
from app.models.goods_receipt_line import GoodsReceiptLine
from app.models.inventory_existence_ledger_entry import InventoryExistenceLedgerEntry
from app.models.inventory_item import InventoryItem
from app.models.inventory_lot import InventoryLot
from app.models.inventory_quality_command import InventoryQualityCommand
from app.models.inventory_quantity_cohort import InventoryQuantityCohort
from app.models.quality_disposition_event import QualityDispositionEvent
from app.services import inventory_cohort_accounting_service
from app.services.audit import append_audit_event
from app.services.errors import (
    IneligibleStorageBinError,
    InvalidQualityDispositionTransitionError,
    InvalidQualityEffectiveTimeError,
    InventoryQuantityCohortSplitAllocationExceedsBalanceError,
    QualityCorrectionCommandReusedWithDifferentPayloadError,
    QualityCorrectionTargetNotCurrentError,
    QualityDispositionCommandReusedWithDifferentPayloadError,
    QualityDispositionEventNotFoundError,
    QualityDispositionNoCurrentHumanDecisionError,
    QualityPartialCorrectionCommandReusedWithDifferentPayloadError,
    QualityPartialDispositionCommandReusedWithDifferentPayloadError,
    QualitySegregationOfDutiesError,
)
from app.services.inventory_existence_ledger_service import (
    _lock_cohort,
    _split_cohort_core,
    get_cohort_bin_balance,
)
from app.services.inventory_storage_service import _lock_bin, split_custody_core

# The four ordinary human-decision event kinds a caller may request as a
# disposition or a correction's replacement/corrected outcome.
# `RECEIVED_QUARANTINED` is only ever written automatically by `.1`'s
# receipt transaction; `REVERSAL` is only ever written by
# `correct_quality_disposition` itself.
VALID_DISPOSITIONS = ("RELEASED", "HELD", "REJECTED", "HOLD_RELEASED")

# The two current-state values a resulting disposition is "usable" under
# (docs/domain/STORE_INVENTORY_MODEL.md §11) -- implicit RELEASED (no
# events) and explicit RELEASED both resolve to the string "RELEASED" here.
USABLE_STATES = frozenset({"RELEASED", "HOLD_RELEASED"})

# The frozen state machine (STORE_INVENTORY_MODEL.md §11). Keyed by the
# CURRENT derived state; value is the set of legal ORDINARY next
# dispositions. `PARTIAL_CORRECT` deliberately bypasses this table -- it is
# a compensating correction of a misclassification, never an ordinary
# transition (docs/build-plans -- CTO closure pass §3).
_TRANSITIONS: dict[str, frozenset[str]] = {
    "RECEIVED_QUARANTINED": frozenset({"RELEASED", "HELD", "REJECTED"}),
    "RELEASED": frozenset({"HELD", "REJECTED"}),
    "HELD": frozenset({"HOLD_RELEASED", "REJECTED"}),
    "HOLD_RELEASED": frozenset({"HELD", "REJECTED"}),
    "REJECTED": frozenset(),
}


def _legal_next_dispositions(current_state: str) -> frozenset[str]:
    return _TRANSITIONS.get(current_state, frozenset())


# --- Chronology integrity (PILOT-BLOCKER-005 F07) ---------------------------

# The Quality UI itself never needs any allowance here: its effective_time
# field defaults to the operator's local clock truncated DOWN to the minute
# at the moment the action panel opens (never recomputed at submit), so a
# submission built from the untouched default is always <= that operator's
# own "now". The only real source of an apparent future timestamp is
# ordinary, unavoidable clock disagreement between an operator's device and
# this server (ONE relevant device may not be NTP-synced) -- this tiny,
# fixed allowance absorbs exactly that and nothing more. It is deliberately
# far too small to serve as a "schedule this for later" mechanism: there is
# no scheduled-future-disposition feature, an operator cannot use this
# window to pre-arrange a Hold/Release, and any attempt to backdate/postdate
# beyond it is rejected outright.
_EFFECTIVE_TIME_FUTURE_TOLERANCE = timedelta(seconds=30)

# Monkeypatchable seam for deterministic boundary testing only (PILOT-BLOCKER-008
# A1): production behavior is untouched (default is real wall-clock time). No
# freezegun/fake-clock dependency exists in this repo; a test pins this to a
# fixed reference so both the constructed `effective_time` and the validator's
# own comparison "now" derive from the same fixed value, giving an exact
# `<=30s accepted / >30s rejected` proof with no dependency on real elapsed
# execution time.
_now_provider = datetime.now


def _require_tz_aware_effective_time(effective_time: datetime) -> None:
    """Every Quality effective timestamp must be timezone-aware -- a naive
    datetime is inherently ambiguous chronology (docs/domain/
    STORE_INVENTORY_MODEL.md §11 / PILOT-BLOCKER-005 F07 rule 1). Applies to
    ordinary dispositions AND corrections alike."""
    if effective_time.tzinfo is None or effective_time.utcoffset() is None:
        raise InvalidQualityEffectiveTimeError("effective_time must be timezone-aware")


def _validate_ordinary_effective_time(
    *, effective_time: datetime, current_event: QualityDispositionEvent | None,
) -> None:
    """ORDINARY (non-correction) chronology rules only (F07 rules 2-3):
    reject a materially future effective time, and reject one that precedes
    the cohort's currently effective Quality decision -- an equal
    `effective_time` remains legal (rule 4); existing `(effective_time,
    recorded_time, id)` ordering already resolves the later command as
    current. Corrections are explicit target-based operations and run
    through `_validate_correction_effective_time` instead (rule 5)."""
    _require_tz_aware_effective_time(effective_time)
    now = _now_provider(effective_time.tzinfo)
    if effective_time > now + _EFFECTIVE_TIME_FUTURE_TOLERANCE:
        raise InvalidQualityEffectiveTimeError("effective_time must not be in the future")
    if current_event is not None and effective_time < current_event.effective_time:
        raise InvalidQualityEffectiveTimeError(
            "effective_time cannot precede the cohort's currently effective Quality decision"
        )


def _validate_correction_effective_time(*, effective_time: datetime) -> None:
    """CORRECTION chronology rules (PILOT-BLOCKER-008 A1, extending F07):
    a correction remains an explicit target-based operation and is legitimately
    historical/backdated -- it is never subject to the ordinary nondecreasing-
    vs-current-event check. It DOES now share the same tz-awareness and
    30-second future-skew ceiling every other Quality family uses: GrowCMP has
    no scheduled-decision model, so a materially future correction must not be
    accepted and become the current Quality decision immediately. Do not add
    the ordinary "cannot precede current decision" check here -- that would
    reintroduce scheduled-decision semantics this function must not have."""
    _require_tz_aware_effective_time(effective_time)
    now = _now_provider(effective_time.tzinfo)
    if effective_time > now + _EFFECTIVE_TIME_FUTURE_TOLERANCE:
        raise InvalidQualityEffectiveTimeError("effective_time must not be in the future")


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


# --- Current-state resolution ------------------------------------------------


def resolve_current_event(
    db: Session, *, tenant_id: uuid.UUID, cohort_id: uuid.UUID
) -> QualityDispositionEvent | None:
    """The current (latest, not-yet-reversed) disposition event for a
    cohort -- `None` means implicit RELEASED (no events at all). Mirrors
    the `.1` DB trigger's own "current event" resolution exactly."""
    reversed_target_ids = select(QualityDispositionEvent.reverses_event_id).where(
        QualityDispositionEvent.tenant_id == tenant_id,
        QualityDispositionEvent.reverses_event_id.isnot(None),
    )
    return db.execute(
        select(QualityDispositionEvent)
        .where(
            QualityDispositionEvent.tenant_id == tenant_id,
            QualityDispositionEvent.inventory_quantity_cohort_id == cohort_id,
            QualityDispositionEvent.event_kind != "REVERSAL",
            QualityDispositionEvent.id.not_in(reversed_target_ids),
        )
        .order_by(
            QualityDispositionEvent.effective_time.desc(),
            QualityDispositionEvent.recorded_time.desc(),
            QualityDispositionEvent.id.desc(),
        )
        .limit(1)
    ).scalar_one_or_none()


def resolve_current_state(db: Session, *, tenant_id: uuid.UUID, cohort_id: uuid.UUID) -> str:
    event = resolve_current_event(db, tenant_id=tenant_id, cohort_id=cohort_id)
    return event.event_kind if event is not None else "RELEASED"


def _resolve_state_excluding(
    db: Session, *, tenant_id: uuid.UUID, cohort_id: uuid.UUID, excluded_event_id: uuid.UUID
) -> str:
    """The state the cohort would fall back to if `excluded_event_id` (the
    event a correction is about to reverse) were removed from
    consideration -- i.e. the predecessor state a correction with no
    replacement reverts to. Never assumes RELEASED by default."""
    reversed_target_ids = select(QualityDispositionEvent.reverses_event_id).where(
        QualityDispositionEvent.tenant_id == tenant_id,
        QualityDispositionEvent.reverses_event_id.isnot(None),
    )
    event = db.execute(
        select(QualityDispositionEvent)
        .where(
            QualityDispositionEvent.tenant_id == tenant_id,
            QualityDispositionEvent.inventory_quantity_cohort_id == cohort_id,
            QualityDispositionEvent.event_kind != "REVERSAL",
            QualityDispositionEvent.id != excluded_event_id,
            QualityDispositionEvent.id.not_in(reversed_target_ids),
        )
        .order_by(
            QualityDispositionEvent.effective_time.desc(),
            QualityDispositionEvent.recorded_time.desc(),
            QualityDispositionEvent.id.desc(),
        )
        .limit(1)
    ).scalar_one_or_none()
    return event.event_kind if event is not None else "RELEASED"


# --- Segregation of duties ---------------------------------------------------


def _get_original_receiver_user_id(db: Session, *, tenant_id: uuid.UUID, cohort: InventoryQuantityCohort) -> uuid.UUID:
    """The Goods Receipt's own `received_by_user_id` -- the ONLY identity
    segregation-of-duties ever compares against."""
    return db.execute(
        select(GoodsReceipt.received_by_user_id)
        .join(GoodsReceiptLine, GoodsReceiptLine.goods_receipt_id == GoodsReceipt.id)
        .where(
            GoodsReceipt.tenant_id == tenant_id,
            GoodsReceiptLine.id == cohort.source_goods_receipt_line_id,
        )
    ).scalar_one()


def _enforce_segregation_of_duties(
    db: Session, *, tenant_id: uuid.UUID, cohort: InventoryQuantityCohort, actor_user_id: uuid.UUID,
    resulting_state: str,
) -> None:
    """Frozen scope (docs/domain/STORE_INVENTORY_MODEL.md §11): "wherever
    `InventoryItem.qc_release_required = true`..." -- this check applies
    ONLY to QC-controlled material. A non-QC item's material may be freely
    released/hold-released by its own receiver; segregation is never
    broadened onto every usable-result action indiscriminately (CTO
    closure pass §4)."""
    if resulting_state not in USABLE_STATES:
        return
    qc_release_required = db.execute(
        select(InventoryItem.qc_release_required).where(
            InventoryItem.tenant_id == tenant_id, InventoryItem.id == cohort.inventory_item_id,
        )
    ).scalar_one()
    if not qc_release_required:
        return
    receiver_id = _get_original_receiver_user_id(db, tenant_id=tenant_id, cohort=cohort)
    if actor_user_id == receiver_id:
        raise QualitySegregationOfDutiesError(
            "you received this delivery -- another authorized user must release this quantity"
        )


# --- Command idempotency ------------------------------------------------------


def _find_command(
    db: Session, *, tenant_id: uuid.UUID, client_command_id: uuid.UUID
) -> InventoryQualityCommand | None:
    return db.execute(
        select(InventoryQualityCommand).where(
            InventoryQualityCommand.tenant_id == tenant_id,
            InventoryQualityCommand.client_command_id == client_command_id,
        )
    ).scalar_one_or_none()


def _events_for_command(db: Session, *, command_id: uuid.UUID) -> list[QualityDispositionEvent]:
    return list(
        db.execute(
            select(QualityDispositionEvent).where(QualityDispositionEvent.command_id == command_id)
        ).scalars()
    )


def _insert_command(
    db: Session, *, tenant_id: uuid.UUID, cohort_id: uuid.UUID, operation_kind: str,
    target_event_id: uuid.UUID | None, actor_user_id: uuid.UUID, client_command_id: uuid.UUID,
    fingerprint: str, conflict_error: type[Exception],
) -> InventoryQualityCommand:
    """Inserts the command header, catching the tenant-wide unique-index
    race (two concurrent requests sharing one `client_command_id`, even
    against different cohorts) and resolving it to a replay or a typed
    conflict -- this is the actual command-level idempotency backstop."""
    command = InventoryQualityCommand(
        id=uuid.uuid4(), tenant_id=tenant_id, inventory_quantity_cohort_id=cohort_id, operation_kind=operation_kind,
        target_event_id=target_event_id, actor_user_id=actor_user_id, client_command_id=client_command_id,
        request_fingerprint=fingerprint,
    )
    db.add(command)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_inventory_quality_commands_tenant_client_command_id":
            raise conflict_error(str(client_command_id)) from exc
        raise
    return command


def _compute_disposition_fingerprint(
    *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, cohort_id: uuid.UUID, disposition: str,
    effective_time: datetime, reason: str | None,
) -> str:
    parts = [
        str(tenant_id), str(actor_user_id), str(cohort_id), disposition, effective_time.isoformat(), reason or "",
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _compute_correction_fingerprint(
    *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, cohort_id: uuid.UUID, target_event_id: uuid.UUID,
    reason: str, replacement_disposition: str | None, effective_time: datetime,
) -> str:
    parts = [
        str(tenant_id), str(actor_user_id), str(cohort_id), str(target_event_id), reason,
        replacement_disposition or "", effective_time.isoformat(),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _compute_partial_fingerprint(
    *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, source_cohort_id: uuid.UUID, quantity: Decimal,
    disposition: str, reason: str | None, effective_time: datetime, custody_location_id: uuid.UUID | None = None,
) -> str:
    parts = [
        str(tenant_id), str(actor_user_id), str(source_cohort_id), str(quantity), disposition, reason or "",
        effective_time.isoformat(), str(custody_location_id or ""),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _compute_partial_correction_fingerprint(
    *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, source_cohort_id: uuid.UUID, target_event_id: uuid.UUID,
    quantity: Decimal, corrected_disposition: str, reason: str, effective_time: datetime,
    custody_location_id: uuid.UUID | None = None,
) -> str:
    parts = [
        str(tenant_id), str(actor_user_id), str(source_cohort_id), str(target_event_id), str(quantity),
        corrected_disposition, reason, effective_time.isoformat(), str(custody_location_id or ""),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


# --- Commands ------------------------------------------------------------------


def record_quality_disposition(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_command_id: uuid.UUID,
    cohort_id: uuid.UUID,
    disposition: str,
    effective_time: datetime,
    reason: str | None = None,
) -> QualityDispositionEvent:
    """Release / Hold / Reject / Hold-Release -- one ordinary whole-cohort
    human quality decision (`operation_kind='RECORD'`)."""
    if disposition not in VALID_DISPOSITIONS:
        raise InvalidQualityDispositionTransitionError(f"{disposition!r} is not a valid disposition")

    fingerprint = _compute_disposition_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, cohort_id=cohort_id, disposition=disposition,
        effective_time=effective_time, reason=reason,
    )

    def _replay() -> QualityDispositionEvent | None:
        existing = _find_command(db, tenant_id=tenant_id, client_command_id=client_command_id)
        if existing is None:
            return None
        if existing.request_fingerprint != fingerprint:
            raise QualityDispositionCommandReusedWithDifferentPayloadError(str(client_command_id))
        return _events_for_command(db, command_id=existing.id)[0]

    replay = _replay()
    if replay is not None:
        return replay

    cohort = _lock_cohort(db, tenant_id=tenant_id, cohort_id=cohort_id)

    replay = _replay()
    if replay is not None:
        return replay

    current_event = resolve_current_event(db, tenant_id=tenant_id, cohort_id=cohort.id)
    current_state = current_event.event_kind if current_event is not None else "RELEASED"
    if disposition not in _legal_next_dispositions(current_state):
        raise InvalidQualityDispositionTransitionError(
            f"cannot transition this cohort from {current_state} to {disposition}"
        )
    _validate_ordinary_effective_time(effective_time=effective_time, current_event=current_event)

    _enforce_segregation_of_duties(
        db, tenant_id=tenant_id, cohort=cohort, actor_user_id=actor_user_id, resulting_state=disposition
    )

    command = _insert_command(
        db, tenant_id=tenant_id, cohort_id=cohort.id, operation_kind="RECORD", target_event_id=None,
        actor_user_id=actor_user_id, client_command_id=client_command_id, fingerprint=fingerprint,
        conflict_error=QualityDispositionCommandReusedWithDifferentPayloadError,
    )

    event = QualityDispositionEvent(
        tenant_id=tenant_id, inventory_quantity_cohort_id=cohort.id, event_kind=disposition,
        effective_time=effective_time, recorded_time=datetime.now(effective_time.tzinfo),
        actor_user_id=actor_user_id, reason=reason, command_id=command.id,
    )
    db.add(event)
    db.flush()

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="quality_disposition.recorded",
        entity_type="quality_disposition_event", entity_id=event.id,
        event_data={"cohort_id": str(cohort.id), "disposition": disposition, "reason": reason},
    )
    db.commit()
    db.refresh(event)
    return event


def correct_quality_disposition(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_command_id: uuid.UUID,
    cohort_id: uuid.UUID,
    target_event_id: uuid.UUID,
    reason: str,
    replacement_disposition: str | None,
    effective_time: datetime,
) -> tuple[QualityDispositionEvent, QualityDispositionEvent | None]:
    """Corrects the cohort's current human decision -- `target_event_id` is
    the event the OPERATOR OBSERVED (from the Quality work-queue read
    model), never resolved to "whatever is current" server-side. If the
    cohort's current event has since changed, this is rejected as a typed
    stale-target conflict, never silently reinterpreted onto the newer
    decision (CTO closure pass §2)."""
    if replacement_disposition is not None and replacement_disposition not in VALID_DISPOSITIONS:
        raise InvalidQualityDispositionTransitionError(
            f"{replacement_disposition!r} is not a valid replacement disposition"
        )
    # PILOT-BLOCKER-008 A1: tz-aware + 30s future-skew ceiling, but never the
    # ordinary nondecreasing-vs-current-event check -- corrections remain
    # explicit target-based operations and may legitimately be historical.
    _validate_correction_effective_time(effective_time=effective_time)

    fingerprint = _compute_correction_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, cohort_id=cohort_id, target_event_id=target_event_id,
        reason=reason, replacement_disposition=replacement_disposition, effective_time=effective_time,
    )

    def _replay() -> tuple[QualityDispositionEvent, QualityDispositionEvent | None] | None:
        existing = _find_command(db, tenant_id=tenant_id, client_command_id=client_command_id)
        if existing is None:
            return None
        if existing.request_fingerprint != fingerprint:
            raise QualityCorrectionCommandReusedWithDifferentPayloadError(str(client_command_id))
        events = _events_for_command(db, command_id=existing.id)
        reversal = next(e for e in events if e.event_kind == "REVERSAL")
        replacement = next((e for e in events if e.event_kind != "REVERSAL"), None)
        return reversal, replacement

    replay = _replay()
    if replay is not None:
        return replay

    cohort = _lock_cohort(db, tenant_id=tenant_id, cohort_id=cohort_id)

    replay = _replay()
    if replay is not None:
        return replay

    target_cohort_id = db.execute(
        select(QualityDispositionEvent.inventory_quantity_cohort_id).where(
            QualityDispositionEvent.id == target_event_id, QualityDispositionEvent.tenant_id == tenant_id,
        )
    ).scalar_one_or_none()
    if target_cohort_id is None or target_cohort_id != cohort.id:
        raise QualityDispositionEventNotFoundError(str(target_event_id))

    current_event = resolve_current_event(db, tenant_id=tenant_id, cohort_id=cohort.id)
    if current_event is None or current_event.event_kind == "RECEIVED_QUARANTINED":
        raise QualityDispositionNoCurrentHumanDecisionError(
            "there is no current human quality decision on this cohort to correct"
        )
    if current_event.id != target_event_id:
        raise QualityCorrectionTargetNotCurrentError(
            "Quality decision changed since you opened this action. Refresh and review the current decision."
        )

    fallback_state = _resolve_state_excluding(
        db, tenant_id=tenant_id, cohort_id=cohort.id, excluded_event_id=current_event.id
    )
    resulting_state = replacement_disposition if replacement_disposition is not None else fallback_state

    if replacement_disposition is not None and replacement_disposition not in _legal_next_dispositions(fallback_state):
        raise InvalidQualityDispositionTransitionError(
            f"replacement disposition {replacement_disposition} is not valid from {fallback_state}"
        )

    _enforce_segregation_of_duties(
        db, tenant_id=tenant_id, cohort=cohort, actor_user_id=actor_user_id, resulting_state=resulting_state
    )

    command = _insert_command(
        db, tenant_id=tenant_id, cohort_id=cohort.id, operation_kind="CORRECT", target_event_id=target_event_id,
        actor_user_id=actor_user_id, client_command_id=client_command_id, fingerprint=fingerprint,
        conflict_error=QualityCorrectionCommandReusedWithDifferentPayloadError,
    )

    recorded_time = datetime.now(effective_time.tzinfo)
    reversal = QualityDispositionEvent(
        tenant_id=tenant_id, inventory_quantity_cohort_id=cohort.id, event_kind="REVERSAL",
        reverses_event_id=target_event_id, effective_time=effective_time, recorded_time=recorded_time,
        actor_user_id=actor_user_id, reason=reason, command_id=command.id,
    )
    db.add(reversal)
    db.flush()

    replacement = None
    if replacement_disposition is not None:
        replacement = QualityDispositionEvent(
            tenant_id=tenant_id, inventory_quantity_cohort_id=cohort.id, event_kind=replacement_disposition,
            effective_time=effective_time, recorded_time=recorded_time, actor_user_id=actor_user_id, reason=reason,
            command_id=command.id,
        )
        db.add(replacement)
        db.flush()

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="quality_disposition.corrected",
        entity_type="quality_disposition_event", entity_id=reversal.id,
        event_data={
            "cohort_id": str(cohort.id), "corrected_event_id": str(target_event_id), "reason": reason,
            "replacement_disposition": replacement_disposition,
        },
    )
    db.commit()
    db.refresh(reversal)
    if replacement is not None:
        db.refresh(replacement)
    return reversal, replacement


def apply_quality_disposition_to_partial_quantity(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_command_id: uuid.UUID,
    source_cohort_id: uuid.UUID,
    quantity: Decimal,
    disposition: str,
    effective_time: datetime,
    reason: str | None = None,
    custody_location_id: uuid.UUID | None = None,
) -> InventoryQuantityCohort:
    """"Apply disposition to part of quantity" -- an ORDINARY partial
    transition (still validated against the frozen state machine).
    Internally composes `.1`'s internal `_split_cohort_core` primitive
    with this child's own opening `QualityDispositionEvent`, all in ONE
    transaction ending in ONE commit.

    STORE-INV-002B: `custody_location_id` names the exact physical
    "bucket" this partial action acts against -- `None` for "Not put
    away", or a specific `store_bin` id. The requested quantity is
    validated against THAT bucket's own balance, never the cohort's whole
    existence balance, and when the bucket is a Bin, custody is logically
    reassigned to the child cohort in the same transaction (docs §11's
    partial-quality/custody integration seam)."""
    if disposition not in VALID_DISPOSITIONS:
        raise InvalidQualityDispositionTransitionError(f"{disposition!r} is not a valid disposition")
    if quantity <= 0:
        raise InventoryQuantityCohortSplitAllocationExceedsBalanceError("quantity must be positive")

    fingerprint = _compute_partial_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, source_cohort_id=source_cohort_id, quantity=quantity,
        disposition=disposition, reason=reason, effective_time=effective_time,
        custody_location_id=custody_location_id,
    )

    def _replay() -> InventoryQuantityCohort | None:
        existing = _find_command(db, tenant_id=tenant_id, client_command_id=client_command_id)
        if existing is None:
            return None
        if existing.request_fingerprint != fingerprint:
            raise QualityPartialDispositionCommandReusedWithDifferentPayloadError(str(client_command_id))
        event = _events_for_command(db, command_id=existing.id)[0]
        return db.execute(
            select(InventoryQuantityCohort).where(
                InventoryQuantityCohort.tenant_id == tenant_id,
                InventoryQuantityCohort.id == event.inventory_quantity_cohort_id,
            )
        ).scalar_one()

    replay = _replay()
    if replay is not None:
        return replay

    source = _lock_cohort(db, tenant_id=tenant_id, cohort_id=source_cohort_id)

    replay = _replay()
    if replay is not None:
        return replay

    source_current_event = resolve_current_event(db, tenant_id=tenant_id, cohort_id=source.id)
    current_state = source_current_event.event_kind if source_current_event is not None else "RELEASED"
    if disposition not in _legal_next_dispositions(current_state):
        raise InvalidQualityDispositionTransitionError(
            f"cannot transition this cohort from {current_state} to {disposition}"
        )
    _validate_ordinary_effective_time(effective_time=effective_time, current_event=source_current_event)

    _enforce_segregation_of_duties(
        db, tenant_id=tenant_id, cohort=source, actor_user_id=actor_user_id, resulting_state=disposition
    )

    if custody_location_id is None:
        # PILOT-BLOCKER-004 F02: not-put-away's own canonical formula
        # (existence - custody + settled-from-issued), never the stale
        # `existence - custody` alone -- see
        # `inventory_cohort_accounting_service`.
        bucket_balance = inventory_cohort_accounting_service.get_cohort_accounting_snapshot(
            db, cohort_id=source.id
        ).not_put_away
    else:
        bin_ = _lock_bin(db, tenant_id=tenant_id, farm_id=source.receiving_farm_id, location_id=custody_location_id)
        if bin_.status != "active":
            raise IneligibleStorageBinError(str(custody_location_id))
        bucket_balance = get_cohort_bin_balance(db, cohort_id=source.id, location_id=custody_location_id)
    if quantity > bucket_balance:
        raise InventoryQuantityCohortSplitAllocationExceedsBalanceError(
            f"requested quantity {quantity} exceeds bucket balance {bucket_balance} for cohort {source_cohort_id}"
        )

    command = _insert_command(
        db, tenant_id=tenant_id, cohort_id=source.id, operation_kind="PARTIAL", target_event_id=None,
        actor_user_id=actor_user_id, client_command_id=client_command_id, fingerprint=fingerprint,
        conflict_error=QualityPartialDispositionCommandReusedWithDifferentPayloadError,
    )

    children = _split_cohort_core(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, source_cohort_id=source.id,
        allocations=[quantity], reason=reason or "partial quality disposition", effective_time=effective_time,
    )
    child = children[0]

    if custody_location_id is not None:
        split_custody_core(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, farm_id=source.receiving_farm_id,
            source_cohort_id=source.id, child_cohort_id=child.id, location_id=custody_location_id,
            quantity=quantity, effective_time=effective_time,
        )

    opening_event = QualityDispositionEvent(
        tenant_id=tenant_id, inventory_quantity_cohort_id=child.id, event_kind=disposition,
        effective_time=effective_time, recorded_time=datetime.now(effective_time.tzinfo),
        actor_user_id=actor_user_id, reason=reason, command_id=command.id,
    )
    db.add(opening_event)
    db.flush()

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="quality_disposition.partial_applied",
        entity_type="inventory_quantity_cohort", entity_id=child.id,
        event_data={
            "source_cohort_id": str(source.id), "quantity": str(quantity), "disposition": disposition,
            "reason": reason, "custody_location_id": str(custody_location_id) if custody_location_id else None,
        },
    )
    db.commit()
    db.refresh(child)
    return child


def correct_quality_disposition_for_partial_quantity(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_command_id: uuid.UUID,
    source_cohort_id: uuid.UUID,
    target_event_id: uuid.UUID,
    quantity: Decimal,
    corrected_disposition: str,
    reason: str,
    effective_time: datetime,
    custody_location_id: uuid.UUID | None = None,
) -> InventoryQuantityCohort:
    """"Correct decision for part of quantity" -- compensating quantity
    partitioning for a mistaken classification, NEVER an ordinary forward
    transition (`operation_kind='PARTIAL_CORRECT'`). Example: 100 kg
    currently REJECTED, 20 kg of it was wrongly rejected -- this command
    partitions exactly 20 kg into a new child cohort whose OWN opening
    disposition is the corrected outcome (e.g. RELEASED), while the
    source's remaining 80 kg keeps its existing REJECTED disposition/
    history completely untouched. `target_event_id` must be the source
    cohort's CURRENT human decision (never `RECEIVED_QUARANTINED`) --
    deliberately NOT validated against the ordinary `_TRANSITIONS` table,
    since this command exists precisely to bypass it (REJECTED has no
    ordinary forward transition, but a MISTAKEN rejection is correctable).
    The same `target_event_id` may legitimately be the target of more than
    one `PARTIAL_CORRECT` command over time (the source's own current
    event never changes as a result of this command), unlike whole-cohort
    `CORRECT`, which may only ever be applied once per target."""
    if corrected_disposition not in VALID_DISPOSITIONS:
        raise InvalidQualityDispositionTransitionError(f"{corrected_disposition!r} is not a valid disposition")
    if quantity <= 0:
        raise InventoryQuantityCohortSplitAllocationExceedsBalanceError("quantity must be positive")
    # PILOT-BLOCKER-008 A1 -- see correct_quality_disposition's own comment.
    _validate_correction_effective_time(effective_time=effective_time)

    fingerprint = _compute_partial_correction_fingerprint(
        tenant_id=tenant_id, actor_user_id=actor_user_id, source_cohort_id=source_cohort_id,
        target_event_id=target_event_id, quantity=quantity, corrected_disposition=corrected_disposition,
        reason=reason, effective_time=effective_time, custody_location_id=custody_location_id,
    )

    def _replay() -> InventoryQuantityCohort | None:
        existing = _find_command(db, tenant_id=tenant_id, client_command_id=client_command_id)
        if existing is None:
            return None
        if existing.request_fingerprint != fingerprint:
            raise QualityPartialCorrectionCommandReusedWithDifferentPayloadError(str(client_command_id))
        event = _events_for_command(db, command_id=existing.id)[0]
        return db.execute(
            select(InventoryQuantityCohort).where(
                InventoryQuantityCohort.tenant_id == tenant_id,
                InventoryQuantityCohort.id == event.inventory_quantity_cohort_id,
            )
        ).scalar_one()

    replay = _replay()
    if replay is not None:
        return replay

    source = _lock_cohort(db, tenant_id=tenant_id, cohort_id=source_cohort_id)

    replay = _replay()
    if replay is not None:
        return replay

    target_cohort_id = db.execute(
        select(QualityDispositionEvent.inventory_quantity_cohort_id).where(
            QualityDispositionEvent.id == target_event_id, QualityDispositionEvent.tenant_id == tenant_id,
        )
    ).scalar_one_or_none()
    if target_cohort_id is None or target_cohort_id != source.id:
        raise QualityDispositionEventNotFoundError(str(target_event_id))

    current_event = resolve_current_event(db, tenant_id=tenant_id, cohort_id=source.id)
    if current_event is None or current_event.event_kind == "RECEIVED_QUARANTINED":
        raise QualityDispositionNoCurrentHumanDecisionError(
            "there is no current human quality decision on this cohort to correct"
        )
    if current_event.id != target_event_id:
        raise QualityCorrectionTargetNotCurrentError(
            "Quality decision changed since you opened this action. Refresh and review the current decision."
        )

    _enforce_segregation_of_duties(
        db, tenant_id=tenant_id, cohort=source, actor_user_id=actor_user_id, resulting_state=corrected_disposition
    )

    if custody_location_id is None:
        # PILOT-BLOCKER-004 F02: same canonical not-put-away formula as
        # `apply_quality_disposition_to_partial_quantity` above.
        bucket_balance = inventory_cohort_accounting_service.get_cohort_accounting_snapshot(
            db, cohort_id=source.id
        ).not_put_away
    else:
        bin_ = _lock_bin(db, tenant_id=tenant_id, farm_id=source.receiving_farm_id, location_id=custody_location_id)
        if bin_.status != "active":
            raise IneligibleStorageBinError(str(custody_location_id))
        bucket_balance = get_cohort_bin_balance(db, cohort_id=source.id, location_id=custody_location_id)
    if quantity > bucket_balance:
        raise InventoryQuantityCohortSplitAllocationExceedsBalanceError(
            f"requested quantity {quantity} exceeds bucket balance {bucket_balance} for cohort {source_cohort_id}"
        )

    command = _insert_command(
        db, tenant_id=tenant_id, cohort_id=source.id, operation_kind="PARTIAL_CORRECT",
        target_event_id=target_event_id, actor_user_id=actor_user_id, client_command_id=client_command_id,
        fingerprint=fingerprint, conflict_error=QualityPartialCorrectionCommandReusedWithDifferentPayloadError,
    )

    children = _split_cohort_core(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, source_cohort_id=source.id,
        allocations=[quantity], reason=reason, effective_time=effective_time,
    )
    child = children[0]

    if custody_location_id is not None:
        split_custody_core(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, farm_id=source.receiving_farm_id,
            source_cohort_id=source.id, child_cohort_id=child.id, location_id=custody_location_id,
            quantity=quantity, effective_time=effective_time,
        )

    opening_event = QualityDispositionEvent(
        tenant_id=tenant_id, inventory_quantity_cohort_id=child.id, event_kind=corrected_disposition,
        effective_time=effective_time, recorded_time=datetime.now(effective_time.tzinfo),
        actor_user_id=actor_user_id, reason=reason, command_id=command.id,
    )
    db.add(opening_event)
    db.flush()

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="quality_disposition.partial_corrected",
        entity_type="inventory_quantity_cohort", entity_id=child.id,
        event_data={
            "source_cohort_id": str(source.id), "target_event_id": str(target_event_id), "quantity": str(quantity),
            "corrected_disposition": corrected_disposition, "reason": reason,
            "custody_location_id": str(custody_location_id) if custody_location_id else None,
        },
    )
    db.commit()
    db.refresh(child)
    return child


# --- Usable-existence read model -------------------------------------------


def _current_state_subquery(tenant_id: uuid.UUID):
    reversed_target_ids = select(QualityDispositionEvent.reverses_event_id).where(
        QualityDispositionEvent.tenant_id == tenant_id,
        QualityDispositionEvent.reverses_event_id.isnot(None),
    )
    candidate = (
        select(
            QualityDispositionEvent.inventory_quantity_cohort_id.label("cohort_id"),
            QualityDispositionEvent.id.label("event_id"),
            QualityDispositionEvent.event_kind.label("event_kind"),
            QualityDispositionEvent.actor_user_id.label("actor_user_id"),
            QualityDispositionEvent.effective_time.label("effective_time"),
            func.row_number()
            .over(
                partition_by=QualityDispositionEvent.inventory_quantity_cohort_id,
                order_by=(
                    QualityDispositionEvent.effective_time.desc(),
                    QualityDispositionEvent.recorded_time.desc(),
                    QualityDispositionEvent.id.desc(),
                ),
            )
            .label("rn"),
        )
        .where(
            QualityDispositionEvent.tenant_id == tenant_id,
            QualityDispositionEvent.event_kind != "REVERSAL",
            QualityDispositionEvent.id.not_in(reversed_target_ids),
        )
        .subquery()
    )
    return (
        select(
            candidate.c.cohort_id, candidate.c.event_id, candidate.c.event_kind, candidate.c.actor_user_id,
            candidate.c.effective_time,
        )
        .where(candidate.c.rn == 1)
        .subquery()
    )


def get_item_usable_existence(
    db: Session, *, tenant_id: uuid.UUID, inventory_item_id: uuid.UUID, as_of: date | None = None
) -> Decimal:
    """`SUM` of every cohort's current balance whose current derived
    disposition is usable (implicit or explicit `RELEASED`, or
    `HOLD_RELEASED`) AND not expired AND balance > 0. Never called
    "available" -- Reservation does not exist yet."""
    as_of = as_of or date.today()
    state_subq = _current_state_subquery(tenant_id)
    balance_subq = (
        select(
            InventoryExistenceLedgerEntry.inventory_quantity_cohort_id.label("cohort_id"),
            func.coalesce(func.sum(InventoryExistenceLedgerEntry.quantity_delta_base), 0).label("balance"),
        )
        .where(
            InventoryExistenceLedgerEntry.tenant_id == tenant_id,
            InventoryExistenceLedgerEntry.inventory_item_id == inventory_item_id,
        )
        .group_by(InventoryExistenceLedgerEntry.inventory_quantity_cohort_id)
        .subquery()
    )
    query = (
        select(func.coalesce(func.sum(balance_subq.c.balance), 0))
        .select_from(balance_subq)
        .join(InventoryQuantityCohort, InventoryQuantityCohort.id == balance_subq.c.cohort_id)
        .outerjoin(state_subq, state_subq.c.cohort_id == balance_subq.c.cohort_id)
        .outerjoin(InventoryLot, InventoryLot.id == InventoryQuantityCohort.inventory_lot_id)
        .where(
            balance_subq.c.balance > 0,
            func.coalesce(state_subq.c.event_kind, "RELEASED").in_(("RELEASED", "HOLD_RELEASED")),
            (InventoryLot.expiry_date.is_(None)) | (InventoryLot.expiry_date >= as_of),
        )
    )
    return db.execute(query).scalar_one()


def get_lot_usable_existence(
    db: Session, *, tenant_id: uuid.UUID, inventory_lot_id: uuid.UUID, as_of: date | None = None
) -> Decimal:
    as_of = as_of or date.today()

    expiry = db.execute(
        select(InventoryLot.expiry_date).where(
            InventoryLot.tenant_id == tenant_id, InventoryLot.id == inventory_lot_id
        )
    ).scalar_one_or_none()
    if expiry is not None and expiry < as_of:
        return Decimal(0)

    state_subq = _current_state_subquery(tenant_id)
    balance_subq = (
        select(
            InventoryExistenceLedgerEntry.inventory_quantity_cohort_id.label("cohort_id"),
            func.coalesce(func.sum(InventoryExistenceLedgerEntry.quantity_delta_base), 0).label("balance"),
        )
        .where(
            InventoryExistenceLedgerEntry.tenant_id == tenant_id,
            InventoryExistenceLedgerEntry.inventory_lot_id == inventory_lot_id,
        )
        .group_by(InventoryExistenceLedgerEntry.inventory_quantity_cohort_id)
        .subquery()
    )
    query = (
        select(func.coalesce(func.sum(balance_subq.c.balance), 0))
        .select_from(balance_subq)
        .outerjoin(state_subq, state_subq.c.cohort_id == balance_subq.c.cohort_id)
        .where(
            balance_subq.c.balance > 0,
            func.coalesce(state_subq.c.event_kind, "RELEASED").in_(("RELEASED", "HOLD_RELEASED")),
        )
    )
    return db.execute(query).scalar_one()


def list_quality_work_queue(db: Session, *, tenant_id: uuid.UUID) -> list[dict]:
    """Every cohort with a positive current balance, company-wide, with its
    current derived quality state plus enough denormalized context for a
    single work-queue screen. A cohort left at zero balance after a full
    split never appears here -- `balance_subq.c.balance > 0` excludes it
    (proven by `test_quality_work_queue_excludes_zero_balance_source_after_full_split`)."""
    state_subq = _current_state_subquery(tenant_id)
    balance_subq = (
        select(
            InventoryExistenceLedgerEntry.inventory_quantity_cohort_id.label("cohort_id"),
            func.coalesce(func.sum(InventoryExistenceLedgerEntry.quantity_delta_base), 0).label("balance"),
        )
        .where(InventoryExistenceLedgerEntry.tenant_id == tenant_id)
        .group_by(InventoryExistenceLedgerEntry.inventory_quantity_cohort_id)
        .subquery()
    )
    rows = db.execute(
        select(
            InventoryQuantityCohort.id,
            InventoryQuantityCohort.inventory_item_id,
            InventoryItem.name.label("item_name"),
            InventoryItem.base_uom_id,
            InventoryQuantityCohort.inventory_lot_id,
            InventoryLot.manufacturer_lot_reference,
            InventoryLot.expiry_date,
            InventoryQuantityCohort.receiving_farm_id,
            InventoryQuantityCohort.source_goods_receipt_line_id,
            GoodsReceipt.code.label("receipt_code"),
            GoodsReceipt.received_at.label("receipt_received_at"),
            balance_subq.c.balance,
            func.coalesce(state_subq.c.event_kind, "RELEASED").label("current_state"),
            state_subq.c.event_id.label("current_event_id"),
            state_subq.c.actor_user_id.label("last_actor_user_id"),
            state_subq.c.effective_time.label("last_effective_time"),
        )
        .select_from(InventoryQuantityCohort)
        .join(balance_subq, balance_subq.c.cohort_id == InventoryQuantityCohort.id)
        .join(InventoryItem, InventoryItem.id == InventoryQuantityCohort.inventory_item_id)
        .outerjoin(InventoryLot, InventoryLot.id == InventoryQuantityCohort.inventory_lot_id)
        .join(GoodsReceiptLine, GoodsReceiptLine.id == InventoryQuantityCohort.source_goods_receipt_line_id)
        .join(GoodsReceipt, GoodsReceipt.id == GoodsReceiptLine.goods_receipt_id)
        .outerjoin(state_subq, state_subq.c.cohort_id == InventoryQuantityCohort.id)
        .where(InventoryQuantityCohort.tenant_id == tenant_id, balance_subq.c.balance > 0)
        .order_by(GoodsReceipt.received_at.desc())
    ).all()
    return [
        {
            "inventory_quantity_cohort_id": row.id,
            "inventory_item_id": row.inventory_item_id,
            "item_name": row.item_name,
            "base_uom_id": row.base_uom_id,
            "inventory_lot_id": row.inventory_lot_id,
            "manufacturer_lot_reference": row.manufacturer_lot_reference,
            "expiry_date": row.expiry_date,
            "received_at_farm_id": row.receiving_farm_id,
            "source_goods_receipt_line_id": row.source_goods_receipt_line_id,
            "receipt_code": row.receipt_code,
            "receipt_received_at": row.receipt_received_at,
            "balance": row.balance,
            "current_state": row.current_state,
            "current_event_id": row.current_event_id,
            "last_actor_user_id": row.last_actor_user_id,
            "last_effective_time": row.last_effective_time,
        }
        for row in rows
    ]
