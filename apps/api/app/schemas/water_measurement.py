from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class WaterMeasurementCreate(BaseModel):
    metric: str
    value: Decimal
    unit: str
    effective_at: datetime
    water_instrument_id: uuid.UUID | None = None
    notes: str | None = None
    client_command_id: uuid.UUID


class WaterMeasurementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    sampling_point_id: uuid.UUID
    metric: str
    value: Decimal
    unit: str
    effective_at: datetime
    recorded_at: datetime
    water_instrument_id: uuid.UUID | None
    notes: str | None
