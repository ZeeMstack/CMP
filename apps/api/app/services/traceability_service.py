"""CMP-019 read-only traceability service.

Every public function here opens its own short-lived, dedicated connection
in a PostgreSQL REPEATABLE READ, READ ONLY transaction (see
`_snapshot_connection`), and every query the trace issues -- including
tenant/farm and subject-existence validation -- runs on that one
connection/snapshot. This guarantees a trace response is never a mix of
pre- and post-commit state relative to a concurrent dispatch or storage
movement. The router's own injected `Session` is used only to authenticate
the tenant/user context (`require_tenant_context`); it never touches
trace data.

No table here is written to. No audit event is appended for a read. No
proportional attribution is invented anywhere in this module -- every
"potentially affected" downstream quantity is a finished-goods lot's own
entire current quantity, never a fraction derived from an upstream input.
"""
import uuid
from decimal import Decimal

from sqlalchemy import Connection, Engine, text

from app.services.errors import (
    CropBatchNotFoundError,
    FarmNotFoundError,
    FinishedGoodsLotNotFoundError,
    HarvestedProduceLotNotFoundError,
    TraceabilityIntegrityError,
)
from app.services.lineage_traversal import (
    _batch_lineage_closure,
    _batch_lineage_edges,
    _batch_lineage_nodes,
    _bulk_available,
    _bulk_dispatch_lines,
    _bulk_location_balances,
    _bulk_placed,
    _bulk_storage_movements,
    _finished_goods_lots_for_packing_events,
    _graded_produce_lots_by_ids,
    _grading_events_by_ids,
    _harvest_events_for_batches,
    _packing_events,
    _packing_input_lines_for_packing_events,
    _packing_input_lines_for_produce_lots,
    _produce_lots_for_harvest_events,
    _quality_holds_for_batches,
    _seed_origins_for_batches,
    _snapshot_connection,
)


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
        packing_inputs = _packing_input_lines_for_packing_events(
            conn, tenant_id=tenant_id, farm_id=farm_id, packing_event_ids=[lot["packing_event_id"]]
        )

        # POSTHARVEST-OPS-001F: GPL is a first-class traceability entity --
        # every source GraduatedProduceLot this FG lot's packing event
        # consumed, and every GradingEvent that produced one, resolved
        # directly rather than left implicit behind the HPL join.
        graded_produce_lot_ids = sorted({r["graded_produce_lot_id"] for r in packing_inputs})
        graded_produce_lots = _graded_produce_lots_by_ids(
            conn, tenant_id=tenant_id, farm_id=farm_id, graded_produce_lot_ids=graded_produce_lot_ids
        )
        if len(graded_produce_lots) != len(graded_produce_lot_ids):
            raise TraceabilityIntegrityError(
                f"packing event {lot['packing_event_id']} has an input line referencing a graded "
                "produce lot that does not resolve; this violates the schema's own FK guarantee."
            )
        grading_event_ids = sorted({g["grading_event_id"] for g in graded_produce_lots})
        grading_events = _grading_events_by_ids(
            conn, tenant_id=tenant_id, farm_id=farm_id, grading_event_ids=grading_event_ids
        )
        if len(grading_events) != len(grading_event_ids):
            raise TraceabilityIntegrityError(
                f"a graded produce lot feeding finished-goods lot {finished_goods_lot_id} references a "
                "grading event that does not resolve; this violates the schema's own FK guarantee."
            )

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
            "graded_produce_lots": graded_produce_lots,
            "grading_events": grading_events,
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
    packing_inputs = _packing_input_lines_for_packing_events(
        conn, tenant_id=tenant_id, farm_id=farm_id, packing_event_ids=affected_packing_event_ids
    )
    for r in packing_inputs:
        r["is_affected_source"] = r["harvested_produce_lot_id"] in affected_produce_lot_ids

    # POSTHARVEST-OPS-001F: GPL is a first-class traceability entity in the
    # forward direction too -- every GraduatedProduceLot reached through an
    # affected or context packing input line, resolved directly rather than
    # left implicit behind the HPL join. A GPL is affected iff its own one
    # source HPL is affected (a GPL always has exactly one source HPL via
    # its GradingEvent), so `is_affected_source` here mirrors the same flag
    # already computed per packing input line above.
    graded_produce_lot_ids = sorted({r["graded_produce_lot_id"] for r in packing_inputs})
    affected_graded_produce_lot_ids = {r["graded_produce_lot_id"] for r in packing_inputs if r["is_affected_source"]}
    graded_produce_lots_rows = _graded_produce_lots_by_ids(
        conn, tenant_id=tenant_id, farm_id=farm_id, graded_produce_lot_ids=graded_produce_lot_ids
    )
    if len(graded_produce_lots_rows) != len(graded_produce_lot_ids):
        raise TraceabilityIntegrityError(
            "a packing input line references a graded produce lot that does not resolve; this violates "
            "the schema's own FK guarantee."
        )
    graded_produce_lots = [
        dict(r) | {"is_affected_source": r["graded_produce_lot_id"] in affected_graded_produce_lot_ids}
        for r in graded_produce_lots_rows
    ]

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
        "affected_graded_produce_lot_count": len(affected_graded_produce_lot_ids),
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
        "graded_produce_lots": graded_produce_lots,
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
            "graded_produce_lots": downstream["graded_produce_lots"],
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
            "graded_produce_lots": downstream["graded_produce_lots"],
            "finished_goods": downstream["finished_goods"],
            "storage": downstream["storage"],
            "dispatches": downstream["dispatches"],
            "summary": downstream["summary"],
            "completeness": {"trace_complete": True, "limitations": [], "capability_limitations": ["recipient_not_modeled"]},
        }
