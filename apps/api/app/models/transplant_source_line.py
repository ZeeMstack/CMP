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


class TransplantSourceLine(Base):
    """Immutable, insert-only record of one source carrier assignment
    consumed within one transplant event.

    NURSERY-OPS-004A: for a modern (SeedlingEntry-anchored) source, an
    assignment may appear as a source in MULTIPLE, sequential transplant
    events (partial transplant) — enforced by a per-event, not lifetime,
    unique constraint. `source_plant_count` is no longer a caller-supplied
    fact for a modern source: it is the server-derived authoritative
    `source_available_before` at this transplant's `effective_time` (see
    `seedling_disposition_service`'s checkpoint-anchor formula).
    `discarded_plant_count` is preserved as a read-compatible aggregate of
    the four new categorized loss counts (never independently
    disagreeing — same-row CHECK), rather than repurposed or dropped."""

    __tablename__ = "transplant_source_lines"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    transplant_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transplant_events.id"), nullable=False
    )
    source_batch_carrier_assignment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batch_carrier_assignments.id"), nullable=False
    )
    source_carrier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("carriers.id"), nullable=False)
    source_plant_count: Mapped[int] = mapped_column(Integer, nullable=False)
    discarded_plant_count: Mapped[int] = mapped_column(Integer, nullable=False)
    transplant_damage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    qc_rejection_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    other_loss_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    other_loss_note: Mapped[str | None] = mapped_column(String, nullable=True)
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("source_plant_count > 0", name="ck_transplant_source_lines_count_positive"),
        CheckConstraint(
            "discarded_plant_count >= 0", name="ck_transplant_source_lines_discarded_non_negative"
        ),
        CheckConstraint(
            "discarded_plant_count <= source_plant_count",
            name="ck_transplant_source_lines_discarded_within_count",
        ),
        CheckConstraint("transplant_damage_count >= 0", name="ck_transplant_source_lines_damage_non_negative"),
        CheckConstraint("qc_rejection_count >= 0", name="ck_transplant_source_lines_rejection_non_negative"),
        CheckConstraint("sample_count >= 0", name="ck_transplant_source_lines_sample_non_negative"),
        CheckConstraint("other_loss_count >= 0", name="ck_transplant_source_lines_other_loss_non_negative"),
        # NURSERY-OPS-004A section 14: discarded_plant_count is preserved as
        # the read-compatible aggregate of the four categorized counts --
        # DB-enforced so the two can never silently disagree.
        CheckConstraint(
            "discarded_plant_count = transplant_damage_count + qc_rejection_count "
            "+ sample_count + other_loss_count",
            name="ck_transplant_source_lines_discarded_matches_categories",
        ),
        CheckConstraint(
            "other_loss_count = 0 OR (other_loss_note IS NOT NULL AND btrim(other_loss_note) <> '')",
            name="ck_transplant_source_lines_other_loss_requires_note",
        ),
        # NURSERY-OPS-004A section 3/20: per-event, not lifetime, uniqueness
        # -- the same source assignment may appear across SEQUENTIAL
        # transplant events (partial transplant) but never twice within one.
        UniqueConstraint(
            "transplant_event_id", "source_batch_carrier_assignment_id",
            name="ux_transplant_source_lines_event_assignment",
        ),
        UniqueConstraint(
            "tenant_id", "farm_id", "transplant_event_id", "id",
            name="uq_transplant_source_lines_tenant_farm_event_id",
        ),
        # Needed as the FK target for seedling_source_checkpoints'
        # (tenant_id, farm_id, transplant_source_line_id) composite FK.
        UniqueConstraint(
            "tenant_id", "farm_id", "id", name="uq_transplant_source_lines_tenant_farm_id"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "transplant_event_id"],
            ["transplant_events.tenant_id", "transplant_events.farm_id", "transplant_events.id"],
            name="fk_transplant_source_lines_tenant_farm_event",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "source_batch_carrier_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id",
                "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_transplant_source_lines_tenant_farm_assignment",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "source_carrier_id"],
            ["carriers.tenant_id", "carriers.farm_id", "carriers.id"],
            name="fk_transplant_source_lines_tenant_farm_carrier",
        ),
    )
