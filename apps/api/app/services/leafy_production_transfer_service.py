"""NURSERY-OPS-005B: the Leafy Production Transfer composite operator
command --

    Nursery Cultivation Plate source(s)
    -> biological Transplant                     (transplant_service._record_transplant_core)
    -> Production Cultivation Plate destination(s)
    -> physical placement of those Plate(s)       (movement_service._execute_movement_core)
    -> Leafy Production Table(s)

committed atomically, one transaction, one commit. Mirrors `intersalads_
transplant_service.py`'s proven architecture line-for-line -- composes the
two existing, unmodified non-committing cores rather than building a second
biological-accounting or physical-movement engine; Movement gains zero
Transplant/Leafy-Production awareness from this module. `_record_transplant_
core` already accepts a `nursery_cultivation_plate` source (NURSERY-OPS-
005A's own unified source authority) and a `production_cultivation_plate`
destination (already generic, gated only by the target WorkflowStage's own
`required_carrier_type_id`) with zero code changes needed on that side --
005A's population architecture is used exactly as-is, never re-derived here.

Execution order: `_record_transplant_core` FIRST, exactly as InterSalads
requires and for the identical reason (a caller composing them must run it
before any write it cannot afford to lose to that core's own internal
IntegrityError-triggered rollback).

Idempotency: one outer `client_command_id` anchors the Transplant half
(`_record_transplant_core`'s own three-tier idempotency, unchanged); each
destination Plate's Movement gets its own deterministically-derived command
id via `_derive_movement_client_command_id`, the exact InterSalads formula
(uuid5 of `f"{outer_id}:{destination_carrier_id}"`) under a distinct,
non-colliding namespace constant.

On exact replay, this module does NOT re-invoke the movement cores -- it
derives expected per-destination Movement command ids, loads the already-
committed Movements, and verifies each against the requested destination
Carrier/Location, raising `LeafyProductionTransferReplayStateConflictError`
on any mismatch, mirroring `_resolve_expected_movements` exactly.

Destination-Location lock order: identical rationale and mechanism to
`intersalads_transplant_service._lock_destination_locations_in_order` --
every distinct destination Location is locked in deterministic (sorted)
UUID order before any Movement call, closing the same proven inter-
transaction deadlock risk for two different Batches' concurrent composite
commands targeting overlapping Tables."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.location import Location
from app.models.movement import Movement
from app.schemas.carrier_specification import CarrierSpecificationSummary
from app.schemas.crop_batch import CropSummary, VarietySummary
from app.schemas.leafy_production_transfer import (
    AvailableLeafyProductionSourceRead,
    AvailableProductionCultivationPlateRead,
    LeafyProductionCurrentLocationSummary,
    LeafyProductionDestinationLineRead,
    LeafyProductionTransferRead,
)
from app.schemas.sowing_event import CarrierSummary, CarrierTypeSummary
from app.services import carrier_service, movement_service, transplant_service, transplant_source_authority
from app.services.errors import LeafyProductionTransferReplayStateConflictError

NURSERY_CULTIVATION_PLATE_CARRIER_TYPE_CODE = "nursery_cultivation_plate"
PRODUCTION_CULTIVATION_PLATE_CARRIER_TYPE_CODE = "production_cultivation_plate"


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


# A fixed, stable namespace distinct from both seedling_entry_service's and
# intersalads_transplant_service's own -- never colliding with either, or
# with a genuinely different destination Carrier under the same outer
# command.
_MOVEMENT_COMMAND_NAMESPACE = uuid.UUID("413a7a50-f6e3-4975-95cb-fdd239389d24")


def _derive_movement_client_command_id(
    outer_client_command_id: uuid.UUID, destination_carrier_id: uuid.UUID
) -> uuid.UUID:
    """Deterministic and collision-safe: the same (outer command,
    destination carrier) pair always re-derives the same child Movement
    identity, so an exact replay of the composite command never creates a
    second Movement for the same Plate."""
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
            raise LeafyProductionTransferReplayStateConflictError(
                f"expected Movement for destination carrier {cid} does not exist"
            )
        if movement.occupant_carrier_id != cid or movement.destination_location_id != expected_location_id:
            raise LeafyProductionTransferReplayStateConflictError(
                f"existing Movement for destination carrier {cid} does not match the requested "
                f"destination carrier/location"
            )
        movements_by_carrier_id[cid] = movement
    return movements_by_carrier_id


def _describe_leafy_production_transfer(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    transplant_event_id: uuid.UUID,
    movements_by_carrier_id: dict[uuid.UUID, Movement],
) -> LeafyProductionTransferRead:
    """Reuses the existing, already-proven generic Transplant read
    composition (`transplant_service.get_transplant_event`) in full,
    layering only the genuinely new placement facts on top of its
    destination lines -- no duplicate genealogy query, mirroring
    `intersalads_transplant_service._describe_intersalads_transplant`
    exactly."""
    generic = transplant_service.get_transplant_event(
        db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id, transplant_event_id=transplant_event_id
    )
    destination_lines = [
        LeafyProductionDestinationLineRead(
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
    return LeafyProductionTransferRead(
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


def record_leafy_production_transfer(
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
) -> LeafyProductionTransferRead:
    """Owns the transaction: commit, rollback, and composite replay
    behavior. `destination_lines` items carry `destination_carrier_id`,
    `assigned_plant_count`, `destination_location_id`, `note` -- the extra
    `destination_location_id` key is simply ignored by
    `_record_transplant_core` (it only reads the keys it knows about), so
    the same dicts are passed straight through, no stripping needed. Never
    calls `crop_batch_service.transition_stage` -- this command has no
    stage-transition side effect of any kind, by design (NURSERY-OPS-005A's
    own leaving-transplanting and entering-production guards remain the
    Batch's only stage gates)."""
    try:
        event, is_new = transplant_service._record_transplant_core(
            db, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, batch_id=batch_id,
            client_command_id=client_command_id, effective_time=effective_time, note=note,
            source_lines=source_lines, destination_lines=destination_lines, allocations=allocations,
        )
        if is_new:
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

    return _describe_leafy_production_transfer(
        db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id, transplant_event_id=event.id,
        movements_by_carrier_id=movements_by_carrier_id,
    )


def list_available_leafy_production_sources(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID | None = None,
) -> list[AvailableLeafyProductionSourceRead]:
    """NURSERY-OPS-005B section 13-15: every `nursery_cultivation_plate`-
    typed BatchCarrierAssignment currently eligible as a Leafy Production
    Transfer source -- active (unreleased) only, so a released historical
    generation can structurally never appear; a restored active descendant
    appears in its place automatically, with zero special-casing. One query
    for batch/carrier/crop/variety/current-location context (no N+1); the
    authoritative available count is then resolved per row through the ONE
    approved unified source-authority path (`transplant_source_authority.
    get_source_available`), never hand-summed from historical events here
    or on the client -- rows with a non-positive result are dropped.
    Physical current-location context is informational only (section 3):
    never an eligibility filter."""
    carrier_service._require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    query = (
        "SELECT bca.id AS assignment_id, "
        "carrier.id AS carrier_id, carrier.code AS carrier_code, "
        "ct.id AS carrier_type_id, ct.code AS carrier_type_code, ct.name AS carrier_type_name, "
        "cb.id AS batch_id, cb.code AS batch_code, "
        "crop.id AS crop_id, crop.code AS crop_code, crop.common_name, "
        "variety.id AS variety_id, variety.code AS variety_code, variety.name AS variety_name, "
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
    )
    params: dict[str, object] = {"tid": tenant_id, "fid": farm_id, "plate_type_code": NURSERY_CULTIVATION_PLATE_CARRIER_TYPE_CODE}
    if batch_id is not None:
        query += "AND cb.id = :bid "
        params["bid"] = batch_id
    query += "ORDER BY cb.code, carrier.code"

    rows = db.execute(text(query), params).mappings().all()

    as_of = datetime.now(timezone.utc)
    results: list[AvailableLeafyProductionSourceRead] = []
    for r in rows:
        authority = transplant_source_authority.resolve_source_authority(
            db, assignment_id=r["assignment_id"], carrier_type_code=r["carrier_type_code"],
        )
        if authority is None:
            continue
        available = transplant_source_authority.get_source_available(
            db, authority=authority, assignment_id=r["assignment_id"], as_of=as_of,
        )
        if available <= 0:
            continue
        results.append(
            AvailableLeafyProductionSourceRead(
                source_assignment_id=r["assignment_id"],
                carrier=CarrierSummary(
                    id=r["carrier_id"], code=r["carrier_code"],
                    carrier_type=CarrierTypeSummary(
                        id=r["carrier_type_id"], code=r["carrier_type_code"], name=r["carrier_type_name"],
                    ),
                ),
                batch_id=r["batch_id"], batch_code=r["batch_code"],
                crop=CropSummary(id=r["crop_id"], code=r["crop_code"], common_name=r["common_name"]),
                variety=(
                    VarietySummary(id=r["variety_id"], code=r["variety_code"], name=r["variety_name"])
                    if r["variety_id"] is not None
                    else None
                ),
                authoritative_available_count=available,
                current_location=(
                    LeafyProductionCurrentLocationSummary(
                        id=r["location_id"], code=r["location_code"], name=r["location_name"],
                        location_type_code=r["location_type_code"],
                    )
                    if r["location_id"] is not None
                    else None
                ),
            )
        )
    return results


def list_available_production_plates(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID
) -> list[AvailableProductionCultivationPlateRead]:
    """NURSERY-OPS-005B section 16-18: every `production_cultivation_plate`
    Carrier in this Farm eligible as a NEW Leafy Production Transfer
    destination right now -- active status, no currently-active
    `BatchCarrierAssignment`. Deliberately does NOT require "no active
    Occupancy" -- Movement legitimately relocates a Carrier and closes its
    prior Occupancy atomically as part of the same move. One query, no N+1,
    mirrors `intersalads_transplant_service.list_available_intersalads_
    plates`'s exact shape for the sibling carrier type."""
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
        {"tid": tenant_id, "fid": farm_id, "plate_type_code": PRODUCTION_CULTIVATION_PLATE_CARRIER_TYPE_CODE},
    ).mappings().all()
    return [
        AvailableProductionCultivationPlateRead(
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
