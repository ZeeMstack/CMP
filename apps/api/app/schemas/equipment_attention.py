from __future__ import annotations

import uuid

from pydantic import BaseModel

# PART 15: never manufactures alerts -- every kind here is derived from an
# explicit, already-recorded fact (an open Incident, a persisted readiness
# state), mirroring `water_attention_service`'s own documented restraint.
EQUIPMENT_ATTENTION_KINDS = (
    "OPEN_INCIDENT", "MAINTENANCE", "DAMAGED", "AWAITING_CLEANING", "CLEANING_COMPLETED_NOT_RELEASED",
)


class EquipmentAttentionItem(BaseModel):
    kind: str
    message: str
    asset_id: uuid.UUID | None = None
    carrier_id: uuid.UUID | None = None
    code: str | None = None
    equipment_incident_id: uuid.UUID | None = None
    severity: str | None = None
    criticality: str | None = None
