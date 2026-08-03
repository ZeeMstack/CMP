from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

MAX_BULK_CARRIERS = 500


def _normalize_code(v: str) -> str:
    v = v.strip().upper()
    if not v:
        raise ValueError("code must not be blank")
    return v


class CarrierCreate(BaseModel):
    carrier_type_code: str
    code: str
    issued_date: date | None = None

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        return _normalize_code(v)


class CarrierBulkCreate(BaseModel):
    carrier_type_code: str
    code_prefix: str
    start: int
    end: int
    pad_width: int

    @field_validator("code_prefix")
    @classmethod
    def validate_prefix(cls, v: str) -> str:
        v = v.strip().upper()
        if not v:
            raise ValueError("code_prefix must not be blank")
        return v

    @model_validator(mode="after")
    def validate_range(self) -> "CarrierBulkCreate":
        if self.start < 1:
            raise ValueError("start must be a positive integer")
        if self.end < self.start:
            raise ValueError("end must be greater than or equal to start")
        if self.pad_width < 1:
            raise ValueError("pad_width must be a positive integer")
        count = self.end - self.start + 1
        if count > MAX_BULK_CARRIERS:
            raise ValueError(f"cannot generate more than {MAX_BULK_CARRIERS} carriers per command")
        return self


class CarrierRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    carrier_type_id: uuid.UUID
    code: str
    status: str
    issued_date: date | None
    retired_date: date | None
