"""vines grow cube disposition identity

VINES-OPS-002 -- production_disposition_service.py, production_disposition_
events, and the batch_carrier_assignments population-root/opener/releaser
machinery are all already carrier-type-generic (proven by
`a5c9e21f7b64`'s own triggers, which never mention `production_cultivation_
plate` anywhere): a `grow_bag`'s BatchCarrierAssignment -- created self-
referencing its own `population_root_batch_carrier_assignment_id` by
VINES-OPS-001B's `vines_production_transfer_service.py`, exactly like a
Leafy Production Cultivation Plate -- is already a valid Production
Disposition population lineage root with zero schema change. This migration
adds exactly the one piece that IS genuinely new: `grow_bag`'s own
`ProductionDispositionEvent.quantity_delta` is an anonymous count (correct
for a Plate, whose individual wells carry no separate traceable identity),
but Vines' frozen physical model makes one Grow Cube = one plant, and the
ticket requires truthful, unambiguous plant-level loss identity -- never a
bare count subtracted from a Gutter or Bag.

`production_disposition_event_grow_cubes` names exactly which Grow Cube(s) a
RECORD command's own REDUCTION event removed from population -- append-only,
one row per Grow Cube. No row is ever attached to a REVERSAL event: reversing
a REDUCTION (`production_disposition_service.correct_disposition`, already
unmodified-generic) restores every one of that REDUCTION's own named Grow
Cube(s) to disposal eligibility automatically, because every "already
disposed" check (service-side AND this migration's own trigger backstop)
walks the REDUCTION -> its own REVERSAL relationship at query time rather
than reading a static per-row status column.

The trigger `enforce_production_disposition_grow_cube_not_already_disposed`
is DB-level defense-in-depth only -- correctness under true concurrency
already comes from `record_grow_cube_disposition`'s own CropBatch-row lock
(mirrors `record_disposition`'s established lock-first discipline exactly: a
Grow Cube belongs to exactly one Batch, so two commands racing to dispose the
same Grow Cube always serialize behind that lock before either re-checks
"already disposed"), the same "service pre-check + DB CHECK-violation
backstop" pattern this module's own chronological-balance trigger already
established.

Also seeds one additional platform-approved `production_disposition_reasons`
row, `culled` -- the ticket's own example Vines disposition reason with no
existing equivalent in the LEAFY-OPS-001 catalog (`dead`, `disease_removal`,
`pest_damage`, `mechanical_damage`, `quality_removal`, `other` already cover
the rest). Reused by BOTH Leafy and Vines identically -- this table has no
carrier-type scoping column, by design (LEAFY-OPS-001's own docstring).

Revision ID: ecedd713789a
Revises: 43246a360bbd
Create Date: 2026-09-08 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ecedd713789a"
down_revision: str | None = "43246a360bbd"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_NOT_ALREADY_DISPOSED_MARKER = "CMP-DOMAIN-VINES-001 grow cube already disposed"

_NOT_ALREADY_DISPOSED_FUNCTION = f"""
    CREATE FUNCTION enforce_production_disposition_grow_cube_not_already_disposed() RETURNS trigger AS $$
    DECLARE
        v_event_kind TEXT;
        v_conflict BOOLEAN;
    BEGIN
        SELECT event_kind INTO v_event_kind
        FROM production_disposition_events WHERE id = NEW.production_disposition_event_id;
        IF v_event_kind IS NULL THEN
            RAISE EXCEPTION 'production disposition event not found';
        END IF;
        IF v_event_kind <> 'REDUCTION' THEN
            RAISE EXCEPTION 'a grow cube identity row may only be attached to a REDUCTION event';
        END IF;

        SELECT EXISTS (
            SELECT 1 FROM production_disposition_event_grow_cubes gc
            JOIN production_disposition_events e ON e.id = gc.production_disposition_event_id
            WHERE gc.grow_cube_carrier_id = NEW.grow_cube_carrier_id
              AND gc.id <> NEW.id
              AND e.event_kind = 'REDUCTION'
              AND NOT EXISTS (
                  SELECT 1 FROM production_disposition_events r WHERE r.reverses_event_id = e.id
              )
        ) INTO v_conflict;
        IF v_conflict THEN
            RAISE EXCEPTION '{_NOT_ALREADY_DISPOSED_MARKER}' USING ERRCODE = '23514';
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

_REJECT_MUTATION_FUNCTION_NAME = "reject_append_only_mutation"


def upgrade() -> None:
    bind = op.get_bind()

    op.create_table(
        "production_disposition_event_grow_cubes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column(
            "production_disposition_event_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("production_disposition_events.id"), nullable=False,
        ),
        sa.Column("grow_cube_carrier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("carriers.id"), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint(
            "production_disposition_event_id", "grow_cube_carrier_id",
            name="ux_production_disposition_event_grow_cubes_event_carrier",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "production_disposition_event_id"],
            [
                "production_disposition_events.tenant_id", "production_disposition_events.farm_id",
                "production_disposition_events.id",
            ],
            name="fk_production_disposition_event_grow_cubes_tenant_farm_event",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "grow_cube_carrier_id"],
            ["carriers.tenant_id", "carriers.farm_id", "carriers.id"],
            name="fk_production_disposition_event_grow_cubes_tenant_farm_carrier",
        ),
    )
    op.create_index(
        "ix_production_disposition_event_grow_cubes_carrier",
        "production_disposition_event_grow_cubes", ["grow_cube_carrier_id"],
    )
    op.create_index(
        "ix_production_disposition_event_grow_cubes_event",
        "production_disposition_event_grow_cubes", ["production_disposition_event_id"],
    )

    op.execute(_NOT_ALREADY_DISPOSED_FUNCTION)
    op.execute(
        "CREATE TRIGGER trg_production_disposition_grow_cube_not_already_disposed "
        "BEFORE INSERT ON production_disposition_event_grow_cubes "
        "FOR EACH ROW EXECUTE FUNCTION enforce_production_disposition_grow_cube_not_already_disposed();"
    )
    # Append-only: no UPDATE or DELETE ever, mirroring every other
    # disposition-event-shaped table in this codebase (`reject_append_only_
    # mutation` already exists, created by e2a7c9f4b816).
    op.execute(
        "CREATE TRIGGER trg_production_disposition_event_grow_cubes_no_update "
        "BEFORE UPDATE ON production_disposition_event_grow_cubes "
        f"FOR EACH ROW EXECUTE FUNCTION {_REJECT_MUTATION_FUNCTION_NAME}();"
    )
    op.execute(
        "CREATE TRIGGER trg_production_disposition_event_grow_cubes_no_delete "
        "BEFORE DELETE ON production_disposition_event_grow_cubes "
        f"FOR EACH ROW EXECUTE FUNCTION {_REJECT_MUTATION_FUNCTION_NAME}();"
    )

    bind.execute(
        sa.text("INSERT INTO production_disposition_reasons (code, name) VALUES (:code, :name)"),
        {"code": "culled", "name": "Culled"},
    )


def downgrade() -> None:
    bind = op.get_bind()
    row_count = bind.execute(
        sa.text("SELECT count(*) FROM production_disposition_event_grow_cubes")
    ).scalar_one()
    if row_count > 0:
        raise RuntimeError(
            "Cannot downgrade past VINES-OPS-002: "
            f"{row_count} existing production_disposition_event_grow_cubes row(s) would be destroyed."
        )
    culled_in_use = bind.execute(
        sa.text("SELECT count(*) FROM production_disposition_events WHERE reason_code = 'culled'")
    ).scalar_one()
    if culled_in_use > 0:
        raise RuntimeError(
            "Cannot downgrade past VINES-OPS-002: "
            f"{culled_in_use} existing production_disposition_events row(s) already use reason_code='culled'."
        )

    op.execute("DROP TRIGGER trg_production_disposition_event_grow_cubes_no_delete ON production_disposition_event_grow_cubes")
    op.execute("DROP TRIGGER trg_production_disposition_event_grow_cubes_no_update ON production_disposition_event_grow_cubes")
    op.execute("DROP TRIGGER trg_production_disposition_grow_cube_not_already_disposed ON production_disposition_event_grow_cubes")
    op.execute("DROP FUNCTION enforce_production_disposition_grow_cube_not_already_disposed()")
    op.drop_index("ix_production_disposition_event_grow_cubes_event", table_name="production_disposition_event_grow_cubes")
    op.drop_index("ix_production_disposition_event_grow_cubes_carrier", table_name="production_disposition_event_grow_cubes")
    op.drop_table("production_disposition_event_grow_cubes")
    bind.execute(sa.text("DELETE FROM production_disposition_reasons WHERE code = 'culled'"))
