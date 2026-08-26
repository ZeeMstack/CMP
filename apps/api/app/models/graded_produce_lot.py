import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class GradedProduceLot(Base):
    """POSTHARVEST-OPS-001C: one immutable commercial grading output —
    the direct, sole child of one `GradingEvent` (never a
    `grading_output_lines` join table; a `GradedProduceLot` row IS the
    output). Lineage back to the source `HarvestedProduceLot` is exactly
    one join, through `grading_event_id` — this table deliberately does
    NOT also carry `source_harvested_produce_lot_id`, so there is only
    ever one source-of-truth path for lineage
    (`GradedProduceLot -> GradingEvent -> HarvestedProduceLot`), never
    two that could drift apart.

    `crop_id`/`variety_id` are copied verbatim from the source
    `HarvestedProduceLot` at grading time (never independently chosen —
    enforced by `enforce_graded_produce_lot_insert_integrity`), mirroring
    `HarvestedProduceLot`'s own crop/variety snapshot convention one level
    up. `grade_definition_version_id` pins the EXACT commercial grading
    standard used, never merely the `GradeDefinition` — `UNIQUE
    (grading_event_id, grade_definition_version_id)` is the frozen
    invariant preventing two outputs of one event from claiming the same
    exact grade version (one event creates at most one lot per exact
    grade version)."""

    __tablename__ = "graded_produce_lots"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    grading_event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("grading_events.id"), nullable=False)
    crop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crops.id"), nullable=False)
    variety_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("varieties.id"), nullable=True)
    grade_definition_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("grade_definition_versions.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String, nullable=False)
    original_received_weight_kg: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    original_received_whole_unit_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "original_received_weight_kg > 0 AND original_received_weight_kg = trunc(original_received_weight_kg, 3) "
            "AND original_received_weight_kg < 100000000000",
            name="ck_graded_produce_lots_weight_envelope",
        ),
        CheckConstraint(
            "original_received_whole_unit_count IS NULL OR original_received_whole_unit_count > 0",
            name="ck_graded_produce_lots_count_positive",
        ),
        Index("ux_graded_produce_lots_tenant_code_lower", "tenant_id", func.lower(code), unique=True),
        UniqueConstraint(
            "grading_event_id", "grade_definition_version_id",
            name="uq_graded_produce_lots_event_grade_version",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_graded_produce_lots_tenant_id"),
        UniqueConstraint("tenant_id", "farm_id", "id", name="uq_graded_produce_lots_tenant_farm_id"),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "grading_event_id"],
            ["grading_events.tenant_id", "grading_events.farm_id", "grading_events.id"],
            name="fk_graded_produce_lots_tenant_farm_event",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "crop_id"], ["crops.tenant_id", "crops.id"], name="fk_graded_produce_lots_tenant_crop"
        ),
        # MATCH SIMPLE (Postgres default): only evaluated when variety_id
        # IS NOT NULL.
        ForeignKeyConstraint(
            ["tenant_id", "crop_id", "variety_id"],
            ["varieties.tenant_id", "varieties.crop_id", "varieties.id"],
            name="fk_graded_produce_lots_tenant_crop_variety",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "grade_definition_version_id"],
            ["grade_definition_versions.tenant_id", "grade_definition_versions.id"],
            name="fk_graded_produce_lots_tenant_grade_version",
        ),
    )
