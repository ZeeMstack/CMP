import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

CALIBRATION_METRICS = ("PH", "EC", "SOLUTION_TEMPERATURE", "DISSOLVED_OXYGEN", "OTHER")
CALIBRATION_RESULTS = ("pass", "fail", "adjusted")


class InstrumentCalibrationEvent(Base):
    """PILOT-WATER-001A section 11: immutable, insert-only calibration
    history for a `WaterInstrument`, deliberately its own historical fact --
    never inferred from a `WaterMeasurement` merely existing (ticket rule
    7: "Do not silently consider an instrument calibrated merely because it
    produced a measurement"). No hard delete, no update: enforced by the
    generic `water_domain_reject_update`/`water_domain_reject_delete`
    triggers (see migration) shared by every insert-only table this ticket
    adds. Correction of a mis-recorded calibration is deferred -- see
    docs/domain/WATER_NUTRIENT_SYSTEM_MODEL.md's "Known gaps" section; a
    wrong entry is corrected by recording a new, later calibration event,
    never by editing this one."""

    __tablename__ = "instrument_calibration_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    water_instrument_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("water_instruments.id"), nullable=False)
    metric: Mapped[str] = mapped_column(String, nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    recorded_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    result: Mapped[str] = mapped_column(String, nullable=False)
    standard_reference: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        CheckConstraint("metric IN " + str(CALIBRATION_METRICS), name="ck_instrument_calibration_events_metric"),
        CheckConstraint("result IN " + str(CALIBRATION_RESULTS), name="ck_instrument_calibration_events_result"),
        Index(
            "ux_instrument_calibration_events_tenant_client_command_id", "tenant_id", "client_command_id",
            unique=True,
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "water_instrument_id"],
            ["water_instruments.tenant_id", "water_instruments.farm_id", "water_instruments.id"],
            name="fk_instrument_calibration_events_tenant_farm_instrument",
        ),
    )
