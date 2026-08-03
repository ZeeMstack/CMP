import uuid
from datetime import date

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, String, func
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

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'inactive', 'damaged', 'retired')", name="ck_carriers_status"
        ),
        CheckConstraint(
            "status <> 'retired' OR retired_date IS NOT NULL",
            name="ck_carriers_retired_requires_retired_date",
        ),
        Index("ux_carriers_tenant_code_lower", "tenant_id", func.lower(code), unique=True),
    )
