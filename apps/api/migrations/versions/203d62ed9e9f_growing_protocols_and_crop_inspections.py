"""growing protocols and crop inspections

PILOT-AGRO-001: introduces the Growing Protocol / Grower Inspection / Crop
Issue domain -- "what SHOULD happen to this crop" (versioned, immutable-
once-ACTIVE `GrowingProtocol`/`GrowingProtocolVersion`/
`ProtocolObservationRequirement`/`ProtocolCareActivity`), "what protocol
version is a Batch actually following, with full history"
(`BatchProtocolAssignment`), "what did a grower actually observe"
(`GrowerInspection`/`InspectionFinding`, referencing -- never duplicating --
the existing `ObservationEvent`/`ObservationDefinition` architecture), and
"is there a persistent crop problem, who owns it, was it followed up, was
it deliberately resolved" (`CropIssue`/`CropIssueFollowUp`).

PILOT-AGRO-001A domain closure review: `protocol_observation_requirements`
and `protocol_care_activities` each additionally carry a nullable
`stage_sequence_index` (1-based) -- confirmed against the pilot's own
Iceberg Lettuce template (`config/pilot/iceberg-pilot.example.yaml`) that
more than one real `WorkflowStage` within one `WorkflowVersion` can share
the same `stage_category` (both the Seedling->InterSalads and the
InterSalads->Production moves are `stage_category = 'transplanting'`),
so `stage_category` alone is not always granular enough to target one of
them without also matching the other. `stage_sequence_index` optionally
narrows a requirement to the Nth occurrence of its `stage_category`
(ordered by `display_order`) within whichever `WorkflowVersion` a Batch
actually runs, computed at READ time -- never a `workflow_stage_id` FK,
which would still pin the requirement to one specific `WorkflowVersion`
(the exact problem `stage_category` was chosen to avoid). `NULL` (every
existing row, since this ticket had no prior release) preserves "applies
to every occurrence of the category."

Entirely additive: nine new tables, plus one new nullable
`farm_work_items.crop_issue_id` context column (mirrors that table's
existing `crop_batch_id`/`location_id`/`carrier_id`/`asset_id` context-
reference shape exactly) and a `CREATE OR REPLACE` of
`enforce_farm_work_item_mutable_fields` (defined by 3a278fa65f80) that
extends its identity/content freeze to cover the new column. No existing
table's data, other columns, or other constraints are touched.

Lifecycle/immutability triggers, all reusing pre-existing shared trigger
functions (`reject_hard_delete` from 5f3a9c2d1b44, `reject_append_only_
mutation` from c48f21a6b3d9) except one new one:
  - `grower_inspections`, `inspection_findings`, `crop_issue_follow_ups`:
    fully immutable, insert-only, like `ObservationEvent` itself.
  - `crop_issues`: a CURRENT-STATE row (ADR-005) -- a new
    `enforce_crop_issue_mutable_fields` (BEFORE UPDATE) freezes identity/
    content fields for life, mirroring `enforce_farm_work_item_mutable_
    fields` exactly; only lifecycle fields may change, and only through
    `crop_issue_service`'s owning commands.
  - `growing_protocol_versions`: no dedicated trigger -- mirrors
    `GradeDefinitionVersion`'s own precedent (e621...none) of relying on
    the DB-level state-shape CHECK plus service-level `state == 'draft'`
    gating (see `growing_protocol_service.add_observation_requirement`,
    mirroring `workflow_service.add_stage`'s `WorkflowVersionNotDraftError`
    precedent) rather than a second immutability trigger.
  - `growing_protocols`, `protocol_observation_requirements`,
    `protocol_care_activities`, `batch_protocol_assignments`: no trigger --
    master-data/current-state rows the owning service already gates.

Downgrade is destructive by nature (drops nine new tables and the new
`farm_work_items` column) and is guarded like every other domain-
introducing migration in this codebase: it raises and makes zero schema
change if any row already exists in any of the new tables.

Revision ID: 203d62ed9e9f
Revises: 29d6697de6d5
Create Date: 2026-09-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "203d62ed9e9f"
down_revision: Union[str, None] = "29d6697de6d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


STAGE_CATEGORIES = (
    "seeding", "germination", "nursery", "transplanting", "intermediate", "production",
    "harvest_ready", "harvesting", "completed", "rejected",
)
PROTOCOL_VERSION_STATES = ("draft", "active", "retired")
REQUIREMENT_LEVELS = ("required", "recommended")
CARE_ACTIVITY_TYPES = (
    "inspect_roots", "scout_pests", "pruning", "training", "spacing", "crop_hygiene",
    "transfer_readiness", "harvest_readiness", "other",
)
OVERALL_ASSESSMENTS = ("normal", "attention_needed", "critical")
FINDING_CATEGORIES = (
    "vigor", "uniformity", "roots", "leaf_condition", "pest_evidence", "disease_like_symptoms",
    "physical_damage", "deficiency_like_symptoms", "growth_deviation", "contamination_concern", "other",
)
FINDING_SEVERITIES = ("low", "medium", "high", "critical")
CROP_ISSUE_STATUSES = ("open", "resolved", "closed")
FOLLOW_UP_OUTCOMES = ("improved", "unchanged", "worsened", "resolved")


def upgrade() -> None:
    # --- growing_protocols ---------------------------------------------------
    op.create_table(
        "growing_protocols",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("crop_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("crops.id"), nullable=False),
        sa.Column("variety_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("varieties.id"), nullable=True),
        sa.Column(
            "production_system_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("production_systems.id"),
            nullable=True,
        ),
        sa.Column("season_context", sa.String(), nullable=True),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_growing_protocols_status"),
        sa.Index("ux_growing_protocols_tenant_code_lower", "tenant_id", sa.func.lower(sa.column("code")), unique=True),
        sa.UniqueConstraint("tenant_id", "id", name="uq_growing_protocols_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "crop_id"], ["crops.tenant_id", "crops.id"], name="fk_growing_protocols_tenant_crop"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "crop_id", "variety_id"],
            ["varieties.tenant_id", "varieties.crop_id", "varieties.id"],
            name="fk_growing_protocols_tenant_crop_variety",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "production_system_id"],
            ["production_systems.tenant_id", "production_systems.id"],
            name="fk_growing_protocols_tenant_production_system",
        ),
    )

    # --- growing_protocol_versions --------------------------------------------
    op.create_table(
        "growing_protocol_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "growing_protocol_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("growing_protocols.id"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(), nullable=False, server_default="draft"),
        sa.Column("author_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.Column("activation_client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("activation_request_fingerprint", sa.String(), nullable=True),
        sa.Column("retirement_client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("retirement_request_fingerprint", sa.String(), nullable=True),
        sa.CheckConstraint(
            "state IN " + str(PROTOCOL_VERSION_STATES), name="ck_growing_protocol_versions_state"
        ),
        sa.CheckConstraint("version_number > 0", name="ck_growing_protocol_versions_number_positive"),
        sa.CheckConstraint("length(btrim(reason)) > 0", name="ck_growing_protocol_versions_reason_not_blank"),
        sa.CheckConstraint(
            "(state = 'draft' AND activated_at IS NULL AND retired_at IS NULL "
            " AND activation_client_command_id IS NULL AND activation_request_fingerprint IS NULL "
            " AND retirement_client_command_id IS NULL AND retirement_request_fingerprint IS NULL) OR "
            "(state = 'active' AND activated_at IS NOT NULL AND retired_at IS NULL "
            " AND activation_client_command_id IS NOT NULL AND activation_request_fingerprint IS NOT NULL "
            " AND retirement_client_command_id IS NULL AND retirement_request_fingerprint IS NULL) OR "
            "(state = 'retired' AND activated_at IS NOT NULL AND retired_at IS NOT NULL "
            " AND activation_client_command_id IS NOT NULL AND activation_request_fingerprint IS NOT NULL)",
            name="ck_growing_protocol_versions_state_shape",
        ),
        sa.CheckConstraint(
            "retired_at IS NULL OR retired_at >= activated_at",
            name="ck_growing_protocol_versions_retired_after_activated",
        ),
        sa.UniqueConstraint(
            "growing_protocol_id", "version_number", name="uq_growing_protocol_versions_protocol_number"
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_growing_protocol_versions_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id", "growing_protocol_id", "id", name="uq_growing_protocol_versions_tenant_protocol_id"
        ),
        sa.Index(
            "ux_growing_protocol_versions_active_once", "growing_protocol_id", unique=True,
            postgresql_where=sa.text("state = 'active'"),
        ),
        sa.Index(
            "ux_growing_protocol_versions_tenant_client_command_id", "tenant_id", "client_command_id", unique=True
        ),
        sa.Index(
            "ux_growing_protocol_versions_tenant_activation_command", "tenant_id", "activation_client_command_id",
            unique=True, postgresql_where=sa.text("activation_client_command_id IS NOT NULL"),
        ),
        sa.Index(
            "ux_growing_protocol_versions_tenant_retirement_command", "tenant_id", "retirement_client_command_id",
            unique=True, postgresql_where=sa.text("retirement_client_command_id IS NOT NULL"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "growing_protocol_id"],
            ["growing_protocols.tenant_id", "growing_protocols.id"],
            name="fk_growing_protocol_versions_tenant_protocol",
        ),
    )

    # --- protocol_observation_requirements ------------------------------------
    op.create_table(
        "protocol_observation_requirements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "growing_protocol_version_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("growing_protocol_versions.id"), nullable=False,
        ),
        sa.Column("stage_category", sa.String(), nullable=False),
        sa.Column(
            "observation_definition_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("observation_definitions.id"),
            nullable=False,
        ),
        sa.Column("requirement_level", sa.String(), nullable=False),
        sa.Column("frequency_days", sa.Integer(), nullable=True),
        sa.Column("due_window_start_days", sa.Integer(), nullable=True),
        sa.Column("due_window_end_days", sa.Integer(), nullable=True),
        sa.Column("stage_sequence_index", sa.Integer(), nullable=True),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("escalation_guidance", sa.Text(), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint(
            "stage_category IN " + str(STAGE_CATEGORIES), name="ck_protocol_observation_requirements_stage_category"
        ),
        sa.CheckConstraint(
            "requirement_level IN " + str(REQUIREMENT_LEVELS), name="ck_protocol_observation_requirements_level"
        ),
        sa.CheckConstraint(
            "frequency_days IS NULL OR frequency_days > 0",
            name="ck_protocol_observation_requirements_frequency_positive",
        ),
        sa.CheckConstraint(
            "stage_sequence_index IS NULL OR stage_sequence_index > 0",
            name="ck_protocol_observation_requirements_stage_sequence_positive",
        ),
        sa.CheckConstraint(
            "(due_window_start_days IS NULL) = (due_window_end_days IS NULL)",
            name="ck_protocol_observation_requirements_due_window_together",
        ),
        sa.CheckConstraint(
            "due_window_start_days IS NULL OR "
            "(due_window_start_days >= 0 AND due_window_end_days >= due_window_start_days)",
            name="ck_protocol_observation_requirements_due_window_order",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_protocol_observation_requirements_tenant_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "growing_protocol_version_id"],
            ["growing_protocol_versions.tenant_id", "growing_protocol_versions.id"],
            name="fk_protocol_observation_requirements_tenant_version",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "observation_definition_id"],
            ["observation_definitions.tenant_id", "observation_definitions.id"],
            name="fk_protocol_observation_requirements_tenant_definition",
        ),
    )

    # --- protocol_care_activities ----------------------------------------------
    op.create_table(
        "protocol_care_activities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "growing_protocol_version_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("growing_protocol_versions.id"), nullable=False,
        ),
        sa.Column("stage_category", sa.String(), nullable=False),
        sa.Column("activity_type", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("frequency_days", sa.Integer(), nullable=True),
        sa.Column("stage_sequence_index", sa.Integer(), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint(
            "stage_category IN " + str(STAGE_CATEGORIES), name="ck_protocol_care_activities_stage_category"
        ),
        sa.CheckConstraint(
            "activity_type IN " + str(CARE_ACTIVITY_TYPES), name="ck_protocol_care_activities_activity_type"
        ),
        sa.CheckConstraint("length(btrim(title)) > 0", name="ck_protocol_care_activities_title_not_blank"),
        sa.CheckConstraint(
            "frequency_days IS NULL OR frequency_days > 0", name="ck_protocol_care_activities_frequency_positive"
        ),
        sa.CheckConstraint(
            "stage_sequence_index IS NULL OR stage_sequence_index > 0",
            name="ck_protocol_care_activities_stage_sequence_positive",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_protocol_care_activities_tenant_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "growing_protocol_version_id"],
            ["growing_protocol_versions.tenant_id", "growing_protocol_versions.id"],
            name="fk_protocol_care_activities_tenant_version",
        ),
    )

    # --- batch_protocol_assignments ---------------------------------------------
    op.create_table(
        "batch_protocol_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("crop_batches.id"), nullable=False),
        sa.Column(
            "growing_protocol_version_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("growing_protocol_versions.id"), nullable=False,
        ),
        sa.Column("assigned_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_batch_protocol_assignments_effective_order",
        ),
        sa.Index(
            "ux_batch_protocol_assignments_active_batch", "batch_id", unique=True,
            postgresql_where=sa.text("effective_to IS NULL"),
        ),
        sa.Index(
            "ux_batch_protocol_assignments_tenant_client_command_id", "tenant_id", "client_command_id", unique=True
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_batch_protocol_assignments_tenant_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_batch_protocol_assignments_tenant_farm_batch",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "growing_protocol_version_id"],
            ["growing_protocol_versions.tenant_id", "growing_protocol_versions.id"],
            name="fk_batch_protocol_assignments_tenant_version",
        ),
    )

    # --- grower_inspections -------------------------------------------------------
    op.create_table(
        "grower_inspections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("crop_batches.id"), nullable=False),
        sa.Column(
            "batch_carrier_assignment_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("batch_carrier_assignments.id"), nullable=True,
        ),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("locations.id"), nullable=True),
        sa.Column(
            "growing_protocol_version_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("growing_protocol_versions.id"), nullable=True,
        ),
        sa.Column("inspected_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_time", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("inspected_count", sa.Integer(), nullable=True),
        sa.Column("overall_assessment", sa.String(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "observation_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("observation_events.id"),
            nullable=True,
        ),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.CheckConstraint(
            "overall_assessment IN " + str(OVERALL_ASSESSMENTS), name="ck_grower_inspections_overall_assessment"
        ),
        sa.CheckConstraint(
            "inspected_count IS NULL OR inspected_count >= 0",
            name="ck_grower_inspections_inspected_count_non_negative",
        ),
        sa.Index("ux_grower_inspections_tenant_client_command_id", "tenant_id", "client_command_id", unique=True),
        sa.Index("ix_grower_inspections_farm_batch", "tenant_id", "farm_id", "batch_id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_grower_inspections_tenant_id"),
        sa.UniqueConstraint("tenant_id", "farm_id", "id", name="uq_grower_inspections_tenant_farm_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_grower_inspections_tenant_farm_batch",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_carrier_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id",
                "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_grower_inspections_tenant_farm_assignment",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "location_id"],
            ["locations.tenant_id", "locations.farm_id", "locations.id"],
            name="fk_grower_inspections_tenant_farm_location",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "growing_protocol_version_id"],
            ["growing_protocol_versions.tenant_id", "growing_protocol_versions.id"],
            name="fk_grower_inspections_tenant_protocol_version",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "observation_event_id"],
            ["observation_events.tenant_id", "observation_events.farm_id", "observation_events.id"],
            name="fk_grower_inspections_tenant_farm_observation_event",
        ),
    )

    # --- inspection_findings -------------------------------------------------------
    op.create_table(
        "inspection_findings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column(
            "grower_inspection_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("grower_inspections.id"),
            nullable=False,
        ),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("affected_count", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("suspected_cause", sa.Text(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("category IN " + str(FINDING_CATEGORIES), name="ck_inspection_findings_category"),
        sa.CheckConstraint("severity IN " + str(FINDING_SEVERITIES), name="ck_inspection_findings_severity"),
        sa.CheckConstraint(
            "affected_count IS NULL OR affected_count >= 0",
            name="ck_inspection_findings_affected_count_non_negative",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_inspection_findings_tenant_id"),
        sa.UniqueConstraint("tenant_id", "farm_id", "id", name="uq_inspection_findings_tenant_farm_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "grower_inspection_id"],
            ["grower_inspections.tenant_id", "grower_inspections.farm_id", "grower_inspections.id"],
            name="fk_inspection_findings_tenant_farm_inspection",
        ),
    )

    # --- crop_issues -----------------------------------------------------------
    op.create_table(
        "crop_issues",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("crop_batches.id"), nullable=False),
        sa.Column(
            "batch_carrier_assignment_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("batch_carrier_assignments.id"), nullable=True,
        ),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("locations.id"), nullable=True),
        sa.Column(
            "originating_grower_inspection_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("grower_inspections.id"), nullable=False,
        ),
        sa.Column(
            "originating_finding_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("inspection_findings.id"),
            nullable=True,
        ),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("suspected_cause", sa.Text(), nullable=True),
        sa.Column("confirmed_diagnosis", sa.Text(), nullable=True),
        sa.Column(
            "diagnosis_confirmed_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("diagnosis_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
        sa.Column("opened_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "assigned_owner_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column("follow_up_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("closed_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("close_note", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.Column("update_client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("update_request_fingerprint", sa.String(), nullable=True),
        sa.Column("diagnosis_client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("diagnosis_request_fingerprint", sa.String(), nullable=True),
        sa.Column("resolve_client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolve_request_fingerprint", sa.String(), nullable=True),
        sa.Column("close_client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("close_request_fingerprint", sa.String(), nullable=True),
        sa.CheckConstraint("status IN " + str(CROP_ISSUE_STATUSES), name="ck_crop_issues_status"),
        sa.CheckConstraint("category IN " + str(FINDING_CATEGORIES), name="ck_crop_issues_category"),
        sa.CheckConstraint("severity IN " + str(FINDING_SEVERITIES), name="ck_crop_issues_severity"),
        sa.CheckConstraint("length(btrim(description)) > 0", name="ck_crop_issues_description_not_blank"),
        sa.CheckConstraint(
            "(confirmed_diagnosis IS NULL) = (diagnosis_confirmed_by_user_id IS NULL) AND "
            "(confirmed_diagnosis IS NULL) = (diagnosis_confirmed_at IS NULL)",
            name="ck_crop_issues_diagnosis_fields_together",
        ),
        sa.CheckConstraint(
            "("
            "status = 'open' AND resolved_at IS NULL AND resolved_by_user_id IS NULL AND resolution_note IS NULL "
            "AND closed_at IS NULL AND closed_by_user_id IS NULL AND close_note IS NULL"
            ") OR ("
            "status = 'resolved' AND resolved_at IS NOT NULL AND resolved_by_user_id IS NOT NULL "
            "AND closed_at IS NULL AND closed_by_user_id IS NULL AND close_note IS NULL"
            ") OR ("
            "status = 'closed' AND resolved_at IS NOT NULL AND resolved_by_user_id IS NOT NULL "
            "AND closed_at IS NOT NULL AND closed_by_user_id IS NOT NULL"
            ")",
            name="ck_crop_issues_status_shape",
        ),
        sa.Index("ux_crop_issues_tenant_code_lower", "tenant_id", sa.func.lower(sa.column("code")), unique=True),
        sa.Index("ux_crop_issues_tenant_client_command_id", "tenant_id", "client_command_id", unique=True),
        sa.Index(
            "ux_crop_issues_tenant_update_command", "tenant_id", "update_client_command_id",
            unique=True, postgresql_where=sa.text("update_client_command_id IS NOT NULL"),
        ),
        sa.Index(
            "ux_crop_issues_tenant_diagnosis_command", "tenant_id", "diagnosis_client_command_id",
            unique=True, postgresql_where=sa.text("diagnosis_client_command_id IS NOT NULL"),
        ),
        sa.Index(
            "ux_crop_issues_tenant_resolve_command", "tenant_id", "resolve_client_command_id",
            unique=True, postgresql_where=sa.text("resolve_client_command_id IS NOT NULL"),
        ),
        sa.Index(
            "ux_crop_issues_tenant_close_command", "tenant_id", "close_client_command_id",
            unique=True, postgresql_where=sa.text("close_client_command_id IS NOT NULL"),
        ),
        sa.Index("ix_crop_issues_farm_status", "tenant_id", "farm_id", "status"),
        sa.Index("ix_crop_issues_farm_batch", "tenant_id", "farm_id", "batch_id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crop_issues_tenant_id"),
        sa.UniqueConstraint("tenant_id", "farm_id", "id", name="uq_crop_issues_tenant_farm_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id"], ["farms.tenant_id", "farms.id"], name="fk_crop_issues_tenant_farm"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_crop_issues_tenant_farm_batch",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_carrier_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id",
                "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_crop_issues_tenant_farm_assignment",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "location_id"],
            ["locations.tenant_id", "locations.farm_id", "locations.id"],
            name="fk_crop_issues_tenant_farm_location",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "originating_grower_inspection_id"],
            ["grower_inspections.tenant_id", "grower_inspections.farm_id", "grower_inspections.id"],
            name="fk_crop_issues_tenant_farm_originating_inspection",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "originating_finding_id"],
            ["inspection_findings.tenant_id", "inspection_findings.farm_id", "inspection_findings.id"],
            name="fk_crop_issues_tenant_farm_originating_finding",
        ),
    )

    # --- crop_issue_follow_ups --------------------------------------------------
    op.create_table(
        "crop_issue_follow_ups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("crop_issue_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("crop_issues.id"), nullable=False),
        sa.Column(
            "follow_up_grower_inspection_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("grower_inspections.id"), nullable=True,
        ),
        sa.Column("affected_count", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column(
            "recorded_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.CheckConstraint("outcome IN " + str(FOLLOW_UP_OUTCOMES), name="ck_crop_issue_follow_ups_outcome"),
        sa.CheckConstraint(
            "affected_count IS NULL OR affected_count >= 0",
            name="ck_crop_issue_follow_ups_affected_count_non_negative",
        ),
        sa.Index(
            "ux_crop_issue_follow_ups_tenant_client_command_id", "tenant_id", "client_command_id", unique=True
        ),
        sa.Index("ix_crop_issue_follow_ups_issue", "tenant_id", "farm_id", "crop_issue_id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crop_issue_follow_ups_tenant_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "crop_issue_id"],
            ["crop_issues.tenant_id", "crop_issues.farm_id", "crop_issues.id"],
            name="fk_crop_issue_follow_ups_tenant_farm_issue",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "follow_up_grower_inspection_id"],
            ["grower_inspections.tenant_id", "grower_inspections.farm_id", "grower_inspections.id"],
            name="fk_crop_issue_follow_ups_tenant_farm_inspection",
        ),
    )

    # --- farm_work_items: additive context column -------------------------------
    op.add_column("farm_work_items", sa.Column("crop_issue_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_farm_work_items_tenant_farm_crop_issue", "farm_work_items", "crop_issues",
        ["tenant_id", "farm_id", "crop_issue_id"], ["tenant_id", "farm_id", "id"],
    )
    op.create_index(
        "ix_farm_work_items_farm_crop_issue", "farm_work_items", ["tenant_id", "farm_id", "crop_issue_id"]
    )
    # Extend the existing identity/content freeze (3a278fa65f80) to cover the
    # new column -- CREATE OR REPLACE keeps the already-attached trigger,
    # only the function body changes.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_farm_work_item_mutable_fields() RETURNS trigger AS $$
        BEGIN
            IF NEW.tenant_id <> OLD.tenant_id OR NEW.farm_id <> OLD.farm_id OR NEW.code <> OLD.code
               OR NEW.work_type <> OLD.work_type OR NEW.category <> OLD.category OR NEW.title <> OLD.title
               OR NEW.instructions IS DISTINCT FROM OLD.instructions
               OR NEW.crop_batch_id IS DISTINCT FROM OLD.crop_batch_id
               OR NEW.location_id IS DISTINCT FROM OLD.location_id
               OR NEW.carrier_id IS DISTINCT FROM OLD.carrier_id
               OR NEW.asset_id IS DISTINCT FROM OLD.asset_id
               OR NEW.crop_issue_id IS DISTINCT FROM OLD.crop_issue_id
               OR NEW.quantity IS DISTINCT FROM OLD.quantity
               OR NEW.quantity_uom_id IS DISTINCT FROM OLD.quantity_uom_id
               OR NEW.completion_mode <> OLD.completion_mode
               OR NEW.created_by_user_id <> OLD.created_by_user_id OR NEW.created_at <> OLD.created_at
               OR NEW.client_command_id <> OLD.client_command_id
               OR NEW.request_fingerprint <> OLD.request_fingerprint
            THEN
                RAISE EXCEPTION 'farm_work_item identity/content fields are immutable; only lifecycle state may change';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # --- immutability / lifecycle triggers ---------------------------------------
    for table in ("grower_inspections", "inspection_findings", "crop_issue_follow_ups"):
        op.execute(
            f"""
            CREATE TRIGGER {table}_no_update
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER {table}_no_delete
            BEFORE DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
            """
        )

    op.execute(
        """
        CREATE FUNCTION enforce_crop_issue_mutable_fields() RETURNS trigger AS $$
        BEGIN
            IF NEW.tenant_id <> OLD.tenant_id OR NEW.farm_id <> OLD.farm_id OR NEW.code <> OLD.code
               OR NEW.batch_id <> OLD.batch_id
               OR NEW.batch_carrier_assignment_id IS DISTINCT FROM OLD.batch_carrier_assignment_id
               OR NEW.location_id IS DISTINCT FROM OLD.location_id
               OR NEW.originating_grower_inspection_id <> OLD.originating_grower_inspection_id
               OR NEW.originating_finding_id IS DISTINCT FROM OLD.originating_finding_id
               OR NEW.category <> OLD.category
               OR NEW.description <> OLD.description
               OR NEW.opened_by_user_id <> OLD.opened_by_user_id OR NEW.opened_at <> OLD.opened_at
               OR NEW.client_command_id <> OLD.client_command_id
               OR NEW.request_fingerprint <> OLD.request_fingerprint
            THEN
                RAISE EXCEPTION 'crop_issue identity/content fields are immutable; only lifecycle state may change';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER crop_issues_enforce_mutable_fields
        BEFORE UPDATE ON crop_issues
        FOR EACH ROW EXECUTE FUNCTION enforce_crop_issue_mutable_fields();
        """
    )
    op.execute(
        """
        CREATE TRIGGER crop_issues_no_delete
        BEFORE DELETE ON crop_issues
        FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();
        """
    )


def downgrade() -> None:
    bind = op.get_bind()

    counts = {
        table: bind.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one()
        for table in (
            "growing_protocols", "growing_protocol_versions", "protocol_observation_requirements",
            "protocol_care_activities", "batch_protocol_assignments", "grower_inspections",
            "inspection_findings", "crop_issues", "crop_issue_follow_ups",
        )
    }
    non_empty = {table: count for table, count in counts.items() if count > 0}
    if non_empty:
        raise RuntimeError(
            "Cannot downgrade past PILOT-AGRO-001's Growing Protocol / Grower Inspection / Crop Issue tables: "
            f"{non_empty} already contain data. Downgrading would destroy real agronomic history."
        )

    op.execute("DROP TRIGGER IF EXISTS crop_issues_no_delete ON crop_issues")
    op.execute("DROP TRIGGER IF EXISTS crop_issues_enforce_mutable_fields ON crop_issues")
    op.execute("DROP FUNCTION IF EXISTS enforce_crop_issue_mutable_fields()")
    for table in ("grower_inspections", "inspection_findings", "crop_issue_follow_ups"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_delete ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_update ON {table}")

    # Restore the pre-PILOT-AGRO-001 mutable-fields function (3a278fa65f80's
    # own body, verbatim) before dropping the column it referenced.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_farm_work_item_mutable_fields() RETURNS trigger AS $$
        BEGIN
            IF NEW.tenant_id <> OLD.tenant_id OR NEW.farm_id <> OLD.farm_id OR NEW.code <> OLD.code
               OR NEW.work_type <> OLD.work_type OR NEW.category <> OLD.category OR NEW.title <> OLD.title
               OR NEW.instructions IS DISTINCT FROM OLD.instructions
               OR NEW.crop_batch_id IS DISTINCT FROM OLD.crop_batch_id
               OR NEW.location_id IS DISTINCT FROM OLD.location_id
               OR NEW.carrier_id IS DISTINCT FROM OLD.carrier_id
               OR NEW.asset_id IS DISTINCT FROM OLD.asset_id
               OR NEW.quantity IS DISTINCT FROM OLD.quantity
               OR NEW.quantity_uom_id IS DISTINCT FROM OLD.quantity_uom_id
               OR NEW.completion_mode <> OLD.completion_mode
               OR NEW.created_by_user_id <> OLD.created_by_user_id OR NEW.created_at <> OLD.created_at
               OR NEW.client_command_id <> OLD.client_command_id
               OR NEW.request_fingerprint <> OLD.request_fingerprint
            THEN
                RAISE EXCEPTION 'farm_work_item identity/content fields are immutable; only lifecycle state may change';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.drop_index("ix_farm_work_items_farm_crop_issue", table_name="farm_work_items")
    op.drop_constraint("fk_farm_work_items_tenant_farm_crop_issue", "farm_work_items", type_="foreignkey")
    op.drop_column("farm_work_items", "crop_issue_id")

    op.drop_table("crop_issue_follow_ups")
    op.drop_table("crop_issues")
    op.drop_table("inspection_findings")
    op.drop_table("grower_inspections")
    op.drop_table("batch_protocol_assignments")
    op.drop_table("protocol_care_activities")
    op.drop_table("protocol_observation_requirements")
    op.drop_table("growing_protocol_versions")
    op.drop_table("growing_protocols")
