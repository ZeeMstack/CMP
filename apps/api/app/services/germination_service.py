"""NURSERY-OPS-002A: Germination Placement.

FROZEN authoritative physical model (product decision, no chamber_position):

    Nursery Greenhouse
    -> Germination Chamber (occupiable, capacity = number of Trolleys)
        -> Germination Trolley Asset (occupies the Chamber directly)
            -> Shelf/Level AssetPosition
                -> Slot AssetPosition
                    -> Seed Tray Carrier (occupies the Slot)

This module is a thin, Germination-aware orchestration layer over the
existing, unmodified `movement_service.execute_movement` -- it adds no new
physical-movement engine. Every idempotency/concurrency/capacity guarantee
is `movement_service`'s own, reused verbatim. What this module adds is the
domain-specific validation `movement_service` cannot know about on its own:
a Trolley must be an active `germination_trolley` in this tenant/farm, a
Chamber must be an active, occupiable `germination_chamber` under a
Nursery-classified Greenhouse, and -- critically -- a Tray may only be
placed into a Trolley's Slot while that Trolley itself currently occupies a
valid Germination Chamber (section 16).

Physical placement only. No biological Germination outcome (that is
NURSERY-OPS-002B's `GerminationCheck`, untouched here), no workflow-stage
transition (physical location and workflow stage are separate facts)."""
import uuid
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.asset_position import AssetPosition
from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.carrier import Carrier
from app.models.location import Location
from app.models.movement import Movement
from app.schemas.germination import (
    AvailableTrolleyRead,
    GerminationChamberAvailabilityRead,
    GerminationChamberSummary,
    GerminationResolvedPlacement,
    GerminationTrayRead,
    SlotSummary,
    TrayPlacementRead,
    TrolleyPlacementRead,
    TrolleySlotAvailabilityRead,
    TrolleySummary,
)
from app.schemas.crop_batch import CropSummary, VarietySummary
from app.schemas.sowing_event import CarrierSummary, CarrierTypeSummary, SeedLotSummary
from app.services import asset_service, carrier_service, farm_service, location_service, movement_service
from app.services.errors import (
    AssetPositionNotFoundError,
    FarmNotFoundError,
    GerminationChamberInvalidError,
    GerminationTraySlotInvalidError,
    GerminationTrolleyInvalidError,
    TrayNotSownError,
    TrolleyNotInGerminationError,
)

GERMINATION_TROLLEY_ASSET_TYPE_CODE = "germination_trolley"
GERMINATION_CHAMBER_LOCATION_TYPE_CODE = "germination_chamber"
SEED_TRAY_CARRIER_TYPE_CODE = "seed_tray"
SLOT_POSITION_KIND = "slot"


def _require_active_farm(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID):
    farm = farm_service.get_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    if farm.status != "active":
        raise FarmNotFoundError(str(farm_id))
    return farm


def _validate_chamber(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, chamber_id: uuid.UUID) -> Location:
    # `get_location` is tenant/farm-scoped and raises the generic, existing
    # `LocationNotFoundError` for a missing/cross-tenant/cross-farm id --
    # section 35 requires cross-tenant/cross-farm to read as a plain 404,
    # never leaking "exists but wrong type" via a 422 Invalid error. Only a
    # row that genuinely resolves in this tenant/farm is then checked
    # against Germination-specific business rules below.
    location = location_service.get_location(db, tenant_id=tenant_id, farm_id=farm_id, location_id=chamber_id)
    if location.status != "active":
        raise GerminationChamberInvalidError(str(chamber_id))
    chamber_type = location_service._get_location_type_by_code(db, GERMINATION_CHAMBER_LOCATION_TYPE_CODE)
    if location.location_type_id != chamber_type.id:
        raise GerminationChamberInvalidError(str(chamber_id))
    if not location.occupiable:
        raise GerminationChamberInvalidError(str(chamber_id))
    classification = location_service._resolve_governing_greenhouse_classification(
        db, tenant_id=tenant_id, farm_id=farm_id, parent=location
    )
    if classification != "nursery":
        raise GerminationChamberInvalidError(str(chamber_id))
    return location


def _validate_trolley(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, trolley_id: uuid.UUID) -> Asset:
    # `get_asset` is tenant/farm-scoped and raises the generic, existing
    # `AssetNotFoundError` for a missing/cross-tenant/cross-farm id -- same
    # 404-not-422 reasoning as `_validate_chamber` above.
    asset = asset_service.get_asset(db, tenant_id=tenant_id, farm_id=farm_id, asset_id=trolley_id)
    if asset.status != "active":
        raise GerminationTrolleyInvalidError(str(trolley_id))
    trolley_type = asset_service._get_asset_type_by_code(db, GERMINATION_TROLLEY_ASSET_TYPE_CODE)
    if asset.asset_type_id != trolley_type.id:
        raise GerminationTrolleyInvalidError(str(trolley_id))
    return asset


def _validate_slot(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, trolley_id: uuid.UUID, slot_id: uuid.UUID
) -> AssetPosition:
    # A truly nonexistent (or cross-tenant, via a mismatched trolley_id)
    # slot reads as `AssetPositionNotFoundError` (404) -- the same generic
    # error `movement_service._resolve_target` itself already raises for
    # this exact case, kept consistent rather than inventing a second
    # "not found" shape. `trolley_id` here has already been tenant/farm-
    # validated by `_validate_trolley` above, so "wrong trolley" already
    # implies "not a slot this caller may legitimately reference."
    position = db.execute(select(AssetPosition).where(AssetPosition.id == slot_id)).scalar_one_or_none()
    if position is None or position.asset_id != trolley_id:
        raise AssetPositionNotFoundError(str(slot_id))
    if position.position_kind != SLOT_POSITION_KIND:
        raise GerminationTraySlotInvalidError(str(slot_id))
    return position


def _validate_sown_tray(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, tray_id: uuid.UUID
) -> tuple[Carrier, BatchCarrierAssignment]:
    carrier = carrier_service.get_carrier(db, tenant_id=tenant_id, farm_id=farm_id, carrier_id=tray_id)
    carrier_type = carrier_service._get_carrier_type_by_code(db, SEED_TRAY_CARRIER_TYPE_CODE)
    if carrier.carrier_type_id != carrier_type.id:
        raise GerminationTraySlotInvalidError(str(tray_id))
    assignment = db.execute(
        select(BatchCarrierAssignment).where(
            BatchCarrierAssignment.carrier_id == tray_id,
            BatchCarrierAssignment.tenant_id == tenant_id,
            BatchCarrierAssignment.farm_id == farm_id,
            BatchCarrierAssignment.released_effective_time.is_(None),
            BatchCarrierAssignment.opening_sowing_event_id.isnot(None),
        )
    ).scalar_one_or_none()
    if assignment is None:
        raise TrayNotSownError(str(tray_id))
    return carrier, assignment


def _trolleys_current_chamber(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, trolley_id: uuid.UUID
) -> Location | None:
    """The Trolley's OWN current active Occupancy, if its target is a valid
    Nursery Germination Chamber -- durable, re-resolved from the live
    Occupancy row, never assumed or cached (mirrors
    `movement_service.get_resolved_location`'s own approach)."""
    occupancy = movement_service._get_active_occupancy_for_occupant(db, occupant_kind="asset", occupant_id=trolley_id)
    if occupancy is None or occupancy.target_location_id is None:
        return None
    try:
        return _validate_chamber(db, tenant_id=tenant_id, farm_id=farm_id, chamber_id=occupancy.target_location_id)
    except GerminationChamberInvalidError:
        return None


# --- Commands ----------------------------------------------------------------------


def place_trolley_in_chamber(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_command_id: uuid.UUID,
    trolley_id: uuid.UUID,
    chamber_id: uuid.UUID,
    effective_time: datetime,
    reason: str | None,
) -> Movement:
    """Section 13: initial placement (no current Occupancy) or a genuine
    move (Chamber -> Chamber) both go through the same, single,
    unmodified `movement_service.execute_movement` call -- it already
    resolves the real current source (or none) itself; no source is ever
    accepted from the caller."""
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    _validate_trolley(db, tenant_id=tenant_id, farm_id=farm_id, trolley_id=trolley_id)
    _validate_chamber(db, tenant_id=tenant_id, farm_id=farm_id, chamber_id=chamber_id)

    return movement_service.execute_movement(
        db,
        tenant_id=tenant_id,
        farm_id=farm_id,
        actor_user_id=actor_user_id,
        client_command_id=client_command_id,
        effective_time=effective_time,
        occupant_kind="asset",
        occupant_id=trolley_id,
        destination_kind="location",
        destination_id=chamber_id,
        reason=reason,
    )


def place_tray_in_slot(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_command_id: uuid.UUID,
    tray_id: uuid.UUID,
    trolley_id: uuid.UUID,
    slot_id: uuid.UUID,
    effective_time: datetime,
    reason: str | None,
) -> Movement:
    """Section 15-16: the Germination-specific business rule
    `movement_service` cannot express generically -- the Trolley must
    CURRENTLY occupy a valid Nursery Germination Chamber, checked fresh
    (not cached) on every call, before the generic Movement command is
    even attempted. `BatchCarrierAssignment`/Seed Lot/Seeds Sown are
    validated for eligibility but never written to -- this command touches
    only `Occupancy`/`Movement` (section 18)."""
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    _validate_sown_tray(db, tenant_id=tenant_id, farm_id=farm_id, tray_id=tray_id)
    _validate_trolley(db, tenant_id=tenant_id, farm_id=farm_id, trolley_id=trolley_id)
    _validate_slot(db, tenant_id=tenant_id, farm_id=farm_id, trolley_id=trolley_id, slot_id=slot_id)

    if _trolleys_current_chamber(db, tenant_id=tenant_id, farm_id=farm_id, trolley_id=trolley_id) is None:
        raise TrolleyNotInGerminationError(str(trolley_id))

    return movement_service.execute_movement(
        db,
        tenant_id=tenant_id,
        farm_id=farm_id,
        actor_user_id=actor_user_id,
        client_command_id=client_command_id,
        effective_time=effective_time,
        occupant_kind="carrier",
        occupant_id=tray_id,
        destination_kind="asset_position",
        destination_id=slot_id,
        reason=reason,
    )


# --- Command reads (compose the rich response from the plain Movement) -------------


def _carrier_summary(carrier: Carrier, carrier_type_code: str, carrier_type_name: str) -> CarrierSummary:
    return CarrierSummary(
        id=carrier.id, code=carrier.code,
        carrier_type=CarrierTypeSummary(id=carrier.carrier_type_id, code=carrier_type_code, name=carrier_type_name),
    )


def describe_trolley_placement(db: Session, *, movement: Movement) -> TrolleyPlacementRead:
    trolley = db.get(Asset, movement.occupant_asset_id)
    chamber = db.get(Location, movement.destination_location_id)
    return TrolleyPlacementRead(
        movement_id=movement.id, client_command_id=movement.client_command_id,
        trolley=TrolleySummary(id=trolley.id, code=trolley.code, name=trolley.name),
        chamber=GerminationChamberSummary(id=chamber.id, code=chamber.code, name=chamber.name),
        effective_time=movement.effective_time,
    )


def describe_tray_placement(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, movement: Movement) -> TrayPlacementRead:
    tray = db.get(Carrier, movement.occupant_carrier_id)
    slot = db.get(AssetPosition, movement.destination_asset_position_id)
    shelf = db.get(AssetPosition, slot.parent_position_id)
    trolley = db.get(Asset, slot.asset_id)
    chamber = _trolleys_current_chamber(db, tenant_id=tenant_id, farm_id=farm_id, trolley_id=trolley.id)
    row = db.execute(
        text(
            "SELECT cb.code, sel.seed_count, ct.code AS carrier_type_code, ct.name AS carrier_type_name "
            "FROM batch_carrier_assignments bca "
            "JOIN crop_batches cb ON cb.id = bca.batch_id "
            "JOIN sowing_event_lines sel ON sel.batch_carrier_assignment_id = bca.id "
            "JOIN carriers c ON c.id = bca.carrier_id "
            "JOIN carrier_types ct ON ct.id = c.carrier_type_id "
            "WHERE bca.carrier_id = :cid AND bca.tenant_id = :tid AND bca.farm_id = :fid "
            "AND bca.released_effective_time IS NULL"
        ),
        {"cid": tray.id, "tid": tenant_id, "fid": farm_id},
    ).mappings().first()
    return TrayPlacementRead(
        movement_id=movement.id, client_command_id=movement.client_command_id,
        tray=_carrier_summary(tray, row["carrier_type_code"], row["carrier_type_name"]),
        batch_code=row["code"], seeds_sown=row["seed_count"],
        trolley=TrolleySummary(id=trolley.id, code=trolley.code, name=trolley.name),
        slot=SlotSummary(id=slot.id, code=slot.code, name=slot.name, shelf_code=shelf.code),
        chamber=GerminationChamberSummary(id=chamber.id, code=chamber.code, name=chamber.name),
        effective_time=movement.effective_time,
    )


# --- Reads ---------------------------------------------------------------------------


def list_available_chambers(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID
) -> list[GerminationChamberAvailabilityRead]:
    """Section 21: same-farm/tenant Nursery Germination Chambers only.
    `active_trolley_count` is a fresh COUNT of live Occupancy rows -- never
    inferred from configured capacity alone."""
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    rows = db.execute(
        text(
            "SELECT l.id, l.code, l.name, l.capacity, "
            "(SELECT count(*) FROM occupancies o WHERE o.target_location_id = l.id AND o.end_time IS NULL) "
            "AS active_trolley_count "
            "FROM locations l "
            "JOIN location_types lt ON lt.id = l.location_type_id AND lt.code = :chamber_code "
            "JOIN locations gh ON gh.id = l.parent_location_id "
            "WHERE l.tenant_id = :tid AND l.farm_id = :fid AND l.status = 'active' AND l.occupiable "
            "AND gh.greenhouse_classification = 'nursery' "
            "ORDER BY l.code"
        ),
        {"tid": tenant_id, "fid": farm_id, "chamber_code": GERMINATION_CHAMBER_LOCATION_TYPE_CODE},
    ).mappings().all()
    result = []
    for r in rows:
        effective_capacity = r["capacity"] or 1
        result.append(
            GerminationChamberAvailabilityRead(
                id=r["id"], code=r["code"], name=r["name"], trolley_capacity=r["capacity"],
                active_trolley_count=r["active_trolley_count"],
                remaining_capacity=max(effective_capacity - r["active_trolley_count"], 0),
            )
        )
    return result


def list_available_trolleys(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> list[AvailableTrolleyRead]:
    """Section 22: Trolleys currently occupying a valid Nursery Germination
    Chamber -- eligible destinations for Tray placement. Slot availability
    is derived from actual active Occupancy, never the configured slot
    count alone (section 23's own explicit requirement)."""
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    rows = db.execute(
        text(
            "SELECT a.id, a.code, a.name, c.id AS chamber_id, c.code AS chamber_code, c.name AS chamber_name, "
            "(SELECT count(*) FROM asset_positions sl WHERE sl.asset_id = a.id AND sl.position_kind = 'slot') "
            "AS total_slot_count, "
            "(SELECT count(*) FROM asset_positions sl "
            " JOIN occupancies o ON o.target_asset_position_id = sl.id AND o.end_time IS NULL "
            " WHERE sl.asset_id = a.id AND sl.position_kind = 'slot') AS occupied_slot_count "
            "FROM assets a "
            "JOIN asset_types at ON at.id = a.asset_type_id AND at.code = :trolley_code "
            "JOIN occupancies o ON o.occupant_asset_id = a.id AND o.end_time IS NULL "
            "JOIN locations c ON c.id = o.target_location_id "
            "JOIN location_types clt ON clt.id = c.location_type_id AND clt.code = :chamber_code "
            "JOIN locations gh ON gh.id = c.parent_location_id AND gh.greenhouse_classification = 'nursery' "
            "WHERE a.tenant_id = :tid AND a.farm_id = :fid AND a.status = 'active' "
            "ORDER BY a.code"
        ),
        {
            "tid": tenant_id, "fid": farm_id,
            "trolley_code": GERMINATION_TROLLEY_ASSET_TYPE_CODE, "chamber_code": GERMINATION_CHAMBER_LOCATION_TYPE_CODE,
        },
    ).mappings().all()
    return [
        AvailableTrolleyRead(
            id=r["id"], code=r["code"], name=r["name"],
            chamber=GerminationChamberSummary(id=r["chamber_id"], code=r["chamber_code"], name=r["chamber_name"]),
            total_slot_count=r["total_slot_count"], occupied_slot_count=r["occupied_slot_count"],
            available_slot_count=r["total_slot_count"] - r["occupied_slot_count"],
        )
        for r in rows
    ]


def list_trolley_slots(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, trolley_id: uuid.UUID
) -> list[TrolleySlotAvailabilityRead]:
    """Section 23: every Slot on the Trolley, occupied or not, with human
    Shelf/Slot codes -- the frontend decides how to group/hide occupied
    ones; the backend never hides truthful state."""
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    _validate_trolley(db, tenant_id=tenant_id, farm_id=farm_id, trolley_id=trolley_id)
    rows = db.execute(
        text(
            "SELECT slot.id, slot.code, slot.name, shelf.code AS shelf_code, "
            "(o.id IS NOT NULL) AS occupied "
            "FROM asset_positions slot "
            "JOIN asset_positions shelf ON shelf.id = slot.parent_position_id "
            "LEFT JOIN occupancies o ON o.target_asset_position_id = slot.id AND o.end_time IS NULL "
            "WHERE slot.asset_id = :aid AND slot.position_kind = 'slot' "
            "ORDER BY shelf.code, slot.code"
        ),
        {"aid": trolley_id},
    ).mappings().all()
    return [
        TrolleySlotAvailabilityRead(
            id=r["id"], code=r["code"], name=r["name"], shelf_code=r["shelf_code"], occupied=r["occupied"]
        )
        for r in rows
    ]


def list_germination_trays(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> list[GerminationTrayRead]:
    """Section 19-20: every Sown Seed Tray (active, sowing-origin
    BatchCarrierAssignment), classified into awaiting_placement / elsewhere
    / in_germination -- derived fresh from live Occupancy state, never a
    persisted status field. One query, no N+1 (section 44)."""
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    rows = db.execute(
        text(
            "SELECT "
            "cb.id AS batch_id, cb.code AS batch_code, "
            "sl.id AS seed_lot_id, sl.code AS seed_lot_code, sl.supplier_lot_reference, "
            "crop.id AS crop_id, crop.code AS crop_code, crop.common_name, "
            "variety.id AS variety_id, variety.code AS variety_code, variety.name AS variety_name, "
            "carrier.id AS tray_id, carrier.code AS tray_code, ct.id AS carrier_type_id, "
            "ct.code AS carrier_type_code, ct.name AS carrier_type_name, "
            "bca.id AS assignment_id, sel.seed_count, "
            "occ.id AS occupancy_id, slot.id AS slot_id, slot.code AS slot_code, slot.name AS slot_name, "
            "shelf.code AS shelf_code, trolley.id AS trolley_id, trolley.code AS trolley_code, "
            "trolley.name AS trolley_name, trolley_occ.target_location_id AS chamber_id, "
            "chamber.code AS chamber_code, chamber.name AS chamber_name, chamber_gh.greenhouse_classification "
            "FROM batch_carrier_assignments bca "
            "JOIN crop_batches cb ON cb.id = bca.batch_id "
            "JOIN carriers carrier ON carrier.id = bca.carrier_id "
            "JOIN carrier_types ct ON ct.id = carrier.carrier_type_id AND ct.code = :seed_tray_code "
            "JOIN sowing_event_lines sel ON sel.batch_carrier_assignment_id = bca.id "
            "JOIN seed_lots sl ON sl.id = sel.seed_lot_id "
            "JOIN crops crop ON crop.id = sl.crop_id "
            "JOIN varieties variety ON variety.id = sl.variety_id "
            "LEFT JOIN occupancies occ ON occ.occupant_carrier_id = carrier.id AND occ.end_time IS NULL "
            "LEFT JOIN asset_positions slot ON slot.id = occ.target_asset_position_id "
            "LEFT JOIN asset_positions shelf ON shelf.id = slot.parent_position_id "
            "LEFT JOIN assets trolley ON trolley.id = slot.asset_id "
            "LEFT JOIN occupancies trolley_occ ON trolley_occ.occupant_asset_id = trolley.id AND trolley_occ.end_time IS NULL "
            "LEFT JOIN locations chamber ON chamber.id = trolley_occ.target_location_id "
            "LEFT JOIN location_types chamber_lt ON chamber_lt.id = chamber.location_type_id AND chamber_lt.code = :chamber_code "
            "LEFT JOIN locations chamber_gh ON chamber_gh.id = chamber.parent_location_id "
            "WHERE bca.tenant_id = :tid AND bca.farm_id = :fid "
            "AND bca.released_effective_time IS NULL AND bca.opening_sowing_event_id IS NOT NULL "
            "ORDER BY cb.code, carrier.code"
        ),
        {
            "tid": tenant_id, "fid": farm_id,
            "seed_tray_code": SEED_TRAY_CARRIER_TYPE_CODE, "chamber_code": GERMINATION_CHAMBER_LOCATION_TYPE_CODE,
        },
    ).mappings().all()

    results = []
    for r in rows:
        in_germination = (
            r["occupancy_id"] is not None and r["trolley_id"] is not None and r["chamber_id"] is not None
            and r["chamber_code"] is not None and r["greenhouse_classification"] == "nursery"
        )
        if in_germination:
            state = "in_germination"
            placement = GerminationResolvedPlacement(
                trolley=TrolleySummary(id=r["trolley_id"], code=r["trolley_code"], name=r["trolley_name"]),
                chamber=GerminationChamberSummary(id=r["chamber_id"], code=r["chamber_code"], name=r["chamber_name"]),
                slot=SlotSummary(id=r["slot_id"], code=r["slot_code"], name=r["slot_name"], shelf_code=r["shelf_code"]),
            )
        elif r["occupancy_id"] is None:
            state = "awaiting_placement"
            placement = None
        else:
            state = "elsewhere"
            placement = None
        results.append(
            GerminationTrayRead(
                batch_id=r["batch_id"], batch_code=r["batch_code"],
                seed_lot=SeedLotSummary(
                    id=r["seed_lot_id"], code=r["seed_lot_code"], supplier_lot_reference=r["supplier_lot_reference"],
                    crop=CropSummary(id=r["crop_id"], code=r["crop_code"], common_name=r["common_name"]),
                    variety=VarietySummary(id=r["variety_id"], code=r["variety_code"], name=r["variety_name"]),
                ),
                tray=_carrier_summary(
                    Carrier(id=r["tray_id"], code=r["tray_code"], carrier_type_id=r["carrier_type_id"]),
                    r["carrier_type_code"], r["carrier_type_name"],
                ),
                batch_carrier_assignment_id=r["assignment_id"], seeds_sown=r["seed_count"],
                state=state, placement=placement,
            )
        )
    return results
