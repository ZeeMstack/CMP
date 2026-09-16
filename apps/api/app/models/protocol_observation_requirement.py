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

REQUIREMENT_LEVELS = ("required", "recommended")


class ProtocolObservationRequirement(Base):
    """PILOT-AGRO-001: one protocol-driven expectation that a given
    `ObservationDefinition` be recorded during a given workflow
    `stage_category` -- REFERENCES the existing Observation architecture
    (CMP-010), never duplicates its value/unit/range storage. Deliberately
    keyed by `stage_category` (the existing crop-agnostic classification
    already carried by every `WorkflowStage`, e.g. 'nursery',
    'transplanting', 'harvest_ready') rather than a specific
    `workflow_stage_id` row: a `GrowingProtocolVersion` is scoped to a
    Crop/Variety/ProductionSystem, not pinned to one exact
    `WorkflowVersion`, so pinning a requirement to one WorkflowVersion's
    own stage row would silently orphan it the moment that workflow is
    republished (CMP-008's own version-immutability). `stage_category` is
    the one EXISTING stage concept stable across a crop's workflow
    versions -- see docs/domain/GROWING_PROTOCOL_INSPECTION_MODEL.md.
    Only mutable while the owning version is DRAFT (service-enforced,
    mirroring `workflow_service.add_stage`'s `WorkflowVersionNotDraftError`
    precedent -- no DB trigger duplicate of that check).

    PILOT-AGRO-001A domain closure review: a single `stage_category` can be
    shared by more than one real operational `WorkflowStage` within the
    SAME `WorkflowVersion` -- confirmed against the pilot's own Iceberg
    Lettuce template (`config/pilot/iceberg-pilot.example.yaml`), where
    both the Seedling->InterSalads move (`INTER_LEAFY_GREENS`) and the
    InterSalads->Production move (`PRODUCTION_TRANSFER`) are
    `stage_category = 'transplanting'`. `stage_sequence_index` (nullable,
    1-based) optionally narrows a requirement to the Nth occurrence of its
    `stage_category`, ordered by `display_order`, within whichever
    `WorkflowVersion` a Batch actually runs -- computed at READ time
    (`growing_protocol_service.get_batch_protocol_status`), never
    persisted against one specific `WorkflowVersion`, so the requirement
    stays crop-agnostic and portable exactly like `stage_category` itself.
    `NULL` (the default) preserves the original, pre-review behavior:
    applies to every occurrence of the category."""

    __tablename__ = "protocol_observation_requirements"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    growing_protocol_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("growing_protocol_versions.id"), nullable=False
    )
    stage_category: Mapped[str] = mapped_column(String, nullable=False)
    observation_definition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("observation_definitions.id"), nullable=False
    )
    requirement_level: Mapped[str] = mapped_column(String, nullable=False)
    frequency_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    due_window_start_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    due_window_end_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stage_sequence_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    escalation_guidance: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        CheckConstraint(
            "stage_category IN ('" + "', '".join(STAGE_CATEGORIES) + "')",
            name="ck_protocol_observation_requirements_stage_category",
        ),
        CheckConstraint(
            "requirement_level IN ('" + "', '".join(REQUIREMENT_LEVELS) + "')",
            name="ck_protocol_observation_requirements_level",
        ),
        CheckConstraint("frequency_days IS NULL OR frequency_days > 0", name="ck_protocol_observation_requirements_frequency_positive"),
        CheckConstraint(
            "stage_sequence_index IS NULL OR stage_sequence_index > 0",
            name="ck_protocol_observation_requirements_stage_sequence_positive",
        ),
        CheckConstraint(
            "(due_window_start_days IS NULL) = (due_window_end_days IS NULL)",
            name="ck_protocol_observation_requirements_due_window_together",
        ),
        CheckConstraint(
            "due_window_start_days IS NULL OR "
            "(due_window_start_days >= 0 AND due_window_end_days >= due_window_start_days)",
            name="ck_protocol_observation_requirements_due_window_order",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_protocol_observation_requirements_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "growing_protocol_version_id"],
            ["growing_protocol_versions.tenant_id", "growing_protocol_versions.id"],
            name="fk_protocol_observation_requirements_tenant_version",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "observation_definition_id"],
            ["observation_definitions.tenant_id", "observation_definitions.id"],
            name="fk_protocol_observation_requirements_tenant_definition",
        ),
    )
