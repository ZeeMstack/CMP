from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


def _not_blank(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("must not be blank")
    return v


class WaterSourceCreate(BaseModel):
    code: str
    name: str
    source_type: str
    notes: str | None = None

    @field_validator("code", "name")
    @classmethod
    def _validate_not_blank(cls, v: str) -> str:
        return _not_blank(v)


class WaterSourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    code: str
    name: str
    source_type: str
    status: str
    notes: str | None


class ReservoirCreate(BaseModel):
    code: str
    name: str
    reservoir_type: str
    nominal_capacity: float | None = None
    nominal_capacity_uom_id: uuid.UUID | None = None
    linked_asset_id: uuid.UUID | None = None
    location_id: uuid.UUID | None = None
    notes: str | None = None

    @field_validator("code", "name")
    @classmethod
    def _validate_not_blank(cls, v: str) -> str:
        return _not_blank(v)


class ReservoirRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    code: str
    name: str
    reservoir_type: str
    nominal_capacity: float | None
    nominal_capacity_uom_id: uuid.UUID | None
    linked_asset_id: uuid.UUID | None
    location_id: uuid.UUID | None
    status: str
    notes: str | None


class IrrigationCircuitCreate(BaseModel):
    code: str
    name: str
    system_type: str | None = None
    notes: str | None = None

    @field_validator("code", "name")
    @classmethod
    def _validate_not_blank(cls, v: str) -> str:
        return _not_blank(v)


class IrrigationCircuitRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    code: str
    name: str
    system_type: str | None
    status: str
    notes: str | None


class WaterDeliveryPointCreate(BaseModel):
    code: str
    name: str
    location_id: uuid.UUID
    notes: str | None = None

    @field_validator("code", "name")
    @classmethod
    def _validate_not_blank(cls, v: str) -> str:
        return _not_blank(v)


class WaterDeliveryPointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    code: str
    name: str
    location_id: uuid.UUID
    status: str
    notes: str | None


class WaterReturnPointCreate(BaseModel):
    code: str
    name: str
    location_id: uuid.UUID | None = None
    notes: str | None = None

    @field_validator("code", "name")
    @classmethod
    def _validate_not_blank(cls, v: str) -> str:
        return _not_blank(v)


class WaterReturnPointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    code: str
    name: str
    location_id: uuid.UUID | None
    status: str
    notes: str | None


class WaterSourceReservoirLinkOpen(BaseModel):
    water_source_id: uuid.UUID
    reservoir_id: uuid.UUID
    effective_from: datetime
    reason: str | None = None


class ReservoirCircuitLinkOpen(BaseModel):
    reservoir_id: uuid.UUID
    irrigation_circuit_id: uuid.UUID
    effective_from: datetime
    reason: str | None = None


class CircuitDeliveryPointLinkOpen(BaseModel):
    irrigation_circuit_id: uuid.UUID
    water_delivery_point_id: uuid.UUID
    effective_from: datetime
    reason: str | None = None


class ReturnPointReservoirLinkOpen(BaseModel):
    water_return_point_id: uuid.UUID
    return_reservoir_id: uuid.UUID
    effective_from: datetime
    reason: str | None = None


class TopologyLinkClose(BaseModel):
    effective_to: datetime


class TopologyLinkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    effective_from: datetime
    effective_to: datetime | None
    reason: str | None
    water_source_id: uuid.UUID | None = None
    reservoir_id: uuid.UUID | None = None
    irrigation_circuit_id: uuid.UUID | None = None
    water_delivery_point_id: uuid.UUID | None = None
    water_return_point_id: uuid.UUID | None = None
    return_reservoir_id: uuid.UUID | None = None
