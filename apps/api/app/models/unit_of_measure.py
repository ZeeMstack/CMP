import uuid

from sqlalchemy import CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

QUANTITY_KINDS = ("mass", "volume", "count")
CONVERSION_FAMILIES = ("MASS", "VOLUME")


class UnitOfMeasure(Base):
    """STORE-INV-001B: global, system-seeded UOM catalog -- no tenant
    scoping, no tenant-specific extensions, no mutation API of any kind
    (mirrors `location_types`/`carrier_types`/`asset_types`). `code` is the
    canonical physical/count symbol as written (`kg`, `g`, `L`, `mL`) or an
    uppercase label (`EA`, `SEED`) -- never uppercase-normalized the way a
    tenant-entered business code elsewhere in this codebase is.

    `conversion_family` (nullable) is the sole gate for global
    convertibility -- deliberately NOT `quantity_kind`. `EA` and `SEED`
    both carry `quantity_kind = 'count'` but `conversion_family = NULL`,
    so they are structurally never globally convertible even though they
    share a kind (`docs/domain/STORE_INVENTORY_MODEL.md` §6)."""

    __tablename__ = "unit_of_measures"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    quantity_kind: Mapped[str] = mapped_column(String, nullable=False)
    conversion_family: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "quantity_kind IN ('mass', 'volume', 'count')", name="ck_unit_of_measures_quantity_kind_allowed"
        ),
        CheckConstraint(
            "conversion_family IS NULL OR conversion_family IN ('MASS', 'VOLUME')",
            name="ck_unit_of_measures_conversion_family_allowed",
        ),
    )
