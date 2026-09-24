"""water delivery end events

UX-OPS-001D0 (N07): an immutable, idempotent way to END an ongoing
`WaterDeliveryEvent` (one created with `effective_end = NULL`) without ever
updating or deleting the original, insert-only delivery row.

Additive only:

1. `uq_water_delivery_events_tenant_farm_id` -- a composite
   `(tenant_id, farm_id, id)` unique key on the existing
   `water_delivery_events` table, so the new end-event table can carry a
   tenant/farm-pinned foreign key. `id` is already the primary key, so this
   constraint can never fail on existing rows; no existing row, column,
   constraint, or trigger is changed. `ALTER TABLE ... ADD CONSTRAINT`
   fires no row trigger, so the table's `reject_append_only_mutation()`
   UPDATE trigger is untouched.

2. `water_delivery_end_events` -- the append-only closure ledger
   (`effective_end`, optional `note`, recorder, command identity). Exactly
   one end event per delivery (`ux_water_delivery_end_events_delivery`);
   command identity unique per tenant
   (`ux_water_delivery_end_events_tenant_client_command_id`); the end event
   is pinned to its delivery's own tenant AND farm by
   `fk_water_delivery_end_events_tenant_farm_delivery`.

3. `enforce_water_delivery_end_event_parent()` -- a BEFORE INSERT trigger
   that rejects ending a delivery that was created WITH an end (its original
   end stays authoritative) and an end before the delivery's start. Both
   are cross-row rules a CHECK constraint cannot express. The future-end
   rule stays in the service, matching `water_delivery_events`' own
   existing policy.

4. UPDATE/DELETE on the new table are rejected by the pre-existing, generic
   `reject_append_only_mutation()` (c48f21a6b3d9), exactly like
   `water_delivery_events` itself.

No backfill: a delivery created with an `effective_end` never gets an end
event -- its original end remains authoritative.

Downgrade is guarded like every other ledger-introducing migration in this
codebase: it refuses (and changes nothing) if any end event exists, since
dropping the table would destroy immutable closure history.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3686130d89a9"
down_revision: str | None = "b44ba79079ef"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_water_delivery_events_tenant_farm_id", "water_delivery_events", ["tenant_id", "farm_id", "id"]
    )

    op.create_table(
        "water_delivery_end_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("water_delivery_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("effective_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("recorded_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "water_delivery_event_id"],
            ["water_delivery_events.tenant_id", "water_delivery_events.farm_id", "water_delivery_events.id"],
            name="fk_water_delivery_end_events_tenant_farm_delivery",
        ),
    )
    op.create_index(
        "ux_water_delivery_end_events_delivery", "water_delivery_end_events", ["water_delivery_event_id"],
        unique=True,
    )
    op.create_index(
        "ux_water_delivery_end_events_tenant_client_command_id", "water_delivery_end_events",
        ["tenant_id", "client_command_id"], unique=True,
    )

    op.execute(
        """
        CREATE FUNCTION enforce_water_delivery_end_event_parent() RETURNS trigger AS $$
        DECLARE
            parent_start timestamptz;
            parent_end timestamptz;
        BEGIN
            SELECT effective_start, effective_end INTO parent_start, parent_end
            FROM water_delivery_events
            WHERE id = NEW.water_delivery_event_id AND tenant_id = NEW.tenant_id AND farm_id = NEW.farm_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'water delivery event % not found in the end event''s tenant/farm',
                    NEW.water_delivery_event_id;
            END IF;
            IF parent_end IS NOT NULL THEN
                RAISE EXCEPTION 'water delivery event % was recorded with an effective_end and cannot be ended',
                    NEW.water_delivery_event_id;
            END IF;
            IF NEW.effective_end < parent_start THEN
                RAISE EXCEPTION 'water delivery end event effective_end % is before delivery % effective_start %',
                    NEW.effective_end, NEW.water_delivery_event_id, parent_start;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER water_delivery_end_events_enforce_parent
        BEFORE INSERT ON water_delivery_end_events
        FOR EACH ROW EXECUTE FUNCTION enforce_water_delivery_end_event_parent();
        """
    )
    op.execute(
        """
        CREATE TRIGGER water_delivery_end_events_no_update
        BEFORE UPDATE ON water_delivery_end_events
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER water_delivery_end_events_no_delete
        BEFORE DELETE ON water_delivery_end_events
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    end_event_count = bind.execute(sa.text("SELECT count(*) FROM water_delivery_end_events")).scalar_one()
    if end_event_count > 0:
        raise RuntimeError(
            "Cannot downgrade past UX-OPS-001D0: "
            f"{end_event_count} existing water_delivery_end_events row(s) would be destroyed."
        )

    op.execute("DROP TRIGGER IF EXISTS water_delivery_end_events_no_delete ON water_delivery_end_events")
    op.execute("DROP TRIGGER IF EXISTS water_delivery_end_events_no_update ON water_delivery_end_events")
    op.execute("DROP TRIGGER IF EXISTS water_delivery_end_events_enforce_parent ON water_delivery_end_events")
    op.execute("DROP FUNCTION IF EXISTS enforce_water_delivery_end_event_parent()")
    op.drop_index("ux_water_delivery_end_events_tenant_client_command_id", table_name="water_delivery_end_events")
    op.drop_index("ux_water_delivery_end_events_delivery", table_name="water_delivery_end_events")
    op.drop_table("water_delivery_end_events")
    op.drop_constraint("uq_water_delivery_events_tenant_farm_id", "water_delivery_events", type_="unique")
