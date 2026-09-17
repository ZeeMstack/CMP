"""PILOT-ASSET-001 PART 15: Today-on-the-Farm "Equipment Attention" --
a live, conservative read-model. Never manufactures alerts -- every item is
derived from an explicit, already-recorded fact (an open Incident, a
persisted readiness state), mirroring `water_attention_service`'s own
documented restraint. Never duplicates `FarmWorkItem` rows."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.carrier import Carrier
from app.models.equipment_readiness_state import EquipmentReadinessState
from app.schemas.equipment_attention import EquipmentAttentionItem
from app.services import equipment_incident_service, farm_service
from app.services.errors import FarmNotFoundError

_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _require_active_farm(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID):
    farm = farm_service.get_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    if farm.status != "active":
        raise FarmNotFoundError(str(farm_id))
    return farm


def get_equipment_attention(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID
) -> list[EquipmentAttentionItem]:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    items: list[EquipmentAttentionItem] = []

    incidents = equipment_incident_service.list_open_critical_incidents(db, tenant_id=tenant_id, farm_id=farm_id)
    asset_ids = {i.asset_id for i in incidents}
    asset_criticality = {}
    if asset_ids:
        for row in db.execute(
            select(Asset.id, Asset.code, Asset.criticality).where(
                Asset.tenant_id == tenant_id, Asset.id.in_(asset_ids)
            )
        ):
            asset_criticality[row.id] = (row.code, row.criticality)

    def _incident_sort_key(incident) -> tuple:
        _code, criticality = asset_criticality.get(incident.asset_id, (None, "normal"))
        criticality_rank = {"critical": 0, "important": 1, "normal": 2}.get(criticality, 2)
        return (criticality_rank, _SEVERITY_RANK.get(incident.severity, 3), incident.opened_at)

    for incident in sorted(incidents, key=_incident_sort_key):
        code, criticality = asset_criticality.get(incident.asset_id, (None, "normal"))
        items.append(
            EquipmentAttentionItem(
                kind="OPEN_INCIDENT",
                message=f"{incident.code}: {incident.category} incident ({incident.severity}) on {code or incident.asset_id}",
                asset_id=incident.asset_id, code=code, equipment_incident_id=incident.id,
                severity=incident.severity, criticality=criticality,
            )
        )

    readiness_states = list(
        db.execute(
            select(EquipmentReadinessState).where(
                EquipmentReadinessState.tenant_id == tenant_id, EquipmentReadinessState.farm_id == farm_id,
                EquipmentReadinessState.current_state.in_(
                    ("maintenance", "damaged", "awaiting_cleaning", "cleaning_completed")
                ),
            )
        ).scalars()
    )
    asset_state_ids = {s.asset_id for s in readiness_states if s.asset_id}
    carrier_state_ids = {s.carrier_id for s in readiness_states if s.carrier_id}
    asset_codes = {}
    if asset_state_ids:
        for row in db.execute(
            select(Asset.id, Asset.code).where(Asset.tenant_id == tenant_id, Asset.id.in_(asset_state_ids))
        ):
            asset_codes[row.id] = row.code
    carrier_codes = {}
    if carrier_state_ids:
        for row in db.execute(
            select(Carrier.id, Carrier.code).where(Carrier.tenant_id == tenant_id, Carrier.id.in_(carrier_state_ids))
        ):
            carrier_codes[row.id] = row.code

    kind_by_state = {
        "maintenance": "MAINTENANCE", "damaged": "DAMAGED", "awaiting_cleaning": "AWAITING_CLEANING",
        "cleaning_completed": "CLEANING_COMPLETED_NOT_RELEASED",
    }
    message_by_state = {
        "maintenance": "under maintenance", "damaged": "reported damaged",
        "awaiting_cleaning": "awaiting cleaning", "cleaning_completed": "cleaned but not yet released ready",
    }
    for state in sorted(readiness_states, key=lambda s: s.state_changed_at):
        code = asset_codes.get(state.asset_id) if state.entity_type == "asset" else carrier_codes.get(state.carrier_id)
        items.append(
            EquipmentAttentionItem(
                kind=kind_by_state[state.current_state],
                message=f"{code or state.id} is {message_by_state[state.current_state]}",
                asset_id=state.asset_id, carrier_id=state.carrier_id, code=code,
            )
        )

    return items
