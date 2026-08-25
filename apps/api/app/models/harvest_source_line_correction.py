import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class HarvestSourceLineCorrection(Base):
    """HARVEST-OPS-001: immutable, insert-only commercial/audit correction
    chain for one ORIGINAL `HarvestSourceLine` -- `harvest_source_line_id`
    always names that original line and never changes across a chain;
    `supersedes_correction_id` links each correction to whichever node
    (another correction, or NULL meaning the original line itself) it
    replaces, forming a strict linear chain structurally identical to
    `BatchCarrierAssignment.restored_from_batch_carrier_assignment_id`'s own
    restoration lineage -- the "current effective" node is always the one
    tip nothing else supersedes (see `harvest_service.py`'s resolver, which
    mirrors `resolve_lineage_tip_assignment_id` exactly). Every non-void
    node is a COMPLETE state snapshot (both `corrected_harvested_weight_kg`
    and `corrected_whole_unit_count` always populated, even when the
    operator changed only one) -- this is what makes each node
    independently readable without walking its own predecessor. A void
    node (`is_void`) carries NULL/NULL for both -- "currently nothing
    harvested from this line" -- and is not terminal: a later correction
    may supersede a void node exactly like any other (see
    `harvest_service.py`'s CASE 1/CASE 2 biological-correction algorithm).
    The original `HarvestSourceLine`/`HarvestedProduceLot` rows are never
    modified by any correction in this chain."""

    __tablename__ = "harvest_source_line_corrections"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    harvest_source_line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("harvest_source_lines.id"), nullable=False
    )
    supersedes_correction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("harvest_source_line_corrections.id"), nullable=True
    )
    is_void: Mapped[bool] = mapped_column(Boolean, nullable=False)
    corrected_harvested_weight_kg: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    corrected_whole_unit_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reason_code: Mapped[str] = mapped_column(String, nullable=False)
    note: Mapped[str] = mapped_column(String, nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "is_void = (corrected_harvested_weight_kg IS NULL AND corrected_whole_unit_count IS NULL)",
            name="ck_harvest_source_line_corrections_void_shape",
        ),
        # Same envelope as harvest_source_lines' own (CMP-013), applied only
        # on the non-void branch -- reproduced explicitly rather than
        # scoped-NUMERIC for the same "reject rather than silently round"
        # reason CMP-013's own CHECK already documents.
        CheckConstraint(
            "is_void OR (corrected_harvested_weight_kg > 0 "
            "AND corrected_harvested_weight_kg = trunc(corrected_harvested_weight_kg, 3) "
            "AND corrected_harvested_weight_kg < 100000000000)",
            name="ck_harvest_source_line_corrections_weight_envelope",
        ),
        CheckConstraint(
            "is_void OR corrected_whole_unit_count > 0",
            name="ck_harvest_source_line_corrections_count_positive",
        ),
        CheckConstraint(
            "supersedes_correction_id IS NULL OR supersedes_correction_id <> id",
            name="ck_harvest_source_line_corrections_not_self",
        ),
        CheckConstraint(
            "btrim(reason_code) <> '' AND btrim(note) <> ''",
            name="ck_harvest_source_line_corrections_reason_note_required",
        ),
        # Non-branching chain: at most one ROOT correction per original
        # line, at most one direct successor per correction -- together
        # these make the chain a strict linked list, and the second index
        # is simultaneously the optimistic-concurrency primitive (a
        # concurrent correction targeting the same predecessor loses the
        # unique-violation race, never silently retargets).
        Index(
            "ux_harvest_source_line_corrections_root_once",
            "harvest_source_line_id",
            unique=True,
            postgresql_where=text("supersedes_correction_id IS NULL"),
        ),
        Index(
            "ux_harvest_source_line_corrections_successor_once",
            "supersedes_correction_id",
            unique=True,
            postgresql_where=text("supersedes_correction_id IS NOT NULL"),
        ),
        UniqueConstraint(
            "tenant_id", "client_command_id",
            name="ux_harvest_source_line_corrections_tenant_client_command_id",
        ),
        UniqueConstraint(
            "tenant_id", "farm_id", "id", name="uq_harvest_source_line_corrections_tenant_farm_id"
        ),
    )
