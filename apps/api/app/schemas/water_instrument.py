from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


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
    effective_at: datetime
    result: str
    standard_reference: str | None = None
    notes: str | None = None
    client_command_id: uuid.UUID


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
