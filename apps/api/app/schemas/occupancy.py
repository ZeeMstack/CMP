from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.movement import OccupantRef, TargetRef


class OccupancyRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    occupant: OccupantRef
    target: TargetRef
    effective_time: datetime
    end_time: datetime | None
    opened_by_movement_id: uuid.UUID
    closed_by_movement_id: uuid.UUID | None
    actor_user_id: uuid.UUID | None
    created_at: datetime

    @classmethod
    def from_model(cls, occupancy) -> "OccupancyRead":
        occupant = (
            OccupantRef(kind="asset", id=occupancy.occupant_asset_id)
            if occupancy.occupant_asset_id is not None
            else OccupantRef(kind="carrier", id=occupancy.occupant_carrier_id)
        )
        target = (
            TargetRef(kind="location", id=occupancy.target_location_id)
            if occupancy.target_location_id is not None
            else TargetRef(kind="asset_position", id=occupancy.target_asset_position_id)
        )
        return cls(
            id=occupancy.id,
            tenant_id=occupancy.tenant_id,
            farm_id=occupancy.farm_id,
            occupant=occupant,
            target=target,
            effective_time=occupancy.effective_time,
            end_time=occupancy.end_time,
            opened_by_movement_id=occupancy.opened_by_movement_id,
            closed_by_movement_id=occupancy.closed_by_movement_id,
            actor_user_id=occupancy.actor_user_id,
            created_at=occupancy.created_at,
        )


class TargetOccupantRead(BaseModel):
    """Legacy singular read. `active_occupancy` is only ONE occupant for a
    capacity>1 target with several active occupancies (the earliest by
    effective_time) -- `active_occupancy_count` (DOMAIN-FARM-002.1, additive)
    makes that explicit rather than silently implying `active_occupancy` is
    the complete state. A caller must check `active_occupancy_count > 1` (or
    just always prefer `TargetOccupantsRead`/`active_occupancies` below) to
    know whether more occupants exist than are shown here."""

    target: TargetRef
    active_occupancy: OccupancyRead | None
    active_occupancy_count: int


class TargetOccupantsRead(BaseModel):
    """DOMAIN-FARM-002.1: the truthful, complete read -- every active
    occupancy for the target, not just one. For a truly exclusive
    (capacity<=1) target this is 0 or 1 entries, identical in substance to
    `TargetOccupantRead`."""

    target: TargetRef
    active_occupancies: list[OccupancyRead]


class PathEntry(BaseModel):
    id: uuid.UUID
    code: str
    name: str


class ContainingAssetRef(BaseModel):
    id: uuid.UUID
    code: str
    name: str


class ResolvedLocationRead(BaseModel):
    occupant: OccupantRef
    direct_target: TargetRef | None
    position_path: list[PathEntry] | None
    containing_asset: ContainingAssetRef | None
    fixed_location_path: list[PathEntry] | None
    path_string: str | None
    unresolved_reason: str | None
