import uuid

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AssetType(Base):
    """Global, system-defined asset types. No tenant scoping, no
    tenant-specific extensions — seeded once by migration (CMP-005 scope)."""

    __tablename__ = "asset_types"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    supports_positions: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # PILOT-ASSET-001: platform metadata (like `supports_positions`) --
    # whether the Equipment Readiness lifecycle applies to Assets of this
    # type at all, and whether their post-use path goes through
    # AWAITING_CLEANING. See docs/domain/EQUIPMENT_READINESS_MODEL.md.
    readiness_tracked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requires_cleaning: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
