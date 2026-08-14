import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.asset_position import AssetPosition
from app.models.asset_type import AssetType
from app.services import farm_service
from app.services.audit import append_audit_event
from app.services.errors import (
    AssetNotFoundError,
    AssetTypeNotFoundError,
    DuplicateAssetCodeError,
    DuplicatePositionCodeError,
    FarmNotFoundError,
    PositionsNotSupportedError,
)


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _require_active_farm(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> None:
    farm = farm_service.get_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    if farm.status != "active":
        raise FarmNotFoundError(str(farm_id))


def _get_asset_type_by_code(db: Session, code: str) -> AssetType:
    asset_type = db.execute(select(AssetType).where(AssetType.code == code)).scalar_one_or_none()
    if asset_type is None:
        raise AssetTypeNotFoundError(code)
    return asset_type


def _register_asset_core(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    asset_type_code: str,
    code: str,
    name: str,
    commissioned_date: date | None,
) -> Asset:
    """The validate+insert+flush core of `register_asset`, with no commit
    and no audit event -- reused by FARM-SETUP-001's orchestration service
    so a setup command that also registers assets (Germination Trolley,
    Seeding Machine) commits everything, locations and assets alike, in
    one transaction. Public `register_asset` below is an unchanged thin
    wrapper around this."""
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    asset_type = _get_asset_type_by_code(db, asset_type_code)

    asset = Asset(
        tenant_id=tenant_id,
        farm_id=farm_id,
        asset_type_id=asset_type.id,
        code=code,
        name=name,
        commissioned_date=commissioned_date,
    )
    db.add(asset)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateAssetCodeError(f"{tenant_id}:{code}") from exc
    return asset


def register_asset(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    asset_type_code: str,
    code: str,
    name: str,
    commissioned_date: date | None,
) -> Asset:
    asset = _register_asset_core(
        db,
        tenant_id=tenant_id,
        farm_id=farm_id,
        asset_type_code=asset_type_code,
        code=code,
        name=name,
        commissioned_date=commissioned_date,
    )

    append_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="asset.registered",
        entity_type="asset",
        entity_id=asset.id,
        event_data={"code": asset.code, "asset_type_code": asset_type_code},
    )
    db.commit()
    db.refresh(asset)
    return asset


def get_asset(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, asset_id: uuid.UUID) -> Asset:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    asset = db.execute(
        select(Asset).where(Asset.id == asset_id, Asset.tenant_id == tenant_id, Asset.farm_id == farm_id)
    ).scalar_one_or_none()
    if asset is None:
        raise AssetNotFoundError(str(asset_id))
    return asset


def list_assets(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, asset_type_code: str | None
) -> list[Asset]:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    query = select(Asset).where(Asset.tenant_id == tenant_id, Asset.farm_id == farm_id)
    if asset_type_code is not None:
        asset_type = _get_asset_type_by_code(db, asset_type_code)
        query = query.where(Asset.asset_type_id == asset_type.id)
    return list(db.execute(query.order_by(func.lower(Asset.code))).scalars())


def _generate_positions_core(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    asset_id: uuid.UUID,
    shelf_count: int,
    slots_per_shelf: int,
    shelf_prefix: str,
    slot_prefix: str,
    shelf_pad_width: int,
    slot_pad_width: int,
    shelf_capacity: int | None = None,
    slot_capacity: int | None = None,
) -> tuple[AssetType, list[AssetPosition]]:
    """The validate+insert+flush core of `generate_positions`, with no
    commit and no audit event -- see `_register_asset_core`'s docstring for
    why FARM-SETUP-001 needs this split. Returns the asset type alongside
    the created positions since the public wrapper's audit event needs
    `asset_type.code` too."""
    asset = get_asset(db, tenant_id=tenant_id, farm_id=farm_id, asset_id=asset_id)
    asset_type = db.get(AssetType, asset.asset_type_id)
    if asset_type is None or not asset_type.supports_positions:
        raise PositionsNotSupportedError(str(asset_id))

    shelf_codes = [f"{shelf_prefix}{str(n).zfill(shelf_pad_width)}" for n in range(1, shelf_count + 1)]
    existing = db.execute(
        select(AssetPosition.code).where(
            AssetPosition.asset_id == asset_id,
            AssetPosition.parent_position_id.is_(None),
            func.lower(AssetPosition.code).in_([c.lower() for c in shelf_codes]),
        )
    ).scalars().all()
    if existing:
        raise DuplicatePositionCodeError(f"{asset_id}:{','.join(existing)}")

    created: list[AssetPosition] = []
    for shelf_code in shelf_codes:
        shelf_id = uuid.uuid4()
        shelf = AssetPosition(
            id=shelf_id,
            asset_id=asset_id,
            parent_position_id=None,
            position_kind="shelf",
            code=shelf_code,
            name=f"Shelf {shelf_code}",
            capacity=shelf_capacity,
        )
        db.add(shelf)
        created.append(shelf)

        for slot_n in range(1, slots_per_shelf + 1):
            slot_code = f"{slot_prefix}{str(slot_n).zfill(slot_pad_width)}"
            slot = AssetPosition(
                asset_id=asset_id,
                parent_position_id=shelf_id,
                position_kind="slot",
                code=slot_code,
                name=f"Slot {slot_code}",
                capacity=slot_capacity,
            )
            db.add(slot)
            created.append(slot)

    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) not in ("ux_asset_positions_sibling_code_lower", "ux_asset_positions_root_code_lower"):
            raise
        raise DuplicatePositionCodeError(f"{asset_id}:{shelf_prefix}/{slot_prefix}") from exc
    return asset_type, created


def generate_positions(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    asset_id: uuid.UUID,
    shelf_count: int,
    slots_per_shelf: int,
    shelf_prefix: str,
    slot_prefix: str,
    shelf_pad_width: int,
    slot_pad_width: int,
    shelf_capacity: int | None = None,
    slot_capacity: int | None = None,
) -> list[AssetPosition]:
    asset_type, created = _generate_positions_core(
        db,
        tenant_id=tenant_id,
        farm_id=farm_id,
        asset_id=asset_id,
        shelf_count=shelf_count,
        slots_per_shelf=slots_per_shelf,
        shelf_prefix=shelf_prefix,
        slot_prefix=slot_prefix,
        shelf_pad_width=shelf_pad_width,
        slot_pad_width=slot_pad_width,
        shelf_capacity=shelf_capacity,
        slot_capacity=slot_capacity,
    )

    append_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="asset.positions_generated",
        entity_type="asset",
        entity_id=asset_id,
        event_data={
            "asset_id": str(asset_id),
            "asset_type_code": asset_type.code,
            "shelf_count": shelf_count,
            "slots_per_shelf": slots_per_shelf,
            "shelf_prefix": shelf_prefix,
            "slot_prefix": slot_prefix,
            "shelf_pad_width": shelf_pad_width,
            "slot_pad_width": slot_pad_width,
            "total_positions": len(created),
        },
    )
    db.commit()
    for position in created:
        db.refresh(position)
    return created


def get_positions_tree(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, asset_id: uuid.UUID
) -> list[AssetPosition]:
    get_asset(db, tenant_id=tenant_id, farm_id=farm_id, asset_id=asset_id)
    return list(
        db.execute(
            select(AssetPosition)
            .where(AssetPosition.asset_id == asset_id)
            .order_by(func.lower(AssetPosition.code))
        ).scalars()
    )
