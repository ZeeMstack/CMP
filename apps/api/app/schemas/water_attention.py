from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel

WATER_ATTENTION_KINDS = ("CIRCUIT_MISSING_RESERVOIR", "INSTRUMENT_NEVER_CALIBRATED", "MEASUREMENT_OUTSIDE_RECIPE_TARGET")


class WaterAttentionItem(BaseModel):
    kind: str
    message: str
    irrigation_circuit_id: uuid.UUID | None = None
    code: str | None = None
    name: str | None = None
    water_instrument_id: uuid.UUID | None = None
    reservoir_id: uuid.UUID | None = None
    sampling_point_id: uuid.UUID | None = None
    metric: str | None = None
    measured_value: Decimal | None = None
    target_value: Decimal | None = None
    nutrient_recipe_version_id: uuid.UUID | None = None
