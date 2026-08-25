"""HARVEST-OPS-001 / LEAFY-OPS-001: the ONE shared authoritative living-
population calculation for a Leafy Production population lineage --
reused, unmodified in formula, by both Production Biological Disposition
(Plant Loss) and Leafy Harvest. Never a second, independently-derived
population authority (CLAUDE.md rule 8: never hide differences).

Authoritative living population is always:

    root BCA's own TransplantDestinationLine.assigned_plant_count (opening)
    + SUM(ProductionDispositionEvent.quantity_delta WHERE population_root = root)
    + SUM(HarvestPopulationEvent.quantity_delta WHERE population_root = root)

`production_disposition_service.py` re-exports every function below under
its own established names (unchanged call signatures -- every existing
caller/test keeps working byte-for-byte); `harvest_service.py` imports this
module directly. LEAFY-OPS-001's own behavior is unchanged when no Harvest
event exists for a lineage (the Harvest SUM is simply zero)."""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.harvest_population_event import HarvestPopulationEvent
from app.models.production_disposition_event import ProductionDispositionEvent
from app.models.transplant_destination_line import TransplantDestinationLine
from app.services.errors import NoPopulationRootError, ProductionDispositionBalanceError


def get_root_opening_population(db: Session, *, root_batch_carrier_assignment_id: uuid.UUID) -> int:
    """The ONLY opening-population authority -- the lineage root's own
    `TransplantDestinationLine.assigned_plant_count`. Never a second,
    independently-derived starting quantity."""
    value = db.execute(
        select(TransplantDestinationLine.assigned_plant_count).where(
            TransplantDestinationLine.destination_batch_carrier_assignment_id == root_batch_carrier_assignment_id
        )
    ).scalar_one_or_none()
    if value is None:
        raise NoPopulationRootError(str(root_batch_carrier_assignment_id))
    return value


def get_current_living_population(
    db: Session, *, root_batch_carrier_assignment_id: uuid.UUID, as_of: datetime | None = None
) -> int:
    """Authoritative current living population for an entire population
    lineage -- one flat, non-recursive SUM across BOTH
    `ProductionDispositionEvent` and `HarvestPopulationEvent`, keyed by the
    stable root id. `as_of=None` means "all events ever recorded"."""
    opening = get_root_opening_population(db, root_batch_carrier_assignment_id=root_batch_carrier_assignment_id)

    disposition_query = select(func.coalesce(func.sum(ProductionDispositionEvent.quantity_delta), 0)).where(
        ProductionDispositionEvent.population_root_batch_carrier_assignment_id == root_batch_carrier_assignment_id
    )
    harvest_query = select(func.coalesce(func.sum(HarvestPopulationEvent.quantity_delta), 0)).where(
        HarvestPopulationEvent.population_root_batch_carrier_assignment_id == root_batch_carrier_assignment_id
    )
    if as_of is not None:
        disposition_query = disposition_query.where(ProductionDispositionEvent.effective_time <= as_of)
        harvest_query = harvest_query.where(HarvestPopulationEvent.effective_time <= as_of)

    disposition_sum = db.execute(disposition_query).scalar_one()
    harvest_sum = db.execute(harvest_query).scalar_one()
    return opening + disposition_sum + harvest_sum


def resolve_active_assignment_id_for_root(
    db: Session, *, root_batch_carrier_assignment_id: uuid.UUID
) -> uuid.UUID | None:
    """The currently-active (unreleased) BCA generation for this population
    lineage, or `None` if the lineage is fully exhausted and not (yet)
    restored. At most one such row can exist by construction (a lineage is
    a strict linear chain: a restoration only ever opens a NEW generation
    once its predecessor is released) -- true regardless of whether the
    exhausting/restoring event was a Production Disposition or a Harvest."""
    return db.execute(
        select(BatchCarrierAssignment.id).where(
            BatchCarrierAssignment.population_root_batch_carrier_assignment_id == root_batch_carrier_assignment_id,
            BatchCarrierAssignment.released_effective_time.is_(None),
        )
    ).scalar_one_or_none()


def resolve_lineage_tip_assignment_id(
    db: Session, *, root_batch_carrier_assignment_id: uuid.UUID
) -> uuid.UUID:
    """The most recent generation in this population lineage, active or
    released -- the one row nothing else's `restored_from_batch_carrier_
    assignment_id` names as its own predecessor."""
    successor = aliased(BatchCarrierAssignment)
    return db.execute(
        select(BatchCarrierAssignment.id).where(
            BatchCarrierAssignment.population_root_batch_carrier_assignment_id == root_batch_carrier_assignment_id,
            ~select(successor.id)
            .where(successor.restored_from_batch_carrier_assignment_id == BatchCarrierAssignment.id)
            .exists(),
        )
    ).scalar_one()


_CHRONOLOGICAL_BALANCE_MARKER = "CMP-DOMAIN-PRODUCTION-001 chronological balance violated"


def validate_chronological_balance(
    db: Session, *, root_batch_carrier_assignment_id: uuid.UUID, opening: int,
    new_effective_time: datetime, new_delta: int,
    exclude_production_disposition_event_id: uuid.UUID | None = None,
    exclude_harvest_population_event_id: uuid.UUID | None = None,
) -> None:
    """Service-side pre-check (defense-in-depth against the DB's own
    CHECK-violation trigger backstop) -- walks BOTH `ProductionDispositionEvent`
    and `HarvestPopulationEvent` rows for one root together, grouped by
    `effective_time` first (same-timestamp deltas summed before the running
    check, so the result is independent of any incidental within-timestamp
    or cross-table row ordering), then walked ascending. Each caller
    excludes only its own table's target row (a Plant Loss correction never
    excludes a Harvest row and vice versa -- a REVERSAL/correction never
    crosses authorities)."""
    disposition_rows = db.execute(
        select(ProductionDispositionEvent.effective_time, ProductionDispositionEvent.quantity_delta).where(
            ProductionDispositionEvent.population_root_batch_carrier_assignment_id
            == root_batch_carrier_assignment_id,
            ProductionDispositionEvent.id != exclude_production_disposition_event_id
            if exclude_production_disposition_event_id is not None
            else True,
        )
    ).all()
    harvest_rows = db.execute(
        select(HarvestPopulationEvent.effective_time, HarvestPopulationEvent.quantity_delta).where(
            HarvestPopulationEvent.population_root_batch_carrier_assignment_id == root_batch_carrier_assignment_id,
            HarvestPopulationEvent.id != exclude_harvest_population_event_id
            if exclude_harvest_population_event_id is not None
            else True,
        )
    ).all()

    grouped: dict[datetime, int] = {}
    for et, delta in (*disposition_rows, *harvest_rows):
        grouped[et] = grouped.get(et, 0) + delta
    grouped[new_effective_time] = grouped.get(new_effective_time, 0) + new_delta

    running = opening
    for et in sorted(grouped.keys()):
        running += grouped[et]
        if running < 0:
            raise ProductionDispositionBalanceError(
                f"recording this event would drive the chronological authoritative living-population balance "
                f"below zero as of {et.isoformat()}"
            )
        if running > opening:
            raise ProductionDispositionBalanceError(
                f"recording this event would drive the chronological authoritative living-population balance "
                f"above the population root's own opening quantity as of {et.isoformat()}"
            )


def is_balance_violation_error(exc) -> bool:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    message = getattr(diag, "message_primary", None) or str(orig or exc)
    return _CHRONOLOGICAL_BALANCE_MARKER in message
