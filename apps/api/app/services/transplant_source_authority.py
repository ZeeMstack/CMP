"""NURSERY-OPS-005A: the one shared resolver over every Transplant source's
biological population authority.

Two authority kinds exist, each keyed to a genuinely different identity:

- `seedling_entry` -- a Seed Tray's SeedlingEntry/SeedlingSourceCheckpoint
  authority (NURSERY-OPS-004A), UNCHANGED. The identity is the
  `SeedlingEntry` (invariant across restoration generations); resolving it
  for a given `BatchCarrierAssignment.id` requires the existing backward
  restoration-lineage walk (`seedling_source_lineage`), since a restored
  descendant assignment does not itself own a `SeedlingEntry` row.

- `batch_carrier_population` -- a transplant-created placement's own
  `BatchCarrierAssignment`/`BatchCarrierPopulationCheckpoint` authority
  (NURSERY-OPS-005A), new. The identity IS the assignment itself -- no
  separate "entry" object exists, so no lineage walk is needed: each
  restoration generation (A, B, C, ...) gets its own checkpoint chain,
  scoped by its own `batch_carrier_assignment_id`.

Every service that validates/consumes a Transplant source (`transplant_
service`, `transplant_correction_service`) goes through this module's
functions rather than branching on carrier type or duplicating checkpoint
arithmetic itself -- `record_transplant`/`correct_transplant` contain
exactly one call site each for resolve/available/append, never two
independent implementations.

`SeedlingEntry`/`SeedlingSourceCheckpoint` are never rewritten, migrated,
or generalized by this module -- see `docs/domain/TRANSPLANTATION_MODEL.md`.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.batch_carrier_population_checkpoint import BatchCarrierPopulationCheckpoint
from app.models.carrier import Carrier
from app.models.carrier_type import CarrierType
from app.models.seedling_entry import SeedlingEntry
from app.models.seedling_source_checkpoint import SeedlingSourceCheckpoint
from app.models.transplant_destination_line import TransplantDestinationLine
from app.models.transplant_event import TransplantEvent
from app.services import seedling_disposition_service, seedling_source_lineage

SEED_TRAY_CARRIER_TYPE_CODE = "seed_tray"
NURSERY_CULTIVATION_PLATE_CARRIER_TYPE_CODE = "nursery_cultivation_plate"

# NURSERY-OPS-005A section 6/19: the smallest safe gating mechanism -- a
# fixed, explicit allowlist of eligible Transplant source Carrier types,
# never a generic rules engine. production_cultivation_plate deliberately
# is NOT here: having a population authority (every supported transplant-
# created destination gets one, see `derive_or_get_opening_authority`)
# does not by itself imply Transplant-source eligibility.
ELIGIBLE_SOURCE_CARRIER_TYPE_CODES = frozenset(
    {SEED_TRAY_CARRIER_TYPE_CODE, NURSERY_CULTIVATION_PLATE_CARRIER_TYPE_CODE}
)


@dataclass(frozen=True)
class SourceAuthority:
    """A small, service-layer-only discriminated value -- never a database
    authority-supertype table. `kind` selects which underlying mechanism
    every other function in this module dispatches to."""

    kind: str  # "seedling_entry" | "batch_carrier_population"
    seedling_entry: SeedlingEntry | None = None


def resolve_source_authority(
    db: Session, *, assignment_id: uuid.UUID, carrier_type_code: str
) -> SourceAuthority | None:
    """Never raises. Returns `None` when `carrier_type_code` is not an
    eligible source type at all, OR when it IS eligible (seed_tray) but no
    authority can currently be resolved for this specific assignment (no
    SeedlingEntry anywhere in its restoration lineage). Callers are
    responsible for their own typed error on `None` -- `transplant_service`
    and `transplant_correction_service` each already have their own
    distinct, existing conventions for this (see their own call sites),
    which this module deliberately does not collapse into one shared
    error class."""
    if carrier_type_code == SEED_TRAY_CARRIER_TYPE_CODE:
        entry = seedling_source_lineage.resolve_seedling_entry_for_assignment(db, assignment_id=assignment_id)
        if entry is None:
            return None
        return SourceAuthority(kind="seedling_entry", seedling_entry=entry)
    if carrier_type_code == NURSERY_CULTIVATION_PLATE_CARRIER_TYPE_CODE:
        return SourceAuthority(kind="batch_carrier_population")
    return None


def _get_batch_carrier_population_anchor(
    db: Session, *, assignment_id: uuid.UUID
) -> tuple[int, datetime]:
    """`(anchor_value, anchor_time)` for a batch_carrier_population
    authority -- the structural chain tip if any checkpoint exists for
    this assignment (mirrors `seedling_disposition_service.
    _latest_checkpoint_anchor`'s identical NOT EXISTS shape, scoped by
    `batch_carrier_assignment_id` rather than `seedling_entry_id`, since
    each restoration generation owns its own checkpoint chain -- no
    lineage walk needed), otherwise derived structurally from this exact
    assignment's own `TransplantDestinationLine.assigned_plant_count` and
    its originating `TransplantEvent.effective_time` (mirrors `SeedlingEntry.
    starting_living_seedling_count`/`effective_time`'s identical role).
    A restored assignment always has at least one checkpoint by the time
    anything calls this (written immediately by the restoring REVERSAL,
    see `append_source_consumption_checkpoint`), so the destination-line
    fallback path only applies to a never-yet-consumed, never-restored
    assignment."""
    successor = aliased(BatchCarrierPopulationCheckpoint)
    row = db.execute(
        select(BatchCarrierPopulationCheckpoint.remainder_after, BatchCarrierPopulationCheckpoint.effective_time)
        .where(
            BatchCarrierPopulationCheckpoint.batch_carrier_assignment_id == assignment_id,
            ~select(successor.id)
            .where(successor.previous_checkpoint_id == BatchCarrierPopulationCheckpoint.id)
            .exists(),
        )
    ).first()
    if row is not None:
        return row[0], row[1]

    destination_row = db.execute(
        select(TransplantDestinationLine.assigned_plant_count, TransplantEvent.effective_time)
        .join(TransplantEvent, TransplantEvent.id == TransplantDestinationLine.transplant_event_id)
        .where(TransplantDestinationLine.destination_batch_carrier_assignment_id == assignment_id)
    ).first()
    if destination_row is None:
        raise RuntimeError(
            f"batch_carrier_assignment {assignment_id} has no BatchCarrierPopulationCheckpoint and no "
            "TransplantDestinationLine of its own -- every transplant-created assignment must have exactly "
            "one of these; this indicates a genuine data-integrity violation, not a normal caller error"
        )
    return destination_row[0], destination_row[1]


def get_source_availability_anchor(
    db: Session, *, authority: SourceAuthority, assignment_id: uuid.UUID
) -> tuple[int, datetime, bool]:
    """Public: `(anchor_value, anchor_time, has_checkpoint)`, dispatched by
    `authority.kind` -- the one place `transplant_service` reads this for
    EITHER authority kind, so the temporal-floor branch it applies stays
    identical regardless of source type."""
    if authority.kind == "seedling_entry":
        assert authority.seedling_entry is not None
        return seedling_disposition_service.get_source_availability_anchor(
            db, seedling_entry=authority.seedling_entry
        )
    anchor_value, anchor_time = _get_batch_carrier_population_anchor(db, assignment_id=assignment_id)
    return anchor_value, anchor_time, True


def get_source_available(
    db: Session, *, authority: SourceAuthority, assignment_id: uuid.UUID, as_of: datetime
) -> int:
    """Public: the authoritative, server-derived source availability,
    dispatched by `authority.kind`. A `batch_carrier_population` authority
    has no disposition-style delta ledger in NURSERY-OPS-005A's scope -- its
    available count IS its anchor value; `as_of` is accepted only for
    interface symmetry with the seedling_entry path (the caller's own
    temporal-floor check via `get_source_availability_anchor` already
    guarantees `as_of` is never before the anchor)."""
    if authority.kind == "seedling_entry":
        assert authority.seedling_entry is not None
        return seedling_disposition_service.get_source_available(
            db, seedling_entry=authority.seedling_entry, as_of=as_of
        )
    anchor_value, _anchor_time = _get_batch_carrier_population_anchor(db, assignment_id=assignment_id)
    return anchor_value


def append_source_consumption_checkpoint(
    db: Session,
    *,
    authority: SourceAuthority,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    assignment_id: uuid.UUID,
    transplant_source_line_id: uuid.UUID,
    remainder_after: int,
    effective_time: datetime,
) -> None:
    """Writes exactly one checkpoint row, dispatched by `authority.kind` --
    the ONLY place either checkpoint table is ever inserted into from
    `transplant_service`/`transplant_correction_service`, eliminating what
    would otherwise be duplicated chain-tip-lookup arithmetic at each call
    site. Chain-tip resolution mirrors `SeedlingSourceCheckpoint`'s own
    NOT EXISTS shape exactly, scoped to the correct identity column for
    each authority kind."""
    if authority.kind == "seedling_entry":
        assert authority.seedling_entry is not None
        entry = authority.seedling_entry
        successor = aliased(SeedlingSourceCheckpoint)
        previous_checkpoint_id = db.execute(
            select(SeedlingSourceCheckpoint.id)
            .where(
                SeedlingSourceCheckpoint.seedling_entry_id == entry.id,
                ~select(successor.id)
                .where(successor.previous_checkpoint_id == SeedlingSourceCheckpoint.id)
                .exists(),
            )
            .limit(1)
        ).scalar_one_or_none()
        db.add(
            SeedlingSourceCheckpoint(
                id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id,
                seedling_entry_id=entry.id, source_batch_carrier_assignment_id=assignment_id,
                transplant_source_line_id=transplant_source_line_id, previous_checkpoint_id=previous_checkpoint_id,
                remainder_after=remainder_after, effective_time=effective_time,
            )
        )
        return

    successor2 = aliased(BatchCarrierPopulationCheckpoint)
    previous_checkpoint_id2 = db.execute(
        select(BatchCarrierPopulationCheckpoint.id)
        .where(
            BatchCarrierPopulationCheckpoint.batch_carrier_assignment_id == assignment_id,
            ~select(successor2.id)
            .where(successor2.previous_checkpoint_id == BatchCarrierPopulationCheckpoint.id)
            .exists(),
        )
        .limit(1)
    ).scalar_one_or_none()
    db.add(
        BatchCarrierPopulationCheckpoint(
            id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id,
            batch_carrier_assignment_id=assignment_id, transplant_source_line_id=transplant_source_line_id,
            previous_checkpoint_id=previous_checkpoint_id2, remainder_after=remainder_after,
            effective_time=effective_time,
        )
    )


def get_unresolved_batch_carrier_population_remainder(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID, as_of: datetime
) -> tuple[int, int]:
    """WORKFLOW-INTEGRITY-001 / NURSERY-OPS-005A: `(unresolved_source_count,
    total_unresolved_living_count)` across every ACTIVE (unreleased)
    nursery_cultivation_plate BatchCarrierAssignment belonging to this
    batch -- mirrors `seedling_disposition_service.
    get_unresolved_seedling_remainder`'s exact shape and simple per-entity
    reuse-of-the-existing-helper philosophy, for the sibling authority. A
    released/exhausted Nursery Plate is excluded by construction (only
    active assignments are ever considered), matching the frozen product
    decision that a historical released assignment must never block."""
    plate_type_id = db.execute(
        select(CarrierType.id).where(CarrierType.code == NURSERY_CULTIVATION_PLATE_CARRIER_TYPE_CODE)
    ).scalar_one()
    assignment_ids = list(
        db.execute(
            select(BatchCarrierAssignment.id)
            .join(Carrier, Carrier.id == BatchCarrierAssignment.carrier_id)
            .where(
                BatchCarrierAssignment.tenant_id == tenant_id, BatchCarrierAssignment.farm_id == farm_id,
                BatchCarrierAssignment.batch_id == batch_id,
                BatchCarrierAssignment.released_effective_time.is_(None),
                Carrier.carrier_type_id == plate_type_id,
            )
        ).scalars()
    )
    unresolved_source_count = 0
    total_unresolved_living_count = 0
    authority = SourceAuthority(kind="batch_carrier_population")
    for assignment_id in assignment_ids:
        available = get_source_available(db, authority=authority, assignment_id=assignment_id, as_of=as_of)
        if available > 0:
            unresolved_source_count += 1
            total_unresolved_living_count += available
    return unresolved_source_count, total_unresolved_living_count
