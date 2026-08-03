from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.schemas.crop_batch import CropSummary, VarietySummary


def _normalize_code(v: str) -> str:
    v = v.strip().upper()
    if not v:
        raise ValueError("code must not be blank")
    return v


def _blank_to_none(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


class SeedLotCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    crop_id: uuid.UUID
    variety_id: uuid.UUID
    code: str
    supplier_name: str | None = None
    supplier_lot_reference: str | None = None
    received_date: date | None = None
    expiry_date: date | None = None

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        return _normalize_code(v)

    @field_validator("supplier_name", "supplier_lot_reference")
    @classmethod
    def validate_optional_text(cls, v: str | None) -> str | None:
        return _blank_to_none(v)

    @model_validator(mode="after")
    def validate_dates(self) -> "SeedLotCreate":
        if self.received_date is not None and self.expiry_date is not None:
            if self.expiry_date < self.received_date:
                raise ValueError("expiry_date cannot precede received_date")
        return self


class SeedLotRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    crop: CropSummary
    variety: VarietySummary
    code: str
    supplier_name: str | None
    supplier_lot_reference: str | None
    received_date: date | None
    expiry_date: date | None
    status: str
    created_at: datetime
    updated_at: datetime
