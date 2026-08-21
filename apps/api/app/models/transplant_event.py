import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

EVENT_KINDS = ("RECORD", "REVERSAL", "REPLACEMENT")


class TransplantEvent(Base):
    """Immutable, insert-only record of one transplantation command: source
    sowing-origin assignments released, destination assignments opened, for
    the same crop batch, in its current (unchanged) stage run (CMP-011).

    TRANSPLANT-CORRECTION-001: `event_kind` extends every RECORD (ordinary
    transplant, `event_kind='RECORD'`, the pre-existing shape) with two
    correction-only kinds mirroring the Seedling Disposition
    RECORD/REVERSAL/(replacement) precedent -- REVERSAL reverses exactly one
    directly-corrected target (`reverses_transplant_event_id`) and carries a
    required `correction_reason`; REPLACEMENT re-declares the correct
    biological facts for exactly one directly-corrected target
    (`corrects_transplant_event_id`). Both point at the SAME target event
    directly -- never at each other -- so a REPLACEMENT can itself later
    become the target of a further correction without any special-casing."""

    __tablename__ = "transplant_events"

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
    event_kind: Mapped[str] = mapped_column(String, nullable=False, default="RECORD", server_default="RECORD")
    reverses_transplant_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transplant_events.id"), nullable=True
    )
    corrects_transplant_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transplant_events.id"), nullable=True
    )
    correction_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    __table_args__ = (
        Index(
            "ux_transplant_events_tenant_client_command_id", "tenant_id", "client_command_id", unique=True
        ),
        UniqueConstraint("tenant_id", "farm_id", "id", name="uq_transplant_events_tenant_farm_id"),
        UniqueConstraint(
            "tenant_id", "farm_id", "batch_id", "id", name="uq_transplant_events_tenant_farm_batch_id"
        ),
        CheckConstraint(
            "event_kind IN ('RECORD', 'REVERSAL', 'REPLACEMENT')", name="ck_transplant_events_kind"
        ),
        # TRANSPLANT-CORRECTION-001 section 3: per-kind field shape, same-row
        # only -- cross-row proof (target-kind restriction, pair integrity)
        # lives in triggers, not here.
        CheckConstraint(
            "(event_kind = 'RECORD' AND reverses_transplant_event_id IS NULL "
            "  AND corrects_transplant_event_id IS NULL AND correction_reason IS NULL) "
            "OR (event_kind = 'REVERSAL' AND reverses_transplant_event_id IS NOT NULL "
            "  AND corrects_transplant_event_id IS NULL "
            "  AND correction_reason IS NOT NULL AND btrim(correction_reason) <> '') "
            "OR (event_kind = 'REPLACEMENT' AND reverses_transplant_event_id IS NULL "
            "  AND corrects_transplant_event_id IS NOT NULL AND correction_reason IS NULL)",
            name="ck_transplant_events_kind_field_shape",
        ),
        Index(
            "ux_transplant_events_reverses_once",
            "reverses_transplant_event_id",
            unique=True,
            postgresql_where=text("reverses_transplant_event_id IS NOT NULL"),
        ),
        Index(
            "ux_transplant_events_corrects_once",
            "corrects_transplant_event_id",
            unique=True,
            postgresql_where=text("corrects_transplant_event_id IS NOT NULL"),
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_transplant_events_tenant_farm_batch",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id", "active_batch_stage_run_id"],
            [
                "batch_stage_runs.tenant_id",
                "batch_stage_runs.farm_id",
                "batch_stage_runs.batch_id",
                "batch_stage_runs.id",
            ],
            name="fk_transplant_events_stage_run",
        ),
    )
