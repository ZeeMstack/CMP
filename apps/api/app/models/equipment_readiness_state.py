import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.common import TimestampMixin

READINESS_ENTITY_TYPES = ("asset", "carrier")
# PILOT-ASSET-001: `IN_USE` is deliberately never a persisted value here --
# see docs/domain/EQUIPMENT_READINESS_MODEL.md ("Readiness state model").
READINESS_STATES = (
    "unknown", "awaiting_cleaning", "cleaning_completed", "ready", "damaged", "maintenance", "retired",
)
READINESS_TERMINAL_STATES = ("retired",)


class EquipmentReadinessState(TimestampMixin, Base):
    """PILOT-ASSET-001: a CURRENT-STATE row (ADR-005), one per
    readiness-tracked Asset/Carrier -- identity/content fields are frozen
    for life by `enforce_equipment_readiness_state_mutable_fields`; only
    `current_state`/`state_changed_at`/`state_changed_by_user_id`/
    `state_note`/`last_cleaning_event_id` ever change, and only through
    `equipment_readiness_service`'s owning commands. Full transition
    history is read from `audit_events`
    (`entity_type='equipment_readiness_state'`), never duplicated onto
    this row -- mirrors `FarmWorkItem`/`CropIssue` exactly. See
    docs/domain/EQUIPMENT_READINESS_MODEL.md."""

    __tablename__ = "equipment_readiness_states"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    asset_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    carrier_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    current_state: Mapped[str] = mapped_column(String, nullable=False, default="unknown")
    state_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state_changed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    state_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_cleaning_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cleaning_events.id"), nullable=True
    )

    awaiting_cleaning_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    awaiting_cleaning_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)
    ready_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    ready_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)
    damaged_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    damaged_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)
    maintenance_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    maintenance_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)
    return_from_maintenance_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    return_from_maintenance_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)
    retire_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    retire_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "entity_type IN " + str(READINESS_ENTITY_TYPES), name="ck_equipment_readiness_states_entity_type"
        ),
        CheckConstraint("current_state IN " + str(READINESS_STATES), name="ck_equipment_readiness_states_state"),
        CheckConstraint(
            "(entity_type = 'asset' AND asset_id IS NOT NULL AND carrier_id IS NULL) OR "
            "(entity_type = 'carrier' AND carrier_id IS NOT NULL AND asset_id IS NULL)",
            name="ck_equipment_readiness_states_occupant_xor",
        ),
        Index(
            "ux_equipment_readiness_states_tenant_asset", "tenant_id", "asset_id",
            unique=True, postgresql_where=text("asset_id IS NOT NULL"),
        ),
        Index(
            "ux_equipment_readiness_states_tenant_carrier", "tenant_id", "carrier_id",
            unique=True, postgresql_where=text("carrier_id IS NOT NULL"),
        ),
        Index(
            "ux_equipment_readiness_states_tenant_awaiting_cleaning_command", "tenant_id",
            "awaiting_cleaning_client_command_id", unique=True,
            postgresql_where=text("awaiting_cleaning_client_command_id IS NOT NULL"),
        ),
        Index(
            "ux_equipment_readiness_states_tenant_ready_command", "tenant_id", "ready_client_command_id",
            unique=True, postgresql_where=text("ready_client_command_id IS NOT NULL"),
        ),
        Index(
            "ux_equipment_readiness_states_tenant_damaged_command", "tenant_id", "damaged_client_command_id",
            unique=True, postgresql_where=text("damaged_client_command_id IS NOT NULL"),
        ),
        Index(
            "ux_equipment_readiness_states_tenant_maintenance_command", "tenant_id",
            "maintenance_client_command_id", unique=True,
            postgresql_where=text("maintenance_client_command_id IS NOT NULL"),
        ),
        Index(
            "ux_equipment_readiness_states_tenant_return_maint_command", "tenant_id",
            "return_from_maintenance_client_command_id", unique=True,
            postgresql_where=text("return_from_maintenance_client_command_id IS NOT NULL"),
        ),
        Index(
            "ux_equipment_readiness_states_tenant_retire_command", "tenant_id", "retire_client_command_id",
            unique=True, postgresql_where=text("retire_client_command_id IS NOT NULL"),
        ),
        Index("ix_equipment_readiness_states_farm_state", "tenant_id", "farm_id", "current_state"),
        UniqueConstraint("tenant_id", "farm_id", "id", name="uq_equipment_readiness_states_tenant_farm_id"),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id"], ["farms.tenant_id", "farms.id"],
            name="fk_equipment_readiness_states_tenant_farm",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "asset_id"],
            ["assets.tenant_id", "assets.farm_id", "assets.id"],
            name="fk_equipment_readiness_states_tenant_farm_asset",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "carrier_id"],
            ["carriers.tenant_id", "carriers.farm_id", "carriers.id"],
            name="fk_equipment_readiness_states_tenant_farm_carrier",
        ),
    )
