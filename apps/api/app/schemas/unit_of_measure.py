from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict


class UnitOfMeasureRead(BaseModel):
    """STORE-INV-001B: read-only system catalog -- no create/update/delete
    schema exists for `UnitOfMeasure` at all."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    quantity_kind: str
    conversion_family: str | None


__all__ = ["UnitOfMeasureRead"]
