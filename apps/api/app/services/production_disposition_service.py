"""LEAFY-OPS-001: Production Biological Disposition & Authoritative Living
Population.

Adds biological quantity-reducing facts against a Production Cultivation
Plate's `BatchCarrierAssignment`, after the Nursery -> Leafy Production
transplant (NURSERY-OPS-005B) opens it. `TransplantDestinationLine.
assigned_plant_count` remains the sole, immutable opening-population
authority for a lineage's ROOT assignment -- this module never rewrites it
and never introduces a second opening-population table (see
`BatchCarrierPopulationCheckpoint`'s own docstring for the architectural
reason a running-balance/checkpoint table is unnecessary here).

Two kinds of immutable, insert-only `ProductionDispositionEvent` rows:

- REDUCTION (`quantity_delta < 0`): living plants that stopped continuing in
  a Plate's authoritative population (death, disease/pest/mechanical
  removal, quality removal, or another explicit biological removal). A
  weak/small/stressed/diseased-but-retained/off-spec plant is NOT removed
  from population merely by being observed as such -- only an explicit
  disposition command does that.
- REVERSAL (`quantity_delta > 0`): the EXACT negation of one specific,
  named prior REDUCTION (`reverses_event_id`) -- accounting correction,
  never biological resurrection.

Authoritative living population is never persisted -- always
`TransplantDestinationLine.assigned_plant_count` (for the lineage's ROOT
BatchCarrierAssignment) + `SUM(quantity_delta)` across every event sharing
that root, regardless of how many times the Plate's biological assignment
has been exhausted (population reaches exactly zero -> BCA released) and
restored (a correction reopens positive population -> a NEW BCA generation
is created, NEVER the historical released one, chained via
`restored_from_batch_carrier_assignment_id` and sharing the same
`population_root_batch_carrier_assignment_id`). See
`BatchCarrierAssignment.population_root_batch_carrier_assignment_id`'s own
model docstring and the `a5c9e21f7b64` migration for the full lineage
design and its A -> B -> C worked proof.

A `ProductionDispositionCommand` is the logical operator-command header,
mirroring `SeedlingDispositionCommand`'s own header-plus-variable-child-
events shape: a RECORD command always produces exactly one REDUCTION; a
CORRECT command always produces exactly one REVERSAL and, optionally, one
replacement REDUCTION -- both committed atomically, in one transaction.

Frozen product decisions (LEAFY-OPS-001 BUILD ticket): disposition is
allowed whenever the Production Cultivation Plate BCA is active, even while
the CropBatch remains formally in a pre-production WorkflowStage category
(mixed Nursery+Production placement is legal, per NURSERY-OPS-005B); Quality
Hold never blocks a truthful disposition; disposition never writes Movement
or Occupancy, and a missing/unexpected current Occupancy never blocks a
biologically valid disposition (informational context only)."""

import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.carrier import Carrier
from app.models.carrier_type import CarrierType
from app.models.crop_batch import CropBatch
from app.models.production_disposition_command import ProductionDispositionCommand
from app.models.production_disposition_event import ProductionDispositionEvent
from app.models.production_disposition_event_grow_cube import ProductionDispositionEventGrowCube
from app.models.production_disposition_reason import ProductionDispositionReason
from app.services import farm_service, leafy_population_service
from app.services.audit import append_audit_event
from app.services.errors import (
    BatchCarrierAssignmentNotFoundError,
    CropBatchClosedError,
    FarmNotFoundError,
    InvalidProductionDispositionEffectiveTimeError,
    InvalidProductionDispositionReasonError,
    NoPopulationRootError,
    ProductionDispositionAlreadyCorrectedError,
    ProductionDispositionAssignmentReleasedError,
    ProductionDispositionBalanceError,
    ProductionDispositionCarrierReusedError,
    ProductionDispositionCommandReusedWithDifferentPayloadError,
    ProductionDispositionEventNotFoundError,
    ProductionDispositionGrowCubeAlreadyDisposedError,
    ProductionDispositionGrowCubeNotInAssignmentError,
    ProductionDispositionNotReductionError,
    ProductionDispositionValidationError,
    UnsupportedProductionDispositionCarrierTypeError,
)

OTHER_REASON_CODE = "other"
PRODUCTION_CULTIVATION_PLATE_CARRIER_TYPE_CODE = "production_cultivation_plate"
# VINES-OPS-002
GROW_BAG_CARRIER_TYPE_CODE = "grow_bag"
_GROW_CUBE_ALREADY_DISPOSED_MARKER = "CMP-DOMAIN-VINES-001 grow cube already disposed"


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
    return leafy_population_service.is_balance_violation_error(exc)


def _compute_record_fingerprint(
    *, tenant_id, farm_id, actor_user_id, batch_carrier_assignment_id, plant_loss_count, reason_code,
    effective_time: datetime, note: str | None,
) -> str:
    parts = [
        "RECORD", str(tenant_id), str(farm_id), str(actor_user_id) if actor_user_id else "",
        str(batch_carrier_assignment_id), str(plant_loss_count), reason_code,
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
            "replace", str(corrected["plant_loss_count"]), corrected["reason_code"],
            corrected["effective_time"].astimezone(timezone.utc).isoformat(), corrected.get("note") or "",
        ]
    parts = [
        "CORRECT", str(tenant_id), str(farm_id), str(actor_user_id) if actor_user_id else "",
        str(target_event_id), *corrected_parts,
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _compute_grow_cube_record_fingerprint(
    *, tenant_id, farm_id, actor_user_id, batch_carrier_assignment_id, grow_cube_carrier_ids: list[uuid.UUID],
    reason_code, effective_time: datetime, note: str | None,
) -> str:
    """VINES-OPS-002: the Vines-side sibling of `_compute_record_fingerprint`
    -- adds the sorted (order-independent) set of specific Grow Cube ids so
    an idempotent replay is only ever recognized for the exact same set of
    named plants, never merely the same count."""
    parts = [
        "RECORD_GROW_CUBE", str(tenant_id), str(farm_id), str(actor_user_id) if actor_user_id else "",
        str(batch_carrier_assignment_id), ",".join(sorted(str(gid) for gid in grow_cube_carrier_ids)),
        reason_code, effective_time.astimezone(timezone.utc).isoformat(), note or "",
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _find_existing_command(
    db: Session, *, tenant_id: uuid.UUID, client_command_id: uuid.UUID
) -> ProductionDispositionCommand | None:
    return db.execute(
        select(ProductionDispositionCommand).where(
            ProductionDispositionCommand.tenant_id == tenant_id,
            ProductionDispositionCommand.client_command_id == client_command_id,
        )
    ).scalar_one_or_none()


# HARVEST-OPS-001: these four resolvers now live in leafy_population_service
# (the ONE shared authoritative calculation Plant Loss and Harvest both
# use) -- re-exported here under their original names so every existing
# caller/test (`production_disposition_service.get_current_living_population(...)`
# etc.) keeps working byte-for-byte. `get_current_living_population` now
# correctly includes HarvestPopulationEvent deltas too, which is a no-op
# change for any lineage with no Harvest history (LEAFY-OPS-001's own
# behavior is unchanged).
get_root_opening_population = leafy_population_service.get_root_opening_population
get_current_living_population = leafy_population_service.get_current_living_population
resolve_active_assignment_id_for_root = leafy_population_service.resolve_active_assignment_id_for_root
resolve_lineage_tip_assignment_id = leafy_population_service.resolve_lineage_tip_assignment_id


def _validate_chronological_balance(
    db: Session, *, root_batch_carrier_assignment_id: uuid.UUID, opening: int,
    new_effective_time: datetime, new_delta: int, exclude_event_id: uuid.UUID | None = None,
) -> None:
    leafy_population_service.validate_chronological_balance(
        db, root_batch_carrier_assignment_id=root_batch_carrier_assignment_id, opening=opening,
        new_effective_time=new_effective_time, new_delta=new_delta,
        exclude_production_disposition_event_id=exclude_event_id,
    )


def _require_production_cultivation_plate(db: Session, *, carrier_id: uuid.UUID) -> None:
    carrier_type_code = db.execute(
        select(CarrierType.code).join(Carrier, Carrier.carrier_type_id == CarrierType.id).where(
            Carrier.id == carrier_id
        )
    ).scalar_one_or_none()
    if carrier_type_code != PRODUCTION_CULTIVATION_PLATE_CARRIER_TYPE_CODE:
        raise UnsupportedProductionDispositionCarrierTypeError(str(carrier_id))


def _require_grow_bag(db: Session, *, carrier_id: uuid.UUID) -> None:
    """VINES-OPS-002: the Vines-side sibling of `_require_production_
    cultivation_plate` -- record_disposition's own carrier-type gate stays
    untouched (zero regression risk to LEAFY-OPS-001); `record_grow_cube_
    disposition` uses this one instead. The underlying population-root/
    ledger mechanism is carrier-agnostic either way (see this module's own
    docstring)."""
    carrier_type_code = db.execute(
        select(CarrierType.code).join(Carrier, Carrier.carrier_type_id == CarrierType.id).where(
            Carrier.id == carrier_id
        )
    ).scalar_one_or_none()
    if carrier_type_code != GROW_BAG_CARRIER_TYPE_CODE:
        raise UnsupportedProductionDispositionCarrierTypeError(str(carrier_id))


def _to_event_read_dict(event: ProductionDispositionEvent, *, is_reversed: bool, actor_user_id: uuid.UUID | None) -> dict:
    return {
        "id": event.id, "command_id": event.command_id,
        "batch_carrier_assignment_id": event.batch_carrier_assignment_id,
        "population_root_batch_carrier_assignment_id": event.population_root_batch_carrier_assignment_id,
        "event_kind": event.event_kind, "reason_code": event.reason_code,
        "quantity_delta": event.quantity_delta, "plant_loss_quantity": max(0, -event.quantity_delta),
        "effective_time": event.effective_time, "recorded_at": event.recorded_at, "note": event.note,
        "reverses_event_id": event.reverses_event_id, "corrects_event_id": event.corrects_event_id,
        "is_reversed": is_reversed, "actor_user_id": actor_user_id,
    }


# --- RECORD ------------------------------------------------------------------------


def record_disposition(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_command_id: uuid.UUID,
    batch_carrier_assignment_id: uuid.UUID,
    plant_loss_count: int,
    reason_code: str,
    effective_time: datetime,
    note: str | None,
) -> ProductionDispositionCommand:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    fingerprint = _compute_record_fingerprint(
        tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id,
        batch_carrier_assignment_id=batch_carrier_assignment_id, plant_loss_count=plant_loss_count,
        reason_code=reason_code, effective_time=effective_time, note=note,
    )

    existing = _find_existing_command(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise ProductionDispositionCommandReusedWithDifferentPayloadError(str(client_command_id))

    if effective_time > datetime.now(timezone.utc):
        raise InvalidProductionDispositionEffectiveTimeError("effective_time cannot be in the future")
    if reason_code == OTHER_REASON_CODE and _blank(note):
        raise ProductionDispositionValidationError("'other' requires a non-blank note")

    assignment = db.execute(
        select(BatchCarrierAssignment).where(
            BatchCarrierAssignment.id == batch_carrier_assignment_id,
            BatchCarrierAssignment.tenant_id == tenant_id,
            BatchCarrierAssignment.farm_id == farm_id,
        )
    ).scalar_one_or_none()
    if assignment is None:
        raise BatchCarrierAssignmentNotFoundError(str(batch_carrier_assignment_id))

    # Lock the owning CropBatch FIRST -- same lock target/order established
    # throughout this codebase (seedling_entry_service, observation_service,
    # seedling_disposition_service).
    db.execute(select(CropBatch.id).where(CropBatch.id == assignment.batch_id).with_for_update()).scalar_one()

    existing = _find_existing_command(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise ProductionDispositionCommandReusedWithDifferentPayloadError(str(client_command_id))

    batch = db.execute(select(CropBatch).where(CropBatch.id == assignment.batch_id)).scalar_one()
    if batch.state != "active":
        raise CropBatchClosedError(str(batch.id))

    _require_production_cultivation_plate(db, carrier_id=assignment.carrier_id)

    root_id = assignment.population_root_batch_carrier_assignment_id
    if root_id is None:
        raise NoPopulationRootError(str(batch_carrier_assignment_id))

    active_id = resolve_active_assignment_id_for_root(db, root_batch_carrier_assignment_id=root_id)
    if active_id is None or active_id != assignment.id:
        raise ProductionDispositionAssignmentReleasedError(str(batch_carrier_assignment_id))

    reason_exists = db.execute(
        select(ProductionDispositionReason.code).where(ProductionDispositionReason.code == reason_code)
    ).scalar_one_or_none()
    if reason_exists is None:
        raise InvalidProductionDispositionReasonError(reason_code)

    if effective_time < assignment.assigned_effective_time:
        raise InvalidProductionDispositionEffectiveTimeError(
            "effective_time precedes the assignment's assigned_effective_time"
        )

    opening = get_root_opening_population(db, root_batch_carrier_assignment_id=root_id)
    _validate_chronological_balance(
        db, root_batch_carrier_assignment_id=root_id, opening=opening,
        new_effective_time=effective_time, new_delta=-plant_loss_count,
    )
    previous_population = get_current_living_population(db, root_batch_carrier_assignment_id=root_id)

    command = ProductionDispositionCommand(
        id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, batch_id=batch.id,
        batch_carrier_assignment_id=assignment.id, operation_kind="RECORD", target_event_id=None,
        actor_user_id=actor_user_id, client_command_id=client_command_id, request_fingerprint=fingerprint,
    )
    db.add(command)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_production_disposition_commands_tenant_client_command_id":
            replay = _find_existing_command(db, tenant_id=tenant_id, client_command_id=client_command_id)
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise ProductionDispositionCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    event = ProductionDispositionEvent(
        id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, command_id=command.id,
        batch_carrier_assignment_id=assignment.id, population_root_batch_carrier_assignment_id=root_id,
        event_kind="REDUCTION", reason_code=reason_code, quantity_delta=-plant_loss_count,
        effective_time=effective_time, note=note, reverses_event_id=None, corrects_event_id=None,
    )
    db.add(event)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _is_balance_violation_error(exc):
            raise ProductionDispositionBalanceError(
                "recording this event would violate the chronological authoritative living-population balance"
            ) from exc
        raise

    released_assignment_id: uuid.UUID | None = None
    available_after = get_current_living_population(
        db, root_batch_carrier_assignment_id=root_id, as_of=effective_time
    )
    if available_after == 0:
        assignment.released_effective_time = effective_time
        assignment.released_by_production_disposition_event_id = event.id
        db.flush()
        released_assignment_id = assignment.id

    resulting_population = get_current_living_population(db, root_batch_carrier_assignment_id=root_id)

    audit_data = {
        "command_id": str(command.id), "client_command_id": str(client_command_id),
        "batch_carrier_assignment_id": str(batch_carrier_assignment_id),
        "population_root_batch_carrier_assignment_id": str(root_id),
        "reason_code": reason_code, "plant_loss_count": plant_loss_count,
        "effective_time": effective_time.isoformat(),
        "previous_living_population": previous_population, "resulting_living_population": resulting_population,
    }
    if released_assignment_id is not None:
        audit_data["released_assignment_id"] = str(released_assignment_id)

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id,
        action="crop_batch.production_disposition_recorded",
        entity_type="production_disposition_event", entity_id=event.id, event_data=audit_data,
    )
    db.commit()
    db.refresh(command)
    return command


# --- RECORD (Vines, specific Grow Cube identity) ----------------------------------


def _grow_cube_carrier_ids_placed_in_assignment(
    db: Session, *, destination_batch_carrier_assignment_id: uuid.UUID
) -> set[uuid.UUID]:
    """VINES-OPS-002: every Grow Cube this specific Grow Bag's own
    BatchCarrierAssignment was populated with -- walked via the same
    already-proven `TransplantDestinationLine`/`TransplantAllocation`/
    `TransplantSourceLine` chain `vines_production_transfer_service.
    list_vines_production_placement_grow_bags` already reads (a Grow Bag is
    filled exactly once, by its one Vines Production Transfer -- no later
    re-fill exists in this ticket's scope)."""
    rows = db.execute(
        text(
            "SELECT DISTINCT tsl.source_carrier_id AS grow_cube_carrier_id "
            "FROM transplant_destination_lines tdl "
            "JOIN transplant_allocations ta ON ta.destination_line_id = tdl.id "
            "JOIN transplant_source_lines tsl ON tsl.id = ta.source_line_id "
            "WHERE tdl.destination_batch_carrier_assignment_id = :assignment_id"
        ),
        {"assignment_id": destination_batch_carrier_assignment_id},
    ).scalars().all()
    return set(rows)


def get_grow_cube_disposition_status(
    db: Session, *, grow_cube_carrier_ids: list[uuid.UUID] | set[uuid.UUID],
) -> dict[uuid.UUID, dict]:
    """VINES-OPS-002: for each of the given Grow Cube carrier ids that has a
    non-reversed disposition REDUCTION recorded against it, the disposing
    event's own facts (reason, effective time, actor) -- read-model support
    shared by every Vines population/drill-down/history read, so "living"
    vs. "removed" is always resolved via this ONE query shape, never
    reimplemented ad hoc. A ``grow_cube_carrier_id`` absent from the returned
    dict is currently living."""
    if not grow_cube_carrier_ids:
        return {}
    rows = db.execute(
        text(
            "SELECT gc.grow_cube_carrier_id, e.id AS event_id, e.reason_code, e.effective_time, e.note, "
            "c.actor_user_id "
            "FROM production_disposition_event_grow_cubes gc "
            "JOIN production_disposition_events e ON e.id = gc.production_disposition_event_id "
            "JOIN production_disposition_commands c ON c.id = e.command_id "
            "WHERE gc.grow_cube_carrier_id = ANY(:ids) AND e.event_kind = 'REDUCTION' "
            "AND NOT EXISTS (SELECT 1 FROM production_disposition_events r WHERE r.reverses_event_id = e.id)"
        ),
        {"ids": list(grow_cube_carrier_ids)},
    ).mappings().all()
    return {
        r["grow_cube_carrier_id"]: {
            "event_id": r["event_id"], "reason_code": r["reason_code"], "effective_time": r["effective_time"],
            "note": r["note"], "actor_user_id": r["actor_user_id"],
        }
        for r in rows
    }


def get_grow_cube_disposition_event_carriers(
    db: Session, *, production_disposition_event_id: uuid.UUID,
) -> list[dict]:
    """VINES-OPS-002: the specific Grow Cube(s) one REDUCTION event named, in
    `carrier.code` order -- read-model support for rendering a RECORD/CORRECT
    command result. Empty for a REVERSAL (see `ProductionDispositionEventGrowCube`'s
    own docstring). Returns plain dicts (never a Pydantic schema type) --
    this module stays a service layer; the API layer owns response shaping."""
    rows = db.execute(
        text(
            "SELECT carrier.id, carrier.code, ct.id AS carrier_type_id, ct.code AS carrier_type_code, "
            "ct.name AS carrier_type_name "
            "FROM production_disposition_event_grow_cubes gc "
            "JOIN carriers carrier ON carrier.id = gc.grow_cube_carrier_id "
            "JOIN carrier_types ct ON ct.id = carrier.carrier_type_id "
            "WHERE gc.production_disposition_event_id = :event_id "
            "ORDER BY carrier.code"
        ),
        {"event_id": production_disposition_event_id},
    ).mappings().all()
    return [dict(r) for r in rows]


def record_grow_cube_disposition(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_command_id: uuid.UUID,
    batch_carrier_assignment_id: uuid.UUID,
    grow_cube_carrier_ids: list[uuid.UUID],
    reason_code: str,
    effective_time: datetime,
    note: str | None,
) -> ProductionDispositionCommand:
    """VINES-OPS-002: the Vines-side sibling of `record_disposition` --
    same RECORD-command-produces-exactly-one-REDUCTION shape, same
    population-root/balance/audit/commit mechanics (all already carrier-
    agnostic), targeting a `grow_bag` BatchCarrierAssignment instead of a
    `production_cultivation_plate` one. The one genuinely new step: the
    REDUCTION additionally names the exact Grow Cube(s) (one living plant
    each) it removed, via `ProductionDispositionEventGrowCube` rows, so a
    multi-plant Grow Bag's own loss is never a bare, ambiguous count. Kept as
    its own function (rather than widening `record_disposition` itself) to
    keep LEAFY-OPS-001's own proven RECORD path byte-for-byte unmodified."""
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    if not grow_cube_carrier_ids:
        raise ProductionDispositionValidationError("at least one grow_cube_carrier_id is required")
    if len(set(grow_cube_carrier_ids)) != len(grow_cube_carrier_ids):
        raise ProductionDispositionValidationError("grow_cube_carrier_ids must not contain duplicates")
    plant_loss_count = len(grow_cube_carrier_ids)

    fingerprint = _compute_grow_cube_record_fingerprint(
        tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id,
        batch_carrier_assignment_id=batch_carrier_assignment_id, grow_cube_carrier_ids=grow_cube_carrier_ids,
        reason_code=reason_code, effective_time=effective_time, note=note,
    )

    existing = _find_existing_command(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise ProductionDispositionCommandReusedWithDifferentPayloadError(str(client_command_id))

    if effective_time > datetime.now(timezone.utc):
        raise InvalidProductionDispositionEffectiveTimeError("effective_time cannot be in the future")
    if reason_code == OTHER_REASON_CODE and _blank(note):
        raise ProductionDispositionValidationError("'other' requires a non-blank note")

    assignment = db.execute(
        select(BatchCarrierAssignment).where(
            BatchCarrierAssignment.id == batch_carrier_assignment_id,
            BatchCarrierAssignment.tenant_id == tenant_id,
            BatchCarrierAssignment.farm_id == farm_id,
        )
    ).scalar_one_or_none()
    if assignment is None:
        raise BatchCarrierAssignmentNotFoundError(str(batch_carrier_assignment_id))

    # Same CropBatch-first lock order as record_disposition -- this is also
    # what makes "two operators dispose the same Grow Cube" serialize
    # correctly: a Grow Cube belongs to exactly one Batch, so both commands
    # always contend for the same row here before either re-checks "already
    # disposed" below.
    db.execute(select(CropBatch.id).where(CropBatch.id == assignment.batch_id).with_for_update()).scalar_one()

    existing = _find_existing_command(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise ProductionDispositionCommandReusedWithDifferentPayloadError(str(client_command_id))

    batch = db.execute(select(CropBatch).where(CropBatch.id == assignment.batch_id)).scalar_one()
    if batch.state != "active":
        raise CropBatchClosedError(str(batch.id))

    _require_grow_bag(db, carrier_id=assignment.carrier_id)

    root_id = assignment.population_root_batch_carrier_assignment_id
    if root_id is None:
        raise NoPopulationRootError(str(batch_carrier_assignment_id))

    active_id = resolve_active_assignment_id_for_root(db, root_batch_carrier_assignment_id=root_id)
    if active_id is None or active_id != assignment.id:
        raise ProductionDispositionAssignmentReleasedError(str(batch_carrier_assignment_id))

    reason_exists = db.execute(
        select(ProductionDispositionReason.code).where(ProductionDispositionReason.code == reason_code)
    ).scalar_one_or_none()
    if reason_exists is None:
        raise InvalidProductionDispositionReasonError(reason_code)

    if effective_time < assignment.assigned_effective_time:
        raise InvalidProductionDispositionEffectiveTimeError(
            "effective_time precedes the assignment's assigned_effective_time"
        )

    # Grow Cube placement is a one-time historical fact recorded against the
    # population lineage's ROOT `TransplantDestinationLine` only -- a
    # correction-restored generation (a NEW BatchCarrierAssignment, see
    # `production_disposition_service.correct_disposition`'s own docstring)
    # never gets a TransplantDestinationLine of its own, so this must always
    # resolve via `root_id`, never `assignment.id`.
    placed_ids = _grow_cube_carrier_ids_placed_in_assignment(
        db, destination_batch_carrier_assignment_id=root_id
    )
    requested_ids = set(grow_cube_carrier_ids)
    not_placed = requested_ids - placed_ids
    if not_placed:
        raise ProductionDispositionGrowCubeNotInAssignmentError(
            f"grow_cube_carrier_id(s) not placed in this Grow Bag: {sorted(str(i) for i in not_placed)}"
        )
    already_disposed = get_grow_cube_disposition_status(db, grow_cube_carrier_ids=requested_ids)
    if already_disposed:
        raise ProductionDispositionGrowCubeAlreadyDisposedError(
            f"grow_cube_carrier_id(s) already disposed: {sorted(str(i) for i in already_disposed)}"
        )

    opening = get_root_opening_population(db, root_batch_carrier_assignment_id=root_id)
    _validate_chronological_balance(
        db, root_batch_carrier_assignment_id=root_id, opening=opening,
        new_effective_time=effective_time, new_delta=-plant_loss_count,
    )
    previous_population = get_current_living_population(db, root_batch_carrier_assignment_id=root_id)

    command = ProductionDispositionCommand(
        id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, batch_id=batch.id,
        batch_carrier_assignment_id=assignment.id, operation_kind="RECORD", target_event_id=None,
        actor_user_id=actor_user_id, client_command_id=client_command_id, request_fingerprint=fingerprint,
    )
    db.add(command)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_production_disposition_commands_tenant_client_command_id":
            replay = _find_existing_command(db, tenant_id=tenant_id, client_command_id=client_command_id)
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise ProductionDispositionCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    event = ProductionDispositionEvent(
        id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, command_id=command.id,
        batch_carrier_assignment_id=assignment.id, population_root_batch_carrier_assignment_id=root_id,
        event_kind="REDUCTION", reason_code=reason_code, quantity_delta=-plant_loss_count,
        effective_time=effective_time, note=note, reverses_event_id=None, corrects_event_id=None,
    )
    db.add(event)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _is_balance_violation_error(exc):
            raise ProductionDispositionBalanceError(
                "recording this event would violate the chronological authoritative living-population balance"
            ) from exc
        raise

    for grow_cube_carrier_id in grow_cube_carrier_ids:
        db.add(
            ProductionDispositionEventGrowCube(
                id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, production_disposition_event_id=event.id,
                grow_cube_carrier_id=grow_cube_carrier_id,
            )
        )
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        orig = getattr(exc, "orig", None)
        diag = getattr(orig, "diag", None)
        message = getattr(diag, "message_primary", None) or str(orig or exc)
        if _GROW_CUBE_ALREADY_DISPOSED_MARKER in message:
            raise ProductionDispositionGrowCubeAlreadyDisposedError(
                "one or more grow_cube_carrier_id(s) were disposed by a concurrent command"
            ) from exc
        raise

    released_assignment_id: uuid.UUID | None = None
    available_after = get_current_living_population(
        db, root_batch_carrier_assignment_id=root_id, as_of=effective_time
    )
    if available_after == 0:
        assignment.released_effective_time = effective_time
        assignment.released_by_production_disposition_event_id = event.id
        db.flush()
        released_assignment_id = assignment.id

    resulting_population = get_current_living_population(db, root_batch_carrier_assignment_id=root_id)

    audit_data = {
        "command_id": str(command.id), "client_command_id": str(client_command_id),
        "batch_carrier_assignment_id": str(batch_carrier_assignment_id),
        "population_root_batch_carrier_assignment_id": str(root_id),
        "reason_code": reason_code, "plant_loss_count": plant_loss_count,
        "grow_cube_carrier_ids": [str(i) for i in grow_cube_carrier_ids],
        "effective_time": effective_time.isoformat(),
        "previous_living_population": previous_population, "resulting_living_population": resulting_population,
    }
    if released_assignment_id is not None:
        audit_data["released_assignment_id"] = str(released_assignment_id)

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id,
        action="crop_batch.vines_grow_cube_disposition_recorded",
        entity_type="production_disposition_event", entity_id=event.id, event_data=audit_data,
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
) -> ProductionDispositionCommand:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    fingerprint = _compute_correct_fingerprint(
        tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id,
        target_event_id=target_event_id, corrected=corrected,
    )

    existing = _find_existing_command(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise ProductionDispositionCommandReusedWithDifferentPayloadError(str(client_command_id))

    if corrected is not None:
        if corrected["effective_time"] > datetime.now(timezone.utc):
            raise InvalidProductionDispositionEffectiveTimeError("effective_time cannot be in the future")
        if corrected["reason_code"] == OTHER_REASON_CODE and _blank(corrected.get("note")):
            raise ProductionDispositionValidationError("'other' requires a non-blank note")

    target = db.execute(
        select(ProductionDispositionEvent).where(
            ProductionDispositionEvent.id == target_event_id,
            ProductionDispositionEvent.tenant_id == tenant_id,
            ProductionDispositionEvent.farm_id == farm_id,
        )
    ).scalar_one_or_none()
    if target is None:
        raise ProductionDispositionEventNotFoundError(str(target_event_id))

    root_id = target.population_root_batch_carrier_assignment_id

    # Section 34-equivalent: CropBatch first.
    batch_id = db.execute(
        select(ProductionDispositionCommand.batch_id).where(ProductionDispositionCommand.id == target.command_id)
    ).scalar_one()
    batch = db.execute(select(CropBatch).where(CropBatch.id == batch_id).with_for_update()).scalar_one()

    existing = _find_existing_command(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise ProductionDispositionCommandReusedWithDifferentPayloadError(str(client_command_id))

    if batch.state != "active":
        raise CropBatchClosedError(str(batch.id))

    if target.event_kind != "REDUCTION":
        raise ProductionDispositionNotReductionError(str(target_event_id))
    already_corrected = db.execute(
        select(ProductionDispositionEvent.id).where(ProductionDispositionEvent.reverses_event_id == target.id)
    ).scalar_one_or_none()
    if already_corrected is not None:
        raise ProductionDispositionAlreadyCorrectedError(str(target_event_id))

    target_assignment = db.execute(
        select(BatchCarrierAssignment).where(BatchCarrierAssignment.id == target.batch_carrier_assignment_id)
    ).scalar_one()

    # LEAFY-OPS-001 BUILD section 15: CASE A (target did not exhaust its
    # BCA) vs CASE B (target DID exhaust it, so its BCA is released).
    active_id = resolve_active_assignment_id_for_root(db, root_batch_carrier_assignment_id=root_id)
    predecessor_to_restore: BatchCarrierAssignment | None = None
    assignment: BatchCarrierAssignment | None
    if active_id is not None:
        # CASE A: some generation is still active. The REVERSAL always
        # references the target's own generation (target_assignment);
        # since the target did not exhaust it (an already-released
        # generation is never the active one), target_assignment IS the
        # active one, and no restoration occurs.
        assignment = db.execute(
            select(BatchCarrierAssignment).where(BatchCarrierAssignment.id == active_id)
        ).scalar_one()
    else:
        # CASE B: the whole lineage is currently exhausted. Restoration is
        # permitted ONLY when the lineage tip was released by the EXACT
        # target event being corrected.
        tip_id = resolve_lineage_tip_assignment_id(db, root_batch_carrier_assignment_id=root_id)
        tip = db.execute(select(BatchCarrierAssignment).where(BatchCarrierAssignment.id == tip_id)).scalar_one()
        if tip.released_by_production_disposition_event_id != target.id:
            raise ProductionDispositionAssignmentReleasedError(str(target.batch_carrier_assignment_id))
        predecessor_to_restore = tip
        assignment = None

    assignment_for_floor = assignment if assignment is not None else predecessor_to_restore

    if corrected is not None:
        reason_exists = db.execute(
            select(ProductionDispositionReason.code).where(
                ProductionDispositionReason.code == corrected["reason_code"]
            )
        ).scalar_one_or_none()
        if reason_exists is None:
            raise InvalidProductionDispositionReasonError(corrected["reason_code"])
        if corrected["effective_time"] < assignment_for_floor.assigned_effective_time:
            raise InvalidProductionDispositionEffectiveTimeError(
                "effective_time precedes the assignment's assigned_effective_time"
            )
        opening = get_root_opening_population(db, root_batch_carrier_assignment_id=root_id)
        _validate_chronological_balance(
            db, root_batch_carrier_assignment_id=root_id, opening=opening,
            new_effective_time=corrected["effective_time"], new_delta=-corrected["plant_loss_count"],
            exclude_event_id=target.id,
        )

    # Carrier lock -- terminal-tier, only when actually restoring.
    if predecessor_to_restore is not None:
        carrier = db.execute(
            select(Carrier).where(Carrier.id == predecessor_to_restore.carrier_id).with_for_update()
        ).scalar_one()
        if carrier.latest_batch_carrier_assignment_id != predecessor_to_restore.id:
            raise ProductionDispositionCarrierReusedError(str(predecessor_to_restore.carrier_id))

    previous_population = get_current_living_population(db, root_batch_carrier_assignment_id=root_id)

    command = ProductionDispositionCommand(
        id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, batch_id=batch.id,
        batch_carrier_assignment_id=target.batch_carrier_assignment_id, operation_kind="CORRECT",
        target_event_id=target.id, actor_user_id=actor_user_id, client_command_id=client_command_id,
        request_fingerprint=fingerprint,
    )
    db.add(command)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_production_disposition_commands_tenant_client_command_id":
            replay = _find_existing_command(db, tenant_id=tenant_id, client_command_id=client_command_id)
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise ProductionDispositionCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    # LEAFY-OPS-001 BUILD section 15: REVERSAL always references the
    # target's own BCA generation.
    reversal = ProductionDispositionEvent(
        id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, command_id=command.id,
        batch_carrier_assignment_id=target.batch_carrier_assignment_id,
        population_root_batch_carrier_assignment_id=root_id, event_kind="REVERSAL",
        reason_code=target.reason_code, quantity_delta=-target.quantity_delta, effective_time=target.effective_time,
        note=None, reverses_event_id=target.id, corrects_event_id=None,
    )
    db.add(reversal)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_production_disposition_events_reverses_once":
            raise ProductionDispositionAlreadyCorrectedError(str(target_event_id)) from exc
        raise

    restored_assignment_id: uuid.UUID | None = None
    if predecessor_to_restore is not None:
        assignment = BatchCarrierAssignment(
            id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, batch_id=batch.id,
            carrier_id=predecessor_to_restore.carrier_id,
            batch_stage_run_id=predecessor_to_restore.batch_stage_run_id,
            assigned_effective_time=target.effective_time, released_effective_time=None,
            opening_production_disposition_reversal_event_id=reversal.id,
            restored_from_batch_carrier_assignment_id=predecessor_to_restore.id,
            population_root_batch_carrier_assignment_id=root_id, actor_user_id=actor_user_id,
        )
        db.add(assignment)
        db.flush()
        restored_assignment_id = assignment.id

    # LEAFY-OPS-001 BUILD section 15: the replacement always references
    # whichever BCA is now current -- `assignment` at this point is either
    # the still-active generation (CASE A, unchanged) or the just-created
    # restoration (CASE B), never the released target generation.
    replacement = None
    if corrected is not None:
        replacement = ProductionDispositionEvent(
            id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, command_id=command.id,
            batch_carrier_assignment_id=assignment.id, population_root_batch_carrier_assignment_id=root_id,
            event_kind="REDUCTION", reason_code=corrected["reason_code"],
            quantity_delta=-corrected["plant_loss_count"], effective_time=corrected["effective_time"],
            note=corrected.get("note"), reverses_event_id=None, corrects_event_id=target.id,
        )
        db.add(replacement)
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            if _is_balance_violation_error(exc):
                raise ProductionDispositionBalanceError(
                    "recording this correction would violate the chronological "
                    "authoritative living-population balance"
                ) from exc
            raise

    replacement_released_assignment_id: uuid.UUID | None = None
    if replacement is not None:
        available_after = get_current_living_population(
            db, root_batch_carrier_assignment_id=root_id, as_of=replacement.effective_time
        )
        if available_after == 0:
            assignment.released_effective_time = replacement.effective_time
            assignment.released_by_production_disposition_event_id = replacement.id
            db.flush()
            replacement_released_assignment_id = assignment.id

    resulting_population = get_current_living_population(db, root_batch_carrier_assignment_id=root_id)

    audit_data = {
        "command_id": str(command.id), "client_command_id": str(client_command_id),
        "target_event_id": str(target.id), "reversal_event_id": str(reversal.id),
        "replacement_event_id": str(replacement.id) if replacement else None,
        "original_plant_loss_count": -target.quantity_delta, "original_reason_code": target.reason_code,
        "corrected_plant_loss_count": corrected["plant_loss_count"] if corrected else None,
        "corrected_reason_code": corrected["reason_code"] if corrected else None,
        "previous_living_population": previous_population, "resulting_living_population": resulting_population,
    }
    if restored_assignment_id is not None:
        audit_data["restored_assignment_id"] = str(restored_assignment_id)
    if replacement_released_assignment_id is not None:
        audit_data["replacement_released_assignment_id"] = str(replacement_released_assignment_id)

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id,
        action="crop_batch.production_disposition_corrected",
        entity_type="production_disposition_event", entity_id=target.id, event_data=audit_data,
    )
    db.commit()
    db.refresh(command)
    return command


# --- CORRECT (Vines, void only) ----------------------------------------------------


def correct_grow_cube_disposition(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_command_id: uuid.UUID,
    target_event_id: uuid.UUID,
    corrected: dict | None,
) -> ProductionDispositionCommand:
    """VINES-OPS-002: void-only correction entry point for a Vines
    `grow_bag` disposition REDUCTION -- delegates to `correct_disposition`
    completely unmodified (its population-root/reversal mechanics are
    already carrier-agnostic; see this module's own docstring). A pure
    REVERSAL (`corrected=None`) needs no Vines-specific extension: it is the
    exact negation of the target's own `quantity_delta`, which already
    correctly reopens every one of the target REDUCTION's named Grow
    Cube(s) for a future truthful disposition -- `get_grow_cube_disposition_
    status`'s own "no un-reversed REDUCTION exists" check picks this up with
    zero new code. REPLACE-mode correction (a corrected replacement
    REDUCTION) is intentionally NOT exposed here yet: the replacement would
    need its own new set of named Grow Cube ids, and `correct_disposition`'s
    existing REPLACE shape has no such field -- extending it is explicitly
    deferred (ticket: "if extending correction materially complicates this
    ticket, STOP ONLY that subpart and report it as follow-up")."""
    if corrected is not None:
        raise ProductionDispositionValidationError(
            "Vines grow cube disposition correction currently supports void (reversal) only -- "
            "replacement with a corrected plant/reason is not yet available"
        )

    target = db.execute(
        select(ProductionDispositionEvent).where(
            ProductionDispositionEvent.id == target_event_id,
            ProductionDispositionEvent.tenant_id == tenant_id,
            ProductionDispositionEvent.farm_id == farm_id,
        )
    ).scalar_one_or_none()
    if target is None:
        raise ProductionDispositionEventNotFoundError(str(target_event_id))
    assignment_carrier_id = db.execute(
        select(BatchCarrierAssignment.carrier_id).where(
            BatchCarrierAssignment.id == target.batch_carrier_assignment_id
        )
    ).scalar_one()
    _require_grow_bag(db, carrier_id=assignment_carrier_id)

    return correct_disposition(
        db, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id,
        client_command_id=client_command_id, target_event_id=target_event_id, corrected=None,
    )


# --- Reads ---------------------------------------------------------------------------


def _resolve_location_ancestry_label(db: Session, *, location_id: uuid.UUID) -> str:
    """Operator context only (section 20/26, frozen), never biological
    authority -- walks `parent_location_id` up to a bounded depth,
    mirroring every other lineage-walk's own safety bound elsewhere in this
    codebase. Small, operator-scale per-row cost (see NURSERY-OPS-005B's
    own precedent for this exact tolerance)."""
    codes: list[str] = []
    current_id: uuid.UUID | None = location_id
    hops = 0
    while current_id is not None and hops < 10:
        row = db.execute(
            text("SELECT code, parent_location_id FROM locations WHERE id = :id"), {"id": current_id}
        ).mappings().first()
        if row is None:
            break
        codes.append(row["code"])
        current_id = row["parent_location_id"]
        hops += 1
    return " / ".join(reversed(codes))


def list_active_production_plates(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID | None = None,
) -> list[dict]:
    """LEAFY-OPS-001 section 28: every `production_cultivation_plate`-typed
    BatchCarrierAssignment currently active (unreleased) -- a zero-
    exhausted lineage's released generation never appears here (see
    `get_production_disposition_history` for that). Current Occupancy is
    informational context only, never an eligibility filter or biological
    authority."""
    farm_service.get_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    query = (
        "SELECT bca.id AS assignment_id, bca.population_root_batch_carrier_assignment_id AS root_id, "
        "carrier.id AS carrier_id, carrier.code AS carrier_code, "
        "cb.id AS batch_id, cb.code AS batch_code, "
        "crop.common_name, variety.name AS variety_name, "
        "loc.id AS location_id, loc.code AS location_code, loc.name AS location_name, "
        "loc_type.code AS location_type_code "
        "FROM batch_carrier_assignments bca "
        "JOIN carriers carrier ON carrier.id = bca.carrier_id "
        "JOIN carrier_types ct ON ct.id = carrier.carrier_type_id AND ct.code = :plate_type_code "
        "JOIN crop_batches cb ON cb.id = bca.batch_id "
        "JOIN workflows wf ON wf.id = cb.workflow_id "
        "JOIN crops crop ON crop.id = wf.crop_id "
        "LEFT JOIN varieties variety ON variety.id = wf.variety_id "
        "LEFT JOIN occupancies occ ON occ.occupant_carrier_id = carrier.id AND occ.end_time IS NULL "
        "LEFT JOIN locations loc ON loc.id = occ.target_location_id "
        "LEFT JOIN location_types loc_type ON loc_type.id = loc.location_type_id "
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

    results: list[dict] = []
    for r in rows:
        root_id = r["root_id"]
        opening = get_root_opening_population(db, root_batch_carrier_assignment_id=root_id)
        # HARVEST-OPS-001 SLICE 2: `current_living` must route through the
        # shared authority (which also sums HarvestPopulationEvent), not an
        # inline ProductionDispositionEvent-only SUM -- a plate that has
        # ever been Harvested would otherwise show a stale, too-high living
        # count here. `total_recorded_loss` stays Production-Disposition-
        # specific (Plant Loss only, by design) and keeps its own inline sum.
        current_living = leafy_population_service.get_current_living_population(
            db, root_batch_carrier_assignment_id=root_id
        )
        total_recorded_loss = db.execute(
            select(
                func.coalesce(
                    func.sum(func.greatest(-ProductionDispositionEvent.quantity_delta, 0)), 0,
                )
            ).where(ProductionDispositionEvent.population_root_batch_carrier_assignment_id == root_id)
        ).scalar_one()

        location = None
        has_warning = True
        if r["location_id"] is not None:
            has_warning = False
            location = {
                "id": r["location_id"], "code": r["location_code"], "name": r["location_name"],
                "location_type_code": r["location_type_code"],
                "ancestry_label": _resolve_location_ancestry_label(db, location_id=r["location_id"]),
            }

        results.append(
            {
                "carrier_id": r["carrier_id"], "plate_code": r["carrier_code"],
                "batch_carrier_assignment_id": r["assignment_id"],
                "population_root_batch_carrier_assignment_id": root_id,
                "batch_id": r["batch_id"], "batch_code": r["batch_code"],
                "crop_common_name": r["common_name"], "variety_name": r["variety_name"],
                "opening_population": opening, "current_living_population": current_living,
                "total_recorded_loss": total_recorded_loss,
                "current_location": location, "has_location_warning": has_warning,
            }
        )
    return results


def get_production_disposition_history(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID,
    batch_carrier_assignment_id: uuid.UUID | None = None, batch_id: uuid.UUID | None = None,
) -> list[dict]:
    """LEAFY-OPS-001 section 30: remains accessible for a fully-exhausted
    (released, not restored) lineage -- never discoverable only through
    `list_active_production_plates`. Groups by population root (one row per
    lineage), not by individual BCA generation.

    BROWSER QA CORRECTION 1: `population_root_batch_carrier_assignment_id`
    is deliberately carrier-type-generic (every transplant destination, Nursery
    Cultivation Plate and Production Cultivation Plate alike, gets one -- see
    the `a5c9e21f7b64` migration and `transplant_service.py`'s own
    self-referencing root assignment). A Leafy Production read model must
    still narrow to `production_cultivation_plate` lineages only, exactly as
    `list_active_production_plates` already does -- never a NursERY/
    InterSalads lineage. Filtering on ANY row in the lineage's own
    `carrier_id` is equivalent to filtering on the root's: the origin-
    integrity trigger guarantees every restoration generation shares its
    predecessor's exact physical Carrier, so carrier type never varies
    within one lineage."""
    farm_service.get_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    root_query = (
        select(
            BatchCarrierAssignment.population_root_batch_carrier_assignment_id.label("root_id"),
        )
        .join(Carrier, Carrier.id == BatchCarrierAssignment.carrier_id)
        .join(CarrierType, CarrierType.id == Carrier.carrier_type_id)
        .where(
            BatchCarrierAssignment.tenant_id == tenant_id,
            BatchCarrierAssignment.farm_id == farm_id,
            BatchCarrierAssignment.population_root_batch_carrier_assignment_id.is_not(None),
            CarrierType.code == PRODUCTION_CULTIVATION_PLATE_CARRIER_TYPE_CODE,
        )
        .distinct()
    )
    if batch_carrier_assignment_id is not None:
        root_query = root_query.where(
            (BatchCarrierAssignment.id == batch_carrier_assignment_id)
            | (BatchCarrierAssignment.population_root_batch_carrier_assignment_id == batch_carrier_assignment_id)
        )
    if batch_id is not None:
        root_query = root_query.where(BatchCarrierAssignment.batch_id == batch_id)

    root_ids = [row[0] for row in db.execute(root_query).all()]

    results: list[dict] = []
    for root_id in root_ids:
        root_row = db.execute(
            text(
                "SELECT bca.id, carrier.code AS plate_code, cb.id AS batch_id, cb.code AS batch_code "
                "FROM batch_carrier_assignments bca "
                "JOIN carriers carrier ON carrier.id = bca.carrier_id "
                "JOIN crop_batches cb ON cb.id = bca.batch_id "
                "WHERE bca.id = :root_id"
            ),
            {"root_id": root_id},
        ).mappings().one()

        opening = get_root_opening_population(db, root_batch_carrier_assignment_id=root_id)
        current_living = get_current_living_population(db, root_batch_carrier_assignment_id=root_id)
        active_id = resolve_active_assignment_id_for_root(db, root_batch_carrier_assignment_id=root_id)

        event_rows = db.execute(
            select(ProductionDispositionEvent, ProductionDispositionCommand.actor_user_id)
            .join(ProductionDispositionCommand, ProductionDispositionCommand.id == ProductionDispositionEvent.command_id)
            .where(ProductionDispositionEvent.population_root_batch_carrier_assignment_id == root_id)
            .order_by(ProductionDispositionEvent.effective_time, ProductionDispositionEvent.recorded_at)
        ).all()
        reversed_ids = {
            event.reverses_event_id for event, _actor in event_rows if event.reverses_event_id is not None
        }
        events = [
            _to_event_read_dict(event, is_reversed=event.id in reversed_ids, actor_user_id=actor)
            for event, actor in event_rows
        ]

        results.append(
            {
                "population_root_batch_carrier_assignment_id": root_id,
                "plate_code": root_row["plate_code"], "batch_id": root_row["batch_id"],
                "batch_code": root_row["batch_code"], "opening_population": opening,
                "current_living_population": current_living, "is_active": active_id is not None,
                "events": events,
            }
        )
    return results
