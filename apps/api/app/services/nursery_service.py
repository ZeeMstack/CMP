"""NURSERY-OPS-001: the operator-facing Sowing command.

Reuses CMP-009's Seed Lot / Sowing / Batch-Carrier-Assignment primitives
verbatim (`sowing_service`) and CMP-007/008's Crop Batch / Workflow
primitives verbatim (`crop_batch_service`) -- this module invents no new
domain tables. It adds exactly what was missing for a real operator to
complete one Sowing in a single command:

- Auto-resolves the Workflow from the selected Seed Lot's (crop, variety)
  -- the operator never sees or picks a "Workflow" (`_resolve_sowing_workflow`).
- Generates a human-readable, non-user-supplied Crop Batch code, safe
  under concurrency (`_generate_batch_code`, `pg_advisory_xact_lock`,
  mirrors FARM-SETUP-001's own established concurrency-safety pattern).
- Validates the Seeding Station (`seeding_station` location under a
  Nursery greenhouse) and optional Seeding Machine (`seeding_machine`
  asset, farm-level equipment -- provenance only, never Nursery-owned;
  see FARM-SETUP-001.1's Trolley/Seeding Machine review).
- Orchestrates `crop_batch_service._create_batch_core` +
  `sowing_service._sow_batch_core` inside ONE transaction, ONE
  idempotency check, ONE audit event, ONE commit -- true atomicity, not
  two separately-committing HTTP calls.

`sow_new_batch`'s own idempotency key IS `SowingEvent.client_command_id`
(reused directly, not a new table) -- valid because NURSERY-OPS-001 also
makes "at most one Sowing Event per Crop Batch, ever" a DB-enforced
invariant (`ux_sowing_events_batch_id`), so a batch created by this
command can, by construction, have exactly one associated command.
"""
import hashlib
import uuid
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.carrier import Carrier
from app.models.carrier_type import CarrierType
from app.models.crop_batch import CropBatch
from app.models.location import Location
from app.models.seed_lot import SeedLot
from app.models.sowing_event import SowingEvent
from app.models.workflow import Workflow
from app.models.workflow_stage import WorkflowStage
from app.models.workflow_version import WorkflowVersion
from app.schemas.nursery import AvailableSeedTrayRead
from app.schemas.sowing_event import CarrierTypeSummary
from app.services import asset_service, crop_batch_service, farm_service, location_service, sowing_service
from app.services.audit import append_audit_event
from app.services.errors import (
    AmbiguousSowingWorkflowError,
    BatchAlreadySownError,
    CarrierAlreadyAssignedError,
    DuplicateBatchCodeError,
    FarmNotFoundError,
    NoSowingWorkflowFoundError,
    SeedingMachineInvalidError,
    SeedingStationInvalidError,
    SeedLotNotFoundError,
    SowingCommandReusedWithDifferentPayloadError,
    SowingValidationError,
)

SEED_TRAY_CARRIER_TYPE_CODE = "seed_tray"
SEEDING_STATION_LOCATION_TYPE_CODE = "seeding_station"
SEEDING_MACHINE_ASSET_TYPE_CODE = "seeding_machine"
ACTION = "nursery.batch_sown"


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _require_active_farm(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID):
    farm = farm_service.get_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    if farm.status != "active":
        raise FarmNotFoundError(str(farm_id))
    return farm


def _compute_sow_new_batch_fingerprint(
    *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, seed_lot_id: uuid.UUID,
    seeding_station_id: uuid.UUID, seeding_machine_id: uuid.UUID | None, effective_time: datetime,
    note: str | None, trays: list[dict],
) -> str:
    sorted_trays = sorted(trays, key=lambda t: str(t["carrier_id"]))
    parts = [
        str(tenant_id), str(farm_id), str(actor_user_id), str(seed_lot_id), str(seeding_station_id),
        str(seeding_machine_id) if seeding_machine_id else "", effective_time.astimezone(timezone.utc).isoformat(),
        note or "",
    ]
    for tray in sorted_trays:
        parts.extend([str(tray["carrier_id"]), str(tray["seeds_sown"])])
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _resolve_sowing_workflow(db: Session, *, tenant_id: uuid.UUID, crop_id: uuid.UUID, variety_id: uuid.UUID) -> Workflow:
    """Auto-resolves the one active Workflow (published version, seeding-
    category start stage, required_carrier_type = seed_tray) matching this
    crop/variety -- the operator never selects a Workflow directly (see
    module docstring). Zero or multiple matches is a configuration gap,
    reported plainly rather than guessed."""
    seed_tray_type = db.execute(
        select(CarrierType).where(CarrierType.code == SEED_TRAY_CARRIER_TYPE_CODE)
    ).scalar_one()
    workflows = list(
        db.execute(
            select(Workflow)
            .join(WorkflowVersion, WorkflowVersion.workflow_id == Workflow.id)
            .join(WorkflowStage, WorkflowStage.workflow_version_id == WorkflowVersion.id)
            .where(
                Workflow.tenant_id == tenant_id, Workflow.crop_id == crop_id, Workflow.variety_id == variety_id,
                Workflow.status == "active", WorkflowVersion.state == "published",
                WorkflowStage.is_start.is_(True), WorkflowStage.stage_category == "seeding",
                WorkflowStage.required_carrier_type_id == seed_tray_type.id,
            )
            .distinct()
        ).scalars()
    )
    if len(workflows) == 0:
        raise NoSowingWorkflowFoundError(f"{crop_id}:{variety_id}")
    if len(workflows) > 1:
        raise AmbiguousSowingWorkflowError(f"{crop_id}:{variety_id}")
    return workflows[0]


def _generate_batch_code(db: Session, *, tenant_id: uuid.UUID, local_date: date) -> str:
    """Concurrency-safe, human-readable, non-user-supplied Crop Batch code:
    `CB-YYYYMMDD-NNN`, sequential per tenant per local sowing date. Reuses
    FARM-SETUP-001's own established `pg_advisory_xact_lock` technique --
    no new sequence table. Locked by TENANT alone (not farm), matching
    `ux_crop_batches_tenant_code_lower`'s actual tenant-wide (not per-farm)
    uniqueness scope -- two farms in the same tenant generating codes on
    the same date must still serialize against each other."""
    lock_key = f"{tenant_id}:batch-code:{local_date.isoformat()}"
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": lock_key})
    prefix = f"CB-{local_date.strftime('%Y%m%d')}-"
    seq = 1
    while True:
        code = f"{prefix}{seq:03d}"
        exists = db.execute(
            select(CropBatch.id).where(
                CropBatch.tenant_id == tenant_id, CropBatch.code.ilike(code)
            )
        ).first()
        if exists is None:
            return code
        seq += 1


def _validate_seeding_station(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, seeding_station_id: uuid.UUID) -> Location:
    location = db.execute(
        select(Location).where(
            Location.id == seeding_station_id, Location.tenant_id == tenant_id, Location.farm_id == farm_id
        )
    ).scalar_one_or_none()
    if location is None or location.status != "active":
        raise SeedingStationInvalidError(str(seeding_station_id))
    seeding_station_type = location_service._get_location_type_by_code(db, SEEDING_STATION_LOCATION_TYPE_CODE)
    if location.location_type_id != seeding_station_type.id:
        raise SeedingStationInvalidError(str(seeding_station_id))
    classification = location_service._resolve_governing_greenhouse_classification(
        db, tenant_id=tenant_id, farm_id=farm_id, parent=location
    )
    if classification != "nursery":
        raise SeedingStationInvalidError(str(seeding_station_id))
    return location


def _validate_seeding_machine(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, seeding_machine_id: uuid.UUID | None) -> Asset | None:
    if seeding_machine_id is None:
        return None
    try:
        asset = asset_service.get_asset(db, tenant_id=tenant_id, farm_id=farm_id, asset_id=seeding_machine_id)
    except Exception as exc:
        raise SeedingMachineInvalidError(str(seeding_machine_id)) from exc
    if asset.status != "active":
        raise SeedingMachineInvalidError(str(seeding_machine_id))
    seeding_machine_type = asset_service._get_asset_type_by_code(db, SEEDING_MACHINE_ASSET_TYPE_CODE)
    if asset.asset_type_id != seeding_machine_type.id:
        raise SeedingMachineInvalidError(str(seeding_machine_id))
    return asset


def list_available_seed_trays(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> list[AvailableSeedTrayRead]:
    """"Available for Sowing" (ticket section 16): an active `seed_tray`
    Carrier in this tenant/farm with no active Batch-Carrier-Assignment.
    Never infers physical location/occupancy -- CMP does not model where a
    reusable tray currently sits (see module docstring / SEED_SOWING_MODEL.md);
    availability here is purely "not already carrying a live crop batch"."""
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    seed_tray_type = db.execute(
        select(CarrierType).where(CarrierType.code == SEED_TRAY_CARRIER_TYPE_CODE)
    ).scalar_one()
    active_assignment_carrier_ids = select(BatchCarrierAssignment.carrier_id).where(
        BatchCarrierAssignment.tenant_id == tenant_id, BatchCarrierAssignment.released_effective_time.is_(None)
    )
    carriers = list(
        db.execute(
            select(Carrier)
            .where(
                Carrier.tenant_id == tenant_id, Carrier.farm_id == farm_id,
                Carrier.carrier_type_id == seed_tray_type.id, Carrier.status == "active",
                Carrier.id.not_in(active_assignment_carrier_ids),
            )
            .order_by(Carrier.code)
        ).scalars()
    )
    carrier_type_summary = CarrierTypeSummary(id=seed_tray_type.id, code=seed_tray_type.code, name=seed_tray_type.name)
    return [AvailableSeedTrayRead(id=c.id, code=c.code, carrier_type=carrier_type_summary) for c in carriers]


def sow_new_batch(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_command_id: uuid.UUID,
    seed_lot_id: uuid.UUID,
    seeding_station_id: uuid.UUID,
    seeding_machine_id: uuid.UUID | None,
    effective_time: datetime,
    note: str | None,
    trays: list[dict],
) -> SowingEvent:
    """The atomic NURSERY-OPS-001 Sowing command: creates exactly one Crop
    Batch and its one Sowing Event (plus tray allocations) in a single
    transaction. Trays: `[{"carrier_id": UUID, "seeds_sown": int}, ...]`."""
    farm = _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    if not trays:
        raise SowingValidationError("a sowing command requires at least one tray")
    carrier_ids_in = [t["carrier_id"] for t in trays]
    if len(carrier_ids_in) != len(set(carrier_ids_in)):
        raise SowingValidationError("duplicate carrier_id within one sowing command")

    fingerprint = _compute_sow_new_batch_fingerprint(
        tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, seed_lot_id=seed_lot_id,
        seeding_station_id=seeding_station_id, seeding_machine_id=seeding_machine_id,
        effective_time=effective_time, note=note, trays=trays,
    )

    # Transaction-scoped advisory lock, keyed on tenant+client_command_id --
    # serializes concurrent attempts sharing the same command id (mirrors
    # FARM-SETUP-001's own established pattern) so only one can ever observe
    # "no prior event" and proceed to create the Batch/SowingEvent pair.
    lock_key = f"{tenant_id}:{client_command_id}"
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": lock_key})

    existing = sowing_service._find_existing_sowing_event(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise SowingCommandReusedWithDifferentPayloadError(str(client_command_id))

    seed_lot = db.execute(
        select(SeedLot).where(SeedLot.id == seed_lot_id, SeedLot.tenant_id == tenant_id, SeedLot.farm_id == farm_id)
    ).scalar_one_or_none()
    if seed_lot is None:
        raise SeedLotNotFoundError(str(seed_lot_id))

    _validate_seeding_station(db, tenant_id=tenant_id, farm_id=farm_id, seeding_station_id=seeding_station_id)
    _validate_seeding_machine(db, tenant_id=tenant_id, farm_id=farm_id, seeding_machine_id=seeding_machine_id)

    workflow = _resolve_sowing_workflow(db, tenant_id=tenant_id, crop_id=seed_lot.crop_id, variety_id=seed_lot.variety_id)

    local_date = effective_time.astimezone(ZoneInfo(farm.timezone)).date()
    code = _generate_batch_code(db, tenant_id=tenant_id, local_date=local_date)

    # NURSERY-OPS-001.1: Seeds Sown is the only quantity the operator
    # supplies here -- "sown site/cell count" is a separate,
    # separately-observed fact this command never asks for, so it is
    # recorded as unknown (NULL), never fabricated as equal to seed_count
    # (see SEED_SOWING_MODEL.md).
    lines = [
        {
            "carrier_id": tray["carrier_id"], "seed_lot_id": seed_lot_id,
            "sown_site_count": None, "seed_count": tray["seeds_sown"], "line_note": None,
        }
        for tray in trays
    ]

    # The `pg_advisory_xact_lock` above already serializes every concurrent
    # attempt sharing this exact client_command_id, so a duplicate-command-id
    # IntegrityError here is not expected in normal operation -- handled
    # anyway as defense in depth. `ux_batch_carrier_assignments_active_carrier`
    # (section 20's concurrent-tray-claim race between two DIFFERENT
    # command ids) genuinely can fire here: `_sow_batch_core`'s own
    # `with_for_update()` carrier-row locking already catches this via a
    # clean `CarrierAlreadyAssignedError` in the ordinary case (proven in
    # test_nursery_ops_concurrency.py), so this IntegrityError branch is
    # this constraint's own backstop, not the primary mechanism.
    try:
        batch, _workflow, _version, _start_stage = crop_batch_service._create_batch_core(
            db, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, code=code,
            workflow_id=workflow.id, effective_time=effective_time,
            client_command_id=client_command_id, request_fingerprint=fingerprint,
        )
        event = sowing_service._sow_batch_core(
            db, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, batch_id=batch.id,
            client_command_id=client_command_id, effective_time=effective_time, note=note, lines=lines,
            request_fingerprint=fingerprint,
            seeding_station_id=seeding_station_id, seeding_machine_id=seeding_machine_id,
        )
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint in ("ux_crop_batches_tenant_client_command_id", "ux_sowing_events_tenant_client_command_id"):
            replay = sowing_service._find_existing_sowing_event(db, tenant_id=tenant_id, client_command_id=client_command_id)
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise SowingCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        if constraint == "ux_batch_carrier_assignments_active_carrier":
            raise CarrierAlreadyAssignedError("a tray in this command is already assigned to another active batch") from exc
        if constraint == "ux_sowing_events_batch_id":
            raise BatchAlreadySownError(str(client_command_id)) from exc
        if constraint == "ux_crop_batches_tenant_code_lower":
            raise DuplicateBatchCodeError(f"{tenant_id}:{code}") from exc
        raise
    except Exception:
        db.rollback()
        raise

    try:
        sorted_carrier_ids = sorted({t["carrier_id"] for t in trays})
        append_audit_event(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, action=ACTION,
            entity_type="sowing_event", entity_id=event.id,
            event_data={
                "sowing_event_id": str(event.id), "batch_id": str(batch.id), "batch_code": batch.code,
                "farm_id": str(farm_id), "seed_lot_id": str(seed_lot_id),
                "seeding_station_id": str(seeding_station_id),
                "seeding_machine_id": str(seeding_machine_id) if seeding_machine_id else None,
                "effective_time": effective_time.isoformat(), "client_command_id": str(client_command_id),
                "tray_count": len(sorted_carrier_ids), "carrier_ids": [str(c) for c in sorted_carrier_ids],
                "total_seeds_sown": sum(t["seeds_sown"] for t in trays),
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(event)
    return event
