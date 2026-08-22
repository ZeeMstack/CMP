import uuid
from datetime import date

from sqlalchemy import CheckConstraint, Date, ForeignKey, ForeignKeyConstraint, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.common import TimestampMixin

CARRIER_STATUSES = ("active", "inactive", "damaged", "retired")


class Carrier(TimestampMixin, Base):
    __tablename__ = "carriers"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    carrier_type_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("carrier_types.id"), nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    issued_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    retired_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # CARRIER-CONFIG-001: nullable -- legacy Carriers (and any Carrier of a
    # CarrierType that doesn't require one) never get a fabricated
    # specification. Tenant-safe via the composite FK below, not a bare
    # single-column FK (CLAUDE.md rule 2: tenant isolation is never a
    # frontend-only concern) -- mirrors `Variety.crop_id -> Crop`'s own
    # established composite-FK precedent exactly.
    specification_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("carrier_specifications.id"), nullable=True
    )
    # SEEDLING-DISPOSITION-LIFECYCLE-001: authoritative, forward-only pointer
    # to the most recently CREATED `BatchCarrierAssignment` for this physical
    # Carrier -- maintained exclusively by `maintain_carrier_latest_
    # assignment_pointer` (AFTER INSERT on batch_carrier_assignments).
    # Release never changes it; only a NEW assignment's creation does. This
    # is derived infrastructure (never operator-editable) proving whether a
    # released assignment is still this Carrier's latest-ever physical use --
    # the one question `assigned_effective_time`/`recorded_at`/restoration
    # lineage alone cannot answer (see docs/domain/ASSET_CARRIER_MODEL.md).
    latest_batch_carrier_assignment_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'inactive', 'damaged', 'retired')", name="ck_carriers_status"
        ),
        CheckConstraint(
            "status <> 'retired' OR retired_date IS NOT NULL",
            name="ck_carriers_retired_requires_retired_date",
        ),
        Index("ux_carriers_tenant_code_lower", "tenant_id", func.lower(code), unique=True),
        ForeignKeyConstraint(
            ["tenant_id", "specification_id"],
            ["carrier_specifications.tenant_id", "carrier_specifications.id"],
            name="fk_carriers_tenant_specification",
        ),
        # SEEDLING-DISPOSITION-LIFECYCLE-001: structurally proves the pointer
        # (when non-null) references an assignment for THIS SAME Carrier (and
        # tenant/farm) -- a declarative FK, not a trigger, since
        # `batch_carrier_assignments` gains a matching
        # (tenant_id, farm_id, id, carrier_id) unique constraint for exactly
        # this purpose.
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "latest_batch_carrier_assignment_id", "id"],
            [
                "batch_carrier_assignments.tenant_id",
                "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
                "batch_carrier_assignments.carrier_id",
            ],
            name="fk_carriers_latest_assignment",
        ),
    )
