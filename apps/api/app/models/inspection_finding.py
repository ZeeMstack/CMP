import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

FINDING_CATEGORIES = (
    "vigor", "uniformity", "roots", "leaf_condition", "pest_evidence", "disease_like_symptoms",
    "physical_damage", "deficiency_like_symptoms", "growth_deviation", "contamination_concern", "other",
)
FINDING_SEVERITIES = ("low", "medium", "high", "critical")


class InspectionFinding(Base):
    """PILOT-AGRO-001 section 9: one practical finding recorded within a
    `GrowerInspection`. `suspected_cause` is deliberately this row's own
    field, separate and forever distinct from `CropIssue.confirmed_
    diagnosis` (section 11) -- the system never promotes one into the
    other. `affected_count` never reduces `crop_batches` living inventory
    by itself (section 8/ISSUE != LOSS) -- it is descriptive only,
    validated against the parent Inspection's `inspected_count` in
    `grower_inspection_service` (affected_count <= inspected_count), not by
    a DB CHECK (no cross-table CHECK constraints), mirroring
    `observation_service`'s own established cross-row validation
    convention (e.g. germination site-count bounds). Fully insert-only."""

    __tablename__ = "inspection_findings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    grower_inspection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("grower_inspections.id"), nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    severity: Mapped[str] = mapped_column(String, nullable=False)
    affected_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    suspected_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "category IN ('" + "', '".join(FINDING_CATEGORIES) + "')", name="ck_inspection_findings_category"
        ),
        CheckConstraint(
            "severity IN ('" + "', '".join(FINDING_SEVERITIES) + "')", name="ck_inspection_findings_severity"
        ),
        CheckConstraint("affected_count IS NULL OR affected_count >= 0", name="ck_inspection_findings_affected_count_non_negative"),
        UniqueConstraint("tenant_id", "id", name="uq_inspection_findings_tenant_id"),
        UniqueConstraint("tenant_id", "farm_id", "id", name="uq_inspection_findings_tenant_farm_id"),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "grower_inspection_id"],
            ["grower_inspections.tenant_id", "grower_inspections.farm_id", "grower_inspections.id"],
            name="fk_inspection_findings_tenant_farm_inspection",
        ),
    )
