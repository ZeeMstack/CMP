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


class GerminationCheck(Base):
    """Immutable, insert-only germination inspection for one carrier
    assignment within one observation event. A narrow relational model
    (not generic observation values) because its integrity rules compare
    sibling counts within a single inspection — expressible as ordinary
    same-row CHECK constraints only if the counts live in one row
    (CMP-010)."""

    __tablename__ = "germination_checks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    observation_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("observation_events.id"), nullable=False
    )
    batch_carrier_assignment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batch_carrier_assignments.id"), nullable=False
    )
    inspected_site_count: Mapped[int] = mapped_column(Integer, nullable=False)
    normal_germinated_site_count: Mapped[int] = mapped_column(Integer, nullable=False)
    abnormal_germinated_site_count: Mapped[int] = mapped_column(Integer, nullable=False)
    failed_site_count: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("inspected_site_count > 0", name="ck_germination_checks_inspected_positive"),
        CheckConstraint(
            "normal_germinated_site_count >= 0", name="ck_germination_checks_normal_non_negative"
        ),
        CheckConstraint(
            "abnormal_germinated_site_count >= 0", name="ck_germination_checks_abnormal_non_negative"
        ),
        CheckConstraint("failed_site_count >= 0", name="ck_germination_checks_failed_non_negative"),
        CheckConstraint(
            "normal_germinated_site_count + abnormal_germinated_site_count + failed_site_count "
            "<= inspected_site_count",
            name="ck_germination_checks_categories_within_inspected",
        ),
        UniqueConstraint(
            "observation_event_id", "batch_carrier_assignment_id", name="ux_germination_checks_event_assignment"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "observation_event_id"],
            ["observation_events.tenant_id", "observation_events.farm_id", "observation_events.id"],
            name="fk_germination_checks_tenant_farm_event",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_carrier_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id",
                "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_germination_checks_tenant_farm_assignment",
        ),
    )
