from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


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


class InventoryCategoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    code: str
    name: str

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        return _normalize_code(v)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return _require_non_blank(v, field_name="name")


class InventoryCategoryUpdate(BaseModel):
    """Narrow update -- `name` only, the sole mutable field beyond status.
    `code` is never accepted here; there is no update path for it at all."""

    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    name: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return _require_non_blank(v, field_name="name")


class InventoryCategoryDeactivate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID


class InventoryCategoryReactivate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID


class InventoryCategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    code: str
    name: str
    status: str
    created_at: datetime


__all__ = [
    "InventoryCategoryCreate",
    "InventoryCategoryUpdate",
    "InventoryCategoryDeactivate",
    "InventoryCategoryReactivate",
    "InventoryCategoryRead",
]
