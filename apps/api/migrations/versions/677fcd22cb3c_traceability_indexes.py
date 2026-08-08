"""traceability indexes

Revision ID: 677fcd22cb3c
Revises: dd8b86a52acf
Create Date: 2026-08-15 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = '677fcd22cb3c'
down_revision: Union[str, None] = 'dd8b86a52acf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # CMP-019: indexes only, no tables, no columns, no triggers, no data
    # rewritten. Each backs a real reverse-traversal predicate that CMP-019's
    # traceability service issues on every request and that no existing
    # unique constraint or primary key covers as a leading-column match:
    #
    # - packing_input_lines' only unique index is
    #   (packing_event_id, harvested_produce_lot_id) -- the produce-lot
    #   column is the *trailing* key, unusable for "find every packing
    #   input line for produce lot X" (forward trace: produce lot -> packing).
    # - dispatch_lines' only unique index is
    #   (dispatch_event_id, finished_goods_lot_id) -- same trailing-column
    #   problem for "find every dispatch line for finished-goods lot X"
    #   (both backward trace and forward impact).
    # - finished_goods_storage_movements has no index at all on
    #   finished_goods_lot_id (its FK constraints do not implicitly create
    #   one on the referencing side) -- needed for both a single lot's full
    #   movement history (backward trace) and a lot-set placement
    #   aggregate (forward impact).
    #
    # harvested_produce_lots.batch_id is deliberately NOT indexed here:
    # CMP-019 reaches produce lots through the authoritative
    # harvest_events.batch_id -> harvested_produce_lots.harvest_event_id
    # (UNIQUE) join, not through the batch_id snapshot column, and
    # harvest_events' own existing (tenant_id, farm_id, batch_id, id)
    # unique constraint already supports that first hop. Adding an index
    # on the snapshot column would only encourage bypassing the
    # authoritative relationship.
    #
    # batch_derivation_sources.source_batch_id and
    # batch_derivation_outputs.output_batch_id already carry their own
    # dedicated UNIQUE(single-column) indexes (CMP-012) -- no gap there.
    op.create_index(
        "ix_packing_input_lines_tenant_farm_produce_lot",
        "packing_input_lines",
        ["tenant_id", "farm_id", "harvested_produce_lot_id"],
    )
    op.create_index(
        "ix_dispatch_lines_tenant_farm_finished_goods_lot",
        "dispatch_lines",
        ["tenant_id", "farm_id", "finished_goods_lot_id"],
    )
    op.create_index(
        "ix_finished_goods_storage_movements_tenant_farm_lot",
        "finished_goods_storage_movements",
        ["tenant_id", "farm_id", "finished_goods_lot_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_finished_goods_storage_movements_tenant_farm_lot", table_name="finished_goods_storage_movements")
    op.drop_index("ix_dispatch_lines_tenant_farm_finished_goods_lot", table_name="dispatch_lines")
    op.drop_index("ix_packing_input_lines_tenant_farm_produce_lot", table_name="packing_input_lines")
