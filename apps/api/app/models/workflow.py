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


class Workflow(TimestampMixin, Base):
    __tablename__ = "workflows"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    crop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crops.id"), nullable=False)
    variety_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("varieties.id"), nullable=True)
    production_system_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("production_systems.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")

    __table_args__ = (
        CheckConstraint("status IN ('active', 'inactive')", name="ck_workflows_status"),
        Index("ux_workflows_tenant_code_lower", "tenant_id", func.lower(code), unique=True),
        UniqueConstraint("tenant_id", "id", name="uq_workflows_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "crop_id"],
            ["crops.tenant_id", "crops.id"],
            name="fk_workflows_tenant_crop",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "production_system_id"],
            ["production_systems.tenant_id", "production_systems.id"],
            name="fk_workflows_tenant_production_system",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "crop_id", "variety_id"],
            ["varieties.tenant_id", "varieties.crop_id", "varieties.id"],
            name="fk_workflows_tenant_crop_variety",
        ),
    )
