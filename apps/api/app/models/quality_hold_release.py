import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class QualityHoldRelease(Base):
    """Immutable, insert-only decision removing a quality hold. A separate
    record rather than a mutation of the hold — open/released state is
    derived from whether one of these rows exists for a given hold
    (CMP-010)."""

    __tablename__ = "quality_hold_releases"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    quality_hold_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("quality_holds.id"), nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crop_batches.id"), nullable=False)
    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    release_reason: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        Index(
            "ux_quality_hold_releases_tenant_client_command_id",
            "tenant_id",
            "client_command_id",
            unique=True,
        ),
        Index("ux_quality_hold_releases_hold", "tenant_id", "quality_hold_id", unique=True),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id", "quality_hold_id"],
            [
                "quality_holds.tenant_id",
                "quality_holds.farm_id",
                "quality_holds.batch_id",
                "quality_holds.id",
            ],
            name="fk_quality_hold_releases_hold",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_quality_hold_releases_tenant_farm_batch",
        ),
    )
