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


class Variety(TimestampMixin, Base):
    __tablename__ = "varieties"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    crop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crops.id"), nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    supplier_reference: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")

    __table_args__ = (
        CheckConstraint("status IN ('active', 'inactive')", name="ck_varieties_status"),
        Index("ux_varieties_crop_code_lower", "crop_id", func.lower(code), unique=True),
        UniqueConstraint("tenant_id", "crop_id", "id", name="uq_varieties_tenant_crop_id"),
        ForeignKeyConstraint(
            ["tenant_id", "crop_id"],
            ["crops.tenant_id", "crops.id"],
            name="fk_varieties_tenant_crop",
        ),
    )
