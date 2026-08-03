from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator, model_validator


class OccupantRef(BaseModel):
    kind: Literal["asset", "carrier"]
    id: uuid.UUID


class TargetRef(BaseModel):
    kind: Literal["location", "asset_position"]
    id: uuid.UUID


class MovementCreate(BaseModel):
    client_command_id: uuid.UUID
    effective_time: datetime
    occupant: OccupantRef
    destination: TargetRef | None = None
    reason: str | None = None

    @field_validator("effective_time")
    @classmethod
    def require_timezone(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("effective_time must be timezone-aware")
        return v

    @model_validator(mode="after")
    def normalize_reason(self) -> "MovementCreate":
        if self.reason is not None:
            trimmed = self.reason.strip()
            self.reason = trimmed or None
        return self


class MovementRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    occupant: OccupantRef
    source: TargetRef | None
    destination: TargetRef | None
    command_type: str
    client_command_id: uuid.UUID
    effective_time: datetime
    recorded_time: datetime
    actor_user_id: uuid.UUID | None
    reason: str | None

    @classmethod
    def from_model(cls, movement) -> "MovementRead":
        occupant = (
            OccupantRef(kind="asset", id=movement.occupant_asset_id)
            if movement.occupant_asset_id is not None
            else OccupantRef(kind="carrier", id=movement.occupant_carrier_id)
        )
        source = None
        if movement.source_location_id is not None:
            source = TargetRef(kind="location", id=movement.source_location_id)
        elif movement.source_asset_position_id is not None:
            source = TargetRef(kind="asset_position", id=movement.source_asset_position_id)
        destination = None
        if movement.destination_location_id is not None:
            destination = TargetRef(kind="location", id=movement.destination_location_id)
        elif movement.destination_asset_position_id is not None:
            destination = TargetRef(kind="asset_position", id=movement.destination_asset_position_id)
        return cls(
            id=movement.id,
            tenant_id=movement.tenant_id,
            farm_id=movement.farm_id,
            occupant=occupant,
            source=source,
            destination=destination,
            command_type=movement.command_type,
            client_command_id=movement.client_command_id,
            effective_time=movement.effective_time,
            recorded_time=movement.recorded_time,
            actor_user_id=movement.actor_user_id,
            reason=movement.reason,
        )
