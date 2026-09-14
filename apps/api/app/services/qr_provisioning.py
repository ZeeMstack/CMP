"""PILOT-SCAN-001D: the shared, leaf-level `QrIdentifier` row-insert
primitive, plus the creation-time auto-provisioning entry point every
permanent physical master-data creation path (Carrier/Asset/Location)
calls.

Deliberately has NO dependency on `carrier_service`/`location_service`/
`asset_service`/etc. (unlike `qr_service.py`, which needs those for its
own `_require_entity_exists`/scan-context-resolution responsibilities) --
this keeps the dependency graph acyclic so those very services can import
this module to provision a permanent QR identity at entity-creation time
without a circular import (`qr_service` -> `carrier_service`/
`location_service`/`asset_service` already exists the other way).
"""
from __future__ import annotations

import secrets
import uuid

from sqlalchemy.orm import Session

from app.models.qr_identifier import QrIdentifier
from app.services.audit import append_audit_event

ENTITY_COLUMNS: dict[str, str] = {
    "crop_batch": "crop_batch_id",
    "location": "location_id",
    "carrier": "carrier_id",
    "asset": "asset_id",
    "batch_carrier_assignment": "batch_carrier_assignment_id",
    "harvested_produce_lot": "harvested_produce_lot_id",
    "graded_produce_lot": "graded_produce_lot_id",
    "finished_goods_lot": "finished_goods_lot_id",
}


def insert_qr_identifier(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> QrIdentifier:
    """Pure insert+flush of a new active `QrIdentifier` row -- no dedup
    check, no audit event, no commit. `qr_service.generate_or_get_qr_identifier`
    wraps this with its own dedup check + `IntegrityError` fallback for
    the general case (an already-existing entity, possibly raced by a
    concurrent caller). `ensure_qr_identifier_for_new_entity` below wraps
    it for the creation-time case, where that race is structurally
    impossible (see its own docstring)."""
    column = ENTITY_COLUMNS[entity_type]
    identifier = QrIdentifier(
        tenant_id=tenant_id,
        farm_id=farm_id,
        entity_type=entity_type,
        token=secrets.token_urlsafe(24),
        status="active",
        created_by_user_id=actor_user_id,
        **{column: entity_id},
    )
    db.add(identifier)
    db.flush()
    return identifier


def ensure_qr_identifier_for_new_entity(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> QrIdentifier:
    """PILOT-SCAN-001D: called immediately after flushing a brand-new
    Carrier/Asset/Location row, from WITHIN the caller's own still-open
    transaction -- no commit here. The caller's own existing commit (its
    creation command's one and only commit point) finalizes the entity
    and its permanent QR identity together, atomically: the smallest
    correct transactional approach, and the one that preserves every
    creation path's existing all-or-nothing guarantee (including
    composite commands like Farm Setup, which create several Locations/
    Assets in one transaction) rather than introducing a second, earlier
    commit point that could leave a partially-built structure behind if a
    later step in the same command then failed.

    Never needs `generate_or_get_qr_identifier`'s dedup-check/
    `IntegrityError`-retry dance: `entity_id` here is a UUID freshly
    generated for a row no other session can see until this transaction
    commits, so no concurrent caller can already hold (or be racing to
    create) a `QrIdentifier` for it -- there is no existing row to find,
    and no possible duplicate-insert race to fall back from. If this
    INSERT ever does fail, the exception propagates naturally and aborts
    the caller's whole transaction: physical master data must never
    silently end up without its permanent QR identity."""
    identifier = insert_qr_identifier(
        db,
        tenant_id=tenant_id,
        farm_id=farm_id,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_user_id=actor_user_id,
    )
    append_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="qr_identifier_generated",
        entity_type="qr_identifier",
        entity_id=identifier.id,
        event_data={"target_entity_type": entity_type, "target_entity_id": str(entity_id)},
    )
    return identifier
