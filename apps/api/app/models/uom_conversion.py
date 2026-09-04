import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class UomConversion(Base):
    """STORE-INV-001B: global, system-seeded, one-directional conversion
    factor between two `UnitOfMeasure`s sharing a non-NULL
    `conversion_family` -- the application computes the inverse where
    needed; the opposite direction is never a second stored row, and
    neither is a self-conversion row. No mutation API -- immutable system
    infrastructure, same as `UnitOfMeasure` itself. Cross-family rows
    (including any row where either side's `conversion_family` is NULL --
    e.g. `EA`/`SEED`) are rejected by a DB trigger, since a CHECK
    constraint cannot join to `unit_of_measures` to inspect the referenced
    rows (`docs/domain/STORE_INVENTORY_MODEL.md` §6). A second DB trigger
    (`enforce_uom_conversion_no_reverse_pair`) rejects inserting the
    reverse of an already-stored pair -- `UniqueConstraint(from_uom_id,
    to_uom_id)` alone only prevents an exact duplicate row, not the
    reverse direction, which a plain unique index cannot express."""

    __tablename__ = "uom_conversions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    from_uom_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("unit_of_measures.id"), nullable=False)
    to_uom_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("unit_of_measures.id"), nullable=False)
    multiply_factor: Mapped[float] = mapped_column(Numeric, nullable=False)

    __table_args__ = (
        CheckConstraint("multiply_factor > 0", name="ck_uom_conversions_factor_positive"),
        CheckConstraint("from_uom_id <> to_uom_id", name="ck_uom_conversions_no_self_conversion"),
        UniqueConstraint("from_uom_id", "to_uom_id", name="ux_uom_conversions_from_to"),
    )
