"""CMP-020 recall case request/response models. `frozen_scope` (immutable
ID lists) and `live_state` (current available/placed/unplaced/dispatch
reads) are always kept as distinct sections -- never merged, never
persisted balances. Weight fields are plain `Decimal`, matching CMP-019's
own convention."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


def _normalize_code(v: str) -> str:
    v = v.strip().upper()
    if not v:
        raise ValueError("code must not be blank")
    return v


def _require_tz_aware(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError("effective_time must be timezone-aware")
    return v


# --- Commands ----------------------------------------------------------------------


class RecallCaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    effective_time: datetime
    code: str
    crop_batch_id: uuid.UUID | None = None
    harvested_produce_lot_id: uuid.UUID | None = None
    graded_produce_lot_id: uuid.UUID | None = None
    finished_goods_lot_id: uuid.UUID | None = None
    reason_code: str
    reason_text: str

    @field_validator("effective_time")
    @classmethod
    def validate_effective_time(cls, v: datetime) -> datetime:
        return _require_tz_aware(v)

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        return _normalize_code(v)

    @field_validator("reason_code", "reason_text")
    @classmethod
    def validate_reason(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v

    @model_validator(mode="after")
    def validate_exactly_one_source(self) -> "RecallCaseCreate":
        sources = [
            self.crop_batch_id, self.harvested_produce_lot_id, self.graded_produce_lot_id,
            self.finished_goods_lot_id,
        ]
        if sum(s is not None for s in sources) != 1:
            raise ValueError(
                "exactly one of crop_batch_id, harvested_produce_lot_id, graded_produce_lot_id, "
                "finished_goods_lot_id must be provided"
            )
        return self


class RecallCaseClose(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    effective_time: datetime
    close_reason: str

    @field_validator("effective_time")
    @classmethod
    def validate_effective_time(cls, v: datetime) -> datetime:
        return _require_tz_aware(v)

    @field_validator("close_reason")
    @classmethod
    def validate_close_reason(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v


# --- Reads -----------------------------------------------------------------------


class RecallCaseSummaryRead(BaseModel):
    recall_case_id: uuid.UUID
    code: str
    crop_batch_id: uuid.UUID | None
    harvested_produce_lot_id: uuid.UUID | None
    graded_produce_lot_id: uuid.UUID | None
    finished_goods_lot_id: uuid.UUID | None
    reason_code: str
    reason_text: str
    effective_time: datetime
    recorded_time: datetime
    actor_user_id: uuid.UUID
    is_open: bool


class RecallCaseClosureRead(BaseModel):
    id: uuid.UUID
    effective_time: datetime
    recorded_time: datetime
    actor_user_id: uuid.UUID
    close_reason: str


class FrozenScopeRead(BaseModel):
    crop_batch_ids: list[uuid.UUID]
    harvested_produce_lot_ids: list[uuid.UUID]
    graded_produce_lot_ids: list[uuid.UUID]
    finished_goods_lot_ids: list[uuid.UUID]


class RecallFinishedGoodsLotLiveRead(BaseModel):
    finished_goods_lot_id: uuid.UUID
    code: str
    packing_event_id: uuid.UUID
    net_packed_weight_kg: Decimal
    package_count: int
    effective_time: datetime
    available_weight_kg: Decimal
    available_package_count: int
    placed_weight_kg: Decimal
    placed_package_count: int
    unplaced_weight_kg: Decimal
    unplaced_package_count: int


class RecallLocationBalanceRead(BaseModel):
    finished_goods_lot_id: uuid.UUID
    location_id: uuid.UUID
    weight_kg: Decimal
    package_count: int


class RecallDispatchLineRead(BaseModel):
    dispatch_event_id: uuid.UUID
    dispatch_event_code: str
    dispatch_line_id: uuid.UUID
    finished_goods_lot_id: uuid.UUID
    dispatched_weight_kg: Decimal
    dispatched_package_count: int
    effective_time: datetime
    recorded_time: datetime


class LiveStateRead(BaseModel):
    finished_goods_lots: list[RecallFinishedGoodsLotLiveRead]
    storage: list[RecallLocationBalanceRead]
    dispatches: list[RecallDispatchLineRead]


class RecallCaseDetailRead(BaseModel):
    recall_case_id: uuid.UUID
    code: str
    crop_batch_id: uuid.UUID | None
    harvested_produce_lot_id: uuid.UUID | None
    graded_produce_lot_id: uuid.UUID | None
    finished_goods_lot_id: uuid.UUID | None
    reason_code: str
    reason_text: str
    effective_time: datetime
    recorded_time: datetime
    actor_user_id: uuid.UUID
    is_open: bool
    closure: RecallCaseClosureRead | None
    frozen_scope: FrozenScopeRead
    live_state: LiveStateRead


__all__ = [
    "RecallCaseCreate",
    "RecallCaseClose",
    "RecallCaseSummaryRead",
    "RecallCaseClosureRead",
    "FrozenScopeRead",
    "RecallFinishedGoodsLotLiveRead",
    "RecallLocationBalanceRead",
    "RecallDispatchLineRead",
    "LiveStateRead",
    "RecallCaseDetailRead",
]
