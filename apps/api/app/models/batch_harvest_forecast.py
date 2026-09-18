import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

FORECAST_BASES = ("grower_estimate", "planning_assumption", "protocol_guidance")


class BatchHarvestForecast(Base):
    """PILOT-PLAN-001A: a grower-owned, revisable LOW/EXPECTED/HIGH harvest
    forecast for one Crop Batch -- planning intelligence, never biological
    truth, never inventory, never automatically adjusted by an actual
    Harvest or a Crop Issue (see `docs/domain/HARVEST_FORECAST_CAPACITY_
    MODEL.md`).

    Insert-only revision chain, not a mutable current-state row: recording
    a new forecast for a Batch that already has one never updates the
    prior row in place -- it inserts a new row and stamps the prior row's
    `superseded_at`/`superseded_by_forecast_id`, mirroring `batch_stage_
    runs`'/`batch_protocol_assignments`' own "current = no successor yet"
    shape. `ux_batch_harvest_forecasts_current_batch` (below) guarantees
    exactly one CURRENT (`superseded_at IS NULL`) row per Batch at a time.
    Every prior revision remains permanently inspectable -- never
    hard-deleted or rewritten (CLAUDE.md rule 7)."""

    __tablename__ = "batch_harvest_forecasts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crop_batches.id"), nullable=False)

    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_by_forecast_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("batch_harvest_forecasts.id"), nullable=True
    )

    window_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    window_end_date: Mapped[date] = mapped_column(Date, nullable=False)

    low_quantity: Mapped[Numeric] = mapped_column(Numeric(18, 3), nullable=False)
    expected_quantity: Mapped[Numeric] = mapped_column(Numeric(18, 3), nullable=False)
    high_quantity: Mapped[Numeric] = mapped_column(Numeric(18, 3), nullable=False)
    quantity_uom_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("unit_of_measures.id"), nullable=False)

    basis: Mapped[str] = mapped_column(String, nullable=False)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    revision_reason: Mapped[str | None] = mapped_column(String, nullable=True)

    recorded_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "basis IN ('" + "', '".join(FORECAST_BASES) + "')", name="ck_batch_harvest_forecasts_basis"
        ),
        CheckConstraint(
            "low_quantity >= 0 AND low_quantity <= expected_quantity "
            "AND expected_quantity <= high_quantity AND expected_quantity > 0",
            name="ck_batch_harvest_forecasts_range_shape",
        ),
        CheckConstraint("window_end_date >= window_start_date", name="ck_batch_harvest_forecasts_window_shape"),
        CheckConstraint("revision_number >= 1", name="ck_batch_harvest_forecasts_revision_positive"),
        CheckConstraint(
            "(superseded_at IS NULL) = (superseded_by_forecast_id IS NULL)",
            name="ck_batch_harvest_forecasts_superseded_fields_together",
        ),
        Index(
            "ux_batch_harvest_forecasts_current_batch", "tenant_id", "farm_id", "batch_id",
            unique=True, postgresql_where=text("superseded_at IS NULL"),
        ),
        Index(
            "ux_batch_harvest_forecasts_tenant_client_command_id", "tenant_id", "client_command_id", unique=True
        ),
        UniqueConstraint("tenant_id", "batch_id", "revision_number", name="uq_batch_harvest_forecasts_batch_revision"),
        UniqueConstraint("tenant_id", "id", name="uq_batch_harvest_forecasts_tenant_id"),
        Index("ix_batch_harvest_forecasts_farm_window", "tenant_id", "farm_id", "window_start_date", "window_end_date"),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id"], ["farms.tenant_id", "farms.id"], name="fk_batch_harvest_forecasts_tenant_farm"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_batch_harvest_forecasts_tenant_farm_batch",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "superseded_by_forecast_id"],
            ["batch_harvest_forecasts.tenant_id", "batch_harvest_forecasts.id"],
            name="fk_batch_harvest_forecasts_tenant_superseded_by",
            # DEFERRABLE: the revision service closes the prior CURRENT row
            # (setting superseded_by_forecast_id) before the new row it
            # points at exists, in the same transaction -- see
            # harvest_forecast_service.record_batch_harvest_forecast.
            # Checked at COMMIT, by which point the new row exists.
            deferrable=True, initially="DEFERRED",
        ),
    )
