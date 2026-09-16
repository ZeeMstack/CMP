import uuid

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.common import TimestampMixin


class GrowingProtocol(TimestampMixin, Base):
    """PILOT-AGRO-001: the identity of one agronomic program (e.g. "Iceberg
    Lettuce -- DWC -- Summer Standard"), scoped by the existing Crop/
    Variety/ProductionSystem catalogs -- never a new crop catalog of its
    own. Mirrors `Workflow`'s own identity shape (crop/variety/production-
    system applicability, immutable human-readable `code`) deliberately:
    a Growing Protocol is a parallel, independently-versioned concern from
    a Workflow (what SHOULD agronomically happen vs. the actual stage
    machine a Batch runs through) that happens to share the same
    applicability dimensions. All agronomic CONTENT lives on
    `GrowingProtocolVersion`; this row is only the versioned identity plus
    applicability."""

    __tablename__ = "growing_protocols"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    crop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crops.id"), nullable=False)
    variety_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("varieties.id"), nullable=True)
    production_system_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("production_systems.id"), nullable=True
    )
    season_context: Mapped[str | None] = mapped_column(String, nullable=True)
    code: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)

    __table_args__ = (
        CheckConstraint("status IN ('active', 'inactive')", name="ck_growing_protocols_status"),
        Index("ux_growing_protocols_tenant_code_lower", "tenant_id", func.lower(code), unique=True),
        UniqueConstraint("tenant_id", "id", name="uq_growing_protocols_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "crop_id"], ["crops.tenant_id", "crops.id"], name="fk_growing_protocols_tenant_crop"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "crop_id", "variety_id"],
            ["varieties.tenant_id", "varieties.crop_id", "varieties.id"],
            name="fk_growing_protocols_tenant_crop_variety",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "production_system_id"],
            ["production_systems.tenant_id", "production_systems.id"],
            name="fk_growing_protocols_tenant_production_system",
        ),
    )
