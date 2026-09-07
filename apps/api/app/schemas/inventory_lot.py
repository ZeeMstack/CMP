from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class InventoryLotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    inventory_item_id: uuid.UUID
    code: str
    manufacturer_name: str | None
    manufacturer_lot_reference: str | None
    manufacturing_date: date | None
    expiry_date: date | None
    created_at: datetime | None = None


__all__ = ["InventoryLotRead"]
