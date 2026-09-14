import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

# PILOT-SCAN-001: the exact current entity names this registry supports --
# never a fabricated "lot"/"placement" concept. `batch_carrier_assignment`
# is the stable PHYSICAL PLACEMENT identity (CMP-006/HARVEST-OPS-001's own
# name for "what crop batch does this carrier contain right now"),
# deliberately independent of both the permanent `carrier` identity and the
# `crop_batch` identity it belongs to -- see docs/domain/QR_SCAN_MODEL.md.
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

_ENTITY_COLUMNS = (
    "crop_batch_id",
    "location_id",
    "carrier_id",
    "asset_id",
    "batch_carrier_assignment_id",
    "harvested_produce_lot_id",
    "graded_produce_lot_id",
    "finished_goods_lot_id",
)


class QrIdentifier(Base):
    """PILOT-SCAN-001: the one QR identity registry for every scannable
    GrowCMP entity. One typed nullable FK column per supported entity type
    -- mirroring `FarmWorkItem`'s own structured-context precedent
    (real composite FKs, never a bare polymorphic `entity_id` with no
    referential integrity) -- with `entity_type` as a redundant, CHECK-
    enforced discriminator naming exactly which one is populated.

    `token` is an opaque, high-entropy, URL-safe identifier chosen by the
    server (`secrets.token_urlsafe`) -- it encodes no mutable operational
    fact (crop, location, status, quantity, occupant) and is never itself
    an authorization grant; every resolve still goes through the caller's
    own authenticated tenant/permission context (see `qr_service`).

    Reprinting reuses the one active row for an entity (`status='active'`,
    enforced per-entity-type by the eight partial unique indexes below,
    each a straight mirror of `Occupancy`'s own
    `ux_occupancies_active_occupant_asset`/`..._carrier` XOR-uniqueness
    pattern) -- "generate" is idempotent, never minting a second identity.
    Only `status`/`revoked_at`/`revoked_by_user_id` may ever change after
    insert (enforced by `enforce_qr_identifier_mutable_fields`, this
    migration); no hard delete is possible (`reject_hard_delete`, already
    defined by 5f3a9c2d1b44, reused unmodified)."""

    __tablename__ = "qr_identifiers"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    entity_type: Mapped[str] = mapped_column(String, nullable=False)

    crop_batch_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    location_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    carrier_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    asset_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    batch_carrier_assignment_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    harvested_produce_lot_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    graded_produce_lot_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    finished_goods_lot_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    token: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "entity_type IN " + str(QR_IDENTIFIER_ENTITY_TYPES), name="ck_qr_identifiers_entity_type"
        ),
        CheckConstraint("status IN " + str(QR_IDENTIFIER_STATUSES), name="ck_qr_identifiers_status"),
        CheckConstraint(
            "(status = 'active' AND revoked_at IS NULL AND revoked_by_user_id IS NULL) OR "
            "(status = 'revoked' AND revoked_at IS NOT NULL AND revoked_by_user_id IS NOT NULL)",
            name="ck_qr_identifiers_revocation_shape",
        ),
        # Exactly one typed entity column is populated, and it matches
        # `entity_type` -- mirrors `BatchCarrierAssignment`'s own
        # `ck_batch_carrier_assignments_exactly_one_opener` "exactly one of
        # N" shape.
        CheckConstraint(
            "(CASE WHEN entity_type = 'crop_batch' THEN crop_batch_id IS NOT NULL ELSE crop_batch_id IS NULL END) AND "
            "(CASE WHEN entity_type = 'location' THEN location_id IS NOT NULL ELSE location_id IS NULL END) AND "
            "(CASE WHEN entity_type = 'carrier' THEN carrier_id IS NOT NULL ELSE carrier_id IS NULL END) AND "
            "(CASE WHEN entity_type = 'asset' THEN asset_id IS NOT NULL ELSE asset_id IS NULL END) AND "
            "(CASE WHEN entity_type = 'batch_carrier_assignment' THEN batch_carrier_assignment_id IS NOT NULL "
            "ELSE batch_carrier_assignment_id IS NULL END) AND "
            "(CASE WHEN entity_type = 'harvested_produce_lot' THEN harvested_produce_lot_id IS NOT NULL "
            "ELSE harvested_produce_lot_id IS NULL END) AND "
            "(CASE WHEN entity_type = 'graded_produce_lot' THEN graded_produce_lot_id IS NOT NULL "
            "ELSE graded_produce_lot_id IS NULL END) AND "
            "(CASE WHEN entity_type = 'finished_goods_lot' THEN finished_goods_lot_id IS NOT NULL "
            "ELSE finished_goods_lot_id IS NULL END)",
            name="ck_qr_identifiers_entity_shape",
        ),
        Index("ux_qr_identifiers_token", "token", unique=True),
        *(
            Index(
                f"ux_qr_identifiers_active_{col}",
                "tenant_id",
                col,
                unique=True,
                postgresql_where=text(f"status = 'active' AND {col} IS NOT NULL"),
            )
            for col in _ENTITY_COLUMNS
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "crop_batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_qr_identifiers_crop_batch",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "location_id"],
            ["locations.tenant_id", "locations.farm_id", "locations.id"],
            name="fk_qr_identifiers_location",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "carrier_id"],
            ["carriers.tenant_id", "carriers.farm_id", "carriers.id"],
            name="fk_qr_identifiers_carrier",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "asset_id"],
            ["assets.tenant_id", "assets.farm_id", "assets.id"],
            name="fk_qr_identifiers_asset",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_carrier_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id",
                "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_qr_identifiers_batch_carrier_assignment",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "harvested_produce_lot_id"],
            [
                "harvested_produce_lots.tenant_id",
                "harvested_produce_lots.farm_id",
                "harvested_produce_lots.id",
            ],
            name="fk_qr_identifiers_harvested_produce_lot",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "graded_produce_lot_id"],
            ["graded_produce_lots.tenant_id", "graded_produce_lots.farm_id", "graded_produce_lots.id"],
            name="fk_qr_identifiers_graded_produce_lot",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "finished_goods_lot_id"],
            ["finished_goods_lots.tenant_id", "finished_goods_lots.farm_id", "finished_goods_lots.id"],
            name="fk_qr_identifiers_finished_goods_lot",
        ),
    )
