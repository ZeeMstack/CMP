from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, field_validator


def _normalize_code(v: str) -> str:
    v = v.strip().upper()
    if not v:
        raise ValueError("code must not be blank")
    return v


def _normalize_name(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("name must not be blank")
    return v


def _positive_or_none(v: int | None) -> int | None:
    if v is not None and v <= 0:
        raise ValueError("must be a positive integer")
    return v


class CarrierSpecificationCreate(BaseModel):
    carrier_type_code: str
    code: str
    name: str
    length_mm: int | None = None
    width_mm: int | None = None
    height_mm: int | None = None
    biological_position_count: int | None = None

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        return _normalize_code(v)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return _normalize_name(v)

    @field_validator("length_mm", "width_mm", "height_mm", "biological_position_count")
    @classmethod
    def validate_positive(cls, v: int | None) -> int | None:
        return _positive_or_none(v)


class CarrierSpecificationUpdate(BaseModel):
    """Full-body update, not a partial PATCH -- the server diffs every
    field against the current row and enforces the structural-freeze rule
    (section 14) field-by-field. `name` always applies; a structural field
    (`carrier_type_code`, `code`, dimensions, `biological_position_count`)
    that actually differs from the current value is rejected once any
    Carrier already references this specification."""

    carrier_type_code: str
    code: str
    name: str
    length_mm: int | None = None
    width_mm: int | None = None
    height_mm: int | None = None
    biological_position_count: int | None = None

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        return _normalize_code(v)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return _normalize_name(v)

    @field_validator("length_mm", "width_mm", "height_mm", "biological_position_count")
    @classmethod
    def validate_positive(cls, v: int | None) -> int | None:
        return _positive_or_none(v)


class CarrierSpecificationSummary(BaseModel):
    """Small, nested summary for embedding inside `CarrierRead` -- avoids
    flattening every dimension field onto every Carrier list result while
    still avoiding N+1 (resolved via one join in the same list/get query)."""

    id: uuid.UUID
    code: str
    name: str
    biological_position_count: int | None


class CarrierSpecificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    carrier_type_id: uuid.UUID
    carrier_type_code: str
    biological_position_label: str | None
    code: str
    name: str
    length_mm: int | None
    width_mm: int | None
    height_mm: int | None
    biological_position_count: int | None
    status: str
    is_structurally_locked: bool
