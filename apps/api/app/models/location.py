import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.common import TimestampMixin


class Location(TimestampMixin, Base):
    __tablename__ = "locations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    parent_location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("locations.id"), nullable=True
    )
    location_type_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("location_types.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    greenhouse_classification: Mapped[str | None] = mapped_column(String, nullable=True)
    occupiable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # DOMAIN-FARM-002: configured occupant capacity. NULL means an effective
    # capacity of 1 (backward-compatible exclusive behavior); distinct from
    # `occupiable`, which governs whether this location may be a target at
    # all. See CHECK below and `occupancies_enforce_insert_integrity`
    # (migration) for the authoritative, concurrency-safe enforcement.
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # UX-IA-001: command idempotency for update/deactivate/reactivate only
    # -- create_location/bulk_generate_children remain non-idempotent
    # (acknowledged, pre-existing debt, explicitly out of scope). Mirrors
    # InventoryItem/InventoryCategory's own per-command column-pair
    # convention (docs/domain/STORE_INVENTORY_MODEL.md §5) -- the first
    # idempotency support this table has had for any command.
    update_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    update_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)
    deactivation_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    deactivation_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)
    reactivation_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    reactivation_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('active', 'inactive')", name="ck_locations_status"),
        CheckConstraint(
            "greenhouse_classification IS NULL OR greenhouse_classification IN "
            "('nursery', 'leafy_greens', 'vines')",
            name="ck_locations_greenhouse_classification_allowed",
        ),
        CheckConstraint("capacity IS NULL OR capacity >= 1", name="ck_locations_capacity_positive"),
        # Whether classification is required/forbidden depends on the row's
        # location_type (greenhouse vs not) — a plain CHECK can't join to
        # location_types, so that half of the rule is enforced by a
        # PostgreSQL trigger (in the migration) plus schema/service checks.
        # DOMAIN-FARM-001: the same trigger also enforces immutability —
        # once set on a greenhouse, greenhouse_classification can never
        # change (UPDATE is rejected if NEW differs from OLD).
        Index(
            "ux_locations_sibling_code_lower",
            "parent_location_id",
            func.lower(code),
            unique=True,
            postgresql_where=text("parent_location_id IS NOT NULL"),
        ),
        Index(
            "ux_locations_root_code_lower",
            "farm_id",
            func.lower(code),
            unique=True,
            postgresql_where=text("parent_location_id IS NULL"),
        ),
        # CMP-018-added: backs the composite foreign keys from
        # finished_goods_storage_movements.source_location_id/
        # destination_location_id, matching every other typed-source
        # composite FK convention in this codebase. Removed on clean
        # CMP-018 downgrade.
        UniqueConstraint("tenant_id", "farm_id", "id", name="uq_locations_tenant_farm_id"),
        # UX-IA-001: tenant-scoped idempotency indexes for update/
        # deactivate/reactivate, mirroring InventoryItem/InventoryCategory's
        # own per-command partial-unique-index shape exactly.
        Index(
            "ux_locations_tenant_update_command", "tenant_id", "update_client_command_id",
            unique=True, postgresql_where=text("update_client_command_id IS NOT NULL"),
        ),
        Index(
            "ux_locations_tenant_deactivation_command", "tenant_id", "deactivation_client_command_id",
            unique=True, postgresql_where=text("deactivation_client_command_id IS NOT NULL"),
        ),
        Index(
            "ux_locations_tenant_reactivation_command", "tenant_id", "reactivation_client_command_id",
            unique=True, postgresql_where=text("reactivation_client_command_id IS NOT NULL"),
        ),
    )
