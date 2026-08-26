import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class PackSpecificationVersion(Base):
    """POSTHARVEST-OPS-001B: the versioned, immutable-once-created exact
    commercial packing standard for one `PackSpecification`. Lifecycle
    (`draft -> active -> retired`), the per-command idempotency column
    shape (`client_command_id`/`activation_*`/`retirement_*`), and the
    partial-unique "at most one ACTIVE version" index all mirror
    `GradeDefinitionVersion` exactly -- see that model's own docstring for
    the full rationale, which applies here unchanged.

    Two relationships this table alone cannot fully validate at the
    declarative level are enforced by
    `pack_specification_versions_enforce_insert_integrity` (a narrow
    BEFORE INSERT trigger, since a same-row CHECK/plain FK cannot express
    a cross-table STATUS or a two-hop crop/variety comparison):
    `packaging_unit_id` must reference a currently-ACTIVE `PackagingUnit`
    (tenant match is a real composite FK; ACTIVE-ness is not, since
    status is mutable), and, when populated, `grade_definition_version_id`
    must reference a non-DRAFT `GradeDefinitionVersion` whose own
    `GradeDefinition.crop_id`/`variety_id` are compatible with this
    version's own parent `PackSpecification.crop_id`/`variety_id`. Neither
    a later PackagingUnit retirement nor a later GradeDefinitionVersion
    retirement ever mutates an already-created row here -- the trigger
    fires once, at INSERT, never again."""

    __tablename__ = "pack_specification_versions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    pack_specification_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pack_specifications.id"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft")
    grade_definition_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("grade_definition_versions.id"), nullable=True
    )
    packaging_unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("packaging_units.id"), nullable=False)
    nominal_net_weight_kg: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    whole_units_per_pack: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    spec_notes: Mapped[str | None] = mapped_column(String, nullable=True)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    activation_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    activation_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)
    retirement_client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    retirement_request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'active', 'retired')", name="ck_pack_specification_versions_status"
        ),
        CheckConstraint("version_number > 0", name="ck_pack_specification_versions_number_positive"),
        CheckConstraint(
            "(status = 'draft' AND effective_from IS NULL AND effective_until IS NULL "
            " AND activation_client_command_id IS NULL AND activation_request_fingerprint IS NULL "
            " AND retirement_client_command_id IS NULL AND retirement_request_fingerprint IS NULL) "
            "OR (status = 'active' AND effective_from IS NOT NULL AND effective_until IS NULL "
            " AND activation_client_command_id IS NOT NULL AND activation_request_fingerprint IS NOT NULL "
            " AND retirement_client_command_id IS NULL AND retirement_request_fingerprint IS NULL) "
            "OR (status = 'retired' AND effective_from IS NOT NULL AND effective_until IS NOT NULL "
            " AND activation_client_command_id IS NOT NULL AND activation_request_fingerprint IS NOT NULL)",
            name="ck_pack_specification_versions_status_shape",
        ),
        CheckConstraint(
            "effective_until IS NULL OR effective_until >= effective_from",
            name="ck_pack_specification_versions_effective_order",
        ),
        # Frozen pack-measure rule: at least one of the two commercial
        # measures must be present (both may be), NULL (never zero) when
        # not applicable, and each strictly positive when present. The
        # weight envelope reproduces the same unscoped-NUMERIC + explicit
        # CHECK idiom CMP-013's own harvested_weight_kg established, for
        # the identical "reject rather than silently round" reason.
        CheckConstraint(
            "nominal_net_weight_kg IS NOT NULL OR whole_units_per_pack IS NOT NULL",
            name="ck_pack_specification_versions_measure_present",
        ),
        CheckConstraint(
            "nominal_net_weight_kg IS NULL OR (nominal_net_weight_kg > 0 "
            "AND nominal_net_weight_kg = trunc(nominal_net_weight_kg, 3) "
            "AND nominal_net_weight_kg < 100000000000)",
            name="ck_pack_specification_versions_weight_envelope",
        ),
        CheckConstraint(
            "whole_units_per_pack IS NULL OR whole_units_per_pack > 0",
            name="ck_pack_specification_versions_units_positive",
        ),
        UniqueConstraint(
            "pack_specification_id", "version_number", name="uq_pack_specification_versions_spec_number"
        ),
        UniqueConstraint("tenant_id", "id", name="uq_pack_specification_versions_tenant_id"),
        UniqueConstraint(
            "tenant_id", "pack_specification_id", "id", name="uq_pack_specification_versions_tenant_spec_id"
        ),
        # DB-level "at most one ACTIVE version per PackSpecification".
        Index(
            "ux_pack_specification_versions_active_once", "pack_specification_id", unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index(
            "ux_pack_specification_versions_tenant_client_command_id", "tenant_id", "client_command_id",
            unique=True,
        ),
        Index(
            "ux_pack_specification_versions_tenant_activation_command", "tenant_id",
            "activation_client_command_id", unique=True,
            postgresql_where=text("activation_client_command_id IS NOT NULL"),
        ),
        Index(
            "ux_pack_specification_versions_tenant_retirement_command", "tenant_id",
            "retirement_client_command_id", unique=True,
            postgresql_where=text("retirement_client_command_id IS NOT NULL"),
        ),
        ForeignKeyConstraint(
            ["tenant_id", "pack_specification_id"],
            ["pack_specifications.tenant_id", "pack_specifications.id"],
            name="fk_pack_specification_versions_tenant_spec",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "packaging_unit_id"],
            ["packaging_units.tenant_id", "packaging_units.id"],
            name="fk_pack_specification_versions_tenant_unit",
        ),
        # MATCH SIMPLE: only evaluated when grade_definition_version_id IS
        # NOT NULL -- the optional grade reference is null-safe.
        ForeignKeyConstraint(
            ["tenant_id", "grade_definition_version_id"],
            ["grade_definition_versions.tenant_id", "grade_definition_versions.id"],
            name="fk_pack_specification_versions_tenant_grade_version",
        ),
    )
