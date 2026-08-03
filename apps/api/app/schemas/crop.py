from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, field_validator

CROP_CATEGORIES = frozenset({"leafy_green", "vine", "herb", "other"})


def _normalize_code(v: str) -> str:
    v = v.strip().upper()
    if not v:
        raise ValueError("code must not be blank")
    return v


def _not_blank(v: str, field: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError(f"{field} must not be blank")
    return v


class CropCreate(BaseModel):
    code: str
    common_name: str
    scientific_name: str | None = None
    crop_category: str

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        return _normalize_code(v)

    @field_validator("common_name")
    @classmethod
    def validate_common_name(cls, v: str) -> str:
        return _not_blank(v, "common_name")

    @field_validator("crop_category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        if v not in CROP_CATEGORIES:
            allowed = ", ".join(sorted(CROP_CATEGORIES))
            raise ValueError(f"crop_category must be one of: {allowed}")
        return v


class CropRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    code: str
    common_name: str
    scientific_name: str | None
    crop_category: str
    status: str


class VarietyCreate(BaseModel):
    code: str
    name: str
    supplier_reference: str | None = None

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        return _normalize_code(v)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return _not_blank(v, "name")


class VarietyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    crop_id: uuid.UUID
    code: str
    name: str
    supplier_reference: str | None
    status: str
