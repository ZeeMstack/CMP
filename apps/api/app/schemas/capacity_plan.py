from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

# PILOT-PLAN-001A: `locations.capacity` (DOMAIN-FARM-002) is the sole
# authoritative capacity source in V1 -- always an occupant-slot count, so
# the unit is a fixed constant, not a stored/variable field. See
# `docs/domain/HARVEST_FORECAST_CAPACITY_MODEL.md` §Capacity Grain.
CAPACITY_UNIT = "position"


def _blank_to_none(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


class CreateProductionCapacityAllocation(BaseModel):
    """PILOT-PLAN-001A Part 5: a PLANNING reservation of future
    occupant-slot capacity at one Location. `planned_start_date`/
    `planned_end_date` are a half-open `[start, end)` window -- the
    allocation covers calendar dates `planned_start_date` through
    `planned_end_date - 1 day` inclusive."""

    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    location_id: uuid.UUID
    production_system_id: uuid.UUID | None = None
    planned_start_date: date
    planned_end_date: date
    planned_capacity_amount: int
    source_seeding_program_line_id: uuid.UUID | None = None
    source_crop_batch_id: uuid.UUID | None = None
    notes: str | None = None

    @field_validator("planned_capacity_amount")
    @classmethod
    def validate_amount(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("planned_capacity_amount must be positive")
        return v

    @field_validator("notes")
    @classmethod
    def validate_text(cls, v: str | None) -> str | None:
        return _blank_to_none(v)

    @model_validator(mode="after")
    def validate_window(self) -> "CreateProductionCapacityAllocation":
        if self.planned_end_date <= self.planned_start_date:
            raise ValueError("planned_end_date must be after planned_start_date")
        return self


class UpdateProductionCapacityAllocation(BaseModel):
    """Full-replace command for the allocation's own editable fields --
    only permitted while `status = 'active'`. `location_id`/source
    references have no update path (identity, never corrected -- cancel
    and create a new allocation instead)."""

    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    planned_start_date: date
    planned_end_date: date
    planned_capacity_amount: int
    production_system_id: uuid.UUID | None = None
    notes: str | None = None

    @field_validator("planned_capacity_amount")
    @classmethod
    def validate_amount(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("planned_capacity_amount must be positive")
        return v

    @field_validator("notes")
    @classmethod
    def validate_text(cls, v: str | None) -> str | None:
        return _blank_to_none(v)

    @model_validator(mode="after")
    def validate_window(self) -> "UpdateProductionCapacityAllocation":
        if self.planned_end_date <= self.planned_start_date:
            raise ValueError("planned_end_date must be after planned_start_date")
        return self


class CapacityAllocationStatusCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID


class ProductionCapacityAllocationRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    code: str
    location_id: uuid.UUID
    location_code: str
    production_system_id: uuid.UUID | None
    planned_start_date: date
    planned_end_date: date
    planned_capacity_amount: int
    capacity_unit: str = CAPACITY_UNIT
    source_seeding_program_line_id: uuid.UUID | None
    source_crop_batch_id: uuid.UUID | None
    status: str
    notes: str | None
    created_by_user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    cancelled_by_user_id: uuid.UUID | None
    cancelled_at: datetime | None


class LocationCapacitySummaryRead(BaseModel):
    """PILOT-PLAN-001A Part 5/6: PLANNED / ACTUAL / AVAILABLE kept as
    distinct dimensions, never collapsed. `capacity_status = 'unknown'`
    whenever the target Location carries no authoritative capacity fact
    (never fabricated as unlimited or zero) -- see `capacity_plan_service.
    _effective_capacity`."""

    location_id: uuid.UUID
    location_code: str
    window_start_date: date
    window_end_date: date
    capacity_status: str  # "known" | "unknown"
    authoritative_capacity: int | None
    capacity_unit: str = CAPACITY_UNIT
    planned_used_capacity: int
    available_planned_capacity: int | None
    allocations: list[ProductionCapacityAllocationRead]
