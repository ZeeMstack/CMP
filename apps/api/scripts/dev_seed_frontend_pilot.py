"""Idempotent development-only seed script for the FE-001 frontend pilot
demo scenario, against the existing IMPERIAL tenant / PB-01 farm in the
`cmp` development database.

Usage (from apps/api, with the venv active):
    python scripts/dev_seed_frontend_pilot.py

Safe to rerun: every catalog/config step (workflow version, locations,
carriers, seed lot) checks for already-created pilot data first and either
reuses it exactly or stops on a conflicting definition; every operational
command (batches, sowing, transitions, transplant, split, quality holds)
uses a deterministic client_command_id derived from a fixed scenario key,
so a rerun replays each command's own exact-replay path instead of erroring
or duplicating. Every write goes through the same service layer normal
application commands use -- no raw INSERT/UPDATE/DELETE of operational
facts anywhere in this file.

Refuses to run against anything other than the `cmp` database. Creates no
cleanup/delete/reset tooling -- that is an explicitly separate, not-yet
approved task. Never touches the IMPERIAL tenant, PB-01 farm, or the
existing ICEBERG/MAMUTIK-RZ/LEAFY-PLATE/ICEBERG-MAMUTIK-v1 reference rows
beyond the *expected* side effect of publish_version retiring v1 (its own
rows are never modified).
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import app.main  # noqa: F401  forces full model registration before any ORM flush
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.settings import settings
from app.models.carrier import Carrier
from app.models.carrier_specification import CarrierSpecification
from app.models.crop_batch import CropBatch
from app.models.location import Location
from app.models.seed_lot import SeedLot
from app.models.workflow_stage import WorkflowStage
from app.models.workflow_transition import WorkflowTransition
from app.models.workflow_version import WorkflowVersion
from app.services import (
    batch_derivation_service,
    carrier_service,
    carrier_specification_service,
    crop_batch_service,
    location_service,
    movement_service,
    quality_hold_service,
    sowing_service,
    transplant_service,
    workflow_service,
)
from app.services.errors import CropBatchNotFoundError

# --- Fixed identity -----------------------------------------------------------
TENANT_ID = uuid.UUID("52348003-cdbc-4e96-a63d-31fa2d1640dc")  # IMPERIAL
FARM_ID = uuid.UUID("5b2f350c-7ea7-4b29-baf4-ad4b07d757ba")  # PB-01
ACTOR_USER_ID = uuid.UUID("165ec7d9-83fa-473f-97d3-93b89b0e8281")  # zeeshan@imperial.com
WORKFLOW_ID = uuid.UUID("9584e51a-12df-41b8-9921-46c752e0f8ec")  # ICEBERG-MAMUTIK

# Deterministic idempotency: fixed namespace, stable per-command keys, fixed
# effective_time literals (never datetime.now()) -- required so a rerun's
# fingerprint matches exactly and hits the exact-replay path.
PILOT_NAMESPACE = uuid.UUID("6f6d1f2a-6b1a-4e6a-9b1a-b16d10001111")


def cmd_id(key: str) -> uuid.UUID:
    return uuid.uuid5(PILOT_NAMESPACE, key)


def dt(y: int, m: int, d: int, hh: int = 8) -> datetime:
    return datetime(y, m, d, hh, 0, 0, tzinfo=timezone.utc)


manifest: dict = {
    "database": None,
    "tenant_id": str(TENANT_ID),
    "farm_id": str(FARM_ID),
    "run_at": None,
    "workflow_version_id": None,
    "stage_ids": {},
    "location_ids": {},
    "carrier_ids": {"seed_tray": [], "cultivation_plate": []},
    "seed_lot_id": None,
    "batch_ids": {},
    "split_event_id": None,
    "quality_hold_ids": {},
}


def fail(message: str) -> None:
    print(f"\nFATAL: {message}", file=sys.stderr)
    raise SystemExit(1)


# --- Step 1: workflow v2 -------------------------------------------------------

STAGE_DEFS = [
    # code, stage_category, required_carrier_type_code, is_start, is_terminal
    ("SOWN", "seeding", "seed_tray", True, False),
    ("GERMINATION", "germination", "seed_tray", False, False),
    ("SEEDLING", "nursery", "seed_tray", False, False),
    ("TRANSPLANTED", "transplanting", "cultivation_plate", False, False),
    ("GROWING", "production", "cultivation_plate", False, False),
    ("HARVEST_READY", "harvest_ready", "cultivation_plate", False, False),
    ("HARVESTING", "harvesting", "cultivation_plate", False, False),
    ("COMPLETED", "completed", None, False, True),
]
TRANSITION_DEFS = [
    ("SOWN", "GERMINATION"), ("GERMINATION", "SEEDLING"), ("SEEDLING", "TRANSPLANTED"),
    ("TRANSPLANTED", "GROWING"), ("GROWING", "HARVEST_READY"),
    ("HARVEST_READY", "HARVESTING"), ("HARVESTING", "COMPLETED"),
]


def get_or_create_workflow_v2(db: Session) -> tuple[uuid.UUID, dict[str, uuid.UUID]]:
    existing = db.execute(
        select(WorkflowVersion).where(
            WorkflowVersion.tenant_id == TENANT_ID,
            WorkflowVersion.workflow_id == WORKFLOW_ID,
            WorkflowVersion.version_number == 2,
        )
    ).scalar_one_or_none()

    if existing is not None:
        stages = list(db.execute(
            select(WorkflowStage).where(WorkflowStage.workflow_version_id == existing.id)
        ).scalars())
        stage_by_code = {s.code: s for s in stages}
        expected_codes = {d[0] for d in STAGE_DEFS}
        if set(stage_by_code) != expected_codes:
            fail(
                f"existing ICEBERG-MAMUTIK v2 (id={existing.id}) has stage codes "
                f"{sorted(stage_by_code)} which does not match the expected pilot set "
                f"{sorted(expected_codes)} -- refusing to mutate or replace it."
            )
        for code, category, _carrier, is_start, is_terminal in STAGE_DEFS:
            s = stage_by_code[code]
            if (s.stage_category, s.is_start, s.is_terminal) != (category, is_start, is_terminal):
                fail(f"existing stage {code} on v2 does not match expected definition -- refusing to mutate.")
        print(f"Workflow v2 already exists and matches expected shape (id={existing.id}, state={existing.state}). Reusing.")
        return existing.id, {code: s.id for code, s in stage_by_code.items()}

    print("Creating new draft workflow version 2 on ICEBERG-MAMUTIK...")
    version = workflow_service.create_draft_version(db, tenant_id=TENANT_ID, actor_user_id=ACTOR_USER_ID, workflow_id=WORKFLOW_ID)
    db.commit()

    stage_ids: dict[str, uuid.UUID] = {}
    for i, (code, category, carrier_type, is_start, is_terminal) in enumerate(STAGE_DEFS):
        stage = workflow_service.add_stage(
            db, tenant_id=TENANT_ID, actor_user_id=ACTOR_USER_ID, workflow_id=WORKFLOW_ID, version_id=version.id,
            code=code, name=code.replace("_", " ").title(), display_order=i, stage_category=category,
            expected_duration_minutes=None, permitted_location_type_code=None,
            required_carrier_type_code=carrier_type, is_start=is_start, is_terminal=is_terminal,
        )
        db.commit()
        stage_ids[code] = stage.id
        print(f"  stage {code} -> {stage.id}")

    for i, (from_code, to_code) in enumerate(TRANSITION_DEFS):
        workflow_service.add_transition(
            db, tenant_id=TENANT_ID, actor_user_id=ACTOR_USER_ID, workflow_id=WORKFLOW_ID, version_id=version.id,
            from_stage_id=stage_ids[from_code], to_stage_id=stage_ids[to_code],
            code=f"ADV-{i + 1}", name=f"{from_code} -> {to_code}",
        )
        db.commit()
        print(f"  transition {from_code} -> {to_code}")

    workflow_service.publish_version(db, tenant_id=TENANT_ID, actor_user_id=ACTOR_USER_ID, workflow_id=WORKFLOW_ID, version_id=version.id)
    db.commit()
    print(f"Published workflow v2 (id={version.id}). v1 is now retired (expected, its own rows untouched).")
    return version.id, stage_ids


def get_transition_id(db: Session, version_id: uuid.UUID, from_code: str, to_code: str, stage_ids: dict) -> uuid.UUID:
    t = db.execute(
        select(WorkflowTransition).where(
            WorkflowTransition.workflow_version_id == version_id,
            WorkflowTransition.from_stage_id == stage_ids[from_code],
            WorkflowTransition.to_stage_id == stage_ids[to_code],
        )
    ).scalar_one()
    return t.id


# --- Step 2: locations ----------------------------------------------------------

def get_location_id(db: Session, code: str, parent_id: uuid.UUID | None) -> uuid.UUID | None:
    q = select(Location).where(
        Location.tenant_id == TENANT_ID, Location.farm_id == FARM_ID, Location.code == code,
    )
    q = q.where(Location.parent_location_id == parent_id) if parent_id is not None else q.where(Location.parent_location_id.is_(None))
    row = db.execute(q).scalar_one_or_none()
    return row.id if row else None


def get_or_create_location(db: Session, *, code: str, name: str, location_type_code: str, parent_id: uuid.UUID | None, greenhouse_classification: str | None = None) -> uuid.UUID:
    existing = get_location_id(db, code, parent_id)
    if existing is not None:
        return existing
    loc = location_service.create_location(
        db, tenant_id=TENANT_ID, farm_id=FARM_ID, actor_user_id=ACTOR_USER_ID,
        location_type_code=location_type_code, code=code, name=name, parent_location_id=parent_id,
        greenhouse_classification=greenhouse_classification, occupiable=None,
    )
    db.commit()
    print(f"  location {code} ({location_type_code}) -> {loc.id}")
    return loc.id


def get_or_create_bulk_children(db: Session, *, parent_id: uuid.UUID, location_type_code: str, code_prefix: str, count: int, pad_width: int = 2) -> list[uuid.UUID]:
    existing = list(db.execute(
        select(Location).where(
            Location.tenant_id == TENANT_ID, Location.farm_id == FARM_ID,
            Location.parent_location_id == parent_id, Location.code.like(f"{code_prefix}%"),
        )
    ).scalars())
    if len(existing) >= count:
        return [loc.id for loc in existing][:count]
    if existing:
        fail(f"partial bulk-children set already exists under {parent_id} with prefix {code_prefix} ({len(existing)} of {count}) -- refusing to guess how to complete it.")
    created = location_service.bulk_generate_children(
        db, tenant_id=TENANT_ID, farm_id=FARM_ID, parent_id=parent_id, actor_user_id=ACTOR_USER_ID,
        location_type_code=location_type_code, code_prefix=code_prefix, start=1, end=count, pad_width=pad_width, name_template=None,
    )
    db.commit()
    print(f"  bulk {count}x {location_type_code} under {parent_id} (prefix {code_prefix})")
    return [loc.id for loc in created]


def get_or_create_locations(db: Session) -> dict[str, uuid.UUID]:
    L: dict[str, uuid.UUID] = {}
    print("Locations...")
    L["NURSERY"] = get_or_create_location(db, code="PILOT-NURSERY", name="Nursery", location_type_code="greenhouse", parent_id=None, greenhouse_classification="nursery")
    L["SEEDING_AREA"] = get_or_create_location(db, code="PILOT-SEED-AREA", name="Seeding Area", location_type_code="area", parent_id=L["NURSERY"])
    L["GERM_AREA"] = get_or_create_location(db, code="PILOT-GERM-AREA", name="Germination Area", location_type_code="area", parent_id=L["NURSERY"])
    L["GERM_CHAMBER"] = get_or_create_location(db, code="PILOT-GERM-CH1", name="Germination Chamber 1", location_type_code="germination_chamber", parent_id=L["GERM_AREA"])
    L["GERM_POSITIONS"] = get_or_create_bulk_children(db, parent_id=L["GERM_CHAMBER"], location_type_code="chamber_position", code_prefix="PILOT-CHP-", count=4)
    L["SEEDLING_AREA"] = get_or_create_location(db, code="PILOT-SEEDLING-AREA", name="Seedling Area", location_type_code="area", parent_id=L["NURSERY"])
    L["SEEDLING_TABLE"] = get_or_create_location(db, code="PILOT-SEEDLING-GT1", name="Seedling Grow Table 1", location_type_code="grow_table", parent_id=L["SEEDLING_AREA"])
    L["SEEDLING_POSITIONS"] = get_or_create_bulk_children(db, parent_id=L["SEEDLING_TABLE"], location_type_code="table_position", code_prefix="PILOT-STP-", count=6)

    L["GH01"] = get_or_create_location(db, code="PILOT-GH01", name="Greenhouse 01", location_type_code="greenhouse", parent_id=None, greenhouse_classification="leafy_greens")
    L["GH01_ZA"] = get_or_create_location(db, code="PILOT-GH01-ZA", name="Zone A", location_type_code="zone", parent_id=L["GH01"])
    L["GH01_ZA_SPAN"] = get_or_create_location(db, code="PILOT-GH01-ZA-SP1", name="Span 1", location_type_code="span", parent_id=L["GH01_ZA"])
    L["GH01_ZA_TABLE"] = get_or_create_location(db, code="PILOT-GH01-ZA-GT1", name="Grow Table 1", location_type_code="grow_table", parent_id=L["GH01_ZA_SPAN"])
    L["GH01_ZA_POSITIONS"] = get_or_create_bulk_children(db, parent_id=L["GH01_ZA_TABLE"], location_type_code="table_position", code_prefix="PILOT-GH01ZA-P-", count=8)
    L["GH01_ZB"] = get_or_create_location(db, code="PILOT-GH01-ZB", name="Zone B", location_type_code="zone", parent_id=L["GH01"])
    L["GH01_ZB_SPAN"] = get_or_create_location(db, code="PILOT-GH01-ZB-SP1", name="Span 1", location_type_code="span", parent_id=L["GH01_ZB"])
    L["GH01_ZB_TABLE"] = get_or_create_location(db, code="PILOT-GH01-ZB-GT1", name="Grow Table 1", location_type_code="grow_table", parent_id=L["GH01_ZB_SPAN"])
    L["GH01_ZB_POSITIONS"] = get_or_create_bulk_children(db, parent_id=L["GH01_ZB_TABLE"], location_type_code="table_position", code_prefix="PILOT-GH01ZB-P-", count=8)

    L["GH02"] = get_or_create_location(db, code="PILOT-GH02", name="Greenhouse 02", location_type_code="greenhouse", parent_id=None, greenhouse_classification="leafy_greens")
    L["GH02_ZA"] = get_or_create_location(db, code="PILOT-GH02-ZA", name="Zone A", location_type_code="zone", parent_id=L["GH02"])
    L["GH02_ZA_SPAN"] = get_or_create_location(db, code="PILOT-GH02-ZA-SP1", name="Span 1", location_type_code="span", parent_id=L["GH02_ZA"])
    L["GH02_ZA_TABLE"] = get_or_create_location(db, code="PILOT-GH02-ZA-GT1", name="Grow Table 1", location_type_code="grow_table", parent_id=L["GH02_ZA_SPAN"])
    L["GH02_ZA_POSITIONS"] = get_or_create_bulk_children(db, parent_id=L["GH02_ZA_TABLE"], location_type_code="table_position", code_prefix="PILOT-GH02ZA-P-", count=8)
    return L


# --- Step 3: carriers -----------------------------------------------------------

SEED_TRAY_COUNT = 7  # one per originally-sown batch (LOT-001..007)
CULTIVATION_PLATE_COUNT = 5  # LOT-004,005,006 (1 each) + LOT-007 (2, split into 007A/007B)


def get_or_create_seed_tray_specification(db: Session) -> uuid.UUID:
    # CARRIER-CONFIG-001A: seed_tray now requires_specification -- this
    # pilot demo scenario needs one reusable specification to register its
    # seed trays against, following the same idempotent lookup-then-create
    # pattern as every other pilot catalog/config step in this script.
    existing = db.execute(
        select(CarrierSpecification).where(
            CarrierSpecification.tenant_id == TENANT_ID,
            CarrierSpecification.code == "PILOT-SEED-TRAY-SPEC",
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing.id
    spec = carrier_specification_service.register_carrier_specification(
        db, tenant_id=TENANT_ID, actor_user_id=ACTOR_USER_ID, carrier_type_code="seed_tray",
        code="PILOT-SEED-TRAY-SPEC", name="Pilot Demo Seed Tray Specification",
        length_mm=300, width_mm=200, height_mm=50, biological_position_count=104,
    )
    db.commit()
    print(f"  seed_tray specification PILOT-SEED-TRAY-SPEC -> {spec.id}")
    return spec.id


def get_or_create_carriers(db: Session) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    print("Carriers...")
    existing_trays = list(db.execute(select(Carrier).where(Carrier.tenant_id == TENANT_ID, Carrier.farm_id == FARM_ID, Carrier.code.like("PILOT-TRAY-%")).order_by(Carrier.code)).scalars())
    if existing_trays:
        trays = [c.id for c in existing_trays]
    else:
        seed_tray_spec_id = get_or_create_seed_tray_specification(db)
        created = carrier_service.bulk_register_carriers(db, tenant_id=TENANT_ID, farm_id=FARM_ID, actor_user_id=ACTOR_USER_ID, specification_id=seed_tray_spec_id, code_prefix="PILOT-TRAY-", start=1, end=SEED_TRAY_COUNT, pad_width=2)
        db.commit()
        trays = [c.id for c in created]
        print(f"  {SEED_TRAY_COUNT}x seed_tray created")

    existing_plates = list(db.execute(select(Carrier).where(Carrier.tenant_id == TENANT_ID, Carrier.farm_id == FARM_ID, Carrier.code.like("PILOT-PLATE-%")).order_by(Carrier.code)).scalars())
    if existing_plates:
        plates = [c.id for c in existing_plates]
    else:
        created = carrier_service.bulk_register_carriers(db, tenant_id=TENANT_ID, farm_id=FARM_ID, actor_user_id=ACTOR_USER_ID, carrier_type_code="cultivation_plate", code_prefix="PILOT-PLATE-", start=1, end=CULTIVATION_PLATE_COUNT, pad_width=2)
        db.commit()
        plates = [c.id for c in created]
        print(f"  {CULTIVATION_PLATE_COUNT}x cultivation_plate created")
    return trays, plates


# --- Step 4: seed lot -------------------------------------------------------------

def get_or_create_seed_lot(db: Session, crop_id: uuid.UUID, variety_id: uuid.UUID) -> uuid.UUID:
    existing = db.execute(select(SeedLot).where(SeedLot.tenant_id == TENANT_ID, SeedLot.farm_id == FARM_ID, SeedLot.code == "PILOT-SEED-001")).scalar_one_or_none()
    if existing is not None:
        return existing.id
    lot = sowing_service.register_seed_lot(
        db, tenant_id=TENANT_ID, farm_id=FARM_ID, actor_user_id=ACTOR_USER_ID, crop_id=crop_id, variety_id=variety_id,
        code="PILOT-SEED-001", supplier_name="Rijk Zwaan (pilot placeholder)", supplier_lot_reference="RZ-PILOT-2026-01",
        received_date=date(2026, 5, 1), expiry_date=date(2027, 5, 1),
    )
    db.commit()
    print(f"Seed lot PILOT-SEED-001 -> {lot.id}")
    return lot.id


# --- Step 5: batches, sowing, transitions, transplant ---------------------------

def get_or_create_batch(db: Session, code: str, effective_time: datetime) -> uuid.UUID:
    existing = db.execute(select(CropBatch).where(CropBatch.tenant_id == TENANT_ID, CropBatch.farm_id == FARM_ID, CropBatch.code == code)).scalar_one_or_none()
    if existing is not None:
        return existing.id
    batch = crop_batch_service.create_batch(
        db, tenant_id=TENANT_ID, farm_id=FARM_ID, actor_user_id=ACTOR_USER_ID,
        client_command_id=cmd_id(f"{code}:create"), code=code, workflow_id=WORKFLOW_ID, effective_time=effective_time,
    )
    db.commit()
    print(f"  batch {code} -> {batch.id}")
    return batch.id


def ensure_sown(db: Session, *, batch_id: uuid.UUID, code: str, tray_id: uuid.UUID, seed_lot_id: uuid.UUID, effective_time: datetime) -> None:
    sowing_service.sow_batch(
        db, tenant_id=TENANT_ID, farm_id=FARM_ID, actor_user_id=ACTOR_USER_ID, batch_id=batch_id,
        client_command_id=cmd_id(f"{code}:sow"), effective_time=effective_time, note="Pilot scenario sowing.",
        lines=[{"carrier_id": tray_id, "seed_lot_id": seed_lot_id, "sown_site_count": 104, "seed_count": 104, "line_note": None}],
    )
    db.commit()
    print(f"    {code}: sown")


def ensure_transition(db: Session, *, batch_id: uuid.UUID, code: str, to_stage: str, transition_id: uuid.UUID, effective_time: datetime) -> None:
    crop_batch_service.transition_stage(
        db, tenant_id=TENANT_ID, farm_id=FARM_ID, actor_user_id=ACTOR_USER_ID, batch_id=batch_id,
        client_command_id=cmd_id(f"{code}:stage:{to_stage}"), configured_transition_id=transition_id,
        effective_time=effective_time, reason="Pilot scenario progression.",
    )
    db.commit()
    print(f"    {code}: -> {to_stage}")


def active_assignment_ids(db: Session, batch_id: uuid.UUID) -> list[uuid.UUID]:
    from app.models.batch_carrier_assignment import BatchCarrierAssignment
    rows = db.execute(
        select(BatchCarrierAssignment.id).where(
            BatchCarrierAssignment.tenant_id == TENANT_ID, BatchCarrierAssignment.batch_id == batch_id,
            BatchCarrierAssignment.released_effective_time.is_(None),
        ).order_by(BatchCarrierAssignment.id)
    ).scalars().all()
    return list(rows)


def ensure_transplant(db: Session, *, batch_id: uuid.UUID, code: str, destination_carrier_ids: list[uuid.UUID], effective_time: datetime) -> None:
    from app.models.transplant_event import TransplantEvent
    already = db.execute(select(TransplantEvent).where(TransplantEvent.tenant_id == TENANT_ID, TransplantEvent.batch_id == batch_id)).scalar_one_or_none()
    if already is not None:
        return
    source_ids = active_assignment_ids(db, batch_id)
    if len(source_ids) != 1:
        fail(f"{code}: expected exactly 1 active (seed_tray) assignment before transplant, found {len(source_ids)}")
    per_dest = 104 // len(destination_carrier_ids)
    remainder = 104 - per_dest * len(destination_carrier_ids)
    counts = [per_dest + (1 if i < remainder else 0) for i in range(len(destination_carrier_ids))]
    transplant_service.record_transplant(
        db, tenant_id=TENANT_ID, farm_id=FARM_ID, actor_user_id=ACTOR_USER_ID, batch_id=batch_id,
        client_command_id=cmd_id(f"{code}:transplant"), effective_time=effective_time, note="Pilot scenario transplant to cultivation plates.",
        source_lines=[{"source_assignment_id": source_ids[0], "source_plant_count": 104, "discarded_plant_count": 0, "note": None}],
        destination_lines=[{"destination_carrier_id": cid, "assigned_plant_count": n, "note": None} for cid, n in zip(destination_carrier_ids, counts)],
        allocations=[{"source_assignment_id": source_ids[0], "destination_carrier_id": cid, "allocated_plant_count": n} for cid, n in zip(destination_carrier_ids, counts)],
    )
    db.commit()
    print(f"    {code}: transplanted seed_tray -> {len(destination_carrier_ids)} cultivation_plate(s)")


def ensure_placement(db: Session, *, code: str, carrier_id: uuid.UUID, location_id: uuid.UUID, effective_time: datetime) -> None:
    movement_service.execute_movement(
        db, tenant_id=TENANT_ID, farm_id=FARM_ID, actor_user_id=ACTOR_USER_ID,
        client_command_id=cmd_id(f"{code}:place:{location_id}"), effective_time=effective_time,
        occupant_kind="carrier", occupant_id=carrier_id, destination_kind="location", destination_id=location_id,
        reason="Pilot scenario placement.",
    )
    db.commit()
    print(f"    {code}: placed carrier {carrier_id} into location {location_id}")


# --- Step 6: split ----------------------------------------------------------------

def ensure_split(db: Session, *, source_batch_id: uuid.UUID, source_code: str, output_codes: tuple[str, str], effective_time: datetime) -> tuple[uuid.UUID, uuid.UUID]:
    existing_a = db.execute(select(CropBatch).where(CropBatch.tenant_id == TENANT_ID, CropBatch.farm_id == FARM_ID, CropBatch.code == output_codes[0])).scalar_one_or_none()
    existing_b = db.execute(select(CropBatch).where(CropBatch.tenant_id == TENANT_ID, CropBatch.farm_id == FARM_ID, CropBatch.code == output_codes[1])).scalar_one_or_none()
    if existing_a is not None and existing_b is not None:
        return existing_a.id, existing_b.id
    if existing_a is not None or existing_b is not None:
        fail(f"split of {source_code} is partially present ({output_codes}) -- refusing to guess how to complete it.")

    aids = active_assignment_ids(db, source_batch_id)
    if len(aids) != 2:
        fail(f"{source_code}: expected exactly 2 active assignments before split, found {len(aids)}")

    event = batch_derivation_service.split_batch(
        db, tenant_id=TENANT_ID, farm_id=FARM_ID, actor_user_id=ACTOR_USER_ID, batch_id=source_batch_id,
        client_command_id=cmd_id(f"{source_code}:split"), effective_time=effective_time,
        note="Split to give each half more table space before harvest.",
        outputs=[
            {"output_batch_code": output_codes[0], "source_assignment_ids": [aids[0]]},
            {"output_batch_code": output_codes[1], "source_assignment_ids": [aids[1]]},
        ],
    )
    db.commit()
    manifest["split_event_id"] = str(event.id)
    a = db.execute(select(CropBatch).where(CropBatch.tenant_id == TENANT_ID, CropBatch.farm_id == FARM_ID, CropBatch.code == output_codes[0])).scalar_one()
    b = db.execute(select(CropBatch).where(CropBatch.tenant_id == TENANT_ID, CropBatch.farm_id == FARM_ID, CropBatch.code == output_codes[1])).scalar_one()
    print(f"    {source_code}: split -> {output_codes[0]} ({a.id}), {output_codes[1]} ({b.id})")
    return a.id, b.id


# --- Step 7: quality holds ---------------------------------------------------------

def ensure_hold_open(db: Session, *, batch_id: uuid.UUID, code: str, reason_code: str, reason_text: str, effective_time: datetime):
    from app.models.quality_hold import QualityHold
    existing = db.execute(select(QualityHold).where(QualityHold.tenant_id == TENANT_ID, QualityHold.batch_id == batch_id, QualityHold.reason_code == reason_code.strip().upper())).scalar_one_or_none()
    if existing is not None:
        return existing
    hold = quality_hold_service.place_quality_hold(
        db, tenant_id=TENANT_ID, farm_id=FARM_ID, actor_user_id=ACTOR_USER_ID, batch_id=batch_id,
        client_command_id=cmd_id(f"{code}:hold:{reason_code}"), effective_time=effective_time,
        source_observation_event_id=None, reason_code=reason_code, reason_text=reason_text,
    )
    db.commit()
    print(f"    {code}: quality hold opened ({reason_code}) -> {hold.id}")
    return hold


def ensure_hold_released(db: Session, *, batch_id: uuid.UUID, hold_id: uuid.UUID, code: str, release_reason: str, effective_time: datetime) -> None:
    from app.models.quality_hold_release import QualityHoldRelease
    already = db.execute(select(QualityHoldRelease).where(QualityHoldRelease.tenant_id == TENANT_ID, QualityHoldRelease.quality_hold_id == hold_id)).scalar_one_or_none()
    if already is not None:
        return
    quality_hold_service.release_quality_hold(
        db, tenant_id=TENANT_ID, farm_id=FARM_ID, actor_user_id=ACTOR_USER_ID, batch_id=batch_id, hold_id=hold_id,
        client_command_id=cmd_id(f"{code}:hold-release"), effective_time=effective_time, release_reason=release_reason,
    )
    db.commit()
    print(f"    {code}: quality hold released")


# --- Orchestration ------------------------------------------------------------------

def main() -> None:
    engine = create_engine(settings.database_url)
    with engine.connect() as conn:
        from sqlalchemy import text
        dbname = conn.execute(text("SELECT current_database()")).scalar()
        print(f"current_database(): {dbname}")
        if dbname == "cmp_test":
            fail("refusing to run against cmp_test -- this script is for the cmp development database only.")
        if dbname != "cmp":
            fail(f"refusing to run against {dbname!r} -- this script only ever writes to 'cmp'.")
        rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        if rev != "68215f964ca9":
            fail(f"unexpected Alembic revision {rev!r}, expected 68215f964ca9.")
        t = conn.execute(text("SELECT id, code, name FROM tenants WHERE id=:t"), {"t": str(TENANT_ID)}).fetchone()
        f = conn.execute(text("SELECT id, code FROM farms WHERE id=:f"), {"f": str(FARM_ID)}).fetchone()
        if t is None or t.code != "IMPERIAL":
            fail("IMPERIAL tenant ID does not match expected value.")
        if f is None or f.code != "PB-01":
            fail("PB-01 farm ID does not match expected value.")
        pre_batches = conn.execute(text("SELECT count(*) FROM crop_batches WHERE tenant_id=:t"), {"t": str(TENANT_ID)}).scalar()
        pre_locations = conn.execute(text("SELECT count(*) FROM locations WHERE tenant_id=:t"), {"t": str(TENANT_ID)}).scalar()
        pre_audit = conn.execute(text("SELECT count(*) FROM audit_events WHERE tenant_id=:t"), {"t": str(TENANT_ID)}).scalar()
        print(f"Pre-seed counts: crop_batches={pre_batches}, locations={pre_locations}, audit_events={pre_audit}")
    manifest["database"] = dbname
    manifest["run_at"] = datetime.now(timezone.utc).isoformat()

    session = Session(bind=engine.connect())
    try:
        version_id, stage_ids = get_or_create_workflow_v2(session)
        manifest["workflow_version_id"] = str(version_id)
        manifest["stage_ids"] = {k: str(v) for k, v in stage_ids.items()}

        locations = get_or_create_locations(session)
        manifest["location_ids"] = {
            k: (str(v) if isinstance(v, uuid.UUID) else [str(x) for x in v]) for k, v in locations.items()
        }

        trays, plates = get_or_create_carriers(session)
        manifest["carrier_ids"]["seed_tray"] = [str(c) for c in trays]
        manifest["carrier_ids"]["cultivation_plate"] = [str(c) for c in plates]

        from app.models.crop import Crop
        from app.models.variety import Variety
        crop_id = session.execute(select(Crop.id).where(Crop.tenant_id == TENANT_ID, Crop.code == "ICEBERG")).scalar_one()
        variety_id = session.execute(select(Variety.id).where(Variety.tenant_id == TENANT_ID, Variety.code == "MAMUTIK-RZ")).scalar_one()
        seed_lot_id = get_or_create_seed_lot(session, crop_id, variety_id)
        manifest["seed_lot_id"] = str(seed_lot_id)

        print("Batches...")
        batch_ids: dict[str, uuid.UUID] = {}

        def T(code: str, from_s: str, to_s: str) -> uuid.UUID:
            return get_transition_id(session, version_id, from_s, to_s, stage_ids)

        # LOT-001: SOWN only.
        b = get_or_create_batch(session, "PILOT-LOT-001", dt(2026, 7, 20))
        ensure_sown(session, batch_id=b, code="PILOT-LOT-001", tray_id=trays[0], seed_lot_id=seed_lot_id, effective_time=dt(2026, 7, 20))
        batch_ids["PILOT-LOT-001"] = b

        # LOT-002: -> GERMINATION.
        b = get_or_create_batch(session, "PILOT-LOT-002", dt(2026, 7, 13))
        ensure_sown(session, batch_id=b, code="PILOT-LOT-002", tray_id=trays[1], seed_lot_id=seed_lot_id, effective_time=dt(2026, 7, 13))
        ensure_transition(session, batch_id=b, code="PILOT-LOT-002", to_stage="GERMINATION", transition_id=T("2", "SOWN", "GERMINATION"), effective_time=dt(2026, 7, 18))
        batch_ids["PILOT-LOT-002"] = b

        # LOT-003: -> SEEDLING.
        b = get_or_create_batch(session, "PILOT-LOT-003", dt(2026, 7, 6))
        ensure_sown(session, batch_id=b, code="PILOT-LOT-003", tray_id=trays[2], seed_lot_id=seed_lot_id, effective_time=dt(2026, 7, 6))
        ensure_transition(session, batch_id=b, code="PILOT-LOT-003", to_stage="GERMINATION", transition_id=T("3", "SOWN", "GERMINATION"), effective_time=dt(2026, 7, 11))
        ensure_transition(session, batch_id=b, code="PILOT-LOT-003", to_stage="SEEDLING", transition_id=T("3", "GERMINATION", "SEEDLING"), effective_time=dt(2026, 7, 16))
        batch_ids["PILOT-LOT-003"] = b

        # LOT-004: -> TRANSPLANTED, with a released historical quality hold along the way.
        b = get_or_create_batch(session, "PILOT-LOT-004", dt(2026, 6, 29))
        ensure_sown(session, batch_id=b, code="PILOT-LOT-004", tray_id=trays[3], seed_lot_id=seed_lot_id, effective_time=dt(2026, 6, 29))
        ensure_transition(session, batch_id=b, code="PILOT-LOT-004", to_stage="GERMINATION", transition_id=T("4", "SOWN", "GERMINATION"), effective_time=dt(2026, 7, 4))
        ensure_transition(session, batch_id=b, code="PILOT-LOT-004", to_stage="SEEDLING", transition_id=T("4", "GERMINATION", "SEEDLING"), effective_time=dt(2026, 7, 9))
        hold4 = ensure_hold_open(session, batch_id=b, code="PILOT-LOT-004",
            reason_code="PEST_SIGHTING", reason_text="Minor pest sighting identified during routine scouting; treated promptly.",
            effective_time=dt(2026, 7, 10))
        ensure_hold_released(session, batch_id=b, hold_id=hold4.id, code="PILOT-LOT-004",
            release_reason="Re-inspection confirmed the batch is clear; hold released.", effective_time=dt(2026, 7, 12))
        ensure_transition(session, batch_id=b, code="PILOT-LOT-004", to_stage="TRANSPLANTED", transition_id=T("4", "SEEDLING", "TRANSPLANTED"), effective_time=dt(2026, 7, 14))
        ensure_transplant(session, batch_id=b, code="PILOT-LOT-004", destination_carrier_ids=[plates[0]], effective_time=dt(2026, 7, 14))
        batch_ids["PILOT-LOT-004"] = b
        manifest["quality_hold_ids"]["PILOT-LOT-004"] = str(hold4.id)

        # LOT-005: -> GROWING, placed into a real location.
        b = get_or_create_batch(session, "PILOT-LOT-005", dt(2026, 6, 15))
        ensure_sown(session, batch_id=b, code="PILOT-LOT-005", tray_id=trays[4], seed_lot_id=seed_lot_id, effective_time=dt(2026, 6, 15))
        ensure_transition(session, batch_id=b, code="PILOT-LOT-005", to_stage="GERMINATION", transition_id=T("5", "SOWN", "GERMINATION"), effective_time=dt(2026, 6, 20))
        ensure_transition(session, batch_id=b, code="PILOT-LOT-005", to_stage="SEEDLING", transition_id=T("5", "GERMINATION", "SEEDLING"), effective_time=dt(2026, 6, 25))
        ensure_transition(session, batch_id=b, code="PILOT-LOT-005", to_stage="TRANSPLANTED", transition_id=T("5", "SEEDLING", "TRANSPLANTED"), effective_time=dt(2026, 6, 30))
        ensure_transplant(session, batch_id=b, code="PILOT-LOT-005", destination_carrier_ids=[plates[1]], effective_time=dt(2026, 6, 30))
        ensure_transition(session, batch_id=b, code="PILOT-LOT-005", to_stage="GROWING", transition_id=T("5", "TRANSPLANTED", "GROWING"), effective_time=dt(2026, 7, 14))
        ensure_placement(session, code="PILOT-LOT-005", carrier_id=plates[1], location_id=locations["GH01_ZA_POSITIONS"][0], effective_time=dt(2026, 7, 15))
        batch_ids["PILOT-LOT-005"] = b

        # LOT-006: -> GROWING, with an OPEN quality hold (explains why it hasn't advanced).
        b = get_or_create_batch(session, "PILOT-LOT-006", dt(2026, 6, 8))
        ensure_sown(session, batch_id=b, code="PILOT-LOT-006", tray_id=trays[5], seed_lot_id=seed_lot_id, effective_time=dt(2026, 6, 8))
        ensure_transition(session, batch_id=b, code="PILOT-LOT-006", to_stage="GERMINATION", transition_id=T("6", "SOWN", "GERMINATION"), effective_time=dt(2026, 6, 13))
        ensure_transition(session, batch_id=b, code="PILOT-LOT-006", to_stage="SEEDLING", transition_id=T("6", "GERMINATION", "SEEDLING"), effective_time=dt(2026, 6, 18))
        ensure_transition(session, batch_id=b, code="PILOT-LOT-006", to_stage="TRANSPLANTED", transition_id=T("6", "SEEDLING", "TRANSPLANTED"), effective_time=dt(2026, 6, 23))
        ensure_transplant(session, batch_id=b, code="PILOT-LOT-006", destination_carrier_ids=[plates[2]], effective_time=dt(2026, 6, 23))
        ensure_transition(session, batch_id=b, code="PILOT-LOT-006", to_stage="GROWING", transition_id=T("6", "TRANSPLANTED", "GROWING"), effective_time=dt(2026, 7, 7))
        ensure_placement(session, code="PILOT-LOT-006", carrier_id=plates[2], location_id=locations["GH01_ZB_POSITIONS"][0], effective_time=dt(2026, 7, 8))
        hold6 = ensure_hold_open(session, batch_id=b, code="PILOT-LOT-006",
            reason_code="NUTRIENT_DEFICIENCY", reason_text="Suspected nutrient deficiency -- lower-leaf yellowing observed, pending agronomist review.",
            effective_time=dt(2026, 7, 25))
        batch_ids["PILOT-LOT-006"] = b
        manifest["quality_hold_ids"]["PILOT-LOT-006"] = str(hold6.id)

        # LOT-007: -> HARVEST_READY, then split into 007A/007B (two plates from one tray).
        b = get_or_create_batch(session, "PILOT-LOT-007", dt(2026, 5, 18))
        ensure_sown(session, batch_id=b, code="PILOT-LOT-007", tray_id=trays[6], seed_lot_id=seed_lot_id, effective_time=dt(2026, 5, 18))
        ensure_transition(session, batch_id=b, code="PILOT-LOT-007", to_stage="GERMINATION", transition_id=T("7", "SOWN", "GERMINATION"), effective_time=dt(2026, 5, 23))
        ensure_transition(session, batch_id=b, code="PILOT-LOT-007", to_stage="SEEDLING", transition_id=T("7", "GERMINATION", "SEEDLING"), effective_time=dt(2026, 5, 28))
        ensure_transition(session, batch_id=b, code="PILOT-LOT-007", to_stage="TRANSPLANTED", transition_id=T("7", "SEEDLING", "TRANSPLANTED"), effective_time=dt(2026, 6, 2))
        ensure_transplant(session, batch_id=b, code="PILOT-LOT-007", destination_carrier_ids=[plates[3], plates[4]], effective_time=dt(2026, 6, 2))
        ensure_transition(session, batch_id=b, code="PILOT-LOT-007", to_stage="GROWING", transition_id=T("7", "TRANSPLANTED", "GROWING"), effective_time=dt(2026, 6, 16))
        ensure_placement(session, code="PILOT-LOT-007", carrier_id=plates[3], location_id=locations["GH02_ZA_POSITIONS"][0], effective_time=dt(2026, 6, 17))
        ensure_placement(session, code="PILOT-LOT-007", carrier_id=plates[4], location_id=locations["GH02_ZA_POSITIONS"][1], effective_time=dt(2026, 6, 17))
        ensure_transition(session, batch_id=b, code="PILOT-LOT-007", to_stage="HARVEST_READY", transition_id=T("7", "GROWING", "HARVEST_READY"), effective_time=dt(2026, 7, 14))
        batch_ids["PILOT-LOT-007"] = b
        a_id, b_id = ensure_split(session, source_batch_id=b, source_code="PILOT-LOT-007", output_codes=("PILOT-LOT-007A", "PILOT-LOT-007B"), effective_time=dt(2026, 7, 28))
        batch_ids["PILOT-LOT-007A"] = a_id
        batch_ids["PILOT-LOT-007B"] = b_id

        manifest["batch_ids"] = {k: str(v) for k, v in batch_ids.items()}

        with engine.connect() as conn2:
            from sqlalchemy import text as _text
            post_batches = conn2.execute(_text("SELECT count(*) FROM crop_batches WHERE tenant_id=:t"), {"t": str(TENANT_ID)}).scalar()
            post_locations = conn2.execute(_text("SELECT count(*) FROM locations WHERE tenant_id=:t"), {"t": str(TENANT_ID)}).scalar()
            post_audit = conn2.execute(_text("SELECT count(*) FROM audit_events WHERE tenant_id=:t"), {"t": str(TENANT_ID)}).scalar()
        print(f"\nPost-seed counts: crop_batches={post_batches} (was {pre_batches}), locations={post_locations} (was {pre_locations}), audit_events={post_audit} (was {pre_audit})")

        manifest_path = Path(__file__).parent / ".pilot_seed_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
        print(f"\nManifest written to {manifest_path}")
        print("\nDone.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
