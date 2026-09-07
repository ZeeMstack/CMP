import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.uom_conversion import UomConversion
from app.models.unit_of_measure import UnitOfMeasure
from app.services.errors import UnitOfMeasureNotFoundError


def list_uoms(db: Session) -> list[UnitOfMeasure]:
    """STORE-INV-001B: global, system-seeded, read-only catalog -- no
    tenant scoping, no create/update/delete."""
    return list(db.execute(select(UnitOfMeasure).order_by(UnitOfMeasure.code)).scalars())


def get_uom(db: Session, *, uom_id: uuid.UUID) -> UnitOfMeasure:
    uom = db.execute(select(UnitOfMeasure).where(UnitOfMeasure.id == uom_id)).scalar_one_or_none()
    if uom is None:
        raise UnitOfMeasureNotFoundError(str(uom_id))
    return uom


def resolve_conversion_factor(
    db: Session, *, from_uom_id: uuid.UUID, to_uom_id: uuid.UUID
) -> Decimal | None:
    """STORE-INV-002A.1: `entered_quantity * factor = base_quantity`.
    Same unit -> factor 1. A stored `(from, to)` row -> that row's own
    factor. Only the reverse direction stored -> the application computes
    the inverse (`docs/domain/STORE_INVENTORY_MODEL.md` §6 -- the inverse is
    never a second stored row). No matching pair at all (including any
    `conversion_family`-incompatible pair, e.g. `EA`<->`SEED`) -> `None`,
    never guessed."""
    if from_uom_id == to_uom_id:
        return Decimal("1")
    direct = db.execute(
        select(UomConversion.multiply_factor).where(
            UomConversion.from_uom_id == from_uom_id, UomConversion.to_uom_id == to_uom_id
        )
    ).scalar_one_or_none()
    if direct is not None:
        return Decimal(direct)
    reverse = db.execute(
        select(UomConversion.multiply_factor).where(
            UomConversion.from_uom_id == to_uom_id, UomConversion.to_uom_id == from_uom_id
        )
    ).scalar_one_or_none()
    if reverse is not None:
        return Decimal("1") / Decimal(reverse)
    return None
