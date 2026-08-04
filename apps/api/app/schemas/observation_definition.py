from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

VALUE_TYPES = ("integer", "decimal", "percentage", "boolean", "text")
TARGET_SCOPES = ("crop_batch", "carrier_assignment", "either")


def _normalize_code(v: str) -> str:
    v = v.strip().upper()
    if not v:
        raise ValueError("code must not be blank")
    return v


def _require_non_blank(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("must not be blank")
    return v


def _blank_to_none(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


class ObservationDefinitionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    name: str
    description: str | None = None
    value_type: str
    unit: str | None = None
    target_scope: str
    min_value: Decimal | None = None
    max_value: Decimal | None = None

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        return _normalize_code(v)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return _require_non_blank(v)

    @field_validator("description", "unit")
    @classmethod
    def validate_optional_text(cls, v: str | None) -> str | None:
        return _blank_to_none(v)

    @field_validator("value_type")
    @classmethod
    def validate_value_type(cls, v: str) -> str:
        if v not in VALUE_TYPES:
            raise ValueError(f"value_type must be one of {VALUE_TYPES}")
        return v

    @field_validator("target_scope")
    @classmethod
    def validate_target_scope(cls, v: str) -> str:
        if v not in TARGET_SCOPES:
            raise ValueError(f"target_scope must be one of {TARGET_SCOPES}")
        return v

    @model_validator(mode="after")
    def validate_bounds(self) -> "ObservationDefinitionCreate":
        if self.min_value is not None and self.max_value is not None and self.min_value > self.max_value:
            raise ValueError("min_value cannot exceed max_value")

        if self.value_type in ("boolean", "text"):
            if self.min_value is not None or self.max_value is not None:
                raise ValueError(f"{self.value_type} definitions must not declare min_value/max_value")

        if self.value_type == "percentage":
            if self.min_value is not None and self.min_value < 0:
                raise ValueError("percentage min_value cannot be below 0")
            if self.max_value is not None and self.max_value > 100:
                raise ValueError("percentage max_value cannot exceed 100")

        if self.value_type == "integer":
            if self.min_value is not None and self.min_value != self.min_value.to_integral_value():
                raise ValueError("integer definitions require an integral min_value")
            if self.max_value is not None and self.max_value != self.max_value.to_integral_value():
                raise ValueError("integer definitions require an integral max_value")

        return self


class ObservationDefinitionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    code: str
    name: str
    description: str | None
    value_type: str
    unit: str | None
    target_scope: str
    min_value: Decimal | None
    max_value: Decimal | None
    status: str
    created_by_user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
