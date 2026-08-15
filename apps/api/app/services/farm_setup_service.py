"""FARM-SETUP-001: physical farm setup orchestration.

A single Farm Setup command creates a Greenhouse plus its entire requested
physical structure (locations, and for Nursery optionally assets) in ONE
database transaction, committed exactly once -- never many independent
per-node commits that could leave a half-created setup if a later step
fails. This is achieved by calling the `_*_core` variants of
`location_service`/`asset_service` (validate+insert+flush, no commit, no
audit) directly, and writing exactly one audit event plus one commit here,
at the very end.

Idempotency reuses the existing `audit_events` table -- no new schema.
The single audit event this service writes carries `client_command_id` and
a `request_fingerprint` in its `event_data`; an exact replay is detected by
looking up a prior event with the same `client_command_id` (scoped to this
tenant and this action) and, if its fingerprint matches, returning the
already-created result instead of attempting to create a second
Greenhouse. A same-id-different-payload retry is rejected explicitly
(mirrors `movement_service`'s established `client_command_id` pattern).

Reuses the authoritative `location_service`/`asset_service` validation
(hierarchy rules, capacity, code uniqueness) verbatim -- this module
contains zero topology/capacity validation logic of its own.
"""
import hashlib
import uuid
from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from app.models.location import Location
from app.services import asset_service, location_service
from app.services.audit import append_audit_event
from app.schemas.farm_setup import (
    GreenhouseOverviewItem,
    GreenhouseSetupCounts,
    GreenhouseSetupCreate,
    GreenhouseSetupResult,
    GreenhouseStructureRead,
    LeafySetupConfig,
    NurserySetupConfig,
    StructureGerminationChamberNode,
    StructureGutterNode,
    StructureNurseryTableGroup,
    StructureSectionNode,
    StructureSpanNode,
    StructureTableNode,
    StructureVinesSpanNode,
    StructureVinesZoneNode,
    StructureZoneNode,
    VinesSetupConfig,
)
from app.services.errors import (
    FarmNotFoundError,
    FarmSetupCommandReusedWithDifferentPayloadError,
    LocationNotFoundError,
)

ACTION = "farm_setup.greenhouse_created"


def _compute_fingerprint(payload: GreenhouseSetupCreate) -> str:
    # model_dump_json() is stable for a fixed Pydantic schema (field order
    # is declaration order, not insertion order) -- exclude
    # client_command_id itself so the fingerprint reflects only the
    # structural request content, matching movement_service's own
    # fingerprint/client_command_id separation.
    body = payload.model_dump_json(exclude={"client_command_id"})
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _find_existing_setup(db: Session, *, tenant_id: uuid.UUID, client_command_id: uuid.UUID) -> dict | None:
    row = db.execute(
        text(
            """
            SELECT entity_id, event_data FROM audit_events
            WHERE tenant_id = :tid AND action = :action
              AND event_data->>'client_command_id' = :ccid
            ORDER BY recorded_time DESC LIMIT 1
            """
        ),
        {"tid": tenant_id, "action": ACTION, "ccid": str(client_command_id)},
    ).mappings().first()
    return dict(row) if row is not None else None


def _result_from_prior_event(row: dict) -> GreenhouseSetupResult:
    event_data = row["event_data"]
    return GreenhouseSetupResult(
        greenhouse_id=row["entity_id"],
        code=event_data["code"],
        name=event_data["name"],
        classification=event_data["classification"],
        counts=GreenhouseSetupCounts(**event_data["counts"]),
    )


def _create_leafy_structure(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, greenhouse: Location,
    config: LeafySetupConfig, counts: GreenhouseSetupCounts,
) -> None:
    for zone_cfg in config.zones:
        zone = location_service._create_location_core(
            db, tenant_id=tenant_id, farm_id=farm_id, location_type_code="zone",
            code=zone_cfg.code, name=f"Zone {zone_cfg.code}", parent_location_id=greenhouse.id,
            greenhouse_classification=None, occupiable=None, capacity=None,
        )
        counts.zones += 1
        for span_cfg in zone_cfg.spans:
            span = location_service._create_location_core(
                db, tenant_id=tenant_id, farm_id=farm_id, location_type_code="span",
                code=span_cfg.code, name=f"Span {span_cfg.code}", parent_location_id=zone.id,
                greenhouse_classification=None, occupiable=None, capacity=None,
            )
            counts.spans += 1
            tables_cfg = span_cfg.tables
            tables = location_service._bulk_generate_children_core(
                db, tenant_id=tenant_id, farm_id=farm_id, parent_id=span.id,
                location_type_code="grow_table", code_prefix=tables_cfg.code_prefix,
                start=tables_cfg.start, end=tables_cfg.end, pad_width=tables_cfg.pad_width,
                name_template=None, capacity=tables_cfg.capacity,
                # grow_table.default_occupiable is False (purely structural
                # until a real instance is deliberately made the Leafy
                # occupiable leaf) -- see location_service's own docstring.
                occupiable=True,
            )
            counts.tables += len(tables)


def _create_vines_structure(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, greenhouse: Location,
    config: VinesSetupConfig, counts: GreenhouseSetupCounts,
) -> None:
    for zone_cfg in config.zones:
        zone = location_service._create_location_core(
            db, tenant_id=tenant_id, farm_id=farm_id, location_type_code="zone",
            code=zone_cfg.code, name=f"Zone {zone_cfg.code}", parent_location_id=greenhouse.id,
            greenhouse_classification=None, occupiable=None, capacity=None,
        )
        counts.zones += 1
        for span_cfg in zone_cfg.spans:
            span = location_service._create_location_core(
                db, tenant_id=tenant_id, farm_id=farm_id, location_type_code="span",
                code=span_cfg.code, name=f"Span {span_cfg.code}", parent_location_id=zone.id,
                greenhouse_classification=None, occupiable=None, capacity=None,
            )
            counts.spans += 1
            gutters_cfg = span_cfg.gutters
            gutters = location_service._bulk_generate_children_core(
                db, tenant_id=tenant_id, farm_id=farm_id, parent_id=span.id,
                location_type_code="grow_gutter", code_prefix=gutters_cfg.code_prefix,
                start=gutters_cfg.start, end=gutters_cfg.end, pad_width=gutters_cfg.pad_width,
                name_template=None, capacity=None,
                # grow_gutter is a purely structural node (grow_bag_position
                # is the occupiable leaf) -- its own type default
                # (non-occupiable) is correct and left unchanged.
            )
            counts.gutters += len(gutters)
            for gutter in gutters:
                bag_positions = location_service._bulk_generate_children_core(
                    db, tenant_id=tenant_id, farm_id=farm_id, parent_id=gutter.id,
                    location_type_code="grow_bag_position", code_prefix=gutters_cfg.bag_position_code_prefix,
                    start=1, end=gutters_cfg.bag_positions_per_gutter, pad_width=gutters_cfg.bag_position_pad_width,
                    name_template=None,
                    # Grow Bag Position is a true exclusive physical
                    # position -- capacity is never accepted from the
                    # setup request (GutterGeneratorConfig has no capacity
                    # field at all); NULL here means the correct,
                    # unconfigurable effective capacity of 1.
                    capacity=None,
                    # grow_bag_position.default_occupiable is already True.
                    occupiable=None,
                )
                counts.bag_positions += len(bag_positions)


def _create_nursery_structure(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, greenhouse: Location,
    config: NurserySetupConfig, counts: GreenhouseSetupCounts,
) -> None:
    if config.seeding_station is not None:
        location_service._create_location_core(
            db, tenant_id=tenant_id, farm_id=farm_id, location_type_code="seeding_station",
            code=config.seeding_station.code, name=config.seeding_station.name or "Seeding Station",
            parent_location_id=greenhouse.id, greenhouse_classification=None, occupiable=None, capacity=None,
        )
        counts.seeding_stations = 1

    if config.germination_chamber is not None:
        # NURSERY-OPS-002A: the frozen authoritative model -- a Germination
        # Trolley Asset occupies the Chamber directly (no chamber_position
        # child locations are ever generated here). `occupiable=True` is an
        # explicit override, since germination_chamber's own
        # `LocationType.default_occupiable` stays `false` (mirrors the same
        # override pattern already used for leafy `grow_table`).
        location_service._create_location_core(
            db, tenant_id=tenant_id, farm_id=farm_id, location_type_code="germination_chamber",
            code=config.germination_chamber.code, name=config.germination_chamber.name or "Germination Chamber",
            parent_location_id=greenhouse.id, greenhouse_classification=None, occupiable=True,
            capacity=config.germination_chamber.trolley_capacity,
        )
        counts.germination_chambers = 1

    groups = (
        ("seedling_area", "seedling_table", config.seedling_tables, "seedling_tables"),
        ("intersalads", "intersalads_table", config.intersalads_tables, "intersalads_tables"),
        ("intervines", "intervines_table", config.intervines_tables, "intervines_tables"),
    )
    for area_type_code, table_type_code, table_cfg, count_field in groups:
        if table_cfg is None:
            continue
        area = location_service._create_location_core(
            db, tenant_id=tenant_id, farm_id=farm_id, location_type_code=area_type_code,
            code=f"{greenhouse.code}-{area_type_code.upper()}", name=area_type_code.replace("_", " ").title(),
            parent_location_id=greenhouse.id, greenhouse_classification=None, occupiable=None, capacity=None,
        )
        tables = location_service._bulk_generate_children_core(
            db, tenant_id=tenant_id, farm_id=farm_id, parent_id=area.id,
            location_type_code=table_type_code, code_prefix=table_cfg.code_prefix,
            start=table_cfg.start, end=table_cfg.end, pad_width=table_cfg.pad_width,
            name_template=None, capacity=table_cfg.capacity,
            # seedling_table/intersalads_table/intervines_table are already
            # default_occupiable=True -- no override needed.
            occupiable=None,
        )
        setattr(counts, count_field, len(tables))

    for trolley_cfg in config.trolleys:
        trolley = asset_service._register_asset_core(
            db, tenant_id=tenant_id, farm_id=farm_id, asset_type_code="germination_trolley",
            code=trolley_cfg.code, name=trolley_cfg.name or f"Trolley {trolley_cfg.code}", commissioned_date=None,
        )
        levels_cfg = trolley_cfg.levels
        _asset_type, positions = asset_service._generate_positions_core(
            db, tenant_id=tenant_id, farm_id=farm_id, asset_id=trolley.id,
            shelf_count=levels_cfg.shelf_count, slots_per_shelf=levels_cfg.slots_per_shelf,
            shelf_prefix=levels_cfg.shelf_prefix, slot_prefix=levels_cfg.slot_prefix,
            shelf_pad_width=levels_cfg.shelf_pad_width, slot_pad_width=levels_cfg.slot_pad_width,
            shelf_capacity=None, slot_capacity=levels_cfg.slot_capacity,
        )
        counts.trolleys += 1
        counts.trolley_levels += levels_cfg.shelf_count
        counts.trolley_slots += levels_cfg.shelf_count * levels_cfg.slots_per_shelf

    for machine_cfg in config.seeding_machines:
        asset_service._register_asset_core(
            db, tenant_id=tenant_id, farm_id=farm_id, asset_type_code="seeding_machine",
            code=machine_cfg.code, name=machine_cfg.name or f"Seeding Machine {machine_cfg.code}",
            commissioned_date=None,
        )
        counts.seeding_machines += 1


def create_greenhouse_setup(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID | None,
    payload: GreenhouseSetupCreate,
) -> GreenhouseSetupResult:
    fingerprint = _compute_fingerprint(payload)

    # Transaction-scoped advisory lock, keyed on tenant+client_command_id --
    # serializes concurrent attempts that share the same command id so only
    # one can ever observe "no prior event" and proceed to create the
    # Greenhouse tree. Auto-released at commit/rollback; reuses a native
    # Postgres primitive instead of adding a new table/column.
    lock_key = f"{tenant_id}:{payload.client_command_id}"
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": lock_key})

    existing = _find_existing_setup(db, tenant_id=tenant_id, client_command_id=payload.client_command_id)
    if existing is not None:
        if existing["event_data"].get("request_fingerprint") == fingerprint:
            return _result_from_prior_event(existing)
        raise FarmSetupCommandReusedWithDifferentPayloadError(str(payload.client_command_id))

    try:
        greenhouse = location_service._create_location_core(
            db, tenant_id=tenant_id, farm_id=farm_id, location_type_code="greenhouse",
            code=payload.code, name=payload.name, parent_location_id=None,
            greenhouse_classification=payload.classification, occupiable=None, capacity=None,
        )

        counts = GreenhouseSetupCounts()
        if payload.classification == "nursery":
            _create_nursery_structure(
                db, tenant_id=tenant_id, farm_id=farm_id, greenhouse=greenhouse,
                config=payload.nursery, counts=counts,
            )
        elif payload.classification == "leafy_greens":
            _create_leafy_structure(
                db, tenant_id=tenant_id, farm_id=farm_id, greenhouse=greenhouse,
                config=payload.leafy, counts=counts,
            )
        else:
            _create_vines_structure(
                db, tenant_id=tenant_id, farm_id=farm_id, greenhouse=greenhouse,
                config=payload.vines, counts=counts,
            )
    except Exception:
        # Defensive backstop: every `_*_core` call already rolls back on
        # its own IntegrityError, but any other exception (a validation
        # error raised by this module, an unexpected failure) must still
        # guarantee nothing partial survives -- no new Greenhouse, no
        # partial Zones/Spans/Tables/Gutters/Bag Positions/assets.
        db.rollback()
        raise

    append_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action=ACTION,
        entity_type="location",
        entity_id=greenhouse.id,
        event_data={
            "client_command_id": str(payload.client_command_id),
            "request_fingerprint": fingerprint,
            "farm_id": str(farm_id),
            "code": greenhouse.code,
            "name": greenhouse.name,
            "classification": greenhouse.greenhouse_classification,
            "counts": counts.model_dump(),
            "includes_assets": counts.trolleys > 0 or counts.seeding_machines > 0,
        },
    )
    db.commit()
    db.refresh(greenhouse)
    return GreenhouseSetupResult(
        greenhouse_id=greenhouse.id, code=greenhouse.code, name=greenhouse.name,
        classification=greenhouse.greenhouse_classification, counts=counts,
    )


# =====================================================================
# Read side: Greenhouse overview + existing-structure view.
#
# Both load every location row for the farm in ONE query (mirroring
# `operational_read_service.get_location_subtree_occupancy`'s own
# established "load the scope once, aggregate in Python" convention) --
# never one query per greenhouse/zone/span, regardless of how many
# Greenhouses or how deep/wide any one of them is.
# =====================================================================


def _require_active_farm_read(conn: Connection, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> None:
    row = conn.execute(
        text("SELECT status FROM farms WHERE id = :fid AND tenant_id = :tid"),
        {"fid": farm_id, "tid": tenant_id},
    ).scalar_one_or_none()
    if row is None or row != "active":
        raise FarmNotFoundError(str(farm_id))


def _load_farm_locations(conn: Connection, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> list[dict]:
    rows = conn.execute(
        text(
            """
            SELECT l.id, l.parent_location_id, l.code, l.name, l.capacity, l.greenhouse_classification,
                   lt.code AS type_code
            FROM locations l
            JOIN location_types lt ON lt.id = l.location_type_id
            WHERE l.tenant_id = :tid AND l.farm_id = :fid
            """
        ),
        {"tid": tenant_id, "fid": farm_id},
    ).mappings().all()
    return [dict(r) for r in rows]


def _derive_status(*, classification: str, counts: GreenhouseSetupCounts) -> str:
    # FARM-SETUP-001.2: Nursery "configured" means the COMPLETE physical
    # Nursery structure is present -- ALL FIVE of Seeding Station,
    # Germination Chamber, Seedling tables, InterSalads tables, InterVines
    # tables, not merely one. Any real component present but not all five
    # is "partial" -- a Nursery with only a Seeding Station, for example,
    # must never read as fully configured. Trolleys/seeding machines are
    # EXCLUDED from both `configured` and `any_descendant` for Nursery --
    # they are farm-level equipment registered alongside the command, not
    # Nursery-owned Locations, so they must never influence this
    # greenhouse's own structural completion status at all (a Nursery with
    # a Trolley but zero structural sections is "empty", not "partial" --
    # see FARM-SETUP-001.1's Trolley/Seeding Machine review).
    if classification == "nursery":
        components = [
            counts.seeding_stations > 0, counts.germination_chambers > 0,
            counts.seedling_tables > 0, counts.intersalads_tables > 0, counts.intervines_tables > 0,
        ]
        configured = all(components)
        any_descendant = any(components)
    elif classification == "leafy_greens":
        configured = counts.tables > 0
        any_descendant = any([counts.zones, counts.spans, counts.tables])
    else:
        configured = counts.bag_positions > 0
        any_descendant = any([counts.zones, counts.spans, counts.gutters, counts.bag_positions])

    if configured:
        return "configured"
    if any_descendant:
        return "partial"
    return "empty"


def get_greenhouse_setup_overview(
    conn: Connection, *, tenant_id: uuid.UUID, farm_id: uuid.UUID
) -> list[GreenhouseOverviewItem]:
    _require_active_farm_read(conn, tenant_id=tenant_id, farm_id=farm_id)
    all_rows = _load_farm_locations(conn, tenant_id=tenant_id, farm_id=farm_id)

    children_of: dict[uuid.UUID, list[dict]] = defaultdict(list)
    for r in all_rows:
        if r["parent_location_id"] is not None:
            children_of[r["parent_location_id"]].append(r)

    greenhouses = [r for r in all_rows if r["type_code"] == "greenhouse"]

    # Nursery asset counts (trolleys/seeding machines) belong to the farm,
    # not to any Location parent -- loaded once, matched by type only
    # (assets are not per-greenhouse in this schema; every active asset of
    # the relevant type in the farm is attributed to every Nursery
    # greenhouse's overview, since Farm Setup does not model a
    # greenhouse-asset ownership link). Kept out of the overview counts to
    # avoid a misleading per-greenhouse attribution -- see structure view
    # for a single greenhouse's own detail instead.

    items: list[GreenhouseOverviewItem] = []
    for gh in sorted(greenhouses, key=lambda r: r["code"].lower()):
        counts = GreenhouseSetupCounts()

        def walk(node_id: uuid.UUID) -> None:
            for child in children_of.get(node_id, ()):
                type_code = child["type_code"]
                if type_code == "zone":
                    counts.zones += 1
                elif type_code == "span":
                    counts.spans += 1
                elif type_code == "grow_table":
                    counts.tables += 1
                elif type_code == "grow_gutter":
                    counts.gutters += 1
                elif type_code == "grow_bag_position":
                    counts.bag_positions += 1
                elif type_code == "seeding_station":
                    counts.seeding_stations += 1
                elif type_code == "germination_chamber":
                    counts.germination_chambers += 1
                elif type_code == "seedling_table":
                    counts.seedling_tables += 1
                elif type_code == "intersalads_table":
                    counts.intersalads_tables += 1
                elif type_code == "intervines_table":
                    counts.intervines_tables += 1
                walk(child["id"])

        walk(gh["id"])
        classification = gh["greenhouse_classification"]
        items.append(
            GreenhouseOverviewItem(
                greenhouse_id=gh["id"], code=gh["code"], name=gh["name"], classification=classification,
                status=_derive_status(classification=classification, counts=counts), counts=counts,
            )
        )
    return items


def _load_greenhouse_subtree_locations(
    conn: Connection, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, greenhouse_id: uuid.UUID
) -> list[dict]:
    """Bounded-by-root, like `operational_read_service.get_location_
    subtree_occupancy`'s own query -- the one Greenhouse's own subtree
    only, never every other Greenhouse's locations in the farm too. A farm
    with several large greenhouses would otherwise pay for all of them on
    every single-greenhouse structure view."""
    rows = conn.execute(
        text(
            """
            WITH RECURSIVE subtree AS (
                SELECT l.id, l.parent_location_id, l.code, l.name, l.capacity, l.greenhouse_classification,
                       lt.code AS type_code
                FROM locations l
                JOIN location_types lt ON lt.id = l.location_type_id
                WHERE l.id = :gid AND l.tenant_id = :tid AND l.farm_id = :fid
                UNION ALL
                SELECT l.id, l.parent_location_id, l.code, l.name, l.capacity, l.greenhouse_classification,
                       lt.code AS type_code
                FROM locations l
                JOIN location_types lt ON lt.id = l.location_type_id
                JOIN subtree s ON l.parent_location_id = s.id
                WHERE l.tenant_id = :tid AND l.farm_id = :fid
            )
            SELECT * FROM subtree
            """
        ),
        {"gid": greenhouse_id, "tid": tenant_id, "fid": farm_id},
    ).mappings().all()
    return [dict(r) for r in rows]


def get_greenhouse_structure(
    conn: Connection, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, greenhouse_id: uuid.UUID
) -> GreenhouseStructureRead:
    _require_active_farm_read(conn, tenant_id=tenant_id, farm_id=farm_id)
    all_rows = _load_greenhouse_subtree_locations(conn, tenant_id=tenant_id, farm_id=farm_id, greenhouse_id=greenhouse_id)

    by_id = {r["id"]: r for r in all_rows}
    children_of: dict[uuid.UUID, list[dict]] = defaultdict(list)
    for r in all_rows:
        if r["parent_location_id"] is not None:
            children_of[r["parent_location_id"]].append(r)

    greenhouse = by_id.get(greenhouse_id)
    if greenhouse is None or greenhouse["type_code"] != "greenhouse":
        raise LocationNotFoundError(str(greenhouse_id))
    classification = greenhouse["greenhouse_classification"]

    result = GreenhouseStructureRead(
        greenhouse_id=greenhouse_id, code=greenhouse["code"], name=greenhouse["name"], classification=classification,
    )

    def sorted_children(node_id: uuid.UUID, type_code: str) -> list[dict]:
        return sorted(
            (c for c in children_of.get(node_id, ()) if c["type_code"] == type_code),
            key=lambda r: r["code"].lower(),
        )

    if classification == "leafy_greens":
        zones = []
        for zone in sorted_children(greenhouse_id, "zone"):
            spans = []
            for span in sorted_children(zone["id"], "span"):
                tables = [
                    StructureTableNode(id=t["id"], code=t["code"], capacity=t["capacity"])
                    for t in sorted_children(span["id"], "grow_table")
                ]
                spans.append(StructureSpanNode(id=span["id"], code=span["code"], tables=tables))
            zones.append(StructureZoneNode(id=zone["id"], code=zone["code"], spans=spans))
        result.leafy_zones = zones

    elif classification == "vines":
        zones = []
        for zone in sorted_children(greenhouse_id, "zone"):
            spans = []
            for span in sorted_children(zone["id"], "span"):
                gutters = [
                    StructureGutterNode(
                        id=g["id"], code=g["code"],
                        bag_position_count=len(sorted_children(g["id"], "grow_bag_position")),
                    )
                    for g in sorted_children(span["id"], "grow_gutter")
                ]
                spans.append(StructureVinesSpanNode(id=span["id"], code=span["code"], gutters=gutters))
            zones.append(StructureVinesZoneNode(id=zone["id"], code=zone["code"], spans=spans))
        result.vines_zones = zones

    else:  # nursery
        # Seeding Station is returned as the FULL list, never collapsed to
        # "the first one" -- a Nursery can structurally have more than one
        # (see GreenhouseStructureRead.nursery_seeding_stations), and
        # silently picking one would let the Sowing form record an
        # operator's chosen Nursery against a station they never selected.
        result.nursery_seeding_stations = [
            StructureSectionNode(id=s["id"], code=s["code"], name=s["name"])
            for s in sorted_children(greenhouse_id, "seeding_station")
        ]
        germination_chambers = sorted_children(greenhouse_id, "germination_chamber")
        if germination_chambers:
            chamber = germination_chambers[0]
            result.nursery_germination_chamber = StructureGerminationChamberNode(
                id=chamber["id"], code=chamber["code"], name=chamber["name"],
                trolley_capacity=chamber["capacity"],
            )

        for area_type, table_type, field_name in (
            ("seedling_area", "seedling_table", "nursery_seedling"),
            ("intersalads", "intersalads_table", "nursery_intersalads"),
            ("intervines", "intervines_table", "nursery_intervines"),
        ):
            areas = sorted_children(greenhouse_id, area_type)
            area = areas[0] if areas else None
            tables = (
                [
                    StructureTableNode(id=t["id"], code=t["code"], capacity=t["capacity"])
                    for t in sorted_children(area["id"], table_type)
                ]
                if area is not None
                else []
            )
            setattr(
                result, field_name,
                StructureNurseryTableGroup(area_id=area["id"] if area else None, tables=tables),
            )

    return result
