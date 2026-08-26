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


class GradingEvent(Base):
    """POSTHARVEST-OPS-001C: immutable, insert-only record of one
    Processing/Grading command against EXACTLY ONE `HarvestedProduceLot`
    (a direct FK, never a join/line table — different source lots are
    never combined at grading; combination of compatible material happens
    later, at Packing, through `GradedProduceLot`s). Mirrors CMP-013's own
    `HarvestEvent` shape (farm-scoped identity + command/idempotency
    fields), widened with the frozen 5-way pack-measure vocabulary
    (rejected/loss/sample/remainder) CMP-015's `PackingEvent` already
    established, plus a mandatory `processing_hall_location_id`.

    `processed_weight_kg`/`processed_whole_unit_count` are deliberately
    NEVER stored columns — always derived as `input_presented - remainder`
    at the point of use (service layer and DB triggers alike), exactly
    matching this codebase's "balance is always derived" convention
    everywhere else. Weight/count validation follows a single-row CHECK
    envelope for basic bounds; the full cross-table 5-way reconciliation
    against this event's own `GradedProduceLot` children is proven by a
    deferred constraint trigger (`enforce_grading_reconciliation`), since a
    same-row CHECK cannot see child rows."""

    __tablename__ = "grading_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    source_harvested_produce_lot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("harvested_produce_lots.id"), nullable=False
    )
    processing_hall_location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("locations.id"), nullable=False)
    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    note: Mapped[str | None] = mapped_column(String, nullable=True)

    input_presented_weight_kg: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    input_presented_whole_unit_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    rejected_weight_kg: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    rejected_whole_unit_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    loss_weight_kg: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    loss_whole_unit_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sample_weight_kg: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    sample_whole_unit_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    remainder_weight_kg: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    remainder_whole_unit_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "input_presented_weight_kg > 0 AND input_presented_weight_kg = trunc(input_presented_weight_kg, 3) "
            "AND input_presented_weight_kg < 100000000000",
            name="ck_grading_events_input_presented_envelope",
        ),
        CheckConstraint(
            "rejected_weight_kg >= 0 AND rejected_weight_kg = trunc(rejected_weight_kg, 3) "
            "AND rejected_weight_kg < 100000000000",
            name="ck_grading_events_rejected_envelope",
        ),
        CheckConstraint(
            "loss_weight_kg >= 0 AND loss_weight_kg = trunc(loss_weight_kg, 3) AND loss_weight_kg < 100000000000",
            name="ck_grading_events_loss_envelope",
        ),
        CheckConstraint(
            "sample_weight_kg >= 0 AND sample_weight_kg = trunc(sample_weight_kg, 3) "
            "AND sample_weight_kg < 100000000000",
            name="ck_grading_events_sample_envelope",
        ),
        CheckConstraint(
            "remainder_weight_kg >= 0 AND remainder_weight_kg = trunc(remainder_weight_kg, 3) "
            "AND remainder_weight_kg < 100000000000",
            name="ck_grading_events_remainder_envelope",
        ),
        # Frozen rule: a zero-processing event is invalid (input_presented
        # == remainder implies processed == 0). Strict inequality also
        # implies remainder can never exceed input_presented.
        CheckConstraint(
            "remainder_weight_kg < input_presented_weight_kg", name="ck_grading_events_remainder_less_than_presented"
        ),
        # Same-row, necessary-but-not-sufficient defense in depth; the full
        # equality including SUM(graded outputs) is proven by the deferred
        # cross-table trigger below (a same-row CHECK cannot see child rows).
        CheckConstraint(
            "rejected_weight_kg + loss_weight_kg + sample_weight_kg + remainder_weight_kg "
            "<= input_presented_weight_kg",
            name="ck_grading_events_weight_bounds",
        ),
        # Count-mode shape: either every count field is NULL (weight-only
        # source) or every one is populated and internally consistent —
        # never a partial mix, mirroring CMP-013's own "all-lines-counted
        # or zero-lines-counted, never partial" discipline one level up.
        CheckConstraint(
            "(input_presented_whole_unit_count IS NULL AND rejected_whole_unit_count IS NULL "
            " AND loss_whole_unit_count IS NULL AND sample_whole_unit_count IS NULL "
            " AND remainder_whole_unit_count IS NULL) "
            "OR (input_presented_whole_unit_count IS NOT NULL AND rejected_whole_unit_count IS NOT NULL "
            " AND loss_whole_unit_count IS NOT NULL AND sample_whole_unit_count IS NOT NULL "
            " AND remainder_whole_unit_count IS NOT NULL "
            " AND input_presented_whole_unit_count > 0 AND rejected_whole_unit_count >= 0 "
            " AND loss_whole_unit_count >= 0 AND sample_whole_unit_count >= 0 "
            " AND remainder_whole_unit_count >= 0 "
            " AND remainder_whole_unit_count < input_presented_whole_unit_count "
            " AND rejected_whole_unit_count + loss_whole_unit_count + sample_whole_unit_count "
            "     + remainder_whole_unit_count <= input_presented_whole_unit_count)",
            name="ck_grading_events_count_mode_shape",
        ),
        Index(
            "ux_grading_events_tenant_client_command_id", "tenant_id", "client_command_id", unique=True
        ),
        Index(
            "ix_grading_events_tenant_farm_source_lot", "tenant_id", "farm_id", "source_harvested_produce_lot_id"
        ),
        UniqueConstraint("tenant_id", "id", name="uq_grading_events_tenant_id"),
        UniqueConstraint("tenant_id", "farm_id", "id", name="uq_grading_events_tenant_farm_id"),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "source_harvested_produce_lot_id"],
            [
                "harvested_produce_lots.tenant_id", "harvested_produce_lots.farm_id",
                "harvested_produce_lots.id",
            ],
            name="fk_grading_events_tenant_farm_lot",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "processing_hall_location_id"],
            ["locations.tenant_id", "locations.farm_id", "locations.id"],
            name="fk_grading_events_tenant_farm_hall",
        ),
    )
