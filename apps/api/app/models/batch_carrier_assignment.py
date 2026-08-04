import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class BatchCarrierAssignment(Base):
    """Immutable-history record of one carrier holding one crop batch —
    "what crop batch does this carrier contain", never "where is it"
    (occupancy, CMP-006, remains untouched). Opened by exactly one command
    (a CMP-009 sowing event or a CMP-011 transplant event) and, once
    released, permanently closed — never reopened. Only sowing-origin
    assignments may ever be released (CMP-011); transplant-created
    assignments cannot yet be released — that remains deferred."""

    __tablename__ = "batch_carrier_assignments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crop_batches.id"), nullable=False)
    carrier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("carriers.id"), nullable=False)
    batch_stage_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batch_stage_runs.id"), nullable=False
    )
    assigned_effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    released_effective_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    opening_sowing_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sowing_events.id"), nullable=True
    )
    opening_transplant_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transplant_events.id"), nullable=True
    )
    released_by_transplant_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transplant_events.id"), nullable=True
    )
    opening_batch_derivation_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("batch_derivation_events.id"), nullable=True
    )
    released_by_batch_derivation_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("batch_derivation_events.id"), nullable=True
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN opening_sowing_event_id IS NOT NULL THEN 1 ELSE 0 END "
            "+ CASE WHEN opening_transplant_event_id IS NOT NULL THEN 1 ELSE 0 END "
            "+ CASE WHEN opening_batch_derivation_event_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="ck_batch_carrier_assignments_exactly_one_opener",
        ),
        CheckConstraint(
            "(released_effective_time IS NULL) = "
            "(released_by_transplant_event_id IS NULL AND released_by_batch_derivation_event_id IS NULL)",
            name="ck_batch_carrier_assignments_release_fields_together",
        ),
        CheckConstraint(
            "NOT (released_by_transplant_event_id IS NOT NULL AND released_by_batch_derivation_event_id IS NOT NULL)",
            name="ck_batch_carrier_assignments_at_most_one_releaser",
        ),
        CheckConstraint(
            "released_by_transplant_event_id IS NULL OR opening_sowing_event_id IS NOT NULL",
            name="ck_batch_carrier_assignments_only_sowing_origin_releasable",
        ),
        Index(
            "ux_batch_carrier_assignments_active_carrier",
            "tenant_id",
            "carrier_id",
            unique=True,
            postgresql_where=text("released_effective_time IS NULL"),
        ),
        UniqueConstraint(
            "tenant_id", "farm_id", "id", name="uq_batch_carrier_assignments_tenant_farm_id"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_batch_carrier_assignments_tenant_farm_batch",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "carrier_id"],
            ["carriers.tenant_id", "carriers.farm_id", "carriers.id"],
            name="fk_batch_carrier_assignments_tenant_farm_carrier",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id", "batch_stage_run_id"],
            [
                "batch_stage_runs.tenant_id",
                "batch_stage_runs.farm_id",
                "batch_stage_runs.batch_id",
                "batch_stage_runs.id",
            ],
            name="fk_batch_carrier_assignments_stage_run",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "opening_sowing_event_id"],
            ["sowing_events.tenant_id", "sowing_events.farm_id", "sowing_events.id"],
            name="fk_batch_carrier_assignments_opening_event",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id", "opening_transplant_event_id"],
            [
                "transplant_events.tenant_id",
                "transplant_events.farm_id",
                "transplant_events.batch_id",
                "transplant_events.id",
            ],
            name="fk_batch_carrier_assignments_opening_transplant_event",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id", "released_by_transplant_event_id"],
            [
                "transplant_events.tenant_id",
                "transplant_events.farm_id",
                "transplant_events.batch_id",
                "transplant_events.id",
            ],
            name="fk_batch_carrier_assignments_released_by_transplant_event",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "opening_batch_derivation_event_id"],
            [
                "batch_derivation_events.tenant_id",
                "batch_derivation_events.farm_id",
                "batch_derivation_events.id",
            ],
            name="fk_batch_carrier_assignments_opening_derivation_event",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "released_by_batch_derivation_event_id"],
            [
                "batch_derivation_events.tenant_id",
                "batch_derivation_events.farm_id",
                "batch_derivation_events.id",
            ],
            name="fk_batch_carrier_assignments_released_by_derivation_event",
        ),
    )
