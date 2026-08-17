from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.schemas.carrier_specification import CarrierSpecificationSummary

MAX_BULK_CARRIERS = 500


def _normalize_code(v: str) -> str:
    v = v.strip().upper()
    if not v:
        raise ValueError("code must not be blank")
    return v


class CarrierCreate(BaseModel):
    # CARRIER-CONFIG-001: either may be supplied; at least one is required
    # (enforced below). Supplying `specification_id` is the modern,
    # preferred path -- `carrier_type_code` is then derived server-side,
    # never asked for redundantly. Legacy `carrier_type_code`-only requests
    # remain valid for any CarrierType that does not require a
    # specification. If both are supplied, they must resolve to the same
    # CarrierType (service-layer check) -- never two independently
    # mutable truths about what type this Carrier is.
    carrier_type_code: str | None = None
    specification_id: uuid.UUID | None = None
    code: str
    issued_date: date | None = None

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        return _normalize_code(v)

    @model_validator(mode="after")
    def validate_type_or_specification(self) -> "CarrierCreate":
        if self.carrier_type_code is None and self.specification_id is None:
            raise ValueError("either carrier_type_code or specification_id must be provided")
        return self


class CarrierBulkCreate(BaseModel):
    carrier_type_code: str | None = None
    specification_id: uuid.UUID | None = None
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
        if self.carrier_type_code is None and self.specification_id is None:
            raise ValueError("either carrier_type_code or specification_id must be provided")
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
    specification_id: uuid.UUID | None
    specification: CarrierSpecificationSummary | None = None


class CarrierTypeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    requires_specification: bool
    biological_position_label: str | None
