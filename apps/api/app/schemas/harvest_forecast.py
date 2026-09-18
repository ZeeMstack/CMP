from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.models.batch_harvest_forecast import FORECAST_BASES
from app.schemas.crop_batch import CropSummary, StageSummary, VarietySummary
from app.schemas.planning import UomSummary


def _blank_to_none(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


class RecordBatchHarvestForecast(BaseModel):
    """PILOT-PLAN-001A: records the Batch's first forecast, or revises its
    current one -- the same command handles both (mirrors `batch_stage_
    runs`' "insert a new row, close the old one" shape). `window_end_date`
    and `window_start_date` are farm-local planning dates, inclusive on
    both ends (a human date range, not the half-open interval Capacity
    Allocation uses -- see `docs/domain/HARVEST_FORECAST_CAPACITY_MODEL.md`
    §Time Semantics)."""

    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    window_start_date: date
    window_end_date: date
    low_quantity: Decimal
    expected_quantity: Decimal
    high_quantity: Decimal
    quantity_uom_id: uuid.UUID
    basis: str
    effective_time: datetime
    notes: str | None = None
    revision_reason: str | None = None

    @field_validator("low_quantity")
    @classmethod
    def validate_low(cls, v: Decimal) -> Decimal:
        if v < 0:
            raise ValueError("low_quantity must be >= 0")
        return v

    @field_validator("expected_quantity")
    @classmethod
    def validate_expected(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("expected_quantity must be positive")
        return v

    @field_validator("high_quantity")
    @classmethod
    def validate_high(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("high_quantity must be positive")
        return v

    @field_validator("basis")
    @classmethod
    def validate_basis(cls, v: str) -> str:
        if v not in FORECAST_BASES:
            raise ValueError(f"basis must be one of {FORECAST_BASES}")
        return v

    @field_validator("notes", "revision_reason")
    @classmethod
    def validate_text(cls, v: str | None) -> str | None:
        return _blank_to_none(v)

    @model_validator(mode="after")
    def validate_shape(self) -> "RecordBatchHarvestForecast":
        if not (self.low_quantity <= self.expected_quantity <= self.high_quantity):
            raise ValueError("forecast range must satisfy low <= expected <= high")
        if self.window_end_date < self.window_start_date:
            raise ValueError("window_end_date must not be before window_start_date")
        return self


class BatchHarvestForecastRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    batch_id: uuid.UUID
    revision_number: int
    is_current: bool
    superseded_at: datetime | None
    superseded_by_forecast_id: uuid.UUID | None
    window_start_date: date
    window_end_date: date
    low_quantity: Decimal
    expected_quantity: Decimal
    high_quantity: Decimal
    uom: UomSummary
    basis: str
    notes: str | None
    revision_reason: str | None
    recorded_by_user_id: uuid.UUID
    effective_time: datetime
    recorded_time: datetime


class BatchHarvestActualSummary(BaseModel):
    """READ-ONLY comparison against the current forecast -- never written
    back to the forecast row, and never derived by mutating it. Harvest
    weight is always recorded in kg (`harvested_produce_lots.total_
    harvested_weight_kg`, the codebase-wide harvest convention); `comparable`
    is false, and the *_in_forecast_uom fields are None, whenever no UOM
    conversion path exists from kg to the forecast's own UOM (never a
    silently invented conversion)."""

    total_harvested_weight_kg: Decimal
    first_harvest_date: date | None
    latest_harvest_date: date | None
    comparable_to_forecast_uom: bool
    actual_quantity_in_forecast_uom: Decimal | None
    remaining_forecast_quantity_in_forecast_uom: Decimal | None


class BatchHarvestForecastStatusRead(BaseModel):
    """PILOT-PLAN-001A Part 2 read model -- forecast vs actual, plus risk
    signals. A pure computed read; nothing here is persisted."""

    batch_id: uuid.UUID
    batch_code: str
    crop: CropSummary
    variety: VarietySummary | None
    current_stage: StageSummary
    current_forecast: BatchHarvestForecastRead | None
    actual: BatchHarvestActualSummary
    open_crop_issue_count: int
    active_location_codes: list[str]
