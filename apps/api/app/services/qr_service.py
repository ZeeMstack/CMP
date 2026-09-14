"""PILOT-SCAN-001: QR identifier registry + scan-context resolution.

Two responsibilities, deliberately kept separate:

1. `generate_or_get_qr_identifier` -- the one, idempotent way a QR identity
   for an entity comes to exist. Reprinting reuses the row this returns;
   it never mints a second active identity for the same entity (DB-backed
   by `ux_qr_identifiers_active_<column>`, see `app.models.qr_identifier`).

2. `resolve_scan_context` -- given a token already proven to belong to the
   caller's tenant, builds the typed `ScanContext` a scan page renders.
   Every "current" fact (occupancy, batch placement, stage) is read fresh
   from the authoritative live tables here -- never from the QR row
   itself, which stores no mutable operational fact (PILOT-SCAN-001's own
   core rule).

Authorization is NOT this module's concern: which `Permission` a caller
needs for a given `entity_type` is a router-layer policy
(`app.api.qr.ENTITY_PERMISSIONS`), mirroring this codebase's existing
services-never-import-`app.core.permissions` convention. `resolve_scan_context`
accepts a `may_manage` predicate purely to decide which prepared action
links to include (never to gate whether the row itself may be read at all
-- that gate already happened one layer up, before this function is ever
called).
"""
from __future__ import annotations

import secrets
import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.asset_type import AssetType
from app.models.audit_event import AuditEvent
from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.carrier import Carrier
from app.models.carrier_type import CarrierType
from app.models.grading_event import GradingEvent
from app.models.harvested_produce_lot import HarvestedProduceLot
from app.models.qr_identifier import QR_IDENTIFIER_ENTITY_TYPES, QrIdentifier
from app.schemas.qr import (
    AssetScanContext,
    BatchCarrierAssignmentScanContext,
    BatchSummary,
    CarrierScanContext,
    CropBatchScanContext,
    QrCropSummary,
    FinishedGoodsLotScanContext,
    GradedProduceLotScanContext,
    HarvestedProduceLotScanContext,
    LocationOccupantSummary,
    LocationPathSummary,
    LocationScanContext,
    PlacementSummary,
    ScanAction,
    ScanContext,
    ScanWorkItemSummary,
    QrVarietySummary,
)
from app.services import (
    asset_service,
    carrier_service,
    crop_batch_service,
    farm_service,
    farm_work_item_service,
    grading_service,
    location_service,
    movement_service,
    packing_service,
    sowing_service,
)
from app.services.audit import append_audit_event
from app.services.errors import (
    BatchCarrierAssignmentNotFoundError,
    FarmNotFoundError,
    HarvestedProduceLotNotFoundError,
    QrEntityNotEligibleError,
    QrIdentifierNotFoundError,
    QrReprintReasonRequiredError,
)

_ENTITY_COLUMNS: dict[str, str] = {
    "crop_batch": "crop_batch_id",
    "location": "location_id",
    "carrier": "carrier_id",
    "asset": "asset_id",
    "batch_carrier_assignment": "batch_carrier_assignment_id",
    "harvested_produce_lot": "harvested_produce_lot_id",
    "graded_produce_lot": "graded_produce_lot_id",
    "finished_goods_lot": "finished_goods_lot_id",
}

# PILOT-SCAN-001: permanent physical identity (label never requires a reason
# to reprint) vs. everything else, which is an operational/lot record (a
# reprint reason is required -- see `record_label_print`).
_PERMANENT_ENTITY_TYPES = frozenset({"carrier", "asset", "location"})


def _require_active_farm(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> None:
    farm = farm_service.get_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    if farm.status != "active":
        raise FarmNotFoundError(str(farm_id))


def _require_entity_exists(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, entity_type: str, entity_id: uuid.UUID
) -> None:
    """The single source of truth for "does this entity exist, in this
    tenant/farm" -- reuses each domain's own existing, already-tenant/farm-
    scoped read wherever one exists, never a bespoke re-implementation."""
    if entity_type == "crop_batch":
        crop_batch_service.get_batch(db, tenant_id=tenant_id, farm_id=farm_id, batch_id=entity_id)
    elif entity_type == "location":
        location_service.get_location(db, tenant_id=tenant_id, farm_id=farm_id, location_id=entity_id)
    elif entity_type == "carrier":
        carrier_service.get_carrier(db, tenant_id=tenant_id, farm_id=farm_id, carrier_id=entity_id)
    elif entity_type == "asset":
        asset_service.get_asset(db, tenant_id=tenant_id, farm_id=farm_id, asset_id=entity_id)
    elif entity_type == "batch_carrier_assignment":
        _get_assignment_row(db, tenant_id=tenant_id, farm_id=farm_id, assignment_id=entity_id)
    elif entity_type == "harvested_produce_lot":
        _get_harvested_lot_row(db, tenant_id=tenant_id, farm_id=farm_id, lot_id=entity_id)
    elif entity_type == "graded_produce_lot":
        grading_service.get_graded_produce_lot(
            db, tenant_id=tenant_id, farm_id=farm_id, graded_produce_lot_id=entity_id
        )
    elif entity_type == "finished_goods_lot":
        packing_service.get_finished_goods_lot(
            db, tenant_id=tenant_id, farm_id=farm_id, finished_goods_lot_id=entity_id
        )
    else:  # pragma: no cover -- guarded by the CHECK constraint + eligibility check below
        raise QrEntityNotEligibleError(entity_type)


def generate_or_get_qr_identifier(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> QrIdentifier:
    """Idempotent: returns the entity's one active `QrIdentifier`, creating
    it only if none exists yet. Concurrent callers racing to create the
    first identity for the same entity never both win -- the loser's
    INSERT hits `ux_qr_identifiers_active_<column>` and this function
    simply re-reads the row the winner just committed."""
    if entity_type not in QR_IDENTIFIER_ENTITY_TYPES:
        raise QrEntityNotEligibleError(entity_type)
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    _require_entity_exists(db, tenant_id=tenant_id, farm_id=farm_id, entity_type=entity_type, entity_id=entity_id)

    column = _ENTITY_COLUMNS[entity_type]
    existing = db.execute(
        select(QrIdentifier).where(
            QrIdentifier.tenant_id == tenant_id,
            getattr(QrIdentifier, column) == entity_id,
            QrIdentifier.status == "active",
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

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
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.execute(
            select(QrIdentifier).where(
                QrIdentifier.tenant_id == tenant_id,
                getattr(QrIdentifier, column) == entity_id,
                QrIdentifier.status == "active",
            )
        ).scalar_one_or_none()
        if existing is None:
            raise
        return existing

    append_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="qr_identifier_generated",
        entity_type="qr_identifier",
        entity_id=identifier.id,
        event_data={"target_entity_type": entity_type, "target_entity_id": str(entity_id)},
    )
    db.commit()
    db.refresh(identifier)
    return identifier


def record_label_print(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    qr_identifier: QrIdentifier,
    template: str,
    template_version: str,
    reason: str | None,
) -> tuple[datetime, bool]:
    """Appends one `AuditEvent` per print/reprint -- never a second QR
    identity, never a business/operational event (PILOT-SCAN-001: printing
    a label is not proof that farm work occurred). `is_reprint` is derived
    from whether a prior print event already exists for this QR identity,
    never accepted from the caller (an operator cannot declare their own
    print "not a reprint")."""
    prior_print_count = db.execute(
        select(sa_func.count(AuditEvent.id)).where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.entity_type == "qr_identifier",
            AuditEvent.entity_id == qr_identifier.id,
            AuditEvent.action == "qr_label_printed",
        )
    ).scalar_one()
    is_reprint = prior_print_count > 0
    if is_reprint and qr_identifier.entity_type not in _PERMANENT_ENTITY_TYPES and not (reason and reason.strip()):
        raise QrReprintReasonRequiredError(qr_identifier.entity_type)

    printed_at = datetime.now(timezone.utc)
    append_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="qr_label_printed",
        entity_type="qr_identifier",
        entity_id=qr_identifier.id,
        event_data={
            "target_entity_type": qr_identifier.entity_type,
            "target_entity_id": str(_entity_id_of(qr_identifier)),
            "farm_id": str(farm_id),
            "template": template,
            "template_version": template_version,
            "is_reprint": is_reprint,
            "reason": reason,
        },
    )
    db.commit()
    return printed_at, is_reprint


def _entity_id_of(identifier: QrIdentifier) -> uuid.UUID:
    return getattr(identifier, _ENTITY_COLUMNS[identifier.entity_type])


def get_active_qr_identifier_by_token(db: Session, *, tenant_id: uuid.UUID, token: str) -> QrIdentifier:
    """A wrong tenant, an unknown token, and a revoked token all raise the
    identical `QrIdentifierNotFoundError` -- the router maps every one of
    them to the same generic 404 so a token is never an oracle for what
    exists (PILOT-SCAN-001)."""
    row = db.execute(
        select(QrIdentifier).where(
            QrIdentifier.token == token, QrIdentifier.tenant_id == tenant_id, QrIdentifier.status == "active"
        )
    ).scalar_one_or_none()
    if row is None:
        raise QrIdentifierNotFoundError(token)
    return row


# --- scan-context resolution -------------------------------------------------


def _get_assignment_row(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, assignment_id: uuid.UUID
) -> BatchCarrierAssignment:
    row = db.execute(
        select(BatchCarrierAssignment).where(
            BatchCarrierAssignment.id == assignment_id,
            BatchCarrierAssignment.tenant_id == tenant_id,
            BatchCarrierAssignment.farm_id == farm_id,
        )
    ).scalar_one_or_none()
    if row is None:
        raise BatchCarrierAssignmentNotFoundError(str(assignment_id))
    return row


def _get_harvested_lot_row(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, lot_id: uuid.UUID
) -> HarvestedProduceLot:
    row = db.execute(
        select(HarvestedProduceLot).where(
            HarvestedProduceLot.id == lot_id,
            HarvestedProduceLot.tenant_id == tenant_id,
            HarvestedProduceLot.farm_id == farm_id,
        )
    ).scalar_one_or_none()
    if row is None:
        raise HarvestedProduceLotNotFoundError(str(lot_id))
    return row


def _location_path_summary(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, location_id: uuid.UUID) -> LocationPathSummary:
    path = location_service.get_path(db, tenant_id=tenant_id, farm_id=farm_id, location_id=location_id)
    codes = [entry["code"] for entry in path]
    return LocationPathSummary(path_string=" / ".join(codes), codes=codes)


def _resolved_location_summary(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, occupant_kind: str, occupant_id: uuid.UUID
) -> tuple[LocationPathSummary | None, str | None]:
    resolved = movement_service.get_resolved_location(
        db, tenant_id=tenant_id, farm_id=farm_id, occupant_kind=occupant_kind, occupant_id=occupant_id
    )
    if resolved["path_string"] is None:
        return None, resolved["unresolved_reason"]
    codes = (
        [e["code"] for e in resolved["fixed_location_path"]] if resolved["fixed_location_path"] else []
    )
    return LocationPathSummary(path_string=resolved["path_string"], codes=codes), None


def _work_item_summaries(items) -> list[ScanWorkItemSummary]:
    return [
        ScanWorkItemSummary(id=i.id, code=i.code, title=i.title, status=i.status, priority=i.priority)
        for i in items
    ]


def resolve_scan_context(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    qr_identifier: QrIdentifier,
    may: Callable[[str], bool],
) -> ScanContext:
    """`may(permission_value)` decides which prepared action links are
    included -- never whether the identity/context itself may be read
    (the router already proved that before calling this)."""
    farm_id = qr_identifier.farm_id
    entity_type = qr_identifier.entity_type
    entity_id = _entity_id_of(qr_identifier)
    common = {"qr_identifier_id": qr_identifier.id, "farm_id": farm_id}

    work_items = _work_item_summaries(
        farm_work_item_service.list_work_items_for_context(
            db, tenant_id=tenant_id, farm_id=farm_id, **_work_item_context_kwargs(entity_type, entity_id, db, tenant_id, farm_id)
        )
    )

    if entity_type == "crop_batch":
        batch = crop_batch_service.get_batch(db, tenant_id=tenant_id, farm_id=farm_id, batch_id=entity_id)
        assignments = sowing_service.list_batch_carriers(db, tenant_id=tenant_id, farm_id=farm_id, batch_id=entity_id)
        placements = []
        for a in assignments:
            if a.released_effective_time is not None:
                continue
            loc, _ = _resolved_location_summary(
                db, tenant_id=tenant_id, farm_id=farm_id, occupant_kind="carrier", occupant_id=a.carrier.id
            )
            placements.append(
                PlacementSummary(batch_carrier_assignment_id=a.id, carrier_code=a.carrier.code, location=loc)
            )
        actions = [ScanAction(label="View Batch", href=f"/farms/{farm_id}/crop-batches/{entity_id}")]
        if may("observation_entry.manage"):
            actions.append(ScanAction(label="Record Observation", href=f"/farms/{farm_id}/observations?crop_batch_id={entity_id}"))
        if may("harvest.manage"):
            actions.append(ScanAction(label="Harvest", href=f"/farms/{farm_id}/leafy-production/harvest?crop_batch_id={entity_id}"))
        if may("traceability.read"):
            actions.append(ScanAction(label="View traceability", href=f"/farms/{farm_id}/traceability?entryType=crop-batch&id={entity_id}"))
        return CropBatchScanContext(
            **common,
            code=batch.code,
            crop=QrCropSummary(code=batch.crop.code, common_name=batch.crop.common_name),
            variety=_variety_summary(batch.variety),
            state=batch.state,
            current_stage_name=batch.current_stage.name,
            placements=placements,
            actions=actions,
            work_items=work_items,
        )

    if entity_type == "location":
        location = location_service.get_location(db, tenant_id=tenant_id, farm_id=farm_id, location_id=entity_id)
        path = _location_path_summary(db, tenant_id=tenant_id, farm_id=farm_id, location_id=entity_id)
        occupancies = movement_service.list_target_occupants(
            db, tenant_id=tenant_id, farm_id=farm_id, target_kind="location", target_id=entity_id
        )
        occupants = []
        for occ in occupancies:
            if occ.occupant_carrier_id is not None:
                carrier = db.get(Carrier, occ.occupant_carrier_id)
                occupants.append(LocationOccupantSummary(kind="carrier", code=carrier.code))
            elif occ.occupant_asset_id is not None:
                asset = db.get(Asset, occ.occupant_asset_id)
                occupants.append(LocationOccupantSummary(kind="asset", code=asset.code))
        actions = [ScanAction(label="View occupants", href=f"/farms/{farm_id}/locations?highlight={entity_id}")]
        return LocationScanContext(
            **common,
            code=location.code,
            name=location.name,
            location=path,
            occupants=occupants,
            actions=actions,
            work_items=work_items,
        )

    if entity_type == "carrier":
        carrier = carrier_service.get_carrier(db, tenant_id=tenant_id, farm_id=farm_id, carrier_id=entity_id)
        carrier_type = db.get(CarrierType, carrier.carrier_type_id)
        loc, unresolved = _resolved_location_summary(
            db, tenant_id=tenant_id, farm_id=farm_id, occupant_kind="carrier", occupant_id=entity_id
        )
        assignment = sowing_service.get_carrier_batch_assignment(db, tenant_id=tenant_id, farm_id=farm_id, carrier_id=entity_id)
        current_batch = None
        if assignment is not None:
            batch = crop_batch_service.get_batch(db, tenant_id=tenant_id, farm_id=farm_id, batch_id=assignment.batch_id)
            current_batch = BatchSummary(
                id=batch.id, code=batch.code,
                crop=QrCropSummary(code=batch.crop.code, common_name=batch.crop.common_name),
                variety=_variety_summary(batch.variety),
            )
        actions = []
        if current_batch is not None and may("observation_entry.manage"):
            actions.append(ScanAction(label="Record Observation", href=f"/farms/{farm_id}/observations?crop_batch_id={current_batch.id}"))
        actions.append(ScanAction(label="View current occupancy", href=f"/farms/{farm_id}/carriers"))
        return CarrierScanContext(
            **common,
            code=carrier.code,
            carrier_type_name=carrier_type.name,
            status=carrier.status,
            current_batch=current_batch,
            current_location=loc,
            unresolved_reason=unresolved,
            actions=actions,
            work_items=work_items,
        )

    if entity_type == "asset":
        asset = asset_service.get_asset(db, tenant_id=tenant_id, farm_id=farm_id, asset_id=entity_id)
        asset_type = db.get(AssetType, asset.asset_type_id)
        loc, unresolved = _resolved_location_summary(
            db, tenant_id=tenant_id, farm_id=farm_id, occupant_kind="asset", occupant_id=entity_id
        )
        return AssetScanContext(
            **common,
            code=asset.code,
            name=asset.name,
            asset_type_name=asset_type.name,
            status=asset.status,
            current_location=loc,
            unresolved_reason=unresolved,
            actions=[],
            work_items=work_items,
        )

    if entity_type == "batch_carrier_assignment":
        assignment = _get_assignment_row(db, tenant_id=tenant_id, farm_id=farm_id, assignment_id=entity_id)
        carrier = db.get(Carrier, assignment.carrier_id)
        batch = crop_batch_service.get_batch(db, tenant_id=tenant_id, farm_id=farm_id, batch_id=assignment.batch_id)
        loc, unresolved = _resolved_location_summary(
            db, tenant_id=tenant_id, farm_id=farm_id, occupant_kind="carrier", occupant_id=assignment.carrier_id
        )
        actions = [ScanAction(label="View Batch", href=f"/farms/{farm_id}/crop-batches/{batch.id}")]
        if assignment.released_effective_time is None and may("harvest.manage"):
            actions.append(ScanAction(label="Harvest", href=f"/farms/{farm_id}/leafy-production/harvest?assignment_id={entity_id}"))
        return BatchCarrierAssignmentScanContext(
            **common,
            code=f"{batch.code} @ {carrier.code}",
            batch=BatchSummary(
                id=batch.id, code=batch.code,
                crop=QrCropSummary(code=batch.crop.code, common_name=batch.crop.common_name),
                variety=_variety_summary(batch.variety),
            ),
            carrier_code=carrier.code,
            current_location=loc,
            released=assignment.released_effective_time is not None,
            unresolved_reason=unresolved,
            actions=actions,
            work_items=work_items,
        )

    if entity_type == "harvested_produce_lot":
        lot = _get_harvested_lot_row(db, tenant_id=tenant_id, farm_id=farm_id, lot_id=entity_id)
        batch = crop_batch_service.get_batch(db, tenant_id=tenant_id, farm_id=farm_id, batch_id=lot.batch_id)
        actions = [ScanAction(label="View Batch", href=f"/farms/{farm_id}/crop-batches/{batch.id}")]
        if may("grading.manage"):
            actions.append(ScanAction(label="Grade this lot", href=f"/farms/{farm_id}/processing/grading?harvested_produce_lot_id={entity_id}"))
        if may("traceability.read"):
            actions.append(ScanAction(label="View traceability", href=f"/farms/{farm_id}/traceability?entryType=hpl&id={entity_id}"))
        return HarvestedProduceLotScanContext(
            **common,
            code=lot.code,
            batch=BatchSummary(
                id=batch.id, code=batch.code,
                crop=QrCropSummary(code=batch.crop.code, common_name=batch.crop.common_name),
                variety=_variety_summary(batch.variety),
            ),
            total_harvested_weight_kg=lot.total_harvested_weight_kg,
            total_whole_unit_count=lot.total_whole_unit_count,
            effective_time=lot.effective_time,
            actions=actions,
            work_items=work_items,
        )

    if entity_type == "graded_produce_lot":
        lot = grading_service.get_graded_produce_lot(db, tenant_id=tenant_id, farm_id=farm_id, graded_produce_lot_id=entity_id)
        event = db.get(GradingEvent, lot.grading_event_id)
        source_lot = db.get(HarvestedProduceLot, event.source_harvested_produce_lot_id)
        actions = []
        if may("packing.manage"):
            actions.append(ScanAction(label="Pack", href=f"/farms/{farm_id}/processing/packing?graded_produce_lot_id={entity_id}"))
        if may("traceability.read"):
            actions.append(ScanAction(label="View traceability", href=f"/farms/{farm_id}/traceability?entryType=gpl&id={entity_id}"))
        return GradedProduceLotScanContext(
            **common,
            code=lot.code,
            crop=QrCropSummary(code=lot.crop.code, common_name=lot.crop.common_name),
            variety=_variety_summary(lot.variety),
            source_harvested_produce_lot_code=source_lot.code,
            original_received_weight_kg=lot.original_received_weight_kg,
            effective_time=lot.effective_time,
            actions=actions,
            work_items=work_items,
        )

    if entity_type == "finished_goods_lot":
        lot = packing_service.get_finished_goods_lot(db, tenant_id=tenant_id, farm_id=farm_id, finished_goods_lot_id=entity_id)
        actions = []
        if may("finished_goods_storage.manage"):
            actions.append(ScanAction(label="Cold Storage", href=f"/farms/{farm_id}/processing/finished-goods/{entity_id}"))
        if may("dispatch.manage"):
            actions.append(ScanAction(label="Dispatch", href=f"/farms/{farm_id}/processing/dispatch?finished_goods_lot_id={entity_id}"))
        if may("traceability.read"):
            actions.append(ScanAction(label="View traceability", href=f"/farms/{farm_id}/traceability?entryType=fgl&id={entity_id}"))
        return FinishedGoodsLotScanContext(
            **common,
            code=lot.code,
            crop=QrCropSummary(code=lot.crop.code, common_name=lot.crop.common_name),
            variety=_variety_summary(lot.variety),
            net_packed_weight_kg=lot.net_packed_weight_kg,
            package_count=lot.package_count,
            effective_time=lot.effective_time,
            actions=actions,
            work_items=work_items,
        )

    raise QrEntityNotEligibleError(entity_type)  # pragma: no cover -- guarded above


def _variety_summary(variety):
    """Small shared helper: every `*Read` variety summary already carried
    on the domain reads above (`QrVarietySummary(code=..., name=...)`) has
    the same two-field shape -- this just re-wraps it as this module's own
    `app.schemas.qr.QrVarietySummary`, never invents a new one."""
    if variety is None:
        return None
    return QrVarietySummary(code=variety.code, name=variety.name)


def _work_item_context_kwargs(entity_type: str, entity_id: uuid.UUID, db: Session, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> dict:
    """Maps a QR entity onto `FarmWorkItem`'s own structured context
    columns (PILOT-OPS-001) -- never inferring a relationship those
    columns don't already express. A Carrier/Batch-carrier-assignment scan
    surfaces work tied to the CARRIER (the physical thing the operator is
    standing next to); a placement's Batch surfaces work tied to that
    Batch as well, since both are equally relevant to "what should I do
    here"."""
    if entity_type == "crop_batch":
        return {"crop_batch_id": entity_id}
    if entity_type == "location":
        return {"location_id": entity_id}
    if entity_type == "asset":
        return {"asset_id": entity_id}
    if entity_type == "carrier":
        return {"carrier_id": entity_id}
    if entity_type == "batch_carrier_assignment":
        assignment = _get_assignment_row(db, tenant_id=tenant_id, farm_id=farm_id, assignment_id=entity_id)
        return {"carrier_id": assignment.carrier_id, "crop_batch_id": assignment.batch_id}
    return {}
