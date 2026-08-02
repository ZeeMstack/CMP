import uuid

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class LocationType(Base):
    """Global, system-defined location types. No tenant scoping, no
    tenant-specific extensions — seeded once by migration (CMP-004 scope)."""

    __tablename__ = "location_types"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    default_occupiable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
