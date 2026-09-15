"""PILOT-SCAN-001: QR identifier + scan-context response shapes.

`ScanContext` is a discriminated union keyed on `entity_type` -- never one
giant universal object carrying every entity's fields at once (a caller
that receives a `CarrierScanContext` gets exactly Carrier-shaped fields,
nothing else). Every "current" fact here (occupancy, batch placement,
status) is resolved fresh by `qr_service` from the authoritative live
tables at request time -- the QR row itself stores none of it (see
`app.models.qr_identifier`).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


class ScanAction(BaseModel):
    """One prepared-workspace link. `href` is a CMP frontend route the
    caller is already authorized to open -- the destination page
    independently re-resolves/validates every id itself (PILOT-SCAN-001:
    QR resolution is never authorization for the downstream command)."""

    label: str
    href: str


class ScanWorkItemSummary(BaseModel):
    """PILOT-OPS-001 structured-context cross-reference -- never a
    duplicate of the Work Item itself, just enough to let the operator
    decide whether to open it."""

    id: uuid.UUID
    code: str
    title: str
    status: str
    priority: str


class LocationPathSummary(BaseModel):
    path_string: str
    codes: list[str]
    # PILOT-SCAN-001F: stable Location ids for the same ancestor chain
    # `codes` already describes, root-first, ending with the leaf/current
    # Location itself -- `ids[-1]` is the authoritative current Location
    # id, and every other entry is one of its ancestors. Location-first
    # scan validation compares these ids, never `codes`/`path_string`
    # (CLAUDE.md rule 3: locations are UUID-based; never string-prefix
    # matching on a display path).
    ids: list[uuid.UUID]


class QrCropSummary(BaseModel):
    code: str
    common_name: str


class QrVarietySummary(BaseModel):
    code: str
    name: str


class BatchSummary(BaseModel):
    id: uuid.UUID
    code: str
    crop: QrCropSummary
    variety: QrVarietySummary | None


class PlacementSummary(BaseModel):
    """One current physical portion of a Batch -- CMP-006's own
    BatchCarrierAssignment identity, never collapsed into the parent
    Batch (a Batch may occupy several Carriers/Locations at once)."""

    batch_carrier_assignment_id: uuid.UUID
    carrier_code: str
    location: LocationPathSummary | None


class _ScanContextBase(BaseModel):
    qr_identifier_id: uuid.UUID
    farm_id: uuid.UUID
    code: str
    actions: list[ScanAction] = Field(default_factory=list)
    work_items: list[ScanWorkItemSummary] = Field(default_factory=list)


class CropBatchScanContext(_ScanContextBase):
    entity_type: Literal["crop_batch"] = "crop_batch"
    crop: QrCropSummary
    variety: QrVarietySummary | None
    state: str
    current_stage_name: str
    placements: list[PlacementSummary]


class LocationOccupantSummary(BaseModel):
    kind: Literal["carrier", "asset"]
    code: str


class LocationScanContext(_ScanContextBase):
    entity_type: Literal["location"] = "location"
    name: str
    location: LocationPathSummary
    occupants: list[LocationOccupantSummary]


class CarrierScanContext(_ScanContextBase):
    entity_type: Literal["carrier"] = "carrier"
    carrier_type_name: str
    status: str
    current_batch: BatchSummary | None
    current_location: LocationPathSummary | None
    unresolved_reason: str | None


class AssetScanContext(_ScanContextBase):
    entity_type: Literal["asset"] = "asset"
    name: str
    asset_type_name: str
    status: str
    current_location: LocationPathSummary | None
    unresolved_reason: str | None


class BatchCarrierAssignmentScanContext(_ScanContextBase):
    entity_type: Literal["batch_carrier_assignment"] = "batch_carrier_assignment"
    batch: BatchSummary
    carrier_code: str
    current_location: LocationPathSummary | None
    released: bool
    unresolved_reason: str | None


class HarvestedProduceLotScanContext(_ScanContextBase):
    entity_type: Literal["harvested_produce_lot"] = "harvested_produce_lot"
    batch: BatchSummary
    total_harvested_weight_kg: Decimal
    total_whole_unit_count: int | None
    effective_time: datetime


class GradedProduceLotScanContext(_ScanContextBase):
    entity_type: Literal["graded_produce_lot"] = "graded_produce_lot"
    crop: QrCropSummary
    variety: QrVarietySummary | None
    source_harvested_produce_lot_code: str
    original_received_weight_kg: Decimal
    effective_time: datetime


class FinishedGoodsLotScanContext(_ScanContextBase):
    entity_type: Literal["finished_goods_lot"] = "finished_goods_lot"
    crop: QrCropSummary
    variety: QrVarietySummary | None
    net_packed_weight_kg: Decimal
    package_count: int
    effective_time: datetime


ScanContext = Annotated[
    Union[
        CropBatchScanContext,
        LocationScanContext,
        CarrierScanContext,
        AssetScanContext,
        BatchCarrierAssignmentScanContext,
        HarvestedProduceLotScanContext,
        GradedProduceLotScanContext,
        FinishedGoodsLotScanContext,
    ],
    Field(discriminator="entity_type"),
]


class QrIdentifierRead(BaseModel):
    id: uuid.UUID
    entity_type: str
    token: str
    created_at: datetime


class PrintLabelRequest(BaseModel):
    reason: str | None = None
    template: str
    template_version: str


class PrintLabelResponse(BaseModel):
    """`requested_at`, not `printed_at`: a browser print dialog cannot
    prove a physical label was actually produced (PILOT-SCAN-001 FINAL
    SECURITY CLOSURE) -- this only records when the print request was
    made."""

    qr_identifier_id: uuid.UUID
    requested_at: datetime
    is_reprint: bool
