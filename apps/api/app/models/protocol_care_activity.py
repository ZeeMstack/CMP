import uuid

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.workflow_stage import STAGE_CATEGORIES

CARE_ACTIVITY_TYPES = (
    "inspect_roots", "scout_pests", "pruning", "training", "spacing", "crop_hygiene",
    "transfer_readiness", "harvest_readiness", "other",
)


class ProtocolCareActivity(Base):
    """PILOT-AGRO-001 section 5: a small, deliberately non-agronomic-dosing
    structured expectation ("inspect roots", "scout pests", "prune") a
    protocol stage carries -- NOT a nutrient recipe, dosing, or irrigation
    instruction (PILOT-WATER-001 territory, explicitly out of scope here).
    `stage_category` mirrors `ProtocolObservationRequirement`'s own
    deliberate choice of the existing crop-agnostic stage classification
    over a version-pinned `workflow_stage_id` -- see that model's
    docstring. `stage_sequence_index` mirrors that same model's own
    optional Nth-occurrence disambiguation field (added by the
    PILOT-AGRO-001A domain closure review) for the identical reason --
    stored here for parity/forward-compatibility even though no current
    read filters a Care Activity by it yet (only the Observation
    Requirement due-read does, as of this ticket)."""

    __tablename__ = "protocol_care_activities"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    growing_protocol_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("growing_protocol_versions.id"), nullable=False
    )
    stage_category: Mapped[str] = mapped_column(String, nullable=False)
    activity_type: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    frequency_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stage_sequence_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        CheckConstraint(
            "stage_category IN ('" + "', '".join(STAGE_CATEGORIES) + "')",
            name="ck_protocol_care_activities_stage_category",
        ),
        CheckConstraint(
            "activity_type IN ('" + "', '".join(CARE_ACTIVITY_TYPES) + "')",
            name="ck_protocol_care_activities_activity_type",
        ),
        CheckConstraint("length(btrim(title)) > 0", name="ck_protocol_care_activities_title_not_blank"),
        CheckConstraint("frequency_days IS NULL OR frequency_days > 0", name="ck_protocol_care_activities_frequency_positive"),
        CheckConstraint(
            "stage_sequence_index IS NULL OR stage_sequence_index > 0",
            name="ck_protocol_care_activities_stage_sequence_positive",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_protocol_care_activities_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "growing_protocol_version_id"],
            ["growing_protocol_versions.tenant_id", "growing_protocol_versions.id"],
            name="fk_protocol_care_activities_tenant_version",
        ),
    )
