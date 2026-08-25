import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class BatchCarrierAssignment(Base):
    """Immutable-history record of one carrier holding one crop batch —
    "what crop batch does this carrier contain", never "where is it"
    (occupancy, CMP-006, remains untouched). Opened by exactly one command
    (a CMP-009 sowing event or a CMP-011 transplant event) and, once
    released, permanently closed — never reopened. Only sowing-origin
    assignments may ever be released (CMP-011); transplant-created
    assignments cannot yet be released — that remains deferred."""

    __tablename__ = "batch_carrier_assignments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crop_batches.id"), nullable=False)
    carrier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("carriers.id"), nullable=False)
    batch_stage_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batch_stage_runs.id"), nullable=False
    )
    assigned_effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    released_effective_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    opening_sowing_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sowing_events.id"), nullable=True
    )
    opening_transplant_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transplant_events.id"), nullable=True
    )
    released_by_transplant_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transplant_events.id"), nullable=True
    )
    opening_batch_derivation_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("batch_derivation_events.id"), nullable=True
    )
    released_by_batch_derivation_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("batch_derivation_events.id"), nullable=True
    )
    opening_transplant_reversal_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transplant_events.id"), nullable=True
    )
    restored_from_batch_carrier_assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("batch_carrier_assignments.id"), nullable=True
    )
    # SEEDLING-DISPOSITION-LIFECYCLE-001: a third typed releaser -- the exact
    # SeedlingDispositionEvent (REDUCTION) whose insert drove this
    # SeedlingEntry's authoritative source availability to exactly zero.
    # Never reuses released_by_transplant_event_id/released_by_batch_
    # derivation_event_id (a different biological lifecycle each).
    released_by_seedling_disposition_event_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    # A restoration's opener when correcting the exhausting Disposition
    # above restores positive biology -- the REVERSAL event that reopens the
    # source. Always co-present with restored_from_batch_carrier_assignment_
    # id, mirroring opening_transplant_reversal_event_id exactly.
    opening_seedling_disposition_reversal_event_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    # LEAFY-OPS-001: a fourth typed releaser -- the exact
    # ProductionDispositionEvent (REDUCTION) whose insert drove a Production
    # Cultivation Plate's authoritative living population to exactly zero.
    # Never reuses any other typed releaser (a different biological
    # lifecycle each).
    released_by_production_disposition_event_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    # A restoration's opener when correcting the exhausting Production
    # Disposition above restores positive population -- mirrors
    # opening_seedling_disposition_reversal_event_id exactly.
    opening_production_disposition_reversal_event_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    # LEAFY-OPS-001: stable population-lineage identity, immutable once set
    # (enforced by enforce_batch_carrier_assignment_closure_only_v2, which
    # already rejects any column change beyond release on UPDATE). Set once
    # at INSERT by the origin-integrity trigger: an ordinary Transplant-
    # created destination BCA (opening_transplant_event_id -- the row that
    # owns the one-and-only TransplantDestinationLine for this lineage, per
    # ux_transplant_destination_lines_assignment) self-references its own
    # id; a Production-Disposition-restored BCA
    # (opening_production_disposition_reversal_event_id) copies its
    # predecessor's own value forward unchanged. NULL for every other
    # origin (sowing, batch derivation, Transplant-reversal-restored,
    # Seedling-Disposition-reversal-restored) -- those are not
    # TransplantDestinationLine-anchored population lineages, and forcing a
    # root onto them would be a fabricated fact, not a derived one.
    population_root_batch_carrier_assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("batch_carrier_assignments.id"), nullable=True
    )
    # HARVEST-OPS-001: a fifth typed releaser -- the exact
    # HarvestPopulationEvent (CONSUMPTION) whose insert drove a Production
    # Cultivation Plate's authoritative living population to exactly zero.
    # Deliberately source-line-specific, not HarvestEvent-header-specific:
    # a multi-Plate HarvestEvent may zero-exhaust one Plate while leaving
    # another active, and this column names the exact biological fact for
    # THIS BCA's own lineage, never the shared event header. Never reuses
    # any other typed releaser (a different biological lifecycle each).
    released_by_harvest_population_event_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    # A restoration's opener when a Harvest correction restores positive
    # population after the exhausting Harvest above released this
    # lineage's active BCA -- mirrors opening_production_disposition_
    # reversal_event_id exactly.
    opening_harvest_population_reversal_event_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN opening_sowing_event_id IS NOT NULL THEN 1 ELSE 0 END "
            "+ CASE WHEN opening_transplant_event_id IS NOT NULL THEN 1 ELSE 0 END "
            "+ CASE WHEN opening_batch_derivation_event_id IS NOT NULL THEN 1 ELSE 0 END "
            "+ CASE WHEN opening_transplant_reversal_event_id IS NOT NULL THEN 1 ELSE 0 END "
            "+ CASE WHEN opening_seedling_disposition_reversal_event_id IS NOT NULL THEN 1 ELSE 0 END "
            "+ CASE WHEN opening_production_disposition_reversal_event_id IS NOT NULL THEN 1 ELSE 0 END "
            "+ CASE WHEN opening_harvest_population_reversal_event_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="ck_batch_carrier_assignments_exactly_one_opener",
        ),
        CheckConstraint(
            "(released_effective_time IS NULL) = "
            "(released_by_transplant_event_id IS NULL AND released_by_batch_derivation_event_id IS NULL "
            "AND released_by_seedling_disposition_event_id IS NULL "
            "AND released_by_production_disposition_event_id IS NULL "
            "AND released_by_harvest_population_event_id IS NULL)",
            name="ck_batch_carrier_assignments_release_fields_together",
        ),
        CheckConstraint(
            "(CASE WHEN released_by_transplant_event_id IS NOT NULL THEN 1 ELSE 0 END "
            "+ CASE WHEN released_by_batch_derivation_event_id IS NOT NULL THEN 1 ELSE 0 END "
            "+ CASE WHEN released_by_seedling_disposition_event_id IS NOT NULL THEN 1 ELSE 0 END "
            "+ CASE WHEN released_by_production_disposition_event_id IS NOT NULL THEN 1 ELSE 0 END "
            "+ CASE WHEN released_by_harvest_population_event_id IS NOT NULL THEN 1 ELSE 0 END) <= 1",
            name="ck_batch_carrier_assignments_at_most_one_releaser",
        ),
        # HARVEST-OPS-001: mirrors ck_batch_carrier_assignments_only_
        # production_source_releasable exactly -- a Harvest-driven release
        # is only ever a Transplant-created destination BCA or one already
        # restored by a prior Production Disposition OR Harvest correction
        # (the same population lineage this and LEAFY-OPS-001 share).
        CheckConstraint(
            "released_by_harvest_population_event_id IS NULL "
            "OR opening_transplant_event_id IS NOT NULL "
            "OR opening_production_disposition_reversal_event_id IS NOT NULL "
            "OR opening_harvest_population_reversal_event_id IS NOT NULL",
            name="ck_batch_carrier_assignments_only_harvest_source_releasable",
        ),
        # LEAFY-OPS-001: a Production-Disposition-driven release is only ever
        # a Transplant-created destination BCA (the population lineage this
        # ticket owns) or one already restored by a prior Production
        # Disposition correction -- never a sowing-origin, batch-derivation,
        # or Seedling-side-restored assignment (different lineage/authority
        # entirely). Same-row shape proof only -- the origin-integrity
        # trigger proves the full cross-row lineage/root match.
        CheckConstraint(
            "released_by_production_disposition_event_id IS NULL "
            "OR opening_transplant_event_id IS NOT NULL "
            "OR opening_production_disposition_reversal_event_id IS NOT NULL "
            "OR opening_harvest_population_reversal_event_id IS NOT NULL",
            name="ck_batch_carrier_assignments_only_production_source_releasable",
        ),
        # SEEDLING-DISPOSITION-LIFECYCLE-001: a Disposition-driven release is
        # only ever the current active assignment in a SeedlingEntry's
        # restoration lineage -- always sowing-origin, transplant-restored,
        # or itself Disposition-restored, never an ordinary Transplant
        # destination or Batch Derivation output (neither is ever
        # SeedlingEntry-anchored).
        CheckConstraint(
            "released_by_seedling_disposition_event_id IS NULL "
            "OR opening_sowing_event_id IS NOT NULL "
            "OR opening_transplant_reversal_event_id IS NOT NULL "
            "OR opening_seedling_disposition_reversal_event_id IS NOT NULL",
            name="ck_batch_carrier_assignments_only_seedling_source_releasable",
        ),
        # TRANSPLANT-CORRECTION-001 section 14 widens the old
        # "sowing-origin-only" rule: a reversal-restored source assignment is
        # an equally releasable biological source lifecycle. Which
        # TransplantEvent *kind* may actually perform the release (RECORD/
        # REPLACEMENT exhaustion vs. REVERSAL closing the destination it
        # opened) is a cross-table fact the closure trigger enforces -- this
        # CHECK only proves the opener SHAPE is one of the two eligible ones.
        CheckConstraint(
            "released_by_transplant_event_id IS NULL "
            "OR opening_sowing_event_id IS NOT NULL "
            "OR opening_transplant_reversal_event_id IS NOT NULL "
            "OR opening_transplant_event_id IS NOT NULL "
            "OR opening_seedling_disposition_reversal_event_id IS NOT NULL",
            name="ck_batch_carrier_assignments_only_sowing_origin_releasable",
        ),
        # TRANSPLANT-CORRECTION-001 section 12: restoration lineage is
        # exactly co-present with the reversal opener, never a self-loop.
        CheckConstraint(
            "(restored_from_batch_carrier_assignment_id IS NOT NULL) = "
            "(opening_transplant_reversal_event_id IS NOT NULL "
            "OR opening_seedling_disposition_reversal_event_id IS NOT NULL "
            "OR opening_production_disposition_reversal_event_id IS NOT NULL "
            "OR opening_harvest_population_reversal_event_id IS NOT NULL)",
            name="ck_batch_carrier_assignments_restoration_opener_match",
        ),
        CheckConstraint(
            "restored_from_batch_carrier_assignment_id IS NULL OR restored_from_batch_carrier_assignment_id <> id",
            name="ck_batch_carrier_assignments_restoration_not_self",
        ),
        Index(
            "ux_batch_carrier_assignments_active_carrier",
            "tenant_id",
            "carrier_id",
            unique=True,
            postgresql_where=text("released_effective_time IS NULL"),
        ),
        # SEEDLING-DISPOSITION-LIFECYCLE-001 section 5: one REDUCTION may
        # release at most one assignment, ever -- DB-level, unreachable via
        # direct SQL.
        Index(
            "ux_batch_carrier_assignments_released_by_disposition_once",
            "released_by_seedling_disposition_event_id",
            unique=True,
            postgresql_where=text("released_by_seedling_disposition_event_id IS NOT NULL"),
        ),
        # section 7: one REVERSAL may open at most one restored assignment.
        Index(
            "ux_batch_carrier_assignments_opened_by_disposition_once",
            "opening_seedling_disposition_reversal_event_id",
            unique=True,
            postgresql_where=text("opening_seedling_disposition_reversal_event_id IS NOT NULL"),
        ),
        # LEAFY-OPS-001: same two DB-level backstops, mirrored for the new
        # Production Disposition typed pair.
        Index(
            "ux_batch_carrier_assignments_released_by_prod_disposition_once",
            "released_by_production_disposition_event_id",
            unique=True,
            postgresql_where=text("released_by_production_disposition_event_id IS NOT NULL"),
        ),
        Index(
            "ux_batch_carrier_assignments_opened_by_prod_disposition_once",
            "opening_production_disposition_reversal_event_id",
            unique=True,
            postgresql_where=text("opening_production_disposition_reversal_event_id IS NOT NULL"),
        ),
        # HARVEST-OPS-001: same two DB-level backstops, mirrored for the new
        # Harvest typed pair.
        Index(
            "ux_batch_carrier_assignments_released_by_harvest_pop_once",
            "released_by_harvest_population_event_id",
            unique=True,
            postgresql_where=text("released_by_harvest_population_event_id IS NOT NULL"),
        ),
        Index(
            "ux_batch_carrier_assignments_opened_by_harvest_pop_once",
            "opening_harvest_population_reversal_event_id",
            unique=True,
            postgresql_where=text("opening_harvest_population_reversal_event_id IS NOT NULL"),
        ),
        UniqueConstraint(
            "tenant_id", "farm_id", "id", name="uq_batch_carrier_assignments_tenant_farm_id"
        ),
        # TRANSPLANT-CORRECTION-001: target for the new restoration-lineage
        # composite FK below (mirrors uq_transplant_events_tenant_farm_batch_id).
        UniqueConstraint(
            "tenant_id", "farm_id", "batch_id", "id", name="uq_batch_carrier_assignments_tenant_farm_batch_id"
        ),
        # SEEDLING-DISPOSITION-LIFECYCLE-001: target for Carrier's own
        # latest-assignment pointer FK -- proves "same Carrier" structurally
        # rather than via a trigger.
        UniqueConstraint(
            "tenant_id", "farm_id", "id", "carrier_id",
            name="uq_batch_carrier_assignments_tenant_farm_id_carrier",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_batch_carrier_assignments_tenant_farm_batch",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "carrier_id"],
            ["carriers.tenant_id", "carriers.farm_id", "carriers.id"],
            name="fk_batch_carrier_assignments_tenant_farm_carrier",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id", "batch_stage_run_id"],
            [
                "batch_stage_runs.tenant_id",
                "batch_stage_runs.farm_id",
                "batch_stage_runs.batch_id",
                "batch_stage_runs.id",
            ],
            name="fk_batch_carrier_assignments_stage_run",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "opening_sowing_event_id"],
            ["sowing_events.tenant_id", "sowing_events.farm_id", "sowing_events.id"],
            name="fk_batch_carrier_assignments_opening_event",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id", "opening_transplant_event_id"],
            [
                "transplant_events.tenant_id",
                "transplant_events.farm_id",
                "transplant_events.batch_id",
                "transplant_events.id",
            ],
            name="fk_batch_carrier_assignments_opening_transplant_event",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id", "released_by_transplant_event_id"],
            [
                "transplant_events.tenant_id",
                "transplant_events.farm_id",
                "transplant_events.batch_id",
                "transplant_events.id",
            ],
            name="fk_batch_carrier_assignments_released_by_transplant_event",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id", "opening_transplant_reversal_event_id"],
            [
                "transplant_events.tenant_id",
                "transplant_events.farm_id",
                "transplant_events.batch_id",
                "transplant_events.id",
            ],
            name="fk_batch_carrier_assignments_opening_reversal_event",
        ),
        # TRANSPLANT-CORRECTION-001 section 12/E: structurally proves
        # tenant/farm/batch equality between a restored assignment and its
        # immediate predecessor -- same-Carrier and released-by-target-X
        # linkage are cross-row facts a composite FK cannot express, and are
        # instead proven by the origin-integrity trigger.
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id", "restored_from_batch_carrier_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id",
                "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.batch_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_batch_carrier_assignments_restored_from",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "opening_batch_derivation_event_id"],
            [
                "batch_derivation_events.tenant_id",
                "batch_derivation_events.farm_id",
                "batch_derivation_events.id",
            ],
            name="fk_batch_carrier_assignments_opening_derivation_event",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "released_by_batch_derivation_event_id"],
            [
                "batch_derivation_events.tenant_id",
                "batch_derivation_events.farm_id",
                "batch_derivation_events.id",
            ],
            name="fk_batch_carrier_assignments_released_by_derivation_event",
        ),
        # SEEDLING-DISPOSITION-LIFECYCLE-001: `SeedlingDispositionEvent` has
        # no `batch_id` column (only its owning `SeedlingDispositionCommand`
        # does), so these two FKs use the 2-column tenant/farm form -- same
        # batch/lineage/Carrier equality is proven by the closure and
        # origin-integrity triggers instead, exactly as same-Carrier already
        # is for the Transplant-reversal opener.
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "released_by_seedling_disposition_event_id"],
            [
                "seedling_disposition_events.tenant_id",
                "seedling_disposition_events.farm_id",
                "seedling_disposition_events.id",
            ],
            name="fk_batch_carrier_assignments_released_by_disposition_event",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "opening_seedling_disposition_reversal_event_id"],
            [
                "seedling_disposition_events.tenant_id",
                "seedling_disposition_events.farm_id",
                "seedling_disposition_events.id",
            ],
            name="fk_batch_carrier_assignments_opening_disposition_reversal_event",
        ),
        # LEAFY-OPS-001: same 2-column tenant/farm form as the Seedling
        # Disposition FKs above (ProductionDispositionEvent has no batch_id
        # column of its own either) -- same-batch/lineage equality is
        # proven by the closure and origin-integrity triggers instead.
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "released_by_production_disposition_event_id"],
            [
                "production_disposition_events.tenant_id",
                "production_disposition_events.farm_id",
                "production_disposition_events.id",
            ],
            name="fk_batch_carrier_assignments_released_by_prod_disposition_event",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "opening_production_disposition_reversal_event_id"],
            [
                "production_disposition_events.tenant_id",
                "production_disposition_events.farm_id",
                "production_disposition_events.id",
            ],
            name="fk_batch_carrier_assignments_opening_prod_disp_reversal_event",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "population_root_batch_carrier_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id",
                "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_batch_carrier_assignments_population_root",
        ),
        # HARVEST-OPS-001: same 2-column tenant/farm form as the Production
        # Disposition FKs above (HarvestPopulationEvent has no batch_id
        # column of its own either) -- same-batch/lineage equality is
        # proven by the closure and origin-integrity triggers instead.
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "released_by_harvest_population_event_id"],
            [
                "harvest_population_events.tenant_id",
                "harvest_population_events.farm_id",
                "harvest_population_events.id",
            ],
            name="fk_batch_carrier_assignments_released_by_harvest_pop_event",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "opening_harvest_population_reversal_event_id"],
            [
                "harvest_population_events.tenant_id",
                "harvest_population_events.farm_id",
                "harvest_population_events.id",
            ],
            name="fk_batch_carrier_assignments_opening_harvest_pop_reversal_event",
        ),
    )
