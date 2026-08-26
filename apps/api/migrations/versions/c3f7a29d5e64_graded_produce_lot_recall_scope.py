"""graded produce lot recall scope

POSTHARVEST-OPS-001D: widens CMP-020's typed recall-case source from three
kinds to four -- `GradedProduceLot` becomes a first-class, independently
recallable containment source, with its own frozen scope table
(`recall_scope_graded_produce_lots`), exactly following the existing three
scope tables' conventions (`recall_scope_batches`/`recall_scope_produce_
lots`/`recall_scope_finished_goods_lots`): entity-ID-only rows, append-only,
no hard delete, structural reconciliation via the same shared deferred
constraint-trigger function (widened, not duplicated).

This ticket is recall containment only -- it adds no new consumption gate
(nothing yet consumes a `GradedProduceLot`; that is POSTHARVEST-OPS-001E),
so none of the four existing write-path containment triggers (batch
derivation, packing, storage release, dispatch) are touched here.

Revision ID: c3f7a29d5e64
Revises: f2c8a5d1e793
Create Date: 2026-08-26 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'c3f7a29d5e64'
down_revision: Union[str, None] = 'f2c8a5d1e793'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 1. recall_cases: widen typed source shape to four ---------------------------
    # Mirrors the existing three source columns exactly: a plain nullable
    # UUID column with no bare single-column FK (only the composite
    # tenant/farm-safe FK below provides referential integrity, the same
    # asymmetry `crop_batch_id`/`harvested_produce_lot_id`/
    # `finished_goods_lot_id` already have on this table).
    op.add_column(
        "recall_cases",
        sa.Column("graded_produce_lot_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_recall_cases_tenant_farm_graded_lot",
        "recall_cases", "graded_produce_lots",
        ["tenant_id", "farm_id", "graded_produce_lot_id"],
        ["tenant_id", "farm_id", "id"],
    )
    op.drop_constraint("ck_recall_cases_typed_source_shape", "recall_cases", type_="check")
    op.create_check_constraint(
        "ck_recall_cases_typed_source_shape",
        "recall_cases",
        "(CASE WHEN crop_batch_id IS NOT NULL THEN 1 ELSE 0 END) + "
        "(CASE WHEN harvested_produce_lot_id IS NOT NULL THEN 1 ELSE 0 END) + "
        "(CASE WHEN graded_produce_lot_id IS NOT NULL THEN 1 ELSE 0 END) + "
        "(CASE WHEN finished_goods_lot_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
    )

    # --- 2. recall_scope_graded_produce_lots ------------------------------------------
    op.create_table(
        "recall_scope_graded_produce_lots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("recall_case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("recall_cases.id"), nullable=False),
        sa.Column(
            "graded_produce_lot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("graded_produce_lots.id"),
            nullable=False,
        ),
        sa.Column("recorded_time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint(
            "recall_case_id", "graded_produce_lot_id", name="ux_recall_scope_graded_lots_case_lot"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "recall_case_id"],
            ["recall_cases.tenant_id", "recall_cases.farm_id", "recall_cases.id"],
            name="fk_recall_scope_graded_lots_tenant_farm_case",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "graded_produce_lot_id"],
            ["graded_produce_lots.tenant_id", "graded_produce_lots.farm_id", "graded_produce_lots.id"],
            name="fk_recall_scope_graded_lots_tenant_farm_lot",
        ),
    )
    op.create_index(
        "ix_recall_scope_graded_lots_tenant_farm_lot", "recall_scope_graded_produce_lots",
        ["tenant_id", "farm_id", "graded_produce_lot_id"],
    )
    op.execute(
        "CREATE TRIGGER recall_scope_graded_lots_no_update BEFORE UPDATE ON recall_scope_graded_produce_lots "
        "FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();"
    )
    op.execute(
        "CREATE TRIGGER recall_scope_graded_lots_no_delete BEFORE DELETE ON recall_scope_graded_produce_lots "
        "FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();"
    )

    # --- 3. widen structural reconciliation (CREATE OR REPLACE, same function) -------
    # Same shared function CMP-020 attached (as a deferred constraint
    # trigger) to `recall_cases` and its three original scope tables --
    # widened in place with a fourth ELSIF branch, never duplicated.
    # `CREATE OR REPLACE FUNCTION` preserves the function's OID, so the
    # three existing trigger attachments on `recall_cases`/
    # `recall_scope_batches`/`recall_scope_produce_lots`/
    # `recall_scope_finished_goods_lots` automatically pick up the widened
    # body with no trigger drop/recreate needed.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_recall_case_reconciliation() RETURNS trigger AS $$
        DECLARE
            v_case RECORD;
        BEGIN
            IF TG_TABLE_NAME = 'recall_cases' THEN
                SELECT * INTO v_case FROM recall_cases WHERE id = NEW.id;
            ELSE
                SELECT * INTO v_case FROM recall_cases WHERE id = NEW.recall_case_id;
            END IF;
            IF v_case.id IS NULL THEN
                RAISE EXCEPTION 'recall scope row references a recall case that does not resolve';
            END IF;

            IF v_case.crop_batch_id IS NOT NULL THEN
                IF NOT EXISTS (
                    SELECT 1 FROM recall_scope_batches
                    WHERE recall_case_id = v_case.id AND crop_batch_id = v_case.crop_batch_id
                ) THEN
                    RAISE EXCEPTION 'recall case % has a crop_batch_id source with no matching recall_scope_batches row', v_case.id;
                END IF;
            ELSIF v_case.harvested_produce_lot_id IS NOT NULL THEN
                IF NOT EXISTS (
                    SELECT 1 FROM recall_scope_produce_lots
                    WHERE recall_case_id = v_case.id AND harvested_produce_lot_id = v_case.harvested_produce_lot_id
                ) THEN
                    RAISE EXCEPTION 'recall case % has a harvested_produce_lot_id source with no matching recall_scope_produce_lots row', v_case.id;
                END IF;
            ELSIF v_case.graded_produce_lot_id IS NOT NULL THEN
                IF NOT EXISTS (
                    SELECT 1 FROM recall_scope_graded_produce_lots
                    WHERE recall_case_id = v_case.id AND graded_produce_lot_id = v_case.graded_produce_lot_id
                ) THEN
                    RAISE EXCEPTION 'recall case % has a graded_produce_lot_id source with no matching recall_scope_graded_produce_lots row', v_case.id;
                END IF;
            ELSIF v_case.finished_goods_lot_id IS NOT NULL THEN
                IF NOT EXISTS (
                    SELECT 1 FROM recall_scope_finished_goods_lots
                    WHERE recall_case_id = v_case.id AND finished_goods_lot_id = v_case.finished_goods_lot_id
                ) THEN
                    RAISE EXCEPTION 'recall case % has a finished_goods_lot_id source with no matching recall_scope_finished_goods_lots row', v_case.id;
                END IF;
            END IF;

            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER recall_scope_graded_produce_lots_enforce_recall_reconciliation
        AFTER INSERT ON recall_scope_graded_produce_lots
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_recall_case_reconciliation();
        """
    )


def downgrade() -> None:
    bind = op.get_bind()

    # --- downgrade guard: graded-lot recall history is independent compliance data ---
    # Same unconditional-block model the rest of CMP-020 already uses:
    # blocks if any graded-lot scope row exists, OR if any recall_cases
    # row still has a populated graded_produce_lot_id (the reconciliation
    # trigger should make these co-occur, but both are checked directly
    # rather than relying on that invariant holding for a downgrade guard).
    unsafe = bind.execute(
        sa.text(
            "SELECT "
            "(SELECT count(*) FROM recall_scope_graded_produce_lots) AS scope_count, "
            "(SELECT count(*) FROM recall_cases WHERE graded_produce_lot_id IS NOT NULL) AS typed_source_count"
        )
    ).mappings().first()
    if any(unsafe[k] > 0 for k in unsafe.keys()):
        raise RuntimeError(
            "Cannot downgrade past POSTHARVEST-OPS-001D: graded-produce-lot recall scope or typed-source "
            "history exists. Recall history is independent compliance data, never reconstructible from any "
            "other table. Do not downgrade."
        )

    # --- drop the new table's deferred reconciliation trigger -------------------------
    op.execute(
        "DROP TRIGGER IF EXISTS recall_scope_graded_produce_lots_enforce_recall_reconciliation "
        "ON recall_scope_graded_produce_lots"
    )

    # --- restore the exact CMP-020 (three-source) reconciliation function body -------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_recall_case_reconciliation() RETURNS trigger AS $$
        DECLARE
            v_case RECORD;
        BEGIN
            IF TG_TABLE_NAME = 'recall_cases' THEN
                SELECT * INTO v_case FROM recall_cases WHERE id = NEW.id;
            ELSE
                SELECT * INTO v_case FROM recall_cases WHERE id = NEW.recall_case_id;
            END IF;
            IF v_case.id IS NULL THEN
                RAISE EXCEPTION 'recall scope row references a recall case that does not resolve';
            END IF;

            IF v_case.crop_batch_id IS NOT NULL THEN
                IF NOT EXISTS (
                    SELECT 1 FROM recall_scope_batches
                    WHERE recall_case_id = v_case.id AND crop_batch_id = v_case.crop_batch_id
                ) THEN
                    RAISE EXCEPTION 'recall case % has a crop_batch_id source with no matching recall_scope_batches row', v_case.id;
                END IF;
            ELSIF v_case.harvested_produce_lot_id IS NOT NULL THEN
                IF NOT EXISTS (
                    SELECT 1 FROM recall_scope_produce_lots
                    WHERE recall_case_id = v_case.id AND harvested_produce_lot_id = v_case.harvested_produce_lot_id
                ) THEN
                    RAISE EXCEPTION 'recall case % has a harvested_produce_lot_id source with no matching recall_scope_produce_lots row', v_case.id;
                END IF;
            ELSIF v_case.finished_goods_lot_id IS NOT NULL THEN
                IF NOT EXISTS (
                    SELECT 1 FROM recall_scope_finished_goods_lots
                    WHERE recall_case_id = v_case.id AND finished_goods_lot_id = v_case.finished_goods_lot_id
                ) THEN
                    RAISE EXCEPTION 'recall case % has a finished_goods_lot_id source with no matching recall_scope_finished_goods_lots row', v_case.id;
                END IF;
            END IF;

            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # --- drop recall_scope_graded_produce_lots (cascades its own indexes/triggers) ---
    op.drop_table("recall_scope_graded_produce_lots")

    # --- restore the exact CMP-020 (three-source) typed source shape ----------------
    op.drop_constraint("ck_recall_cases_typed_source_shape", "recall_cases", type_="check")
    op.create_check_constraint(
        "ck_recall_cases_typed_source_shape",
        "recall_cases",
        "(CASE WHEN crop_batch_id IS NOT NULL THEN 1 ELSE 0 END) + "
        "(CASE WHEN harvested_produce_lot_id IS NOT NULL THEN 1 ELSE 0 END) + "
        "(CASE WHEN finished_goods_lot_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
    )
    op.drop_constraint("fk_recall_cases_tenant_farm_graded_lot", "recall_cases", type_="foreignkey")
    op.drop_column("recall_cases", "graded_produce_lot_id")
