"""Shared, set-based lineage/impact traversal primitives (extracted from
CMP-019's `traceability_service.py`, CMP-020).

Every function here takes a plain SQLAlchemy `Connection` and tenant/farm-
scoped IDs, and issues one parameterized SQL statement -- never an ORM
`Session`, never a per-row loop. This is what lets both CMP-019 (which runs
these against its own dedicated read-only `REPEATABLE READ` connection) and
CMP-020 (which runs them against an ordinary write-transaction connection,
via `Session.connection()`, so it can layer row locks around the discovered
IDs) share the exact same recursive-CTE and set-based-query logic without a
second, subtly-different lineage implementation. No function here writes,
locks, or opens its own transaction -- callers own connection/transaction
lifecycle entirely.

This module is a pure move, not a rewrite: every function body is
byte-identical to its pre-extraction form in `traceability_service.py`."""
import uuid
from contextlib import contextmanager
from decimal import Decimal
from typing import Iterator

from sqlalchemy import Connection, Engine, text

from app.core.db import engine as _default_engine
from app.services.errors import TraceabilityIntegrityError

# Defensive corruption guard only -- never a business lineage limit. Real
# split/merge lineage is expected to be at most a handful of generations
# deep; this exists solely to bound a genuinely corrupted (cyclic) graph.
_MAX_LINEAGE_DEPTH = 500


@contextmanager
def _snapshot_connection(engine: Engine | None = None) -> Iterator[Connection]:
    """A dedicated, short-lived REPEATABLE READ / READ ONLY connection, for
    any read-only multi-query trace that must never mix pre- and
    post-commit state (CMP-019's own three public functions; CMP-020's
    recall-case detail reads). Never used for a write path -- a write
    transaction that needs row locks uses its own ordinary `Session`
    instead (see `recall_service.open_recall_case`)."""
    conn = (engine or _default_engine).connect().execution_options(
        isolation_level="REPEATABLE READ", postgresql_readonly=True
    )
    try:
        with conn.begin():
            yield conn
    finally:
        conn.close()


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


def _graded_produce_lots_for_harvested_produce_lots(
    conn: Connection, *, tenant_id, farm_id, harvested_produce_lot_ids: list[uuid.UUID]
) -> list[dict]:
    """POSTHARVEST-OPS-001D: every existing `GradedProduceLot` whose
    `GradingEvent.source_harvested_produce_lot_id` is one of
    `harvested_produce_lot_ids` -- the one join `recall_service` needs to
    freeze upstream (crop-batch- or produce-lot-source) recall scope into
    already-created downstream graded material. Unlike the functions
    above, this is new for 001D, not a CMP-019 extraction -- `traceability_
    service.py`'s own public contract is untouched by it."""
    if not harvested_produce_lot_ids:
        return []
    rows = conn.execute(
        text(
            "SELECT gpl.id AS graded_produce_lot_id, gpl.grading_event_id, "
            "ge.source_harvested_produce_lot_id, gpl.effective_time "
            "FROM graded_produce_lots gpl "
            "JOIN grading_events ge ON ge.id = gpl.grading_event_id "
            "  AND ge.tenant_id = gpl.tenant_id AND ge.farm_id = gpl.farm_id "
            "WHERE gpl.tenant_id = :tid AND gpl.farm_id = :fid "
            "  AND ge.source_harvested_produce_lot_id = ANY(:ids) "
            "ORDER BY gpl.effective_time, gpl.id"
        ),
        {"tid": tenant_id, "fid": farm_id, "ids": harvested_produce_lot_ids},
    ).mappings().all()
    return [dict(r) for r in rows]


def _packing_input_lines_for_produce_lots(conn: Connection, *, tenant_id, farm_id, produce_lot_ids: list[uuid.UUID]) -> list[dict]:
    """POSTHARVEST-OPS-001E: `packing_input_lines` no longer has a
    `harvested_produce_lot_id` column at all -- Packing consumes
    `GradedProduceLot`s exclusively. This helper's own name, signature, and
    return shape (`harvested_produce_lot_id` per row) are preserved
    byte-for-byte so its two existing callers (`traceability_service.py`'s
    own forward-impact function; this module's own `recall_service`-facing
    FG derivation, which callers key off produce-lot ids for the batch-/
    HPL-source freeze paths) continue to work unmodified -- the one join
    hop through `GradedProduceLot -> GradingEvent.source_harvested_
    produce_lot_id` needed to recover the same field is added internally
    here, not at either caller. No proportional ambiguity: one packing
    input line names exactly one GradedProduceLot, which names exactly one
    GradingEvent, which names exactly one source HarvestedProduceLot.

    POSTHARVEST-OPS-001F: also returns `graded_produce_lot_id` (Packing's
    own real source column, previously only exposed by the sibling
    `_packing_input_lines_for_graded_produce_lots`/`_packing_input_lines_
    for_packing_events` helpers) so callers can surface GPL identity
    without a second query."""
    if not produce_lot_ids:
        return []
    rows = conn.execute(
        text(
            "SELECT pil.id AS packing_input_line_id, pil.packing_event_id, pil.graded_produce_lot_id, "
            "ge.source_harvested_produce_lot_id AS harvested_produce_lot_id, "
            "pil.consumed_weight_kg, pil.consumed_whole_unit_count "
            "FROM packing_input_lines pil "
            "JOIN graded_produce_lots gpl ON gpl.id = pil.graded_produce_lot_id "
            "  AND gpl.tenant_id = pil.tenant_id AND gpl.farm_id = pil.farm_id "
            "JOIN grading_events ge ON ge.id = gpl.grading_event_id "
            "  AND ge.tenant_id = gpl.tenant_id AND ge.farm_id = gpl.farm_id "
            "WHERE pil.tenant_id = :tid AND pil.farm_id = :fid "
            "  AND ge.source_harvested_produce_lot_id = ANY(:ids) "
            "ORDER BY pil.packing_event_id, ge.source_harvested_produce_lot_id"
        ),
        {"tid": tenant_id, "fid": farm_id, "ids": produce_lot_ids},
    ).mappings().all()
    return [dict(r) for r in rows]


def _packing_input_lines_for_graded_produce_lots(
    conn: Connection, *, tenant_id, farm_id, graded_produce_lot_ids: list[uuid.UUID]
) -> list[dict]:
    """POSTHARVEST-OPS-001E: the direct (no extra join hop) equivalent of
    `_packing_input_lines_for_produce_lots` above, keyed on
    `graded_produce_lot_id` -- this is Packing's own real, current source
    column. Used by `recall_service`'s graded-produce-lot-source freeze
    (which has exactly one selected GPL, not a produce-lot set to walk
    forward from)."""
    if not graded_produce_lot_ids:
        return []
    rows = conn.execute(
        text(
            "SELECT id AS packing_input_line_id, packing_event_id, graded_produce_lot_id, "
            "consumed_weight_kg, consumed_whole_unit_count FROM packing_input_lines "
            "WHERE tenant_id = :tid AND farm_id = :fid AND graded_produce_lot_id = ANY(:ids) "
            "ORDER BY packing_event_id, graded_produce_lot_id"
        ),
        {"tid": tenant_id, "fid": farm_id, "ids": graded_produce_lot_ids},
    ).mappings().all()
    return [dict(r) for r in rows]


def _packing_input_lines_for_packing_events(
    conn: Connection, *, tenant_id, farm_id, packing_event_ids: list[uuid.UUID]
) -> list[dict]:
    """POSTHARVEST-OPS-001E: replaces the two ad-hoc raw-SQL blocks
    `traceability_service.py` used to run directly against
    `packing_input_lines` (keyed by `packing_event_id`, not by produce-lot
    id) -- same GPL/GradingEvent join as `_packing_input_lines_for_
    produce_lots` above, centralized here so the join is written exactly
    once. Returns the same `harvested_produce_lot_id`-keyed shape
    `traceability_service.py`'s own response contract already exposes, so
    neither of its two call sites needs any response-shape change.

    POSTHARVEST-OPS-001F: also returns `graded_produce_lot_id`, so the
    public traceability response can expose GPL identity directly instead
    of only the HPL it was graded from."""
    if not packing_event_ids:
        return []
    rows = conn.execute(
        text(
            "SELECT pil.id AS packing_input_line_id, pil.packing_event_id, pil.graded_produce_lot_id, "
            "ge.source_harvested_produce_lot_id AS harvested_produce_lot_id, "
            "pil.consumed_weight_kg, pil.consumed_whole_unit_count "
            "FROM packing_input_lines pil "
            "JOIN graded_produce_lots gpl ON gpl.id = pil.graded_produce_lot_id "
            "  AND gpl.tenant_id = pil.tenant_id AND gpl.farm_id = pil.farm_id "
            "JOIN grading_events ge ON ge.id = gpl.grading_event_id "
            "  AND ge.tenant_id = gpl.tenant_id AND ge.farm_id = gpl.farm_id "
            "WHERE pil.tenant_id = :tid AND pil.farm_id = :fid AND pil.packing_event_id = ANY(:ids) "
            "ORDER BY pil.packing_event_id, ge.source_harvested_produce_lot_id"
        ),
        {"tid": tenant_id, "fid": farm_id, "ids": packing_event_ids},
    ).mappings().all()
    return [dict(r) for r in rows]


# --- Graded produce lots / grading events (POSTHARVEST-OPS-001F) -----------


def _graded_produce_lots_by_ids(
    conn: Connection, *, tenant_id, farm_id, graded_produce_lot_ids: list[uuid.UUID]
) -> list[dict]:
    """Full public-traceability detail for an explicit set of GPL ids --
    used once GPL ids are already known (from packing input lines), never
    a produce-lot- or grading-event-keyed lookup, so distinct GPLs graded
    from the same HPL (or the same GradingEvent) are never collapsed."""
    if not graded_produce_lot_ids:
        return []
    rows = conn.execute(
        text(
            "SELECT id AS graded_produce_lot_id, code, grading_event_id, crop_id, variety_id, "
            "grade_definition_version_id, original_received_weight_kg, original_received_whole_unit_count, "
            "effective_time FROM graded_produce_lots "
            "WHERE tenant_id = :tid AND farm_id = :fid AND id = ANY(:ids) ORDER BY effective_time, id"
        ),
        {"tid": tenant_id, "fid": farm_id, "ids": graded_produce_lot_ids},
    ).mappings().all()
    return [dict(r) for r in rows]


def _grading_events_by_ids(conn: Connection, *, tenant_id, farm_id, grading_event_ids: list[uuid.UUID]) -> list[dict]:
    """Full public-traceability detail for an explicit set of GradingEvent
    ids -- one GradingEvent may be the parent of several distinct
    GradedProduceLots (different grade outputs of one command); this
    helper is deduplicated by event id, never by GPL, so it is called once
    per distinct grading_event_id already collected from the GPL set.

    POSTHARVEST-OPS-001F correction: also returns the whole-unit-count
    sibling of each weight field (rejected/loss/sample/remainder) -- these
    already existed on `GradingEvent` (all-or-none per
    `ck_grading_events_count_mode_shape`) but were omitted from the first
    pass. No new database field; a weight-only (non-count-mode) grading
    event still returns every count field NULL."""
    if not grading_event_ids:
        return []
    rows = conn.execute(
        text(
            "SELECT id AS grading_event_id, source_harvested_produce_lot_id, effective_time, recorded_time, "
            "input_presented_weight_kg, input_presented_whole_unit_count, "
            "rejected_weight_kg, rejected_whole_unit_count, "
            "loss_weight_kg, loss_whole_unit_count, "
            "sample_weight_kg, sample_whole_unit_count, "
            "remainder_weight_kg, remainder_whole_unit_count FROM grading_events "
            "WHERE tenant_id = :tid AND farm_id = :fid AND id = ANY(:ids) ORDER BY effective_time, id"
        ),
        {"tid": tenant_id, "fid": farm_id, "ids": grading_event_ids},
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
# Callers intentionally do not call finished_goods_ledger_service or
# finished_goods_storage_service (both take a single lot and an ORM
# Session bound to the caller's own connection) -- doing so per lot would
# be N+1. These bulk helpers reproduce the identical canonical formulas --
# plain SUM(weight_delta_kg)/SUM(package_count_delta) for available, and
# SUM(place)-SUM(release) for total placed -- against the caller's own
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
