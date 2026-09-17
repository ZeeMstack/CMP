from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator


def _require_tz_aware(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError("must be timezone-aware")
    return v


class ReservoirEventCreate(BaseModel):
    event_type: str
    # PILOT-WATER-001B (HOTFIX-TIME-002 pattern): omitting effective_at
    # means "record now" -- see WaterMeasurementCreate's identical note.
    effective_at: datetime | None = None
    quantity: Decimal | None = None
    quantity_uom_id: uuid.UUID | None = None
    inventory_item_id: uuid.UUID | None = None
    notes: str | None = None
    client_command_id: uuid.UUID

    @field_validator("effective_at")
    @classmethod
    def validate_effective_at(cls, v: datetime | None) -> datetime | None:
        return v if v is None else _require_tz_aware(v)


class ReservoirEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    reservoir_id: uuid.UUID
    event_type: str
    effective_at: datetime
    recorded_at: datetime
    quantity: Decimal | None
    quantity_uom_id: uuid.UUID | None
    inventory_item_id: uuid.UUID | None
    notes: str | None


class WaterDeliveryEventCreate(BaseModel):
    reservoir_id: uuid.UUID
    irrigation_circuit_id: uuid.UUID
    # PILOT-WATER-001B (HOTFIX-TIME-002 pattern): omitting effective_start
    # means "starting now". effective_end=None remains its own, separate
    # fact -- an ongoing/continuous delivery, never conflated with
    # "starting now" (section 17/21).
    effective_start: datetime | None = None
    effective_end: datetime | None = None
    delivered_volume: Decimal | None = None
    delivered_volume_uom_id: uuid.UUID | None = None
    nutrient_mix_id: uuid.UUID | None = None
    notes: str | None = None
    client_command_id: uuid.UUID

    @field_validator("effective_start", "effective_end")
    @classmethod
    def validate_timestamps(cls, v: datetime | None) -> datetime | None:
        return v if v is None else _require_tz_aware(v)


class WaterDeliveryEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    reservoir_id: uuid.UUID
    irrigation_circuit_id: uuid.UUID
    effective_start: datetime
    effective_end: datetime | None
    delivered_volume: Decimal | None
    delivered_volume_uom_id: uuid.UUID | None
    nutrient_mix_id: uuid.UUID | None
    notes: str | None
