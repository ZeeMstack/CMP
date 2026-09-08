"""VINES-OPS-001B: the Nursery(InterVines) -> Vines Production Transfer
composite operator command --

    InterVines Grow Cube(s) (one living plant each, currently at one named
    (Batch, InterVines Table) group)
    -> biological Transplant                       (transplant_service._record_transplant_core)
    -> a server-allocated pool of Grow Bag(s)       (grow_bag Carriers, configurable plant capacity
                                                      via CarrierSpecification.biological_position_count)
    -> physical placement of those Grow Bag(s)      (movement_service._execute_movement_core)
    -> free Grow Bag Position(s) under one selected Grow Gutter

committed atomically, one transaction, one commit. Composes the same two
existing, unmodified non-committing cores `intervines_transplant_service`
already proved out -- no second biological-accounting or physical-movement
engine is built here, and Movement gains no Vines-Production awareness.

The Grow Cube retention seam (the ticket's central modeling question) is
solved by ONE fact already true before this ticket started, plus one
explicit physical-release step this ticket adds:
`transplant_source_authority`'s `batch_carrier_population` authority is
carrier-type-agnostic (keyed on the assignment id alone). Adding `grow_cube`
to `ELIGIBLE_SOURCE_CARRIER_TYPE_CODES` (this ticket's one small extension
to that shared module) makes a Grow Cube a legitimate Transplant SOURCE with
zero other changes. Treating it as a source means `_record_transplant_core`
RELEASES the Grow Cube's own `BatchCarrierAssignment` when its one plant is
consumed (`remainder_after == 0`, always true here -- one plant per Grow
Cube) -- exactly the existing, generic "a fully-consumed source is closed"
rule, applied to a new source type. Biological release alone leaves the Grow
Cube's PHYSICAL Occupancy row still open at the InterVines Table (Transplant
itself never moves a source Carrier's own location) -- the frozen rule "the
Grow Cube moves WITH the plant" requires this command to close that
Occupancy explicitly, which it now does with one `_execute_movement_core`
call per consumed Grow Cube, `destination_kind=None` -- the same generic
"removal" shape (close current occupancy, open none) `movement_service`
already supports and documents for exactly this case (see its own
`kind = "removal" if destination_kind is None else ...`). The Grow Cube is
never re-placed at the Grow Bag Position itself: that Location is already
exclusively occupied by the Grow Bag (capacity 1 by construction), and
`ux_occupancies_active_occupant_carrier` forbids a second simultaneous
occupancy for the same carrier elsewhere anyway -- one Grow Cube, one
Occupancy, ever. Its CURRENT production Grow Bag is instead resolved through
the same already-existing, immutable `TransplantSourceLine`/`Transplant
Allocation`/`TransplantDestinationLine` chain this command's own biological
transplant already writes (see `list_vines_production_placement_grow_bags`
below) -- no new "carried-by" relation table is needed, since a released
Grow Cube assignment can never source a second allocation (the same
`released_effective_time IS NULL` gate `_select_intervines_grow_cube_
sources_for_update` already enforces), so that chain always resolves to
exactly one current Grow Bag. `intervines_transplant_service.list_intervines_
placements`'s own read view already joins `released_effective_time IS NULL`
together with an active Occupancy, so a released, now-occupancy-closed Grow
Cube drops out of "currently in InterVines" on both grounds, with no code
change to that read model. Backward traceability (Grow Bag -> Grow Cube -> Seed Tray) is likewise free:
it is the SAME already-proven `TransplantSourceLine`/`TransplantAllocation`/
`TransplantDestinationLine` chain this ticket's own event writes, walked
one hop further back into VINES-OPS-001A's own chain (see
`list_vines_production_placement_grow_bags` below) -- no new lineage table.

This command is POOL-BASED on BOTH sides, unlike `intervines_transplant_
service` (pool-based destination only): the operator names one source
InterVines (Batch, Table) group and a plant quantity (never an individual
Grow Cube), and one destination Grow Gutter plus a Grow Bag specification
(never an individual Grow Bag or Grow Bag Position) -- the server
deterministically allocates enough currently-available Grow Cubes, Grow
Bags, and free Grow Bag Positions under lock, filling each Grow Bag to its
own configured capacity before moving to the next (ticket's own frozen fill
policy), so a real, uneven-remainder batch (e.g. 20 plants at capacity 3 ->
6 full Bags + 1 partial) is handled with zero special-casing.

Idempotency mirrors `intervines_transplant_service`'s own two-tier check-
lock-recheck discipline exactly, for the identical reason: the server
chooses BOTH the Grow Cube ids and the Grow Bag/Position ids, so a client
resending the same request cannot itself reproduce identical `destination_
lines`/`allocations` the way a destination-picker-based composite's client
naturally would -- this module owns its own replay short-circuit, entirely
before ever touching any of the three pools (source Grow Cubes, Grow Bags,
Grow Bag Positions), locking the CropBatch row first so a truly-concurrent
duplicate call serializes behind the winner instead of racing the pools."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.carrier import Carrier
from app.models.carrier_specification import CarrierSpecification
from app.models.carrier_type import CarrierType
from app.models.crop_batch import CropBatch
from app.models.location import Location
from app.models.location_type import LocationType
from app.models.movement import Movement
from app.models.occupancy import Occupancy
from app.models.transplant_event import TransplantEvent
from app.schemas.carrier_specification import CarrierSpecificationSummary
from app.schemas.sowing_event import CarrierSummary, CarrierTypeSummary
from app.schemas.vines_production_transfer import (
    AvailableGrowBagPoolRead,
    VinesProductionGrowBagPlacementRead,
    VinesProductionPlacementGrowBagRead,
    VinesProductionPlacementGrowCubeRead,
    VinesProductionPlacementRead,
    VinesProductionTransferRead,
)
from app.services import carrier_service, movement_service, transplant_service
from app.services.errors import (
    CarrierSpecificationNotFoundError,
    CarrierSpecificationTypeMismatchError,
    InsufficientAvailableGrowBagPositionsError,
    InsufficientAvailableGrowBagsError,
    InsufficientAvailableInterVinesPlantsError,
    LocationNotFoundError,
    TransplantValidationError,
    VinesProductionTransferReplayStateConflictError,
)

GROW_CUBE_CARRIER_TYPE_CODE = "grow_cube"
GROW_BAG_CARRIER_TYPE_CODE = "grow_bag"
SEED_TRAY_CARRIER_TYPE_CODE = "seed_tray"
INTERVINES_TABLE_LOCATION_TYPE_CODE = "intervines_table"
GROW_GUTTER_LOCATION_TYPE_CODE = "grow_gutter"
GROW_BAG_POSITION_LOCATION_TYPE_CODE = "grow_bag_position"

# A fixed, stable namespace distinct from every sibling composite's own.
_MOVEMENT_COMMAND_NAMESPACE = uuid.UUID("2a7e5c91-4f8b-4d3a-9c6e-1b8f4a2d7e35")


def _derive_movement_client_command_id(
    outer_client_command_id: uuid.UUID, destination_carrier_id: uuid.UUID
) -> uuid.UUID:
    return uuid.uuid5(_MOVEMENT_COMMAND_NAMESPACE, f"{outer_client_command_id}:{destination_carrier_id}")


def _lock_batch_for_command(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID) -> None:
    db.execute(
        select(CropBatch.id).where(
            CropBatch.id == batch_id, CropBatch.tenant_id == tenant_id, CropBatch.farm_id == farm_id
        ).with_for_update()
    ).all()


def _select_intervines_grow_cube_sources_for_update(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID, source_table_id: uuid.UUID,
    quantity: int,
) -> list[tuple[uuid.UUID, Carrier]]:
    """Deterministically selects up to `quantity` currently-living InterVines
    plants (active, unreleased Grow Cube `BatchCarrierAssignment`s, each
    still occupying `source_table_id`) belonging to this Batch -- ascending
    Grow Cube `code` order, `FOR UPDATE` on the assignment rows so a
    concurrent duplicate command serializes here rather than racing.
    Already-transferred (released) or lost/disposed (also released -- no
    disposition path exists yet for `grow_cube`, but this check is the same
    generic one regardless) plants are excluded by construction. Raises
    `InsufficientAvailableInterVinesPlantsError` -- before any write -- if
    fewer than `quantity` are actually available."""
    grow_cube_type = db.execute(
        select(CarrierType).where(CarrierType.code == GROW_CUBE_CARRIER_TYPE_CODE)
    ).scalar_one()
    rows = db.execute(
        select(BatchCarrierAssignment.id, Carrier)
        .join(Carrier, Carrier.id == BatchCarrierAssignment.carrier_id)
        .join(
            Occupancy,
            (Occupancy.occupant_carrier_id == Carrier.id) & (Occupancy.end_time.is_(None)),
        )
        .where(
            BatchCarrierAssignment.tenant_id == tenant_id,
            BatchCarrierAssignment.farm_id == farm_id,
            BatchCarrierAssignment.batch_id == batch_id,
            BatchCarrierAssignment.released_effective_time.is_(None),
            Carrier.carrier_type_id == grow_cube_type.id,
            Occupancy.target_location_id == source_table_id,
        )
        .order_by(Carrier.code)
        .limit(quantity)
        .with_for_update(of=BatchCarrierAssignment)
    ).all()
    if len(rows) < quantity:
        raise InsufficientAvailableInterVinesPlantsError(
            f"requested {quantity} plant(s) but only {len(rows)} are currently living in this InterVines placement"
        )
    return [(r[0], r[1]) for r in rows]


def _select_available_grow_bags_for_update(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, specification_id: uuid.UUID, quantity: int,
) -> list[Carrier]:
    """Mirrors `intervines_transplant_service._select_available_grow_cubes_
    for_update` exactly, for `grow_bag` -- `specification_id` is always
    supplied here (unlike that sibling's optional filter), since a Grow
    Bag's plant capacity is only knowable via its own specification."""
    grow_bag_type = db.execute(
        select(CarrierType).where(CarrierType.code == GROW_BAG_CARRIER_TYPE_CODE)
    ).scalar_one()
    active_assignment_carrier_ids = select(BatchCarrierAssignment.carrier_id).where(
        BatchCarrierAssignment.tenant_id == tenant_id, BatchCarrierAssignment.released_effective_time.is_(None)
    )
    bags = list(
        db.execute(
            select(Carrier)
            .where(
                Carrier.tenant_id == tenant_id, Carrier.farm_id == farm_id,
                Carrier.carrier_type_id == grow_bag_type.id, Carrier.status == "active",
                Carrier.specification_id == specification_id,
                Carrier.id.not_in(active_assignment_carrier_ids),
            )
            .order_by(Carrier.code)
            .limit(quantity)
            .with_for_update()
        ).scalars()
    )
    if len(bags) < quantity:
        raise InsufficientAvailableGrowBagsError(
            f"requested {quantity} Grow Bag(s) but only {len(bags)} are currently available for this specification"
        )
    return bags


def _select_free_grow_bag_positions_for_update(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, gutter_id: uuid.UUID, quantity: int,
) -> list[Location]:
    """Deterministic allocation in ascending Position `code` order (ticket:
    "deterministic allocation may use the first valid free positions in
    canonical code order"). Raises `InsufficientAvailableGrowBagPositionsError`
    -- before any write -- if fewer than `quantity` free positions exist
    under this Gutter (this also naturally rejects a bogus/wrong-type
    `gutter_id`, which structurally has zero `grow_bag_position` children)."""
    position_type = db.execute(
        select(LocationType).where(LocationType.code == GROW_BAG_POSITION_LOCATION_TYPE_CODE)
    ).scalar_one()
    occupied_location_ids = select(Occupancy.target_location_id).where(Occupancy.end_time.is_(None))
    positions = list(
        db.execute(
            select(Location)
            .where(
                Location.tenant_id == tenant_id, Location.farm_id == farm_id,
                Location.parent_location_id == gutter_id, Location.location_type_id == position_type.id,
                Location.status == "active",
                Location.id.not_in(occupied_location_ids),
            )
            .order_by(Location.code)
            .limit(quantity)
            .with_for_update()
        ).scalars()
    )
    if len(positions) < quantity:
        raise InsufficientAvailableGrowBagPositionsError(
            f"requested {quantity} Grow Bag Position(s) but only {len(positions)} are currently free under this Gutter"
        )
    return positions


def _allocate_bag_quantities(plant_count: int, capacity: int, bags: list[Carrier]) -> list[tuple[Carrier, int]]:
    """Frozen fill policy (ticket Scenario 3): fill each Grow Bag to its own
    capacity before moving to the next; the last Bag may carry a partial
    remainder. `bags` must already contain exactly `ceil(plant_count /
    capacity)` entries (the caller's own pool selection guarantees this)."""
    remaining = plant_count
    allocations: list[tuple[Carrier, int]] = []
    for bag in bags:
        if remaining <= 0:
            break
        qty = min(capacity, remaining)
        allocations.append((bag, qty))
        remaining -= qty
    return allocations


def _resolve_expected_movements(
    db: Session, *, tenant_id: uuid.UUID, client_command_id: uuid.UUID, carrier_ids: list[uuid.UUID],
) -> dict[uuid.UUID, Movement]:
    """Shared by both movement kinds this command writes: destination Grow
    Bag placements (`destination_kind="location"`) and source Grow Cube
    releases (`destination_kind=None`) -- both are keyed the same way
    (`_derive_movement_client_command_id(client_command_id, carrier_id)`),
    so a replay can verify either set of Movements exists and belongs to the
    expected carrier by the same check."""
    movements_by_carrier_id: dict[uuid.UUID, Movement] = {}
    for cid in carrier_ids:
        movement_command_id = _derive_movement_client_command_id(client_command_id, cid)
        movement = movement_service._find_existing_movement(
            db, tenant_id=tenant_id, client_command_id=movement_command_id
        )
        if movement is None:
            raise VinesProductionTransferReplayStateConflictError(
                f"expected Movement for carrier {cid} does not exist"
            )
        if movement.occupant_carrier_id != cid:
            raise VinesProductionTransferReplayStateConflictError(
                f"existing Movement for carrier {cid} does not match the requested carrier"
            )
        movements_by_carrier_id[cid] = movement
    return movements_by_carrier_id


def _describe_vines_production_transfer(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    transplant_event_id: uuid.UUID,
    source_intervines_table_id: uuid.UUID,
    destination_grow_gutter_id: uuid.UUID,
    grow_bag_specification_id: uuid.UUID,
    movements_by_carrier_id: dict[uuid.UUID, Movement],
) -> VinesProductionTransferRead:
    generic = transplant_service.get_transplant_event(
        db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id, transplant_event_id=transplant_event_id
    )
    source_grow_cubes = [line.carrier for line in generic.source_lines]
    grow_bags = [
        VinesProductionGrowBagPlacementRead(
            destination_batch_carrier_assignment_id=line.destination_batch_carrier_assignment_id,
            grow_bag=line.carrier, assigned_plant_count=line.assigned_plant_count,
            grow_bag_position_id=movements_by_carrier_id[line.carrier.id].destination_location_id,
            movement_id=movements_by_carrier_id[line.carrier.id].id,
        )
        for line in generic.destination_lines
    ]
    return VinesProductionTransferRead(
        id=generic.id, tenant_id=generic.tenant_id, farm_id=generic.farm_id, batch_id=generic.batch_id,
        batch_code=generic.batch_code, workflow_version_id=generic.workflow_version_id, stage=generic.stage,
        effective_time=generic.effective_time, recorded_time=generic.recorded_time,
        actor_user_id=generic.actor_user_id, client_command_id=generic.client_command_id, note=generic.note,
        source_intervines_table_id=source_intervines_table_id, plant_count=len(source_grow_cubes),
        destination_grow_gutter_id=destination_grow_gutter_id, grow_bag_specification_id=grow_bag_specification_id,
        source_grow_cubes=source_grow_cubes, grow_bags=grow_bags,
    )


def _replay_vines_production_transfer(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    existing_event: TransplantEvent,
    client_command_id: uuid.UUID,
    source_intervines_table_id: uuid.UUID,
    plant_count: int,
    destination_grow_gutter_id: uuid.UUID,
    grow_bag_specification_id: uuid.UUID,
) -> VinesProductionTransferRead:
    generic = transplant_service.get_transplant_event(
        db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id, transplant_event_id=existing_event.id,
    )
    if len(generic.source_lines) != plant_count:
        raise VinesProductionTransferReplayStateConflictError(
            "existing command for this client_command_id does not match the requested plant_count"
        )
    source_carrier_ids = [line.carrier.id for line in generic.source_lines]
    # Historical, not active: the original command's own success path closes
    # each Grow Cube's InterVines Occupancy (the frozen "moves with the
    # plant" rule) -- a closed row still names `target_location_id`, so this
    # remains a faithful check that THIS replay's `source_intervines_table_
    # id` matches what the original command actually used, without
    # resurrecting the pre-fix assumption that the Grow Cube is still
    # sitting there.
    ever_at_source_table = db.execute(
        select(Occupancy.occupant_carrier_id).distinct().where(
            Occupancy.occupant_carrier_id.in_(source_carrier_ids),
            Occupancy.target_location_id == source_intervines_table_id,
        )
    ).scalars().all()
    if len(ever_at_source_table) != plant_count:
        raise VinesProductionTransferReplayStateConflictError(
            "existing command for this client_command_id does not match the requested source_intervines_table_id"
        )
    still_active_at_source_table = db.execute(
        select(Occupancy.occupant_carrier_id).where(
            Occupancy.occupant_carrier_id.in_(source_carrier_ids),
            Occupancy.target_location_id == source_intervines_table_id,
            Occupancy.end_time.is_(None),
        )
    ).scalars().all()
    if still_active_at_source_table:
        raise VinesProductionTransferReplayStateConflictError(
            "existing command's Grow Cube(s) still have an active InterVines occupancy -- "
            "expected it closed by this command's own Grow Cube release movement"
        )
    _resolve_expected_movements(
        db, tenant_id=tenant_id, client_command_id=client_command_id, carrier_ids=source_carrier_ids,
    )

    destination_carrier_ids = [line.carrier.id for line in generic.destination_lines]
    destination_carriers = db.execute(
        select(Carrier).where(Carrier.id.in_(destination_carrier_ids))
    ).scalars().all()
    if any(c.specification_id != grow_bag_specification_id for c in destination_carriers):
        raise VinesProductionTransferReplayStateConflictError(
            "existing command for this client_command_id does not match the requested grow_bag_specification_id"
        )

    movements_by_carrier_id = _resolve_expected_movements(
        db, tenant_id=tenant_id, client_command_id=client_command_id, carrier_ids=destination_carrier_ids,
    )
    position_ids = [m.destination_location_id for m in movements_by_carrier_id.values()]
    positions = db.execute(select(Location).where(Location.id.in_(position_ids))).scalars().all()
    if any(p.parent_location_id != destination_grow_gutter_id for p in positions):
        raise VinesProductionTransferReplayStateConflictError(
            "existing command for this client_command_id does not match the requested destination_grow_gutter_id"
        )

    return _describe_vines_production_transfer(
        db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id, transplant_event_id=existing_event.id,
        source_intervines_table_id=source_intervines_table_id, destination_grow_gutter_id=destination_grow_gutter_id,
        grow_bag_specification_id=grow_bag_specification_id, movements_by_carrier_id=movements_by_carrier_id,
    )


def record_vines_production_transfer(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    batch_id: uuid.UUID,
    client_command_id: uuid.UUID,
    effective_time: datetime,
    note: str | None,
    source_intervines_table_id: uuid.UUID,
    plant_count: int,
    destination_grow_gutter_id: uuid.UUID,
    grow_bag_specification_id: uuid.UUID,
) -> VinesProductionTransferRead:
    """Owns the transaction: commit, rollback, and replay behavior. See the
    module docstring for the two-tier check-lock-recheck idempotency
    discipline and the deterministic fill policy."""
    existing_event = transplant_service._find_existing_transplant_event(
        db, tenant_id=tenant_id, client_command_id=client_command_id
    )
    if existing_event is not None:
        return _replay_vines_production_transfer(
            db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id, existing_event=existing_event,
            client_command_id=client_command_id, source_intervines_table_id=source_intervines_table_id,
            plant_count=plant_count, destination_grow_gutter_id=destination_grow_gutter_id,
            grow_bag_specification_id=grow_bag_specification_id,
        )

    carrier_service._require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    _lock_batch_for_command(db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id)
    existing_event = transplant_service._find_existing_transplant_event(
        db, tenant_id=tenant_id, client_command_id=client_command_id
    )
    if existing_event is not None:
        return _replay_vines_production_transfer(
            db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id, existing_event=existing_event,
            client_command_id=client_command_id, source_intervines_table_id=source_intervines_table_id,
            plant_count=plant_count, destination_grow_gutter_id=destination_grow_gutter_id,
            grow_bag_specification_id=grow_bag_specification_id,
        )

    gutter_type = db.execute(
        select(LocationType).where(LocationType.code == GROW_GUTTER_LOCATION_TYPE_CODE)
    ).scalar_one()
    gutter = db.execute(
        select(Location).where(
            Location.id == destination_grow_gutter_id, Location.tenant_id == tenant_id, Location.farm_id == farm_id,
            Location.location_type_id == gutter_type.id, Location.status == "active",
        )
    ).scalar_one_or_none()
    if gutter is None:
        raise LocationNotFoundError(str(destination_grow_gutter_id))

    specification = db.execute(
        select(CarrierSpecification).where(
            CarrierSpecification.id == grow_bag_specification_id, CarrierSpecification.tenant_id == tenant_id,
        )
    ).scalar_one_or_none()
    if specification is None:
        raise CarrierSpecificationNotFoundError(str(grow_bag_specification_id))
    grow_bag_type = db.execute(select(CarrierType).where(CarrierType.code == GROW_BAG_CARRIER_TYPE_CODE)).scalar_one()
    if specification.carrier_type_id != grow_bag_type.id:
        raise CarrierSpecificationTypeMismatchError(
            f"specification {grow_bag_specification_id} is not a grow_bag specification"
        )
    capacity = specification.biological_position_count
    if capacity is None or capacity <= 0:
        raise TransplantValidationError(
            f"grow_bag_specification_id {grow_bag_specification_id} has no configured biological_position_count"
        )

    sources = _select_intervines_grow_cube_sources_for_update(
        db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id, source_table_id=source_intervines_table_id,
        quantity=plant_count,
    )
    bags_needed = -(-plant_count // capacity)  # ceiling division
    bags = _select_available_grow_bags_for_update(
        db, tenant_id=tenant_id, farm_id=farm_id, specification_id=grow_bag_specification_id, quantity=bags_needed,
    )
    positions = _select_free_grow_bag_positions_for_update(
        db, tenant_id=tenant_id, farm_id=farm_id, gutter_id=destination_grow_gutter_id, quantity=bags_needed,
    )
    bag_allocations = _allocate_bag_quantities(plant_count, capacity, bags)

    source_lines = [
        {
            "source_assignment_id": aid, "transplant_damage_count": 0, "qc_rejection_count": 0, "sample_count": 0,
            "other_loss_count": 0, "other_loss_note": None, "note": None,
        }
        for aid, _carrier in sources
    ]
    destination_lines = [
        {"destination_carrier_id": bag.id, "assigned_plant_count": qty, "note": None} for bag, qty in bag_allocations
    ]
    allocations: list[dict] = []
    source_iter = iter(sources)
    for bag, qty in bag_allocations:
        for _ in range(qty):
            aid, _carrier = next(source_iter)
            allocations.append(
                {"source_assignment_id": aid, "destination_carrier_id": bag.id, "allocated_plant_count": 1}
            )

    try:
        event, is_new = transplant_service._record_transplant_core(
            db, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, batch_id=batch_id,
            client_command_id=client_command_id, effective_time=effective_time, note=note,
            source_lines=source_lines, destination_lines=destination_lines, allocations=allocations,
        )
        if is_new:
            movements_by_carrier_id: dict[uuid.UUID, Movement] = {}
            for (bag, _qty), position in zip(bag_allocations, positions):
                movement_command_id = _derive_movement_client_command_id(client_command_id, bag.id)
                movement = movement_service._execute_movement_core(
                    db, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id,
                    client_command_id=movement_command_id, effective_time=effective_time,
                    occupant_kind="carrier", occupant_id=bag.id,
                    destination_kind="location", destination_id=position.id,
                    reason=None,
                )
                movements_by_carrier_id[bag.id] = movement
            # FROZEN RULE: the Grow Cube moves WITH the plant -- close its
            # InterVines Table Occupancy now (a "removal", `destination_
            # kind=None`: closes the active occupancy, opens none) so it no
            # longer physically reads as present at the source Table. Same
            # transaction as the transplant + bag placements above: any
            # failure here rolls back the whole command via the shared
            # `except Exception: db.rollback()` below, leaving the original
            # InterVines occupancy fully intact (invariant G).
            for _source_assignment_id, grow_cube in sources:
                release_command_id = _derive_movement_client_command_id(client_command_id, grow_cube.id)
                movement_service._execute_movement_core(
                    db, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id,
                    client_command_id=release_command_id, effective_time=effective_time,
                    occupant_kind="carrier", occupant_id=grow_cube.id,
                    destination_kind=None, destination_id=None,
                    reason="vines_production_transfer",
                )
            db.commit()
            db.refresh(event)
        else:
            destination_carrier_ids = [bag.id for bag, _qty in bag_allocations]
            movements_by_carrier_id = _resolve_expected_movements(
                db, tenant_id=tenant_id, client_command_id=client_command_id,
                carrier_ids=destination_carrier_ids,
            )
            source_carrier_ids = [grow_cube.id for _aid, grow_cube in sources]
            _resolve_expected_movements(
                db, tenant_id=tenant_id, client_command_id=client_command_id, carrier_ids=source_carrier_ids,
            )
    except Exception:
        db.rollback()
        raise

    return _describe_vines_production_transfer(
        db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id, transplant_event_id=event.id,
        source_intervines_table_id=source_intervines_table_id, destination_grow_gutter_id=destination_grow_gutter_id,
        grow_bag_specification_id=grow_bag_specification_id, movements_by_carrier_id=movements_by_carrier_id,
    )


def list_available_grow_bag_pools(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, destination_grow_gutter_id: uuid.UUID | None = None,
) -> list[AvailableGrowBagPoolRead]:
    """VINES-OPS-001B: every Grow Bag CarrierSpecification pool currently
    eligible as a Vines Production destination in this Farm. Every eligible
    Grow Bag necessarily has a specification (platform-enforced, VINES-OPS-
    001B's own migration) -- an INNER join, never the NULL-group handling
    `intervines_transplant_service.list_available_grow_cube_pools` needs for
    `grow_cube` (which stays optionally-specified)."""
    carrier_service._require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    rows = db.execute(
        text(
            "SELECT spec.id AS specification_id, spec.code AS spec_code, spec.name AS spec_name, "
            "spec.biological_position_count, count(*) AS available_bag_count "
            "FROM carriers c "
            "JOIN carrier_types ct ON ct.id = c.carrier_type_id AND ct.code = :grow_bag_type_code "
            "JOIN carrier_specifications spec ON spec.id = c.specification_id "
            "WHERE c.tenant_id = :tid AND c.farm_id = :fid AND c.status = 'active' "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM batch_carrier_assignments bca "
            "  WHERE bca.carrier_id = c.id AND bca.released_effective_time IS NULL"
            ") "
            "GROUP BY spec.id, spec.code, spec.name, spec.biological_position_count "
            "ORDER BY spec.code"
        ),
        {"tid": tenant_id, "fid": farm_id, "grow_bag_type_code": GROW_BAG_CARRIER_TYPE_CODE},
    ).mappings().all()

    free_position_count: int | None = None
    if destination_grow_gutter_id is not None:
        free_position_count = db.execute(
            text(
                "SELECT count(*) FROM locations l "
                "JOIN location_types lt ON lt.id = l.location_type_id AND lt.code = :position_type_code "
                "WHERE l.tenant_id = :tid AND l.farm_id = :fid AND l.parent_location_id = :gutter_id "
                "AND l.status = 'active' "
                "AND NOT EXISTS (SELECT 1 FROM occupancies o WHERE o.target_location_id = l.id AND o.end_time IS NULL)"
            ),
            {
                "tid": tenant_id, "fid": farm_id, "gutter_id": destination_grow_gutter_id,
                "position_type_code": GROW_BAG_POSITION_LOCATION_TYPE_CODE,
            },
        ).scalar_one()

    results: list[AvailableGrowBagPoolRead] = []
    for r in rows:
        capacity = r["biological_position_count"] or 0
        bag_count = r["available_bag_count"]
        effective_bags = min(bag_count, free_position_count) if free_position_count is not None else bag_count
        results.append(
            AvailableGrowBagPoolRead(
                specification_id=r["specification_id"],
                specification=CarrierSpecificationSummary(
                    id=r["specification_id"], code=r["spec_code"], name=r["spec_name"],
                    biological_position_count=r["biological_position_count"],
                ),
                available_bag_count=bag_count, available_position_count=free_position_count,
                available_plant_capacity=effective_bags * capacity,
            )
        )
    return results


def list_vines_production_placements(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID,
) -> list[VinesProductionPlacementRead]:
    """VINES-OPS-001B: the compact Vines Production read view -- one
    aggregated row per (Batch, Grow Gutter), never one row per plant/Grow
    Bag. `plant_count` sums each active Grow Bag assignment's own
    `TransplantDestinationLine.assigned_plant_count` (a Bag may carry more
    than one plant) -- never a bare `count(*)` of Bags."""
    carrier_service._require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    rows = db.execute(
        text(
            "SELECT cb.id AS batch_id, cb.code AS batch_code, "
            "crop.id AS crop_id, crop.code AS crop_code, crop.common_name AS crop_common_name, "
            "variety.id AS variety_id, variety.code AS variety_code, variety.name AS variety_name, "
            "greenhouse.id AS greenhouse_id, greenhouse.code AS greenhouse_code, greenhouse.name AS greenhouse_name, "
            "gutter.id AS gutter_id, gutter.code AS gutter_code, "
            "sum(tdl.assigned_plant_count) AS plant_count, "
            "min(bca.assigned_effective_time) AS earliest_assigned_effective_time "
            "FROM batch_carrier_assignments bca "
            "JOIN carriers c ON c.id = bca.carrier_id "
            "JOIN carrier_types ct ON ct.id = c.carrier_type_id AND ct.code = :grow_bag_type_code "
            "JOIN transplant_destination_lines tdl ON tdl.destination_batch_carrier_assignment_id = bca.id "
            "JOIN crop_batches cb ON cb.id = bca.batch_id "
            "JOIN workflows wf ON wf.id = cb.workflow_id "
            "JOIN crops crop ON crop.id = wf.crop_id "
            "LEFT JOIN varieties variety ON variety.id = wf.variety_id "
            "JOIN occupancies occ ON occ.occupant_carrier_id = c.id AND occ.end_time IS NULL "
            "JOIN locations position ON position.id = occ.target_location_id "
            "JOIN locations gutter ON gutter.id = position.parent_location_id "
            "JOIN locations span ON span.id = gutter.parent_location_id "
            "JOIN locations zone ON zone.id = span.parent_location_id "
            "JOIN locations greenhouse ON greenhouse.id = zone.parent_location_id "
            "WHERE bca.tenant_id = :tid AND bca.farm_id = :fid AND bca.released_effective_time IS NULL "
            "GROUP BY cb.id, cb.code, crop.id, crop.code, crop.common_name, variety.id, variety.code, variety.name, "
            "greenhouse.id, greenhouse.code, greenhouse.name, gutter.id, gutter.code "
            "ORDER BY cb.code, gutter.code"
        ),
        {"tid": tenant_id, "fid": farm_id, "grow_bag_type_code": GROW_BAG_CARRIER_TYPE_CODE},
    ).mappings().all()
    as_of = datetime.now(timezone.utc)
    results: list[VinesProductionPlacementRead] = []
    for r in rows:
        earliest = r["earliest_assigned_effective_time"]
        results.append(
            VinesProductionPlacementRead(
                batch_id=r["batch_id"], batch_code=r["batch_code"],
                crop_id=r["crop_id"], crop_code=r["crop_code"], crop_common_name=r["crop_common_name"],
                variety_id=r["variety_id"], variety_code=r["variety_code"], variety_name=r["variety_name"],
                greenhouse_id=r["greenhouse_id"], greenhouse_code=r["greenhouse_code"],
                greenhouse_name=r["greenhouse_name"],
                gutter_id=r["gutter_id"], gutter_code=r["gutter_code"],
                plant_count=r["plant_count"], earliest_assigned_effective_time=earliest,
                days_in_production=(as_of - earliest).days,
            )
        )
    return results


def list_vines_production_placement_grow_bags(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID, gutter_id: uuid.UUID,
) -> list[VinesProductionPlacementGrowBagRead]:
    """VINES-OPS-001B: drill-down for one aggregated Vines Production
    placement row -- every Grow Bag currently carrying living plants there,
    and every Grow Cube inside each Bag with its own Seed Tray lineage (the
    ticket's required backward chain: Grow Bag -> Grow Cube -> Seed Tray),
    walked via the plain `TransplantSourceLine`/`TransplantAllocation`/
    `TransplantDestinationLine` chain -- one hop for this event's own Grow
    Cube sources, one more hop into VINES-OPS-001A's own InterVines event
    for each Grow Cube's Seed Tray. Two round trips (bags+cubes, then a
    single batched Seed-Tray lookup for every cube found) -- never N+1."""
    carrier_service._require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    bag_rows = db.execute(
        text(
            "SELECT c.id AS bag_id, c.code AS bag_code, "
            "ct.id AS carrier_type_id, ct.code AS carrier_type_code, ct.name AS carrier_type_name, "
            "bca.id AS assignment_id, bca.assigned_effective_time, "
            "tdl.id AS destination_line_id, tdl.assigned_plant_count, "
            "position.code AS position_code "
            "FROM batch_carrier_assignments bca "
            "JOIN carriers c ON c.id = bca.carrier_id "
            "JOIN carrier_types ct ON ct.id = c.carrier_type_id AND ct.code = :grow_bag_type_code "
            "JOIN transplant_destination_lines tdl ON tdl.destination_batch_carrier_assignment_id = bca.id "
            "JOIN occupancies occ ON occ.occupant_carrier_id = c.id AND occ.end_time IS NULL "
            "JOIN locations position ON position.id = occ.target_location_id AND position.parent_location_id = :gutter_id "
            "WHERE bca.tenant_id = :tid AND bca.farm_id = :fid AND bca.released_effective_time IS NULL "
            "AND bca.batch_id = :batch_id "
            "ORDER BY c.code"
        ),
        {"tid": tenant_id, "fid": farm_id, "batch_id": batch_id, "gutter_id": gutter_id, "grow_bag_type_code": GROW_BAG_CARRIER_TYPE_CODE},
    ).mappings().all()
    if not bag_rows:
        return []

    destination_line_ids = [r["destination_line_id"] for r in bag_rows]
    cube_rows = db.execute(
        text(
            "SELECT ta.destination_line_id, gc.id AS grow_cube_id, gc.code AS grow_cube_code, "
            "gct.id AS grow_cube_type_id, gct.code AS grow_cube_type_code, gct.name AS grow_cube_type_name, "
            "tsl.source_batch_carrier_assignment_id AS grow_cube_assignment_id "
            "FROM transplant_allocations ta "
            "JOIN transplant_source_lines tsl ON tsl.id = ta.source_line_id "
            "JOIN carriers gc ON gc.id = tsl.source_carrier_id "
            "JOIN carrier_types gct ON gct.id = gc.carrier_type_id "
            "WHERE ta.destination_line_id = ANY(:destination_line_ids)"
        ),
        {"destination_line_ids": destination_line_ids},
    ).mappings().all()

    grow_cube_assignment_ids = [r["grow_cube_assignment_id"] for r in cube_rows]
    seed_tray_by_grow_cube_assignment: dict[uuid.UUID, dict] = {}
    if grow_cube_assignment_ids:
        lineage_rows = db.execute(
            text(
                "SELECT tdl2.destination_batch_carrier_assignment_id AS grow_cube_assignment_id, "
                "st.id AS seed_tray_id, st.code AS seed_tray_code, "
                "stt.id AS seed_tray_type_id, stt.code AS seed_tray_type_code, stt.name AS seed_tray_type_name "
                "FROM transplant_destination_lines tdl2 "
                "JOIN transplant_allocations ta2 ON ta2.destination_line_id = tdl2.id "
                "JOIN transplant_source_lines tsl2 ON tsl2.id = ta2.source_line_id "
                "JOIN carriers st ON st.id = tsl2.source_carrier_id "
                "JOIN carrier_types stt ON stt.id = st.carrier_type_id AND stt.code = :seed_tray_type_code "
                "WHERE tdl2.destination_batch_carrier_assignment_id = ANY(:grow_cube_assignment_ids)"
            ),
            {"grow_cube_assignment_ids": grow_cube_assignment_ids, "seed_tray_type_code": SEED_TRAY_CARRIER_TYPE_CODE},
        ).mappings().all()
        seed_tray_by_grow_cube_assignment = {r["grow_cube_assignment_id"]: r for r in lineage_rows}

    cubes_by_destination_line: dict[uuid.UUID, list[VinesProductionPlacementGrowCubeRead]] = {}
    for r in cube_rows:
        lineage = seed_tray_by_grow_cube_assignment.get(r["grow_cube_assignment_id"])
        cubes_by_destination_line.setdefault(r["destination_line_id"], []).append(
            VinesProductionPlacementGrowCubeRead(
                grow_cube=CarrierSummary(
                    id=r["grow_cube_id"], code=r["grow_cube_code"],
                    carrier_type=CarrierTypeSummary(
                        id=r["grow_cube_type_id"], code=r["grow_cube_type_code"], name=r["grow_cube_type_name"],
                    ),
                ),
                source_seed_tray=(
                    CarrierSummary(
                        id=lineage["seed_tray_id"], code=lineage["seed_tray_code"],
                        carrier_type=CarrierTypeSummary(
                            id=lineage["seed_tray_type_id"], code=lineage["seed_tray_type_code"],
                            name=lineage["seed_tray_type_name"],
                        ),
                    )
                    if lineage is not None
                    else None
                ),
            )
        )

    return [
        VinesProductionPlacementGrowBagRead(
            grow_bag=CarrierSummary(
                id=r["bag_id"], code=r["bag_code"],
                carrier_type=CarrierTypeSummary(
                    id=r["carrier_type_id"], code=r["carrier_type_code"], name=r["carrier_type_name"],
                ),
            ),
            grow_bag_position_code=r["position_code"],
            batch_carrier_assignment_id=r["assignment_id"], assigned_plant_count=r["assigned_plant_count"],
            assigned_effective_time=r["assigned_effective_time"],
            grow_cubes=cubes_by_destination_line.get(r["destination_line_id"], []),
        )
        for r in bag_rows
    ]
