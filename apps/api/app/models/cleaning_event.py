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
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.equipment_readiness_state import READINESS_ENTITY_TYPES

CLEANING_RESULTS = ("completed", "needs_rework")


class CleaningEvent(Base):
    """PILOT-ASSET-001 PART 5: immutable, insert-only cleaning record for a
    readiness-tracked Asset/Carrier -- rejected by DB trigger on UPDATE/
    DELETE, exactly like `WaterMeasurement`/`ReservoirEvent`. Recording one
    does not by itself make the equipment READY (see
    docs/domain/EQUIPMENT_READINESS_MODEL.md, "Cleaning record" /
    "Ready validation") -- `equipment_readiness_service.record_cleaning_
    completed` advances the linked `EquipmentReadinessState` to
    CLEANING_COMPLETED only, in the same transaction."""

    __tablename__ = "cleaning_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    asset_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    carrier_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    performed_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    method: Mapped[str | None] = mapped_column(String, nullable=True)
    result: Mapped[str] = mapped_column(String, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        CheckConstraint("entity_type IN " + str(READINESS_ENTITY_TYPES), name="ck_cleaning_events_entity_type"),
        CheckConstraint(
            "(entity_type = 'asset' AND asset_id IS NOT NULL AND carrier_id IS NULL) OR "
            "(entity_type = 'carrier' AND carrier_id IS NOT NULL AND asset_id IS NULL)",
            name="ck_cleaning_events_occupant_xor",
        ),
        CheckConstraint("result IN " + str(CLEANING_RESULTS), name="ck_cleaning_events_result"),
        Index("ux_cleaning_events_tenant_client_command_id", "tenant_id", "client_command_id", unique=True),
        Index("ix_cleaning_events_farm_asset", "tenant_id", "farm_id", "asset_id"),
        Index("ix_cleaning_events_farm_carrier", "tenant_id", "farm_id", "carrier_id"),
        UniqueConstraint("tenant_id", "farm_id", "id", name="uq_cleaning_events_tenant_farm_id"),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id"], ["farms.tenant_id", "farms.id"], name="fk_cleaning_events_tenant_farm"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "asset_id"],
            ["assets.tenant_id", "assets.farm_id", "assets.id"],
            name="fk_cleaning_events_tenant_farm_asset",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "carrier_id"],
            ["carriers.tenant_id", "carriers.farm_id", "carriers.id"],
            name="fk_cleaning_events_tenant_farm_carrier",
        ),
    )
