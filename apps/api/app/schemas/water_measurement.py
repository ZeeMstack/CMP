from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator


def _require_tz_aware(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError("must be timezone-aware")
    return v


class WaterMeasurementCreate(BaseModel):
    metric: str
    value: Decimal
    unit: str
    # PILOT-WATER-001B (HOTFIX-TIME-002 pattern): omitting effective_at
    # means "record now" -- the server assigns its own authoritative
    # current time (water_instrument_service.record_measurement), never a
    # browser-clock-derived timestamp. An explicit value is still required
    # to be timezone-aware and is still rejected if genuinely in the future.
    effective_at: datetime | None = None
    water_instrument_id: uuid.UUID | None = None
    notes: str | None = None
    client_command_id: uuid.UUID

    @field_validator("effective_at")
    @classmethod
    def validate_effective_at(cls, v: datetime | None) -> datetime | None:
        return v if v is None else _require_tz_aware(v)


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
