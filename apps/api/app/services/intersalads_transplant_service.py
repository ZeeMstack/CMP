"""NURSERY-OPS-004B.1: the InterSalads composite operator command --

    Seedling source Carrier(s)
    -> biological Transplant                     (transplant_service._record_transplant_core)
    -> Nursery Cultivation Plate destination(s)
    -> physical placement of those Plate(s)       (movement_service._execute_movement_core)
    -> InterSalads Table(s)

committed atomically, one transaction, one commit. Composes the two
existing, unmodified non-committing cores rather than building a second
biological-accounting or physical-movement engine -- Movement gains no
Transplant/InterSalads/biology awareness from this module (every check
specific to this composite lives here, never inside `movement_service`,
exactly the same discipline `seedling_entry_service` already established
for its own Movement-core composition).

Execution order is not a style choice: both cores' own docstrings require
the same thing -- a caller composing them must run `_record_transplant_core`
FIRST, before any write it cannot afford to lose to that core's own
internal IntegrityError-triggered rollback. This module follows that order
exactly.

Idempotency: the outer `client_command_id` anchors the Transplant half
(reusing `transplant_service._record_transplant_core`'s own three-tier
idempotency unchanged). Each destination Plate's own Movement needs a
DISTINCT command id -- reusing the outer id directly for N movements would
violate Movement's own `UNIQUE(tenant_id, command_type, client_command_id)`
after the first. `_derive_movement_client_command_id` derives one
deterministically per destination Carrier, the same technique
`seedling_entry_service._derive_movement_client_command_id` already
established for its own single-movement case, extended here with the
destination Carrier id as a second input since one composite command can
place many Plates.

On an exact-fingerprint replay (`_record_transplant_core` returns
`is_new=False`), this module does NOT call the movement cores again -- doing
so would still be *safe* (each movement call's own three-tier idempotency
would independently resolve to the same pre-existing rows), but it would be
N pointless lock acquisitions and round-trips on every mere replay. Instead
it derives the expected per-destination Movement command ids, loads the
already-committed Movements directly, and verifies each corresponds to the
requested destination Carrier and Location -- raising
`IntersaladsTransplantReplayStateConflictError` if any expected Movement is
missing or mismatched, rather than silently fabricating or accepting
inconsistent state.

Destination-Location lock order (pre-commit audit finding, PROVEN via a
direct two-connection `SELECT ... FOR UPDATE` reproduction: PostgreSQL
raises `deadlock detected`, SQLSTATE 40P01, in ~1s -- not caught anywhere,
so it would surface as a raw 500): `_execute_movement_core` locks each
destination Location itself (`_resolve_target(..., lock=True)`), one at a
time, in whatever order `destination_lines` happens to list them --
request/payload order, not any deterministic order. Two *different* Crop
Batches' composite commands are NOT serialized against each other by the
CropBatch-row lock `_record_transplant_core` holds (that lock is scoped to
one batch), so two concurrent commands targeting the same two InterSalads
Tables in opposite order could lock-invert and deadlock. `_lock_destination_locations_in_order`
below closes this: before any Movement call, it locks every *distinct*
destination Location referenced by this command, in deterministic (sorted)
UUID order, inside this same transaction. Re-locking an already-self-held
row inside `_execute_movement_core` afterward is a no-op (Postgres row
locks are per-transaction, not per-statement), so this adds no new
behavior for a single-destination command and no self-deadlock risk for a
multi-destination one -- it only removes the *inter*-transaction lock-order
inversion. Movement's own responsibilities are unchanged; this lives
entirely in the composite orchestration layer."""

import uuid
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.location import Location
from app.models.movement import Movement
from app.services import carrier_service, movement_service, transplant_service
from app.services.errors import IntersaladsTransplantReplayStateConflictError
from app.schemas.carrier_specification import CarrierSpecificationSummary
from app.schemas.intersalads_transplant import (
    AvailableNurseryCultivationPlateRead,
    IntersaladsDestinationLineRead,
    IntersaladsTransplantRead,
)

NURSERY_CULTIVATION_PLATE_CARRIER_TYPE_CODE = "nursery_cultivation_plate"


def _lock_destination_locations_in_order(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, destination_lines: list[dict]
) -> None:
    location_ids = sorted({line["destination_location_id"] for line in destination_lines})
    if not location_ids:
        return
    db.execute(
        select(Location.id)
        .where(Location.id.in_(location_ids), Location.tenant_id == tenant_id, Location.farm_id == farm_id)
        .order_by(Location.id)
        .with_for_update()
    ).all()

# A fixed, stable namespace distinct from seedling_entry_service's own --
# never colliding with it or with a genuinely different destination Carrier
# under the same outer command (uuid5 of distinct inputs under one
# namespace does not collide in practice).
_MOVEMENT_COMMAND_NAMESPACE = uuid.UUID("9f4c2e8a-1b6d-4a3e-8c9f-2d7b5e1a6c4f")


def _derive_movement_client_command_id(
    outer_client_command_id: uuid.UUID, destination_carrier_id: uuid.UUID
) -> uuid.UUID:
    """Deterministic and collision-safe: the same (outer command,
    destination carrier) pair always re-derives the same child Movement
    identity, so an exact replay of the composite command never creates a
    second Movement for the same Plate and never weakens Movement's own
    `client_command_id` uniqueness across the N destinations of one
    command."""
    return uuid.uuid5(_MOVEMENT_COMMAND_NAMESPACE, f"{outer_client_command_id}:{destination_carrier_id}")


def _resolve_expected_movements(
    db: Session, *, tenant_id: uuid.UUID, client_command_id: uuid.UUID, destination_lines: list[dict]
) -> dict[uuid.UUID, Movement]:
    movements_by_carrier_id: dict[uuid.UUID, Movement] = {}
    for line in destination_lines:
        cid = line["destination_carrier_id"]
        expected_location_id = line["destination_location_id"]
        movement_command_id = _derive_movement_client_command_id(client_command_id, cid)
        movement = movement_service._find_existing_movement(
            db, tenant_id=tenant_id, client_command_id=movement_command_id
        )
        if movement is None:
            raise IntersaladsTransplantReplayStateConflictError(
                f"expected Movement for destination carrier {cid} does not exist"
            )
        if movement.occupant_carrier_id != cid or movement.destination_location_id != expected_location_id:
            raise IntersaladsTransplantReplayStateConflictError(
                f"existing Movement for destination carrier {cid} does not match the requested "
                f"destination carrier/location"
            )
        movements_by_carrier_id[cid] = movement
    return movements_by_carrier_id


def _describe_intersalads_transplant(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    transplant_event_id: uuid.UUID,
    movements_by_carrier_id: dict[uuid.UUID, Movement],
) -> IntersaladsTransplantRead:
    """Reuses the existing, already-proven generic Transplant read
    composition (`transplant_service.get_transplant_event`) in full --
    source lines, allocations, and reconciliation totals are identical
    facts regardless of which command recorded them -- and layers only the
    genuinely new placement facts (destination Location, Movement id) on
    top of its destination lines. No duplicate genealogy query."""
    generic = transplant_service.get_transplant_event(
        db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id, transplant_event_id=transplant_event_id
    )
    destination_lines = [
        IntersaladsDestinationLineRead(
            destination_batch_carrier_assignment_id=line.destination_batch_carrier_assignment_id,
            carrier=line.carrier,
            assigned_plant_count=line.assigned_plant_count,
            allocated_plant_count=line.allocated_plant_count,
            destination_location_id=movements_by_carrier_id[line.carrier.id].destination_location_id,
            movement_id=movements_by_carrier_id[line.carrier.id].id,
            note=line.note,
        )
        for line in generic.destination_lines
    ]
    return IntersaladsTransplantRead(
        id=generic.id, tenant_id=generic.tenant_id, farm_id=generic.farm_id, batch_id=generic.batch_id,
        batch_code=generic.batch_code, workflow_version_id=generic.workflow_version_id, stage=generic.stage,
        effective_time=generic.effective_time, recorded_time=generic.recorded_time,
        actor_user_id=generic.actor_user_id, client_command_id=generic.client_command_id, note=generic.note,
        source_lines=generic.source_lines, destination_lines=destination_lines, allocations=generic.allocations,
        total_source_available_before=generic.total_source_available_before,
        total_destination_plant_count=generic.total_destination_plant_count,
        total_discarded_plant_count=generic.total_discarded_plant_count,
        total_remainder_after=generic.total_remainder_after,
    )


def record_intersalads_transplant(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    batch_id: uuid.UUID,
    client_command_id: uuid.UUID,
    effective_time: datetime,
    note: str | None,
    source_lines: list[dict],
    destination_lines: list[dict],
    allocations: list[dict],
) -> IntersaladsTransplantRead:
    """Owns the transaction: commit, rollback, and composite replay
    behavior. `destination_lines` items carry `destination_carrier_id`,
    `assigned_plant_count`, `destination_location_id`, `note` -- the extra
    `destination_location_id` key is simply ignored by
    `_record_transplant_core` (it only reads the keys it knows about), so
    the same dicts are passed straight through to it, no stripping needed."""
    try:
        event, is_new = transplant_service._record_transplant_core(
            db, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, batch_id=batch_id,
            client_command_id=client_command_id, effective_time=effective_time, note=note,
            source_lines=source_lines, destination_lines=destination_lines, allocations=allocations,
        )
        if is_new:
            # BLOCKER fix (pre-commit audit): lock every distinct destination
            # Location in deterministic order BEFORE any Movement call, so two
            # concurrent commands from different Batches targeting the same
            # Tables in opposite order serialize here instead of deadlocking.
            _lock_destination_locations_in_order(
                db, tenant_id=tenant_id, farm_id=farm_id, destination_lines=destination_lines
            )
            movements_by_carrier_id: dict[uuid.UUID, Movement] = {}
            for line in destination_lines:
                cid = line["destination_carrier_id"]
                movement_command_id = _derive_movement_client_command_id(client_command_id, cid)
                movement = movement_service._execute_movement_core(
                    db, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id,
                    client_command_id=movement_command_id, effective_time=effective_time,
                    occupant_kind="carrier", occupant_id=cid,
                    destination_kind="location", destination_id=line["destination_location_id"],
                    reason=None,
                )
                movements_by_carrier_id[cid] = movement
            db.commit()
            db.refresh(event)
        else:
            movements_by_carrier_id = _resolve_expected_movements(
                db, tenant_id=tenant_id, client_command_id=client_command_id, destination_lines=destination_lines
            )
    except Exception:
        db.rollback()
        raise

    return _describe_intersalads_transplant(
        db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id, transplant_event_id=event.id,
        movements_by_carrier_id=movements_by_carrier_id,
    )


def list_available_intersalads_plates(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID
) -> list[AvailableNurseryCultivationPlateRead]:
    """NURSERY-OPS-004B.2 section 13: every `nursery_cultivation_plate`
    Carrier in this Farm eligible as a NEW InterSalads Transplant
    destination right now -- active status, and no currently-active
    `BatchCarrierAssignment` (`released_effective_time IS NULL`), the exact
    same eligibility `transplant_service._record_transplant_core` itself
    enforces via `DestinationCarrierAlreadyAssignedError`/`carrier.status !=
    "active"`, reproduced here read-only for the picker -- never a
    generalized "available Carrier" framework, and never touching
    `production_cultivation_plate`/the historical generic
    `cultivation_plate` type. One query, no N+1 (mirrors
    `seedling_entry_service.list_available_seedling_tables`'s own shape)."""
    carrier_service._require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    rows = db.execute(
        text(
            "SELECT c.id, c.code, c.status, c.specification_id, "
            "spec.id AS spec_id, spec.code AS spec_code, spec.name AS spec_name, "
            "spec.biological_position_count "
            "FROM carriers c "
            "JOIN carrier_types ct ON ct.id = c.carrier_type_id AND ct.code = :plate_type_code "
            "LEFT JOIN carrier_specifications spec ON spec.id = c.specification_id "
            "WHERE c.tenant_id = :tid AND c.farm_id = :fid AND c.status = 'active' "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM batch_carrier_assignments bca "
            "  WHERE bca.carrier_id = c.id AND bca.released_effective_time IS NULL"
            ") "
            "ORDER BY c.code"
        ),
        {"tid": tenant_id, "fid": farm_id, "plate_type_code": NURSERY_CULTIVATION_PLATE_CARRIER_TYPE_CODE},
    ).mappings().all()
    return [
        AvailableNurseryCultivationPlateRead(
            id=r["id"], code=r["code"], status=r["status"], specification_id=r["specification_id"],
            specification=(
                CarrierSpecificationSummary(
                    id=r["spec_id"], code=r["spec_code"], name=r["spec_name"],
                    biological_position_count=r["biological_position_count"],
                )
                if r["specification_id"] is not None
                else None
            ),
        )
        for r in rows
    ]
