import uuid

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class CarrierType(Base):
    """Global, system-defined carrier types. No tenant scoping, no
    tenant-specific extensions — seeded once by migration (CMP-005 scope)."""

    __tablename__ = "carrier_types"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
