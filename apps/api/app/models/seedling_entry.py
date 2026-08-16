import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class SeedlingEntry(Base):
    """NURSERY-OPS-003A: immutable, insert-only biological handoff anchor --
    "this Seed Tray entered Seedling operations using this exact completed
    Germination outcome quantity." Distinct from `Movement` (which records
    only WHERE the Tray physically moved, and stays crop/biology-blind) and
    from `GerminationOutcomeSnapshot` (which this table references but never
    mutates or supersedes). `starting_living_seedling_count` is a deliberate
    freeze of `source_germination_outcome_snapshot_id`'s own
    `normal_seedling_count + abnormal_seedling_count` at the moment of entry --
    a later, even historically-valid, completed Germination correction never
    rewrites it (see `docs/domain/OBSERVATION_QUALITY_MODEL.md`'s NURSERY-
    OPS-003A addendum). At most one row per `batch_carrier_assignment_id`,
    ever (`ux_seedling_entries_assignment`) -- a later physical Movement
    (e.g. Table-to-Table) is not another biological entry."""

    __tablename__ = "seedling_entries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crop_batches.id"), nullable=False)
    batch_carrier_assignment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batch_carrier_assignments.id"), nullable=False
    )
    source_germination_outcome_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("germination_outcome_snapshots.id"), nullable=False
    )
    movement_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("movements.id"), nullable=False)
    starting_living_seedling_count: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "starting_living_seedling_count >= 0", name="ck_seedling_entries_starting_count_non_negative"
        ),
        UniqueConstraint("batch_carrier_assignment_id", name="ux_seedling_entries_assignment"),
        UniqueConstraint(
            "tenant_id", "client_command_id", name="ux_seedling_entries_tenant_client_command_id"
        ),
        # NURSERY-OPS-004A: needed as the FK target for
        # seedling_source_checkpoints' (tenant_id, farm_id, seedling_entry_id)
        # composite FK. Added via a new migration (ALTER TABLE) -- the
        # historical migration that created this table is untouched.
        UniqueConstraint(
            "tenant_id", "farm_id", "id", name="uq_seedling_entries_tenant_farm_id"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_seedling_entries_tenant_farm_batch",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_carrier_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id",
                "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_seedling_entries_tenant_farm_assignment",
        ),
    )
