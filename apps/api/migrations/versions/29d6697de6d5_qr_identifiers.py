"""qr identifiers (PILOT-SCAN-001)

Introduces `qr_identifiers` -- the one QR identity registry backing
physical label printing and scan resolution for every scannable GrowCMP
entity. One typed nullable FK column per supported entity type (crop
batch, location, carrier, asset, batch carrier assignment/"placement",
harvested produce lot, graded produce lot, finished goods lot) -- the same
structured-real-FK shape `farm_work_items` already established for its own
context references (3a278fa65f80), deliberately never a bare polymorphic
`entity_id` with no referential integrity. `entity_type` is a redundant,
CHECK-enforced discriminator naming exactly which one typed column is
populated.

`token` is server-chosen (`secrets.token_urlsafe`), opaque, and globally
unique (`ux_qr_identifiers_token`) -- it encodes no mutable operational
fact and is never itself an authorization grant (see
docs/domain/QR_SCAN_MODEL.md). Eight partial unique indexes (one per typed
column, `WHERE status = 'active'`) enforce "at most one active QR identity
per entity" at the database level -- mirroring `Occupancy`'s own
`ux_occupancies_active_occupant_asset`/`..._carrier` XOR-uniqueness
pattern -- so concurrent "generate" requests for the same entity can never
mint two active identities; the service layer additionally treats a
unique-violation race as "return the identity that won".

`farm_id` is NOT NULL: every one of the eight entity types this ticket
supports is already farm-scoped in the current domain (no tenant-wide
entity type exists yet), so a nullable `farm_id` would be unused,
speculative schema (CLAUDE.md: no code/schema for hypothetical future
requirements). If a future ticket adds a genuinely tenant-wide scannable
entity, that migration can widen this column then.

Only `status`/`revoked_at`/`revoked_by_user_id` may ever change after
insert (`enforce_qr_identifier_mutable_fields`, BEFORE UPDATE) -- every
identity/content field (tenant/farm, entity_type, every typed entity
column, token, created_by_user_id/created_at) is frozen for life. No hard
delete is possible (`reject_hard_delete`, already defined by 5f3a9c2d1b44,
reused unmodified).

Downgrade is destructive by nature (drops the new table) and is guarded
like every other domain-introducing migration in this codebase: it raises
and makes zero schema change if any `qr_identifiers` row already exists.

Revision ID: 29d6697de6d5
Revises: 3a278fa65f80
Create Date: 2026-09-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "29d6697de6d5"
down_revision: Union[str, None] = "3a278fa65f80"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


QR_IDENTIFIER_ENTITY_TYPES = (
    "crop_batch",
    "location",
    "carrier",
    "asset",
    "batch_carrier_assignment",
    "harvested_produce_lot",
    "graded_produce_lot",
    "finished_goods_lot",
)
QR_IDENTIFIER_STATUSES = ("active", "revoked")

_ENTITY_COLUMN_TO_TABLE = {
    "crop_batch_id": ("crop_batch", "crop_batches"),
    "location_id": ("location", "locations"),
    "carrier_id": ("carrier", "carriers"),
    "asset_id": ("asset", "assets"),
    "batch_carrier_assignment_id": ("batch_carrier_assignment", "batch_carrier_assignments"),
    "harvested_produce_lot_id": ("harvested_produce_lot", "harvested_produce_lots"),
    "graded_produce_lot_id": ("graded_produce_lot", "graded_produce_lots"),
    "finished_goods_lot_id": ("finished_goods_lot", "finished_goods_lots"),
}


def upgrade() -> None:
    op.create_table(
        "qr_identifiers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("crop_batch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("carrier_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("batch_carrier_assignment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("harvested_produce_lot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("graded_produce_lot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("finished_goods_lot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("token", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.CheckConstraint(
            "entity_type IN " + str(QR_IDENTIFIER_ENTITY_TYPES), name="ck_qr_identifiers_entity_type"
        ),
        sa.CheckConstraint("status IN " + str(QR_IDENTIFIER_STATUSES), name="ck_qr_identifiers_status"),
        sa.CheckConstraint(
            "(status = 'active' AND revoked_at IS NULL AND revoked_by_user_id IS NULL) OR "
            "(status = 'revoked' AND revoked_at IS NOT NULL AND revoked_by_user_id IS NOT NULL)",
            name="ck_qr_identifiers_revocation_shape",
        ),
        sa.CheckConstraint(
            " AND ".join(
                f"(CASE WHEN entity_type = '{entity_type}' THEN {col} IS NOT NULL ELSE {col} IS NULL END)"
                for col, (entity_type, _) in _ENTITY_COLUMN_TO_TABLE.items()
            ),
            name="ck_qr_identifiers_entity_shape",
        ),
    )

    op.create_index("ux_qr_identifiers_token", "qr_identifiers", ["token"], unique=True)
    for col in _ENTITY_COLUMN_TO_TABLE:
        op.create_index(
            f"ux_qr_identifiers_active_{col}",
            "qr_identifiers",
            ["tenant_id", col],
            unique=True,
            postgresql_where=sa.text(f"status = 'active' AND {col} IS NOT NULL"),
        )

    for col, (_, table) in _ENTITY_COLUMN_TO_TABLE.items():
        op.create_foreign_key(
            f"fk_qr_identifiers_{col[:-3]}",
            "qr_identifiers",
            table,
            ["tenant_id", "farm_id", col],
            ["tenant_id", "farm_id", "id"],
        )

    op.execute(
        """
        CREATE FUNCTION enforce_qr_identifier_mutable_fields() RETURNS trigger AS $$
        BEGIN
            IF NEW.tenant_id <> OLD.tenant_id OR NEW.farm_id <> OLD.farm_id
               OR NEW.entity_type <> OLD.entity_type
               OR NEW.crop_batch_id IS DISTINCT FROM OLD.crop_batch_id
               OR NEW.location_id IS DISTINCT FROM OLD.location_id
               OR NEW.carrier_id IS DISTINCT FROM OLD.carrier_id
               OR NEW.asset_id IS DISTINCT FROM OLD.asset_id
               OR NEW.batch_carrier_assignment_id IS DISTINCT FROM OLD.batch_carrier_assignment_id
               OR NEW.harvested_produce_lot_id IS DISTINCT FROM OLD.harvested_produce_lot_id
               OR NEW.graded_produce_lot_id IS DISTINCT FROM OLD.graded_produce_lot_id
               OR NEW.finished_goods_lot_id IS DISTINCT FROM OLD.finished_goods_lot_id
               OR NEW.token <> OLD.token
               OR NEW.created_by_user_id <> OLD.created_by_user_id OR NEW.created_at <> OLD.created_at
            THEN
                RAISE EXCEPTION 'qr_identifier identity/content fields are immutable; only revocation status may change';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER qr_identifiers_enforce_mutable_fields
        BEFORE UPDATE ON qr_identifiers
        FOR EACH ROW EXECUTE FUNCTION enforce_qr_identifier_mutable_fields();
        """
    )
    op.execute(
        """
        CREATE TRIGGER qr_identifiers_no_delete
        BEFORE DELETE ON qr_identifiers
        FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    row_count = bind.execute(sa.text("SELECT count(*) FROM qr_identifiers")).scalar_one()
    if row_count > 0:
        raise RuntimeError(
            "Cannot downgrade past PILOT-SCAN-001's qr_identifiers table: "
            f"{row_count} qr_identifiers row(s) already exist. Downgrading would destroy printed-label identity."
        )

    op.execute("DROP TRIGGER IF EXISTS qr_identifiers_no_delete ON qr_identifiers")
    op.execute("DROP TRIGGER IF EXISTS qr_identifiers_enforce_mutable_fields ON qr_identifiers")
    op.execute("DROP FUNCTION IF EXISTS enforce_qr_identifier_mutable_fields()")
    op.drop_table("qr_identifiers")
