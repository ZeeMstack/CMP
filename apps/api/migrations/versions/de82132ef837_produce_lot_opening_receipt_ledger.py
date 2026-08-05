"""produce lot opening receipt ledger

Revision ID: de82132ef837
Revises: c7f14b8e29a3
Create Date: 2026-08-05 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'de82132ef837'
down_revision: Union[str, None] = 'c7f14b8e29a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# One shared field-equality predicate: a harvest_receipt row is a
# deterministic, reconstructible projection of its produce lot and harvest
# event. Used both to verify the migration's own backfill and, again, as
# the downgrade guard's "is every receipt exactly reconstructible" check.
_RECEIPT_MISMATCH_PREDICATE = """
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


def upgrade() -> None:
    # --- produce_lot_ledger_entries (immutable) ---------------------------------
    op.create_table(
        "produce_lot_ledger_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column(
            "produce_lot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("harvested_produce_lots.id"),
            nullable=False,
        ),
        sa.Column(
            "harvest_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("harvest_events.id"), nullable=False
        ),
        sa.Column("entry_kind", sa.String(), nullable=False),
        sa.Column("weight_delta_kg", sa.Numeric(), nullable=False),
        sa.Column("whole_unit_count_delta", sa.BigInteger(), nullable=True),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.CheckConstraint("entry_kind IN ('harvest_receipt')", name="ck_produce_lot_ledger_entries_kind_allowed"),
        sa.CheckConstraint(
            "weight_delta_kg > 0 AND weight_delta_kg = trunc(weight_delta_kg, 3) "
            "AND weight_delta_kg < 100000000000",
            name="ck_produce_lot_ledger_entries_weight_envelope",
        ),
        sa.CheckConstraint(
            "whole_unit_count_delta IS NULL OR whole_unit_count_delta > 0",
            name="ck_produce_lot_ledger_entries_count_positive",
        ),
        sa.CheckConstraint(
            "entry_kind <> 'harvest_receipt' OR note IS NULL",
            name="ck_produce_lot_ledger_entries_receipt_note_null",
        ),
        sa.UniqueConstraint(
            "tenant_id", "farm_id", "id", name="uq_produce_lot_ledger_entries_tenant_farm_id"
        ),
        # No composite (tenant_id, farm_id, produce_lot_id) FK here:
        # harvested_produce_lots (CMP-013) has no (tenant_id, farm_id, id)
        # unique constraint to reference (unlike harvest_events, below) —
        # and the CMP-013 migration must not be modified to add one.
        # produce_lot_id's plain single-column FK (declared on the column
        # itself, referencing harvested_produce_lots.id) proves the lot
        # exists; tenant/farm consistency against the lot is instead proven
        # by enforce_produce_lot_ledger_entry_insert_integrity below.
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "harvest_event_id"],
            ["harvest_events.tenant_id", "harvest_events.farm_id", "harvest_events.id"],
            name="fk_produce_lot_ledger_entries_tenant_farm_event",
        ),
    )
    # Partial (kind-scoped), not table-wide: a future consumption entry
    # kind must be able to reference the same lot/event repeatedly without
    # being blocked by this ticket's one-receipt-per-lot rule.
    op.create_index(
        "ux_produce_lot_ledger_entries_lot_harvest_receipt", "produce_lot_ledger_entries", ["produce_lot_id"],
        unique=True, postgresql_where=sa.text("entry_kind = 'harvest_receipt'"),
    )
    op.create_index(
        "ux_produce_lot_ledger_entries_event_harvest_receipt", "produce_lot_ledger_entries", ["harvest_event_id"],
        unique=True, postgresql_where=sa.text("entry_kind = 'harvest_receipt'"),
    )

    # --- backfill: one deterministic opening receipt per existing lot ----------
    # id and produce_lot_id both equal the lot's own id; recorded_time comes
    # from the lot's own recorded_at (not a fresh default) so live creation
    # and this backfill always produce identical rows; note is always NULL.
    op.execute(
        """
        INSERT INTO produce_lot_ledger_entries (
            id, tenant_id, farm_id, produce_lot_id, harvest_event_id, entry_kind,
            weight_delta_kg, whole_unit_count_delta, effective_time, recorded_time, actor_user_id, note
        )
        SELECT
            lot.id, lot.tenant_id, lot.farm_id, lot.id, lot.harvest_event_id, 'harvest_receipt',
            lot.total_harvested_weight_kg, lot.total_whole_unit_count, lot.effective_time, lot.recorded_at,
            event.actor_user_id, NULL
        FROM harvested_produce_lots lot
        JOIN harvest_events event ON event.id = lot.harvest_event_id
        """
    )

    # --- verify the complete backfill before enabling deferred enforcement -----
    bind = op.get_bind()

    lot_count, receipt_count = bind.execute(
        sa.text(
            "SELECT (SELECT count(*) FROM harvested_produce_lots), "
            "(SELECT count(*) FROM produce_lot_ledger_entries WHERE entry_kind = 'harvest_receipt')"
        )
    ).one()
    if lot_count != receipt_count:
        raise RuntimeError(
            f"CMP-014 backfill failed: {lot_count} harvested produce lots but {receipt_count} harvest "
            f"receipts were created. Aborting before enabling deferred enforcement."
        )

    mismatch_count = bind.execute(
        sa.text(
            "SELECT count(*) FROM harvested_produce_lots lot "
            "JOIN harvest_events event ON event.id = lot.harvest_event_id "
            "LEFT JOIN produce_lot_ledger_entries r "
            "  ON r.produce_lot_id = lot.id AND r.entry_kind = 'harvest_receipt' "
            f"WHERE r.id IS NULL OR ({_RECEIPT_MISMATCH_PREDICATE})"
        )
    ).scalar_one()
    if mismatch_count > 0:
        raise RuntimeError(
            f"CMP-014 backfill failed: {mismatch_count} harvested produce lot(s) have a missing or "
            f"field-mismatched harvest receipt. Aborting before enabling deferred enforcement."
        )

    orphan_count = bind.execute(
        sa.text(
            "SELECT count(*) FROM produce_lot_ledger_entries r "
            "WHERE r.entry_kind = 'harvest_receipt' "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM harvested_produce_lots lot "
            "  WHERE lot.id = r.produce_lot_id AND lot.harvest_event_id = r.harvest_event_id"
            ")"
        )
    ).scalar_one()
    if orphan_count > 0:
        raise RuntimeError(
            f"CMP-014 backfill failed: {orphan_count} harvest receipt(s) reference no matching produce "
            f"lot/event. Aborting before enabling deferred enforcement."
        )

    # --- immediate insert-integrity trigger -------------------------------------
    op.execute(
        """
        CREATE FUNCTION enforce_produce_lot_ledger_entry_insert_integrity() RETURNS trigger AS $$
        DECLARE
            v_lot_tenant_id UUID;
            v_lot_farm_id UUID;
            v_lot_event_id UUID;
            v_lot_weight NUMERIC;
            v_lot_count BIGINT;
            v_lot_effective TIMESTAMPTZ;
            v_lot_recorded TIMESTAMPTZ;
            v_event_actor UUID;
        BEGIN
            SELECT tenant_id, farm_id, harvest_event_id, total_harvested_weight_kg, total_whole_unit_count,
                   effective_time, recorded_at
            INTO v_lot_tenant_id, v_lot_farm_id, v_lot_event_id, v_lot_weight, v_lot_count, v_lot_effective,
                 v_lot_recorded
            FROM harvested_produce_lots WHERE id = NEW.produce_lot_id;
            IF v_lot_tenant_id IS NULL THEN
                RAISE EXCEPTION 'produce lot not found for ledger entry';
            END IF;
            IF v_lot_tenant_id <> NEW.tenant_id OR v_lot_farm_id <> NEW.farm_id THEN
                RAISE EXCEPTION 'ledger entry tenant/farm does not match the produce lot''s own';
            END IF;
            IF v_lot_event_id <> NEW.harvest_event_id THEN
                RAISE EXCEPTION 'ledger entry harvest event does not match the produce lot''s own event';
            END IF;

            SELECT actor_user_id INTO v_event_actor FROM harvest_events WHERE id = NEW.harvest_event_id;
            IF v_event_actor IS NULL THEN
                RAISE EXCEPTION 'harvest event not found for ledger entry';
            END IF;

            IF NEW.entry_kind = 'harvest_receipt' THEN
                IF NEW.id <> NEW.produce_lot_id THEN
                    RAISE EXCEPTION 'harvest receipt id must equal its produce lot id';
                END IF;
                IF NEW.weight_delta_kg <> v_lot_weight THEN
                    RAISE EXCEPTION 'harvest receipt weight does not match the produce lot''s total weight';
                END IF;
                IF NEW.whole_unit_count_delta IS DISTINCT FROM v_lot_count THEN
                    RAISE EXCEPTION 'harvest receipt count does not match the produce lot''s total count';
                END IF;
                IF NEW.actor_user_id <> v_event_actor THEN
                    RAISE EXCEPTION 'harvest receipt actor does not match the harvest event''s actor';
                END IF;
                IF NEW.effective_time <> v_lot_effective THEN
                    RAISE EXCEPTION 'harvest receipt effective time does not match the produce lot''s effective time';
                END IF;
                IF NEW.recorded_time <> v_lot_recorded THEN
                    RAISE EXCEPTION 'harvest receipt recorded time does not match the produce lot''s recorded time';
                END IF;
                IF NEW.note IS NOT NULL THEN
                    RAISE EXCEPTION 'harvest receipt note must be null';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER produce_lot_ledger_entries_enforce_insert_integrity
        BEFORE INSERT ON produce_lot_ledger_entries
        FOR EACH ROW EXECUTE FUNCTION enforce_produce_lot_ledger_entry_insert_integrity();
        """
    )
    op.execute(
        """
        CREATE TRIGGER produce_lot_ledger_entries_no_update
        BEFORE UPDATE ON produce_lot_ledger_entries
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER produce_lot_ledger_entries_no_delete
        BEFORE DELETE ON produce_lot_ledger_entries
        FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();
        """
    )

    # --- deferred reconciliation --------------------------------------------------
    # One shared function, attached via two DEFERRABLE INITIALLY DEFERRED
    # constraint triggers, so any insert — even direct SQL against an
    # already-committed lot, in a later transaction — re-validates complete
    # field equality between the lot/event and its exactly-one receipt at
    # commit. harvest_events gets no third attachment here: CMP-013 already
    # guarantees exactly one lot per event, and this reconciliation
    # guarantees exactly one receipt per lot, so event-to-receipt 1:1 holds
    # transitively without re-checking the same invariant a third time.
    op.execute(
        f"""
        CREATE FUNCTION enforce_produce_lot_ledger_reconciliation() RETURNS trigger AS $$
        DECLARE
            v_lot_id UUID;
            v_receipt_count INTEGER;
            v_mismatch_count INTEGER;
        BEGIN
            IF TG_TABLE_NAME = 'harvested_produce_lots' THEN
                v_lot_id := NEW.id;
            ELSIF TG_TABLE_NAME = 'produce_lot_ledger_entries' THEN
                v_lot_id := NEW.produce_lot_id;
            END IF;

            IF v_lot_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT count(*) INTO v_receipt_count
            FROM produce_lot_ledger_entries
            WHERE produce_lot_id = v_lot_id AND entry_kind = 'harvest_receipt';
            IF v_receipt_count <> 1 THEN
                RAISE EXCEPTION 'produce lot % must have exactly one harvest receipt', v_lot_id;
            END IF;

            SELECT count(*) INTO v_mismatch_count
            FROM harvested_produce_lots lot
            JOIN harvest_events event ON event.id = lot.harvest_event_id
            JOIN produce_lot_ledger_entries r
              ON r.produce_lot_id = lot.id AND r.entry_kind = 'harvest_receipt'
            WHERE lot.id = v_lot_id
              AND ({_RECEIPT_MISMATCH_PREDICATE});
            IF v_mismatch_count > 0 THEN
                RAISE EXCEPTION 'produce lot % harvest receipt does not exactly match the lot/event', v_lot_id;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER harvested_produce_lots_enforce_ledger_reconciliation
        AFTER INSERT ON harvested_produce_lots
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_produce_lot_ledger_reconciliation();
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER produce_lot_ledger_entries_enforce_reconciliation
        AFTER INSERT ON produce_lot_ledger_entries
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_produce_lot_ledger_reconciliation();
        """
    )


def downgrade() -> None:
    bind = op.get_bind()

    # --- downgrade guard: only remove rows exactly reconstructible from CMP-013 --
    unknown_kind = bind.execute(
        sa.text("SELECT count(*) FROM produce_lot_ledger_entries WHERE entry_kind <> 'harvest_receipt'")
    ).scalar_one()
    if unknown_kind > 0:
        raise RuntimeError(
            "Cannot downgrade past CMP-014: produce_lot_ledger_entries contains an entry kind other than "
            "'harvest_receipt'. Those rows are not reconstructible from CMP-013 data alone; downgrading "
            "would silently discard independent ledger history. Do not downgrade."
        )

    malformed_count = bind.execute(
        sa.text(
            "SELECT count(*) FROM harvested_produce_lots lot "
            "JOIN harvest_events event ON event.id = lot.harvest_event_id "
            "LEFT JOIN produce_lot_ledger_entries r "
            "  ON r.produce_lot_id = lot.id AND r.entry_kind = 'harvest_receipt' "
            f"WHERE r.id IS NULL OR ({_RECEIPT_MISMATCH_PREDICATE})"
        )
    ).scalar_one()
    if malformed_count > 0:
        raise RuntimeError(
            "Cannot downgrade past CMP-014: at least one produce lot is missing its harvest receipt, or "
            "has a receipt that does not exactly reconstruct from CMP-013 lot/event data. Downgrading "
            "would silently discard or misrepresent ledger history. Do not downgrade."
        )

    op.execute(
        "DROP TRIGGER IF EXISTS produce_lot_ledger_entries_enforce_reconciliation ON produce_lot_ledger_entries"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS harvested_produce_lots_enforce_ledger_reconciliation ON harvested_produce_lots"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_produce_lot_ledger_reconciliation()")

    op.execute("DROP TRIGGER IF EXISTS produce_lot_ledger_entries_no_delete ON produce_lot_ledger_entries")
    op.execute("DROP TRIGGER IF EXISTS produce_lot_ledger_entries_no_update ON produce_lot_ledger_entries")
    op.execute(
        "DROP TRIGGER IF EXISTS produce_lot_ledger_entries_enforce_insert_integrity ON produce_lot_ledger_entries"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_produce_lot_ledger_entry_insert_integrity()")

    op.drop_index("ux_produce_lot_ledger_entries_event_harvest_receipt", table_name="produce_lot_ledger_entries")
    op.drop_index("ux_produce_lot_ledger_entries_lot_harvest_receipt", table_name="produce_lot_ledger_entries")
    op.drop_table("produce_lot_ledger_entries")
