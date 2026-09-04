import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

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
