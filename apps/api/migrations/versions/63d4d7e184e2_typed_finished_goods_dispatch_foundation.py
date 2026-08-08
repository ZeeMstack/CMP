"""typed finished goods dispatch foundation

Revision ID: 63d4d7e184e2
Revises: dd4e6fab718a
Create Date: 2026-08-07 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '63d4d7e184e2'
down_revision: Union[str, None] = 'dd4e6fab718a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# --- exact CMP-016 pre-state, copied literally from b3f6e9a2d174 (never
# derived dynamically from the currently-active constraints — by the time
# downgrade() runs those are already CMP-017's own kind-aware bodies, not
# CMP-016's). Used both to validate the expected starting shape before
# upgrade() replaces anything, and to restore it byte-exact on downgrade.
_CMP016_KIND_ALLOWED_DEF = "CHECK (((entry_kind)::text = 'packing_receipt'::text))"
_CMP016_DETERMINISTIC_ID_DEF = "CHECK ((id = finished_goods_lot_id))"
_CMP016_WEIGHT_ENVELOPE_DEF = (
    "CHECK (((weight_delta_kg > (0)::numeric) AND (weight_delta_kg = trunc(weight_delta_kg, 3)) "
    "AND (weight_delta_kg < ('100000000000'::bigint)::numeric)))"
)
_CMP016_COUNT_POSITIVE_DEF = "CHECK ((package_count_delta > 0))"

_CMP016_KIND_ALLOWED_BODY = "entry_kind IN ('packing_receipt')"
_CMP016_DETERMINISTIC_ID_BODY = "id = finished_goods_lot_id"
_CMP016_WEIGHT_ENVELOPE_BODY = (
    "weight_delta_kg > 0 AND weight_delta_kg = trunc(weight_delta_kg, 3) AND weight_delta_kg < 100000000000"
)
_CMP016_COUNT_POSITIVE_BODY = "package_count_delta > 0"

# Same-lot -> receipt mismatch predicate CMP-016 itself already uses,
# reused here (verbatim, receipt-only) as an explicit post-ALTER proof
# that every existing packing_receipt is untouched by the widened schema.
_RECEIPT_MISMATCH_PREDICATE = """
    r.id IS DISTINCT FROM lot.id
    OR r.tenant_id IS DISTINCT FROM lot.tenant_id
    OR r.farm_id IS DISTINCT FROM lot.farm_id
    OR r.packing_event_id IS DISTINCT FROM lot.packing_event_id
    OR r.dispatch_line_id IS NOT NULL
    OR r.weight_delta_kg IS DISTINCT FROM lot.net_packed_weight_kg
    OR r.package_count_delta IS DISTINCT FROM lot.package_count
    OR r.effective_time IS DISTINCT FROM lot.effective_time
    OR r.recorded_time IS DISTINCT FROM lot.recorded_time
    OR r.actor_user_id IS DISTINCT FROM event.actor_user_id
    OR r.note IS NOT NULL
"""


def upgrade() -> None:
    bind = op.get_bind()

    # --- 1. validate the exact CMP-016 pre-state before touching anything ------
    expected_checks = {
        "ck_finished_goods_ledger_entries_kind_allowed": _CMP016_KIND_ALLOWED_DEF,
        "ck_finished_goods_ledger_entries_deterministic_id": _CMP016_DETERMINISTIC_ID_DEF,
        "ck_finished_goods_ledger_entries_weight_envelope": _CMP016_WEIGHT_ENVELOPE_DEF,
        "ck_finished_goods_ledger_entries_count_positive": _CMP016_COUNT_POSITIVE_DEF,
    }
    actual_checks = dict(
        bind.execute(
            sa.text(
                "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = 'finished_goods_ledger_entries'::regclass AND conname = ANY(:names)"
            ),
            {"names": list(expected_checks)},
        ).all()
    )
    for name, expected_def in expected_checks.items():
        if actual_checks.get(name) != expected_def:
            raise RuntimeError(
                f"CMP-017 cannot upgrade: {name} does not match the expected CMP-016 definition. "
                "Refusing to replace an unexpected pre-state."
            )
    packing_event_nullable = bind.execute(
        sa.text(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name = 'finished_goods_ledger_entries' AND column_name = 'packing_event_id'"
        )
    ).scalar_one()
    if packing_event_nullable != "NO":
        raise RuntimeError(
            "CMP-017 cannot upgrade: finished_goods_ledger_entries.packing_event_id is not the expected "
            "CMP-016 NOT NULL shape. Refusing to replace an unexpected pre-state."
        )

    # --- 2-3. dispatch tables + composite unique targets ------------------------
    op.create_table(
        "dispatch_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.Column("external_reference", sa.String(), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
        # Farm-scoped (not tenant-scoped, unlike every other *_code index
        # in this codebase) -- a dispatch code is a facility-local document
        # number, not a tenant-wide identity like a produce/finished-goods
        # lot code.
        sa.UniqueConstraint("tenant_id", "farm_id", "id", name="uq_dispatch_events_tenant_farm_id"),
    )
    op.create_index(
        "ux_dispatch_events_farm_code_lower", "dispatch_events", ["farm_id", sa.text("lower(code)")], unique=True,
    )
    op.create_index(
        "ux_dispatch_events_tenant_client_command_id", "dispatch_events", ["tenant_id", "client_command_id"],
        unique=True,
    )

    op.create_table(
        "dispatch_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dispatch_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("finished_goods_lot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dispatched_weight_kg", sa.Numeric(), nullable=False),
        sa.Column("dispatched_package_count", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "dispatched_weight_kg > 0 AND dispatched_weight_kg = trunc(dispatched_weight_kg, 3) "
            "AND dispatched_weight_kg < 100000000000",
            name="ck_dispatch_lines_weight_positive",
        ),
        sa.CheckConstraint("dispatched_package_count > 0", name="ck_dispatch_lines_count_positive"),
        sa.UniqueConstraint("dispatch_event_id", "finished_goods_lot_id", name="ux_dispatch_lines_event_lot"),
        sa.UniqueConstraint("tenant_id", "farm_id", "id", name="uq_dispatch_lines_tenant_farm_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "dispatch_event_id"],
            ["dispatch_events.tenant_id", "dispatch_events.farm_id", "dispatch_events.id"],
            name="fk_dispatch_lines_tenant_farm_event",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "finished_goods_lot_id"],
            ["finished_goods_lots.tenant_id", "finished_goods_lots.farm_id", "finished_goods_lots.id"],
            name="fk_dispatch_lines_tenant_farm_lot",
        ),
    )

    # --- 4-6. ledger amendment: nullable packing_event_id, new dispatch_line_id -
    op.add_column(
        "finished_goods_ledger_entries",
        sa.Column("dispatch_line_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.alter_column("finished_goods_ledger_entries", "packing_event_id", nullable=True)
    op.create_foreign_key(
        "fk_finished_goods_ledger_entries_tenant_farm_line", "finished_goods_ledger_entries", "dispatch_lines",
        ["tenant_id", "farm_id", "dispatch_line_id"], ["tenant_id", "farm_id", "id"],
    )

    # --- 7. replace receipt-only CHECKs with kind-aware ones --------------------
    op.drop_constraint("ck_finished_goods_ledger_entries_kind_allowed", "finished_goods_ledger_entries")
    op.create_check_constraint(
        "ck_finished_goods_ledger_entries_kind_allowed", "finished_goods_ledger_entries",
        "entry_kind IN ('packing_receipt', 'dispatch_issue')",
    )
    op.drop_constraint("ck_finished_goods_ledger_entries_deterministic_id", "finished_goods_ledger_entries")
    op.create_check_constraint(
        "ck_finished_goods_ledger_entries_deterministic_id", "finished_goods_ledger_entries",
        "(entry_kind = 'packing_receipt' AND id = finished_goods_lot_id) "
        "OR (entry_kind = 'dispatch_issue' AND id = dispatch_line_id)",
    )
    op.create_check_constraint(
        "ck_finished_goods_ledger_entries_typed_source_shape", "finished_goods_ledger_entries",
        "(entry_kind = 'packing_receipt' AND packing_event_id IS NOT NULL AND dispatch_line_id IS NULL) "
        "OR (entry_kind = 'dispatch_issue' AND packing_event_id IS NULL AND dispatch_line_id IS NOT NULL)",
    )
    op.drop_constraint("ck_finished_goods_ledger_entries_weight_envelope", "finished_goods_ledger_entries")
    op.create_check_constraint(
        "ck_finished_goods_ledger_entries_weight_envelope", "finished_goods_ledger_entries",
        "weight_delta_kg = trunc(weight_delta_kg, 3) AND ("
        "  (entry_kind = 'packing_receipt' AND weight_delta_kg > 0 AND weight_delta_kg < 100000000000)"
        "  OR (entry_kind = 'dispatch_issue' AND weight_delta_kg < 0 AND weight_delta_kg > -100000000000)"
        ")",
    )
    op.drop_constraint("ck_finished_goods_ledger_entries_count_positive", "finished_goods_ledger_entries")
    op.create_check_constraint(
        "ck_finished_goods_ledger_entries_count_signed", "finished_goods_ledger_entries",
        # Explicit range comparisons, never ABS(): the BIGINT minimum
        # (-9223372036854775808) has no positive int64 equivalent, so the
        # issue lower bound is deliberately -9223372036854775807.
        "(entry_kind = 'packing_receipt' AND package_count_delta > 0 "
        "  AND package_count_delta <= 9223372036854775807)"
        "OR (entry_kind = 'dispatch_issue' AND package_count_delta < 0 "
        "  AND package_count_delta >= -9223372036854775807)",
    )
    # note_null is untouched: dispatch_issue also requires note IS NULL, so
    # this CHECK never needed to become kind-aware.

    # --- 8. dispatch partial unique index ----------------------------------------
    op.create_index(
        "ux_finished_goods_ledger_entries_line_dispatch_issue", "finished_goods_ledger_entries",
        ["dispatch_line_id"], unique=True, postgresql_where=sa.text("entry_kind = 'dispatch_issue'"),
    )

    # --- 9. explicit field-level proof that every existing receipt is untouched -
    receipt_mismatch = bind.execute(
        sa.text(
            "SELECT count(*) FROM finished_goods_lots lot "
            "JOIN packing_events event ON event.id = lot.packing_event_id "
            "JOIN finished_goods_ledger_entries r "
            "  ON r.finished_goods_lot_id = lot.id AND r.entry_kind = 'packing_receipt' "
            f"WHERE ({_RECEIPT_MISMATCH_PREDICATE})"
        )
    ).scalar_one()
    if receipt_mismatch > 0:
        raise RuntimeError(
            f"CMP-017 cannot upgrade: {receipt_mismatch} existing packing receipt(s) no longer exactly "
            "match their lot/event after widening the ledger schema. Aborting before installing the new "
            "immediate trigger."
        )
    lot_count, receipt_count = bind.execute(
        sa.text(
            "SELECT (SELECT count(*) FROM finished_goods_lots), "
            "(SELECT count(*) FROM finished_goods_ledger_entries WHERE entry_kind = 'packing_receipt')"
        )
    ).one()
    if lot_count != receipt_count:
        raise RuntimeError(
            f"CMP-017 cannot upgrade: {lot_count} finished-goods lots but {receipt_count} packing "
            "receipts exist after widening the ledger schema. Aborting."
        )

    # --- 10. versioned immediate insert-integrity trigger ------------------------
    # CMP-016's own function (enforce_finished_goods_ledger_entry_insert_integrity)
    # is never modified -- only its trigger *attachment* is dropped and
    # replaced, exactly the idiom CMP-015 used against CMP-014's own ledger
    # function. On clean downgrade the v2 attachment/function are dropped
    # and the original attachment is recreated pointing at the
    # still-untouched original function.
    op.execute(
        """
        CREATE FUNCTION enforce_finished_goods_ledger_entry_insert_integrity_v2() RETURNS trigger AS $$
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
            v_line_tenant_id UUID;
            v_line_farm_id UUID;
            v_line_event_id UUID;
            v_line_lot_id UUID;
            v_line_weight NUMERIC;
            v_line_count BIGINT;
            v_dispatch_tenant_id UUID;
            v_dispatch_farm_id UUID;
            v_dispatch_actor UUID;
            v_dispatch_effective TIMESTAMPTZ;
            v_dispatch_recorded TIMESTAMPTZ;
            v_prior_weight NUMERIC;
            v_prior_count BIGINT;
            v_prior_max_effective TIMESTAMPTZ;
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

            IF NEW.entry_kind = 'packing_receipt' THEN
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

            ELSIF NEW.entry_kind = 'dispatch_issue' THEN
                SELECT tenant_id, farm_id, dispatch_event_id, finished_goods_lot_id, dispatched_weight_kg,
                       dispatched_package_count
                INTO v_line_tenant_id, v_line_farm_id, v_line_event_id, v_line_lot_id, v_line_weight, v_line_count
                FROM dispatch_lines WHERE id = NEW.dispatch_line_id;
                IF v_line_tenant_id IS NULL THEN
                    RAISE EXCEPTION 'dispatch line not found for ledger entry';
                END IF;
                IF v_line_tenant_id <> NEW.tenant_id OR v_line_farm_id <> NEW.farm_id THEN
                    RAISE EXCEPTION 'ledger entry tenant/farm does not match the dispatch line''s own';
                END IF;
                IF v_line_lot_id <> NEW.finished_goods_lot_id THEN
                    RAISE EXCEPTION 'ledger entry finished-goods lot does not match the dispatch line''s own lot';
                END IF;

                SELECT tenant_id, farm_id, actor_user_id, effective_time, recorded_time
                INTO v_dispatch_tenant_id, v_dispatch_farm_id, v_dispatch_actor, v_dispatch_effective,
                     v_dispatch_recorded
                FROM dispatch_events WHERE id = v_line_event_id;
                IF v_dispatch_tenant_id IS NULL THEN
                    RAISE EXCEPTION 'dispatch event not found for ledger entry';
                END IF;
                IF v_dispatch_tenant_id <> NEW.tenant_id OR v_dispatch_farm_id <> NEW.farm_id THEN
                    RAISE EXCEPTION 'ledger entry tenant/farm does not match the dispatch event''s own';
                END IF;

                IF NEW.weight_delta_kg <> -v_line_weight THEN
                    RAISE EXCEPTION 'dispatch issue weight does not match the negative dispatch line weight';
                END IF;
                IF NEW.package_count_delta <> -v_line_count THEN
                    RAISE EXCEPTION 'dispatch issue package count does not match the negative dispatch line package count';
                END IF;
                IF NEW.actor_user_id <> v_dispatch_actor THEN
                    RAISE EXCEPTION 'dispatch issue actor does not match the dispatch event''s actor';
                END IF;
                IF NEW.effective_time <> v_dispatch_effective THEN
                    RAISE EXCEPTION 'dispatch issue effective time does not match the dispatch event''s effective time';
                END IF;
                IF NEW.effective_time < v_lot_effective THEN
                    RAISE EXCEPTION 'dispatch issue effective time precedes the finished-goods lot''s own effective time';
                END IF;
                IF NEW.recorded_time <> v_dispatch_recorded THEN
                    RAISE EXCEPTION 'dispatch issue recorded time does not match the dispatch event''s recorded time';
                END IF;

                -- Lock the lot row as the serialization mutex for this
                -- lot's ledger (the application already holds this same
                -- lock, sorted by lot id, before any insert -- re-locking
                -- an already-held row lock in the same transaction is an
                -- immediate no-op, never a new deadlock source; a
                -- direct-SQL writer that does NOT presort its own
                -- multi-lot inserts can still deadlock against another
                -- such writer, exactly as any FOR UPDATE-guarded table
                -- can -- this is a documented limitation, not a bug).
                PERFORM 1 FROM finished_goods_lots WHERE id = NEW.finished_goods_lot_id FOR UPDATE;

                -- BEFORE INSERT: NEW has not been persisted yet, so this
                -- plain aggregate over existing rows never double-counts it.
                SELECT COALESCE(SUM(weight_delta_kg), 0), COALESCE(SUM(package_count_delta), 0), MAX(effective_time)
                INTO v_prior_weight, v_prior_count, v_prior_max_effective
                FROM finished_goods_ledger_entries WHERE finished_goods_lot_id = NEW.finished_goods_lot_id;

                IF v_prior_max_effective IS NOT NULL AND NEW.effective_time < v_prior_max_effective THEN
                    RAISE EXCEPTION 'dispatch issue effective time precedes the finished-goods lot''s latest existing ledger entry';
                END IF;
                IF v_prior_weight + NEW.weight_delta_kg < 0 THEN
                    RAISE EXCEPTION 'dispatch issue would leave finished-goods lot % with negative available weight', NEW.finished_goods_lot_id;
                END IF;
                IF v_prior_count + NEW.package_count_delta < 0 THEN
                    RAISE EXCEPTION 'dispatch issue would leave finished-goods lot % with negative available package count', NEW.finished_goods_lot_id;
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute("DROP TRIGGER finished_goods_ledger_entries_enforce_insert_integrity ON finished_goods_ledger_entries")
    op.execute(
        """
        CREATE TRIGGER finished_goods_ledger_entries_enforce_insert_integrity
        BEFORE INSERT ON finished_goods_ledger_entries
        FOR EACH ROW EXECUTE FUNCTION enforce_finished_goods_ledger_entry_insert_integrity_v2();
        """
    )

    # --- append-only protection for the new tables --------------------------------
    op.execute(
        "CREATE TRIGGER dispatch_events_no_update BEFORE UPDATE ON dispatch_events "
        "FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();"
    )
    op.execute(
        "CREATE TRIGGER dispatch_events_no_delete BEFORE DELETE ON dispatch_events "
        "FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();"
    )
    op.execute(
        "CREATE TRIGGER dispatch_lines_no_update BEFORE UPDATE ON dispatch_lines "
        "FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();"
    )
    op.execute(
        "CREATE TRIGGER dispatch_lines_no_delete BEFORE DELETE ON dispatch_lines "
        "FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();"
    )

    # --- 11. deferred dispatch reconciliation --------------------------------------
    # One shared function across three AFTER INSERT DEFERRABLE INITIALLY
    # DEFERRED triggers -- dispatch_events, dispatch_lines, and (a third,
    # sibling attachment alongside CMP-016's own, untouched)
    # finished_goods_ledger_entries. CMP-016's own
    # enforce_finished_goods_ledger_reconciliation keeps firing for every
    # insert on that table too (it only ever counts packing_receipt rows,
    # so a dispatch_issue insert is a harmless no-op re-confirmation for
    # it) -- it is never edited, so packing-receipt reconciliation is
    # never weakened.
    op.execute(
        """
        CREATE FUNCTION enforce_dispatch_reconciliation() RETURNS trigger AS $$
        DECLARE
            v_event_id UUID;
            v_line_count INTEGER;
            v_mismatch_count INTEGER;
            v_duplicate_count INTEGER;
        BEGIN
            IF TG_TABLE_NAME = 'dispatch_events' THEN
                v_event_id := NEW.id;
            ELSIF TG_TABLE_NAME = 'dispatch_lines' THEN
                v_event_id := NEW.dispatch_event_id;
            ELSIF TG_TABLE_NAME = 'finished_goods_ledger_entries' THEN
                IF NEW.entry_kind <> 'dispatch_issue' THEN
                    RETURN NEW;
                END IF;
                SELECT dispatch_event_id INTO v_event_id FROM dispatch_lines WHERE id = NEW.dispatch_line_id;
                IF v_event_id IS NULL THEN
                    RAISE EXCEPTION 'dispatch_issue ledger entry % references no matching dispatch line', NEW.id;
                END IF;
            END IF;

            SELECT count(*) INTO v_line_count FROM dispatch_lines WHERE dispatch_event_id = v_event_id;
            IF v_line_count < 1 THEN
                RAISE EXCEPTION 'dispatch event % must have at least one line', v_event_id;
            END IF;

            SELECT count(*) INTO v_mismatch_count
            FROM dispatch_lines line
            JOIN dispatch_events event ON event.id = line.dispatch_event_id
            LEFT JOIN finished_goods_ledger_entries issue
              ON issue.dispatch_line_id = line.id AND issue.entry_kind = 'dispatch_issue'
            WHERE line.dispatch_event_id = v_event_id
              AND (
                issue.id IS NULL
                OR issue.id IS DISTINCT FROM line.id
                OR issue.tenant_id IS DISTINCT FROM line.tenant_id
                OR issue.farm_id IS DISTINCT FROM line.farm_id
                OR issue.finished_goods_lot_id IS DISTINCT FROM line.finished_goods_lot_id
                OR issue.weight_delta_kg IS DISTINCT FROM (-line.dispatched_weight_kg)
                OR issue.package_count_delta IS DISTINCT FROM (-line.dispatched_package_count)
                OR issue.effective_time IS DISTINCT FROM event.effective_time
                OR issue.recorded_time IS DISTINCT FROM event.recorded_time
                OR issue.actor_user_id IS DISTINCT FROM event.actor_user_id
                OR issue.packing_event_id IS NOT NULL
                OR issue.note IS NOT NULL
              );
            IF v_mismatch_count > 0 THEN
                RAISE EXCEPTION 'dispatch event % has a line missing or mismatched its dispatch_issue', v_event_id;
            END IF;

            SELECT count(*) INTO v_duplicate_count FROM (
                SELECT dispatch_line_id FROM finished_goods_ledger_entries
                WHERE entry_kind = 'dispatch_issue'
                  AND dispatch_line_id IN (SELECT id FROM dispatch_lines WHERE dispatch_event_id = v_event_id)
                GROUP BY dispatch_line_id HAVING count(*) > 1
            ) dup;
            IF v_duplicate_count > 0 THEN
                RAISE EXCEPTION 'dispatch event % has a line with more than one dispatch_issue', v_event_id;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER dispatch_events_enforce_reconciliation AFTER INSERT ON dispatch_events "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION enforce_dispatch_reconciliation();"
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER dispatch_lines_enforce_reconciliation AFTER INSERT ON dispatch_lines "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION enforce_dispatch_reconciliation();"
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER finished_goods_ledger_entries_enforce_dispatch_reconciliation "
        "AFTER INSERT ON finished_goods_ledger_entries "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION enforce_dispatch_reconciliation();"
    )


def downgrade() -> None:
    bind = op.get_bind()

    # --- downgrade guard: dispatch history is independent operational data, ----
    # never reconstructible -- CMP-015's own unconditional-block model, not
    # CMP-016's reconstructible-projection one.
    dispatch_event_count = bind.execute(sa.text("SELECT count(*) FROM dispatch_events")).scalar_one()
    if dispatch_event_count > 0:
        raise RuntimeError(
            "Cannot downgrade past CMP-017: dispatch_events contains history. Dispatch history is "
            "independent operational data, not reconstructible from any other table. Do not downgrade."
        )
    dispatch_line_count = bind.execute(sa.text("SELECT count(*) FROM dispatch_lines")).scalar_one()
    if dispatch_line_count > 0:
        raise RuntimeError(
            "Cannot downgrade past CMP-017: dispatch_lines contains history. Do not downgrade."
        )
    issue_count = bind.execute(
        sa.text("SELECT count(*) FROM finished_goods_ledger_entries WHERE entry_kind = 'dispatch_issue'")
    ).scalar_one()
    if issue_count > 0:
        raise RuntimeError(
            "Cannot downgrade past CMP-017: finished_goods_ledger_entries contains dispatch_issue rows. "
            "Do not downgrade."
        )
    unknown_kind_count = bind.execute(
        sa.text(
            "SELECT count(*) FROM finished_goods_ledger_entries "
            "WHERE entry_kind NOT IN ('packing_receipt', 'dispatch_issue')"
        )
    ).scalar_one()
    if unknown_kind_count > 0:
        raise RuntimeError(
            "Cannot downgrade past CMP-017: finished_goods_ledger_entries contains an entry kind this "
            "migration does not recognize. Do not downgrade."
        )
    dangling_line_ref_count = bind.execute(
        sa.text("SELECT count(*) FROM finished_goods_ledger_entries WHERE dispatch_line_id IS NOT NULL")
    ).scalar_one()
    if dangling_line_ref_count > 0:
        raise RuntimeError(
            "Cannot downgrade past CMP-017: finished_goods_ledger_entries has a non-null dispatch_line_id "
            "even though no dispatch_issue rows were found above. Refusing to proceed against this "
            "inconsistent state."
        )

    # Every remaining row must be a packing_receipt that will still satisfy
    # the exact restored CMP-016 constraints once they are back in place.
    receipt_would_violate = bind.execute(
        sa.text(
            "SELECT count(*) FROM finished_goods_ledger_entries "
            "WHERE NOT (id = finished_goods_lot_id) "
            "   OR weight_delta_kg <= 0 OR weight_delta_kg <> trunc(weight_delta_kg, 3) "
            "   OR weight_delta_kg >= 100000000000 "
            "   OR package_count_delta <= 0 "
            "   OR packing_event_id IS NULL "
            "   OR note IS NOT NULL"
        )
    ).scalar_one()
    if receipt_would_violate > 0:
        raise RuntimeError(
            "Cannot downgrade past CMP-017: at least one remaining ledger row would violate the exact "
            "CMP-016 constraints being restored. Do not downgrade."
        )

    # --- 1. drop CMP-017 deferred triggers -----------------------------------------
    op.execute(
        "DROP TRIGGER IF EXISTS finished_goods_ledger_entries_enforce_dispatch_reconciliation "
        "ON finished_goods_ledger_entries"
    )
    op.execute("DROP TRIGGER IF EXISTS dispatch_lines_enforce_reconciliation ON dispatch_lines")
    op.execute("DROP TRIGGER IF EXISTS dispatch_events_enforce_reconciliation ON dispatch_events")
    op.execute("DROP FUNCTION IF EXISTS enforce_dispatch_reconciliation()")

    # --- 2-3. drop the v2 immediate trigger/function, restore the exact original --
    op.execute(
        "DROP TRIGGER IF EXISTS finished_goods_ledger_entries_enforce_insert_integrity "
        "ON finished_goods_ledger_entries"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_finished_goods_ledger_entry_insert_integrity_v2()")
    op.execute(
        """
        CREATE TRIGGER finished_goods_ledger_entries_enforce_insert_integrity
        BEFORE INSERT ON finished_goods_ledger_entries
        FOR EACH ROW EXECUTE FUNCTION enforce_finished_goods_ledger_entry_insert_integrity();
        """
    )

    op.execute("DROP TRIGGER IF EXISTS dispatch_lines_no_delete ON dispatch_lines")
    op.execute("DROP TRIGGER IF EXISTS dispatch_lines_no_update ON dispatch_lines")
    op.execute("DROP TRIGGER IF EXISTS dispatch_events_no_delete ON dispatch_events")
    op.execute("DROP TRIGGER IF EXISTS dispatch_events_no_update ON dispatch_events")

    # --- 6-7. restore the exact CMP-016 CHECKs, BEFORE dropping dispatch_line_id --
    # (typed_source_shape and deterministic_id both reference dispatch_line_id in
    # their body; dropping that column would implicitly cascade-drop them first,
    # making an explicit DROP CONSTRAINT afterward fail with "does not exist" --
    # so both are handled here, ahead of the column drop below.)
    op.drop_constraint("ck_finished_goods_ledger_entries_typed_source_shape", "finished_goods_ledger_entries")
    op.drop_constraint("ck_finished_goods_ledger_entries_deterministic_id", "finished_goods_ledger_entries")
    op.create_check_constraint(
        "ck_finished_goods_ledger_entries_deterministic_id", "finished_goods_ledger_entries",
        _CMP016_DETERMINISTIC_ID_BODY,
    )
    op.drop_constraint("ck_finished_goods_ledger_entries_count_signed", "finished_goods_ledger_entries")
    op.create_check_constraint(
        "ck_finished_goods_ledger_entries_count_positive", "finished_goods_ledger_entries",
        _CMP016_COUNT_POSITIVE_BODY,
    )
    op.drop_constraint("ck_finished_goods_ledger_entries_weight_envelope", "finished_goods_ledger_entries")
    op.create_check_constraint(
        "ck_finished_goods_ledger_entries_weight_envelope", "finished_goods_ledger_entries",
        _CMP016_WEIGHT_ENVELOPE_BODY,
    )
    op.drop_constraint("ck_finished_goods_ledger_entries_kind_allowed", "finished_goods_ledger_entries")
    op.create_check_constraint(
        "ck_finished_goods_ledger_entries_kind_allowed", "finished_goods_ledger_entries", _CMP016_KIND_ALLOWED_BODY,
    )

    # --- 4-5. drop dispatch-only indexes and the ledger's dispatch-line FK/column --
    op.drop_index("ux_finished_goods_ledger_entries_line_dispatch_issue", table_name="finished_goods_ledger_entries")
    op.drop_constraint(
        "fk_finished_goods_ledger_entries_tenant_farm_line", "finished_goods_ledger_entries", type_="foreignkey"
    )
    op.drop_column("finished_goods_ledger_entries", "dispatch_line_id")

    # --- restore packing_event_id NOT NULL -----------------------------------------
    op.alter_column("finished_goods_ledger_entries", "packing_event_id", nullable=False)

    # --- 8. drop dispatch tables (lines first: FK to events) ----------------------
    # Dropping each table cascades its own indexes/constraints automatically
    # -- no separate op.drop_index calls needed.
    op.drop_table("dispatch_lines")
    op.drop_table("dispatch_events")

    # Steps 9-10 (preserve every packing receipt; leave CMP-016A env.py
    # unchanged) require no code here: no packing_receipt row is ever
    # touched above, and this migration makes no env.py change at all.
