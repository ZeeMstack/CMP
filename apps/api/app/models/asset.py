import uuid
from datetime import date

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.common import TimestampMixin

ASSET_STATUSES = ("active", "inactive", "damaged", "retired")
# PILOT-ASSET-001 PART 11: a small, non-scoring instance-level
# classification -- does NOT change automatically, never touched by
# Equipment Readiness/Incident commands themselves. Informs Today-on-the-
# Farm ordering and Incident severity presentation only.
ASSET_CRITICALITIES = ("normal", "important", "critical")


class Asset(TimestampMixin, Base):
    __tablename__ = "assets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    asset_type_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("asset_types.id"), nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    commissioned_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    retired_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    criticality: Mapped[str] = mapped_column(String, nullable=False, default="normal")

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'inactive', 'damaged', 'retired')", name="ck_assets_status"
        ),
        CheckConstraint(
            "status <> 'retired' OR retired_date IS NOT NULL",
            name="ck_assets_retired_requires_retired_date",
        ),
        CheckConstraint(
            "criticality IN ('normal', 'important', 'critical')", name="ck_assets_criticality"
        ),
        Index("ux_assets_tenant_code_lower", "tenant_id", func.lower(code), unique=True),
    )
