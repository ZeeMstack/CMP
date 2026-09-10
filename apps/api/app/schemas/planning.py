from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator

from app.schemas.crop_batch import CropSummary, VarietySummary


def _blank_to_none(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


def _validate_positive_quantity(v: Decimal) -> Decimal:
    if v <= 0:
        raise ValueError("quantity must be positive")
    return v


class UomSummary(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    quantity_kind: str


# --- Production Requirement --------------------------------------------------------


class ProductionRequirementCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    crop_id: uuid.UUID
    variety_id: uuid.UUID | None = None
    required_by_date: date
    required_quantity: Decimal
    quantity_uom_id: uuid.UUID
    reference: str | None = None
    notes: str | None = None

    @field_validator("required_quantity")
    @classmethod
    def validate_required_quantity(cls, v: Decimal) -> Decimal:
        return _validate_positive_quantity(v)

    @field_validator("reference", "notes")
    @classmethod
    def validate_text(cls, v: str | None) -> str | None:
        return _blank_to_none(v)


class ProductionRequirementUpdate(BaseModel):
    """Full-replace command for the requirement's own editable fields --
    only permitted while `status = 'open'`. `crop_id`/`variety_id`/
    `quantity_uom_id` have no update path (identity, never corrected)."""

    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    required_by_date: date
    required_quantity: Decimal
    reference: str | None = None
    notes: str | None = None

    @field_validator("required_quantity")
    @classmethod
    def validate_required_quantity(cls, v: Decimal) -> Decimal:
        return _validate_positive_quantity(v)

    @field_validator("reference", "notes")
    @classmethod
    def validate_text(cls, v: str | None) -> str | None:
        return _blank_to_none(v)


class ProductionRequirementStatusCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID


class RequirementFulfillment(BaseModel):
    """PLANNING-OPS-001: kept deliberately separate from `demand_quantity`/
    `planned_coverage_quantity` -- never collapsed into one 'quantity',
    never called 'forecast harvest'. `planned_coverage_quantity` sums only
    non-cancelled Seeding Program Lines' `expected_coverage_quantity`
    (already in the requirement's own UOM -- no conversion). `actual_
    sowings_count` counts real Sowing Events linked to this requirement's
    plan lines -- never equated with harvested quantity."""

    demand_quantity: Decimal
    planned_coverage_quantity: Decimal
    gap_quantity: Decimal
    is_overplanned: bool
    overplanned_quantity: Decimal
    planned_lines_count: int
    actual_sowings_count: int


class ProductionRequirementRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    code: str
    crop: CropSummary
    variety: VarietySummary | None
    required_by_date: date
    required_quantity: Decimal
    uom: UomSummary
    reference: str | None
    notes: str | None
    status: str
    created_by_user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    fulfillment: RequirementFulfillment


# --- Seeding Program Line -----------------------------------------------------------


class SeedingProgramLineCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    planned_sow_date: date
    crop_id: uuid.UUID
    variety_id: uuid.UUID | None = None
    planned_quantity: Decimal
    planned_quantity_uom_id: uuid.UUID
    expected_coverage_quantity: Decimal
    expected_coverage_uom_id: uuid.UUID
    notes: str | None = None

    @field_validator("planned_quantity", "expected_coverage_quantity")
    @classmethod
    def validate_quantities(cls, v: Decimal) -> Decimal:
        return _validate_positive_quantity(v)

    @field_validator("notes")
    @classmethod
    def validate_text(cls, v: str | None) -> str | None:
        return _blank_to_none(v)


class SeedingProgramLineUpdate(BaseModel):
    """Full-replace command for the line's own editable fields -- only
    permitted while `status = 'planned'` AND no actual Sowing has linked to
    this line yet. `crop_id`/`variety_id`/both UOM ids have no update path
    (identity, never corrected)."""

    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    planned_sow_date: date
    planned_quantity: Decimal
    expected_coverage_quantity: Decimal
    notes: str | None = None

    @field_validator("planned_quantity", "expected_coverage_quantity")
    @classmethod
    def validate_quantities(cls, v: Decimal) -> Decimal:
        return _validate_positive_quantity(v)

    @field_validator("notes")
    @classmethod
    def validate_text(cls, v: str | None) -> str | None:
        return _blank_to_none(v)


class SeedingProgramLineStatusCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID


class LinkedSowingSummary(BaseModel):
    id: uuid.UUID
    batch_id: uuid.UUID
    batch_code: str
    effective_time: datetime
    total_seeds_sown: int


class SeedingProgramLineRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    production_requirement_id: uuid.UUID
    requirement_code: str
    planned_sow_date: date
    crop: CropSummary
    variety: VarietySummary | None
    planned_quantity: Decimal
    planned_quantity_uom: UomSummary
    expected_coverage_quantity: Decimal
    expected_coverage_uom: UomSummary
    notes: str | None
    status: str
    linked_sowing_count: int
    created_by_user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class SeedingProgramLineDetailRead(SeedingProgramLineRead):
    linked_sowings: list[LinkedSowingSummary]
