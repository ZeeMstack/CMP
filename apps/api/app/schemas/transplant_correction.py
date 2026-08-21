from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.transplant_event import (
    MAX_ALLOCATIONS,
    MAX_DESTINATION_LINES,
    MAX_SOURCE_LINES,
    TransplantAllocationIn,
    TransplantDestinationLineIn,
    TransplantEventRead,
    TransplantSourceLineIn,
)


def _blank_to_none(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


class TransplantCorrectionReplacementIn(BaseModel):
    """The normal biological Transplant payload representing the correct
    facts -- no `effective_time` (server-derived from the target being
    corrected) and no InterSalads/Movement fields (biology only)."""

    model_config = ConfigDict(extra="forbid")

    note: str | None = None
    source_lines: list[TransplantSourceLineIn] = Field(min_length=1, max_length=MAX_SOURCE_LINES)
    destination_lines: list[TransplantDestinationLineIn] = Field(
        min_length=1, max_length=MAX_DESTINATION_LINES
    )
    allocations: list[TransplantAllocationIn] = Field(min_length=1, max_length=MAX_ALLOCATIONS)

    @field_validator("note")
    @classmethod
    def validate_note(cls, v: str | None) -> str | None:
        return _blank_to_none(v)


class TransplantCorrectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    reason: str
    replacement: TransplantCorrectionReplacementIn | None = None

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("reason is required and must be non-empty")
        if len(v) > 500:
            raise ValueError("reason must be at most 500 characters")
        return v


class TransplantCorrectionRead(BaseModel):
    target_event: TransplantEventRead
    status: str
    reversal_event: TransplantEventRead
    replacement_event: TransplantEventRead | None
    reason: str
