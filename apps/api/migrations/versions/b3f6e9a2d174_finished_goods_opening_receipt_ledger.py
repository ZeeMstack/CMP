"""finished goods opening receipt ledger

Revision ID: b3f6e9a2d174
Revises: a91f4c7b2e58
Create Date: 2026-08-06 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'b3f6e9a2d174'
down_revision: Union[str, None] = 'a91f4c7b2e58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# One shared field-equality predicate: a packing_receipt row is a
# deterministic, reconstructible projection of its finished-goods lot and
# packing event. Used both to verify the migration's own backfill and, again,
# as the downgrade guard's "is every receipt exactly reconstructible" check —
# the same shared-predicate idiom CMP-014 established.
_RECEIPT_MISMATCH_PREDICATE = """
    r.id IS DISTINCT FROM lot.id
    OR r.tenant_id IS DISTINCT FROM lot.tenant_id
    OR r.farm_id IS DISTINCT FROM lot.farm_id
    OR r.finished_goods_lot_id IS DISTINCT FROM lot.id
    OR r.packing_event_id IS DISTINCT FROM lot.packing_event_id
    OR r.weight_delta_kg IS DISTINCT FROM lot.net_packed_weight_kg
    OR r.package_count_delta IS DISTINCT FROM lot.package_count
    OR r.effective_time IS DISTINCT FROM lot.effective_time
    OR r.recorded_time IS DISTINCT FROM lot.recorded_time
    OR r.actor_user_id IS DISTINCT FROM event.actor_user_id
    OR r.note IS NOT NULL
"""


def upgrade() -> None:
    # --- finished_goods_ledger_entries (immutable) ------------------------------
    # Both composite FK targets already exist — finished_goods_lots and
    # packing_events each already carry their own (tenant_id, farm_id, id)
    # unique constraint (added by CMP-015 itself), unlike CMP-014's own
    # situation with harvested_produce_lots. No new composite uniqueness is
    # added here, and therefore none needs removing on downgrade.
    op.create_table(
        "finished_goods_ledger_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column(
            "finished_goods_lot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("finished_goods_lots.id"),
            nullable=False,
        ),
        sa.Column(
            "packing_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("packing_events.id"), nullable=False
        ),
        sa.Column("entry_kind", sa.String(), nullable=False),
        sa.Column("weight_delta_kg", sa.Numeric(), nullable=False),
        sa.Column("package_count_delta", sa.BigInteger(), nullable=False),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.CheckConstraint(
            "entry_kind IN ('packing_receipt')", name="ck_finished_goods_ledger_entries_kind_allowed"
        ),
        # Same-row rules as ordinary CHECK constraints — unconditional
        # today since only one entry kind exists. A future ticket widening
        # entry_kind (e.g. dispatch) must widen these to be kind-guarded,
        # the same way CMP-015 widened CMP-014's own weight/count CHECKs.
        sa.CheckConstraint(
            "id = finished_goods_lot_id", name="ck_finished_goods_ledger_entries_deterministic_id"
        ),
        sa.CheckConstraint(
            "weight_delta_kg > 0 AND weight_delta_kg = trunc(weight_delta_kg, 3) "
            "AND weight_delta_kg < 100000000000",
            name="ck_finished_goods_ledger_entries_weight_envelope",
        ),
        sa.CheckConstraint(
            "package_count_delta > 0", name="ck_finished_goods_ledger_entries_count_positive"
        ),
        sa.CheckConstraint("note IS NULL", name="ck_finished_goods_ledger_entries_note_null"),
        sa.UniqueConstraint(
            "tenant_id", "farm_id", "id", name="uq_finished_goods_ledger_entries_tenant_farm_id"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "finished_goods_lot_id"],
            ["finished_goods_lots.tenant_id", "finished_goods_lots.farm_id", "finished_goods_lots.id"],
            name="fk_finished_goods_ledger_entries_tenant_farm_lot",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "packing_event_id"],
            ["packing_events.tenant_id", "packing_events.farm_id", "packing_events.id"],
            name="fk_finished_goods_ledger_entries_tenant_farm_event",
        ),
    )
    # Partial (kind-scoped), not table-wide: a future entry kind must be
    # able to reference the same lot/event without being blocked by this
    # ticket's one-receipt-per-lot rule.
    op.create_index(
        "ux_finished_goods_ledger_entries_lot_packing_receipt", "finished_goods_ledger_entries",
        ["finished_goods_lot_id"], unique=True, postgresql_where=sa.text("entry_kind = 'packing_receipt'"),
    )
    op.create_index(
        "ux_finished_goods_ledger_entries_event_packing_receipt", "finished_goods_ledger_entries",
        ["packing_event_id"], unique=True, postgresql_where=sa.text("entry_kind = 'packing_receipt'"),
    )

    # --- backfill: one deterministic opening receipt per existing lot ----------
    # id and finished_goods_lot_id both equal the lot's own id; recorded_time
    # comes from the lot's own recorded_time (not a fresh default) so live
    # creation and this backfill always produce identical rows; note is
    # always NULL.
    op.execute(
        """
        INSERT INTO finished_goods_ledger_entries (
            id, tenant_id, farm_id, finished_goods_lot_id, packing_event_id, entry_kind,
            weight_delta_kg, package_count_delta, effective_time, recorded_time, actor_user_id, note
        )
        SELECT
            lot.id, lot.tenant_id, lot.farm_id, lot.id, lot.packing_event_id, 'packing_receipt',
            lot.net_packed_weight_kg, lot.package_count, lot.effective_time, lot.recorded_time,
            event.actor_user_id, NULL
        FROM finished_goods_lots lot
        JOIN packing_events event ON event.id = lot.packing_event_id
        """
    )

    # --- verify the complete backfill before enabling deferred enforcement -----
    bind = op.get_bind()

    lot_count, receipt_count = bind.execute(
        sa.text(
            "SELECT (SELECT count(*) FROM finished_goods_lots), "
            "(SELECT count(*) FROM finished_goods_ledger_entries WHERE entry_kind = 'packing_receipt')"
        )
    ).one()
    if lot_count != receipt_count:
        raise RuntimeError(
            f"CMP-016 backfill failed: {lot_count} finished-goods lots but {receipt_count} packing "
            f"receipts were created. Aborting before enabling deferred enforcement."
        )

    mismatch_count = bind.execute(
        sa.text(
            "SELECT count(*) FROM finished_goods_lots lot "
            "JOIN packing_events event ON event.id = lot.packing_event_id "
            "LEFT JOIN finished_goods_ledger_entries r "
            "  ON r.finished_goods_lot_id = lot.id AND r.entry_kind = 'packing_receipt' "
            f"WHERE r.id IS NULL OR ({_RECEIPT_MISMATCH_PREDICATE})"
        )
    ).scalar_one()
    if mismatch_count > 0:
        raise RuntimeError(
            f"CMP-016 backfill failed: {mismatch_count} finished-goods lot(s) have a missing or "
            f"field-mismatched packing receipt. Aborting before enabling deferred enforcement."
        )

    orphan_count = bind.execute(
        sa.text(
            "SELECT count(*) FROM finished_goods_ledger_entries r "
            "WHERE r.entry_kind = 'packing_receipt' "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM finished_goods_lots lot "
            "  WHERE lot.id = r.finished_goods_lot_id AND lot.packing_event_id = r.packing_event_id"
            ")"
        )
    ).scalar_one()
    if orphan_count > 0:
        raise RuntimeError(
            f"CMP-016 backfill failed: {orphan_count} packing receipt(s) reference no matching "
            f"finished-goods lot/event. Aborting before enabling deferred enforcement."
        )

    # --- immediate insert-integrity trigger -------------------------------------
    # Same-row rules (id, kind, note) are already enforced by CHECK
    # constraints above; this trigger only proves the cross-table
    # (join-requiring) equalities a CHECK constraint cannot express.
    op.execute(
        """
        CREATE FUNCTION enforce_finished_goods_ledger_entry_insert_integrity() RETURNS trigger AS $$
        DECLARE
            v_lot_tenant_id UUID;
            v_lot_farm_id UUID;
            v_lot_event_id UUID;
            v_lot_weight NUMERIC;
            v_lot_count BIGINT;
            v_lot_effective TIMESTAMPTZ;
            v_lot_recorded TIMESTAMPTZ;
            v_event_actor UUID;
            v_event_effective TIMESTAMPTZ;
        BEGIN
            SELECT tenant_id, farm_id, packing_event_id, net_packed_weight_kg, package_count,
                   effective_time, recorded_time
            INTO v_lot_tenant_id, v_lot_farm_id, v_lot_event_id, v_lot_weight, v_lot_count, v_lot_effective,
                 v_lot_recorded
            FROM finished_goods_lots WHERE id = NEW.finished_goods_lot_id;
            IF v_lot_tenant_id IS NULL THEN
                RAISE EXCEPTION 'finished-goods lot not found for ledger entry';
            END IF;
            IF v_lot_tenant_id <> NEW.tenant_id OR v_lot_farm_id <> NEW.farm_id THEN
                RAISE EXCEPTION 'ledger entry tenant/farm does not match the finished-goods lot''s own';
            END IF;
            IF v_lot_event_id <> NEW.packing_event_id THEN
                RAISE EXCEPTION 'ledger entry packing event does not match the finished-goods lot''s own event';
            END IF;

            SELECT actor_user_id, effective_time INTO v_event_actor, v_event_effective
            FROM packing_events WHERE id = NEW.packing_event_id;
            IF v_event_actor IS NULL THEN
                RAISE EXCEPTION 'packing event not found for ledger entry';
            END IF;

            IF NEW.weight_delta_kg <> v_lot_weight THEN
                RAISE EXCEPTION 'packing receipt weight does not match the finished-goods lot''s net packed weight';
            END IF;
            IF NEW.package_count_delta <> v_lot_count THEN
                RAISE EXCEPTION 'packing receipt package count does not match the finished-goods lot''s package count';
            END IF;
            IF NEW.actor_user_id <> v_event_actor THEN
                RAISE EXCEPTION 'packing receipt actor does not match the packing event''s actor';
            END IF;
            IF NEW.effective_time <> v_lot_effective THEN
                RAISE EXCEPTION 'packing receipt effective time does not match the finished-goods lot''s effective time';
            END IF;
            IF NEW.effective_time <> v_event_effective THEN
                RAISE EXCEPTION 'packing receipt effective time does not match the packing event''s effective time';
            END IF;
            IF NEW.recorded_time <> v_lot_recorded THEN
                RAISE EXCEPTION 'packing receipt recorded time does not match the finished-goods lot''s recorded time';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER finished_goods_ledger_entries_enforce_insert_integrity
        BEFORE INSERT ON finished_goods_ledger_entries
        FOR EACH ROW EXECUTE FUNCTION enforce_finished_goods_ledger_entry_insert_integrity();
        """
    )
    op.execute(
        """
        CREATE TRIGGER finished_goods_ledger_entries_no_update
        BEFORE UPDATE ON finished_goods_ledger_entries
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER finished_goods_ledger_entries_no_delete
        BEFORE DELETE ON finished_goods_ledger_entries
        FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();
        """
    )

    # --- deferred reconciliation --------------------------------------------------
    # One shared function, attached via two DEFERRABLE INITIALLY DEFERRED
    # constraint triggers, so any insert — even direct SQL against an
    # already-committed lot, in a later transaction — re-validates complete
    # field equality between the lot/event and its exactly-one receipt at
    # commit. packing_events gets no attachment here: CMP-015's own
    # enforce_packing_reconciliation already proves exactly one
    # finished_goods_lots row per packing_events row (a `count(*) <> 1`
    # check, not merely `>= 1`), and this ticket's own two triggers prove
    # exactly one receipt per finished-goods lot — the two compose
    # transitively to prove packing_events -> receipt is exactly 1:1,
    # without a third attachment re-checking an already-proven invariant
    # (the identical reasoning CMP-014 used to skip a harvest_events
    # attachment).
    op.execute(
        f"""
        CREATE FUNCTION enforce_finished_goods_ledger_reconciliation() RETURNS trigger AS $$
        DECLARE
            v_lot_id UUID;
            v_receipt_count INTEGER;
            v_mismatch_count INTEGER;
        BEGIN
            IF TG_TABLE_NAME = 'finished_goods_lots' THEN
                v_lot_id := NEW.id;
            ELSIF TG_TABLE_NAME = 'finished_goods_ledger_entries' THEN
                v_lot_id := NEW.finished_goods_lot_id;
            END IF;

            IF v_lot_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT count(*) INTO v_receipt_count
            FROM finished_goods_ledger_entries
            WHERE finished_goods_lot_id = v_lot_id AND entry_kind = 'packing_receipt';
            IF v_receipt_count <> 1 THEN
                RAISE EXCEPTION 'finished-goods lot % must have exactly one packing receipt', v_lot_id;
            END IF;

            SELECT count(*) INTO v_mismatch_count
            FROM finished_goods_lots lot
            JOIN packing_events event ON event.id = lot.packing_event_id
            JOIN finished_goods_ledger_entries r
              ON r.finished_goods_lot_id = lot.id AND r.entry_kind = 'packing_receipt'
            WHERE lot.id = v_lot_id
              AND ({_RECEIPT_MISMATCH_PREDICATE});
            IF v_mismatch_count > 0 THEN
                RAISE EXCEPTION 'finished-goods lot % packing receipt does not exactly match the lot/event', v_lot_id;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER finished_goods_lots_enforce_ledger_reconciliation
        AFTER INSERT ON finished_goods_lots
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_finished_goods_ledger_reconciliation();
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER finished_goods_ledger_entries_enforce_reconciliation
        AFTER INSERT ON finished_goods_ledger_entries
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_finished_goods_ledger_reconciliation();
        """
    )


def downgrade() -> None:
    bind = op.get_bind()

    # --- downgrade guard: only remove rows exactly reconstructible from CMP-015 --
    unknown_kind = bind.execute(
        sa.text("SELECT count(*) FROM finished_goods_ledger_entries WHERE entry_kind <> 'packing_receipt'")
    ).scalar_one()
    if unknown_kind > 0:
        raise RuntimeError(
            "Cannot downgrade past CMP-016: finished_goods_ledger_entries contains an entry kind other "
            "than 'packing_receipt'. Those rows are not reconstructible from CMP-015 data alone; "
            "downgrading would silently discard independent ledger history. Do not downgrade."
        )

    malformed_count = bind.execute(
        sa.text(
            "SELECT count(*) FROM finished_goods_lots lot "
            "JOIN packing_events event ON event.id = lot.packing_event_id "
            "LEFT JOIN finished_goods_ledger_entries r "
            "  ON r.finished_goods_lot_id = lot.id AND r.entry_kind = 'packing_receipt' "
            f"WHERE r.id IS NULL OR ({_RECEIPT_MISMATCH_PREDICATE})"
        )
    ).scalar_one()
    if malformed_count > 0:
        raise RuntimeError(
            "Cannot downgrade past CMP-016: at least one finished-goods lot is missing its packing "
            "receipt, or has a receipt that does not exactly reconstruct from CMP-015 lot/event data. "
            "Downgrading would silently discard or misrepresent ledger history. Do not downgrade."
        )

    # The lot -> receipt LEFT JOIN above only walks known lots; it cannot see
    # a receipt whose finished_goods_lot_id/packing_event_id no longer
    # resolves to a real lot/event. This mirrors upgrade()'s own separate
    # orphan_count check (receipt -> lot direction), which downgrade() must
    # repeat independently rather than trusting the backfill ran cleanly.
    orphan_count = bind.execute(
        sa.text(
            "SELECT count(*) FROM finished_goods_ledger_entries r "
            "WHERE r.entry_kind = 'packing_receipt' "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM finished_goods_lots lot "
            "  WHERE lot.id = r.finished_goods_lot_id AND lot.packing_event_id = r.packing_event_id"
            ")"
        )
    ).scalar_one()
    if orphan_count > 0:
        raise RuntimeError(
            "Cannot downgrade past CMP-016: at least one packing receipt references no matching "
            "finished-goods lot/event. Downgrading would silently discard orphaned ledger history. "
            "Do not downgrade."
        )

    # Normal operation makes more than one receipt per lot/event unreachable
    # (the deterministic-id CHECK ties a receipt's id to its lot's id, so a
    # genuine duplicate collides with the primary key first; the two partial
    # unique indexes are a second, independent barrier). Both barriers are
    # database-level constraints, not application logic, so this check
    # exists purely as defence in depth against already-corrupted state
    # that predates this downgrade attempt (e.g. a constraint dropped and
    # not fully repaired by some earlier, unrelated bypass).
    duplicate_count = bind.execute(
        sa.text(
            "SELECT count(*) FROM ("
            "  SELECT finished_goods_lot_id FROM finished_goods_ledger_entries "
            "  WHERE entry_kind = 'packing_receipt' GROUP BY finished_goods_lot_id HAVING count(*) > 1"
            "  UNION ALL "
            "  SELECT packing_event_id FROM finished_goods_ledger_entries "
            "  WHERE entry_kind = 'packing_receipt' GROUP BY packing_event_id HAVING count(*) > 1"
            ") dup"
        )
    ).scalar_one()
    if duplicate_count > 0:
        raise RuntimeError(
            "Cannot downgrade past CMP-016: at least one finished-goods lot or packing event has more "
            "than one packing receipt. Downgrading would silently discard duplicate ledger history. "
            "Do not downgrade."
        )

    op.execute(
        "DROP TRIGGER IF EXISTS finished_goods_ledger_entries_enforce_reconciliation "
        "ON finished_goods_ledger_entries"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS finished_goods_lots_enforce_ledger_reconciliation ON finished_goods_lots"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_finished_goods_ledger_reconciliation()")

    op.execute("DROP TRIGGER IF EXISTS finished_goods_ledger_entries_no_delete ON finished_goods_ledger_entries")
    op.execute("DROP TRIGGER IF EXISTS finished_goods_ledger_entries_no_update ON finished_goods_ledger_entries")
    op.execute(
        "DROP TRIGGER IF EXISTS finished_goods_ledger_entries_enforce_insert_integrity "
        "ON finished_goods_ledger_entries"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_finished_goods_ledger_entry_insert_integrity()")

    op.drop_index(
        "ux_finished_goods_ledger_entries_event_packing_receipt", table_name="finished_goods_ledger_entries"
    )
    op.drop_index(
        "ux_finished_goods_ledger_entries_lot_packing_receipt", table_name="finished_goods_ledger_entries"
    )
    op.drop_table("finished_goods_ledger_entries")
