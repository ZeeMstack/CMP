"""water and nutrient domain foundation

PILOT-WATER-001A: introduces the hydroponic water/nutrient DOMAIN
FOUNDATION -- water TOPOLOGY (`water_sources`, `reservoirs`,
`irrigation_circuits`, `water_delivery_points`, `water_return_points`,
`sampling_points`), effective-dated topology CONNECTIONS
(`water_source_reservoir_links`, `reservoir_circuit_links`,
`circuit_delivery_point_links`, `return_point_reservoir_links`),
instrumentation (`water_instruments`, `instrument_calibration_events`,
`water_measurements`), and the nutrient program
(`nutrient_recipes`/`nutrient_recipe_versions`/`nutrient_recipe_components`,
`nutrient_mixes`/`nutrient_mix_inputs`, `reservoir_events`,
`water_delivery_events`). Twenty new tables, entirely additive -- no
existing table's data, columns, or constraints are touched.

Deliberately kept SEPARATE from the physical Location hierarchy (CLAUDE.md
/ ticket rule: "Water topology != physical location hierarchy"): only
`water_delivery_points.location_id` and the optional `reservoirs.
location_id`/`water_return_points.location_id` ever reference `locations`,
and always as a plain reference, never as a new level inserted into the
Location tree.

Approved Recipe / actual Mix / actual Delivery are three structurally
independent tables (never one inferring another): `nutrient_recipe_
versions` (target only), `nutrient_mixes`/`nutrient_mix_inputs` (actually
prepared), `water_delivery_events` (actually supplied). `nutrient_mix_
inputs` carries no Store-inventory-consumption column -- recording one
never touches `inventory_existence_ledger_entries` or any other Store
accounting table (ticket section 15); it optionally references an
existing `inventory_items` row purely as a catalog label, and that FK
alone.

Immutability, three tiers, each reusing this codebase's own pre-existing
convention rather than inventing new patterns (mirrors 203d62ed9e9f's own
documented split exactly):
  - `water_measurements`, `instrument_calibration_events`,
    `nutrient_mixes`, `nutrient_mix_inputs`, `reservoir_events`,
    `water_delivery_events`: fully immutable, insert-only -- BEFORE
    UPDATE/DELETE both reject via the pre-existing generic
    `reject_append_only_mutation()` (from c48f21a6b3d9), exactly like
    `grower_inspections`/`inspection_findings`/`crop_issue_follow_ups`
    (203d62ed9e9f). A wrong entry is corrected by recording a new, later
    event -- never by editing or deleting the old one (CLAUDE.md rule 7).
    Building a first-class correction/void command for these is out of
    scope for this foundation ticket; see
    docs/domain/WATER_NUTRIENT_SYSTEM_MODEL.md "Known gaps".
  - `water_source_reservoir_links`, `reservoir_circuit_links`,
    `circuit_delivery_point_links`, `return_point_reservoir_links`: a new,
    narrowly-scoped `enforce_water_topology_link_closure_only()` allows
    exactly one UPDATE per row -- setting `effective_to` from NULL to a
    timestamp, once, to close it -- and rejects every other column change
    or a second close; DELETE is rejected outright via
    `reject_append_only_mutation()`. Superseding a link means closing the
    old row and inserting a new one in the same transaction (the
    service-layer pattern), never rewriting the old row's endpoints --
    this is the mechanism that makes "what was connected to what on
    September 20" answerable from history that is never lost.
  - `water_sources`, `reservoirs`, `irrigation_circuits`, `water_delivery_
    points`, `water_return_points`, `sampling_points`, `water_instruments`,
    `nutrient_recipes`, `nutrient_recipe_versions`,
    `nutrient_recipe_components`: no DB trigger -- master-data/current-
    state rows the owning service already gates (no delete endpoint is
    ever exposed), mirroring `growing_protocols`/`growing_protocol_
    versions`'s own identical precedent (203d62ed9e9f) of relying on the
    DB-level state-shape CHECK plus service-level `state == 'draft'`
    gating for `nutrient_recipe_versions` rather than a second
    immutability trigger.

Downgrade is destructive by nature (drops twenty new tables) and is
guarded like every other domain-introducing migration in this codebase:
it raises and makes zero schema change if any row already exists in any
of the new tables.

Revision ID: 0d62f68527a2
Revises: 203d62ed9e9f
Create Date: 2026-09-17 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0d62f68527a2"
down_revision: Union[str, None] = "203d62ed9e9f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

WATER_SOURCE_TYPES = ("bore", "municipal", "ro_treated", "storage_tank_feed", "other")
RESERVOIR_TYPES = ("source_tank", "nutrient_reservoir", "return_reservoir", "mixing_reservoir", "other")
SAMPLING_POINT_TYPES = ("source", "reservoir", "circuit_supply", "delivery", "drain_return", "other")
WATER_MEASUREMENT_METRICS = ("PH", "EC", "SOLUTION_TEMPERATURE", "DISSOLVED_OXYGEN")
CANONICAL_UNIT_BY_METRIC = {
    "PH": "pH",
    "EC": "mS/cm",
    "SOLUTION_TEMPERATURE": "°C",
    "DISSOLVED_OXYGEN": "mg/L",
}
CALIBRATION_METRICS = ("PH", "EC", "SOLUTION_TEMPERATURE", "DISSOLVED_OXYGEN", "OTHER")
CALIBRATION_RESULTS = ("pass", "fail", "adjusted")
RECIPE_VERSION_STATES = ("draft", "active", "retired")
RESERVOIR_EVENT_TYPES = (
    "NUTRIENT_ADDITION", "WATER_TOP_UP", "PH_ADJUSTMENT", "SOLUTION_REPLACEMENT", "FLUSH", "DRAIN", "OTHER",
)

_NEW_TABLES = (
    "water_sources", "reservoirs", "irrigation_circuits", "water_delivery_points", "water_return_points",
    "water_source_reservoir_links", "reservoir_circuit_links", "circuit_delivery_point_links",
    "return_point_reservoir_links", "sampling_points", "water_instruments", "instrument_calibration_events",
    "water_measurements", "nutrient_recipes", "nutrient_recipe_versions", "nutrient_recipe_components",
    "nutrient_mixes", "nutrient_mix_inputs", "reservoir_events", "water_delivery_events",
)

_IMMUTABLE_TABLES = (
    "water_measurements", "instrument_calibration_events", "nutrient_mixes", "nutrient_mix_inputs",
    "reservoir_events", "water_delivery_events",
)

_TOPOLOGY_LINK_TABLES = (
    "water_source_reservoir_links", "reservoir_circuit_links", "circuit_delivery_point_links",
    "return_point_reservoir_links",
)


def upgrade() -> None:
    bind = op.get_bind()

    # PILOT-WATER-001A section 10: no existing seeded `asset_types` row
    # (germination_trolley/transfer_trolley/seeding_machine/weighing_scale/
    # label_printer, from 5f3a9c2d1b44) represents a water-quality
    # instrument -- adds exactly one new row to the existing global catalog
    # (CLAUDE.md: no second Asset catalog) rather than inventing a
    # parallel one. `water_instruments.asset_id` may reference an Asset of
    # this type, or any other Asset a farm already uses for this role.
    bind.execute(
        sa.text(
            "INSERT INTO asset_types (id, code, name, supports_positions) "
            "VALUES (gen_random_uuid(), 'water_quality_meter', 'Water Quality Meter', false)"
        )
    )

    # --- water_sources -------------------------------------------------------
    op.create_table(
        "water_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_water_sources_status"),
        sa.CheckConstraint("source_type IN " + str(WATER_SOURCE_TYPES), name="ck_water_sources_source_type_allowed"),
        sa.UniqueConstraint("tenant_id", "farm_id", "id", name="uq_water_sources_tenant_farm_id"),
    )
    op.create_index(
        "ux_water_sources_tenant_code_lower", "water_sources", ["tenant_id", sa.text("lower(code)")], unique=True
    )
    op.create_index("ix_water_sources_tenant_farm", "water_sources", ["tenant_id", "farm_id"])

    # --- reservoirs ------------------------------------------------------------
    op.create_table(
        "reservoirs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("reservoir_type", sa.String(), nullable=False),
        sa.Column("nominal_capacity", sa.Numeric(), nullable=True),
        sa.Column(
            "nominal_capacity_uom_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("unit_of_measures.id"),
            nullable=True,
        ),
        sa.Column("linked_asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_reservoirs_status"),
        sa.CheckConstraint("reservoir_type IN " + str(RESERVOIR_TYPES), name="ck_reservoirs_reservoir_type_allowed"),
        sa.CheckConstraint(
            "(nominal_capacity IS NULL) = (nominal_capacity_uom_id IS NULL)",
            name="ck_reservoirs_capacity_uom_pairing",
        ),
        sa.CheckConstraint("nominal_capacity IS NULL OR nominal_capacity > 0", name="ck_reservoirs_capacity_positive"),
        sa.UniqueConstraint("tenant_id", "farm_id", "id", name="uq_reservoirs_tenant_farm_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "linked_asset_id"], ["assets.tenant_id", "assets.farm_id", "assets.id"],
            name="fk_reservoirs_tenant_farm_linked_asset",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "location_id"], ["locations.tenant_id", "locations.farm_id", "locations.id"],
            name="fk_reservoirs_tenant_farm_location",
        ),
    )
    op.create_index(
        "ux_reservoirs_tenant_code_lower", "reservoirs", ["tenant_id", sa.text("lower(code)")], unique=True
    )
    op.create_index("ix_reservoirs_tenant_farm", "reservoirs", ["tenant_id", "farm_id"])

    # --- irrigation_circuits ----------------------------------------------------
    op.create_table(
        "irrigation_circuits",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("system_type", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_irrigation_circuits_status"),
        sa.UniqueConstraint("tenant_id", "farm_id", "id", name="uq_irrigation_circuits_tenant_farm_id"),
    )
    op.create_index(
        "ux_irrigation_circuits_tenant_code_lower", "irrigation_circuits", ["tenant_id", sa.text("lower(code)")],
        unique=True,
    )
    op.create_index("ix_irrigation_circuits_tenant_farm", "irrigation_circuits", ["tenant_id", "farm_id"])

    # --- water_delivery_points ----------------------------------------------------
    op.create_table(
        "water_delivery_points",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_water_delivery_points_status"),
        sa.UniqueConstraint("tenant_id", "farm_id", "id", name="uq_water_delivery_points_tenant_farm_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "location_id"], ["locations.tenant_id", "locations.farm_id", "locations.id"],
            name="fk_water_delivery_points_tenant_farm_location",
        ),
    )
    op.create_index(
        "ux_water_delivery_points_tenant_code_lower", "water_delivery_points", ["tenant_id", sa.text("lower(code)")],
        unique=True,
    )
    op.create_index("ix_water_delivery_points_location", "water_delivery_points", ["location_id"])

    # --- water_return_points ----------------------------------------------------
    op.create_table(
        "water_return_points",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_water_return_points_status"),
        sa.UniqueConstraint("tenant_id", "farm_id", "id", name="uq_water_return_points_tenant_farm_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "location_id"], ["locations.tenant_id", "locations.farm_id", "locations.id"],
            name="fk_water_return_points_tenant_farm_location",
        ),
    )
    op.create_index(
        "ux_water_return_points_tenant_code_lower", "water_return_points", ["tenant_id", sa.text("lower(code)")],
        unique=True,
    )

    # --- effective-dated topology links -----------------------------------------
    op.create_table(
        "water_source_reservoir_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("water_source_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("water_sources.id"), nullable=False),
        sa.Column("reservoir_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reservoirs.id"), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_water_source_reservoir_links_to_after_from",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "water_source_id"],
            ["water_sources.tenant_id", "water_sources.farm_id", "water_sources.id"],
            name="fk_water_source_reservoir_links_tenant_farm_source",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "reservoir_id"],
            ["reservoirs.tenant_id", "reservoirs.farm_id", "reservoirs.id"],
            name="fk_water_source_reservoir_links_tenant_farm_reservoir",
        ),
    )
    op.create_index(
        "ux_water_source_reservoir_links_active_reservoir", "water_source_reservoir_links", ["reservoir_id"],
        unique=True, postgresql_where=sa.text("effective_to IS NULL"),
    )
    op.create_index(
        "ix_water_source_reservoir_links_source_window", "water_source_reservoir_links",
        ["water_source_id", "effective_from", "effective_to"],
    )
    op.create_index(
        "ix_water_source_reservoir_links_reservoir_window", "water_source_reservoir_links",
        ["reservoir_id", "effective_from", "effective_to"],
    )

    op.create_table(
        "reservoir_circuit_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("reservoir_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reservoirs.id"), nullable=False),
        sa.Column(
            "irrigation_circuit_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("irrigation_circuits.id"),
            nullable=False,
        ),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from", name="ck_reservoir_circuit_links_to_after_from"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "reservoir_id"],
            ["reservoirs.tenant_id", "reservoirs.farm_id", "reservoirs.id"],
            name="fk_reservoir_circuit_links_tenant_farm_reservoir",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "irrigation_circuit_id"],
            ["irrigation_circuits.tenant_id", "irrigation_circuits.farm_id", "irrigation_circuits.id"],
            name="fk_reservoir_circuit_links_tenant_farm_circuit",
        ),
    )
    op.create_index(
        "ux_reservoir_circuit_links_active_circuit", "reservoir_circuit_links", ["irrigation_circuit_id"],
        unique=True, postgresql_where=sa.text("effective_to IS NULL"),
    )
    op.create_index(
        "ix_reservoir_circuit_links_reservoir_window", "reservoir_circuit_links",
        ["reservoir_id", "effective_from", "effective_to"],
    )
    op.create_index(
        "ix_reservoir_circuit_links_circuit_window", "reservoir_circuit_links",
        ["irrigation_circuit_id", "effective_from", "effective_to"],
    )

    op.create_table(
        "circuit_delivery_point_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column(
            "irrigation_circuit_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("irrigation_circuits.id"),
            nullable=False,
        ),
        sa.Column(
            "water_delivery_point_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("water_delivery_points.id"),
            nullable=False,
        ),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_circuit_delivery_point_links_to_after_from",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "irrigation_circuit_id"],
            ["irrigation_circuits.tenant_id", "irrigation_circuits.farm_id", "irrigation_circuits.id"],
            name="fk_circuit_delivery_point_links_tenant_farm_circuit",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "water_delivery_point_id"],
            ["water_delivery_points.tenant_id", "water_delivery_points.farm_id", "water_delivery_points.id"],
            name="fk_circuit_delivery_point_links_tenant_farm_delivery_point",
        ),
    )
    op.create_index(
        "ux_circuit_delivery_point_links_active_delivery_point", "circuit_delivery_point_links",
        ["water_delivery_point_id"], unique=True, postgresql_where=sa.text("effective_to IS NULL"),
    )
    op.create_index(
        "ix_circuit_delivery_point_links_circuit_window", "circuit_delivery_point_links",
        ["irrigation_circuit_id", "effective_from", "effective_to"],
    )
    op.create_index(
        "ix_circuit_delivery_point_links_point_window", "circuit_delivery_point_links",
        ["water_delivery_point_id", "effective_from", "effective_to"],
    )

    op.create_table(
        "return_point_reservoir_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column(
            "water_return_point_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("water_return_points.id"),
            nullable=False,
        ),
        sa.Column("return_reservoir_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reservoirs.id"), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_return_point_reservoir_links_to_after_from",
        ),
        sa.UniqueConstraint("tenant_id", "farm_id", "id", name="uq_return_point_reservoir_links_tenant_farm_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "water_return_point_id"],
            ["water_return_points.tenant_id", "water_return_points.farm_id", "water_return_points.id"],
            name="fk_return_point_reservoir_links_tenant_farm_return_point",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "return_reservoir_id"],
            ["reservoirs.tenant_id", "reservoirs.farm_id", "reservoirs.id"],
            name="fk_return_point_reservoir_links_tenant_farm_return_reservoir",
        ),
    )
    op.create_index(
        "ux_return_point_reservoir_links_active_return_point", "return_point_reservoir_links",
        ["water_return_point_id"], unique=True, postgresql_where=sa.text("effective_to IS NULL"),
    )
    op.create_index(
        "ix_return_point_reservoir_links_point_window", "return_point_reservoir_links",
        ["water_return_point_id", "effective_from", "effective_to"],
    )
    op.create_index(
        "ix_return_point_reservoir_links_reservoir_window", "return_point_reservoir_links",
        ["return_reservoir_id", "effective_from", "effective_to"],
    )

    # --- sampling_points ---------------------------------------------------------
    op.create_table(
        "sampling_points",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("point_type", sa.String(), nullable=False),
        sa.Column("water_source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reservoir_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("irrigation_circuit_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("water_delivery_point_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("water_return_point_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_sampling_points_status"),
        sa.CheckConstraint("point_type IN " + str(SAMPLING_POINT_TYPES), name="ck_sampling_points_point_type_allowed"),
        sa.CheckConstraint(
            "(CASE WHEN point_type = 'source' THEN water_source_id IS NOT NULL ELSE water_source_id IS NULL END) AND "
            "(CASE WHEN point_type = 'reservoir' THEN reservoir_id IS NOT NULL ELSE reservoir_id IS NULL END) AND "
            "(CASE WHEN point_type = 'circuit_supply' THEN irrigation_circuit_id IS NOT NULL "
            "ELSE irrigation_circuit_id IS NULL END) AND "
            "(CASE WHEN point_type = 'delivery' THEN water_delivery_point_id IS NOT NULL "
            "ELSE water_delivery_point_id IS NULL END) AND "
            "(CASE WHEN point_type = 'drain_return' THEN water_return_point_id IS NOT NULL "
            "ELSE water_return_point_id IS NULL END)",
            name="ck_sampling_points_anchor_matches_type",
        ),
        sa.UniqueConstraint("tenant_id", "farm_id", "id", name="uq_sampling_points_tenant_farm_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "water_source_id"],
            ["water_sources.tenant_id", "water_sources.farm_id", "water_sources.id"],
            name="fk_sampling_points_tenant_farm_source",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "reservoir_id"],
            ["reservoirs.tenant_id", "reservoirs.farm_id", "reservoirs.id"],
            name="fk_sampling_points_tenant_farm_reservoir",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "irrigation_circuit_id"],
            ["irrigation_circuits.tenant_id", "irrigation_circuits.farm_id", "irrigation_circuits.id"],
            name="fk_sampling_points_tenant_farm_circuit",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "water_delivery_point_id"],
            ["water_delivery_points.tenant_id", "water_delivery_points.farm_id", "water_delivery_points.id"],
            name="fk_sampling_points_tenant_farm_delivery_point",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "water_return_point_id"],
            ["water_return_points.tenant_id", "water_return_points.farm_id", "water_return_points.id"],
            name="fk_sampling_points_tenant_farm_return_point",
        ),
    )
    op.create_index(
        "ux_sampling_points_tenant_code_lower", "sampling_points", ["tenant_id", sa.text("lower(code)")],
        unique=True,
    )
    op.create_index("ix_sampling_points_reservoir", "sampling_points", ["reservoir_id"])
    op.create_index("ix_sampling_points_circuit", "sampling_points", ["irrigation_circuit_id"])

    # --- water_instruments ---------------------------------------------------------
    op.create_table(
        "water_instruments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("supports_ph", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("supports_ec", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("supports_solution_temperature", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("supports_dissolved_oxygen", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_water_instruments_status"),
        sa.CheckConstraint(
            "supports_ph OR supports_ec OR supports_solution_temperature OR supports_dissolved_oxygen",
            name="ck_water_instruments_at_least_one_capability",
        ),
        sa.UniqueConstraint("tenant_id", "asset_id", name="ux_water_instruments_tenant_asset"),
        sa.UniqueConstraint("tenant_id", "farm_id", "id", name="uq_water_instruments_tenant_farm_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "asset_id"], ["assets.tenant_id", "assets.farm_id", "assets.id"],
            name="fk_water_instruments_tenant_farm_asset",
        ),
    )

    # --- instrument_calibration_events ------------------------------------------
    op.create_table(
        "instrument_calibration_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column(
            "water_instrument_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("water_instruments.id"),
            nullable=False,
        ),
        sa.Column("metric", sa.String(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("recorded_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("result", sa.String(), nullable=False),
        sa.Column("standard_reference", sa.String(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.CheckConstraint("metric IN " + str(CALIBRATION_METRICS), name="ck_instrument_calibration_events_metric"),
        sa.CheckConstraint("result IN " + str(CALIBRATION_RESULTS), name="ck_instrument_calibration_events_result"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "water_instrument_id"],
            ["water_instruments.tenant_id", "water_instruments.farm_id", "water_instruments.id"],
            name="fk_instrument_calibration_events_tenant_farm_instrument",
        ),
    )
    op.create_index(
        "ix_instrument_calibration_events_instrument_effective", "instrument_calibration_events",
        ["water_instrument_id", "effective_at"],
    )
    op.create_index(
        "ux_instrument_calibration_events_tenant_client_command_id", "instrument_calibration_events",
        ["tenant_id", "client_command_id"], unique=True,
    )

    # --- water_measurements --------------------------------------------------------
    metric_unit_cases = " AND ".join(
        f"(metric <> '{metric}' OR unit = '{unit}')" for metric, unit in CANONICAL_UNIT_BY_METRIC.items()
    )
    op.create_table(
        "water_measurements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column(
            "sampling_point_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sampling_points.id"), nullable=False
        ),
        sa.Column("metric", sa.String(), nullable=False),
        sa.Column("value", sa.Numeric(), nullable=False),
        sa.Column("unit", sa.String(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("recorded_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("water_instrument_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.CheckConstraint(
            "metric IN " + str(WATER_MEASUREMENT_METRICS), name="ck_water_measurements_metric_allowed"
        ),
        sa.CheckConstraint(metric_unit_cases, name="ck_water_measurements_unit_matches_metric"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "sampling_point_id"],
            ["sampling_points.tenant_id", "sampling_points.farm_id", "sampling_points.id"],
            name="fk_water_measurements_tenant_farm_sampling_point",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "water_instrument_id"],
            ["water_instruments.tenant_id", "water_instruments.farm_id", "water_instruments.id"],
            name="fk_water_measurements_tenant_farm_instrument",
        ),
    )
    op.create_index(
        "ix_water_measurements_tenant_farm_effective", "water_measurements", ["tenant_id", "farm_id", "effective_at"]
    )
    op.create_index(
        "ix_water_measurements_sampling_point_effective", "water_measurements", ["sampling_point_id", "effective_at"]
    )
    op.create_index(
        "ux_water_measurements_tenant_client_command_id", "water_measurements", ["tenant_id", "client_command_id"],
        unique=True,
    )

    # --- nutrient_recipes -----------------------------------------------------------
    op.create_table(
        "nutrient_recipes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("crop_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("variety_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("production_system_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_nutrient_recipes_status"),
        sa.CheckConstraint(
            "crop_id IS NOT NULL OR variety_id IS NULL", name="ck_nutrient_recipes_variety_requires_crop"
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_nutrient_recipes_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "crop_id"], ["crops.tenant_id", "crops.id"], name="fk_nutrient_recipes_tenant_crop"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "crop_id", "variety_id"],
            ["varieties.tenant_id", "varieties.crop_id", "varieties.id"],
            name="fk_nutrient_recipes_tenant_crop_variety",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "production_system_id"],
            ["production_systems.tenant_id", "production_systems.id"],
            name="fk_nutrient_recipes_tenant_production_system",
        ),
    )
    op.create_index(
        "ux_nutrient_recipes_tenant_code_lower", "nutrient_recipes", ["tenant_id", sa.text("lower(code)")],
        unique=True,
    )

    # --- nutrient_recipe_versions -----------------------------------------------
    op.create_table(
        "nutrient_recipe_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "nutrient_recipe_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("nutrient_recipes.id"), nullable=False
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(), nullable=False, server_default="draft"),
        sa.Column("author_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("target_ec", sa.Numeric(), nullable=True),
        sa.Column("target_ph", sa.Numeric(), nullable=True),
        sa.Column("instructions", sa.Text(), nullable=True),
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
            "state IN " + str(RECIPE_VERSION_STATES), name="ck_nutrient_recipe_versions_state"
        ),
        sa.CheckConstraint("version_number > 0", name="ck_nutrient_recipe_versions_number_positive"),
        sa.CheckConstraint("length(btrim(reason)) > 0", name="ck_nutrient_recipe_versions_reason_not_blank"),
        sa.CheckConstraint("target_ec IS NULL OR target_ec > 0", name="ck_nutrient_recipe_versions_target_ec_positive"),
        sa.CheckConstraint(
            "target_ph IS NULL OR (target_ph >= 0 AND target_ph <= 14)",
            name="ck_nutrient_recipe_versions_target_ph_range",
        ),
        sa.CheckConstraint(
            "(state = 'draft' AND activated_at IS NULL AND retired_at IS NULL "
            " AND activation_client_command_id IS NULL AND activation_request_fingerprint IS NULL "
            " AND retirement_client_command_id IS NULL AND retirement_request_fingerprint IS NULL) OR "
            "(state = 'active' AND activated_at IS NOT NULL AND retired_at IS NULL "
            " AND activation_client_command_id IS NOT NULL AND activation_request_fingerprint IS NOT NULL "
            " AND retirement_client_command_id IS NULL AND retirement_request_fingerprint IS NULL) OR "
            "(state = 'retired' AND activated_at IS NOT NULL AND retired_at IS NOT NULL "
            " AND activation_client_command_id IS NOT NULL AND activation_request_fingerprint IS NOT NULL)",
            name="ck_nutrient_recipe_versions_state_shape",
        ),
        sa.CheckConstraint(
            "retired_at IS NULL OR retired_at >= activated_at",
            name="ck_nutrient_recipe_versions_retired_after_activated",
        ),
        sa.UniqueConstraint(
            "nutrient_recipe_id", "version_number", name="uq_nutrient_recipe_versions_recipe_number"
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_nutrient_recipe_versions_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id", "nutrient_recipe_id", "id", name="uq_nutrient_recipe_versions_tenant_recipe_id"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "nutrient_recipe_id"], ["nutrient_recipes.tenant_id", "nutrient_recipes.id"],
            name="fk_nutrient_recipe_versions_tenant_recipe",
        ),
    )
    op.create_index(
        "ux_nutrient_recipe_versions_active_once", "nutrient_recipe_versions", ["nutrient_recipe_id"], unique=True,
        postgresql_where=sa.text("state = 'active'"),
    )
    op.create_index(
        "ux_nutrient_recipe_versions_tenant_client_command_id", "nutrient_recipe_versions",
        ["tenant_id", "client_command_id"], unique=True,
    )
    op.create_index(
        "ux_nutrient_recipe_versions_tenant_activation_command", "nutrient_recipe_versions",
        ["tenant_id", "activation_client_command_id"], unique=True,
        postgresql_where=sa.text("activation_client_command_id IS NOT NULL"),
    )
    op.create_index(
        "ux_nutrient_recipe_versions_tenant_retirement_command", "nutrient_recipe_versions",
        ["tenant_id", "retirement_client_command_id"], unique=True,
        postgresql_where=sa.text("retirement_client_command_id IS NOT NULL"),
    )

    # --- nutrient_recipe_components -----------------------------------------------
    op.create_table(
        "nutrient_recipe_components",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "nutrient_recipe_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("nutrient_recipe_versions.id"),
            nullable=False,
        ),
        sa.Column("inventory_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("component_label", sa.String(), nullable=False),
        sa.Column("target_quantity", sa.Numeric(), nullable=False),
        sa.Column(
            "target_quantity_uom_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("unit_of_measures.id"),
            nullable=False,
        ),
        sa.Column("basis_volume", sa.Numeric(), nullable=True),
        sa.Column(
            "basis_volume_uom_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("unit_of_measures.id"), nullable=True
        ),
        sa.Column("sequence_number", sa.Integer(), nullable=True),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "length(btrim(component_label)) > 0", name="ck_nutrient_recipe_components_label_not_blank"
        ),
        sa.CheckConstraint("target_quantity > 0", name="ck_nutrient_recipe_components_quantity_positive"),
        sa.CheckConstraint(
            "(basis_volume IS NULL) = (basis_volume_uom_id IS NULL)",
            name="ck_nutrient_recipe_components_basis_pairing",
        ),
        sa.CheckConstraint(
            "basis_volume IS NULL OR basis_volume > 0", name="ck_nutrient_recipe_components_basis_positive"
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_nutrient_recipe_components_tenant_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "nutrient_recipe_version_id"],
            ["nutrient_recipe_versions.tenant_id", "nutrient_recipe_versions.id"],
            name="fk_nutrient_recipe_components_tenant_version",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "inventory_item_id"], ["inventory_items.tenant_id", "inventory_items.id"],
            name="fk_nutrient_recipe_components_tenant_inventory_item",
        ),
    )
    op.create_index(
        "ix_nutrient_recipe_components_version", "nutrient_recipe_components", ["nutrient_recipe_version_id"]
    )

    # --- nutrient_mixes -----------------------------------------------------------
    op.create_table(
        "nutrient_mixes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("reservoir_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reservoirs.id"), nullable=False),
        sa.Column(
            "nutrient_recipe_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("nutrient_recipe_versions.id"),
            nullable=True,
        ),
        sa.Column("prepared_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("target_volume", sa.Numeric(), nullable=True),
        sa.Column(
            "target_volume_uom_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("unit_of_measures.id"), nullable=True
        ),
        sa.Column("actual_volume", sa.Numeric(), nullable=True),
        sa.Column(
            "actual_volume_uom_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("unit_of_measures.id"), nullable=True
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.CheckConstraint(
            "(target_volume IS NULL) = (target_volume_uom_id IS NULL)",
            name="ck_nutrient_mixes_target_volume_uom_pairing",
        ),
        sa.CheckConstraint(
            "(actual_volume IS NULL) = (actual_volume_uom_id IS NULL)",
            name="ck_nutrient_mixes_actual_volume_uom_pairing",
        ),
        sa.CheckConstraint(
            "target_volume IS NULL OR target_volume > 0", name="ck_nutrient_mixes_target_volume_positive"
        ),
        sa.CheckConstraint(
            "actual_volume IS NULL OR actual_volume > 0", name="ck_nutrient_mixes_actual_volume_positive"
        ),
        sa.UniqueConstraint("tenant_id", "farm_id", "id", name="uq_nutrient_mixes_tenant_farm_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "reservoir_id"],
            ["reservoirs.tenant_id", "reservoirs.farm_id", "reservoirs.id"],
            name="fk_nutrient_mixes_tenant_farm_reservoir",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "nutrient_recipe_version_id"],
            ["nutrient_recipe_versions.tenant_id", "nutrient_recipe_versions.id"],
            name="fk_nutrient_mixes_tenant_recipe_version",
        ),
    )
    op.create_index(
        "ux_nutrient_mixes_tenant_client_command_id", "nutrient_mixes", ["tenant_id", "client_command_id"],
        unique=True,
    )
    op.create_index(
        "ix_nutrient_mixes_reservoir_effective", "nutrient_mixes", ["reservoir_id", "effective_at"]
    )
    op.create_index(
        "ix_nutrient_mixes_tenant_farm_effective", "nutrient_mixes", ["tenant_id", "farm_id", "effective_at"]
    )

    # --- nutrient_mix_inputs -----------------------------------------------------
    op.create_table(
        "nutrient_mix_inputs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("nutrient_mix_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("nutrient_mixes.id"), nullable=False),
        sa.Column("inventory_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("component_label", sa.String(), nullable=False),
        sa.Column("actual_quantity", sa.Numeric(), nullable=False),
        sa.Column(
            "actual_quantity_uom_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("unit_of_measures.id"),
            nullable=False,
        ),
        sa.Column("sequence_number", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("length(btrim(component_label)) > 0", name="ck_nutrient_mix_inputs_label_not_blank"),
        sa.CheckConstraint("actual_quantity > 0", name="ck_nutrient_mix_inputs_quantity_positive"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "nutrient_mix_id"],
            ["nutrient_mixes.tenant_id", "nutrient_mixes.farm_id", "nutrient_mixes.id"],
            name="fk_nutrient_mix_inputs_tenant_farm_mix",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "inventory_item_id"], ["inventory_items.tenant_id", "inventory_items.id"],
            name="fk_nutrient_mix_inputs_tenant_inventory_item",
        ),
    )
    op.create_index("ix_nutrient_mix_inputs_mix", "nutrient_mix_inputs", ["nutrient_mix_id"])

    # --- reservoir_events ----------------------------------------------------------
    op.create_table(
        "reservoir_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("reservoir_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reservoirs.id"), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("operator_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("quantity", sa.Numeric(), nullable=True),
        sa.Column(
            "quantity_uom_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("unit_of_measures.id"), nullable=True
        ),
        sa.Column("inventory_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.CheckConstraint(
            "event_type IN " + str(RESERVOIR_EVENT_TYPES), name="ck_reservoir_events_event_type_allowed"
        ),
        sa.CheckConstraint(
            "(quantity IS NULL) = (quantity_uom_id IS NULL)", name="ck_reservoir_events_quantity_uom_pairing"
        ),
        sa.CheckConstraint("quantity IS NULL OR quantity > 0", name="ck_reservoir_events_quantity_positive"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "reservoir_id"],
            ["reservoirs.tenant_id", "reservoirs.farm_id", "reservoirs.id"],
            name="fk_reservoir_events_tenant_farm_reservoir",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "inventory_item_id"], ["inventory_items.tenant_id", "inventory_items.id"],
            name="fk_reservoir_events_tenant_inventory_item",
        ),
    )
    op.create_index(
        "ix_reservoir_events_reservoir_effective", "reservoir_events", ["reservoir_id", "effective_at"]
    )
    op.create_index(
        "ix_reservoir_events_tenant_farm_effective", "reservoir_events", ["tenant_id", "farm_id", "effective_at"]
    )
    op.create_index(
        "ux_reservoir_events_tenant_client_command_id", "reservoir_events", ["tenant_id", "client_command_id"],
        unique=True,
    )

    # --- water_delivery_events --------------------------------------------------
    op.create_table(
        "water_delivery_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("reservoir_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reservoirs.id"), nullable=False),
        sa.Column(
            "irrigation_circuit_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("irrigation_circuits.id"),
            nullable=False,
        ),
        sa.Column("effective_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_volume", sa.Numeric(), nullable=True),
        sa.Column(
            "delivered_volume_uom_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("unit_of_measures.id"),
            nullable=True,
        ),
        sa.Column("recorded_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("nutrient_mix_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.CheckConstraint(
            "effective_end IS NULL OR effective_end >= effective_start",
            name="ck_water_delivery_events_end_after_start",
        ),
        sa.CheckConstraint(
            "(delivered_volume IS NULL) = (delivered_volume_uom_id IS NULL)",
            name="ck_water_delivery_events_volume_uom_pairing",
        ),
        sa.CheckConstraint(
            "delivered_volume IS NULL OR delivered_volume > 0", name="ck_water_delivery_events_volume_positive"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "reservoir_id"],
            ["reservoirs.tenant_id", "reservoirs.farm_id", "reservoirs.id"],
            name="fk_water_delivery_events_tenant_farm_reservoir",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "irrigation_circuit_id"],
            ["irrigation_circuits.tenant_id", "irrigation_circuits.farm_id", "irrigation_circuits.id"],
            name="fk_water_delivery_events_tenant_farm_circuit",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "nutrient_mix_id"],
            ["nutrient_mixes.tenant_id", "nutrient_mixes.farm_id", "nutrient_mixes.id"],
            name="fk_water_delivery_events_tenant_farm_mix",
        ),
    )
    op.create_index(
        "ix_water_delivery_events_circuit_window", "water_delivery_events",
        ["irrigation_circuit_id", "effective_start", "effective_end"],
    )
    op.create_index(
        "ix_water_delivery_events_tenant_farm_start", "water_delivery_events",
        ["tenant_id", "farm_id", "effective_start"],
    )
    op.create_index(
        "ux_water_delivery_events_tenant_client_command_id", "water_delivery_events",
        ["tenant_id", "client_command_id"], unique=True,
    )

    # --- triggers ------------------------------------------------------------------
    # Reuses the pre-existing, generic `reject_append_only_mutation()`
    # (c48f21a6b3d9) for every fully immutable insert-only table -- no new
    # trigger function needed.
    for table in _IMMUTABLE_TABLES:
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

    # Topology links: exactly one UPDATE is legal per row -- closing it by
    # setting effective_to from NULL to a timestamp, once. Every other
    # column change (including re-opening a closed link) is rejected. One
    # generic function serves all four link tables via to_jsonb() row
    # comparison, since they share this exact shape but not their column
    # names.
    op.execute(
        """
        CREATE FUNCTION enforce_water_topology_link_closure_only() RETURNS trigger AS $$
        BEGIN
            IF OLD.effective_to IS NOT NULL THEN
                RAISE EXCEPTION '% link % is already closed; effective_to cannot be edited again',
                    TG_TABLE_NAME, OLD.id;
            END IF;
            IF NEW.effective_to IS NULL THEN
                RAISE EXCEPTION '% link % update must close it (set effective_to), never re-open',
                    TG_TABLE_NAME, OLD.id;
            END IF;
            IF (to_jsonb(NEW) - 'effective_to') IS DISTINCT FROM (to_jsonb(OLD) - 'effective_to') THEN
                RAISE EXCEPTION '% link %: only effective_to may be updated to close a topology link',
                    TG_TABLE_NAME, OLD.id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table in _TOPOLOGY_LINK_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER {table}_enforce_closure_only
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION enforce_water_topology_link_closure_only();
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER {table}_no_delete
            BEFORE DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
            """
        )


def downgrade() -> None:
    bind = op.get_bind()

    counts = {
        table: bind.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one() for table in _NEW_TABLES
    }
    non_empty = {table: n for table, n in counts.items() if n > 0}
    if non_empty:
        raise RuntimeError(
            "Refusing to downgrade 0d62f68527a2: the following water/nutrient tables already have rows: "
            f"{non_empty}. This downgrade drops twenty tables outright -- it is only safe against an empty "
            "schema (e.g. immediately after a failed/aborted upgrade in a scratch environment)."
        )

    assets_using_water_quality_meter = bind.execute(
        sa.text(
            "SELECT count(*) FROM assets a JOIN asset_types t ON t.id = a.asset_type_id "
            "WHERE t.code = 'water_quality_meter'"
        )
    ).scalar_one()
    if assets_using_water_quality_meter > 0:
        raise RuntimeError(
            "Refusing to downgrade 0d62f68527a2: an Asset still references the 'water_quality_meter' asset type."
        )

    for table in _TOPOLOGY_LINK_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_delete ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_enforce_closure_only ON {table}")
    op.execute("DROP FUNCTION IF EXISTS enforce_water_topology_link_closure_only()")

    for table in _IMMUTABLE_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_delete ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_update ON {table}")

    op.drop_table("water_delivery_events")
    op.drop_table("reservoir_events")
    op.drop_table("nutrient_mix_inputs")
    op.drop_table("nutrient_mixes")
    op.drop_table("nutrient_recipe_components")
    op.drop_table("nutrient_recipe_versions")
    op.drop_table("nutrient_recipes")
    op.drop_table("water_measurements")
    op.drop_table("instrument_calibration_events")
    op.drop_table("water_instruments")
    op.drop_table("sampling_points")
    op.drop_table("return_point_reservoir_links")
    op.drop_table("circuit_delivery_point_links")
    op.drop_table("reservoir_circuit_links")
    op.drop_table("water_source_reservoir_links")
    op.drop_table("water_return_points")
    op.drop_table("water_delivery_points")
    op.drop_table("irrigation_circuits")
    op.drop_table("reservoirs")
    op.drop_table("water_sources")

    bind.execute(sa.text("DELETE FROM asset_types WHERE code = 'water_quality_meter'"))
