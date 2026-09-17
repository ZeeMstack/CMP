"""equipment readiness and critical equipment incidents

PILOT-ASSET-001: introduces the Equipment Readiness lifecycle
(`EquipmentReadinessState`, `CleaningEvent`) and the Critical Equipment
Incident domain (`EquipmentIncident`), plus small additive metadata on the
existing Asset/Carrier registry. See docs/domain/EQUIPMENT_READINESS_MODEL.md
for the full frozen design; this docstring only summarizes the migration.

Entirely additive:
  - `carrier_types.readiness_tracked`/`requires_cleaning`,
    `asset_types.readiness_tracked`/`requires_cleaning` -- platform
    metadata flags, seeded for the current type catalog (never forcing
    readiness onto grow_cube/grow_bag, which remain untracked).
  - `assets.criticality` (`normal`/`important`/`critical`, default
    `normal`) -- an instance-level classification, never a scoring engine.
  - `farm_work_items.equipment_incident_id` -- mirrors the existing
    `crop_issue_id` context-reference column exactly (a `CREATE OR REPLACE`
    of `enforce_farm_work_item_mutable_fields` extends its freeze to cover
    it).
  - Three new tables: `cleaning_events` (immutable, insert-only),
    `equipment_readiness_states` (CURRENT-STATE row, one per
    readiness-tracked Asset/Carrier), `equipment_incidents` (CURRENT-STATE
    row, mirrors `crop_issues`' shape).
  - Backfill: one `EquipmentReadinessState(current_state='unknown')` row
    per pre-existing readiness-tracked Asset/Carrier -- never `ready`
    (would fabricate an assessment that never happened). No occupancy/
    movement table, trigger, or semantic is touched.

No existing table's data, other columns, or other constraints are
touched. Downgrade is destructive by nature (drops three new tables and
the four new columns) and is guarded like every other domain-introducing
migration in this codebase: it refuses if any of the new tables already
contain data.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b202c013643f"
down_revision: str | None = "0d62f68527a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

READINESS_STATES = (
    "unknown", "awaiting_cleaning", "cleaning_completed", "ready", "damaged", "maintenance", "retired",
)
CLEANING_RESULTS = ("completed", "needs_rework")
INCIDENT_STATUSES = ("open", "acknowledged", "action_in_progress", "resolved", "closed")
INCIDENT_SEVERITIES = ("low", "medium", "high", "critical")
INCIDENT_CATEGORIES = (
    "cooling", "ventilation", "irrigation_water", "fertigation_dosing", "ro_plant", "reservoir",
    "germination_chamber", "seeding_equipment", "scale", "cold_store", "other",
)

# PART 1 pilot scope -- see docs/domain/EQUIPMENT_READINESS_MODEL.md.
CARRIER_TYPE_READINESS = {
    "seed_tray": True, "cultivation_plate": True, "nursery_cultivation_plate": True,
    "production_cultivation_plate": True, "harvest_crate": True,
    "grow_cube": False, "grow_bag": False,
}
CARRIER_TYPE_REQUIRES_CLEANING = {
    "seed_tray": True, "cultivation_plate": True, "nursery_cultivation_plate": True,
    "production_cultivation_plate": True, "harvest_crate": True,
}
ASSET_TYPE_READINESS = {
    "germination_trolley": True, "transfer_trolley": True, "seeding_machine": True,
    "weighing_scale": True, "label_printer": True, "water_quality_meter": True,
}
ASSET_TYPE_REQUIRES_CLEANING = {
    "germination_trolley": True, "transfer_trolley": True, "seeding_machine": False,
    "weighing_scale": False, "label_printer": False, "water_quality_meter": False,
}


def upgrade() -> None:
    bind = op.get_bind()

    # --- carrier_types / asset_types: additive readiness metadata ---------------
    op.add_column(
        "carrier_types",
        sa.Column("readiness_tracked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "carrier_types",
        sa.Column("requires_cleaning", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("carrier_types", "readiness_tracked", server_default=None)
    op.alter_column("carrier_types", "requires_cleaning", server_default=None)
    op.add_column(
        "asset_types",
        sa.Column("readiness_tracked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "asset_types",
        sa.Column("requires_cleaning", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("asset_types", "readiness_tracked", server_default=None)
    op.alter_column("asset_types", "requires_cleaning", server_default=None)

    for code, tracked in CARRIER_TYPE_READINESS.items():
        bind.execute(
            sa.text("UPDATE carrier_types SET readiness_tracked = :tracked WHERE code = :code"),
            {"tracked": tracked, "code": code},
        )
    for code, requires in CARRIER_TYPE_REQUIRES_CLEANING.items():
        bind.execute(
            sa.text("UPDATE carrier_types SET requires_cleaning = :requires WHERE code = :code"),
            {"requires": requires, "code": code},
        )
    for code, tracked in ASSET_TYPE_READINESS.items():
        bind.execute(
            sa.text("UPDATE asset_types SET readiness_tracked = :tracked WHERE code = :code"),
            {"tracked": tracked, "code": code},
        )
    for code, requires in ASSET_TYPE_REQUIRES_CLEANING.items():
        bind.execute(
            sa.text("UPDATE asset_types SET requires_cleaning = :requires WHERE code = :code"),
            {"requires": requires, "code": code},
        )

    # --- assets: additive criticality --------------------------------------------
    op.add_column(
        "assets", sa.Column("criticality", sa.String(), nullable=False, server_default="normal")
    )
    op.alter_column("assets", "criticality", server_default=None)
    op.create_check_constraint(
        "ck_assets_criticality", "assets", "criticality IN ('normal', 'important', 'critical')"
    )

    # --- cleaning_events -----------------------------------------------------------
    op.create_table(
        "cleaning_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("carrier_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "performed_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("method", sa.String(), nullable=True),
        sa.Column("result", sa.String(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.CheckConstraint("entity_type IN ('asset', 'carrier')", name="ck_cleaning_events_entity_type"),
        sa.CheckConstraint(
            "(entity_type = 'asset' AND asset_id IS NOT NULL AND carrier_id IS NULL) OR "
            "(entity_type = 'carrier' AND carrier_id IS NOT NULL AND asset_id IS NULL)",
            name="ck_cleaning_events_occupant_xor",
        ),
        sa.CheckConstraint("result IN " + str(CLEANING_RESULTS), name="ck_cleaning_events_result"),
        sa.Index("ux_cleaning_events_tenant_client_command_id", "tenant_id", "client_command_id", unique=True),
        sa.Index("ix_cleaning_events_farm_asset", "tenant_id", "farm_id", "asset_id"),
        sa.Index("ix_cleaning_events_farm_carrier", "tenant_id", "farm_id", "carrier_id"),
        sa.UniqueConstraint("tenant_id", "farm_id", "id", name="uq_cleaning_events_tenant_farm_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id"], ["farms.tenant_id", "farms.id"], name="fk_cleaning_events_tenant_farm"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "asset_id"],
            ["assets.tenant_id", "assets.farm_id", "assets.id"],
            name="fk_cleaning_events_tenant_farm_asset",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "carrier_id"],
            ["carriers.tenant_id", "carriers.farm_id", "carriers.id"],
            name="fk_cleaning_events_tenant_farm_carrier",
        ),
    )
    op.execute(
        """
        CREATE TRIGGER cleaning_events_no_update
        BEFORE UPDATE ON cleaning_events
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER cleaning_events_no_delete
        BEFORE DELETE ON cleaning_events
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )

    # --- equipment_readiness_states -------------------------------------------------
    op.create_table(
        "equipment_readiness_states",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("carrier_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("current_state", sa.String(), nullable=False, server_default="unknown"),
        sa.Column("state_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "state_changed_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column("state_note", sa.Text(), nullable=True),
        sa.Column(
            "last_cleaning_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("cleaning_events.id"),
            nullable=True,
        ),
        sa.Column("awaiting_cleaning_client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("awaiting_cleaning_request_fingerprint", sa.String(), nullable=True),
        sa.Column("ready_client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ready_request_fingerprint", sa.String(), nullable=True),
        sa.Column("damaged_client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("damaged_request_fingerprint", sa.String(), nullable=True),
        sa.Column("maintenance_client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("maintenance_request_fingerprint", sa.String(), nullable=True),
        sa.Column("return_from_maintenance_client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("return_from_maintenance_request_fingerprint", sa.String(), nullable=True),
        sa.Column("retire_client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("retire_request_fingerprint", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            onupdate=sa.func.now(), nullable=False,
        ),
        sa.CheckConstraint(
            "entity_type IN ('asset', 'carrier')", name="ck_equipment_readiness_states_entity_type"
        ),
        sa.CheckConstraint(
            "current_state IN " + str(READINESS_STATES), name="ck_equipment_readiness_states_state"
        ),
        sa.CheckConstraint(
            "(entity_type = 'asset' AND asset_id IS NOT NULL AND carrier_id IS NULL) OR "
            "(entity_type = 'carrier' AND carrier_id IS NOT NULL AND asset_id IS NULL)",
            name="ck_equipment_readiness_states_occupant_xor",
        ),
        sa.Index(
            "ux_equipment_readiness_states_tenant_asset", "tenant_id", "asset_id",
            unique=True, postgresql_where=sa.text("asset_id IS NOT NULL"),
        ),
        sa.Index(
            "ux_equipment_readiness_states_tenant_carrier", "tenant_id", "carrier_id",
            unique=True, postgresql_where=sa.text("carrier_id IS NOT NULL"),
        ),
        sa.Index(
            "ux_equipment_readiness_states_tenant_awaiting_cleaning_command", "tenant_id",
            "awaiting_cleaning_client_command_id", unique=True,
            postgresql_where=sa.text("awaiting_cleaning_client_command_id IS NOT NULL"),
        ),
        sa.Index(
            "ux_equipment_readiness_states_tenant_ready_command", "tenant_id", "ready_client_command_id",
            unique=True, postgresql_where=sa.text("ready_client_command_id IS NOT NULL"),
        ),
        sa.Index(
            "ux_equipment_readiness_states_tenant_damaged_command", "tenant_id", "damaged_client_command_id",
            unique=True, postgresql_where=sa.text("damaged_client_command_id IS NOT NULL"),
        ),
        sa.Index(
            "ux_equipment_readiness_states_tenant_maintenance_command", "tenant_id",
            "maintenance_client_command_id", unique=True,
            postgresql_where=sa.text("maintenance_client_command_id IS NOT NULL"),
        ),
        sa.Index(
            "ux_equipment_readiness_states_tenant_return_maint_command", "tenant_id",
            "return_from_maintenance_client_command_id", unique=True,
            postgresql_where=sa.text("return_from_maintenance_client_command_id IS NOT NULL"),
        ),
        sa.Index(
            "ux_equipment_readiness_states_tenant_retire_command", "tenant_id", "retire_client_command_id",
            unique=True, postgresql_where=sa.text("retire_client_command_id IS NOT NULL"),
        ),
        sa.Index("ix_equipment_readiness_states_farm_state", "tenant_id", "farm_id", "current_state"),
        sa.UniqueConstraint("tenant_id", "farm_id", "id", name="uq_equipment_readiness_states_tenant_farm_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id"], ["farms.tenant_id", "farms.id"],
            name="fk_equipment_readiness_states_tenant_farm",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "asset_id"],
            ["assets.tenant_id", "assets.farm_id", "assets.id"],
            name="fk_equipment_readiness_states_tenant_farm_asset",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "carrier_id"],
            ["carriers.tenant_id", "carriers.farm_id", "carriers.id"],
            name="fk_equipment_readiness_states_tenant_farm_carrier",
        ),
    )
    op.execute(
        """
        CREATE FUNCTION enforce_equipment_readiness_state_mutable_fields() RETURNS trigger AS $$
        BEGIN
            IF NEW.tenant_id <> OLD.tenant_id OR NEW.farm_id <> OLD.farm_id
               OR NEW.entity_type <> OLD.entity_type
               OR NEW.asset_id IS DISTINCT FROM OLD.asset_id
               OR NEW.carrier_id IS DISTINCT FROM OLD.carrier_id
               OR NEW.created_at <> OLD.created_at
            THEN
                RAISE EXCEPTION
                    'equipment_readiness_state identity fields are immutable; only lifecycle state may change';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER equipment_readiness_states_enforce_mutable_fields
        BEFORE UPDATE ON equipment_readiness_states
        FOR EACH ROW EXECUTE FUNCTION enforce_equipment_readiness_state_mutable_fields();
        """
    )
    op.execute(
        """
        CREATE TRIGGER equipment_readiness_states_no_delete
        BEFORE DELETE ON equipment_readiness_states
        FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();
        """
    )

    # --- equipment_incidents ---------------------------------------------------------
    op.create_table(
        "equipment_incidents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("potentially_impacted_location_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "detected_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
        sa.Column(
            "opened_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("opened_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("assigned_owner_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "acknowledged_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("closed_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("close_note", sa.Text(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            onupdate=sa.func.now(), nullable=False,
        ),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.Column("acknowledge_client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("acknowledge_request_fingerprint", sa.String(), nullable=True),
        sa.Column("action_client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action_request_fingerprint", sa.String(), nullable=True),
        sa.Column("assign_client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assign_request_fingerprint", sa.String(), nullable=True),
        sa.Column("resolve_client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolve_request_fingerprint", sa.String(), nullable=True),
        sa.Column("close_client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("close_request_fingerprint", sa.String(), nullable=True),
        sa.CheckConstraint("status IN " + str(INCIDENT_STATUSES), name="ck_equipment_incidents_status"),
        sa.CheckConstraint("severity IN " + str(INCIDENT_SEVERITIES), name="ck_equipment_incidents_severity"),
        sa.CheckConstraint("category IN " + str(INCIDENT_CATEGORIES), name="ck_equipment_incidents_category"),
        sa.CheckConstraint(
            "length(btrim(description)) > 0", name="ck_equipment_incidents_description_not_blank"
        ),
        sa.CheckConstraint(
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
        sa.Index("ux_equipment_incidents_tenant_code_lower", "tenant_id", sa.func.lower(sa.column("code")), unique=True),
        sa.Index("ux_equipment_incidents_tenant_client_command_id", "tenant_id", "client_command_id", unique=True),
        sa.Index(
            "ux_equipment_incidents_tenant_acknowledge_command", "tenant_id", "acknowledge_client_command_id",
            unique=True, postgresql_where=sa.text("acknowledge_client_command_id IS NOT NULL"),
        ),
        sa.Index(
            "ux_equipment_incidents_tenant_action_command", "tenant_id", "action_client_command_id",
            unique=True, postgresql_where=sa.text("action_client_command_id IS NOT NULL"),
        ),
        sa.Index(
            "ux_equipment_incidents_tenant_assign_command", "tenant_id", "assign_client_command_id",
            unique=True, postgresql_where=sa.text("assign_client_command_id IS NOT NULL"),
        ),
        sa.Index(
            "ux_equipment_incidents_tenant_resolve_command", "tenant_id", "resolve_client_command_id",
            unique=True, postgresql_where=sa.text("resolve_client_command_id IS NOT NULL"),
        ),
        sa.Index(
            "ux_equipment_incidents_tenant_close_command", "tenant_id", "close_client_command_id",
            unique=True, postgresql_where=sa.text("close_client_command_id IS NOT NULL"),
        ),
        sa.Index("ix_equipment_incidents_farm_status", "tenant_id", "farm_id", "status"),
        sa.Index("ix_equipment_incidents_farm_asset", "tenant_id", "farm_id", "asset_id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_equipment_incidents_tenant_id"),
        sa.UniqueConstraint("tenant_id", "farm_id", "id", name="uq_equipment_incidents_tenant_farm_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id"], ["farms.tenant_id", "farms.id"], name="fk_equipment_incidents_tenant_farm"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "asset_id"],
            ["assets.tenant_id", "assets.farm_id", "assets.id"],
            name="fk_equipment_incidents_tenant_farm_asset",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "location_id"],
            ["locations.tenant_id", "locations.farm_id", "locations.id"],
            name="fk_equipment_incidents_tenant_farm_location",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "potentially_impacted_location_id"],
            ["locations.tenant_id", "locations.farm_id", "locations.id"],
            name="fk_equipment_incidents_tenant_farm_impacted_location",
        ),
    )
    op.execute(
        """
        CREATE FUNCTION enforce_equipment_incident_mutable_fields() RETURNS trigger AS $$
        BEGIN
            IF NEW.tenant_id <> OLD.tenant_id OR NEW.farm_id <> OLD.farm_id OR NEW.code <> OLD.code
               OR NEW.asset_id <> OLD.asset_id
               OR NEW.location_id IS DISTINCT FROM OLD.location_id
               OR NEW.potentially_impacted_location_id IS DISTINCT FROM OLD.potentially_impacted_location_id
               OR NEW.severity <> OLD.severity OR NEW.category <> OLD.category
               OR NEW.description <> OLD.description
               OR NEW.detected_by_user_id <> OLD.detected_by_user_id OR NEW.detected_at <> OLD.detected_at
               OR NEW.opened_by_user_id <> OLD.opened_by_user_id OR NEW.opened_at <> OLD.opened_at
               OR NEW.client_command_id <> OLD.client_command_id
               OR NEW.request_fingerprint <> OLD.request_fingerprint
            THEN
                RAISE EXCEPTION
                    'equipment_incident identity/content fields are immutable; only lifecycle state may change';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER equipment_incidents_enforce_mutable_fields
        BEFORE UPDATE ON equipment_incidents
        FOR EACH ROW EXECUTE FUNCTION enforce_equipment_incident_mutable_fields();
        """
    )
    op.execute(
        """
        CREATE TRIGGER equipment_incidents_no_delete
        BEFORE DELETE ON equipment_incidents
        FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();
        """
    )

    # --- farm_work_items: additive context column ---------------------------------
    op.add_column(
        "farm_work_items", sa.Column("equipment_incident_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key(
        "fk_farm_work_items_tenant_farm_equipment_incident", "farm_work_items", "equipment_incidents",
        ["tenant_id", "farm_id", "equipment_incident_id"], ["tenant_id", "farm_id", "id"],
    )
    op.create_index(
        "ix_farm_work_items_farm_equipment_incident", "farm_work_items",
        ["tenant_id", "farm_id", "equipment_incident_id"],
    )
    # Extend the existing identity/content freeze (3a278fa65f80, already
    # extended once by 203d62ed9e9f for crop_issue_id) to cover the new
    # column -- CREATE OR REPLACE keeps the already-attached trigger, only
    # the function body changes.
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
               OR NEW.equipment_incident_id IS DISTINCT FROM OLD.equipment_incident_id
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

    # --- backfill: UNKNOWN readiness for every pre-existing readiness-tracked row --
    # Never READY -- see docs/domain/EQUIPMENT_READINESS_MODEL.md, "Legacy
    # backfill: UNKNOWN, not READY". state_changed_by_user_id is left NULL
    # (no operator performed this backfill assessment).
    bind.execute(
        sa.text(
            """
            INSERT INTO equipment_readiness_states
                (id, tenant_id, farm_id, entity_type, asset_id, carrier_id, current_state, state_changed_at)
            SELECT gen_random_uuid(), a.tenant_id, a.farm_id, 'asset', a.id, NULL, 'unknown', now()
            FROM assets a
            JOIN asset_types at ON at.id = a.asset_type_id
            WHERE at.readiness_tracked = true
            """
        )
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO equipment_readiness_states
                (id, tenant_id, farm_id, entity_type, asset_id, carrier_id, current_state, state_changed_at)
            SELECT gen_random_uuid(), c.tenant_id, c.farm_id, 'carrier', NULL, c.id, 'unknown', now()
            FROM carriers c
            JOIN carrier_types ct ON ct.id = c.carrier_type_id
            WHERE ct.readiness_tracked = true
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()

    counts = {
        table: bind.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one()
        for table in ("cleaning_events", "equipment_incidents")
    }
    # equipment_readiness_states is expected to be non-empty after the
    # backfill above ran on upgrade -- a plain row count would always
    # block downgrade. Instead this checks for any row an operator has
    # actually touched (moved off the backfilled 'unknown' state, or
    # carries a state_changed_by_user_id) -- untouched backfill rows are
    # reproducible by re-running this same migration, never hand-entered,
    # so they alone never block a downgrade.
    counts["equipment_readiness_states"] = bind.execute(
        sa.text(
            "SELECT count(*) FROM equipment_readiness_states "
            "WHERE current_state <> 'unknown' OR state_changed_by_user_id IS NOT NULL"
        )
    ).scalar_one()
    non_empty = {table: count for table, count in counts.items() if count > 0}
    if non_empty:
        raise RuntimeError(
            "Cannot downgrade past PILOT-ASSET-001's Equipment Readiness / Incident tables: "
            f"{non_empty} already contain real operator-recorded data. Downgrading would destroy it."
        )

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
    op.drop_index("ix_farm_work_items_farm_equipment_incident", table_name="farm_work_items")
    op.drop_constraint("fk_farm_work_items_tenant_farm_equipment_incident", "farm_work_items", type_="foreignkey")
    op.drop_column("farm_work_items", "equipment_incident_id")

    op.execute("DROP TRIGGER IF EXISTS equipment_incidents_no_delete ON equipment_incidents")
    op.execute("DROP TRIGGER IF EXISTS equipment_incidents_enforce_mutable_fields ON equipment_incidents")
    op.execute("DROP FUNCTION IF EXISTS enforce_equipment_incident_mutable_fields()")
    op.drop_table("equipment_incidents")

    op.execute("DROP TRIGGER IF EXISTS equipment_readiness_states_no_delete ON equipment_readiness_states")
    op.execute(
        "DROP TRIGGER IF EXISTS equipment_readiness_states_enforce_mutable_fields ON equipment_readiness_states"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_equipment_readiness_state_mutable_fields()")
    op.drop_table("equipment_readiness_states")

    op.execute("DROP TRIGGER IF EXISTS cleaning_events_no_delete ON cleaning_events")
    op.execute("DROP TRIGGER IF EXISTS cleaning_events_no_update ON cleaning_events")
    op.drop_table("cleaning_events")

    op.drop_constraint("ck_assets_criticality", "assets", type_="check")
    op.drop_column("assets", "criticality")

    op.drop_column("asset_types", "requires_cleaning")
    op.drop_column("asset_types", "readiness_tracked")
    op.drop_column("carrier_types", "requires_cleaning")
    op.drop_column("carrier_types", "readiness_tracked")
