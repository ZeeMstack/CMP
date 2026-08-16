"""NURSERY-OPS-003A: Seedling Entry & Placement.

FROZEN authoritative physical model (product decision, no table position):

    Nursery Greenhouse
    -> Seedling Area (not occupiable)
        -> Seedling Table (occupiable, capacity = number of simultaneous
           Seed Tray occupants -- never a seedling/plant count)
            -> Seed Tray Carrier (occupies the Table directly)

A completed Germination outcome cannot wait for a later, separate ticket to
be frozen: once a Tray genuinely enters Seedling operations, CMP must record
exactly which completed `GerminationOutcomeSnapshot` supplied the starting
biological quantity, permanently -- otherwise a later, even historically
truthful, Germination reassessment could silently change a quantity Seedling
operations has already built history on top of (see
`docs/domain/OBSERVATION_QUALITY_MODEL.md`'s NURSERY-OPS-003A addendum).

This module therefore commits TWO separate domain facts atomically, in one
transaction/commit:

1. A generic, biology-blind physical `Movement` (Trolley Slot/wherever the
   Tray currently is -> the selected Seedling Table) -- reuses
   `movement_service._execute_movement_core` verbatim, adding no second
   physical-movement engine. `movement_service` itself gains no Germination/
   Seedling awareness (section 14 of the ticket): every validation this
   module adds lives here, never inside `movement_service`.
2. An immutable `SeedlingEntry` anchor row: the exact completed Germination
   snapshot that was historically valid at the entry's own `effective_time`
   (never simply "the latest completed snapshot now" -- section 10/19),
   and the frozen `starting_living_seedling_count` derived from it
   server-side (never caller-supplied).

At most one `SeedlingEntry` may ever exist per `BatchCarrierAssignment`
(section 8) -- a later physical Movement (e.g. a future Table-to-Table move,
deliberately NOT built here pending product policy, section 23) is not
another biological entry. No Seedling biological loss/removal accounting
exists yet -- that is NURSERY-OPS-003B's own, separate scope (section 35/36):
until then, current biological quantity for a Tray with a SeedlingEntry is
simply its own `starting_living_seedling_count`, unconditionally."""

import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.carrier import Carrier
from app.models.crop_batch import CropBatch
from app.models.location import Location
from app.models.seedling_entry import SeedlingEntry
from app.schemas.seedling_entry import (
    AvailableSeedlingTableRead,
    GerminationHandoffSummary,
    ResolvedPhysicalPlacement,
    SeedlingAreaSummary,
    SeedlingCandidateTrayRead,
    SeedlingEntryRead,
    SeedlingEntrySummary,
    SeedlingGreenhouseSummary,
    SeedlingTableSummary,
)
from app.schemas.germination import GerminationChamberSummary, GerminationResolvedPlacement, SlotSummary, TrolleySummary
from app.schemas.crop_batch import CropSummary, VarietySummary
from app.schemas.sowing_event import CarrierSummary, CarrierTypeSummary, SeedLotSummary
from app.services import carrier_service, farm_service, location_service, movement_service
from app.services.audit import append_audit_event
from app.services.errors import (
    BatchCarrierAssignmentNotFoundError,
    FarmNotFoundError,
    InvalidEffectiveTimeError,
    InvalidSeedlingEntryEffectiveTimeError,
    NoCompletedGerminationHandoffError,
    SeedlingEntryAlreadyExistsError,
    SeedlingEntryCommandReusedWithDifferentPayloadError,
    SeedlingEntryPhysicalChronologyError,
    SeedlingEntryValidationError,
    SeedlingTableInvalidError,
)

SEED_TRAY_CARRIER_TYPE_CODE = "seed_tray"
SEEDLING_TABLE_LOCATION_TYPE_CODE = "seedling_table"
GERMINATION_CHAMBER_LOCATION_TYPE_CODE = "germination_chamber"

# Section 28: a fixed, stable namespace so the derived Movement
# client_command_id is a pure, deterministic function of the SeedlingEntry
# command's own client_command_id -- never a fresh uuid4() on retry, and
# never colliding with a genuinely different SeedlingEntry command (uuid5 of
# distinct inputs under one namespace does not collide in practice).
_MOVEMENT_COMMAND_NAMESPACE = uuid.UUID("6b2f9e2a-6e9b-4c9a-9a2b-3e6a1f9c7d4a")


def _require_active_farm(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> None:
    farm = farm_service.get_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    if farm.status != "active":
        raise FarmNotFoundError(str(farm_id))


def _derive_movement_client_command_id(entry_client_command_id: uuid.UUID) -> uuid.UUID:
    """Section 28: deterministic, collision-safe derivation -- the same
    entry command_id always re-derives the same child Movement identity, so
    an exact replay of the SeedlingEntry command never creates a second
    Movement and never weakens Movement's own client_command_id uniqueness."""
    return uuid.uuid5(_MOVEMENT_COMMAND_NAMESPACE, str(entry_client_command_id))


def _compute_fingerprint(
    *, tenant_id, farm_id, actor_user_id, batch_carrier_assignment_id, destination_seedling_table_id,
    effective_time: datetime, reason: str | None,
) -> str:
    parts = [
        str(tenant_id), str(farm_id), str(actor_user_id) if actor_user_id else "",
        str(batch_carrier_assignment_id), str(destination_seedling_table_id),
        effective_time.astimezone(timezone.utc).isoformat(), reason or "",
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _find_existing_entry(db: Session, *, tenant_id: uuid.UUID, client_command_id: uuid.UUID) -> SeedlingEntry | None:
    return db.execute(
        select(SeedlingEntry).where(
            SeedlingEntry.tenant_id == tenant_id, SeedlingEntry.client_command_id == client_command_id
        )
    ).scalar_one_or_none()


def _validate_seedling_table(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, table_id: uuid.UUID
) -> Location:
    # Tenant/farm-scoped `get_location` raises the generic, existing
    # `LocationNotFoundError` (404) for a missing/cross-tenant/cross-farm id
    # -- only a row that genuinely resolves in this tenant/farm is then
    # checked against Seedling-specific business rules (mirrors
    # `germination_service._validate_chamber`'s own reasoning).
    location = location_service.get_location(db, tenant_id=tenant_id, farm_id=farm_id, location_id=table_id)
    if location.status != "active":
        raise SeedlingTableInvalidError(str(table_id))
    table_type = location_service._get_location_type_by_code(db, SEEDLING_TABLE_LOCATION_TYPE_CODE)
    if location.location_type_id != table_type.id:
        raise SeedlingTableInvalidError(str(table_id))
    if not location.occupiable:
        raise SeedlingTableInvalidError(str(table_id))
    classification = location_service._resolve_governing_greenhouse_classification(
        db, tenant_id=tenant_id, farm_id=farm_id, parent=location
    )
    if classification != "nursery":
        raise SeedlingTableInvalidError(str(table_id))
    return location


def _resolve_source_snapshot(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_carrier_assignment_id: uuid.UUID,
    effective_time: datetime,
) -> dict:
    """Section 10: temporal truth, not "latest completed now" -- the latest
    COMPLETED snapshot whose own `ObservationEvent.effective_time` is at or
    before this entry's `effective_time`, using 002B's own deterministic
    tie-break (`effective_time`, then `recorded_time`). Selecting id and
    counts from the SAME row in one query means a concurrently-recording
    newer completed snapshot can never produce a mixed id/count result
    (section 31) -- whichever row this query returns is used verbatim."""
    row = db.execute(
        text(
            "SELECT gos.id, gos.normal_seedling_count, gos.abnormal_seedling_count, oe.effective_time "
            "FROM germination_outcome_snapshots gos "
            "JOIN observation_events oe ON oe.id = gos.observation_event_id "
            "WHERE gos.tenant_id = :tid AND gos.farm_id = :fid "
            "AND gos.batch_carrier_assignment_id = :aid AND gos.assessment_complete = true "
            "AND oe.effective_time <= :t "
            "ORDER BY oe.effective_time DESC, oe.recorded_time DESC LIMIT 1"
        ),
        {"tid": tenant_id, "fid": farm_id, "aid": batch_carrier_assignment_id, "t": effective_time},
    ).mappings().first()
    if row is None:
        raise NoCompletedGerminationHandoffError(str(batch_carrier_assignment_id))
    return dict(row)


# --- Command -----------------------------------------------------------------------


def record_seedling_entry(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_command_id: uuid.UUID,
    batch_carrier_assignment_id: uuid.UUID,
    destination_seedling_table_id: uuid.UUID,
    effective_time: datetime,
    reason: str | None,
) -> SeedlingEntry:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    fingerprint = _compute_fingerprint(
        tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id,
        batch_carrier_assignment_id=batch_carrier_assignment_id,
        destination_seedling_table_id=destination_seedling_table_id, effective_time=effective_time, reason=reason,
    )

    # Section 27: exact replay resolves here, before ANY lock, re-resolution,
    # or capacity recheck -- the original SeedlingEntry (and its already-
    # linked Movement/source snapshot/frozen quantity) is returned verbatim,
    # regardless of what has changed since (Table now full, Tray moved
    # again, a newer Germination snapshot exists).
    existing = _find_existing_entry(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise SeedlingEntryCommandReusedWithDifferentPayloadError(str(client_command_id))

    if effective_time > datetime.now(timezone.utc):
        raise InvalidSeedlingEntryEffectiveTimeError("effective_time cannot be in the future")

    # Section 29/31: lock the owning CropBatch FIRST -- deliberately the
    # SAME lock target and order as observation_service.record_observation
    # (which locks CropBatch, then later inserts a GerminationOutcomeSnapshot
    # row whose FK implicitly locks the assignment). Locking the assignment
    # directly here instead would invert that established, documented
    # CMP-wide discipline (CropBatch row = the shared serialization point
    # for coordinated per-batch writes) and produces a genuine cross-command
    # deadlock against a concurrent Germination-outcome command for the same
    # assignment (reproduced during this ticket's own concurrency testing).
    # An unlocked probe resolves batch_id first since assignment.batch_id is
    # immutable post-creation -- safe to read before the lock is held.
    batch_id_probe = db.execute(
        select(BatchCarrierAssignment.batch_id).where(
            BatchCarrierAssignment.id == batch_carrier_assignment_id,
            BatchCarrierAssignment.tenant_id == tenant_id,
            BatchCarrierAssignment.farm_id == farm_id,
        )
    ).scalar_one_or_none()
    if batch_id_probe is None:
        raise BatchCarrierAssignmentNotFoundError(str(batch_carrier_assignment_id))
    db.execute(select(CropBatch.id).where(CropBatch.id == batch_id_probe).with_for_update()).scalar_one()

    assignment = db.execute(
        select(BatchCarrierAssignment).where(
            BatchCarrierAssignment.id == batch_carrier_assignment_id,
            BatchCarrierAssignment.tenant_id == tenant_id,
            BatchCarrierAssignment.farm_id == farm_id,
        )
    ).scalar_one_or_none()
    if assignment is None:
        raise BatchCarrierAssignmentNotFoundError(str(batch_carrier_assignment_id))

    # Re-check idempotency now the CropBatch lock has serialized us behind
    # any concurrent submission of the same command id -- a losing
    # concurrent duplicate must resolve as a replay here, before any
    # business rule evaluates state a concurrent winner may have just
    # committed (mirrors movement_service's own two-stage recheck).
    existing = _find_existing_entry(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise SeedlingEntryCommandReusedWithDifferentPayloadError(str(client_command_id))

    carrier = db.get(Carrier, assignment.carrier_id)
    carrier_type = carrier_service._get_carrier_type_by_code(db, SEED_TRAY_CARRIER_TYPE_CODE)
    if carrier is None or carrier.carrier_type_id != carrier_type.id:
        raise SeedlingEntryValidationError("assignment is not a seed_tray carrier")

    if effective_time < assignment.assigned_effective_time:
        raise InvalidSeedlingEntryEffectiveTimeError(
            "effective_time precedes the assignment's assigned_effective_time"
        )
    if assignment.released_effective_time is not None and effective_time >= assignment.released_effective_time:
        raise InvalidSeedlingEntryEffectiveTimeError(
            "effective_time is at or after the assignment's release; the assignment was not active at that time"
        )

    # Section 8/22: at most one SeedlingEntry per assignment, ever -- checked
    # under the same assignment lock so a losing concurrent request always
    # observes the winner's already-committed row (backstopped by
    # ux_seedling_entries_assignment at the DB layer regardless).
    already = db.execute(
        select(SeedlingEntry.id).where(SeedlingEntry.batch_carrier_assignment_id == batch_carrier_assignment_id)
    ).scalar_one_or_none()
    if already is not None:
        raise SeedlingEntryAlreadyExistsError(str(batch_carrier_assignment_id))

    _validate_seedling_table(db, tenant_id=tenant_id, farm_id=farm_id, table_id=destination_seedling_table_id)

    # Section 10/19/31: resolve historically, not "latest completed now".
    snapshot = _resolve_source_snapshot(
        db, tenant_id=tenant_id, farm_id=farm_id, batch_carrier_assignment_id=batch_carrier_assignment_id,
        effective_time=effective_time,
    )
    starting_count = snapshot["normal_seedling_count"] + snapshot["abnormal_seedling_count"]

    # Section 15/16: one transaction, one commit -- the physical Movement
    # (via the non-committing core) and the SeedlingEntry insert below share
    # this same uncommitted transaction; either both survive the final
    # commit or neither does.
    #
    # NURSERY-OPS-003A.1: Movement is append-forward only --
    # `_execute_movement_core` already rejects `effective_time` preceding
    # the Tray's CURRENT active Occupancy's own `effective_time` (whether
    # that Occupancy was opened by an earlier SeedlingEntry, a bare generic
    # Movement, or the original Germination placement). This is exactly the
    # protection needed: a historical SeedlingEntry `effective_time` must
    # never be allowed to fabricate a Movement that falsifies the Tray's
    # already-recorded physical chronology (e.g. a Tray that has since
    # moved again). That check happens entirely before any row is written
    # in this call (every prior step is a read/lock), so catching it here
    # requires no rollback of partial state -- nothing has been written yet.
    movement_command_id = _derive_movement_client_command_id(client_command_id)
    try:
        movement = movement_service._execute_movement_core(
            db,
            tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id,
            client_command_id=movement_command_id, effective_time=effective_time,
            occupant_kind="carrier", occupant_id=carrier.id,
            destination_kind="location", destination_id=destination_seedling_table_id,
            reason=reason,
        )
    except InvalidEffectiveTimeError as exc:
        raise SeedlingEntryPhysicalChronologyError(
            "effective_time precedes this Tray's current physical occupancy -- the Tray has already "
            "physically moved since that time, so a Seedling entry cannot be backdated to before its "
            "most recent recorded Movement"
        ) from exc

    entry = SeedlingEntry(
        id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, batch_id=assignment.batch_id,
        batch_carrier_assignment_id=batch_carrier_assignment_id,
        source_germination_outcome_snapshot_id=snapshot["id"], movement_id=movement.id,
        starting_living_seedling_count=starting_count, effective_time=effective_time,
        actor_user_id=actor_user_id, client_command_id=client_command_id, request_fingerprint=fingerprint,
    )
    db.add(entry)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_seedling_entries_tenant_client_command_id":
            replay = _find_existing_entry(db, tenant_id=tenant_id, client_command_id=client_command_id)
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise SeedlingEntryCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        if constraint == "ux_seedling_entries_assignment":
            raise SeedlingEntryAlreadyExistsError(str(batch_carrier_assignment_id)) from exc
        raise

    append_audit_event(
        db,
        tenant_id=tenant_id, actor_user_id=actor_user_id, action="crop_batch.seedling_entry_recorded",
        entity_type="seedling_entry", entity_id=entry.id,
        event_data={
            "seedling_entry_id": str(entry.id), "client_command_id": str(client_command_id),
            "batch_id": str(assignment.batch_id), "batch_carrier_assignment_id": str(batch_carrier_assignment_id),
            "movement_id": str(movement.id), "source_germination_outcome_snapshot_id": str(snapshot["id"]),
            "starting_living_seedling_count": starting_count, "effective_time": effective_time.isoformat(),
            "destination_seedling_table_id": str(destination_seedling_table_id),
        },
    )
    db.commit()
    db.refresh(entry)
    return entry


# --- Command read (composes the rich response) --------------------------------------


def describe_seedling_entry(db: Session, *, entry: SeedlingEntry) -> SeedlingEntryRead:
    row = db.execute(
        text(
            "SELECT cb.code AS batch_code, carrier.id AS tray_id, carrier.code AS tray_code, "
            "ct.id AS carrier_type_id, ct.code AS carrier_type_code, ct.name AS carrier_type_name, "
            "t.id AS table_id, t.code AS table_code, t.name AS table_name, "
            "gos.normal_seedling_count, gos.abnormal_seedling_count, oe.effective_time AS source_effective_time "
            "FROM seedling_entries se "
            "JOIN crop_batches cb ON cb.id = se.batch_id "
            "JOIN batch_carrier_assignments bca ON bca.id = se.batch_carrier_assignment_id "
            "JOIN carriers carrier ON carrier.id = bca.carrier_id "
            "JOIN carrier_types ct ON ct.id = carrier.carrier_type_id "
            "JOIN movements m ON m.id = se.movement_id "
            "JOIN locations t ON t.id = m.destination_location_id "
            "JOIN germination_outcome_snapshots gos ON gos.id = se.source_germination_outcome_snapshot_id "
            "JOIN observation_events oe ON oe.id = gos.observation_event_id "
            "WHERE se.id = :eid"
        ),
        {"eid": entry.id},
    ).mappings().first()
    return SeedlingEntryRead(
        id=entry.id, client_command_id=entry.client_command_id, batch_id=entry.batch_id,
        batch_code=row["batch_code"], batch_carrier_assignment_id=entry.batch_carrier_assignment_id,
        tray=CarrierSummary(
            id=row["tray_id"], code=row["tray_code"],
            carrier_type=CarrierTypeSummary(
                id=row["carrier_type_id"], code=row["carrier_type_code"], name=row["carrier_type_name"]
            ),
        ),
        seedling_table=SeedlingTableSummary(id=row["table_id"], code=row["table_code"], name=row["table_name"]),
        movement_id=entry.movement_id,
        source_germination_outcome_snapshot_id=entry.source_germination_outcome_snapshot_id,
        source_normal_seedling_count=row["normal_seedling_count"],
        source_abnormal_seedling_count=row["abnormal_seedling_count"],
        source_effective_time=row["source_effective_time"],
        starting_living_seedling_count=entry.starting_living_seedling_count,
        effective_time=entry.effective_time, recorded_at=entry.recorded_at,
    )


# --- Reads ---------------------------------------------------------------------------


def list_available_seedling_tables(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID
) -> list[AvailableSeedlingTableRead]:
    """Section 38: same tenant/farm, Nursery-classified, `seedling_table`
    location type only. `active_tray_count` is a fresh COUNT of live
    Occupancy rows -- never inferred from configured capacity alone (mirrors
    `germination_service.list_available_chambers`)."""
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    rows = db.execute(
        text(
            "SELECT t.id, t.code, t.name, t.capacity, "
            "(SELECT count(*) FROM occupancies o WHERE o.target_location_id = t.id AND o.end_time IS NULL) "
            "AS active_tray_count, "
            "area.id AS area_id, area.code AS area_code, area.name AS area_name, "
            "gh.id AS greenhouse_id, gh.code AS greenhouse_code, gh.name AS greenhouse_name "
            "FROM locations t "
            "JOIN location_types lt ON lt.id = t.location_type_id AND lt.code = :table_code "
            "JOIN locations area ON area.id = t.parent_location_id "
            "JOIN locations gh ON gh.id = area.parent_location_id AND gh.greenhouse_classification = 'nursery' "
            "WHERE t.tenant_id = :tid AND t.farm_id = :fid AND t.status = 'active' AND t.occupiable "
            "ORDER BY t.code"
        ),
        {"tid": tenant_id, "fid": farm_id, "table_code": SEEDLING_TABLE_LOCATION_TYPE_CODE},
    ).mappings().all()
    result = []
    for r in rows:
        effective_capacity = r["capacity"] or 1
        result.append(
            AvailableSeedlingTableRead(
                id=r["id"], code=r["code"], name=r["name"], capacity=r["capacity"],
                active_tray_count=r["active_tray_count"],
                remaining_capacity=max(effective_capacity - r["active_tray_count"], 0),
                seedling_area=SeedlingAreaSummary(id=r["area_id"], code=r["area_code"], name=r["area_name"]),
                greenhouse=SeedlingGreenhouseSummary(
                    id=r["greenhouse_id"], code=r["greenhouse_code"], name=r["greenhouse_name"]
                ),
            )
        )
    return result


def list_seedling_candidate_trays(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID
) -> list[SeedlingCandidateTrayRead]:
    """Section 37: every Sown Seed Tray, with its completed Germination
    handoff (if any), its SeedlingEntry (if any), its live physical
    placement, and a derived (never persisted) placement/entry state
    (section 21/32). One query, no N+1 -- mirrors
    `germination_service.list_germination_trays`'s own shape, extended with
    the Seedling-side facts."""
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
            "occ.id AS occupancy_id, "
            "slot.id AS slot_id, slot.code AS slot_code, slot.name AS slot_name, shelf.code AS shelf_code, "
            "trolley.id AS trolley_id, trolley.code AS trolley_code, trolley.name AS trolley_name, "
            "chamber.id AS chamber_id, chamber.code AS chamber_code, chamber.name AS chamber_name, "
            "chamber_lt.code AS chamber_type_code, chamber_gh.greenhouse_classification AS chamber_gh_classification, "
            "table_loc.id AS table_id, table_loc.code AS table_code, table_loc.name AS table_name, "
            "table_lt.code AS table_type_code, "
            "handoff.snapshot_id, handoff.normal_seedling_count, handoff.abnormal_seedling_count, "
            "handoff.effective_time AS handoff_effective_time, "
            "se.id AS seedling_entry_id, se.movement_id AS seedling_entry_movement_id, "
            "se.source_germination_outcome_snapshot_id, se.starting_living_seedling_count, "
            "se.effective_time AS seedling_entry_effective_time "
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
            "LEFT JOIN locations table_loc ON table_loc.id = occ.target_location_id "
            "LEFT JOIN location_types table_lt ON table_lt.id = table_loc.location_type_id AND table_lt.code = :table_code "
            "LEFT JOIN LATERAL ( "
            "  SELECT gos.id AS snapshot_id, gos.normal_seedling_count, gos.abnormal_seedling_count, oe.effective_time "
            "  FROM germination_outcome_snapshots gos "
            "  JOIN observation_events oe ON oe.id = gos.observation_event_id "
            "  WHERE gos.batch_carrier_assignment_id = bca.id AND gos.assessment_complete = true "
            "  ORDER BY oe.effective_time DESC, oe.recorded_time DESC LIMIT 1 "
            ") handoff ON true "
            "LEFT JOIN seedling_entries se ON se.batch_carrier_assignment_id = bca.id "
            "WHERE bca.tenant_id = :tid AND bca.farm_id = :fid "
            "AND bca.released_effective_time IS NULL AND bca.opening_sowing_event_id IS NOT NULL "
            "ORDER BY cb.code, carrier.code"
        ),
        {
            "tid": tenant_id, "fid": farm_id,
            "seed_tray_code": SEED_TRAY_CARRIER_TYPE_CODE, "chamber_code": GERMINATION_CHAMBER_LOCATION_TYPE_CODE,
            "table_code": SEEDLING_TABLE_LOCATION_TYPE_CODE,
        },
    ).mappings().all()

    results = []
    for r in rows:
        in_germination = (
            r["occupancy_id"] is not None and r["trolley_id"] is not None and r["chamber_id"] is not None
            and r["chamber_type_code"] is not None and r["chamber_gh_classification"] == "nursery"
        )
        on_seedling_table = r["occupancy_id"] is not None and r["table_type_code"] is not None

        if in_germination:
            placement_kind = "in_germination"
            placement = ResolvedPhysicalPlacement(
                kind="in_germination",
                germination=GerminationResolvedPlacement(
                    trolley=TrolleySummary(id=r["trolley_id"], code=r["trolley_code"], name=r["trolley_name"]),
                    chamber=GerminationChamberSummary(id=r["chamber_id"], code=r["chamber_code"], name=r["chamber_name"]),
                    slot=SlotSummary(id=r["slot_id"], code=r["slot_code"], name=r["slot_name"], shelf_code=r["shelf_code"]),
                ),
                seedling_table=None,
            )
        elif on_seedling_table:
            placement_kind = "on_seedling_table"
            placement = ResolvedPhysicalPlacement(
                kind="on_seedling_table", germination=None,
                seedling_table=SeedlingTableSummary(id=r["table_id"], code=r["table_code"], name=r["table_name"]),
            )
        elif r["occupancy_id"] is None:
            placement_kind = "unplaced"
            placement = ResolvedPhysicalPlacement(kind="unplaced", germination=None, seedling_table=None)
        else:
            placement_kind = "elsewhere"
            placement = ResolvedPhysicalPlacement(kind="elsewhere", germination=None, seedling_table=None)

        has_completed_handoff = r["snapshot_id"] is not None
        has_entry = r["seedling_entry_id"] is not None

        # Section 21/32: derived, never persisted -- truthful even when
        # physical and biological facts disagree (a Tray may occupy a
        # Seedling Table with no SeedlingEntry, or vice versa after some
        # future physical move).
        if not has_completed_handoff:
            state = "no_completed_handoff"
        elif on_seedling_table and has_entry:
            state = "in_seedling"
        elif on_seedling_table and not has_entry:
            state = "in_seedling_unanchored"
        elif not has_entry:
            state = "ready_for_seedling"
        else:
            state = "elsewhere"

        germination_handoff = (
            GerminationHandoffSummary(
                normal_seedling_count=r["normal_seedling_count"], abnormal_seedling_count=r["abnormal_seedling_count"],
                living_seedling_count=r["normal_seedling_count"] + r["abnormal_seedling_count"],
                effective_time=r["handoff_effective_time"],
            )
            if has_completed_handoff
            else None
        )
        seedling_entry = (
            SeedlingEntrySummary(
                id=r["seedling_entry_id"], movement_id=r["seedling_entry_movement_id"],
                source_germination_outcome_snapshot_id=r["source_germination_outcome_snapshot_id"],
                starting_living_seedling_count=r["starting_living_seedling_count"],
                effective_time=r["seedling_entry_effective_time"],
            )
            if has_entry
            else None
        )

        results.append(
            SeedlingCandidateTrayRead(
                batch_id=r["batch_id"], batch_code=r["batch_code"],
                seed_lot=SeedLotSummary(
                    id=r["seed_lot_id"], code=r["seed_lot_code"], supplier_lot_reference=r["supplier_lot_reference"],
                    crop=CropSummary(id=r["crop_id"], code=r["crop_code"], common_name=r["common_name"]),
                    variety=VarietySummary(id=r["variety_id"], code=r["variety_code"], name=r["variety_name"]),
                ),
                tray=CarrierSummary(
                    id=r["tray_id"], code=r["tray_code"],
                    carrier_type=CarrierTypeSummary(
                        id=r["carrier_type_id"], code=r["carrier_type_code"], name=r["carrier_type_name"]
                    ),
                ),
                batch_carrier_assignment_id=r["assignment_id"], seeds_sown=r["seed_count"],
                germination_handoff=germination_handoff, seedling_entry=seedling_entry,
                current_placement=placement, state=state,
            )
        )
    return results
