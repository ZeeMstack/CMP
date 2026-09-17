from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class ReservoirEventCreate(BaseModel):
    event_type: str
    effective_at: datetime
    quantity: Decimal | None = None
    quantity_uom_id: uuid.UUID | None = None
    inventory_item_id: uuid.UUID | None = None
    notes: str | None = None
    client_command_id: uuid.UUID


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
    effective_start: datetime
    effective_end: datetime | None = None
    delivered_volume: Decimal | None = None
    delivered_volume_uom_id: uuid.UUID | None = None
    nutrient_mix_id: uuid.UUID | None = None
    notes: str | None = None
    client_command_id: uuid.UUID


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
