import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.production_system import ProductionSystem
from app.services.audit import append_audit_event
from app.services.errors import DuplicateProductionSystemCodeError, ProductionSystemNotFoundError


def register_production_system(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    code: str,
    name: str,
    description: str | None,
) -> ProductionSystem:
    production_system = ProductionSystem(
        tenant_id=tenant_id,
        code=code,
        name=name,
        description=description,
    )
    db.add(production_system)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateProductionSystemCodeError(f"{tenant_id}:{code}") from exc

    append_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="production_system.registered",
        entity_type="production_system",
        entity_id=production_system.id,
        event_data={"code": production_system.code, "name": production_system.name},
    )
    db.commit()
    db.refresh(production_system)
    return production_system


def get_production_system(
    db: Session, *, tenant_id: uuid.UUID, production_system_id: uuid.UUID
) -> ProductionSystem:
    production_system = db.execute(
        select(ProductionSystem).where(
            ProductionSystem.id == production_system_id, ProductionSystem.tenant_id == tenant_id
        )
    ).scalar_one_or_none()
    if production_system is None:
        raise ProductionSystemNotFoundError(str(production_system_id))
    return production_system


def list_production_systems(db: Session, *, tenant_id: uuid.UUID) -> list[ProductionSystem]:
    return list(
        db.execute(
            select(ProductionSystem).where(ProductionSystem.tenant_id == tenant_id).order_by(ProductionSystem.code)
        ).scalars()
    )
