from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


def _require_tz_aware(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError("must be timezone-aware")
    return v


class WaterInstrumentCreate(BaseModel):
    asset_id: uuid.UUID
    supports_ph: bool = False
    supports_ec: bool = False
    supports_solution_temperature: bool = False
    supports_dissolved_oxygen: bool = False


class WaterInstrumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    asset_id: uuid.UUID
    supports_ph: bool
    supports_ec: bool
    supports_solution_temperature: bool
    supports_dissolved_oxygen: bool
    status: str


class CalibrationEventCreate(BaseModel):
    metric: str
    # PILOT-WATER-001B (HOTFIX-TIME-002 pattern): omitting effective_at
    # means "record now" -- see WaterMeasurementCreate's identical note.
    effective_at: datetime | None = None
    result: str
    standard_reference: str | None = None
    notes: str | None = None
    client_command_id: uuid.UUID

    @field_validator("effective_at")
    @classmethod
    def validate_effective_at(cls, v: datetime | None) -> datetime | None:
        return v if v is None else _require_tz_aware(v)


class CalibrationEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    water_instrument_id: uuid.UUID
    metric: str
    effective_at: datetime
    recorded_at: datetime
    result: str
    standard_reference: str | None
    notes: str | None
