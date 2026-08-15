import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class SowingEvent(Base):
    """Immutable, insert-only record of one sowing command. Always tied to
    the batch's currently active (seeding-category) stage run at the moment
    it executes — enforced by a DB trigger, since a CHECK cannot join to
    other tables (CMP-009)."""

    __tablename__ = "sowing_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crop_batches.id"), nullable=False)
    active_batch_stage_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batch_stage_runs.id"), nullable=False
    )
    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    # NURSERY-OPS-001: provenance only -- NULL on every event predating this
    # ticket. seeding_station_id is composite tenant/farm-scoped (Location
    # already has that unique target); seeding_machine_id is a plain FK to
    # assets.id (Asset is farm-level equipment, referenced as provenance
    # only, never owned by a Location -- see FARM-SETUP-001.1).
    seeding_station_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id"), nullable=True)
    seeding_machine_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("assets.id"), nullable=True)
    # NURSERY-OPS-001.1: the canonical, single Seed Lot for this event --
    # CMP-009's original design put `seed_lot_id` only on each
    # `SowingEventLine`, with no DB-level guarantee that every line of one
    # event referenced the same lot. This column is now authoritative
    # (backfilled from existing lines on upgrade); the
    # `enforce_sowing_event_line_insert_integrity` trigger rejects any
    # line whose `seed_lot_id` disagrees with it (see SEED_SOWING_MODEL.md).
    seed_lot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("seed_lots.id"), nullable=False)

    __table_args__ = (
        Index(
            "ux_sowing_events_tenant_client_command_id", "tenant_id", "client_command_id", unique=True
        ),
        # NURSERY-OPS-001: at most one Sowing Event per Crop Batch, ever --
        # a deliberate system-wide restriction superseding CMP-009's
        # earlier "may be sown multiple times" design (see
        # SEED_SOWING_MODEL.md's NURSERY-OPS-001 addendum).
        UniqueConstraint("batch_id", name="ux_sowing_events_batch_id"),
        UniqueConstraint("tenant_id", "farm_id", "id", name="uq_sowing_events_tenant_farm_id"),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_sowing_events_tenant_farm_batch",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id", "active_batch_stage_run_id"],
            [
                "batch_stage_runs.tenant_id",
                "batch_stage_runs.farm_id",
                "batch_stage_runs.batch_id",
                "batch_stage_runs.id",
            ],
            name="fk_sowing_events_stage_run",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "seeding_station_id"],
            ["locations.tenant_id", "locations.farm_id", "locations.id"],
            name="fk_sowing_events_tenant_farm_seeding_station",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "seed_lot_id"],
            ["seed_lots.tenant_id", "seed_lots.farm_id", "seed_lots.id"],
            name="fk_sowing_events_tenant_farm_seed_lot",
        ),
    )
