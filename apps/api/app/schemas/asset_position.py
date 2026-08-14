from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

MAX_BULK_POSITIONS = 1000


def _normalize_prefix(v: str, field: str) -> str:
    v = v.strip().upper()
    if not v:
        raise ValueError(f"{field} must not be blank")
    return v


class AssetPositionsGenerate(BaseModel):
    shelf_count: int
    slots_per_shelf: int
    shelf_prefix: str
    slot_prefix: str
    shelf_pad_width: int
    slot_pad_width: int
    # DOMAIN-FARM-002: applied identically to every generated shelf/slot
    # respectively. NULL/omitted -> effective capacity 1 (exclusive,
    # backward-compatible). Configured data only, never a guessed default --
    # this ticket does not create any Germination workflow that uses it.
    shelf_capacity: int | None = None
    slot_capacity: int | None = None

    @field_validator("shelf_prefix")
    @classmethod
    def validate_shelf_prefix(cls, v: str) -> str:
        return _normalize_prefix(v, "shelf_prefix")

    @field_validator("slot_prefix")
    @classmethod
    def validate_slot_prefix(cls, v: str) -> str:
        return _normalize_prefix(v, "slot_prefix")

    @field_validator("shelf_capacity", "slot_capacity")
    @classmethod
    def validate_capacities(cls, v: int | None) -> int | None:
        if v is not None and v < 1:
            raise ValueError("capacity must be a positive integer")
        return v

    @model_validator(mode="after")
    def validate_counts(self) -> "AssetPositionsGenerate":
        if self.shelf_count < 1:
            raise ValueError("shelf_count must be a positive integer")
        if self.slots_per_shelf < 1:
            raise ValueError("slots_per_shelf must be a positive integer")
        if self.shelf_pad_width < 1:
            raise ValueError("shelf_pad_width must be a positive integer")
        if self.slot_pad_width < 1:
            raise ValueError("slot_pad_width must be a positive integer")
        total = self.shelf_count + (self.shelf_count * self.slots_per_shelf)
        if total > MAX_BULK_POSITIONS:
            raise ValueError(f"cannot generate more than {MAX_BULK_POSITIONS} positions per command")
        return self


class AssetPositionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    asset_id: uuid.UUID
    parent_position_id: uuid.UUID | None
    position_kind: str
    code: str
    name: str
    capacity: int | None


class AssetPositionTreeNode(BaseModel):
    id: uuid.UUID
    position_kind: str
    code: str
    name: str
    children: list["AssetPositionTreeNode"] = []


AssetPositionTreeNode.model_rebuild()
