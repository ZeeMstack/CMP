"""dispatch temperature

Revision ID: 2cd787662e3d
Revises: f823982f465a
Create Date: 2026-08-28 09:00:00.000000

PILOT-READY-001: one factual Celsius reading per DispatchEvent (whole
dispatch/vehicle), never per FinishedGoodsLot/dispatch line/product/
container. `dispatch_events.dispatch_temperature_c` is added NULLable at
the DB layer only -- this never fabricates a reading for any row that
predates this column; every dispatch created through
`DispatchEventCreate` from this point on is required (at the Pydantic
schema layer, see `app.schemas.dispatch`) to supply a real value, so in
practice every row inserted after this migration has one. No backfill is
performed (none is possible without inventing history). The CHECK
constraint is a data-sanity bound only (rejects obviously-garbage input),
not a cold-chain acceptability threshold -- no pass/fail semantics.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2cd787662e3d"
down_revision: Union[str, None] = "f823982f465a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CHECK_NAME = "ck_dispatch_events_temperature_sane_range"
_CHECK_BODY = "dispatch_temperature_c IS NULL OR (dispatch_temperature_c > -100 AND dispatch_temperature_c < 100)"


def upgrade() -> None:
    op.add_column("dispatch_events", sa.Column("dispatch_temperature_c", sa.Numeric(), nullable=True))
    op.create_check_constraint(_CHECK_NAME, "dispatch_events", _CHECK_BODY)


def downgrade() -> None:
    op.drop_constraint(_CHECK_NAME, "dispatch_events", type_="check")
    op.drop_column("dispatch_events", "dispatch_temperature_c")
