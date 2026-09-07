from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class GoodsReceiptLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inventory_item_id: uuid.UUID
    entered_quantity: Decimal | None = None
    entered_uom_id: uuid.UUID | None = None
    packaging_id: uuid.UUID | None = None
    package_count: int | None = None
    manufacturer_name: str | None = None
    manufacturer_lot_reference: str | None = None
    manufacturing_date: date | None = None
    expiry_date: date | None = None
    seed_crop_id: uuid.UUID | None = None
    seed_variety_id: uuid.UUID | None = None
    seed_lot_code: str | None = None
    external_line_id: str | None = None

    @model_validator(mode="after")
    def validate_entry_shape(self) -> "GoodsReceiptLineIn":
        direct = self.entered_quantity is not None or self.entered_uom_id is not None
        packaged = self.packaging_id is not None or self.package_count is not None
        if direct and packaged:
            raise ValueError("a line may use direct quantity entry or packaging entry, not both")
        if not direct and not packaged:
            raise ValueError("a line must use either direct quantity entry or packaging entry")
        if direct and (self.entered_quantity is None or self.entered_uom_id is None):
            raise ValueError("entered_quantity and entered_uom_id are both required together")
        if self.entered_quantity is not None and self.entered_quantity <= 0:
            raise ValueError("entered_quantity must be positive")
        if packaged and (self.packaging_id is None or self.package_count is None):
            raise ValueError("packaging_id and package_count are both required together")
        if self.package_count is not None and self.package_count <= 0:
            raise ValueError("package_count must be positive")
        if self.manufacturer_lot_reference is not None and self.manufacturer_name is None:
            raise ValueError("manufacturer_lot_reference requires manufacturer_name")
        return self


class GoodsReceiptCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    received_at: datetime
    supplier_name: str | None = None
    external_system: str | None = None
    external_document_id: str | None = None
    notes: str | None = None
    lines: list[GoodsReceiptLineIn]

    @field_validator("lines")
    @classmethod
    def validate_lines(cls, v: list[GoodsReceiptLineIn]) -> list[GoodsReceiptLineIn]:
        if not v:
            raise ValueError("a receipt must have at least one line")
        if len(v) > 500:
            raise ValueError("a receipt may not exceed 500 lines")
        return v


class GoodsReceiptLineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    goods_receipt_id: uuid.UUID
    inventory_item_id: uuid.UUID
    inventory_lot_id: uuid.UUID | None
    entered_quantity: Decimal | None
    entered_uom_id: uuid.UUID | None
    conversion_factor_applied: Decimal | None
    packaging_id: uuid.UUID | None
    package_count: int | None
    package_quantity_snapshot: Decimal | None
    base_quantity: Decimal
    external_line_id: str | None


class GoodsReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    code: str
    received_at: datetime
    recorded_at: datetime
    received_by_user_id: uuid.UUID
    supplier_name: str | None
    external_system: str | None
    external_document_id: str | None
    notes: str | None


__all__ = ["GoodsReceiptLineIn", "GoodsReceiptCreate", "GoodsReceiptLineRead", "GoodsReceiptRead"]
