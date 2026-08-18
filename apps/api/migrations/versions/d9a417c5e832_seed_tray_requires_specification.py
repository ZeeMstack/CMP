"""seed tray requires specification

CARRIER-CONFIG-001A -- completes the seed_tray specification rollout that
CARRIER-CONFIG-001 (e5b8c3a72f04) deliberately deferred: flips
`carrier_types.requires_specification` from `false` to `true` for the
`seed_tray` CarrierType only. No other `carrier_types` row is touched.

This is a pure metadata flip -- no new table, no new trigger, no new CHECK
constraint, no backfill of `carriers.specification_id` for legacy rows.
Every pre-existing `seed_tray` Carrier keeps `specification_id = NULL`
(CLAUDE.md rule 7: never rewrite history) and remains fully valid; only NEW
`seed_tray` Carrier registrations are affected, enforced entirely in
`carrier_service._resolve_carrier_type_and_specification` (application
layer), exactly as `requires_specification` already works for every other
CarrierType. `carrier_types.code` already carries a DB-level
`unique=True` constraint (see `app/models/carrier_type.py`), so the
`UPDATE ... WHERE code = 'seed_tray'` below is expected to affect exactly
one row on both upgrade and downgrade; both directions fail fast via
`rowcount` if that ever stops being true (e.g. the seed_tray row is
missing or was renamed), rather than silently doing nothing.

Revision ID: d9a417c5e832
Revises: e5b8c3a72f04
Create Date: 2026-08-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd9a417c5e832'
down_revision: Union[str, None] = 'e5b8c3a72f04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    result = bind.execute(
        sa.text("UPDATE carrier_types SET requires_specification = true WHERE code = 'seed_tray'")
    )
    if result.rowcount != 1:
        raise RuntimeError(
            "CARRIER-CONFIG-001A: expected exactly 1 carrier_types row with code='seed_tray', "
            f"affected {result.rowcount}. Refusing to proceed -- the seed_tray row is missing, "
            "duplicated, or was renamed; this migration's assumption no longer holds."
        )


def downgrade() -> None:
    bind = op.get_bind()
    result = bind.execute(
        sa.text("UPDATE carrier_types SET requires_specification = false WHERE code = 'seed_tray'")
    )
    if result.rowcount != 1:
        raise RuntimeError(
            "CARRIER-CONFIG-001A: expected exactly 1 carrier_types row with code='seed_tray', "
            f"affected {result.rowcount}. Refusing to proceed -- the seed_tray row is missing, "
            "duplicated, or was renamed; this migration's assumption no longer holds."
        )
