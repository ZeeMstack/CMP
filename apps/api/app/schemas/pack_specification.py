from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator

from app.schemas.harvest import MAX_WHOLE_UNIT_COUNT, _parse_strict_decimal, canonical_decimal_str


def _normalize_code(v: str) -> str:
    v = v.strip().upper()
    if not v:
        raise ValueError("code must not be blank")
    return v


def _require_non_blank(v: str, *, field_name: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError(f"{field_name} must not be blank")
    return v


def _blank_to_none(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


def _require_tz_aware(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError("effective_time must be timezone-aware")
    return v


# --- Commands ----------------------------------------------------------------------


class PackSpecificationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    code: str
    name: str
    crop_id: uuid.UUID
    variety_id: uuid.UUID | None = None
    customer_reference: str | None = None

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        return _normalize_code(v)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return _require_non_blank(v, field_name="name")

    @field_validator("customer_reference")
    @classmethod
    def validate_customer_reference(cls, v: str | None) -> str | None:
        return _blank_to_none(v)


class PackSpecificationVersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    grade_definition_version_id: uuid.UUID | None = None
    packaging_unit_id: uuid.UUID
    nominal_net_weight_kg: Decimal | None = None
    whole_units_per_pack: int | None = Field(default=None, gt=0, le=MAX_WHOLE_UNIT_COUNT)
    spec_notes: str | None = None

    @field_validator("nominal_net_weight_kg", mode="before")
    @classmethod
    def validate_weight(cls, v: object) -> Decimal | None:
        if v is None:
            return None
        return _parse_strict_decimal(v)

    @field_validator("spec_notes")
    @classmethod
    def validate_spec_notes(cls, v: str | None) -> str | None:
        return _blank_to_none(v)

    @model_validator(mode="after")
    def validate_measure_present(self) -> "PackSpecificationVersionCreate":
        if self.nominal_net_weight_kg is None and self.whole_units_per_pack is None:
            raise ValueError("at least one of nominal_net_weight_kg or whole_units_per_pack is required")
        return self


class PackSpecificationVersionActivate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    effective_time: datetime

    @field_validator("effective_time")
    @classmethod
    def validate_effective_time(cls, v: datetime) -> datetime:
        return _require_tz_aware(v)


class PackSpecificationVersionRetire(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    effective_time: datetime

    @field_validator("effective_time")
    @classmethod
    def validate_effective_time(cls, v: datetime) -> datetime:
        return _require_tz_aware(v)


# --- Reads -----------------------------------------------------------------------


class PackSpecificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    crop_id: uuid.UUID
    variety_id: uuid.UUID | None
    code: str
    name: str
    customer_reference: str | None
    created_at: datetime


class PackSpecificationVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    pack_specification_id: uuid.UUID
    version_number: int
    status: str
    grade_definition_version_id: uuid.UUID | None
    packaging_unit_id: uuid.UUID
    nominal_net_weight_kg: Decimal | None
    whole_units_per_pack: int | None
    spec_notes: str | None
    effective_from: datetime | None
    effective_until: datetime | None
    created_by: uuid.UUID | None
    created_at: datetime

    @field_serializer("nominal_net_weight_kg")
    def serialize_weight(self, v: Decimal | None) -> str | None:
        return canonical_decimal_str(v) if v is not None else None


__all__ = [
    "PackSpecificationCreate",
    "PackSpecificationVersionCreate",
    "PackSpecificationVersionActivate",
    "PackSpecificationVersionRetire",
    "PackSpecificationRead",
    "PackSpecificationVersionRead",
]
