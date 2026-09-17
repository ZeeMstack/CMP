import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.common import TimestampMixin


class IrrigationCircuit(TimestampMixin, Base):
    """PILOT-WATER-001A: a controlled delivery path from a Reservoir toward
    crop delivery points -- water TOPOLOGY, never a Location and never a
    crop-specific table (CLAUDE.md rule 1: crop-agnostic). `system_type` is
    free-text farm-chosen description (e.g. "DWC circulation", "vines
    drip"), never a hardcoded crop/variety/greenhouse enum -- new
    irrigation approaches are configuration, not new code paths."""

    __tablename__ = "irrigation_circuits"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    system_type: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('active', 'inactive')", name="ck_irrigation_circuits_status"),
        Index("ux_irrigation_circuits_tenant_code_lower", "tenant_id", func.lower(code), unique=True),
        UniqueConstraint("tenant_id", "farm_id", "id", name="uq_irrigation_circuits_tenant_farm_id"),
    )
