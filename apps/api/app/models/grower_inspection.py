import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

OVERALL_ASSESSMENTS = ("normal", "attention_needed", "critical")


class GrowerInspection(Base):
    """PILOT-AGRO-001 section 7: a structured, immutable-once-recorded
    grower floor check -- an ACTUAL FARM EVENT, never a protocol
    expectation (that remains `ProtocolObservationRequirement`, read
    separately as "due" context, never proved by this row's mere
    existence). `batch_carrier_assignment_id`/`location_id` are point-in-
    time SNAPSHOTS captured at record time (never re-derived later from
    current occupancy), so section 8/19's "Inspection preserves Batch +
    placement/location" holds even if the Carrier is later moved.
    `observation_event_id` is an optional link to the existing Observation
    architecture (CMP-010) -- values recorded during this Inspection are
    NEVER re-stored here; this row only points at the one `ObservationEvent`
    created in the same command (see `grower_inspection_service.
    record_inspection`). Fully insert-only (`reject_append_only_mutation`),
    like `ObservationEvent` itself."""

    __tablename__ = "grower_inspections"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crop_batches.id"), nullable=False)
    batch_carrier_assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("batch_carrier_assignments.id"), nullable=True
    )
    location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id"), nullable=True)
    growing_protocol_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("growing_protocol_versions.id"), nullable=True
    )
    inspected_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    inspected_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    overall_assessment: Mapped[str] = mapped_column(String, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    observation_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("observation_events.id"), nullable=True
    )

    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "overall_assessment IN ('" + "', '".join(OVERALL_ASSESSMENTS) + "')",
            name="ck_grower_inspections_overall_assessment",
        ),
        CheckConstraint("inspected_count IS NULL OR inspected_count >= 0", name="ck_grower_inspections_inspected_count_non_negative"),
        Index("ux_grower_inspections_tenant_client_command_id", "tenant_id", "client_command_id", unique=True),
        Index("ix_grower_inspections_farm_batch", "tenant_id", "farm_id", "batch_id"),
        UniqueConstraint("tenant_id", "id", name="uq_grower_inspections_tenant_id"),
        UniqueConstraint("tenant_id", "farm_id", "id", name="uq_grower_inspections_tenant_farm_id"),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_grower_inspections_tenant_farm_batch",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_carrier_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id",
                "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_grower_inspections_tenant_farm_assignment",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "location_id"],
            ["locations.tenant_id", "locations.farm_id", "locations.id"],
            name="fk_grower_inspections_tenant_farm_location",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "growing_protocol_version_id"],
            ["growing_protocol_versions.tenant_id", "growing_protocol_versions.id"],
            name="fk_grower_inspections_tenant_protocol_version",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "observation_event_id"],
            ["observation_events.tenant_id", "observation_events.farm_id", "observation_events.id"],
            name="fk_grower_inspections_tenant_farm_observation_event",
        ),
    )
