"""PILOT-ASSET-001: Equipment Readiness lifecycle -- WHETHER a
readiness-tracked Asset/Carrier is ready to use, kept deliberately separate
from WHERE it is (Occupancy) and from its registry `status`
(active/inactive/damaged/retired). Every mutating command here follows the
same per-command idempotency shape `farm_work_item_service`/
`crop_issue_service` established -- pre-lock replay check, row lock,
post-lock replay recheck, mutate, flush with IntegrityError fallback,
`append_audit_event`, commit. Full lifecycle history is read back from
`audit_events` (`list_readiness_history`), never duplicated onto the
current-state row. See docs/domain/EQUIPMENT_READINESS_MODEL.md for the
full frozen design (state model, transitions, occupancy interaction, ready
validation, legacy UNKNOWN backfill)."""

import hashlib
import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.asset_type import AssetType
from app.models.audit_event import AuditEvent
from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.carrier import Carrier
from app.models.carrier_type import CarrierType
from app.models.cleaning_event import CleaningEvent
from app.models.equipment_readiness_state import READINESS_TERMINAL_STATES, EquipmentReadinessState
from app.services import farm_service
from app.services.audit import append_audit_event
from app.services.errors import (
    AssetNotFoundError,
    CarrierNotFoundError,
    CleaningEventCommandReusedWithDifferentPayloadError,
    EquipmentReadinessCarrierInUseError,
    EquipmentReadinessCleaningNotCompletedError,
    EquipmentReadinessCleaningNotRequiredError,
    EquipmentReadinessCommandReusedWithDifferentPayloadError,
    EquipmentReadinessInvalidTransitionError,
    EquipmentReadinessNotTrackedError,
    EquipmentReadinessStateNotFoundError,
    FarmNotFoundError,
)

MAX_LIST_LIMIT = 500


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


class _TypeInfo:
    __slots__ = ("readiness_tracked", "requires_cleaning")

    def __init__(self, readiness_tracked: bool, requires_cleaning: bool) -> None:
        self.readiness_tracked = readiness_tracked
        self.requires_cleaning = requires_cleaning


def _get_asset_and_type(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, asset_id: uuid.UUID
) -> tuple[Asset, _TypeInfo]:
    row = db.execute(
        select(Asset, AssetType)
        .join(AssetType, AssetType.id == Asset.asset_type_id)
        .where(Asset.id == asset_id, Asset.tenant_id == tenant_id, Asset.farm_id == farm_id)
    ).first()
    if row is None:
        raise AssetNotFoundError(str(asset_id))
    asset, asset_type = row
    return asset, _TypeInfo(asset_type.readiness_tracked, asset_type.requires_cleaning)


def _get_carrier_and_type(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, carrier_id: uuid.UUID
) -> tuple[Carrier, _TypeInfo]:
    row = db.execute(
        select(Carrier, CarrierType)
        .join(CarrierType, CarrierType.id == Carrier.carrier_type_id)
        .where(Carrier.id == carrier_id, Carrier.tenant_id == tenant_id, Carrier.farm_id == farm_id)
    ).first()
    if row is None:
        raise CarrierNotFoundError(str(carrier_id))
    carrier, carrier_type = row
    return carrier, _TypeInfo(carrier_type.readiness_tracked, carrier_type.requires_cleaning)


def has_active_batch_carrier_assignment(db: Session, *, tenant_id: uuid.UUID, carrier_id: uuid.UUID) -> bool:
    """Mirrors `nursery_service.list_available_seed_trays`'s own
    "not already carrying a live crop batch" subquery -- the authoritative
    "is this Carrier currently IN USE" signal (never physical Occupancy,
    which only answers WHERE -- see docs/domain/EQUIPMENT_READINESS_MODEL.md)."""
    row = db.execute(
        select(BatchCarrierAssignment.id).where(
            BatchCarrierAssignment.tenant_id == tenant_id,
            BatchCarrierAssignment.carrier_id == carrier_id,
            BatchCarrierAssignment.released_effective_time.is_(None),
        )
    ).first()
    return row is not None


def _require_state_for_asset(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, asset_id: uuid.UUID
) -> EquipmentReadinessState:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    _, type_info = _get_asset_and_type(db, tenant_id=tenant_id, farm_id=farm_id, asset_id=asset_id)
    if not type_info.readiness_tracked:
        raise EquipmentReadinessNotTrackedError(str(asset_id))
    state = db.execute(
        select(EquipmentReadinessState).where(
            EquipmentReadinessState.tenant_id == tenant_id, EquipmentReadinessState.asset_id == asset_id
        )
    ).scalar_one_or_none()
    if state is None:
        raise EquipmentReadinessStateNotFoundError(str(asset_id))
    return state


def _require_state_for_carrier(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, carrier_id: uuid.UUID
) -> EquipmentReadinessState:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    _, type_info = _get_carrier_and_type(db, tenant_id=tenant_id, farm_id=farm_id, carrier_id=carrier_id)
    if not type_info.readiness_tracked:
        raise EquipmentReadinessNotTrackedError(str(carrier_id))
    state = db.execute(
        select(EquipmentReadinessState).where(
            EquipmentReadinessState.tenant_id == tenant_id, EquipmentReadinessState.carrier_id == carrier_id
        )
    ).scalar_one_or_none()
    if state is None:
        raise EquipmentReadinessStateNotFoundError(str(carrier_id))
    return state


def get_readiness_for_asset(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, asset_id: uuid.UUID
) -> EquipmentReadinessState:
    return _require_state_for_asset(db, tenant_id=tenant_id, farm_id=farm_id, asset_id=asset_id)


def get_readiness_for_carrier(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, carrier_id: uuid.UUID
) -> EquipmentReadinessState:
    return _require_state_for_carrier(db, tenant_id=tenant_id, farm_id=farm_id, carrier_id=carrier_id)


def _lock_state(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, state_id: uuid.UUID) -> EquipmentReadinessState:
    state = db.execute(
        select(EquipmentReadinessState)
        .where(
            EquipmentReadinessState.id == state_id, EquipmentReadinessState.tenant_id == tenant_id,
            EquipmentReadinessState.farm_id == farm_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if state is None:
        raise EquipmentReadinessStateNotFoundError(str(state_id))
    return state


def _type_info_for_state(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, state: EquipmentReadinessState) -> _TypeInfo:
    if state.entity_type == "asset":
        _, type_info = _get_asset_and_type(db, tenant_id=tenant_id, farm_id=farm_id, asset_id=state.asset_id)
    else:
        _, type_info = _get_carrier_and_type(db, tenant_id=tenant_id, farm_id=farm_id, carrier_id=state.carrier_id)
    return type_info


def _entity_id(state: EquipmentReadinessState) -> uuid.UUID:
    return state.asset_id if state.entity_type == "asset" else state.carrier_id


# --- generic transition runner -----------------------------------------------------


def _run_transition(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    state_id: uuid.UUID,
    client_command_id: uuid.UUID,
    verb: str,
    command_id_field: str,
    fingerprint_field: str,
    unique_constraint_name: str,
    allowed_from: tuple[str, ...],
    target_state: str,
    note: str | None,
    action: str,
    validate: Callable[[Session, EquipmentReadinessState], None] | None = None,
) -> EquipmentReadinessState:
    fingerprint = _fingerprint(tenant_id, state_id, actor_user_id, verb, note)

    def _find_by_command() -> EquipmentReadinessState | None:
        return db.execute(
            select(EquipmentReadinessState).where(
                EquipmentReadinessState.tenant_id == tenant_id,
                getattr(EquipmentReadinessState, command_id_field) == client_command_id,
            )
        ).scalar_one_or_none()

    existing = _find_by_command()
    if existing is not None:
        if getattr(existing, fingerprint_field) == fingerprint:
            return existing
        raise EquipmentReadinessCommandReusedWithDifferentPayloadError(str(client_command_id))

    state = _lock_state(db, tenant_id=tenant_id, farm_id=farm_id, state_id=state_id)

    existing = _find_by_command()
    if existing is not None:
        if getattr(existing, fingerprint_field) == fingerprint:
            return existing
        raise EquipmentReadinessCommandReusedWithDifferentPayloadError(str(client_command_id))

    if state.current_state in READINESS_TERMINAL_STATES:
        raise EquipmentReadinessInvalidTransitionError(
            f"equipment readiness state {state_id} is retired (terminal)"
        )
    if state.current_state not in allowed_from:
        raise EquipmentReadinessInvalidTransitionError(
            f"cannot {verb} from state {state.current_state} (allowed: {allowed_from})"
        )
    if validate is not None:
        validate(db, state)

    before_state = state.current_state
    state.current_state = target_state
    state.state_changed_at = datetime.now(timezone.utc)
    state.state_changed_by_user_id = actor_user_id
    state.state_note = note
    setattr(state, command_id_field, client_command_id)
    setattr(state, fingerprint_field, fingerprint)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == unique_constraint_name:
            replay = _find_by_command()
            if replay is not None and getattr(replay, fingerprint_field) == fingerprint:
                return replay
            raise EquipmentReadinessCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action=action,
        entity_type="equipment_readiness_state", entity_id=state.id,
        event_data={
            "readiness_entity_type": state.entity_type, "readiness_entity_id": str(_entity_id(state)),
            "before_state": before_state, "after_state": target_state, "note": note,
        },
    )
    db.commit()
    db.refresh(state)
    return state


# --- commands ------------------------------------------------------------------------


def mark_awaiting_cleaning(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, state_id: uuid.UUID,
    client_command_id: uuid.UUID, note: str | None = None,
) -> EquipmentReadinessState:
    def _validate(db: Session, state: EquipmentReadinessState) -> None:
        type_info = _type_info_for_state(db, tenant_id=tenant_id, farm_id=farm_id, state=state)
        if not type_info.requires_cleaning:
            raise EquipmentReadinessCleaningNotRequiredError(str(_entity_id(state)))

    return _run_transition(
        db, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, state_id=state_id,
        client_command_id=client_command_id, verb="mark_awaiting_cleaning",
        command_id_field="awaiting_cleaning_client_command_id",
        fingerprint_field="awaiting_cleaning_request_fingerprint",
        unique_constraint_name="ux_equipment_readiness_states_tenant_awaiting_cleaning_command",
        allowed_from=("unknown", "cleaning_completed", "ready"), target_state="awaiting_cleaning", note=note,
        action="equipment_readiness.marked_awaiting_cleaning", validate=_validate,
    )


def record_cleaning_completed(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, state_id: uuid.UUID,
    client_command_id: uuid.UUID, effective_at: datetime, method: str | None, result: str, notes: str | None,
) -> tuple[EquipmentReadinessState, CleaningEvent]:
    """PART 5/6: inserts one immutable `CleaningEvent` and advances the
    linked `EquipmentReadinessState` to CLEANING_COMPLETED in the same
    transaction, regardless of `result` -- a NEEDS_REWORK result still
    stays at CLEANING_COMPLETED (never auto-reverts to AWAITING_CLEANING);
    `mark_ready` is the command that later checks the result. Idempotency
    is carried entirely by `CleaningEvent.client_command_id` -- a replay
    with the same id/payload returns the same pair without re-mutating the
    readiness row a second time."""
    fingerprint = _fingerprint(tenant_id, state_id, actor_user_id, effective_at, method, result, notes)

    def _find_event() -> CleaningEvent | None:
        return db.execute(
            select(CleaningEvent).where(
                CleaningEvent.tenant_id == tenant_id, CleaningEvent.client_command_id == client_command_id
            )
        ).scalar_one_or_none()

    existing = _find_event()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            state = _lock_state(db, tenant_id=tenant_id, farm_id=farm_id, state_id=state_id)
            db.commit()
            return state, existing
        raise CleaningEventCommandReusedWithDifferentPayloadError(str(client_command_id))

    state = _lock_state(db, tenant_id=tenant_id, farm_id=farm_id, state_id=state_id)

    existing = _find_event()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            db.commit()
            return state, existing
        raise CleaningEventCommandReusedWithDifferentPayloadError(str(client_command_id))

    if state.current_state in READINESS_TERMINAL_STATES:
        raise EquipmentReadinessInvalidTransitionError(f"equipment readiness state {state_id} is retired")
    if state.current_state != "awaiting_cleaning":
        raise EquipmentReadinessInvalidTransitionError(
            f"cannot record cleaning from state {state.current_state} (must be awaiting_cleaning)"
        )

    event = CleaningEvent(
        tenant_id=tenant_id, farm_id=farm_id, entity_type=state.entity_type,
        asset_id=state.asset_id, carrier_id=state.carrier_id, effective_at=effective_at,
        performed_by_user_id=actor_user_id, method=method, result=result, notes=notes,
        client_command_id=client_command_id, request_fingerprint=fingerprint,
    )
    db.add(event)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_cleaning_events_tenant_client_command_id":
            replay = _find_event()
            if replay is not None and replay.request_fingerprint == fingerprint:
                state = _lock_state(db, tenant_id=tenant_id, farm_id=farm_id, state_id=state_id)
                db.commit()
                return state, replay
            raise CleaningEventCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    before_state = state.current_state
    state.current_state = "cleaning_completed"
    state.state_changed_at = datetime.now(timezone.utc)
    state.state_changed_by_user_id = actor_user_id
    state.state_note = notes
    state.last_cleaning_event_id = event.id
    db.flush()

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="equipment_readiness.cleaning_recorded",
        entity_type="equipment_readiness_state", entity_id=state.id,
        event_data={
            "readiness_entity_type": state.entity_type, "readiness_entity_id": str(_entity_id(state)),
            "before_state": before_state, "after_state": "cleaning_completed",
            "cleaning_event_id": str(event.id), "result": result,
        },
    )
    db.commit()
    db.refresh(state)
    db.refresh(event)
    return state, event


def mark_ready(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, state_id: uuid.UUID,
    client_command_id: uuid.UUID, note: str | None = None,
) -> EquipmentReadinessState:
    def _validate(db: Session, state: EquipmentReadinessState) -> None:
        # `ready` is included so a fresh command re-confirming an
        # already-READY item (a genuine, different client_command_id, not
        # a replay -- replays are already handled before this runs)
        # succeeds as a no-op rather than being treated as an illegal
        # transition -- see docs/domain/EQUIPMENT_READINESS_MODEL.md.
        type_info = _type_info_for_state(db, tenant_id=tenant_id, farm_id=farm_id, state=state)
        if type_info.requires_cleaning:
            if state.current_state not in ("cleaning_completed", "unknown", "ready"):
                raise EquipmentReadinessInvalidTransitionError(
                    f"cannot mark_ready from state {state.current_state} (cleaning required)"
                )
            if state.current_state == "cleaning_completed" and state.last_cleaning_event_id is not None:
                last_event = db.get(CleaningEvent, state.last_cleaning_event_id)
                if last_event is not None and last_event.result != "completed":
                    raise EquipmentReadinessCleaningNotCompletedError(str(_entity_id(state)))
        elif state.current_state not in ("unknown", "ready", "awaiting_cleaning"):
            raise EquipmentReadinessInvalidTransitionError(
                f"cannot mark_ready from state {state.current_state}"
            )
        if state.entity_type == "carrier" and has_active_batch_carrier_assignment(
            db, tenant_id=tenant_id, carrier_id=state.carrier_id
        ):
            raise EquipmentReadinessCarrierInUseError(str(state.carrier_id))

    allowed_from = ("unknown", "cleaning_completed", "ready", "awaiting_cleaning")
    return _run_transition(
        db, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, state_id=state_id,
        client_command_id=client_command_id, verb="mark_ready", command_id_field="ready_client_command_id",
        fingerprint_field="ready_request_fingerprint",
        unique_constraint_name="ux_equipment_readiness_states_tenant_ready_command",
        allowed_from=allowed_from, target_state="ready", note=note,
        action="equipment_readiness.marked_ready", validate=_validate,
    )


def report_damage(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, state_id: uuid.UUID,
    client_command_id: uuid.UUID, note: str,
) -> EquipmentReadinessState:
    allowed_from = ("unknown", "awaiting_cleaning", "cleaning_completed", "ready", "maintenance")
    return _run_transition(
        db, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, state_id=state_id,
        client_command_id=client_command_id, verb="report_damage", command_id_field="damaged_client_command_id",
        fingerprint_field="damaged_request_fingerprint",
        unique_constraint_name="ux_equipment_readiness_states_tenant_damaged_command",
        allowed_from=allowed_from, target_state="damaged", note=note,
        action="equipment_readiness.damage_reported",
    )


def send_to_maintenance(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, state_id: uuid.UUID,
    client_command_id: uuid.UUID, note: str | None = None,
) -> EquipmentReadinessState:
    allowed_from = ("unknown", "awaiting_cleaning", "cleaning_completed", "ready", "damaged")
    return _run_transition(
        db, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, state_id=state_id,
        client_command_id=client_command_id, verb="send_to_maintenance",
        command_id_field="maintenance_client_command_id", fingerprint_field="maintenance_request_fingerprint",
        unique_constraint_name="ux_equipment_readiness_states_tenant_maintenance_command",
        allowed_from=allowed_from, target_state="maintenance", note=note,
        action="equipment_readiness.sent_to_maintenance",
    )


def return_from_maintenance(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, state_id: uuid.UUID,
    client_command_id: uuid.UUID, note: str | None = None,
) -> EquipmentReadinessState:
    def _target(db: Session, state: EquipmentReadinessState) -> str:
        type_info = _type_info_for_state(db, tenant_id=tenant_id, farm_id=farm_id, state=state)
        return "awaiting_cleaning" if type_info.requires_cleaning else "ready"

    fingerprint = _fingerprint(tenant_id, state_id, actor_user_id, "return_from_maintenance", note)

    def _find_by_command() -> EquipmentReadinessState | None:
        return db.execute(
            select(EquipmentReadinessState).where(
                EquipmentReadinessState.tenant_id == tenant_id,
                EquipmentReadinessState.return_from_maintenance_client_command_id == client_command_id,
            )
        ).scalar_one_or_none()

    existing = _find_by_command()
    if existing is not None:
        if existing.return_from_maintenance_request_fingerprint == fingerprint:
            return existing
        raise EquipmentReadinessCommandReusedWithDifferentPayloadError(str(client_command_id))

    state = _lock_state(db, tenant_id=tenant_id, farm_id=farm_id, state_id=state_id)

    existing = _find_by_command()
    if existing is not None:
        if existing.return_from_maintenance_request_fingerprint == fingerprint:
            return existing
        raise EquipmentReadinessCommandReusedWithDifferentPayloadError(str(client_command_id))

    if state.current_state != "maintenance":
        raise EquipmentReadinessInvalidTransitionError(
            f"cannot return_from_maintenance from state {state.current_state} (must be maintenance)"
        )

    target_state = _target(db, state)
    before_state = state.current_state
    state.current_state = target_state
    state.state_changed_at = datetime.now(timezone.utc)
    state.state_changed_by_user_id = actor_user_id
    state.state_note = note
    state.return_from_maintenance_client_command_id = client_command_id
    state.return_from_maintenance_request_fingerprint = fingerprint
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_equipment_readiness_states_tenant_return_maint_command":
            replay = _find_by_command()
            if replay is not None and replay.return_from_maintenance_request_fingerprint == fingerprint:
                return replay
            raise EquipmentReadinessCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id,
        action="equipment_readiness.returned_from_maintenance", entity_type="equipment_readiness_state",
        entity_id=state.id,
        event_data={
            "readiness_entity_type": state.entity_type, "readiness_entity_id": str(_entity_id(state)),
            "before_state": before_state, "after_state": target_state, "note": note,
        },
    )
    db.commit()
    db.refresh(state)
    return state


def retire(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, state_id: uuid.UUID,
    client_command_id: uuid.UUID, note: str | None = None,
) -> EquipmentReadinessState:
    """PART 6: RETIRED is terminal (`CLAUDE.md` rule 6) -- also moves the
    underlying Asset/Carrier's own registry `status` to `retired`, in the
    SAME flush/commit as the readiness transition itself (CLAUDE.md rule
    10: atomic commit) -- never two separate commits that could leave the
    two "retired" facts disagreeing if the process died between them. Not
    built on the generic `_run_transition` runner for exactly this reason
    -- that helper commits before this function would get a chance to also
    mutate the Asset/Carrier row."""
    allowed_from = ("unknown", "awaiting_cleaning", "cleaning_completed", "ready", "damaged", "maintenance")
    fingerprint = _fingerprint(tenant_id, state_id, actor_user_id, "retire", note)

    def _find_by_command() -> EquipmentReadinessState | None:
        return db.execute(
            select(EquipmentReadinessState).where(
                EquipmentReadinessState.tenant_id == tenant_id,
                EquipmentReadinessState.retire_client_command_id == client_command_id,
            )
        ).scalar_one_or_none()

    existing = _find_by_command()
    if existing is not None:
        if existing.retire_request_fingerprint == fingerprint:
            return existing
        raise EquipmentReadinessCommandReusedWithDifferentPayloadError(str(client_command_id))

    state = _lock_state(db, tenant_id=tenant_id, farm_id=farm_id, state_id=state_id)

    existing = _find_by_command()
    if existing is not None:
        if existing.retire_request_fingerprint == fingerprint:
            return existing
        raise EquipmentReadinessCommandReusedWithDifferentPayloadError(str(client_command_id))

    if state.current_state in READINESS_TERMINAL_STATES:
        raise EquipmentReadinessInvalidTransitionError(f"equipment readiness state {state_id} is retired (terminal)")
    if state.current_state not in allowed_from:
        raise EquipmentReadinessInvalidTransitionError(
            f"cannot retire from state {state.current_state} (allowed: {allowed_from})"
        )

    before_state = state.current_state
    state.current_state = "retired"
    state.state_changed_at = datetime.now(timezone.utc)
    state.state_changed_by_user_id = actor_user_id
    state.state_note = note
    state.retire_client_command_id = client_command_id
    state.retire_request_fingerprint = fingerprint

    if state.entity_type == "asset":
        asset = db.get(Asset, state.asset_id)
        if asset is not None and asset.status != "retired":
            asset.status = "retired"
            asset.retired_date = datetime.now(timezone.utc).date()
    else:
        carrier = db.get(Carrier, state.carrier_id)
        if carrier is not None and carrier.status != "retired":
            carrier.status = "retired"
            carrier.retired_date = datetime.now(timezone.utc).date()

    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_equipment_readiness_states_tenant_retire_command":
            replay = _find_by_command()
            if replay is not None and replay.retire_request_fingerprint == fingerprint:
                return replay
            raise EquipmentReadinessCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="equipment_readiness.retired",
        entity_type="equipment_readiness_state", entity_id=state.id,
        event_data={
            "readiness_entity_type": state.entity_type, "readiness_entity_id": str(_entity_id(state)),
            "before_state": before_state, "after_state": "retired", "note": note,
        },
    )
    db.commit()
    db.refresh(state)
    return state


# --- reads -----------------------------------------------------------------------


def list_readiness_history(
    db: Session, *, tenant_id: uuid.UUID, state_id: uuid.UUID
) -> list[AuditEvent]:
    return list(
        db.execute(
            select(AuditEvent)
            .where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.entity_type == "equipment_readiness_state",
                AuditEvent.entity_id == state_id,
            )
            .order_by(AuditEvent.recorded_time.asc())
        ).scalars().all()
    )


def list_cleaning_history(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, asset_id: uuid.UUID | None = None,
    carrier_id: uuid.UUID | None = None,
) -> list[CleaningEvent]:
    query = select(CleaningEvent).where(CleaningEvent.tenant_id == tenant_id, CleaningEvent.farm_id == farm_id)
    if asset_id is not None:
        query = query.where(CleaningEvent.asset_id == asset_id)
    if carrier_id is not None:
        query = query.where(CleaningEvent.carrier_id == carrier_id)
    query = query.order_by(CleaningEvent.effective_at.desc())
    return list(db.execute(query).scalars().all())


def list_awaiting_cleaning(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, limit: int = MAX_LIST_LIMIT
) -> list[EquipmentReadinessState]:
    """PART 19: the Cleaning Queue -- awaiting cleaning, plus cleaning
    completed but not yet released ready (both need floor attention)."""
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    query = (
        select(EquipmentReadinessState)
        .where(
            EquipmentReadinessState.tenant_id == tenant_id, EquipmentReadinessState.farm_id == farm_id,
            EquipmentReadinessState.current_state.in_(("awaiting_cleaning", "cleaning_completed")),
        )
        .order_by(EquipmentReadinessState.state_changed_at.asc())
        .limit(min(limit, MAX_LIST_LIMIT))
    )
    return list(db.execute(query).scalars().all())


def list_farm_readiness_states(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, states: list[str] | None = None,
    limit: int = MAX_LIST_LIMIT,
) -> list[EquipmentReadinessState]:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    query = select(EquipmentReadinessState).where(
        EquipmentReadinessState.tenant_id == tenant_id, EquipmentReadinessState.farm_id == farm_id
    )
    if states:
        query = query.where(EquipmentReadinessState.current_state.in_(states))
    query = query.order_by(EquipmentReadinessState.state_changed_at.desc()).limit(min(limit, MAX_LIST_LIMIT))
    return list(db.execute(query).scalars().all())


def get_ready_asset_ids(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, asset_type_id: uuid.UUID) -> set[uuid.UUID]:
    """Ready-equipment queue helper (PART 16): every Asset of the given
    type whose readiness is currently allocation-eligible (`ready` or
    `unknown` -- see the pilot transition rule in
    docs/domain/EQUIPMENT_READINESS_MODEL.md), or which is not
    readiness-tracked at all (no row -- unaffected by this filter)."""
    non_ready_asset_ids = set(db.execute(non_ready_asset_ids_subquery(tenant_id=tenant_id, farm_id=farm_id)).scalars())
    all_asset_ids = set(
        db.execute(
            select(Asset.id).where(
                Asset.tenant_id == tenant_id, Asset.farm_id == farm_id, Asset.asset_type_id == asset_type_id,
                Asset.status == "active",
            )
        ).scalars()
    )
    return all_asset_ids - non_ready_asset_ids


# PART 17: leaving CLEANING_COMPLETED out of this list would let a cleaned
# -but-not-yet-released item silently allocate, contradicting "Cleaning
# Completed != Ready" -- see docs/domain/EQUIPMENT_READINESS_MODEL.md.
NON_READY_STATES = ("awaiting_cleaning", "cleaning_completed", "damaged", "maintenance", "retired")


def non_ready_carrier_ids_subquery(*, tenant_id: uuid.UUID, farm_id: uuid.UUID):
    """PART 16/17: the one filter every "available Carrier" read applies
    (`Carrier.id.not_in(non_ready_carrier_ids_subquery(...))`) -- READY and
    UNKNOWN remain eligible per the pilot transition rule (see the domain
    doc). A Carrier with no readiness row at all (non-readiness-tracked
    type) is never included here and is therefore unaffected."""
    return select(EquipmentReadinessState.carrier_id).where(
        EquipmentReadinessState.tenant_id == tenant_id, EquipmentReadinessState.farm_id == farm_id,
        EquipmentReadinessState.entity_type == "carrier",
        EquipmentReadinessState.current_state.in_(NON_READY_STATES),
    )


def non_ready_asset_ids_subquery(*, tenant_id: uuid.UUID, farm_id: uuid.UUID):
    """Asset counterpart of `non_ready_carrier_ids_subquery`."""
    return select(EquipmentReadinessState.asset_id).where(
        EquipmentReadinessState.tenant_id == tenant_id, EquipmentReadinessState.farm_id == farm_id,
        EquipmentReadinessState.entity_type == "asset",
        EquipmentReadinessState.current_state.in_(NON_READY_STATES),
    )
