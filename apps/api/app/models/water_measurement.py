import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

# PILOT-WATER-001A section 9: pilot metric set, plus room to extend
# (source-water EC/pH, ORP, alkalinity, flow, drainage EC/pH) without a
# schema change -- new metrics are new allowed CHECK values, never new
# columns or new code paths.
WATER_MEASUREMENT_METRICS = ("PH", "EC", "SOLUTION_TEMPERATURE", "DISSOLVED_OXYGEN")

# Canonical unit per metric. Deliberately NOT the shared `unit_of_measures`
# catalog: that table's `quantity_kind` CHECK is scoped to mass/volume/count
# for Store inventory convertibility (docs/domain/STORE_INVENTORY_MODEL.md
# §6) and has no concept of a dimensionless ratio (pH), a compound
# conductivity unit (mS/cm), or a temperature scale -- extending its global,
# immutable CHECK constraint to accommodate them would touch a shared
# invariant well outside this ticket's scope. This small, local, per-metric
# mapping is the documented alternative (see WATER_NUTRIENT_SYSTEM_MODEL.md).
CANONICAL_UNIT_BY_METRIC = {
    "PH": "pH",
    "EC": "mS/cm",
    "SOLUTION_TEMPERATURE": "°C",
    "DISSOLVED_OXYGEN": "mg/L",
}

_METRIC_UNIT_CASES = " AND ".join(
    f"(metric <> '{metric}' OR unit = '{unit}')" for metric, unit in CANONICAL_UNIT_BY_METRIC.items()
)


class WaterMeasurement(Base):
    """PILOT-WATER-001A section 9: immutable, insert-only pH/EC/temperature/
    DO reading. `sampling_point_id` is mandatory (section 6 of the ticket:
    "Do not allow a floating measurement with only Farm=X" -- a
    SamplingPoint is the one authoritative water-context anchor). Never
    rewrites a Recipe target (`NutrientRecipeVersion.target_ec`/
    `target_ph`) and is never rewritten by one -- TARGET and MEASUREMENT
    are always two distinct facts, enforced structurally by living in two
    separate, independently immutable tables. `instrument_id` is optional
    context only; recording a measurement with an instrument never implies
    that instrument is currently calibrated (see
    `InstrumentCalibrationEvent`). Immutable: no update, no delete
    (`water_domain_reject_update`/`water_domain_reject_delete` triggers,
    this ticket's migration)."""

    __tablename__ = "water_measurements"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    sampling_point_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sampling_points.id"), nullable=False)
    metric: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    unit: Mapped[str] = mapped_column(String, nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    recorded_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    water_instrument_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        CheckConstraint("metric IN " + str(WATER_MEASUREMENT_METRICS), name="ck_water_measurements_metric_allowed"),
        CheckConstraint(_METRIC_UNIT_CASES, name="ck_water_measurements_unit_matches_metric"),
        Index("ux_water_measurements_tenant_client_command_id", "tenant_id", "client_command_id", unique=True),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "sampling_point_id"],
            ["sampling_points.tenant_id", "sampling_points.farm_id", "sampling_points.id"],
            name="fk_water_measurements_tenant_farm_sampling_point",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "water_instrument_id"],
            ["water_instruments.tenant_id", "water_instruments.farm_id", "water_instruments.id"],
            name="fk_water_measurements_tenant_farm_instrument",
        ),
    )
