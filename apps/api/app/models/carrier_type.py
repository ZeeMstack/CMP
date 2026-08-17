import uuid

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class CarrierType(Base):
    """Global, system-defined carrier types. No tenant scoping, no
    tenant-specific extensions — seeded once by migration (CMP-005 scope).

    CARRIER-CONFIG-001: `requires_specification`/`biological_position_label`
    are platform metadata about the TYPE (a role), never a physical fact
    about any one design — those live on the tenant-configurable
    `CarrierSpecification` a Carrier of this type may reference. A CarrierType
    with `requires_specification=False` (every carrier type that predates
    this ticket) is never forced to gain one; `biological_position_label` is
    purely a display hint (e.g. "Cells" for seed_tray, "Holes" for a
    Cultivation Plate) — no arithmetic ever reads it, only UI copy."""

    __tablename__ = "carrier_types"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    requires_specification: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    biological_position_label: Mapped[str | None] = mapped_column(String, nullable=True)
