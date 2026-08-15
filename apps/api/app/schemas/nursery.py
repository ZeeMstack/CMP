from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.sowing_event import CarrierTypeSummary


def _require_tz_aware(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError("effective_time must be timezone-aware")
    return v


def _blank_to_none(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


class SowNewBatchTrayIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    carrier_id: uuid.UUID
    seeds_sown: int = Field(gt=0)


class SowNewBatchCreate(BaseModel):
    """NURSERY-OPS-001: the operator-facing Sowing command -- one call
    creates exactly one Crop Batch and its one Sowing Event. No
    `workflow_id` field: the Workflow is auto-resolved server-side from
    the Seed Lot's crop/variety (see nursery_service._resolve_sowing_workflow)."""

    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    seed_lot_id: uuid.UUID
    seeding_station_id: uuid.UUID
    seeding_machine_id: uuid.UUID | None = None
    effective_time: datetime
    note: str | None = None
    trays: list[SowNewBatchTrayIn] = Field(min_length=1, max_length=500)

    @field_validator("effective_time")
    @classmethod
    def validate_effective_time(cls, v: datetime) -> datetime:
        return _require_tz_aware(v)

    @field_validator("note")
    @classmethod
    def validate_note(cls, v: str | None) -> str | None:
        return _blank_to_none(v)

    @model_validator(mode="after")
    def validate_trays(self) -> "SowNewBatchCreate":
        carrier_ids = [t.carrier_id for t in self.trays]
        if len(carrier_ids) != len(set(carrier_ids)):
            raise ValueError("duplicate carrier_id within one sowing command")
        return self


class AvailableSeedTrayRead(BaseModel):
    id: uuid.UUID
    code: str
    carrier_type: CarrierTypeSummary


__all__ = ["SowNewBatchCreate", "SowNewBatchTrayIn", "AvailableSeedTrayRead"]
