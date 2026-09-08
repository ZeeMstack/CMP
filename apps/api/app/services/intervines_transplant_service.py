"""VINES-OPS-001A: the InterVines Transplant composite operator command --

    Seedling source Carrier (seed_tray, one per command)
    -> biological Transplant                      (transplant_service._record_transplant_core)
    -> a server-allocated pool of Grow Cube(s)     (grow_cube Carriers, one plant each)
    -> physical placement of those Grow Cube(s)    (movement_service._execute_movement_core)
    -> one InterVines Table

committed atomically, one transaction, one commit. Composes the two
existing, unmodified non-committing cores exactly as `intersalads_transplant_
service`/`leafy_production_transfer_service` already do -- Movement gains no
Transplant/InterVines/biology awareness from this module, and no second
biological-accounting or physical-movement engine is built here.

The one genuine architectural difference from those two siblings: this
command is POOL-BASED, not destination-Carrier-picker-based. The operator
never names a destination Grow Cube id -- only a quantity (`plant_count`) and
one destination Table. This module is the one responsible for
deterministically allocating that many currently-available Grow Cubes under
lock (`_select_available_grow_cubes_for_update`), building the underlying
generic `destination_lines`/`allocations` (one line per Grow Cube, always
exactly 1 plant each -- this is what makes "one living plant per Grow Cube" a
structural guarantee of this command, never dependent on an admin having
configured a `biological_position_count=1` CarrierSpecification), and then
composing them into the shared cores exactly like its siblings.

Idempotency is the other place this command differs from its siblings. There,
`destination_carrier_id` is CLIENT-SUPPLIED, so an exact replay trivially
resends the identical `destination_lines`/`allocations`, and `_record_
transplant_core`'s OWN fingerprint check resolves the replay -- including the
TRUE CONCURRENT case (two threads submit the identical command at once):
whichever thread's write lands second recomputes the SAME destination_lines
(same client-supplied ids) and matches the fingerprint cleanly. Here, the
server chooses the Grow Cube ids itself -- two concurrent calls for the same
`client_command_id` would independently lock and select two DIFFERENT sets
of Grow Cubes (`FOR UPDATE` guarantees no row overlap), so if both proceeded
to `_record_transplant_core` the second would build a DIFFERENT fingerprint
and get a spurious `TransplantCommandReusedWithDifferentPayloadError` even
though the client's own request was byte-identical. This module closes that
gap itself, BEFORE ever selecting a Grow Cube: it looks up whether a
TransplantEvent already exists for this `client_command_id` (`transplant_
service._find_existing_transplant_event`) and, if so, re-derives the read
entirely from already-committed rows (`_replay_intervines_transplant`,
verifying the replay's own composite-level fields against what was actually
recorded); otherwise it locks the CropBatch row itself
(`_lock_batch_for_command`) -- serializing any second, truly-concurrent call
for the SAME `client_command_id` behind the first -- and re-checks once more
under that lock before ever touching the Grow Cube pool, mirroring the exact
two-tier check-lock-recheck discipline `_record_transplant_core` itself uses
internally for the identical reason.

Destination-Location locking: unlike its two siblings, this command always
targets exactly ONE destination Location (one InterVines Table per command),
never several -- so the proven multi-Table lock-order-inversion deadlock
those siblings guard against cannot occur here (a deadlock needs a cycle
across at least two contended resources; one shared resource only ever
serializes). No `_lock_destination_locations_in_order` equivalent is needed;
`_execute_movement_core`'s own per-call target lock already serializes
concurrent commands against the same Table correctly."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.carrier import Carrier
from app.models.carrier_type import CarrierType
from app.models.crop_batch import CropBatch
from app.models.movement import Movement
from app.models.transplant_event import TransplantEvent
from app.schemas.carrier_specification import CarrierSpecificationSummary
from app.schemas.intervines_transplant import (
    AvailableGrowCubePoolRead,
    IntervinesGrowCubePlacementRead,
    IntervinesPlacementGrowCubeRead,
    IntervinesPlacementRead,
    IntervinesTransplantRead,
)
from app.schemas.sowing_event import CarrierSummary, CarrierTypeSummary
from app.services import carrier_service, movement_service, transplant_service
from app.services.errors import (
    InsufficientAvailableGrowCubesError,
    IntervinesTransplantReplayStateConflictError,
)

GROW_CUBE_CARRIER_TYPE_CODE = "grow_cube"
INTERVINES_TABLE_LOCATION_TYPE_CODE = "intervines_table"

# A fixed, stable namespace distinct from every sibling composite's own
# (`intersalads_transplant_service`, `leafy_production_transfer_service`) --
# never colliding with either, or with a genuinely different destination
# Grow Cube under the same outer command.
_MOVEMENT_COMMAND_NAMESPACE = uuid.UUID("6d2f8b41-9c3a-4e7d-8f1b-5a6e2c9d4f70")


def _derive_movement_client_command_id(
    outer_client_command_id: uuid.UUID, destination_carrier_id: uuid.UUID
) -> uuid.UUID:
    """Deterministic and collision-safe: the same (outer command,
    destination Grow Cube) pair always re-derives the same child Movement
    identity, so an exact replay of the composite command never creates a
    second Movement for the same Grow Cube."""
    return uuid.uuid5(_MOVEMENT_COMMAND_NAMESPACE, f"{outer_client_command_id}:{destination_carrier_id}")


def _lock_batch_for_command(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID) -> None:
    """Locks the CropBatch row (if it exists) so a second, truly-concurrent
    call for the SAME `client_command_id` blocks here instead of racing this
    module's own Grow Cube pool selection -- see the module docstring. A
    non-existent Batch is deliberately not raised as an error here: locking
    zero rows is a safe no-op, and `_record_transplant_core` itself is the
    single authoritative place `CropBatchNotFoundError` is raised."""
    db.execute(
        select(CropBatch.id).where(
            CropBatch.id == batch_id, CropBatch.tenant_id == tenant_id, CropBatch.farm_id == farm_id
        ).with_for_update()
    ).all()


def _select_available_grow_cubes_for_update(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, specification_id: uuid.UUID | None, quantity: int
) -> list[Carrier]:
    """Deterministically allocates up to `quantity` currently-available Grow
    Cube Carriers -- active status, no currently-active
    `BatchCarrierAssignment`, optionally scoped to one CarrierSpecification
    -- locking each selected row (`FOR UPDATE`, ascending `code` order, the
    same blocking-lock discipline this codebase already uses everywhere
    else, e.g. `transplant_service._record_transplant_core`'s own Carrier
    lock). Two concurrent commands racing for the same pool serialize on
    this query (never deadlock: both lock in the same ascending order) --
    Postgres re-checks each blocked-then-unblocked row's own eligibility
    against the freshly committed data before returning it, so a Grow Cube
    consumed by the winner is correctly excluded from the loser's result set
    (the same guarantee this codebase already relies on for `DestinationCarrierAlreadyAssignedError`'s
    own re-validation). Raises `InsufficientAvailableGrowCubesError` --
    before any write -- if fewer than `quantity` are actually available."""
    grow_cube_type = db.execute(
        select(CarrierType).where(CarrierType.code == GROW_CUBE_CARRIER_TYPE_CODE)
    ).scalar_one()

    active_assignment_carrier_ids = select(BatchCarrierAssignment.carrier_id).where(
        BatchCarrierAssignment.tenant_id == tenant_id, BatchCarrierAssignment.released_effective_time.is_(None)
    )

    query = (
        select(Carrier)
        .where(
            Carrier.tenant_id == tenant_id,
            Carrier.farm_id == farm_id,
            Carrier.carrier_type_id == grow_cube_type.id,
            Carrier.status == "active",
            Carrier.id.not_in(active_assignment_carrier_ids),
        )
    )
    if specification_id is not None:
        query = query.where(Carrier.specification_id == specification_id)

    cubes = list(
        db.execute(query.order_by(Carrier.code).limit(quantity).with_for_update()).scalars()
    )
    if len(cubes) < quantity:
        raise InsufficientAvailableGrowCubesError(
            f"requested {quantity} Grow Cube(s) but only {len(cubes)} are currently available"
        )
    return cubes


def _resolve_expected_movements(
    db: Session, *, tenant_id: uuid.UUID, client_command_id: uuid.UUID, destination_carrier_ids: list[uuid.UUID],
    destination_location_id: uuid.UUID,
) -> dict[uuid.UUID, Movement]:
    movements_by_carrier_id: dict[uuid.UUID, Movement] = {}
    for cid in destination_carrier_ids:
        movement_command_id = _derive_movement_client_command_id(client_command_id, cid)
        movement = movement_service._find_existing_movement(
            db, tenant_id=tenant_id, client_command_id=movement_command_id
        )
        if movement is None:
            raise IntervinesTransplantReplayStateConflictError(
                f"expected Movement for destination Grow Cube {cid} does not exist"
            )
        if movement.occupant_carrier_id != cid or movement.destination_location_id != destination_location_id:
            raise IntervinesTransplantReplayStateConflictError(
                f"existing Movement for destination Grow Cube {cid} does not match the requested "
                f"destination Grow Cube/Table"
            )
        movements_by_carrier_id[cid] = movement
    return movements_by_carrier_id


def _describe_intervines_transplant(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    transplant_event_id: uuid.UUID,
    destination_location_id: uuid.UUID,
    movements_by_carrier_id: dict[uuid.UUID, Movement],
) -> IntervinesTransplantRead:
    """Reuses the existing, already-proven generic Transplant read
    composition (`transplant_service.get_transplant_event`) in full for the
    single source line and every destination line -- source availability and
    reconciliation totals are identical facts regardless of which command
    recorded them -- and layers only the genuinely new placement facts
    (destination Table, Movement id) on top. No duplicate genealogy query."""
    generic = transplant_service.get_transplant_event(
        db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id, transplant_event_id=transplant_event_id
    )
    source_line = generic.source_lines[0]
    grow_cubes = [
        IntervinesGrowCubePlacementRead(
            destination_batch_carrier_assignment_id=line.destination_batch_carrier_assignment_id,
            carrier=line.carrier,
            destination_location_id=destination_location_id,
            movement_id=movements_by_carrier_id[line.carrier.id].id,
        )
        for line in generic.destination_lines
    ]
    return IntervinesTransplantRead(
        id=generic.id, tenant_id=generic.tenant_id, farm_id=generic.farm_id, batch_id=generic.batch_id,
        batch_code=generic.batch_code, workflow_version_id=generic.workflow_version_id, stage=generic.stage,
        effective_time=generic.effective_time, recorded_time=generic.recorded_time,
        actor_user_id=generic.actor_user_id, client_command_id=generic.client_command_id, note=generic.note,
        source_assignment_id=source_line.source_batch_carrier_assignment_id, source_carrier=source_line.carrier,
        total_source_available_before=generic.total_source_available_before,
        total_remainder_after=generic.total_remainder_after,
        plant_count=len(grow_cubes), destination_location_id=destination_location_id, grow_cubes=grow_cubes,
    )


def _replay_intervines_transplant(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    existing_event: TransplantEvent,
    client_command_id: uuid.UUID,
    source_assignment_id: uuid.UUID,
    plant_count: int,
    destination_location_id: uuid.UUID,
    grow_cube_specification_id: uuid.UUID | None,
) -> IntervinesTransplantRead:
    generic = transplant_service.get_transplant_event(
        db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id, transplant_event_id=existing_event.id,
    )
    if len(generic.source_lines) != 1 or generic.source_lines[0].source_batch_carrier_assignment_id != source_assignment_id:
        raise IntervinesTransplantReplayStateConflictError(
            "existing command for this client_command_id does not match the requested source_assignment_id"
        )
    if len(generic.destination_lines) != plant_count:
        raise IntervinesTransplantReplayStateConflictError(
            "existing command for this client_command_id does not match the requested plant_count"
        )
    destination_carrier_ids = [line.carrier.id for line in generic.destination_lines]
    if grow_cube_specification_id is not None:
        specification_ids = {
            c.specification_id
            for c in db.execute(select(Carrier).where(Carrier.id.in_(destination_carrier_ids))).scalars()
        }
        if specification_ids != {grow_cube_specification_id}:
            raise IntervinesTransplantReplayStateConflictError(
                "existing command for this client_command_id does not match the requested "
                "grow_cube_specification_id"
            )
    movements_by_carrier_id = _resolve_expected_movements(
        db, tenant_id=tenant_id, client_command_id=client_command_id,
        destination_carrier_ids=destination_carrier_ids, destination_location_id=destination_location_id,
    )
    return _describe_intervines_transplant(
        db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id, transplant_event_id=existing_event.id,
        destination_location_id=destination_location_id, movements_by_carrier_id=movements_by_carrier_id,
    )


def record_intervines_transplant(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    batch_id: uuid.UUID,
    client_command_id: uuid.UUID,
    effective_time: datetime,
    note: str | None,
    source_assignment_id: uuid.UUID,
    plant_count: int,
    destination_location_id: uuid.UUID,
    grow_cube_specification_id: uuid.UUID | None,
) -> IntervinesTransplantRead:
    """Owns the transaction: commit, rollback, and replay behavior. See the
    module docstring for why this command's replay path (`_replay_intervines_
    transplant`) is checked FIRST, before any Grow Cube is ever selected --
    unlike its siblings, this command cannot rely on the client resending the
    same destination Carrier ids to make `_record_transplant_core`'s own
    fingerprint short-circuit resolve the replay correctly."""
    existing_event = transplant_service._find_existing_transplant_event(
        db, tenant_id=tenant_id, client_command_id=client_command_id
    )
    if existing_event is not None:
        return _replay_intervines_transplant(
            db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id, existing_event=existing_event,
            client_command_id=client_command_id, source_assignment_id=source_assignment_id,
            plant_count=plant_count, destination_location_id=destination_location_id,
            grow_cube_specification_id=grow_cube_specification_id,
        )

    carrier_service._require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    # Second check, under the CropBatch row lock -- closes the true
    # concurrent-duplicate race the module docstring describes: a sibling
    # call for this exact client_command_id that committed while we were
    # blocked acquiring this lock is now visible.
    _lock_batch_for_command(db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id)
    existing_event = transplant_service._find_existing_transplant_event(
        db, tenant_id=tenant_id, client_command_id=client_command_id
    )
    if existing_event is not None:
        return _replay_intervines_transplant(
            db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id, existing_event=existing_event,
            client_command_id=client_command_id, source_assignment_id=source_assignment_id,
            plant_count=plant_count, destination_location_id=destination_location_id,
            grow_cube_specification_id=grow_cube_specification_id,
        )

    cubes = _select_available_grow_cubes_for_update(
        db, tenant_id=tenant_id, farm_id=farm_id, specification_id=grow_cube_specification_id, quantity=plant_count,
    )
    source_lines = [
        {
            "source_assignment_id": source_assignment_id, "transplant_damage_count": 0, "qc_rejection_count": 0,
            "sample_count": 0, "other_loss_count": 0, "other_loss_note": None, "note": None,
        }
    ]
    destination_lines = [
        {"destination_carrier_id": c.id, "assigned_plant_count": 1, "note": None} for c in cubes
    ]
    allocations = [
        {"source_assignment_id": source_assignment_id, "destination_carrier_id": c.id, "allocated_plant_count": 1}
        for c in cubes
    ]

    try:
        event, is_new = transplant_service._record_transplant_core(
            db, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, batch_id=batch_id,
            client_command_id=client_command_id, effective_time=effective_time, note=note,
            source_lines=source_lines, destination_lines=destination_lines, allocations=allocations,
        )
        if is_new:
            movements_by_carrier_id: dict[uuid.UUID, Movement] = {}
            for c in cubes:
                movement_command_id = _derive_movement_client_command_id(client_command_id, c.id)
                movement = movement_service._execute_movement_core(
                    db, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id,
                    client_command_id=movement_command_id, effective_time=effective_time,
                    occupant_kind="carrier", occupant_id=c.id,
                    destination_kind="location", destination_id=destination_location_id,
                    reason=None,
                )
                movements_by_carrier_id[c.id] = movement
            db.commit()
            db.refresh(event)
        else:
            # Vanishingly rare true concurrent-replay race (see module
            # docstring): another transaction committed the same
            # client_command_id between our own pre-check and this call.
            # Re-derive the read from what actually landed, exactly like
            # the ordinary replay path.
            destination_carrier_ids = [c.id for c in cubes]
            movements_by_carrier_id = _resolve_expected_movements(
                db, tenant_id=tenant_id, client_command_id=client_command_id,
                destination_carrier_ids=destination_carrier_ids, destination_location_id=destination_location_id,
            )
    except Exception:
        db.rollback()
        raise

    return _describe_intervines_transplant(
        db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id, transplant_event_id=event.id,
        destination_location_id=destination_location_id, movements_by_carrier_id=movements_by_carrier_id,
    )


def list_available_grow_cube_pools(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID
) -> list[AvailableGrowCubePoolRead]:
    """VINES-OPS-001A section 13 (setup/master-data support): every Grow
    Cube CarrierSpecification pool currently eligible as an InterVines
    Transplant destination in this Farm, aggregated into one row per
    specification (plus one row for un-specified Grow Cubes, if any) --
    never a per-Grow-Cube row list. One query, no N+1."""
    carrier_service._require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    rows = db.execute(
        text(
            "SELECT c.specification_id, spec.code AS spec_code, spec.name AS spec_name, "
            "spec.biological_position_count, count(*) AS available_count "
            "FROM carriers c "
            "JOIN carrier_types ct ON ct.id = c.carrier_type_id AND ct.code = :grow_cube_type_code "
            "LEFT JOIN carrier_specifications spec ON spec.id = c.specification_id "
            "WHERE c.tenant_id = :tid AND c.farm_id = :fid AND c.status = 'active' "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM batch_carrier_assignments bca "
            "  WHERE bca.carrier_id = c.id AND bca.released_effective_time IS NULL"
            ") "
            "GROUP BY c.specification_id, spec.code, spec.name, spec.biological_position_count "
            "ORDER BY spec_code NULLS FIRST"
        ),
        {"tid": tenant_id, "fid": farm_id, "grow_cube_type_code": GROW_CUBE_CARRIER_TYPE_CODE},
    ).mappings().all()
    return [
        AvailableGrowCubePoolRead(
            specification_id=r["specification_id"],
            specification=(
                CarrierSpecificationSummary(
                    id=r["specification_id"], code=r["spec_code"], name=r["spec_name"],
                    biological_position_count=r["biological_position_count"],
                )
                if r["specification_id"] is not None
                else None
            ),
            available_count=r["available_count"],
        )
        for r in rows
    ]


def list_intervines_placements(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID
) -> list[IntervinesPlacementRead]:
    """VINES-OPS-001A: the compact InterVines read view -- one aggregated
    row per (Batch, InterVines Table), never one row per Grow Cube. Only
    currently-active placements (`released_effective_time IS NULL` and an
    open Occupancy) are counted, mirroring `leafy_production_transfer_
    service.list_available_leafy_production_sources`'s own eligibility
    shape for the sibling read-view concern."""
    carrier_service._require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    rows = db.execute(
        text(
            "SELECT cb.id AS batch_id, cb.code AS batch_code, "
            "crop.id AS crop_id, crop.code AS crop_code, crop.common_name AS crop_common_name, "
            "variety.id AS variety_id, variety.code AS variety_code, variety.name AS variety_name, "
            "loc.id AS table_id, loc.code AS table_code, loc.name AS table_name, "
            "count(*) AS plant_count, min(bca.assigned_effective_time) AS earliest_assigned_effective_time "
            "FROM batch_carrier_assignments bca "
            "JOIN carriers c ON c.id = bca.carrier_id "
            "JOIN carrier_types ct ON ct.id = c.carrier_type_id AND ct.code = :grow_cube_type_code "
            "JOIN crop_batches cb ON cb.id = bca.batch_id "
            "JOIN workflows wf ON wf.id = cb.workflow_id "
            "JOIN crops crop ON crop.id = wf.crop_id "
            "LEFT JOIN varieties variety ON variety.id = wf.variety_id "
            "JOIN occupancies occ ON occ.occupant_carrier_id = c.id AND occ.end_time IS NULL "
            "JOIN locations loc ON loc.id = occ.target_location_id "
            "JOIN location_types loc_type ON loc_type.id = loc.location_type_id AND loc_type.code = :table_type_code "
            "WHERE bca.tenant_id = :tid AND bca.farm_id = :fid AND bca.released_effective_time IS NULL "
            "GROUP BY cb.id, cb.code, crop.id, crop.code, crop.common_name, "
            "variety.id, variety.code, variety.name, loc.id, loc.code, loc.name "
            "ORDER BY cb.code, loc.code"
        ),
        {
            "tid": tenant_id, "fid": farm_id, "grow_cube_type_code": GROW_CUBE_CARRIER_TYPE_CODE,
            "table_type_code": INTERVINES_TABLE_LOCATION_TYPE_CODE,
        },
    ).mappings().all()
    as_of = datetime.now(timezone.utc)
    results: list[IntervinesPlacementRead] = []
    for r in rows:
        earliest = r["earliest_assigned_effective_time"]
        results.append(
            IntervinesPlacementRead(
                batch_id=r["batch_id"], batch_code=r["batch_code"],
                crop_id=r["crop_id"], crop_code=r["crop_code"], crop_common_name=r["crop_common_name"],
                variety_id=r["variety_id"], variety_code=r["variety_code"], variety_name=r["variety_name"],
                table_id=r["table_id"], table_code=r["table_code"], table_name=r["table_name"],
                plant_count=r["plant_count"], earliest_assigned_effective_time=earliest,
                days_in_intervines=(as_of - earliest).days,
            )
        )
    return results


def list_intervines_placement_grow_cubes(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID, table_id: uuid.UUID
) -> list[IntervinesPlacementGrowCubeRead]:
    """VINES-OPS-001A: drill-down detail for one aggregated InterVines
    placement row -- every individual Grow Cube currently carrying a live
    plant for this (Batch, Table) pair. Deliberately narrow: only reachable
    by naming both a Batch and a Table, never a general "list all Grow
    Cubes" endpoint."""
    carrier_service._require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    rows = db.execute(
        text(
            "SELECT c.id AS carrier_id, c.code AS carrier_code, "
            "ct.id AS carrier_type_id, ct.code AS carrier_type_code, ct.name AS carrier_type_name, "
            "bca.id AS assignment_id, bca.assigned_effective_time "
            "FROM batch_carrier_assignments bca "
            "JOIN carriers c ON c.id = bca.carrier_id "
            "JOIN carrier_types ct ON ct.id = c.carrier_type_id AND ct.code = :grow_cube_type_code "
            "JOIN occupancies occ ON occ.occupant_carrier_id = c.id AND occ.end_time IS NULL "
            "JOIN locations loc ON loc.id = occ.target_location_id AND loc.id = :table_id "
            "JOIN location_types loc_type ON loc_type.id = loc.location_type_id AND loc_type.code = :table_type_code "
            "WHERE bca.tenant_id = :tid AND bca.farm_id = :fid AND bca.released_effective_time IS NULL "
            "AND bca.batch_id = :batch_id "
            "ORDER BY c.code"
        ),
        {
            "tid": tenant_id, "fid": farm_id, "batch_id": batch_id, "table_id": table_id,
            "grow_cube_type_code": GROW_CUBE_CARRIER_TYPE_CODE,
            "table_type_code": INTERVINES_TABLE_LOCATION_TYPE_CODE,
        },
    ).mappings().all()
    return [
        IntervinesPlacementGrowCubeRead(
            carrier=CarrierSummary(
                id=r["carrier_id"], code=r["carrier_code"],
                carrier_type=CarrierTypeSummary(
                    id=r["carrier_type_id"], code=r["carrier_type_code"], name=r["carrier_type_name"],
                ),
            ),
            batch_carrier_assignment_id=r["assignment_id"], assigned_effective_time=r["assigned_effective_time"],
        )
        for r in rows
    ]
