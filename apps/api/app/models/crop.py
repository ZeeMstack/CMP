import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.common import TimestampMixin


class Crop(TimestampMixin, Base):
    __tablename__ = "crops"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    common_name: Mapped[str] = mapped_column(String, nullable=False)
    scientific_name: Mapped[str | None] = mapped_column(String, nullable=True)
    crop_category: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")

    __table_args__ = (
        CheckConstraint("status IN ('active', 'inactive')", name="ck_crops_status"),
        CheckConstraint(
            "crop_category IN ('leafy_green', 'vine', 'herb', 'other')", name="ck_crops_category_allowed"
        ),
        Index("ux_crops_tenant_code_lower", "tenant_id", func.lower(code), unique=True),
        UniqueConstraint("tenant_id", "id", name="uq_crops_tenant_id_id"),
    )
