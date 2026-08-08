import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.common import TimestampMixin


class Location(TimestampMixin, Base):
    __tablename__ = "locations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    parent_location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("locations.id"), nullable=True
    )
    location_type_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("location_types.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    greenhouse_classification: Mapped[str | None] = mapped_column(String, nullable=True)
    occupiable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        CheckConstraint("status IN ('active', 'inactive')", name="ck_locations_status"),
        CheckConstraint(
            "greenhouse_classification IS NULL OR greenhouse_classification IN "
            "('nursery', 'leafy_greens', 'vines', 'mixed', 'other')",
            name="ck_locations_greenhouse_classification_allowed",
        ),
        # Whether classification is required/forbidden depends on the row's
        # location_type (greenhouse vs not) — a plain CHECK can't join to
        # location_types, so that half of the rule is enforced by a
        # PostgreSQL trigger (in the migration) plus schema/service checks.
        Index(
            "ux_locations_sibling_code_lower",
            "parent_location_id",
            func.lower(code),
            unique=True,
            postgresql_where=text("parent_location_id IS NOT NULL"),
        ),
        Index(
            "ux_locations_root_code_lower",
            "farm_id",
            func.lower(code),
            unique=True,
            postgresql_where=text("parent_location_id IS NULL"),
        ),
        # CMP-018-added: backs the composite foreign keys from
        # finished_goods_storage_movements.source_location_id/
        # destination_location_id, matching every other typed-source
        # composite FK convention in this codebase. Removed on clean
        # CMP-018 downgrade.
        UniqueConstraint("tenant_id", "farm_id", "id", name="uq_locations_tenant_farm_id"),
    )
