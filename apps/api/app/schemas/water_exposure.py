from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class ExposedPlacementRead(BaseModel):
    batch_id: uuid.UUID
    carrier_id: uuid.UUID
    location_id: uuid.UUID
    irrigation_circuit_id: uuid.UUID
    exposure_kind: str
    overlap_start: datetime
    overlap_end: datetime


class BatchWaterExposureRead(BaseModel):
    irrigation_circuit_id: uuid.UUID
    reservoir_ids: list[uuid.UUID]
    location_ids: list[uuid.UUID]
    exposure_kind: str
