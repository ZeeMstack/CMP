from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class InventoryItemSeedProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    inventory_item_id: uuid.UUID
    crop_id: uuid.UUID
    variety_id: uuid.UUID


class InventoryItemSeedProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    crop_id: uuid.UUID
    variety_id: uuid.UUID


class InventoryItemSeedProfileRemove(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID


class InventoryItemSeedProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    inventory_item_id: uuid.UUID
    crop_id: uuid.UUID
    variety_id: uuid.UUID
    created_at: datetime


__all__ = [
    "InventoryItemSeedProfileCreate",
    "InventoryItemSeedProfileUpdate",
    "InventoryItemSeedProfileRemove",
    "InventoryItemSeedProfileRead",
]
