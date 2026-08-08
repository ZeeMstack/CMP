"""CMP-019 read-only traceability response models. Every quantity field is
a canonical Decimal string (never binary float). Every "potentially
affected" downstream quantity is the affected finished-goods lot's own
*entire* current quantity -- never a proportional share of an upstream
input -- per the ticket's explicit no-proportional-attribution rule."""
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class Limitation(BaseModel):
    code: str
    message: str


class Completeness(BaseModel):
    trace_complete: bool
    limitations: list[Limitation] = []
    capability_limitations: list[str] = []


class CropBatchNode(BaseModel):
    batch_id: uuid.UUID
    code: str
    state: str
    created_effective_time: datetime
    transformation_type: str  # "sown" | "split" | "merge"
    derivation_event_id: uuid.UUID | None = None


class LineageEdge(BaseModel):
    parent_batch_id: uuid.UUID
    child_batch_id: uuid.UUID
    derivation_event_id: uuid.UUID
    derivation_kind: str  # "split" | "merge"


class Lineage(BaseModel):
    batches: list[CropBatchNode]
    edges: list[LineageEdge]


class SeedOrigin(BaseModel):
    seed_lot_id: uuid.UUID
    seed_lot_code: str
    sowing_event_id: uuid.UUID
    sowing_event_line_id: uuid.UUID
    batch_carrier_assignment_id: uuid.UUID
    carrier_id: uuid.UUID
    originating_batch_id: uuid.UUID


class HarvestEventRead(BaseModel):
    harvest_event_id: uuid.UUID
    batch_id: uuid.UUID
    effective_time: datetime
    recorded_time: datetime


class HarvestedProduceLotRead(BaseModel):
    harvested_produce_lot_id: uuid.UUID
    code: str
    harvest_event_id: uuid.UUID
    batch_id: uuid.UUID
    total_harvested_weight_kg: Decimal
    total_whole_unit_count: int | None
    effective_time: datetime


class PackingInputLineRead(BaseModel):
    packing_input_line_id: uuid.UUID
    packing_event_id: uuid.UUID
    harvested_produce_lot_id: uuid.UUID
    consumed_weight_kg: Decimal
    consumed_whole_unit_count: int | None
    is_affected_source: bool | None = None


class PackingEventRead(BaseModel):
    packing_event_id: uuid.UUID
    total_input_weight_kg: Decimal
    packed_output_weight_kg: Decimal
    process_loss_weight_kg: Decimal
    rejected_weight_kg: Decimal
    effective_time: datetime
    recorded_time: datetime


class FinishedGoodsLotRead(BaseModel):
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


class FinishedGoodsLotImpactRead(FinishedGoodsLotRead):
    source_input_weight_kg: Decimal
    source_input_whole_unit_count: int | None
    potentially_affected_available_weight_kg: Decimal
    potentially_affected_available_package_count: int
    potentially_affected_placed_weight_kg: Decimal
    potentially_affected_placed_package_count: int
    potentially_affected_unplaced_weight_kg: Decimal
    potentially_affected_unplaced_package_count: int
    potentially_affected_dispatched_weight_kg: Decimal
    potentially_affected_dispatched_package_count: int


class StorageMovementRead(BaseModel):
    movement_id: uuid.UUID
    finished_goods_lot_id: uuid.UUID
    movement_kind: str
    source_location_id: uuid.UUID | None
    destination_location_id: uuid.UUID | None
    moved_weight_kg: Decimal
    moved_package_count: int
    effective_time: datetime
    recorded_time: datetime


class LocationBalanceRead(BaseModel):
    location_id: uuid.UUID
    weight_kg: Decimal
    package_count: int


class DispatchLineRead(BaseModel):
    dispatch_event_id: uuid.UUID
    dispatch_event_code: str
    dispatch_line_id: uuid.UUID
    finished_goods_lot_id: uuid.UUID
    dispatched_weight_kg: Decimal
    dispatched_package_count: int
    effective_time: datetime
    recorded_time: datetime


class QualityHoldRead(BaseModel):
    quality_hold_id: uuid.UUID
    batch_id: uuid.UUID
    reason_code: str
    reason_text: str
    effective_time: datetime
    is_open: bool
    released_effective_time: datetime | None = None


class ImpactSummary(BaseModel):
    affected_crop_batch_count: int
    affected_harvested_produce_lot_count: int
    affected_finished_goods_lot_count: int
    affected_dispatch_event_count: int
    potentially_affected_available_weight_kg: Decimal
    potentially_affected_available_package_count: int
    potentially_affected_placed_weight_kg: Decimal
    potentially_affected_placed_package_count: int
    potentially_affected_unplaced_weight_kg: Decimal
    potentially_affected_unplaced_package_count: int
    potentially_affected_dispatched_weight_kg: Decimal
    potentially_affected_dispatched_package_count: int


class FinishedGoodsLotTraceRead(BaseModel):
    model_config = ConfigDict()

    subject: FinishedGoodsLotRead
    packing_event: PackingEventRead
    packing_inputs: list[PackingInputLineRead]
    produce_lots: list[HarvestedProduceLotRead]
    harvest_events: list[HarvestEventRead]
    lineage: Lineage
    seed_origins: list[SeedOrigin]
    storage_movements: list[StorageMovementRead]
    dispatches: list[DispatchLineRead]
    quality: list[QualityHoldRead]
    completeness: Completeness


class CropBatchImpactRead(BaseModel):
    subject_batch_id: uuid.UUID
    subject_batch_code: str
    lineage: Lineage
    harvest_events: list[HarvestEventRead]
    produce_lots: list[HarvestedProduceLotRead]
    packing_inputs: list[PackingInputLineRead]
    finished_goods: list[FinishedGoodsLotImpactRead]
    storage: list[LocationBalanceRead]
    dispatches: list[DispatchLineRead]
    summary: ImpactSummary
    completeness: Completeness


class HarvestedProduceLotImpactRead(BaseModel):
    subject_harvested_produce_lot_id: uuid.UUID
    subject_harvested_produce_lot_code: str
    produce_lots: list[HarvestedProduceLotRead]
    packing_inputs: list[PackingInputLineRead]
    finished_goods: list[FinishedGoodsLotImpactRead]
    storage: list[LocationBalanceRead]
    dispatches: list[DispatchLineRead]
    summary: ImpactSummary
    completeness: Completeness
