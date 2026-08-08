"""CMP-019 read-only traceability service.

Every public function here opens its own short-lived, dedicated connection
in a PostgreSQL REPEATABLE READ, READ ONLY transaction (see
`_snapshot_connection`), and every query the trace issues -- including
tenant/farm and subject-existence validation -- runs on that one
connection/snapshot. This guarantees a trace response is never a mix of
pre- and post-commit state relative to a concurrent dispatch or storage
movement. The router's own injected `Session` is used only to authenticate
the tenant/user context (`require_dev_tenant_context`); it never touches
trace data.

No table here is written to. No audit event is appended for a read. No
proportional attribution is invented anywhere in this module -- every
"potentially affected" downstream quantity is a finished-goods lot's own
entire current quantity, never a fraction derived from an upstream input.
"""
import uuid
from contextlib import contextmanager
from decimal import Decimal
from typing import Iterator

from sqlalchemy import Connection, Engine, text

from app.core.db import engine as _default_engine
from app.services.errors import (
    CropBatchNotFoundError,
    FarmNotFoundError,
    FinishedGoodsLotNotFoundError,
    HarvestedProduceLotNotFoundError,
    TraceabilityIntegrityError,
)

# Defensive corruption guard only -- never a business lineage limit. Real
# split/merge lineage is expected to be at most a handful of generations
# deep; this exists solely to bound a genuinely corrupted (cyclic) graph.
_MAX_LINEAGE_DEPTH = 500


@contextmanager
def _snapshot_connection(engine: Engine | None = None) -> Iterator[Connection]:
    conn = (engine or _default_engine).connect().execution_options(
        isolation_level="REPEATABLE READ", postgresql_readonly=True
    )
    try:
        with conn.begin():
            yield conn
    finally:
        conn.close()


def _require_active_farm(conn: Connection, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> None:
    row = conn.execute(
        text("SELECT 1 FROM farms WHERE id = :farm_id AND tenant_id = :tenant_id AND status = 'active'"),
        {"farm_id": farm_id, "tenant_id": tenant_id},
    ).first()
    if row is None:
        raise FarmNotFoundError(str(farm_id))


def _resolve_finished_goods_lot(conn: Connection, *, tenant_id, farm_id, finished_goods_lot_id):
    row = conn.execute(
        text(
            "SELECT id, tenant_id, farm_id, code, packing_event_id, net_packed_weight_kg, package_count, "
            "effective_time FROM finished_goods_lots WHERE id = :id AND tenant_id = :tid AND farm_id = :fid"
        ),
        {"id": finished_goods_lot_id, "tid": tenant_id, "fid": farm_id},
    ).mappings().first()
    if row is None:
        raise FinishedGoodsLotNotFoundError(str(finished_goods_lot_id))
    return row


def _resolve_crop_batch(conn: Connection, *, tenant_id, farm_id, batch_id):
    row = conn.execute(
        text(
            "SELECT id, code, state, created_effective_time, created_by_batch_derivation_event_id "
            "FROM crop_batches WHERE id = :id AND tenant_id = :tid AND farm_id = :fid"
        ),
        {"id": batch_id, "tid": tenant_id, "fid": farm_id},
    ).mappings().first()
    if row is None:
        raise CropBatchNotFoundError(str(batch_id))
    return row


def _resolve_harvested_produce_lot(conn: Connection, *, tenant_id, farm_id, harvested_produce_lot_id):
    row = conn.execute(
        text(
            "SELECT id, code, harvest_event_id, batch_id, total_harvested_weight_kg, total_whole_unit_count, "
            "effective_time FROM harvested_produce_lots WHERE id = :id AND tenant_id = :tid AND farm_id = :fid"
        ),
        {"id": harvested_produce_lot_id, "tid": tenant_id, "fid": farm_id},
    ).mappings().first()
    if row is None:
        raise HarvestedProduceLotNotFoundError(str(harvested_produce_lot_id))
    return row


# --- Recursive batch lineage --------------------------------------------------


def _batch_lineage_closure(
    conn: Connection, *, tenant_id, farm_id, start_batch_ids: list[uuid.UUID], direction: str
) -> set[uuid.UUID]:
    """Returns the closed set of batch IDs reachable from `start_batch_ids`
    (inclusive) in the given direction ("ancestors" or "descendants"),
    using a tenant/farm-constrained recursive CTE that carries a per-branch
    visited path. Raises TraceabilityIntegrityError if a true cycle (a
    batch reachable from itself along one branch) or the defensive depth
    guard is detected -- ordinary re-convergent lineage (the same ancestor
    reached via two independent branches, e.g. after a split followed by a
    re-merge) is not a cycle and is handled correctly, since the cycle
    check is per-branch, not across the whole result set."""
    if not start_batch_ids:
        return set()

    if direction == "ancestors":
        event_col = "created_by_batch_derivation_event_id"
        bridge_table = "batch_derivation_sources"
        bridge_col = "source_batch_id"
    else:
        event_col = "superseded_by_batch_derivation_event_id"
        bridge_table = "batch_derivation_outputs"
        bridge_col = "output_batch_id"

    rows = conn.execute(
        text(
            f"""
            WITH RECURSIVE lineage AS (
                SELECT cb.id AS batch_id, cb.{event_col} AS next_event_id,
                       ARRAY[cb.id] AS visited, 0 AS depth, false AS cycle_detected
                FROM crop_batches cb
                WHERE cb.id = ANY(:start_ids) AND cb.tenant_id = :tid AND cb.farm_id = :fid
                UNION ALL
                SELECT nxt.id, nxt.{event_col}, l.visited || nxt.id, l.depth + 1,
                       (nxt.id = ANY(l.visited))
                FROM lineage l
                JOIN {bridge_table} bridge
                    ON bridge.derivation_event_id = l.next_event_id
                    AND bridge.tenant_id = :tid AND bridge.farm_id = :fid
                JOIN crop_batches nxt
                    ON nxt.id = bridge.{bridge_col}
                    AND nxt.tenant_id = :tid AND nxt.farm_id = :fid
                WHERE l.next_event_id IS NOT NULL AND l.depth < :max_depth AND NOT l.cycle_detected
            )
            SELECT batch_id, depth, cycle_detected FROM lineage
            """
        ),
        {"start_ids": start_batch_ids, "tid": tenant_id, "fid": farm_id, "max_depth": _MAX_LINEAGE_DEPTH},
    ).mappings().all()

    if any(r["cycle_detected"] for r in rows):
        raise TraceabilityIntegrityError(
            "Detected a crop-batch lineage cycle: a batch is reachable from itself through "
            "split/merge derivation history. This should be structurally impossible and indicates "
            "corrupted derivation data."
        )
    if any(r["depth"] == _MAX_LINEAGE_DEPTH - 1 for r in rows):
        raise TraceabilityIntegrityError(
            f"Crop-batch lineage traversal reached its defensive depth guard ({_MAX_LINEAGE_DEPTH} "
            "generations) without terminating naturally. This is not a normal business lineage depth "
            "and indicates corrupted or pathological derivation data."
        )
    return {r["batch_id"] for r in rows}


def _batch_lineage_edges(conn: Connection, *, tenant_id, farm_id, batch_ids: set[uuid.UUID]) -> list[dict]:
    if not batch_ids:
        return []
    ids = list(batch_ids)
    rows = conn.execute(
        text(
            """
            SELECT bds.source_batch_id AS parent_batch_id, bdo.output_batch_id AS child_batch_id,
                   bde.id AS derivation_event_id, bde.derivation_kind
            FROM batch_derivation_events bde
            JOIN batch_derivation_sources bds ON bds.derivation_event_id = bde.id
            JOIN batch_derivation_outputs bdo ON bdo.derivation_event_id = bde.id
            WHERE bde.tenant_id = :tid AND bde.farm_id = :fid
              AND bds.source_batch_id = ANY(:ids) AND bdo.output_batch_id = ANY(:ids)
            ORDER BY bde.effective_time, bde.id, parent_batch_id, child_batch_id
            """
        ),
        {"tid": tenant_id, "fid": farm_id, "ids": ids},
    ).mappings().all()
    return [dict(r) for r in rows]


def _batch_lineage_nodes(conn: Connection, *, tenant_id, farm_id, batch_ids: set[uuid.UUID], edges: list[dict]) -> list[dict]:
    if not batch_ids:
        return []
    rows = conn.execute(
        text(
            "SELECT id AS batch_id, code, state, created_effective_time, created_by_batch_derivation_event_id "
            "FROM crop_batches WHERE id = ANY(:ids) AND tenant_id = :tid AND farm_id = :fid "
            "ORDER BY created_effective_time, id"
        ),
        {"ids": list(batch_ids), "tid": tenant_id, "fid": farm_id},
    ).mappings().all()
    kind_by_child = {e["child_batch_id"]: e["derivation_kind"] for e in edges}
    event_by_child = {e["child_batch_id"]: e["derivation_event_id"] for e in edges}
    nodes = []
    for r in rows:
        transformation_type = kind_by_child.get(r["batch_id"], "sown")
        nodes.append(
            {
                "batch_id": r["batch_id"], "code": r["code"], "state": r["state"],
                "created_effective_time": r["created_effective_time"],
                "transformation_type": transformation_type,
                "derivation_event_id": event_by_child.get(r["batch_id"]),
            }
        )
    return nodes


# --- Seed provenance -----------------------------------------------------------


def _seed_origins_for_batches(conn: Connection, *, tenant_id, farm_id, batch_ids: set[uuid.UUID]) -> list[dict]:
    """Every provable seed origin for the given batch set: walks each
    sowing-origin batch_carrier_assignment (opened directly by a sowing
    event -- transplant- and derivation-opened assignments are not
    themselves a seed origin, only a continuation of one) to its own
    sowing_event_line and seed_lot. A merge may legitimately surface
    several distinct origins; none is collapsed or guessed."""
    if not batch_ids:
        return []
    rows = conn.execute(
        text(
            """
            SELECT sl.id AS seed_lot_id, sl.code AS seed_lot_code, se.id AS sowing_event_id,
                   sel.id AS sowing_event_line_id, bca.id AS batch_carrier_assignment_id,
                   sel.carrier_id AS carrier_id, bca.batch_id AS originating_batch_id
            FROM batch_carrier_assignments bca
            JOIN sowing_event_lines sel ON sel.batch_carrier_assignment_id = bca.id
                AND sel.tenant_id = :tid AND sel.farm_id = :fid
            JOIN sowing_events se ON se.id = bca.opening_sowing_event_id
                AND se.tenant_id = :tid AND se.farm_id = :fid
            JOIN seed_lots sl ON sl.id = sel.seed_lot_id AND sl.tenant_id = :tid AND sl.farm_id = :fid
            WHERE bca.tenant_id = :tid AND bca.farm_id = :fid
              AND bca.opening_sowing_event_id IS NOT NULL
              AND bca.batch_id = ANY(:ids)
            ORDER BY sl.code, se.id, sel.id
            """
        ),
        {"tid": tenant_id, "fid": farm_id, "ids": list(batch_ids)},
    ).mappings().all()
    return [dict(r) for r in rows]


# --- Harvest / produce lots / packing --------------------------------------


def _harvest_events_for_batches(conn: Connection, *, tenant_id, farm_id, batch_ids: set[uuid.UUID]) -> list[dict]:
    if not batch_ids:
        return []
    rows = conn.execute(
        text(
            "SELECT id AS harvest_event_id, batch_id, effective_time, recorded_time FROM harvest_events "
            "WHERE tenant_id = :tid AND farm_id = :fid AND batch_id = ANY(:ids) "
            "ORDER BY effective_time, recorded_time, id"
        ),
        {"tid": tenant_id, "fid": farm_id, "ids": list(batch_ids)},
    ).mappings().all()
    return [dict(r) for r in rows]


def _produce_lots_for_harvest_events(conn: Connection, *, tenant_id, farm_id, harvest_event_ids: list[uuid.UUID]) -> list[dict]:
    if not harvest_event_ids:
        return []
    rows = conn.execute(
        text(
            "SELECT id AS harvested_produce_lot_id, code, harvest_event_id, batch_id, "
            "total_harvested_weight_kg, total_whole_unit_count, effective_time FROM harvested_produce_lots "
            "WHERE tenant_id = :tid AND farm_id = :fid AND harvest_event_id = ANY(:ids) "
            "ORDER BY effective_time, id"
        ),
        {"tid": tenant_id, "fid": farm_id, "ids": harvest_event_ids},
    ).mappings().all()
    return [dict(r) for r in rows]


def _packing_input_lines_for_produce_lots(conn: Connection, *, tenant_id, farm_id, produce_lot_ids: list[uuid.UUID]) -> list[dict]:
    if not produce_lot_ids:
        return []
    rows = conn.execute(
        text(
            "SELECT id AS packing_input_line_id, packing_event_id, harvested_produce_lot_id, "
            "consumed_weight_kg, consumed_whole_unit_count FROM packing_input_lines "
            "WHERE tenant_id = :tid AND farm_id = :fid AND harvested_produce_lot_id = ANY(:ids) "
            "ORDER BY packing_event_id, harvested_produce_lot_id"
        ),
        {"tid": tenant_id, "fid": farm_id, "ids": produce_lot_ids},
    ).mappings().all()
    return [dict(r) for r in rows]


def _packing_events(conn: Connection, *, tenant_id, farm_id, packing_event_ids: list[uuid.UUID]) -> list[dict]:
    if not packing_event_ids:
        return []
    rows = conn.execute(
        text(
            "SELECT id AS packing_event_id, total_input_weight_kg, packed_output_weight_kg, "
            "process_loss_weight_kg, rejected_weight_kg, effective_time, recorded_time FROM packing_events "
            "WHERE tenant_id = :tid AND farm_id = :fid AND id = ANY(:ids) ORDER BY effective_time, id"
        ),
        {"tid": tenant_id, "fid": farm_id, "ids": packing_event_ids},
    ).mappings().all()
    return [dict(r) for r in rows]


def _finished_goods_lots_for_packing_events(conn: Connection, *, tenant_id, farm_id, packing_event_ids: list[uuid.UUID]) -> list[dict]:
    if not packing_event_ids:
        return []
    rows = conn.execute(
        text(
            "SELECT id AS finished_goods_lot_id, code, packing_event_id, net_packed_weight_kg, package_count, "
            "effective_time FROM finished_goods_lots "
            "WHERE tenant_id = :tid AND farm_id = :fid AND packing_event_id = ANY(:ids) ORDER BY effective_time, id"
        ),
        {"tid": tenant_id, "fid": farm_id, "ids": packing_event_ids},
    ).mappings().all()
    return [dict(r) for r in rows]


# --- Balances (bulk, set-based; matches the canonical formulas exactly) ----
# The service intentionally does not call finished_goods_ledger_service or
# finished_goods_storage_service (both take a single lot and an ORM
# Session bound to the request's own connection) -- doing so per lot would
# be N+1 and would run outside this trace's own REPEATABLE READ snapshot.
# These bulk helpers reproduce the identical canonical formulas -- plain
# SUM(weight_delta_kg)/SUM(package_count_delta) for available, and
# SUM(place)-SUM(release) for total placed -- against this trace's own
# connection, for a whole set of lots in one query each.


def _bulk_available(conn: Connection, *, tenant_id, farm_id, fg_lot_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[Decimal, int]]:
    if not fg_lot_ids:
        return {}
    rows = conn.execute(
        text(
            "SELECT finished_goods_lot_id, COALESCE(SUM(weight_delta_kg), 0) AS weight, "
            "COALESCE(SUM(package_count_delta), 0) AS count FROM finished_goods_ledger_entries "
            "WHERE tenant_id = :tid AND farm_id = :fid AND finished_goods_lot_id = ANY(:ids) "
            "GROUP BY finished_goods_lot_id"
        ),
        {"tid": tenant_id, "fid": farm_id, "ids": fg_lot_ids},
    ).mappings().all()
    # SUM(bigint) is promoted to NUMERIC by PostgreSQL -- cast back to a
    # genuine Python int so downstream Pydantic validation and arithmetic
    # never silently operates on Decimal counts.
    return {r["finished_goods_lot_id"]: (r["weight"], int(r["count"])) for r in rows}


def _bulk_placed(conn: Connection, *, tenant_id, farm_id, fg_lot_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[Decimal, int]]:
    if not fg_lot_ids:
        return {}
    rows = conn.execute(
        text(
            "SELECT finished_goods_lot_id, "
            "COALESCE(SUM(CASE WHEN movement_kind = 'place' THEN moved_weight_kg "
            "  WHEN movement_kind = 'release' THEN -moved_weight_kg ELSE 0 END), 0) AS weight, "
            "COALESCE(SUM(CASE WHEN movement_kind = 'place' THEN moved_package_count "
            "  WHEN movement_kind = 'release' THEN -moved_package_count ELSE 0 END), 0) AS count "
            "FROM finished_goods_storage_movements "
            "WHERE tenant_id = :tid AND farm_id = :fid AND finished_goods_lot_id = ANY(:ids) "
            "GROUP BY finished_goods_lot_id"
        ),
        {"tid": tenant_id, "fid": farm_id, "ids": fg_lot_ids},
    ).mappings().all()
    return {r["finished_goods_lot_id"]: (r["weight"], int(r["count"])) for r in rows}


def _bulk_location_balances(conn: Connection, *, tenant_id, farm_id, fg_lot_ids: list[uuid.UUID]) -> list[dict]:
    if not fg_lot_ids:
        return []
    rows = conn.execute(
        text(
            "SELECT finished_goods_lot_id, loc_id AS location_id, "
            "SUM(weight_in) - SUM(weight_out) AS weight_kg, SUM(count_in) - SUM(count_out) AS package_count FROM ("
            "  SELECT finished_goods_lot_id, destination_location_id AS loc_id, moved_weight_kg AS weight_in, "
            "         0 AS weight_out, moved_package_count AS count_in, 0 AS count_out "
            "  FROM finished_goods_storage_movements "
            "  WHERE tenant_id = :tid AND farm_id = :fid AND finished_goods_lot_id = ANY(:ids) "
            "    AND destination_location_id IS NOT NULL "
            "  UNION ALL "
            "  SELECT finished_goods_lot_id, source_location_id, 0, moved_weight_kg, 0, moved_package_count "
            "  FROM finished_goods_storage_movements "
            "  WHERE tenant_id = :tid AND farm_id = :fid AND finished_goods_lot_id = ANY(:ids) "
            "    AND source_location_id IS NOT NULL "
            ") x GROUP BY finished_goods_lot_id, loc_id HAVING SUM(weight_in) - SUM(weight_out) > 0 "
            "ORDER BY finished_goods_lot_id, loc_id"
        ),
        {"tid": tenant_id, "fid": farm_id, "ids": fg_lot_ids},
    ).mappings().all()
    return [dict(r) | {"package_count": int(r["package_count"])} for r in rows]


def _bulk_storage_movements(conn: Connection, *, tenant_id, farm_id, fg_lot_ids: list[uuid.UUID]) -> list[dict]:
    if not fg_lot_ids:
        return []
    rows = conn.execute(
        text(
            "SELECT id AS movement_id, finished_goods_lot_id, movement_kind, source_location_id, "
            "destination_location_id, moved_weight_kg, moved_package_count, effective_time, recorded_time "
            "FROM finished_goods_storage_movements "
            "WHERE tenant_id = :tid AND farm_id = :fid AND finished_goods_lot_id = ANY(:ids) "
            "ORDER BY effective_time, recorded_time, id"
        ),
        {"tid": tenant_id, "fid": farm_id, "ids": fg_lot_ids},
    ).mappings().all()
    return [dict(r) for r in rows]


def _bulk_dispatch_lines(conn: Connection, *, tenant_id, farm_id, fg_lot_ids: list[uuid.UUID]) -> list[dict]:
    if not fg_lot_ids:
        return []
    rows = conn.execute(
        text(
            "SELECT de.id AS dispatch_event_id, de.code AS dispatch_event_code, dl.id AS dispatch_line_id, "
            "dl.finished_goods_lot_id, dl.dispatched_weight_kg, dl.dispatched_package_count, "
            "de.effective_time, de.recorded_time "
            "FROM dispatch_lines dl JOIN dispatch_events de ON de.id = dl.dispatch_event_id "
            "  AND de.tenant_id = dl.tenant_id AND de.farm_id = dl.farm_id "
            "WHERE dl.tenant_id = :tid AND dl.farm_id = :fid AND dl.finished_goods_lot_id = ANY(:ids) "
            "ORDER BY de.effective_time, de.recorded_time, dl.id"
        ),
        {"tid": tenant_id, "fid": farm_id, "ids": fg_lot_ids},
    ).mappings().all()
    return [dict(r) for r in rows]


def _quality_holds_for_batches(conn: Connection, *, tenant_id, farm_id, batch_ids: set[uuid.UUID]) -> list[dict]:
    if not batch_ids:
        return []
    rows = conn.execute(
        text(
            "SELECT qh.id AS quality_hold_id, qh.batch_id, qh.reason_code, qh.reason_text, qh.effective_time, "
            "qhr.effective_time AS released_effective_time "
            "FROM quality_holds qh LEFT JOIN quality_hold_releases qhr ON qhr.quality_hold_id = qh.id "
            "  AND qhr.tenant_id = qh.tenant_id "
            "WHERE qh.tenant_id = :tid AND qh.farm_id = :fid AND qh.batch_id = ANY(:ids) "
            "ORDER BY qh.effective_time, qh.id"
        ),
        {"tid": tenant_id, "fid": farm_id, "ids": list(batch_ids)},
    ).mappings().all()
    return [
        {
            "quality_hold_id": r["quality_hold_id"], "batch_id": r["batch_id"], "reason_code": r["reason_code"],
            "reason_text": r["reason_text"], "effective_time": r["effective_time"],
            "is_open": r["released_effective_time"] is None,
            "released_effective_time": r["released_effective_time"],
        }
        for r in rows
    ]


def _finished_goods_lot_read(row: dict, available: tuple, placed: tuple) -> dict:
    available_weight, available_count = available
    placed_weight, placed_count = placed
    return {
        "finished_goods_lot_id": row["finished_goods_lot_id"], "code": row["code"],
        "packing_event_id": row["packing_event_id"], "net_packed_weight_kg": row["net_packed_weight_kg"],
        "package_count": row["package_count"], "effective_time": row["effective_time"],
        "available_weight_kg": available_weight, "available_package_count": available_count,
        "placed_weight_kg": placed_weight, "placed_package_count": placed_count,
        "unplaced_weight_kg": available_weight - placed_weight,
        "unplaced_package_count": available_count - placed_count,
    }


# --- Public: backward trace -----------------------------------------------


def get_finished_goods_lot_trace(
    *, tenant_id: uuid.UUID, farm_id: uuid.UUID, finished_goods_lot_id: uuid.UUID, engine: Engine | None = None
) -> dict:
    with _snapshot_connection(engine) as conn:
        _require_active_farm(conn, tenant_id=tenant_id, farm_id=farm_id)
        lot = _resolve_finished_goods_lot(conn, tenant_id=tenant_id, farm_id=farm_id, finished_goods_lot_id=finished_goods_lot_id)

        packing_events = _packing_events(conn, tenant_id=tenant_id, farm_id=farm_id, packing_event_ids=[lot["packing_event_id"]])
        packing_event = packing_events[0] if packing_events else None
        limitations = []
        if packing_event is None:
            raise TraceabilityIntegrityError(
                f"finished-goods lot {finished_goods_lot_id} references packing event "
                f"{lot['packing_event_id']} which does not resolve; this violates the schema's own FK guarantee."
            )

        # Packing inputs for THIS lot's own event (reverse of the usual
        # produce-lot-keyed helper -- query directly by packing_event_id).
        packing_inputs = conn.execute(
            text(
                "SELECT id AS packing_input_line_id, packing_event_id, harvested_produce_lot_id, "
                "consumed_weight_kg, consumed_whole_unit_count FROM packing_input_lines "
                "WHERE tenant_id = :tid AND farm_id = :fid AND packing_event_id = :peid "
                "ORDER BY harvested_produce_lot_id"
            ),
            {"tid": tenant_id, "fid": farm_id, "peid": lot["packing_event_id"]},
        ).mappings().all()
        packing_inputs = [dict(r) for r in packing_inputs]
        produce_lot_ids = sorted({r["harvested_produce_lot_id"] for r in packing_inputs})

        produce_lots = []
        if produce_lot_ids:
            rows = conn.execute(
                text(
                    "SELECT id AS harvested_produce_lot_id, code, harvest_event_id, batch_id, "
                    "total_harvested_weight_kg, total_whole_unit_count, effective_time FROM harvested_produce_lots "
                    "WHERE tenant_id = :tid AND farm_id = :fid AND id = ANY(:ids) ORDER BY effective_time, id"
                ),
                {"tid": tenant_id, "fid": farm_id, "ids": produce_lot_ids},
            ).mappings().all()
            produce_lots = [dict(r) for r in rows]
        if len(produce_lots) != len(produce_lot_ids):
            raise TraceabilityIntegrityError(
                f"packing event {lot['packing_event_id']} has an input line referencing a harvested "
                "produce lot that does not resolve; this violates the schema's own FK guarantee."
            )

        direct_batch_ids = {r["batch_id"] for r in produce_lots}
        harvest_event_ids = sorted({r["harvest_event_id"] for r in produce_lots})
        harvest_events = []
        if harvest_event_ids:
            rows = conn.execute(
                text(
                    "SELECT id AS harvest_event_id, batch_id, effective_time, recorded_time FROM harvest_events "
                    "WHERE tenant_id = :tid AND farm_id = :fid AND id = ANY(:ids) ORDER BY effective_time, id"
                ),
                {"tid": tenant_id, "fid": farm_id, "ids": harvest_event_ids},
            ).mappings().all()
            harvest_events = [dict(r) for r in rows]

        ancestor_ids = _batch_lineage_closure(
            conn, tenant_id=tenant_id, farm_id=farm_id, start_batch_ids=list(direct_batch_ids), direction="ancestors"
        )
        edges = _batch_lineage_edges(conn, tenant_id=tenant_id, farm_id=farm_id, batch_ids=ancestor_ids)
        nodes = _batch_lineage_nodes(conn, tenant_id=tenant_id, farm_id=farm_id, batch_ids=ancestor_ids, edges=edges)

        seed_origins = _seed_origins_for_batches(conn, tenant_id=tenant_id, farm_id=farm_id, batch_ids=ancestor_ids)
        root_batches_without_seed_origin = {n["batch_id"] for n in nodes if n["transformation_type"] == "sown"} - {
            o["originating_batch_id"] for o in seed_origins
        }
        if root_batches_without_seed_origin:
            limitations.append(
                {
                    "code": "no_provable_seed_origin",
                    "message": (
                        "The following sown-origin batches have no resolvable sowing-event/seed-lot "
                        f"evidence: {sorted(str(b) for b in root_batches_without_seed_origin)}."
                    ),
                }
            )

        available = _bulk_available(conn, tenant_id=tenant_id, farm_id=farm_id, fg_lot_ids=[finished_goods_lot_id])
        placed = _bulk_placed(conn, tenant_id=tenant_id, farm_id=farm_id, fg_lot_ids=[finished_goods_lot_id])
        subject = _finished_goods_lot_read(
            {**lot, "finished_goods_lot_id": lot["id"]},
            available.get(finished_goods_lot_id, (Decimal("0"), 0)),
            placed.get(finished_goods_lot_id, (Decimal("0"), 0)),
        )

        storage_movements = _bulk_storage_movements(conn, tenant_id=tenant_id, farm_id=farm_id, fg_lot_ids=[finished_goods_lot_id])
        dispatches = _bulk_dispatch_lines(conn, tenant_id=tenant_id, farm_id=farm_id, fg_lot_ids=[finished_goods_lot_id])
        quality = _quality_holds_for_batches(conn, tenant_id=tenant_id, farm_id=farm_id, batch_ids=ancestor_ids)

        return {
            "subject": subject,
            "packing_event": dict(packing_event),
            "packing_inputs": packing_inputs,
            "produce_lots": produce_lots,
            "harvest_events": harvest_events,
            "lineage": {"batches": nodes, "edges": edges},
            "seed_origins": seed_origins,
            "storage_movements": storage_movements,
            "dispatches": dispatches,
            "quality": quality,
            "completeness": {"trace_complete": True, "limitations": limitations, "capability_limitations": ["recipient_not_modeled"]},
        }


# --- Public: forward impact (shared engine for crop-batch/produce-lot) -----


def _forward_impact_from_produce_lots(
    conn: Connection, *, tenant_id, farm_id, produce_lot_ids: list[uuid.UUID], affected_produce_lot_ids: set[uuid.UUID]
) -> dict:
    seed_inputs = _packing_input_lines_for_produce_lots(conn, tenant_id=tenant_id, farm_id=farm_id, produce_lot_ids=produce_lot_ids)
    affected_packing_event_ids = sorted({r["packing_event_id"] for r in seed_inputs})

    # Re-fetch every input line for each *affected* packing event -- not
    # just the lines for the affected produce lots themselves -- so an
    # unaffected co-input packed alongside an affected one remains visible
    # as context (per the ticket: co-inputs are shown, never promoted to
    # an additional affected source).
    packing_inputs = (
        conn.execute(
            text(
                "SELECT id AS packing_input_line_id, packing_event_id, harvested_produce_lot_id, "
                "consumed_weight_kg, consumed_whole_unit_count FROM packing_input_lines "
                "WHERE tenant_id = :tid AND farm_id = :fid AND packing_event_id = ANY(:ids) "
                "ORDER BY packing_event_id, harvested_produce_lot_id"
            ),
            {"tid": tenant_id, "fid": farm_id, "ids": affected_packing_event_ids},
        ).mappings().all()
        if affected_packing_event_ids else []
    )
    packing_inputs = [dict(r) for r in packing_inputs]
    for r in packing_inputs:
        r["is_affected_source"] = r["harvested_produce_lot_id"] in affected_produce_lot_ids

    fg_lot_rows = _finished_goods_lots_for_packing_events(conn, tenant_id=tenant_id, farm_id=farm_id, packing_event_ids=affected_packing_event_ids)
    fg_lot_ids = [r["finished_goods_lot_id"] for r in fg_lot_rows]

    # source_input is keyed by the *finished-goods lot* the packing event
    # produced, aggregated across every affected input line feeding that
    # one packing event.
    source_input_by_lot: dict[uuid.UUID, tuple[Decimal, int]] = {}
    fg_lot_by_packing_event = {r["packing_event_id"]: r["finished_goods_lot_id"] for r in fg_lot_rows}
    for r in packing_inputs:
        if not r["is_affected_source"]:
            continue
        fg_lot_id = fg_lot_by_packing_event.get(r["packing_event_id"])
        if fg_lot_id is None:
            continue
        w, c = source_input_by_lot.get(fg_lot_id, (Decimal("0"), 0))
        source_input_by_lot[fg_lot_id] = (
            w + r["consumed_weight_kg"],
            c + (r["consumed_whole_unit_count"] or 0) if r["consumed_whole_unit_count"] is not None else c,
        )

    available = _bulk_available(conn, tenant_id=tenant_id, farm_id=farm_id, fg_lot_ids=fg_lot_ids)
    placed = _bulk_placed(conn, tenant_id=tenant_id, farm_id=farm_id, fg_lot_ids=fg_lot_ids)
    dispatches = _bulk_dispatch_lines(conn, tenant_id=tenant_id, farm_id=farm_id, fg_lot_ids=fg_lot_ids)
    storage = _bulk_location_balances(conn, tenant_id=tenant_id, farm_id=farm_id, fg_lot_ids=fg_lot_ids)

    dispatched_by_lot: dict[uuid.UUID, tuple[Decimal, int]] = {}
    dispatch_event_ids: set[uuid.UUID] = set()
    for d in dispatches:
        dispatch_event_ids.add(d["dispatch_event_id"])
        w, c = dispatched_by_lot.get(d["finished_goods_lot_id"], (Decimal("0"), 0))
        dispatched_by_lot[d["finished_goods_lot_id"]] = (w + d["dispatched_weight_kg"], c + d["dispatched_package_count"])

    finished_goods = []
    for r in fg_lot_rows:
        lot_id = r["finished_goods_lot_id"]
        av_w, av_c = available.get(lot_id, (Decimal("0"), 0))
        pl_w, pl_c = placed.get(lot_id, (Decimal("0"), 0))
        di_w, di_c = dispatched_by_lot.get(lot_id, (Decimal("0"), 0))
        src_w, src_c = source_input_by_lot.get(lot_id, (Decimal("0"), 0))
        finished_goods.append(
            {
                "finished_goods_lot_id": lot_id, "code": r["code"], "packing_event_id": r["packing_event_id"],
                "net_packed_weight_kg": r["net_packed_weight_kg"], "package_count": r["package_count"],
                "effective_time": r["effective_time"],
                "available_weight_kg": av_w, "available_package_count": av_c,
                "placed_weight_kg": pl_w, "placed_package_count": pl_c,
                "unplaced_weight_kg": av_w - pl_w, "unplaced_package_count": av_c - pl_c,
                "source_input_weight_kg": src_w, "source_input_whole_unit_count": src_c or None,
                "potentially_affected_available_weight_kg": av_w,
                "potentially_affected_available_package_count": av_c,
                "potentially_affected_placed_weight_kg": pl_w,
                "potentially_affected_placed_package_count": pl_c,
                "potentially_affected_unplaced_weight_kg": av_w - pl_w,
                "potentially_affected_unplaced_package_count": av_c - pl_c,
                "potentially_affected_dispatched_weight_kg": di_w,
                "potentially_affected_dispatched_package_count": di_c,
            }
        )

    summary = {
        "affected_crop_batch_count": 0,  # filled by callers that know the batch set
        "affected_harvested_produce_lot_count": len(affected_produce_lot_ids),
        "affected_finished_goods_lot_count": len(finished_goods),
        "affected_dispatch_event_count": len(dispatch_event_ids),
        "potentially_affected_available_weight_kg": sum((f["potentially_affected_available_weight_kg"] for f in finished_goods), Decimal("0")),
        "potentially_affected_available_package_count": sum(f["potentially_affected_available_package_count"] for f in finished_goods),
        "potentially_affected_placed_weight_kg": sum((f["potentially_affected_placed_weight_kg"] for f in finished_goods), Decimal("0")),
        "potentially_affected_placed_package_count": sum(f["potentially_affected_placed_package_count"] for f in finished_goods),
        "potentially_affected_unplaced_weight_kg": sum((f["potentially_affected_unplaced_weight_kg"] for f in finished_goods), Decimal("0")),
        "potentially_affected_unplaced_package_count": sum(f["potentially_affected_unplaced_package_count"] for f in finished_goods),
        "potentially_affected_dispatched_weight_kg": sum((f["potentially_affected_dispatched_weight_kg"] for f in finished_goods), Decimal("0")),
        "potentially_affected_dispatched_package_count": sum(f["potentially_affected_dispatched_package_count"] for f in finished_goods),
    }

    return {
        "packing_inputs": packing_inputs,
        "finished_goods": finished_goods,
        "storage": storage,
        "dispatches": dispatches,
        "summary": summary,
    }


def get_crop_batch_impact(
    *, tenant_id: uuid.UUID, farm_id: uuid.UUID, crop_batch_id: uuid.UUID, engine: Engine | None = None
) -> dict:
    with _snapshot_connection(engine) as conn:
        _require_active_farm(conn, tenant_id=tenant_id, farm_id=farm_id)
        subject = _resolve_crop_batch(conn, tenant_id=tenant_id, farm_id=farm_id, batch_id=crop_batch_id)

        descendant_ids = _batch_lineage_closure(
            conn, tenant_id=tenant_id, farm_id=farm_id, start_batch_ids=[crop_batch_id], direction="descendants"
        )
        edges = _batch_lineage_edges(conn, tenant_id=tenant_id, farm_id=farm_id, batch_ids=descendant_ids)
        nodes = _batch_lineage_nodes(conn, tenant_id=tenant_id, farm_id=farm_id, batch_ids=descendant_ids, edges=edges)

        harvest_events = _harvest_events_for_batches(conn, tenant_id=tenant_id, farm_id=farm_id, batch_ids=descendant_ids)
        harvest_event_ids = [h["harvest_event_id"] for h in harvest_events]
        produce_lots = _produce_lots_for_harvest_events(conn, tenant_id=tenant_id, farm_id=farm_id, harvest_event_ids=harvest_event_ids)
        affected_produce_lot_ids = {p["harvested_produce_lot_id"] for p in produce_lots}
        produce_lot_ids = sorted(affected_produce_lot_ids)

        downstream = _forward_impact_from_produce_lots(
            conn, tenant_id=tenant_id, farm_id=farm_id, produce_lot_ids=produce_lot_ids,
            affected_produce_lot_ids=affected_produce_lot_ids,
        )
        downstream["summary"]["affected_crop_batch_count"] = len(descendant_ids)

        return {
            "subject_batch_id": subject["id"], "subject_batch_code": subject["code"],
            "lineage": {"batches": nodes, "edges": edges},
            "harvest_events": harvest_events,
            "produce_lots": produce_lots,
            "packing_inputs": downstream["packing_inputs"],
            "finished_goods": downstream["finished_goods"],
            "storage": downstream["storage"],
            "dispatches": downstream["dispatches"],
            "summary": downstream["summary"],
            "completeness": {"trace_complete": True, "limitations": [], "capability_limitations": ["recipient_not_modeled"]},
        }


def get_harvested_produce_lot_impact(
    *, tenant_id: uuid.UUID, farm_id: uuid.UUID, harvested_produce_lot_id: uuid.UUID, engine: Engine | None = None
) -> dict:
    with _snapshot_connection(engine) as conn:
        _require_active_farm(conn, tenant_id=tenant_id, farm_id=farm_id)
        subject = _resolve_harvested_produce_lot(
            conn, tenant_id=tenant_id, farm_id=farm_id, harvested_produce_lot_id=harvested_produce_lot_id
        )

        affected_produce_lot_ids = {harvested_produce_lot_id}
        downstream = _forward_impact_from_produce_lots(
            conn, tenant_id=tenant_id, farm_id=farm_id, produce_lot_ids=[harvested_produce_lot_id],
            affected_produce_lot_ids=affected_produce_lot_ids,
        )
        downstream["summary"]["affected_crop_batch_count"] = 1

        return {
            "subject_harvested_produce_lot_id": subject["id"], "subject_harvested_produce_lot_code": subject["code"],
            "produce_lots": [dict(subject) | {"harvested_produce_lot_id": subject["id"]}],
            "packing_inputs": downstream["packing_inputs"],
            "finished_goods": downstream["finished_goods"],
            "storage": downstream["storage"],
            "dispatches": downstream["dispatches"],
            "summary": downstream["summary"],
            "completeness": {"trace_complete": True, "limitations": [], "capability_limitations": ["recipient_not_modeled"]},
        }
