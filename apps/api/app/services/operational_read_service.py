"""CMP-FE-002A: read-only operational models over existing crop-batch,
sowing/derivation-lineage, and occupancy facts. Every function here takes a
plain SQLAlchemy `Connection` (never a `Session`) and issues bounded,
set-based queries -- no per-batch or per-location loop ever issues its own
SQL statement. Callers open one `lineage_traversal._snapshot_connection`
(REPEATABLE READ, READ ONLY) per request and pass it through, exactly like
CMP-019's traceability service and CMP-020's recall-case reads -- this file
adds no second isolation implementation.

Origin-sowing resolution reuses `lineage_traversal._batch_lineage_closure`
and `_seed_origins_for_batches` verbatim (zero changes to that module) --
the same two functions CMP-019 already depends on for its own backward
traces, applied here to a new call site rather than reimplemented."""
from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import Connection, text

from app.schemas.crop_batch import CropSummary, VarietySummary
from app.schemas.operational_read import (
    BatchOperationalContext,
    BatchPlacement,
    LocationAggregateCount,
    LocationOccupant,
    LocationPathSegment,
    OccupantBatchContext,
    OccupiedLocation,
    OperationalStageSummary,
    PlacementFacts,
    SowingOrigin,
    SubtreeOccupancyRead,
)
from app.services import lineage_traversal
from app.services.errors import FarmNotFoundError, LocationNotFoundError


def _require_active_farm(conn: Connection, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> None:
    row = conn.execute(
        text("SELECT status FROM farms WHERE id = :fid AND tenant_id = :tid"),
        {"fid": farm_id, "tid": tenant_id},
    ).scalar_one_or_none()
    if row is None or row != "active":
        raise FarmNotFoundError(str(farm_id))


# --- Batch selection --------------------------------------------------------


def resolve_batch_ids_by_state(
    conn: Connection, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, state_filter: str
) -> list[uuid.UUID]:
    """`state_filter` is `"active"` (default, used by Home) or `"all"` (used
    by the Batch Register, which must be able to inspect every legitimate
    `crop_batches.state` value: active, closed, superseded -- not just
    active+superseded). No free-text filtering is exposed."""
    where_extra = "AND state = 'active'" if state_filter == "active" else ""
    rows = conn.execute(
        text(f"SELECT id FROM crop_batches WHERE tenant_id = :tid AND farm_id = :fid {where_extra} ORDER BY code"),
        {"tid": tenant_id, "fid": farm_id},
    ).scalars().all()
    return list(rows)


# --- Core batch facts ---------------------------------------------------------


def _core_facts(conn: Connection, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_ids: set[uuid.UUID]) -> dict[uuid.UUID, dict]:
    if not batch_ids:
        return {}
    rows = conn.execute(
        text(
            """
            SELECT cb.id AS batch_id, cb.code, cb.state,
                   cr.id AS crop_id, cr.code AS crop_code, cr.common_name AS crop_common_name,
                   v.id AS variety_id, v.code AS variety_code, v.name AS variety_name,
                   ws.id AS stage_id, ws.code AS stage_code, ws.name AS stage_name, ws.is_terminal AS stage_is_terminal,
                   ws.stage_category AS stage_category
            FROM crop_batches cb
            JOIN workflows w ON w.id = cb.workflow_id
            JOIN crops cr ON cr.id = w.crop_id
            LEFT JOIN varieties v ON v.id = w.variety_id
            JOIN batch_stage_runs bsr ON bsr.batch_id = cb.id AND bsr.exited_effective_time IS NULL
            JOIN workflow_stages ws ON ws.id = bsr.workflow_stage_id
            WHERE cb.tenant_id = :tid AND cb.farm_id = :fid AND cb.id = ANY(:ids)
            """
        ),
        {"tid": tenant_id, "fid": farm_id, "ids": list(batch_ids)},
    ).mappings().all()
    return {r["batch_id"]: dict(r) for r in rows}


# --- Sowing origin -------------------------------------------------------------


def _resolve_sowing_origins(
    conn: Connection, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_ids: set[uuid.UUID]
) -> dict[uuid.UUID, list[SowingOrigin]]:
    if not batch_ids:
        return {}

    closure = lineage_traversal._batch_lineage_closure(
        conn, tenant_id=tenant_id, farm_id=farm_id, start_batch_ids=list(batch_ids), direction="ancestors"
    )
    edges = lineage_traversal._batch_lineage_edges(conn, tenant_id=tenant_id, farm_id=farm_id, batch_ids=closure)
    origins = lineage_traversal._seed_origins_for_batches(conn, tenant_id=tenant_id, farm_id=farm_id, batch_ids=closure)

    sowing_event_ids = {o["sowing_event_id"] for o in origins}
    effective_times: dict[uuid.UUID, object] = {}
    if sowing_event_ids:
        rows = conn.execute(
            text("SELECT id, effective_time FROM sowing_events WHERE id = ANY(:ids)"),
            {"ids": list(sowing_event_ids)},
        ).mappings().all()
        effective_times = {r["id"]: r["effective_time"] for r in rows}

    batch_codes: dict[uuid.UUID, str] = {}
    if closure:
        rows = conn.execute(
            text("SELECT id, code FROM crop_batches WHERE id = ANY(:ids) AND tenant_id = :tid AND farm_id = :fid"),
            {"ids": list(closure), "tid": tenant_id, "fid": farm_id},
        ).mappings().all()
        batch_codes = {r["id"]: r["code"] for r in rows}

    parents_of: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for e in edges:
        parents_of[e["child_batch_id"]].add(e["parent_batch_id"])

    def ancestor_set_for(start: uuid.UUID) -> set[uuid.UUID]:
        seen = {start}
        frontier = [start]
        while frontier:
            nxt = []
            for b in frontier:
                for p in parents_of.get(b, ()):
                    if p not in seen:
                        seen.add(p)
                        nxt.append(p)
            frontier = nxt
        return seen

    origins_by_origin_batch: dict[uuid.UUID, list[dict]] = defaultdict(list)
    for o in origins:
        origins_by_origin_batch[o["originating_batch_id"]].append(o)

    result: dict[uuid.UUID, list[SowingOrigin]] = {}
    for bid in batch_ids:
        own_ancestors = ancestor_set_for(bid)
        found: list[dict] = []
        for anc in own_ancestors:
            found.extend(origins_by_origin_batch.get(anc, []))
        found.sort(key=lambda o: (o["seed_lot_code"], str(o["sowing_event_id"])))
        result[bid] = [
            SowingOrigin(
                source_batch_id=o["originating_batch_id"],
                source_batch_code=batch_codes.get(o["originating_batch_id"], ""),
                sowing_event_id=o["sowing_event_id"],
                effective_time=effective_times[o["sowing_event_id"]],
                seed_lot_id=o["seed_lot_id"],
                seed_lot_code=o["seed_lot_code"],
            )
            for o in found
        ]
    return result


def _sown_effective_time(origins: list[SowingOrigin]):
    if not origins:
        return None
    distinct = {o.effective_time for o in origins}
    return next(iter(distinct)) if len(distinct) == 1 else None


# --- Placement -----------------------------------------------------------------


def _resolve_placements(
    conn: Connection, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_ids: set[uuid.UUID]
) -> dict[uuid.UUID, PlacementFacts]:
    if not batch_ids:
        return {}

    assignment_rows = conn.execute(
        text(
            """
            SELECT bca.batch_id, bca.carrier_id, c.code AS carrier_code, o.target_location_id AS location_id
            FROM batch_carrier_assignments bca
            JOIN carriers c ON c.id = bca.carrier_id AND c.tenant_id = :tid AND c.farm_id = :fid
            LEFT JOIN occupancies o
                ON o.occupant_carrier_id = bca.carrier_id AND o.end_time IS NULL
                AND o.tenant_id = :tid AND o.farm_id = :fid
            WHERE bca.tenant_id = :tid AND bca.farm_id = :fid
              AND bca.batch_id = ANY(:ids) AND bca.released_effective_time IS NULL
            ORDER BY bca.batch_id, c.code
            """
        ),
        {"tid": tenant_id, "fid": farm_id, "ids": list(batch_ids)},
    ).mappings().all()

    location_ids = {r["location_id"] for r in assignment_rows if r["location_id"] is not None}
    paths = _resolve_location_paths(conn, tenant_id=tenant_id, farm_id=farm_id, location_ids=location_ids)

    by_batch: dict[uuid.UUID, list[dict]] = defaultdict(list)
    for r in assignment_rows:
        by_batch[r["batch_id"]].append(dict(r))

    result: dict[uuid.UUID, PlacementFacts] = {}
    for bid in batch_ids:
        rows = by_batch.get(bid, [])
        placements: list[BatchPlacement] = []
        for r in rows:
            if r["location_id"] is None:
                continue
            path = paths[r["location_id"]]
            leaf = path[-1]
            placements.append(
                BatchPlacement(
                    carrier_id=r["carrier_id"], carrier_code=r["carrier_code"],
                    location_id=leaf.id, location_code=leaf.code, location_name=leaf.name, path=path,
                )
            )
        placements.sort(key=lambda p: p.carrier_code)
        active_count = len(rows)
        placed_count = len(placements)
        result[bid] = PlacementFacts(
            active_carrier_count=active_count,
            placed_carrier_count=placed_count,
            unplaced_carrier_count=active_count - placed_count,
            placements=placements,
            common_ancestor_path=_common_ancestor_path([p.path for p in placements]),
        )
    return result


def _resolve_location_paths(
    conn: Connection, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, location_ids: set[uuid.UUID]
) -> dict[uuid.UUID, list[LocationPathSegment]]:
    if not location_ids:
        return {}
    rows = conn.execute(
        text(
            """
            WITH RECURSIVE ancestry AS (
                SELECT id, parent_location_id, code, name, id AS leaf_id, 0 AS depth
                FROM locations WHERE id = ANY(:ids) AND tenant_id = :tid AND farm_id = :fid
                UNION ALL
                SELECT l.id, l.parent_location_id, l.code, l.name, a.leaf_id, a.depth + 1
                FROM locations l
                JOIN ancestry a ON l.id = a.parent_location_id
                WHERE l.tenant_id = :tid AND l.farm_id = :fid
            )
            SELECT leaf_id, id, code, name, depth FROM ancestry ORDER BY leaf_id, depth DESC
            """
        ),
        {"ids": list(location_ids), "tid": tenant_id, "fid": farm_id},
    ).mappings().all()
    by_leaf: dict[uuid.UUID, list[LocationPathSegment]] = defaultdict(list)
    for r in rows:
        by_leaf[r["leaf_id"]].append(LocationPathSegment(id=r["id"], code=r["code"], name=r["name"]))
    return dict(by_leaf)


def _common_ancestor_path(paths: list[list[LocationPathSegment]]) -> list[LocationPathSegment] | None:
    if not paths:
        return None
    shortest = min(len(p) for p in paths)
    common: list[LocationPathSegment] = []
    for i in range(shortest):
        ids_at_depth = {p[i].id for p in paths}
        if len(ids_at_depth) != 1:
            break
        common.append(paths[0][i])
    return common or None


# --- Open quality holds ---------------------------------------------------------


def _open_hold_counts(
    conn: Connection, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_ids: set[uuid.UUID]
) -> dict[uuid.UUID, int]:
    if not batch_ids:
        return {}
    rows = conn.execute(
        text(
            """
            SELECT qh.batch_id, count(*) AS open_count
            FROM quality_holds qh
            LEFT JOIN quality_hold_releases qhr ON qhr.quality_hold_id = qh.id
            WHERE qh.tenant_id = :tid AND qh.farm_id = :fid AND qh.batch_id = ANY(:ids) AND qhr.id IS NULL
            GROUP BY qh.batch_id
            """
        ),
        {"tid": tenant_id, "fid": farm_id, "ids": list(batch_ids)},
    ).mappings().all()
    return {r["batch_id"]: r["open_count"] for r in rows}


# --- Public entry point ---------------------------------------------------------


def get_batch_operational_contexts(
    conn: Connection, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_ids: list[uuid.UUID]
) -> list[BatchOperationalContext]:
    """One coherent snapshot read for the given batch IDs (already resolved
    by the caller -- e.g. via `resolve_batch_ids_by_state`, or a single
    `[batch_id]` for the single-batch route). Returns results in
    `batch_ids` order. Raises `CropBatchNotFoundError`-equivalent behavior
    is the caller's responsibility (an unresolvable ID is simply absent
    from the result -- routes translate that to 404 for the single-batch
    case)."""
    _require_active_farm(conn, tenant_id=tenant_id, farm_id=farm_id)
    id_set = set(batch_ids)
    core = _core_facts(conn, tenant_id=tenant_id, farm_id=farm_id, batch_ids=id_set)
    origins = _resolve_sowing_origins(conn, tenant_id=tenant_id, farm_id=farm_id, batch_ids=id_set)
    placements = _resolve_placements(conn, tenant_id=tenant_id, farm_id=farm_id, batch_ids=id_set)
    hold_counts = _open_hold_counts(conn, tenant_id=tenant_id, farm_id=farm_id, batch_ids=id_set)

    results: list[BatchOperationalContext] = []
    for bid in batch_ids:
        c = core.get(bid)
        if c is None:
            continue
        batch_origins = origins.get(bid, [])
        results.append(
            BatchOperationalContext(
                id=bid, code=c["code"],
                crop=CropSummary(id=c["crop_id"], code=c["crop_code"], common_name=c["crop_common_name"]),
                variety=(
                    VarietySummary(id=c["variety_id"], code=c["variety_code"], name=c["variety_name"])
                    if c["variety_id"] is not None else None
                ),
                state=c["state"],
                current_stage=OperationalStageSummary(
                    id=c["stage_id"], code=c["stage_code"], name=c["stage_name"], is_terminal=c["stage_is_terminal"],
                    stage_category=c["stage_category"],
                ),
                sowing_origins=batch_origins,
                sown_effective_time=_sown_effective_time(batch_origins),
                placement=placements.get(bid, PlacementFacts(
                    active_carrier_count=0, placed_carrier_count=0, unplaced_carrier_count=0,
                    placements=[], common_ancestor_path=None,
                )),
                open_quality_hold_count=hold_counts.get(bid, 0),
            )
        )
    return results


# --- Location subtree occupancy ------------------------------------------------


def get_location_subtree_occupancy(
    conn: Connection, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, root_location_id: uuid.UUID
) -> SubtreeOccupancyRead:
    _require_active_farm(conn, tenant_id=tenant_id, farm_id=farm_id)

    root_row = conn.execute(
        text("SELECT id FROM locations WHERE id = :rid AND tenant_id = :tid AND farm_id = :fid"),
        {"rid": root_location_id, "tid": tenant_id, "fid": farm_id},
    ).scalar_one_or_none()
    if root_row is None:
        raise LocationNotFoundError(str(root_location_id))

    subtree_rows = conn.execute(
        text(
            """
            WITH RECURSIVE subtree AS (
                SELECT id, parent_location_id, occupiable
                FROM locations WHERE id = :rid AND tenant_id = :tid AND farm_id = :fid
                UNION ALL
                SELECT l.id, l.parent_location_id, l.occupiable
                FROM locations l
                JOIN subtree s ON l.parent_location_id = s.id
                WHERE l.tenant_id = :tid AND l.farm_id = :fid
            )
            SELECT id, parent_location_id, occupiable FROM subtree
            """
        ),
        {"rid": root_location_id, "tid": tenant_id, "fid": farm_id},
    ).mappings().all()

    nodes = {r["id"]: dict(r) for r in subtree_rows}
    children_of: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for r in subtree_rows:
        if r["parent_location_id"] in nodes:
            children_of[r["parent_location_id"]].append(r["id"])

    occupiable_ids = {nid for nid, n in nodes.items() if n["occupiable"]}

    occupancy_rows = conn.execute(
        text(
            """
            SELECT o.id AS occupancy_id, o.target_location_id AS location_id,
                   o.occupant_asset_id, o.occupant_carrier_id, c.code AS carrier_code
            FROM occupancies o
            LEFT JOIN carriers c ON c.id = o.occupant_carrier_id
            WHERE o.tenant_id = :tid AND o.farm_id = :fid AND o.end_time IS NULL
              AND o.target_location_id = ANY(:ids)
            ORDER BY o.effective_time, o.id
            """
        ),
        {"tid": tenant_id, "fid": farm_id, "ids": list(occupiable_ids) or [uuid.UUID(int=0)]},
    ).mappings().all()
    # DOMAIN-FARM-002.1: a capacity>1 location may have several simultaneous
    # active occupancies -- group into a list per location (deterministically
    # ordered above) rather than collapsing to one via dict-overwrite, which
    # silently dropped every occupant but the last.
    occupied_by_location: dict[uuid.UUID, list[dict]] = defaultdict(list)
    for r in occupancy_rows:
        occupied_by_location[r["location_id"]].append(dict(r))

    carrier_ids = {r["occupant_carrier_id"] for r in occupancy_rows if r["occupant_carrier_id"] is not None}
    batch_context_by_carrier: dict[uuid.UUID, dict] = {}
    if carrier_ids:
        rows = conn.execute(
            text(
                """
                SELECT bca.carrier_id, cb.id AS batch_id, cb.code AS batch_code,
                       cr.id AS crop_id, cr.code AS crop_code, cr.common_name AS crop_common_name,
                       ws.id AS stage_id, ws.code AS stage_code, ws.name AS stage_name, ws.is_terminal AS stage_is_terminal,
                       ws.stage_category AS stage_category
                FROM batch_carrier_assignments bca
                JOIN crop_batches cb ON cb.id = bca.batch_id AND cb.tenant_id = :tid AND cb.farm_id = :fid
                JOIN workflows w ON w.id = cb.workflow_id
                JOIN crops cr ON cr.id = w.crop_id
                JOIN batch_stage_runs bsr ON bsr.batch_id = cb.id AND bsr.exited_effective_time IS NULL
                JOIN workflow_stages ws ON ws.id = bsr.workflow_stage_id
                WHERE bca.tenant_id = :tid AND bca.farm_id = :fid
                  AND bca.carrier_id = ANY(:ids) AND bca.released_effective_time IS NULL
                """
            ),
            {"tid": tenant_id, "fid": farm_id, "ids": list(carrier_ids)},
        ).mappings().all()
        batch_context_by_carrier = {r["carrier_id"]: dict(r) for r in rows}

    def occupiable_descendant_count(node_id: uuid.UUID) -> tuple[int, int]:
        stack = [node_id]
        total = 0
        occupied = 0
        while stack:
            nid = stack.pop()
            if nid in occupiable_ids:
                total += 1
                if nid in occupied_by_location:
                    occupied += 1
            stack.extend(children_of.get(nid, ()))
        return total, occupied

    aggregate_nodes = {root_location_id} | {nid for nid, kids in children_of.items() if kids}
    aggregate_counts = []
    for nid in sorted(aggregate_nodes, key=str):
        total, occupied = occupiable_descendant_count(nid)
        aggregate_counts.append(LocationAggregateCount(
            location_id=nid, occupiable_location_count=total, occupied_location_count=occupied,
        ))

    def _build_occupant(r: dict) -> LocationOccupant:
        is_carrier = r["occupant_carrier_id"] is not None
        occupant_id = r["occupant_carrier_id"] if is_carrier else r["occupant_asset_id"]
        batch_ctx = None
        if is_carrier and r["occupant_carrier_id"] in batch_context_by_carrier:
            b = batch_context_by_carrier[r["occupant_carrier_id"]]
            batch_ctx = OccupantBatchContext(
                batch_id=b["batch_id"], batch_code=b["batch_code"],
                crop=CropSummary(id=b["crop_id"], code=b["crop_code"], common_name=b["crop_common_name"]),
                current_stage=OperationalStageSummary(
                    id=b["stage_id"], code=b["stage_code"], name=b["stage_name"], is_terminal=b["stage_is_terminal"],
                    stage_category=b["stage_category"],
                ),
            )
        return LocationOccupant(
            kind="carrier" if is_carrier else "asset", id=occupant_id,
            carrier_code=r["carrier_code"] if is_carrier else None, batch=batch_ctx,
        )

    occupied_locations = []
    for nid in sorted(occupied_by_location.keys(), key=str):
        occupants = [_build_occupant(r) for r in occupied_by_location[nid]]
        occupied_locations.append(OccupiedLocation(location_id=nid, occupant=occupants[0], occupants=occupants))

    return SubtreeOccupancyRead(
        root_location_id=root_location_id, aggregate_counts=aggregate_counts, occupied_locations=occupied_locations,
    )
