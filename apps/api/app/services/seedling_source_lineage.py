"""TRANSPLANT-CORRECTION-001: the one shared restoration-lineage resolver.

A `BatchCarrierAssignment` opened by a Transplant REVERSAL
(`opening_transplant_reversal_event_id`) represents the SAME physical Seed
Tray / SeedlingEntry becoming biologically active again after a
full-exhaustion correction -- `restored_from_batch_carrier_assignment_id`
chains it back to the assignment it restores, which may itself be a prior
restoration (arbitrary depth: original -> restored once -> exhausted again
-> restored again -> ...). `SeedlingEntry.batch_carrier_assignment_id`
never repoints -- it always names the ORIGINAL assignment.

This module is the single place every biological source consumer resolves
"which SeedlingEntry does this assignment id belong to" -- deliberately a
small, neutral module (not folded into `seedling_disposition_service` or
`seedling_entry_service`) so `transplant_service`, `seedling_disposition_
service`, and `seedling_entry_service` can all import it without creating
a cycle between themselves.

Bounded, not merely defensive-in-name: the walk is structurally acyclic by
construction (every opener/lineage column on `batch_carrier_assignments`
is immutable after INSERT -- see `enforce_batch_carrier_assignment_
closure_only_v2`'s own protected-column list -- and a restoration's `id`
must already exist at FK-check time, so a chain can only ever grow
forward). The hop cap exists purely so a genuinely corrupted database
fails loudly instead of looping forever; it is never expected to fire in
correct operation."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.seedling_entry import SeedlingEntry

MAX_RESTORATION_HOPS = 50


class RestorationLineageDepthExceededError(RuntimeError):
    pass


def resolve_seedling_entry_for_assignment(
    db: Session, *, assignment_id: uuid.UUID
) -> SeedlingEntry | None:
    """Backward walk: the SeedlingEntry that anchors `assignment_id`'s
    biological source authority -- direct ownership if `assignment_id` IS
    the SeedlingEntry's own (original) assignment, otherwise walking
    `restored_from_batch_carrier_assignment_id` backward until an
    assignment with a directly-owned SeedlingEntry is found. `None` if the
    lineage terminates (no restoration link) without ever finding one --
    an assignment with no SeedlingEntry at all, exactly as before this
    ticket for a never-restored assignment."""
    current_id: uuid.UUID | None = assignment_id
    hops = 0
    while current_id is not None:
        entry = db.execute(
            select(SeedlingEntry).where(SeedlingEntry.batch_carrier_assignment_id == current_id)
        ).scalar_one_or_none()
        if entry is not None:
            return entry
        hops += 1
        if hops > MAX_RESTORATION_HOPS:
            raise RestorationLineageDepthExceededError(
                f"restoration lineage exceeds maximum depth for assignment {assignment_id}"
            )
        current_id = db.execute(
            select(BatchCarrierAssignment.restored_from_batch_carrier_assignment_id).where(
                BatchCarrierAssignment.id == current_id
            )
        ).scalar_one_or_none()
    return None


def resolve_active_assignment_id_in_lineage(
    db: Session, *, original_assignment_id: uuid.UUID
) -> uuid.UUID | None:
    """Forward walk: the id of the CURRENTLY ACTIVE (unreleased) assignment
    in the restoration lineage rooted at `original_assignment_id` -- the
    original itself if never exhausted, or the latest restored descendant
    otherwise. `None` only if every assignment in the lineage is released
    (the source is genuinely, currently unavailable -- no active
    restoration exists yet)."""
    current_id: uuid.UUID | None = original_assignment_id
    hops = 0
    while current_id is not None:
        released = db.execute(
            select(BatchCarrierAssignment.released_effective_time).where(
                BatchCarrierAssignment.id == current_id
            )
        ).scalar_one()
        if released is None:
            return current_id
        hops += 1
        if hops > MAX_RESTORATION_HOPS:
            raise RestorationLineageDepthExceededError(
                f"restoration lineage exceeds maximum depth for assignment {original_assignment_id}"
            )
        current_id = db.execute(
            select(BatchCarrierAssignment.id).where(
                BatchCarrierAssignment.restored_from_batch_carrier_assignment_id == current_id
            )
        ).scalar_one_or_none()
    return None
