import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

INCIDENT_STATUSES = ("open", "acknowledged", "action_in_progress", "resolved", "closed")
INCIDENT_TERMINAL_STATUSES = ("closed",)
# PILOT-ASSET-001 PART 9: mirrors `InspectionFinding.FINDING_SEVERITIES`.
INCIDENT_SEVERITIES = ("low", "medium", "high", "critical")
# PILOT-ASSET-001 PART 9: drawn directly from the ticket's own worked
# examples (cooling pad, fan, pump, fertigation pump, dosing system, RO
# Plant, reservoir leak, germination chamber, seeding machine, scale,
# cold-store) -- never an invented exhaustive failure taxonomy.
INCIDENT_CATEGORIES = (
    "cooling", "ventilation", "irrigation_water", "fertigation_dosing", "ro_plant", "reservoir",
    "germination_chamber", "seeding_equipment", "scale", "cold_store", "other",
)


class EquipmentIncident(Base):
    """PILOT-ASSET-001 PART 9: a small, lightweight CURRENT-STATE row
    (ADR-005) -- never a full CMMS. Modeled directly on `CropIssue`'s
    shape. Identity/content fields are frozen for life by
    `enforce_equipment_incident_mutable_fields`; only the lifecycle fields
    below ever change, and only through `equipment_incident_service`'s
    owning commands. `potentially_impacted_location_id` is deliberately a
    second, independently-optional location -- never the same field as
    `location_id` -- see docs/domain/EQUIPMENT_READINESS_MODEL.md.
    Never creates, references, or infers a `CropIssue` (Incident != Crop
    Issue). Linked Work Items reference this row via `FarmWorkItem.
    equipment_incident_id`; completing one never resolves this Incident
    (Work Item Complete != Incident Resolved) -- only `resolve_incident`
    does, and only `close_incident` closes it."""

    __tablename__ = "equipment_incidents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    asset_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    location_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    potentially_impacted_location_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    severity: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    detected_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String, nullable=False, default="open")
    opened_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    assigned_owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    acknowledged_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    closed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    close_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    acknowledge_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    acknowledge_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)
    action_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    action_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)
    assign_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    assign_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)
    resolve_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    resolve_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)
    close_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    close_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint("status IN " + str(INCIDENT_STATUSES), name="ck_equipment_incidents_status"),
        CheckConstraint("severity IN " + str(INCIDENT_SEVERITIES), name="ck_equipment_incidents_severity"),
        CheckConstraint("category IN " + str(INCIDENT_CATEGORIES), name="ck_equipment_incidents_category"),
        CheckConstraint("length(btrim(description)) > 0", name="ck_equipment_incidents_description_not_blank"),
        CheckConstraint(
            "("
            "status = 'open' AND acknowledged_at IS NULL AND acknowledged_by_user_id IS NULL "
            "AND resolved_at IS NULL AND resolved_by_user_id IS NULL AND resolution_note IS NULL "
            "AND closed_at IS NULL AND closed_by_user_id IS NULL AND close_note IS NULL"
            ") OR ("
            "status = 'acknowledged' AND acknowledged_at IS NOT NULL AND acknowledged_by_user_id IS NOT NULL "
            "AND resolved_at IS NULL AND resolved_by_user_id IS NULL AND resolution_note IS NULL "
            "AND closed_at IS NULL AND closed_by_user_id IS NULL AND close_note IS NULL"
            ") OR ("
            "status = 'action_in_progress' AND acknowledged_at IS NOT NULL AND acknowledged_by_user_id IS NOT NULL "
            "AND resolved_at IS NULL AND resolved_by_user_id IS NULL AND resolution_note IS NULL "
            "AND closed_at IS NULL AND closed_by_user_id IS NULL AND close_note IS NULL"
            ") OR ("
            "status = 'resolved' AND resolved_at IS NOT NULL AND resolved_by_user_id IS NOT NULL "
            "AND closed_at IS NULL AND closed_by_user_id IS NULL AND close_note IS NULL"
            ") OR ("
            "status = 'closed' AND resolved_at IS NOT NULL AND resolved_by_user_id IS NOT NULL "
            "AND closed_at IS NOT NULL AND closed_by_user_id IS NOT NULL"
            ")",
            name="ck_equipment_incidents_status_shape",
        ),
        Index("ux_equipment_incidents_tenant_code_lower", "tenant_id", func.lower(code), unique=True),
        Index("ux_equipment_incidents_tenant_client_command_id", "tenant_id", "client_command_id", unique=True),
        Index(
            "ux_equipment_incidents_tenant_acknowledge_command", "tenant_id", "acknowledge_client_command_id",
            unique=True, postgresql_where=text("acknowledge_client_command_id IS NOT NULL"),
        ),
        Index(
            "ux_equipment_incidents_tenant_action_command", "tenant_id", "action_client_command_id",
            unique=True, postgresql_where=text("action_client_command_id IS NOT NULL"),
        ),
        Index(
            "ux_equipment_incidents_tenant_assign_command", "tenant_id", "assign_client_command_id",
            unique=True, postgresql_where=text("assign_client_command_id IS NOT NULL"),
        ),
        Index(
            "ux_equipment_incidents_tenant_resolve_command", "tenant_id", "resolve_client_command_id",
            unique=True, postgresql_where=text("resolve_client_command_id IS NOT NULL"),
        ),
        Index(
            "ux_equipment_incidents_tenant_close_command", "tenant_id", "close_client_command_id",
            unique=True, postgresql_where=text("close_client_command_id IS NOT NULL"),
        ),
        Index("ix_equipment_incidents_farm_status", "tenant_id", "farm_id", "status"),
        Index("ix_equipment_incidents_farm_asset", "tenant_id", "farm_id", "asset_id"),
        UniqueConstraint("tenant_id", "id", name="uq_equipment_incidents_tenant_id"),
        UniqueConstraint("tenant_id", "farm_id", "id", name="uq_equipment_incidents_tenant_farm_id"),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id"], ["farms.tenant_id", "farms.id"], name="fk_equipment_incidents_tenant_farm"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "asset_id"],
            ["assets.tenant_id", "assets.farm_id", "assets.id"],
            name="fk_equipment_incidents_tenant_farm_asset",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "location_id"],
            ["locations.tenant_id", "locations.farm_id", "locations.id"],
            name="fk_equipment_incidents_tenant_farm_location",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "potentially_impacted_location_id"],
            ["locations.tenant_id", "locations.farm_id", "locations.id"],
            name="fk_equipment_incidents_tenant_farm_impacted_location",
        ),
    )
