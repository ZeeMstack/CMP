from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, field_validator


def _normalize_code(v: str) -> str:
    v = v.strip().upper()
    if not v:
        raise ValueError("code must not be blank")
    return v


class AssetCreate(BaseModel):
    asset_type_code: str
    code: str
    name: str
    commissioned_date: date | None = None

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        return _normalize_code(v)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        return v


class AssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    asset_type_id: uuid.UUID
    code: str
    name: str
    status: str
    commissioned_date: date | None
    retired_date: date | None
