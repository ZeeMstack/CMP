from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, field_serializer

from app.schemas.harvest import canonical_decimal_str

# --- Reads -----------------------------------------------------------------------


class ProduceLotLedgerEntryRead(BaseModel):
    id: uuid.UUID
    entry_kind: str
    produce_lot_id: uuid.UUID
    produce_lot_code: str
    harvest_event_id: uuid.UUID
    actor_user_id: uuid.UUID
    weight_delta_kg: Decimal
    whole_unit_count_delta: int | None
    effective_time: datetime
    recorded_time: datetime
    note: str | None

    @field_serializer("weight_delta_kg")
    def serialize_weight_delta(self, v: Decimal) -> str:
        return canonical_decimal_str(v)


class ProduceLotBalanceRead(BaseModel):
    produce_lot_id: uuid.UUID
    produce_lot_code: str
    received_weight_kg: Decimal
    available_weight_kg: Decimal
    received_whole_unit_count: int | None
    available_whole_unit_count: int | None
    entry_count: int
    last_effective_time: datetime

    @field_serializer("received_weight_kg", "available_weight_kg")
    def serialize_weights(self, v: Decimal) -> str:
        return canonical_decimal_str(v)
