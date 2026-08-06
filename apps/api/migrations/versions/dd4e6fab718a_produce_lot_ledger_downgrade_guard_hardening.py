"""produce lot ledger downgrade guard hardening

Revision ID: dd4e6fab718a
Revises: b3f6e9a2d174
Create Date: 2026-08-06 12:00:00.000000

"""
import importlib.util
from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = 'dd4e6fab718a'
down_revision: Union[str, None] = 'b3f6e9a2d174'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _load_validation_module():
    # See _produce_lot_ledger_validation.py's own module docstring: loaded
    # by absolute path, not by a package-relative `import`, since
    # `migrations` is not an installed package and the working directory
    # is not a reliable sys.path source across every invocation context.
    path = Path(__file__).resolve().parent.parent / "_produce_lot_ledger_validation.py"
    spec = importlib.util.spec_from_file_location("cmp_produce_lot_ledger_validation", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# CMP-016A: a marker revision closing the gap in de82132ef837's (CMP-014)
# own downgrade() — it never had a receipt -> lot orphan check or a
# duplicate check, only a lot -> receipt "missing/mismatched" check
# (unlike its own upgrade() backfill validation, which does have all
# three). de82132ef837 is historical and is never edited. This revision
# adds NO schema, NO table, NO column: it is a marker that (a) proves
# current history is clean the moment it is applied/removed and (b)
# anchors the shared validation module import path. The durable,
# staged-downgrade-proof protection lives in migrations/env.py's
# pre-migration guard, which runs on every Alembic invocation regardless
# of which specific revisions currently exist in the database's history —
# a marker migration's own downgrade() cannot, by itself, protect a later,
# separate downgrade command issued after this revision has already been
# undone. See docs/domain/PRODUCE_LOT_LEDGER_MODEL.md.


def upgrade() -> None:
    plv = _load_validation_module()
    bind = op.get_bind()
    violations = plv.run_projection_validation(bind)
    if violations:
        raise RuntimeError(
            "CMP-016A cannot upgrade: existing produce_lot_ledger_entries history is not "
            f"exactly reconstructible ({', '.join(violations)}). Repair the offending rows "
            "out-of-band before upgrading."
        )


def downgrade() -> None:
    # Defence in depth for the one-shot downgrade path (this revision's own
    # downgrade() still runs when the walk passes through it). Projection-
    # only: downgrading CMP-016A -> CMP-016 removes neither the produce-lot
    # ledger nor packing behavior, so legitimate packing_consumption rows
    # must not block it.
    plv = _load_validation_module()
    bind = op.get_bind()
    violations = plv.run_projection_validation(bind)
    if violations:
        raise RuntimeError(
            "Cannot downgrade past CMP-016A: existing produce_lot_ledger_entries history is "
            f"not exactly reconstructible ({', '.join(violations)}). Downgrading would risk "
            "silently discarding or misrepresenting ledger history. Do not downgrade."
        )
