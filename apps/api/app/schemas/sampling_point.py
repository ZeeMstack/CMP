from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, field_validator


class SamplingPointCreate(BaseModel):
    code: str
    name: str
    point_type: str
    anchor_id: uuid.UUID | None = None
    notes: str | None = None

    @field_validator("code", "name")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v


class SamplingPointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    code: str
    name: str
    point_type: str
    water_source_id: uuid.UUID | None
    reservoir_id: uuid.UUID | None
    irrigation_circuit_id: uuid.UUID | None
    water_delivery_point_id: uuid.UUID | None
    water_return_point_id: uuid.UUID | None
    status: str
    notes: str | None
