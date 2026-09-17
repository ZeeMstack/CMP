"""PILOT-ASSET-001: automatic readiness provisioning at creation, mirroring
`qr_provisioning.py`'s own established pattern (small, dependency-light
leaf module, called from inside every current Asset/Carrier creation path,
immediately after the entity is flushed and BEFORE that command's own
single commit -- so the entity and its initial readiness row always
succeed or fail together, atomically, in whichever transaction that
creation command already uses).

Unlike QR identity, readiness is not unconditional: a newly-created
Asset/Carrier only gets an `EquipmentReadinessState` row when its TYPE has
`readiness_tracked=true` (see docs/domain/EQUIPMENT_READINESS_MODEL.md,
"Readiness scope"). It starts at `unknown` -- never `ready` -- exactly
like the migration's own legacy backfill; a freshly registered Carrier/
Asset has not actually been assessed any more than a pre-existing one had
been at migration time."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.asset_type import AssetType
from app.models.carrier import Carrier
from app.models.carrier_type import CarrierType
from app.models.equipment_readiness_state import EquipmentReadinessState


def ensure_readiness_state_for_new_asset(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, asset: Asset) -> None:
    asset_type = db.get(AssetType, asset.asset_type_id)
    if asset_type is None or not asset_type.readiness_tracked:
        return
    existing = db.execute(
        select(EquipmentReadinessState.id).where(
            EquipmentReadinessState.tenant_id == tenant_id, EquipmentReadinessState.asset_id == asset.id
        )
    ).first()
    if existing is not None:
        return
    db.add(
        EquipmentReadinessState(
            tenant_id=tenant_id, farm_id=farm_id, entity_type="asset", asset_id=asset.id,
            current_state="unknown", state_changed_at=datetime.now(timezone.utc),
        )
    )


def ensure_readiness_state_for_new_carrier(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, carrier: Carrier
) -> None:
    carrier_type = db.get(CarrierType, carrier.carrier_type_id)
    if carrier_type is None or not carrier_type.readiness_tracked:
        return
    existing = db.execute(
        select(EquipmentReadinessState.id).where(
            EquipmentReadinessState.tenant_id == tenant_id, EquipmentReadinessState.carrier_id == carrier.id
        )
    ).first()
    if existing is not None:
        return
    db.add(
        EquipmentReadinessState(
            tenant_id=tenant_id, farm_id=farm_id, entity_type="carrier", carrier_id=carrier.id,
            current_state="unknown", state_changed_at=datetime.now(timezone.utc),
        )
    )
