"""finished goods storage foundation

Revision ID: dd8b86a52acf
Revises: 63d4d7e184e2
Create Date: 2026-08-09 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'dd8b86a52acf'
down_revision: Union[str, None] = '63d4d7e184e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

STORAGE_ELIGIBLE_LOCATION_TYPE_CODE = "cold_store_position"


def upgrade() -> None:
    bind = op.get_bind()

    # --- 1. validate the exact expected CMP-017 pre-state -----------------------
    # CMP-017's own v2 function is never dropped by CMP-017's own migration
    # (only its trigger attachment is swapped in future tickets) -- confirm
    # it is still the currently-active attachment before replacing it.
    v2_attached = bind.execute(
        sa.text(
            "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'finished_goods_ledger_entries'::regclass "
            "AND tgname = 'finished_goods_ledger_entries_enforce_insert_integrity' "
            "AND tgfoid = to_regproc('enforce_finished_goods_ledger_entry_insert_integrity_v2')"
        )
    ).scalar_one()
    if v2_attached != 1:
        raise RuntimeError(
            "CMP-018 cannot upgrade: the expected CMP-017 v2 ledger insert-integrity trigger "
            "attachment was not found. Refusing to replace an unexpected pre-state."
        )
    eligible_type_exists = bind.execute(
        sa.text("SELECT count(*) FROM location_types WHERE code = :code"),
        {"code": STORAGE_ELIGIBLE_LOCATION_TYPE_CODE},
    ).scalar_one()
    if eligible_type_exists != 1:
        raise RuntimeError(
            f"CMP-018 cannot upgrade: expected location type {STORAGE_ELIGIBLE_LOCATION_TYPE_CODE!r} "
            "does not exist. Refusing to proceed against an unexpected pre-state."
        )

    # --- 2. locations composite unique (new, CMP-018-added) ---------------------
    # locations carried no (tenant_id, farm_id, id) unique constraint before
    # this ticket -- required so dispatch/source/destination location
    # references below can use real composite foreign keys rather than
    # trigger-only tenant/farm consistency.
    op.create_unique_constraint("uq_locations_tenant_farm_id", "locations", ["tenant_id", "farm_id", "id"])

    # --- 3. finished_goods_storage_movements table -------------------------------
    op.create_table(
        "finished_goods_storage_movements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("finished_goods_lot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("movement_kind", sa.String(), nullable=False),
        sa.Column("source_location_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("destination_location_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("moved_weight_kg", sa.Numeric(), nullable=False),
        sa.Column("moved_package_count", sa.BigInteger(), nullable=False),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.CheckConstraint(
            "movement_kind IN ('place', 'transfer', 'release')",
            name="ck_finished_goods_storage_movements_kind_allowed",
        ),
        sa.CheckConstraint(
            "(movement_kind = 'place' AND source_location_id IS NULL AND destination_location_id IS NOT NULL) "
            "OR (movement_kind = 'transfer' AND source_location_id IS NOT NULL "
            "     AND destination_location_id IS NOT NULL AND source_location_id <> destination_location_id) "
            "OR (movement_kind = 'release' AND source_location_id IS NOT NULL AND destination_location_id IS NULL)",
            name="ck_finished_goods_storage_movements_shape",
        ),
        sa.CheckConstraint(
            "moved_weight_kg > 0 AND moved_weight_kg = trunc(moved_weight_kg, 3) "
            "AND moved_weight_kg < 100000000000",
            name="ck_finished_goods_storage_movements_weight_positive",
        ),
        sa.CheckConstraint("moved_package_count > 0", name="ck_finished_goods_storage_movements_count_positive"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "finished_goods_lot_id"],
            ["finished_goods_lots.tenant_id", "finished_goods_lots.farm_id", "finished_goods_lots.id"],
            name="fk_finished_goods_storage_movements_tenant_farm_lot",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "source_location_id"],
            ["locations.tenant_id", "locations.farm_id", "locations.id"],
            name="fk_finished_goods_storage_movements_tenant_farm_src_location",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "destination_location_id"],
            ["locations.tenant_id", "locations.farm_id", "locations.id"],
            name="fk_finished_goods_storage_movements_tenant_farm_dest_location",
        ),
    )
    op.create_index(
        "ux_finished_goods_storage_movements_tenant_client_command_id", "finished_goods_storage_movements",
        ["tenant_id", "client_command_id"], unique=True,
    )

    # --- 4. immediate insert-integrity trigger -----------------------------------
    # Independently protects direct SQL: kind/shape, lot existence, location
    # existence/eligibility/tenant-farm match, active-destination (inactive
    # source permitted -- see FINISHED_GOODS_STORAGE_MODEL.md), Decimal
    # envelope (via CHECKs above), combined ledger/storage chronology, no
    # source overdraw, no placement beyond unplaced quantity. Locks the
    # finished-goods lot first (the single global serialization point
    # shared with the amended dispatch ledger trigger below), then any
    # referenced location rows in sorted-UUID order.
    op.execute(
        """
        CREATE FUNCTION enforce_finished_goods_storage_movement_insert_integrity() RETURNS trigger AS $$
        DECLARE
            v_lot_tenant_id UUID;
            v_lot_farm_id UUID;
            v_lot_effective TIMESTAMPTZ;
            v_first_location UUID;
            v_second_location UUID;
            v_src_tenant_id UUID;
            v_src_farm_id UUID;
            v_src_type_code VARCHAR;
            v_dest_tenant_id UUID;
            v_dest_farm_id UUID;
            v_dest_type_code VARCHAR;
            v_dest_status VARCHAR;
            v_available_weight NUMERIC;
            v_available_count BIGINT;
            v_placed_weight NUMERIC;
            v_placed_count BIGINT;
            v_source_balance_weight NUMERIC;
            v_source_balance_count BIGINT;
            v_latest_movement_effective TIMESTAMPTZ;
            v_latest_ledger_effective TIMESTAMPTZ;
        BEGIN
            IF NEW.movement_kind NOT IN ('place', 'transfer', 'release') THEN
                RAISE EXCEPTION 'unrecognized storage movement kind %', NEW.movement_kind;
            END IF;

            SELECT tenant_id, farm_id, effective_time INTO v_lot_tenant_id, v_lot_farm_id, v_lot_effective
            FROM finished_goods_lots WHERE id = NEW.finished_goods_lot_id FOR UPDATE;
            IF v_lot_tenant_id IS NULL THEN
                RAISE EXCEPTION 'finished-goods lot not found for storage movement';
            END IF;
            IF v_lot_tenant_id <> NEW.tenant_id OR v_lot_farm_id <> NEW.farm_id THEN
                RAISE EXCEPTION 'storage movement tenant/farm does not match the finished-goods lot''s own';
            END IF;

            -- Lock referenced location rows in deterministic sorted-UUID
            -- order (never source-then-destination or vice versa by role),
            -- matching the application's own ordering exactly.
            IF NEW.source_location_id IS NOT NULL AND NEW.destination_location_id IS NOT NULL THEN
                IF NEW.source_location_id < NEW.destination_location_id THEN
                    v_first_location := NEW.source_location_id;
                    v_second_location := NEW.destination_location_id;
                ELSE
                    v_first_location := NEW.destination_location_id;
                    v_second_location := NEW.source_location_id;
                END IF;
                PERFORM 1 FROM locations WHERE id = v_first_location FOR UPDATE;
                PERFORM 1 FROM locations WHERE id = v_second_location FOR UPDATE;
            ELSIF NEW.source_location_id IS NOT NULL THEN
                PERFORM 1 FROM locations WHERE id = NEW.source_location_id FOR UPDATE;
            ELSIF NEW.destination_location_id IS NOT NULL THEN
                PERFORM 1 FROM locations WHERE id = NEW.destination_location_id FOR UPDATE;
            END IF;

            IF NEW.source_location_id IS NOT NULL THEN
                SELECT l.tenant_id, l.farm_id, lt.code INTO v_src_tenant_id, v_src_farm_id, v_src_type_code
                FROM locations l JOIN location_types lt ON lt.id = l.location_type_id
                WHERE l.id = NEW.source_location_id;
                IF v_src_tenant_id IS NULL THEN
                    RAISE EXCEPTION 'source location not found for storage movement';
                END IF;
                IF v_src_tenant_id <> NEW.tenant_id OR v_src_farm_id <> NEW.farm_id THEN
                    RAISE EXCEPTION 'storage movement tenant/farm does not match the source location''s own';
                END IF;
                IF v_src_type_code <> 'cold_store_position' THEN
                    RAISE EXCEPTION 'source location is not a storage-eligible cold-store position';
                END IF;
                -- Source is deliberately not required to be active: CMP-018
                -- adds no location-deactivation guard, so requiring an
                -- active source could permanently trap recorded stock.
            END IF;

            IF NEW.destination_location_id IS NOT NULL THEN
                SELECT l.tenant_id, l.farm_id, lt.code, l.status
                INTO v_dest_tenant_id, v_dest_farm_id, v_dest_type_code, v_dest_status
                FROM locations l JOIN location_types lt ON lt.id = l.location_type_id
                WHERE l.id = NEW.destination_location_id;
                IF v_dest_tenant_id IS NULL THEN
                    RAISE EXCEPTION 'destination location not found for storage movement';
                END IF;
                IF v_dest_tenant_id <> NEW.tenant_id OR v_dest_farm_id <> NEW.farm_id THEN
                    RAISE EXCEPTION 'storage movement tenant/farm does not match the destination location''s own';
                END IF;
                IF v_dest_type_code <> 'cold_store_position' THEN
                    RAISE EXCEPTION 'destination location is not a storage-eligible cold-store position';
                END IF;
                IF v_dest_status <> 'active' THEN
                    RAISE EXCEPTION 'destination location is not active';
                END IF;
            END IF;

            IF NEW.effective_time < v_lot_effective THEN
                RAISE EXCEPTION 'storage movement effective time precedes the finished-goods lot''s own effective time';
            END IF;

            SELECT MAX(effective_time) INTO v_latest_movement_effective
            FROM finished_goods_storage_movements WHERE finished_goods_lot_id = NEW.finished_goods_lot_id;
            IF v_latest_movement_effective IS NOT NULL AND NEW.effective_time < v_latest_movement_effective THEN
                RAISE EXCEPTION 'storage movement effective time precedes the finished-goods lot''s latest existing storage movement';
            END IF;

            SELECT MAX(effective_time) INTO v_latest_ledger_effective
            FROM finished_goods_ledger_entries WHERE finished_goods_lot_id = NEW.finished_goods_lot_id;
            IF v_latest_ledger_effective IS NOT NULL AND NEW.effective_time < v_latest_ledger_effective THEN
                RAISE EXCEPTION 'storage movement effective time precedes the finished-goods lot''s latest ledger entry';
            END IF;

            SELECT COALESCE(SUM(weight_delta_kg), 0), COALESCE(SUM(package_count_delta), 0)
            INTO v_available_weight, v_available_count
            FROM finished_goods_ledger_entries WHERE finished_goods_lot_id = NEW.finished_goods_lot_id;

            SELECT
                COALESCE(SUM(CASE WHEN movement_kind = 'place' THEN moved_weight_kg
                                   WHEN movement_kind = 'release' THEN -moved_weight_kg ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN movement_kind = 'place' THEN moved_package_count
                                   WHEN movement_kind = 'release' THEN -moved_package_count ELSE 0 END), 0)
            INTO v_placed_weight, v_placed_count
            FROM finished_goods_storage_movements WHERE finished_goods_lot_id = NEW.finished_goods_lot_id;

            IF NEW.movement_kind = 'place' THEN
                IF NEW.moved_weight_kg > (v_available_weight - v_placed_weight) THEN
                    RAISE EXCEPTION 'placement would exceed unplaced weight for finished-goods lot %', NEW.finished_goods_lot_id;
                END IF;
                IF NEW.moved_package_count > (v_available_count - v_placed_count) THEN
                    RAISE EXCEPTION 'placement would exceed unplaced package count for finished-goods lot %', NEW.finished_goods_lot_id;
                END IF;
            ELSE
                SELECT
                    COALESCE(SUM(CASE WHEN destination_location_id = NEW.source_location_id THEN moved_weight_kg ELSE 0 END), 0)
                    - COALESCE(SUM(CASE WHEN source_location_id = NEW.source_location_id THEN moved_weight_kg ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN destination_location_id = NEW.source_location_id THEN moved_package_count ELSE 0 END), 0)
                    - COALESCE(SUM(CASE WHEN source_location_id = NEW.source_location_id THEN moved_package_count ELSE 0 END), 0)
                INTO v_source_balance_weight, v_source_balance_count
                FROM finished_goods_storage_movements
                WHERE finished_goods_lot_id = NEW.finished_goods_lot_id
                  AND (source_location_id = NEW.source_location_id OR destination_location_id = NEW.source_location_id);

                IF NEW.moved_weight_kg > v_source_balance_weight THEN
                    RAISE EXCEPTION 'storage movement would leave source location with negative weight for finished-goods lot %', NEW.finished_goods_lot_id;
                END IF;
                IF NEW.moved_package_count > v_source_balance_count THEN
                    RAISE EXCEPTION 'storage movement would leave source location with negative package count for finished-goods lot %', NEW.finished_goods_lot_id;
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        "CREATE TRIGGER finished_goods_storage_movements_enforce_insert_integrity "
        "BEFORE INSERT ON finished_goods_storage_movements "
        "FOR EACH ROW EXECUTE FUNCTION enforce_finished_goods_storage_movement_insert_integrity();"
    )

    # --- 5. append-only protection -------------------------------------------------
    op.execute(
        "CREATE TRIGGER finished_goods_storage_movements_no_update BEFORE UPDATE ON finished_goods_storage_movements "
        "FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();"
    )
    op.execute(
        "CREATE TRIGGER finished_goods_storage_movements_no_delete BEFORE DELETE ON finished_goods_storage_movements "
        "FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();"
    )

    # --- 6. versioned ledger insert-integrity trigger (v2 -> v3) --------------------
    # CMP-017's own v2 function is never modified or dropped -- only its
    # trigger attachment is swapped, exactly the idiom used three times
    # before it (CMP-014->015, CMP-015->016, CMP-016->017). v3 reproduces
    # the entire v2 body unchanged and adds, only in the dispatch_issue
    # branch: a check against the lot's latest storage-movement effective
    # time, and a check that post-dispatch available quantity never falls
    # below currently placed quantity (the database-level form of
    # "dispatch may consume only unplaced quantity").
    op.execute(
        """
        CREATE FUNCTION enforce_finished_goods_ledger_entry_insert_integrity_v3() RETURNS trigger AS $$
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
            v_latest_movement_effective TIMESTAMPTZ;
            v_placed_weight NUMERIC;
            v_placed_count BIGINT;
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
                -- lot's ledger AND its physical placement (CMP-018:
                -- finished_goods_storage_movements' own immediate trigger
                -- locks this same row first, so the two are transitively
                -- serialized with no new lock resource).
                PERFORM 1 FROM finished_goods_lots WHERE id = NEW.finished_goods_lot_id FOR UPDATE;

                -- BEFORE INSERT: NEW has not been persisted yet, so this
                -- plain aggregate over existing rows never double-counts it.
                SELECT COALESCE(SUM(weight_delta_kg), 0), COALESCE(SUM(package_count_delta), 0), MAX(effective_time)
                INTO v_prior_weight, v_prior_count, v_prior_max_effective
                FROM finished_goods_ledger_entries WHERE finished_goods_lot_id = NEW.finished_goods_lot_id;

                IF v_prior_max_effective IS NOT NULL AND NEW.effective_time < v_prior_max_effective THEN
                    RAISE EXCEPTION 'dispatch issue effective time precedes the finished-goods lot''s latest existing ledger entry';
                END IF;

                -- CMP-018: dispatch effective time must not precede this
                -- lot's latest storage movement either -- the combined
                -- ledger/storage chronology stays monotonic in both
                -- directions.
                SELECT MAX(effective_time) INTO v_latest_movement_effective
                FROM finished_goods_storage_movements WHERE finished_goods_lot_id = NEW.finished_goods_lot_id;
                IF v_latest_movement_effective IS NOT NULL AND NEW.effective_time < v_latest_movement_effective THEN
                    RAISE EXCEPTION 'dispatch issue effective time precedes the finished-goods lot''s latest storage movement';
                END IF;

                IF v_prior_weight + NEW.weight_delta_kg < 0 THEN
                    RAISE EXCEPTION 'dispatch issue would leave finished-goods lot % with negative available weight', NEW.finished_goods_lot_id;
                END IF;
                IF v_prior_count + NEW.package_count_delta < 0 THEN
                    RAISE EXCEPTION 'dispatch issue would leave finished-goods lot % with negative available package count', NEW.finished_goods_lot_id;
                END IF;

                -- CMP-018: dispatch may only consume currently unplaced
                -- quantity -- the database-level form of release-before-
                -- dispatch, independent of and in addition to the plain
                -- negative-balance checks above.
                SELECT
                    COALESCE(SUM(CASE WHEN movement_kind = 'place' THEN moved_weight_kg
                                       WHEN movement_kind = 'release' THEN -moved_weight_kg ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN movement_kind = 'place' THEN moved_package_count
                                       WHEN movement_kind = 'release' THEN -moved_package_count ELSE 0 END), 0)
                INTO v_placed_weight, v_placed_count
                FROM finished_goods_storage_movements WHERE finished_goods_lot_id = NEW.finished_goods_lot_id;

                IF (v_prior_weight + NEW.weight_delta_kg) < v_placed_weight THEN
                    RAISE EXCEPTION 'dispatch issue would leave finished-goods lot % with available weight below physically placed quantity', NEW.finished_goods_lot_id;
                END IF;
                IF (v_prior_count + NEW.package_count_delta) < v_placed_count THEN
                    RAISE EXCEPTION 'dispatch issue would leave finished-goods lot % with available package count below physically placed quantity', NEW.finished_goods_lot_id;
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
        FOR EACH ROW EXECUTE FUNCTION enforce_finished_goods_ledger_entry_insert_integrity_v3();
        """
    )


def downgrade() -> None:
    bind = op.get_bind()

    # --- downgrade guard: storage movement history is independent operational --
    # data, never reconstructible -- CMP-015/017's own unconditional-block
    # model.
    movement_count = bind.execute(sa.text("SELECT count(*) FROM finished_goods_storage_movements")).scalar_one()
    if movement_count > 0:
        raise RuntimeError(
            "Cannot downgrade past CMP-018: finished_goods_storage_movements contains history. Storage "
            "movement history is independent operational data, not reconstructible from any other table. "
            "Do not downgrade."
        )

    # --- restore the exact CMP-017 (v2) ledger trigger attachment ----------------
    # v2's own function was never dropped by CMP-017 or by this migration's
    # own upgrade() -- only re-attach it; nothing to recreate.
    op.execute("DROP TRIGGER finished_goods_ledger_entries_enforce_insert_integrity ON finished_goods_ledger_entries")
    op.execute("DROP FUNCTION IF EXISTS enforce_finished_goods_ledger_entry_insert_integrity_v3()")
    op.execute(
        """
        CREATE TRIGGER finished_goods_ledger_entries_enforce_insert_integrity
        BEFORE INSERT ON finished_goods_ledger_entries
        FOR EACH ROW EXECUTE FUNCTION enforce_finished_goods_ledger_entry_insert_integrity_v2();
        """
    )

    # --- drop CMP-018 storage objects ---------------------------------------------
    op.execute("DROP TRIGGER IF EXISTS finished_goods_storage_movements_no_delete ON finished_goods_storage_movements")
    op.execute("DROP TRIGGER IF EXISTS finished_goods_storage_movements_no_update ON finished_goods_storage_movements")
    op.execute(
        "DROP TRIGGER IF EXISTS finished_goods_storage_movements_enforce_insert_integrity "
        "ON finished_goods_storage_movements"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_finished_goods_storage_movement_insert_integrity()")

    # Dropping the table cascades its own indexes/constraints automatically.
    op.drop_table("finished_goods_storage_movements")

    # --- remove only the CMP-018-added composite unique on locations -------------
    op.drop_constraint("uq_locations_tenant_farm_id", "locations", type_="unique")

    # Every packing/dispatch/audit row, and the location_types/hierarchy
    # seed data, are untouched above -- nothing to restore for them.
    # CMP-016A's env.py guard targets a different table/revision entirely
    # and is unaffected by any of this.
