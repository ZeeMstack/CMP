"""Canonical produce-lot ledger reconstructibility validation (CMP-016A).

Standalone module: only `sqlalchemy` is imported (no `app.*` ORM/service
code), so it can run inside a bare Alembic environment with no application
runtime dependency. Consumers (`env.py`, the CMP-016A marker migration, and
tests) must not import this module via a normal `import`/`from` statement —
`migrations` is not an installed package (see `pyproject.toml`'s
`[tool.setuptools.packages.find] include = ["app*"]`) and the working
directory is not a reliable source of `sys.path` entries across every
invocation context (bare Alembic CLI, `alembic.command.*` called
programmatically from an arbitrary directory, and pytest). Load this file
by absolute path instead, e.g.:

    import importlib.util
    from pathlib import Path
    _path = Path(__file__).resolve().parent / "_produce_lot_ledger_validation.py"
    _spec = importlib.util.spec_from_file_location("cmp_produce_lot_ledger_validation", _path)
    plv = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(plv)

(adjust `.parent` to `.parent.parent` from `migrations/versions/*.py`).

Two validation modes, not one:

- `run_projection_validation`: validates only the `harvest_receipt` subset
  of `produce_lot_ledger_entries` — every other entry kind (e.g. CMP-015's
  `packing_consumption`) is ignored. Safe to run whenever the current
  schema still supports those other kinds (CMP-016A's own upgrade/
  downgrade, or general integrity checks at head).
- `run_crossing_validation`: projection validation plus a rejection of any
  row whose `entry_kind` is not `harvest_receipt` — correct only at the
  exact boundary where `de82132ef837.downgrade()` is about to run, since
  the destination CMP-013 schema cannot represent any other kind at all.

Eight distinguishable violation categories, one query (or query pair) each
— never lumped together, so a test or operator can tell which structural
invariant actually broke:

- ``lot_missing_harvest_receipt`` — a produce lot with zero receipts.
- ``extra_harvest_receipt`` — a receipt whose ``produce_lot_id`` and
  ``harvest_event_id`` each individually resolve to a real, existing row,
  but not to *each other* (the lot's own real event differs) — a
  bijection-pairing violation, distinct from an orphan (nothing real) and
  from a plain field mismatch on an otherwise-correctly-matched row.
- ``orphan_harvest_receipt_missing_lot`` — ``produce_lot_id`` resolves to
  no real row at all.
- ``orphan_harvest_receipt_missing_event`` — ``produce_lot_id`` is real,
  but ``harvest_event_id`` resolves to no real row at all.
- ``duplicate_harvest_receipt_by_lot`` — more than one receipt for one
  ``produce_lot_id``.
- ``duplicate_harvest_receipt_by_event`` — more than one receipt for one
  ``harvest_event_id``.
- ``harvest_receipt_projection_mismatch`` — a receipt matched to its real
  lot (by ``produce_lot_id``) whose fields (id, tenant, farm, weight,
  count, effective/recorded time, actor, note, or a *real-but-wrong*
  ``harvest_event_id``) do not exactly reconstruct from the lot/event.
- ``unsupported_entry_kind_at_crossing`` — crossing-only: any entry kind
  other than ``harvest_receipt`` (e.g. a legitimate CMP-015
  ``packing_consumption`` row), which the CMP-013 schema a crossing
  downgrade lands on cannot represent at all.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

# The historical revision whose own downgrade() must never run against
# malformed history. Never modified; this module exists to guard it from
# the outside instead.
PRODUCE_LOT_LEDGER_REVISION = "de82132ef837"

# Tables the crossing guard locks and validates against, in this exact
# deterministic (alphabetical) order.
GUARDED_TABLES = ("harvest_events", "harvested_produce_lots", "produce_lot_ledger_entries")

_TABLE = "produce_lot_ledger_entries"

# Null-safe (IS DISTINCT FROM throughout) field-equality predicate for a
# harvest_receipt row matched to its own real lot, excluding the bijection-
# pairing case (extra_harvest_receipt) which is checked separately so the
# two categories never collide.
_MISMATCH_PREDICATE = """
    r.id IS DISTINCT FROM lot.id
    OR r.tenant_id IS DISTINCT FROM lot.tenant_id
    OR r.farm_id IS DISTINCT FROM lot.farm_id
    OR r.harvest_event_id IS DISTINCT FROM lot.harvest_event_id
    OR r.weight_delta_kg IS DISTINCT FROM lot.total_harvested_weight_kg
    OR r.whole_unit_count_delta IS DISTINCT FROM lot.total_whole_unit_count
    OR r.effective_time IS DISTINCT FROM lot.effective_time
    OR r.recorded_time IS DISTINCT FROM lot.recorded_at
    OR r.actor_user_id IS DISTINCT FROM event.actor_user_id
    OR r.note IS NOT NULL
"""


def table_exists(conn: Connection, name: str = _TABLE) -> bool:
    return (
        conn.execute(
            text("SELECT 1 FROM information_schema.tables WHERE table_name = :n"), {"n": name}
        ).first()
        is not None
    )


def count_missing(conn: Connection) -> int:
    """State 1: a produce lot with zero harvest_receipt rows."""
    return conn.execute(
        text(
            "SELECT count(*) FROM harvested_produce_lots lot "
            "LEFT JOIN produce_lot_ledger_entries r "
            "  ON r.produce_lot_id = lot.id AND r.entry_kind = 'harvest_receipt' "
            "WHERE r.id IS NULL"
        )
    ).scalar_one()


def count_projection_mismatch(conn: Connection) -> int:
    """States 7-10, 12-17: a receipt matched to its real lot (by
    produce_lot_id) whose fields do not exactly reconstruct — including a
    real-but-wrong harvest_event_id (state 10), which is a field mismatch
    on an otherwise-correctly-matched row, not a bijection-pairing
    violation (see count_extra)."""
    return conn.execute(
        text(
            "SELECT count(*) FROM harvested_produce_lots lot "
            "JOIN harvest_events event ON event.id = lot.harvest_event_id "
            "JOIN produce_lot_ledger_entries r "
            "  ON r.produce_lot_id = lot.id AND r.entry_kind = 'harvest_receipt' "
            f"WHERE ({_MISMATCH_PREDICATE})"
        )
    ).scalar_one()


def count_extra(conn: Connection) -> int:
    """State 2: a receipt whose produce_lot_id and harvest_event_id each
    individually resolve to a real, existing row, but not to each other
    (the lot's own real harvest_event_id differs). Both foreign keys are
    genuinely satisfiable — nothing is fabricated — yet the row is not the
    unique deterministic receipt expected for either parent: a bijection-
    pairing violation, not an orphan (count_orphan_*, where a parent does
    not exist at all) and not a duplicate (count_duplicate_*, where more
    than one row shares a key)."""
    return conn.execute(
        text(
            "SELECT count(*) FROM produce_lot_ledger_entries r "
            "JOIN harvested_produce_lots lot ON lot.id = r.produce_lot_id "
            "JOIN harvest_events event ON event.id = r.harvest_event_id "
            "WHERE r.entry_kind = 'harvest_receipt' AND lot.harvest_event_id <> r.harvest_event_id"
        )
    ).scalar_one()


def count_orphan_missing_lot(conn: Connection) -> int:
    """State 3: produce_lot_id resolves to no real harvested_produce_lots
    row at all."""
    return conn.execute(
        text(
            "SELECT count(*) FROM produce_lot_ledger_entries r "
            "WHERE r.entry_kind = 'harvest_receipt' "
            "AND NOT EXISTS (SELECT 1 FROM harvested_produce_lots lot WHERE lot.id = r.produce_lot_id)"
        )
    ).scalar_one()


def count_orphan_missing_event(conn: Connection) -> int:
    """State 4: produce_lot_id is real, but harvest_event_id resolves to
    no real harvest_events row at all."""
    return conn.execute(
        text(
            "SELECT count(*) FROM produce_lot_ledger_entries r "
            "WHERE r.entry_kind = 'harvest_receipt' "
            "AND EXISTS (SELECT 1 FROM harvested_produce_lots lot WHERE lot.id = r.produce_lot_id) "
            "AND NOT EXISTS (SELECT 1 FROM harvest_events event WHERE event.id = r.harvest_event_id)"
        )
    ).scalar_one()


def count_duplicate_by_lot(conn: Connection) -> int:
    """State 5: more than one harvest_receipt row for one produce_lot_id.
    Unreachable through ordinary operation (the deterministic-id CHECK
    plus the lot-scoped partial unique index both forbid it) — defence in
    depth against already-corrupted state."""
    return conn.execute(
        text(
            "SELECT count(*) FROM ("
            "  SELECT produce_lot_id FROM produce_lot_ledger_entries "
            "  WHERE entry_kind = 'harvest_receipt' GROUP BY produce_lot_id HAVING count(*) > 1"
            ") dup"
        )
    ).scalar_one()


def count_duplicate_by_event(conn: Connection) -> int:
    """State 6: more than one harvest_receipt row for one harvest_event_id."""
    return conn.execute(
        text(
            "SELECT count(*) FROM ("
            "  SELECT harvest_event_id FROM produce_lot_ledger_entries "
            "  WHERE entry_kind = 'harvest_receipt' GROUP BY harvest_event_id HAVING count(*) > 1"
            ") dup"
        )
    ).scalar_one()


def count_unsupported_entry_kind(conn: Connection) -> int:
    """State 11, crossing boundary only: any entry_kind other than
    harvest_receipt (e.g. packing_consumption) cannot be represented by
    the CMP-013 schema a crossing downgrade lands on."""
    return conn.execute(
        text(f"SELECT count(*) FROM {_TABLE} WHERE entry_kind <> 'harvest_receipt'")
    ).scalar_one()


def run_projection_validation(conn: Connection) -> list[str]:
    """Harvest-receipt-subset validation. Ignores any other entry kind, so
    legitimate CMP-015 packing_consumption rows never fail this check."""
    if not table_exists(conn):
        return []
    violations = []
    if count_missing(conn) > 0:
        violations.append("lot_missing_harvest_receipt")
    if count_extra(conn) > 0:
        violations.append("extra_harvest_receipt")
    if count_orphan_missing_lot(conn) > 0:
        violations.append("orphan_harvest_receipt_missing_lot")
    if count_orphan_missing_event(conn) > 0:
        violations.append("orphan_harvest_receipt_missing_event")
    if count_duplicate_by_lot(conn) > 0:
        violations.append("duplicate_harvest_receipt_by_lot")
    if count_duplicate_by_event(conn) > 0:
        violations.append("duplicate_harvest_receipt_by_event")
    if count_projection_mismatch(conn) > 0:
        violations.append("harvest_receipt_projection_mismatch")
    return violations


def run_crossing_validation(conn: Connection) -> list[str]:
    """Projection validation plus the kind check that is only correct at
    the exact de82132ef837 downgrade boundary."""
    violations = run_projection_validation(conn)
    if table_exists(conn) and count_unsupported_entry_kind(conn) > 0:
        violations.append("unsupported_entry_kind_at_crossing")
    return violations
