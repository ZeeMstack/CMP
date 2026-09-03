"""seed tray direct level compatibility

PILOT-UX-001B: Germination Level Capacity Model. A Germination Trolley
Level is an existing `shelf`-kind `AssetPosition` (see 5f3a9c2d1b44,
c2d6f8a4b153) -- no schema change is required to let a Level hold Seed
Trays directly, because DOMAIN-FARM-002 (f91c366cfe57) already made
`AssetPosition.capacity` a generic, row-locked, concurrency-safe N-occupant
mechanism. The ONLY reason a Seed Tray could not already occupy a Level
directly is that `occupancy_compatibility_rules` has never carried a
`carrier:seed_tray -> position:shelf` row -- only `carrier:seed_tray ->
position:slot` (8a2c6f1e9d33). This migration adds exactly that one row,
following the same additive, narrow, single-row pattern already used by
1ffda251c3a8 / a3f7c9d2e0b1 / b7e2f4a9c1d6 / c2d6f8a4b153. The existing
`seed_tray -> slot` row is left completely untouched -- legacy Trolley
Levels that still carry child Slot AssetPositions keep placing Seed Trays
into those Slots exactly as before; nothing here retargets, rewrites, or
removes any existing Level, Slot, Occupancy, or Movement.

IMPORTANT TRIPWIRE (see also docs/domain/ASSET_CARRIER_MODEL.md):
`occupancy_compatibility_rules.target_position_kind` carries no AssetType
scoping of its own -- it matches every AssetPosition of that `position_kind`
regardless of which Asset owns it (verified: neither
`movement_service._check_compatibility` nor this migration's own
`enforce_occupancy_insert_integrity` trigger join back to `assets`/
`asset_types` when resolving compatibility). This row is safe ONLY because
`germination_trolley` is currently the sole AssetType with
`supports_positions = TRUE` (set once, by 5f3a9c2d1b44, never changed by any
later migration) -- so no `shelf`-kind AssetPosition can exist under any
other Asset today. If a future ticket ever gives a second AssetType
`supports_positions = TRUE`, this compatibility rule's target-side model
(AssetType scoping) MUST be revisited before that ticket ships -- do not
assume this row stays safely scoped on its own.

Revision ID: b3bcfef4052e
Revises: 7473ab25731f
Create Date: 2026-09-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3bcfef4052e'
down_revision: Union[str, None] = '7473ab25731f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    seed_tray_type_id = bind.execute(
        sa.text("SELECT id FROM carrier_types WHERE code = 'seed_tray'")
    ).scalar_one()
    bind.execute(
        sa.text(
            "INSERT INTO occupancy_compatibility_rules "
            "(id, occupant_carrier_type_id, target_position_kind) "
            "VALUES (gen_random_uuid(), :occupant_id, 'shelf')"
        ),
        {"occupant_id": seed_tray_type_id},
    )


def downgrade() -> None:
    bind = op.get_bind()

    # --- downgrade guard: never leave live physical data the old model
    # cannot explain -- if any Seed Tray currently occupies a Level
    # (shelf-kind AssetPosition) directly, removing this compatibility row
    # would make that live state impossible to reproduce under the reverted
    # schema. Do not auto-move Trays off Levels to force the downgrade
    # through -- mirrors b7e2f4a9c1d6 / c2d6f8a4b153's own guard pattern.
    live_occupancy = bind.execute(
        sa.text(
            "SELECT count(*) FROM occupancies o "
            "JOIN carriers c ON c.id = o.occupant_carrier_id "
            "JOIN carrier_types ct ON ct.id = c.carrier_type_id AND ct.code = 'seed_tray' "
            "JOIN asset_positions p ON p.id = o.target_asset_position_id AND p.position_kind = 'shelf' "
            "WHERE o.end_time IS NULL"
        )
    ).scalar_one()
    if live_occupancy > 0:
        raise RuntimeError(
            "Cannot downgrade past PILOT-UX-001B: "
            f"{live_occupancy} Seed Tray(s) currently occupy a Germination Trolley Level directly. Removing "
            "the seed_tray -> shelf compatibility rule would leave this live physical state unreproducible "
            "under the reverted schema. Move the affected Tray(s) off their Level(s) out-of-band before "
            "downgrading, or do not downgrade."
        )

    seed_tray_type_id = bind.execute(
        sa.text("SELECT id FROM carrier_types WHERE code = 'seed_tray'")
    ).scalar_one()
    bind.execute(
        sa.text(
            "DELETE FROM occupancy_compatibility_rules "
            "WHERE occupant_carrier_type_id = :occupant_id AND target_position_kind = 'shelf'"
        ),
        {"occupant_id": seed_tray_type_id},
    )
